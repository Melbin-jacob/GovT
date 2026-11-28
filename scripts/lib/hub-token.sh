# Development only: internal tokens for the demo scripts (sourced, not run).
#
#   hub_token AUDIENCE --user demo-officer-01
#   hub_token AUDIENCE --service connector-hub --all-tenants
#   hub_tokens                 # mint every token the demos need (valid 5 minutes)
#   hub_auth METHOD URL        # the Authorization header for one call
#
# Uses the development keys: GOVHUB_KEYS_DIR when set (a local stack), otherwise the keys
# volume inside the Compose control-centre container. Real keys are secrets that these
# scripts never see. The URL variables RULEBOOK, DESK, ENGINE and CONNECTOR say which
# service a URL belongs to (defaults: the Compose ports on localhost).
hub_token() {
  local aud="$1"; shift
  if [ -n "${GOVHUB_KEYS_DIR:-}" ]; then
    uv run --quiet python -m govhub_shared.auth.mint --keys "$GOVHUB_KEYS_DIR" --aud "$aud" "$@"
  else
    docker compose exec -T control-centre \
      python -m govhub_shared.auth.mint --keys /keys --aud "$aud" "$@"
  fi
}

hub_tokens() {
  : "${RULEBOOK:=http://localhost:8000}" "${CONNECTOR:=http://127.0.0.1:8001}"
  : "${DESK:=http://127.0.0.1:8002}" "${ENGINE:=http://127.0.0.1:8005}"
  RB_OFFICER="$(hub_token rulebook --user demo-officer-01)"
  RB_REVIEWER="$(hub_token rulebook --user demo-reviewer-01)"
  RB_SYNC="$(hub_token rulebook --service connector-hub --all-tenants)"
  RD_OFFICER="$(hub_token review-desk --user demo-officer-01)"
  RD_REVIEWER="$(hub_token review-desk --user demo-reviewer-01)"
  RD_AUDITOR="$(hub_token review-desk --user demo-auditor-01)"
  AE_OWNER="$(hub_token assessment-engine --user demo-owner-01)"
  AE_REVIEWER="$(hub_token assessment-engine --user demo-reviewer-01)"
  CH_ADMIN="$(hub_token connector-hub --user demo-tenant-admin-01)"
  CH_OFFICER="$(hub_token connector-hub --user demo-officer-01)"
  CH_REVIEWER="$(hub_token connector-hub --user demo-reviewer-01)"
  export RB_OFFICER RB_REVIEWER RB_SYNC RD_OFFICER RD_REVIEWER RD_AUDITOR
  export AE_OWNER AE_REVIEWER CH_ADMIN CH_OFFICER CH_REVIEWER
}

# The identity follows what the call does (fictional demo users):
# rulebook: shared content as a governance officer, the inventory snapshot as the
# connector-hub sync job, impact reports as the reviewer of all three demo tenants;
# review-desk: intake as the governance officer, the decision log as the auditor of all
# three tenants, everything else as the reviewer; assessment engine: evidence and facts
# as the system owner, assessments as the reviewer; connector-hub: the inventory sync as
# the tenant-admin, impact-report tasks as the governance officer, notes as the reviewer.
hub_auth() {
  local method="$1" url="$2" token="none"
  case "$url" in
    "$RULEBOOK"*)
      case "$method ${url#"$RULEBOOK"}" in
        "PUT /inventory"*) token="$RB_SYNC" ;;
        *"/impact-reports"*) token="$RB_REVIEWER" ;;
        *) token="$RB_OFFICER" ;;
      esac ;;
    "$DESK"*)
      case "${url#"$DESK"}" in
        "/intake/"*) token="$RD_OFFICER" ;;
        "/decision-log/"*) token="$RD_AUDITOR" ;;
        *) token="$RD_REVIEWER" ;;
      esac ;;
    "$ENGINE"*)
      case "$method ${url#"$ENGINE"}" in
        *"/evidence"*|"PUT "*"/facts"*) token="$AE_OWNER" ;;
        *) token="$AE_REVIEWER" ;;
      esac ;;
    "$CONNECTOR"*)
      case "${url#"$CONNECTOR"}" in
        "/inventory/"*) token="$CH_ADMIN" ;;
        "/tasks/sync-impact-report"*) token="$CH_OFFICER" ;;
        *) token="$CH_REVIEWER" ;;
      esac ;;
  esac
  if [ "$token" = "none" ]; then echo "X-GovHub-Note: none"; else echo "Authorization: Bearer $token"; fi
}
