# Research workspace

The default page is a question-first workspace over the active local evidence snapshot.
It interprets common questions without credentials, returns bounded signed routes,
opens the source passages, and connects a selected route to an optional cited research
draft. The original browser remains at `/#explorer`; the intervention view remains at
`/#intervention`.

## Why the previous entry points failed

`GET /nodes/search` searches entity names and aliases. A whole natural-language question
is not an entity mention, so passing it directly to that endpoint usually returns no match.
`POST /api/simulate-target` has a different contract: it parses and grounds a source,
perturbation and readout, then applies its evidence/context policy. A request such as
“What does GFAP activate?” does not name the pair that pipeline needs.

`POST /api/research` and the `POST /ask` alias now dispatch typed research operations.
The question interpreter selects the operation and entity mentions; every returned
relationship still comes from the snapshot. Research exploration never creates a review
manifest or changes the review status of raw evidence.

## Startup

From the `nucleolus` directory on Windows:

```powershell
./scripts/run_research.ps1
```

The launcher builds the UI and serves it with the API at <http://127.0.0.1:8079/>.
Use `-Port 8081` to select another port. Use `-SkipBuild` only when `ui/dist` is current.
The API must have a valid local snapshot; inspect `/health` for `snapshot_ready: true`.
Keep the launcher terminal open; Ctrl+C stops the server.

For a new checkout, install Python 3.12 or newer and Node/npm, then:

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[dev]"
Push-Location ui
npm.cmd ci
Pop-Location
./scripts/run_research.ps1
```

The project data directory must also contain a validated snapshot. Snapshot acquisition
is a separate network task documented in the README; launching the workspace does not
download literature or create synthetic biomedical evidence.

## Supported questions

These forms run locally without Nebius or Claude. Names must resolve uniquely in the
active snapshot; use `/api/research/capabilities` for its entity catalogue.

| Intent | Example | Behavior |
|---|---|---|
| Downstream activity | What does GFAP activate? | One-step activation claims |
| Upstream activity | What activates TREM2? | One-step incoming activation claims |
| Amount | What does TBK1 increase? | Increase-amount claims, distinct from activation |
| Bounded mechanism | Show mechanism of TBK1 | Signed downstream routes within two steps |
| Pair hypothesis | Does TBK1 reduce SQSTM1? | Both signs retained; requested direction assessed per route |
| Perturbation | What happens to SQSTM1 if I decrease TBK1? | Source decrease applied to each signed route |
| Knockout hypothesis | What happens if I knock out TBK1? | Conditional directional effects on reachable nodes |
| Upstream interventions | Which targets could reduce TARDBP? | Target-level increase/decrease ideas for upstream nodes |
| Drug wording | Which drugs target TARDBP? | Upstream relationships with compound and direction limits disclosed |
| Overview | What is TREM2? | Bounded snapshot overview, not a biological definition |
| Species | What does GFAP activate in human? | Only passages with matching species metadata |

Common aliases are accepted when they resolve uniquely. A distinct requested readout
such as `TARDBP aggregation`, pathology, a mutation or a phenotype is not silently
replaced with the underlying gene. A comparison currently produces a one-entity overview
with the unperformed comparison disclosed. Unsupported requests with a grounded entity
may return a bounded overview, explicitly stating that the original request was not executed.

For broader wording, optionally configure `NEBIUS_API_KEY` and `NEBIUS_MODEL` in `.env`.
Nebius receives a strict JSON schema and a catalogue; entity slots are constrained to
mentions in the question. Invalid output has one repair attempt. Each provider call is
capped at 20 seconds or the configured shorter timeout, with SDK retries disabled.
Refusals, malformed responses, timeouts and API errors produce an explicit clarification
result. Provider error details and credentials are not returned.

## API and graph guarantees

```json
{
  "query": "What happens to SQSTM1 if I decrease TBK1?",
  "species": "all",
  "max_paths": 8
}
```

Send this body to `POST /api/research` or `POST /ask`. `species` is one of `all`,
`human`, `mouse`, `rat`; `max_paths` is 2–12. Unknown fields and invalid input are rejected.
The response includes the typed plan, snapshot identity/checksum, interpretation, answer,
nodes, links, paths, assumptions, evidence/publication identifiers and truncation fields.

- Routes contain at most two signed steps. Display caps are 24 nodes, 48 links and
  the requested path count. Search stops after 5,000 examined edges or one second of
  traversal. `total_paths` counts discovered candidates, not every possible route when
  search is truncated; `paths_omitted` counts discovered routes omitted from display.
- Positive and negative candidates are interleaved so both discovered signs survive
  a two-route display cap, even when their path lengths differ. Publication counts
  order routes within a sign; they are not efficacy or independent-replication scores.
- Bindings, unsigned modifications, negated claims, rejected/negated passages, missing
  quotes/documents and retracted support cannot drive these signed routes.
- Species filtering uses passage context metadata, not the human gene namespace.
  Unknown species is excluded by a specific filter. Conflicting question/filter species
  requires clarification. Disease, cell type and tissue restrictions are reported as
  unapplied; an otherwise valid species filter remains in effect.
- Graph and path references, direction, duplicate identifiers and path length are
  validated. Missing entities produce `needs_clarification`; absent eligible routes
  produce `insufficient_evidence`, never a claim that the mechanism does not exist.
- The UI clears stale graphs when a new query begins, cancels superseded queries,
  discards stale draft responses, and reports service errors with a retry action.

## Connected workspace actions

Select a node to inspect its description and displayed relationships. Select a connection
to read eligible source passages, publication links, source class and review status.
Passage pagination allows inspection beyond the first 100 raw evidence records; filtering
continues to use the selected research link's eligible IDs. The evidence snapshot must
match the research result.

Select a route to highlight it. The perturbation selector reruns the question with a
changed source perturbation. Evidence library and Experiment ideas operate on the current
result. Export saves the complete research response as JSON; Save SVG exports the canvas.
Lanes represent graph roles and distance, including upstream distances from the requested
readout. They do not assign biological compartments or a time axis.

## Optional cited drafts

In **Experiment ideas**, select a route and proposed perturbation, then choose
**Generate cited research draft**. This sends a source/readout question to the existing
`POST /api/simulate-target` service with `method: signed_path_hypothesis`, `demo: false`,
and the active `snapshot_id`. The browser rejects a returned snapshot/checksum mismatch.
The simulation pipeline may select additional relevant evidence outside the displayed
research routes; those cited claims remain inspectable in the evidence panel.

Required provider settings are `NEBIUS_API_KEY` and `NEBIUS_MODEL`; drafts use
`NEBIUS_SYNTHESIS_MODEL` when it is set. Claude is opt-in through `LLM_SYNTHESIS_PROVIDER=anthropic`
with `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`. Configuration flags indicate available settings, not successful
authentication, model access or a validated biological model. See
[INTERVENTION_SETUP.md](INTERVENTION_SETUP.md) for provider and evidence-policy setup.
`NOD_ENABLE_EXPLORATORY_MODE=true` permits the separate pipeline to label unreviewed
literature as exploratory when no review manifest is supplied. Otherwise its reviewed
manifest/context requirements still apply. The research workspace never approves evidence.

The drafting model (Nebius by default) receives a bounded evidence bundle. The service validates narrative claim,
evidence, path and rule identifiers and their relationships. Invalid citations cannot
be presented as a generated validated draft. Synthesis failures preserve the deterministic
analysis and show an explicit error. Species-filtered workspace results currently disable
draft generation because that filter has no reviewed context mapping into the draft service.
Optional drafts call configured external providers; ordinary local queries and evidence
inspection do not.

## Scientific scope

The checked snapshot `demo_v4` contains 32 entities, 669 claims and 2,916 publication
records, with zero compounds. Its name is a local snapshot label; the workspace does not
switch to the simulation service's fictional demo. Counts can change with a new snapshot.

All research results are **exploratory literature hypotheses**. Raw extracted signs may
be wrong. Two-step composition assumes compatible activity/abundance states and contexts
that have not been established. Opposite signs can reflect extraction errors or different
experiments. Node colors indicate possible route-implied changes, not measured states,
quantitative effect sizes or Boolean simulation results.

Sourced subcellular compartments, validated context-specific mechanistic models, compound
selection/design, selectivity, dose, delivery, safety, clinical efficacy and prospective
prediction are outside this implementation. A knockout question is a directional hypothesis;
it does not establish the consequences of a real knockout. Gene targets are not drug
candidates. The separate reviewed Boolean pipeline retains its own manifest requirements.

## Verification performed on 2026-09-13

Run from `nucleolus`:

```powershell
./.venv/Scripts/python.exe -m pytest tests/ -q --disable-warnings
Push-Location ui
npm.cmd run build
Pop-Location
./.venv/Scripts/python.exe scripts/verify_research_ui.py --base-url http://127.0.0.1:8081
```

The browser smoke check requires installed Chrome at the path in the script and the
`websockets` package (`python -m pip install websockets` if missing). It uses headless
Chrome with a temporary profile under ignored `data/verification`, saves screenshots,
and writes `data/verification/research-ui-checks.json`.

Verified: **214 backend tests passed**, TypeScript and Vite production build passed,
and the app served the updated UI and API at `http://127.0.0.1:8081/` with healthy
snapshot `demo_v4`. Browser checks cover the default graph, query direction, evidence
links, missing entities, distinct readouts, upstream candidates, JSON export, experiment
briefs, draft citations outside the canvas, mobile width, HTTP failure and retry.
Desktop and mobile screenshots were visually inspected.

Provider SDK serialization, schema failures, timeouts, refusals and citation validation
are tested through mocked transports. The UI draft response is explicitly a synthetic
test fixture over real local evidence IDs; all research queries and passage requests in
the browser check use the running local API. **No paid provider calls were made during
this verification.** Live provider availability and the scientific validity of generated
proposals are not established by these tests. The optional `scripts/smoke_research.py`
performs a live Nebius parser check when deliberately run.

Non-blocking existing warnings: deprecated APIs in FastAPI/PyBEL dependencies and a large
bundle for the advanced graph browser. The research workspace loads that browser lazily.
