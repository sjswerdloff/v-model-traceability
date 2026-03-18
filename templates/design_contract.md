# Design Contract Template

**Schema:** `schemas/nodes/design_contract.csvschema` **CSV file:**
`traceability/design_contracts.csv`

This template covers one design contract entry. A design contract describes what
a module GUARANTEES at its interface — inputs it accepts, outputs it produces,
invariants it maintains, and how it behaves under error. A test author should be
able to derive the full test suite from a contract alone, without reading the
implementation.

---

## How to write a good design contract

- Focus on the module boundary, not internals.
- State guarantees as verifiable invariants (idempotency, atomicity,
  completeness).
- Be explicit about error semantics: what exceptions are raised and when, versus
  what is returned as structured error data.
- A contract that cannot be tested is not a contract — it is a comment.

---

## CSV row format

```
id,title,module,inputs,outputs,guarantees,error_semantics,status
```

### Field guidance

| Field             | Type   | Valid values                                             | Notes                                                                                    |
| ----------------- | ------ | -------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `id`              | string | `DC-NNN`                                                 | Unique within the project. Never reuse a retired ID.                                     |
| `title`           | string | Short phrase                                             | Human-readable name used in reports and cross-references.                                |
| `module`          | string | File path                                                | Relative path to the source file or directory this contract describes.                   |
| `inputs`          | string | Comma-separated list                                     | Parameter names with type and constraint hints. Quote multi-word values in the CSV cell. |
| `outputs`         | string | Description                                              | What the module returns on success. Include type and key properties.                     |
| `guarantees`      | string | Invariant list                                           | Verifiable invariants separated by semicolons. Each should be independently testable.    |
| `error_semantics` | string | Error description                                        | Exactly which exceptions are raised and when, versus which errors are returned as data.  |
| `status`          | enum   | `draft` `approved` `implemented` `verified` `deprecated` | Mirrors the requirement status lifecycle.                                                |

### Status lifecycle

```
draft --> approved --> implemented --> verified
                                           |
                                      deprecated (if retired)
```

---

## Filled-in example

This example is drawn from the project's own
`traceability/design_contracts.csv`.

**CSV row:**

```csv
DC-001,CSV Schema Validator,scripts/validate_csv.py,"csv_path, schema_path","validated rows or error list","all errors collected; no duplicate IDs; schema match","result object with valid+errors; FileNotFoundError for missing files",draft
```

**Narrative form:**

### DC-001: CSV Schema Validator

**Module:** `scripts/validate_csv.py` **Status:** draft **Fulfills:** REQ-012
(Input Validation)

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
- Never raises exceptions for data problems — all data issues are in the errors
  list
- Raises `FileNotFoundError` for missing files
- Raises `SchemaError` for unparseable schema files

---

## Blank template (copy this)

**CSV row:**

```csv
DC-NNN,<Short title>,<scripts/module.py>,"<input_a, input_b>","<output description>","<guarantee 1; guarantee 2; guarantee 3>","<exception semantics>",draft
```

**Narrative form:**

### DC-NNN: \<Short title\>

**Module:** `<scripts/module.py>` **Status:** draft **Fulfills:** \<REQ-NNN
(Requirement title)\> **Depends on:** \<DC-NNN (if this contract builds on
another)\>

**Inputs:**

- `<param_name>`: \<Type and constraint description\>
- `<param_name>`: \<Type and constraint description\>

**Outputs:**

- \<What is returned on success, including type and key properties\>

**Guarantees:**

- \<Verifiable invariant 1 — should map directly to a test case\>
- \<Verifiable invariant 2\>
- \<Verifiable invariant 3\>

**Error Semantics:**

- \<Which errors are returned as structured data vs raised as exceptions\>
- \<What triggers each exception\>

---

## Common mistakes to avoid

- **Omitting error semantics:** "Raises an error" is not a contract. Specify
  which exception class and what precondition violation triggers it.
- **Implementation detail in guarantees:** "Uses a hash table for deduplication"
  belongs in code comments, not a contract.
- **Untestable guarantee:** Every guarantee should map to at least one test
  case. If you cannot write the test, rewrite the guarantee.
- **Missing module path:** The `module` field is used by DC-007 (Test-Code
  Linkage Verifier) to cross-reference contracts against actual code. Use the
  correct relative path from the project root.
