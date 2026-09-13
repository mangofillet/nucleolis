"""Which sources are curated databases and which are machine reading.

Measured on this corpus, INDRA belief does not separate extraction faults from
genuine disagreement: across the 91 hand-labelled contested pairs, fault pairs
have a median belief of 0.4845 against 0.4792 for genuine ones, and every
category bottoms out at the same 0.436. What belief does track is the extracting
reader - a single REACH sentence ranges 0.366-0.694 depending on which rule
fired, while all ten BioGRID-only claims sit at exactly 0.8302.

Source class is the interpretable half of that: a curated database entry was
written by a human curator, a machine-read claim was not. That distinction is
worth showing; the score is not.

Types are INDRA's own, from indra/resources/source_info.json, where every source
is typed either "reader" or "database".
"""
from __future__ import annotations

READERS = frozenset({
    "reach", "sparser", "medscan", "eidos", "trips", "isi", "rlimsp", "tees",
    "geneways", "semrep", "gnbr", "r3", "tkg",
})

DATABASES = frozenset({
    "biogrid", "signor", "hprd", "conib", "bel", "biopax", "trrust", "phosphosite",
    "phosphoelm", "ctd", "drugbank", "omnipath", "tas", "dgi", "ndex", "virhostnet",
    "crog", "creeds", "ubibrowser", "acsn", "minerva", "biofactoid", "hypothes.is",
    "wormbase", "signor_complex", "assertion",
})

LABELS = {
    "curated_database": "curated database",
    "machine_read": "machine-read text",
    "mixed": "curated database and machine-read text",
    "unknown": "source not classified",
}


def classify(source_counts: dict | None) -> dict:
    """Split a claim's sources into curated and machine-read. Unknown stays unknown."""
    counts = {str(k): v for k, v in (source_counts or {}).items()}
    databases = sorted(s for s in counts if s.lower() in DATABASES)
    readers = sorted(s for s in counts if s.lower() in READERS)
    unknown = sorted(s for s in counts if s.lower() not in DATABASES and s.lower() not in READERS)
    if databases and readers:
        source_class = "mixed"
    elif databases:
        source_class = "curated_database"
    elif readers:
        source_class = "machine_read"
    else:
        source_class = "unknown"
    return {
        "source_class": source_class,
        "source_class_label": LABELS[source_class],
        "database_sources": databases,
        "reader_sources": readers,
        "unclassified_sources": unknown,
        "distinct_sources": len(counts),
    }
