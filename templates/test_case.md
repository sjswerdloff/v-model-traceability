# Test Case Template

**Schema:** `schemas/nodes/test_case.csvschema` **CSV file:**
`traceability/test_cases.csv`

This template covers one test case entry. A test case node in the traceability
graph links a concrete pytest function to the design contract guarantee it
verifies. The node exists to make the relationship explicit and queryable — it
is not a substitute for reading the test code.

---

## How to write a good test case entry

- The `title` should state WHICH guarantee of the contract is being tested, not
  just what the test does mechanically.
- The `pytest_path` must be an exact, importable path. It is cross-checked
  against live code by DC-007 (Test-Code Linkage Verifier).
- Add a `@pytest.mark.traces('DC-NNN')` marker in the test function so the
  verifier can confirm the linkage in both directions.
- One test case node per test function. Do not aggregate multiple test functions
  under one TC entry.

---

## CSV row format

```
id,title,pytest_path,test_type,status
```

### Field guidance

| Field         | Type   | Valid values                                           | Notes                                                                                                                                                                   |
| ------------- | ------ | ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`          | string | `TC-NNN`                                               | Unique within the project. Never reuse a retired ID.                                                                                                                    |
| `title`       | string | Short phrase                                           | Describes which contract guarantee this test verifies.                                                                                                                  |
| `pytest_path` | string | `path/to/test_file.py::ClassName::method_name`         | Fully qualified pytest node ID. Must exactly match the live test function.                                                                                              |
| `test_type`   | enum   | `unit` `integration` `end_to_end` `validation`         | `unit`: single function/class. `integration`: multiple components or real I/O. `end_to_end`: full pipeline. `validation`: formal acceptance test against a requirement. |
| `status`      | enum   | `draft` `implemented` `passing` `failing` `deprecated` | Current execution status. Update to `passing` or `failing` after CI runs.                                                                                               |

### test_type selection guide

| Type          | Use when                                                                                   |
| ------------- | ------------------------------------------------------------------------------------------ |
| `unit`        | Testing a single function or class in isolation, with mocks for dependencies               |
| `integration` | Testing two or more real components together, or touching the filesystem/database          |
| `end_to_end`  | Testing the full pipeline from input to output with real data                              |
| `validation`  | Formal test providing evidence against a specific requirement (maps to a ValidationResult) |

### Status lifecycle

```
draft --> implemented --> passing
                     \--> failing --> (fix) --> passing
                                           |
                                      deprecated (if test is removed)
```

---

## Filled-in examples

These examples are drawn from the project's own `traceability/test_cases.csv`.

**CSV rows:**

```csv
TC-001,Valid CSV passes schema validation,tests/test_validate_csv.py::TestSchemaValidator::test_valid_csv_passes,unit,passing
TC-013,Build from valid CSVs,tests/test_build_graph.py::TestGraphBuild::test_builds_database_from_valid_csvs,integration,passing
```

**Narrative form:**

### TC-001: Valid CSV passes schema validation

**pytest_path:**
`tests/test_validate_csv.py::TestSchemaValidator::test_valid_csv_passes`
**test_type:** unit **status:** passing **Verifies:** DC-001 guarantee — "CSV
structure matches schema header exactly"

---

### TC-013: Build from valid CSVs

**pytest_path:**
`tests/test_build_graph.py::TestGraphBuild::test_builds_database_from_valid_csvs`
**test_type:** integration **status:** passing **Verifies:** DC-003 guarantee —
"Build is idempotent; reproducible from CSVs alone"

---

## Blank template (copy this)

**CSV row:**

```csv
TC-NNN,<Which guarantee this verifies>,<tests/test_module.py::TestClass::test_method_name>,<test_type>,draft
```

**Narrative form:**

### TC-NNN: \<Which guarantee this verifies\>

**pytest_path:** `tests/<test_file.py>::<TestClass>::<test_method_name>`
**test_type:** \<unit | integration | end_to_end | validation\> **status:**
draft **Verifies:** \<DC-NNN guarantee — "quoted guarantee text"\>

---

## Corresponding pytest marker (add to test function)

```python
import pytest

@pytest.mark.traces("DC-NNN")
def test_method_name(self):
    """Verifies DC-NNN guarantee: <quoted guarantee text>."""
    ...
```

The `@pytest.mark.traces` marker is read by DC-007 (Test-Code Linkage Verifier)
to confirm that every TC node in the graph has a real test function and every
marked test function has a TC node.

---

## Common mistakes to avoid

- **Stale pytest_path:** If a test is renamed or moved, update the CSV
  immediately. DC-007 will flag the mismatch, but the graph will be wrong until
  the CSV is corrected.
- **Aggregating tests:** Do not create one TC node for a whole test class. Each
  method that verifies a distinct guarantee gets its own TC node.
- **Title describes the test, not the guarantee:** "test_valid_csv" is a test
  name. "Valid CSV passes schema validation" describes the guarantee under test.
- **Leaving status as draft after implementation:** Update to `implemented` when
  the test exists but has not yet run, and `passing` or `failing` after CI.
