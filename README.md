# nucleolus

Evidence-first literature research tool for ALS/FTD mechanisms.

Search a gene, explore a bounded mechanism graph, and read the actual sentences —
with their papers — behind every relationship shown. Built on INDRA's hosted
knowledge resources (CoGEx).

**Status: Phase A vertical slice.** The pipeline, the read-only API, the graph UI
and the evidence panel work end to end on real data. No claim in this tool has
been reviewed by a domain scientist. See `KNOWN_LIMITATIONS.md` before showing it
to anyone.

---

## Run it

```bash
scripts/launch.sh
```

Then open <http://127.0.0.1:8077>. One process, one port — it serves the API and
the built UI together, and makes **no network request**. The script builds the
frontend on first run and refuses to start if no snapshot exists.

### First-time setup

```bash
uv venv
uv pip install fastapi "uvicorn[standard]" pydantic httpx pyyaml networkx pytest
scripts/rebuild_snapshot.sh demo_v3   # ~10 min, needs network
scripts/launch.sh
```

### Development

Two processes with hot reload, UI on 5173 talking to the API on 8077:

```bash
scripts/run_api.sh
scripts/run_ui.sh
```

### Tests

```bash
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/ -q    # 24 tests, no network
```

## What you can do in it

- **Search** a gene — `TARDBP`, `TBK1`, `SOD1`, `SQSTM1`, `OPTN`, `FUS`, `C9orf72`.
- **Read the evidence** — click any claim to see the extracted sentences, each with
  its PubMed link, the reader that produced it, and the species if stated.
- **See disagreement** — opposing claims stay separate and carry a support ratio
  (`41↑ / 19↓`) rather than being merged into one arrow.
- **Trace a causal path** — bounded to 5 paths and 4 hops, causal edges only,
  with truncation reported.
- **Re-centre** — click any node.
- **Export** — JSON of the claims, evidence and query manifest in view.
- **Pathways (default view)** — ask *from X to Y*, or *from X to everything*.
  A deterministic three-column flow — SOURCE → ACTS THROUGH → TARGET — where the
  matching route lights up and the rest dims. One row per target beneath, ranked
  by the weakest supporting step discounted by how promiscuous the intermediate
  is. Click any line for the sentences.
- **3D mechanism space** — an alternative force-directed view (`3D` button).
  Kept, but not the default: a force layout puts nodes wherever the simulation
  settles, so position carries no meaning and the picture changes every load.

---

## How it is put together

```
config/seeds.yaml        7 ALS/FTD seed genes, HGNC IDs verified against HGNC at run time
config/predicates.yaml   predicate vocabulary + INDRA statement-type mapping
config/sources.yaml      source adapters, licences, rate limits

pipeline/retrieve.py     seeds -> CoGEx -> data/raw/<run>/   (immutable, with query manifest)
pipeline/normalize.py    raw -> entities/claims/evidence/documents/provenance
pipeline/enrich.py       PubMed backfill: dates + precision + types + retraction
pipeline/build.py        normalized -> validated snapshot in data/snapshots/

graph/queries.py         bounded in-memory MultiDiGraph over one snapshot
graph/pathways.py        layered routes, thinnest-step ranking, hub penalty
api/main.py              read-only FastAPI
ui/src/pathway/          layered pathway flow (SVG, deterministic) - default
ui/src/App.tsx           2D analysis view (React Flow)
ui/src/graph3d/          3D mechanism space (react-force-graph-3d)
```

One offline writer: the pipeline builds and validates a snapshot; the API only
ever reads one. A snapshot that fails validation is never served.

### Endpoints

| Endpoint | Notes |
|---|---|
| `GET /health` | snapshot id, checksum, coverage, limitations, capability flags |
| `GET /nodes/search?q=` | grounded name lookup |
| `GET /graph?node_id=` | 1-hop bounded neighbourhood; caps 200 nodes / 500 edges |
| `GET /path?source_id=&target_id=` | ≤5 simple paths, causal-only capped at 2 hops |
| `GET /pathways?source_id=` | layered routes: source → intermediates → targets, one row per target |
| `GET /edges/{claim_id}/evidence` | quotes, PMIDs, source, species, provenance |
| `GET /node/{node_id}/evidence` | incident claims by support |
| `GET /exports/graph?node_id=` | claims + evidence + query manifest as JSON |
| `POST /ask` | **501** — Phase D, needs an LLM key. Degrades to browsing, never to an uncited answer |

Every graph response carries the snapshot id, the filters applied and explicit
truncation flags.

---

## Rules the code enforces

These are not stylistic preferences; the tests fail if they are broken.

- **Phosphorylation is a mechanism, not activation.** Modifications and bindings
  get `effect_sign: null` and are excluded from causal path search.
- **Negation is separate from inhibition.** A negated Activation stays an
  `activates` claim marked negated. A sign is never flipped.
- **Opposing claims are never merged.** `A activates B` and `A inhibits B`
  remain two claims, so disagreement stays visible.
- **One paper is one supporting publication**, however many sentences or upstream
  resources report it. Provenance records are separate from support counts.
- **Publication dates are never inferred.** Dates come from PubMed and keep
  their stated precision (year / month / day). Absent dates are
  `date_precision: "unknown"`, never the retrieval date.
- **Papers, primary studies and sentences are counted separately** and never
  collapsed into one "strength" number.
- **Signed inference stops at 2 hops.** Beyond that the tool reports
  reachability and refuses to state a direction.
- **Direction always carries its basis** — undisputed / dominant / contested /
  unsigned. A contested leg asserts no direction at all, and the minority count
  is always shown rather than subtracted.
- **Routes are ranked by the weakest step**, discounted by intermediate degree.
  A hub is a good destination and a poor intermediate.
- **Retracted support is shown, not deleted.** A claim whose every supporting
  paper has been withdrawn says so.
- **Unresolved grounding stays unresolved.** Names are never invented.
- **Truncation is reported, never silent.**

---

## Configuration

The intervention copilot is available at `/#intervention` and `POST /api/simulate-target`.
See [the setup guide](docs/INTERVENTION_SETUP.md) for Nebius/Claude configuration,
the explicit synthetic demo, reviewed evidence manifests, Boolean rules, and tests.

Copy `.env.example` to `.env`. Nothing in `.env` is required for the pipeline or
the UI — CoGEx needs no key.

| Variable | Purpose |
|---|---|
| `NOD_DATA_DIR` | where raw/normalized/snapshots live (default `./data`) |
| `COGEX_BASE_URL` | INDRA CoGEx API |
| `AMASS_API_KEY` | optional; adapter disabled until endpoint schema and rights are confirmed |
| `LLM_API_KEY` | Phase D `/ask` only |

`.env` is gitignored. Keys stay server-side and must not reach logs or exports.

---

## What is not built yet

Phase B onward from `EXECUTION_PLAN.md`: PubMed acquisition and publication
dates, SIGNOR/GO/OmniPath adapters, LLM extraction with a precision gate,
grounded `/ask`, and the temporal benchmark. `KNOWN_LIMITATIONS.md` is the
honest list.
