"""Machine first pass over the contested review sheet.

This produces a MACHINE label, recorded as such. It is a hypothesis about why a
pair disagrees, not a verified finding: every label must be spot-checked before
any number derived from it is quoted. The categories separate scientific causes
(genuine_disagreement, context_difference) from mechanical ones, because the
whole question is which kind dominates.

Judgement is about the SENTENCES SHOWN, never about the underlying biology.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys

from anthropic import Anthropic

from nucleolus import config
from nucleolus.eval.contested import CATEGORIES

BATCH = 8

SYSTEM = """You audit automated biomedical relation extraction.

For each item you receive one ordered pair of entities and TWO opposing claims
about it, each with the verbatim sentences the extractor used. Decide why the
two sides disagree, judging ONLY whether the sentences support the sign they
were filed under.

Categories:
  genuine_disagreement  comparable evidence, genuinely opposite findings
  context_difference    the sides differ in species, cell type, dose or timepoint
  readout_conflation    the object stands for different things (protein abundance
                        vs activity vs phosphorylation vs disease pathology)
  polarity_error        a sentence states the OPPOSITE of the sign it is under
                        (e.g. "knockdown of X reduced Y" filed as X inhibits Y)
  co_mention_error      the sentence's real subject is a third entity; the filed
                        subject is only co-mentioned
  direction_error       the sentence describes the reverse edge (object acting on
                        subject)
  uninterpretable       the sentences do not support any reading of the claim

Rules:
- Choose the SINGLE most specific applicable category.
- Prefer a mechanical category over genuine_disagreement whenever the sentences
  show a mechanical fault. Genuine disagreement requires both sides to actually
  assert opposite results about the same thing.
- Do not use outside knowledge to adjudicate the biology. Judge the sentences.
- Return JSON only: an array of {"pair_id","label","reason"} with one entry per
  item, in the order received. reason is at most 20 words."""


def build_prompt(items: list[dict]) -> str:
    payload = []
    for item in items:
        def side(key: str) -> dict:
            s = item[key]
            return {
                "predicate": s["predicate"],
                "papers": s["n_papers"],
                "indra_type": s["indra_statement_type"],
                "sentences": [q["quote"] for q in s["quotes"]],
            }
        payload.append({
            "pair_id": item["pair_id"],
            "edge": f'{item["subject"]["name"]} -> {item["object"]["name"]}',
            "raises": side("raises"),
            "lowers": side("lowers"),
        })
    return json.dumps({"items": payload}, ensure_ascii=False)


def classify(sheet: dict, model: str, limit: int | None) -> dict:
    env = config.env()
    key = env.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY is not set")
    client = Anthropic(api_key=key)

    items = sheet["items"][:limit] if limit else sheet["items"]
    by_id = {item["pair_id"]: item for item in items}
    labelled = 0

    for start in range(0, len(items), BATCH):
        chunk = items[start:start + BATCH]
        # No temperature: deprecated on claude-sonnet-5 and rejected with 400.
        # Budget generously: this model emits a thinking block that counts
        # against max_tokens, and truncation shows up as unparseable JSON.
        response = client.messages.create(
            model=model,
            max_tokens=8000,
            system=SYSTEM,
            messages=[{"role": "user", "content": build_prompt(chunk)}],
        )
        if response.stop_reason == "max_tokens":
            print(f"  batch {start // BATCH}: TRUNCATED at max_tokens; reduce BATCH")
        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
        if text.startswith("```"):
            text = text.split("```")[1].removeprefix("json").strip()
        try:
            rows = json.loads(text)
        except json.JSONDecodeError:
            print(f"  batch {start // BATCH}: unparseable response, skipped")
            continue
        if isinstance(rows, dict):
            rows = rows.get("items") or rows.get("results") or []
        for row in rows:
            item = by_id.get(row.get("pair_id"))
            if item is None or row.get("label") not in CATEGORIES:
                continue
            item["label"] = row["label"]
            item["labeller"] = f"MACHINE:{model}"
            item["note"] = (row.get("reason") or "")[:160]
            labelled += 1
        print(f"  batch {start // BATCH + 1}/{(len(items) + BATCH - 1) // BATCH}"
              f"  labelled {labelled}/{len(items)}")

    sheet["machine_pass"] = {
        "model": model,
        "labelled": labelled,
        "of_items": len(items),
        "status": "UNVERIFIED - machine labels require human spot-check before quoting",
    }
    return sheet


def report(sheet: dict) -> None:
    counts = collections.Counter(i["label"] for i in sheet["items"] if i["label"])
    total = sum(counts.values())
    if not total:
        print("no labels produced")
        return
    mechanical = {"readout_conflation", "polarity_error", "co_mention_error",
                  "direction_error", "uninterpretable"}
    scientific = {"genuine_disagreement", "context_difference"}
    print(f"\n=== machine first pass over {total} contested pairs ===")
    for label, n in counts.most_common():
        kind = "scientific" if label in scientific else "extraction fault"
        print(f"  {label:<22} {n:>4}  ({100 * n / total:>4.0f}%)  {kind}")
    sci = sum(counts[k] for k in scientific)
    mech = sum(counts[k] for k in mechanical)
    print(f"\n  scientific causes  {sci:>4}  ({100 * sci / total:.0f}%)")
    print(f"  extraction faults  {mech:>4}  ({100 * mech / total:.0f}%)")
    print("\n  UNVERIFIED: machine labels. Spot-check before quoting the number.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--sheet", default="eval/contested_review.json")
    args = parser.parse_args(argv)

    path = config.REPO_ROOT / args.sheet
    sheet = json.loads(path.read_text(encoding="utf-8"))
    model = args.model or config.env().get("ANTHROPIC_MODEL") or "claude-sonnet-5"

    print(f"[classify] model {model}, {len(sheet['items'])} items, batches of {BATCH}")
    sheet = classify(sheet, model, args.limit)
    path.write_text(json.dumps(sheet, indent=1), encoding="utf-8")
    report(sheet)
    print(f"\n[classify] -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
