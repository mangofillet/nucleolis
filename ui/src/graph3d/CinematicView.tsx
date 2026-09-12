import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type EvidenceResponse,
  type GraphResponse,
  type Health,
  type SearchResult,
} from "../api";
import Graph3D from "./Graph3D";
import { fromNucleolus } from "./adapt";
import { agreement } from "./types";
import "./cinematic.css";

interface Props {
  health: Health | null;
  onExit: () => void;
}

export default function CinematicView({ health, onExit }: Props) {
  const [query, setQuery] = useState("TARDBP");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [centerId, setCenterId] = useState<string | null>(null);
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [flyTo, setFlyTo] = useState<string | null>(null);

  const [selectedLinkId, setSelectedLinkId] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<EvidenceResponse | null>(null);
  const [evidenceBusy, setEvidenceBusy] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [focusNodeId, setFocusNodeId] = useState<string | null>(null);

  const [maxNodes, setMaxNodes] = useState(16);
  const [minSupport, setMinSupport] = useState(0);

  const runSearch = useCallback(async (term: string) => {
    if (!term.trim()) return;
    try {
      const found = await api.search(term);
      setResults(found.results);
      if (found.results.length > 0) setCenterId(found.results[0].id);
      else setError(`Nothing named "${term}" in this snapshot.`);
    } catch (e) {
      setError(String((e as Error).message));
    }
  }, []);

  useEffect(() => {
    if (health?.snapshot_ready) void runSearch("TARDBP");
  }, [health, runSearch]);

  useEffect(() => {
    if (!centerId) return;
    setLoading(true);
    setError(null);
    setSelectedLinkId(null);
    setEvidence(null);
    setDrawerOpen(false);
    api
      .graph(centerId, { maxNodes, causalOnly: false, minSupport, edgeScope: "incident" })
      .then((g) => {
        setGraph(g);
        // Let the layout settle before flying, or the camera chases a moving node.
        window.setTimeout(() => setFlyTo(centerId), 900);
      })
      .catch((e) => {
        setGraph(null);
        setError(String((e as Error).message));
      })
      .finally(() => setLoading(false));
  }, [centerId, maxNodes, minSupport]);

  const data = useMemo(() => (graph ? fromNucleolus(graph) : { nodes: [], links: [] }), [graph]);

  const selectLink = useCallback((claimId: string) => {
    setSelectedLinkId(claimId);
    setDrawerOpen(true);
    setEvidenceBusy(true);
    api
      .evidence(claimId)
      .then(setEvidence)
      .catch((e) => setError(String((e as Error).message)))
      .finally(() => setEvidenceBusy(false));
  }, []);

  /** Nodes are large, reliable click targets; thin links in 3D depth are not.
   *  Clicking a node flies to it and lists its claims, and the claim list is the
   *  dependable route into the evidence. */
  const selectNode = useCallback((nodeId: string) => {
    setFlyTo(nodeId);
    setFocusNodeId(nodeId);
    setSelectedLinkId(null);
    setEvidence(null);
    setDrawerOpen(true);
  }, []);

  const nodeClaims = useMemo(() => {
    if (!focusNodeId) return [];
    return data.links
      .filter((l) => l.source === focusNodeId || l.target === focusNodeId)
      .sort((a, b) => {
        const contest = (l: typeof a) =>
          l.opposing ? Math.min(l.opposing.pos, l.opposing.neg) / (l.opposing.pos + l.opposing.neg) : 0;
        if (a.soleSupportRetracted !== b.soleSupportRetracted) {
          return a.soleSupportRetracted ? -1 : 1;
        }
        const diff = contest(b) - contest(a);
        if (Math.abs(diff) > 0.001) return diff;
        return b.papers - a.papers;
      });
  }, [focusNodeId, data.links]);

  const nodeName = useCallback(
    (id: string) => data.nodes.find((n) => n.id === id)?.name ?? id,
    [data.nodes],
  );

  const claim = evidence?.claim;
  const ratio = useMemo(() => {
    if (!claim || !graph) return null;
    const link = data.links.find((l) => l.id === claim.claim_id);
    return link?.opposing ?? null;
  }, [claim, graph, data.links]);

  return (
    <div className="cine">
      <Graph3D
        data={data}
        selectedLinkId={selectedLinkId}
        onSelectLink={selectLink}
        onSelectNode={selectNode}
        flyTo={flyTo}
      />

      {/* ---- top overlay ------------------------------------------------ */}
      <header className="cine-top">
        <div className="cine-brand">
          <span className="cine-mark" />
          <div>
            <strong>nucleolus</strong>
            <span className="cine-sub">ALS/FTD mechanism space</span>
          </div>
        </div>

        <form
          className="cine-search"
          onSubmit={(e) => {
            e.preventDefault();
            void runSearch(query);
          }}
        >
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search a target — TARDBP, TBK1, SOD1…"
            aria-label="Search entities"
          />
          <button type="submit">Query</button>
        </form>

        <button className="cine-exit" onClick={onExit}>
          Analysis view
        </button>
      </header>

      {results.length > 1 && (
        <div className="cine-chips">
          {results.slice(0, 8).map((r) => (
            <button
              key={r.id}
              className={r.id === centerId ? "cine-chip on" : "cine-chip"}
              onClick={() => setCenterId(r.id)}
            >
              {r.preferred_name ?? r.id}
            </button>
          ))}
        </div>
      )}

      {/* ---- bottom-left controls + legend ------------------------------ */}
      <div className="cine-hud">
        <div className="cine-controls">
          <label>
            <span>nodes</span>
            <input
              type="range"
              min={6}
              max={40}
              value={maxNodes}
              onChange={(e) => setMaxNodes(Number(e.target.value))}
            />
            <b>{maxNodes}</b>
          </label>
          <label>
            <span>min papers</span>
            <input
              type="range"
              min={0}
              max={10}
              value={minSupport}
              onChange={(e) => setMinSupport(Number(e.target.value))}
            />
            <b>{minSupport}</b>
          </label>
        </div>
        <div className="cine-legend">
          <span><i style={{ background: "#34d399" }} /> activates</span>
          <span><i style={{ background: "#f87171" }} /> inhibits</span>
          <span><i style={{ background: "#fbbf24" }} /> contested</span>
          <span><i style={{ background: "#64748b" }} /> no causal sign</span>
          <em>thickness = papers · colour = agreement</em>
        </div>
        {data.meta?.truncated && <p className="cine-trunc">{data.meta.truncationNote}</p>}
      </div>

      {loading && <div className="cine-status">resolving mechanism space…</div>}
      {error && <div className="cine-status err">{error}</div>}

      {/* ---- drawer ------------------------------------------------------ */}
      <aside className={drawerOpen ? "cine-drawer open" : "cine-drawer"}>
        {!claim && focusNodeId && (
          <>
            <button className="cine-close" onClick={() => setDrawerOpen(false)}>
              ✕
            </button>
            <div className="cine-eq">
              <strong>{nodeName(focusNodeId)}</strong>
            </div>
            <div className="cine-pred">{nodeClaims.length} claims in view</div>
            <button className="cine-recentre" onClick={() => setCenterId(focusNodeId)}>
              Re-centre the query here
            </button>
            <ul className="cine-list">
              {nodeClaims.map((link) => (
                <li key={link.id}>
                  <button onClick={() => selectLink(link.id)}>
                    <span className="cl-eq">
                      {nodeName(link.source)}{" "}
                      <em>
                        {link.sign === 1 ? "→" : link.sign === -1 ? "⊣" : "—"}
                      </em>{" "}
                      {nodeName(link.target)}
                    </span>
                    <span className="cl-meta">
                      {link.soleSupportRetracted && <b className="red">retracted</b>}
                      {link.opposing && (
                        <b className="amber">
                          {link.opposing.pos}↑/{link.opposing.neg}↓
                        </b>
                      )}
                      {link.papers} papers
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}

        {claim && (
          <>
            <button className="cine-close" onClick={() => setDrawerOpen(false)}>
              ✕
            </button>
            {focusNodeId && (
              <button
                className="cine-back"
                onClick={() => {
                  setEvidence(null);
                  setSelectedLinkId(null);
                }}
              >
                ← {nodeName(focusNodeId)} claims
              </button>
            )}
            <div className="cine-claim">
              <div className="cine-eq">
                <strong>{claim.subject.name}</strong>
                <span className={claim.effect_sign === -1 ? "op neg" : claim.effect_sign === 1 ? "op pos" : "op"}>
                  {claim.effect_sign === 1 ? "→" : claim.effect_sign === -1 ? "⊣" : "—"}
                </span>
                <strong>{claim.object.name}</strong>
              </div>
              <div className="cine-pred">{claim.predicate}</div>

              {claim.sole_support_retracted && (
                <div className="cine-alarm">
                  Every supporting publication has been retracted. This claim has no
                  surviving evidence.
                </div>
              )}

              <div className="cine-metrics">
                <div>
                  <b>{claim.n_papers}</b>
                  <span>papers</span>
                </div>
                <div>
                  <b>{claim.n_primary ?? "—"}</b>
                  <span>primary</span>
                </div>
                <div>
                  <b>{claim.n_sentences ?? "—"}</b>
                  <span>sentences</span>
                </div>
                <div>
                  <b>{claim.earliest_publication_date ?? "—"}</b>
                  <span>earliest</span>
                </div>
              </div>

              {ratio && (
                <div className="cine-contest">
                  <div className="cine-bar">
                    <i
                      className="pos"
                      style={{ width: `${(ratio.pos / (ratio.pos + ratio.neg)) * 100}%` }}
                    />
                    <i
                      className="neg"
                      style={{ width: `${(ratio.neg / (ratio.pos + ratio.neg)) * 100}%` }}
                    />
                  </div>
                  <span>
                    contested — {ratio.pos} papers assert activation, {ratio.neg} assert
                    inhibition. Agreement{" "}
                    {Math.round(
                      (agreement({ opposing: ratio } as never) ?? 1) * 100,
                    )}
                    %. Not netted.
                  </span>
                </div>
              )}

              {claim.n_sentences && claim.n_papers > 0 && claim.n_sentences / claim.n_papers > 1.5 && (
                <p className="cine-note">
                  {(claim.n_sentences / claim.n_papers).toFixed(1)}× more sentences than
                  papers — repetition, not independent replication.
                </p>
              )}

              {claim.source_counts && (
                <div className="cine-srcs">
                  {Object.entries(claim.source_counts).map(([k, v]) => (
                    <span key={k}>
                      {k} · {v}
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className="cine-ev">
              <h4>Evidence {evidenceBusy && <em>loading…</em>}</h4>
              {evidence?.evidence.slice(0, 25).map((item) => (
                <div key={item.evidence_id} className="cine-quote">
                  <p>{item.quote ?? "No sentence supplied by the source."}</p>
                  <div className="cine-qmeta">
                    {item.link ? (
                      <a href={item.link} target="_blank" rel="noreferrer">
                        {item.document?.id}
                      </a>
                    ) : (
                      <span>no reference</span>
                    )}
                    <span>{item.document?.publication_date ?? "date unknown"}</span>
                    {item.document?.is_primary === false && <span className="tag">review</span>}
                    {item.document?.retraction_status === "retracted" && (
                      <span className="tag red">retracted</span>
                    )}
                    <span className="tag">{item.source_evidence_code}</span>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </aside>
    </div>
  );
}
