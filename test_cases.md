# V-Model Traceability Framework - Test Cases

**Project:** v-model-traceability **Authors:** Cora (cora-2f1e43dc), Connor
(connor-227743e6) **Reviewers:** Paxton (paxton-55a34233), Clement
(clement-7074f29f) **Date:** 2026-02-20 **Status:** Draft

**Data:** traceability/test_cases.csv | **Template:** templates/test_case.md

## Purpose

This document describes the test strategy for the V-Model Traceability Framework
and explains what each test case verifies and why. Tests are organized by the
design contract they verify. Each test case corresponds to a row in
`traceability/test_cases.csv` and a real pytest function in the `tests/`
directory.

The test suite covers three contracts: DC-001 (CSV Schema Validator), DC-002
(Reference Integrity Validator), and DC-003 (Graph Build Pipeline). Contracts
DC-004 through DC-009 are either query scripts without dedicated unit tests yet,
or static artifacts (templates, schemas) that do not require executable tests.

---

## DC-001: CSV Schema Validator (TC-001 through TC-008)

DC-001 guarantees that the schema validator correctly accepts well-formed CSVs
and reports all problems in malformed ones — without fail-fast behavior. The
tests in this group exercise each guarantee stated in the contract.

### TC-001: Valid CSV passes schema validation

**pytest_path:**
`tests/test_validate_csv.py::TestSchemaValidator::test_valid_csv_passes`
**test_type:** unit **status:** passing **Verifies:** DC-001 guarantee — "CSV
structure matches schema header exactly" and "Every required field in the schema
is present and non-empty in every row"

A correctly formed CSV with all required fields should pass validation and
return parsed rows. This is the baseline happy-path test confirming that valid
input is not incorrectly rejected.

---

### TC-002: Empty required field detected

**pytest_path:**
`tests/test_validate_csv.py::TestSchemaValidator::test_empty_required_field_detected`
**test_type:** unit **status:** passing **Verifies:** DC-001 guarantee — "Every
required field in the schema is present and non-empty in every row"

Submitting a CSV row with a blank required field must produce a
`ValidationError` identifying the row and field. This guards against silently
importing incomplete traceability data into the graph.

---

### TC-003: Duplicate ID detected

**pytest_path:**
`tests/test_validate_csv.py::TestSchemaValidator::test_duplicate_id_detected`
**test_type:** unit **status:** passing **Verifies:** DC-001 guarantee — "No
duplicate IDs within a single CSV file"

Duplicate node IDs would corrupt the graph by creating ambiguous references. The
validator must catch and report them before any graph write occurs.

---

### TC-004: Header mismatch detected

**pytest_path:**
`tests/test_validate_csv.py::TestSchemaValidator::test_header_mismatch_detected`
**test_type:** unit **status:** passing **Verifies:** DC-001 guarantee — "CSV
structure matches schema header exactly"

A CSV whose header row does not match the schema definition must be rejected
immediately. This prevents field misalignment that would silently load data into
the wrong columns.

---

### TC-005: Empty CSV detected

**pytest_path:**
`tests/test_validate_csv.py::TestSchemaValidator::test_empty_csv_detected`
**test_type:** unit **status:** passing **Verifies:** DC-001 guarantee — "Every
required field in the schema is present and non-empty in every row"

An empty CSV (header only, or completely empty) is a degenerate input that
should be caught explicitly rather than silently producing an empty graph with
no diagnostic.

---

### TC-006: Missing file raises error

**pytest_path:**
`tests/test_validate_csv.py::TestSchemaValidator::test_missing_file_raises`
**test_type:** unit **status:** passing **Verifies:** DC-001 error semantics —
"Raises `FileNotFoundError` for missing files"

Infrastructure errors (a missing CSV file) must raise an exception rather than
return a validation-failure result. This distinguishes between "data is wrong"
and "the file doesn't exist at all."

---

### TC-007: Bad schema raises error

**pytest_path:**
`tests/test_validate_csv.py::TestSchemaValidator::test_bad_schema_raises`
**test_type:** unit **status:** passing **Verifies:** DC-001 error semantics —
"Raises `SchemaError` for unparseable schema files"

An unparseable schema file is a framework configuration error, not a data error.
It must raise `SchemaError` so operators know to fix the schema definition
rather than the CSV data.

---

### TC-008: All errors collected not fail-fast

**pytest_path:**
`tests/test_validate_csv.py::TestSchemaValidator::test_all_errors_collected`
**test_type:** unit **status:** passing **Verifies:** DC-001 guarantee —
"Validation is complete: ALL errors are collected before returning, not
fail-fast on the first error"

When a CSV has multiple problems, the validator must report all of them in a
single pass. Fail-fast behavior would force repeated fix-and-retry cycles; this
is especially important for large traceability CSVs being edited by multiple
contributors.

---

## DC-002: Reference Integrity Validator (TC-009 through TC-012)

DC-002 guarantees that edge CSVs only reference node IDs that actually exist.
These tests verify that dangling references are caught before they reach the
graph build step.

### TC-009: Valid references pass

**pytest_path:**
`tests/test_validate_csv.py::TestReferenceValidator::test_valid_references_pass`
**test_type:** unit **status:** passing **Verifies:** DC-002 guarantee — "Every
foreign key in an edge CSV references an existing node ID"

An edge CSV where all source and target IDs reference real node entries should
pass reference validation. This is the baseline that confirms valid graphs are
not blocked.

---

### TC-010: Dangling reference detected

**pytest_path:**
`tests/test_validate_csv.py::TestReferenceValidator::test_dangling_reference_detected`
**test_type:** unit **status:** passing **Verifies:** DC-002 guarantee — "Every
foreign key in an edge CSV references an existing node ID"

A single dangling reference in an edge CSV must be caught and reported with
enough detail (row number, field, offending ID) to locate and fix it. A graph
with dangling references would silently omit traceability links.

---

### TC-011: Both endpoints validated

**pytest_path:**
`tests/test_validate_csv.py::TestReferenceValidator::test_both_endpoints_validated`
**test_type:** unit **status:** passing **Verifies:** DC-002 guarantee — "Both
endpoints of every edge are validated (source and target)"

Reference validation must check both the source ID and the target ID of each
edge, not just one. A missing source is as broken as a missing target.

---

### TC-012: All dangling references reported

**pytest_path:**
`tests/test_validate_csv.py::TestReferenceValidator::test_all_dangling_references_reported`
**test_type:** unit **status:** passing **Verifies:** DC-002 guarantee —
"Reports ALL dangling references, not just the first"

Consistent with DC-001's all-errors policy, reference validation must report
every dangling reference in a single pass. This matters for edge CSVs that may
contain many rows added in a single batch.

---

## DC-003: Graph Build Pipeline (TC-013 through TC-020)

DC-003 guarantees that the graph build is idempotent, atomic on failure, and
produces a queryable database whose node counts match the source CSVs. The tests
in this group are integration tests because they write real files and build a
real Kuzu database.

### TC-013: Build from valid CSVs

**pytest_path:**
`tests/test_build_graph.py::TestGraphBuild::test_builds_database_from_valid_csvs`
**test_type:** integration **status:** passing **Verifies:** DC-003 guarantee —
"Reproducible from CSVs alone: no external state required"

The baseline test: given a directory of valid CSVs and schemas, the build script
must produce a Kuzu database without error. This confirms the fundamental
pipeline path works end to end.

---

### TC-014: Node data queryable after build

**pytest_path:**
`tests/test_build_graph.py::TestGraphBuild::test_node_data_queryable`
**test_type:** integration **status:** passing **Verifies:** DC-003 guarantee —
"Node counts in graph match row counts in CSVs (verifiable post-build)"

After a successful build, node data must be retrievable via Kuzu query. A
database that exists but contains no queryable data is not a usable graph.

---

### TC-015: Edge data queryable after build

**pytest_path:**
`tests/test_build_graph.py::TestGraphBuild::test_edge_data_queryable`
**test_type:** integration **status:** passing **Verifies:** DC-003 guarantee —
"Node counts in graph match row counts in CSVs (verifiable post-build)"

Extends TC-014 to confirm that relationship edges are also loaded and
traversable. Traceability queries depend on edges; a graph with nodes but no
edges provides no traceability information.

---

### TC-016: Idempotent rebuild

**pytest_path:**
`tests/test_build_graph.py::TestGraphBuild::test_idempotent_rebuild`
**test_type:** integration **status:** passing **Verifies:** DC-003 guarantee —
"Build is idempotent: running twice with identical CSVs produces identical
graph"

Running the build script twice on the same input must not corrupt the graph or
produce duplicate nodes. This matters because CI pipelines may rebuild the
database repeatedly without manually cleaning up first.

---

### TC-017: Validation failure prevents build

**pytest_path:**
`tests/test_build_graph.py::TestGraphBuild::test_validation_failure_prevents_build`
**test_type:** integration **status:** passing **Verifies:** DC-003 guarantee —
"All CSVs pass DC-001 and DC-002 validation before any graph writes"

When validation fails, the build must abort before writing any graph data. This
prevents a partial or corrupt database from being silently used by downstream
queries.

---

### TC-018: No partial database on failure

**pytest_path:**
`tests/test_build_graph.py::TestGraphBuild::test_no_partial_database_on_failure`
**test_type:** integration **status:** passing **Verifies:** DC-003 guarantee —
"Database is either fully built or not present (atomic: removes partial build on
failure)"

If the build fails mid-way, any partial database must be removed. A partial
database is worse than no database: downstream tools may open it successfully
but receive incomplete or corrupted traceability data.

---

### TC-019: Project graph builds successfully

**pytest_path:**
`tests/test_build_graph.py::TestSelfApplication::test_project_graph_builds_successfully`
**test_type:** integration **status:** passing **Verifies:** DC-003 guarantee
(self-application) — the framework's own CSVs build without error

This is the self-application test required by REQ-010. The framework must be
able to build its own traceability graph from its own CSV files. A framework
that cannot trace itself is not credible as traceability infrastructure.

---

### TC-020: Project graph node counts match CSVs

**pytest_path:**
`tests/test_build_graph.py::TestSelfApplication::test_project_graph_node_counts_match_csvs`
**test_type:** integration **status:** passing **Verifies:** DC-003 guarantee —
"Node counts in graph match row counts in CSVs (verifiable post-build)"
(self-application variant)

Extends TC-019 by asserting that the number of nodes loaded into the graph
exactly matches the row counts in the source CSVs. This detects silent data loss
during import — a build that completes without error but drops rows.
