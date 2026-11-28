# Development only: mint internal tokens for the demo scripts (sourced, not run).
#
#   hub_token AUDIENCE --user demo-officer-01
#   hub_token AUDIENCE --service connector-hub --all-tenants
#
# Uses the development keys: GOVHUB_KEYS_DIR when set (a local stack), otherwise the
# keys volume inside the Compose control-centre container. Real keys are secrets that
# these scripts never see.
hub_token() {
  local aud="$1"; shift
  if [ -n "${GOVHUB_KEYS_DIR:-}" ]; then
    uv run --quiet python -m govhub_shared.auth.mint --keys "$GOVHUB_KEYS_DIR" --aud "$aud" "$@"
  else
    docker compose exec -T control-centre \
      python -m govhub_shared.auth.mint --keys /keys --aud "$aud" "$@"
  fi
}

# rulebook_auth METHOD URL: the Authorization header for one rulebook call, chosen by what
# the call does (shared content: a governance officer; the inventory snapshot: the
# connector-hub sync job; impact reports: the fictional reviewer of all demo tenants).
rulebook_auth() {
  case "$1 $2" in
    "PUT "*"/inventory"*) echo "Authorization: Bearer $RB_SYNC" ;;
    *"/impact-reports"*) echo "Authorization: Bearer $RB_REVIEWER" ;;
    *) echo "Authorization: Bearer $RB_OFFICER" ;;
  esac
}

rulebook_tokens() {
  RB_OFFICER="$(hub_token rulebook --user demo-officer-01)"
  RB_REVIEWER="$(hub_token rulebook --user demo-reviewer-01)"
  RB_SYNC="$(hub_token rulebook --service connector-hub --all-tenants)"
  export RB_OFFICER RB_REVIEWER RB_SYNC
}
