"""
Tests for date_engine.normalize_date and normalize_date_pair.

Covers:
  - Standard human-readable formats from ATS/resume data
  - "Present" and synonyms
  - Already-canonical ISO-8601 pass-through
  - Year-only inputs
  - Chronological inversion detection and swap
  - Garbage / empty inputs → None (never raises)
  - Delimiter variants
"""

import pytest
from src.normalize.date_engine import normalize_date, normalize_date_pair, parse_years_experience


class TestNormalizeDate:
    def test_month_year_full(self):
        assert normalize_date("January 2018") == "2018-01"

    def test_month_year_abbreviated(self):
        assert normalize_date("Jan 2018") == "2018-01"

    def test_month_year_abbreviated_period(self):
        assert normalize_date("Mar. 2021") == "2021-03"

    def test_numeric_slash(self):
        assert normalize_date("01/2018") == "2018-01"

    def test_already_iso(self):
        assert normalize_date("2018-01") == "2018-01"

    def test_year_only(self):
        assert normalize_date("2020") == "2020-01"

    def test_present_lowercase(self):
        assert normalize_date("present") == "present"

    def test_present_titlecase(self):
        assert normalize_date("Present") == "present"

    def test_current(self):
        assert normalize_date("current") == "present"

    def test_now(self):
        assert normalize_date("now") == "present"

    def test_ongoing(self):
        assert normalize_date("ongoing") == "present"

    def test_till_date(self):
        assert normalize_date("till date") == "present"

    def test_empty_string(self):
        assert normalize_date("") is None

    def test_none_input(self):
        assert normalize_date(None) is None

    def test_garbage_string(self):
        assert normalize_date("not a date at all") is None

    def test_numeric_string_short(self):
        # 3-digit number is not a year
        result = normalize_date("123")
        assert result is None

    def test_whitespace_only(self):
        assert normalize_date("   ") is None

    def test_december_2023(self):
        assert normalize_date("December 2023") == "2023-12"

    def test_sep_2022(self):
        assert normalize_date("Sep 2022") == "2022-09"

    def test_deterministic(self):
        """Same input must always produce the same output."""
        result1 = normalize_date("March 2019")
        result2 = normalize_date("March 2019")
        assert result1 == result2 == "2019-03"


class TestNormalizeDatePair:
    def test_normal_pair(self):
        start, end = normalize_date_pair("January 2018", "March 2020")
        assert start == "2018-01"
        assert end == "2020-03"

    def test_open_ended_role(self):
        start, end = normalize_date_pair("January 2018", "Present")
        assert start == "2018-01"
        assert end == "present"

    def test_chronological_inversion_swapped(self):
        """When start > end, values should be swapped."""
        start, end = normalize_date_pair("March 2022", "January 2018")
        assert start == "2018-01"
        assert end == "2022-03"

    def test_both_none(self):
        start, end = normalize_date_pair(None, None)
        assert start is None
        assert end is None

    def test_start_only(self):
        start, end = normalize_date_pair("2020-06", None)
        assert start == "2020-06"
        assert end is None

    def test_garbage_end(self):
        start, end = normalize_date_pair("2019-01", "garbage")
        assert start == "2019-01"
        assert end is None


class TestParseYearsExperience:
    def test_two_year_role(self):
        years = parse_years_experience("2018-01", "2020-01")
        assert years is not None
        assert 1.9 <= years <= 2.1

    def test_present_role(self):
        """Open-ended roles should compute from start to today."""
        years = parse_years_experience("2020-01", "present")
        assert years is not None
        assert years > 0

    def test_garbage_dates(self):
        assert parse_years_experience("garbage", "garbage") is None

    def test_none_dates(self):
        assert parse_years_experience(None, None) is None
