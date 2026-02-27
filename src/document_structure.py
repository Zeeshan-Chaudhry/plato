"""
Document Structure Extraction Module

Provides a preprocessing layer that creates a structured representation
of the PDF before field extraction. This enables reliable "where to look"
decisions and reduces false positives.

Uses PyMuPDF (fitz) for layout extraction (font sizes, bounding boxes)
and pdfplumber for table extraction.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple, Any
from pathlib import Path

try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

import pdfplumber


@dataclass
class TextBlock:
    """A block of text with layout metadata."""
    text: str
    page_num: int
    x0: float  # Left coordinate
    y0: float  # Top coordinate
    x1: float  # Right coordinate
    y1: float  # Bottom coordinate
    font_size: float = 12.0
    is_bold: bool = False
    font_name: str = ""
    
    @property
    def width(self) -> float:
        return self.x1 - self.x0
    
    @property
    def height(self) -> float:
        return self.y1 - self.y0
    
    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2
    
    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class ReconstructedLine:
    """A line reconstructed from text blocks via y-coordinate clustering."""
    blocks: List[TextBlock]
    page_num: int
    y_center: float
    
    @property
    def text(self) -> str:
        """Get full text of line, ordered left to right."""
        sorted_blocks = sorted(self.blocks, key=lambda b: b.x0)
        return " ".join(b.text.strip() for b in sorted_blocks if b.text.strip())
    
    @property
    def left_text(self) -> str:
        """Get text from left half of line."""
        if not self.blocks:
            return ""
        sorted_blocks = sorted(self.blocks, key=lambda b: b.x0)
        midpoint = (sorted_blocks[0].x0 + sorted_blocks[-1].x1) / 2
        return " ".join(b.text.strip() for b in sorted_blocks 
                       if b.x0 < midpoint and b.text.strip())
    
    @property
    def right_text(self) -> str:
        """Get text from right half of line."""
        if not self.blocks:
            return ""
        sorted_blocks = sorted(self.blocks, key=lambda b: b.x0)
        midpoint = (sorted_blocks[0].x0 + sorted_blocks[-1].x1) / 2
        return " ".join(b.text.strip() for b in sorted_blocks 
                       if b.x0 >= midpoint and b.text.strip())
    
    @property
    def max_font_size(self) -> float:
        if not self.blocks:
            return 12.0
        return max(b.font_size for b in self.blocks)
    
    @property
    def has_bold(self) -> bool:
        return any(b.is_bold for b in self.blocks)


@dataclass
class DetectedTable:
    """A table detected in the PDF."""
    rows: List[List[str]]
    page_num: int
    headers: List[str] = field(default_factory=list)
    table_type: str = "unknown"  # "pdfplumber", "reconstructed"
    y0: float = 0.0
    y1: float = 0.0
    
    @property
    def num_rows(self) -> int:
        return len(self.rows)
    
    @property
    def num_cols(self) -> int:
        if not self.rows:
            return 0
        return max(len(row) for row in self.rows)


@dataclass
class Section:
    """A detected section in the PDF."""
    name: str
    heading_text: str
    start_page: int
    start_y: float
    end_page: int
    end_y: float
    confidence: float = 0.8
    
    def contains(self, page_num: int, y: float) -> bool:
        """Check if a position is within this section."""
        if page_num < self.start_page or page_num > self.end_page:
            return False
        if page_num == self.start_page and y < self.start_y:
            return False
        if page_num == self.end_page and y > self.end_y:
            return False
        return True


@dataclass
class DocumentStructure:
    """Complete structured representation of a PDF document."""
    pages: List[Dict[str, Any]]  # Per-page data
    blocks: List[TextBlock]
    lines: List[ReconstructedLine]
    tables: List[DetectedTable]
    sections: List[Section]
    headings: List[TextBlock]
    
    def get_section(self, name: str) -> Optional[Section]:
        """Get a section by name (case-insensitive, partial match)."""
        name_lower = name.lower()
        for section in self.sections:
            if name_lower in section.name.lower():
                return section
        return None
    
    def get_evaluation_section(self) -> Optional[Section]:
        """Get the evaluation/assessment/grading section."""
        keywords = ['evaluation', 'assessment', 'grading', 'grade breakdown', 
                   'methods of evaluation', 'course evaluation']
        for keyword in keywords:
            section = self.get_section(keyword)
            if section:
                return section
        return None
    
    def get_text_in_section(self, section: Section) -> str:
        """Get all text within a section."""
        text_parts = []
        for block in self.blocks:
            if section.contains(block.page_num, block.y0):
                text_parts.append(block.text)
        return "\n".join(text_parts)
    
    def get_tables_in_section(self, section: Section) -> List[DetectedTable]:
        """Get all tables within a section."""
        result = []
        for table in self.tables:
            if section.contains(table.page_num, table.y0):
                result.append(table)
        return result


class DocumentStructureExtractor:
    """Extracts structured representation from PDF."""
    
    # Heading keywords for section detection
    SECTION_KEYWORDS = {
        'evaluation': ['evaluation', 'assessment', 'grading', 'grade breakdown', 
                      'methods of evaluation', 'course evaluation', 'grading scheme'],
        'course_info': ['course information', 'course description', 'course details',
                       'course overview'],
        'schedule': ['schedule', 'calendar', 'important dates', 'key dates',
                    'course schedule', 'lecture schedule'],
        'learning_outcomes': ['learning outcomes', 'course objectives', 'objectives'],
        'requirements': ['requirements', 'prerequisites', 'essential requirements'],
        'policies': ['policies', 'academic integrity', 'accommodations'],
    }
    
    def __init__(self, pdf_path: Path):
        self.pdf_path = Path(pdf_path)
        self.blocks: List[TextBlock] = []
        self.lines: List[ReconstructedLine] = []
        self.tables: List[DetectedTable] = []
        self.sections: List[Section] = []
        self.headings: List[TextBlock] = []
        self.pages: List[Dict[str, Any]] = []
        
    def extract(self) -> DocumentStructure:
        """Extract complete document structure."""
        # Extract blocks with layout info
        self._extract_blocks()
        
        # Reconstruct lines from blocks
        self._reconstruct_lines()
        
        # Detect headings
        self._detect_headings()
        
        # Segment into sections
        self._segment_sections()
        
        # Extract tables
        self._extract_tables()
        
        return DocumentStructure(
            pages=self.pages,
            blocks=self.blocks,
            lines=self.lines,
            tables=self.tables,
            sections=self.sections,
            headings=self.headings
        )
    
    def _extract_blocks(self):
        """Extract text blocks with layout metadata using PyMuPDF."""
        if HAS_FITZ:
            self._extract_blocks_fitz()
        else:
            self._extract_blocks_pdfplumber()
    
    def _extract_blocks_fitz(self):
        """Extract blocks using PyMuPDF (better layout info)."""
        doc = fitz.open(str(self.pdf_path))
        
        for page_num, page in enumerate(doc, 1):
            page_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
            page_blocks = []
            
            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:  # Skip non-text blocks
                    continue
                
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        if not text:
                            continue
                        
                        bbox = span.get("bbox", [0, 0, 0, 0])
                        font_size = span.get("size", 12.0)
                        font_name = span.get("font", "")
                        is_bold = "bold" in font_name.lower() or "Bold" in font_name
                        
                        tb = TextBlock(
                            text=text,
                            page_num=page_num,
                            x0=bbox[0],
                            y0=bbox[1],
                            x1=bbox[2],
                            y1=bbox[3],
                            font_size=font_size,
                            is_bold=is_bold,
                            font_name=font_name
                        )
                        self.blocks.append(tb)
                        page_blocks.append(tb)
            
            self.pages.append({
                'page_num': page_num,
                'width': page.rect.width,
                'height': page.rect.height,
                'blocks': page_blocks
            })
        
        doc.close()
    
    def _extract_blocks_pdfplumber(self):
        """Fallback extraction using pdfplumber (less layout info)."""
        with pdfplumber.open(str(self.pdf_path)) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                chars = page.chars
                if not chars:
                    continue
                
                # Group chars into words/blocks
                words = page.extract_words()
                page_blocks = []
                
                for word in words:
                    text = word.get("text", "").strip()
                    if not text:
                        continue
                    
                    tb = TextBlock(
                        text=text,
                        page_num=page_num,
                        x0=word.get("x0", 0),
                        y0=word.get("top", 0),
                        x1=word.get("x1", 0),
                        y1=word.get("bottom", 0),
                        font_size=word.get("size", 12.0) if "size" in word else 12.0,
                        is_bold=False,
                        font_name=word.get("fontname", "") if "fontname" in word else ""
                    )
                    self.blocks.append(tb)
                    page_blocks.append(tb)
                
                self.pages.append({
                    'page_num': page_num,
                    'width': page.width,
                    'height': page.height,
                    'blocks': page_blocks
                })
    
    def _reconstruct_lines(self):
        """Reconstruct lines from blocks using y-coordinate clustering."""
        # Group blocks by page
        blocks_by_page = {}
        for block in self.blocks:
            if block.page_num not in blocks_by_page:
                blocks_by_page[block.page_num] = []
            blocks_by_page[block.page_num].append(block)
        
        # For each page, cluster blocks by y-coordinate
        for page_num, page_blocks in blocks_by_page.items():
            if not page_blocks:
                continue
            
            # Sort by y-coordinate
            sorted_blocks = sorted(page_blocks, key=lambda b: b.y0)
            
            # Cluster blocks that are on the same line (within y_tolerance)
            y_tolerance = 5  # pixels
            current_line_blocks = []
            current_y = None
            
            for block in sorted_blocks:
                if current_y is None:
                    current_y = block.y0
                    current_line_blocks = [block]
                elif abs(block.y0 - current_y) <= y_tolerance:
                    current_line_blocks.append(block)
                else:
                    # Save current line and start new one
                    if current_line_blocks:
                        avg_y = sum(b.center_y for b in current_line_blocks) / len(current_line_blocks)
                        self.lines.append(ReconstructedLine(
                            blocks=current_line_blocks,
                            page_num=page_num,
                            y_center=avg_y
                        ))
                    current_line_blocks = [block]
                    current_y = block.y0
            
            # Don't forget last line
            if current_line_blocks:
                avg_y = sum(b.center_y for b in current_line_blocks) / len(current_line_blocks)
                self.lines.append(ReconstructedLine(
                    blocks=current_line_blocks,
                    page_num=page_num,
                    y_center=avg_y
                ))
    
    def _detect_headings(self):
        """Detect headings based on font size, bold, and keywords."""
        if not self.blocks:
            return
        
        # Calculate font size percentiles
        font_sizes = [b.font_size for b in self.blocks if b.font_size > 0]
        if not font_sizes:
            return
        
        avg_font_size = sum(font_sizes) / len(font_sizes)
        large_font_threshold = avg_font_size * 1.2  # 20% larger than average
        
        # Heading keywords (flattened from SECTION_KEYWORDS)
        heading_keywords = set()
        for keywords in self.SECTION_KEYWORDS.values():
            heading_keywords.update(kw.lower() for kw in keywords)
        
        for block in self.blocks:
            is_heading = False
            
            # Check font size
            if block.font_size >= large_font_threshold:
                is_heading = True
            
            # Check bold
            if block.is_bold:
                is_heading = True
            
            # Check keywords
            text_lower = block.text.lower().strip()
            if any(kw in text_lower for kw in heading_keywords):
                is_heading = True
            
            # Check numbered heading patterns (e.g., "1. Introduction", "2. Evaluation")
            if re.match(r'^\d+\.?\s+[A-Z]', block.text):
                is_heading = True
            
            if is_heading:
                self.headings.append(block)
    
    def _segment_sections(self):
        """Segment PDF into sections based on detected headings."""
        if not self.headings:
            return
        
        # Sort headings by position
        sorted_headings = sorted(self.headings, 
                                key=lambda h: (h.page_num, h.y0))
        
        # Map headings to section types
        for i, heading in enumerate(sorted_headings):
            heading_text = heading.text.lower().strip()
            
            # Determine section type
            section_type = None
            for stype, keywords in self.SECTION_KEYWORDS.items():
                if any(kw in heading_text for kw in keywords):
                    section_type = stype
                    break
            
            if not section_type:
                section_type = "other"
            
            # Determine section end (start of next heading or end of document)
            if i + 1 < len(sorted_headings):
                next_heading = sorted_headings[i + 1]
                end_page = next_heading.page_num
                end_y = next_heading.y0
            else:
                # End at bottom of last page
                end_page = len(self.pages)
                end_y = 9999  # Large number
            
            section = Section(
                name=section_type,
                heading_text=heading.text,
                start_page=heading.page_num,
                start_y=heading.y0,
                end_page=end_page,
                end_y=end_y,
                confidence=0.8 if section_type != "other" else 0.5
            )
            self.sections.append(section)
    
    def _extract_tables(self):
        """Extract tables using pdfplumber and reconstructed table detection."""
        # First, use pdfplumber for well-formatted tables
        self._extract_pdfplumber_tables()
        
        # Then, reconstruct tables from aligned lines
        self._reconstruct_tables()
    
    def _extract_pdfplumber_tables(self):
        """Extract tables using pdfplumber."""
        with pdfplumber.open(str(self.pdf_path)) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                tables = page.extract_tables()
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    
                    # Get headers (first row)
                    headers = [str(cell) if cell else "" for cell in table[0]]
                    
                    # Get rows (remaining)
                    rows = [[str(cell) if cell else "" for cell in row] 
                           for row in table[1:]]
                    
                    self.tables.append(DetectedTable(
                        rows=[table[0]] + rows,  # Include header in rows
                        page_num=page_num,
                        headers=headers,
                        table_type="pdfplumber"
                    ))
    
    def _reconstruct_tables(self):
        """Reconstruct tables from aligned lines (for fake tables)."""
        # Group lines by page
        lines_by_page = {}
        for line in self.lines:
            if line.page_num not in lines_by_page:
                lines_by_page[line.page_num] = []
            lines_by_page[line.page_num].append(line)
        
        for page_num, page_lines in lines_by_page.items():
            # Look for sequences of lines with right-aligned percentages
            table_rows = []
            
            for line in page_lines:
                right_text = line.right_text.strip()
                left_text = line.left_text.strip()
                
                # Check if right text contains a percentage
                percent_match = re.search(r'(\d+(?:\.\d+)?)\s*%?$', right_text)
                if percent_match and left_text and len(left_text) > 3:
                    # This looks like a table row: [title] [weight%]
                    table_rows.append([left_text, right_text])
            
            # If we found at least 2 table-like rows, treat as reconstructed table
            if len(table_rows) >= 2:
                self.tables.append(DetectedTable(
                    rows=table_rows,
                    page_num=page_num,
                    headers=["Item", "Weight"],
                    table_type="reconstructed"
                ))


def extract_document_structure(pdf_path: Path) -> DocumentStructure:
    """Convenience function to extract document structure."""
    extractor = DocumentStructureExtractor(pdf_path)
    return extractor.extract()

