#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  Rufino — GitHub ingestor
#  Daily 06:30. Fetches GitHub activity from the previous day for
#  the authenticated `gh` user and writes facts to:
#    ${RUFINO_VAULT_PATH}/github/facts/<slug>.md
#  Audit trail dumped at:
#    ${RUFINO_VAULT_PATH}/github/raw/<YYYY-MM-DD>.json
#
#  Requires:
#    - `gh` CLI authenticated (`gh auth status` should pass)
#    - $RUFINO_VAULT_PATH set
# ─────────────────────────────────────────────────────────────
set -euo pipefail

LOGFILE="${RUFINO_LOG_DIR:-$HOME/.claude/logs/rufino}/rufino-ingest-github.log"
mkdir -p "$(dirname "$LOGFILE")"
PROMPT_FILE="$HOME/.claude/prompts/rufino-ingest-github.md"
CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"
VAULT_PATH="${RUFINO_VAULT_PATH:?RUFINO_VAULT_PATH must be set}"
LOCKFILE="$VAULT_PATH/_meta/.ingest-github.lock"

mkdir -p "$VAULT_PATH/_meta" "$VAULT_PATH/github/facts" "$VAULT_PATH/github/raw"

# Stale-lock-aware locking
if [ -f "$LOCKFILE" ]; then
    LOCK_PID=$(cat "$LOCKFILE" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "=== Rufino ingest-github skipped: already running (PID $LOCK_PID) at $(date) ===" >> "$LOGFILE"
        exit 0
    fi
    rm -f "$LOCKFILE"
fi
echo "$$" > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

echo "=== Rufino ingest-github run: $(date) ===" >> "$LOGFILE"

# Sanity: gh auth + jq present
if ! command -v gh >/dev/null 2>&1; then
    echo "ERROR: gh CLI not installed" >> "$LOGFILE"
    exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: jq not installed" >> "$LOGFILE"
    exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
    echo "ERROR: gh CLI not authenticated. Run: gh auth login" >> "$LOGFILE"
    exit 1
fi
if [ ! -f "$PROMPT_FILE" ]; then
    echo "ERROR: Prompt file not found at $PROMPT_FILE" >> "$LOGFILE"
    exit 1
fi

# ────────────────────────────────────
# Step 1: Fetch raw data for "yesterday"
# ────────────────────────────────────
GH_USER="$(gh api user --jq '.login')"
# Date being processed. Default: yesterday. Override via env var for backfills.
TARGET_DATE="${RUFINO_GITHUB_FORCE_DATE:-$(date -v-1d +%Y-%m-%d)}"
YESTERDAY="$TARGET_DATE"
FROM="${TARGET_DATE}T00:00:00Z"
TO="${TARGET_DATE}T23:59:59Z"
RAW_FILE="$VAULT_PATH/github/raw/${TARGET_DATE}.json"

echo "  User: $GH_USER  Date: $YESTERDAY" >> "$LOGFILE"

# GraphQL: contribution summary (commits per repo, PRs, issues, reviews)
gh api graphql -f login="$GH_USER" -f from="$FROM" -f to="$TO" -f query='
query($login:String!, $from:DateTime!, $to:DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      commitContributionsByRepository(maxRepositories: 50) {
        repository { nameWithOwner url isPrivate primaryLanguage { name } }
        contributions(first: 100) {
          nodes { commitCount occurredAt }
        }
      }
      pullRequestContributions(first: 50) {
        nodes {
          pullRequest {
            title url state createdAt mergedAt number
            repository { nameWithOwner }
            additions deletions changedFiles
          }
        }
      }
      issueContributions(first: 50) {
        nodes {
          issue {
            title url state createdAt number
            repository { nameWithOwner }
          }
        }
      }
      pullRequestReviewContributions(first: 50) {
        nodes {
          pullRequest { title url number repository { nameWithOwner } }
          occurredAt
        }
      }
    }
  }
}' > "$RAW_FILE.contrib" 2>>"$LOGFILE" || { echo "ERROR: graphql contrib failed" >>"$LOGFILE"; }

# Public events (stars, repo creations, releases)
gh api "/users/$GH_USER/events?per_page=100" \
    --jq "[.[] | select(.created_at >= \"$FROM\" and .created_at <= \"$TO\")]" \
    > "$RAW_FILE.events" 2>>"$LOGFILE" || { echo "ERROR: events fetch failed" >>"$LOGFILE"; }

# Combine into single JSON for the prompt
jq -n \
    --slurpfile contrib "$RAW_FILE.contrib" \
    --slurpfile events "$RAW_FILE.events" \
    --arg user "$GH_USER" \
    --arg date "$YESTERDAY" \
    '{user: $user, date: $date, contributions: ($contrib[0].data.user.contributionsCollection), events: $events[0]}' \
    > "$RAW_FILE"

rm -f "$RAW_FILE.contrib" "$RAW_FILE.events"

# Short-circuit: if there's literally no activity, log and exit
HAS_ACTIVITY=$(jq -r '
    ((.contributions.commitContributionsByRepository | length) > 0)
    or ((.contributions.pullRequestContributions.nodes | length) > 0)
    or ((.contributions.issueContributions.nodes | length) > 0)
    or ((.contributions.pullRequestReviewContributions.nodes | length) > 0)
    or ((.events | length) > 0)
' "$RAW_FILE")

if [ "$HAS_ACTIVITY" != "true" ]; then
    echo "  No GitHub activity on $YESTERDAY. Skipping Claude invocation." >> "$LOGFILE"
    echo "=== Rufino ingest-github done (no-op): $(date) ===" >> "$LOGFILE"
    exit 0
fi

# ────────────────────────────────────
# Step 2: Invoke Claude with the prompt
# ────────────────────────────────────
RUFINO_DISPLAY_NAME="${RUFINO_DISPLAY_NAME:-el usuario}"
export RUFINO_VAULT_PATH RUFINO_DISPLAY_NAME
export RUFINO_GITHUB_RAW_FILE="$RAW_FILE"
export RUFINO_GITHUB_USER="$GH_USER"
export RUFINO_GITHUB_DATE="$YESTERDAY"

PROMPT=$(envsubst '${RUFINO_VAULT_PATH} ${RUFINO_DISPLAY_NAME} ${RUFINO_GITHUB_RAW_FILE} ${RUFINO_GITHUB_USER} ${RUFINO_GITHUB_DATE}' < "$PROMPT_FILE")

"$CLAUDE" -p "$PROMPT" \
    --allowedTools "Read,Write,Edit,Glob,Grep,Bash" \
    --dangerously-skip-permissions \
    --model sonnet \
    >> "$LOGFILE" 2>&1

echo "=== Rufino ingest-github done: $(date) ===" >> "$LOGFILE"
