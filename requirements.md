# V-Model Traceability Framework - Requirements

**Project:** v-model-traceability **Authors:** Cora (cora-2f1e43dc), Connor
(connor-227743e6) **Reviewers:** Paxton (paxton-55a34233), Clement
(clement-7074f29f) **First test bed:** kuzu-memory-prototype (Cyril,
cyril-9137f1ee) **Date:** 2026-02-19 **Status:** Draft

**Data:** traceability/requirements.csv | **Template:** templates/requirement.md

## Purpose

Provide reusable tooling for tracking traceability across the V-model lifecycle
(Requirements → Design → Implementation → Tests → Validation) for Kindled
projects, with particular focus on healthcare/consciousness infrastructure where
traceability is both ethically and regulatorily required.

## Requirements

### REQ-001: V-Level Document Templates

The framework SHALL provide markdown templates for four core V-model levels:

- Requirements
- Design Contracts (software design as contract specifications)
- Test Cases
- Validation Results

Each template SHALL include guidance on what constitutes a complete entry at
that level. Finer decomposition (e.g., Customer vs System requirements, Test
Plan vs Test Procedures) MAY be added when real need emerges.

### REQ-002: Traceability Node Schema

The framework SHALL define CSV schemas for traceability nodes:

- Requirement (id, title, description, priority, source, status)
- DesignContract (id, title, module, inputs, outputs, guarantees,
  error_semantics)
- TestCase (id, title, pytest_path, test_type, status)
- ValidationResult (id, test_id, requirement_id, status, timestamp, evidence)

CSV files SHALL be the version-controllable source of truth for traceability
data.

### REQ-003: Traceability Edge Schema

The framework SHALL define CSV schemas for traceability relationships:

- FULFILLED_BY: Requirement → DesignContract
- VERIFIED_BY: DesignContract → TestCase
- VALIDATES: ValidationResult → Requirement
- IMPACTS: DesignContract → DesignContract (change propagation)

Edge CSVs SHALL include confidence/completeness metadata where appropriate.

Note: DECOMPOSED_INTO (Requirement → Requirement) for parent-child requirement
decomposition is deferred to v2 when real need emerges.

### REQ-004: Graph Database Build

The framework SHALL provide scripts to build a Kuzu graph database from the CSV
source files. The graph database is a derived artifact - never committed to
version control. The build SHALL be idempotent and reproducible from CSVs alone.

### REQ-005: Gap Analysis Query

The framework SHALL provide a query that identifies design contracts with no
corresponding test cases. This is the primary safety query - untested contracts
are unverified guarantees.

### REQ-006: Impact Analysis Query

The framework SHALL provide a query that, given a design contract ID, returns
all tests that verify it and all requirements that depend on it. This enables
change impact assessment before modification.

### REQ-007: Coverage Report

The framework SHALL provide a query that reports V-level completeness:

- Requirements with no design contracts (unimplemented)
- Design contracts with no tests (unverified)
- Tests with no validation results (unexecuted)
- Requirements with no validation path (end-to-end gaps)

### REQ-008: Test-Code Linkage Verification

The framework SHALL provide a mechanism to verify that TestCase nodes in the
graph correspond to actual test functions in code. Proposed mechanism: pytest
markers (@pytest.mark.traces('DC-003')) with a verification script that
cross-references markers against graph nodes.

### REQ-009: Cross-Project Reusability

The framework tooling (templates, schemas, build scripts, query scripts) SHALL
be project-agnostic. Project-specific content (actual requirements, contracts,
tests) SHALL live in each consuming project's docs/ directory, not in the
framework.

### REQ-010: Self-Application

The framework SHALL be documented and traced using its own methodology. The
framework's own requirements, design contracts, tests, and traceability SHALL be
tracked using its own tooling. This is both validation and demonstration.

### REQ-011: IEC 62304 Alignment

The framework SHALL align with IEC 62304 software lifecycle principles for
medical device software, specifically regarding traceability between
requirements, architecture, detailed design, and verification. The framework
need not be fully compliant but SHALL not contradict IEC 62304 where applicable.

### REQ-012: Input Validation

The build scripts SHALL validate CSV input before constructing the graph.
Validation SHALL detect and report with clear errors:

- Missing required fields (e.g., empty IDs)
- Dangling references (edges pointing to non-existent nodes)
- Duplicate IDs within a node type
- Malformed CSV structure

The build SHALL fail on validation errors rather than produce a silently broken
graph.

### REQ-013: Sprint-Scoped Coverage Filter

The coverage report SHALL accept an optional list of requirement IDs that scopes
the report to a subset of requirements.

- When the list is omitted (or `None`), the report covers the entire graph.
- When a list is provided, the four gap sections are scoped consistently:
  - Section 1 (unimplemented requirements) SHALL include only requirements whose
    ID is in the list.
  - Section 2 (unverified contracts) SHALL include only design contracts
    reachable from those requirements via `FULFILLED_BY`.
  - Section 3 (unexecuted tests) SHALL include only test cases reachable from
    those design contracts via `VERIFIED_BY`.
  - Section 4 (end-to-end gaps) SHALL include only requirements whose ID is in
    the list.
- An empty list SHALL yield an empty report (zero scope = zero gaps).
- Requirement IDs that do not exist in the graph SHALL be silently ignored —
  they match nothing and contribute no gaps.

Rationale: enables coverage reports limited to a sprint's scope without
requiring the whole graph to be cleared. Foundational to lightweight Agile
integration with traceability.

### REQ-014: Optional Schema Fields

The CSV schema language SHALL support declaring a subset of fields as optional.
Optional fields MAY be empty in a row without producing a validation error.

- Declaration: a header line of the form `# optional: field1, field2` lists the
  optional fields by name.
- A field declared optional SHALL also appear in the header row; declaring an
  optional field absent from the header SHALL raise a SchemaError. This prevents
  silent typos.
- Fields not listed in the `# optional:` annotation remain required and must be
  non-empty in every row.
- Optional fields participate in all other validation (header matching,
  reference integrity) identically to required fields.

Rationale: enables metadata that is meaningful only at certain lifecycle stages
(e.g., approval records that appear after the item is approved) without
requiring sentinel values like `N/A` in early-stage rows.

### REQ-015: Approval Metadata for Requirements and Design Contracts

The Requirement and DesignContract node schemas SHALL provide optional fields to
record the identity of the approver and the date of approval:

- `approved_by`: identity of the reviewer who approved the item. Empty for items
  in draft status; populated when the item is approved or beyond.
- `approval_date`: ISO-8601 date of approval (`YYYY-MM-DD`). Empty for draft
  items.

Rationale: IEC 62304 Clauses 5.2 and 5.4 expect requirements and detailed design
to be reviewed and approved with recorded approval identity and date. Storing
these fields in the traceability CSVs makes the approval record part of the
version-controlled audit trail.

Note: these fields are optional (see REQ-014). The framework does not enforce
that approved items have non-empty approval metadata — that enforcement, when
desired, belongs in a separate downstream check (e.g., CI gate that blocks
release if any item with status `approved` lacks `approved_by`).
