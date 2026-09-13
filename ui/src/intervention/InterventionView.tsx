import { useEffect, useMemo, useState } from "react";
import Graph3D from "../graph3d/Graph3D";
import { interventionApi, type Capabilities, type SimulationResponse } from "./api";
import "../graph3d/cinematic.css";
import "./intervention.css";

export default function InterventionView({ onExit }: { onExit: () => void }) {
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [query, setQuery] = useState("What happens to SQSTM1 if I decrease TBK1?");
  const [demo, setDemo] = useState(false);
  const [boolean, setBoolean] = useState(false);
  const [modelId, setModelId] = useState("");
  const [exclude, setExclude] = useState("");
  const [result, setResult] = useState<SimulationResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  useEffect(() => {
    interventionApi.capabilities().then(setCapabilities).catch((e: Error) => setError(e.message));
  }, []);
  const graph = useMemo(() => ({ nodes: result?.nodes ?? [], links: result?.links ?? [] }), [result]);
  const evidence = result?.evidence.filter((e) => e.claim_id === selected) ?? [];
  const readout = result?.analysis?.after_exclusion ?? result?.analysis?.baseline;
  const node = result?.nodes.find((n) => n.id === selectedNode);
  const protocol = result?.synthesis?.validation_protocol;

  async function run() {
    setBusy(true); setError(null); setResult(null); setSelected(null); setSelectedNode(null);
    try {
      const next = await interventionApi.simulate({ query, demo,
        method: boolean ? "illustrative_boolean" : "signed_path_hypothesis",
        context_id: demo ? "demo_context" : capabilities?.context_id ?? null,
        boolean_model_id: boolean ? (demo ? "synthetic_boolean_v1" : modelId || null) : null,
        exclude_publication_ids: exclude.trim() ? [exclude.trim()] : [],
      });
      setResult(next);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  function download() {
    if (!result) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }));
    const anchor = document.createElement("a");
    anchor.href = url; anchor.download = `intervention-${result.request_id}.json`; anchor.click();
    URL.revokeObjectURL(url);
  }

  return <main className="intervention">
    <header className="iv-header">
      <div><small>nucleolus / mechanism research</small><h1>Explore an intervention</h1></div>
      <button onClick={onExit}>Evidence browser</button>
    </header>
    <p>Trace an assumed perturbation through reviewed evidence, inspect competing directions, and draft a discriminating experiment.</p>
    <form className="iv-form" onSubmit={(e) => { e.preventDefault(); void run(); }}>
      <label htmlFor="intervention-query">Research question</label>
      <textarea id="intervention-query" maxLength={2000} value={query} onChange={(e) => setQuery(e.target.value)} required />
      <div className="iv-options">
        <label><input type="checkbox" checked={boolean} onChange={(e) => setBoolean(e.target.checked)} /> Illustrative Boolean rules</label>
        {capabilities?.synthetic_demo_enabled && <label><input type="checkbox" checked={demo} onChange={(e) => {
          setDemo(e.target.checked); setResult(null); setExclude("");
          if (e.target.checked) setQuery(capabilities.demo_query);
          else setQuery("What happens to SQSTM1 if I decrease TBK1?");
        }} /> Synthetic software demo</label>}
        {boolean && !demo && <input aria-label="Reviewed Boolean model ID" placeholder="Reviewed model ID" value={modelId} onChange={(e) => setModelId(e.target.value)} />}
        {!boolean && <input aria-label="Publication to exclude" placeholder="Optional exclusion: PMID:…" value={exclude} onChange={(e) => setExclude(e.target.value)} />}
        <button type="submit" disabled={busy}>{busy ? "Analyzing…" : "Explore"}</button>
      </div>
    </form>
    {!demo && capabilities && <p className="iv-status">
      {capabilities.review_manifest_version ? `Review: ${capabilities.review_manifest_version}` : "No reviewed mechanism is configured. Real evidence results will remain insufficient until review is supplied."}
      {!capabilities.parser_configured && " Live question parsing is not configured."}
      {!capabilities.synthesis_configured && " Generated research drafts are not configured."}
      {capabilities.review_issue && ` ${capabilities.review_issue}`}
    </p>}
    {error && <p role="alert" className="iv-error">{error}</p>}
    {result && <>
      <div className="iv-result-heading"><div><strong>{result.synthetic ? "SYNTHETIC SOFTWARE DEMO" : result.snapshot.id}</strong>
        <p>{result.method === "illustrative_boolean" ? "Illustrative Boolean model · logical update steps" : "Signed-path directional inference"} · {result.status.replaceAll("_", " ")}</p></div>
        <button onClick={download}>Download JSON</button></div>
      {result.warnings.map((w) => <p className="iv-status" key={w}>{w}</p>)}
      {result.errors.map((e) => <p role="status" className="iv-error" key={e.code}>{e.message}</p>)}
      {readout && <p>{readout.category.replaceAll("_", " ")} · {readout.total_paths} readout paths · {readout.completion.replaceAll("_", " ")}
        {result.truncation.display_paths_omitted > 0 && ` · ${result.truncation.display_paths_omitted} paths omitted from the displayed list`}</p>}
      {result.analysis?.boolean && <p>Baseline: {result.analysis.boolean.baseline.completion} · Intervention: {result.analysis.boolean.perturbed.completion} · {result.analysis.boolean.flips.length} fixed-point state flips</p>}
      {graph.nodes.length > 0 && <div className="iv-grid">
        <section className="iv-graph"><Graph3D data={graph} selectedLinkId={selected} onSelectLink={setSelected} onSelectNode={setSelectedNode} />
          <p className="iv-legend">Green: increased/on · Red: decreased/off · Amber: conflicting · Blue: unchanged · Gray: unknown/unmodeled. Edge width: papers.</p></section>
        <aside className="iv-evidence"><h2>Inspect the evidence</h2>
          {node && <p><strong>{node.name}</strong>: {node.state}{node.baseline_state != null && ` (${node.baseline_state} → ${node.perturbed_state})`}</p>}
          {!selected && <p>Select an edge for its source passages or a node for its inferred state.</p>}
          {evidence.map((e) => <article key={e.id}><blockquote>{e.quote}</blockquote>
            {e.publication_url ? <a href={e.publication_url} target="_blank" rel="noreferrer">{e.publication_id}</a> : <span>{e.publication_id ?? "No publication identifier"}</span>}
            <p><small>{e.context_id} · {e.id}</small></p></article>)}
          {readout?.paths.map((p) => <button className="iv-path" key={p.id} onClick={() => setSelected(p.claim_ids[0] ?? null)}>
            {p.node_ids.map((id) => result.nodes.find((n) => n.id === id)?.name ?? id).join(" → ")} · {p.implied_direction > 0 ? "increase" : "decrease"}
          </button>)}
        </aside>
      </div>}
      {result.evidence_assessment && <p className="iv-status">Where this comes from: {result.evidence_assessment.curated_database_claims} of {result.links.length} claims have curated-database support · {result.evidence_assessment.machine_read_claims} are machine-read text only · {result.evidence_assessment.multi_source_claims} have more than one source.
        {" "}<small>INDRA belief (weakest {result.evidence_assessment.weakest_belief ?? "unavailable"}, coverage {result.evidence_assessment.belief_coverage == null ? "unavailable" : `${Math.round(result.evidence_assessment.belief_coverage * 100)}%`}) scores statement assembly, not correctness: it tracks which reader extracted the sentence, and on this corpus it does not separate extraction faults from genuine disagreement. Read the quote.</small></p>}
      {result.amass_corroboration.status !== "not_requested" && <section className="iv-status">
        <p><strong>Corroboration · {result.amass_corroboration.mode.replaceAll("_", " ")}</strong>: {result.amass_corroboration.status} · {result.amass_corroboration.claims_assessed} claims assessed · {result.amass_corroboration.calls_used} calls · policy {result.amass_corroboration.review_policy.replaceAll("_", " ")}
          {result.amass_corroboration.from_cache && ` · from cache${result.amass_corroboration.retrieved_at ? ` (${result.amass_corroboration.retrieved_at})` : ""}`}
          {result.amass_corroboration.truncated && " · search truncated"}</p>
        {result.amass_corroboration.corroborations.map((c) => <article key={c.claim_id}>
          <p><button onClick={() => setSelected(c.claim_id)}>{c.claim_id}</button> {c.status.replaceAll("_", " ")} · {c.distinct_publication_families} distinct publication families · {c.distinct_primary_study_count} qualifying primary studies · {c.source_pipeline_classes.map((s) => s.replaceAll("_", " ")).join(" + ") || "no pipeline recorded"}</p>
          {c.cross_indexed_publication_ids.length > 0 && <p><small>Cross-indexed, already cited by INDRA — not corroboration: {c.cross_indexed_publication_ids.join(", ")}</small></p>}
          {c.passages.map((p) => <blockquote key={p.id}>{p.quote}
            <footer><small>{p.publication_id} · {p.stance.replaceAll("_", " ")} · context {p.context_match} · {p.evidence_role.replaceAll("_", " ")} · {p.review_status}</small></footer></blockquote>)}
          {c.documents.filter((d) => d.is_retracted === true).map((d) => <p key={d.amass_id} role="status"><small>Retracted: {d.title ?? d.amass_id} — shown, never counted as corroboration</small></p>)}
          {c.limitations.map((l) => <p key={l}><small>{l}</small></p>)}
        </article>)}
        {result.amass_corroboration.warnings.map((w) => <p key={w}><small>{w}</small></p>)}
      </section>}
      {result.synthesis && <section className="iv-synthesis"><h2>{result.synthetic ? "Fixture draft" : "Generated research draft · requires review"}</h2>
        {result.synthesis.biological_rationale.map((r, i) => <p key={i}>{r.text} <small>({r.basis.replaceAll("_", " ")})</small>
          {r.claim_ids.map((id) => <button key={id} onClick={() => setSelected(id)}>Inspect {id}</button>)}</p>)}
        <p>{result.synthesis.confidence_assessment}</p>
        {[...result.synthesis.assumptions, ...result.synthesis.limitations].map((text, i) => <p key={i}>{text}</p>)}
        {protocol && <article><h3>Proposed in vitro validation · requires review</h3><p>{protocol.hypothesis}</p><p>{protocol.experimental_system}</p><p>{protocol.perturbation}</p>
          {([ ["Competing explanations", protocol.competing_explanations], ["Controls", protocol.controls], ["Readouts", protocol.readouts],
            ["Procedure outline", protocol.procedure_outline], ["Discriminating observations", protocol.discriminating_observations],
            ["Confounders", protocol.confounders], ["Parameters to optimize", protocol.parameters_to_optimize] ] as [string, string[]][]).map(([title, items]) =>
            <div key={title}><h4>{title}</h4><ul>{items.map((item, i) => <li key={i}>{item}</li>)}</ul></div>)}</article>}
      </section>}
    </>}
  </main>;
}
