/* Resilience vs damage - the brain-ageing showcase.
 *
 * Two sides, the claims that cross between them, and the sentences behind each
 * one. The view never resolves a contested pair into an arrow: where the
 * literature disagrees it says so and shows both counts, because in this corpus
 * disagreement is the common case rather than the exception.
 */
import { useEffect, useState } from "react";
import { NucleolisLockup } from "../brand/Logo";
import "./showcase.css";

const BASE = import.meta.env.VITE_API_BASE ?? "";

type Side = "resilience" | "damage";

interface Gene {
  id: string;
  name: string;
  long_name: string | null;
  axis: string;
  side: Side;
  degree: number;
  rationale: string;
}

interface AxisGroup {
  axis: string;
  genes: Gene[];
}

interface LinkEnd {
  id: string;
  name: string;
  axis: string;
  side: Side;
}

interface Claim {
  claim_id: string;
  predicate: string;
  effect_sign: 1 | -1 | null;
  negated: boolean;
  support_count: number;
}

interface Link {
  from: LinkEnd;
  to: LinkEnd;
  direction: 1 | -1 | null;
  basis: "undisputed" | "dominant" | "contested";
  support_up: number;
  support_down: number;
  claims: Claim[];
}

interface AxesResponse {
  snapshot_id: string;
  filters: Record<string, unknown>;
  sides: Record<string, AxisGroup[]>;
  seeds_not_in_snapshot: { symbol: string; axis: string; side: Side | null; reason: string }[];
  links: Link[];
  truncated: boolean;
  total_links: number;
  note: string;
}

interface EvidenceRecord {
  quote: string | null;
  pmid: string | null;
  source_api: string | null;
  species: string | null;
}

const AXIS_LABEL: Record<string, string> = {
  autophagy: "Autophagy & proteostasis",
  mitochondrial: "Mitochondrial function",
  plasticity: "Synaptic plasticity",
  nutrient_sensing: "Nutrient sensing",
  senescence: "Cellular senescence",
  neuroinflammation: "Neuroinflammation",
  oxidative_stress: "Oxidative stress",
  proteostasis: "Protein aggregation",
};

const label = (axis: string) => AXIS_LABEL[axis] ?? axis.replaceAll("_", " ");

function Ratio({ up, down }: { up: number; down: number }) {
  return (
    <span className="sc-ratio">
      {up > 0 && <span className="sc-ratio__up">{up}↑</span>}
      {up > 0 && down > 0 && <span className="sc-ratio__sep">/</span>}
      {down > 0 && <span className="sc-ratio__down">{down}↓</span>}
      <span className="sc-ratio__unit">papers</span>
    </span>
  );
}

export default function ResilienceView() {
  const [data, setData] = useState<AxesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openLink, setOpenLink] = useState<Link | null>(null);
  const [evidence, setEvidence] = useState<EvidenceRecord[] | null>(null);
  const [evidenceFor, setEvidenceFor] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${BASE}/axes?max_links=60`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`${r.status} ${(await r.text()).slice(0, 200)}`);
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(String(e.message ?? e)));
  }, []);

  async function inspect(link: Link) {
    setOpenLink(link);
    const claim = link.claims[0];
    setEvidenceFor(claim.claim_id);
    setEvidence(null);
    try {
      const r = await fetch(`${BASE}/edges/${encodeURIComponent(claim.claim_id)}/evidence?limit=8`);
      const payload = await r.json();
      setEvidence(payload.evidence ?? []);
    } catch {
      setEvidence([]);
    }
  }

  if (error) {
    return (
      <div className="sc-page">
        <p className="sc-error">
          Could not load the mechanism axes: {error}
          <br />
          This view needs a built snapshot. Run <code>scripts/rebuild_snapshot.sh</code>.
        </p>
      </div>
    );
  }
  if (!data) return <div className="sc-page"><p className="sc-loading">Loading mechanism axes…</p></div>;

  const resilience = data.sides.resilience ?? [];
  const damage = data.sides.damage ?? [];

  return (
    <div className="sc-page">
      <header className="sc-hero">
        <div className="sc-hero__bar">
          <NucleolisLockup size={30} tone="reverse" />
          <nav className="sc-hero__nav">
            <a href="#">Workspace</a>
            <a href="#explorer">Evidence browser</a>
          </nav>
        </div>
        <p className="eyebrow sc-hero__eyebrow">Brain ageing · mechanism showcase</p>
        <h1 className="display sc-hero__title">
          What holds cognition up,
          <br />
          and what wears it down.
        </h1>
        <p className="sc-hero__lede">
          Two sides of the same literature. On the left, the mechanisms associated with
          maintained cognitive function; on the right, those associated with its decline.
          Every line between them is a claim you can open and read the sentences behind.
        </p>
        <dl className="sc-hero__stats">
          <div>
            <dt>Crossing claims</dt>
            <dd>{data.total_links}</dd>
          </div>
          <div>
            <dt>Contested</dt>
            <dd>{data.links.filter((l) => l.basis === "contested").length}</dd>
          </div>
          <div>
            <dt>Snapshot</dt>
            <dd className="mono">{data.snapshot_id}</dd>
          </div>
        </dl>
      </header>

      <section className="sc-axes">
        <div className="sc-column sc-column--resilience">
          <h2 className="sc-column__head">
            <span className="sc-column__dot" /> Resilience
          </h2>
          {resilience.map((group) => (
            <div key={group.axis} className="sc-group">
              <h3>{label(group.axis)}</h3>
              <ul>
                {group.genes.map((g) => (
                  <li key={g.id} title={g.rationale}>
                    <strong>{g.name}</strong>
                    <span className="sc-gene__degree">{g.degree}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="sc-column sc-column--damage">
          <h2 className="sc-column__head">
            <span className="sc-column__dot" /> Damage
          </h2>
          {damage.map((group) => (
            <div key={group.axis} className="sc-group">
              <h3>{label(group.axis)}</h3>
              <ul>
                {group.genes.map((g) => (
                  <li key={g.id} title={g.rationale}>
                    <strong>{g.name}</strong>
                    <span className="sc-gene__degree">{g.degree}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      <section className="sc-links">
        <h2 className="sc-links__head">
          Where the two sides meet
          <span className="sc-links__sub">
            signed causal claims only · ranked by supporting papers
            {data.truncated && ` · showing ${data.links.length} of ${data.total_links}`}
          </span>
        </h2>

        <ul className="sc-linklist">
          {data.links.map((link) => (
            <li key={`${link.from.id}-${link.to.id}`}>
              <button className="sc-link" onClick={() => void inspect(link)}>
                <span className={`sc-link__end sc-link__end--${link.from.side}`}>
                  {link.from.name}
                </span>
                <span className={`sc-link__arrow sc-link__arrow--${link.basis}`}>
                  {link.direction === 1 ? "increases" : link.direction === -1 ? "decreases" : "direction disputed"}
                </span>
                <span className={`sc-link__end sc-link__end--${link.to.side}`}>{link.to.name}</span>
                <span className={`sc-basis sc-basis--${link.basis}`}>{link.basis}</span>
                <Ratio up={link.support_up} down={link.support_down} />
              </button>
            </li>
          ))}
        </ul>

        {data.links.length === 0 && (
          <p className="sc-empty">
            No signed causal claim in this snapshot crosses between the two sides. That is a
            finding about the corpus, not a rendering failure.
          </p>
        )}
      </section>

      {openLink && (
        <aside className="sc-drawer">
          <div className="sc-drawer__head">
            <h3>
              {openLink.from.name} → {openLink.to.name}
            </h3>
            <button onClick={() => { setOpenLink(null); setEvidence(null); }} aria-label="Close">
              ✕
            </button>
          </div>
          <p className="sc-drawer__basis">
            <span className={`sc-basis sc-basis--${openLink.basis}`}>{openLink.basis}</span>
            <Ratio up={openLink.support_up} down={openLink.support_down} />
          </p>
          {openLink.basis === "contested" && (
            <p className="sc-drawer__warn">
              The literature supports both directions at comparable weight. This view asserts
              no direction for this pair, and the minority count is shown rather than subtracted.
            </p>
          )}
          <ul className="sc-claims">
            {openLink.claims.map((c) => (
              <li key={c.claim_id} className={c.claim_id === evidenceFor ? "active" : ""}>
                <code>{c.predicate}</code>
                <span>{c.support_count} papers</span>
                {c.negated && <em>negated</em>}
              </li>
            ))}
          </ul>
          <h4>Evidence</h4>
          {evidence === null && <p className="sc-loading">Loading sentences…</p>}
          {evidence?.length === 0 && <p className="sc-loading">No quoted sentence on this claim.</p>}
          {evidence?.map((e, i) => (
            <blockquote key={i}>
              {e.quote ?? <em>No sentence text stored for this record.</em>}
              <footer>
                {e.pmid && (
                  <a href={`https://pubmed.ncbi.nlm.nih.gov/${e.pmid}/`} target="_blank" rel="noreferrer">
                    PMID {e.pmid}
                  </a>
                )}
                {e.source_api && <span>{e.source_api}</span>}
                <span>{e.species ?? "species not stated"}</span>
              </footer>
            </blockquote>
          ))}
        </aside>
      )}

      <footer className="sc-foot">
        <p>{data.note}</p>
        {data.seeds_not_in_snapshot.length > 0 && (
          <p>
            <strong>{data.seeds_not_in_snapshot.length} seeded genes are not in this snapshot</strong>{" "}
            and are therefore absent from the columns above:{" "}
            {data.seeds_not_in_snapshot.map((s) => s.symbol).join(", ")}. They are listed rather
            than hidden so the axes are not read as complete.
          </p>
        )}
        <p>
          Nothing here has been reviewed by a domain scientist. Claims come from automated
          reading of the literature and carry its errors.
        </p>
      </footer>
    </div>
  );
}
