# Validation Result Template

**Schema:** `schemas/nodes/validation_result.csvschema` **CSV file:**
`traceability/validation_results.csv`

This template covers one validation result entry. A validation result records a
specific execution of a test case and links that execution to the requirement it
validates. It is the bottom-right corner of the V-model: evidence that a
requirement was verified in practice, not just in design.

---

## How to write a good validation result

- One VR node per test execution that provides formal evidence against a
  requirement. Routine CI passes do not all require VR nodes — record VR entries
  for milestone executions (release gates, acceptance tests, formal reviews).
- The `evidence` field should point to something durable: a CI run URL, a log
  file committed to the repo, or a test report artifact. A VR with no evidence
  reference is an assertion, not evidence.
- `timestamp` is the actual execution time, not the time the CSV row was
  written.
- If a test fails, record the VR with `status: fail`. Do not omit failed
  results. Failures are as important as passes for traceability.

---

## CSV row format

```
id,test_id,requirement_id,status,timestamp,evidence
```

### Field guidance

| Field            | Type   | Valid values                 | Notes                                                                                                        |
| ---------------- | ------ | ---------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `id`             | string | `VR-NNN`                     | Unique within the project. Never reuse a retired ID.                                                         |
| `test_id`        | string | `TC-NNN`                     | ID of the TestCase node that was executed. Must reference an existing TC entry.                              |
| `requirement_id` | string | `REQ-NNN`                    | ID of the Requirement node being validated. Must reference an existing REQ entry.                            |
| `status`         | enum   | `pass` `fail` `skip` `error` | Outcome of this specific execution. `error` means the test infrastructure failed, not the system under test. |
| `timestamp`      | string | ISO 8601                     | Date and time of execution. Format: `YYYY-MM-DDTHH:MM:SSZ` or with offset.                                   |
| `evidence`       | string | URL or file path             | Durable reference to the test output, CI run, log file, or report artifact.                                  |

### Status meanings

| Status  | Meaning                                                       |
| ------- | ------------------------------------------------------------- |
| `pass`  | Test executed and all assertions succeeded                    |
| `fail`  | Test executed and at least one assertion failed               |
| `skip`  | Test was skipped (e.g., missing dependency, conditional skip) |
| `error` | Test infrastructure failed before assertions could run        |

---

## Filled-in examples

These examples are constructed from the project's test cases and requirements.
(No `validation_results.csv` exists yet — these show what the first entries
would look like after CI runs.)

**CSV rows:**

```csv
VR-001,TC-001,REQ-012,pass,2026-02-20T14:32:00Z,https://ci.example.com/runs/42#TC-001
VR-002,TC-013,REQ-004,pass,2026-02-20T14:35:17Z,https://ci.example.com/runs/42#TC-013
VR-003,TC-017,REQ-012,pass,2026-02-20T14:35:22Z,https://ci.example.com/runs/42#TC-017
```

**Narrative form:**

### VR-001

**test_id:** TC-001 (Valid CSV passes schema validation) **requirement_id:**
REQ-012 (Input Validation) **status:** pass **timestamp:** 2026-02-20T14:32:00Z
**evidence:** https://ci.example.com/runs/42#TC-001

This execution confirms that REQ-012's requirement for input validation is
satisfied: a well-formed CSV passes the schema validator without errors.

---

### VR-002

**test_id:** TC-013 (Build from valid CSVs) **requirement_id:** REQ-004 (Graph
Database Build) **status:** pass **timestamp:** 2026-02-20T14:35:17Z
**evidence:** https://ci.example.com/runs/42#TC-013

This execution confirms that REQ-004's requirement for graph database build is
satisfied: the pipeline builds a queryable Kuzu database from valid CSVs.

---

## Blank template (copy this)

**CSV row:**

```csv
VR-NNN,TC-NNN,REQ-NNN,<status>,<YYYY-MM-DDTHH:MM:SSZ>,<evidence URL or path>
```

**Narrative form:**

### VR-NNN

**test_id:** TC-NNN (\<test title\>) **requirement_id:** REQ-NNN (\<requirement
title\>) **status:** \<pass | fail | skip | error\> **timestamp:**
\<YYYY-MM-DDTHH:MM:SSZ\> **evidence:** \<URL to CI run, path to log file, or
report artifact\>

\<Optional: one sentence describing what this execution demonstrates.\>

---

## Relationship to the V-model graph

Validation results connect to the graph via the `validates` edge:

```
ValidationResult --[VALIDATES]--> Requirement
```

The `VALIDATES` edge uses the `requirement_id` field. The `test_id` field allows
DC-006 (Coverage Report) to check whether test cases have any execution record
(Section 3: tests with no validation results).

To be counted in the end-to-end coverage path (Section 4 of the coverage
report), a validation result must exist on the path:

```
Requirement --[FULFILLED_BY]--> DesignContract --[VERIFIED_BY]--> TestCase <-- ValidationResult --[VALIDATES]--> Requirement
```

---

## Common mistakes to avoid

- **Recording only passes:** Failed and skipped results are traceability data. A
  requirement with only skipped validation results is not validated.
- **Vague evidence field:** "pytest output" is not a durable reference. Use a CI
  run URL, a committed log file path, or a test report artifact path.
- **Wrong timestamp:** Use the test execution time, not the time the CSV row was
  written. For CI runs, use the run start timestamp.
- **Dangling test_id or requirement_id:** The graph build (DC-003) will fail if
  `test_id` or `requirement_id` do not reference existing nodes. Check the CSV
  before committing.
