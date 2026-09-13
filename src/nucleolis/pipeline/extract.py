"""Extraction stage: papers -> role-aware claims.

The piece HANDOVER.md s8 lists as unwritten and SIMULATION.md s3.1 calls "the
irreplaceable fix". Measured justification, from this snapshot: of 91 contested
pairs, ~87% disagree because of extraction faults (37% polarity inversion,
25% co-mention, 11% readout conflation) and only ~13% for scientific reasons.

Pipeline position: an alternative front end to retrieve.py. Everything
downstream - normalize's contract, the snapshot builder, the bounded graph,
pathway ranking, the API and all three UI views - is source agnostic and works
unchanged.

Grounding is deliberately closed-world: the model may only copy IDs from the
catalog it is given. Anything else is recorded as not_in_catalog and never
invented into an identifier.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from openai import AsyncOpenAI, APIError
from pydantic import ValidationError

from nucleolis import config
from nucleolis.llm.common import provider_schema
from nucleolis.pipeline.extract_schema import PaperExtraction, signed_direction

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

SYSTEM = """You extract causal claims from biomedical text for a research tool.

For every sentence that reports a directional experimental result, identify FOUR
things separately. Getting the roles right is the whole point of this task.

  intervention  the entity the experimenters PERTURBED (knocked out, inhibited,
                overexpressed, administered)
  stimulus      a background challenge present in the experiment, such as LPS,
                hypoxia or a disease model. A stimulus is NEVER the intervention.
  readout       the entity that was MEASURED
  direction     what happened to the readout

The single most important rule: in "LPS-induced TNF release was suppressed by
theanine", the intervention is theanine, the stimulus is LPS, the readout is
TNF, and the readout direction is decrease. It is NOT a claim that LPS
suppresses TNF. If you cannot tell which entity was perturbed, set confidence
low or omit the claim.

Also required:
- readout_state: is the measurement about abundance, activity, phosphorylation,
  localisation, pathology or function? Never conflate them.
- species, system, dose, duration: verbatim when stated, null when not. Never
  infer species from context or assume human.
- sentence: the verbatim sentence, unedited.
- is_restatement: true when the sentence attributes the finding to OTHER work
  ("previously shown", "it has been reported", "X et al. found"). Those are not
  this paper's observations.
- candidate_id: copy an ID EXACTLY from the supplied catalog, or null with
  resolution not_in_catalog. Never invent or adapt an identifier.

Omit sentences that are background, motivation, method description or pure
correlation with no direction. Returning an empty claims list is correct and
common. Output JSON only."""


def search(query: str, retmax: int, mindate: str | None = None) -> list[str]:
    params = {"db": "pubmed", "term": query, "retmax": str(retmax),
              "retmode": "json", "sort": "relevance", "tool": "nucleolis",
              "email": config.env().get("NCBI_EMAIL", "")}
    if mindate:
        params.update({"mindate": mindate, "datetype": "pdat"})
    url = ESEARCH + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)["esearchresult"].get("idlist", [])


def fetch_abstracts(pmids: list[str]) -> list[dict]:
    """Title + abstract + MeSH per PMID. Free, and MeSH gives species/system."""
    out = []
    for start in range(0, len(pmids), 100):
        chunk = pmids[start:start + 100]
        params = {"db": "pubmed", "id": ",".join(chunk), "retmode": "xml",
                  "tool": "nucleolis", "email": config.env().get("NCBI_EMAIL", "")}
        url = EFETCH + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=90) as response:
            root = ET.fromstring(response.read())
        for article in root.iter("PubmedArticle"):
            pmid_el = article.find(".//PMID")
            if pmid_el is None:
                continue
            chunks = []
            for node in article.iter("AbstractText"):
                label = node.get("Label")
                text = "".join(node.itertext()).strip()
                if text:
                    chunks.append(f"{label}: {text}" if label else text)
            mesh = [d.findtext("DescriptorName") or "" for d in article.iter("MeshHeading")]
            out.append({
                "pmid": pmid_el.text,
                "title": (article.findtext(".//ArticleTitle") or "").strip(),
                "abstract": " ".join(chunks),
                "mesh": [m for m in mesh if m],
            })
        time.sleep(0.4)  # NCBI: 3 requests/second without a key
    return out


async def extract_paper(client, model: str, paper: dict, catalog: list[dict],
                        schema: dict) -> PaperExtraction | None:
    user = json.dumps({
        "pmid": paper["pmid"],
        "title": paper["title"],
        "abstract": paper["abstract"],
        "mesh_terms": paper["mesh"][:25],
        "entity_catalog": catalog,
        "output_schema": schema,
    }, ensure_ascii=False)
    try:
        response = await client.chat.completions.create(
            model=model, max_tokens=4000, temperature=0,
            response_format={"type": "json_schema", "json_schema": {
                "name": "paper_extraction", "strict": True, "schema": schema}},
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": user}])
    except APIError as exc:
        print(f"    {paper['pmid']}: provider error {str(exc)[:70]}")
        return None
    choice = response.choices[0] if response.choices else None
    if not choice or choice.finish_reason != "stop" or not choice.message.content:
        print(f"    {paper['pmid']}: incomplete ({choice.finish_reason if choice else 'none'})")
        return None
    try:
        return PaperExtraction.model_validate_json(choice.message.content)
    except ValidationError as exc:
        print(f"    {paper['pmid']}: schema invalid {str(exc)[:70]}")
        return None


async def run(query: str, retmax: int, concurrency: int) -> dict:
    env = config.env()
    key, base = env.get("NEBIUS_API_KEY", "").strip(), env.get("NEBIUS_BASE_URL", "").strip()
    model = env.get("NEBIUS_MODEL", "").strip()
    if not (key and model):
        raise SystemExit("Set NEBIUS_API_KEY and NEBIUS_MODEL")

    # Closed-world catalog from the active snapshot's entities.
    from nucleolis.analysis import grounding
    from nucleolis.graph import queries
    snap = queries.load_snapshot()
    catalog = [{"id": e["id"], "name": e.get("preferred_name")}
               for e in snap.entities.values()]

    print(f"[extract] query: {query}")
    pmids = search(query, retmax)
    print(f"[extract] PubMed returned {len(pmids)} PMIDs")
    papers = fetch_abstracts(pmids)
    papers = [p for p in papers if len(p["abstract"]) > 200]
    print(f"[extract] {len(papers)} with a usable abstract")
    print(f"[extract] catalog: {len(catalog)} entities  model: {model}")

    schema = provider_schema(PaperExtraction)
    client = AsyncOpenAI(api_key=key, base_url=base, timeout=120.0, max_retries=1)
    semaphore = asyncio.Semaphore(concurrency)

    async def guarded(paper):
        async with semaphore:
            return paper, await extract_paper(client, model, paper, catalog, schema)

    started = time.monotonic()
    results = await asyncio.gather(*(guarded(p) for p in papers))
    await client.close()
    elapsed = time.monotonic() - started

    claims, failed = [], 0
    for paper, extraction in results:
        if extraction is None:
            failed += 1
            continue
        for claim in extraction.claims:
            row = claim.model_dump()
            row["pmid"] = paper["pmid"]
            row["signed_direction"] = signed_direction(claim)
            row["grounded_both_ends"] = bool(
                claim.intervention.candidate_id and claim.readout.candidate_id)
            claims.append(row)

    return {
        "query": query,
        "model": model,
        "papers_searched": len(pmids),
        "papers_extracted": len(papers) - failed,
        "papers_failed": failed,
        "seconds": round(elapsed, 1),
        "claims": claims,
        "status": "UNREVIEWED machine extraction; precision must be measured "
                  "before any claim is presented as evidence",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default=
        "(TBK1 OR OPTN OR SQSTM1) AND (autophagy OR mitophagy) AND "
        "(amyotrophic lateral sclerosis OR frontotemporal)")
    parser.add_argument("--retmax", type=int, default=30)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--out", default="data/extracted_claims.json")
    args = parser.parse_args(argv)

    result = asyncio.run(run(args.query, args.retmax, args.concurrency))
    path = config.REPO_ROOT / args.out
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1), encoding="utf-8")

    claims = result["claims"]
    grounded = [c for c in claims if c["grounded_both_ends"]]
    signed = [c for c in grounded if c["signed_direction"] is not None]
    print(f"\n[extract] {result['papers_extracted']} papers extracted "
          f"({result['papers_failed']} failed) in {result['seconds']}s")
    print(f"[extract] claims                 {len(claims)}")
    print(f"[extract]   grounded both ends   {len(grounded)}")
    print(f"[extract]   signed + grounded    {len(signed)}")
    print(f"[extract]   with a stimulus      {sum(1 for c in claims if c.get('stimulus'))}")
    print(f"[extract]   restatements flagged {sum(1 for c in claims if c['is_restatement'])}")
    print(f"[extract]   species stated       {sum(1 for c in claims if c.get('species'))}")
    print(f"[extract]   dose stated          {sum(1 for c in claims if c.get('dose'))}")
    print(f"[extract] -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
