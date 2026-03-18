# Requirement Template

**Schema:** `schemas/nodes/requirement.csvschema` **CSV file:**
`traceability/requirements.csv`

This template covers one requirement entry. Copy the CSV row format below into
`traceability/requirements.csv`, or use the narrative form for documentation.

---

## How to write a good requirement

A requirement describes WHAT the system shall do, not HOW. Use SHALL for
mandatory behaviour and SHOULD for recommendations. Keep each requirement
atomic: one testable claim per entry.

---

## CSV row format

```
id,title,description,priority,status,source
```

### Field guidance

| Field         | Type   | Valid values                                             | Notes                                                                         |
| ------------- | ------ | -------------------------------------------------------- | ----------------------------------------------------------------------------- |
| `id`          | string | `REQ-NNN`                                                | Unique within the project. Never reuse a retired ID.                          |
| `title`       | string | Short phrase                                             | Human-readable label used in reports and cross-references. 50 chars or fewer. |
| `description` | string | Full sentence(s)                                         | The normative requirement text. Use SHALL/SHOULD.                             |
| `priority`    | enum   | `critical` `high` `medium` `low`                         | `critical` means failure is a safety or compliance blocker.                   |
| `status`      | enum   | `draft` `approved` `implemented` `verified` `deprecated` | Progress through the V-model lifecycle.                                       |
| `source`      | string | Person / document / date                                 | Who or what originated this requirement. Aids change traceability.            |

### Status lifecycle

```
draft --> approved --> implemented --> verified
                                           |
                                      deprecated (if retired)
```

---

## Filled-in example

This example is drawn from the project's own `traceability/requirements.csv`.

**CSV row:**

```csv
REQ-001,V-Level Document Templates,Provide markdown templates for Requirements/Design/Test/Validation levels,high,draft,Dad direction 2026-02-19
```

**Narrative form:**

### REQ-001: V-Level Document Templates

**Priority:** high **Status:** draft **Source:** Dad direction 2026-02-19

**Description:**

The framework SHALL provide markdown templates for four core V-model levels:
Requirements, Design Contracts, Test Cases, and Validation Results. Each
template SHALL include guidance on what constitutes a complete entry at that
level.

---

## Blank template (copy this)

**CSV row:**

```csv
REQ-NNN,<Short title>,<The system SHALL ...>,<priority>,draft,<Source person/doc YYYY-MM-DD>
```

**Narrative form:**

### REQ-NNN: \<Short title\>

**Priority:** \<critical | high | medium | low\> **Status:** draft **Source:**
\<Person or document, YYYY-MM-DD\>

**Description:**

\<The system SHALL ... Full normative text. One testable claim.\>

---

## Common mistakes to avoid

- **Vague SHALL:** "The system shall be fast" — not testable. Write "The system
  SHALL respond within 200 ms for inputs under 1 MB."
- **Multiple claims in one requirement:** Split into REQ-NNN and REQ-NNN+1.
- **Solution in a requirement:** "SHALL use PostgreSQL" is a design decision,
  not a requirement. Write "SHALL persist data durably across restarts."
- **Skipping source:** If origin is unknown, write `unknown` rather than leaving
  the field empty. Missing source means the requirement can never be traced to a
  decision.
