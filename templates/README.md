# V-Model Document Templates

This directory contains four markdown templates for the core levels of the
V-model traceability framework. Each template corresponds to one node type in
the traceability graph and one CSV schema file.

These templates satisfy **DC-008** (V-Level Document Templates), which fulfils
**REQ-001** (V-Level Document Templates).

---

## The four templates

| Template               | Node type        | CSV file                              | Schema                                      |
| ---------------------- | ---------------- | ------------------------------------- | ------------------------------------------- |
| `requirement.md`       | Requirement      | `traceability/requirements.csv`       | `schemas/nodes/requirement.csvschema`       |
| `design_contract.md`   | DesignContract   | `traceability/design_contracts.csv`   | `schemas/nodes/design_contract.csvschema`   |
| `test_case.md`         | TestCase         | `traceability/test_cases.csv`         | `schemas/nodes/test_case.csvschema`         |
| `validation_result.md` | ValidationResult | `traceability/validation_results.csv` | `schemas/nodes/validation_result.csvschema` |

---

## How to use these templates

### Adding a new requirement

1. Open `requirement.md` and read the field guidance table.
2. Copy the blank CSV row at the bottom of the template.
3. Fill in all fields and append the row to `traceability/requirements.csv`.
4. Assign the next available `REQ-NNN` ID (check the CSV for the current highest
   number).

### Adding a new design contract

1. Open `design_contract.md` and read the field guidance.
2. Copy the blank CSV row and fill in all fields.
3. Append to `traceability/design_contracts.csv`.
4. Add a `FULFILLED_BY` edge row in `traceability/fulfilled_by.csv` linking the
   requirement to this contract.
5. When tests are written for this contract, add `VERIFIED_BY` edge rows in
   `traceability/verified_by.csv` linking this contract to each test case.

### Adding a new test case

1. Open `test_case.md` and read the field guidance.
2. Write the actual test function first. Add `@pytest.mark.traces('DC-NNN')` to
   the function.
3. Copy the blank CSV row and fill in the exact `pytest_path`.
4. Append to `traceability/test_cases.csv`.
5. Add a `VERIFIED_BY` edge row in `traceability/verified_by.csv` linking the
   design contract to this test case.

### Recording a validation result

1. Run the test suite (or the specific test) and note the execution timestamp.
2. Open `validation_result.md` and copy the blank CSV row.
3. Fill in `test_id`, `requirement_id`, `status`, `timestamp`, and a durable
   `evidence` reference (CI run URL or committed log path).
4. Append to `traceability/validation_results.csv`.
5. Add a `VALIDATES` edge row in `traceability/validates.csv` linking this
   result to the requirement.

---

## V-model flow

The four node types map to the four corners of the V-model:

```
Requirements                              Validation Results
     |                                           ^
     | FULFILLED_BY                   VALIDATES  |
     v                                           |
Design Contracts ---VERIFIED_BY---> Test Cases
```

A complete traceability path from requirement to validation looks like:

```
REQ-NNN --[FULFILLED_BY]--> DC-NNN --[VERIFIED_BY]--> TC-NNN <-- VR-NNN --[VALIDATES]--> REQ-NNN
```

Run `uv run python scripts/query_coverage.py <db_path>` to see which
requirements have incomplete paths.

---

## ID conventions

| Node type         | Prefix | Example   |
| ----------------- | ------ | --------- |
| Requirement       | `REQ-` | `REQ-001` |
| Design Contract   | `DC-`  | `DC-001`  |
| Test Case         | `TC-`  | `TC-001`  |
| Validation Result | `VR-`  | `VR-001`  |

Use three-digit zero-padded numbers. Increment from the current highest ID in
each CSV. Never reuse a retired ID — mark it `deprecated` instead.

---

## Validating your additions

After editing any CSV, rebuild the graph to verify referential integrity:

```bash
uv run python scripts/build_graph.py traceability/ schemas/ traceability.db
```

The build will fail with clear errors if any field is missing, any ID is
duplicated, or any edge references a non-existent node.
