"""
Main CLI entry point for course outline to iCalendar converter.
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import date, datetime, time
from typing import Optional

from .models import (
    ExtractedCourseData, UserSelections, CourseTerm, SectionOption,
    serialize_date, serialize_datetime, serialize_time
)
from .cache import get_cache_manager, compute_pdf_hash
from .pdf_extractor import PDFExtractor
from .rule_resolver import RuleResolver
from .study_plan import StudyPlanGenerator
from .icalendar_gen import ICalendarGenerator


def prompt_section_selection(sections: list, section_type: str) -> Optional[SectionOption]:
    """Prompt user to select a section.
    
    Args:
        sections: List of SectionOption objects
        section_type: "Lecture" or "Lab"
        
    Returns:
        Selected section or None
    """
    if not sections:
        return None
    
    if len(sections) == 1:
        return sections[0]
    
    print(f"\nMultiple {section_type} sections found:")
    for i, section in enumerate(sections, start=1):
        days_str = ", ".join([
            ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d]
            for d in section.days_of_week
        ])
        location_str = f" ({section.location})" if section.location else ""
        # Format times in 12-hour format
        def format_time_12h(t):
            hour = t.hour
            minute = t.minute
            ampm = 'AM' if hour < 12 else 'PM'
            display_hour = hour % 12
            if display_hour == 0:
                display_hour = 12
            return f"{display_hour}:{minute:02d} {ampm}"
        print(f"  {i}. Section {section.section_id or 'N/A'}: {days_str} "
              f"{format_time_12h(section.start_time)}-{format_time_12h(section.end_time)}"
              f"{location_str}")
    
    while True:
        try:
            choice = input(f"\nWhich {section_type} section are you enrolled in? (1-{len(sections)}): ")
            idx = int(choice) - 1
            if 0 <= idx < len(sections):
                return sections[idx]
            else:
                print(f"Please enter a number between 1 and {len(sections)}")
        except ValueError:
            print("Please enter a valid number")
        except KeyboardInterrupt:
            print("\nCancelled.")
            sys.exit(1)


def prompt_term_info() -> CourseTerm:
    """Prompt user for term information.
    
    Returns:
        CourseTerm object
    """
    print("\nTerm information not found in PDF. Please provide:")
    
    term_name = input("Term name (e.g., 'Fall 2026'): ").strip()
    if not term_name:
        term_name = "Unknown"
    
    while True:
        start_str = input("Term start date (YYYY-MM-DD): ").strip()
        try:
            start_date = date.fromisoformat(start_str)
            break
        except ValueError:
            print("Please enter date in YYYY-MM-DD format")
    
    while True:
        end_str = input("Term end date (YYYY-MM-DD): ").strip()
        try:
            end_date = date.fromisoformat(end_str)
            break
        except ValueError:
            print("Please enter date in YYYY-MM-DD format")
    
    return CourseTerm(
        term_name=term_name,
        start_date=start_date,
        end_date=end_date,
        timezone="America/Toronto"
    )


def prompt_missing_section(section_type: str) -> Optional[SectionOption]:
    """Prompt user for missing section information.
    
    Args:
        section_type: "Lecture" or "Lab"
        
    Returns:
        SectionOption or None if user skips
    """
    print(f"\n{section_type} schedule not found in PDF.")
    response = input(f"Do you have a {section_type} section? (y/n): ").strip().lower()
    
    if response != 'y':
        return None
    
    # Get days of week
    print("\nEnter days of week (e.g., 'MWF' for Mon/Wed/Fri, or 'TTh' for Tue/Thu):")
    days_str = input("Days: ").strip().upper()
    
    # Parse days
    day_map = {
        'M': 0, 'MON': 0, 'MONDAY': 0,
        'T': 1, 'TUE': 1, 'TUESDAY': 1,
        'W': 2, 'WED': 2, 'WEDNESDAY': 2,
        'TH': 3, 'THU': 3, 'THURSDAY': 3,
        'F': 4, 'FRI': 4, 'FRIDAY': 4,
        'S': 5, 'SAT': 5, 'SATURDAY': 5,
        'SU': 6, 'SUN': 6, 'SUNDAY': 6,
    }
    
    days_of_week = []
    i = 0
    while i < len(days_str):
        if i + 1 < len(days_str) and days_str[i:i+2] in day_map:
            days_of_week.append(day_map[days_str[i:i+2]])
            i += 2
        elif days_str[i] in day_map:
            days_of_week.append(day_map[days_str[i]])
            i += 1
        else:
            i += 1
    
    if not days_of_week:
        print("Could not parse days. Using Monday as default.")
        days_of_week = [0]
    
    # Get time (input is 24-hour format, but will be displayed in 12-hour format)
    while True:
        time_str = input("Start time (HH:MM, 24-hour format, e.g., 14:30 for 2:30 PM): ").strip()
        try:
            hour, minute = map(int, time_str.split(':'))
            start_time = time(hour, minute)
            break
        except ValueError:
            print("Please enter time in HH:MM format (24-hour)")
    
    while True:
        time_str = input("End time (HH:MM, 24-hour format, e.g., 16:00 for 4:00 PM): ").strip()
        try:
            hour, minute = map(int, time_str.split(':'))
            end_time = time(hour, minute)
            break
        except ValueError:
            print("Please enter time in HH:MM format (24-hour)")
    
    location = input("Location (optional, press Enter to skip): ").strip() or None
    
    return SectionOption(
        section_type=section_type,
        section_id="",
        days_of_week=sorted(list(set(days_of_week))),
        start_time=start_time,
        end_time=end_time,
        location=location
    )


def review_assessments(assessments: list) -> list:
    """Review and allow user to correct assessments.
    
    Args:
        assessments: List of AssessmentTask objects
        
    Returns:
        Updated list of assessments
    """
    needs_review = [a for a in assessments if a.needs_review]
    
    if not needs_review:
        return assessments
    
    print(f"\n{len(needs_review)} assessment(s) need review:")
    
    for i, assessment in enumerate(needs_review, start=1):
        print(f"\n{i}. {assessment.title}")
        print(f"   Type: {assessment.type}")
        print(f"   Weight: {assessment.weight_percent or 'Not specified'}")
        print(f"   Due: {assessment.due_datetime or assessment.due_rule or 'Not specified'}")
        print(f"   Source: {assessment.source_evidence or 'N/A'}")
        
        response = input("\nIs this information correct? (y/n/skip): ").strip().lower()
        
        if response == 'n':
            # Allow user to correct
            new_due = input("Due date (YYYY-MM-DD HH:MM, or press Enter to skip): ").strip()
            if new_due:
                try:
                    assessment.due_datetime = datetime.fromisoformat(new_due.replace(' ', 'T'))
                except ValueError:
                    print("Invalid date format, skipping")
            
            new_weight = input("Weight percentage (or press Enter to skip): ").strip()
            if new_weight:
                try:
                    assessment.weight_percent = float(new_weight)
                except ValueError:
                    print("Invalid weight, skipping")
            
            assessment.needs_review = False
        elif response == 'skip':
            # Keep needs_review = True
            pass
        else:
            # User confirmed, mark as reviewed
            assessment.needs_review = False
    
    return assessments


def serialize_extracted_data(data: ExtractedCourseData) -> dict:
    """Serialize ExtractedCourseData to JSON-serializable dict."""
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


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Convert Western University course outline PDF to iCalendar file"
    )
    parser.add_argument(
        "pdf_path",
        type=str,
        help="Path to course outline PDF file"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=".",
        help="Output directory for JSON and .ics files (default: current directory)"
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable caching (reprocess PDF even if cached)"
    )
    
    args = parser.parse_args()
    
    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"Error: PDF file not found: {pdf_path}")
        sys.exit(1)
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize components
    cache_manager = get_cache_manager()
    pdf_hash = compute_pdf_hash(pdf_path)
    
    # Check cache
    extracted_data = None
    user_selections = UserSelections()
    
    if not args.no_cache:
        # Try to get cached extraction data
        cached_extraction = cache_manager.lookup_extraction(pdf_hash)
        if cached_extraction:
            print(f"Found cached extraction data for this PDF")
            use_cache = input("Use cached extraction data? (y/n): ").strip().lower() == 'y'
            if use_cache:
                extracted_data = cached_extraction
                # Also try to get user choices
                cached_choices = cache_manager.lookup_user_choices(pdf_hash)
                if cached_choices:
                    user_selections = cached_choices
    
    # Extract from PDF if not cached
    if extracted_data is None:
        print(f"Extracting data from PDF: {pdf_path}")
        extractor = PDFExtractor(pdf_path)
        extracted_data = extractor.extract_all()
        
        # Prompt for term if missing
        if extracted_data.term.term_name == "Unknown" or not extracted_data.term.start_date:
            extracted_data.term = prompt_term_info()
        
        # Resolve relative rules
        resolver = RuleResolver()
        all_sections = extracted_data.lecture_sections + extracted_data.lab_sections
        extracted_data.assessments = resolver.resolve_rules(
            extracted_data.assessments,
            all_sections,
            extracted_data.term
        )
        
        # Review assessments
        extracted_data.assessments = review_assessments(extracted_data.assessments)
    
    # Get user selections (if not already cached)
    if not user_selections.selected_lecture_section:
        user_selections.selected_lecture_section = prompt_section_selection(
            extracted_data.lecture_sections, "Lecture"
        )
        
        if not user_selections.selected_lecture_section and not extracted_data.lecture_sections:
            user_selections.selected_lecture_section = prompt_missing_section("Lecture")
    
    if not user_selections.selected_lab_section:
        user_selections.selected_lab_section = prompt_section_selection(
            extracted_data.lab_sections, "Lab"
        )
        
        if not user_selections.selected_lab_section and not extracted_data.lab_sections:
            user_selections.selected_lab_section = prompt_missing_section("Lab")
    
    # Generate study plan
    study_plan_gen = StudyPlanGenerator()
    study_plan = study_plan_gen.generate_study_plan(extracted_data.assessments)
    
    # Generate calendar
    print("\nGenerating iCalendar file...")
    cal_gen = ICalendarGenerator(timezone_str=extracted_data.term.timezone)
    calendar = cal_gen.generate_calendar(
        term=extracted_data.term,
        lecture_section=user_selections.selected_lecture_section,
        lab_section=user_selections.selected_lab_section,
        assessments=extracted_data.assessments,
        study_plan=study_plan
    )
    
    # Save outputs
    base_name = pdf_path.stem
    json_path = output_dir / f"{base_name}_extracted.json"
    ics_path = output_dir / f"{base_name}.ics"
    
    # Save JSON
    with open(json_path, 'w') as f:
        json.dump(serialize_extracted_data(extracted_data), f, indent=2)
    print(f"Saved extracted data to: {json_path}")
    
    # Save .ics
    cal_gen.export_to_file(calendar, str(ics_path))
    print(f"Saved calendar to: {ics_path}")
    
    # Cache results
    if not args.no_cache:
        # Store extraction data and user choices separately
        cache_manager.store_extraction(pdf_hash, extracted_data)
        cache_manager.store_user_choices(pdf_hash, user_selections)
        print("Results cached for future use.")
    
    print("\nDone! You can now import the .ics file into your calendar.")


if __name__ == "__main__":
    main()






