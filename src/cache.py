"""
Caching system for course outline processing.

Uses SQLite for local development and Supabase PostgreSQL for production.
Automatically selects the appropriate cache manager based on environment variables.

The cache system separates:
- extraction_cache: PDF-derived facts (keyed by PDF hash)
- user_choices: User selections (sections, lead times) - separate from extraction
"""

import os
import sqlite3
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional
from .models import (
    ExtractedCourseData, UserSelections, CacheEntry,
    CourseTerm, SectionOption, AssessmentTask,
    serialize_date, deserialize_date,
    serialize_datetime, deserialize_datetime,
    serialize_time, deserialize_time
)


def compute_pdf_hash(pdf_path: Path) -> str:
    """Compute SHA-256 hash of PDF file."""
    with open(pdf_path, 'rb') as f:
        pdf_bytes = f.read()
    return hashlib.sha256(pdf_bytes).hexdigest()


class CacheManager:
    """Manages cache storage and retrieval for PDF processing."""
    
    def __init__(self, cache_dir: Optional[Path] = None):
        """Initialize cache manager.
        
        Args:
            cache_dir: Directory for cache storage. Defaults to ~/.course_outline_cache
        """
        if cache_dir is None:
            cache_dir = Path.home() / ".course_outline_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = cache_dir / "cache.db"
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema.
        
        Per CLARIFYING_QUESTIONS.md: Separate extraction cache from user choices.
        - extraction_cache: Derived facts from PDF (keyed by PDF hash)
        - user_choices: Selected sections, lead-time overrides (keyed by session/user)
        """
        conn = sqlite3.connect(self.db_path)
        # Extraction cache: derived facts from PDF
        conn.execute("""
            CREATE TABLE IF NOT EXISTS extraction_cache (
                pdf_hash TEXT PRIMARY KEY,
                extracted_json TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)
        # User choices cache: separate from extraction
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_choices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pdf_hash TEXT NOT NULL,
                session_id TEXT,
                selected_lecture_section_json TEXT,
                selected_lab_section_json TEXT,
                lead_time_overrides_json TEXT,
                timestamp TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()
    
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
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "SELECT extracted_json, timestamp FROM extraction_cache WHERE pdf_hash = ?",
            (pdf_hash,)
        )
        row = cursor.fetchone()
        conn.close()
        
        if row is None:
            return None
        
        extracted_json, timestamp_str = row
        
        # Deserialize extracted data
        extracted_dict = json.loads(extracted_json)
        return self._deserialize_extracted_data(extracted_dict)
    
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
        conn = sqlite3.connect(self.db_path)
        
        if session_id:
            cursor = conn.execute(
                """
                SELECT selected_lecture_section_json, selected_lab_section_json, 
                       lead_time_overrides_json
                FROM user_choices
                WHERE pdf_hash = ? AND session_id = ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (pdf_hash, session_id)
            )
        else:
            cursor = conn.execute(
                """
                SELECT selected_lecture_section_json, selected_lab_section_json,
                       lead_time_overrides_json
                FROM user_choices
                WHERE pdf_hash = ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (pdf_hash,)
            )
        
        row = cursor.fetchone()
        conn.close()
        
        if row is None:
            return None
        
        lecture_json, lab_json, overrides_json = row
        
        # Deserialize user selections
        selections_dict = {}
        if lecture_json:
            selections_dict['selected_lecture_section'] = json.loads(lecture_json)
        if lab_json:
            selections_dict['selected_lab_section'] = json.loads(lab_json)
        if overrides_json:
            selections_dict['lead_time_overrides'] = json.loads(overrides_json)
        
        return self._deserialize_selections(selections_dict)
    
    def lookup(self, pdf_hash: str) -> Optional[CacheEntry]:
        """Look up cache entry by PDF hash (legacy method for compatibility).
        
        This method combines extraction cache and user choices for backward
        compatibility. New code should use lookup_extraction() and lookup_user_choices()
        separately.
        
        Args:
            pdf_hash: SHA-256 hash of PDF
            
        Returns:
            CacheEntry if found, None otherwise
        """
        extracted_data = self.lookup_extraction(pdf_hash)
        if extracted_data is None:
            return None
        
        user_selections = self.lookup_user_choices(pdf_hash) or UserSelections()
        
        # Note: generated_ics is not stored separately anymore
        # It can be regenerated from extracted_data and user_selections
        return CacheEntry(
            pdf_hash=pdf_hash,
            extracted_data=extracted_data,
            user_selections=user_selections,
            generated_ics="",  # Will be regenerated
            timestamp=datetime.now()  # Approximate
        )
    
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
        
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT OR REPLACE INTO extraction_cache (pdf_hash, extracted_json, timestamp)
            VALUES (?, ?, ?)
            """,
            (pdf_hash, extracted_json, datetime.now().isoformat())
        )
        conn.commit()
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
        
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO user_choices 
            (pdf_hash, session_id, selected_lecture_section_json, 
             selected_lab_section_json, lead_time_overrides_json, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                pdf_hash,
                session_id,
                json.dumps(selections_dict.get('selected_lecture_section')),
                json.dumps(selections_dict.get('selected_lab_section')),
                json.dumps(selections_dict.get('lead_time_overrides', {})),
                datetime.now().isoformat()
            )
        )
        conn.commit()
        conn.close()
    
    def store(self, pdf_hash: str, extracted_data: ExtractedCourseData,
              generated_ics: str, user_selections: UserSelections):
        """Store cache entry (legacy method for compatibility).
        
        This method stores both extraction data and user choices for backward
        compatibility. New code should use store_extraction() and store_user_choices()
        separately.
        
        Args:
            pdf_hash: SHA-256 hash of PDF
            extracted_data: Extracted course data
            generated_ics: Generated .ics file content (not stored separately)
            user_selections: User selections (sections, overrides)
        """
        self.store_extraction(pdf_hash, extracted_data)
        self.store_user_choices(pdf_hash, user_selections)
    
    def _serialize_extracted_data(self, data: ExtractedCourseData) -> dict:
        """Serialize ExtractedCourseData to dict."""
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
            selections.selected_lecture_section = self._deserialize_section(
                data["selected_lecture_section"]
            )
        
        if "selected_lab_section" in data and data["selected_lab_section"]:
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


# Auto-select cache manager based on environment
def get_cache_manager():
    """Get the appropriate cache manager based on environment.
    
    Returns:
        SupabaseCacheManager if DATABASE_URL is set, otherwise SQLiteCacheManager
    """
    if os.getenv("DATABASE_URL"):
        # Use Supabase for production
        from .supabase_cache import SupabaseCacheManager
        return SupabaseCacheManager()
    else:
        # Use SQLite for local development
        return CacheManager()


# Alias for backward compatibility
SQLiteCacheManager = CacheManager

