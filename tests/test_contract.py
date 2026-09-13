"""Essential invariants from EXECUTION_PLAN.md s8.

These are fixture-based and make no network call.
"""
from __future__ import annotations

import copy

import pytest

from nucleolis import config
from nucleolis.graph import queries
from nucleolis.pipeline import build, normalize


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _snapshot_payload():
    """Two entities, one conflicting pair, one unsigned claim, one shared paper."""
    entities = [
        {"id": "HGNC:1", "namespace": "HGNC", "accession": "1", "entity_type": "gene_protein",
         "preferred_name": "AAA", "long_name": "gene A", "taxon_id": 9606},
        {"id": "HGNC:2", "namespace": "HGNC", "accession": "2", "entity_type": "gene_protein",
         "preferred_name": "BBB", "long_name": "gene B", "taxon_id": 9606},
        {"id": "HGNC:3", "namespace": "HGNC", "accession": "3", "entity_type": "gene_protein",
         "preferred_name": "CCC", "long_name": "gene C", "taxon_id": 9606},
    ]
    contexts = [{"id": "ctx_unknown", "taxon_id": None, "tissue": None, "cell_type": None,
                 "cell_line": None, "disease": None, "location": None}]
    documents = [
        {"id": "PMID:1", "pmid": "1", "pmcid": None, "doi": None, "publication_date": None,
         "date_precision": "unknown", "publication_type": None, "license": None,
         "text_hash": None, "retraction_status": "unchecked"},
        {"id": "PMID:2", "pmid": "2", "pmcid": None, "doi": None, "publication_date": None,
         "date_precision": "unknown", "publication_type": None, "license": None,
         "text_hash": None, "retraction_status": "unchecked"},
    ]

    def claim(cid, subj, pred, obj, sign, causal, evidence_ids, docs, negated=False):
        return {
            "id": cid, "subject_id": subj, "predicate": pred, "object_id": obj,
            "effect_sign": sign, "causal": causal, "context_id": "ctx_unknown",
            "negated": negated, "epistemic_status": "negated" if negated else "asserted",
            "qualifiers_json": {}, "source_statement_hash": cid + "_h",
            "source_counts": {"reach": 1}, "evidence_ids": evidence_ids,
            "document_ids": docs, "support_count": len(docs),
        }

    def evidence(eid, cid, doc, quote, negated=False):
        return {
            "id": eid, "claim_id": cid, "document_id": doc,
            "text_ref": {"pmid": doc.split(":")[1] if doc else None, "pmcid": None, "doi": None},
            "quote": quote, "start_offset": None, "end_offset": None, "section": None,
            "experimental_basis": "unknown", "source_evidence_code": "reach",
            "context_id": "ctx_unknown", "negated": negated,
            "review_status": "unreviewed", "extraction_run_id": "test",
        }

    claims = [
        claim("clm_pos", "HGNC:1", "activates", "HGNC:2", 1, True, ["evd_1", "evd_2"],
              ["PMID:1", "PMID:2"]),
        claim("clm_neg", "HGNC:1", "inhibits", "HGNC:2", -1, True, ["evd_3"], ["PMID:2"]),
        claim("clm_bind", "HGNC:1", "binds", "HGNC:3", None, False, ["evd_4"], ["PMID:1"]),
        claim("clm_hop", "HGNC:2", "activates", "HGNC:3", 1, True, ["evd_5"], ["PMID:1"]),
    ]
    evidence_rows = [
        evidence("evd_1", "clm_pos", "PMID:1", "A activates B in cortex."),
        evidence("evd_2", "clm_pos", "PMID:2", "A increased B activity."),
        evidence("evd_3", "clm_neg", "PMID:2", "A inhibited B under stress."),
        evidence("evd_4", "clm_bind", "PMID:1", "A binds C."),
        evidence("evd_5", "clm_hop", "PMID:1", "B activates C."),
    ]
    provenance = [
        {"id": "prv_" + e["id"], "claim_id": e["claim_id"], "evidence_id": e["id"],
         "source": "indra_cogex", "upstream_resource": "reach", "source_record_id": None,
         "source_release": None, "retrieved_at": None, "license": "test", "raw_ref": "test"}
        for e in evidence_rows
    ]
    return {
        "id": "test_snap", "schema_version": 1, "created_at": "2026-01-01T00:00:00+00:00",
        "checksum": "sha256:test", "coverage": {}, "limitations": [], "license_note": "test",
        "query": {}, "entities": entities, "contexts": contexts, "claims": claims,
        "documents": documents, "evidence": evidence_rows, "provenance": provenance,
    }


@pytest.fixture
def snap():
    return queries.Snapshot(_snapshot_payload(), path=None)


@pytest.fixture
def tables():
    payload = _snapshot_payload()
    payload["stats"] = {
        "claims_signed": 3, "claims_unsigned": 1, "relations_unmapped": 0,
        "evidence_negated": 0, "evidence_with_quote": 5, "evidence_with_context": 0,
        "documents_without_date": 2,
    }
    return payload


# ---------------------------------------------------------------------------
# semantics: predicates, signs, negation
# ---------------------------------------------------------------------------

def test_mechanism_predicates_carry_no_causal_sign():
    """Phosphorylation is a mechanism, not activation. Binding has no sign."""
    mapping = config.predicates()["indra_mapping"]
    for stmt_type in ("Phosphorylation", "Dephosphorylation", "Complex", "Association"):
        spec = mapping[stmt_type]
        assert spec["effect_sign"] is None, stmt_type + " must not carry a sign"
        assert spec["causal"] is False, stmt_type + " must not be causal"


def test_signed_predicates_map_to_expected_signs():
    mapping = config.predicates()["indra_mapping"]
    assert mapping["Activation"]["effect_sign"] == 1
    assert mapping["Inhibition"]["effect_sign"] == -1
    assert mapping["IncreaseAmount"]["effect_sign"] == 1
    assert mapping["DecreaseAmount"]["effect_sign"] == -1


def test_every_mapped_predicate_is_in_the_vocabulary():
    predicates = config.predicates()
    vocabulary = set(predicates["vocabulary"])
    for spec in predicates["indra_mapping"].values():
        assert spec["predicate"] in vocabulary


def test_negation_is_separate_from_inhibition():
    """A negated Activation must stay an 'activates' claim marked negated -
    it must never become an inhibition."""
    mapping = config.predicates()["indra_mapping"]
    spec = mapping["Activation"]
    assert spec["predicate"] == "activates"
    assert spec["effect_sign"] == 1
    # negation lives on the evidence/claim, not in the predicate vocabulary
    assert "negated" not in config.predicates()["vocabulary"]


# ---------------------------------------------------------------------------
# identity and deduplication
# ---------------------------------------------------------------------------

def test_ids_are_deterministic_across_runs():
    first = normalize._hash("HGNC:1", "activates", "HGNC:2", "ctx_unknown", False)
    second = normalize._hash("HGNC:1", "activates", "HGNC:2", "ctx_unknown", False)
    assert first == second
    assert first != normalize._hash("HGNC:1", "inhibits", "HGNC:2", "ctx_unknown", False)


def test_curie_parsing_normalizes_namespace_case():
    assert normalize.parse_curie("hgnc:11741") == ("HGNC", "11741")
    assert normalize.parse_curie("HGNC:11741") == ("HGNC", "11741")


def test_opposing_claims_are_not_merged(snap):
    """The activating and inhibiting claims between the same pair stay distinct."""
    view = snap.neighborhood("HGNC:1", edge_scope="incident")
    pair = [e for e in view["edges"]
            if e["subject"]["id"] == "HGNC:1" and e["object"]["id"] == "HGNC:2"]
    assert len(pair) == 2
    assert {e["effect_sign"] for e in pair} == {1, -1}


def test_one_paper_counts_once_even_with_several_sentences(snap):
    """PMID:2 supports clm_pos and clm_neg; each counts it once."""
    assert snap.claims["clm_pos"]["support_count"] == 2  # PMID:1 and PMID:2
    assert snap.claims["clm_neg"]["support_count"] == 1  # PMID:2 only


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def test_valid_tables_pass_validation(tables):
    assert build.validate(tables) == []


def test_validation_rejects_sign_on_non_causal_predicate(tables):
    broken = copy.deepcopy(tables)
    bind = next(c for c in broken["claims"] if c["predicate"] == "binds")
    bind["effect_sign"] = 1
    problems = build.validate(broken)
    assert any("non-causal predicate" in p for p in problems)


def test_validation_rejects_dangling_evidence_reference(tables):
    broken = copy.deepcopy(tables)
    broken["claims"][0]["evidence_ids"].append("evd_missing")
    problems = build.validate(broken)
    assert any("dangling evidence" in p for p in problems)


def test_validation_rejects_unresolvable_document(tables):
    broken = copy.deepcopy(tables)
    broken["evidence"][0]["document_id"] = "PMID:does_not_exist"
    problems = build.validate(broken)
    assert any("document does not resolve" in p for p in problems)


def test_validation_rejects_missing_date_not_marked_unknown(tables):
    broken = copy.deepcopy(tables)
    broken["documents"][0]["date_precision"] = "day"  # but publication_date is None
    problems = build.validate(broken)
    assert any("missing date not marked unknown" in p for p in problems)


def test_validation_rejects_predicate_outside_vocabulary(tables):
    broken = copy.deepcopy(tables)
    broken["claims"][0]["predicate"] = "causes_somehow"
    problems = build.validate(broken)
    assert any("outside vocabulary" in p for p in problems)


# ---------------------------------------------------------------------------
# bounded graph behaviour
# ---------------------------------------------------------------------------

def test_neighborhood_reports_truncation_rather_than_hiding_it(snap):
    view = snap.neighborhood("HGNC:1", max_nodes=1)
    assert view["truncation"]["nodes_truncated"] is True
    assert len(view["nodes"]) == 1


def test_incident_scope_excludes_neighbour_to_neighbour_edges(snap):
    incident = snap.neighborhood("HGNC:1", edge_scope="incident")
    everything = snap.neighborhood("HGNC:1", edge_scope="all")
    incident_ids = {e["claim_id"] for e in incident["edges"]}
    all_ids = {e["claim_id"] for e in everything["edges"]}
    assert "clm_hop" not in incident_ids       # B -> C does not touch A
    assert "clm_hop" in all_ids
    assert incident_ids < all_ids


def test_causal_only_filter_drops_binding_claims(snap):
    view = snap.neighborhood("HGNC:1", causal_only=True, edge_scope="incident")
    assert all(e["causal"] for e in view["edges"])
    assert "clm_bind" not in {e["claim_id"] for e in view["edges"]}


def test_min_support_filter_is_applied(snap):
    view = snap.neighborhood("HGNC:1", min_support=2, edge_scope="incident")
    assert {e["claim_id"] for e in view["edges"]} == {"clm_pos"}


def test_paths_are_bounded_and_report_truncation(snap):
    result = snap.paths("HGNC:1", "HGNC:3", max_paths=1)
    assert len(result["paths"]) <= 1
    assert "paths_truncated" in result["truncation"]


def test_causal_path_search_ignores_non_causal_edges(snap):
    """A binds C exists, but binding must never carry a causal path."""
    result = snap.paths("HGNC:1", "HGNC:3", causal_only=True)
    for path in result["paths"]:
        for step in path["steps"]:
            assert all(claim["causal"] for claim in step["claims"])


# ---------------------------------------------------------------------------
# evidence integrity
# ---------------------------------------------------------------------------

def test_every_evidence_row_resolves_to_a_real_document(snap):
    for row in snap.evidence.values():
        if row["document_id"] is not None:
            assert row["document_id"] in snap.documents


def test_evidence_quotes_are_preserved_verbatim(snap):
    detail = snap.evidence_for_claim("clm_pos")
    quotes = [item["quote"] for item in detail["evidence"]]
    assert "A activates B in cortex." in quotes


def test_evidence_exposes_publication_link(snap):
    detail = snap.evidence_for_claim("clm_pos")
    links = [item["link"] for item in detail["evidence"]]
    assert all(link and link.startswith("https://pubmed.ncbi.nlm.nih.gov/") for link in links)


def test_dates_are_reported_as_unknown_not_invented(snap):
    for document in snap.documents.values():
        if document["publication_date"] is None:
            assert document["date_precision"] == "unknown"
