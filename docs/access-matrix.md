# Access matrix (role by endpoint)

Generated from `docs/access-matrix.toml` by `scripts/access_matrix.py`; a test fails
if any route of the five services is missing or if a declared gate differs from the
code. Roles: SO system-owner, RV reviewer, GO governance-officer, TA tenant-admin,
AU auditor (read-only), PA platform-admin. **Scope** says what the roles apply to:
`shared` (not tenant data), `tenant` (only the caller's tenants: other tenants'
records are "not found"), `platform`, `public` (probes and sign-in pages).
Gates: `require` (checked before the endpoint runs), `code` (checked per tenant or
per system inside the endpoint), `session` (control-centre pages: a signed-in user;
the services behind them check the user's token again), `public`.

## rulebook

| Method | Path | Gate | Roles | Services | Scope | Notes |
|---|---|---|---|---|---|---|
| POST | `/sources` | require | GO | - | shared |  |
| GET | `/sources` | require | AU, GO, RV, SO, TA | assessment-engine, connector-hub, control-centre-service, review-desk | shared |  |
| GET | `/sources/{instrument}/versions/{version}` | require | AU, GO, RV, SO, TA | assessment-engine, connector-hub, control-centre-service, review-desk | shared |  |
| GET | `/sources/{instrument}/versions/{version}/clauses/{number}` | require | AU, GO, RV, SO, TA | assessment-engine, connector-hub, control-centre-service, review-desk | shared |  |
| GET | `/sources/{instrument}/diff` | require | AU, GO, RV, SO, TA | assessment-engine, connector-hub, control-centre-service, review-desk | shared |  |
| POST | `/sources/{instrument}/diff` | require | AU, GO, RV, SO, TA | assessment-engine, connector-hub, control-centre-service, review-desk | shared |  |
| PUT | `/profiles/{name}` | require | GO | - | shared |  |
| GET | `/profiles` | require | AU, GO, RV, SO, TA | assessment-engine, connector-hub, control-centre-service, review-desk | shared |  |
| GET | `/profiles/{name}` | require | AU, GO, RV, SO, TA | assessment-engine, connector-hub, control-centre-service, review-desk | shared |  |
| PUT | `/inventory` | require | - | connector-hub | platform | replaces every tenant's systems; needs all-tenants scope |
| GET | `/inventory` | require | AU, RV, SO, TA | assessment-engine, connector-hub, control-centre-service, review-desk | tenant | systems of the caller's tenants only |
| GET | `/systems/{system_id}` | require | AU, RV, SO, TA | assessment-engine, connector-hub, control-centre-service, review-desk | tenant |  |
| PUT | `/systems/{system_id}/profiles` | require | TA | - | tenant | capability profile-assignment, in the system's tenant |
| POST | `/impact-reports` | require | AU, GO, RV, SO, TA | assessment-engine, connector-hub, control-centre-service, review-desk | tenant | shared controls; systems of the caller's tenants only |
| POST | `/drafts/batches` | require | GO | - | shared |  |
| GET | `/drafts/batches` | require | AU, GO, RV | assessment-engine | shared |  |
| GET | `/drafts/batches/{batch_id}` | require | AU, GO, RV | assessment-engine | shared |  |
| PUT | `/drafts/items/{item_id}/model/{lang}` | require | - | assessment-engine | shared |  |
| GET | `/drafts/log/verify` | require | AU, GO | - | shared |  |
| POST | `/drafts/sessions` | require | GO, RV | - | shared |  |
| POST | `/drafts/batches/{batch_id}/views` | require | GO, RV | - | shared |  |
| PUT | `/drafts/items/{item_id}` | require | GO, RV | - | shared |  |
| POST | `/drafts/items/{item_id}/approve` | require | GO | - | shared |  |
| POST | `/drafts/items/{item_id}/reject` | require | GO | - | shared |  |
| GET | `/drafts/batches/{batch_id}/publish-defaults` | require | AU, GO, RV | assessment-engine | shared |  |
| POST | `/drafts/batches/{batch_id}/publish` | require | GO | - | shared |  |
| GET | `/drafts/batches/{batch_id}/change-set` | require | AU, GO | - | shared |  |
| GET | `/drafts/log/export` | require | AU, GO | - | shared |  |
| GET | `/health` | public | - | - | public | probe |
| GET | `/ready` | public | - | - | public | probe |
| POST | `/catalogs` | require | GO | - | shared |  |
| GET | `/catalogs` | require | AU, GO, RV, SO, TA | assessment-engine, connector-hub, control-centre-service, review-desk | shared |  |
| GET | `/catalogs/{name}/versions/{version}` | require | AU, GO, RV, SO, TA | assessment-engine, connector-hub, control-centre-service, review-desk | shared |  |
| POST | `/catalogs/{name}/versions/{version}/retire-control/{control_id}` | require | GO | - | shared |  |
| POST | `/catalogs/{name}/diff` | require | AU, GO, RV, SO, TA | assessment-engine, connector-hub, control-centre-service, review-desk | shared |  |
| GET | `/catalogs/{name}/diff` | require | AU, GO, RV, SO, TA | assessment-engine, connector-hub, control-centre-service, review-desk | shared |  |
| POST | `/profiles/resolve` | require | AU, GO, RV, SO, TA | assessment-engine, connector-hub, control-centre-service, review-desk | shared |  |
| GET | `/controls/{control_id}` | require | AU, GO, RV, SO, TA | assessment-engine, connector-hub, control-centre-service, review-desk | shared |  |

## review-desk

| Method | Path | Gate | Roles | Services | Scope | Notes |
|---|---|---|---|---|---|---|
| GET | `/health` | public | - | - | public | probe |
| GET | `/ready` | public | - | - | public | probe |
| POST | `/intake/impact-report` | require | GO | connector-hub, control-centre-service | tenant |  |
| GET | `/queue` | require | AU, RV, SO, TA | assessment-engine, control-centre-service | tenant |  |
| GET | `/findings/{finding_id}` | require | AU, RV, SO, TA | assessment-engine, control-centre-service | tenant |  |
| PUT | `/findings/{finding_id}/assessment` | require | - | assessment-engine | tenant | engine drafts; the finding stays open |
| POST | `/findings/{finding_id}/open` | require | RV | - | tenant | a reviewer of the finding's tenant |
| POST | `/findings/{finding_id}/decisions` | require | RV | - | tenant | a reviewer of the finding's tenant; refused on conflict of interest |
| GET | `/poam` | require | AU, RV, SO, TA | assessment-engine, control-centre-service | tenant |  |
| GET | `/poam/{system_id}` | require | AU, RV, SO, TA | assessment-engine, control-centre-service | tenant |  |
| GET | `/findings/{finding_id}/decisions` | require | AU, RV, SO, TA | assessment-engine, control-centre-service | tenant |  |
| GET | `/decision-log/verify` | require | AU, RV, TA | - | tenant |  |
| GET | `/decision-log/checkpoint-status` | require | AU, RV, TA | - | tenant |  |
| GET | `/decision-log/export` | require | AU, RV, TA | - | tenant | records of the caller's tenants |
| POST | `/decision-log/verify-export` | require | AU, RV, TA | - | tenant |  |
| GET | `/decision-log/checkpoint` | require | AU, RV, TA | - | tenant |  |
| POST | `/forecast` | require | AU, GO, RV, TA | - | tenant |  |
| GET | `/forecast` | require | AU, GO, RV, TA | - | tenant |  |

## assessment-engine

| Method | Path | Gate | Roles | Services | Scope | Notes |
|---|---|---|---|---|---|---|
| GET | `/health` | public | - | - | public | probe |
| GET | `/ready` | public | - | - | public | probe |
| GET | `/evidence-policy` | require | AU, GO, PA, RV, SO, TA | control-centre-service, review-desk | tenant |  |
| POST | `/systems/{system_id}/evidence` | code | SO, RV | - | tenant | uploader recorded (conflict of interest); access-logged later |
| GET | `/systems/{system_id}/evidence` | code | SO, RV, TA, AU | - | tenant | metadata only, no text |
| GET | `/evidence/{document_id}/passages` | code | SO, RV, AU | - | tenant | evidence text |
| GET | `/systems/{system_id}/evidence/search` | code | SO, RV, AU | - | tenant | evidence text |
| PUT | `/systems/{system_id}/facts` | code | SO, RV | - | tenant | writer recorded (conflict of interest) |
| GET | `/systems/{system_id}/facts` | code | SO, RV, AU | - | tenant |  |
| GET | `/systems/{system_id}/provenance` | require | - | review-desk | tenant | who uploaded evidence or wrote facts (conflict of interest) |
| GET | `/systems/{system_id}/rule-checks` | code | SO, RV, AU | - | tenant |  |
| POST | `/assessments` | code | RV | - | tenant | drafts only; a person decides |
| GET | `/assessments/{assessment_id}` | code | SO, RV, AU | - | tenant |  |
| GET | `/runs/{run_id}/assessment-results` | code | SO, RV, AU | - | tenant | OSCAL assessment-results |
| POST | `/systems/{system_id}/assess-open-findings` | code | RV | - | tenant | drafts go to review-desk |
| POST | `/drafting/batches/{batch_id}/draft` | require | GO | - | tenant |  |

## connector-hub

| Method | Path | Gate | Roles | Services | Scope | Notes |
|---|---|---|---|---|---|---|
| GET | `/health` | public | - | - | public | probe |
| POST | `/inventory/sync` | require | TA | control-centre-service | platform | the sync job runs as connector-hub, all tenants |
| POST | `/tasks/sync-impact-report` | require | GO | control-centre-service, review-desk | shared |  |
| POST | `/tasks` | require | - | review-desk | shared |  |
| GET | `/tasks/notes` | require | AU, GO, RV, TA | review-desk | shared |  |
| POST | `/tasks/{correlation_id}/notes` | require | - | review-desk | shared |  |

## control-centre

| Method | Path | Gate | Roles | Services | Scope | Notes |
|---|---|---|---|---|---|---|
| GET | `/{lang}/policy-change` | session | - | - | tenant | signed-in user; the services check the user's token again |
| GET | `/{lang}/impact` | session | - | - | tenant | signed-in user; the services check the user's token again |
| GET | `/{lang}/review` | session | - | - | tenant | signed-in user; the services check the user's token again |
| GET | `/{lang}/review/{finding_id}` | session | - | - | tenant | signed-in user; the services check the user's token again |
| POST | `/{lang}/review/{finding_id}/evidence` | session | - | - | tenant | signed-in user; the services check the user's token again |
| POST | `/{lang}/review/{finding_id}/assess` | session | - | - | tenant | signed-in user; the services check the user's token again |
| POST | `/{lang}/review/{finding_id}/open` | session | - | - | tenant | signed-in user; the services check the user's token again |
| POST | `/{lang}/review/{finding_id}/decide` | session | - | - | tenant | signed-in user; the services check the user's token again |
| GET | `/{lang}/decision-log` | session | - | - | tenant | signed-in user; the services check the user's token again |
| GET | `/{lang}/inventory` | session | - | - | tenant | signed-in user; the services check the user's token again |
| GET | `/{lang}/drafts` | session | - | - | tenant | signed-in user; the services check the user's token again |
| POST | `/{lang}/drafts` | session | - | - | tenant | signed-in user; the services check the user's token again |
| GET | `/{lang}/drafts/{batch_id}` | session | - | - | tenant | signed-in user; the services check the user's token again |
| POST | `/{lang}/drafts/{batch_id}/items/{item_id}/edit` | session | - | - | tenant | signed-in user; the services check the user's token again |
| POST | `/{lang}/drafts/{batch_id}/items/{item_id}/{action}` | session | - | - | tenant | signed-in user; the services check the user's token again |
| POST | `/{lang}/drafts/{batch_id}/publish` | session | - | - | tenant | signed-in user; the services check the user's token again |
| GET | `/{lang}/sign-in` | public | - | - | public | sign-in page |
| POST | `/{lang}/sign-in/demo` | public | - | - | public | demo mode only (404 otherwise) |
| GET | `/auth/login` | public | - | - | public | OIDC (oidc mode only) |
| GET | `/auth/callback` | public | - | - | public | OIDC (oidc mode only) |
| POST | `/{lang}/sign-out` | public | - | - | public | ends the session |
| GET | `/internal/tenants` | require | - | assessment-engine, connector-hub, review-desk, rulebook | platform | hub services only |
| GET | `/health` | public | - | - | public | probe |
| GET | `/` | public | - | - | public | language choice |
| GET | `/{lang}/` | session | - | - | tenant | signed-in user; the services check the user's token again |

platform-admin holds no tenant role: it reaches no tenant data (break-glass grants
come in a later commit). Health and readiness probes are public on every service.
