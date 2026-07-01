"""
Pre-flight package exports.
"""

from src.preflight.layout_parser import (
    LineTag,
    TaggedLine,
    tag_lines,
    lines_in_section,
    extract_section_text,
    LayoutInfo,
    detect_pdf_layout,
    sort_pdf_blocks,
)
from src.preflight.ocr_engine import ocr_page_if_needed, should_ocr
from src.preflight.lang_detect import detect_language, is_latin_script

__all__ = [
    # layout_parser
    "LineTag",
    "TaggedLine",
    "tag_lines",
    "lines_in_section",
    "extract_section_text",
    "LayoutInfo",
    "detect_pdf_layout",
    "sort_pdf_blocks",
    # ocr_engine
    "ocr_page_if_needed",
    "should_ocr",
    # lang_detect
    "detect_language",
    "is_latin_script",
]
