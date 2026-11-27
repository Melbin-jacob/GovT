# control-centre

Bilingual (English/French) web UI for the evaluator demo (Milestone 4). Pages are rendered
on the server (FastAPI + Jinja2, plain HTML forms, no JavaScript framework, nothing loaded
from outside the service). It reads from rulebook, review-desk and connector-hub over the
internal network; the only writes are review actions and log verification, through
review-desk's own endpoints.

**Demo only: no authentication.** Every page says so. The UI sends a fixed placeholder
identity (`demo-reviewer-01`, role `reviewer`) to review-desk. Like review-desk, it must be
bound to localhost or the internal network only (Compose: `127.0.0.1:8004`) and never
exposed.

TODO(control-centre): OIDC sign-in (Entra ID compatible), central role enforcement, tenant
isolation, residency/retention/deletion settings, vendor access off by default.

| Path | Screen |
|---|---|
| `/` | Language selection (English \| Français) |
| `/en/…`, `/fr/…` | The same screens in each language |
| `…/policy-change` | 1. Clause diff between two source versions |
| `…/impact` | 2. Impact report, tasks, forecast |
| `…/review` | 3. Review queue, finding detail, five actions |
| `…/decision-log` | 4. Decision log, verification, external checkpoints |
| `…/inventory` | 5. System inventory with data gaps |

UI strings: `src/control_centre/locales/{en,fr}.toml` (same keys; a test enforces it).
French strings and their provenance: `docs/fr-ui-strings.md`.
