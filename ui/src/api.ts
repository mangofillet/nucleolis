const BASE = import.meta.env.VITE_API_BASE ?? "";

export interface EntityRef {
  id: string;
  name: string | null;
}

export interface ClaimView {
  claim_id: string;
  subject: EntityRef;
  predicate: string;
  object: EntityRef;
  effect_sign: 1 | -1 | null;
  causal: boolean;
  negated: boolean;
  epistemic_status: string;
  context_id: string;
  support_count: number;
  n_papers: number;
  n_primary: number | null;
  n_retracted: number;
  n_sentences: number | null;
  sole_support_retracted: boolean;
  earliest_publication_date: string | null;
  evidence_count: number;
  evidence_ids: string[];
  source_statement_hash: string | null;
  source_counts: Record<string, number> | null;
  source_class: "curated_database" | "machine_read" | "mixed" | "unknown";
  source_class_label: string;
  curated_sources: string[];
  indra_statement_type: string | null;
}

export interface GraphNode {
  id: string;
  name: string | null;
  long_name: string | null;
  entity_type: string | null;
  taxon_id: number | null;
  is_center: boolean;
}

export interface GraphResponse {
  snapshot_id: string;
  center: string;
  filters: Record<string, unknown>;
  nodes: GraphNode[];
  edges: ClaimView[];
  truncation: {
    nodes_truncated: boolean;
    edges_truncated: boolean;
    hard_max_nodes: number;
    hard_max_edges: number;
  };
}

export interface DocumentRow {
  id: string;
  pmid: string | null;
  pmcid: string | null;
  doi: string | null;
  publication_date: string | null;
  date_precision: string;
  retraction_status: string;
  publication_type?: string | null;
  publication_types?: string[];
  is_primary?: boolean | null;
  journal?: string | null;
}

export interface EvidenceItem {
  evidence_id: string;
  quote: string | null;
  negated: boolean;
  experimental_basis: string;
  source_evidence_code: string | null;
  review_status: string;
  context: Record<string, unknown> | null;
  document: DocumentRow | null;
  link: string | null;
  provenance: Array<Record<string, unknown>>;
}

export interface EvidenceResponse {
  snapshot_id: string;
  claim: ClaimView;
  total: number;
  offset: number;
  limit: number;
  evidence: EvidenceItem[];
}

export interface SearchResult {
  id: string;
  preferred_name: string | null;
  long_name: string | null;
  entity_type: string | null;
  degree: number;
}

export interface PathStep {
  from: string;
  to: string;
  from_name: string | null;
  to_name: string | null;
  claims: ClaimView[];
}

export interface PathResponse {
  snapshot_id: string;
  source_id: string;
  target_id: string;
  mode: string;
  filters: Record<string, unknown>;
  paths: Array<{ nodes: string[]; hops: number; steps: PathStep[] }>;
  truncation: { paths_truncated: boolean; note: string };
}

export interface PathwayNode {
  id: string;
  name: string;
  long_name: string | null;
  layer: 0 | 1 | 2;
  degree: number;
  specificity: number;
}

export interface PathwayLeg {
  from: string;
  to: string;
  claims: ClaimView[];
  papers: number;
  sign: 1 | -1 | null;
  sign_basis: "undisputed" | "dominant" | "contested" | "unsigned";
  contested: { pos: number; neg: number } | null;
}

export interface PathwayRoute {
  target_id: string;
  hops: number;
  nodes: string[];
  legs: PathwayLeg[];
  weakest_leg_papers: number;
  specificity: number;
  score: number;
  implied_direction: 1 | -1 | null;
  direction_basis: string;
}

export interface PathwayResponse {
  snapshot_id: string;
  source: { id: string; name: string | null; degree: number };
  filters: Record<string, unknown>;
  layers: string[];
  nodes: PathwayNode[];
  legs: PathwayLeg[];
  routes: PathwayRoute[];
  truncation: {
    candidates_truncated: boolean;
    targets_truncated: boolean;
    candidate_budget: number;
    note: string;
  };
}

export interface Health {
  status: string;
  snapshot_ready: boolean;
  detail?: string;
  snapshot?: { id: string; created_at: string; checksum: string; schema_version: number };
  coverage?: Record<string, number>;
  limitations?: string[];
  license_note?: string;
  capabilities?: Record<string, unknown>;
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(BASE + path);
  if (!response.ok) {
    let detail: unknown = response.statusText;
    try {
      detail = (await response.json()).detail;
    } catch {
      /* keep statusText */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => get<Health>("/health"),
  search: (q: string) =>
    get<{ results: SearchResult[] }>(`/nodes/search?q=${encodeURIComponent(q)}`),
  graph: (nodeId: string, opts: { maxNodes: number; causalOnly: boolean; minSupport: number; edgeScope: "incident" | "all" }) =>
    get<GraphResponse>(
      `/graph?node_id=${encodeURIComponent(nodeId)}&max_nodes=${opts.maxNodes}` +
        `&causal_only=${opts.causalOnly}&min_support=${opts.minSupport}&edge_scope=${opts.edgeScope}`,
    ),
  path: (sourceId: string, targetId: string, causalOnly: boolean) =>
    get<PathResponse>(
      `/path?source_id=${encodeURIComponent(sourceId)}&target_id=${encodeURIComponent(targetId)}` +
        `&causal_only=${causalOnly}`,
    ),
  pathways: (sourceId: string, opts: { maxTargets: number; minPapers: number; targetId?: string | null }) =>
    get<PathwayResponse>(
      `/pathways?source_id=${encodeURIComponent(sourceId)}&max_targets=${opts.maxTargets}` +
        `&min_papers=${opts.minPapers}` +
        (opts.targetId ? `&target_id=${encodeURIComponent(opts.targetId)}` : ""),
    ),
  evidence: (claimId: string, offset = 0) =>
    get<EvidenceResponse>(`/edges/${encodeURIComponent(claimId)}/evidence?limit=100&offset=${offset}`),
  exportUrl: (nodeId: string, maxNodes: number) =>
    `${BASE}/exports/graph?node_id=${encodeURIComponent(nodeId)}&max_nodes=${maxNodes}`,
};
