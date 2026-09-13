"""Four-slot extraction schema.

Why this shape: INDRA flattens a sentence to a binary statement, and the role of
each entity is lost. Measured on our own snapshot, that single design choice
accounts for most of the apparent disagreement in the graph - 37% polarity
inversion and 25% co-mention, against 13% genuine scientific causes.

The fix is not a downstream filter. It is to extract the roles:

    (intervention, stimulus/context, readout, direction)

A sentence whose subject is the *stimulus* never becomes a causal edge. It
becomes context on someone else's edge, which is both cleaner and richer:
"theanine inhibits TNF UNDER LPS CHALLENGE" beats "theanine inhibits TNF",
and crucially it never mints "LPS inhibits TNF".

Readout state is explicit because "MAPT" in a binary graph silently merges
protein abundance, phosphorylation state, and disease pathology - responsible
for another 11% of the apparent contradictions.

Locally-extracted claims carry `confidence`, never `belief`. Copying INDRA's
field name would launder a model's guess into a statistic.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["intervention", "stimulus", "readout", "mediator", "unclear"]
ReadoutState = Literal["abundance", "activity", "phosphorylation", "localisation",
                       "pathology", "function", "unspecified"]
System = Literal["in_vivo", "ex_vivo", "primary_culture", "cell_line",
                 "cell_free", "human_subject", "unspecified"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Mention(Model):
    """A surface mention plus the catalog ID it was matched to, if any."""
    text: str = Field(max_length=120, description="verbatim span from the sentence")
    candidate_id: str | None = Field(
        default=None, max_length=64,
        description="ID copied EXACTLY from the supplied catalog, or null")
    resolution: Literal["matched", "not_in_catalog", "ambiguous"] = "not_in_catalog"


class ExtractedClaim(Model):
    """One directional claim, with the roles that make it interpretable."""

    # --- the four slots ---------------------------------------------------
    intervention: Mention = Field(description="the entity that was perturbed")
    intervention_direction: Literal["increase", "decrease", "knockout",
                                    "overexpression", "unspecified"]
    readout: Mention = Field(description="the entity that was measured")
    readout_state: ReadoutState
    readout_direction: Literal["increase", "decrease", "no_change", "unclear"]
    stimulus: Mention | None = Field(
        default=None,
        description="background challenge, e.g. LPS. NEVER treat as the intervention")

    # --- conditions, absent from INDRA entirely ---------------------------
    species: str | None = Field(default=None, max_length=60)
    system: System = "unspecified"
    dose: str | None = Field(default=None, max_length=80,
                             description="verbatim if stated, else null")
    duration: str | None = Field(default=None, max_length=80)

    # --- provenance -------------------------------------------------------
    sentence: str = Field(max_length=1200, description="verbatim, unedited")
    is_restatement: bool = Field(
        default=False,
        description="true when the sentence attributes the finding to other work")
    confidence: Literal["high", "medium", "low"]
    note: str | None = Field(default=None, max_length=200)


class PaperExtraction(Model):
    """All claims from one paper. Empty is a valid, common answer."""
    pmid: str = Field(max_length=20)
    claims: list[ExtractedClaim] = Field(default_factory=list, max_length=12)
    no_claims_reason: str | None = Field(default=None, max_length=200)


def signed_direction(claim: ExtractedClaim) -> int | None:
    """Compose the intervention and readout directions into one sign.

    decrease(X) -> decrease(Y)  implies  X raises Y.
    A no_change or unclear readout yields no sign at all; it is never guessed,
    and a stimulus-subject sentence must not reach this function.
    """
    lower = {"decrease", "knockout"}
    raise_ = {"increase", "overexpression"}
    if claim.intervention_direction == "unspecified":
        return None
    if claim.readout_direction in {"no_change", "unclear"}:
        return None
    intervention_sign = 1 if claim.intervention_direction in raise_ else (
        -1 if claim.intervention_direction in lower else None)
    if intervention_sign is None:
        return None
    readout_sign = 1 if claim.readout_direction == "increase" else -1
    return intervention_sign * readout_sign
