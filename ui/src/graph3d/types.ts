/**
 * Node-Link JSON contract for the 3D view.
 *
 * Deliberately source-agnostic: nucleolus `/graph` is adapted into this shape,
 * and amass-graph's `graph_data.json` maps onto the same fields. Nothing in the
 * renderer knows which produced it.
 *
 * Two rules carried from HANDOVER.md s4 that the visual encoding must respect:
 *   - Support and dispute are NEVER netted. An edge asserted 400 times and
 *     denied 480 times is contested, not negative.
 *   - Thickness = attention (how much has been said).
 *     Colour = agreement (how much of it agrees).
 */

export interface GNode {
  id: string;
  name: string;
  /** free-form; drives node colour. e.g. gene_protein, chemical, process */
  kind?: string;
  /** true for the node the camera is centred on */
  focus?: boolean;
  /** graph degree, used for size and for the hub warning */
  degree?: number;
  /** Qualitative intervention result; absent in the existing evidence browser. */
  state?: "increased" | "decreased" | "conflicting" | "unknown" | "on" | "off" | "unchanged" | "not_modeled";
  state_kind?: "directional" | "boolean";
  baseline_state?: 0 | 1 | null;
  perturbed_state?: 0 | 1 | null;
  /** anything else to show in the drawer */
  meta?: Record<string, unknown>;
}

export interface GLink {
  source: string;
  target: string;
  /** stable id of the underlying claim */
  id: string;
  predicate: string;
  /** +1 activating, -1 inhibiting, null for binding/modification */
  sign: 1 | -1 | null;
  /** distinct supporting publications - drives thickness */
  papers: number;
  /** extracted sentences; papers vs sentences is the inflation signal */
  sentences?: number | null;
  /** primary studies among the papers */
  primary?: number | null;
  /** retracted papers among the supporting set */
  retracted?: number;
  /** every supporting paper withdrawn */
  soleSupportRetracted?: boolean;
  /** INDRA belief where available */
  belief?: number | null;
  eligible?: boolean;
  earliestDate?: string | null;
  /** claims in the opposite direction between the same ordered pair */
  opposing?: { pos: number; neg: number } | null;
}

export interface GraphData {
  nodes: GNode[];
  links: GLink[];
  meta?: {
    snapshotId?: string;
    truncated?: boolean;
    truncationNote?: string;
  };
}

/** Agreement ratio in [0,1]: 1 = undisputed, 0.5 = evenly contested. */
export function agreement(link: GLink): number | null {
  if (!link.opposing) return null;
  const { pos, neg } = link.opposing;
  const total = pos + neg;
  if (total === 0) return null;
  return Math.max(pos, neg) / total;
}

export function isContested(link: GLink): boolean {
  const value = agreement(link);
  return value !== null && value < 0.999;
}
