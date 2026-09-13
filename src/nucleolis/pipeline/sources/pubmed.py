"""PubMed E-utilities adapter: publication dates, types and retraction status.

Public domain (US Government). No key required; a key raises the rate limit from
3 to 10 requests/second. NCBI requires tool and email metadata on every request.

Why this and not a commercial metadata source: PubMed reports date *precision*
("2018", "2014 Jun", "2014 Jul 17"), which the EXECUTION_PLAN.md s4 contract
requires us to preserve. A normalised ISO date would assert day precision that
the source does not have.

Publication types are the cheapest independence signal available
(HANDOVER.md s9): a claim backed by six reviews and one comment is not backed by
seven studies.
"""
from __future__ import annotations

import time
from typing import Iterable

import httpx

ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
BATCH_SIZE = 200  # NCBI accepts up to ~200 ids per GET comfortably

# Publication types that indicate the paper reports original observations.
# Everything else (Review, Comment, Editorial, ...) is secondary literature.
SECONDARY_TYPES = {
    "Review",
    "Systematic Review",
    "Meta-Analysis",
    "Comment",
    "Editorial",
    "Letter",
    "News",
    "Published Erratum",
    "Retraction of Publication",
    "Congress",
    "Conference Proceedings",
    "Historical Article",
    "Biography",
    "Patient Education Handout",
    "Practice Guideline",
    "Guideline",
}

# Administrative / funding tags. They say who paid, not what was done, so they
# must never on their own make a paper count as a primary study.
NEUTRAL_TYPE_PREFIXES = ("Research Support",)
NEUTRAL_TYPES = {"English Abstract", "Multicenter Study", "Validation Study"}


def _is_neutral(publication_type: str) -> bool:
    return publication_type in NEUTRAL_TYPES or publication_type.startswith(
        NEUTRAL_TYPE_PREFIXES
    )


_MONTHS = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


def parse_pubdate(raw: str | None) -> tuple[str | None, str]:
    """'2014 Jul 17' -> ('2014-07-17', 'day').  '2018' -> ('2018', 'year').

    Returns (value, precision) where precision is one of
    day / month / year / unknown. Missing input stays unknown - never guessed.
    """
    if not raw:
        return None, "unknown"
    text = str(raw).strip()
    if not text:
        return None, "unknown"

    # Ranges like "2014 Jul-Aug" keep only the first month.
    parts = text.replace(",", " ").split()
    if not parts:
        return None, "unknown"

    year = parts[0][:4]
    if not year.isdigit():
        return None, "unknown"

    if len(parts) == 1:
        return year, "year"

    month_token = parts[1][:3].lower()
    month = _MONTHS.get(month_token)
    if month is None:
        # e.g. "2014 Spring" - a real season, not a month. Year precision.
        return year, "year"

    if len(parts) == 2:
        return f"{year}-{month}", "month"

    day_token = parts[2].split("-")[0]
    if day_token.isdigit():
        return f"{year}-{month}-{int(day_token):02d}", "day"
    return f"{year}-{month}", "month"


def classify_types(pubtypes: Iterable[str]) -> tuple[list[str], bool]:
    """Return (types, is_primary). A paper is primary when it carries at least
    one publication type that is not secondary literature."""
    types = [t for t in pubtypes if t]
    if not types:
        return [], False  # unknown stays not-primary rather than assumed primary
    primary = any(
        t not in SECONDARY_TYPES and not _is_neutral(t) for t in types
    )
    return types, primary


class PubMedClient:
    def __init__(
        self,
        tool: str = "nucleolis",
        email: str = "",
        api_key: str = "",
        rate_limit_rps: float | None = None,
    ) -> None:
        self.tool = tool
        self.email = email
        self.api_key = api_key
        # NCBI: 3 req/s without a key, 10 with one.
        rps = rate_limit_rps or (10.0 if api_key else 3.0)
        self._min_interval = 1.0 / rps
        self._last_call = 0.0
        self._client = httpx.Client(timeout=60.0, headers={"User-Agent": "nucleolis/0.1"})
        self.calls = 0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PubMedClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call = time.monotonic()

    def _params(self, pmids: list[str]) -> dict:
        params = {
            "db": "pubmed",
            "retmode": "json",
            "id": ",".join(pmids),
            "tool": self.tool,
        }
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def summaries(self, pmids: list[str]) -> dict[str, dict]:
        """Fetch ESummary records for up to BATCH_SIZE PMIDs.

        Returns {pmid: normalized_record}. PMIDs NCBI does not return are simply
        absent - never filled with a placeholder.
        """
        if not pmids:
            return {}
        out: dict[str, dict] = {}
        for attempt in range(3):
            self._throttle()
            try:
                response = self._client.get(ESUMMARY, params=self._params(pmids))
                self.calls += 1
            except httpx.HTTPError:
                time.sleep(2**attempt)
                continue
            if response.status_code != 200:
                time.sleep(2**attempt)
                continue
            try:
                payload = response.json()
            except ValueError:
                time.sleep(2**attempt)
                continue

            result = payload.get("result", {})
            for uid in result.get("uids", []):
                record = result.get(uid, {})
                if record.get("error"):
                    continue
                date, precision = parse_pubdate(record.get("pubdate"))
                types, is_primary = classify_types(record.get("pubtype") or [])
                out[str(uid)] = {
                    "publication_date": date,
                    "date_precision": precision,
                    "publication_types": types,
                    "is_primary": is_primary,
                    "journal": record.get("fulljournalname") or record.get("source"),
                    "retraction_status": (
                        "retracted"
                        if "Retracted Publication" in types
                        else "not_flagged"
                    ),
                }
            return out
        return out

    def summaries_for_all(self, pmids: list[str], progress=None) -> dict[str, dict]:
        """Batch over an arbitrary number of PMIDs."""
        unique = sorted({str(p) for p in pmids if p})
        out: dict[str, dict] = {}
        for index in range(0, len(unique), BATCH_SIZE):
            chunk = unique[index : index + BATCH_SIZE]
            out.update(self.summaries(chunk))
            if progress:
                progress(min(index + BATCH_SIZE, len(unique)), len(unique))
        return out
