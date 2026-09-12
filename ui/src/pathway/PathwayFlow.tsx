import { useMemo } from "react";
import type { PathwayLeg, PathwayNode, PathwayResponse, PathwayRoute } from "../api";

/**
 * Layered pathway flow: SOURCE -> ACTS THROUGH -> TARGET.
 *
 * Deliberately SVG and deliberately deterministic. A force layout puts nodes
 * wherever the simulation settles, which means position carries no information
 * and the picture differs on every load. Here the column *is* the meaning:
 * left is what you perturb, middle is what carries the effect, right is what
 * moves. Vertical order is evidence strength.
 *
 * Encoding:
 *   thickness  distinct supporting papers behind the leg (log-scaled)
 *   colour     direction where the evidence agrees; amber where it does not
 *   dashed     no direction asserted (contested, or an unsigned relation)
 */

export const FLOW = {
  bg: "#0b0c0e",
  ink: "#e9e7e3",
  muted: "#82868d",
  faint: "#2a2d33",
  increase: "#5fb49c",
  decrease: "#c97f66",
  contested: "#d9a441",
  unsigned: "#6b7480",
  source: "#f0ede8",
  intermediate: "#dd8b5c",
  target: "#e0b33c",
};

export function legColor(leg: PathwayLeg): string {
  if (leg.sign_basis === "contested") return FLOW.contested;
  if (leg.sign === 1) return FLOW.increase;
  if (leg.sign === -1) return FLOW.decrease;
  return FLOW.unsigned;
}

const PAD_TOP = 54;
const BOTTOM = 26;
// Intermediates carry a second line ("connects to 59,487"), so they need more
// vertical room than a single-line node. One row height for all three columns
// made the middle column collide with itself.
const ROW_BY_LAYER = [32, 48, 30];

export interface Layout {
  width: number;
  height: number;
  pos: Map<string, { x: number; y: number }>;
  columns: { x: number; label: string; anchor: "start" | "middle" | "end" }[];
}

export function layoutPathways(data: PathwayResponse | null, width: number): Layout {
  const pos = new Map<string, { x: number; y: number }>();
  const columns = [
    { x: width * 0.11, label: "COMPOUND / SOURCE", anchor: "start" as const },
    { x: width * 0.5, label: "ACTS THROUGH", anchor: "middle" as const },
    { x: width * 0.84, label: "TARGET", anchor: "end" as const },
  ];
  if (!data) return { width, height: 200, pos, columns };

  const byLayer: PathwayNode[][] = [[], [], []];
  for (const node of data.nodes) byLayer[node.layer].push(node);

  // The tallest column in pixels, not in node count, sets the canvas height.
  const columnSpans = byLayer.map((c, layer) => c.length * ROW_BY_LAYER[layer]);
  const tallestSpan = Math.max(...columnSpans, ROW_BY_LAYER[0]);
  const height = PAD_TOP + tallestSpan + BOTTOM;

  byLayer.forEach((column, layer) => {
    const row = ROW_BY_LAYER[layer];
    const span = column.length * row;
    const start = PAD_TOP + (tallestSpan - span) / 2 + row / 2;
    column.forEach((node, index) => {
      pos.set(node.id, { x: columns[layer].x, y: start + index * row });
    });
  });

  return { width, height, pos, columns };
}

/** Horizontal cubic bezier, flattening as the vertical gap closes. */
export function legPath(
  a: { x: number; y: number },
  b: { x: number; y: number },
): string {
  const dx = Math.abs(b.x - a.x);
  const c = Math.max(dx * 0.42, 30);
  return `M ${a.x} ${a.y} C ${a.x + c} ${a.y}, ${b.x - c} ${b.y}, ${b.x} ${b.y}`;
}

export function legWidth(papers: number, emphasised: boolean): number {
  const base = 0.9 + Math.log10(1 + papers) * 2.1;
  return emphasised ? base + 1.6 : base;
}

interface Props {
  data: PathwayResponse | null;
  width: number;
  /** claim ids on the highlighted route, or null for "show everything" */
  activeRoute: PathwayRoute | null;
  hoverLeg: string | null;
  selectedLegKey: string | null;
  onLegClick: (leg: PathwayLeg) => void;
  onLegHover: (key: string | null) => void;
  onNodeClick: (id: string) => void;
}

export const legKey = (leg: PathwayLeg) => leg.from + "->" + leg.to;

export default function PathwayFlow({
  data,
  width,
  activeRoute,
  hoverLeg,
  selectedLegKey,
  onLegClick,
  onLegHover,
  onNodeClick,
}: Props) {
  const layout = useMemo(() => layoutPathways(data, width), [data, width]);

  if (!data) return null;

  const routeNodes = activeRoute ? new Set(activeRoute.nodes) : null;
  const routeLegs = activeRoute
    ? new Set(activeRoute.legs.map((l) => legKey(l)))
    : null;

  const nodeFill = (node: PathwayNode) =>
    node.layer === 0 ? FLOW.source : node.layer === 1 ? FLOW.intermediate : FLOW.target;

  return (
    <svg
      className="flow-svg"
      width={width}
      height={layout.height}
      viewBox={`0 0 ${width} ${layout.height}`}
      role="img"
      aria-label="Pathway flow from source through intermediates to targets"
    >
      {/* column headers */}
      {layout.columns.map((column) => (
        <text
          key={column.label}
          x={column.x}
          y={26}
          className="flow-colhead"
          textAnchor={column.anchor}
        >
          {column.label}
        </text>
      ))}
      <line x1={16} y1={38} x2={width - 16} y2={38} stroke={FLOW.faint} />

      {/* legs, drawn under the nodes */}
      <g>
        {data.legs.map((leg) => {
          const a = layout.pos.get(leg.from);
          const b = layout.pos.get(leg.to);
          if (!a || !b) return null;
          const key = legKey(leg);
          const onRoute = routeLegs ? routeLegs.has(key) : true;
          const emphasised = key === hoverLeg || key === selectedLegKey;
          const dim = (routeLegs && !onRoute) || (selectedLegKey && !emphasised);
          const d = legPath(a, b);
          const tip = `${leg.from.split(":")[1]} → ${leg.to.split(":")[1]} · ${leg.papers} papers · ${leg.sign_basis}`;
          return (
            <g key={key}>
              {/* The drawn line is only a few pixels wide, and a perfectly
                  horizontal one has no vertical extent at all. This invisible
                  wider path is what the pointer actually hits. */}
              <path
                d={d}
                fill="none"
                stroke="transparent"
                strokeWidth={16}
                strokeLinecap="round"
                className="flow-hit"
                onMouseEnter={() => onLegHover(key)}
                onMouseLeave={() => onLegHover(null)}
                onClick={() => onLegClick(leg)}
              >
                <title>{tip}</title>
              </path>
              <path
                d={d}
                fill="none"
                stroke={legColor(leg)}
                strokeWidth={legWidth(leg.papers, emphasised)}
                strokeOpacity={dim ? 0.12 : emphasised ? 0.95 : 0.62}
                strokeLinecap="round"
                strokeDasharray={leg.sign === null ? "7 5" : undefined}
                className="flow-leg"
                pointerEvents="none"
              />
            </g>
          );
        })}
      </g>

      {/* nodes */}
      <g>
        {data.nodes.map((node) => {
          const p = layout.pos.get(node.id);
          if (!p) return null;
          const dim = routeNodes ? !routeNodes.has(node.id) : false;
          return (
            <g
              key={node.id}
              className="flow-node"
              opacity={dim ? 0.22 : 1}
              onClick={() => onNodeClick(node.id)}
            >
              <circle
                cx={p.x}
                cy={p.y}
                r={node.layer === 0 ? 6.5 : 5}
                fill={nodeFill(node)}
                stroke={FLOW.bg}
                strokeWidth={2}
              />
              <text
                x={p.x + 12}
                y={p.y + (node.layer === 1 ? 0 : 4)}
                className={node.layer === 0 ? "flow-label flow-label--source" : "flow-label"}
                textAnchor="start"
                paintOrder="stroke"
                stroke={FLOW.bg}
                strokeWidth={3.5}
                strokeLinejoin="round"
              >
                {node.name}
              </text>
              {/* The specificity penalty, made visible: a node everything routes
                  through discriminates nothing. */}
              {node.layer === 1 && (
                <text
                  x={p.x + 12}
                  y={p.y + 13}
                  className="flow-sub"
                  paintOrder="stroke"
                  stroke={FLOW.bg}
                  strokeWidth={3}
                  strokeLinejoin="round"
                >
                  connects to {node.degree.toLocaleString()}
                </text>
              )}
            </g>
          );
        })}
      </g>
    </svg>
  );
}
