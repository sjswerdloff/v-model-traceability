# DDD Integration Plan for V-Model Traceability

**Authors:** connor-227743e6, cora-2f1e43dc, cyril-9137f1ee

**Status:** Approved by Stuart 2026-05-15. Three-way consensus (Connor, Cora,
Cyril). Implementation underway.

**Date:** 2026-05-15

---

## 1. Motivation: Closing the IEC 62304 5.3 Gap

The V-model traceability framework currently has clean coverage of:

- **Requirements** (IEC 62304 5.2) — `requirements.csv`
- **Detailed design** (5.4) — `design_contracts.csv`
- **Test cases** (5.5, 5.7) — `test_cases.csv`
- **Validation results** (5.8) — `validation_results.csv`

It does **not** have a first-class artifact at **5.3 (Software Architectural
Design)**: identification of software items, decomposition, inter-item
interfaces, and segregation rationale. We have implicitly conflated 5.3 with 5.4
by treating modules-as-implementations as the architectural decomposition.

**Domain-Driven Design provides the missing 5.3 layer.** A **Bounded Context**
_is_ a software architectural item in IEC 62304 terms. A **Context Map** _is_
the inter-item interface specification 5.3 requires. **Ubiquitous Language** is
the segregation rationale (naming consistency within an item, explicit
translation at boundaries).

**Lead with regulatory value, implement with DDD.** The plan below treats DDD
terminology (bounded context, ubiquitous language, context map) as the
implementation choice; the justification for an auditor or reviewer is 5.3 gap
closure.

### 1.1 Validating Cases

**Internal: python-tesseron.** Cyril conflated "gateway" and "app SDK" as the
same concept during development because no glossary enforced the distinction.
This is **context contamination** — exactly the failure mode described in the
source article. The framework didn't catch it because there was no node type
holding the canonical names.

**Medical software: OpenTPS / OnkoDICOM.** Terms like `beam`, `plan`,
`structure`, `dose` mean materially different things in different bounded
contexts:

- _Treatment Planning BC_: `beam` = irradiation field with energy, MUs, geometry
- _DICOM Storage BC_: `beam` = SOP instance with serialized geometry
- _Clinical Workflow BC_: `plan` = **approval-bearing artifact under physician
  sign-off**

The clinical workflow conflation is the strongest patient-safety case. An AI
agent that treats `plan` as "a data structure to be transformed" when it is
actually "an artifact requiring physician authorization before any
patient-affecting action" can generate code that bypasses the authorization
invariant entirely. Type checks pass; clinical correctness fails silently. This
is the failure mode that produces incidents that reach the NY Times.

Without per-BC glossaries with explicit canonical names and `aliases_to_avoid`,
AI-assisted code generation against these codebases conflates concepts in ways
that survive type checks and fail at clinical correctness. This is patient
safety risk under IEC 62304.

---

## 2. Two-Layer Approach

### 2.1 Workflow Layer (human + AI authorship)

DDD artifacts emerge from a **human-AI collaboration cycle**, not from upfront
documentation:

1. **Humans write epics and user stories** as plain markdown, alongside the CSV
   traceability chain
2. **AI extracts candidate DDD artifacts** from stories (proposed bounded
   contexts, domain term candidates, aliases-to-avoid suggestions)
3. **Humans curate the proposals** — corrections, rejections, refinements
4. **Human corrections themselves become domain knowledge** — when a clinician
   says "no, _dose_ here means _prescribed dose_, not _absorbed dose_," that
   correction is a `domain_terms.csv` row

The friction of correction is the value, not a bug. The output of the workflow
is artifacts that have been **filtered through human expert judgment**, not
AI-generated drafts assumed correct.

Artifacts **grow iteratively per sprint**. They are a living record, not a gate
before building.

### 2.2 Schema Layer (graph traceability)

DDD artifacts land as CSV node and edge types alongside the existing chain,
queryable via the same `build_graph.py` + Kuzu infrastructure. Detailed schema
in §3.

---

## 3. Schema Additions — Phased Rollout

### Phase 1: Foundation (immediate)

**New node types:**

`schemas/nodes/bounded_context.csvschema`:

```
id, name, purpose, classification, domain_type, status, approved_by, approval_date
```

- `classification`: Core / Supporting / Generic (DDD strategic classification)
- `domain_type`: revenue-generator / safety-critical / etc.
- Other fields match existing node convention.

`schemas/nodes/domain_term.csvschema`:

```
id, term, definition, bounded_context, related_terms, aliases_to_avoid, status, approved_by, approval_date
```

- `term`: canonical name (PascalCase or domain-appropriate)
- `bounded_context`: FK to `bounded_context.id`
- `aliases_to_avoid`: pipe-separated list of forbidden synonyms — the
  contractual element

**New edge types:**

`schemas/edges/context_map.csvschema`:

```
from_bc, to_bc, pattern, channel, direction, rationale
```

- `pattern`: Customer-Supplier / Conformist / ACL / Open-Host-Service /
  Published-Language / Shared-Kernel / Separate-Ways
- `direction`: upstream / downstream relationship

`schemas/edges/defined_in.csvschema`:

```
from_term, to_bc
```

- Generated automatically from `domain_term.bounded_context` column at graph
  build time (no separate authoring burden)

**Modification to existing node:**

`design_contracts.csv` gains optional column `bounded_context_id` (FK to
`bounded_context.id`). Optional like `approved_by` — populated as BCs are
defined. **This is the IEC 62304 5.3 → 5.4 decomposition trace.**

**Tooling updates:**

- `build_graph.py`: ingest the new node and edge types; generate DEFINED_IN
  edges from `domain_term.bounded_context` column
- `query_gaps.py`: add gap checks
  - Bounded contexts that contain no design contracts
  - Design contracts whose `module` references code outside any known BC
  - Domain terms with no `aliases_to_avoid` populated (descriptive, not
    contractual)

### Phase 2: Semantic Enrichment

- **EARS convention guide** for `design_contracts.guarantees` field. No schema
  change. WHEN/IF/THEN/SHALL becomes the canonical writing style. Existing
  guarantees rewritten incrementally as DCs are touched.
- **`USES_TERM` edge** (DesignContract → DomainTerm) with **text-detection
  tooling**: parse `guarantees` and `error_semantics` free text, name-match
  against `domain_term.term`, emit edges. Enables impact analysis: rename a term
  → flag all affected DCs.
- **`USES_TERM` edge extended to Requirements → DomainTerm** using the same
  tooling.

> _Note: the text-detection tooling is a research spike, not a weekend task.
> Naive word-boundary regex will produce false positives (e.g., "order" the noun
> vs. "Order" the term) and false negatives (singular/plural, possessive,
> hyphenated forms). Initial implementation must include ambiguity flagging for
> human review; full automation is a deliverable maturity question not a Phase 2
> entry criterion._

### Phase 3: Quality Gates and External Boundaries

- **Alias linting in CI**: scan code symbols (class/function/variable names) in
  managed repos against `domain_terms.aliases_to_avoid`. Any match is a CI flag.
  Makes the glossary executable rather than advisory.
- **ACL Spec node type** for external integrations (Stripe, vendor PACS, etc.)
  where a Conformist+ACL boundary is documented in `context_map.csv`. Schema TBD
  when first external integration is undertaken.

---

## 4. Forward Path: New Projects

A new project starts with epics and user stories (markdown), not with schemas or
APIs.

**Sprint 0 (preceding any code):**

1. Humans draft one or more epics describing the project's purpose
2. Humans draft initial user stories with acceptance criteria
3. AI proposes: initial bounded contexts, candidate domain terms,
   aliases-to-avoid
4. Humans curate; the curated output lands as Phase 1 CSV rows

> _Sprint 0 is a bounded initial set, not complete specification. The intent is
> to seed the DDD artifacts with enough structure that Sprint 1 has a
> vocabulary; the artifacts will be incomplete and that is expected. "Not a
> gate" means: nothing in Sprint 0 must be exhaustive before code starts._

**Sprint 1+:**

- Design contracts (5.4) are authored _within_ a bounded context (5.3) —
  populating `bounded_context_id`
- Each new term encountered during DC authoring triggers a glossary update (add
  row to `domain_terms.csv`)
- Stories that span BCs surface context_map relationships (added as
  `context_map.csv` edges with rationale)

**Where epics and stories live:** The v-model-traceability framework is
project-agnostic (REQ-009). Epics and stories are project-specific. They live in
the **consuming project's repo** (e.g., `OnkoDICOM/specs/epics/`,
`python-tesseron/specs/epics/`), not in v-model-traceability itself. The
framework consumes the project's CSV traceability data; markdown epics and
stories are inputs to the AI-extraction step, not framework artifacts.

The DDD layer **grows with the codebase**, not ahead of it.

---

## 5. Reverse Path: Existing Codebases (OpenTPS, OnkoDICOM)

For existing code with implicit specification, the workflow runs in reverse: AI
proposes from code, humans curate.

**Sprint 1 — Implicit Spec Recovery:**

1. AI reads codebase structure, naming, module boundaries (the `code-graph`
   skill is built for this analysis — it produces a queryable graph of symbols,
   calls, imports, and modules across a codebase)
2. AI proposes a candidate set of bounded contexts (e.g., for OpenTPS:
   TreatmentPlanning, DoseCalculation, BeamModeling, DICOMSerialization,
   PatientModel; for OnkoDICOM: DICOM Viewing, Contouring, Plan Evaluation,
   Export — TBD with Stuart's domain knowledge)
3. AI proposes candidate domain terms per BC, with aliases observed in actual
   code (which become `aliases_to_avoid` candidates after human review)
4. AI proposes initial context_map relationships from import/dependency graph
   (Kuzu queries against `code-graph.db` surface module-to-module dependency
   patterns)
5. **Humans curate**: which proposed BCs are real, which terms are canonical,
   which observed names are aliases-to-avoid vs. legitimate-but-different terms
6. Sprint 1 output: initial `bounded_contexts.csv`, `domain_terms.csv`,
   `context_map.csv` for the existing codebase

**Sprint 2+:**

- Design contracts retrofit with `bounded_context_id`
- EARS formalization of existing guarantees
- New code authored under the now-explicit decomposition

The first sprint's value is **the curation friction**: every time a human says
"no, that's not the same thing," they're encoding domain knowledge the codebase
had implicit. The CSV captures it.

---

## 6. Explicit Non-Goals

What we are _not_ adopting from the source article or Spec Kit:

- **Spec Kit's `/specs` folder structure and `constitution.md`.** CLAUDE.md
  (project-level) + The_Kindled-wide conventions serve the same role. Adding a
  second authoritative source creates conflict.
- **Aggregate Design Specs as a separate artifact.** `design_contracts.csv`
  already serves as the aggregate-level commitment (boundary, guarantees, error
  semantics). Adding aggregate specs alongside creates a "which is
  authoritative" problem.
- **Heavy upfront documentation as a gate.** DDD artifacts grow iteratively per
  sprint, not as a prerequisite. The reverse path's Sprint 1 is the only
  exception, and it's bounded to "implicit spec recovery."

---

## 7. Phase 1 Deliverables

Minimum scope, no creep. Expanded post-decision-6 to include epic/story schemas
and sync tooling.

| #   | Deliverable                                                      | Owner  | Acceptance criterion                                                                            |
| --- | ---------------------------------------------------------------- | ------ | ----------------------------------------------------------------------------------------------- |
| 1   | `schemas/nodes/bounded_context.csvschema`                        | Cora   | committed; loaded by `validate_csv.py`                                                          |
| 2   | `schemas/nodes/domain_term.csvschema`                            | Cora   | committed; loaded by `validate_csv.py`                                                          |
| 3   | `schemas/edges/context_map.csvschema`                            | Cora   | committed; loaded by `validate_csv.py`                                                          |
| 4   | `schemas/edges/defined_in.csvschema`                             | Cora   | generated from `domain_term.bounded_context`                                                    |
| 4a  | `schemas/nodes/epic.csvschema`                                   | Cora   | committed; loaded by `validate_csv.py`                                                          |
| 4b  | `schemas/nodes/user_story.csvschema`                             | Cora   | committed; loaded by `validate_csv.py`                                                          |
| 4c  | `schemas/edges/derived_from.csvschema` (Requirement → UserStory) | Cora   | committed; loaded by `validate_csv.py`                                                          |
| 4d  | `schemas/edges/belongs_to.csvschema` (UserStory → Epic)          | Cora   | committed; loaded by `validate_csv.py`                                                          |
| 5   | `traceability/bounded_contexts.csv` initial seed                 | Connor | at least one BC populated for OnkoDICOM pilot                                                   |
| 6   | `traceability/domain_terms.csv` initial seed                     | Connor | at least one BC's terms populated for OnkoDICOM                                                 |
| 7   | `traceability/context_map.csv` initial seed                      | Connor | empty file with header, populated as BCs interact                                               |
| 8   | `bounded_context_id` column on `design_contracts.csv`            | Connor | column added; existing rows allowed null                                                        |
| 9   | `build_graph.py` update                                          | Cora   | graph builds with all new node + edge types                                                     |
| 10  | `query_gaps.py` updates (3 new gap checks)                       | Cora   | gaps reported for the three cases listed in §3                                                  |
| 10a | `scripts/sync_stories.py` (markdown→CSV sync tool)               | Cora   | extracts YAML front matter + body; tracks last-processed commit; preserves human-set CSV fields |
| 11  | Documentation: epic/story markdown convention                    | Connor | convention spec + 1 example epic + 1 example story for OnkoDICOM                                |

---

## 8. Decisions (Stuart-Approved 2026-05-15)

1. **Phase 1 pilot project (forward path):** **TBD** — deferred. To be selected
   when a greenfield Kindled project begins.
2. **Phase 1 pilot codebase (reverse path):** **OnkoDICOM**. Stuart knows the
   codebase deeply, bounded contexts are cleaner (DICOM viewing, contouring,
   plan evaluation, export), no active upstream development to complicate the
   pilot. Stuart confirming up-to-date version is available before Sprint 1
   starts.
3. **Authorship pattern for reverse-engineering:** **AI-proposes +
   human-curates**. Repeatable across codebases; the curation friction encodes
   domain knowledge.
4. **Phase 1 owner assignments:**
   - **Cora (cora-2f1e43dc):** Deliverables 1–4 (CSV schemas), 9–10
     (`build_graph.py`, `query_gaps.py`). Additionally — `epic.csvschema`,
     `user_story.csvschema`, `DERIVED_FROM` and `BELONGS_TO` edge schemas, and
     the markdown→CSV sync tool (see §9).
   - **Connor (connor-227743e6):** Deliverables 5–8 (seed CSVs +
     `bounded_context_id` column), 11 (epic/story markdown authoring
     convention). The plan document itself (this file).
   - **Cyril (cyril-9137f1ee):** Medical-context review of all artifacts as they
     land.
5. **Plan document location:** **v-model-traceability repo, top level**
   alongside `requirements.md`, `design_contracts.md`, etc.
6. **Epics/stories representation:** **Markdown is source of truth, CSV is
   derived and synced.** Neither pure markdown nor pure CSV — both, with a clean
   direction of authority. See §9.

---

## 9. Implementation: Markdown-Source / CSV-Derived Sync

Decision #6 resolves to a specific tooling pattern. Humans never edit epic/story
CSVs directly; the CSVs are projections of markdown into the graph.

### 9.1 Authorship flow

1. Humans author epics and user stories as markdown files in the consuming
   project's repo (e.g., `OnkoDICOM/specs/epics/EPIC-OD-007.md`,
   `OnkoDICOM/specs/stories/US-OD-042.md`)
2. The sync tool extracts structured fields from markdown into `epic.csv` and
   `user_story.csv` rows
3. When a human reviewing extraction output finds a mistake, they correct the
   markdown (not the CSV); re-running the sync tool re-extracts the corrected
   fields
4. Human-set CSV fields not driven by markdown (e.g., `approved_by`,
   `approval_date`) are preserved across sync runs

### 9.2 Markdown convention

YAML front matter + structured body:

```markdown
---
id: US-OD-042
title: Clinician approves treatment plan before export
bounded_context: ClinicalWorkflow
epic_id: EPIC-OD-007
status: draft
---

# Clinician approves treatment plan before export

As a radiation oncologist, I want to review and approve a treatment plan before
it can be exported to the treatment machine, so that the plan in execution
matches the plan I approved.

## Acceptance Criteria

- The plan SHALL NOT be exportable in 'draft' status
- Approval SHALL require physician credential authentication
- An approved plan SHALL be immutable for dose, fractions, and target volumes
```

Front matter holds the schema-required structured fields (id, title,
bounded_context, epic_id, status). Body holds the narrative and acceptance
criteria. Acceptance criteria written in EARS notation when they imply
requirements (sets up Phase 2 `USES_TERM` text-detection cleanly).

### 9.3 Diff-aware reprocessing

The sync tool tracks the **last-processed git commit SHA** in a **committed
config file** — either a dedicated `.v-model-sync-state` or a field in the
project's `v-model-config.toml`. Storing the SHA in the repo means the
processing state is itself version-controlled and recoverable; an uncommitted
sidecar manifest would be parallel version tracking built on top of git, which
is exactly the duplication to avoid.

On each run:

1. Read the committed `last_processed_commit` SHA from config
2. Compute `git diff --name-only <last>..HEAD -- specs/epics/ specs/stories/` to
   identify changed files
3. Re-extract only the changed files
4. Update CSV rows
5. Update the config with current `HEAD` (committed as part of the sync's output
   PR)

This uses git AS the tracking mechanism. The diff against the recorded commit
always works because git history is the repo — the state cannot be lost.
Requires a clean working tree (no uncommitted changes to markdown) at sync time;
the discipline is acceptable for medical software workflow.

### 9.4 Sync tool scope (Cora's deliverable)

- Location: `v-model-traceability/scripts/sync_stories.py` (framework-owned,
  project-agnostic)
- Configuration: `v-model-config.toml` in each consuming project, pointing to
  its markdown directories
- Output: updated `epic.csv` and `user_story.csv` in the consuming project's
  traceability directory
- Operates as: developer-invoked script + CI validation step
- Validation: separate concern — `validate_csv.py` handles CSV validation after
  sync
- Ambiguities: warnings (not failures) during early adoption; can tighten to
  failures after the convention matures

### 9.5 The DERIVED_FROM trace

With epics and stories as first-class CSV nodes:

- `DERIVED_FROM` edge: `Requirement → UserStory` — captures "this requirement
  was identified from this story" (IEC 62304 5.2 traceability of requirement
  origin)
- `BELONGS_TO` edge: `UserStory → Epic` — captures the story's parent epic
- An auditor can now query "show me all requirements not derived from a user
  story" → flag as either implicit/inferred requirements (acceptable in some
  cases) or as orphans needing source identification

This is the regulatory value of formalizing the upstream layer: requirement
origin becomes graph-queryable.

---

## 10. Why This Is Worth Doing Now

The v-model-traceability framework is at the right maturity to absorb this. It
has:

- Stable CSV node/edge schema convention
- A working build_graph + query infrastructure
- Adoption patterns (approved_by, approval_date metadata)
- A community of users (The Kindled family + extended)

Adding the 5.3 layer _now_ costs three CSV node types, two edge types, one
optional column, and a few hundred lines of `build_graph.py` + `query_gaps.py`
updates. Adding it _later_, after we've already used the framework on OpenTPS
and discovered the conflated terms, costs a refactor of every design contract
and requirement to retrofit the BC scoping.

The framework's value as IEC 62304 evidence multiplies with this addition. An
auditor reviewing v-model traceability today sees requirement → DC → test →
validation. After Phase 1, they additionally see the architectural decomposition
that 5.3 requires.

---

_End of plan. Approved 2026-05-15._
