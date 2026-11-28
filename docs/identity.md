# Identity: sign-in, internal tokens, roles

## How it fits together

```
browser ──(OIDC code flow + PKCE)──> sign-in provider (Keycloak locally / Entra ID)
   │                                        ▲
   ▼                                        │ only control-centre calls it,
control-centre ── internal token (ES256, 5 min, one audience) ──> rulebook,
   (session)                                │                     review-desk,
                                            │                     assessment-engine,
                                            │                     connector-hub
services ── their own service tokens ──> each other (internal network)
```

- **control-centre** is the only component that talks to the sign-in provider, and only
  to the hosts in `OIDC_ALLOWED_HOSTS` (HTTPS; plain HTTP only with
  `OIDC_ALLOW_INSECURE_HTTP=1` for a local Keycloak). connector-hub still calls ServiceNow.
  Nothing else calls out.
- After sign-in, control-centre keeps a **server-side session** (the cookie holds a random
  token; the database holds its hash): idle 30 minutes, at most 8 hours (PLACEHOLDER).
- For every call to a hub service, control-centre mints an **internal token** for that
  service only (`aud`), valid 5 minutes, signed ES256 with a key ID (`kid`). It carries
  the user's roles per tenant. Services verify it against a local **trust file** of
  public keys and never contact the sign-in provider.
- Services call each other with tokens signed by **their own keys** (service identities).

## Roles

| Role | Scope | Notes |
|---|---|---|
| `system-owner` | per tenant | their tenant's systems and evidence |
| `reviewer` | per tenant | findings, decisions, assessments |
| `tenant-admin` | per tenant | data settings, residency labels, evidence deletion, break-glass approval; holds `profile-assignment` (which profiles apply to the tenant's systems) |
| `auditor` | per tenant | read-only, including logs |
| `governance-officer` | platform | shared catalogs and drafts |
| `platform-admin` | platform | operations; no tenant data without a break-glass grant |

Role and group names here are **fictional and unverified**: replace them with your own.

## Local and CI: Keycloak

The Compose file has a Keycloak service (profile `oidc`, image
`quay.io/keycloak/keycloak:26.0.7`) with a fictional realm
(`docker/keycloak/govhub-realm.json`, generated from `data/demo/users.toml` by
`scripts/make_keycloak_realm.py`; a test keeps them in sync).

```bash
docker compose --profile oidc up -d --wait keycloak
AUTH_MODE=oidc make up
```

Open http://127.0.0.1:8004 and sign in as a fictional user, e.g. `demo-reviewer-01`,
password `dev-only-fictional` (local and CI only). Keycloak's console is on
http://127.0.0.1:8080 (admin / `dev-only-admin`).

- Realm `govhub`, client `control-centre`: confidential client, standard flow only
  (no direct grants), PKCE `S256` required, redirect `http://127.0.0.1:8004/auth/callback`.
- Groups: `/govhub/<tenant>/<role>` and `/govhub/platform/<role>`. A **group membership**
  mapper puts full paths in the ID token's `groups` claim.
- Inside Compose, control-centre fetches discovery from `http://keycloak:8080` (backchannel)
  while browsers use `http://127.0.0.1:8080`: `KC_HOSTNAME` sets the issuer to the
  browser address and `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true` lets the token and key
  endpoints answer on the internal name.

## The same setup with Microsoft Entra ID (documented, not yet tested)

No Entra test tenant has been used yet (project owner's answer 8); the steps below follow
the same configuration control-centre reads, and need to be confirmed on a real tenant.

1. **App registration** (Entra admin centre > App registrations > New): a web app.
   - Redirect URI (Web): `https://<control-centre host>/auth/callback`.
   - Front-channel logout URL: `https://<control-centre host>/en/sign-in`.
   - Certificates & secrets: a client secret (or, better, a certificate; control-centre
     reads the secret from `OIDC_CLIENT_SECRET`, from a Kubernetes secret).
   - API permissions: `openid`, `profile`, `email` (delegated).
2. **Groups in the token**: Token configuration > Add groups claim > Security groups, ID
   token. Entra sends group **object IDs**, not paths, so list each group in
   `data/config/oidc-roles.toml` under `[groups]`:

   ```toml
   user_id_claim = "oid"
   [groups]
   "<object id>" = { tenant = "dept-a", role = "reviewer" }
   "<object id>" = { platform = "governance-officer" }
   ```

   Users in more than 200 groups get a "groups overage" claim instead of the list; assign
   only the hub's groups to the app (Enterprise applications > the app > Properties >
   Assignment required, and Token configuration > "Groups assigned to the application").
   App roles are an alternative to groups (one role value per tenant and role).
3. **control-centre configuration**:

   ```bash
   AUTH_MODE=oidc
   OIDC_ISSUER=https://login.microsoftonline.com/<tenant-id>/v2.0
   OIDC_CLIENT_ID=<application (client) id>
   OIDC_CLIENT_SECRET=<from a secret>
   OIDC_REDIRECT_URL=https://<control-centre host>/auth/callback
   OIDC_ALLOWED_HOSTS=login.microsoftonline.com
   ```

   PKCE `S256` is used as with Keycloak. The ID token is verified against Entra's
   published keys (signature, issuer, audience = client ID, expiry, nonce).
4. **Network**: control-centre must reach `login.microsoftonline.com` over HTTPS; nothing
   else in the hub does.

## Demo mode (evaluator walkthroughs)

`AUTH_MODE=demo` replaces sign-in with fictional users chosen on the page ("Acting as")
and shows the banner "Demo mode: fictional users, no sign-in." Services still receive only
internal tokens. It **refuses to start** unless control-centre is bound to a loopback or
internal address (or to all interfaces with `GOVHUB_INTERNAL_ONLY=1`, as in Compose where
ports are published on 127.0.0.1) **and** every tenant is marked synthetic.

## Keys

`python -m govhub_shared.auth.devkeys var/keys` makes development keys and `trust.json`
(Compose does this in a one-shot `keys` container into its own volume). In production,
each issuer's private key is a secret mounted into that service only, and every service
gets the same trust file. **Rotation**: add the new public key (new `kid`) to the trust
file everywhere, switch the issuer to the new private key, then remove the old public key
after at most 5 minutes plus clock skew.
