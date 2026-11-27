# assessment-engine

Milestone 5. Assesses each affected (system, control) pair:

- **rule-based checks** in plain code, against structured facts about the system
  (`data/rules/*.rules.toml`, unverified drafts until the annotators confirm them);
- **judgment checks** drafted by a self-hosted model through the model gateway, from the
  control statement and the best evidence passages. One of five verdicts, a confidence
  score, the cited passage (checked word for word) and the reasoning. Anything
  unparseable, unsupported or below the confidence threshold is *unable to determine*.

The model never closes a finding: results replace the placeholder findings in the
review-desk queue and a person decides. Evidence is untrusted (prompt-injection defence)
and may be personal or Protected: stored only on its own volume, optionally encrypted by
the service, never logged. Internal only (Compose: `127.0.0.1:8005`).
