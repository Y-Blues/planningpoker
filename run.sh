#!/usr/bin/env bash
# Builds the page (its browser wheels, conf/worktrees) and starts the server on http://localhost:8080/ (memory storage).
#   ./run.sh [conf/application.yml]          PYTHON=... to use another interpreter than `uv run python`
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source scripts/env.sh
exec ${PYTHON:-uv run python} -m ycappuccino.build run --host "${1:-conf/application.yml}" --project conf/worktrees
