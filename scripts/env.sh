# sourced: until the framework's `poker` branches are released, their <repo>-poker worktrees (beside this repo) are
# imported before anything installed (ui and ui_web are released: ui v0.5.52, ui_web v0.6.50)
_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
_path="$_root/planningpoker/src/main/python"
for _repo in api core client remote pubsub build; do
  [ -d "$_root/$_repo-poker" ] && _path="$_path:$_root/$_repo-poker/src/main/python"
done
export PYTHONPATH="$_path${PYTHONPATH:+:$PYTHONPATH}"
