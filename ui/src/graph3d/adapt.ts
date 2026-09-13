/**
 * Adapts a nucleolis `/graph` response into the source-agnostic Node-Link
 * contract the 3D renderer consumes.
 *
 * Kept separate from the renderer on purpose: amass-graph's `graph_data.json`
 * gets its own adapter here and the visual layer does not change.
 */
import type { GraphResponse } from "../api";
import type { GLink, GNode, GraphData } from "./types";

export function fromNucleolis(graph: GraphResponse): GraphData {
  // Opposing claims between the same ordered pair, counted in papers.
  // Never netted - the pair is carried through so the renderer can show both.
  const byPair = new Map<string, { pos: number; neg: number }>();
  for (const edge of graph.edges) {
    if (edge.effect_sign === null) continue;
    const key = edge.subject.id + "->" + edge.object.id;
    const entry = byPair.get(key) ?? { pos: 0, neg: 0 };
    if (edge.effect_sign === 1) entry.pos += edge.support_count;
    else entry.neg += edge.support_count;
    byPair.set(key, entry);
  }

  const degree = new Map<string, number>();
  for (const edge of graph.edges) {
    degree.set(edge.subject.id, (degree.get(edge.subject.id) ?? 0) + 1);
    degree.set(edge.object.id, (degree.get(edge.object.id) ?? 0) + 1);
  }

  const nodes: GNode[] = graph.nodes.map((node) => ({
    id: node.id,
    name: node.name ?? node.id,
    kind: node.entity_type ?? undefined,
    focus: node.is_center,
    degree: degree.get(node.id) ?? 0,
    meta: {
      identifier: node.id,
      description: node.long_name,
      taxon: node.taxon_id,
    },
  }));

  const links: GLink[] = graph.edges.map((edge) => {
    const key = edge.subject.id + "->" + edge.object.id;
    const pair = byPair.get(key);
    // Only a signed claim can be contested. A `binds` claim between the same
    // pair must not inherit the disagreement of the signed claims beside it -
    // it asserts no direction to disagree about.
    const contested =
      edge.effect_sign !== null && pair && pair.pos > 0 && pair.neg > 0 ? pair : null;
    return {
      id: edge.claim_id,
      source: edge.subject.id,
      target: edge.object.id,
      predicate: edge.predicate,
      sign: edge.effect_sign,
      papers: edge.n_papers ?? edge.support_count,
      sentences: edge.n_sentences ?? null,
      primary: edge.n_primary ?? null,
      retracted: edge.n_retracted ?? 0,
      soleSupportRetracted: edge.sole_support_retracted ?? false,
      earliestDate: edge.earliest_publication_date ?? null,
      opposing: contested,
    };
  });

  // Say which limit actually bit. "Truncated at 500 edges" when the node cap
  // was the binding constraint is a misleading message.
  const reasons: string[] = [];
  if (graph.truncation.nodes_truncated) {
    reasons.push(`node budget (${nodes.length} shown)`);
  }
  if (graph.truncation.edges_truncated) {
    reasons.push(`edge ceiling (${graph.truncation.hard_max_edges})`);
  }

  return {
    nodes,
    links,
    meta: {
      snapshotId: graph.snapshot_id,
      truncated: reasons.length > 0,
      truncationNote: reasons.length
        ? `View limited by ${reasons.join(" and ")}. Absence here is not evidence of absence.`
        : undefined,
    },
  };
}
