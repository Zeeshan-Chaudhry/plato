"""
Flask web application for Course Outline to iCalendar Converter.

This is the main web interface for the application. It provides:
- PDF upload functionality
- Data review and editing interface
- Section selection
- Assessment review
- Manual mode for manual data entry
- Calendar file download
"""

import os
import json
import hashlib
import uuid
from pathlib import Path
from datetime import date, datetime, time
from typing import Optional, Dict, Any
from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash, jsonify
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge

# Load environment variables from .env file (for local development)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv not installed, assume environment variables are set by hosting platform
    pass

from .models import (
    ExtractedCourseData, UserSelections, CourseTerm, SectionOption, AssessmentTask,
    serialize_date, serialize_datetime, serialize_time,
    deserialize_date, deserialize_datetime, deserialize_time
)
from .cache import get_cache_manager, compute_pdf_hash
from .pdf_extractor import PDFExtractor
from .rule_resolver import RuleResolver
from .study_plan import StudyPlanGenerator
from .icalendar_gen import ICalendarGenerator
from .user_tier import tier_manager
from .openai_extractor import OpenAIExtractor

# Initialize Flask app
# Set template and static folders to be in project root
app = Flask(__name__, 
            template_folder='../templates',
            static_folder='../static')
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

# Configuration
UPLOAD_FOLDER = Path('uploads')
UPLOAD_FOLDER.mkdir(exist_ok=True)
ALLOWED_EXTENSIONS = {'pdf'}
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16MB

app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# Custom Jinja2 filter for 12-hour time format
@app.template_filter('time_12h')
def time_12h_filter(time_obj):
    """Convert time object to 12-hour format with AM/PM."""
    if not time_obj:
        return 'N/A'
    if isinstance(time_obj, time):
        hour = time_obj.hour
        minute = time_obj.minute
        ampm = 'AM' if hour < 12 else 'PM'
        display_hour = hour % 12
        if display_hour == 0:
            display_hour = 12
        return f"{display_hour}:{minute:02d} {ampm}"
    elif isinstance(time_obj, datetime):
        hour = time_obj.hour
        minute = time_obj.minute
        ampm = 'AM' if hour < 12 else 'PM'
        display_hour = hour % 12
        if display_hour == 0:
            display_hour = 12
        return f"{display_hour}:{minute:02d} {ampm}"
    return str(time_obj)

# Initialize cache manager (auto-selects SQLite or Supabase)
cache_manager = get_cache_manager()


def allowed_file(filename: str) -> bool:
    """Check if file extension is allowed.
    
    Args:
        filename: Name of the uploaded file
        
    Returns:
        True if file extension is allowed, False otherwise
    """
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def serialize_section(section: Optional[SectionOption]) -> Optional[Dict[str, Any]]:
    """Serialize SectionOption to dict.
    
    Args:
        section: SectionOption object to serialize, or None
        
    Returns:
        Dictionary representation of section, or None
    """
    if section is None:
        return None
    return {
        "section_type": section.section_type,
        "section_id": section.section_id,
        "days_of_week": section.days_of_week,
        "start_time": serialize_time(section.start_time),
        "end_time": serialize_time(section.end_time),
        "location": section.location
    }


def serialize_extracted_data(data: ExtractedCourseData) -> Dict[str, Any]:
    """Serialize ExtractedCourseData to JSON-serializable dict.
    
    This function converts the ExtractedCourseData object into a dictionary
    that can be easily converted to JSON for storage in session or database.
    
    Args:
        data: ExtractedCourseData object to serialize
        
    Returns:
        Dictionary representation of the data
    """
    return {
        "term": {
            "term_name": data.term.term_name,
            "start_date": serialize_date(data.term.start_date),
            "end_date": serialize_date(data.term.end_date),
            "timezone": data.term.timezone
        },
        "lecture_sections": [
            {
                "section_type": s.section_type,
                "section_id": s.section_id,
                "days_of_week": s.days_of_week,
                "start_time": serialize_time(s.start_time),
                "end_time": serialize_time(s.end_time),
                "location": s.location
            }
            for s in data.lecture_sections
        ],
        "lab_sections": [
            {
                "section_type": s.section_type,
                "section_id": s.section_id,
                "days_of_week": s.days_of_week,
                "start_time": serialize_time(s.start_time),
                "end_time": serialize_time(s.end_time),
                "location": s.location
            }
            for s in data.lab_sections
        ],
        "assessments": [
            {
                "title": a.title,
                "type": a.type,
                "weight_percent": a.weight_percent,
                "due_datetime": serialize_datetime(a.due_datetime) if a.due_datetime else None,
                "due_rule": a.due_rule,
                "rule_anchor": a.rule_anchor,
                "confidence": a.confidence,
                "source_evidence": a.source_evidence,
                "needs_review": a.needs_review
            }
            for a in data.assessments
        ],
        "course_code": data.course_code,
        "course_name": data.course_name
    }


def calculate_completeness(data: ExtractedCourseData) -> Dict[str, Any]:
    """Calculate extraction completeness metrics.
    
    This function analyzes the extracted course data to determine:
    - How much of the course material is successfully extracted
    - What information is missing
    - Total assessment weight (handling extra credit >100%)
    
    Args:
        data: ExtractedCourseData object
        
    Returns:
        Dictionary with completeness metrics
    """
    metrics = {
        'course_code_found': data.course_code is not None,
        'course_name_found': data.course_name is not None,
        'term_found': data.term is not None and data.term.term_name != "Unknown",
        'lecture_sections_found': len(data.lecture_sections) > 0,
        'lab_sections_found': len(data.lab_sections) > 0,
        'num_lecture_sections': len(data.lecture_sections),
        'num_lab_sections': len(data.lab_sections),
        'num_assessments': len(data.assessments),
        'assessments_with_weight': 0,
        'assessments_with_date': 0,
        'assessments_complete': 0,  # Has both weight and date
        'total_weight': 0.0,
        'total_weight_with_dates': 0.0,
        'total_weight_without_dates': 0.0,
        'has_extra_credit': False,
    }
    
    # Analyze assessments
    for assessment in data.assessments:
        has_weight = assessment.weight_percent is not None
        has_date = assessment.due_datetime is not None
        
        if has_weight:
            metrics['assessments_with_weight'] += 1
            metrics['total_weight'] += assessment.weight_percent
            
            if has_date:
                metrics['assessments_complete'] += 1
                metrics['total_weight_with_dates'] += assessment.weight_percent
            else:
                metrics['total_weight_without_dates'] += assessment.weight_percent
        
        if has_date:
            metrics['assessments_with_date'] += 1
    
    # Check for extra credit (total > 100%)
    if metrics['total_weight'] > 100.0:
        metrics['has_extra_credit'] = True
    
    # Calculate completeness percentages
    total_items = 0
    found_items = 0
    
    # Course info
    total_items += 2  # course_code, course_name
    if metrics['course_code_found']:
        found_items += 1
    if metrics['course_name_found']:
        found_items += 1
    
    # Term
    total_items += 1
    if metrics['term_found']:
        found_items += 1
    
    # Sections
    total_items += 2  # lecture sections, lab sections
    if metrics['lecture_sections_found']:
        found_items += 1
    if metrics['lab_sections_found']:
        found_items += 1
    
    # Assessments completeness
    # This measures the quality of extracted assessments (do they have weight + date?)
    if metrics['num_assessments'] > 0:
        assessment_completeness = (metrics['assessments_complete'] / metrics['num_assessments']) * 100
    else:
        assessment_completeness = 0.0
    
    # Weight coverage: how much of the expected 100% weight have we captured?
    # This helps identify missing assessments
    # If total_weight is 60%, we're missing 40% worth of assessments
    if metrics['total_weight'] > 0:
        # Calculate coverage (capped at 100% for display, but can exceed due to extra credit)
        weight_coverage = min(metrics['total_weight'], 100.0)
        metrics['weight_coverage_percent'] = weight_coverage
        metrics['weight_missing_percent'] = max(0.0, 100.0 - weight_coverage)
    else:
        metrics['weight_coverage_percent'] = 0.0
        metrics['weight_missing_percent'] = 100.0
    
    metrics['overall_completeness'] = (found_items / total_items) * 100 if total_items > 0 else 0.0
    metrics['assessment_completeness'] = assessment_completeness
    
    return metrics


def deserialize_extracted_data(data: Dict[str, Any]) -> ExtractedCourseData:
    """Deserialize dict to ExtractedCourseData.
    
    This function converts a dictionary (from JSON) back into an
    ExtractedCourseData object. Used when loading data from cache or session.
    
    Args:
        data: Dictionary representation of ExtractedCourseData
        
    Returns:
        ExtractedCourseData object
    """
    from .models import CourseTerm, SectionOption, AssessmentTask
    
    term_dict = data["term"]
    term = CourseTerm(
        term_name=term_dict["term_name"],
        start_date=deserialize_date(term_dict["start_date"]),
        end_date=deserialize_date(term_dict["end_date"]),
        timezone=term_dict.get("timezone", "America/Toronto")
    )
    
    lecture_sections = [
        SectionOption(
            section_type=s["section_type"],
            section_id=s["section_id"],
            days_of_week=s["days_of_week"],
            start_time=deserialize_time(s["start_time"]),
            end_time=deserialize_time(s["end_time"]),
            location=s.get("location")
        )
        for s in data.get("lecture_sections", [])
    ]
    
    lab_sections = [
        SectionOption(
            section_type=s["section_type"],
            section_id=s["section_id"],
            days_of_week=s["days_of_week"],
            start_time=deserialize_time(s["start_time"]),
            end_time=deserialize_time(s["end_time"]),
            location=s.get("location")
        )
        for s in data.get("lab_sections", [])
    ]
    
    assessments = [
        AssessmentTask(
            title=a["title"],
            type=a["type"],
            weight_percent=a.get("weight_percent"),
            due_datetime=deserialize_datetime(a["due_datetime"]) if a.get("due_datetime") else None,
            due_rule=a.get("due_rule"),
            rule_anchor=a.get("rule_anchor"),
            confidence=a.get("confidence", 0.0),
            source_evidence=a.get("source_evidence"),
            needs_review=a.get("needs_review", False)
        )
        for a in data.get("assessments", [])
    ]
    
    return ExtractedCourseData(
        term=term,
        lecture_sections=lecture_sections,
        lab_sections=lab_sections,
        assessments=assessments,
        course_code=data.get("course_code"),
        course_name=data.get("course_name")
    )


@app.route('/')
def index():
    """Home page with PDF upload form.
    
    This is the main entry point of the web application. Users can upload
    a course outline PDF here to begin the conversion process.
    
    Returns:
        Rendered index.html template
    """
    # Pass tier info to template
    tier_info = tier_manager.get_tier_info()
    return render_template('index.html', tier_info=tier_info)


@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle PDF file upload.
    
    This route processes the uploaded PDF file:
    1. Validates the file
    2. Saves it temporarily
    3. Computes PDF hash
    4. Checks cache for existing extraction
    5. Extracts data if not cached
    6. Redirects to review page
    
    Returns:
        Redirect to review page or error page
    """
    # Check if file was uploaded
    if 'pdf_file' not in request.files:
        flash('No file selected. Please choose a PDF file.', 'error')
        return redirect(url_for('index'))
    
    file = request.files['pdf_file']
    force_refresh = request.form.get('force_refresh') == 'on'
    
    # Check if file is selected
    if file.filename == '':
        flash('No file selected. Please choose a PDF file.', 'error')
        return redirect(url_for('index'))
    
    # Check file extension
    if not allowed_file(file.filename):
        flash('Invalid file type. Please upload a PDF file.', 'error')
        return redirect(url_for('index'))
    
    try:
        # Save uploaded file
        filename = secure_filename(file.filename)
        filepath = Path(app.config['UPLOAD_FOLDER']) / filename
        file.save(str(filepath))
        
        # Check file size and tier limits
        file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
        can_process, error_msg = tier_manager.can_process_document(file_size_mb)
        if not can_process:
            os.remove(filepath)  # Clean up
            flash(error_msg, 'error')
            return redirect(url_for('index'))
        
        # Compute PDF hash
        pdf_hash = compute_pdf_hash(filepath)
        
        # Initialize session
        if 'session_id' not in session:
            session['session_id'] = str(uuid.uuid4())
        
        # Determine extraction method based on tier
        user_tier = tier_manager.get_user_tier()
        use_openai = user_tier == 'paid'
        
        # Check cache (unless force refresh)
        # Note: We cache by PDF hash only, but extraction method is determined by tier
        extracted_data = None
        if not force_refresh:
            extracted_data = cache_manager.lookup_extraction(pdf_hash)
            if extracted_data:
                flash('Found cached extraction data for this PDF.', 'info')
        
        # Extract from PDF if not cached or force refresh
        if extracted_data is None:
            try:
                if use_openai:
                    # Use OpenAI extractor for paid tier
                    try:
                        openai_extractor = OpenAIExtractor()
                        extracted_data = openai_extractor.extract_from_pdf(filepath)
                        flash('PDF extracted successfully using AI-powered extraction.', 'success')
                    except Exception as e:
                        # Fallback to free tier extraction if OpenAI fails
                        flash(f'AI extraction failed, using standard extraction: {str(e)}', 'warning')
                        extractor = PDFExtractor(filepath)
                        extracted_data = extractor.extract_all()
                else:
                    # Use standard extractor for free tier
                    extractor = PDFExtractor(filepath)
                    extracted_data = extractor.extract_all()
                
                # Resolve relative rules
                resolver = RuleResolver()
                all_sections = extracted_data.lecture_sections + extracted_data.lab_sections
                extracted_data.assessments = resolver.resolve_rules(
                    extracted_data.assessments,
                    all_sections,
                    extracted_data.term
                )
                
                # Cache extraction results (by PDF hash)
                cache_manager.store_extraction(pdf_hash, extracted_data)
                
                # Increment document count for paid users
                if use_openai:
                    tier_manager.increment_document_count()
                
            except Exception as e:
                flash(f'Error extracting PDF: {str(e)}', 'error')
                return redirect(url_for('index'))
        
        # Store in session for review page
        session['pdf_hash'] = pdf_hash
        session['pdf_filename'] = filename
        session['extracted_data'] = serialize_extracted_data(extracted_data)
        
        # Check for cached user choices
        user_choices = cache_manager.lookup_user_choices(pdf_hash, session.get('session_id'))
        if user_choices:
            session['user_choices'] = {
                'selected_lecture_section': serialize_section(user_choices.selected_lecture_section) if user_choices and user_choices.selected_lecture_section else None,
                'selected_lab_section': serialize_section(user_choices.selected_lab_section) if user_choices and user_choices.selected_lab_section else None,
            }
        else:
            session['user_choices'] = {}
        
        # Redirect to review page
        return redirect(url_for('review'))
        
    except RequestEntityTooLarge:
        flash('File too large. Maximum size is 16MB.', 'error')
        return redirect(url_for('index'))
    except Exception as e:
        flash(f'Error processing file: {str(e)}', 'error')
        return redirect(url_for('index'))


@app.route('/review', methods=['GET', 'POST'])
def review():
    """Review and edit extracted data.
    
    GET: Display review page with extracted data
    POST: Process user selections and generate calendar
    
    Returns:
        Rendered review.html template or redirect to download
    """
    # Check if we have extracted data
    if 'extracted_data' not in session:
        flash('No data to review. Please upload a PDF first.', 'error')
        return redirect(url_for('index'))
    
    extracted_data_dict = session['extracted_data']
    extracted_data = deserialize_extracted_data(extracted_data_dict)
    
    # ALWAYS check cache first - session data can be stale
    # This ensures we always have the latest extracted data
    pdf_hash = session.get('pdf_hash')
    if pdf_hash:
        cached_data = cache_manager.lookup_extraction(pdf_hash)
        if cached_data:
            # Use cached data (it's more reliable than session)
            extracted_data = cached_data
            # Update session with fresh data
            session['extracted_data'] = serialize_extracted_data(extracted_data)
    
    # Check if assessments are missing (likely stale session data)
    # This happens when session has old data from before extraction was fixed
    if len(extracted_data.assessments) == 0:
        print(f"DEBUG: No assessments found in session data. PDF hash: {session.get('pdf_hash')}")
        # Try to re-extract from cache or suggest force refresh
        pdf_hash = session.get('pdf_hash')
        if pdf_hash:
            cached_data = cache_manager.lookup_extraction(pdf_hash)
            if cached_data and len(cached_data.assessments) > 0:
                # Use cached data instead
                extracted_data = cached_data
                session['extracted_data'] = serialize_extracted_data(extracted_data)
                flash('Loaded updated assessment data from cache.', 'info')
            else:
                # Cache also empty - try re-extracting from PDF
                pdf_filename = session.get('pdf_filename')
                if pdf_filename:
                    filepath = Path(app.config['UPLOAD_FOLDER']) / pdf_filename
                    if filepath.exists():
                        try:
                            from .pdf_extractor import PDFExtractor
                            from .rule_resolver import RuleResolver
                            
                            extractor = PDFExtractor(filepath)
                            extracted_data = extractor.extract_all()
                            
                            # Resolve relative rules
                            resolver = RuleResolver()
                            all_sections = extracted_data.lecture_sections + extracted_data.lab_sections
                            extracted_data.assessments = resolver.resolve_rules(
                                extracted_data.assessments,
                                all_sections,
                                extracted_data.term
                            )
                            
                            # Update session and cache
                            session['extracted_data'] = serialize_extracted_data(extracted_data)
                            cache_manager.store_extraction(pdf_hash, extracted_data)
                            flash('Re-extracted assessments from PDF.', 'info')
                        except Exception as e:
                            flash(f'Could not re-extract: {str(e)}', 'warning')
    
    if request.method == 'POST':
        # Process form submission
        # Handle manual sections first (add them to extracted_data)
        # Note: Manual sections are only used when automatic extraction found no sections
        # The template only shows the "Add Manually" button when lab_sections/lecture_sections is empty
        manual_lecture_sections = request.form.get('manual_lecture_sections')
        manual_lab_sections = request.form.get('manual_lab_sections')
        
        if manual_lecture_sections:
            try:
                from .models import SectionOption
                from datetime import time as dt_time
                
                sections_data = json.loads(manual_lecture_sections)
                for section_data in sections_data:
                    # Parse time strings to time objects
                    start_hour, start_min = map(int, section_data['start_time'].split(':'))
                    end_hour, end_min = map(int, section_data['end_time'].split(':'))
                    
                    section = SectionOption(
                        section_type="Lecture",
                        section_id="",  # Manual sections don't have IDs
                        days_of_week=section_data['days'],
                        start_time=dt_time(start_hour, start_min),
                        end_time=dt_time(end_hour, end_min),
                        location=section_data.get('location') or None
                    )
                    extracted_data.lecture_sections.append(section)
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                flash(f'Error parsing manual lecture sections: {str(e)}', 'warning')
        
        if manual_lab_sections:
            try:
                from .models import SectionOption
                from datetime import time as dt_time
                
                sections_data = json.loads(manual_lab_sections)
                for section_data in sections_data:
                    # Parse time strings to time objects
                    start_hour, start_min = map(int, section_data['start_time'].split(':'))
                    end_hour, end_min = map(int, section_data['end_time'].split(':'))
                    
                    section = SectionOption(
                        section_type="Lab",
                        section_id="",  # Manual sections don't have IDs
                        days_of_week=section_data['days'],
                        start_time=dt_time(start_hour, start_min),
                        end_time=dt_time(end_hour, end_min),
                        location=section_data.get('location') or None
                    )
                    extracted_data.lab_sections.append(section)
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                flash(f'Error parsing manual lab sections: {str(e)}', 'warning')
        
        # Get selected sections
        lecture_idx = request.form.get('lecture_section')
        lab_idx = request.form.get('lab_section')
        
        user_selections = UserSelections()
        
        # Set selected lecture section
        if lecture_idx and lecture_idx != 'none':
            try:
                # Check if it's a manual section (starts with "manual_")
                if lecture_idx.startswith('manual_'):
                    # Extract index from "manual_X"
                    manual_idx = int(lecture_idx.split('_')[1])
                    # Manual sections are added at the end, so we need to find them
                    # Count how many manual sections we added
                    manual_count = len(json.loads(manual_lecture_sections)) if manual_lecture_sections else 0
                    # The manual sections are the last N sections in the list
                    # Find the section at the correct position
                    original_count = len(extracted_data.lecture_sections) - manual_count
                    section_idx = original_count + manual_idx
                    if 0 <= section_idx < len(extracted_data.lecture_sections):
                        user_selections.selected_lecture_section = extracted_data.lecture_sections[section_idx]
                else:
                    idx = int(lecture_idx)
                    if 0 <= idx < len(extracted_data.lecture_sections):
                        user_selections.selected_lecture_section = extracted_data.lecture_sections[idx]
            except (ValueError, IndexError, AttributeError):
                pass
        
        # Set selected lab section
        if lab_idx and lab_idx != 'none':
            try:
                # Check if it's a manual section (starts with "manual_")
                if lab_idx.startswith('manual_'):
                    # Extract index from "manual_X"
                    manual_idx = int(lab_idx.split('_')[1])
                    # Manual sections are added at the end, so we need to find them
                    # Count how many manual sections we added
                    manual_count = len(json.loads(manual_lab_sections)) if manual_lab_sections else 0
                    # The manual sections are the last N sections in the list
                    # Find the section at the correct position
                    original_count = len(extracted_data.lab_sections) - manual_count
                    section_idx = original_count + manual_idx
                    if 0 <= section_idx < len(extracted_data.lab_sections):
                        user_selections.selected_lab_section = extracted_data.lab_sections[section_idx]
                else:
                    idx = int(lab_idx)
                    if 0 <= idx < len(extracted_data.lab_sections):
                        user_selections.selected_lab_section = extracted_data.lab_sections[idx]
            except (ValueError, IndexError, AttributeError):
                pass
        
        # Get lead time overrides from session
        user_choices_dict = session.get('user_choices', {})
        lead_time_overrides = user_choices_dict.get('lead_time_overrides', {})
        
        # Store user choices in session
        session['user_choices'] = {
            'selected_lecture_section': serialize_section(user_selections.selected_lecture_section),
            'selected_lab_section': serialize_section(user_selections.selected_lab_section),
            'lead_time_overrides': lead_time_overrides  # Preserve lead time overrides
        }
        
        # Generate calendar
        try:
            # Get custom lead time mapping from session
            user_choices_dict = session.get('user_choices', {})
            custom_lead_time_mapping = user_choices_dict.get('custom_lead_time_mapping', {})
            
            # Convert custom mapping to StudyPlanGenerator format if provided
            # The generator expects a dict mapping weight thresholds to days
            # We need to convert range strings like "0-5%" to the appropriate threshold
            # Also merge with defaults for ranges not customized
            if custom_lead_time_mapping:
                # Convert range strings to weight thresholds
                range_to_threshold = {
                    "0-5%": 5,
                    "6-10%": 10,
                    "11-20%": 20,
                    "21-30%": 30,
                    "31%+": 50,
                    "Finals": 50  # Finals use the same as 31%+
                }
                # Start with default mapping
                default_gen = StudyPlanGenerator()
                lead_time_mapping_for_gen = default_gen.lead_time_mapping.copy()
                # Override with custom values
                for range_key, days in custom_lead_time_mapping.items():
                    threshold = range_to_threshold.get(range_key)
                    if threshold:
                        lead_time_mapping_for_gen[threshold] = days
                study_plan_gen = StudyPlanGenerator(lead_time_mapping=lead_time_mapping_for_gen)
            else:
                study_plan_gen = StudyPlanGenerator()
            
            # Resolve relative date rules before generating calendar
            # This ensures assessments with due_rule get converted to due_datetime
            from .rule_resolver import RuleResolver
            resolver = RuleResolver()
            all_sections = extracted_data.lecture_sections + extracted_data.lab_sections
            extracted_data.assessments = resolver.resolve_rules(
                extracted_data.assessments,
                all_sections,
                extracted_data.term
            )
            
            # Update session and cache with resolved assessments
            session['extracted_data'] = serialize_extracted_data(extracted_data)
            if pdf_hash:
                cache_manager.store_extraction(pdf_hash, extracted_data)
            
            # Generate study plan (pass lead time overrides)
            study_plan = study_plan_gen.generate_study_plan(
                extracted_data.assessments,
                user_lead_times=lead_time_overrides if lead_time_overrides else None
            )
            
            # Generate calendar
            cal_gen = ICalendarGenerator(timezone_str=extracted_data.term.timezone)
            calendar = cal_gen.generate_calendar(
                term=extracted_data.term,
                lecture_section=user_selections.selected_lecture_section,
                lab_section=user_selections.selected_lab_section,
                assessments=extracted_data.assessments,
                study_plan=study_plan
            )
            
            # Generate filename
            pdf_hash = session.get('pdf_hash', 'unknown')
            hash_short = pdf_hash[:8] if len(pdf_hash) >= 8 else pdf_hash
            course_code = extracted_data.course_code or 'Unknown'
            term_name = extracted_data.term.term_name.replace(' ', '')
            lec_id = user_selections.selected_lecture_section.section_id if user_selections.selected_lecture_section and user_selections.selected_lecture_section.section_id else 'None'
            lab_id = user_selections.selected_lab_section.section_id if user_selections.selected_lab_section and user_selections.selected_lab_section.section_id else 'None'
            
            # Sanitize filename components
            course_code_safe = (course_code or 'Unknown').replace(' ', '_').replace('/', '_')
            term_name_safe = term_name.replace(' ', '').replace('/', '_')
            lec_id_safe = lec_id if lec_id else 'None'
            lab_id_safe = lab_id if lab_id else 'None'
            hash_short_safe = hash_short[:8] if len(hash_short) >= 8 else hash_short
            
            filename = f"{course_code_safe}_{term_name_safe}_Lec{lec_id_safe}_Lab{lab_id_safe}_{hash_short_safe}.ics"
            # Final sanitization - remove any problematic characters
            filename = "".join(c for c in filename if c.isalnum() or c in "._-")
            
            # Save calendar to temporary file (use absolute path to avoid path issues)
            # Get project root (parent of src directory)
            project_root = Path(__file__).parent.parent
            temp_dir = project_root / 'temp_calendars'
            temp_dir.mkdir(exist_ok=True)
            temp_path = temp_dir / filename
            
            # Ensure the file is written successfully
            cal_gen.export_to_file(calendar, str(temp_path))
            
            if not temp_path.exists():
                raise FileNotFoundError(f"Calendar file was not created at {temp_path}")
            
            # Store in session (use absolute path)
            session['calendar_filename'] = filename
            session['calendar_path'] = str(temp_path.absolute())
            
            # Cache user choices
            pdf_hash = session.get('pdf_hash')
            if pdf_hash:
                cache_manager.store_user_choices(
                    pdf_hash,
                    user_selections,
                    session.get('session_id')
                )
            
            # Redirect to download
            return redirect(url_for('download', filename=filename))
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"Error generating calendar: {error_details}")
            flash(f'Error generating calendar: {str(e)}. Please try again or contact support if the issue persists.', 'error')
            # Continue to show review page with error
    
    # Get study plan mapping for display
    study_plan_gen = StudyPlanGenerator()
    default_lead_time_mapping = study_plan_gen.get_default_mapping_display()
    
    # Get user lead time overrides and custom mappings from session
    user_choices_dict = session.get('user_choices', {})
    lead_time_overrides = user_choices_dict.get('lead_time_overrides', {})
    custom_lead_time_mapping = user_choices_dict.get('custom_lead_time_mapping', {})
    
    # Merge custom mappings with default (custom takes precedence)
    lead_time_mapping = default_lead_time_mapping.copy()
    for range_key, days in custom_lead_time_mapping.items():
        if range_key in lead_time_mapping:
            lead_time_mapping[range_key] = days
    
    # Calculate completeness metrics (do this for both GET and POST)
    completeness = calculate_completeness(extracted_data)
    
    # Prepare assessments list for template
    # Calculate current lead time for each assessment
    study_plan_gen = StudyPlanGenerator()
    assessments_list = []
    for a in extracted_data.assessments:
        # Calculate current lead time (using override if available, otherwise default)
        current_lead_time = lead_time_overrides.get(a.title)
        if current_lead_time is None:
            # Use default calculation
            current_lead_time = study_plan_gen._get_lead_time(a, lead_time_overrides)
        
        assessments_list.append({
            'title': a.title,
            'type': a.type,
            'weight_percent': a.weight_percent,
            'due_datetime': a.due_datetime,  # Keep as datetime object for template
            'due_rule': a.due_rule,
            'confidence': a.confidence,
            'source_evidence': a.source_evidence,
            'needs_review': a.needs_review,
            'lead_time_days': current_lead_time  # Add lead time for display
        })
    
    # Prepare data for template (convert to dict for easier template handling)
    context = {
        'extracted_data': extracted_data_dict,
        'course_code': extracted_data.course_code or 'Not found',
        'course_name': extracted_data.course_name or 'Not found',
        'term': {
            'term_name': extracted_data.term.term_name,
            'start_date': extracted_data.term.start_date,
            'end_date': extracted_data.term.end_date,
            'timezone': extracted_data.term.timezone
        },
        'completeness': completeness,
        'lecture_sections': [
            {
                'section_type': s.section_type,
                'section_id': s.section_id,
                'days_of_week': s.days_of_week,
                'start_time': s.start_time,
                'end_time': s.end_time,
                'location': s.location
            }
            for s in extracted_data.lecture_sections
        ],
        'lab_sections': [
            {
                'section_type': s.section_type,
                'section_id': s.section_id,
                'days_of_week': s.days_of_week,
                'start_time': s.start_time,
                'end_time': s.end_time,
                'location': s.location
            }
            for s in extracted_data.lab_sections
        ],
        'assessments': assessments_list,
        'lead_time_mapping': lead_time_mapping,
        'user_choices': session.get('user_choices', {})
    }
    
    return render_template('review.html', **context)


@app.route('/manual', methods=['GET', 'POST'])
def manual():
    """Manual data entry mode.
    
    GET: Display manual entry form
    POST: Process manual input and generate calendar
    
    Returns:
        Rendered manual.html template or redirect to download
    """
    if request.method == 'POST':
        # Process manual form data
        # This will be implemented to handle manual input
        flash('Manual mode is not yet fully implemented.', 'info')
        return redirect(url_for('index'))
    
    return render_template('manual.html')


@app.route('/api/update-field', methods=['POST'])
def update_field():
    """API endpoint to update a field in the extracted data.
    
    This allows users to manually edit missing or incorrect information
    directly from the review page.
    
    Expected JSON payload:
    {
        "field_type": "course_code" | "course_name" | "term_start" | "term_end" | "assessment",
        "field_path": "course_code" or "assessments.0.due_datetime" etc,
        "value": new value,
        "assessment_index": optional, for assessment updates
    }
    
    Returns:
        JSON response with success status
    """
    if 'extracted_data' not in session:
        return jsonify({'success': False, 'error': 'No data to update'}), 400
    
    try:
        data = request.get_json()
        field_type = data.get('field_type')
        value = data.get('value')
        assessment_index = data.get('assessment_index')
        
        # Get current extracted data
        extracted_data_dict = session['extracted_data']
        extracted_data = deserialize_extracted_data(extracted_data_dict)
        
        # Update based on field type
        if field_type == 'course_code':
            extracted_data.course_code = value if value else None
            
        elif field_type == 'course_name':
            extracted_data.course_name = value if value else None
            
        elif field_type == 'term_start':
            if value:
                try:
                    # Parse date from datetime-local format (YYYY-MM-DDTHH:MM) or just YYYY-MM-DD
                    if 'T' in value:
                        date_str = value.split('T')[0]
                    elif ' ' in value:
                        date_str = value.split(' ')[0]
                    else:
                        date_str = value
                    extracted_data.term.start_date = deserialize_date(date_str)
                except (ValueError, AttributeError) as e:
                    return jsonify({'success': False, 'error': f'Invalid date format: {str(e)}. Use YYYY-MM-DD'}), 400
            else:
                extracted_data.term.start_date = None
            
        elif field_type == 'term_end':
            if value:
                try:
                    # Parse date from datetime-local format (YYYY-MM-DDTHH:MM) or just YYYY-MM-DD
                    if 'T' in value:
                        date_str = value.split('T')[0]
                    elif ' ' in value:
                        date_str = value.split(' ')[0]
                    else:
                        date_str = value
                    extracted_data.term.end_date = deserialize_date(date_str)
                except (ValueError, AttributeError) as e:
                    return jsonify({'success': False, 'error': f'Invalid date format: {str(e)}. Use YYYY-MM-DD'}), 400
            else:
                extracted_data.term.end_date = None
            
        elif field_type == 'assessment_due_date':
            if assessment_index is not None:
                try:
                    idx = int(assessment_index)
                    if 0 <= idx < len(extracted_data.assessments):
                        if value:
                            # Parse datetime from datetime-local format (YYYY-MM-DDTHH:MM)
                            try:
                                if 'T' in value:
                                    dt_str = value.replace('T', ' ')
                                else:
                                    dt_str = value
                                # Ensure we have time component
                                if len(dt_str.split(' ')) == 1:
                                    dt_str += ' 23:59:59'
                                extracted_data.assessments[idx].due_datetime = deserialize_datetime(dt_str)
                                # Clear rule if setting absolute date
                                extracted_data.assessments[idx].due_rule = None
                            except (ValueError, AttributeError) as e:
                                return jsonify({'success': False, 'error': f'Invalid datetime format: {str(e)}'}), 400
                        else:
                            extracted_data.assessments[idx].due_datetime = None
                except (ValueError, IndexError) as e:
                    return jsonify({'success': False, 'error': f'Invalid assessment index: {str(e)}'}), 400
            else:
                return jsonify({'success': False, 'error': 'assessment_index required for assessment updates'}), 400
                
        elif field_type == 'assessment_title':
            if assessment_index is not None:
                try:
                    idx = int(assessment_index)
                    if 0 <= idx < len(extracted_data.assessments):
                        if value and value.strip():
                            extracted_data.assessments[idx].title = value.strip()
                        else:
                            return jsonify({'success': False, 'error': 'Assessment title cannot be empty'}), 400
                except (ValueError, IndexError):
                    return jsonify({'success': False, 'error': 'Invalid assessment index'}), 400
            else:
                return jsonify({'success': False, 'error': 'assessment_index required for assessment updates'}), 400
                
        elif field_type == 'assessment_weight':
            if assessment_index is not None:
                try:
                    idx = int(assessment_index)
                    if 0 <= idx < len(extracted_data.assessments):
                        if value:
                            try:
                                weight = float(value)
                                extracted_data.assessments[idx].weight_percent = weight
                            except ValueError:
                                return jsonify({'success': False, 'error': 'Invalid weight value'}), 400
                        else:
                            extracted_data.assessments[idx].weight_percent = None
                except (ValueError, IndexError):
                    return jsonify({'success': False, 'error': 'Invalid assessment index'}), 400
            else:
                return jsonify({'success': False, 'error': 'assessment_index required for assessment updates'}), 400
                
        elif field_type == 'assessment_lead_time':
            if assessment_index is not None:
                try:
                    idx = int(assessment_index)
                    if 0 <= idx < len(extracted_data.assessments):
                        assessment = extracted_data.assessments[idx]
                        
                        # Get or create lead_time_overrides in user_choices
                        user_choices_dict = session.get('user_choices', {})
                        if 'lead_time_overrides' not in user_choices_dict:
                            user_choices_dict['lead_time_overrides'] = {}
                        
                        if value:
                            try:
                                lead_time = int(value)
                                if lead_time < 0:
                                    return jsonify({'success': False, 'error': 'Lead time must be non-negative'}), 400
                                # Store override
                                user_choices_dict['lead_time_overrides'][assessment.title] = lead_time
                            except ValueError:
                                return jsonify({'success': False, 'error': 'Invalid lead time value (must be an integer)'}), 400
                        else:
                            # Remove override (use default)
                            if assessment.title in user_choices_dict['lead_time_overrides']:
                                del user_choices_dict['lead_time_overrides'][assessment.title]
                        
                        # Update session
                        session['user_choices'] = user_choices_dict
                        
                        # Also update cache
                        pdf_hash = session.get('pdf_hash')
                        if pdf_hash:
                            # Get existing user selections or create new
                            user_selections = cache_manager.lookup_user_choices(pdf_hash, session.get('session_id'))
                            if user_selections is None:
                                from .models import UserSelections
                                user_selections = UserSelections()
                            
                            # Update lead time overrides
                            if not hasattr(user_selections, 'lead_time_overrides') or user_selections.lead_time_overrides is None:
                                user_selections.lead_time_overrides = {}
                            else:
                                # Convert from dict if needed
                                if isinstance(user_selections.lead_time_overrides, dict):
                                    pass  # Already a dict
                                else:
                                    user_selections.lead_time_overrides = {}
                            
                            if value:
                                user_selections.lead_time_overrides[assessment.title] = int(value)
                            elif assessment.title in user_selections.lead_time_overrides:
                                del user_selections.lead_time_overrides[assessment.title]
                            
                            cache_manager.store_user_choices(pdf_hash, user_selections, session.get('session_id'))
                except (ValueError, IndexError) as e:
                    return jsonify({'success': False, 'error': f'Invalid assessment index: {str(e)}'}), 400
            else:
                return jsonify({'success': False, 'error': 'assessment_index required for assessment updates'}), 400
        
        elif field_type == 'lead_time_mapping':
            # Get weight range from request
            weight_range = request.json.get('weight_range')
            if not weight_range:
                return jsonify({'success': False, 'error': 'weight_range required for lead_time_mapping updates'}), 400
            
            # Get or create custom_lead_time_mapping in user_choices
            user_choices_dict = session.get('user_choices', {})
            if 'custom_lead_time_mapping' not in user_choices_dict:
                user_choices_dict['custom_lead_time_mapping'] = {}
            
            if value:
                try:
                    lead_time = int(value)
                    if lead_time < 0:
                        return jsonify({'success': False, 'error': 'Lead time must be non-negative'}), 400
                    # Store custom mapping
                    user_choices_dict['custom_lead_time_mapping'][weight_range] = lead_time
                except ValueError:
                    return jsonify({'success': False, 'error': 'Invalid lead time value (must be an integer)'}), 400
            else:
                # Remove custom mapping (use default)
                if weight_range in user_choices_dict['custom_lead_time_mapping']:
                    del user_choices_dict['custom_lead_time_mapping'][weight_range]
            
            # Update session
            session['user_choices'] = user_choices_dict
            
            # Also update cache
            pdf_hash = session.get('pdf_hash')
            if pdf_hash:
                # Get existing user selections or create new
                user_selections = cache_manager.lookup_user_choices(pdf_hash, session.get('session_id'))
                if user_selections is None:
                    from .models import UserSelections
                    user_selections = UserSelections()
                
                # Update custom lead time mapping
                if not hasattr(user_selections, 'custom_lead_time_mapping') or user_selections.custom_lead_time_mapping is None:
                    user_selections.custom_lead_time_mapping = {}
                else:
                    # Convert from dict if needed
                    if isinstance(user_selections.custom_lead_time_mapping, dict):
                        pass  # Already a dict
                    else:
                        user_selections.custom_lead_time_mapping = {}
                
                if value:
                    user_selections.custom_lead_time_mapping[weight_range] = int(value)
                elif weight_range in user_selections.custom_lead_time_mapping:
                    del user_selections.custom_lead_time_mapping[weight_range]
                
                cache_manager.store_user_choices(pdf_hash, user_selections, session.get('session_id'))
        
        else:
            return jsonify({'success': False, 'error': f'Unknown field_type: {field_type}'}), 400
        
        # Update session with modified data
        session['extracted_data'] = serialize_extracted_data(extracted_data)
        
        # Also update cache
        pdf_hash = session.get('pdf_hash')
        if pdf_hash:
            cache_manager.store_extraction(pdf_hash, extracted_data)
        
        return jsonify({'success': True, 'message': 'Field updated successfully'})
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error updating field: {error_details}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/add-assessment', methods=['POST'])
def add_assessment():
    """API endpoint to add a new assessment.
    
    Expected JSON payload:
    {
        "title": "Assessment title",
        "type": "assignment" | "quiz" | "midterm" | "final" | etc,
        "weight_percent": 15.5 (optional),
        "due_datetime": "2025-12-15T23:59" (optional),
        "due_rule": "24 hours after lab" (optional),
        "rule_anchor": "lab" | "tutorial" | "lecture" (optional),
        "confidence": 0.8 (optional, default 0.8),
        "source_evidence": "Manual entry" (optional),
        "needs_review": true/false (optional)
    }
    
    Returns:
        JSON response with success status and updated completeness
    """
    if 'extracted_data' not in session:
        return jsonify({'success': False, 'error': 'No data to update'}), 400
    
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data.get('title'):
            return jsonify({'success': False, 'error': 'Title is required'}), 400
        if not data.get('type'):
            return jsonify({'success': False, 'error': 'Type is required'}), 400
        
        # Get current extracted data
        extracted_data_dict = session['extracted_data']
        extracted_data = deserialize_extracted_data(extracted_data_dict)
        
        # Parse due_datetime if provided
        due_datetime = None
        if data.get('due_datetime'):
            try:
                if 'T' in data['due_datetime']:
                    dt_str = data['due_datetime'].replace('T', ' ')
                else:
                    dt_str = data['due_datetime']
                if len(dt_str.split(' ')) == 1:
                    dt_str += ' 23:59:59'
                due_datetime = deserialize_datetime(dt_str)
            except (ValueError, AttributeError) as e:
                return jsonify({'success': False, 'error': f'Invalid datetime format: {str(e)}'}), 400
        
        # Parse weight if provided
        weight_percent = None
        if data.get('weight_percent'):
            try:
                weight_percent = float(data['weight_percent'])
                if weight_percent < 0 or weight_percent > 100:
                    return jsonify({'success': False, 'error': 'Weight must be between 0 and 100'}), 400
            except (ValueError, TypeError):
                return jsonify({'success': False, 'error': 'Invalid weight value'}), 400
        
        # Parse confidence
        confidence = float(data.get('confidence', 0.8))
        if confidence < 0 or confidence > 1:
            confidence = 0.8
        
        # Create new assessment
        new_assessment = AssessmentTask(
            title=data['title'],
            type=data['type'],
            weight_percent=weight_percent,
            due_datetime=due_datetime,
            due_rule=data.get('due_rule'),
            rule_anchor=data.get('rule_anchor'),
            confidence=confidence,
            source_evidence=data.get('source_evidence', 'Manual entry'),
            needs_review=bool(data.get('needs_review', False))
        )
        
        # Add to assessments list
        extracted_data.assessments.append(new_assessment)
        
        # Store updated data back in session
        session['extracted_data'] = serialize_extracted_data(extracted_data)
        
        # Update cache if available
        pdf_hash = session.get('pdf_hash')
        if pdf_hash:
            cache_manager = get_cache_manager()
            cache_manager.store_extraction(pdf_hash, extracted_data)
        
        # Recalculate completeness
        completeness = calculate_completeness(extracted_data)
        
        return jsonify({
            'success': True,
            'completeness': completeness,
            'message': 'Assessment added successfully'
        })
    
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error adding assessment: {error_details}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/remove-assessment', methods=['POST'])
def remove_assessment():
    """API endpoint to remove an assessment.
    
    Expected JSON payload:
    {
        "assessment_index": 0 (index of assessment to remove)
    }
    
    Returns:
        JSON response with success status and updated completeness
    """
    if 'extracted_data' not in session:
        return jsonify({'success': False, 'error': 'No data to update'}), 400
    
    try:
        data = request.get_json()
        assessment_index = data.get('assessment_index')
        
        if assessment_index is None:
            return jsonify({'success': False, 'error': 'assessment_index is required'}), 400
        
        # Get current extracted data
        extracted_data_dict = session['extracted_data']
        extracted_data = deserialize_extracted_data(extracted_data_dict)
        
        # Validate index
        try:
            idx = int(assessment_index)
            if idx < 0 or idx >= len(extracted_data.assessments):
                return jsonify({'success': False, 'error': 'Invalid assessment index'}), 400
            
            # Remove assessment
            removed_assessment = extracted_data.assessments.pop(idx)
            
        except (ValueError, IndexError) as e:
            return jsonify({'success': False, 'error': f'Invalid assessment index: {str(e)}'}), 400
        
        # Store updated data back in session
        session['extracted_data'] = serialize_extracted_data(extracted_data)
        
        # Update cache if available
        pdf_hash = session.get('pdf_hash')
        if pdf_hash:
            cache_manager = get_cache_manager()
            cache_manager.store_extraction(pdf_hash, extracted_data)
        
        # Recalculate completeness
        completeness = calculate_completeness(extracted_data)
        
        return jsonify({
            'success': True,
            'completeness': completeness,
            'message': f'Assessment "{removed_assessment.title}" removed successfully'
        })
    
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error removing assessment: {error_details}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/download/<filename>')
def download(filename: str):
    """Download generated .ics file.
    
    Args:
        filename: Name of the calendar file to download
        
    Returns:
        File download response or redirect with error message
    """
    # Check if file exists in session
    if 'calendar_path' not in session or session.get('calendar_filename') != filename:
        flash('Calendar file not found. Please generate a calendar first.', 'error')
        return redirect(url_for('review'))
    
    filepath = Path(session['calendar_path'])
    
    # Handle both absolute and relative paths
    if not filepath.is_absolute():
        project_root = Path(__file__).parent.parent
        filepath = project_root / filepath
    
    if not filepath.exists():
        flash('Calendar file not found. Please try generating the calendar again.', 'error')
        return redirect(url_for('review'))
    
    try:
        return send_file(
            str(filepath),
            as_attachment=True,
            download_name=filename,
            mimetype='text/calendar'
        )
    except Exception as e:
        flash(f'Error downloading calendar: {str(e)}. Please try generating the calendar again.', 'error')
        return redirect(url_for('review'))


@app.route('/checkout', methods=['POST'])
def checkout():
    """Create Stripe checkout session for paid tier.
    
    Returns:
        Redirect to Stripe checkout page
    """
    try:
        import stripe
        
        stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
        if not stripe.api_key:
            flash('Payment processing is not configured. Please contact support.', 'error')
            return redirect(url_for('index'))
        
        # Create checkout session
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': '15 Document Processing Package',
                        'description': 'Process up to 15 course outlines with AI-powered extraction'
                    },
                    'unit_amount': 300,  # $3.00 in cents
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=url_for('payment_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('index', _external=True),
            metadata={
                'user_session': session.get('session_id', 'unknown')
            }
        )
        
        return redirect(checkout_session.url)
        
    except ImportError:
        flash('Stripe is not installed. Please install with: pip install stripe', 'error')
        return redirect(url_for('index'))
    except Exception as e:
        flash(f'Error creating checkout session: {str(e)}', 'error')
        return redirect(url_for('index'))


@app.route('/payment/success')
def payment_success():
    """Handle successful payment and upgrade user to paid tier.
    
    Returns:
        Redirect to index with success message
    """
    try:
        import stripe
        
        stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
        session_id = request.args.get('session_id')
        
        if session_id:
            # Verify payment with Stripe
            checkout_session = stripe.checkout.Session.retrieve(session_id)
            
            if checkout_session.payment_status == 'paid':
                # Upgrade user to paid tier
                tier_manager.set_user_tier('paid')
                flash('Payment successful! You now have access to AI-powered extraction for 15 documents.', 'success')
            else:
                flash('Payment is still processing. Please wait a moment and refresh.', 'info')
        else:
            flash('Payment successful! You now have access to AI-powered extraction for 15 documents.', 'success')
            tier_manager.set_user_tier('paid')
        
        return redirect(url_for('index'))
        
    except Exception as e:
        flash(f'Error processing payment: {str(e)}', 'error')
        return redirect(url_for('index'))


@app.route('/api/tier-info')
def api_tier_info():
    """Get current user tier information.
    
    Returns:
        JSON with tier information
    """
    tier_info = tier_manager.get_tier_info()
    return jsonify(tier_info)


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return render_template('error.html', error='Page not found'), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    return render_template('error.html', error='Internal server error'), 500


if __name__ == '__main__':
    # Run development server
    app.run(debug=True, host='0.0.0.0', port=5000)

