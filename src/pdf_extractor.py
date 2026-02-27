"""
PDF extraction module for course outlines.

Extracts term information, lecture/lab sections, and assessments from PDF files.
Uses a multi-layered extraction approach for maximum compatibility.

Version 2.0: Now uses document structure layer for improved extraction.
"""

import os
import re
import pdfplumber
from pathlib import Path
from datetime import date, datetime, time
from typing import List, Optional, Tuple, Dict, Any
import dateparser

from .models import (
    CourseTerm, SectionOption, AssessmentTask, ExtractedCourseData
)

# Try to import new extraction modules
try:
    from .document_structure import DocumentStructureExtractor, DocumentStructure
    from .assessment_extractor import AssessmentExtractor
    from .course_extractor import CourseInfoExtractor
    HAS_NEW_EXTRACTORS = True
except ImportError:
    HAS_NEW_EXTRACTORS = False

# Constants
MAX_FILE_SIZE_MB = 5.0  # Increased from 2.0MB to 5.0MB
MAX_PAGES_TO_SEARCH = 8


class PDFExtractor:
    """Extracts course information from PDF course outlines."""
    
    def __init__(self, pdf_path: Path):
        """Initialize extractor with PDF path.
        
        Args:
            pdf_path: Path to PDF file
            
        Raises:
            ValueError: If file is too large
        """
        self.pdf_path = Path(pdf_path)
        self.pages_text = []
        
        # Check file size
        if self.pdf_path.exists():
            size_mb = os.path.getsize(self.pdf_path) / (1024 * 1024)
            if size_mb > MAX_FILE_SIZE_MB:
                raise ValueError(f"PDF too large ({size_mb:.1f}MB). Maximum is {MAX_FILE_SIZE_MB}MB.")
        
        self._load_pdf()
    
    def _load_pdf(self):
        """Load PDF and extract text page by page."""
        with pdfplumber.open(self.pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                text = page.extract_text()
                if text:
                    self.pages_text.append((page_num, text))
    
    def extract_all(self) -> ExtractedCourseData:
        """Extract all course information from PDF.
        
        Returns:
            ExtractedCourseData with term, sections, and assessments
        """
        # Try new document structure-based extraction first
        if HAS_NEW_EXTRACTORS:
            try:
                return self._extract_with_document_structure()
            except Exception as e:
                # Fall back to legacy extraction if new method fails
                print(f"Document structure extraction failed, using legacy: {e}")
        
        # Legacy extraction
        return self._extract_legacy()
    
    def _extract_with_document_structure(self) -> ExtractedCourseData:
        """Extract using the new document structure layer.
        
        This method:
        1. Builds a structured representation of the PDF
        2. Segments into sections (Evaluation, Course Info, etc.)
        3. Scopes extraction to relevant sections
        4. Uses candidate generation + scoring + selection for assessments
        5. Falls back to legacy methods when new methods underperform
        
        Returns:
            ExtractedCourseData with improved accuracy
        """
        # Build document structure
        doc_extractor = DocumentStructureExtractor(self.pdf_path)
        doc_structure = doc_extractor.extract()
        
        # Store for debugging
        self._doc_structure = doc_structure
        
        # Extract term (still using legacy method - works well)
        term = self.extract_term()
        
        # Extract lecture/lab sections (still using legacy - schedules not in PDFs)
        lecture_sections = self.extract_lecture_sections()
        lab_sections = self.extract_lab_sections()
        
        # Extract assessments using BOTH methods, pick best result
        # New pipeline (pass pdf_path for raw text extraction fallback)
        assessment_extractor = AssessmentExtractor(doc_structure, pdf_path=self.pdf_path)
        new_assessments = assessment_extractor.extract()
        new_weight = sum(a.weight_percent or 0 for a in new_assessments)
        
        # Store debug info
        self._assessment_debug = assessment_extractor.get_debug_info()
        
        # Legacy pipeline
        legacy_assessments = self.extract_assessments()
        legacy_weight = sum(a.weight_percent or 0 for a in legacy_assessments)
        
        # Choose best result based on:
        # 1. Weight closest to 100
        # 2. Number of assessments (more is better if weights are similar)
        new_score = self._score_assessment_quality(new_assessments, new_weight)
        legacy_score = self._score_assessment_quality(legacy_assessments, legacy_weight)
        
        if new_score >= legacy_score:
            assessments = new_assessments
            self._assessment_source = "new"
        else:
            assessments = legacy_assessments
            self._assessment_source = "legacy"
        
        # Extract course info using new layout-based method
        course_extractor = CourseInfoExtractor(doc_structure)
        course_code, course_name = course_extractor.extract()
        
        # Store debug info
        self._course_debug = course_extractor.get_debug_info()
        
        # Fallback for course code if new method didn't find it
        if not course_code:
            legacy_code, _ = self.extract_course_info()
            course_code = legacy_code
        
        # Fallback for course name
        if not course_name:
            _, legacy_name = self.extract_course_info()
            course_name = legacy_name
        
        return ExtractedCourseData(
            term=term,
            lecture_sections=lecture_sections,
            lab_sections=lab_sections,
            assessments=assessments,
            course_code=course_code,
            course_name=course_name
        )
    
    def _score_assessment_quality(self, assessments: List[AssessmentTask], total_weight: float) -> float:
        """Score the quality of assessment extraction.
        
        Higher score = better extraction.
        
        Factors:
        - Weight close to 100 (best)
        - Weight in 90-110 range (good)
        - Having multiple assessments
        - Having named assessments (not garbage)
        """
        if not assessments:
            return 0.0
        
        score = 0.0
        
        # Weight score: best if 95-105, good if 90-110, ok if 80-120
        if 95 <= total_weight <= 105:
            score += 50
        elif 90 <= total_weight <= 110:
            score += 40
        elif 80 <= total_weight <= 120:
            score += 25
        elif total_weight > 0:
            # Penalty for being far from 100
            distance = abs(100 - total_weight)
            score += max(0, 20 - distance * 0.3)
        
        # Count of valid assessments (those with weights)
        valid_count = sum(1 for a in assessments if a.weight_percent and a.weight_percent > 0)
        score += min(valid_count * 5, 25)  # Up to 25 points for 5+ assessments
        
        # Bonus for having common assessment types
        common_types = {'exam', 'midterm', 'final', 'quiz', 'assignment', 'lab', 'test'}
        type_matches = sum(1 for a in assessments 
                          if any(t in a.title.lower() for t in common_types))
        score += min(type_matches * 3, 15)  # Up to 15 points
        
        return score
    
    def _extract_legacy(self) -> ExtractedCourseData:
        """Legacy extraction method (fallback).
        
        Returns:
            ExtractedCourseData with term, sections, and assessments
        """
        term = self.extract_term()
        lecture_sections = self.extract_lecture_sections()
        lab_sections = self.extract_lab_sections()
        assessments = self.extract_assessments()
        
        # Try to extract course code and name
        course_code, course_name = self.extract_course_info()
        
        return ExtractedCourseData(
            term=term,
            lecture_sections=lecture_sections,
            lab_sections=lab_sections,
            assessments=assessments,
            course_code=course_code,
            course_name=course_name
        )
    
    def get_extraction_debug(self) -> Dict[str, Any]:
        """Get debug information about the extraction process.
        
        Returns:
            Dictionary with debug info about sections, candidates, etc.
        """
        debug = {
            'has_new_extractors': HAS_NEW_EXTRACTORS,
        }
        
        if hasattr(self, '_doc_structure'):
            ds = self._doc_structure
            debug['document_structure'] = {
                'num_pages': len(ds.pages),
                'num_blocks': len(ds.blocks),
                'num_tables': len(ds.tables),
                'num_sections': len(ds.sections),
                'sections': [
                    {'name': s.name, 'heading': s.heading_text, 
                     'pages': f"{s.start_page}-{s.end_page}"}
                    for s in ds.sections
                ]
            }
        
        if hasattr(self, '_assessment_debug'):
            debug['assessment_extraction'] = self._assessment_debug
        
        if hasattr(self, '_course_debug'):
            debug['course_extraction'] = self._course_debug
        
        return debug
    
    def extract_term(self) -> CourseTerm:
        """Extract term information from PDF.
        
        This function searches the first 3 pages of the PDF for term information.
        It looks for patterns like "Fall 2026" or "Winter Term 2027" and date ranges.
        If information is missing, it returns placeholder values that will be
        filled in by user input later.
        
        Returns:
            CourseTerm object with term name and date range. If information is
            missing, returns placeholder values (term_name="Unknown" or default dates).
        """
        # Search first 3 pages for term information
        # Most course outlines have term info on the first page or two
        search_text = "\n".join([text for _, text in self.pages_text[:3]])
        
        # Pattern for term name - look for "Fall 2026", "Winter Term 2027", etc.
        # These patterns match common ways term names are written in course outlines
        term_patterns = [
            r'(Fall|Winter|Summer)\s+(\d{4})',  # "Fall 2026"
            r'(Fall|Winter|Summer)\s+Term\s+(\d{4})',  # "Fall Term 2026"
            r'(Fall|Winter|Summer)\s+Semester\s+(\d{4})',  # "Fall Semester 2026"
        ]
        
        term_name = None
        # Try each pattern until we find a match
        for pattern in term_patterns:
            match = re.search(pattern, search_text, re.IGNORECASE)
            if match:
                # Combine the season and year (e.g., "Fall 2026")
                term_name = f"{match.group(1)} {match.group(2)}"
                break
        
        # Pattern for date ranges - look for "September 1 - December 15, 2026"
        # or "2026-09-01 - 2026-12-15" format
        date_range_patterns = [
            r'(September|October|November|December|January|February|March|April|May|June|July|August)\s+(\d{1,2})\s*[-–]\s*(September|October|November|December|January|February|March|April|May|June|July|August)\s+(\d{1,2}),?\s+(\d{4})',
            r'(\d{4})-(\d{2})-(\d{2})\s*[-–]\s*(\d{4})-(\d{2})-(\d{2})',
        ]
        
        start_date = None
        end_date = None
        
        # Try to find date ranges in the text
        for pattern in date_range_patterns:
            match = re.search(pattern, search_text, re.IGNORECASE)
            if match:
                # Try to parse dates using dateparser library
                # This handles various date formats automatically
                date_str = match.group(0)
                dates = dateparser.parse(date_str, fuzzy=True)
                if dates:
                    # This is a simplified approach - may need refinement
                    # For now, we'll infer dates from term name if this doesn't work
                    pass
        
        # If term name found but dates missing, try to infer from term name
        # For example, "Fall 2026" typically means September to December
        if term_name and not start_date:
            year_match = re.search(r'\d{4}', term_name)
            if year_match:
                year = int(year_match.group(0))
                # Set default dates based on term type
                if "Fall" in term_name:
                    start_date = date(year, 9, 1)  # September 1
                    end_date = date(year, 12, 15)  # December 15
                elif "Winter" in term_name:
                    start_date = date(year, 1, 8)  # January 8
                    end_date = date(year, 4, 30)  # April 30
                elif "Summer" in term_name:
                    start_date = date(year, 5, 1)  # May 1
                    end_date = date(year, 8, 31)  # August 31
        
        # If still missing, return with placeholder values
        # The caller (main.py or app.py) will prompt the user to fill these in
        if not term_name or not start_date or not end_date:
            # Return placeholder - will be filled by user input
            return CourseTerm(
                term_name=term_name or "Unknown",
                start_date=start_date or date.today(),
                end_date=end_date or date.today()
            )
        
        # Return the extracted term information
        return CourseTerm(
            term_name=term_name,
            start_date=start_date,
            end_date=end_date,
            timezone="America/Toronto"  # Western University is in Toronto timezone
        )
    
    def extract_lecture_sections(self) -> List[SectionOption]:
        """Extract lecture section schedules using multi-pattern matching.
        
        Returns:
            List of SectionOption objects for lectures
        """
        sections = []
        # Search for schedule section (usually in first few pages)
        search_text = "\n".join([text for _, text in self.pages_text[:MAX_PAGES_TO_SEARCH]])
        
        # Try table-based extraction first
        table_sections = self._extract_schedule_from_tables("lecture")
        if table_sections:
            return table_sections
        
        # Try text-based extraction
        text_sections = self._extract_schedule_from_text("lecture", search_text)
        if text_sections:
            return text_sections
        
        # Legacy pattern matching (keeping existing logic as fallback)
        schedule_patterns = [
            r'Lecture\s+([M/T/W/Th/F/S]+)\s+(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})\s*(?:AM|PM)?',
            r'([M/T/W/Th/F/S]+)\s+(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})\s*(?:AM|PM)?',
            r'(?:Lecture|LEC|Class|Section)\s*(\d{3})?\s*[:\s]+([M/T/W/Th/F/S]+)\s+(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})',
            r'(?:Lecture|LEC)\s*([MTWThFS]+)\s+(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})',
        ]
        
        matches = []
        for pattern in schedule_patterns:
            for match in re.finditer(pattern, search_text, re.IGNORECASE):
                matches.append(match)
        
        for match in matches:
            # Handle different pattern groups
            groups = match.groups()
            try:
                if len(groups) == 6:  # First pattern with section ID
                    section_id = groups[0] or ""
                    days_str = groups[1]
                    start_hour = int(groups[2])
                    start_min = int(groups[3])
                    end_hour = int(groups[4])
                    end_min = int(groups[5])
                elif len(groups) == 4:  # Second/third pattern without section ID
                    section_id = ""
                    days_str = groups[0]
                    start_hour = int(groups[1])
                    start_min = int(groups[2])
                    end_hour = int(groups[3])
                    end_min = int(groups[4])
                else:
                    continue
                
                # Parse days of week
                days_of_week = self._parse_days_of_week(days_str)
                if not days_of_week:
                    continue  # Skip if we couldn't parse days
                
                # Determine AM/PM (simplified - may need refinement)
                start_time = time(start_hour % 24, start_min)
                end_time = time(end_hour % 24, end_min)
                
                section = SectionOption(
                    section_type="Lecture",
                    section_id=section_id,
                    days_of_week=days_of_week,
                    start_time=start_time,
                    end_time=end_time,
                    location=None  # Extract location if pattern found
                )
                sections.append(section)
            except (ValueError, IndexError) as e:
                # Skip matches that don't parse correctly
                continue
        
        return sections
    
    def extract_lab_sections(self) -> List[SectionOption]:
        """Extract lab section schedules using multi-pattern matching.
        
        Returns:
            List of SectionOption objects for labs (empty if course has no labs)
        """
        sections = []
        search_text = "\n".join([text for _, text in self.pages_text[:MAX_PAGES_TO_SEARCH]])
        
        # Try table-based extraction first
        table_sections = self._extract_schedule_from_tables("lab")
        if table_sections:
            return table_sections
        
        # Try text-based extraction
        text_sections = self._extract_schedule_from_text("lab", search_text)
        if text_sections:
            return text_sections
        
        # Legacy pattern matching (keeping existing logic as fallback)
        lab_patterns = [
            r'(?:Lab|LAB|Laboratory|Tutorial|TUT)\s*(\d{3})?\s*[:\s]+([M/T/W/Th/F/S]+)\s+(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})',
            r'(?:Lab|LAB|Laboratory|Tutorial|TUT)\s*([MTWThFS]+)\s+(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})',
        ]
        
        matches = []
        for pattern in lab_patterns:
            for match in re.finditer(pattern, search_text, re.IGNORECASE):
                matches.append(match)
        
        for match in matches:
            groups = match.groups()
            try:
                if len(groups) == 5:
                    section_id = groups[0] or ""
                    days_str = groups[1]
                    start_hour = int(groups[2])
                    start_min = int(groups[3])
                    end_hour = int(groups[4])
                    end_min = int(groups[5])
                elif len(groups) == 4:
                    section_id = ""
                    days_str = groups[0]
                    start_hour = int(groups[1])
                    start_min = int(groups[2])
                    end_hour = int(groups[3])
                    end_min = int(groups[4])
                else:
                    continue
                
                days_of_week = self._parse_days_of_week(days_str)
                if not days_of_week:
                    continue
                
                start_time = time(start_hour % 24, start_min)
                end_time = time(end_hour % 24, end_min)
                
                section = SectionOption(
                    section_type="Lab",
                    section_id=section_id,
                    days_of_week=days_of_week,
                    start_time=start_time,
                    end_time=end_time,
                    location=None
                )
                sections.append(section)
            except (ValueError, IndexError):
                continue
        
        return sections
    
    def extract_assessments(self) -> List[AssessmentTask]:
        """Extract assessment information from PDF.
        
        This function searches for the "Assessment and Evaluation" section and extracts
        assessment information from the table. It handles various formats including:
        - Table format with columns: Assessment, Format, Weight, Due Date, Flexibility
        - Multiple due dates (e.g., PeerWise assignments)
        - Date ranges (e.g., "December exam period")
        - Relative dates (e.g., "24 hours after lab")
        
        Returns:
            List of AssessmentTask objects with extracted information
        """
        assessments = []
        # Search entire PDF for assessments
        full_text = "\n".join([text for _, text in self.pages_text])
        
        # First, try structured table extraction using pdfplumber (most reliable for table-based PDFs)
        structured_assessments = self._extract_assessments_from_table_structured()
        if structured_assessments and len(structured_assessments) > 0:
            # Validate that we got meaningful assessments (not just empty ones)
            valid_assessments = [a for a in structured_assessments if a.title and len(a.title.strip()) > 2]
            if len(valid_assessments) > 0:
                assessments.extend(valid_assessments)
                # If we found valid assessments in structured table, return early (avoid duplicates)
                return assessments
        
        # Fallback to text-based table extraction
        table_assessments = self._extract_assessments_from_table(full_text)
        if table_assessments:
            assessments.extend(table_assessments)
            # If we found assessments in table, skip pattern matching (avoid duplicates)
            use_pattern_matching = False
        else:
            use_pattern_matching = True
        
        # Try text-based extraction (for PDFs with assessments in plain text like "Midterm 35%")
        if use_pattern_matching:
            text_assessments = self._extract_assessments_from_text_patterns(full_text)
            if text_assessments:
                assessments.extend(text_assessments)
                use_pattern_matching = False
        
        if use_pattern_matching:
            # Fallback to pattern matching if table extraction didn't work
            # Pattern for assessments with due dates
            assessment_patterns = [
                r'(Assignment|ASSIGNMENT|HW|Homework)\s+(\d+)[^\n]*(?:due|Due|DUE)[^\n]*?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\w+\s+\d{1,2},?\s+\d{4})',
                r'(Quiz|QUIZ|Test)\s+(\d+)[^\n]*(?:due|Due|DUE|on|On)[^\n]*?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\w+\s+\d{1,2},?\s+\d{4})',
                r'(Lab\s+Report|Laboratory\s+Report|Lab\s+Assignment)\s+(\d+)[^\n]*(?:due|Due|DUE)[^\n]*?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\w+\s+\d{1,2},?\s+\d{4})',
                r'(Final\s+Exam|FINAL|Final\s+Examination)[^\n]*?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\w+\s+\d{1,2},?\s+\d{4})',
                r'(Midterm|MIDTERM|Mid-term)[^\n]*?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\w+\s+\d{1,2},?\s+\d{4})',
            ]
            
            for pattern in assessment_patterns:
                matches = re.finditer(pattern, full_text, re.IGNORECASE)
                for match in matches:
                    groups = match.groups()
                    # Determine assessment type and title
                    if 'Quiz' in match.group(0):
                        assessment_type = 'quiz'
                        # Extract quiz number if available
                        quiz_num = groups[1] if len(groups) > 1 and groups[1].isdigit() else (groups[2] if len(groups) > 2 and groups[2].isdigit() else '')
                        title = f"Quiz {quiz_num}" if quiz_num else "Quiz"
                    elif 'Midterm' in match.group(0):
                        assessment_type = 'midterm'
                        title = "Midterm Exam"
                    elif 'Final' in match.group(0):
                        assessment_type = 'final'
                        title = "Final Exam"
                    elif 'Assignment' in match.group(0) or 'HW' in match.group(0):
                        assessment_type = 'assignment'
                        title = match.group(0)[:50]
                    else:
                        assessment_type = 'other'
                        title = match.group(0)[:50]
                    
                    # Try to extract due date - look for month and day in the match
                    due_date_str = None
                    # Check last groups for date info
                    for i in range(len(groups) - 1, -1, -1):
                        if groups[i] and (groups[i].isdigit() or any(month in groups[i] for month in ['Oct', 'Nov', 'Dec', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep'])):
                            # Try to construct date string
                            if i > 0 and groups[i-1]:
                                # Month name and day
                                due_date_str = f"{groups[i-1]} {groups[i]}, 2025"
                            elif groups[i].isdigit() and i > 0:
                                # Look for month before this group
                                context = match.group(0)[:match.start() + match.end()]
                                month_match = re.search(r'(Oct|Nov|Dec|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|September|October|November|December|January|February|March|April|May|June|July|August)', context, re.IGNORECASE)
                                if month_match:
                                    due_date_str = f"{month_match.group(0)} {groups[i]}, 2025"
                            break
                    
                    due_datetime = None
                    if due_date_str:
                        parsed_date = dateparser.parse(due_date_str)
                        if parsed_date:
                            # Default to 11:59 PM if no time specified
                            due_datetime = datetime.combine(
                                parsed_date.date(),
                                time(23, 59)
                            )
                    
                    # Try to extract weight from surrounding text
                    weight = self._extract_weight(match.group(0))
                    
                    assessment = AssessmentTask(
                        title=self._clean_assessment_title(title),
                        type=assessment_type,
                        weight_percent=weight,
                        due_datetime=due_datetime,
                        confidence=0.7 if due_datetime else 0.4,
                        source_evidence=f"Found: {match.group(0)[:100]}",
                        needs_review=(due_datetime is None or weight is None)
                    )
                    assessments.append(assessment)
        
        # Also search for relative rules
            relative_rules = self._extract_relative_rules(full_text)
            for rule_text, anchor in relative_rules:
                # Create assessment with rule
                assessment = AssessmentTask(
                    title=f"Assessment (rule: {rule_text[:30]})",
                    type="other",
                    due_rule=rule_text,
                    rule_anchor=anchor,
                    confidence=0.5,
                    source_evidence=f"Relative rule: {rule_text}",
                    needs_review=True
                )
                assessments.append(assessment)
        
        # Filter out unwanted assessments (e.g., those starting with "#" or other patterns)
        filtered_assessments = []
        excluded_patterns = [
            r'^#',  # Assessments starting with #
            r'^completion#?$',  # Just "Completion" or "Completion#"
            r'^#completion',  # "#Completion"
        ]
        
        for assessment in assessments:
            should_exclude = False
            title_lower = assessment.title.lower().strip()
            
            # Check against exclusion patterns
            for pattern in excluded_patterns:
                if re.match(pattern, title_lower, re.IGNORECASE):
                    should_exclude = True
                    break
            
            # Also exclude if title is just "#" or very short with special characters
            if len(title_lower) <= 2 and '#' in title_lower:
                should_exclude = True
            
            if not should_exclude:
                filtered_assessments.append(assessment)
        
        # Deduplicate: Remove assessments with same title but no date/weight if we have a better version
        # Normalize titles for comparison (remove "In Class", case-insensitive, extract core name)
        def normalize_title(title):
            # Remove common prefixes and normalize
            normalized = title.lower().strip()
            normalized = re.sub(r'^in\s+class\s+', '', normalized)
            normalized = re.sub(r'\s+', ' ', normalized)
            # Extract core: "quiz 1", "midterm test 1", "final exam"
            # Look for number anywhere after the type (not just immediately after)
            match = re.search(r'^(quiz|midterm|final|assignment|lab\s+report).*?(\d+)', normalized)
            if match:
                type_name = match.group(1)
                number = match.group(2)
                normalized = f"{type_name} {number}"
            else:
                # No number found, just extract the type
                normalized = re.sub(r'^(quiz|midterm|final|assignment|lab\s+report).*', r'\1', normalized).strip()
            return normalized
        
        seen_titles = {}
        deduplicated = []
        for assessment in filtered_assessments:
            title_normalized = normalize_title(assessment.title)
            # Check if we already have a better version (with date and weight)
            if title_normalized in seen_titles:
                existing = seen_titles[title_normalized]
                # Keep the one with date and weight, or higher confidence
                if (assessment.due_datetime and assessment.weight_percent and 
                    (not existing.due_datetime or not existing.weight_percent)):
                    # Replace existing with better one
                    deduplicated.remove(existing)
                    deduplicated.append(assessment)
                    seen_titles[title_normalized] = assessment
                elif assessment.confidence > existing.confidence:
                    # Replace with higher confidence
                    deduplicated.remove(existing)
                    deduplicated.append(assessment)
                    seen_titles[title_normalized] = assessment
                # Otherwise skip this duplicate
            else:
                seen_titles[title_normalized] = assessment
                deduplicated.append(assessment)
        
        return deduplicated
    
    def extract_course_info(self) -> Tuple[Optional[str], Optional[str]]:
        """Extract course code and name from the PDF.
        
        Returns:
            Tuple of (course_code, course_name). Both can be None if not found.
        """
        first_page = self.pages_text[0][1] if self.pages_text else ""
        
        course_code = None
        course_name = None
        
        # Extract course code - simple pattern matching
        code_pattern = r'([A-Z]{2,4})\s+(\d{3,4}[A-Z]?)'
        match = re.search(code_pattern, first_page)
        if match:
            dept = match.group(1)
            number = match.group(2)
            course_code = f"{dept} {number}"
        
        # For course name, look at first few lines
        # Course name is usually on the first page, often on line 1 or near the course code
        lines = first_page.split('\n')[:10]
        for i, line in enumerate(lines):
            line = line.strip()
            if len(line) < 5 or len(line) > 100:
                continue
            
            # Skip lines that are obviously not course names
            skip_patterns = ['university', 'www.', 'http', '@', 'email', 'phone', 'office', 
                           'instructor', 'department of', 'course outline', 'syllabus', 'winter', 
                           'fall', 'spring', 'summer', 'semester', r'20\d{2}']
            if any(re.search(pattern, line, re.IGNORECASE) for pattern in skip_patterns):
                continue
            
            # If line contains only letters, spaces, &, and is a reasonable length, it's likely the course name
            if re.match(r'^[A-Za-z\s&\-]+$', line) and len(line) > 8:
                course_name = line
                break
        
        return course_code, course_name
    
    def _extract_schedule_from_tables(self, section_type: str) -> List[SectionOption]:
        """Extract schedule from structured tables.
        
        Args:
            section_type: "lecture" or "lab"
            
        Returns:
            List of SectionOption objects
        """
        sections = []
        keywords = ["lecture", "lec", "class"] if section_type == "lecture" else ["lab", "laboratory", "tutorial", "tut"]
        
        with pdfplumber.open(self.pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages[:MAX_PAGES_TO_SEARCH], 1):
                tables = page.extract_tables()
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    
                    # Check each row for schedule info
                    for row in table:
                        row_text = ' '.join([str(c).lower() if c else '' for c in row])
                        
                        # Check if row contains our section type
                        if not any(kw in row_text for kw in keywords):
                            continue
                        
                        # Look for time pattern in the row
                        for cell in row:
                            if not cell:
                                continue
                            cell_text = str(cell)
                            parsed = self._parse_time_and_days_from_text(cell_text)
                            if parsed:
                                days, start_t, end_t = parsed
                                sections.append(SectionOption(
                                    section_type=section_type.capitalize(),
                                    section_id="",
                                    days_of_week=days,
                                    start_time=start_t,
                                    end_time=end_t,
                                    location=None
                                ))
        
        return sections
    
    def _extract_schedule_from_text(self, section_type: str, search_text: str) -> List[SectionOption]:
        """Extract schedule from text patterns.
        
        Args:
            section_type: "lecture" or "lab"
            search_text: Text to search in
            
        Returns:
            List of SectionOption objects
        """
        sections = []
        
        # Comprehensive patterns for schedule extraction
        patterns = [
            # "Mondays, 1:30 – 4:30 pm in SSC 3018"
            r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)s?[,\s]+(\d{1,2})[:.:](\d{2})\s*[-–]\s*(\d{1,2})[:.:](\d{2})\s*([ap]\.?m\.?)?(?:\s+in\s+([A-Z0-9\s]+))?',
            # "Lecture: Friday 1.30 pm-2.30 pm"
            r'(?:Lecture|Lab|Tutorial)[:\s]+([A-Za-z]+(?:day)?)\s+(\d{1,2})[\.:](\d{2})\s*([ap]\.?m\.?)?\s*[-–]\s*(\d{1,2})[\.:](\d{2})\s*([ap]\.?m\.?)?',
            # "Section 001: Tuesday, 1:30pm-4:30pm"
            r'Section\s*\d*[:\s]+([A-Za-z]+(?:day)?)[,\s]+(\d{1,2})[:.:](\d{2})\s*([ap]\.?m\.?)?\s*[-–]\s*(\d{1,2})[:.:](\d{2})\s*([ap]\.?m\.?)?',
        ]
        
        # Filter patterns by section type
        if section_type == "lecture":
            keyword_pattern = r'(?:lecture|lec|class)[\s:]+.*?(\d{1,2})[:.:](\d{2})\s*[-–]\s*(\d{1,2})[:.:](\d{2})'
        else:
            keyword_pattern = r'(?:lab|laboratory|tutorial)[\s:]+.*?(\d{1,2})[:.:](\d{2})\s*[-–]\s*(\d{1,2})[:.:](\d{2})'
        
        patterns.append(keyword_pattern)
        
        for pattern in patterns:
            for match in re.finditer(pattern, search_text, re.IGNORECASE):
                full_match = match.group(0)
                parsed = self._parse_time_and_days_from_text(full_match)
                if parsed:
                    days, start_t, end_t = parsed
                    sections.append(SectionOption(
                        section_type=section_type.capitalize(),
                        section_id="",
                        days_of_week=days,
                        start_time=start_t,
                        end_time=end_t,
                        location=None
                    ))
        
        # Deduplicate
        seen = set()
        unique = []
        for s in sections:
            key = (tuple(s.days_of_week), s.start_time, s.end_time)
            if key not in seen:
                seen.add(key)
                unique.append(s)
        
        return unique
    
    def _parse_time_and_days_from_text(self, text: str) -> Optional[Tuple[List[int], time, time]]:
        """Parse time and days from text.
        
        Args:
            text: Text containing time and day information
            
        Returns:
            Tuple of (days_list, start_time, end_time) or None
        """
        # Extract days
        days = []
        day_patterns = [
            (r'\b(Monday)s?\b', [0]),
            (r'\b(Tuesday)s?\b', [1]),
            (r'\b(Wednesday)s?\b', [2]),
            (r'\b(Thursday)s?\b', [3]),
            (r'\b(Friday)s?\b', [4]),
            (r'\b(Saturday)s?\b', [5]),
            (r'\b(Sunday)s?\b', [6]),
            (r'\b([MTWRF]{1,5})\b', None),  # MWF, TTh, etc.
        ]
        
        for pattern, fixed_days in day_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                if fixed_days:
                    days = fixed_days
                else:
                    days = self._parse_days_of_week(match.group(1))
                    break
        
        if not days:
            return None
        
        # Extract time
        time_pattern = r'(\d{1,2})[\.:](\d{2})\s*([ap]\.?m\.?)?\s*[-–]\s*(\d{1,2})[\.:](\d{2})\s*([ap]\.?m\.?)?'
        match = re.search(time_pattern, text, re.IGNORECASE)
        if not match:
            return None
        
        try:
            start_hour = int(match.group(1))
            start_min = int(match.group(2))
            start_ampm = match.group(3)
            end_hour = int(match.group(4))
            end_min = int(match.group(5))
            end_ampm = match.group(6)
            
            # Adjust for AM/PM
            if start_ampm and 'p' in start_ampm.lower() and start_hour < 12:
                start_hour += 12
            if end_ampm and 'p' in end_ampm.lower() and end_hour < 12:
                end_hour += 12
            elif not end_ampm and start_ampm and 'p' in start_ampm.lower() and end_hour < 12:
                end_hour += 12
            
            return (days, time(start_hour % 24, start_min), time(end_hour % 24, end_min))
        except (ValueError, IndexError):
            return None
    
    def _extract_assessments_from_text_patterns(self, text: str) -> List[AssessmentTask]:
        """Extract assessments from plain text format.
        
        Handles formats like:
        - "Midterm Test 35%"
        - "Final Exam 45%"
        - "Quizzes... 20%"
        
        Args:
            text: Full text of the PDF
            
        Returns:
            List of AssessmentTask objects
        """
        assessments = []
        
        # Find assessment/evaluation section
        section_patterns = [
            r'(?:Methods\s+of\s+)?Evaluation\b',
            r'Assessment\s+(?:and\s+)?Evaluation',
            r'Grading\s+Scheme',
            r'Grade\s+Breakdown',
            r'Mark\s+Breakdown',
            r'Course\s+Evaluation',
        ]
        
        section_start = -1
        for pattern in section_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                section_start = match.start()
                break
        
        if section_start == -1:
            return []
        
        # Extract the section (next ~5000 chars)
        section_text = text[section_start:section_start + 5000]
        lines = section_text.split('\n')
        
        # Assessment keywords
        assessment_keywords = [
            'quiz', 'midterm', 'final', 'exam', 'test', 'assignment', 'project',
            'lab', 'report', 'essay', 'presentation', 'participation', 'homework',
            'peerwise', 'pcb', 'bonus'
        ]
        
        # Look for lines with percentages or standalone numbers (in % of total grade context)
        for line in lines[:60]:
            if len(line.strip()) < 5 or len(line.strip()) > 200:
                continue
            
            # Check for percentage pattern (with or without % sign)
            weight_match = re.search(r'(\d+(?:\.\d+)?)\s*%', line)
            weight = None
            
            if weight_match:
                weight = float(weight_match.group(1))
            else:
                # Look for standalone numbers at end of line (common in grade tables)
                number_match = re.search(r'\s(\d{1,2}(?:\.\d+)?)\s*$', line.strip())
                if number_match:
                    potential_weight = float(number_match.group(1))
                    if 5 <= potential_weight <= 60:  # Reasonable weight range
                        weight = potential_weight
                        weight_match = number_match
            
            if weight is None:
                continue
            
            # Skip if weight is too high (likely not a percentage)
            if weight > 60:
                continue
            
            # Check if line contains assessment keywords
            line_lower = line.lower()
            if not any(kw in line_lower for kw in assessment_keywords):
                continue
            
            # Extract assessment name
            if weight_match:
                name_text = line[:weight_match.start()].strip()
            else:
                name_text = line.strip()
            name_text = re.sub(r'^[\s\-•·]+', '', name_text)
            name_text = re.sub(r'\([^)]*\)$', '', name_text).strip()
            name_text = re.sub(r'\s+\d+$', '', name_text).strip()  # Remove trailing number
            
            # CRITICAL FILTERS for false positives
            # Skip if name is too short or too long
            if len(name_text) < 3 or len(name_text) > 80:
                continue
            
            # Skip policy/requirement text patterns
            policy_patterns = [
                r'^to be eligible',
                r'^to obtain',
                r'^at least (a|an|\d)',
                r'^you must',
                r'^students must',
                r'^a (minimum|final|passing|grade)',
                r'^the (minimum|final|passing)',
                r'^will be reweighted',
                r'^there (is|are|will)',
                r'^each is worth',
                r'result in',
                r'weighted average',
                r'^obtain a',
                r'^achieve',
                r'a mark of',
                r'a grade of',
            ]
            if any(re.match(pattern, name_text.lower()) for pattern in policy_patterns):
                continue
            
            # Skip if it looks like a sentence fragment (starts with lowercase)
            if name_text and name_text[0].islower():
                continue
            
            # Skip if it contains verbs that indicate it's not an assessment title
            sentence_indicators = ['is', 'are', 'will be', 'must', 'should', 'may', 'can']
            if any(f' {word} ' in name_text.lower() for word in sentence_indicators):
                continue
            
            # Determine assessment type
            if 'quiz' in line_lower:
                atype = 'quiz'
            elif 'midterm' in line_lower or 'mid-term' in line_lower:
                atype = 'midterm'
            elif 'final' in line_lower and 'exam' in line_lower:
                atype = 'final'
            elif 'exam' in line_lower or 'test' in line_lower:
                atype = 'midterm'
            else:
                atype = 'other'
            
            # Try to extract due date
            due_datetime = self._parse_date_from_text(line)
            
            assessment = AssessmentTask(
                title=self._clean_assessment_title(name_text[:80]),
                type=atype,
                weight_percent=weight,
                due_datetime=due_datetime,
                due_rule=None,
                confidence=0.7,
                source_evidence=f"Text: {line[:50]}..."
            )
            assessments.append(assessment)
        
        # Deduplicate
        seen = set()
        unique = []
        for a in assessments:
            key = a.title.lower().strip()
            if key not in seen:
                seen.add(key)
                unique.append(a)
        
        return unique
    
    def _parse_days_of_week(self, days_str: str) -> List[int]:
        """Parse day abbreviations from text like "MWF" or "TTh".
        
        This function converts day abbreviations (like "MWF" for Monday/Wednesday/Friday)
        into a list of weekday numbers. The numbers follow Python's weekday convention:
        0 = Monday, 1 = Tuesday, 2 = Wednesday, 3 = Thursday, 4 = Friday, 5 = Saturday, 6 = Sunday.
        
        Args:
            days_str: String containing day abbreviations (e.g., "MWF", "TTh", "Mon/Wed/Fri")
        
        Returns:
            List of weekday numbers (0=Monday, 6=Sunday), sorted and with duplicates removed.
            Example: "MWF" returns [0, 2, 4]
        """
        # Map of day abbreviations to weekday numbers
        # Python uses 0=Monday, 1=Tuesday, etc.
        day_map = {
            'M': 0, 'Mon': 0, 'Monday': 0,
            'T': 1, 'Tue': 1, 'Tuesday': 1,
            'W': 2, 'Wed': 2, 'Wednesday': 2,
            'Th': 3, 'Thu': 3, 'Thursday': 3,
            'F': 4, 'Fri': 4, 'Friday': 4,
            'S': 5, 'Sat': 5, 'Saturday': 5,
            'Su': 6, 'Sun': 6, 'Sunday': 6,
        }
        
        days = []
        days_str_upper = days_str.upper()  # Convert to uppercase for case-insensitive matching
        
        # Handle common patterns found in course outlines
        # Check for Monday (M) - but make sure it's not part of "MT" or "MW"
        if 'M' in days_str_upper and days_str_upper.index('M') < len(days_str_upper) - 1:
            # Make sure the next character isn't 'T' (which would be part of "MT" or "MW")
            if days_str_upper[days_str_upper.index('M') + 1] != 'T':
                days.append(0)  # Monday
        
        # Check for Tuesday (T) or Thursday (TH)
        if 'T' in days_str_upper:
            idx = days_str_upper.index('T')
            # If next character is 'H', it's Thursday
            if idx + 1 < len(days_str_upper) and days_str_upper[idx + 1] == 'H':
                days.append(3)  # Thursday
            else:
                days.append(1)  # Tuesday
        
        # Check for Wednesday (W)
        if 'W' in days_str_upper:
            days.append(2)  # Wednesday
        
        # Check for Thursday (TH or THU) - in case it wasn't caught above
        if 'TH' in days_str_upper or 'THU' in days_str_upper:
            days.append(3)  # Thursday
        
        # Check for Friday (F)
        if 'F' in days_str_upper:
            days.append(4)  # Friday
        
        # Remove duplicates and sort the list
        # This ensures we return a clean, sorted list like [0, 2, 4] for "MWF"
        return sorted(list(set(days)))
    
    def _extract_assessments_from_table(self, text: str) -> List[AssessmentTask]:
        """Extract assessments from the assessment table in the PDF.
        
        Looks for the "Assessment and Evaluation" section and parses the table
        with columns: Assessment, Format, Weight, Due Date, Flexibility.
        
        Args:
            text: Full text of the PDF
            
        Returns:
            List of AssessmentTask objects extracted from the table
        """
        assessments = []
        
        # Find the assessment section - look for "Assessment and Evaluation" title
        # Try multiple patterns to find the section
        assessment_section_patterns = [
            r'(?:8\.\s*)?Assessment\s+(?:and\s+)?Evaluation[^\n]*(?:\n[^\n]*){0,500}',  # More lines after title
            r'Assessment\s+(?:and\s+)?Evaluation\s+Policy[^\n]*(?:\n[^\n]*){0,500}',
            r'Assessment\s+(?:and\s+)?Evaluation[^\n]*(?:\n[^\n]*){0,1000}',  # Even more lines
        ]
        
        section_text = None
        for pattern in assessment_section_patterns:
            section_match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if section_match:
                section_text = section_match.group(0)
                # Find where the section ends (next major section or end of document)
                # Look for next numbered section or major heading
                next_section_match = re.search(r'\n(?:\d+\.\s+)?(?:Course|Instructor|Textbook|Schedule|Policies|Grading|Contact|Information|General|Appendix)', section_text, re.IGNORECASE)
                if next_section_match:
                    section_text = section_text[:next_section_match.start()]
                break
        
        if not section_text:
            # Fallback: search for any mention of assessment table
            assessment_mentions = re.finditer(r'Assessment[^\n]*(?:\n[^\n]*){0,200}', text, re.IGNORECASE)
            for match in assessment_mentions:
                if 'weight' in match.group(0).lower() or 'due' in match.group(0).lower():
                    section_text = match.group(0)
                    break
        
        if not section_text:
            return assessments
        
        # Look for table header: "Assessment Format Weight Due Date Flexibility"
        header_pattern = r'Assessment\s+(?:Format\s+)?(?:Weight|Weighting)\s+(?:Due\s+)?Date\s*(?:Flexibility)?'
        header_match = re.search(header_pattern, section_text, re.IGNORECASE)
        
        if not header_match:
            # Try alternative header patterns
            header_pattern = r'Assessment\s+Format\s+Weight'
            header_match = re.search(header_pattern, section_text, re.IGNORECASE)
        
        if not header_match:
            return assessments
        
        # Extract text after header (the table rows)
        table_start = header_match.end()
        # Extract more text to capture all assessments (up to 5000 chars)
        table_text = section_text[table_start:table_start+5000]  # Increased limit
        
        # Split table text into lines and process row by row
        # Look for assessment rows - each assessment typically starts with a name
        # Filter out empty/short lines to avoid index issues
        all_lines = table_text.split('\n')
        lines = [l.strip() for l in all_lines if l.strip() and len(l.strip()) >= 3]
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Stop processing if we hit the "Designated Assessment" section - this is informational, not an assessment
            if re.match(r'^Designated\s+Assessment', line, re.IGNORECASE):
                break
            
            # Skip lines that are bullet points (informational sections, not assessments)
            if line.strip().startswith('•') or line.strip().startswith('-'):
                i += 1
                continue
            
            # Check if this line starts an assessment - handle multi-line names
            assessment_name_match = None
            assessment_name = None
            
            # IMPORTANT: Check for Midterm Test FIRST, before other patterns
            # This ensures Midterm Tests are caught even if they appear in unexpected positions
            # Handle both "Midterm Test 1" (with number) and "Midterm Test" (without number)
            if 'Midterm' in line and 'Test' in line:
                match = re.search(r'Midterm\s+(?:Test|TEST)\s+(\d+)', line, re.IGNORECASE)
                if match:
                    midterm_num = match.group(1)
                    assessment_name = f"Midterm Test {midterm_num}"
                    row_lines = [line]
                    j = i + 1
                else:
                    # Try alternative pattern - maybe "Midterm" and number are separated
                    # BUT: Exclude numbers in parentheses like "(2 hrs)" - those are durations, not test numbers
                    # Look for "Midterm Test" followed by a number that's NOT in parentheses
                    alt_match = re.search(r'Midterm\s+(?:Test|TEST)\s+(\d+)', line, re.IGNORECASE)
                    if alt_match:
                        # Check if this number is in parentheses (like "(2 hrs)")
                        num_pos = alt_match.start(1)
                        # Look backwards to see if there's an opening parenthesis before the number
                        before_num = line[:num_pos]
                        if '(' in before_num and ')' not in before_num[:before_num.rfind('(')+1]:
                            # Number is in parentheses - this is a duration, not a test number
                            # Treat as "Midterm Test" without number
                            if re.search(r'Midterm\s+(?:Test|TEST)(?:\s|\(|,|$)', line, re.IGNORECASE):
                                assessment_name = "Midterm Test"
                                row_lines = [line]
                                j = i + 1
                            else:
                                i += 1
                                continue
                        else:
                            midterm_num = alt_match.group(1)
                            assessment_name = f"Midterm Test {midterm_num}"
                            row_lines = [line]
                            j = i + 1
                    else:
                        # No number found - this is just "Midterm Test" (common case)
                        # Check that it's actually "Midterm Test" and not just "Midterm" in another context
                        if re.search(r'Midterm\s+(?:Test|TEST)(?:\s|\(|,|$)', line, re.IGNORECASE):
                            assessment_name = "Midterm Test"
                            row_lines = [line]
                            j = i + 1
                        else:
                            i += 1
                            continue
            
            # First, check if this line starts with "PeerWise" - collect more lines for dates
            elif re.match(r'^PeerWise', line, re.IGNORECASE):
                # Look ahead to next line for "Assignment X"
                if i + 1 < len(lines):
                    next_line = lines[i + 1]  # Already stripped in filtered lines
                    assign_match = re.search(r'Assignment\s+(\d+)', next_line, re.IGNORECASE)
                    if assign_match:
                        assessment_name = f"PeerWise Assignment {assign_match.group(1)}"
                        # Include next line in row_lines
                        row_lines = [line, next_line]
                        i += 1  # Skip next line since we're including it
                        j = i + 1  # Start collecting from line after that
                    else:
                        # Just "PeerWise" without assignment number
                        assessment_name = "PeerWise Assignment"
                        row_lines = [line]
                        j = i + 1
                else:
                    assessment_name = "PeerWise Assignment"
                    row_lines = [line]
                    j = i + 1
                
                # For PeerWise, collect more lines to capture all date information
                # PeerWise dates are often split across multiple lines
                while j < len(lines) and j < i + 8:  # Collect up to 8 more lines for PeerWise
                    next_line = lines[j]
                    # Stop if we hit another assessment
                    if re.match(r'^(?:Midterm|Final|Assignment\s+\d+|PeerWise|Optional|Designated)', next_line, re.IGNORECASE):
                        break
                    # Stop if we've collected enough date information (both Author and Answer dates)
                    if 'by 11:59 PM' in ' '.join(row_lines).lower() and 'feedback' in ' '.join(row_lines).lower():
                        # Check if we have both dates
                        if re.search(r'Author.*?(\w+\.?\s+\w+\.?\s+\d+)', ' '.join(row_lines), re.IGNORECASE) and \
                           re.search(r'feedback.*?(\w+\.?\s+\w+\.?\s+\d+)', ' '.join(row_lines), re.IGNORECASE):
                            break
                    row_lines.append(next_line)
                    j += 1
            
            # Check for "Assignment X Slide redesign" - might be split
            # BUT: Skip if this is part of a PeerWise description (already handled above)
            elif re.match(r'^Assignment\s+(\d+)', line, re.IGNORECASE) and not any('peerwise' in prev_line.lower() for prev_line in lines[max(0, i-2):i]):
                assign_num_match = re.match(r'^Assignment\s+(\d+)', line, re.IGNORECASE)
                assign_num = assign_num_match.group(1) if assign_num_match else None
                
                # Check if next line has "Slide redesign"
                if i + 1 < len(lines):
                    next_line = lines[i + 1]  # Already stripped
                    if 'slide redesign' in next_line.lower():
                        if 'teach' in next_line.lower():
                            assessment_name = f"Assignment {assign_num} Slide redesign & Teach"
                        else:
                            assessment_name = f"Assignment {assign_num} Slide redesign"
                        row_lines = [line, next_line]
                        i += 1
                        j = i + 1
                    else:
                        # Just "Assignment X" - might be PeerWise (already handled above) or other
                        assessment_name = f"Assignment {assign_num}"
                        row_lines = [line]
                        j = i + 1
                else:
                    assessment_name = f"Assignment {assign_num}"
                    row_lines = [line]
                    j = i + 1
            
            # Check for other patterns - Midterm Test (can appear anywhere in line, not just start)
            # Make this check more robust - check if line contains "Midterm Test" followed by a number
            elif 'Midterm' in line and 'Test' in line:
                match = re.search(r'Midterm\s+(?:Test|TEST)\s+(\d+)', line, re.IGNORECASE)
                if match:
                    midterm_num = match.group(1)
                    assessment_name = f"Midterm Test {midterm_num}"
                    row_lines = [line]
                    j = i + 1
                else:
                    # Try alternative pattern - maybe "Midterm" and number are separated
                    # BUT: Exclude numbers in parentheses like "(2 hrs)" - those are durations, not test numbers
                    # Look for "Midterm Test" followed by a number that's NOT in parentheses
                    alt_match = re.search(r'Midterm\s+(?:Test|TEST)\s+(\d+)', line, re.IGNORECASE)
                    if alt_match:
                        midterm_num = alt_match.group(1)
                        assessment_name = f"Midterm Test {midterm_num}"
                        row_lines = [line]
                        j = i + 1
                    else:
                        # Check if there's a number after "Midterm Test" but not in parentheses
                        # Pattern: "Midterm Test" followed by optional whitespace, then a number NOT preceded by "("
                        alt_match2 = re.search(r'Midterm\s+(?:Test|TEST)(?:\s+)(\d+)(?!\s*hrs?|hours?)', line, re.IGNORECASE)
                        if alt_match2 and not re.search(r'Midterm\s+(?:Test|TEST)\s*\(', line, re.IGNORECASE):
                            midterm_num = alt_match2.group(1)
                            assessment_name = f"Midterm Test {midterm_num}"
                            row_lines = [line]
                            j = i + 1
                        else:
                            # No number found - this is just "Midterm Test" (common case)
                            # Check that it's actually "Midterm Test" and not just "Midterm" in another context
                            if re.search(r'Midterm\s+(?:Test|TEST)(?:\s|\(|,|$)', line, re.IGNORECASE):
                                assessment_name = "Midterm Test"
                                row_lines = [line]
                                j = i + 1
                            else:
                                i += 1
                                continue
            
            elif re.match(r'^Final\s+(?:Exam|EXAM)', line, re.IGNORECASE):
                assessment_name = "Final Exam"
                row_lines = [line]
                j = i + 1
            
            elif re.match(r'^(?:Optional\s+)?(?:Bonus|BONUS)', line, re.IGNORECASE):
                assessment_name = "Optional Bonus Assignment"
                row_lines = [line]
                j = i + 1
            
            # Fallback to general pattern
            else:
                general_match = re.search(r'((?:In\s+Class\s+)?(?:Quiz|QUIZ)\s+\d+|(?:Midterm|MIDTERM|Mid-term)\s+(?:Test|Exam)?\s*\d*|(?:Final\s+)?(?:Exam|EXAM|Examination)|(?:Assignment|ASSIGNMENT)\s+\d+|(?:PeerWise|Peerwise)\s+(?:Assignment|ASSIGNMENT)\s+\d+|(?:Lab\s+)?(?:Report|REPORT)|(?:Slide\s+)?(?:redesign|Redesign)(?:\s+&\s+Teach)?|(?:Participation|Participation\s+Grade)|(?:Project|PROJECT)|(?:Presentation|PRESENTATION)|(?:Paper|PAPER)|(?:Essay|ESSAY)|(?:Reflection|REFLECTION)|(?:Optional\s+)?(?:Bonus|BONUS)\s+(?:Assignment|ASSIGNMENT)?)', line, re.IGNORECASE)
                if general_match:
                    assessment_name_match = general_match
                    assessment_name = general_match.group(1)
                    row_lines = [line]
                    j = i + 1
                else:
                    i += 1
                    continue
            
            if assessment_name:
                # Found an assessment - collect continuation lines (if not already done above)
                if 'row_lines' not in locals() or 'j' not in locals():
                    row_lines = [line]
                    j = i + 1
                
                # Collect continuation lines (up to 10 more lines to capture multi-line entries)
                while j < len(lines) and j < i + 11:
                    next_line = lines[j]  # Already stripped in filtered array
                    # Stop if we hit another assessment or section header
                    # Be more specific: only stop if it's clearly a new assessment (not part of description)
                    # Check for assessment names at start of line, or section headers
                    stop_patterns = [
                        r'^(?:In\s+Class\s+)?(?:Quiz|QUIZ)\s+\d+',  # Quiz 1, Quiz 2, etc.
                        r'^Midterm\s+(?:Test|TEST)(?:\s+\d+)?',  # Midterm Test 1, Midterm Test 2, or just Midterm Test
                        r'^(?:Final\s+)?(?:Exam|EXAM)',  # Final Exam
                        r'^PeerWise',  # New PeerWise assignment
                        r'^Assignment\s+\d+\s+(?:Slide|Augment)',  # Assignment X Slide redesign (new assessment)
                        r'^(?:Optional\s+)?(?:Bonus|BONUS)',  # Optional Bonus
                        r'^Designated',  # Section header
                        r'^Information',  # Section header
                        r'^General',  # Section header
                    ]
                    should_stop = False
                    for pattern in stop_patterns:
                        if re.match(pattern, next_line, re.IGNORECASE):
                            should_stop = True
                            break
                    
                    if should_stop:
                        # Don't include this line in row_lines, but j now points to it
                        # This ensures the next iteration will process this line
                        # BUT: Make sure we don't skip the line - the while loop will increment i
                        # Actually, we need to make sure i gets set correctly after processing
                        break
                    
                    if next_line and len(next_line) > 3:
                        row_lines.append(next_line)
                    j += 1
                
                row_text = ' '.join(row_lines)
                
                # Classify type
                assessment_type = self._classify_assessment_type(assessment_name)
                
                # Extract weight
                weight = self._extract_weight(row_text)
                
                # Extract due date(s)
                due_dates = []
                # For PeerWise assignments, look for "Author:" and "Answer and provide feedback:" dates
                if 'peerwise' in assessment_name.lower():
                    # Pattern for PeerWise dates: "Author: Mon, Oct. 27th by 11:59 PM" and "feedback: Wed, Oct. 29th by 11:59 PM"
                    # Handle abbreviated day names (Mon, Tue, Wed, Thu, Fri, Sat, Sun) and abbreviated months (Oct., Jan., etc.)
                    peerwise_patterns = [
                        r'Author:?\s*(?:Mon|Monday|Tue|Tuesday|Wed|Wednesday|Thu|Thursday|Fri|Friday|Sat|Saturday|Sun|Sunday),?\s+(Oct|Nov|Dec|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|September|October|November|December|January|February|March|April|May|June|July|August)\.?\s+(\d{1,2})(?:st|nd|rd|th)?',
                        r'feedback:?\s*(?:Mon|Monday|Tue|Tuesday|Wed|Wednesday|Thu|Thursday|Fri|Friday|Sat|Saturday|Sun|Sunday),?\s+(Oct|Nov|Dec|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|September|October|November|December|January|February|March|April|May|June|July|August)\.?\s+(\d{1,2})(?:st|nd|rd|th)?',
                    ]
                    
                    for pattern in peerwise_patterns:
                        date_matches = re.finditer(pattern, row_text, re.IGNORECASE)
                        for date_match in date_matches:
                            if len(date_match.groups()) == 2:
                                month = date_match.group(1)
                                day = date_match.group(2)
                                
                                # Determine year based on month
                                year = 2025
                                if any(m in month.lower() for m in ['jan', 'feb', 'mar', 'apr']):
                                    year = 2026
                                elif month.lower() in ['october', 'oct', 'november', 'nov', 'december', 'dec']:
                                    year = 2025
                                
                                date_str = f"{month} {day}, {year}"
                                # Avoid duplicates
                                if date_str not in due_dates:
                                    due_dates.append(date_str)
                
                # General date patterns for other assessments
                if not due_dates:
                    # Pattern for dates: "October 1", "Oct 1", "November 14th", "Sunday, Oct 19", "December exam period"
                    # Handle ordinal suffixes (st, nd, rd, th) by making them optional
                    date_patterns = [
                        r'(?:Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday),?\s+(Oct|Nov|Dec|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|September|October|November|December|January|February|March|April|May|June|July|August)\.?\s+(\d{1,2})(?:st|nd|rd|th)?',
                        r'(Oct|Nov|Dec|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|September|October|November|December|January|February|March|April|May|June|July|August)\.?\s+(\d{1,2})(?:st|nd|rd|th)?',
                    ]
                
                    for date_pattern in date_patterns:
                        date_matches = re.finditer(date_pattern, row_text, re.IGNORECASE)
                        for date_match in date_matches:
                            if len(date_match.groups()) == 2:
                                month = date_match.group(1)
                                day = date_match.group(2)
                                
                                # Determine year
                                year = 2025
                                if '2026' in row_text or any(m in row_text.lower() for m in ['january', 'february', 'march', 'april', 'jan', 'feb', 'mar', 'apr']):
                                    year = 2026
                                
                                date_str = f"{month} {day}, {year}"
                                # Avoid duplicates
                                if date_str not in due_dates:
                                    due_dates.append(date_str)
                
                # Handle "December exam period" or date ranges
                if not due_dates and ('exam period' in row_text.lower() or ('december' in row_text.lower() and 'exam' in row_text.lower())):
                    # For final exam, use a placeholder date that will be resolved later
                    due_dates.append("December 15, 2025")  # Default, will be refined
                
                # Extract time if present
                # For PeerWise, times are usually "11:59 PM" and appear after each date
                time_str = None
                if 'peerwise' in assessment_name.lower():
                    # Look for "by 11:59 PM" pattern (common for PeerWise)
                    time_match = re.search(r'by\s+(\d{1,2})(?:[:–-](\d{2}))?\s*(AM|PM)', row_text, re.IGNORECASE)
                    if time_match:
                        time_str = time_match.group(0)
                else:
                    # Look for time patterns: "6-8 PM", "11:59 PM", "in class"
                    time_match = re.search(r'(\d{1,2})(?:[:–-](\d{2}))?\s*(?:[-–]\s*(\d{1,2})(?:[:–-](\d{2}))?)?\s*(AM|PM)', row_text, re.IGNORECASE)
                    if time_match:
                        time_str = time_match.group(0)
                    elif 'in class' in row_text.lower():
                        time_str = 'in class'
                
                # Create assessment(s) - handle multiple due dates (e.g., PeerWise)
                if due_dates:
                    # For PeerWise assignments, use the later date (Answer date) as the primary due date
                    # This represents when the assignment is fully complete
                    if 'peerwise' in assessment_name.lower() and len(due_dates) > 1:
                        # Use the last date (Answer/Feedback date) as the primary due date
                        due_date_str = due_dates[-1]
                        parsed_date = dateparser.parse(due_date_str)
                        if parsed_date:
                            # Extract time for the Answer/Feedback date
                            hour = 23
                            minute = 59
                            feedback_time_match = re.search(r'feedback:?[^.]*?by\s+(\d{1,2})(?:[:–-](\d{2}))?\s*(AM|PM)', row_text, re.IGNORECASE)
                            if feedback_time_match:
                                hour = int(feedback_time_match.group(1))
                                minute = int(feedback_time_match.group(2)) if feedback_time_match.group(2) else 59
                                if feedback_time_match.group(3).upper() == 'PM' and hour != 12:
                                    hour += 12
                                elif feedback_time_match.group(3).upper() == 'AM' and hour == 12:
                                    hour = 0
                            
                            due_datetime = datetime.combine(parsed_date.date(), time(hour, minute))
                            
                            # Create single assessment with the Answer date
                            assessment = AssessmentTask(
                                title=self._clean_assessment_title(assessment_name),
                                type=assessment_type,
                                weight_percent=weight,
                                due_datetime=due_datetime,
                                confidence=0.8 if weight and due_datetime else 0.5,
                                source_evidence=row_text[:200],
                                needs_review=(due_datetime is None or weight is None)
                            )
                            assessments.append(assessment)
                    else:
                        # For non-PeerWise or single-date assessments, process normally
                        for date_idx, due_date_str in enumerate(due_dates[:2]):  # Limit to 2 dates per assessment
                            parsed_date = dateparser.parse(due_date_str)
                            if parsed_date:
                                # Handle time
                                hour = 23
                                minute = 59
                                if time_str:
                                    if 'in class' in time_str.lower():
                                        hour = 10
                                        minute = 0
                                    else:
                                        time_match = re.search(r'(\d{1,2})(?:[:–-](\d{2}))?\s*(AM|PM)', time_str, re.IGNORECASE)
                                        if time_match:
                                            hour = int(time_match.group(1))
                                            minute = int(time_match.group(2)) if time_match.group(2) else 0
                                            if time_match.group(3).upper() == 'PM' and hour != 12:
                                                hour += 12
                                            elif time_match.group(3).upper() == 'AM' and hour == 12:
                                                hour = 0
                                
                                due_datetime = datetime.combine(parsed_date.date(), time(hour, minute))
                                
                                assessment = AssessmentTask(
                                    title=self._clean_assessment_title(assessment_name),
                                    type=assessment_type,
                                    weight_percent=weight,
                                    due_datetime=due_datetime,
                                    confidence=0.8 if weight and due_datetime else 0.5,
                                    source_evidence=row_text[:200],
                                    needs_review=(due_datetime is None or weight is None)
                                )
                                assessments.append(assessment)
                else:
                    # If no dates found, still create assessment without date
                    assessment = AssessmentTask(
                        title=self._clean_assessment_title(assessment_name),
                        type=assessment_type,
                        weight_percent=weight,
                        due_datetime=None,
                        confidence=0.4,
                        source_evidence=row_text[:200],
                        needs_review=True
                    )
                    assessments.append(assessment)
                
                # Move to next potential assessment
                i = j
            else:
                i += 1
        
        return assessments
    
    def _classify_assessment_type(self, text: str) -> str:
        """Classify assessment type from text."""
        text_lower = text.lower()
        if "assignment" in text_lower or "hw" in text_lower or "homework" in text_lower:
            return "assignment"
        elif "lab report" in text_lower or "laboratory report" in text_lower:
            return "lab_report"
        elif "quiz" in text_lower:
            return "quiz"
        elif "midterm" in text_lower or "mid-term" in text_lower:
            return "midterm"
        elif "final" in text_lower:
            return "final"
        elif "project" in text_lower:
            return "project"
        else:
            return "other"
    
    def _extract_weight(self, text: str) -> Optional[float]:
        """Extract weight percentage from text."""
        weight_pattern = r'(\d+(?:\.\d+)?)\s*%'
        match = re.search(weight_pattern, text)
        if match:
            return float(match.group(1))
        return None
    
    def _extract_relative_rules(self, text: str) -> List[Tuple[str, str]]:
        """Extract relative deadline rules.
        
        Returns:
            List of (rule_text, anchor) tuples
        """
        rules = []
        
        # Pattern for relative rules
        rule_patterns = [
            (r'due\s+(\d+)\s+hours?\s+after\s+(the\s+)?(lab|tutorial|lecture)', 'hours'),
            (r'due\s+(\d+)\s+days?\s+after\s+(the\s+)?(lab|tutorial|lecture)', 'days'),
            (r'due\s+(\d+)\s+weeks?\s+after\s+(the\s+)?(lab|tutorial|lecture)', 'weeks'),
        ]
        
        for pattern, unit in rule_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                anchor = match.group(-1)  # lab, tutorial, or lecture
                rule_text = match.group(0)
                rules.append((rule_text, anchor))
        
        return rules
    
    def _extract_assessments_from_table_structured(self) -> List[AssessmentTask]:
        """Extract assessments from structured tables using pdfplumber.
        
        This method uses pdfplumber's table extraction to get structured data,
        which is more reliable than text parsing for table-based PDFs.
        
        Returns:
            List of AssessmentTask objects extracted from tables
        """
        assessments = []
        
        with pdfplumber.open(self.pdf_path) as pdf:
            # Find pages that might contain assessment tables
            # Usually in the middle-to-end of the document (pages 4-12 typically)
            # But check all pages to be thorough
            for page_num, page in enumerate(pdf.pages, 1):
                tables = page.extract_tables()
                
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    
                    # Check if this is an assessment table
                    if self._is_assessment_table(table):
                        # Extract assessments from this table
                        table_assessments = self._extract_from_table(table)
                        if table_assessments:
                            assessments.extend(table_assessments)
                            # Continue searching in case there are multiple assessment tables
                            # (some PDFs split assessments across pages)
        
        return assessments
    
    def _is_assessment_table(self, table: List[List]) -> bool:
        """Check if a table is an assessment/evaluation table.
        
        This function recognizes multiple formats:
        - Tables with "Assessment" in header (original format)
        - Tables with "Evaluation" context (ECE format)
        - Tables with weight/date columns even without explicit keywords
        
        Args:
            table: List of rows, where each row is a list of cells
            
        Returns:
            True if this appears to be an assessment table
        """
        if not table or len(table) < 2:
            return False
        
        # Check header row
        header_row = table[0]
        header_text = ' '.join([str(cell) for cell in header_row if cell]).lower()
        
        # Check for assessment/evaluation keywords OR name column with weight/date
        has_assessment_keyword = 'assessment' in header_text
        has_evaluation_keyword = 'evaluation' in header_text
        has_name_column = any('name' in str(cell).lower() for cell in header_row if cell)
        
        # Must have weight/percentage indicator
        has_weight = any(w in header_text for w in ['weight', 'weighting', '%', 'percent', '% worth', 'worth'])
        
        # Must have date/due indicator OR "assigned" column (some formats use "Assigned" for dates)
        has_date = any(d in header_text for d in ['due', 'date', 'deadline', 'assigned'])
        
        # For evaluation format: name + weight + date is sufficient (no keyword needed in header)
        # This handles ECE format where "Evaluation" is the section title, not in table header
        if has_name_column and has_weight and has_date:
            # Additional validation: check data rows for assessment content
            assessment_keywords = ['quiz', 'midterm', 'final', 'assignment', 'exam', 'report', 'lab', 'peerwise', 'project', 'pcb', 'labs', 'examination']
            keyword_count = 0
            percentage_count = 0
            
            for row in table[1:min(6, len(table))]:  # Check first 5 data rows
                row_text = ' '.join([str(cell) for cell in row if cell]).lower()
                if any(kw in row_text for kw in assessment_keywords):
                    keyword_count += 1
                # Check for percentage patterns
                if re.search(r'\d+\.?\d*%', row_text):
                    percentage_count += 1
            
            # Must have at least one assessment keyword and one percentage
            # This ensures we're matching assessment tables, not other tables with name/weight/date
            if keyword_count >= 1 and percentage_count >= 1:
                return True
        
        # Original assessment format: must have assessment keyword
        if not has_assessment_keyword:
            return False
        
        # Both weight AND date should be present for a valid assessment table
        if not (has_weight and has_date):
            return False
        
        # Additional validation: Check if data rows contain assessment-like content
        # Look at first few data rows for assessment keywords and percentages
        assessment_keywords = ['quiz', 'midterm', 'final', 'assignment', 'exam', 'report', 'lab', 'peerwise']
        keyword_count = 0
        percentage_count = 0
        
        for row in table[1:min(6, len(table))]:  # Check first 5 data rows
            row_text = ' '.join([str(cell) for cell in row if cell]).lower()
            if any(kw in row_text for kw in assessment_keywords):
                keyword_count += 1
            # Check for percentage patterns
            if re.search(r'\d+\.?\d*%', row_text):
                percentage_count += 1
        
        # Must have at least one assessment keyword and one percentage in data rows
        return keyword_count >= 1 and percentage_count >= 1
    
    def _extract_from_table(self, table: List[List]) -> List[AssessmentTask]:
        """Extract assessments from a structured table.
        
        Args:
            table: List of rows, where each row is a list of cells
            
        Returns:
            List of AssessmentTask objects
        """
        if not table or len(table) < 2:
            return []
        
        # Map columns
        header_row = table[0]  # Store header for reference
        column_map = self._map_table_columns(header_row, table[1:min(6, len(table))])
        if not column_map:
            return []
        
        assessments = []
        current_assessment = None
        
        # Process ALL data rows (skip header) - make sure we don't stop early
        # Process from row 1 to the end of the table
        total_rows = len(table)
        for row_idx in range(1, total_rows):
            row = table[row_idx]
            # Skip empty rows
            if not row or not any(cell for cell in row if cell):
                continue
            
            # Check if this is a summary row (Total, COURSE TOTAL, etc.)
            if self._is_summary_row(row, column_map):
                continue
            
            # Extract assessment name
            name = self._extract_name_from_row(row, column_map)
            
            # Extract weight and date to check if this row has meaningful data
            row_weight = self._extract_weight_from_row(row, column_map)
            row_due_datetime = self._extract_date_from_row(row, column_map)
            
            # For formats with both "Assigned" and "Due Date" columns, prefer "Due Date"
            # Check header row to see if both exist, then use "Due Date" if available
            if 'date' in column_map:
                date_idx = column_map['date']
                # Check header to see if we mapped "Assigned" but "Due Date" exists
                for idx, header_cell in enumerate(header_row):
                    if header_cell and idx != date_idx:
                        header_text = str(header_cell).lower()
                        if 'due date' in header_text or ('due' in header_text and 'date' in header_text):
                            # Found "Due Date" column, use it instead of "Assigned"
                            if idx < len(row) and row[idx]:
                                due_date_text = ' '.join(str(row[idx]).split('\n'))
                                temp_date = self._parse_date_from_text(due_date_text)
                                if temp_date:
                                    row_due_datetime = temp_date
                                    break
                                # Also check for relative dates in Due Date column
                                elif 'after' in due_date_text.lower() or 'hours' in due_date_text.lower():
                                    # This is a relative date - will be handled below
                                    pass
            
            # Check if this is a continuation row:
            # 1. Empty name but has date in date column (e.g., "Due Nov 21st")
            # 2. Empty name and empty weight but has date
            # 3. Very short name (< 3 chars) with no weight and no date
            # 4. Short name that looks like a fragment AND previous assessment name suggests continuation
            is_continuation = False
            
            if not name or name.strip() == '':
                # Empty name - check if it has date (likely continuation)
                if row_due_datetime:
                    is_continuation = True
                # Or if it has no weight but previous assessment exists
                elif row_weight is None and current_assessment:
                    is_continuation = True
            elif len(name.strip()) < 3:
                # Very short name with no weight/date - likely continuation
                if row_weight is None and not row_due_datetime:
                    is_continuation = True
            elif current_assessment:
                # Check if this looks like a continuation based on previous assessment
                prev_name = current_assessment.title.lower()
                name_lower = name.lower().strip()
                
                # If name is just a single word or short phrase and previous name exists
                # Check if it looks like a continuation of the previous assessment name
                if len(name_lower) < 20:  # Short name might be continuation
                    # Check if previous name suggests continuation (ends with incomplete phrase)
                    continuation_endings = ['short', 'intro', 'methods', 'results', 'assignment', 'long', 
                                           'rotation 1:', 'rotation 1: short', 'rotation 2:', 'rotation 3:', 
                                           'rotation 3 long', 'time', 'rotation']
                    if any(prev_name.endswith(word) for word in continuation_endings):
                        # And this name is a common continuation word or phrase
                        continuation_words = ['report', 'assignment', 'quiz', 'methods', 'results', 'intro', 
                                            'references', 'in lab', 'in person']
                        if name_lower in continuation_words:
                            # Also check: if current row has no weight and no date, it's likely continuation
                            if row_weight is None and not row_due_datetime:
                                is_continuation = True
                    
                    # Special case: if previous name is "Practicum Time" and this is "in lab", merge them
                    if prev_name.strip() == 'practicum time' and name_lower == 'in lab':
                        is_continuation = True
                    
                    # Special case: "Rotation X: short" or "Rotation X long" followed by "report"
                    if (('rotation' in prev_name and ('short' in prev_name or 'long' in prev_name)) and 
                        name_lower == 'report' and 
                        row_weight is None and not row_due_datetime):
                        is_continuation = True
                    
                    # If previous assessment has no weight and no date, and this row also has no weight,
                    # it might be a continuation (especially if name is short)
                    if (current_assessment.weight_percent is None and 
                        current_assessment.due_datetime is None and
                        row_weight is None and not row_due_datetime and
                        len(name_lower) < 10):
                        is_continuation = True
                    
                    # General rule: if name is just "report" and previous name contains "rotation" and "short" or "long",
                    # and current row has no weight/date, it's almost certainly a continuation
                    if (name_lower == 'report' and 
                        'rotation' in prev_name and 
                        ('short' in prev_name or 'long' in prev_name) and
                        row_weight is None and not row_due_datetime):
                                is_continuation = True
            
            if is_continuation and current_assessment:
                # Merge with previous assessment
                current_assessment = self._merge_continuation_row(current_assessment, row, column_map)
                # Update the last assessment in the list
                if assessments:
                    assessments[-1] = current_assessment
                continue
            
            # Use the extracted weight and date for this row
            weight = row_weight
            due_datetime = row_due_datetime
            
            # Extract format (optional)
            format_type = self._extract_format_from_row(row, column_map)
            
            # Classify assessment type
            assessment_type = self._classify_assessment_type(name)
            
            # Determine confidence
            confidence = 0.8
            if weight is None and due_datetime is None:
                confidence = 0.3
            elif weight is None or due_datetime is None:
                confidence = 0.6
            
            # Skip if name is empty or too short (likely not a real assessment)
            # BUT: Don't skip if it has weight or date (might be a valid assessment with short name)
            if not name or len(name.strip()) < 2:
                # Only skip if it also has no weight and no date
                if weight is None and not due_datetime:
                    continue
                # If it has weight or date, keep it (might be a valid short-named assessment)
            
            # Extract due rule if date is relative (e.g., "24 hours after lab")
            due_rule = None
            rule_anchor = None
            if not due_datetime and 'date' in column_map:
                date_idx = column_map['date']
                if date_idx < len(row) and row[date_idx]:
                    date_text = str(row[date_idx]).strip()
                    date_text = ' '.join(date_text.split('\n'))
                    # Check for relative date patterns
                    if ('after' in date_text.lower() or 
                        ('hours' in date_text.lower() and 'after' in date_text.lower()) or
                        '24hrs' in date_text.lower() or
                        '24 hrs' in date_text.lower() or
                        '24 hours' in date_text.lower()):
                        due_rule = date_text
                        # Extract anchor (lab, tutorial, lecture)
                        if 'lab' in date_text.lower():
                            rule_anchor = 'lab'
                        elif 'tutorial' in date_text.lower():
                            rule_anchor = 'tutorial'
                        elif 'lecture' in date_text.lower():
                            rule_anchor = 'lecture'
            
            # Create assessment with cleaned title
            cleaned_title = self._clean_assessment_title(name.strip())
            
            assessment = AssessmentTask(
                title=cleaned_title,
                type=assessment_type,
                weight_percent=weight,
                due_datetime=due_datetime,
                due_rule=due_rule,
                rule_anchor=rule_anchor,
                confidence=confidence,
                source_evidence=self._get_row_text(row, column_map),
                needs_review=(weight is None and due_datetime is None and due_rule is None)
            )
            
            assessments.append(assessment)
            current_assessment = assessment
        
        return assessments
    
    def _clean_assessment_title(self, title: str) -> str:
        """Clean up assessment title by removing numbering and extra punctuation.
        
        Args:
            title: Raw assessment title
            
        Returns:
            Cleaned title
        """
        if not title:
            return title
        
        # Remove leading numbers and punctuation like "1. ", "2) ", "1: "
        cleaned = re.sub(r'^\d+[\.\)\:]\s*', '', title)
        
        # Remove trailing colons and extra punctuation
        cleaned = re.sub(r':+\s*$', '', cleaned)
        cleaned = re.sub(r'\s*:+\s*:', ':', cleaned)  # Multiple colons to single
        
        # Clean up whitespace
        cleaned = ' '.join(cleaned.split())
        
        return cleaned.strip()
    
    def _map_table_columns(self, header_row: List, sample_rows: List[List] = None) -> dict:
        """Map table columns to their purpose.
        
        Handles both dense tables (all columns used) and sparse tables (columns with None/empty cells).
        
        Args:
            header_row: First row of the table (header)
            sample_rows: Optional sample data rows to help infer column positions in sparse tables
            
        Returns:
            Dictionary mapping column purpose to index, e.g. {'name': 0, 'weight': 2, 'date': 3}
        """
        column_map = {}
        
        # First pass: map by header text
        for idx, cell in enumerate(header_row):
            if not cell:
                continue
            
            cell_text = str(cell).lower().strip()
            
            # Assessment name column - multiple formats
            if 'assessment' in cell_text and 'name' not in column_map:
                column_map['name'] = idx
            elif ('name' in cell_text and 'name' not in column_map) or \
                 (cell_text.strip() == 'name' and 'name' not in column_map):
                # Some tables use "Name" instead of "Assessment" (e.g., ECE format)
                column_map['name'] = idx
            
            # Weight column - multiple formats
            if ('weight' in cell_text or 'weighting' in cell_text or '%' in cell_text or 
                '% worth' in cell_text or 'worth' in cell_text) and 'weight' not in column_map:
                column_map['weight'] = idx
            
            # Format column (optional)
            if 'format' in cell_text and 'format' not in column_map:
                column_map['format'] = idx
        
        # Multi-pass date column mapping to prioritize "Due Date" over "Assigned"
        # Pass 1: Look specifically for "Due Date" (highest priority)
        if 'date' not in column_map:
            for idx, cell in enumerate(header_row):
                if not cell:
                    continue
                cell_text = str(cell).lower().strip()
                if 'due date' in cell_text:
                    column_map['date'] = idx
                    break
        
        # Pass 2: Look for other "due...date" patterns
        if 'date' not in column_map:
            for idx, cell in enumerate(header_row):
                if not cell:
                    continue
                cell_text = str(cell).lower().strip()
                if 'due' in cell_text and 'date' in cell_text:
                    column_map['date'] = idx
                    break
        
        # Pass 3: Look for generic date/deadline
        if 'date' not in column_map:
            for idx, cell in enumerate(header_row):
                if not cell:
                    continue
                cell_text = str(cell).lower().strip()
                if 'date' in cell_text or 'deadline' in cell_text:
                    column_map['date'] = idx
                    break
        
        # Pass 4: Last resort - use "Assigned" if no explicit date column found
        if 'date' not in column_map:
            for idx, cell in enumerate(header_row):
                if not cell:
                    continue
                cell_text = str(cell).lower().strip()
                if 'assigned' in cell_text:
                    column_map['date'] = idx
                    break
        
        # If we have name and at least weight or date, we're good
        if 'name' in column_map and ('weight' in column_map or 'date' in column_map):
            return column_map
        
        # Second pass: for sparse tables, try to infer column positions from data
        # Look at sample rows to find where weight and date actually appear
        if sample_rows and 'name' in column_map:
            # Find weight column by looking for percentages
            if 'weight' not in column_map:
                for row in sample_rows:
                    for idx, cell in enumerate(row):
                        if cell and re.search(r'\d+\.?\d*%', str(cell)):
                            column_map['weight'] = idx
                            break
                    if 'weight' in column_map:
                        break
            
            # Find date column by looking for date patterns
            if 'date' not in column_map:
                for row in sample_rows:
                    for idx, cell in enumerate(row):
                        if cell:
                            cell_text = str(cell).lower()
                            # Look for date indicators
                            if any(indicator in cell_text for indicator in ['oct', 'nov', 'dec', 'jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'due', 'at 6:', 'at 11:', 'pm', 'am']):
                                column_map['date'] = idx
                                break
                    if 'date' in column_map:
                        break
        
        # Return mapping if we have name and at least one other column
        if 'name' in column_map and ('weight' in column_map or 'date' in column_map):
            return column_map
        
        return {}
    
    def _extract_name_from_row(self, row: List, column_map: dict) -> str:
        """Extract assessment name from a table row.
        
        Handles sparse tables where data might be at offset from header column.
        
        Args:
            row: Table row (list of cells)
            column_map: Column mapping dictionary
            
        Returns:
            Assessment name, or empty string if not found
        """
        if 'name' not in column_map:
            # Fallback: try first non-empty cell
            for cell in row:
                if cell and str(cell).strip():
                    text = str(cell).strip()
                    # Skip if it looks like a weight or date
                    if re.search(r'^\d+\.?\d*%$', text) or re.match(r'^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)', text.lower()):
                        continue
                    return text
            return ''
        
        name_idx = column_map['name']
        
        # Try mapped column first
        if name_idx < len(row) and row[name_idx] and str(row[name_idx]).strip():
            name_cell = row[name_idx]
        else:
            # Handle sparse tables: if mapped column is None, check adjacent columns
            # Especially check index 0 which often has the name in sparse tables
            name_cell = None
            
            # Priority order: index 0, then nearby columns
            check_order = [0] + [name_idx - 1, name_idx + 1] if name_idx > 0 else [0, name_idx + 1]
            for idx in check_order:
                if 0 <= idx < len(row) and row[idx] and str(row[idx]).strip():
                    candidate = str(row[idx]).strip()
                    # Skip if it looks like ONLY a weight, format keyword, or metadata
                    # But allow "Test 1", "Quiz 2", etc. (assessment names with numbers)
                    if (re.search(r'^\d+\.?\d*%$', candidate) or  # Just a percentage
                        candidate.lower() in ['mixed', 'online', 'in-person', 'none', 'n/a', 'not applicable']):
                        continue
                    name_cell = row[idx]
                    break
            
            if not name_cell:
                return ''
        
        # Handle multi-line cell content (join with spaces)
        if isinstance(name_cell, str):
            name = ' '.join(name_cell.split('\n'))
        else:
            name = str(name_cell)
        
        # Clean up common prefixes like "1. " or "2. "
        name = re.sub(r'^\d+\.\s*', '', name)
        
        return name.strip()
    
    def _extract_weight_from_row(self, row: List, column_map: dict) -> Optional[float]:
        """Extract weight percentage from a table row.
        
        Handles sparse tables where data might be at offset from header column.
        
        Args:
            row: Table row (list of cells)
            column_map: Column mapping dictionary
            
        Returns:
            Weight as float (percentage), or None if not found or completion-based
        """
        weight_text = ''
        
        if 'weight' in column_map:
            weight_idx = column_map['weight']
            
            # Try mapped column first
            if weight_idx < len(row) and row[weight_idx]:
                weight_text = str(row[weight_idx]).strip()
            else:
                # Handle sparse tables: search for percentage in adjacent columns
                check_order = [weight_idx - 1, weight_idx + 1, weight_idx - 2, weight_idx + 2]
                for idx in check_order:
                    if 0 <= idx < len(row) and row[idx]:
                        cell_text = str(row[idx]).strip()
                        if re.search(r'\d+\.?\d*%', cell_text):
                            weight_text = cell_text
                            break
        
        # Fallback: search entire row for percentage
        if not weight_text:
            for cell in row:
                if cell:
                    cell_text = str(cell).strip()
                    if re.search(r'\d+\.?\d*%', cell_text):
                        weight_text = cell_text
                        break
        
        if not weight_text:
            return None
        
        # Check for completion-based assessments
        if 'completion' in weight_text.lower() or weight_text.endswith('#'):
            return None  # Mark for review
        
        # Extract percentage
        match = re.search(r'(\d+\.?\d*)%', weight_text)
        if match:
            return float(match.group(1))
        
        return None
    
    def _extract_date_from_row(self, row: List, column_map: dict) -> Optional[datetime]:
        """Extract due date from a table row.
        
        Args:
            row: Table row (list of cells)
            column_map: Column mapping dictionary
            
        Returns:
            Due date as datetime, or None if not found
        """
        if 'date' not in column_map:
            return None
        
        date_idx = column_map['date']
        if date_idx >= len(row) or not row[date_idx]:
            return None
        
        date_cell = row[date_idx]
        date_text = str(date_cell).strip() if date_cell else ''
        
        # Handle multi-line cell content
        date_text = ' '.join(date_text.split('\n'))
        
        # Try to parse date using various patterns
        return self._parse_date_from_text(date_text)
    
    def _extract_format_from_row(self, row: List, column_map: dict) -> Optional[str]:
        """Extract format/type from a table row (optional).
        
        Args:
            row: Table row (list of cells)
            column_map: Column mapping dictionary
            
        Returns:
            Format string, or None if not found
        """
        if 'format' not in column_map:
            return None
        
        format_idx = column_map['format']
        if format_idx >= len(row) or not row[format_idx]:
            return None
        
        format_cell = row[format_idx]
        format_text = str(format_cell).strip() if format_cell else ''
        
        return format_text if format_text else None
    
    def _is_summary_row(self, row: List, column_map: dict) -> bool:
        """Check if a row is a summary row (Total, COURSE TOTAL, etc.).
        
        Args:
            row: Table row (list of cells)
            column_map: Column mapping dictionary
            
        Returns:
            True if this is a summary row
        """
        # Check name column
        if 'name' in column_map:
            name_idx = column_map['name']
            if name_idx < len(row) and row[name_idx]:
                name_text = str(row[name_idx]).lower().strip()
                # Check for summary keywords - be more specific to avoid false positives
                # Only match if "total" is the main word, not part of another word/phrase
                # Examples: "Total", "COURSE TOTAL", "Subtotal" = summary row
                # Examples: "Labs (Total = 8)", "Total Marks" = NOT summary row
                summary_patterns = [
                    r'^(course\s+)?total$',  # "Total" or "Course Total" as standalone
                    r'^subtotal$',  # "Subtotal" as standalone
                    r'^sum$',  # "Sum" as standalone
                    r'^grand\s+total$',  # "Grand Total" as standalone
                ]
                for pattern in summary_patterns:
                    if re.match(pattern, name_text, re.IGNORECASE):
                        return True
        
        # Check weight column for sum-like values
        if 'weight' in column_map:
            weight_idx = column_map['weight']
            if weight_idx < len(row) and row[weight_idx]:
                weight_text = str(row[weight_idx]).strip()
                # If weight is a large round number (like 100%, 25.00%), might be a total
                if re.match(r'^\d{2,3}(\.00)?%$', weight_text):
                    # But only if name suggests it's a total
                    if 'name' in column_map:
                        name_idx = column_map['name']
                        if name_idx < len(row) and row[name_idx]:
                            name_text = str(row[name_idx]).lower().strip()
                            # Use same strict patterns as name column check
                            summary_patterns = [
                                r'^(course\s+)?total$',
                                r'^subtotal$',
                                r'^sum$',
                                r'^grand\s+total$',
                            ]
                            for pattern in summary_patterns:
                                if re.match(pattern, name_text, re.IGNORECASE):
                                    return True
        
        return False
    
    def _merge_continuation_row(self, assessment: AssessmentTask, row: List, column_map: dict) -> AssessmentTask:
        """Merge a continuation row into an existing assessment.
        
        Args:
            assessment: Existing assessment to merge into
            row: Continuation row
            column_map: Column mapping dictionary
            
        Returns:
            Updated assessment with merged information
        """
        # Merge name if continuation row has name fragments
        if 'name' in column_map:
            name_idx = column_map['name']
            if name_idx < len(row) and row[name_idx]:
                continuation_name = str(row[name_idx]).strip()
                if continuation_name and continuation_name.lower() not in assessment.title.lower():
                    # Only add if it's not already in the title
                    # Add space if title doesn't end with punctuation
                    if not assessment.title.endswith((':', '-', '&')):
                        assessment.title += " "
                    assessment.title += continuation_name
        
        # Update weight if not already set (continuation rows usually don't have weight)
        if assessment.weight_percent is None and 'weight' in column_map:
            weight_idx = column_map['weight']
            if weight_idx < len(row) and row[weight_idx]:
                weight = self._extract_weight_from_row(row, column_map)
                if weight is not None:
                    assessment.weight_percent = weight
        
        # Update date - continuation rows often have the actual due date
        # Prefer date from continuation row if it exists
        if 'date' in column_map:
            date_idx = column_map['date']
            if date_idx < len(row) and row[date_idx]:
                date_text = str(row[date_idx]).strip()
                parsed_date = self._parse_date_from_text(date_text)
                if parsed_date:
                    # Use continuation row date if current date is None or if continuation date is more specific
                    if not assessment.due_datetime or ('due' in date_text.lower() and 'opens' not in date_text.lower()):
                        assessment.due_datetime = parsed_date
        
        # Update source evidence
        row_text = self._get_row_text(row, column_map)
        if row_text:
            assessment.source_evidence = (assessment.source_evidence or '') + " " + row_text
        
        return assessment
    
    def _get_row_text(self, row: List, column_map: dict) -> str:
        """Get all text from a row for source evidence.
        
        Args:
            row: Table row
            column_map: Column mapping dictionary
            
        Returns:
            Combined text from all cells
        """
        texts = []
        for cell in row:
            if cell:
                cell_text = str(cell).strip()
                if cell_text:
                    texts.append(cell_text)
        return ' '.join(texts)
    
    def _parse_date_from_text(self, date_text: str) -> Optional[datetime]:
        """Parse date from text using various patterns.
        
        Args:
            date_text: Text containing date information
            
        Returns:
            Parsed datetime, or None if not found
        """
        if not date_text or not date_text.strip():
            return None
        
        # Clean up text - handle multi-line and common OCR errors
        date_text = ' '.join(date_text.split('\n'))
        date_text = date_text.replace('S ept', 'Sept').replace('S eptember', 'September')
        
        # Handle "Opens X... Due Y" format - use the Due date
        opens_due_match = re.search(r'Opens\s+[^D]*Due\s+([^\.]+)', date_text, re.IGNORECASE)
        if opens_due_match:
            date_text = opens_due_match.group(1).strip()
        
        # Handle date ranges like "Dec 2nd/3rd" - use the later date
        date_range_match = re.search(r'(\w+)\s+(\d{1,2})(?:st|nd|rd|th)?\s*[/-]\s*(\d{1,2})(?:st|nd|rd|th)?', date_text, re.IGNORECASE)
        if date_range_match:
            month_str = date_range_match.group(1)
            day1 = int(date_range_match.group(2))
            day2 = int(date_range_match.group(3))
            # Use the later day
            day = max(day1, day2)
            month = self._month_name_to_num(month_str)
            if month:
                year = 2025 if month >= 9 else 2026
                return datetime(year, month, day, 23, 59)
        
        # Try dateparser first (handles many formats)
        parsed = dateparser.parse(date_text, settings={'PREFER_DATES_FROM': 'future'})
        if parsed:
            # Extract time if present
            time_match = re.search(r'(\d{1,2})(?:[:–-](\d{2}))?\s*(AM|PM|am|pm)', date_text, re.IGNORECASE)
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2)) if time_match.group(2) else 0
                if time_match.group(3).upper() == 'PM' and hour != 12:
                    hour += 12
                elif time_match.group(3).upper() == 'AM' and hour == 12:
                    hour = 0
                return datetime.combine(parsed.date(), time(hour, minute))
            else:
                # Default to end of day if no time specified
                return datetime.combine(parsed.date(), time(23, 59))
        
        # Fallback to regex patterns
        patterns = [
            r'(?:Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday),?\s+(\w+)\s+(\d{1,2})(?:st|nd|rd|th)?',
            r'(\w+)\s+(\d{1,2})(?:st|nd|rd|th)?',
            r'Due\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+(\w+)\s+(\d{1,2})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, date_text, re.IGNORECASE)
            if match:
                month_str = match.group(1)
                day = int(match.group(2))
                
                # Determine year (default to 2025, adjust based on month)
                year = 2025
                if any(m in month_str.lower() for m in ['jan', 'feb', 'mar', 'apr']):
                    year = 2026
                
                # Convert month name to number
                month = self._month_name_to_num(month_str)
                if month:
                    # Extract time if present
                    time_match = re.search(r'(\d{1,2})(?:[:–-](\d{2}))?\s*(AM|PM|am|pm)', date_text, re.IGNORECASE)
                    if time_match:
                        hour = int(time_match.group(1))
                        minute = int(time_match.group(2)) if time_match.group(2) else 0
                        if time_match.group(3).upper() == 'PM' and hour != 12:
                            hour += 12
                        elif time_match.group(3).upper() == 'AM' and hour == 12:
                            hour = 0
                        return datetime(year, month, day, hour, minute)
                    else:
                        return datetime(year, month, day, 23, 59)
        
        return None
    
    def _month_name_to_num(self, month_str: str) -> Optional[int]:
        """Convert month name/abbreviation to number.
        
        Args:
            month_str: Month name or abbreviation
            
        Returns:
            Month number (1-12), or None if invalid
        """
        month_map = {
            'jan': 1, 'january': 1,
            'feb': 2, 'february': 2,
            'mar': 3, 'march': 3,
            'apr': 4, 'april': 4,
            'may': 5,
            'jun': 6, 'june': 6,
            'jul': 7, 'july': 7,
            'aug': 8, 'august': 8,
            'sep': 9, 'sept': 9, 'september': 9,
            'oct': 10, 'october': 10,
            'nov': 11, 'november': 11,
            'dec': 12, 'december': 12,
        }
        
        month_lower = month_str.lower().rstrip('.')
        return month_map.get(month_lower)

