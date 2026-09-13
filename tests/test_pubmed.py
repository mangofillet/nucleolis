"""Publication-date and publication-type handling.

EXECUTION_PLAN.md s4: preserve date precision and missingness; never substitute
a retrieval date. HANDOVER.md s9: publication type is the cheapest independence
signal, and a claim backed by six reviews is not backed by six studies.
"""
from __future__ import annotations

import pytest

from nucleolis.pipeline.sources.pubmed import classify_types, parse_pubdate


# ---------------------------------------------------------------------------
# date precision
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2014 Jul 17", ("2014-07-17", "day")),
        ("2018", ("2018", "year")),
        ("2014 Jun", ("2014-06", "month")),
        ("2001 Jan 1", ("2001-01-01", "day")),
        ("1999 Dec 31", ("1999-12-31", "day")),
    ],
)
def test_precision_is_preserved_not_upgraded(raw, expected):
    assert parse_pubdate(raw) == expected


def test_missing_date_stays_unknown():
    assert parse_pubdate(None) == (None, "unknown")
    assert parse_pubdate("") == (None, "unknown")
    assert parse_pubdate("   ") == (None, "unknown")


def test_unparseable_date_is_not_guessed():
    value, precision = parse_pubdate("no idea")
    assert value is None
    assert precision == "unknown"


def test_season_degrades_to_year_rather_than_inventing_a_month():
    assert parse_pubdate("2014 Spring") == ("2014", "year")


def test_month_range_keeps_the_first_month():
    value, precision = parse_pubdate("2014 Jul-Aug")
    assert value == "2014-07"
    assert precision == "month"


def test_day_range_keeps_the_first_day():
    value, precision = parse_pubdate("2015 Mar 12-15")
    assert value == "2015-03-12"
    assert precision == "day"


def test_dates_sort_correctly_as_strings_within_a_precision():
    """Earliest-date selection compares these as plain strings."""
    dates = ["2014-07-17", "2014-06", "2013", "2014-07-02"]
    assert min(dates) == "2013"
    assert sorted(dates)[1] == "2014-06"


# ---------------------------------------------------------------------------
# publication types
# ---------------------------------------------------------------------------

def test_journal_article_is_primary():
    types, primary = classify_types(["Journal Article"])
    assert types == ["Journal Article"]
    assert primary is True


def test_review_alone_is_not_primary():
    _, primary = classify_types(["Review"])
    assert primary is False


def test_mixed_types_count_as_primary_when_any_type_is_primary():
    _, primary = classify_types(["Journal Article", "Review"])
    assert primary is True


def test_comment_and_editorial_are_secondary():
    assert classify_types(["Comment"])[1] is False
    assert classify_types(["Editorial"])[1] is False
    assert classify_types(["Meta-Analysis"])[1] is False


def test_unknown_type_is_not_assumed_primary():
    """Silence about type must not be read as evidence of a primary study."""
    types, primary = classify_types([])
    assert types == []
    assert primary is False


def test_funding_tags_alone_do_not_make_a_review_primary():
    """A grant acknowledgement says who paid, not that a study was run.

    The copper/APP case in HANDOVER.md s3 turned on exactly this: six of
    sixteen "supporting papers" were reviews.
    """
    _, primary = classify_types(["Review", "Research Support, N.I.H., Extramural"])
    assert primary is False
    _, still_primary = classify_types(
        ["Journal Article", "Research Support, Non-U.S. Gov't"]
    )
    assert still_primary is True
    _, review_and_comment = classify_types(["Review", "Comment"])
    assert review_and_comment is False
