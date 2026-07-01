"""
Tests for the layout parser indentation edge cases.

Covers:
  1. Pure tab-indented bullet under Skills heading → BULLET tag, section=Skills
  2. Single-space indented line → BULLET tag (was level 0 before fix)
  3. Mixed tab+space line (1 tab + 2 spaces = 6 normalized spaces) → level 2
  4. Deep nesting (2 tabs = 8 normalized spaces) → level 3
  5. ALL-CAPS section heading with no colon → HEADING tag
  6. Skill section parsing: indented skills correctly extracted via lines_in_section()
  7. Standard 2-space and 4-space indents → correct levels
  8. Bullet-prefixed lines at any indent level → BULLET tag
"""

from __future__ import annotations

import pytest

from src.preflight.layout_parser import (
    LineTag,
    TaggedLine,
    _indent_level,
    _normalize_indent,
    _is_heading,
    tag_lines,
    lines_in_section,
)


# ---------------------------------------------------------------------------
# _normalize_indent() tests
# ---------------------------------------------------------------------------

class TestNormalizeIndent:
    def test_no_indent_unchanged(self):
        assert _normalize_indent("hello world") == "hello world"

    def test_single_tab_becomes_four_spaces(self):
        result = _normalize_indent("\thello")
        assert result == "    hello"

    def test_two_tabs_become_eight_spaces(self):
        result = _normalize_indent("\t\thello")
        assert result == "        hello"

    def test_mixed_tab_then_spaces(self):
        # 1 tab (→ 4 spaces) + 2 spaces = 6 leading spaces
        result = _normalize_indent("\t  hello")
        assert result == "      hello"

    def test_spaces_unchanged(self):
        result = _normalize_indent("    hello")
        assert result == "    hello"

    def test_trailing_tab_not_affected(self):
        # Only LEADING whitespace is converted
        result = _normalize_indent("hello\tworld")
        assert result == "hello\tworld"


# ---------------------------------------------------------------------------
# _indent_level() tests
# ---------------------------------------------------------------------------

class TestIndentLevel:
    def test_no_indent(self):
        assert _indent_level("no indent") == 0

    def test_single_space(self):
        # Single-space was previously level 0 (bug). Now it's level 1.
        assert _indent_level(" single space") == 1

    def test_two_spaces(self):
        assert _indent_level("  two spaces") == 1

    def test_three_spaces(self):
        assert _indent_level("   three spaces") == 1

    def test_four_spaces(self):
        assert _indent_level("    four spaces") == 2

    def test_seven_spaces(self):
        assert _indent_level("       seven spaces") == 2

    def test_eight_spaces(self):
        # Deep nesting: new level 3
        assert _indent_level("        eight spaces") == 3

    def test_twelve_spaces(self):
        assert _indent_level("            twelve spaces") == 3

    def test_single_tab(self):
        # 1 tab → 4 normalized spaces → level 2
        assert _indent_level("\tsingle tab") == 2

    def test_two_tabs(self):
        # 2 tabs → 8 normalized spaces → level 3
        assert _indent_level("\t\ttwo tabs") == 3

    def test_mixed_tab_plus_spaces(self):
        # 1 tab (4 spaces) + 2 spaces = 6 → level 2
        assert _indent_level("\t  mixed") == 2

    def test_mixed_tab_plus_many_spaces(self):
        # 1 tab (4 spaces) + 4 spaces = 8 → level 3
        assert _indent_level("\t    deep mixed") == 3

    def test_empty_string(self):
        assert _indent_level("") == 0

    def test_only_spaces(self):
        # All-whitespace line: no content, but classified by its space count
        assert _indent_level("   ") == 1  # 3 spaces


# ---------------------------------------------------------------------------
# _is_heading() tests
# ---------------------------------------------------------------------------

class TestIsHeading:
    def test_known_section_keyword(self):
        assert _is_heading("Skills") is True

    def test_known_keyword_with_colon(self):
        assert _is_heading("Skills:") is True

    def test_all_caps_short_line(self):
        assert _is_heading("EXPERIENCE") is True

    def test_all_caps_with_colon(self):
        assert _is_heading("EDUCATION:") is True

    def test_title_case_with_colon(self):
        assert _is_heading("Work History:") is True

    def test_regular_sentence_not_heading(self):
        assert _is_heading("Worked at Google for 3 years.") is False

    def test_empty_string_not_heading(self):
        assert _is_heading("") is False


# ---------------------------------------------------------------------------
# tag_lines() integration tests
# ---------------------------------------------------------------------------

class TestTagLines:
    def test_blank_line(self):
        tagged = tag_lines("\n\n")
        assert all(t.tag == LineTag.BLANK for t in tagged if t.raw.strip() == "")

    def test_heading_detected(self):
        tagged = tag_lines("Skills:\n  Python\n  Django")
        headings = [t for t in tagged if t.tag == LineTag.HEADING]
        assert len(headings) == 1
        assert "Skills" in headings[0].raw

    def test_two_space_indent_is_bullet(self):
        tagged = tag_lines("Skills:\n  Python")
        bullets = [t for t in tagged if t.tag == LineTag.BULLET]
        assert len(bullets) >= 1
        assert "Python" in bullets[0].raw

    def test_single_space_indent_is_bullet(self):
        """Single-space indent was previously classified as BODY (level 0 bug)."""
        tagged = tag_lines("Skills:\n Python")
        bullets = [t for t in tagged if t.tag == LineTag.BULLET]
        assert any("Python" in b.raw for b in bullets), (
            "Single-space indented line should be tagged as BULLET under a Skills heading."
        )

    def test_tab_indent_is_bullet(self):
        tagged = tag_lines("Skills:\n\tPython\n\tDjango")
        bullets = [t for t in tagged if t.tag == LineTag.BULLET]
        assert len(bullets) == 2

    def test_mixed_indent_bullet(self):
        """1 tab + 2 spaces = 6 normalized spaces → level 2 → BULLET."""
        tagged = tag_lines("Skills:\n\t  Python")
        bullets = [t for t in tagged if t.tag == LineTag.BULLET]
        assert any("Python" in b.raw for b in bullets)

    def test_deep_nesting_level_3(self):
        """8+ spaces → level 3 → BULLET."""
        tagged = tag_lines("Skills:\n        DeepNested")
        bullets = [t for t in tagged if t.tag == LineTag.BULLET]
        assert any("DeepNested" in b.raw for b in bullets)
        level3 = [b for b in bullets if b.indent_level == 3]
        assert len(level3) >= 1

    def test_section_attribution(self):
        text = "Skills:\n  Python\n\nExperience:\n  Google\n"
        tagged = tag_lines(text)
        skills_lines = lines_in_section(tagged, "Skills")
        experience_lines = lines_in_section(tagged, "Experience")

        skill_texts = [t.raw.strip() for t in skills_lines]
        exp_texts    = [t.raw.strip() for t in experience_lines]

        assert "Python" in skill_texts, f"Python not in skills section: {skill_texts}"
        assert "Google" in exp_texts,   f"Google not in experience section: {exp_texts}"
        assert "Google" not in skill_texts, "Google should NOT be in Skills section"

    def test_bullet_prefix_chars(self):
        """Lines starting with -, *, •, –, — are BULLET regardless of indent."""
        text = "Skills:\n- Python\n* Django\n• React"
        tagged = tag_lines(text)
        bullets = [t for t in tagged if t.tag == LineTag.BULLET]
        bullet_texts = [t.raw.strip() for t in bullets]
        assert any("Python" in b for b in bullet_texts)
        assert any("Django" in b for b in bullet_texts)
        assert any("React" in b  for b in bullet_texts)

    def test_body_line_classification(self):
        """Non-indented, non-heading, non-bullet lines → BODY."""
        tagged = tag_lines("This is a regular sentence about the candidate.")
        bodies = [t for t in tagged if t.tag == LineTag.BODY]
        assert len(bodies) >= 1

    def test_determinism(self):
        """Same text always produces the same tagged output."""
        text = "Skills:\n  Python\n  Django\nExperience:\n  Google"
        result_a = tag_lines(text)
        result_b = tag_lines(text)
        assert [(t.tag, t.raw, t.indent_level) for t in result_a] == \
               [(t.tag, t.raw, t.indent_level) for t in result_b]
