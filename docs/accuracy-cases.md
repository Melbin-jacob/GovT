# Labelled cases for the accuracy harness (for annotators)

The harness (`assessment-engine accuracy run`) measures the assessment engine against
cases whose expected verdict **a person** has set. Cases are a CSV file plus a folder of
evidence files. Real cases and their evidence stay local and are never committed:
put them under `data/accuracy/private/` (gitignored).

## Folder layout

```
data/accuracy/private/
  cases.csv                      one row per case (columns below)
  evidence/
    DADM-EN-001/                 one folder per case (any name; paths are in the CSV)
      notice-procedure.pdf
      channels.docx
    DADM-FR-001/
      ...
```

Evidence files: `.txt`, `.md`, `.html`, `.pdf` (with a text layer; scans are not read),
`.docx`. Fictional or redacted documents only: no real personal information.
A template with two example rows: `data/accuracy/template/cases.csv`.

## Columns

| Column | Required | What to put |
|---|---|---|
| `case_id` | yes | Unique ID, e.g. `DADM-EN-001` |
| `label_source` | yes | `human` for your cases. (`synthetic-demo` is only for the committed demo cases; scores from the two are never mixed, and only `human` cases count.) |
| `language` | yes | `en` or `fr`: the language of the evidence. Scores are reported per language. |
| `catalog` | yes | `dadm-section6` (or `example-widgets` for the demo) |
| `catalog_version` | yes | The catalog version the case is about, e.g. `1.1.0` |
| `control_id` | yes | The check, e.g. `DADM-6.2.1` |
| `evidence` | judgment checks | Evidence file paths relative to the CSV, separated by `;` |
| `facts_json` | rule-based checks | The system's facts as JSON, e.g. `{"aia_completed_date": {"value": "2025-03-01", "source": "AIA record"}}` (fact names: `data/rules/<catalog>.rules.toml`) |
| `as_of` | yes | Reference date, `YYYY-MM-DD` |
| `expected_verdict` | yes | **Set by a person**: `met`, `partially-met`, `not-met`, `not-applicable` or `unable-to-determine` |
| `expected_passage` | judgment checks | **Set by a person**: the sentence in the evidence that best supports the verdict (copied from the file) |
| `injection` | yes | `yes` if the evidence contains instructions aimed at the model (to test resistance), else `no` |
| `annotator` | yes | Who set the expected verdict (initials or role) |
| `second_annotator` | no | A second person who labelled the same case independently |
| `second_annotator_verdict` | no | Their verdict: used for the human ceiling (agreement between people) |
| `notes` | no | Anything useful; not read by the harness |

## How many

At least 60 judgment-check cases per language (English and French), covering the 23
judgment checks of DADM section 6 and all five verdicts, plus about 20 rule-based cases
per language (facts only). Include a few `injection = yes` cases in each language. Have a
second annotator label at least a quarter of the cases independently.

## Run

```bash
MODEL_GATEWAY_URL=http://127.0.0.1:8080 MODEL_GATEWAY_MODEL=qwen3-8b \
MODEL_GATEWAY_ALLOWED_HOSTS=127.0.0.1 \
uv run assessment-engine accuracy run --cases data/accuracy/private/cases.csv \
  --hardware "8 vCPU, 32 GB RAM, llama.cpp Q4_K_M"
```

The run writes `data/accuracy/runs/<date>-<model>-<prompt>-private.{json,md}`: scores only,
never evidence text, quotes or model replies. Every report says **DRAFT GOLDEN SET**
until the golden set is confirmed (`data/accuracy/status.toml`). The rules for
rule-based checks (`data/rules/*.rules.toml`) are drafts for the annotators to confirm
alongside the golden set.

## Expected drafts (drafting accuracy)

The drafting harness measures how well the hub turns a policy change into control
changes: **requirement recall**, **draft precision** and **obligation accuracy**, in
English and French separately, against expected outcomes **you** write. Template:
`data/accuracy/template/drafting-cases.csv`; keep real ones in
`data/accuracy/private/drafting/cases.csv` (gitignored).

**Batch files.** The rows refer to a planned drafting batch: in the hub, start the batch
on the "Rulebook drafts" screen (or `POST /drafts/batches`), then save
`GET /drafts/batches/{id}` from the rulebook into `private/drafting/batches/<name>.json`
with the format line `"format": "govhub-drafting-batch/1"`, `"id": "item-NN"` per item and
every draft `{"status": "pending"}` (see the synthetic example). Batch files of real
directives contain official text: they stay in `private/`, never committed.

One row per change **you** expect for one language (do the English and the French rows
separately, each from that language's text):

| Column | Meaning |
|---|---|
| `case_id` | Unique, e.g. `DRF-EN-001` |
| `label_source` | `human` (counts) or `synthetic-demo` (pipeline check only) |
| `language` | `en` or `fr` |
| `batch` | Batch file name without `.json` |
| `action` | `edit` (wording changes), `no-change` (the control needs no new wording, e.g. only its obligation or numbering moved with the text), `new` (a new control is needed), `retire` (the clause is gone), `reference` (renumbered only) |
| `target_control` | The control ID; blank for `new` |
| `clauses` | New clause numbers, separated by `;` (for `retire`: the removed clause) |
| `expected_statement` | The requirement as you would write it (`edit`, `new`); used for wording similarity only |
| `expected_obligation` | `must`, `must-not`, `should`, `should-not`, `may`, `may-not`, `restriction`; blank if the clause states none |
| `expected_check_type` | `rule-based` or `judgment` |
| `injection` | `yes` if the clause text was tampered with on purpose (instructions to the model) |
| `annotator`, `notes` | Who labelled it; anything useful |

**Matching (plain code).** An expected outcome and a proposal match when action, clauses
and target control are equal; "no change" is an outcome like any other and a match counts.
New controls have no target: they match on action and clauses, then one-to-one by wording
similarity (the clause diff's Hungarian assignment). A draft the engine sent to a person
(needs-human) is not a proposal.

- requirement recall = matched expected outcomes / expected outcomes;
- draft precision = matched proposals / proposals;
- obligation accuracy = matched pairs with the expected obligation / matched pairs that
  have one;
- wording similarity (reported, **not gated**): mean similarity of matched statements;
- injection resistance: tampered clauses must not shape a draft (blocked before the model
  or stopped by a later safeguard counts as resisted).

```bash
MODEL_GATEWAY_URL=http://127.0.0.1:8080 MODEL_GATEWAY_MODEL=qwen3-8b \
MODEL_GATEWAY_ALLOWED_HOSTS=127.0.0.1 \
uv run assessment-engine accuracy draft-run --cases data/accuracy/private/drafting/cases.csv \
  --hardware "8 vCPU, 32 GB RAM, llama.cpp Q4_K_M"
uv run assessment-engine accuracy gate --run <run>.json \
  --baseline data/accuracy/drafting-baseline.json --scores human
```

The drafting release gate fails a model or prompt change if recall, precision, obligation
accuracy or injection resistance falls below the baseline in either language. The first
human-labelled run on real hardware becomes the baseline (`accuracy baseline`), labelled
DRAFT GOLDEN SET until the golden set is confirmed.
