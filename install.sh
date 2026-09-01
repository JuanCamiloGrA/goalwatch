#!/usr/bin/env bash
set -euo pipefail

goalwatch_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
goalwatch_data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
goalwatch_config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
goalwatch_app_parent="$goalwatch_data_home/goalwatch"
goalwatch_app="$goalwatch_app_parent/app"
goalwatch_bin="$HOME/.local/bin/goalwatch"
goalwatch_unit="$goalwatch_config_home/systemd/user/goalwatch.service"
goalwatch_plugin="$goalwatch_config_home/omarchy/plugins/com.goalwatch"
goalwatch_doc="$goalwatch_data_home/doc/goalwatch"
goalwatch_with_obsidian=false
goalwatch_skip_obsidian=false
goalwatch_obsidian_explicit=false
goalwatch_skip_packages=false
goalwatch_vault_args=()
goalwatch_obsidian_failed=false
goalwatch_obsidian_ready=false

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

Installs GoalWatch for the current Omarchy user.

Options:
  --with-obsidian    Connect the most recent registered Obsidian vault.
  --vault PATH       Connect this Obsidian vault (implies --with-obsidian).
  --skip-obsidian    Skip updating an already-connected Obsidian companion.
  --skip-packages    Do not install missing Arch packages; fail instead.
  -h, --help         Show this help.
EOF
}

while (( $# > 0 )); do
  case "$1" in
    --vault)
      [[ $# -ge 2 ]] || { echo "--vault requires a path" >&2; exit 2; }
      goalwatch_vault_args+=(--vault "$2")
      goalwatch_with_obsidian=true
      goalwatch_obsidian_explicit=true
      shift 2
      ;;
    --with-obsidian)
      goalwatch_with_obsidian=true
      goalwatch_obsidian_explicit=true
      shift
      ;;
    --skip-obsidian)
      goalwatch_with_obsidian=false
      goalwatch_skip_obsidian=true
      shift
      ;;
    --skip-packages)
      goalwatch_skip_packages=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

command -v omarchy >/dev/null 2>&1 || {
  echo "GoalWatch requires Omarchy." >&2
  exit 1
}
command -v systemctl >/dev/null 2>&1 || {
  echo "GoalWatch requires systemd user services." >&2
  exit 1
}

goalwatch_missing_packages=()
command -v python3 >/dev/null 2>&1 || goalwatch_missing_packages+=(python)
command -v grim >/dev/null 2>&1 || goalwatch_missing_packages+=(grim)
command -v secret-tool >/dev/null 2>&1 || goalwatch_missing_packages+=(libsecret)

if (( ${#goalwatch_missing_packages[@]} > 0 )); then
  if [[ $goalwatch_skip_packages == true ]]; then
    echo "Missing packages: ${goalwatch_missing_packages[*]}" >&2
    exit 1
  fi
  echo "Installing required packages: ${goalwatch_missing_packages[*]}"
  omarchy pkg add "${goalwatch_missing_packages[@]}"
fi

for command_name in python3 grim secret-tool; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "Required command is still missing after package installation: $command_name" >&2
    exit 1
  }
done

goalwatch_was_active=false
if systemctl --user is-active --quiet goalwatch.service 2>/dev/null; then
  goalwatch_was_active=true
  systemctl --user stop goalwatch.service
fi

install -d -m 700 "$goalwatch_app_parent" "$goalwatch_config_home/systemd/user"
install -d -m 755 "$HOME/.local/bin" "$goalwatch_config_home/omarchy/plugins" "$goalwatch_doc"

goalwatch_stage="$(mktemp -d "$goalwatch_app_parent/.install.XXXXXX")"
goalwatch_backup="$goalwatch_app_parent/.previous.$$"
cleanup() {
  if [[ -d $goalwatch_stage ]]; then
    rm -rf -- "$goalwatch_stage"
  fi
  return 0
}
trap cleanup EXIT

cp -a "$goalwatch_root/src/goalwatch" "$goalwatch_stage/goalwatch"
cp -a "$goalwatch_root/integrations/obsidian/goalwatch" "$goalwatch_stage/goalwatch/_obsidian"
if [[ -d $goalwatch_app ]]; then
  mv -- "$goalwatch_app" "$goalwatch_backup"
fi
mv -- "$goalwatch_stage" "$goalwatch_app"
if [[ -d $goalwatch_backup ]]; then
  rm -rf -- "$goalwatch_backup"
fi

install -m 755 "$goalwatch_root/packaging/bin/goalwatch" "$goalwatch_bin"
install -m 644 "$goalwatch_root/packaging/systemd/goalwatch.service" "$goalwatch_unit"

if [[ $(realpath -m "$goalwatch_root") != $(realpath -m "$goalwatch_plugin") ]]; then
  goalwatch_plugin_stage="$(mktemp -d "$goalwatch_config_home/omarchy/plugins/.goalwatch.XXXXXX")"
  goalwatch_plugin_backup="$goalwatch_config_home/omarchy/plugins/.com.goalwatch.previous.$$"
  cp -a "$goalwatch_root/integrations/omarchy/com.goalwatch/." "$goalwatch_plugin_stage/"
  if [[ -d $goalwatch_plugin ]]; then
    mv -- "$goalwatch_plugin" "$goalwatch_plugin_backup"
  fi
  mv -- "$goalwatch_plugin_stage" "$goalwatch_plugin"
  if [[ -d $goalwatch_plugin_backup ]]; then
    rm -rf -- "$goalwatch_plugin_backup"
  fi
fi

install -m 644 "$goalwatch_root/README.md" "$goalwatch_doc/README.md"
install -m 644 "$goalwatch_root/LICENSE" "$goalwatch_doc/LICENSE"
if [[ -d $goalwatch_root/docs ]]; then
  rm -rf -- "$goalwatch_doc/docs"
  cp -a "$goalwatch_root/docs" "$goalwatch_doc/docs"
fi

systemctl --user daemon-reload
"$goalwatch_bin" state-off

omarchy-shell shell rescanPlugins >/dev/null
omarchy plugin validate "$goalwatch_plugin"

if ! python3 - "$goalwatch_config_home/omarchy/shell.json" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
except (OSError, ValueError):
    raise SystemExit(1)
for section in (data.get("bar", {}).get("layout", {}) or {}).values():
    if isinstance(section, list) and any(isinstance(item, dict) and item.get("id") == "com.goalwatch" for item in section):
        raise SystemExit(0)
raise SystemExit(1)
PY
then
  omarchy plugin enable com.goalwatch --section right
fi

if [[ $goalwatch_skip_obsidian == false && $goalwatch_with_obsidian == false ]]; then
  if "$goalwatch_bin" obsidian status \
      | python3 -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin).get("enabled") is True else 1)'; then
    goalwatch_with_obsidian=true
  fi
fi

if [[ $goalwatch_with_obsidian == true ]]; then
  if ! "$goalwatch_bin" obsidian enable "${goalwatch_vault_args[@]}"; then
    echo "GoalWatch itself is installed, but Obsidian Sync could not be enabled." >&2
    echo "Open/create a local vault and use the one-tap switch in the GoalWatch panel." >&2
    if [[ $goalwatch_obsidian_explicit == true ]]; then
      goalwatch_obsidian_failed=true
    fi
  else
    goalwatch_obsidian_ready=true
  fi
fi

if [[ $goalwatch_was_active == true ]]; then
  systemctl --user start goalwatch.service
fi

echo
echo "GoalWatch is installed."
echo "  Eye/gear: Omarchy bar, right section"
echo "  CLI:      $goalwatch_bin"
echo "  Service:  $goalwatch_unit"
echo "  Plugin:   $goalwatch_plugin"
echo
if [[ $goalwatch_was_active == true ]]; then
  echo "The service was running before the update and is running again."
else
  echo "The service is off until you click the eye."
fi
if [[ $goalwatch_obsidian_ready == true ]]; then
  echo "Obsidian Sync is configured. Follow any reload note shown above."
else
  echo "Obsidian Sync is optional and can be connected from the panel with one tap."
fi

if [[ $goalwatch_obsidian_failed == true ]]; then
  exit 1
fi
