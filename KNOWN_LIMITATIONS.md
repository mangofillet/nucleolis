# Known limitations

Measured against snapshot `demo_v3` (32 entities, 669 claims, 2,916 papers,
6,373 evidence records), built 2026-09-12 from INDRA CoGEx and enriched from
PubMed.

Read this before demoing. Every number here came from the snapshot, not from an
estimate.

## 1. Nothing has been reviewed by a domain scientist

All 669 claims are automatically extracted by upstream INDRA readers (mostly
REACH) and curated databases. No biologist has checked any of them against the
source sentence. `review_status` is `unreviewed` on all 6,373 evidence records.

A concrete example found in this snapshot. The claim `ATXN2 inhibits TARDBP`
(19 papers) is supported by PMID 24954906, whose sentence reads:

> "the depletion of Ataxin-2 significantly decreased the half-lives of Ataxin-2
> target mRNAs, namely ARL6IP1, FAM199X, TARDBP, and Cyclin D1"

Depletion of ATXN2 *decreasing* TARDBP implies ATXN2 **increases** TARDBP. The
sentence appears to contradict the sign it was filed under. This is the class of
error a human review layer exists to catch, and it is why the tool shows the
quote next to every claim rather than only the arrow.

## 2. Publication dates — RESOLVED, with residue

Fixed by a PubMed ESummary backfill (15 calls, free, public domain).
**2,875 of 2,916 documents now carry a date**, with precision preserved:

| precision | documents |
|---|---|
| day | 1,304 |
| month | 1,062 |
| year only | 509 |
| unknown | 41 |

1,571 documents are *not* day-precision. A source that normalises everything to
an ISO date would have asserted precision the literature does not have.

Residue: 41 documents (39 with no PMID, 2 PMIDs NCBI did not return) stay
undated and are excluded from date ranges rather than assigned a guess.

### 2b. Publication type and retraction — new

The same call returns publication types, which is the cheapest independence
signal (HANDOVER.md §9):

- **2,852 primary · 23 secondary · 41 unknown.** Funding tags
  ("Research Support, N.I.H., Extramural") are treated as neutral: they say who
  paid, not that a study was run.
- **4 retracted papers** are in the corpus, supporting 6 claims.
- **2 claims have their only support retracted** — `FUS decreases_amount TP53`
  and `MAPT increases_amount TP53`. Both are flagged in the UI as having no
  surviving evidence. They are not deleted; a reader needs to see them.
- Sentence-per-paper inflation: median 1.0×, **max 19.5×**. One claim restates
  a handful of papers nineteen times over.

## 3. Species is present on a minority of evidence, cell type barely at all

840 of 6,373 evidence records (13%) carry structured context. Within the 76
distinct contexts: 74 have a taxon, 16 have a cell type, 3 have a tissue.

Species is **displayed** per quote (human / mouse / rat / yeast / *C. elegans*),
and evidence with no stated species is labelled "species not stated" rather than
assumed human. But because 87% of evidence has no species at all, species is not
yet a *filter* — filtering would silently hide most of the evidence.

This is the weakest point relative to the plan's §1 requirement that animal-model
findings never merge silently into human findings. Today the tool marks what it
knows and is explicit about what it does not.

## 4. Sign disagreement is the norm, not a rare signal

Of 232 ordered gene pairs with at least one supported signed claim, **117 (50%)
are supported in both directions**, with a median minority share of 38%.

So "this tool surfaces contradictions" needs qualifying: at this extraction
quality, bare sign disagreement carries little information. The UI therefore
shows the support ratio (e.g. `41↑ / 19↓`) rather than a "conflicting" badge that
would fire on half the graph. Distinguishing genuine biological disagreement from
extraction noise needs context and human review — neither of which exists yet.

## 5. Coverage is a small, deliberately bounded slice

- 60-node query ceiling; 32 entities actually had relations among them.
- 1-hop neighbourhoods, capped at 200 nodes / 500 edges.
- Path search: ≤5 simple paths. **Signed claims are capped at 2 hops**
  (HANDOVER.md §10): INDRA belief runs 0.37–0.66, and compounding three of those
  before parse and sign-composition error produces a number with no meaning.
  Hop 3+ is available only as unsigned reachability.
- Paths are ranked by the **thinnest supporting step**, discounted by
  intermediate promiscuity (`1/log10(degree)`). Before this, every
  TARDBP→SQSTM1 route ran through the same two hubs; afterwards the direct
  TBK1→OPTN→SQSTM1 autophagy axis surfaces. Truncation is still reported, and a
  truncated search **cannot** establish that no path exists.
- 18 relations used statement types outside the vocabulary (Ubiquitination ×8,
  Deubiquitination ×4, Methylation ×3, Acetylation, Demethylation,
  Deglycosylation). They are preserved in raw storage and counted, never silently
  dropped — but they do not appear in the graph. Ubiquitination is arguably
  relevant to SQSTM1/OPTN autophagy biology and is a vocabulary candidate.

## 6. Support counts are publications, not independent studies

`support_count` is distinct PMIDs. Three papers from one group replicating each
other count as three. The tool says "N papers", never "N independent studies".

## 7. 15 signed claims have zero supporting publications

Their evidence records carry no resolvable PMID/PMCID/DOI. They are kept (the
relation is real in the source) but contribute nothing to support counts, and the
conflict logic ignores them.

## 8. Negation is implemented but untested against real data

0 of 6,373 evidence records are marked negated. The code path exists and is unit
tested against fixtures, but this snapshot cannot demonstrate it.

## 9. Licensing is unresolved

INDRA aggregates upstream readers and databases with differing terms. A
successful public API probe does not establish bulk reuse or redistribution
rights. This must be settled before any commercial use or public hosting.

## 10. Not built at all

Update: the separate `/api/simulate-target` LLM sandwich and Intervention UI are
now implemented. They require a checksum-bound review manifest for real evidence
analysis. No existing evidence has been promoted to reviewed status. The original
`/ask` route remains 501. See `docs/INTERVENTION_SETUP.md` for supported methods,
provider configuration, and the explicitly synthetic software demo.

`/ask` returns 501. No SIGNOR/GO/OmniPath adapters, no LLM extraction, no
precision gate, no evaluation set, no golden queries. AMASS is probed and its
access verified but the adapter is disabled pending reuse terms.

The §7 temporal benchmark is now *possible* (dates exist, and AMASS exposes
`minPublicationDate`/`maxPublicationDate`) but is **not done**: it needs a frozen
pre-cutoff corpus, a candidate universe, and predefined baselines. Dates alone do
not make it a validated prediction — current curation and current seed selection
still leak later knowledge, so any result would be a retrospective
publication-date reconstruction, and must be labelled as one.
