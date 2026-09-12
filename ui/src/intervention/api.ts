import type { GLink, GNode } from "../graph3d/types";

const BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8077";

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
  links: Array<GLink & { evidence_ids: string[]; belief_score: number | null; exclusion_reason: string | null }>;
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
    limitations: string[];
  } | null;
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
  simulate: (body: { query: string; demo: boolean; method: string; context_id: string | null; boolean_model_id: string | null; exclude_publication_ids: string[] }) =>
    request<SimulationResponse>("/api/simulate-target", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
};
