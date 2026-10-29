#!/usr/bin/env bash
# StudentHub server-side deployment script.
# GitHub Actions copies this file to ~/studenthub on the VM and runs it after a
# successful build. You can also run it by hand on the server:
#
#   ./deploy.sh <image-tag>     deploy a specific image tag (a full git commit SHA)
#   ./deploy.sh rollback        redeploy the previously successful tag
#   ./deploy.sh status          show current/previous tags and container health
#   ./deploy.sh backup          write a compressed database backup to ./backups
#
# Safety rules this script follows:
#   * never runs `docker compose down -v` and never removes the mysql_data volume
#   * backs up the database before replacing the application container
#   * only marks a tag as current after the new container reports healthy
#   * if the new version is unhealthy, automatically switches back to the previous tag
#
# Optional: to pull a PRIVATE image, pass a registry token on stdin and set
# GHCR_USERNAME, e.g.  echo "$TOKEN" | GHCR_USERNAME=me ./deploy.sh <tag>
set -Eeuo pipefail

cd "$(dirname "$(readlink -f "$0")")"
COMPOSE=(docker compose -f compose.prod.yaml --env-file .env)
STATE_DIR=".deploy"
BACKUP_DIR="backups"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"
KEEP_BACKUPS="${KEEP_BACKUPS:-10}"
mkdir -p "$STATE_DIR" "$BACKUP_DIR"

log()  { printf '%s [deploy] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "ERROR: $*"; exit 1; }

[[ -f .env ]] || fail ".env not found in $(pwd). Create it from .env.production.example first."
[[ -f compose.prod.yaml && -f Caddyfile ]] || fail "compose.prod.yaml or Caddyfile missing in $(pwd)."
command -v docker >/dev/null || fail "Docker is not installed."

IMAGE_NAME="$(grep -E '^IMAGE_NAME=' .env | tail -1 | cut -d= -f2- | tr -d '"' | tr -d "'")"
[[ -n "$IMAGE_NAME" ]] || fail "IMAGE_NAME is not set in .env (e.g. ghcr.io/your-user/studenthub-assignment-tracker)."

current_tag()  { cat "$STATE_DIR/current" 2>/dev/null || true; }
previous_tag() { cat "$STATE_DIR/previous" 2>/dev/null || true; }

set_image_tag() {
  # Persist IMAGE_TAG in .env so manual `docker compose -f compose.prod.yaml ...` commands keep working.
  local tag="$1"
  if grep -qE '^IMAGE_TAG=' .env; then
    sed -i "s|^IMAGE_TAG=.*|IMAGE_TAG=${tag}|" .env
  else
    printf '\nIMAGE_TAG=%s\n' "$tag" >> .env
  fi
}

registry_login() {
  if [[ -n "${GHCR_USERNAME:-}" && ! -t 0 ]]; then
    local token
    IFS= read -r token || true
    if [[ -n "$token" ]]; then
      printf '%s' "$token" | docker login ghcr.io -u "$GHCR_USERNAME" --password-stdin >/dev/null
      LOGGED_IN=1
      log "logged in to ghcr.io as $GHCR_USERNAME"
    fi
  fi
}

registry_logout() {
  if [[ "${LOGGED_IN:-0}" == "1" ]]; then docker logout ghcr.io >/dev/null 2>&1 || true; fi
}

backup_db() {
  local db_id
  db_id="$("${COMPOSE[@]}" ps -q db 2>/dev/null || true)"
  if [[ -z "$db_id" ]] || [[ "$(docker inspect -f '{{.State.Running}}' "$db_id" 2>/dev/null)" != "true" ]]; then
    log "database container not running yet; skipping backup (first deployment?)"
    return 0
  fi
  local file
  file="$BACKUP_DIR/studenthub-$(date -u +%Y%m%d-%H%M%S).sql.gz"
  log "backing up database to $file"
  "${COMPOSE[@]}" exec -T db sh -c \
    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --routines --triggers --no-tablespaces "$MYSQL_DATABASE"' \
    | gzip > "$file"
  # Keep only the newest backups.
  ls -1t "$BACKUP_DIR"/studenthub-*.sql.gz 2>/dev/null | tail -n +"$((KEEP_BACKUPS + 1))" | xargs -r rm -f
}

wait_healthy() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT)) id status
  while (( SECONDS < deadline )); do
    id="$("${COMPOSE[@]}" ps -q web || true)"
    status="$( [[ -n "$id" ]] && docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$id" 2>/dev/null || echo missing)"
    case "$status" in
      healthy) return 0 ;;
      unhealthy) return 1 ;;
    esac
    sleep 3
  done
  return 1
}

verify_version() {
  local expected="$1"
  "${COMPOSE[@]}" exec -T web python scripts/healthcheck.py http://127.0.0.1:5000/health \
    --expect-version "$expected" --retries 5 --delay 3
}

start_tag() {
  local tag="$1"
  set_image_tag "$tag"
  IMAGE_TAG="$tag" "${COMPOSE[@]}" up -d --remove-orphans
}

prune_images() {
  local keep_current="$1" keep_previous="$2"
  docker image ls "$IMAGE_NAME" --format '{{.Tag}}' | sort -u | while read -r t; do
    [[ -z "$t" || "$t" == "<none>" || "$t" == "$keep_current" || "$t" == "$keep_previous" ]] && continue
    docker image rm "$IMAGE_NAME:$t" >/dev/null 2>&1 && log "removed old image tag $t" || true
  done
  docker image prune -f >/dev/null 2>&1 || true
}

deploy() {
  local tag="$1" previous
  [[ "$tag" =~ ^[A-Za-z0-9_.-]{1,128}$ ]] || fail "invalid image tag '$tag'"
  previous="$(current_tag)"
  log "deploying $IMAGE_NAME:$tag (currently running: ${previous:-none})"

  registry_login
  trap registry_logout EXIT
  IMAGE_TAG="$tag" "${COMPOSE[@]}" pull web || fail "could not pull $IMAGE_NAME:$tag (is the package public, or was a token provided?)"

  backup_db
  start_tag "$tag"

  if wait_healthy && verify_version "$tag"; then
    if [[ -n "$previous" && "$previous" != "$tag" ]]; then echo "$previous" > "$STATE_DIR/previous"; fi
    echo "$tag" > "$STATE_DIR/current"
    prune_images "$tag" "$(previous_tag)"
    log "SUCCESS: $IMAGE_NAME:$tag is live and healthy"
    return 0
  fi

  log "new version is NOT healthy; recent logs:"
  "${COMPOSE[@]}" logs --tail=60 web || true
  if [[ -n "$previous" && "$previous" != "$tag" ]]; then
    log "rolling back to $previous"
    start_tag "$previous"
    if wait_healthy; then
      log "rolled back to $previous; the site is running the previous version"
    else
      log "rollback container is also unhealthy; check 'docker compose -f compose.prod.yaml logs'"
    fi
  fi
  fail "deployment of $tag failed"
}

rollback() {
  local target
  target="${1:-$(previous_tag)}"
  [[ -n "$target" ]] || fail "no previous tag recorded; run ./deploy.sh <tag> with an older commit SHA instead"
  log "manual rollback to $target"
  deploy "$target"
}

status() {
  echo "image:    $IMAGE_NAME"
  echo "current:  $(current_tag)"
  echo "previous: $(previous_tag)"
  "${COMPOSE[@]}" ps
}

case "${1:-}" in
  ""|-h|--help) sed -n '2,20p' "$0" ;;
  rollback) rollback "${2:-}" ;;
  status) status ;;
  backup) backup_db ;;
  *) deploy "$1" ;;
esac
