"""
Data models for course outline to iCalendar converter.

This module defines all the data structures used throughout the application.
All models use Python dataclasses, which provide a simple way to define
classes that mainly store data. Dataclasses automatically generate common
methods like __init__ and __repr__, making the code cleaner and easier to read.

These models represent:
- Course terms (semesters)
- Section schedules (lectures and labs)
- Assessment tasks (assignments, exams, etc.)
- Study plan items
- User selections
- Cache entries
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import List, Optional, Tuple, Dict


@dataclass
class CourseTerm:
    """Represents the academic term/semester for the course.
    
    This class stores information about when the course takes place.
    It includes the term name (like "Fall 2026"), the start and end dates,
    and the timezone (defaults to America/Toronto for Western University).
    """
    term_name: str              # e.g., "Fall 2026", "Winter 2027"
    start_date: date            # First day of term (when classes start)
    end_date: date              # Last day of term (when classes end)
    timezone: str = "America/Toronto"  # Timezone for the course (Western University uses Toronto time)


@dataclass
class SectionOption:
    """Represents a lecture or lab section with its schedule.
    
    A section is a specific time slot for a course. For example, a course
    might have Lecture Section 001 on Monday/Wednesday/Friday from 10:30-11:30 AM.
    This class stores all that information.
    """
    section_type: str           # "Lecture" or "Lab" - what type of section this is
    section_id: str             # Section number like "001", "002", or "" if not specified
    days_of_week: List[int]     # Days when this section meets: 0=Monday, 1=Tuesday, ..., 6=Sunday
    start_time: time            # When the section starts (e.g., 10:30 AM)
    end_time: time              # When the section ends (e.g., 11:30 AM)
    location: Optional[str] = None  # Room/building where it meets (e.g., "UC 202"), or None if unknown
    date_range: Optional[Tuple[date, date]] = None  # Custom date range if different from term dates


@dataclass
class AssessmentTask:
    """Represents an assessment item (assignment, quiz, exam, etc.).
    
    This class stores information about any graded work in the course.
    It can have either an absolute due date (due_datetime) or a relative rule
    (due_rule) that needs to be resolved later. The confidence score indicates
    how certain we are that the extracted information is correct.
    """
    title: str                  # Assessment name/title (e.g., "Assignment 1", "Final Exam")
    type: str                   # Type of assessment: "assignment", "lab_report", "quiz", "midterm", "final", "project", "other"
    weight_percent: Optional[float] = None  # How much this assessment is worth (e.g., 15.0 means 15% of final grade)
    due_datetime: Optional[datetime] = None  # When it's due (absolute date and time), or None if we have a rule instead
    due_rule: Optional[str] = None  # Relative rule text (e.g., "24 hours after lab") - needs to be resolved to a datetime
    rule_anchor: Optional[str] = None  # What the rule is based on: "lab", "tutorial", or "lecture"
    confidence: float = 0.0     # How confident we are in the extraction (0.0 = not confident, 1.0 = very confident)
    source_evidence: Optional[str] = None  # Where we found this info (page number and text snippet for debugging)
    needs_review: bool = False  # True if the information is ambiguous or missing critical data (user should review)


@dataclass
class StudyPlanItem:
    """Represents a study plan event for an assessment."""
    task_id: str                # Reference to AssessmentTask (title or unique ID)
    start_studying_datetime: datetime  # When to start studying
    due_datetime: datetime      # Assessment due date/time


@dataclass
class ExtractedCourseData:
    """Container for all extracted data from PDF."""
    term: CourseTerm
    lecture_sections: List[SectionOption]
    lab_sections: List[SectionOption]
    assessments: List[AssessmentTask]
    course_code: Optional[str] = None  # e.g., "CS 101"
    course_name: Optional[str] = None  # e.g., "Introduction to Computer Science"


@dataclass
class UserSelections:
    """Stores user choices for section selection."""
    selected_lecture_section: Optional[SectionOption] = None
    selected_lab_section: Optional[SectionOption] = None
    assessment_overrides: Dict[str, AssessmentTask] = field(default_factory=dict)  # User-corrected assessments


@dataclass
class CacheEntry:
    """Represents a cached result."""
    pdf_hash: str               # SHA-256 hash of PDF
    extracted_data: ExtractedCourseData
    user_selections: UserSelections
    generated_ics: str          # .ics file content as string
    timestamp: datetime         # When cached


# Serialization helpers for JSON conversion

def serialize_date(d: date) -> str:
    """Convert date to ISO format string."""
    return d.isoformat()


def deserialize_date(s: str) -> date:
    """Convert ISO format string to date."""
    return date.fromisoformat(s)


def serialize_datetime(dt: datetime) -> str:
    """Convert datetime to ISO format string."""
    return dt.isoformat()


def deserialize_datetime(s: str) -> datetime:
    """Convert ISO format string to datetime."""
    return datetime.fromisoformat(s)


def serialize_time(t: time) -> str:
    """Convert time to HH:MM:SS string."""
    return t.isoformat()


def deserialize_time(s: str) -> time:
    """Convert HH:MM:SS string to time."""
    return time.fromisoformat(s)


