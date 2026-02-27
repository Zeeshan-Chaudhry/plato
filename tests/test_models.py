"""Unit tests for data models."""

import pytest
from datetime import date, datetime, time
from src.models import (
    CourseTerm, SectionOption, AssessmentTask, StudyPlanItem,
    serialize_date, deserialize_date,
    serialize_datetime, deserialize_datetime,
    serialize_time, deserialize_time
)


def test_course_term():
    """Test CourseTerm model."""
    term = CourseTerm(
        term_name="Fall 2026",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 15)
    )
    assert term.term_name == "Fall 2026"
    assert term.start_date == date(2026, 9, 1)
    assert term.end_date == date(2026, 12, 15)
    assert term.timezone == "America/Toronto"


def test_section_option():
    """Test SectionOption model."""
    section = SectionOption(
        section_type="Lecture",
        section_id="001",
        days_of_week=[0, 2, 4],  # Mon, Wed, Fri
        start_time=time(10, 30),
        end_time=time(11, 30),
        location="UC 202"
    )
    assert section.section_type == "Lecture"
    assert section.section_id == "001"
    assert section.days_of_week == [0, 2, 4]
    assert section.location == "UC 202"


def test_assessment_task():
    """Test AssessmentTask model."""
    assessment = AssessmentTask(
        title="Assignment 1",
        type="assignment",
        weight_percent=15.0,
        due_datetime=datetime(2026, 10, 15, 23, 59),
        confidence=0.9
    )
    assert assessment.title == "Assignment 1"
    assert assessment.type == "assignment"
    assert assessment.weight_percent == 15.0
    assert assessment.due_datetime == datetime(2026, 10, 15, 23, 59)
    assert assessment.confidence == 0.9


def test_study_plan_item():
    """Test StudyPlanItem model."""
    study_item = StudyPlanItem(
        task_id="Assignment 1",
        start_studying_datetime=datetime(2026, 10, 1, 9, 0),
        due_datetime=datetime(2026, 10, 15, 23, 59)
    )
    assert study_item.task_id == "Assignment 1"
    assert study_item.start_studying_datetime < study_item.due_datetime


def test_serialization():
    """Test serialization helpers."""
    test_date = date(2026, 10, 15)
    assert serialize_date(test_date) == "2026-10-15"
    assert deserialize_date("2026-10-15") == test_date
    
    test_datetime = datetime(2026, 10, 15, 23, 59)
    serialized = serialize_datetime(test_datetime)
    assert deserialize_datetime(serialized) == test_datetime
    
    test_time = time(10, 30)
    assert serialize_time(test_time) == "10:30:00"
    assert deserialize_time("10:30:00") == test_time







