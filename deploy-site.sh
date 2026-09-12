#!/usr/bin/env bash
# deploy.sh — publish 13f to the Hetzner edge.
#
# A thin wrapper so the repo has one obvious entry point:
#
#   bash deploy.sh              deploy the ref in .deploy/site.json
#   bash deploy.sh --dry-run    print what would happen, change nothing
#   bash deploy.sh --rollback   restore the last good commit
#
# All arguments are passed straight through to the skill's site-deploy.sh,
# which holds the actual logic. Nothing site-specific lives here: the
# configuration is .deploy/site.json, and this file only finds the script and
# runs it from the repository root.

set -euo pipefail

# The skill is not part of this repo, so its location is resolved at run time.
# HETZNER_SITE_SKILL wins, which is what makes this work on a machine that
# keeps the skill somewhere else.
for candidate in \
    "${HETZNER_SITE_SKILL:-}" \
    "$HOME/.claude/skills/hetzner-site" \
    "/c/Personal_utilities/hetzner-site" \
    "/mnt/c/Personal_utilities/hetzner-site"; do
    if [ -n "$candidate" ] && [ -x "$candidate/bin/site-deploy.sh" ]; then
        SKILL_DIR="$candidate"
        break
    fi
done

if [ -z "${SKILL_DIR:-}" ]; then
    echo "deploy.sh: cannot find the hetzner-site skill." >&2
    echo "  Looked in ~/.claude/skills/hetzner-site and /c/Personal_utilities/hetzner-site." >&2
    echo "  Set HETZNER_SITE_SKILL=/path/to/hetzner-site and retry." >&2
    exit 1
fi

# site-deploy.sh reads ./.deploy/site.json from the working directory, so run
# it from the repo root — this way `bash deploy.sh` also works from a subdir.
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec bash "$SKILL_DIR/bin/site-deploy.sh" "$@"
