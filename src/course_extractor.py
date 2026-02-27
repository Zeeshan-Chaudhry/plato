"""
Course Information Extraction Module

Uses layout-based ranking to extract course code and title.
"""

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple
from pathlib import Path

from .document_structure import DocumentStructure, TextBlock


@dataclass
class CourseTitleCandidate:
    """A candidate for course title with ranking features."""
    text: str
    page_num: int
    y_position: float
    font_size: float
    is_bold: bool
    
    # Ranking features
    near_course_code: bool = False
    in_top_third: bool = False
    has_allowed_chars: bool = True
    has_negative_keywords: bool = False
    
    # Score
    score: float = 0.0
    
    @property
    def length_valid(self) -> bool:
        return 8 <= len(self.text) <= 120


class CourseInfoExtractor:
    """
    Extracts course code and title using layout-based ranking.
    """
    
    # Course code pattern
    COURSE_CODE_PATTERN = re.compile(
        r'\b([A-Z]{2,5})\s*[\-\/]?\s*(\d{3,4}[A-Z]?(?:/[A-Z])?)\b'
    )
    
    # Negative keywords (should not be in title)
    NEGATIVE_KEYWORDS = {
        'course outline', 'syllabus', 'faculty of', 'department of',
        'university', 'western', 'school of', 'course information',
        'fall 2', 'winter 2', 'summer 2', 'academic year',
        'www.', 'http', '@', 'email', 'phone', 'office hours',
        'instructor', 'professor', 'dr.', 'outline', 'calendar',
        'department', 'faculty', 'engineering', 'sciences', 'science',
        'arts', 'humanities', 'london', 'ontario', 'canada',
        'academic', 'information', 'acknowledgment', 'acknowledgement'
    }
    
    # Words that are OK by themselves (actual course titles)
    TITLE_WORDS = {
        'introduction', 'methods', 'analysis', 'theory', 'principles',
        'fundamentals', 'advanced', 'applied', 'computational', 'organic',
        'inorganic', 'biochemistry', 'physiology', 'anatomy', 'calculus',
        'algebra', 'statistics', 'programming', 'systems', 'design'
    }
    
    # Allowed characters in title
    ALLOWED_TITLE_CHARS = re.compile(r'^[A-Za-z\s\-\:&,\'\"\(\)]+$')
    
    def __init__(self, doc_structure: DocumentStructure):
        self.doc = doc_structure
        self.course_code: Optional[str] = None
        self.course_code_position: Optional[Tuple[int, float]] = None  # (page, y)
        
    def extract(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract course code and title.
        
        Returns:
            Tuple of (course_code, course_title)
        """
        # Step 1: Find course code
        self.course_code = self._extract_course_code()
        
        # Step 2: Find title candidates
        candidates = self._find_title_candidates()
        
        # Step 3: Score and rank candidates
        for candidate in candidates:
            self._score_candidate(candidate)
        
        # Step 4: Select best candidate
        if not candidates:
            return self.course_code, None
        
        candidates.sort(key=lambda c: c.score, reverse=True)
        best = candidates[0]
        
        # If score too low, return None
        if best.score < 0.3:
            return self.course_code, None
        
        return self.course_code, best.text
    
    def _extract_course_code(self) -> Optional[str]:
        """Extract course code from first page."""
        # Look in first page blocks
        first_page_blocks = [b for b in self.doc.blocks if b.page_num == 1]
        
        for block in first_page_blocks:
            match = self.COURSE_CODE_PATTERN.search(block.text)
            if match:
                code = f"{match.group(1)} {match.group(2)}"
                self.course_code_position = (block.page_num, block.y0)
                return code
        
        return None
    
    def _find_title_candidates(self) -> List[CourseTitleCandidate]:
        """Find potential course title candidates from first page."""
        candidates = []
        
        # Only look at first page
        first_page_blocks = [b for b in self.doc.blocks if b.page_num == 1]
        
        if not first_page_blocks:
            return candidates
        
        # Calculate font size percentiles for first page
        font_sizes = [b.font_size for b in first_page_blocks if b.font_size > 0]
        if not font_sizes:
            return candidates
        
        avg_font = sum(font_sizes) / len(font_sizes)
        max_font = max(font_sizes)
        
        # Calculate page height (for top-third check)
        page_info = self.doc.pages[0] if self.doc.pages else None
        page_height = page_info.get('height', 800) if page_info else 800
        top_third_y = page_height / 3
        
        for block in first_page_blocks:
            text = block.text.strip()
            
            # Skip very short or very long text
            if len(text) < 8 or len(text) > 120:
                continue
            
            # Skip if contains only numbers/special chars
            if not re.search(r'[A-Za-z]{3,}', text):
                continue
            
            # Check for negative keywords
            has_negative = any(kw in text.lower() for kw in self.NEGATIVE_KEYWORDS)
            
            # Check for allowed characters
            has_allowed = bool(self.ALLOWED_TITLE_CHARS.match(text))
            
            # Check if in top third
            in_top = block.y0 < top_third_y
            
            # Check if near course code
            near_code = False
            if self.course_code_position:
                code_page, code_y = self.course_code_position
                if block.page_num == code_page:
                    near_code = abs(block.y0 - code_y) < 100
            
            candidate = CourseTitleCandidate(
                text=text,
                page_num=block.page_num,
                y_position=block.y0,
                font_size=block.font_size,
                is_bold=block.is_bold,
                near_course_code=near_code,
                in_top_third=in_top,
                has_allowed_chars=has_allowed,
                has_negative_keywords=has_negative
            )
            candidates.append(candidate)
        
        return candidates
    
    def _score_candidate(self, candidate: CourseTitleCandidate):
        """Score a title candidate based on features."""
        score = 0.0
        
        text_lower = candidate.text.lower().strip()
        words = candidate.text.split()
        
        # Strong negative: has negative keywords
        if candidate.has_negative_keywords:
            score -= 0.8  # Increased penalty
        
        # Strong negative: is just a single generic word
        single_word_generic = {
            'department', 'faculty', 'engineering', 'sciences', 'science',
            'academic', 'information', 'arts', 'humanities', 'medicine'
        }
        if len(words) == 1 and text_lower in single_word_generic:
            score -= 1.0  # Very strong penalty
        
        # Positive: large font size
        if self.doc.blocks:
            first_page_fonts = [b.font_size for b in self.doc.blocks 
                               if b.page_num == 1 and b.font_size > 0]
            if first_page_fonts:
                avg_font = sum(first_page_fonts) / len(first_page_fonts)
                if candidate.font_size > avg_font * 1.3:
                    score += 0.3
                elif candidate.font_size > avg_font * 1.1:
                    score += 0.15
        
        # Positive: is bold
        if candidate.is_bold:
            score += 0.15
        
        # Positive: near course code
        if candidate.near_course_code:
            score += 0.25
        
        # Positive: in top third of page
        if candidate.in_top_third:
            score += 0.15
        
        # Positive: only allowed characters
        if candidate.has_allowed_chars:
            score += 0.1
        
        # Positive: valid length
        if candidate.length_valid:
            score += 0.1
        
        # Positive: looks like a title (starts with capital, multiple words)
        if len(words) >= 2 and candidate.text[0].isupper():
            score += 0.1
        
        # Strong positive: contains title keywords
        if any(tw in text_lower for tw in self.TITLE_WORDS):
            score += 0.25
        
        # Penalty: looks like a sentence (too many words, ends with period)
        if len(words) > 12 or candidate.text.endswith('.'):
            score -= 0.2
        
        # Penalty: all uppercase (likely a header, not a title)
        if candidate.text == candidate.text.upper() and len(words) <= 2:
            score -= 0.15
        
        candidate.score = score
    
    def get_debug_info(self) -> dict:
        """Get debug information."""
        candidates = self._find_title_candidates()
        for c in candidates:
            self._score_candidate(c)
        
        return {
            'course_code': self.course_code,
            'course_code_position': self.course_code_position,
            'candidates': [
                {
                    'text': c.text[:50] + '...' if len(c.text) > 50 else c.text,
                    'score': c.score,
                    'font_size': c.font_size,
                    'is_bold': c.is_bold,
                    'in_top_third': c.in_top_third,
                    'near_code': c.near_course_code,
                    'has_negative': c.has_negative_keywords
                }
                for c in sorted(candidates, key=lambda x: x.score, reverse=True)[:10]
            ]
        }


def extract_course_info(doc_structure: DocumentStructure) -> Tuple[Optional[str], Optional[str]]:
    """Convenience function to extract course info."""
    extractor = CourseInfoExtractor(doc_structure)
    return extractor.extract()

