import { useMemo } from "react";
import type { ResearchResult } from "./api";

export default function MechanismCanvas({ result, selectedNode, selectedLink, activePath, onNode, onLink, zoom }: {
  result: ResearchResult; selectedNode: string | null; selectedLink: string | null;
  activePath: string | null; onNode: (id: string) => void; onLink: (id: string) => void; zoom: number;
}) {
  const layout = useMemo(() => {
    const positions = new Map<string, { x: number; y: number }>();
    const lanes = result.lanes.map((label, lane) => {
      const members = result.nodes.filter(n => n.lane === lane);
      return { label, members, height: Math.max(158, Math.ceil(members.length / 4) * 102 + 44), y: 0 };
    });
    let y = 12;
    for (const lane of lanes) {
      lane.y = y;
      lane.members.forEach((node, i) => {
        const row = Math.floor(i / 4), count = Math.min(4, lane.members.length - row * 4);
        positions.set(node.id, { x: 230 + (760 / count) * (i % 4 + 0.5), y: y + 62 + row * 102 });
      });
      y += lane.height + 12;
    }
    return { lanes, positions, height: y + 8 };
  }, [result]);
  const path = result.paths.find(p => p.id === activePath);
  const upstream = ["incoming", "target_discovery"].includes(result.plan.operation);
  const laneDescriptions = upstream
    ? ["Two steps before the readout", "One step before the readout", "Starting point of the question"]
    : ["Starting point of the question", "One signed relationship", "Readout or two-step hypotheses"];
  const name = (id: string) => result.nodes.find(n => n.id === id)?.name ?? id;
  return <svg className="rw-canvas" data-testid="mechanism-canvas" viewBox={`0 0 1024 ${layout.height}`} style={{ width: `${zoom}%` }} aria-label="Mechanism graph arranged by graph distance" role="group" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <marker id="rw-positive" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0L7 3.5L0 7Z" fill="#278d8d" /></marker>
      <marker id="rw-negative" markerWidth="8" markerHeight="10" refX="6" refY="5" orient="auto"><path d="M6 0v10" stroke="#d35d76" strokeWidth="2" /></marker>
      <filter id="rw-shadow" x="-20%" y="-30%" width="140%" height="170%"><feDropShadow dx="0" dy="2" stdDeviation="3" floodColor="#123c59" floodOpacity="0.05" /></filter>
    </defs>
    {layout.lanes.map((lane, index) => <g key={lane.label}>
      <rect x="10" y={lane.y} width="1004" height={lane.height} rx="10" fill={index % 2 ? "#f0f8fc" : "#edf7fb"} />
      <text x="28" y={lane.y + 34} fill="#253d66" fontSize="14" fontWeight="600">{lane.label}</text>
      <text x="28" y={lane.y + 56} fill="#6e8099" fontSize="12">{laneDescriptions[index]}</text>
      {!lane.members.length && <text x="540" y={lane.y + 85} textAnchor="middle" fill="#73899c" fontSize="12">No nodes retrieved in this layer</text>}
    </g>)}
    {result.links.map((edge) => {
      const a = layout.positions.get(edge.source), b = layout.positions.get(edge.target);
      if (!a || !b) return null;
      // Every claim between one pair gets its own offset lane. A shared offset made
      // siblings cover each other's transparent hit path, so only the top one clicked.
      const siblings = result.links.filter(l => l.source === edge.source && l.target === edge.target);
      const offset = (siblings.findIndex(l => l.id === edge.id) - (siblings.length - 1) / 2) * 13;
      const ay = a.y + 30, by = b.y - 27;
      const mid = (ay + by) / 2 + offset;
      const d = a.y === b.y
        ? `M${a.x + 70},${a.y + offset / 2} C${a.x + 110},${a.y - 70 + offset} ${b.x - 110},${b.y - 70 + offset} ${b.x - 70},${b.y + offset / 2}`
        : `M${a.x + offset},${ay} V${mid} H${b.x + offset} V${by}`;
      const highlighted = selectedLink === edge.id || path?.claim_ids.includes(edge.id);
      const dim = Boolean((path && !path.claim_ids.includes(edge.id)) || (selectedLink && selectedLink !== edge.id));
      const label = `${name(edge.source)} ${edge.predicate.replaceAll("_", " ")} ${name(edge.target)}`;
      return <g key={edge.id} role="button" tabIndex={0} aria-label={label} onClick={() => onLink(edge.id)} onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onLink(edge.id); } }} className="rw-svg-edge">
        <title>{label} · {edge.publication_ids.length} publications · {edge.review_status}</title>
        {/* Narrower than the 13px lane spacing above, so a sibling never covers this hit target. */}
        <path d={d} fill="none" stroke="transparent" strokeWidth="9" />
        <path d={d} fill="none" stroke={edge.sign === 1 ? "#278d8d" : "#d35d76"} strokeWidth={highlighted ? 2.5 : 1.4} strokeOpacity={dim ? .12 : .8} strokeDasharray={edge.sign === -1 ? "5 4" : undefined} markerEnd={`url(#rw-${edge.sign === 1 ? "positive" : "negative"})`} pointerEvents="none" />
      </g>;
    })}
    {result.nodes.map(node => {
      const p = layout.positions.get(node.id);
      if (!p) return null;
      const stroke = node.state === "decreased" ? "#e4a7b4" : node.state === "increased" ? "#94cfca" : node.state === "mixed" ? "#dfbd7b" : node.focus ? "#7aaee0" : "#b6cedf";
      const fill = node.state === "decreased" ? "#fff0f3" : node.state === "increased" ? "#edf9f6" : node.state === "mixed" ? "#fff8e9" : node.focus ? "#e8f3ff" : "#f9fcff";
      return <g key={node.id} role="button" tabIndex={0} aria-label={`Inspect ${node.name}`} className="rw-svg-node" onClick={() => onNode(node.id)} onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onNode(node.id); } }} opacity={path && !path.node_ids.includes(node.id) ? .35 : 1}>
        <title>{node.description ?? node.name}</title>
        <rect x={p.x - 73} y={p.y - 26} width="146" height="56" rx="6" fill={fill} stroke={selectedNode === node.id ? "#217e86" : stroke} strokeWidth={selectedNode === node.id ? 2 : 1.3} filter="url(#rw-shadow)" />
        <text x={p.x} y={p.y - 2} textAnchor="middle" fill="#223654" fontSize="14" fontWeight="600">{node.name.length > 17 ? node.name.slice(0, 16) + "…" : node.name}</text>
        <text x={p.x} y={p.y + 17} textAnchor="middle" fill="#687f94" fontSize="10.5">{node.state !== "unknown" ? `Possible ${node.state === "mixed" ? "opposing effects" : node.state === "decreased" ? "decrease" : "increase"}` : node.kind.replaceAll("_", " / ")}</text>
      </g>;
    })}
  </svg>;
}
