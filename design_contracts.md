# V-Model Traceability Framework - Design Contracts

**Project:** v-model-traceability **Authors:** Cora (cora-2f1e43dc), Connor
(connor-227743e6) **Reviewers:** Paxton (paxton-55a34233), Clement
(clement-7074f29f) **Date:** 2026-02-20 **Status:** Draft

## Overview

Design contracts define what each module guarantees at its interface. A test
author should be able to derive what tests are needed from these contracts
alone, without reading the implementation.

Cross-cutting constraints (applied to ALL contracts):

- **REQ-009 (Reusability):** All scripts accept paths as arguments. No hardcoded
  project paths. Framework tooling is project-agnostic.
- **REQ-010 (Self-Application):** The framework's own requirements, contracts,
  and tests populate its own traceability CSVs.
- **REQ-011 (IEC 62304):** Terminology and structure align with IEC 62304
  software lifecycle principles. The framework does not contradict 62304 where
  applicable.

## Contracts

### DC-001: CSV Schema Validator

**Fulfills:** REQ-012 (Input Validation) **Module:** `scripts/validate_csv.py`

**Inputs:**

- `csv_path`: Path to a CSV data file
- `schema_path`: Path to the corresponding `.csvschema` file

**Outputs:**

- On success: parsed rows as list of dicts (validated)
- On failure: list of `ValidationError` objects with row number, field, and
  message

**Guarantees:**

- Every required field in the schema is present and non-empty in every row
- No duplicate IDs within a single CSV file
- CSV structure matches schema header exactly
- Validation is complete: ALL errors are collected before returning, not
  fail-fast on the first error

**Error Semantics:**

- Returns a result object with `valid: bool` and `errors: list`
- Never raises exceptions for data problems - all data issues are reported in
  the errors list
- Raises `FileNotFoundError` for missing files
- Raises `SchemaError` for unparseable schema files

---

### DC-002: Reference Integrity Validator

**Fulfills:** REQ-012 (Input Validation - dangling references) **Module:**
`scripts/validate_csv.py` (second pass)

**Inputs:**

- `edge_csv_path`: Path to an edge CSV file
- `node_csvs`: Dict mapping node type to validated node data (output of DC-001)

**Outputs:**

- On success: validated edge rows
- On failure: list of `ReferenceError` objects identifying dangling references

**Guarantees:**

- Every foreign key in an edge CSV references an existing node ID
- Both endpoints of every edge are validated (source and target)
- Reports ALL dangling references, not just the first

**Error Semantics:**

- Same result object pattern as DC-001
- Requires node CSVs to have passed DC-001 validation first

---

### DC-003: Graph Build Pipeline

**Fulfills:** REQ-004 (Graph Database Build) **Depends on:** DC-001, DC-002
**Module:** `scripts/build_graph.py`

**Inputs:**

- `csv_dir`: Directory containing node and edge CSV files
- `schema_dir`: Directory containing `.csvschema` files
- `output_path`: Path for the Kuzu database

**Outputs:**

- A Kuzu graph database at `output_path`

**Guarantees:**

- Build is idempotent: running twice with identical CSVs produces identical
  graph
- Reproducible from CSVs alone: no external state required
- All CSVs pass DC-001 and DC-002 validation before any graph writes
- Database is either fully built or not present (atomic: removes partial build
  on failure)
- Node counts in graph match row counts in CSVs (verifiable post-build)

**Error Semantics:**

- Fails with validation report if any CSV fails DC-001 or DC-002
- Fails with build error if Kuzu operations fail
- On failure: no partial database left behind

---

### DC-004: Gap Analysis Query

**Fulfills:** REQ-005 (Gap Analysis) **Module:** `scripts/query_gaps.py`

**Inputs:**

- `db_path`: Path to built Kuzu database

**Outputs:**

- List of `DesignContract` nodes that have zero `VERIFIED_BY` edges (untested
  contracts)

**Guarantees:**

- Returns empty list when every contract has at least one test
- Includes contract ID, title, and module in output for actionability
- Output is deterministically ordered (by contract ID)

**Error Semantics:**

- Fails if database path doesn't exist or database is corrupt
- Fails if expected schema (node/edge tables) is missing from database

---

### DC-005: Impact Analysis Query

**Fulfills:** REQ-006 (Impact Analysis) **Module:** `scripts/query_impact.py`

**Inputs:**

- `db_path`: Path to built Kuzu database
- `contract_id`: ID of the design contract to analyze

**Outputs:**

- `tests`: List of TestCase nodes connected via `VERIFIED_BY`
- `requirements`: List of Requirement nodes connected via `FULFILLED_BY`
  (reverse)
- `impacted_contracts`: List of DesignContract nodes connected via `IMPACTS`
  (both directions)

**Guarantees:**

- Traverses all three relationship types from the contract
- Direct relationships only (transitive traversal deferred to v2 when real need
  emerges)

**Error Semantics:**

- Fails if `contract_id` doesn't exist in the graph
- Fails if database doesn't exist or is corrupt

---

### DC-006: Coverage Report

**Fulfills:** REQ-007 (Coverage Report) **Module:** `scripts/query_coverage.py`

**Inputs:**

- `db_path`: Path to built Kuzu database

**Outputs:**

Structured report with four sections:

1. Requirements with no `FULFILLED_BY` edges (unimplemented)
2. Design contracts with no `VERIFIED_BY` edges (unverified)
3. Test cases with no `ValidationResult` nodes (unexecuted)
4. Requirements with no path to any `ValidationResult` (end-to-end gaps)

**Guarantees:**

- All four gap categories from REQ-007 are reported
- Each section lists affected node IDs and titles
- Section 4 performs multi-hop traversal
  (Requirement->Contract->Test->ValidationResult)
- Summary counts are provided for each section
- Output is deterministically ordered within each section

**Error Semantics:**

- Same as DC-004

---

### DC-007: Test-Code Linkage Verifier

**Fulfills:** REQ-008 (Test-Code Linkage) **Module:**
`scripts/verify_test_linkage.py`

**Inputs:**

- `db_path`: Path to built Kuzu database
- `test_dir`: Path to pytest test directory

**Outputs:**

- `matched`: TestCase nodes whose `pytest_path` exists in code AND has
  `@pytest.mark.traces` marker matching a contract
- `graph_only`: TestCase nodes in graph with no corresponding test function in
  code
- `code_only`: Test functions with `@pytest.mark.traces` marker but no
  corresponding TestCase node in graph
- `unlinked`: Test functions with no `@pytest.mark.traces` marker at all

**Guarantees:**

- Detects mismatches in both directions (graph without code, code without graph)
- Parses pytest markers without executing tests (AST-based or marker collection)
- Reports are actionable: includes file paths and line numbers for code-side
  items

**Error Semantics:**

- Advisory: reports mismatches but exits 0 (non-fatal)
- Exits non-zero only for infrastructure errors (missing database, unreadable
  test directory)

---

### DC-008: V-Level Document Templates

**Fulfills:** REQ-001 (V-Level Document Templates) **Module:** `templates/`
directory

**Outputs:**

Four markdown templates:

1. `templates/requirement.md` - guidance for writing requirements
2. `templates/design_contract.md` - guidance for writing contracts
3. `templates/test_case.md` - guidance for writing test documentation
4. `templates/validation_result.md` - guidance for recording validation

**Guarantees:**

- Each template includes all fields defined in the corresponding node schema
- Each template includes examples of well-formed entries
- Templates are self-contained (usable without reading the framework code)

**Error Semantics:** N/A (static files)

---

### DC-009: Traceability Schema Definitions

**Fulfills:** REQ-002 (Traceability Node Schema), REQ-003 (Traceability Edge
Schema) **Module:** `schemas/` directory

**Outputs:**

Static CSV schema files:

- `schemas/nodes/requirement.csvschema`
- `schemas/nodes/design_contract.csvschema`
- `schemas/nodes/test_case.csvschema`
- `schemas/nodes/validation_result.csvschema`
- `schemas/edges/fulfilled_by.csvschema`
- `schemas/edges/verified_by.csvschema`
- `schemas/edges/validates.csvschema`
- `schemas/edges/impacts.csvschema`

**Guarantees:**

- Each schema defines the complete field set for its node/edge type
- Field comments document semantics and valid values
- Schemas are the authoritative definition consumed by DC-001 (validator) and
  DC-003 (build pipeline)

**Error Semantics:** N/A (static files)
