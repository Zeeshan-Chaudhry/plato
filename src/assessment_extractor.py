"""
Assessment Extraction Module

Implements a formal pipeline for assessment extraction:
1. Candidate Generation (high recall)
2. Candidate Scoring (precision)
3. Constrained Selection (fix over-extraction)
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Set, Union
from datetime import datetime
from pathlib import Path

from .document_structure import DocumentStructure, Section, DetectedTable
from .models import AssessmentTask

# Type for pdf_path
PathLike = Union[str, Path]


@dataclass
class AssessmentCandidate:
    """A candidate assessment with scoring metadata."""
    title: str
    weight: Optional[float]
    due_date: Optional[datetime] = None
    due_rule: Optional[str] = None
    
    # Provenance
    source_method: str = "unknown"  # "table", "reconstructed_table", "inline"
    page_num: int = 0
    raw_evidence: str = ""
    
    # Scoring
    score: float = 0.0
    is_bonus: bool = False
    rejection_reason: Optional[str] = None
    
    # Features for scoring
    has_assessment_noun: bool = False
    is_in_evaluation_section: bool = False
    is_in_table: bool = False
    looks_like_title: bool = True
    has_policy_words: bool = False


class PolicyWindowFilter:
    """
    Filters out false positive assessments using a token window approach.
    
    Inspects ±N tokens around a percentage and rejects if the window
    contains policy-related terms.
    """
    
    POLICY_TERMS = {
        'passing', 'pass', 'minimum', 'eligible', 'eligibility', 'must',
        'achieve', 'obtain', 'requirement', 'required', 'weighted', 
        'average', 'threshold', 'fail', 'reweighted', 'hurdle',
        'grade', 'grading', 'at least', 'least', 'need', 'needs'
    }
    
    POLICY_PHRASES = [
        r'to\s+(?:be\s+)?eligible',
        r'to\s+obtain',
        r'to\s+pass',
        r'must\s+achieve',
        r'must\s+obtain',
        r'must\s+have',
        r'passing\s+grade',
        r'minimum\s+(?:grade|mark|score)',
        r'weighted\s+average',
        r'at\s+least',
        r'will\s+be\s+reweighted',
        r'result\s+in',
        r'a\s+(?:grade|mark)\s+of',
    ]
    
    def __init__(self, window_size: int = 12):
        self.window_size = window_size
    
    def is_policy_context(self, text: str, percent_position: int) -> bool:
        """
        Check if a percentage at given position is in a policy context.
        
        Args:
            text: Full text to analyze
            percent_position: Character position of the percentage
            
        Returns:
            True if the percentage appears to be policy-related
        """
        # Get token window around the percentage
        words = text.lower().split()
        
        # Find which word contains the percentage
        char_pos = 0
        word_idx = 0
        for i, word in enumerate(words):
            if char_pos + len(word) >= percent_position:
                word_idx = i
                break
            char_pos += len(word) + 1  # +1 for space
        
        # Get window of tokens
        start_idx = max(0, word_idx - self.window_size)
        end_idx = min(len(words), word_idx + self.window_size + 1)
        window = words[start_idx:end_idx]
        window_text = " ".join(window)
        
        # Check for policy terms
        for term in self.POLICY_TERMS:
            if term in window:
                return True
        
        # Check for policy phrases
        for phrase in self.POLICY_PHRASES:
            if re.search(phrase, window_text):
                return True
        
        return False
    
    def filter_candidate(self, candidate: AssessmentCandidate) -> bool:
        """
        Determine if a candidate should be rejected.
        
        Returns:
            True if candidate should be rejected (is policy text)
        """
        evidence = candidate.raw_evidence.lower()
        
        # Find percentage position in evidence
        percent_match = re.search(r'\d+(?:\.\d+)?%', evidence)
        if percent_match:
            if self.is_policy_context(evidence, percent_match.start()):
                candidate.rejection_reason = "Policy context (window filter)"
                return True
        
        # Also check title for policy-like patterns
        title_lower = candidate.title.lower()
        
        # Reject if title starts with policy words
        policy_starters = [
            'to be', 'to obtain', 'to pass', 'must', 'should', 'will be',
            'students', 'you must', 'a minimum', 'the minimum', 'minimum',
            'at least', 'achieve', 'eligible'
        ]
        for starter in policy_starters:
            if title_lower.startswith(starter):
                candidate.rejection_reason = f"Title starts with policy word: {starter}"
                return True
        
        # Reject sentence-like titles (contain verb phrases)
        verb_patterns = [
            r'\b(?:is|are|was|were|will|shall|should|must|may|can)\b.*\b(?:be|have|get|receive)\b',
            r'\bto\s+(?:be|have|get|receive|pass|obtain|achieve)\b',
        ]
        for pattern in verb_patterns:
            if re.search(pattern, title_lower):
                candidate.rejection_reason = "Title is sentence-like"
                return True
        
        return False


class AssessmentCandidateGenerator:
    """
    Generates assessment candidates from document structure.
    High recall - aims to find all possible assessments.
    """
    
    ASSESSMENT_NOUNS = {
        'exam', 'examination', 'midterm', 'final', 'test', 'quiz',
        'assignment', 'homework', 'hw', 'project', 'lab', 'laboratory',
        'participation', 'attendance', 'presentation', 'essay', 'report',
        'paper', 'portfolio', 'tutorial', 'exercise', 'practicum',
        'rotation', 'clinical', 'practical', 'total'  # Added 'total' for grouped items
    }
    
    BONUS_INDICATORS = {
        'bonus', 'extra credit', 'optional', 'up to', 'additional'
    }
    
    # Patterns that indicate this is NOT an assessment
    GARBAGE_PATTERNS = [
        r'^[a-z]\.\s',  # Starts with "a. ", "b. ", etc. (learning outcomes)
        r'^\d+\.\s*[a-z]',  # Starts with "1. understand" etc.
        r'^(understand|design|apply|analyze|demonstrate|develop|explain)',  # Learning outcome verbs
        r'^(course|academic|student|you|we|the|a|an)\s',  # Sentence starters
        r'^(not|need|must|should|will|may|can)',  # Modal verbs
        r'(submitted|request|consideration|accommodation)',  # Policy words
        r'^(office|room|email|phone|www\.|http)',  # Contact info
        r'^(january|february|march|april|may|june|july|august|september|october|november|december)\s*\d',  # Dates
        r'^(mon|tue|wed|thu|fri|sat|sun)',  # Days
        r'reading\s*week',  # Reading week
        r'^(classes|exam\s*period)',  # Schedule items
        r'^\d+%$',  # Just a percentage
    ]
    
    def __init__(self, doc_structure: DocumentStructure):
        self.doc = doc_structure
        self.evaluation_section = doc_structure.get_evaluation_section()
        
    def generate_candidates(self) -> List[AssessmentCandidate]:
        """Generate all assessment candidates."""
        candidates = []
        
        # Source 1: Tables (pdfplumber and reconstructed)
        candidates.extend(self._from_tables())
        
        # Source 2: Inline patterns
        candidates.extend(self._from_inline_patterns())
        
        # Enrich all candidates with features
        for candidate in candidates:
            self._compute_features(candidate)
        
        return candidates
    
    def _from_tables(self) -> List[AssessmentCandidate]:
        """Extract candidates from tables."""
        candidates = []
        
        for table in self.doc.tables:
            if not self._is_assessment_table(table):
                continue
            
            # Find column mappings
            col_map = self._map_columns(table)
            if 'name' not in col_map:
                continue
            
            # Skip header row, extract candidates
            for row_idx, row in enumerate(table.rows[1:], 1):
                if len(row) <= col_map['name']:
                    continue
                
                title = self._clean_cell(row[col_map['name']])
                if not title or len(title) < 3:
                    continue
                
                # Skip summary rows
                if self._is_summary_row(title):
                    continue
                
                # Skip garbage titles
                if self._is_garbage_title(title):
                    continue
                
                # Extract weight
                weight = None
                if 'weight' in col_map and len(row) > col_map['weight']:
                    weight = self._extract_weight(row[col_map['weight']])
                
                # Extract date
                due_date = None
                due_rule = None
                if 'date' in col_map and len(row) > col_map['date']:
                    due_date, due_rule = self._extract_date(row[col_map['date']])
                
                # Check for bonus
                is_bonus = any(ind in title.lower() for ind in self.BONUS_INDICATORS)
                
                candidate = AssessmentCandidate(
                    title=title,
                    weight=weight,
                    due_date=due_date,
                    due_rule=due_rule,
                    source_method=table.table_type,
                    page_num=table.page_num,
                    raw_evidence=" | ".join(str(c) for c in row),
                    is_bonus=is_bonus,
                    is_in_table=True
                )
                candidates.append(candidate)
        
        return candidates
    
    def _from_inline_patterns(self) -> List[AssessmentCandidate]:
        """Extract candidates from inline text patterns."""
        candidates = []
        
        # Get text from evaluation section (or full doc if not found)
        if self.evaluation_section:
            text = self.doc.get_text_in_section(self.evaluation_section)
        else:
            text = "\n".join(b.text for b in self.doc.blocks)
        
        # Pattern 1: "Assignment 1: 25%" or "Midterm Test 25%"
        pattern1 = re.compile(
            r'([A-Z][A-Za-z\s]+(?:\d+)?)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*%',
            re.MULTILINE
        )
        
        for match in pattern1.finditer(text):
            title = match.group(1).strip()
            weight = float(match.group(2))
            
            # Check if this is a plausible assessment
            if not self._has_assessment_noun(title):
                continue
            
            candidate = AssessmentCandidate(
                title=title,
                weight=weight,
                source_method="inline",
                raw_evidence=match.group(0),
                is_in_evaluation_section=self.evaluation_section is not None
            )
            candidates.append(candidate)
        
        # Pattern 2: "25% - Final Exam" or "25% Final Exam"
        pattern2 = re.compile(
            r'(\d+(?:\.\d+)?)\s*%\s*[:\-]?\s*([A-Z][A-Za-z\s]+)',
            re.MULTILINE
        )
        
        for match in pattern2.finditer(text):
            weight = float(match.group(1))
            title = match.group(2).strip()
            
            if not self._has_assessment_noun(title):
                continue
            
            candidate = AssessmentCandidate(
                title=title,
                weight=weight,
                source_method="inline",
                raw_evidence=match.group(0),
                is_in_evaluation_section=self.evaluation_section is not None
            )
            candidates.append(candidate)
        
        # Pattern 3: Text-based table format - "Participation 10% Description"
        # This handles formats like:
        # "Participation 10% Participation in class activities"
        # "Midterm 25% Short and long answer"
        pattern3 = re.compile(
            r'^([A-Z][A-Za-z\-\s]{2,25}?)\s+(\d+(?:\.\d+)?)\s*%',
            re.MULTILINE
        )
        
        for match in pattern3.finditer(text):
            title = match.group(1).strip()
            weight = float(match.group(2))
            
            # Skip if title is garbage
            if self._is_garbage_title(title):
                continue
            
            # Skip if we already have this (from pattern 1/2)
            if any(c.title.lower() == title.lower() for c in candidates):
                continue
            
            candidate = AssessmentCandidate(
                title=title,
                weight=weight,
                source_method="inline_table",
                raw_evidence=match.group(0),
                is_in_evaluation_section=self.evaluation_section is not None
            )
            candidates.append(candidate)
        
        # Pattern 4: Lines like "Final Exam 40%" or "Labs 10%"
        # More permissive pattern for shorter titles
        pattern4 = re.compile(
            r'\b((?:Final\s+)?(?:Exam|Midterm|Quiz|Test|Lab|Assignment|Participation|Research|Project)(?:s|ination)?(?:\s+\d+)?)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*%',
            re.IGNORECASE
        )
        
        for match in pattern4.finditer(text):
            title = match.group(1).strip()
            weight = float(match.group(2))
            
            # Normalize title
            title = title.title()  # Capitalize properly
            
            # Skip if we already have this
            title_lower = title.lower()
            if any(title_lower in c.title.lower() or c.title.lower() in title_lower 
                   for c in candidates if c.weight == weight):
                continue
            
            candidate = AssessmentCandidate(
                title=title,
                weight=weight,
                source_method="inline_keyword",
                raw_evidence=match.group(0),
                is_in_evaluation_section=self.evaluation_section is not None,
                has_assessment_noun=True  # Pattern guarantees this
            )
            candidates.append(candidate)
        
        return candidates
    
    def _is_assessment_table(self, table: DetectedTable) -> bool:
        """Determine if a table is an assessment/grading table."""
        if not table.headers:
            return False
        
        header_text = " ".join(table.headers).lower()
        
        # Assessment table keywords
        keywords = [
            'assessment', 'evaluation', 'grading', 'weight', '%',
            'grade', 'component', 'worth', 'weighting'
        ]
        
        return any(kw in header_text for kw in keywords)
    
    def _map_columns(self, table: DetectedTable) -> dict:
        """Map table columns to semantic meaning."""
        col_map = {}
        
        for idx, header in enumerate(table.headers):
            header_lower = header.lower() if header else ""
            
            # Name column
            if any(kw in header_lower for kw in 
                   ['assessment', 'component', 'item', 'task', 'name', 'activity']):
                col_map['name'] = idx
            
            # Weight column
            elif any(kw in header_lower for kw in 
                     ['weight', '%', 'worth', 'value', 'percentage']):
                col_map['weight'] = idx
            
            # Date column (prioritize "due" over "assigned")
            elif 'due' in header_lower:
                col_map['date'] = idx
            elif 'date' in header_lower and 'date' not in col_map:
                col_map['date'] = idx
        
        # If no explicit name column, assume first column
        if 'name' not in col_map and table.headers:
            col_map['name'] = 0
        
        return col_map
    
    def _clean_cell(self, cell: str) -> str:
        """Clean a table cell."""
        if not cell:
            return ""
        
        text = str(cell).strip()
        # Replace newlines with spaces
        text = text.replace('\n', ' ').replace('\r', ' ')
        # Remove leading numbers/bullets
        text = re.sub(r'^[\d\.\)\:\-]+\s*', '', text)
        # Collapse whitespace
        text = ' '.join(text.split())
        return text
    
    def _is_garbage_title(self, title: str) -> bool:
        """Check if a title is garbage (not a real assessment)."""
        title_lower = title.lower().strip()
        
        # Check against garbage patterns
        for pattern in self.GARBAGE_PATTERNS:
            if re.search(pattern, title_lower, re.IGNORECASE):
                return True
        
        # Too short (less than 3 chars of actual content)
        if len(re.sub(r'\W', '', title)) < 3:
            return True
        
        # All lowercase and no assessment nouns (likely a sentence fragment)
        if title == title.lower() and not self._has_assessment_noun(title):
            return True
        
        # Contains too many special characters
        special_ratio = len(re.findall(r'[^A-Za-z0-9\s\-\(\):]', title)) / max(len(title), 1)
        if special_ratio > 0.3:
            return True
        
        return False
    
    def _extract_weight(self, cell: str) -> Optional[float]:
        """Extract weight percentage from cell."""
        if not cell:
            return None
        
        # Look for percentage
        match = re.search(r'(\d+(?:\.\d+)?)\s*%?', str(cell))
        if match:
            value = float(match.group(1))
            if 0 < value <= 100:
                return value
        return None
    
    def _extract_date(self, cell: str) -> Tuple[Optional[datetime], Optional[str]]:
        """Extract date or date rule from cell."""
        if not cell:
            return None, None
        
        cell_str = str(cell).strip().lower()
        
        # Check for relative rules
        relative_keywords = ['after', 'before', 'following', 'hrs', 'hours', 'days', 'week']
        if any(kw in cell_str for kw in relative_keywords):
            return None, cell_str
        
        # Try to parse actual date
        try:
            import dateparser
            parsed = dateparser.parse(cell_str)
            return parsed, None
        except Exception:
            return None, None
    
    def _is_summary_row(self, title: str) -> bool:
        """Check if this is a summary/total row."""
        title_lower = title.lower().strip()
        
        summary_patterns = [
            r'^total$',
            r'^course\s+total$',
            r'^grand\s+total$',
            r'^overall$',
            r'^sum$'
        ]
        
        return any(re.match(p, title_lower) for p in summary_patterns)
    
    def _has_assessment_noun(self, title: str) -> bool:
        """Check if title contains an assessment noun."""
        title_lower = title.lower()
        return any(noun in title_lower for noun in self.ASSESSMENT_NOUNS)
    
    def _compute_features(self, candidate: AssessmentCandidate):
        """Compute scoring features for a candidate."""
        candidate.has_assessment_noun = self._has_assessment_noun(candidate.title)
        candidate.is_in_evaluation_section = (
            self.evaluation_section is not None and 
            (candidate.source_method in ["table", "reconstructed_table"] or
             candidate.is_in_evaluation_section)
        )


class AssessmentScorer:
    """Scores assessment candidates based on features."""
    
    # Scoring weights
    WEIGHTS = {
        'has_weight': 0.3,
        'has_assessment_noun': 0.25,
        'is_in_evaluation_section': 0.2,
        'is_in_table': 0.15,
        'looks_like_title': 0.1
    }
    
    def score(self, candidate: AssessmentCandidate) -> float:
        """Compute confidence score for a candidate."""
        score = 0.0
        
        # Has valid weight (0-100%)
        if candidate.weight is not None and 0 < candidate.weight <= 100:
            score += self.WEIGHTS['has_weight']
        
        # Has assessment noun
        if candidate.has_assessment_noun:
            score += self.WEIGHTS['has_assessment_noun']
        
        # Is in evaluation section
        if candidate.is_in_evaluation_section:
            score += self.WEIGHTS['is_in_evaluation_section']
        
        # Is from table (more reliable)
        if candidate.is_in_table:
            score += self.WEIGHTS['is_in_table']
        
        # Looks like a title (not a sentence)
        if candidate.looks_like_title:
            score += self.WEIGHTS['looks_like_title']
        
        candidate.score = score
        return score


class ConstrainedSelector:
    """
    Selects the optimal subset of candidates to get close to 100%.
    
    Solves: maximize sum(confidence_score) 
            subject to: sum(weights) close to 100
    """
    
    def __init__(self, target: float = 100.0, tolerance: float = 10.0):
        self.target = target
        self.tolerance = tolerance
    
    def select(self, candidates: List[AssessmentCandidate]) -> List[AssessmentCandidate]:
        """
        Select optimal subset of candidates.
        
        Uses a greedy approach with backtracking for simplicity.
        """
        if not candidates:
            return []
        
        # Separate core and bonus candidates
        core = [c for c in candidates if not c.is_bonus and not c.rejection_reason]
        bonus = [c for c in candidates if c.is_bonus and not c.rejection_reason]
        
        # Check if core already sums to ~100
        core_total = sum(c.weight or 0 for c in core)
        
        if abs(core_total - self.target) <= self.tolerance:
            # Core is good, return core + bonus
            return core + bonus
        
        if core_total < self.target - self.tolerance:
            # Under-extraction - return all we have
            return core + bonus
        
        # Over-extraction - need to select subset
        # Sort by score (descending)
        sorted_core = sorted(core, key=lambda c: (c.score, c.weight or 0), reverse=True)
        
        # Find duplicates (same normalized title)
        seen_titles: Set[str] = set()
        deduplicated = []
        
        for candidate in sorted_core:
            norm_title = self._normalize_title(candidate.title)
            if norm_title in seen_titles:
                continue
            seen_titles.add(norm_title)
            deduplicated.append(candidate)
        
        # Greedy selection to get close to 100
        selected = []
        current_total = 0.0
        
        for candidate in deduplicated:
            weight = candidate.weight or 0
            if current_total + weight <= self.target + self.tolerance:
                selected.append(candidate)
                current_total += weight
        
        # If we still have room and bonus items, add them
        for b in bonus:
            selected.append(b)
        
        return selected
    
    def _normalize_title(self, title: str) -> str:
        """Normalize title for comparison."""
        norm = title.lower().strip()
        # Remove common prefixes
        norm = re.sub(r'^in[\s\-]class\s+', '', norm)
        # Remove numbers for comparison
        norm = re.sub(r'\d+', '#', norm)
        # Remove extra whitespace
        norm = ' '.join(norm.split())
        return norm


class AssessmentExtractor:
    """
    Main assessment extraction pipeline.
    
    Combines candidate generation, scoring, filtering, and selection.
    """
    
    def __init__(self, doc_structure: DocumentStructure, pdf_path: Optional[Path] = None):
        self.doc = doc_structure
        self.pdf_path = pdf_path
        self.generator = AssessmentCandidateGenerator(doc_structure)
        self.filter = PolicyWindowFilter()
        self.scorer = AssessmentScorer()
        self.selector = ConstrainedSelector()
        
        # Debug info
        self.all_candidates: List[AssessmentCandidate] = []
        self.rejected_candidates: List[AssessmentCandidate] = []
        self.selected_candidates: List[AssessmentCandidate] = []
    
    def extract(self) -> List[AssessmentTask]:
        """
        Extract assessments using the full pipeline.
        
        Returns:
            List of AssessmentTask objects
        """
        # Step 1: Generate candidates from document structure
        self.all_candidates = self.generator.generate_candidates()
        
        # Step 1b: Also try direct PDF text extraction for inline patterns
        if self.pdf_path:
            raw_candidates = self._extract_from_raw_pdf()
            self.all_candidates.extend(raw_candidates)
            
            # Step 1c: Try special patterns (e.g., "for up to X%")
            try:
                import pdfplumber
                with pdfplumber.open(str(self.pdf_path)) as pdf:
                    full_text = ""
                    for page in pdf.pages[:8]:
                        full_text += (page.extract_text() or "") + "\n"
                    special_candidates = self._extract_special_patterns(full_text)
                    self.all_candidates.extend(special_candidates)
            except Exception:
                pass
        
        # Step 2: Filter policy text
        filtered = []
        for candidate in self.all_candidates:
            if self.filter.filter_candidate(candidate):
                self.rejected_candidates.append(candidate)
            else:
                filtered.append(candidate)
        
        # Step 3: Score candidates
        for candidate in filtered:
            self.scorer.score(candidate)
        
        # Step 4: Select optimal subset
        self.selected_candidates = self.selector.select(filtered)
        
        # Step 5: Convert to AssessmentTask objects
        return self._to_assessment_tasks(self.selected_candidates)
    
    def _extract_from_raw_pdf(self) -> List[AssessmentCandidate]:
        """Extract candidates directly from raw PDF text (not document structure).
        
        This helps with PDFs where the document structure extraction breaks
        text into individual words.
        """
        try:
            import pdfplumber
        except ImportError:
            return []
        
        candidates = []
        
        try:
            with pdfplumber.open(str(self.pdf_path)) as pdf:
                # Get full text from each page
                full_text = ""
                for page in pdf.pages[:8]:  # First 8 pages
                    page_text = page.extract_text() or ""
                    full_text += page_text + "\n"
                
                # Pattern for text-based grade tables:
                # "Participation 10% Description"
                # "Midterm 25% Short and long answer"
                pattern = re.compile(
                    r'^([A-Z][A-Za-z\s\-]+?)\s+(\d+(?:\.\d+)?)\s*%',
                    re.MULTILINE
                )
                
                for match in pattern.finditer(full_text):
                    title = match.group(1).strip()
                    weight = float(match.group(2))
                    
                    # Skip very short titles
                    if len(title) < 3:
                        continue
                    
                    # Skip if title is garbage
                    if self._is_garbage_raw_title(title):
                        continue
                    
                    candidate = AssessmentCandidate(
                        title=title,
                        weight=weight,
                        source_method="raw_pdf",
                        raw_evidence=match.group(0),
                        is_in_evaluation_section=True  # Assume yes
                    )
                    candidates.append(candidate)
        except Exception:
            pass
        
        return candidates
    
    def _is_garbage_raw_title(self, title: str) -> bool:
        """Check if a raw title is garbage."""
        title_lower = title.lower().strip()
        
        # Common garbage patterns
        garbage_patterns = [
            r'^(the|a|an|to|for|of|in|on|at|by|with)\s',  # Articles/prepositions
            r'^(january|february|march|april|may|june|july|august|september|october|november|december)',
            r'^(monday|tuesday|wednesday|thursday|friday|saturday|sunday)',
            r'^(week|page|section|chapter)',
            r'^(past|will|can|may|must|should)',
            r'penalty|deadline|late|applied|consideration',
            r'^assessment',  # "Assessment 10%" is probably a header
        ]
        
        for pattern in garbage_patterns:
            if re.search(pattern, title_lower):
                return True
        
        # Must have some recognizable assessment word for very short titles
        if len(title) < 12:
            assessment_words = {'exam', 'midterm', 'quiz', 'test', 'lab', 'assignment', 
                               'participation', 'research', 'project', 'final', 'report'}
            if not any(word in title_lower for word in assessment_words):
                return True
        
        return False
    
    def _extract_special_patterns(self, text: str) -> List[AssessmentCandidate]:
        """Extract assessments with special patterns like 'for up to X%'."""
        candidates = []
        
        # Pattern: "Quizzes (optional...) X% each for up to Y%"
        # Must start with a known assessment word
        assessment_starters = r'(Quiz(?:zes)?|Assignment(?:s)?|Lab(?:s)?|Test(?:s)?|Homework(?:s)?|Exercise(?:s)?)'
        
        pattern_up_to = re.compile(
            assessment_starters + r'\s*\([^)]*(?:\([^)]*\)[^)]*)*\)[^%]*\d+%[^%]*for\s+up\s+to\s+(\d+(?:\.\d+)?)\s*%',
            re.IGNORECASE
        )
        
        for match in pattern_up_to.finditer(text):
            title = match.group(1).strip()
            weight = float(match.group(2))
            
            candidate = AssessmentCandidate(
                title=title,
                weight=weight,
                source_method="special_pattern",
                raw_evidence=match.group(0)[:100],
                is_in_evaluation_section=True,
                has_assessment_noun=True
            )
            candidates.append(candidate)
        
        return candidates
    
    def _to_assessment_tasks(self, candidates: List[AssessmentCandidate]) -> List[AssessmentTask]:
        """Convert candidates to AssessmentTask objects."""
        tasks = []
        
        for candidate in candidates:
            # Determine assessment type
            assessment_type = self._infer_type(candidate.title)
            
            task = AssessmentTask(
                title=candidate.title,
                type=assessment_type,
                weight_percent=candidate.weight,  # Use weight_percent, not weight
                due_datetime=candidate.due_date,
                due_rule=candidate.due_rule,
                confidence=candidate.score,
                source_evidence=candidate.raw_evidence
            )
            tasks.append(task)
        
        return tasks
    
    def _infer_type(self, title: str) -> str:
        """Infer assessment type from title."""
        title_lower = title.lower()
        
        if 'final' in title_lower and 'exam' in title_lower:
            return 'final_exam'
        if 'midterm' in title_lower:
            return 'midterm'
        if 'quiz' in title_lower or 'test' in title_lower:
            return 'quiz'
        if 'assignment' in title_lower or 'homework' in title_lower:
            return 'assignment'
        if 'lab' in title_lower:
            return 'lab'
        if 'project' in title_lower:
            return 'project'
        if 'participation' in title_lower or 'attendance' in title_lower:
            return 'participation'
        if 'presentation' in title_lower:
            return 'presentation'
        if 'exam' in title_lower:
            return 'exam'
        
        return 'other'
    
    def get_debug_info(self) -> dict:
        """Get debug information for troubleshooting."""
        return {
            'evaluation_section': {
                'found': self.generator.evaluation_section is not None,
                'name': self.generator.evaluation_section.heading_text if self.generator.evaluation_section else None,
                'page_range': (
                    self.generator.evaluation_section.start_page,
                    self.generator.evaluation_section.end_page
                ) if self.generator.evaluation_section else None
            },
            'tables_found': len(self.doc.tables),
            'total_candidates': len(self.all_candidates),
            'rejected_candidates': [
                {'title': c.title, 'reason': c.rejection_reason}
                for c in self.rejected_candidates
            ],
            'selected_candidates': [
                {'title': c.title, 'weight': c.weight, 'score': c.score}
                for c in self.selected_candidates
            ],
            'total_weight': sum(c.weight or 0 for c in self.selected_candidates)
        }

