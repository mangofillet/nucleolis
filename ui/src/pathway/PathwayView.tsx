import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type EvidenceResponse,
  type Health,
  type PathwayLeg,
  type PathwayResponse,
  type PathwayRoute,
} from "../api";
import PathwayFlow, { legColor, legKey } from "./PathwayFlow";
import "./pathway.css";

interface Props {
  health: Health | null;
  onExit: () => void;
}

const DIRECTION_LABEL: Record<string, string> = {
  undisputed: "every supporting paper agrees",
  dominant: "a minority of papers disagree",
  contested: "the literature disagrees — no direction asserted",
  unsigned: "no direction in the underlying relation",
};

export default function PathwayView({ health, onExit }: Props) {
  const [sourceText, setSourceText] = useState("TBK1");
  const [targetText, setTargetText] = useState("");
  const [data, setData] = useState<PathwayResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [minPapers, setMinPapers] = useState(1);

  const [activeRoute, setActiveRoute] = useState<PathwayRoute | null>(null);
  const [hoverLeg, setHoverLeg] = useState<string | null>(null);
  const [selectedLeg, setSelectedLeg] = useState<PathwayLeg | null>(null);
  const [evidence, setEvidence] = useState<EvidenceResponse | null>(null);
  const [evidenceBusy, setEvidenceBusy] = useState(false);

  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(900);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) =>
      setWidth(Math.max(520, entries[0].contentRect.width)),
    );
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const run = useCallback(
    async (sourceName: string, targetName: string, floor: number) => {
      if (!sourceName.trim()) return;
      setBusy(true);
      setError(null);
      setActiveRoute(null);
      setSelectedLeg(null);
      setEvidence(null);
      try {
        const found = await api.search(sourceName);
        if (found.results.length === 0) {
          setData(null);
          setError(`No entity named "${sourceName}" in this snapshot.`);
          return;
        }
        let targetId: string | null = null;
        if (targetName.trim()) {
          const t = await api.search(targetName);
          if (t.results.length === 0) {
            setError(`No entity named "${targetName}" — showing all targets instead.`);
          } else {
            targetId = t.results[0].id;
          }
        }
        const result = await api.pathways(found.results[0].id, {
          maxTargets: 24,
          minPapers: floor,
          targetId,
        });
        setData(result);
        if (targetId) {
          const match = result.routes.find((r) => r.target_id === targetId);
          if (match) setActiveRoute(match);
          else setError("No bounded causal route reaches that target within 2 hops.");
        }
      } catch (e) {
        setData(null);
        setError(String((e as Error).message));
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (health?.snapshot_ready) void run("TBK1", "", 1);
  }, [health, run]);

  const openLeg = useCallback((leg: PathwayLeg) => {
    setSelectedLeg(leg);
    const first = leg.claims[0];
    if (!first) return;
    setEvidenceBusy(true);
    api
      .evidence(first.claim_id)
      .then(setEvidence)
      .catch((e) => setError(String((e as Error).message)))
      .finally(() => setEvidenceBusy(false));
  }, []);

  const names = useMemo(() => {
    const map = new Map<string, string>();
    data?.nodes.forEach((n) => map.set(n.id, n.name));
    return map;
  }, [data]);

  const nodeName = (id: string) => names.get(id) ?? id.split(":")[1] ?? id;

  return (
    <div className="pw">
      <header className="pw-top">
        <div className="pw-brand">
          <strong>nucleolis</strong>
          <span>INDRA CoGEx · bounded 2-hop perturbation search</span>
        </div>
        <button className="pw-exit" onClick={onExit}>
          Analysis view
        </button>
      </header>

      <div className="pw-body">
        <h1>
          {data ? (
            <>
              What does <em>{data.source.name}</em> reach?
            </>
          ) : (
            "Pathway search"
          )}
        </h1>

        <p className="pw-lede">
          Each line below is one claim from the literature: <i>this thing raises or
          lowers that thing</i>. A chain of two lines is how a source reaches something
          it never touches directly. <b>Line thickness is how many separate papers
          said it.</b> Colour is direction where the evidence agrees, amber where it
          does not — support and dispute are never netted into one number. Click any
          line to read the sentences and open the papers.
        </p>

        <form
          className="pw-query"
          onSubmit={(e) => {
            e.preventDefault();
            void run(sourceText, targetText, minPapers);
          }}
        >
          <label>
            <span>from</span>
            <input
              value={sourceText}
              onChange={(e) => setSourceText(e.target.value)}
              placeholder="TBK1"
              aria-label="Source entity"
            />
          </label>
          <label>
            <span>to</span>
            <input
              value={targetText}
              onChange={(e) => setTargetText(e.target.value)}
              placeholder="all targets"
              aria-label="Target entity"
            />
          </label>
          <label className="pw-floor">
            <span>min papers</span>
            <input
              type="range"
              min={1}
              max={10}
              value={minPapers}
              onChange={(e) => setMinPapers(Number(e.target.value))}
            />
            <b>{minPapers}</b>
          </label>
          <button type="submit" disabled={busy}>
            {busy ? "searching…" : "Trace"}
          </button>
        </form>

        <div className="pw-chips">
          {["TBK1", "TARDBP", "SOD1", "OPTN", "SQSTM1", "C9orf72", "FUS"].map((g) => (
            <button
              key={g}
              className={data?.source.name === g ? "pw-chip on" : "pw-chip"}
              onClick={() => {
                setSourceText(g);
                setTargetText("");
                void run(g, "", minPapers);
              }}
            >
              {g}
            </button>
          ))}
          {activeRoute && (
            <button className="pw-chip clear" onClick={() => setActiveRoute(null)}>
              Clear selection
            </button>
          )}
        </div>

        {error && <p className="pw-error">{error}</p>}

        <div className="pw-flowwrap" ref={wrapRef}>
          <PathwayFlow
            data={data}
            width={width}
            activeRoute={activeRoute}
            hoverLeg={hoverLeg}
            selectedLegKey={selectedLeg ? legKey(selectedLeg) : null}
            onLegClick={openLeg}
            onLegHover={setHoverLeg}
            onNodeClick={(id) => {
              const route = data?.routes.find((r) => r.target_id === id);
              setActiveRoute(route ?? null);
            }}
          />
        </div>

        {data && (
          <>
            <div className="pw-legend">
              <span><i style={{ background: "#5fb49c" }} /> raises</span>
              <span><i style={{ background: "#c97f66" }} /> lowers</span>
              <span><i style={{ background: "#d9a441" }} /> contested</span>
              <span className="dash"><i /> no direction asserted</span>
              <em>
                ranked by the weakest step, discounted by how promiscuous the
                intermediate is
              </em>
            </div>

            <table className="pw-table">
              <thead>
                <tr>
                  <th>Target</th>
                  <th>Route</th>
                  <th className="n">Weakest step</th>
                  <th className="n">Score</th>
                  <th>Direction</th>
                </tr>
              </thead>
              <tbody>
                {data.routes.map((route) => (
                  <tr
                    key={route.target_id}
                    className={activeRoute?.target_id === route.target_id ? "on" : ""}
                    onMouseEnter={() => setActiveRoute(route)}
                    onClick={() => setActiveRoute(route)}
                  >
                    <td className="t">{nodeName(route.target_id)}</td>
                    <td className="r">
                      {route.nodes.map((n, i) => (
                        <span key={n}>
                          {i > 0 && <i className="arrow">→</i>}
                          {nodeName(n)}
                        </span>
                      ))}
                    </td>
                    <td className="n">{route.weakest_leg_papers} papers</td>
                    <td className="n">{route.score}</td>
                    <td>
                      <span
                        className="dirpill"
                        style={{
                          color:
                            route.implied_direction === 1
                              ? "#5fb49c"
                              : route.implied_direction === -1
                                ? "#c97f66"
                                : "#d9a441",
                        }}
                      >
                        {route.implied_direction === 1
                          ? "raises"
                          : route.implied_direction === -1
                            ? "lowers"
                            : "contested"}
                      </span>
                      <span className="basis">{DIRECTION_LABEL[route.direction_basis]}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <p className="pw-trunc">{data.truncation.note}</p>
          </>
        )}
      </div>

      {/* evidence drawer */}
      <aside className={selectedLeg ? "pw-drawer open" : "pw-drawer"}>
        {selectedLeg && (
          <>
            <button className="pw-close" onClick={() => setSelectedLeg(null)}>
              ✕
            </button>
            <div className="pw-legtitle">
              <strong>{nodeName(selectedLeg.from)}</strong>
              <i style={{ color: legColor(selectedLeg) }}>
                {selectedLeg.sign === 1 ? "raises" : selectedLeg.sign === -1 ? "lowers" : "—"}
              </i>
              <strong>{nodeName(selectedLeg.to)}</strong>
            </div>
            <p className="pw-basis">{DIRECTION_LABEL[selectedLeg.sign_basis]}</p>

            {selectedLeg.contested && (
              <div className="pw-contest">
                <div className="pw-bar">
                  <i
                    className="pos"
                    style={{
                      width: `${(selectedLeg.contested.pos /
                        (selectedLeg.contested.pos + selectedLeg.contested.neg)) * 100}%`,
                    }}
                  />
                  <i className="neg" style={{ flex: 1 }} />
                </div>
                <span>
                  {selectedLeg.contested.pos} papers say raises · {selectedLeg.contested.neg}{" "}
                  say lowers. Shown as a ratio, never subtracted.
                </span>
              </div>
            )}

            <div className="pw-claims">
              {selectedLeg.claims.map((c) => (
                <button
                  key={c.claim_id}
                  className={evidence?.claim.claim_id === c.claim_id ? "on" : ""}
                  onClick={() => {
                    setEvidenceBusy(true);
                    api
                      .evidence(c.claim_id)
                      .then(setEvidence)
                      .finally(() => setEvidenceBusy(false));
                  }}
                >
                  <span>{c.predicate}</span>
                  <b>
                    {c.n_papers} papers
                    {c.n_sentences ? ` · ${c.n_sentences} sentences` : ""}
                  </b>
                  {c.sole_support_retracted && <em className="red">sole support retracted</em>}
                </button>
              ))}
            </div>

            <h4>Sentences {evidenceBusy && <em>loading…</em>}</h4>
            {evidence?.evidence.slice(0, 30).map((item) => (
              <div key={item.evidence_id} className="pw-quote">
                <p>{item.quote ?? "No sentence supplied by the source."}</p>
                <div className="pw-qmeta">
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
          </>
        )}
      </aside>
    </div>
  );
}
