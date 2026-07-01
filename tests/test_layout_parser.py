"""
Tests for layout_parser.tag_lines() and section helpers.

Covers:
  - Blank line detection
  - Heading detection (ALL CAPS, Title Case with colon, known keywords)
  - Bullet detection (bullet chars, indented lines)
  - Body line detection
  - Section context tracking (tagged lines know their parent section)
  - lines_in_section() helper
  - Two-column PDF layout detection

Edge cases:
  - Mixed indentation (spaces vs tabs)
  - Heading with no colon
  - Deeply indented skill bullet under "Skills:" heading
  - Single-line document
"""

import pytest
from src.preflight.layout_parser import (
    LineTag,
    TaggedLine,
    tag_lines,
    lines_in_section,
    extract_section_text,
    detect_pdf_layout,
    sort_pdf_blocks,
    LayoutInfo,
)


class TestTagLines:
    def test_blank_line(self):
        tagged = tag_lines("")
        assert tagged == []  # empty input → empty list

    def test_single_blank(self):
        tagged = tag_lines("\n")
        assert len(tagged) == 1
        assert tagged[0].tag == LineTag.BLANK

    def test_heading_with_colon(self):
        tagged = tag_lines("Skills:\n  Python")
        assert tagged[0].tag == LineTag.HEADING
        assert tagged[0].section == "Skills"

    def test_heading_all_caps(self):
        tagged = tag_lines("EXPERIENCE\n  Google, 2018-2020")
        assert tagged[0].tag == LineTag.HEADING

    def test_heading_keyword_no_colon(self):
        """Known section keywords like 'Experience' should be headings."""
        tagged = tag_lines("Experience\nGoogle 2018-2020")
        assert tagged[0].tag == LineTag.HEADING

    def test_body_line(self):
        tagged = tag_lines("This is a regular sentence about the candidate.")
        assert tagged[0].tag == LineTag.BODY

    def test_bullet_with_dash(self):
        tagged = tag_lines("- Python\n- Docker")
        assert tagged[0].tag == LineTag.BULLET
        assert tagged[1].tag == LineTag.BULLET

    def test_bullet_with_asterisk(self):
        tagged = tag_lines("* React\n* Node.js")
        assert all(t.tag == LineTag.BULLET for t in tagged if t.tag != LineTag.BLANK)

    def test_indented_line_is_bullet(self):
        """A line indented by 2+ spaces (no bullet char) is still a BULLET."""
        tagged = tag_lines("Skills:\n  Python\n  Docker")
        # Line 0: heading, Lines 1-2: bullets (indented)
        assert tagged[0].tag == LineTag.HEADING
        assert tagged[1].tag == LineTag.BULLET
        assert tagged[2].tag == LineTag.BULLET

    def test_tab_indented_is_bullet(self):
        tagged = tag_lines("Skills:\n\tPython")
        assert tagged[1].tag == LineTag.BULLET

    def test_section_context_propagated(self):
        """BULLET lines under 'Skills:' should have section='Skills'."""
        tagged = tag_lines("Skills:\n  Python\n  JavaScript\nExperience\n  Google")
        skill_bullets = [t for t in tagged if t.tag == LineTag.BULLET and t.section == "Skills"]
        assert len(skill_bullets) == 2

    def test_section_changes_on_heading(self):
        tagged = tag_lines("Skills:\n  Python\nEducation:\n  MIT")
        skills_section = [t for t in tagged if t.section == "Skills" and t.tag == LineTag.BULLET]
        edu_section    = [t for t in tagged if t.section == "Education" and t.tag == LineTag.BULLET]
        assert len(skills_section) >= 1
        assert len(edu_section)    >= 1

    def test_indent_level_0_for_heading(self):
        tagged = tag_lines("Skills:")
        assert tagged[0].indent_level == 0

    def test_indent_level_1_for_two_spaces(self):
        tagged = tag_lines("  Python")
        assert tagged[0].indent_level == 1

    def test_indent_level_2_for_four_spaces(self):
        tagged = tag_lines("    Docker")
        assert tagged[0].indent_level == 2

    def test_deterministic(self):
        text = "Skills:\n  Python\n  JavaScript\nExperience\n  Google 2018"
        r1 = [(t.tag, t.section) for t in tag_lines(text)]
        r2 = [(t.tag, t.section) for t in tag_lines(text)]
        assert r1 == r2


class TestLinesInSection:
    def test_returns_lines_in_named_section(self):
        text = "Skills:\n  Python\n  Docker\nEducation:\n  MIT"
        tagged = tag_lines(text)
        skill_lines = lines_in_section(tagged, "Skills")
        texts = [t.raw.strip() for t in skill_lines]
        assert "Python" in texts
        assert "Docker" in texts

    def test_excludes_lines_from_other_sections(self):
        text = "Skills:\n  Python\nEducation:\n  MIT"
        tagged = tag_lines(text)
        skill_lines = lines_in_section(tagged, "Skills")
        texts = [t.raw.strip() for t in skill_lines]
        assert "MIT" not in texts

    def test_case_insensitive_section_lookup(self):
        text = "SKILLS:\n  Python"
        tagged = tag_lines(text)
        # heading will have section = "SKILLS"
        # lines_in_section is case-insensitive
        result = lines_in_section(tagged, "skills")
        assert len(result) >= 1

    def test_empty_section(self):
        text = "Skills:\n\nEducation:\n  MIT"
        tagged = tag_lines(text)
        skill_lines = lines_in_section(tagged, "Skills")
        assert skill_lines == []


class TestPdfLayoutDetection:
    """Test PDF column layout detection with synthetic block data."""

    def _make_block(self, x0, y0, x1, y1, text="Sample text"):
        """Create a minimal fitz-style block tuple (x0,y0,x1,y1,text,block_no,block_type)."""
        return (x0, y0, x1, y1, text, 0, 0)

    def test_single_column_detected(self):
        """All blocks in left half → single column."""
        blocks = [
            self._make_block(10, 10, 200, 30),
            self._make_block(10, 40, 200, 60),
            self._make_block(10, 70, 200, 90),
        ]
        layout = detect_pdf_layout(page_width=400, text_blocks=blocks)
        assert not layout.is_two_column

    def test_two_column_detected(self):
        """Blocks on both sides → two column."""
        blocks = [
            # Left column
            self._make_block(10, 10, 190, 30),
            self._make_block(10, 40, 190, 60),
            self._make_block(10, 70, 190, 90),
            # Right column
            self._make_block(210, 10, 390, 30),
            self._make_block(210, 40, 390, 60),
            self._make_block(210, 70, 390, 90),
        ]
        layout = detect_pdf_layout(page_width=400, text_blocks=blocks)
        assert layout.is_two_column
        assert layout.mid_x == 200.0

    def test_empty_blocks(self):
        layout = detect_pdf_layout(page_width=400, text_blocks=[])
        assert not layout.is_two_column

    def test_zero_page_width(self):
        blocks = [self._make_block(10, 10, 200, 30)]
        layout = detect_pdf_layout(page_width=0, text_blocks=blocks)
        assert not layout.is_two_column
