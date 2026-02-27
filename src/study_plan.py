"""
Study plan generation module.

Generates "start studying" events for assessments based on weights and lead times.
"""

from datetime import datetime, timedelta
from typing import List, Optional
from .models import AssessmentTask, StudyPlanItem


class StudyPlanGenerator:
    """Generates study plan events for assessments."""
    
    def __init__(self, lead_time_mapping: Optional[dict] = None):
        """Initialize study plan generator.
        
        Args:
            lead_time_mapping: Optional dict mapping weight_percent to days of lead time.
                              If None, uses default mapping.
        """
        if lead_time_mapping is None:
            # Default mapping per CLARIFYING_QUESTIONS.md:
            # 0-5%: 3 days, 6-10%: 7 days, 11-20%: 14 days, 21-30%: 21 days, 31%+: 28 days
            self.lead_time_mapping = {
                5: 3,      # 0-5% -> 3 days
                10: 7,     # 6-10% -> 7 days
                20: 14,    # 11-20% -> 14 days
                30: 21,    # 21-30% -> 21 days
                50: 28,    # 31%+ -> 28 days
            }
        else:
            self.lead_time_mapping = lead_time_mapping
    
    def get_default_mapping_display(self) -> dict:
        """Get default lead-time mapping for display to user.
        
        Returns:
            Dict with ranges and days for user confirmation
        """
        return {
            "0-5%": 3,
            "6-10%": 7,
            "11-20%": 14,
            "21-30%": 21,
            "31%+": 28,
            "Finals": 28
        }
    
    def generate_study_plan(self, assessments: List[AssessmentTask],
                           user_lead_times: Optional[dict] = None) -> List[StudyPlanItem]:
        """Generate study plan items for all assessments.
        
        Args:
            assessments: List of assessments
            user_lead_times: Optional dict mapping assessment title to days of lead time
                           (for user-specified lead times)
        
        Returns:
            List of StudyPlanItem objects
        """
        study_plan = []
        
        for assessment in assessments:
            if not assessment.due_datetime:
                # Skip assessments without due dates
                continue
            
            # Determine lead time
            lead_time_days = self._get_lead_time(assessment, user_lead_times)
            
            if lead_time_days is None:
                # Cannot determine lead time - skip or mark for review
                continue
            
            # Calculate start studying datetime
            start_studying = assessment.due_datetime - timedelta(days=lead_time_days)
            
            # Ensure start is not in the past (relative to term start)
            # This is a simple check - may need refinement
            
            study_item = StudyPlanItem(
                task_id=assessment.title,
                start_studying_datetime=start_studying,
                due_datetime=assessment.due_datetime
            )
            study_plan.append(study_item)
        
        return study_plan
    
    def _get_lead_time(self, assessment: AssessmentTask,
                      user_lead_times: Optional[dict]) -> Optional[int]:
        """Get lead time in days for an assessment.
        
        Args:
            assessment: Assessment task
            user_lead_times: User-specified lead times
            
        Returns:
            Lead time in days, or None if cannot determine (requires user review)
        """
        # Check user-specified lead times first (individual overrides)
        if user_lead_times and assessment.title in user_lead_times:
            return user_lead_times[assessment.title]
        
        # Handle finals specially
        if assessment.type == "final":
            # Check if custom mapping has Finals override
            if self.lead_time_mapping and 50 in self.lead_time_mapping:
                return self.lead_time_mapping[50]
            return 28  # Default: Finals: 28 days
        
        # Use weight-based mapping
        if assessment.weight_percent is not None:
            weight = assessment.weight_percent
            
            # Use custom mapping if available, otherwise use defaults
            if self.lead_time_mapping:
                # Map to appropriate threshold
                if weight <= 5:
                    return self.lead_time_mapping.get(5, 3)
                elif weight <= 10:
                    return self.lead_time_mapping.get(10, 7)
                elif weight <= 20:
                    return self.lead_time_mapping.get(20, 14)
                elif weight <= 30:
                    return self.lead_time_mapping.get(30, 21)
                else:  # 31%+
                    return self.lead_time_mapping.get(50, 28)
            else:
                # Use default mapping
                if weight <= 5:
                    return 3
                elif weight <= 10:
                    return 7
                elif weight <= 20:
                    return 14
                elif weight <= 30:
                    return 21
                else:  # 31%+
                    return 28
        
        # Missing weight: return None to require user review
        # Per CLARIFYING_QUESTIONS.md: "Always require user review"
        return None
    
    def calculate_lead_time_from_weight(self, weight_percent: float) -> int:
        """Calculate lead time from weight percentage.
        
        Args:
            weight_percent: Assessment weight as percentage
            
        Returns:
            Lead time in days
        """
        if weight_percent in self.lead_time_mapping:
            return self.lead_time_mapping[weight_percent]
        
        # Interpolate or use closest
        closest_weight = min(
            self.lead_time_mapping.keys(),
            key=lambda x: abs(x - weight_percent)
        )
        return self.lead_time_mapping[closest_weight]

