"""The corroboration stage: optional, bounded, and unable to change the graph.

Failure here is always an enrichment problem, never a simulation problem: every
AMASS error is caught, sanitized, and reported as partial or unavailable while
the deterministic result stands. A request cannot escalate to live mode when the
server has not enabled it, and cached records are only reused when the snapshot,
claim, context, classifier and review policy all still match.
"""
from __future__ import annotations

import time

from nucleolis.corroboration import cache, discovery, fixtures, rules
from nucleolis.pipeline.sources.amass import AmassClient, AmassError, parse_record, passage_text
from nucleolis.schemas.corroboration import AmassCorroborationSummary, ClaimCorroboration, CorroborationRequest


def claims_for_response(response, snap) -> list[dict]:
    """Claims on displayed paths only - never every edge in the snapshot."""
    from nucleolis.corroboration import identity

    if response.analysis is None:
        return []
    displayed = [cid for result in (response.analysis.baseline, response.analysis.after_exclusion) if result
                 for path in result.paths for cid in path.claim_ids]
    links = {link.id: link for link in response.links}
    claims = []
    for claim_id in dict.fromkeys(displayed):
        link = links.get(claim_id)
        if link is None:
            continue
        stored = snap.claims.get(claim_id) or {}
        documents = [snap.documents.get(pid) or {} for pid in link.publication_ids]
        claims.append({
            "id": claim_id,
            "subject_name": (snap.entities.get(link.source) or {}).get("preferred_name") or link.source,
            "object_name": (snap.entities.get(link.target) or {}).get("preferred_name") or link.target,
            "predicate": link.predicate,
            "sign": link.sign,
            "statement_type": (stored.get("qualifiers_json") or {}).get("indra_statement_type"),
            "context_id": stored.get("context_id"),
            "source_class": link.source_class,
            "snapshot_checksum": snap.checksum,
            "pmids": [d["pmid"] for d in documents if d.get("pmid")],
            "dois": [d["doi"] for d in documents if d.get("doi")],
            "indra_keys": {key for d in documents for key in identity.strong_keys(d)},
        })
    return claims


def effective_mode(settings, requested: str) -> str:
    """Server settings constrain the request. Never a silent escalation to live."""
    if not settings.amass_enabled or settings.amass_mode == "disabled" or requested == "disabled":
        return "disabled"
    if requested == "live" and settings.amass_mode != "live":
        return "cached"
    return requested if requested in {"cached", "live"} else settings.amass_mode


def _summary(settings, mode: str, status: str, **kwargs) -> AmassCorroborationSummary:
    return AmassCorroborationSummary(status=status, mode=mode, review_policy=settings.review_policy,
                                     cache_version=cache.CACHE_VERSION, **kwargs)


class CorroborationService:
    def __init__(self, settings, classifier=None, client=None):
        self.settings, self.classifier, self.client = settings, classifier, client

    def _cache_key(self, claim: dict) -> str:
        return cache.key(snapshot_checksum=claim.get("snapshot_checksum"), claim_id=claim["id"],
                         sign=claim.get("sign"), context_id=claim.get("context_id"),
                         classifier=getattr(self.classifier, "method", "metadata_only"),
                         policy=self.settings.review_policy,
                         include_fulltext=self.settings.amass_include_fulltext)

    async def run(self, claims: list[dict], request: CorroborationRequest | None = None,
                  *, synthetic: bool = False, snapshot_checksum: str | None = None) -> AmassCorroborationSummary:
        settings = self.settings
        if synthetic:
            return fixtures.demo_summary()
        request = request or CorroborationRequest(mode="disabled")
        mode = effective_mode(settings, request.mode)
        if mode == "disabled":
            reason = ("AMASS corroboration is disabled on this server." if not settings.amass_enabled
                      else "Corroboration was not requested.")
            return _summary(settings, "disabled", "not_requested", warnings=[reason],
                            snapshot_checksum=snapshot_checksum)
        selected = claims[:min(request.max_claims, settings.amass_max_claims)]
        if mode == "cached":
            return self._from_cache(selected, snapshot_checksum)
        return await self._live(selected, request, snapshot_checksum)

    def _from_cache(self, claims: list[dict], snapshot_checksum: str | None) -> AmassCorroborationSummary:
        found, retrieved, warnings = [], None, []
        for claim in claims:
            hit = cache.read(self._cache_key(claim))
            if hit is None:
                warnings.append(f"No materialized corroboration for {claim['id']}; nothing was retrieved live.")
                continue
            found.append(hit[0])
            retrieved = retrieved or hit[1]
        status = "completed" if found and len(found) == len(claims) else "partial" if found else "unavailable"
        return _summary(self.settings, "cached", status, claims_assessed=len(found), records_examined=0,
                        from_cache=True, retrieved_at=retrieved, corroborations=found, warnings=warnings[:40],
                        snapshot_checksum=snapshot_checksum)

    async def _live(self, claims: list[dict], request: CorroborationRequest,
                    snapshot_checksum: str | None) -> AmassCorroborationSummary:
        settings = self.settings
        try:
            client = self.client or AmassClient(
                settings.amass_api_key.get_secret_value(), settings.amass_base_url,
                timeout=settings.amass_timeout, max_calls=settings.amass_max_calls,
                deadline_seconds=settings.amass_timeout * settings.amass_max_calls)
        except AmassError as exc:
            return _summary(settings, "live", "unavailable", warnings=[exc.message],
                            snapshot_checksum=snapshot_checksum)
        results, warnings, examined, truncated = [], [], 0, False
        try:
            for claim in claims:
                assessment, seen, hit_limit = await self._assess(client, claim, request)
                results.append(assessment)
                examined += seen
                truncated = truncated or hit_limit
                cache.write(self._cache_key(claim), assessment, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        except AmassError as exc:
            warnings.append(exc.message)
        except OSError:
            warnings.append("Corroboration records could not be cached; the assessment was still computed.")
        status = "completed" if results and not warnings else "partial" if results else "unavailable"
        return _summary(settings, "live", status, claims_assessed=len(results), calls_used=client.calls_used,
                        records_examined=examined, corroborations=results, truncated=truncated,
                        retrieved_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        warnings=warnings[:40], snapshot_checksum=snapshot_checksum)

    async def _assess(self, client, claim: dict, request: CorroborationRequest) -> tuple[ClaimCorroboration, int, bool]:
        settings = self.settings
        documents, passages, queries, raw_by_id = [], [], [], {}
        indra_items = [{"pmid": p} for p in claim.get("pmids", [])] + [{"doi": d} for d in claim.get("dois", [])]
        for row in await client.lookup(indra_items[:settings.amass_max_record_fetches]):
            for amass_id in row.get("amassIds") or []:
                raw_by_id[amass_id] = {"amassId": amass_id, **{k: v for k, v in (row.get("input") or {}).items()}}
        truncated = False
        if request.discover_additional_publications:
            queries = discovery.queries_for_claim(claim["subject_name"], claim["object_name"], claim["predicate"],
                                                  claim.get("statement_type"))
            for query in queries:
                rows = await client.search(query, limit=settings.amass_max_search_results,
                                           include_fulltext=settings.amass_include_fulltext)
                truncated = truncated or len(rows) >= settings.amass_max_search_results
                for raw in rows[:settings.amass_max_record_fetches]:
                    if raw.get("amassId"):
                        raw_by_id.setdefault(raw["amassId"], raw)
        for amass_id, raw in list(raw_by_id.items())[:settings.amass_max_record_fetches]:
            record = parse_record(raw)
            if record is None:
                continue
            documents.append(record)
            text = passage_text(raw)
            if text and self.classifier is not None:
                classified = await self.classifier.classify(
                    {"id": claim["id"], "subject": claim["subject_name"], "object": claim["object_name"],
                     "predicate": claim["predicate"], "asserted_direction": claim.get("sign")},
                    fixtures.publication_id(record), amass_id, text[0], text[1])
                if classified is not None:
                    passages.append(classified)
        return rules.categorize(
            claim["id"], set(claim.get("indra_keys") or set()), documents, passages,
            source_classes=[claim.get("source_class", "unknown")], searched_queries=queries,
            searched=bool(queries), truncated=truncated, policy=settings.review_policy,
            allow_partial_context=settings.allow_partial_context), len(documents), truncated
