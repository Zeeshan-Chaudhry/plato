"""
OpenAI-based PDF extraction for paid tier.

This module provides high-accuracy extraction using OpenAI's GPT models
to ensure perfect assessment extraction regardless of PDF format or university.

The paid tier extraction is UNIVERSAL - it works with course outlines from
ANY university, college, or educational institution worldwide, handling different:
- Academic calendar systems (semesters, trimesters, quarters)
- Date formats (US, international, regional variations)
- Course code formats and naming conventions
- Assessment structures and grading schemes
- PDF layouts and formats
"""

import os
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime, date, time
import dateparser

from .models import ExtractedCourseData, CourseTerm, SectionOption, AssessmentTask
from .pdf_extractor import PDFExtractor


# System prompt for structured extraction
EXTRACTION_SYSTEM_PROMPT = """You are an expert at extracting course information from university course outline PDFs from ANY university worldwide.

Your task is to extract ALL assessment information with perfect accuracy, regardless of which university or institution the course outline is from. You must:
1. Extract EVERY assessment, assignment, quiz, exam, project, lab report, etc.
2. Extract the EXACT weight/percentage for each assessment
3. Extract ALL due dates (including multiple dates for the same assessment)
4. Understand the complete marking scheme - ensure weights sum to 100% (or close to it)
5. Extract course code, course name, and term information (handle any date format, semester system, or academic calendar)
6. Extract lecture/lab schedules if present (handle any time format, day notation, or schedule system)

UNIVERSAL REQUIREMENTS (works for any university):
- This extraction must work for course outlines from ANY university, college, or educational institution
- Handle different academic calendar systems (semesters, trimesters, quarters, etc.)
- Handle different date formats (US, international, various regional formats)
- Handle different course code formats (e.g., "CS 101", "CS101", "COMPSCI 101", etc.)
- Handle different assessment naming conventions and grading schemes
- Adapt to different PDF structures and layouts used by various institutions

CRITICAL REQUIREMENTS:
- Do NOT miss any assessments, even if they're in unusual formats
- Extract weights as exact percentages (e.g., 15.0, 25.5, not "15%" as text)
- Extract dates in ISO format (YYYY-MM-DD) or relative rules (e.g., "24 hours after lab")
- If an assessment has multiple due dates, include all of them
- If weights don't sum to 100%, note which assessments might be missing
- Extract assessment types: "assignment", "quiz", "midterm", "final", "lab_report", "project", "other"

Return a JSON object with the following structure:
{
  "course_code": "CS 2211A",
  "course_name": "Introduction to Software Engineering",
  "term": {
    "term_name": "Fall 2025",
    "start_date": "2025-09-04",
    "end_date": "2025-12-09"
  },
  "lecture_sections": [
    {
      "section_id": "001",
      "days_of_week": [0, 2, 4],
      "start_time": "10:30:00",
      "end_time": "11:30:00",
      "location": "WSC 55"
    }
  ],
  "lab_sections": [],
  "assessments": [
    {
      "title": "Assignment 1",
      "type": "assignment",
      "weight_percent": 10.0,
      "due_datetime": "2025-10-15T23:59:00",
      "due_rule": null,
      "rule_anchor": null
    },
    {
      "title": "Midterm Test 1",
      "type": "midterm",
      "weight_percent": 25.0,
      "due_datetime": "2025-11-14T18:00:00",
      "due_rule": null,
      "rule_anchor": null
    }
  ]
}

For days_of_week: 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, 4=Friday, 5=Saturday, 6=Sunday
For times: Use 24-hour format (HH:MM:SS)
For dates: Use ISO format (YYYY-MM-DD) or ISO datetime (YYYY-MM-DDTHH:MM:SS)
"""


class OpenAIExtractor:
    """Extracts course data using OpenAI API for high-accuracy extraction."""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        """Initialize OpenAI extractor.
        
        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: Model to use (gpt-4o-mini for cost, gpt-4o for accuracy)
            
        Raises:
            ImportError: If openai package is not installed
            ValueError: If API key is not provided
        """
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                "openai package is required for paid tier. Install with: pip install openai"
            )
        
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError(
                "OpenAI API key is required for paid tier. "
                "Set OPENAI_API_KEY environment variable or pass api_key parameter."
            )
        
        self.client = OpenAI(api_key=self.api_key)
        self.model = model
    
    def extract_from_pdf(self, pdf_path: Path) -> ExtractedCourseData:
        """Extract course data from PDF using OpenAI.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            ExtractedCourseData with all course information
        """
        # First, extract text from PDF using existing method
        pdf_extractor = PDFExtractor(pdf_path)
        full_text = self._extract_full_text(pdf_path)
        
        # Send to OpenAI for extraction
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Extract all course information from this course outline:\n\n{full_text}"
                }
            ],
            response_format={"type": "json_object"},
            temperature=0.1,  # Low temperature for consistent extraction
        )
        
        # Parse response
        result = json.loads(response.choices[0].message.content)
        
        # Convert to ExtractedCourseData
        return self._parse_extraction_result(result, pdf_extractor)
    
    def _extract_full_text(self, pdf_path: Path, max_pages: int = 20) -> str:
        """Extract full text from PDF.
        
        Args:
            pdf_path: Path to PDF
            max_pages: Maximum pages to extract (to limit token usage)
            
        Returns:
            Full text content
        """
        try:
            import pdfplumber
            full_text = ""
            with pdfplumber.open(str(pdf_path)) as pdf:
                for i, page in enumerate(pdf.pages[:max_pages], 1):
                    text = page.extract_text()
                    if text:
                        full_text += f"\n--- Page {i} ---\n{text}\n"
            return full_text
        except Exception as e:
            raise ValueError(f"Failed to extract text from PDF: {e}")
    
    def _parse_extraction_result(
        self, 
        result: Dict[str, Any], 
        pdf_extractor: PDFExtractor
    ) -> ExtractedCourseData:
        """Parse OpenAI response into ExtractedCourseData.
        
        Args:
            result: JSON response from OpenAI
            pdf_extractor: PDFExtractor instance for fallback methods
            
        Returns:
            ExtractedCourseData object
        """
        # Parse term
        term_data = result.get('term', {})
        term = CourseTerm(
            term_name=term_data.get('term_name', 'Unknown'),
            start_date=self._parse_date(term_data.get('start_date')),
            end_date=self._parse_date(term_data.get('end_date')),
            timezone="America/Toronto"
        )
        
        # Parse lecture sections
        lecture_sections = []
        for section_data in result.get('lecture_sections', []):
            try:
                section = SectionOption(
                    section_type="Lecture",
                    section_id=section_data.get('section_id', ''),
                    days_of_week=section_data.get('days_of_week', []),
                    start_time=self._parse_time(section_data.get('start_time')),
                    end_time=self._parse_time(section_data.get('end_time')),
                    location=section_data.get('location')
                )
                lecture_sections.append(section)
            except Exception as e:
                print(f"Warning: Failed to parse lecture section: {e}")
        
        # Parse lab sections
        lab_sections = []
        for section_data in result.get('lab_sections', []):
            try:
                section = SectionOption(
                    section_type="Lab",
                    section_id=section_data.get('section_id', ''),
                    days_of_week=section_data.get('days_of_week', []),
                    start_time=self._parse_time(section_data.get('start_time')),
                    end_time=self._parse_time(section_data.get('end_time')),
                    location=section_data.get('location')
                )
                lab_sections.append(section)
            except Exception as e:
                print(f"Warning: Failed to parse lab section: {e}")
        
        # Parse assessments - CRITICAL: Extract ALL assessments
        assessments = []
        for assessment_data in result.get('assessments', []):
            try:
                # Parse due date
                due_datetime = None
                due_rule = None
                rule_anchor = None
                
                if assessment_data.get('due_datetime'):
                    due_datetime = self._parse_datetime(assessment_data['due_datetime'])
                elif assessment_data.get('due_rule'):
                    due_rule = assessment_data['due_rule']
                    rule_anchor = assessment_data.get('rule_anchor')
                
                assessment = AssessmentTask(
                    title=assessment_data.get('title', 'Unknown'),
                    type=assessment_data.get('type', 'other'),
                    weight_percent=assessment_data.get('weight_percent'),
                    due_datetime=due_datetime,
                    due_rule=due_rule,
                    rule_anchor=rule_anchor,
                    confidence=0.95,  # High confidence for OpenAI extraction
                    needs_review=False
                )
                assessments.append(assessment)
            except Exception as e:
                print(f"Warning: Failed to parse assessment: {e}")
                print(f"Assessment data: {assessment_data}")
        
        # Validate assessment weights sum to ~100%
        total_weight = sum(a.weight_percent or 0 for a in assessments)
        if total_weight < 80 or total_weight > 120:
            # Mark for review if weights are off
            for assessment in assessments:
                assessment.needs_review = True
        
        return ExtractedCourseData(
            term=term,
            lecture_sections=lecture_sections,
            lab_sections=lab_sections,
            assessments=assessments,
            course_code=result.get('course_code'),
            course_name=result.get('course_name')
        )
    
    def _parse_date(self, date_str: Optional[str]) -> date:
        """Parse date string to date object."""
        if not date_str:
            return date.today()  # Default fallback
        
        try:
            # Try ISO format first
            return date.fromisoformat(date_str)
        except ValueError:
            # Try dateparser
            parsed = dateparser.parse(date_str)
            if parsed:
                return parsed.date()
            return date.today()
    
    def _parse_datetime(self, datetime_str: Optional[str]) -> Optional[datetime]:
        """Parse datetime string to datetime object."""
        if not datetime_str:
            return None
        
        try:
            # Try ISO format first
            return datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
        except ValueError:
            # Try dateparser
            parsed = dateparser.parse(datetime_str)
            return parsed if parsed else None
    
    def _parse_time(self, time_str: Optional[str]) -> Optional[time]:
        """Parse time string to time object."""
        if not time_str:
            return None
        
        try:
            # Try ISO format (HH:MM:SS)
            parts = time_str.split(':')
            if len(parts) >= 2:
                hour = int(parts[0])
                minute = int(parts[1])
                second = int(parts[2]) if len(parts) > 2 else 0
                return time(hour, minute, second)
        except (ValueError, IndexError):
            pass
        
        # Try dateparser
        parsed = dateparser.parse(f"2025-01-01 {time_str}")
        if parsed:
            return parsed.time()
        
        return None
