"""Grounding stage: extracted mentions -> stable identifiers.

Deliberately separate from extraction. The model's job is to find mentions and
roles; deciding what a mention *is* must be deterministic and auditable, because
a hallucinated identifier is indistinguishable from a real one downstream.

Resolution is HGNC-only for now, in three ordered attempts:
  1. exact symbol match
  2. alias / previous-symbol match
  3. strip decoration a sentence adds ("OPTN (optineurin) ablation" -> OPTN)

Anything unresolved stays unresolved and is reported. Nothing is guessed, and a
near-miss is never promoted to a match - EXECUTION_PLAN.md s4: "Unknown
grounding is recorded, never invented."
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import time
import urllib.parse
import urllib.request

from nucleolis import config

HGNC_SEARCH = "https://rest.genenames.org/search/{field}/{value}"

# Decoration a sentence wraps around a symbol. Order matters: longest first.
STRIP_PATTERNS = [
    r"\b(knock(?:out|down)|ablation|deletion|silencing|overexpression|"
    r"re-?expression|inhibition|activation|depletion|loss|deficiency|"
    r"mutation|mutations|variant|variants|expression|levels?|protein|mRNA)\b",
    r"\bp\.[A-Za-z0-9*]+\b",          # p.E696K
    r"\([^)]*\)",                       # parenthetical gloss
    r"\b(pathogenic|early|late|total|human|murine|mouse)\b",
]


def candidates(mention: str) -> list[str]:
    """Surface forms worth trying, most literal first."""
    text = mention.strip()
    out = [text]
    cleaned = text
    for pattern in STRIP_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.I)
    cleaned = re.sub(r"[^A-Za-z0-9\-/ ]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned and cleaned != text:
        out.append(cleaned)
    # "VCP/p97" and "Sqstm1/p62" -> try each side
    for part in re.split(r"[/]", cleaned):
        part = part.strip()
        if len(part) >= 2 and part not in out:
            out.append(part)
    # a single token is usually the symbol
    tokens = [t for t in cleaned.split() if len(t) >= 2]
    if len(tokens) == 1 and tokens[0] not in out:
        out.append(tokens[0])
    return out


def _query(field: str, value: str) -> list[dict]:
    url = HGNC_SEARCH.format(field=field, value=urllib.parse.quote(value))
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)["response"]["docs"]
    except Exception:
        return []


def resolve(mention: str, cache: dict) -> dict:
    """Return {id, symbol, matched_on} or {id: None, reason}."""
    key = mention.lower().strip()
    if key in cache:
        return cache[key]

    result = {"id": None, "symbol": None, "matched_on": None,
              "reason": "no HGNC record for any surface form"}
    for surface in candidates(mention):
        if not surface or len(surface) > 40:
            continue
        for field in ("symbol", "alias_symbol", "prev_symbol"):
            docs = _query(field, surface)
            # Only an unambiguous single hit counts. Several hits means ambiguous.
            exact = [d for d in docs if (d.get("symbol") or "").upper() == surface.upper()]
            chosen = exact or (docs if len(docs) == 1 else [])
            if len(chosen) == 1:
                doc = chosen[0]
                result = {"id": doc["hgnc_id"], "symbol": doc.get("symbol"),
                          "matched_on": f"{field}:{surface}", "reason": None}
                cache[key] = result
                time.sleep(0.1)
                return result
            if len(docs) > 1 and not exact:
                result = {"id": None, "symbol": None, "matched_on": None,
                          "reason": f"ambiguous: {len(docs)} HGNC hits for '{surface}'"}
            time.sleep(0.1)
    cache[key] = result
    return result


def ground_file(path, cache_path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}

    mentions = set()
    for claim in payload["claims"]:
        mentions.add(claim["intervention"]["text"])
        mentions.add(claim["readout"]["text"])
    print(f"[ground] {len(mentions)} distinct mentions to resolve")

    for index, mention in enumerate(sorted(mentions), start=1):
        resolve(mention, cache)
        if index % 20 == 0:
            print(f"         {index}/{len(mentions)}")
    cache_path.write_text(json.dumps(cache, indent=1), encoding="utf-8")

    stats = collections.Counter()
    for claim in payload["claims"]:
        for slot in ("intervention", "readout"):
            hit = cache.get(claim[slot]["text"].lower().strip(), {})
            if hit.get("id"):
                claim[slot]["candidate_id"] = hit["id"]
                claim[slot]["resolution"] = "matched"
                claim[slot]["grounded_symbol"] = hit["symbol"]
                claim[slot]["matched_on"] = hit["matched_on"]
                stats[f"{slot}_matched"] += 1
            else:
                claim[slot]["resolution"] = (
                    "ambiguous" if "ambiguous" in (hit.get("reason") or "") else "not_in_catalog")
                claim[slot]["ground_reason"] = hit.get("reason")
                stats[f"{slot}_unresolved"] += 1
        claim["grounded_both_ends"] = bool(
            claim["intervention"].get("candidate_id") and claim["readout"].get("candidate_id"))

    payload["grounding"] = {
        "resolver": "HGNC REST (symbol, alias_symbol, prev_symbol)",
        "distinct_mentions": len(mentions),
        **dict(stats),
    }
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default="data/extracted_claims.json")
    args = parser.parse_args(argv)

    path = config.REPO_ROOT / args.file
    cache_path = config.data_dir() / "hgnc_mention_cache.json"
    payload = ground_file(path, cache_path)

    claims = payload["claims"]
    both = [c for c in claims if c["grounded_both_ends"]]
    signed = [c for c in both if c.get("signed_direction") is not None]
    print(f"\n[ground] claims                {len(claims)}")
    print(f"[ground]   grounded both ends   {len(both)}  ({100*len(both)/max(1,len(claims)):.0f}%)")
    print(f"[ground]   signed + grounded    {len(signed)}")
    print(f"[ground] -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
