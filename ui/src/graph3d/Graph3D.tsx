import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph3D, { type ForceGraphMethods } from "react-force-graph-3d";
import * as THREE from "three";
import SpriteText from "three-spritetext";
import { agreement, isContested, type GLink, type GNode, type GraphData } from "./types";

/**
 * Cinematic 3D knowledge graph.
 *
 * Visual encoding, from HANDOVER.md s4:
 *   thickness = attention (distinct supporting papers)
 *   colour    = agreement (contested edges go amber, never "averaged" to neutral)
 * A claim whose only support has been retracted is drawn dashed and red, and
 * says so - it is never quietly removed.
 *
 * Level of detail is camera-distance driven: far out you see topology only;
 * as the camera closes on a node its label and metrics fade in.
 */

const COLOR = {
  bg: "#07090d",
  activate: "#34d399",
  inhibit: "#f87171",
  neutral: "#64748b",
  contested: "#fbbf24",
  retracted: "#ef4444",
  focus: "#e8edf5",
  node: "#7dd3fc",
  hub: "#c4b5fd",
};

const STATE_COLOR: Record<string, string> = {
  increased: "#34d399", on: "#34d399", decreased: "#f87171", off: "#f87171",
  conflicting: "#fbbf24", unknown: "#64748b", not_modeled: "#475569", unchanged: "#7dd3fc",
};

/** Level of detail is measured relative to the fitted framing distance, so the
 *  macro/micro transition behaves the same for a 6-node and a 40-node graph. */
const LOD_FAR = 1.0;   // at the fitted distance: pure topology
const LOD_NEAR = 0.42; // this fraction of it: full detail

export interface Graph3DProps {
  data: GraphData;
  selectedLinkId: string | null;
  onSelectLink: (id: string) => void;
  onSelectNode: (id: string) => void;
  /** node id to fly the camera to; changing this triggers the animation */
  flyTo?: string | null;
}

export default function Graph3D({
  data,
  selectedLinkId,
  onSelectLink,
  onSelectNode,
  flyTo,
}: Graph3DProps) {
  const fgRef = useRef<ForceGraphMethods<GNode, GLink> | undefined>(undefined);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 800, height: 600 });
  const [detail, setDetail] = useState(0); // 0 = macro, 1 = micro
  const detailRef = useRef(0);
  const baseDistanceRef = useRef<number | null>(null);
  const flyPendingRef = useRef(false);

  // -- responsive canvas --------------------------------------------------
  useEffect(() => {
    const element = wrapRef.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const box = entries[0].contentRect;
      setSize({ width: Math.max(320, box.width), height: Math.max(320, box.height) });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // -- level of detail, driven by camera distance --------------------------
  useEffect(() => {
    let frame = 0;
    const tick = () => {
      const graph = fgRef.current;
      const base = baseDistanceRef.current;
      if (graph && base) {
        const distance = graph.camera().position.length();
        const far = base * LOD_FAR;
        const near = base * LOD_NEAR;
        const raw = (far - distance) / (far - near);
        const next = Math.min(1, Math.max(0, raw));
        // Only re-render on a meaningful change; this runs every frame.
        if (Math.abs(next - detailRef.current) > 0.06) {
          detailRef.current = next;
          setDetail(next);
        }
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);

  // -- fly-to animation ----------------------------------------------------
  useEffect(() => {
    if (!flyTo) return;
    const graph = fgRef.current;
    if (!graph) return;
    const node = data.nodes.find((n) => n.id === flyTo) as
      | (GNode & { x?: number; y?: number; z?: number })
      | undefined;
    if (!node || node.x === undefined) return;

    // Approach on a dynamic angle rather than straight down an axis, so the
    // depth of the graph stays legible during and after the move.
    const distance = 150;
    const length = Math.hypot(node.x ?? 0, node.y ?? 0, node.z ?? 0) || 1;
    const ratio = 1 + distance / length;
    flyPendingRef.current = true;
    graph.cameraPosition(
      {
        x: (node.x ?? 0) * ratio,
        y: (node.y ?? 0) * ratio + 40,
        z: (node.z ?? 0) * ratio + 60,
      },
      { x: node.x ?? 0, y: node.y ?? 0, z: node.z ?? 0 },
      1400,
    );
  }, [flyTo, data.nodes]);

  // -- encoding ------------------------------------------------------------
  const linkColor = useCallback(
    (link: GLink) => {
      if (link.soleSupportRetracted) return COLOR.retracted;
      if (isContested(link)) {
        const value = agreement(link) ?? 1;
        // Evenly split reads as full amber; lopsided fades toward its sign colour.
        const mix = Math.min(1, (1 - value) * 2.2);
        const base = link.sign === 1 ? COLOR.activate : link.sign === -1 ? COLOR.inhibit : COLOR.neutral;
        return mix > 0.55 ? COLOR.contested : base;
      }
      if (link.sign === 1) return COLOR.activate;
      if (link.sign === -1) return COLOR.inhibit;
      return COLOR.neutral;
    },
    [],
  );

  const linkWidth = useCallback(
    (link: GLink) => {
      const base = Math.min(0.4 + Math.log10(1 + link.papers) * 1.5, 4.5);
      return link.id === selectedLinkId ? base + 2.2 : base;
    },
    [selectedLinkId],
  );

  const linkOpacity = selectedLinkId ? 0.22 : 0.42;

  const nodeObject = useCallback(
    (node: GNode) => {
      const group = new THREE.Group();
      const isFocus = !!node.focus;
      const stateColor = node.state ? STATE_COLOR[node.state] : undefined;
      const radius = isFocus ? 6.5 : 3.4 + Math.min(Math.log10(1 + (node.degree ?? 1)) * 2.2, 4);

      const core = new THREE.Mesh(
        new THREE.SphereGeometry(radius, 18, 18),
        new THREE.MeshBasicMaterial({
          color: stateColor ?? (isFocus ? COLOR.focus : (node.degree ?? 0) > 60 ? COLOR.hub : COLOR.node),
        }),
      );
      group.add(core);

      // Glow: an additive, back-side sphere reads as light bloom without a
      // post-processing pass, which keeps this cheap at 40+ nodes.
      const glow = new THREE.Mesh(
        new THREE.SphereGeometry(radius * 2.4, 18, 18),
        new THREE.MeshBasicMaterial({
          color: stateColor ?? (isFocus ? COLOR.focus : COLOR.node),
          transparent: true,
          opacity: isFocus ? 0.22 : 0.1,
          side: THREE.BackSide,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        }),
      );
      group.add(glow);

      // Micro view: label and metrics fade in as the camera closes.
      if (detail > 0.05 || isFocus) {
        const label = new SpriteText(node.name);
        label.color = "#e6ecf5";
        label.textHeight = isFocus ? 7 : 5.2;
        label.position.set(0, radius + 6, 0);
        label.material.opacity = isFocus ? 1 : detail;
        label.material.transparent = true;
        group.add(label);

        if (detail > 0.55 && node.degree !== undefined) {
          const sub = new SpriteText(`${node.degree} claims`);
          sub.color = "#7f8da3";
          sub.textHeight = 3.1;
          sub.position.set(0, radius + 1.2, 0);
          sub.material.opacity = (detail - 0.55) / 0.45;
          sub.material.transparent = true;
          group.add(sub);
        }
      }
      return group;
    },
    [detail],
  );

  const linkLabel = useCallback((link: GLink) => {
    const parts = [`<b>${link.predicate}</b>`, `${link.papers} papers`];
    if (link.sentences) parts.push(`${link.sentences} sentences`);
    if (link.opposing) parts.push(`${link.opposing.pos}↑ / ${link.opposing.neg}↓`);
    if (link.soleSupportRetracted) parts.push('<span style="color:#ef4444">sole support retracted</span>');
    return `<div style="background:#0d1117;border:1px solid #263043;border-radius:6px;padding:6px 9px;font:12px system-ui;color:#dce3ee">${parts.join(" · ")}</div>`;
  }, []);

  // A new graph needs a new framing reference.
  useEffect(() => {
    baseDistanceRef.current = null;
    flyPendingRef.current = false;
  }, [data]);

  // react-force-graph mutates the objects it is given; hand it a fresh copy.
  const graphData = useMemo(
    () => ({
      nodes: data.nodes.map((n) => ({ ...n })),
      links: data.links.map((l) => ({ ...l })),
    }),
    [data],
  );

  return (
    <div ref={wrapRef} className="g3d-wrap">
      <ForceGraph3D
        ref={fgRef}
        width={size.width}
        height={size.height}
        graphData={graphData}
        backgroundColor={COLOR.bg}
        showNavInfo={false}
        nodeThreeObject={nodeObject}
        nodeLabel={(n: GNode) => n.name}
        onNodeClick={(n: GNode) => onSelectNode(n.id)}
        linkColor={linkColor}
        linkWidth={linkWidth}
        linkOpacity={linkOpacity}
        linkDirectionalArrowLength={3.2}
        linkDirectionalArrowRelPos={0.92}
        linkDirectionalArrowColor={linkColor}
        linkDirectionalParticles={(l: GLink) => (l.id === selectedLinkId ? 4 : 0)}
        linkDirectionalParticleWidth={2.2}
        linkDirectionalParticleSpeed={0.006}
        linkCurvature={0.18}
        linkLabel={linkLabel}
        onLinkClick={(l: GLink) => onSelectLink(l.id)}
        cooldownTicks={120}
        warmupTicks={24}
        onEngineStop={() => {
          const graph = fgRef.current;
          if (!graph) return;
          // Frame the whole graph once the layout settles, and take that
          // distance as the reference the LOD ramp is measured against.
          if (!flyPendingRef.current) graph.zoomToFit(900, 70);
          window.setTimeout(() => {
            const current = fgRef.current;
            if (current && baseDistanceRef.current === null) {
              baseDistanceRef.current = current.camera().position.length();
            }
          }, 1000);
        }}
        enableNodeDrag={false}
      />
      <div className="g3d-lod" aria-hidden>
        {detail < 0.3 ? "macro — topology" : detail < 0.7 ? "approaching" : "micro — detail"}
      </div>
    </div>
  );
}
