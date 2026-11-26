#!/usr/bin/env bash
# Safe updater for discord-bot-pi.
#
#   update-discord-bot           update only if origin/main has new commits
#   update-discord-bot --force   restart and health-check even with no new commits
#
# Flow: fetch -> fast-forward -> install deps (only if requirements.txt changed)
#       -> run the test suite -> restart -> wait for the bot to log in.
# If the tests fail or the bot does not come up healthy, the previous commit is
# restored (and the service restarted again if it had been restarted).
#
# Everything is wrapped in main() so git can safely replace this file mid-run.

set -uo pipefail

REPO_DIR="${REPO_DIR:-/home/blittz/apps/discord-bot-pi}"
SERVICE="${SERVICE:-discord-bot.service}"
BRANCH="${BRANCH:-main}"
VENV_DIR="${VENV_DIR:-$REPO_DIR/.venv}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-45}"   # seconds to wait for "Logged in as"
POLL_SECONDS="${POLL_SECONDS:-2}"
SETTLE_SECONDS="${SETTLE_SECONDS:-5}"    # must still be active this long after login
LOCK_FILE="${LOCK_FILE:-/tmp/update-discord-bot.lock}"
SUDO="${SUDO:-sudo}"
LOGIN_PATTERN="Logged in as"

log() { echo "[update $(date '+%F %T')] $*"; }

install_deps() {
    log "Installing dependencies..."
    "$VENV_DIR/bin/python" -m pip install -q -r requirements.txt
}

# Restart the service and wait until the bot has logged in and stays up.
restart_and_verify() {
    local since end
    since="$(date '+%F %T')"
    log "Restarting $SERVICE..."
    $SUDO systemctl restart "$SERVICE" || { log "systemctl restart failed"; return 1; }
    end=$((SECONDS + HEALTH_TIMEOUT))
    while (( SECONDS < end )); do
        sleep "$POLL_SECONDS"
        if ! systemctl is-active --quiet "$SERVICE"; then
            log "Service is not active."
            return 1
        fi
        if journalctl -u "$SERVICE" --since "$since" -o cat 2>/dev/null | grep -q "$LOGIN_PATTERN"; then
            sleep "$SETTLE_SECONDS"
            if systemctl is-active --quiet "$SERVICE"; then
                log "Healthy: bot logged in and service is active."
                return 0
            fi
            log "Service stopped right after logging in."
            return 1
        fi
    done
    log "Timed out after ${HEALTH_TIMEOUT}s waiting for the bot to log in."
    return 1
}

main() {
    local force=0 prev target changed=0
    [[ "${1:-}" == "--force" ]] && force=1

    exec 9>"$LOCK_FILE"
    if ! flock -n 9; then
        log "Another update is already running; exiting."
        return 0
    fi

    cd "$REPO_DIR" || { log "Cannot enter $REPO_DIR"; return 1; }

    local branch
    branch="$(git rev-parse --abbrev-ref HEAD)"
    if [[ "$branch" != "$BRANCH" ]]; then
        log "ABORT: repo is on '$branch', not '$BRANCH'. Run: git checkout $BRANCH"
        return 1
    fi
    if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
        log "ABORT: tracked files have uncommitted changes; not touching them."
        return 1
    fi

    git fetch --prune origin || { log "ABORT: git fetch failed."; return 1; }
    prev="$(git rev-parse HEAD)"
    target="$(git rev-parse "origin/$BRANCH")"

    if [[ "$prev" == "$target" ]]; then
        if (( force )); then
            log "No new commits; --force given, verifying a restart."
            restart_and_verify
            return $?
        fi
        log "Already up to date at ${prev:0:7}; nothing to do."
        return 0
    fi

    if ! git merge-base --is-ancestor "$prev" "$target"; then
        log "ABORT: local $BRANCH has commits that are not on origin (cannot fast-forward)."
        return 1
    fi

    log "Updating ${prev:0:7} -> ${target:0:7}"
    git merge -q --ff-only "origin/$BRANCH" || { log "ABORT: fast-forward failed."; return 1; }

    if git diff --name-only "$prev" HEAD | grep -qx 'requirements.txt'; then
        changed=1
    fi

    rollback() {   # $1 = "restart" if the service was already restarted onto bad code
        log "ROLLING BACK to ${prev:0:7}"
        git reset -q --hard "$prev"
        (( changed )) && install_deps
        if [[ "$1" == "restart" ]]; then
            if restart_and_verify; then
                log "Rolled back: previous version is running again."
            else
                log "CRITICAL: previous version also failed its health check. Check: journalctl -u $SERVICE"
            fi
        else
            log "Service was never restarted; it is still running the previous version."
        fi
    }

    if (( changed )) && ! install_deps; then
        log "Dependency install failed."
        rollback norestart
        return 1
    fi

    log "Running tests..."
    local out
    if ! out="$("$VENV_DIR/bin/python" -B -m unittest discover -s tests 2>&1)"; then
        log "Tests FAILED:"
        echo "$out" | tail -25
        rollback norestart
        return 1
    fi
    log "Tests passed: $(echo "$out" | grep -E '^Ran ' | head -1)"

    if ! restart_and_verify; then
        rollback restart
        return 1
    fi

    log "Update complete: now running ${target:0:7}."
    return 0
}

main "$@"
exit $?
