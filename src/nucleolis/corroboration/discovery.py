"""Deterministic search queries for a claim.

Built only from grounded snapshot names and the claim's own predicate; no model
invents synonyms. The opposite direction is always searched, so contradicting
evidence is not structurally harder to find than support.
"""
from __future__ import annotations

_WORDING = {
    "activates": ("activates", "inhibits"),
    "inhibits": ("inhibits", "activates"),
    "increases_amount": ("increases expression of", "decreases expression of"),
    "decreases_amount": ("decreases expression of", "increases expression of"),
}
_MODIFICATIONS = {"Phosphorylation": "phosphorylation", "Ubiquitination": "ubiquitination",
                  "Acetylation": "acetylation", "Methylation": "methylation"}


def queries_for_claim(subject: str, object_: str, predicate: str,
                      statement_type: str | None = None, max_variants: int = 3) -> list[str]:
    s, o = subject.replace('"', "").strip(), object_.replace('"', "").strip()
    queries = []
    if predicate in _WORDING:
        asserted, opposite = _WORDING[predicate]
        queries += [f'"{s}" {asserted} "{o}"', f'"{s}" {opposite} "{o}"']
    if statement_type in _MODIFICATIONS:
        queries.append(f'"{s}" "{o}" {_MODIFICATIONS[statement_type]}')
    queries.append(f'"{s}" "{o}"')
    # Asserted and opposite come first, so the cap can never drop the contradiction query.
    unique = list(dict.fromkeys(queries))
    return unique[:max(2, max_variants)]
