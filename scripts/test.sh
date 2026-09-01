#!/usr/bin/env bash
set -euo pipefail

goalwatch_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$goalwatch_root"

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$goalwatch_root/src" python3 - <<'PY'
from pathlib import Path

for root in (Path("src"), Path("tests"), Path("scripts")):
    for source in root.rglob("*.py"):
        compile(source.read_text(encoding="utf-8"), str(source), "exec")
PY
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$goalwatch_root/src" python3 -m unittest discover -s tests -v
node --check integrations/obsidian/goalwatch/main.js
node tests/test_obsidian.js
bash -n install.sh uninstall.sh packaging/bin/goalwatch scripts/test.sh
if find . -path ./.git -prune -o -type f \( -name 'AGENT.md' -o -name 'AGENTS.md' \) -print -quit | grep -q .; then
  echo "Automatic coding-agent instruction files must not ship in GoalWatch." >&2
  exit 1
fi
test -f CONTRIBUTING.md
python3 -m json.tool manifest.json >/dev/null
python3 -m json.tool integrations/omarchy/com.goalwatch/manifest.json >/dev/null
python3 -m json.tool integrations/obsidian/goalwatch/manifest.json >/dev/null
python3 -m json.tool tests/ai-fixtures/manifest.json >/dev/null
python3 - <<'PY'
import json
from pathlib import Path

root_manifest = json.loads(Path("manifest.json").read_text(encoding="utf-8"))
packaged_manifest = json.loads(
    Path("integrations/omarchy/com.goalwatch/manifest.json").read_text(encoding="utf-8")
)
shared_fields = (
    "schemaVersion", "id", "name", "version", "author", "license",
    "description", "kinds", "keepLoaded", "barWidget",
)
for field in shared_fields:
    assert root_manifest.get(field) == packaged_manifest.get(field), field
for entry_point in root_manifest["entryPoints"].values():
    assert Path(entry_point).is_file(), entry_point

manifest = Path("tests/ai-fixtures/manifest.json")
data = json.loads(manifest.read_text(encoding="utf-8"))
for case in data["cases"]:
    image = manifest.parent / case["image"]
    assert image.is_file(), image
    assert image.read_bytes().startswith(b"\xff\xd8"), image
PY
if command -v omarchy >/dev/null 2>&1; then
  omarchy plugin validate .
  omarchy plugin validate integrations/omarchy/com.goalwatch
fi

echo "All GoalWatch checks passed."
