import type { GLink, GNode } from "../graph3d/types";

const BASE = import.meta.env.VITE_API_BASE ?? "";

export interface Capabilities {
  parser_configured: boolean;
  synthesis_configured: boolean;
  review_manifest_version: string | null;
  context_id: string | null;
  review_issue: string | null;
  synthetic_demo_enabled: boolean;
  demo_query: string;
}

export interface Evidence {
  id: string;
  claim_id: string;
  publication_id: string | null;
  publication_url: string | null;
  quote: string | null;
  context_id: string;
  review_status: "approved" | "unreviewed";
}

interface PathResult {
  category: string;
  completion: string;
  total_paths: number;
  paths: Array<{ id: string; node_ids: string[]; claim_ids: string[]; evidence_ids: string[]; implied_direction: -1 | 1 }>;
}

export interface SimulationResponse {
  request_id: string;
  status: string;
  method: string;
  synthetic: boolean;
  snapshot: { id: string; checksum: string | null };
  nodes: GNode[];
  links: Array<GLink & {
    evidence_ids: string[];
    publication_ids: string[];
    belief_score: number | null;
    sources: Record<string, number>;
    source_class: "curated_database" | "machine_read" | "mixed" | "unknown";
    exclusion_reason: string | null;
  }>;
  evidence: Evidence[];
  analysis: {
    baseline: PathResult;
    after_exclusion: PathResult | null;
    exclusion_effect: string;
    boolean: {
      baseline: { completion: string };
      perturbed: { completion: string };
      flips: Array<{ variable_id: string; entity_id: string; before: number; after: number }>;
    } | null;
  } | null;
  evidence_assessment: {
    belief_coverage: number | null;
    weakest_belief: number | null;
    distinct_publication_count: number;
    curated_database_claims: number;
    machine_read_claims: number;
    multi_source_claims: number;
    limitations: string[];
  } | null;
  amass_corroboration: {
    status: string;
    mode: string;
    claims_assessed: number;
    calls_used: number;
    records_examined: number;
    from_cache: boolean;
    retrieved_at: string | null;
    review_policy: string;
    truncated: boolean;
    warnings: string[];
    corroborations: Array<{
      claim_id: string;
      status: string;
      cross_indexed_publication_ids: string[];
      additional_supporting_publication_ids: string[];
      opposing_publication_ids: string[];
      mention_only_publication_ids: string[];
      distinct_publication_families: number;
      distinct_primary_study_count: number;
      source_pipeline_classes: string[];
      limitations: string[];
      truncated: boolean;
      documents: Array<{ amass_id: string; pmid: string | null; doi: string | null; title: string | null;
        is_retracted: boolean | null; publication_types: string[]; journal: string | null }>;
      passages: Array<{ id: string; publication_id: string; quote: string; stance: string; context_match: string;
        evidence_role: string; review_status: string; location: string | null }>;
    }>;
  };
  synthesis_status: string;
  synthesis: {
    biological_rationale: Array<{ text: string; basis: string; claim_ids: string[]; evidence_ids: string[] }>;
    confidence_assessment: string;
    assumptions: string[];
    limitations: string[];
    validation_protocol: {
      experimental_system: string | null;
      hypothesis: string;
      competing_explanations: string[];
      perturbation: string;
      controls: string[];
      readouts: string[];
      procedure_outline: string[];
      discriminating_observations: string[];
      confounders: string[];
      parameters_to_optimize: string[];
    } | null;
  } | null;
  warnings: string[];
  errors: Array<{ stage: string; code: string; message: string }>;
  truncation: { search: boolean; evidence_bundle: boolean; display_paths_omitted: number };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(BASE + path, init);
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail?.message ?? JSON.stringify(body.detail ?? body));
  return body as T;
}

export const interventionApi = {
  capabilities: () => request<Capabilities>("/api/simulation-capabilities"),
  simulate: (body: { query: string; demo: boolean; method: string; context_id: string | null; boolean_model_id: string | null; exclude_publication_ids: string[]; snapshot_id?: string }) =>
    request<SimulationResponse>("/api/simulate-target", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
};
