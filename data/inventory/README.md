# Fictional AI-system inventory

`systems.csv` is **entirely fictional** demo data: every system, department, tenant and
owner is invented, owners are role titles, and every e-mail address uses the reserved
`example.invalid` domain. It stands in for the ServiceNow CMDB until connector-hub exists.

| Column | Meaning |
|---|---|
| System ID | Stable ID (OSCAL token) |
| Tenant | Department identifier; scopes reports and tasks |
| AIA impact level | I–IV |
| Lifecycle | development, pilot, production or retired (retired systems are never in scope) |
| Profiles | `;`-separated profile names; their resolved controls are the system's checks in scope |
