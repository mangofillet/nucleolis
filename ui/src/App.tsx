import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  api,
  type ClaimView,
  type EvidenceResponse,
  type GraphResponse,
  type Health,
  type PathResponse,
  type SearchResult,
} from "./api";
import CinematicView from "./graph3d/CinematicView";
import PathwayView from "./pathway/PathwayView";
import InterventionView from "./intervention/InterventionView";
import "./App.css";

const SIGN_COLOR: Record<string, string> = {
  "1": "#1a7f4b",
  "-1": "#b3261e",
  null: "#8a8f98",
};

const PREDICATE_GLYPH: Record<string, string> = {
  activates: "→",
  inhibits: "⊣",
  increases_amount: "↑",
  decreases_amount: "↓",
  phosphorylates: "-P",
  dephosphorylates: "-P⁻",
  binds: "—",
  associated_with: "~",
};

/** Deterministic radial layout: the centre node sits at the origin and its
 *  neighbours are placed on a ring. Positions do not reflow between renders. */
function layout(graph: GraphResponse): Node[] {
  const others = graph.nodes.filter((n) => !n.is_center);
  const radius = Math.max(220, 42 * others.length);
  return graph.nodes.map((node) => {
    if (node.is_center) {
      return {
        id: node.id,
        position: { x: 0, y: 0 },
        data: { label: node.name ?? node.id },
        className: "nl-node nl-node--center",
        draggable: true,
      };
    }
    const index = others.findIndex((o) => o.id === node.id);
    const angle = (2 * Math.PI * index) / Math.max(others.length, 1) - Math.PI / 2;
    return {
      id: node.id,
      position: { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius },
      data: { label: node.name ?? node.id },
      className: "nl-node",
      draggable: true,
    };
  });
}

/** Parallel claims between the same pair must stay visually distinct -
 *  opposing evidence is the point, so it is never collapsed into one line. */
function toEdges(graph: GraphResponse, selected: string | null): Edge[] {
  const parallelIndex = new Map<string, number>();
  return graph.edges.map((claim) => {
    const pairKey = [claim.subject.id, claim.object.id].join("->");
    const index = parallelIndex.get(pairKey) ?? 0;
    parallelIndex.set(pairKey, index + 1);
    const color = SIGN_COLOR[String(claim.effect_sign)] ?? SIGN_COLOR.null;
    const isSelected = claim.claim_id === selected;
    return {
      id: claim.claim_id,
      source: claim.subject.id,
      target: claim.object.id,
      type: "default",
      pathOptions: { curvature: 0.18 + index * 0.22 },
      animated: isSelected,
      label: `${PREDICATE_GLYPH[claim.predicate] ?? ""} ${claim.predicate}`,
      labelStyle: { fontSize: 10, fill: "#3c4149" },
      labelBgStyle: { fill: "#ffffff", fillOpacity: 0.85 },
      markerEnd: { type: "arrowclosed", color, width: 14, height: 14 },
      style: {
        stroke: color,
        strokeWidth: isSelected ? 3.5 : Math.min(1 + claim.support_count * 0.25, 4),
        strokeDasharray: claim.negated ? "5 4" : undefined,
        opacity: selected && !isSelected ? 0.28 : 1,
      },
    } as Edge;
  });
}

/** NCBI taxon ids seen in this snapshot's evidence context. Animal-model
 *  findings must stay visibly distinct from human findings (plan s1). */
const TAXON: Record<string, string> = {
  "9606": "human",
  "10090": "mouse",
  "10116": "rat",
  "4932": "yeast",
  "6239": "C. elegans",
  "7227": "Drosophila",
  "7955": "zebrafish",
  "9031": "chicken",
  "9913": "bovine",
  "9544": "macaque",
  "9615": "dog",
  "9986": "rabbit",
};

function SpeciesBadge({ context }: { context: Record<string, unknown> | null }) {
  const taxon = context?.taxon_id;
  if (!taxon) return <span className="muted">species not stated</span>;
  const key = String(taxon);
  const label = TAXON[key] ?? `taxon:${key}`;
  return (
    <span className={key === "9606" ? "badge badge--human" : "badge badge--model"}>
      {label}
    </span>
  );
}

function SignBadge({ claim }: { claim: ClaimView }) {
  if (claim.effect_sign === 1) return <span className="badge badge--pos">activating (+1)</span>;
  if (claim.effect_sign === -1) return <span className="badge badge--neg">inhibiting (−1)</span>;
  return <span className="badge badge--none">no causal sign</span>;
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [query, setQuery] = useState("TARDBP");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [centerId, setCenterId] = useState<string | null>(null);
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [loadingGraph, setLoadingGraph] = useState(false);
  const [selectedClaim, setSelectedClaim] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<EvidenceResponse | null>(null);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [loadingEvidence, setLoadingEvidence] = useState(false);

  const [mode, setMode] = useState<"analysis" | "pathways" | "cinematic" | "intervention">(window.location.hash === "#intervention" ? "intervention" : "pathways");
  const [maxNodes, setMaxNodes] = useState(18);
  const [causalOnly, setCausalOnly] = useState(false);
  const [minSupport, setMinSupport] = useState(0);
  const [edgeScope, setEdgeScope] = useState<"incident" | "all">("incident");
  const [pathQuery, setPathQuery] = useState("");
  const [pathResult, setPathResult] = useState<PathResponse | null>(null);
  const [pathError, setPathError] = useState<string | null>(null);
  const [pathBusy, setPathBusy] = useState(false);

  useEffect(() => {
    api.health().then(setHealth).catch((e) => setHealthError(String(e.message ?? e)));
  }, []);

  const runSearch = useCallback(async (term: string) => {
    if (!term.trim()) return;
    try {
      const data = await api.search(term);
      setResults(data.results);
      if (data.results.length > 0) setCenterId(data.results[0].id);
    } catch (e) {
      setResults([]);
      setGraphError(String((e as Error).message));
    }
  }, []);

  useEffect(() => {
    if (health?.snapshot_ready) void runSearch("TARDBP");
  }, [health, runSearch]);

  useEffect(() => {
    if (!centerId) return;
    setLoadingGraph(true);
    setGraphError(null);
    setSelectedClaim(null);
    setEvidence(null);
    setPathResult(null);
    setPathError(null);
    api
      .graph(centerId, { maxNodes, causalOnly, minSupport, edgeScope })
      .then(setGraph)
      .catch((e) => {
        setGraph(null);
        setGraphError(String((e as Error).message));
      })
      .finally(() => setLoadingGraph(false));
  }, [centerId, maxNodes, causalOnly, minSupport, edgeScope]);

  /** Chips show search hits, but the current centre must always be among them -
   *  otherwise re-centring by node click leaves a stale-looking selection. */
  const chips = useMemo(() => {
    const list = [...results];
    if (centerId && !list.some((r) => r.id === centerId)) {
      const node = graph?.nodes.find((n) => n.is_center);
      list.unshift({
        id: centerId,
        preferred_name: node?.name ?? centerId,
        long_name: node?.long_name ?? null,
        entity_type: node?.entity_type ?? null,
        degree: graph?.edges.length ?? 0,
      });
    }
    return list;
  }, [results, centerId, graph]);

  const nodes = useMemo(() => (graph ? layout(graph) : []), [graph]);
  const edges = useMemo(() => (graph ? toEdges(graph, selectedClaim) : []), [graph, selectedClaim]);

  const selectClaim = useCallback((claimId: string) => {
    setSelectedClaim(claimId);
    setLoadingEvidence(true);
    setEvidenceError(null);
    api
      .evidence(claimId)
      .then(setEvidence)
      .catch((e) => {
        setEvidence(null);
        setEvidenceError(String((e as Error).message));
      })
      .finally(() => setLoadingEvidence(false));
  }, []);

  const onEdgeClick = useCallback(
    (_: unknown, edge: Edge) => selectClaim(edge.id),
    [selectClaim],
  );

  const onNodeClick = useCallback(
    (_: unknown, node: Node) => setCenterId(node.id),
    [],
  );

  /** Resolve a typed gene name, then ask the API for bounded causal paths. */
  const runPath = useCallback(async () => {
    if (!centerId || !pathQuery.trim()) return;
    setPathBusy(true);
    setPathError(null);
    setPathResult(null);
    try {
      const found = await api.search(pathQuery);
      if (found.results.length === 0) {
        setPathError(`No entity named "${pathQuery}" in this snapshot.`);
        return;
      }
      const target = found.results[0];
      if (target.id === centerId) {
        setPathError("Source and target are the same entity.");
        return;
      }
      setPathResult(await api.path(centerId, target.id, true));
    } catch (e) {
      setPathError(String((e as Error).message));
    } finally {
      setPathBusy(false);
    }
  }, [centerId, pathQuery]);

  /** Opposing claims between the same ordered pair - the case the tool exists
   *  to surface. Shown first so it is never buried in the list. */
  const conflicts = useMemo(() => {
    // A conflict requires paper support on BOTH sides. Half of all pairs in this
    // snapshot disagree in sign, so the bare fact of disagreement carries little
    // information - the support ratio is what a reader needs.
    const out = new Map<string, { pos: number; neg: number }>();
    if (!graph) return out;
    const byPair = new Map<string, { pos: number; neg: number }>();
    for (const e of graph.edges) {
      if (e.effect_sign === null || e.support_count === 0) continue;
      const key = e.subject.id + "->" + e.object.id;
      const entry = byPair.get(key) ?? { pos: 0, neg: 0 };
      if (e.effect_sign === 1) entry.pos += e.support_count;
      else entry.neg += e.support_count;
      byPair.set(key, entry);
    }
    for (const e of graph.edges) {
      const key = e.subject.id + "->" + e.object.id;
      const entry = byPair.get(key);
      if (entry && entry.pos > 0 && entry.neg > 0) out.set(e.claim_id, entry);
    }
    return out;
  }, [graph]);

  const sortedEdges = useMemo(() => {
    if (!graph) return [];
    return [...graph.edges].sort((a, b) => {
      const minority = (c: typeof a) => {
        const e = conflicts.get(c.claim_id);
        if (!e) return 0;
        return Math.min(e.pos, e.neg) / (e.pos + e.neg);
      };
      const diff = minority(b) - minority(a);
      if (Math.abs(diff) > 0.001) return diff;
      return b.support_count - a.support_count;
    });
  }, [graph, conflicts]);

  if (healthError) {
    return (
      <div className="fatal">
        <h1>API unreachable</h1>
        <p>{healthError}</p>
        <p className="muted">
          Start the service: <code>scripts/run_api.sh</code> (expects it on port 8077)
        </p>
      </div>
    );
  }

  if (health && !health.snapshot_ready) {
    return (
      <div className="fatal">
        <h1>No snapshot loaded</h1>
        <p>{health.detail}</p>
        <p className="muted">Build one: retrieve → normalize → build</p>
      </div>
    );
  }

  if (mode === "pathways") {
    return <PathwayView health={health} onExit={() => setMode("analysis")} />;
  }

  if (mode === "intervention") {
    return <InterventionView onExit={() => setMode("analysis")} />;
  }

  if (mode === "cinematic") {
    return <CinematicView health={health} onExit={() => setMode("analysis")} />;
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <strong>nucleolus</strong>
          <span className="muted"> ALS/FTD mechanism evidence browser</span>
        </div>
        <form
          className="search"
          onSubmit={(e) => {
            e.preventDefault();
            void runSearch(query);
          }}
        >
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search a gene, e.g. TARDBP, TBK1, SOD1"
            aria-label="Search entities"
          />
          <button type="submit">Search</button>
        </form>
        <button className="modepw" onClick={() => setMode("pathways")}>
          Pathways
        </button>
        <button onClick={() => setMode("intervention")}>Intervention</button>
        <button className="mode3d" onClick={() => setMode("cinematic")}>
          3D
        </button>
        {health?.snapshot && (
          <div className="snapmeta" title={health.snapshot.checksum}>
            snapshot <code>{health.snapshot.id}</code> · {health.coverage?.claims} claims ·{" "}
            {health.coverage?.documents} papers
          </div>
        )}
      </header>

      {chips.length > 0 && (
        <div className="results">
          {chips.map((r) => (
            <button
              key={r.id}
              className={r.id === centerId ? "chip chip--active" : "chip"}
              onClick={() => setCenterId(r.id)}
            >
              {r.preferred_name ?? r.id}
              <span className="muted"> · {r.degree}</span>
            </button>
          ))}
        </div>
      )}

      <div className="filters">
        <label>
          neighbours
          <input
            type="range"
            min={4}
            max={40}
            value={maxNodes}
            onChange={(e) => setMaxNodes(Number(e.target.value))}
          />
          <span className="mono">{maxNodes}</span>
        </label>
        <label>
          min papers
          <input
            type="range"
            min={0}
            max={10}
            value={minSupport}
            onChange={(e) => setMinSupport(Number(e.target.value))}
          />
          <span className="mono">{minSupport}</span>
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={causalOnly}
            onChange={(e) => setCausalOnly(e.target.checked)}
          />
          causal edges only
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={edgeScope === "all"}
            onChange={(e) => setEdgeScope(e.target.checked ? "all" : "incident")}
          />
          include links between neighbours
        </label>
        <label className="check disabled" title="Source provides no publication dates">
          <input type="checkbox" disabled /> date filter — unavailable
        </label>
        <label className="check disabled" title="Species is shown per quote, but 87% of evidence states none - filtering would hide most of it">
          <input type="checkbox" disabled /> species filter — shown, not filterable
        </label>
        {centerId && (
          <a className="export" href={api.exportUrl(centerId, maxNodes)} target="_blank" rel="noreferrer">
            Export JSON
          </a>
        )}
      </div>

      <div className="legend">
        <span><i className="swatch swatch--pos" /> activates / increases</span>
        <span><i className="swatch swatch--neg" /> inhibits / decreases</span>
        <span><i className="swatch swatch--none" /> binding or modification — no causal sign</span>
        <span className="muted">line thickness = supporting papers · click an edge for evidence · click a node to re-centre</span>
      </div>

      <main className="split">
        <section className="canvas">
          {loadingGraph && <div className="overlay">loading graph…</div>}
          {graphError && <div className="overlay error">{graphError}</div>}
          {graph && graph.edges.length === 0 && !loadingGraph && (
            <div className="overlay">
              No edges match these filters. Lower “min papers” or turn off “causal edges only”.
            </div>
          )}
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onEdgeClick={onEdgeClick}
            onNodeClick={onNodeClick}
            fitView
            minZoom={0.15}
            proOptions={{ hideAttribution: false }}
          >
            <Background />
            <Controls />
          </ReactFlow>
          {graph?.truncation.edges_truncated && (
            <div className="truncation">
              Truncated at {graph.truncation.hard_max_edges} edges — this view is not the
              complete set. Absence of an edge here is not evidence of absence.
            </div>
          )}
        </section>

        <aside className="panel">
          {!selectedClaim && (
            <div className="empty">
              <h2>Evidence</h2>
              <p className="muted">
                Click any edge to read the sentences that produced it, with the paper each
                came from.
              </p>
              <div className="pathbox">
                <h3>Causal path from {graph?.nodes.find((n) => n.is_center)?.name}</h3>
                <form
                  className="pathform"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void runPath();
                  }}
                >
                  <input
                    value={pathQuery}
                    onChange={(e) => setPathQuery(e.target.value)}
                    placeholder="to gene, e.g. SQSTM1"
                    aria-label="Path target"
                  />
                  <button type="submit" disabled={pathBusy}>
                    {pathBusy ? "…" : "Find"}
                  </button>
                </form>
                {pathError && <p className="patherr">{pathError}</p>}
                {pathResult && pathResult.paths.length === 0 && (
                  <p className="muted pathnote">
                    No causal path within {String(pathResult.filters.max_hops)} hops. A bounded
                    search finding nothing is not evidence that no path exists.
                  </p>
                )}
                {pathResult && pathResult.paths.length > 0 && (
                  <>
                    <ol className="paths">
                      {pathResult.paths.map((pth, i) => (
                        <li key={i}>
                          {pth.steps.map((step, j) => (
                            <span key={j} className="pstep">
                              {j === 0 && <strong>{step.from_name ?? step.from}</strong>}
                              <em>
                                {step.claims[0]?.effect_sign === 1
                                  ? " →+ "
                                  : step.claims[0]?.effect_sign === -1
                                    ? " —| "
                                    : " → "}
                              </em>
                              <strong>{step.to_name ?? step.to}</strong>
                              {step.claims.length > 1 && (
                                <span className="muted"> ({step.claims.length} claims)</span>
                              )}
                            </span>
                          ))}
                          <button
                            className="inspect"
                            onClick={() => {
                              const first = pth.steps[0]?.claims[0];
                              if (first) selectClaim(first.claim_id);
                            }}
                          >
                            inspect first step
                          </button>
                        </li>
                      ))}
                    </ol>
                    <p className="pathnote muted">
                      {pathResult.truncation.paths_truncated
                        ? pathResult.truncation.note
                        : "Complete within the declared limits."}{" "}
                      Causal edges only; bindings and modifications are excluded.
                    </p>
                  </>
                )}
              </div>

              {sortedEdges.length > 0 && (
                <>
                  <h3>Claims in view ({sortedEdges.length})</h3>
                  <ul className="claimlist">
                    {sortedEdges.map((e) => (
                      <li key={e.claim_id}>
                        <button onClick={() => selectClaim(e.claim_id)}>
                          <span className="cl-names">
                            {e.subject.name} <em>{e.predicate}</em> {e.object.name}
                          </span>
                          <span className="cl-meta">
                            {conflicts.get(e.claim_id) && (
                              <span className="badge badge--warn">
                                {conflicts.get(e.claim_id)!.pos}↑ / {conflicts.get(e.claim_id)!.neg}↓
                              </span>
                            )}
                            <span
                              className={
                                e.effect_sign === 1
                                  ? "dot dot--pos"
                                  : e.effect_sign === -1
                                    ? "dot dot--neg"
                                    : "dot dot--none"
                              }
                            />
                            {e.support_count} papers
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {health?.limitations && (
                <>
                  <h3>Known limitations</h3>
                  <ul className="limits">
                    {health.limitations.map((l) => (
                      <li key={l}>{l}</li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}

          {loadingEvidence && <div className="empty">loading evidence…</div>}
          {evidenceError && <div className="empty error">{evidenceError}</div>}

          {evidence && (
            <>
              <button className="back" onClick={() => { setSelectedClaim(null); setEvidence(null); }}>
                ← all claims in view
              </button>
              <div className="claimhead">
                <h2>
                  {evidence.claim.subject.name} <span className="pred">{evidence.claim.predicate}</span>{" "}
                  {evidence.claim.object.name}
                </h2>
                <div className="badges">
                  <SignBadge claim={evidence.claim} />
                  {evidence.claim.negated && <span className="badge badge--neg">negated</span>}
                  <span className="badge">{evidence.claim.support_count} papers</span>
                  <span className="badge">{evidence.total} extracted sentences</span>
                  <span className="badge">{evidence.claim.source_class_label}</span>
                  <span className="badge badge--warn">unreviewed</span>
                </div>
                {evidence.claim.source_counts && (
                  <div className="sources">
                    {Object.entries(evidence.claim.source_counts).map(([src, n]) => (
                      <span key={src} className="srcbadge">
                        {src} · {n}
                      </span>
                    ))}
                  </div>
                )}
                {(() => {
                  const mix = new Map<string, number>();
                  for (const item of evidence.evidence) {
                    const taxon = item.context?.taxon_id;
                    const key = taxon ? (TAXON[String(taxon)] ?? `taxon:${taxon}`) : "not stated";
                    mix.set(key, (mix.get(key) ?? 0) + 1);
                  }
                  const parts = [...mix.entries()].sort((a, b) => b[1] - a[1]);
                  return (
                    <div className="speciesmix">
                      species of supporting evidence:{" "}
                      {parts.map(([k, n], i) => (
                        <span key={k}>
                          {i > 0 && " · "}
                          <strong>{k}</strong> {n}
                        </span>
                      ))}
                    </div>
                  );
                })()}
                <p className="caveat">
                  {evidence.claim.support_count} distinct publications, not{" "}
                  {evidence.claim.support_count} independent studies. Extracted automatically;
                  no domain scientist has checked these against the source.
                </p>
              </div>

              <ol className="evidence">
                {evidence.evidence.map((item) => (
                  <li key={item.evidence_id}>
                    {item.quote ? (
                      <blockquote>{item.quote}</blockquote>
                    ) : (
                      <blockquote className="muted">
                        No sentence supplied by the source for this record.
                      </blockquote>
                    )}
                    <div className="evmeta">
                      {item.link ? (
                        <a href={item.link} target="_blank" rel="noreferrer">
                          {item.document?.id}
                        </a>
                      ) : (
                        <span className="muted">no publication reference</span>
                      )}
                      <span className="srcbadge">{item.source_evidence_code ?? "unknown source"}</span>
                      <SpeciesBadge context={item.context} />
                      <span className="muted">
                        date {item.document?.date_precision === "unknown" ? "unknown" : item.document?.publication_date}
                      </span>
                      <span className="muted">basis {item.experimental_basis}</span>
                      {item.negated && <span className="badge badge--neg">negated</span>}
                    </div>
                  </li>
                ))}
              </ol>
            </>
          )}
        </aside>
      </main>
    </div>
  );
}
