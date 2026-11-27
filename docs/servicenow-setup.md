# ServiceNow setup (Personal Developer Instance)

The connector uses only the Table API, one custom table, two custom fields and one custom
role. Everything below is done as an administrator on **your developer instance**; the hub
itself never gets `admin`. All demo records are **fictional**.

The field names below match `data/config/servicenow-mapping.toml`. If you name anything
differently, change the mapping file, not the code.

## 1. Role

*All > System Security > Roles > New*

| Field | Value |
|---|---|
| Name | `u_govhub_task_writer` |
| Description | GovHub integration: read and write GovHub tasks |

## 2. Task table `u_govhub_task` (extends Task)

*All > System Definition > Tables > New*

| Field | Value |
|---|---|
| Label | `GovHub Task` |
| Name | `u_govhub_task` (ServiceNow adds the `u_` prefix if you type `govhub_task`) |
| Extends table | `Task [task]` |
| Create module | optional (adds a menu entry to browse the tasks) |
| *Controls* tab > Auto-number | on, prefix `GOVT` |
| *Controls* tab > Create access controls | **on** |
| *Controls* tab > User role | `u_govhub_task_writer` |

It inherits everything the connector writes: `short_description`, `description`,
`assignment_group`, `assigned_to`, `priority`, `due_date`, `state`, `correlation_id`,
`correlation_display`, `cmdb_ci`, `work_notes`.

Then add two columns (*Columns* related list > New):

| Column label | Column name | Type | Max length |
|---|---|---|---|
| GovHub type | `u_govhub_type` | String | 40 |
| GovHub reference | `u_govhub_reference` | String | 100 |

`u_govhub_type` holds `reassessment`, `remediation`, `evidence-request`, `data-gap` or
`smoke`; `u_govhub_reference` holds the impact-report ID or POA&M item UUID.

## 3. Access controls

"Create access controls" (step 2) generates read, write, create and delete ACLs on
`u_govhub_task` for `u_govhub_task_writer`. Review them:

*All > System Security > Access Control (ACL)*, filter *Name starts with* `u_govhub_task`
(elevate to `security_admin` to edit).

| Operation | Keep? |
|---|---|
| read | yes, role `u_govhub_task_writer` |
| write | yes, role `u_govhub_task_writer` |
| create | yes, role `u_govhub_task_writer` |
| delete | **deactivate**: the hub never deletes tasks |

## 4. AI-system inventory fields on `cmdb_ci_business_app`

*All > System Definition > Tables*, open `cmdb_ci_business_app` (Business Application),
*Columns* > New:

| Column label | Column name | Type | Choices / length |
|---|---|---|---|
| AIA impact level | `u_aia_impact_level` | Choice | values `1`, `2`, `3`, `4`, labels `I`, `II`, `III`, `IV` |
| GovHub profiles | `u_govhub_profiles` | String | 255 (`;`-separated profile names) |

Standard fields the connector reads: `name`, `correlation_id` (the GovHub system ID,
e.g. `SYS-001`), `owned_by` (owner; the connector dot-walks to `owned_by.email`),
`managed_by_group` (tenant group), `department`, `install_status` (lifecycle:
Installed → production, In Maintenance → pilot, On Order / Pending Install / In Stock →
development, Retired → retired), `short_description`.

Reading the CMDB needs `cmdb_read`, which the base instance grants read access with.

## 5. Integration user

*All > User Administration > Users > New*

| Field | Value |
|---|---|
| User ID | `govhub.integration` |
| First / last name | GovHub / Integration |
| Web service access only | **on** (cannot log in to the UI) |
| Internal integration user | on (if your release shows it) |
| Time zone | **UTC** (task due dates are sent as `YYYY-MM-DD 23:59:59`) |
| Password | set one; it goes only into your local `.env.servicenow` |

Roles (*Roles* related list > Edit): `u_govhub_task_writer`, `cmdb_read`.
**Do not grant `admin`.**

Two things to check on your release, after step 7:

- **Lookups.** The connector reads `sys_user_group` (by name), `sys_user` (by email) and
  the configuration item (by `correlation_id`) to fill reference fields. If the check in
  step 8 warns `no sys_user record ...` although the user exists, the integration user
  cannot read those tables: add `itil` (simplest) or a read ACL on `sys_user.email` and
  `sys_user_group.name` for `u_govhub_task_writer`.
- **REST API access policies.** If your instance enforces them, also add
  `snc_platform_rest_api_access`.

## 6. Fictional groups and users

*All > User Administration > Groups > New*: three groups, **named exactly**:
`agency-sample-benefits`, `dept-example-services`, `office-fictional-permits`.

*All > User Administration > Users > New*: the eight fictional owners from
`data/inventory/systems.csv`, with the **Email** set exactly (e.g.
`benefits.owner@example.invalid`). They do not need roles or passwords.

## 7. Fictional AI systems

*All > Configuration > Business Applications > New*: one record per row of
`data/inventory/systems.csv`:

| ServiceNow field | From the CSV |
|---|---|
| Name | Name |
| Correlation ID | System ID |
| Owned by | the user with that Owner email |
| Managed by group | Tenant |
| Install status | Lifecycle (production → Installed, pilot → In Maintenance, development → On Order, retired → Retired) |
| AIA impact level | I–IV |
| GovHub profiles | Profiles |

Optionally add `SYS-009` with no owner, no impact level and no profiles to see the
data-gap handling. `data/demo/servicenow/seed.json` holds exactly these records (the mock
uses it).

## 8. Connect and check (on your machine)

```bash
cp .env.servicenow.example .env.servicenow      # gitignored; never commit it
# edit: SERVICENOW_INSTANCE_URL, SERVICENOW_PASSWORD, CONNECTOR_ALLOWED_HOSTS
make servicenow-check
```

`make servicenow-check` reads the inventory, then creates, updates, notes and closes a
task `GOVHUB-SMOKE-TEST` in `u_govhub_task`, printing each step. Then:

```bash
uv run connector-hub sync-inventory --dry-run   # what would be imported, with data gaps
```

A developer instance hibernates when unused; the connector then reports
"... is hibernating: log in to the developer portal to wake the instance".
