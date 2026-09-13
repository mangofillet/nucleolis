"""Source class is shown to readers in place of a belief score, so it must not guess."""
from __future__ import annotations

import pytest

from nucleolus.analysis.sources import classify


@pytest.mark.parametrize("counts,expected", [
    ({"reach": 3}, "machine_read"),
    ({"reach": 1, "sparser": 2}, "machine_read"),
    ({"biogrid": 1}, "curated_database"),
    ({"signor": 1, "hprd": 2}, "curated_database"),
    ({"reach": 4, "biogrid": 1}, "mixed"),
    ({}, "unknown"),
    (None, "unknown"),
])
def test_source_class(counts, expected):
    assert classify(counts)["source_class"] == expected


def test_unrecognised_source_is_reported_not_assumed():
    result = classify({"some_new_reader": 2})
    assert result["source_class"] == "unknown"
    assert result["unclassified_sources"] == ["some_new_reader"]
    assert result["reader_sources"] == [] and result["database_sources"] == []


def test_class_lists_and_counts_are_preserved():
    result = classify({"reach": 4, "BioGRID": 1})
    assert result["database_sources"] == ["BioGRID"]
    assert result["reader_sources"] == ["reach"]
    assert result["distinct_sources"] == 2
    assert result["source_class_label"] == "curated database and machine-read text"
