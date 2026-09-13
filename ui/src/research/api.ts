export type Species = "all" | "human" | "mouse" | "rat";
export interface ResearchNode {
  id: string; name: string; description: string | null; kind: string;
  lane: number; state: "increased" | "decreased" | "mixed" | "unknown"; focus: boolean;
}
export interface ResearchLink {
  id: string; source: string; target: string; predicate: string; sign: 1 | -1;
  evidence_ids: string[]; publication_ids: string[]; source_class: string;
  review_status: string; belief: number | null;
}
export interface ResearchPath {
  id: string; node_ids: string[]; claim_ids: string[]; direction: 1 | -1;
  intervention: "increase" | "decrease" | "knockout" | "none";
  assessment: string; assumptions: string[];
}
export interface ResearchResult {
  query: string; status: string; parser: string;
  snapshot: { id: string; checksum: string | null };
  plan: { operation: string; source: string | null; target: string | null; perturbation: string; desired_direction: number | null };
  interpretation: string; answer: string; source_id: string | null; target_id: string | null;
  species: Species; nodes: ResearchNode[]; links: ResearchLink[]; paths: ResearchPath[];
  lanes: string[]; suggestions: string[]; limitations: string[];
  total_paths: number; paths_omitted: number; search_truncated: boolean; excluded_evidence_count: number;
}
export interface ResearchCapabilities {
  snapshot_id: string; entity_count: number; claim_count: number; publication_count: number;
  entities: Array<{ id: string; name: string; kind: string }>;
  language_parser_configured: boolean; research_draft_configured: boolean; compound_count: number;
}
const BASE = import.meta.env.VITE_API_BASE ?? "";
export async function researchRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(BASE + path, init);
  let body;
  try { body = await response.json(); }
  catch { throw new Error(`Research service returned ${response.status} without a JSON response. Check that the research backend is running.`); }
  if (!response.ok) throw new Error(body.detail?.message ?? (typeof body.detail === "string" ? body.detail : `Research service returned ${response.status}.`));
  return body as T;
}
export const researchApi = {
  capabilities: () => researchRequest<ResearchCapabilities>("/api/research/capabilities"),
  ask: (query: string, species: Species, signal: AbortSignal) => researchRequest<ResearchResult>("/api/research", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, species, max_paths: 8 }), signal,
  }),
};
