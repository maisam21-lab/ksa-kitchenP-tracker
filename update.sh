#!/usr/bin/env bash
# Safe updater for the KSA Kitchen Tracker app slot on data-apps.
# Run with: bash update.sh   (from inside the app folder, or by absolute path)
#
# Guards against the Jul 2026 incident where a force-checkout of one app's repo
# inside another app's folder replaced this tracker on Okta:
#   1. refuses to run if this folder's git remote is not the tracker repo
#   2. refuses to touch anything if the folder is not a git repo at all
#   3. fast-forward only - never merges, never force-overwrites local state
set -euo pipefail
cd "$(dirname "$0")"

EXPECTED="maisam21-lab/ksa-kitchenp-tracker"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "REFUSING: $(pwd) is not a git repository. Do NOT git-init or clone over it."
    exit 1
fi

url=$(git remote get-url origin 2>/dev/null | tr '[:upper:]' '[:lower:]' || echo "none")
case "$url" in
    *"$EXPECTED"*) ;;
    *)
        echo "REFUSING: this folder belongs to a DIFFERENT app."
        echo "  folder : $(pwd)"
        echo "  origin : $url"
        echo "  wanted : $EXPECTED"
        echo "You are probably in the wrong app slot - nothing was changed."
        exit 1
        ;;
esac

git fetch origin
git merge --ff-only origin/main
echo "OK: Kitchen Tracker updated to $(git rev-parse --short HEAD) ($(git log -1 --format=%s))"
