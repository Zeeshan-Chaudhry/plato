"""
Supabase-based cache manager for production deployment.

Uses Supabase PostgreSQL database instead of local SQLite.
Automatically used when DATABASE_URL environment variable is set.
"""

import os
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional
import psycopg2
from psycopg2.extras import RealDictCursor

from .models import (
    ExtractedCourseData, UserSelections, CacheEntry,
    CourseTerm, SectionOption, AssessmentTask,
    serialize_date, deserialize_date,
    serialize_datetime, deserialize_datetime,
    serialize_time, deserialize_time
)


def compute_pdf_hash(pdf_path: Path) -> str:
    """Compute SHA-256 hash of PDF file.
    
    This function is shared between SQLite and Supabase cache managers.
    It calculates a unique hash for each PDF file to use as a cache key.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        SHA-256 hash as hexadecimal string (64 characters)
    """
    with open(pdf_path, 'rb') as f:
        pdf_bytes = f.read()
    return hashlib.sha256(pdf_bytes).hexdigest()


class SupabaseCacheManager:
    """Manages cache storage and retrieval using Supabase PostgreSQL.
    
    This cache manager stores extracted PDF data and user choices in Supabase.
    It separates extraction cache (PDF-derived facts) from user choices,
    allowing multiple users to use the same PDF with different section selections.
    
    The manager automatically uses Supabase when DATABASE_URL environment variable
    is set. Otherwise, falls back to SQLite for local development.
    """
    
    def __init__(self, database_url: Optional[str] = None):
        """Initialize Supabase cache manager.
        
        Args:
            database_url: PostgreSQL connection string. If None, reads from
                         DATABASE_URL environment variable.
                         
        Raises:
            ValueError: If database_url is not provided and DATABASE_URL env var is not set
        """
        if database_url is None:
            database_url = os.getenv("DATABASE_URL")
        
        if not database_url:
            raise ValueError(
                "DATABASE_URL environment variable must be set for Supabase cache. "
                "For local development, use SQLiteCacheManager instead."
            )
        
        self.database_url = database_url
        self._test_connection()
    
    def _test_connection(self):
        """Test database connection on initialization.
        
        Raises:
            psycopg2.OperationalError: If connection fails
        """
        try:
            conn = psycopg2.connect(self.database_url)
            conn.close()
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Supabase: {e}")
    
    def _get_connection(self):
        """Get a database connection.
        
        Returns:
            psycopg2 connection object
        """
        return psycopg2.connect(self.database_url)
    
    def lookup_extraction(self, pdf_hash: str) -> Optional[ExtractedCourseData]:
        """Look up extracted data from cache by PDF hash.
        
        This method queries the extraction_cache table to find previously
        extracted data for a given PDF. The extraction cache stores facts
        derived from the PDF itself, independent of user choices.
        
        Args:
            pdf_hash: SHA-256 hash of the PDF file
            
        Returns:
            ExtractedCourseData if found in cache, None otherwise
        """
        conn = self._get_connection()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT extracted_json, timestamp FROM extraction_cache WHERE pdf_hash = %s",
                (pdf_hash,)
            )
            row = cur.fetchone()
            cur.close()
            
            if row is None:
                return None
            
            # Deserialize extracted data
            extracted_dict = json.loads(row['extracted_json'])
            return self._deserialize_extracted_data(extracted_dict)
            
        finally:
            conn.close()
    
    def store_extraction(self, pdf_hash: str, extracted_data: ExtractedCourseData):
        """Store extracted data in cache.
        
        Stores the extracted course data (term, sections, assessments) in the
        extraction_cache table. This data is derived from the PDF and doesn't
        depend on user choices.
        
        Args:
            pdf_hash: SHA-256 hash of the PDF file
            extracted_data: Extracted course data to store
        """
        # Serialize extracted data
        extracted_dict = self._serialize_extracted_data(extracted_data)
        extracted_json = json.dumps(extracted_dict)
        
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO extraction_cache (pdf_hash, extracted_json, timestamp)
                VALUES (%s, %s, NOW())
                ON CONFLICT (pdf_hash) 
                DO UPDATE SET 
                    extracted_json = EXCLUDED.extracted_json,
                    timestamp = NOW()
                """,
                (pdf_hash, extracted_json)
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()
    
    def lookup_user_choices(self, pdf_hash: str, session_id: Optional[str] = None) -> Optional[UserSelections]:
        """Look up user choices from cache.
        
        Retrieves user selections (sections, lead-time overrides) for a given
        PDF hash. If session_id is provided, looks for session-specific choices.
        Otherwise, returns the most recent choices for that PDF.
        
        Args:
            pdf_hash: SHA-256 hash of the PDF file
            session_id: Optional session identifier for user-specific choices
            
        Returns:
            UserSelections if found, None otherwise
        """
        conn = self._get_connection()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            if session_id:
                cur.execute(
                    """
                    SELECT selected_lecture_section_json, selected_lab_section_json, 
                           lead_time_overrides_json
                    FROM user_choices
                    WHERE pdf_hash = %s AND session_id = %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (pdf_hash, session_id)
                )
            else:
                cur.execute(
                    """
                    SELECT selected_lecture_section_json, selected_lab_section_json,
                           lead_time_overrides_json
                    FROM user_choices
                    WHERE pdf_hash = %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (pdf_hash,)
                )
            
            row = cur.fetchone()
            cur.close()
            
            if row is None:
                return None
            
            # Deserialize user selections
            selections_dict = {}
            if row['selected_lecture_section_json']:
                selections_dict['selected_lecture_section'] = row['selected_lecture_section_json']
            if row['selected_lab_section_json']:
                selections_dict['selected_lab_section'] = row['selected_lab_section_json']
            if row['lead_time_overrides_json']:
                selections_dict['lead_time_overrides'] = row['lead_time_overrides_json']
            
            return self._deserialize_selections(selections_dict)
            
        finally:
            conn.close()
    
    def store_user_choices(self, pdf_hash: str, user_selections: UserSelections, 
                          session_id: Optional[str] = None):
        """Store user choices in cache.
        
        Stores user selections (lecture/lab sections, lead-time overrides) in
        the user_choices table. This is separate from extraction cache, allowing
        multiple users to have different selections for the same PDF.
        
        Args:
            pdf_hash: SHA-256 hash of the PDF file
            user_selections: User selections to store
            session_id: Optional session identifier
        """
        # Serialize user selections
        selections_dict = self._serialize_selections(user_selections)
        
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO user_choices 
                (pdf_hash, session_id, selected_lecture_section_json, 
                 selected_lab_section_json, lead_time_overrides_json, timestamp)
                VALUES (%s, %s, %s, %s, %s, NOW())
                """,
                (
                    pdf_hash,
                    session_id,
                    json.dumps(selections_dict.get('selected_lecture_section')),
                    json.dumps(selections_dict.get('selected_lab_section')),
                    json.dumps(selections_dict.get('lead_time_overrides', {}))
                )
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()
    
    # Serialization methods (same as SQLite cache manager)
    def _serialize_extracted_data(self, data: ExtractedCourseData) -> dict:
        """Serialize ExtractedCourseData to dict for JSON storage."""
        return {
            "term": {
                "term_name": data.term.term_name,
                "start_date": serialize_date(data.term.start_date),
                "end_date": serialize_date(data.term.end_date),
                "timezone": data.term.timezone
            },
            "lecture_sections": [self._serialize_section(s) for s in data.lecture_sections],
            "lab_sections": [self._serialize_section(s) for s in data.lab_sections],
            "assessments": [self._serialize_assessment(a) for a in data.assessments],
            "course_code": data.course_code,
            "course_name": data.course_name
        }
    
    def _deserialize_extracted_data(self, data: dict) -> ExtractedCourseData:
        """Deserialize dict to ExtractedCourseData."""
        term_dict = data["term"]
        term = CourseTerm(
            term_name=term_dict["term_name"],
            start_date=deserialize_date(term_dict["start_date"]),
            end_date=deserialize_date(term_dict["end_date"]),
            timezone=term_dict.get("timezone", "America/Toronto")
        )
        
        lecture_sections = [self._deserialize_section(s) for s in data.get("lecture_sections", [])]
        lab_sections = [self._deserialize_section(s) for s in data.get("lab_sections", [])]
        assessments = [self._deserialize_assessment(a) for a in data.get("assessments", [])]
        
        return ExtractedCourseData(
            term=term,
            lecture_sections=lecture_sections,
            lab_sections=lab_sections,
            assessments=assessments,
            course_code=data.get("course_code"),
            course_name=data.get("course_name")
        )
    
    def _serialize_section(self, section: SectionOption) -> dict:
        """Serialize SectionOption to dict."""
        result = {
            "section_type": section.section_type,
            "section_id": section.section_id,
            "days_of_week": section.days_of_week,
            "start_time": serialize_time(section.start_time),
            "end_time": serialize_time(section.end_time),
            "location": section.location
        }
        if section.date_range:
            result["date_range"] = [
                serialize_date(section.date_range[0]),
                serialize_date(section.date_range[1])
            ]
        return result
    
    def _deserialize_section(self, data: dict) -> SectionOption:
        """Deserialize dict to SectionOption."""
        date_range = None
        if "date_range" in data and data["date_range"]:
            date_range = (
                deserialize_date(data["date_range"][0]),
                deserialize_date(data["date_range"][1])
            )
        
        return SectionOption(
            section_type=data["section_type"],
            section_id=data["section_id"],
            days_of_week=data["days_of_week"],
            start_time=deserialize_time(data["start_time"]),
            end_time=deserialize_time(data["end_time"]),
            location=data.get("location"),
            date_range=date_range
        )
    
    def _serialize_assessment(self, assessment: AssessmentTask) -> dict:
        """Serialize AssessmentTask to dict."""
        result = {
            "title": assessment.title,
            "type": assessment.type,
            "weight_percent": assessment.weight_percent,
            "confidence": assessment.confidence,
            "source_evidence": assessment.source_evidence,
            "needs_review": assessment.needs_review,
            "due_rule": assessment.due_rule,
            "rule_anchor": assessment.rule_anchor
        }
        if assessment.due_datetime:
            result["due_datetime"] = serialize_datetime(assessment.due_datetime)
        return result
    
    def _deserialize_assessment(self, data: dict) -> AssessmentTask:
        """Deserialize dict to AssessmentTask."""
        due_datetime = None
        if "due_datetime" in data and data["due_datetime"]:
            due_datetime = deserialize_datetime(data["due_datetime"])
        
        return AssessmentTask(
            title=data["title"],
            type=data["type"],
            weight_percent=data.get("weight_percent"),
            due_datetime=due_datetime,
            due_rule=data.get("due_rule"),
            rule_anchor=data.get("rule_anchor"),
            confidence=data.get("confidence", 0.0),
            source_evidence=data.get("source_evidence"),
            needs_review=data.get("needs_review", False)
        )
    
    def _serialize_selections(self, selections: UserSelections) -> dict:
        """Serialize UserSelections to dict."""
        result = {
            "assessment_overrides": {
                k: self._serialize_assessment(v)
                for k, v in selections.assessment_overrides.items()
            }
        }
        if selections.selected_lecture_section:
            result["selected_lecture_section"] = self._serialize_section(
                selections.selected_lecture_section
            )
        if selections.selected_lab_section:
            result["selected_lab_section"] = self._serialize_section(
                selections.selected_lab_section
            )
        # Handle lead_time_overrides if it exists as an attribute
        if hasattr(selections, 'lead_time_overrides') and selections.lead_time_overrides:
            result["lead_time_overrides"] = selections.lead_time_overrides
        return result
    
    def _deserialize_selections(self, data: dict) -> UserSelections:
        """Deserialize dict to UserSelections."""
        selections = UserSelections()
        
        if "selected_lecture_section" in data and data["selected_lecture_section"]:
            if isinstance(data["selected_lecture_section"], dict):
                selections.selected_lecture_section = self._deserialize_section(
                    data["selected_lecture_section"]
                )
        
        if "selected_lab_section" in data and data["selected_lab_section"]:
            if isinstance(data["selected_lab_section"], dict):
                selections.selected_lab_section = self._deserialize_section(
                    data["selected_lab_section"]
                )
        
        if "assessment_overrides" in data:
            selections.assessment_overrides = {
                k: self._deserialize_assessment(v)
                for k, v in data["assessment_overrides"].items()
            }
        
        # Handle lead_time_overrides - store as attribute (not in model, but accessible)
        if "lead_time_overrides" in data and data["lead_time_overrides"]:
            # Parse JSON if it's a string
            if isinstance(data["lead_time_overrides"], str):
                import json
                selections.lead_time_overrides = json.loads(data["lead_time_overrides"])
            else:
                selections.lead_time_overrides = data["lead_time_overrides"]
        
        return selections

