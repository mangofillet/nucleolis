"""Corroboration inside the request pipeline: additive, bounded, never load-bearing."""
from __future__ import annotations

import asyncio

import pytest

from nucleolis.analysis import demo
from nucleolis.corroboration import cache, classify
from nucleolis.corroboration.service import CorroborationService, claims_for_response
from nucleolis.llm.settings import Settings
from nucleolis.pipeline.sources.amass import AmassError
from nucleolis.schemas.corroboration import CorroborationRequest
from nucleolis.schemas.simulation import SimulateTargetRequest, SimulateTargetResponse
from nucleolis.services.simulate_target import SimulationService


@pytest.fixture
def data():
    return demo.fixture()


def exploratory_response(snap):
    service = SimulationService(Settings(exploratory_enabled=True), demo.DemoParser(), demo.DemoScientist())
    return asyncio.run(service.run(SimulateTargetRequest(query=demo.DEMO_QUERY), snap))


def test_response_defaults_to_not_requested(data):
    snap, _, _ = data
    result = exploratory_response(snap)
    assert result.amass_corroboration.status == "not_requested"
    assert result.amass_corroboration.mode == "disabled" and result.amass_corroboration.calls_used == 0
    SimulateTargetResponse.model_validate_json(result.model_dump_json())


def test_claims_are_limited_to_displayed_paths(data):
    snap, _, _ = data
    claims = claims_for_response(exploratory_response(snap), snap)
    assert [c["id"] for c in claims] == ["demo_ab", "demo_bc"]
    first = claims[0]
    assert first["subject_name"] == "Switch A" and first["object_name"] == "Mediator B"
    assert first["snapshot_checksum"] == snap.checksum and first["predicate"] == "activates"
    # Demo documents carry no PMID or DOI, so there is nothing to cross-index.
    assert first["pmids"] == [] and first["indra_keys"] == set()


def test_demo_request_uses_synthetic_fixtures(data):
    snap, review, model = data
    service = SimulationService(Settings(amass_enabled=True, amass_mode="live"),
                                demo.DemoParser(), demo.DemoScientist())
    request = SimulateTargetRequest(query=demo.DEMO_QUERY, demo=True, context_id="demo_context",
                                    corroboration=CorroborationRequest(mode="live"))
    result = asyncio.run(service.run(request, snap, review, model))
    assert result.amass_corroboration.mode == "synthetic_fixture"
    assert result.amass_corroboration.calls_used == 0
    assert any("SYNTHETIC" in warning for warning in result.amass_corroboration.warnings)


class FailingClient:
    calls_used = 1

    async def lookup(self, items):
        raise AmassError("unauthorized", "AMASS returned HTTP 401.", 401)


class FixtureClient:
    """Returns one already-cited paper and one new metadata-only record."""

    calls_used = 2

    async def lookup(self, items):
        return [{"input": {"pmid": "38360089"}, "amassIds": ["AMBC_CROSS"]}]

    async def search(self, query, limit=20, include_fulltext=False):
        return [{"amassId": "AMBC_NEW", "pmid": "99999999", "title": "Fixture", "publicationTypes": ["Journal Article"],
                 "isRetracted": False}]

    async def record(self, amass_id, include_fulltext=False):
        return {"amassId": amass_id}


def live_settings():
    return Settings(amass_enabled=True, amass_mode="live", amass_api_key="test-only")


def test_provider_failure_degrades_without_breaking_the_result(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "cache_dir", lambda: tmp_path)
    service = CorroborationService(live_settings(), classify.MetadataOnlyClassifier(), FailingClient())
    summary = asyncio.run(service.run([{"id": "clm_1", "subject_name": "TBK1", "object_name": "OPTN",
                                        "predicate": "activates", "pmids": ["38360089"], "dois": [],
                                        "indra_keys": {"pmid:38360089"}, "snapshot_checksum": "abc"}],
                                      CorroborationRequest(mode="live")))
    assert summary.status == "unavailable" and summary.corroborations == []
    assert summary.warnings and "401" in summary.warnings[0]
    assert all("test-only" not in warning for warning in summary.warnings)


def test_metadata_only_records_never_become_support(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "cache_dir", lambda: tmp_path)
    service = CorroborationService(live_settings(), classify.MetadataOnlyClassifier(), FixtureClient())
    claim = {"id": "clm_1", "subject_name": "TBK1", "object_name": "OPTN", "predicate": "activates",
             "statement_type": "Phosphorylation", "pmids": ["38360089"], "dois": [],
             "indra_keys": {"pmid:38360089"}, "snapshot_checksum": "abc", "source_class": "machine_read"}
    summary = asyncio.run(service.run([claim], CorroborationRequest(mode="live",
                                                                    discover_additional_publications=True)))
    assert summary.status == "completed" and summary.claims_assessed == 1
    assessment = summary.corroborations[0]
    assert assessment.status == "mention_only"
    assert assessment.additional_supporting_publication_ids == []
    assert assessment.distinct_primary_study_count == 0
    assert assessment.searched_queries and '"TBK1" inhibits "OPTN"' in assessment.searched_queries
    # The second run is served from the checksum-bound cache without new calls.
    cached = asyncio.run(CorroborationService(Settings(amass_enabled=True, amass_mode="cached"),
                                              classify.MetadataOnlyClassifier()).run(
        [claim], CorroborationRequest(mode="cached")))
    assert cached.status == "completed" and cached.from_cache and cached.calls_used == 0
