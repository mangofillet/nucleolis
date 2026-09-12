# Intervention backend and UI

The new `POST /api/simulate-target` endpoint extends the existing FastAPI service. It parses with Nebius, computes qualitative implications in Python, and asks Claude for a cited research draft. `/ask` remains the separate, unimplemented legacy endpoint. Existing browsing endpoints are unchanged.

## Install and run on Windows

From `nucleolus`:

```powershell
uv pip install --python .venv/Scripts/python.exe -e '.[dev]'
$env:PYTHONPATH = 'src'
& .venv/Scripts/python.exe -m uvicorn nucleolus.api.main:app --host 127.0.0.1 --port 8077
```

From `nucleolus/ui`, run `npm.cmd run build` before starting the API for a single-service production preview. Open `http://127.0.0.1:8077/#intervention`, or choose **Intervention** from the evidence browser. The default pathways view has an exit to that browser. For Vite development use `npm.cmd run dev`; existing localhost:5173 CORS settings are retained.

The service does not auto-reload `.env` while running. Restart it after changing settings. Process environment values override `.env` values.

## Provider configuration

Add these names to the gitignored `nucleolus/.env`; use real values only in that file or process environment:

```dotenv
NEBIUS_API_KEY=
NEBIUS_MODEL=
NEBIUS_BASE_URL=https://api.studio.nebius.ai/v1/
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-6
```

`NEBIUS_MODEL` must be the exact model ID enabled for the account and support strict JSON schema. No model ID is guessed. The default Nebius URL preserves the requested architecture; current provider examples also use `https://api.tokenfactory.nebius.com/v1/`. Set an explicit override if required by the account. Claude 3.5 Sonnet is retired, so the model is configurable and defaults to Sonnet 4.6.

The default per-stage deadline is 30 seconds and the total deadline 65 seconds. The parser permits one schema-repair attempt and caps each output at 1,000 tokens. Claude has one attempt and 3,000 output tokens. SDK automatic retries are disabled. See `.env.example` for overrides. Credentials and raw upstream error bodies are never included in API responses.

`GET /api/simulation-capabilities` reports configured models, review context, optional BEL availability, and demo availability without exposing keys. Configured means settings are present, not that a live request has succeeded.

An explicitly paid, bounded provider smoke check uses **fictional evidence**, but real Nebius and Claude calls:

```powershell
$env:PYTHONPATH = 'src'
& .venv/Scripts/python.exe -m nucleolus.llm.smoke --live
```

This makes at most two parser calls and one synthesis call. Offline tests never contact the providers.

## Software demonstration without keys

Set `NOD_ENABLE_SYNTHETIC_DEMO=true` and restart the service. In the Intervention view select **Synthetic software demo**. Its fixed question is:

> What happens to Reporter C if I knock out Switch A?

The explicitly synthetic chain is `A activates B; B inhibits C`. Knockout of A implies decreased B and increased C. The fixture's Boolean rules are `A'=A`, `B'=A`, `C'=NOT B`, with initial state `(1,1,0)`. Persistent knockout leads to `(0,0,1)`. These are fictional software examples, not claims about ALS/FTD, INDRA beliefs, or experiments. Fixture text is not a Claude response.

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

The envelope includes `snapshot`, review/rule versions, parsed and grounded query, analysis, backend evidence assessment, Claude synthesis, `nodes`, `links`, citations, limits, truncation, warnings, and provider provenance. Nodes retain the renderer's `id/name/kind` fields and add qualitative state. Links retain claim IDs, predicates, publication counts, signs and evidence, with equal nullable `belief`/`belief_score` aliases. The frontend copies graph objects before force-graph mutates them.

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
| Claude unavailable/invalid/timeout | HTTP 200, `partial`, deterministic graph retained |
| Stale snapshot/review binding | HTTP 409 |
| Malformed request | HTTP 422 |

## Optional PyBEL / INDRA interoperability

The runtime analysis uses the existing NetworkX infrastructure over INDRA-derived claims. `analysis/bel_adapter.py` exports eligible edges to a real `pybel.BELGraph`, with source/target activity modifiers, citations, and claim/evidence annotations. BEL export currently requires PMID-backed evidence and activity/abundance mappings. It is a representation adapter, not a Boolean solver, and is not called by the request pipeline.

Install optional libraries with `uv pip install --python .venv/Scripts/python.exe -e '.[bel]'`. The core service does not need them. `pybel_available` must report actual import capability. The INDRA import helper accepts source statement JSON, so the `indra` Python package is needed only for additional object-based ingestion workflows.

PyBEL 0.15.5 was installed and its real graph adapter tested in the current Python 3.14 environment. It requires `setuptools<81` for its legacy `pkg_resources` import; that compatibility constraint is included in the optional extra. Default PyStow caches/configuration are directed to `data/library-cache` and `data/library-config` rather than user home directories. Existing explicit PyStow environment settings are respected.

## Verification

```powershell
& .venv/Scripts/python.exe -m pytest -q
```

Run `npm.cmd run build` from `ui` for TypeScript and production bundling. Tests cover sign conflicts, eligibility, state composition, exclusions, missing belief, grounding, Boolean controls/cycles/clamps, strict API models, actual SDK serialization through mocked HTTP transports, refusals/timeouts, and synthesis citation validation. The implementation checklist at the workspace root tracks completed and outstanding live checks.
