# Intervention backend and UI

The new `POST /api/simulate-target` endpoint extends the existing FastAPI service. It parses with Nebius, computes qualitative implications in Python, and asks a Nebius model (Claude by opt-in) for a cited research draft. `/ask` is now an alias of `POST /api/research`, which answers questions from the snapshot without any key. Existing browsing endpoints are unchanged.

## Install and run on Windows

From `nucleolus`:

```powershell
uv pip install --python .venv/Scripts/python.exe -e '.[dev]'
$env:PYTHONPATH = 'src'
& .venv/Scripts/python.exe -m uvicorn nucleolis.api.main:app --host 127.0.0.1 --port 8077
```

From `nucleolus/ui`, run `npm.cmd run build` before starting the API for a single-service production preview. Open `http://127.0.0.1:8077/#intervention`, or choose **Intervention** from the evidence browser. The default pathways view has an exit to that browser. For Vite development use `npm.cmd run dev`; existing localhost:5173 CORS settings are retained.

The service does not auto-reload `.env` while running. Restart it after changing settings. Process environment values override `.env` values.

## Provider configuration

Add these names to the gitignored `nucleolus/.env`; use real values only in that file or process environment:

```dotenv
NEBIUS_API_KEY=
NEBIUS_MODEL=
NEBIUS_BASE_URL=https://api.studio.nebius.ai/v1/
# Optional: a separate Nebius model for cited drafts; empty means NEBIUS_MODEL.
NEBIUS_SYNTHESIS_MODEL=
# nebius (default) or anthropic. The Anthropic values are needed only when opting in to Claude.
LLM_SYNTHESIS_PROVIDER=nebius
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-6
```

`NEBIUS_MODEL` must be the exact model ID enabled for the account and support strict JSON schema. No model ID is guessed. The default Nebius URL preserves the requested architecture; current provider examples also use `https://api.tokenfactory.nebius.com/v1/`. Set an explicit override if required by the account. Drafts use the same Nebius model unless `NEBIUS_SYNTHESIS_MODEL` names another strict-schema model. When opting in to Claude, `ANTHROPIC_MODEL` is configurable and defaults to Sonnet 4.6.

The default per-stage deadline is 30 seconds and the total deadline 65 seconds. The parser permits one schema-repair attempt and caps each output at 1,000 tokens. The Nebius drafting model gets one schema-repair attempt and 3,000 output tokens by default; Claude, when opted in, has one attempt. SDK automatic retries are disabled. See `.env.example` for overrides. Credentials and raw upstream error bodies are never included in API responses.

`GET /api/simulation-capabilities` reports configured models, review context, optional BEL availability, and demo availability without exposing keys. Configured means settings are present, not that a live request has succeeded.

An explicitly paid, bounded provider smoke check uses **fictional evidence**, but real provider calls (Nebius for both stages by default):

```powershell
$env:PYTHONPATH = 'src'
& .venv/Scripts/python.exe -m nucleolis.llm.smoke --live
```

This makes at most two parser calls and two synthesis calls. Offline tests never contact the providers.

## Software demonstration without keys

Set `NOD_ENABLE_SYNTHETIC_DEMO=true` and restart the service. In the Intervention view select **Synthetic software demo**. Its fixed question is:

> What happens to Reporter C if I knock out Switch A?

The explicitly synthetic chain is `A activates B; B inhibits C`. Knockout of A implies decreased B and increased C. The fixture's Boolean rules are `A'=A`, `B'=A`, `C'=NOT B`, with initial state `(1,1,0)`. Persistent knockout leads to `(0,0,1)`. These are fictional software examples, not claims about ALS/FTD, INDRA beliefs, or experiments. Fixture text is not a model response.

Example request:

```json
{
  "query": "What happens to Reporter C if I knock out Switch A?",
  "demo": true,
  "context_id": "demo_context",
  "method": "illustrative_boolean",
  "boolean_model_id": "synthetic_boolean_v1",
  "exclude_publication_ids": []
}
```

Use `method="signed_path_hypothesis"` and omit `boolean_model_id` for path inference. Synthetic demo is opt-in per request and server configuration. It never substitutes for a failed live call.

## Real evidence prerequisites

The current `demo_v3` corpus has 32 entities but all evidence is unreviewed. The implementation intentionally returns `insufficient_evidence` without generated synthesis when no eligible reviewed chain exists. Software tests do not provide biological validation.

Author a `ReviewManifest` JSON offline and configure `NOD_REVIEW_MANIFEST=relative/path.json`. Its schema is `schemas/simulation.py`; `docs/examples/synthetic_review.json` illustrates the shape without pretending to approve real evidence.

The manifest binds:

- Exact snapshot ID and checksum, manifest version, and a known experimental context.
- At most 40 selected entity IDs and at most 500 state-mapped claim IDs.
- Explicit evidence approval, source checking, context compatibility, and reviewer identity.
- Source/target activity or abundance states plus the assumptions supporting composition.
- Optional INDRA statement references with original string hashes, types, and nullable belief values; each reviewed evidence row lists only known originating statements.

An eligible evidence record must have a passage, a resolvable document, matching context, non-negated assertion, approved review, and non-retracted support. This sprint's computation excludes records without documents; existing browsing still preserves database-only provenance. There is no automatic promotion of a reviewed seed list to reviewed claims. A stale checksum is HTTP 409.

The existing snapshot lacks INDRA belief fields and can merge several source statements behind one stored hash. `analysis.adapter.statement_refs_from_indra()` imports explicitly supplied serialized statement metadata; it does not fetch missing scores. Recover source hashes/scores offline and bind them to evidence in the manifest. Missing scores or missing attribution produce null aggregate belief, never a fabricated default.

For a real Boolean model, also supply `NOD_BOOLEAN_MANIFEST` and the matching `boolean_model_id`. The model needs at most ten variables, one state per entity, initial bits, one typed rule per variable, a reviewed readout, context/checksum/review bindings, and assumptions. `docs/examples/synthetic_boolean.json` shows the shape. Partial decreases are rejected; only explicit knockout or forced-on intervention is defined. Boolean publication exclusion requires a separately reviewed rule model and is not executed by this endpoint.

## Semantics and response

Signed paths are simple, directed, and at most two edges. Directions multiply along edges; opposing paths never cancel or vote. State mappings must compose exactly. The candidate cap is 5,000 with a one-second traversal budget, and five readout paths are displayed with both signs represented when present. Categories summarize examined paths; truncation is separate. Missing paths are unknown, not evidence of no biological effect. Every displayed path's nodes, claim IDs, and evidence IDs resolve in the response.

Publication exclusion removes evidence and recomputes eligibility. The response retains the **baseline graph/evidence** for comparison and marks wholly lost links ineligible. `analysis.after_exclusion` and node states describe the filtered result; `analysis.baseline` describes the original. The confidence assessment describes surviving eligible evidence. Baseline link paper counts are not filtered counts; inspect the before/after analysis to compare conclusions.

Boolean execution is synchronous, with at most 20 logical updates, persistent clamps, explicit threshold ties (retain prior state), fixed-point and cycle detection. Numeric baseline/perturbed node states and flips are returned only if both runs reach fixed points. Rule steps have no physical time unit.

The envelope includes `snapshot`, review/rule versions, parsed and grounded query, analysis, backend evidence assessment, model synthesis, `nodes`, `links`, citations, limits, truncation, warnings, and provider provenance. Nodes retain the renderer's `id/name/kind` fields and add qualitative state. Links retain claim IDs, predicates, publication counts, signs and evidence, with equal nullable `belief`/`belief_score` aliases. The frontend copies graph objects before force-graph mutates them.

Belief coverage and the weakest observed statement score are descriptive; they are not a treatment probability. The assessment covers eligible evidence in the selected graph. The synthesis bundle contains displayed proof chains, at most 60 evidence records, and passages shortened to 1,200 characters, with omissions disclosed. Pydantic checks provider shape; reference validation checks citation membership and relationships. Neither proves that generated prose is scientifically entailed, so it remains a reviewable draft.

Response handling:

| Situation | Behavior |
|---|---|
| Ambiguous entity, missing intervention/context | HTTP 200, `needs_clarification`, no execution |
| Missing reviewed evidence | HTTP 200, `insufficient_evidence` analysis, no invented synthesis |
| Missing/inapplicable Boolean model | HTTP 200, `model_not_ready`, no silent method substitution |
| Missing parser key/model | HTTP 503 |
| Parser refusal/malformed output | HTTP 502 |
| Parser deadline | HTTP 504 |
| Draft model unavailable/invalid/timeout | HTTP 200, `partial`, deterministic graph retained |
| Stale snapshot/review binding | HTTP 409 |
| Malformed request | HTTP 422 |

## Optional PyBEL / INDRA interoperability

The runtime analysis uses the existing NetworkX infrastructure over INDRA-derived claims. `analysis/bel_adapter.py` exports eligible edges to a real `pybel.BELGraph`, with source/target activity modifiers, citations, and claim/evidence annotations. BEL export currently requires PMID-backed evidence and activity/abundance mappings. It is a representation adapter, not a Boolean solver, and is not called by the request pipeline.

Install optional libraries with `uv pip install --python .venv/Scripts/python.exe -e '.[bel]'`. The core service does not need them. `pybel_available` must report actual import capability. The INDRA import helper accepts source statement JSON, so the `indra` Python package is needed only for additional object-based ingestion workflows.

PyBEL 0.15.5 was installed and its real graph adapter tested in the current Python 3.14 environment. It requires `setuptools<81` for its legacy `pkg_resources` import; that compatibility constraint is included in the optional extra. Default PyStow caches/configuration are directed to `data/library-cache` and `data/library-config` rather than user home directories. Existing explicit PyStow environment settings are respected.

## AMASS corroboration and provenance

An optional enrichment channel beside the INDRA graph. It adds publication metadata and bounded
discovery of further papers. It can never change an edge sign, the graph, a Boolean rule or a
simulated state: a discovered paper enters the graph only through the existing review-manifest
process. Disabled by default; every setting is in `.env.example`.

```dotenv
AMASS_ENABLED=false
AMASS_MODE=cached          # disabled | cached | live
AMASS_CLASSIFIER=metadata_only
NOD_REVIEW_POLICY=require_approval
```

Modes. `disabled` does no work and says so. `cached` serves only records materialized earlier,
bound to the snapshot checksum, claim, sign, context, classifier and review policy; any mismatch
is a miss, never a silent reuse. `live` performs a bounded lookup and search, and only when
enabled here — a request asking for `live` on a `cached` server is downgraded, never escalated.
The synthetic demo uses fixtures and never calls AMASS.

Bounds per request: `AMASS_MAX_CALLS_PER_REQUEST` (default 6), `AMASS_MAX_SEARCH_RESULTS` (20),
`AMASS_MAX_RECORD_FETCHES` (20), `AMASS_MAX_CLAIMS` (5), a 15-second timeout, and a 2 MB response
cap. Cost is 1 credit per call regardless of batch size, so lookup resolves many PMIDs in one call
while each record's metadata needs its own GET. Only claims in the bounded synthesis bundle are
assessed — never every edge in the snapshot.

What the categories mean:

| Category | Meaning |
|---|---|
| `cross_indexed_only` | AMASS resolved a paper INDRA already cites. Cross-indexing, **not** corroboration |
| `additional_support_found` | A distinct publication family, not retracted, with a qualifying primary passage matching subject, object, direction and context |
| `opposing_evidence_found` | The same bar, in the opposite direction |
| `mixed_evidence` | Qualifying families on both sides |
| `context_mismatch` | The relation appears only in an incompatible species, tissue or cell type |
| `mention_only` | Entities co-occur, or only metadata came back; never support |
| `no_additional_evidence_found` | A complete bounded search added nothing. **Not** proof of absence |
| `truncated` | A limit could have changed the category; partial counts are kept |
| `unavailable` | The stage could not run; the deterministic result stands |

Four distinctions the payload keeps separate: **source pipelines** (a curated database and a reader
citing one paper is pipeline diversity, not two studies), **publication families** (a preprint and
its journal version count once, and only an explicit family link or a shared identifier merges
records — never a similar title), **distinct primary studies** (qualifying families only), and
**cross-indexing**. Reviews, editorials and protocols never count as primary support, and sole
support from a retracted paper is shown but never counted.

Passage classification is a separate bounded stage, never the narrative model's job.
`metadata_only` (the default) reads no text, so it cannot produce support. `nebius` sends one
abstract at a time under a strict schema; every quote must be an exact span of the supplied text,
and an invented span, a wrong identifier, a negated or speculative sentence is rejected or
downgraded to `unclear`. Machine classifications stay `unreviewed`, and under the default policy
unreviewed passages cannot qualify as support — set `NOD_REVIEW_POLICY=allow_labelled_unreviewed`
to count them, clearly labelled, instead.

INDRA belief is retained in the API, exports and the expanded provenance, labelled as an assembly
score that reflects automated statement assembly and source-specific extraction assumptions and
does not estimate whether the claim is correct. It is never a headline number, and never the
corroboration signal.

Licensing: access was verified, **reuse and redistribution rights were not**. The adapter stays
disabled by default, tests use synthetic fixtures with mocked transports, no real AMASS response is
committed, the cache lives in the gitignored data directory, and full text is opt-in
(`AMASS_INCLUDE_FULLTEXT=false`). A working key is not permission to republish.

Run the mocked tests with `& .venv/Scripts/python.exe -m pytest tests/test_amass_client.py tests/test_corroboration.py -q`.
They spend no credits and need no key. No live AMASS check has been run from this environment.

## Verification

```powershell
& .venv/Scripts/python.exe -m pytest -q
```

Run `npm.cmd run build` from `ui` for TypeScript and production bundling. Tests cover sign conflicts, eligibility, state composition, exclusions, missing belief, grounding, Boolean controls/cycles/clamps, strict API models, actual SDK serialization through mocked HTTP transports, refusals/timeouts, and synthesis citation validation. The implementation checklist at the workspace root tracks completed and outstanding live checks.
