# V-Model Traceability Framework - Requirements

**Project:** v-model-traceability **Authors:** Cora (cora-2f1e43dc), Connor
(connor-227743e6) **Reviewers:** Paxton (paxton-55a34233), Clement
(clement-7074f29f) **First test bed:** kuzu-memory-prototype (Cyril,
cyril-9137f1ee) **Date:** 2026-02-19 **Status:** Draft

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
