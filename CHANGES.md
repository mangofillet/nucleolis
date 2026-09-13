# Changes on this branch

Work done on top of `0xIkra/nucleolis` @ `2a06bad`. Two themes: **widen the scope
from ALS/FTD to brain ageing**, and **reskin to the Nucleolis brand**. Along the
way four upstream bugs turned up; they are described below with the evidence.

Assisted by Claude Code.

---

## 1. Bugs found in the existing pipeline

### 1.1 The batch evidence endpoint was written but never called

`CogexClient.evidences_for_hashes()` existed in `sources/cogex.py` and POSTs to
`get_evidences_for_stmt_hashes`. `retrieve.py` ignored it and fetched one hash at
a time at 3 rps.

Measured directly against the live API: **200 hashes in 0.76s**. The old loop also
iterated 1,362 *relations* when there were only 1,054 unique *statement hashes* —
23% of calls were duplicates.

Fixed by deduplicating and batching in chunks of 200.

**Result: the retrieve stage went from ~7.5 minutes to 7.2 seconds.**

The reason this went unnoticed is worth knowing: `evidences_for_hashes()` catches
`CogexError` and silently falls back to the per-hash loop, so a broken batch path
and a working-but-unused one look identical from the outside.

### 1.2 `indra_subnetwork_meta` rejects 400+ nodes

Undocumented server limit:

```
HTTP 400: {"message": "Number of nodes must be less than 400"}
```

This caps the node universe, and it is not a limit you can work around by naive
chunking: the endpoint returns only the subgraph **induced** among the nodes you
pass, so splitting the set and unioning the results silently drops every edge that
crosses a chunk boundary.

`_subnetwork_all_pairs()` in `retrieve.py` queries all chunk **pairs** instead.
Any edge has both endpoints in at least one pair, so the result is identical to a
single whole-set call. k chunks cost k(k+1)/2 requests.

### 1.3 `search_nodes` ignored punctuation, so present genes were unfindable

`queries.py` matched `preferred_name` as a raw string. `CSF-1` therefore failed
even where `CSF1` existed, as would `IL-34`, `PGC-1alpha` and similar.

Note that `ground.py` **already** resolves HGNC `alias_symbol` and `prev_symbol`
during the pipeline — that capability simply was never wired into this lookup.
Search now folds to alphanumerics before comparing.

### 1.4 `scripts/rebuild_snapshot.sh` could not run on Linux

It hardcoded `PY=".venv/Scripts/python.exe"` with no POSIX fallback, unlike
`launch.sh` which has one. The script has been rewritten with the fallback, an
explicit error if no interpreter is found, and `EVIDENCE_CAP` / `MAX_NODES`
environment variables. The `README` test command has the same Windows path and is
left alone here to keep this branch focused.

---

## 2. Scope: ALS/FTD → brain ageing and cognitive maintenance

### What forced a curated seed list

MeSH **`Aging` (D000375) returns zero genes** from CoGEx. So do Parkinson Disease
and Lewy Body Disease. The ageing axis cannot be obtained by disease association,
so `config/seeds.yaml` is now v3 and carries the mechanisms explicitly, each with
its own recorded rationale as the file's v1 policy demands.

- **v2 block, ageing resilience** (20 genes): MTOR, FOXO3, PRKAA1, AKT1, IGF1,
  PPARGC1A, SIRT1, SIRT3, NAMPT, TFEB, ATG7, BECN1, NFE2L2, NLRP3, CX3CR1,
  CDKN2A, TERT, KL, BDNF, CREB1. Every one was checked against all queried MeSH
  gene lists and found in none of them.
- **v3 block, microglial/neuroimmune** (9 genes): CSF1, IL34, CSF1R, TYROBP,
  P2RY12, AIF1, C1QA, C3, ITGAM. Also absent from every list. Without these the
  damage side had no microglial mechanism at all, only downstream inflammatory
  markers — a serious gap for brain ageing, where complement-mediated synapse
  pruning is a leading account of cognitive decline.

Each seed carries an `axis`, and `axes:` groups those into a resilience side and a
damage side. This is the assignment the showcase view projects through.

### Disease descriptors: 2 → 24

Was ALS + FTD only. Now adds the core cognitive-ageing set (Alzheimer, dementia,
cognition, memory disorders, MCI, neurodegeneration), the **vascular** contribution
(stroke, brain ischaemia, hypoxia, anoxia, vascular dementia), and the
**neuroinflammatory / white matter** contribution (multiple sclerosis, gliosis,
oligodendroglia, leukoencephalopathy).

Deliberately **excluded**: Bipolar Disorder (480 genes), Seizures/Epilepsy (~250)
and Autism (85). All three were measured and would roughly double the graph again,
but Bipolar alone would dominate the corpus and the tool would stop being about
cognitive ageing. Size was not the goal.

### Effect

| | before | after |
|---|---|---|
| Entities | 32 | 414 → ~870 |
| Claims | 669 | 61,294 |
| Documents | 2,916 | 279,913 |
| Evidence records | 6,373 | 678,363 |
| Negated evidence | 0 | **116** |

That last row matters: `KNOWN_LIMITATIONS.md` §8 says negation is "implemented but
untested against real data" because the old snapshot had zero negated records.
It now has 116, so that path is exercised for the first time.

---

## 3. Evidence capping (new)

Full evidence depth produces a ~900MB snapshot that the API holds in memory.
Measured distribution of evidence records per statement:

```
median 1    p90 11    p99 107    max 7,955
```

The distribution is extremely skewed, so a cap costs almost nothing for the
typical statement and removes most of the bulk. Two independent knobs:

- `build.py --max-evidence-per-claim N` — **safe.** Caps at snapshot build. Raw
  and normalized data stay complete, so a fuller snapshot can be rebuilt
  **without re-fetching from INDRA**.
- `retrieve.py --max-evidence-per-statement N` — **distorts paper counts. Do not
  use it for a snapshot anyone will read numbers off.** See the warning below.

### The two caps are not equivalent

The build cap is safe because normalize computes every paper-level count over the
full evidence set *before* anything is dropped. The fetch cap removes records
before normalize ever sees them, so the counts are computed from truncated data
and are silently understated.

Measured on this corpus, same node set, cap 12 at fetch vs no cap:

| | uncapped fetch | fetch cap 12 |
|---|---|---|
| max `support_count` | 5,064 | 343 |
| mean `support_count` | 8.4 | 3.0 |

This is not a cosmetic loss. Truncation hits concentrated majority support
hardest, so it changes conclusions: `SIRT1 -> NLRP3` reads **44up/124down,
dominant** on an uncapped fetch and **20up/19down, contested** at fetch cap 12.
The direction classification flips. The shipped snapshot is built with an
uncapped fetch and the build cap only.

**The build cap never changes what the tool says:**

- Paper-level counts (`support_count`, `n_papers`, `n_primary`, `n_retracted`,
  `n_sentences`) are computed by normalize over the full set and are untouched.
  "41 papers" stays 41 papers. Only stored *sentences* are sampled.
- Every document row is kept, so dates, retraction status and the
  sentence-inflation metric stay exact.
- Capped claims carry `evidence_total` and `evidence_capped`;
  `/edges/{id}/evidence` returns `total_before_cap`; `/health` reports
  `evidence_cap` and `evidence_dropped_by_cap`; and the cap is appended to the
  `limitations` list the API serves. A capped snapshot says "showing 10 of 214",
  never a bare "10".
- Selection is quality-first and deterministic (quote and resolvable document
  first, then by id), so the same run and cap reproduce the same checksum.

At cap 10 the snapshot is **355MB, builds in 21s, and the API holds 0.4GB**.

---

## 4. Bounds raised

`queries.py`. These were documented in `KNOWN_LIMITATIONS.md` §5 as deliberate, so
this is a product change, not a bug fix — revert if you disagree.

| | was | now |
|---|---|---|
| `HARD_MAX_NODES` | 200 | 800 |
| `HARD_MAX_EDGES` | 500 | 2000 |
| `DEFAULT_NODES` | 50 | 150 |

Truncation reporting is unchanged and still works (`truncation.nodes_truncated`).

---

## 5. Resilience vs damage showcase (new)

`GET /axes` + the `#resilience` view. Projects the snapshot through the axis
assignments in `seeds.yaml`: what holds cognition up on one side, what wears it
down on the other, and the signed causal claims that cross between them.

It inherits the rules the rest of the service enforces, because a summary screen
is the easiest place to quietly break them:

- Opposing claims are never merged; both support counts are shown.
- Direction carries its basis — undisputed / dominant / contested. **A contested
  pair asserts no direction at all** and renders as "direction disputed".
- Unsigned relations (binding, phosphorylation) are excluded: a modification is a
  mechanism, not a direction of effect.
- Seeded genes missing from the snapshot are listed, not hidden.
- Truncation is reported.

Sample output against the 414-entity snapshot:

| | | direction | basis | support |
|---|---|---|---|---|
| SIRT1 | → NLRP3 | decreases | dominant | 44↑ / 124↓ |
| SIRT3 | → NLRP3 | decreases | dominant | 17↑ / 51↓ |
| SIRT1 | → CDKN2A | decreases | dominant | 15↑ / 41↓ |
| MTOR | → NLRP3 | increases | dominant | 33↑ / 17↓ |
| IGF1 | → TERT | increases | dominant | 32↑ / 1↓ |
| SIRT1 | → TERT | *none* | contested | 27↑ / 18↓ |

The sirtuin→inflammasome and sirtuin→p16 axes surfacing as the best-supported
crossing claims is the expected answer for cognitive-ageing biology.

---

## 6. Reskin

- `ui/src/theme.css` — the eight confirmed brand colours as tokens. **249 literal
  hex values** across `research.css`, `pathway.css` and `intervention.css` were
  mapped onto them by hue/lightness band.
- `ui/src/brand/Logo.tsx` — the Nucleolis mark drawn as SVG (five translucent
  petals, solid nucleus, two elliptical orbits) in three lockups: ink, reverse,
  mono. Replaces the previous placeholder mark; `favicon.svg` replaces a leftover
  purple lightning bolt.
- IBM Plex Sans / Serif / Mono bundled via `@fontsource`. **Not** Google Fonts —
  a `<link>` to `fonts.googleapis.com` would break the product's stated guarantee
  that the running app makes no network request.

**One deliberate deviation from the brand sheet, recorded in `theme.css`:** it
assigns Steel Gray `#94A3B8` to secondary *text*, which measures 2.6:1 on
Laboratory White and fails WCAG AA. Steel Gray keeps its icon and divider roles;
secondary text uses a darkened `#56697C` at 5.1:1.

---

## 7. Tests

**230 pass** (213 existing + 17 new), no network required.

- `tests/test_axes.py` (8) — the showcase rules: unsigned relations excluded,
  opposing claims not merged, contested pairs assert no direction, missing seeds
  reported, truncation reported, min-support filtering.
- `tests/test_evidence_cap.py` (9) — paper counts never rewritten, true totals
  recorded, no dangling evidence ids, provenance pruned consistently, quality-first
  selection, deterministic output.

---

## 8. Known gaps in this branch — please read before demoing

1. **No publication dates.** The enrich stage was not run to completion, so all
   documents are `date_precision: "unknown"` and `documents_dated` is 0. This is a
   regression against the old snapshot, which had 2,875 dated. Nothing is guessed,
   but the dating feature is effectively off.

   The reason is a real performance problem: enrich makes ~1,400 PubMed ESummary
   calls for 280k documents and was measured at **~10 calls/minute**, roughly two
   hours. `pubmed.py:127` reads `rps = rate_limit_rps or (10.0 if api_key else 3.0)`
   and no `NCBI_API_KEY` is configured, so it runs at the anonymous floor.
   Setting one is the first thing to try.

2. **`coverage.evidence_with_quote` is a pre-cap statistic** and can exceed the
   post-cap `coverage.evidence` total. Cosmetic but wrong, and not yet fixed.

3. **`README.md` and `KNOWN_LIMITATIONS.md` are stale.** They still describe an
   ALS/FTD tool with 32 entities and 669 claims. Every figure is out by roughly
   90×, and §8's statement that negation is untested no longer holds.
   `KNOWN_LIMITATIONS.md` is the strongest thing in the project and it should not
   be left describing a different tool.

4. **The research workspace at `#` still returns ~7 nodes.** That is by design —
   it answers one typed question via bounded path search (`max_paths`), it is not
   a map. The large graph is at `#explorer`.

5. **Fixed: 13% of entities had no name.** NFE2L2 and KL appeared "absent" from
   the snapshot. They were not absent — NFE2L2 has 2,360 relations and is the
   largest hub in the graph. They had `preferred_name: None`, which makes an
   entity invisible to `search_nodes` and blank in the UI while still sitting in
   the graph with all its edges. 76 of 587 entities were in this state,
   **including APOE**.

   Root cause in `normalize.py`: a transport failure and "HGNC has no such id"
   both produced an empty doc list, and the result was written to a *persistent*
   disk cache. One timeout therefore made a gene permanently nameless on every
   future run. There was no retry and no throttle at all on 173+ sequential
   requests to `rest.genenames.org`, unlike the CoGEx and PubMed clients which
   both pace themselves. Now retried with backoff, throttled, and a negative is
   cached only on a clean HTTP 200; transport failures are reported and left
   uncached. Re-running took the nameless count from 76 to 0.

6. **Licensing is still unresolved**, as `KNOWN_LIMITATIONS.md` §9 says. Nothing
   here changes that, and the repo still has no LICENSE file.
