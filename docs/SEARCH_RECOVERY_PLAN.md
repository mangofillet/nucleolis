# Search diagnosis and recovery plan

Diagnosed against commit `2a06bad` and snapshot `demo_v4` (32 entities).

## Confirmed findings

1. **The previous local server was unavailable.** Local ports 8077, 8079, 8081 and
   5173 did not respond, including outside the execution sandbox. The previous server
   session no longer existed. A new server was started on 8079 and `/health` returned
   HTTP 200 with status `ok`. This establishes local availability, not which URL the
   user was using when the failure occurred.
2. **A recognized sentence can produce an invalid entity mention and bypass Nebius.**
   `parse_local()` accepts `What is the role of TREM2?` as an overview with source
   `the role of TREM2`. `interpret()` returns that local plan before validating entity
   grounding. `analyze()` cannot resolve the source, so it returns no paths. Nebius
   is configured but never receives that question.
3. **Alias handling is inconsistent.** Bare `tau` and `p62` are not recognized by the
   local parser, although `resolve()` has synonym mappings to MAPT and SQSTM1.
   Simple aliases unnecessarily depend on the optional provider. No live provider
   failure is asserted here; this was diagnosed without paid requests.
4. **This is not yet general information search.** `/api/research` answers graph
   questions over 32 entities. The optional language model interprets questions; it
   does not acquire a broader literature corpus. Disease names and information outside
   that graph need a separate retrieval route. Rewording cannot supply missing evidence.
5. **The browser request has no client deadline.** During a stalled fetch, the Explore
   button stays disabled. Cancelling a superseded query exists, but a hanging request
   has no timed recovery. This is a code-level risk, not a reproduced hanging request.
6. **Development ports can be mismatched.** Vite proxies to 8077 while the Windows
   research launcher defaults to 8079. Running those two commands together leaves
   the frontend pointing at the wrong port. This is a configuration mismatch risk;
   the user's failing URL has not been supplied.

## Reproduction evidence

The first three rows were checked through the live API on 8079. Additional rows
were checked directly against the same snapshot's local parser, without LLM calls.

| Query/check | Actual result |
|---|---|
| GET /health | HTTP 200, `ok` after restarting the server |
| What does GFAP activate? | HTTP 200, `completed`, 8 paths, local parser, about 0.01 seconds |
| What is the role of TREM2? | HTTP 200, `needs_clarification`, 0 paths, local parser; invalid mention `the role of TREM2` |
| What is TREM2? | `completed`, 8 paths |
| TREM2 | `completed`, 8 paths |
| tau / p62 | No local plan; routed to optional provider |
| Search for TREM2 | No local plan; routed to optional provider |
| What does TREM2 do? | No local plan; routed to optional provider |
| What happens to GFAP when TREM2 is inhibited? | No local plan; routed to optional provider |
| Tell me about the role of TREM2 in Alzheimer disease | Invalid entity mention; no paths |
| ALS / Alzheimer disease | Outside the current entity catalogue; no local plan |

## Immediate workaround

Use the single-server workspace at <http://127.0.0.1:8079/>. For a user-owned server
that remains available independently of an agent execution session, run from `nucleolus`
and keep that terminal open:

```powershell
./scripts/run_research.ps1 -Port 8079 -SkipBuild
```

If the server is already running on that port, open the existing app rather than
starting another instance. Use exact names or verified forms:

- `TREM2`, `MAPT` instead of `tau`, `SQSTM1` instead of `p62`.
- `What is TREM2?`
- `Show mechanism of TREM2`
- `What does GFAP activate?`
- `What happens to GFAP if I decrease TREM2?`

Use the all-species setting for initial connectivity checks; a specific species can
legitimately yield no eligible passages. This workaround restores the graph workflow.
It does not provide general literature search outside the snapshot.

## Fix order

### P0: Make supported searches reliable

1. Unify alias/mention resolution across bare-name search, local parsing and provider
   grounding. Recognize ordinary overview forms such as `role of`, `what does X do`
   and `search for X`, and passive perturbation forms while preserving source/readout roles.
2. Validate a local plan before treating interpretation as complete. Recover harmless
   wording deterministically first. A parser-produced invalid mention must not block
   optional interpretation. Preserve unresolved phenotypes, variants and multi-entity
   ambiguity; never substitute a gene for a distinct readout or drop a requested context.
3. Add a bounded browser request deadline, clear error/retry state and a way to replace
   a slow query. Distinguish unavailable service, unresolved wording and no evidence.
4. Make the development API target configurable and align documented startup commands.
   Verify readiness before declaring the app available.

### P1: Fulfil general information search

5. Route general gene/disease/topic requests to a separate cited literature retrieval
   operation rather than requiring every question to become a graph route. Return
   publication results with titles, abstracts or available passages, identifiers and links.
6. Use the local graph when the question and entities are supported. For topics outside
   the graph, show literature results and disclose the graph coverage gap. Retrieved
   articles must not automatically become reviewed graph edges.
7. Provide specific suggestions and selectable entity matches for ambiguous or unmatched
   input. Tell the user whether a result is a graph hypothesis or retrieved literature.

### Acceptance checks before declaring search fixed

- Exercise every ordinary wording and alias in the reproduction table through the UI
  and API with provider keys absent; supported graph queries must work deterministically.
- Test local-parse failure followed by optional provider success and provider timeout.
- Test unknown entities, ambiguous pairs and distinct readouts without silent substitution.
- Test backend unavailable, a genuinely stalled request, retry, and a newer query replacing
  an older one. Confirm the loading state always terminates or can be cancelled.
- Test both single-server and development-proxy startup paths.
- For general search, test a topic outside the 32 entities and verify real publication
  links and explicit retrieval errors/empty results. Test this separately from graph paths.

The earlier 214-test suite and browser smoke checks covered the implemented graph
examples and mocked provider contracts. They missed these common phrasings and did
not establish that the input bar met a general information-search expectation.

## Changes made during this diagnosis

Restarted the local API/UI server on 8079, verified health and the successful/failing
API reproductions, and wrote this plan. No parser or retrieval-code fix has been applied
yet, and no live provider request was made.
