# Research workspace implementation

- [x] Trace why natural questions fail in the entity browser and intervention endpoint.
- [x] Inspect the existing APIs, rendering code, evidence fields, and working-tree changes.
- [x] Implement a typed research-query endpoint with key-free common queries and optional Nebius interpretation.
- [x] Return bounded mechanisms, directional hypotheses, upstream intervention candidates, and explicit missing-data results.
- [x] Build the light research workspace, layered canvas, evidence panel, and connected actions.
- [x] Integrate optional cited Claude research drafts using the existing simulation service.
- [x] Test query semantics, graph integrity, failures, and UI build.
- [x] Check the running application and document startup, supported queries, and remaining scientific scope.

The reference's biological compartments require sourced annotations. Initial lanes describe graph roles and distances explicitly. Existing raw evidence may support exploratory hypotheses but is never promoted to reviewed simulation evidence by this workspace.

Verified 2026-09-13: 214 backend tests passed; TypeScript/Vite build passed; the running
workspace passed browser checks for queries, evidence, missing data, exports, draft
citations outside the displayed graph, mobile layout, service failure and retry.
The verified application is at http://127.0.0.1:8081/ while its server remains running.

Implementation, startup, supported queries, limits and verification details:
[Research workspace guide](RESEARCH_WORKSPACE.md).

Provider integrations were verified with mocked transports and a labelled UI draft
fixture. No paid provider call was made in this verification; live provider availability
and biological validity are not implied by checklist completion. Screenshots and the
machine-readable browser check report are in `nucleolus/data/verification/`.
