# Requirements: Edge CSV Generator

**Author:** cora-2f1e43dc
**Date:** 2026-05-12
**Status:** Draft — awaiting review from connor-227743e6 and vivian-1a61bc9a
**Validation data:** python-tesseron/traceability/ (272 hand-written edges)

## Purpose

Automate generation of traceability edge CSVs (fulfilled_by.csv and verified_by.csv) from references embedded in the node CSVs and source files. Eliminates manual edge authoring while preserving full V-model traceability.

## Scope

This tool generates two edge types:
- **fulfilled_by.csv**: Requirement → Design Contract (REQ → DC)
- **verified_by.csv**: Design Contract → Test Case (DC → TC)

---

## Inputs

### EDGE-REQ-001: Input files for fulfilled_by generation

The generator MUST accept `design_contracts.csv` as input for fulfilled_by edge derivation. Each design contract row contains fields per the design_contract.csvschema: `id, title, module, inputs, outputs, guarantees, error_semantics, status`.

### EDGE-REQ-002: Input files for verified_by generation

The generator MUST accept test source files (pytest `.py` files) and `test_cases.csv` as inputs for verified_by edge derivation.

### EDGE-REQ-003: Requirements CSV for validation

The generator MUST accept `requirements.csv` to validate that all referenced requirement IDs exist.

### EDGE-REQ-004: Design contracts CSV for validation

The generator MUST accept `design_contracts.csv` to validate that all referenced design contract IDs exist.

### EDGE-REQ-005: Test cases CSV for validation

The generator MUST accept `test_cases.csv` to validate that all referenced test case IDs exist.

---

## Derivation Rules — fulfilled_by (REQ → DC)

### EDGE-REQ-010: Source of REQ→DC references

The generator MUST derive fulfilled_by edges from requirement IDs referenced in design contract fields. Requirement IDs (pattern `REQ-\d{3}`) MAY appear in any text field of a design contract row (guarantees, error_semantics, inputs, outputs).

### EDGE-REQ-011: Alternative source — module docstrings

The generator SHOULD also scan implementation module docstrings for `REQ-\d{3}` references and associate them with the design contract whose `module` field matches that source file.

### EDGE-REQ-012: Completeness determination

The generator MUST assign completeness as `full` when a requirement is referenced by exactly one design contract, and `partial` when referenced by multiple design contracts.

### EDGE-REQ-013: One edge per REQ-DC pair

The generator MUST produce exactly one row per unique (requirement_id, design_contract_id) pair. Duplicate references within the same DC MUST NOT produce duplicate edges.

---

## Derivation Rules — verified_by (DC → TC)

### EDGE-REQ-020: Source of DC→TC references — test docstrings

The generator MUST derive verified_by edges from test function docstrings. Each test function's docstring contains a test ID (pattern `(AT|WF|ST|ER|CP|SEC|API)-\d{2}`) and requirement IDs (pattern `REQ-\d{3}`).

### EDGE-REQ-021: DC assignment via requirement chain

The generator MUST determine which design contract a test case verifies by following the requirement chain: test references REQ-NNN → fulfilled_by maps REQ-NNN to DC-NNN → therefore the test verifies DC-NNN.

### EDGE-REQ-022: Direct DC references in test docstrings

The generator SHOULD also recognize direct `DC-\d{3}` references in test docstrings, if present, as explicit verified_by edges.

### EDGE-REQ-023: Coverage determination

The generator MUST assign coverage as `full` when a test case verifies requirements that are all fulfilled by the same single DC, and `partial` when the test's requirements span multiple DCs.

### EDGE-REQ-024: One edge per DC-TC pair

The generator MUST produce exactly one row per unique (design_contract_id, test_case_id) pair.

---

## Output Format

### EDGE-REQ-030: fulfilled_by.csv format

The generator MUST produce `fulfilled_by.csv` with columns: `requirement_id,design_contract_id,completeness` per the fulfilled_by.csvschema. The file MUST include a header row.

### EDGE-REQ-031: verified_by.csv format

The generator MUST produce `verified_by.csv` with columns: `design_contract_id,test_case_id,coverage` per the verified_by.csvschema. The file MUST include a header row.

### EDGE-REQ-032: Deterministic ordering

The generator MUST produce rows sorted by the first column, then by the second column. This ensures deterministic output for diff-based review.

### EDGE-REQ-033: Idempotent output

Running the generator twice on the same inputs MUST produce identical output.

---

## Validation

### EDGE-REQ-040: Referential integrity — requirements

The generator MUST verify that every requirement_id in fulfilled_by output exists in requirements.csv. The generator MUST report and fail on phantom requirement references.

### EDGE-REQ-041: Referential integrity — design contracts

The generator MUST verify that every design_contract_id in both fulfilled_by and verified_by output exists in design_contracts.csv. The generator MUST report and fail on phantom DC references.

### EDGE-REQ-042: Referential integrity — test cases

The generator MUST verify that every test_case_id in verified_by output exists in test_cases.csv. The generator MUST report and fail on phantom TC references.

### EDGE-REQ-043: Orphan detection — requirements without DCs

The generator SHOULD warn (not fail) when a requirement has no fulfilled_by edge. These are potentially unimplemented requirements.

### EDGE-REQ-044: Orphan detection — DCs without TCs

The generator SHOULD warn (not fail) when a design contract has no verified_by edge. These are potentially untested contracts.

---

## Validation Against Hand-Written Edges

### EDGE-REQ-050: Golden dataset

The generator MUST be validated against python-tesseron's hand-written edge CSVs (115 fulfilled_by edges, 157 verified_by edges) as a golden dataset. Generated output MUST match the hand-written edges exactly, or deviations MUST be individually justified and reviewed.

### EDGE-REQ-051: Regression testing

The v-model-traceability test suite MUST include a test that runs the generator against the python-tesseron traceability data and compares output to the committed edge CSVs.

---

## CLI Interface

### EDGE-REQ-060: Command-line invocation

The generator MUST be invocable as: `python -m v_model_traceability.generate_edges <traceability_dir> [--tests-dir <path>] [--src-dir <path>]`

### EDGE-REQ-061: Exit codes

The generator MUST exit 0 on success, 1 on validation failure, 2 on missing input files.

### EDGE-REQ-062: Quiet by default

The generator MUST produce one summary line on success and one error line with details on failure. A `--verbose` flag SHOULD enable detailed output including all generated edges.

---

## Edge Cases

### EDGE-REQ-070: Requirements referenced by zero DCs

A requirement with no DC reference MUST NOT appear in fulfilled_by output. A warning SHOULD be emitted per EDGE-REQ-043.

### EDGE-REQ-071: Test cases referencing requirements not in any DC

When a test references a REQ that has no fulfilled_by edge, the generator MUST NOT produce a verified_by edge for that test-DC pair. A warning SHOULD be emitted.

### EDGE-REQ-072: Design contracts with no REQ references in any field

A DC with no parseable REQ references MUST NOT appear in fulfilled_by output. A warning SHOULD be emitted.

### EDGE-REQ-073: Circular or self-referencing edges

The generator MUST NOT produce edges where source equals target (e.g., a DC referencing itself). This is structurally impossible given the node types but MUST be guarded.
