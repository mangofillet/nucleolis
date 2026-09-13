import { useCallback, useEffect, useRef, useState } from "react";
import { api, type EvidenceResponse } from "../api";
import { interventionApi, type SimulationResponse } from "../intervention/api";
import { researchApi, type ResearchCapabilities, type ResearchLink, type ResearchResult, type Species } from "./api";
import MechanismCanvas from "./MechanismCanvas";
import { Icon, Logo } from "./Icon";
import "./research.css";

type Section = "model" | "evidence" | "experiments";
type DetailTab = "overview" | "evidence" | "context" | "related";
const EXAMPLES = [
  { label: "Explore a mechanism", query: "What does GFAP activate?", icon: "model" },
  { label: "Test an intervention", query: "What happens to SQSTM1 if I decrease TBK1?", icon: "bolt" },
  { label: "Find target hypotheses", query: "Which targets could reduce TARDBP?", icon: "target" },
];
const readable = (value: string) => value.replaceAll("_", " ");
const sourceLabel = (value: string) => ({ machine_read: "Machine-read literature", curated_database: "Curated database", mixed: "Curated + machine-read", unknown: "Source not classified" })[value] ?? readable(value);

function download(value: string, type: string, filename: string) {
  const url = URL.createObjectURL(new Blob([value], { type }));
  const a = document.createElement("a"); a.href = url; a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function ResearchWorkspace() {
  const [query, setQuery] = useState("What happens to GFAP if I decrease TREM2?");
  const [species, setSpecies] = useState<Species>("all");
  const [capabilities, setCapabilities] = useState<ResearchCapabilities | null>(null);
  const [result, setResult] = useState<ResearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [selectedLink, setSelectedLink] = useState<string | null>(null);
  const [activePath, setActivePath] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>("overview");
  const [section, setSection] = useState<Section>("model");
  const [evidence, setEvidence] = useState<EvidenceResponse | null>(null);
  const [evidenceBusy, setEvidenceBusy] = useState(false);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [evidenceOffset, setEvidenceOffset] = useState(0);
  const [zoom, setZoom] = useState(100);
  const [help, setHelp] = useState(false);
  const [perturbation, setPerturbation] = useState("none");
  const [draft, setDraft] = useState<SimulationResponse | null>(null);
  const [draftBusy, setDraftBusy] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const sequence = useRef(0);
  const input = useRef<HTMLInputElement>(null);

  const run = useCallback(async (text: string, scope: Species) => {
    abort.current?.abort();
    const controller = new AbortController(); abort.current = controller;
    sequence.current += 1;
    setQuery(text); setBusy(true); setError(null); setResult(null); setEvidence(null);
    setSelectedNode(null); setSelectedLink(null); setActivePath(null); setDraft(null); setDraftError(null); setDraftBusy(false); setZoom(100);
    try {
      const next = await researchApi.ask(text, scope, controller.signal);
      if (controller.signal.aborted) return;
      setResult(next); setPerturbation(next.plan.perturbation); setSelectedNode(next.nodes.find(n => n.focus)?.id ?? null); setDetailTab("overview");
    } catch (e) {
      if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e));
    } finally { if (!controller.signal.aborted) setBusy(false); }
  }, []);

  useEffect(() => {
    let mounted = true;
    researchApi.capabilities().then(c => { if (mounted) setCapabilities(c); }).catch(() => {});
    void run("What happens to GFAP if I decrease TREM2?", "all");
    return () => { mounted = false; abort.current?.abort(); sequence.current += 1; };
  }, [run]);

  useEffect(() => {
    if (!selectedLink) { setEvidence(null); setEvidenceBusy(false); setEvidenceError(null); return; }
    let current = true;
    setEvidence(null); setEvidenceBusy(true); setEvidenceError(null);
    api.evidence(selectedLink, evidenceOffset).then(data => {
      if (data.snapshot_id !== result?.snapshot.id) throw new Error("The evidence snapshot changed. Run the question again before inspecting its passages.");
      if (current) setEvidence(data);
    })
      .catch(e => { if (current) setEvidenceError(String(e.message)); })
      .finally(() => { if (current) setEvidenceBusy(false); });
    return () => { current = false; };
  }, [selectedLink, evidenceOffset, result?.snapshot.id]);

  const citedNode = draft?.nodes.find(n => n.id === selectedNode);
  const node = result?.nodes.find(n => n.id === selectedNode) ?? (citedNode ? {
    id: citedNode.id, name: citedNode.name, kind: citedNode.kind ?? "entity", state: "unknown",
    description: typeof citedNode.meta?.description === "string" ? citedNode.meta.description : null,
  } : undefined);
  const citedLink = draft?.links.find(e => e.id === selectedLink);
  const citedEvidence = draft?.evidence.filter(e => e.claim_id === selectedLink) ?? [];
  const link: ResearchLink | undefined = result?.links.find(e => e.id === selectedLink) ?? (citedLink && citedLink.sign !== null ? {
    ...citedLink, sign: citedLink.sign, belief: citedLink.belief_score,
    review_status: citedEvidence.every(e => e.review_status === "approved") ? "reviewed" : citedEvidence.some(e => e.review_status === "approved") ? "mixed" : "unreviewed",
  } : undefined);
  const connected = result?.links.filter(e => e.source === selectedNode || e.target === selectedNode) ?? [];
  const selectedPath = result?.paths.find(p => p.id === activePath) ?? result?.paths[0];
  const name = (id: string | null | undefined) => result?.nodes.find(n => n.id === id)?.name ?? draft?.nodes.find(n => n.id === id)?.name ?? id ?? "entity";
  const draftSource = selectedPath?.node_ids[0];
  const draftTarget = selectedPath?.node_ids[selectedPath.node_ids.length - 1];
  const draftPerturbation = selectedPath?.intervention && selectedPath.intervention !== "none" ? selectedPath.intervention : perturbation === "none" ? "decrease" : perturbation;
  const draftQuestion = `What happens to ${name(draftTarget)} if I ${draftPerturbation === "knockout" ? "knock out" : draftPerturbation} ${name(draftSource)}?`;
  const supporting = result?.paths.filter(p => p.direction === 1).length ?? 0;
  const opposing = result?.paths.filter(p => p.direction === -1).length ?? 0;
  const shownEvidence = evidence?.evidence.filter(e => link ? link.evidence_ids.includes(e.evidence_id) : draft?.evidence.some(d => d.id === e.evidence_id && d.claim_id === selectedLink)) ?? [];
  const quoteOmitted = link ? Math.max(0, link.evidence_ids.length - shownEvidence.length) : 0;

  function openLink(id: string) { setEvidenceOffset(0); setSelectedLink(id); setSelectedNode(null); setDetailTab("evidence"); }
  function openNode(id: string) { setSelectedNode(id); setSelectedLink(null); setDetailTab("overview"); }
  function example(text: string) { setSection("model"); void run(text, species); }
  async function generateDraft() {
    if (!draftSource || !draftTarget) return;
    const requestSequence = sequence.current;
    setDraftBusy(true); setDraftError(null); setDraft(null);
    try {
      const next = await interventionApi.simulate({ query: draftQuestion, demo: false, method: "signed_path_hypothesis", context_id: null, boolean_model_id: null, exclude_publication_ids: [], snapshot_id: result?.snapshot.id });
      if (sequence.current !== requestSequence) return;
      if (next.snapshot.id !== result?.snapshot.id || next.snapshot.checksum !== result?.snapshot.checksum) throw new Error("The evidence snapshot changed. Run the question again before generating a draft.");
      setDraft(next);
      if (!next.synthesis) setDraftError([...next.warnings, ...next.errors.map(e => e.message)].join(" ") || "A cited draft could not be generated; the exploratory result remains available.");
    } catch (e) { if (sequence.current === requestSequence) setDraftError(e instanceof Error ? e.message : String(e)); }
    finally { if (sequence.current === requestSequence) setDraftBusy(false); }
  }

  const evidenceContent = <>
    {evidenceBusy && <p className="rw-subtle" role="status">Loading source passages…</p>}
    {evidenceError && <p className="rw-error" role="alert">{evidenceError}</p>}
    {!selectedLink && <p className="rw-subtle">Choose a signed connection to read its source passages.</p>}
    {link && <div className="rw-tags"><span>{sourceLabel(link.source_class)}</span><span>{readable(link.review_status)}</span><span>{link.publication_ids.length} publications</span></div>}
    {shownEvidence.map(item => <article className="rw-quote" key={item.evidence_id}>
      <blockquote>{item.quote}</blockquote>
      <div className="rw-quote-footer">{item.link ? <a href={item.link} target="_blank" rel="noreferrer">{item.document?.id} ↗</a> : <span>Reference unavailable</span>}<span>{item.document?.publication_date ?? "Date not recorded"}</span></div>
      <div className="rw-tags"><span>{item.source_evidence_code ?? "Source unknown"}</span><span>{item.document?.is_primary === false ? "Secondary literature" : item.document?.is_primary === true ? "Primary publication" : "Study type unknown"}</span></div>
    </article>)}
    {selectedLink && !evidenceBusy && !shownEvidence.length && <p>No eligible passages on this evidence page. Follow the publication IDs in the export.</p>}
    {quoteOmitted > 0 && <p className="rw-subtle">{quoteOmitted} eligible passages are outside this page. All eligible IDs remain in the result export.</p>}
    {evidence && evidence.total > evidence.limit && <div className="rw-tags"><button disabled={evidenceBusy || evidence.offset === 0} onClick={() => setEvidenceOffset(Math.max(0, evidence.offset - evidence.limit))}>Previous passages</button><span>Passages {evidence.offset + 1}–{Math.min(evidence.total, evidence.offset + evidence.limit)} of {evidence.total}</span><button disabled={evidenceBusy || evidence.offset + evidence.limit >= evidence.total} onClick={() => setEvidenceOffset(evidence.offset + evidence.limit)}>Next passages</button></div>}
  </>;

  return <div className="rw-app">
    <aside className="rw-sidebar">
      <a href="#" className="rw-brand" aria-label="Nucleolus research workspace"><Logo /><span><strong>Nucleolus</strong><small>Mechanistic reasoning<br />for biomedical R&amp;D</small></span></a>
      <nav aria-label="Workspace navigation">
        <button className="rw-nav-item" onClick={() => { input.current?.focus(); input.current?.select(); }}><Icon name="search" />Research questions</button>
        <button className={`rw-nav-item ${section === "model" ? "active" : ""}`} onClick={() => setSection("model")}><Icon name="model" />Mechanistic model</button>
        <button className={`rw-nav-item ${section === "evidence" ? "active" : ""}`} onClick={() => setSection("evidence")}><Icon name="book" />Evidence library</button>
        <button className={`rw-nav-item ${section === "experiments" ? "active" : ""}`} onClick={() => setSection("experiments")}><Icon name="flask" />Experiment ideas</button>
      </nav>
      <div className="rw-sidebar-group"><h3>Start a research question</h3>
        {EXAMPLES.map(e => <button className="rw-nav-item" key={e.label} onClick={() => example(e.query)}><Icon name={e.icon} />{e.label}</button>)}
      </div>
      <div className="rw-sidebar-group"><h3>Available targets</h3><span className="rw-sidebar-caption">ALS / FTD &amp; related biology</span>
        <div className="rw-target-list">{["TREM2", "TBK1", "TARDBP", "GFAP", "SOD1", "SQSTM1"].filter(n => !capabilities || capabilities.entities.some(e => e.name === n)).map(n => <button key={n} onClick={() => example(`Show mechanism of ${n}`)} className={result?.plan.source === n ? "active" : ""}><span className="rw-target-dot" />{n}<span>↗</span></button>)}</div>
      </div>
      <div className="rw-sidebar-bottom"><button className="rw-nav-item" onClick={() => setHelp(!help)}><Icon name="info" />Scope &amp; help</button><a className="rw-nav-item" href="#explorer"><Icon name="settings" />Advanced evidence browser</a></div>
    </aside>

    <header className="rw-topbar">
      <form className="rw-search" onSubmit={e => { e.preventDefault(); setSection("model"); void run(query, species); }}>
        <Icon name="search" /><input ref={input} value={query} onChange={e => setQuery(e.target.value)} aria-label="Research question" placeholder="Ask a hypothesis question about a gene, target or mechanism…" maxLength={2000} required />
        <button disabled={busy} type="submit">{busy ? "Exploring…" : "Explore"}<Icon name="arrow" size={16} /></button>
      </form>
      <div className="rw-context"><small>Evidence scope</small><div><select aria-label="Evidence species" value={species} onChange={e => { const scope = e.target.value as Species; setSpecies(scope); void run(result?.query ?? query, scope); }}><option value="all">All species / unknown</option><option value="human">Human evidence</option><option value="mouse">Mouse evidence</option><option value="rat">Rat evidence</option></select>{result?.source_id && <span className="rw-context-chip">{name(result.source_id)}</span>}</div></div>
      <span className="rw-avatar" title="Local research workspace">NL</span>
    </header>

    <main className="rw-main">
      <div className="rw-page-heading"><div><div className="rw-eyebrow">RESEARCH WORKSPACE <span> / </span> {section === "model" ? "MECHANISMS" : section.toUpperCase()}</div><h1>{section === "model" ? "Mechanistic model" : section === "evidence" ? "Evidence library" : "Design the next experiment"}</h1><p>{result?.interpretation || "Explore a question. Trace the mechanism. Inspect the evidence."}</p></div>
        <div className="rw-tools">{section === "model" && <><label className="rw-perturbation"><Icon name="bolt" /><span><small>Perturbation</small><select aria-label="Perturbation" value={perturbation} onChange={e => { setPerturbation(e.target.value); if (result?.source_id) example(e.target.value === "none" ? `Show mechanism of ${name(result.source_id)}` : `What happens${result.target_id ? ` to ${name(result.target_id)}` : ""} if I ${e.target.value === "knockout" ? "knock out" : e.target.value} ${name(result.source_id)}?`); }} disabled={!result?.source_id}><option value="none">No perturbation</option><option value="decrease">Decrease target</option><option value="increase">Increase target</option><option value="knockout">Knock out target</option></select></span></label><button title="Fit diagram to view" onClick={() => setZoom(100)}><Icon name="fit" />Fit view</button></>}
          <button disabled={!result} onClick={() => result && download(JSON.stringify(result, null, 2), "application/json", "nucleolus-research.json")}><Icon name="download" />Export</button>
        </div>
      </div>

      {help && <section className="rw-help"><button aria-label="Close help" onClick={() => setHelp(false)}><Icon name="close" /></button><h2>From a question to a testable hypothesis</h2><p>Ask what a target regulates, test a source → readout direction, explore a perturbation, or find upstream targets for a desired change. Common questions run locally; broader wording uses the configured language parser.</p><p>This snapshot contains {capabilities?.entity_count ?? "…"} entities and {capabilities?.compound_count ?? 0} compounds. Current diagrams are exploratory literature hypotheses. Biological compartment assignments and drug design require additional sourced models and compound evidence.</p><p>Model lanes describe graph distance. Species filters require matching passage metadata and exclude unknown species. Source quotes remain available without LLM credentials.</p></section>}
      <div className="rw-examples">{EXAMPLES.map(e => <button key={e.label} onClick={() => example(e.query)}><Icon name={e.icon} size={14} />{e.query}</button>)}</div>
      {busy && <div className="rw-loading" role="status"><span className="rw-spinner" /><h2>Tracing the evidence…</h2><p>Interpreting your question and collecting signed mechanisms.</p></div>}
      {error && <section className="rw-empty" role="alert"><Icon name="info" size={30} /><h2>Research service unavailable</h2><p>{error}</p><button onClick={() => void run(query, species)}>Retry question</button><p>Start the updated backend to enable /api/research.</p></section>}
      {result && !result.paths.length && <section className="rw-empty" role="status"><Icon name="search" size={34} /><h2>{result.status === "needs_clarification" ? "Let’s make this question executable" : "Evidence gap found"}</h2><p>{result.answer}</p><div className="rw-tags">{capabilities?.entities.slice(0, 12).map(e => <button key={e.id} onClick={() => example(`Show mechanism of ${e.name}`)}>{e.name}</button>)}</div><p>A missing answer clears the previous graph. No nearby target is substituted.</p></section>}

      {result && result.paths.length > 0 && <>
        {section === "model" && <section className="rw-graph-card"><div className="rw-graph-meta"><span><i />Exploratory literature model</span><span>{result.nodes.length} nodes · {result.links.length} relationships</span></div><div className="rw-graph-scroll"><MechanismCanvas result={result} selectedNode={selectedNode} selectedLink={selectedLink} activePath={activePath} onNode={openNode} onLink={openLink} zoom={zoom} /></div><div className="rw-legend"><strong>Edge legend:</strong><span><i className="positive" />Activates / increases</span><span><i className="negative" />Inhibits / decreases</span><button onClick={() => setZoom(Math.min(160, zoom + 20))} aria-label="Zoom in"><Icon name="plus" size={15} /></button><button onClick={() => { const svg = document.querySelector<SVGSVGElement>(".rw-canvas"); if (svg) download(new XMLSerializer().serializeToString(svg), "image/svg+xml", "nucleolus-mechanism.svg"); }}>Save SVG ↗</button></div><p className="rw-layout-note">Layers show graph roles and distance. Biological compartments are not annotated in this snapshot.</p></section>}

        <section className="rw-answer" aria-label="Research answer"><div className="rw-answer-icon"><Icon name="model" /></div><div><h2>{result.plan.operation === "target_discovery" ? "Target hypotheses to investigate" : "What the evidence graph suggests"}</h2><p>{result.answer}</p><span className="rw-subtle">{result.parser === "local_grammar" ? "Local question interpretation" : "Nebius question interpretation"} · Evidence: {result.species === "all" ? "all species, including unstated" : result.species} · {result.paths_omitted} routes omitted{result.search_truncated ? " · Search limit reached" : ""}</span></div></section>

        {section === "evidence" ? <section className="rw-library"><div className="rw-library-list"><h2>Relationships in this result</h2>{result.links.map(e => <button key={e.id} className={e.id === selectedLink ? "active" : ""} onClick={() => openLink(e.id)}><strong>{name(e.source)} → {name(e.target)}</strong><span>{readable(e.predicate)} · {e.publication_ids.length} publications</span></button>)}</div><div><h2>{link ? `${name(link.source)} → ${name(link.target)}` : "Read the source"}</h2>{evidenceContent}</div></section> : <section className="rw-path-section"><div className="rw-section-title"><h2>{section === "experiments" ? "Choose a mechanism to test" : "Trace a hypothesis"}</h2><span>{result.paths.length} routes in view</span>{activePath && <button onClick={() => setActivePath(null)}>Show all</button>}</div><div className="rw-path-grid">{result.paths.map(p => <button key={p.id} className={`rw-path-card ${p.id === activePath ? "active" : ""}`} onClick={() => { sequence.current += 1; setDraft(null); setDraftError(null); setDraftBusy(false); setActivePath(p.id); openNode(p.node_ids[0]); }}><span className="rw-path-chain">{p.node_ids.map(name).join(" → ")}</span><span className={`rw-direction ${p.direction === 1 ? "positive" : "negative"}`}>{p.intervention !== "none" ? `${p.intervention} ${name(p.node_ids[0])}` : p.direction === 1 ? "Positive signed route" : "Negative signed route"}</span><small>{p.claim_ids.length} step{p.claim_ids.length > 1 ? "s" : ""} · {p.assessment === "directional_hypothesis" ? "Conditional hypothesis" : readable(p.assessment)}</small></button>)}</div></section>}

        {section === "experiments" && <section className="rw-experiment"><div className="rw-section-title"><h2>Research brief</h2><span className="rw-tags"><span>Proposal · requires review</span></span></div><p className="rw-brief-question">{draftQuestion}</p><label>Proposed perturbation <select aria-label="Experiment perturbation" value={draftPerturbation} onChange={e => { sequence.current += 1; setDraft(null); setDraftError(null); setDraftBusy(false); setPerturbation(e.target.value); }} disabled={selectedPath?.intervention !== "none"}><option value="decrease">Decrease</option><option value="increase">Increase</option><option value="knockout">Knock out</option></select></label><div className="rw-brief-grid"><div><h3>Mechanistic assumptions</h3>{selectedPath?.assumptions.map(a => <p key={a}>{a}</p>)}</div><div><h3>Questions the experiment should resolve</h3><p>Does changing {name(draftSource)} alter the specified activity or abundance of {name(draftTarget)} in the chosen experimental system?</p><p>Specify the cell type, assay and matched control. Use an independent readout and a rescue/comparator condition to distinguish the candidate explanation.</p><p>Compound selection, concentrations, timing and biological context remain to be established.</p></div></div><button className="rw-primary" disabled={draftBusy || !capabilities?.research_draft_configured || result.species !== "all"} onClick={() => void generateDraft()}><Icon name="flask" />{draftBusy ? "Drafting with Claude…" : "Generate cited research draft"}</button>{!capabilities?.research_draft_configured && <p className="rw-subtle">The optional cited draft requires configured Nebius and Anthropic credentials.</p>}{result.species !== "all" && <p className="rw-subtle">A reviewed context mapping is required before the separate draft pipeline can use this species filter.</p>}{draftError && <p className="rw-error" role="status">{draftError}</p>}{draft?.synthesis && <div className="rw-generated"><h3>Generated research draft</h3><p className="rw-subtle">{draft.synthesis_status} · {draft.snapshot.id} · {draft.method}</p>{draft.synthesis.biological_rationale.map((r, i) => <article key={i}><p>{r.text}</p><div className="rw-tags">{r.claim_ids.map(cid => <button key={cid} onClick={() => { setSection("evidence"); openLink(cid); }}>Inspect cited claim</button>)}</div></article>)}{draft.synthesis.validation_protocol && <><h3>Proposed validation</h3><p>{draft.synthesis.validation_protocol.hypothesis}</p>{(["experimental_system", "perturbation", "controls", "readouts", "procedure_outline", "confounders", "parameters_to_optimize"] as const).map(key => <div key={key}><h4>{readable(key)}</h4>{Array.isArray(draft.synthesis!.validation_protocol![key]) ? <ul>{(draft.synthesis!.validation_protocol![key] as string[]).map((v, i) => <li key={i}>{v}</li>)}</ul> : <p>{draft.synthesis!.validation_protocol![key]}</p>}</div>)}</>}<details><summary>Draft assumptions and limitations</summary>{[...draft.warnings, ...draft.synthesis.limitations, ...draft.synthesis.assumptions].map((s, i) => <p key={i}>{s}</p>)}</details><button onClick={() => download(JSON.stringify(draft, null, 2), "application/json", "nucleolus-research-draft.json")}>Export draft and citations</button></div>}</section>}

        <details className="rw-limitations"><summary><Icon name="info" size={16} />Model scope, assumptions &amp; provenance</summary>{result.limitations.map(l => <p key={l}>{l}</p>)}<p>Snapshot {result.snapshot.id} · {result.snapshot.checksum ?? "Checksum unavailable"}</p></details>
      </>}
      <footer className="rw-footer"><span className="rw-status-dot" />{capabilities ? `${capabilities.snapshot_id} · ${capabilities.claim_count} claims · ${capabilities.publication_count.toLocaleString()} publications` : "Connecting to evidence snapshot"}<span>Every connection opens its source evidence.</span></footer>
    </main>

    <aside className="rw-details" aria-label="Node and evidence details"><div className="rw-detail-heading"><h2>{link ? "Relationship details" : "Node details"}</h2>{(node || link) && <button aria-label="Clear selection" onClick={() => { setSelectedNode(null); setSelectedLink(null); }}><Icon name="close" size={17} /></button>}</div>
      {node || link ? <><div className="rw-node-heading"><div className={`rw-node-symbol ${node?.state ?? ""}`}>{node?.name ?? <Icon name="model" size={28} />}</div><div><h3>{node?.name ?? `${name(link?.source)} → ${name(link?.target)}`}</h3><p>{node ? readable(node.kind) : readable(link!.predicate)}</p><div className="rw-tags"><span>{node ? "Literature model" : sourceLabel(link!.source_class)}</span></div></div></div>
        <div className="rw-detail-tabs" role="tablist" aria-label="Selection details">{(["overview", "evidence", "context", "related"] as const).map(tab => <button role="tab" aria-selected={detailTab === tab} key={tab} onClick={() => setDetailTab(tab)}>{tab[0].toUpperCase() + tab.slice(1)}</button>)}</div>
        <div className="rw-detail-content" role="tabpanel">
          {detailTab === "overview" && <><h4>Description</h4><p>{node?.description ?? (link ? `${name(link.source)} ${readable(link.predicate)} ${name(link.target)} is a retrieved literature claim. Inspect its passages to assess the extraction.` : "No source description available.")}</p>{node && <><h4>Mechanistic relationships</h4>{connected.slice(0, 6).map(e => <button className="rw-related" key={e.id} onClick={() => openLink(e.id)}>{name(e.source)} <span>{readable(e.predicate)}</span> {name(e.target)} <span>↗</span></button>)}</>}<h4>Evidence profile</h4><div className="rw-evidence-profile"><Icon name="book" size={25} /><div><strong>Source-linked evidence</strong><p>{node ? `${connected.length} displayed relationships` : `${link?.publication_ids.length} distinct publications`}. Open the passages to assess the claim.</p></div></div>{supporting > 0 && opposing > 0 && <div className="rw-evidence-profile warning"><Icon name="info" size={25} /><div><strong>Both signs occur in this result</strong><p>Check endpoints, context and extraction before interpreting disagreement.</p></div></div>}<h4>Next research question</h4><button className="rw-next" onClick={() => example(`What happens if I decrease ${node?.name ?? name(link?.source)}?`)}>Explore a decrease <Icon name="arrow" size={16} /></button><button className="rw-next" onClick={() => { setSection("experiments"); }}>Develop an experiment idea <Icon name="arrow" size={16} /></button></>}
          {detailTab === "evidence" && <>{node && connected.map(e => <button className="rw-related" key={e.id} onClick={() => openLink(e.id)}>{name(e.source)} → {name(e.target)}<span>{e.publication_ids.length} publications</span></button>)}{evidenceContent}{link && <details className="rw-provenance"><summary>Assembly provenance</summary><p>INDRA assembly score: {link.belief ?? "unavailable"}. Reflects automated statement assembly and source-specific extraction assumptions; it does not estimate whether the biological claim is correct.</p><p>{link.id}</p></details>}</>}
          {detailTab === "context" && <><h4>Applied evidence scope</h4><p>{result?.species === "all" ? "All species, including unknown species." : `Only passages marked ${result?.species}.`}</p><h4>Biological context</h4><p>Cell type, disease and subcellular compartment are not reliably annotated in this snapshot. The lane position does not assign a biological location.</p><h4>Review status</h4><p>{link ? readable(link.review_status) : "Review status is shown for each relationship."} Exploratory paths require source and context review before experimental interpretation.</p></>}
          {detailTab === "related" && <>{(node ? [...new Set(connected.flatMap(e => [e.source, e.target]))].filter(id => id !== node.id) : [link!.source, link!.target]).map(id => <button className="rw-related" key={id} onClick={() => openNode(id)}>{name(id)}<Icon name="arrow" size={14} /></button>)}</>}
        </div></> : <div className="rw-selection-empty"><Icon name="target" size={34} /><h3>Inspect the mechanism</h3><p>Select a node for its role in the model, or a connection for the exact evidence behind it.</p></div>}
    </aside>
  </div>;
}
