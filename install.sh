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
command -v flock >/dev/null 2>&1 || {
  echo "GoalWatch requires util-linux flock." >&2
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

install -d -m 700 "$goalwatch_app_parent"
exec 9<"$goalwatch_app_parent"
flock -n 9 || {
  echo "Another GoalWatch installation is already running." >&2
  exit 1
}
install -d -m 755 \
  "$HOME/.local/bin" \
  "$goalwatch_config_home/systemd/user" \
  "$goalwatch_config_home/omarchy/plugins" \
  "$(dirname -- "$goalwatch_doc")"

goalwatch_was_active=false
goalwatch_transaction_started=false
goalwatch_committed=false
goalwatch_widget_added=false
goalwatch_manage_plugin=true
goalwatch_stages=()
goalwatch_targets=()
goalwatch_backups=()
goalwatch_had_old=()

if [[ $(realpath -m "$goalwatch_root") == $(realpath -m "$goalwatch_plugin") ]]; then
  goalwatch_manage_plugin=false
fi

path_exists() {
  [[ -e $1 || -L $1 ]]
}

remove_exact_path() {
  local target="$1"
  [[ -n $target && $target != / && $target != "$HOME" ]] || {
    echo "Refusing unsafe transaction cleanup target: $target" >&2
    return 1
  }
  if [[ -d $target && ! -L $target ]]; then
    rm -rf -- "$target"
  else
    rm -f -- "$target"
  fi
}

swap_target() {
  local target="$1"
  local staged="$2"
  local backup="${target}.goalwatch-previous.$$"
  local had_old=false
  if path_exists "$backup"; then
    echo "Refusing to overwrite transaction backup: $backup" >&2
    return 1
  fi
  if path_exists "$target"; then
    had_old=true
    mv -- "$target" "$backup"
  fi
  goalwatch_targets+=("$target")
  goalwatch_backups+=("$backup")
  goalwatch_had_old+=("$had_old")
  mv -- "$staged" "$target"
}

cleanup_stages() {
  local path
  for path in "${goalwatch_stages[@]}"; do
    path_exists "$path" && remove_exact_path "$path"
  done
}

discard_backups() {
  local path
  for path in "${goalwatch_backups[@]}"; do
    path_exists "$path" && remove_exact_path "$path"
  done
}

rollback_install() {
  local index target backup had_old
  if systemctl --user is-active --quiet goalwatch.service 2>/dev/null; then
    systemctl --user stop goalwatch.service >/dev/null 2>&1 || true
  fi
  if [[ $goalwatch_widget_added == true ]]; then
    omarchy-shell shell setPluginEnabled com.goalwatch false >/dev/null 2>&1 || true
  fi
  for (( index=${#goalwatch_targets[@]}-1; index>=0; index-- )); do
    target="${goalwatch_targets[$index]}"
    backup="${goalwatch_backups[$index]}"
    had_old="${goalwatch_had_old[$index]}"
    path_exists "$target" && remove_exact_path "$target"
    if [[ $had_old == true ]] && path_exists "$backup"; then
      mv -- "$backup" "$target"
    fi
  done
  systemctl --user daemon-reload >/dev/null 2>&1 || true
  if [[ -x $goalwatch_bin ]]; then
    "$goalwatch_bin" state-off >/dev/null 2>&1 || true
  fi
  omarchy-shell shell rescanPlugins >/dev/null 2>&1 || true
}

finish_install() {
  local status=$?
  trap - EXIT INT TERM HUP
  set +e
  if [[ $status -ne 0 && $goalwatch_transaction_started == true && $goalwatch_committed == false ]]; then
    echo "Installation failed; restoring the previous GoalWatch state." >&2
    rollback_install
  fi
  cleanup_stages
  if [[ $goalwatch_committed == true ]]; then
    discard_backups
  fi
  if [[ $goalwatch_was_active == true ]] && ! systemctl --user is-active --quiet goalwatch.service 2>/dev/null; then
    if ! systemctl --user start goalwatch.service; then
      echo "Could not restore the previously active GoalWatch service." >&2
      status=1
    fi
  fi
  exit "$status"
}

trap finish_install EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP

goalwatch_app_stage="$(mktemp -d "$goalwatch_app_parent/.install.XXXXXX")"
goalwatch_stages+=("$goalwatch_app_stage")
cp -a "$goalwatch_root/src/goalwatch" "$goalwatch_app_stage/goalwatch"
cp -a "$goalwatch_root/integrations/obsidian/goalwatch" "$goalwatch_app_stage/goalwatch/_obsidian"
find "$goalwatch_app_stage/goalwatch" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
find "$goalwatch_app_stage/goalwatch" -depth -type d -name '__pycache__' -empty -delete

goalwatch_bin_stage="$(mktemp "$HOME/.local/bin/.goalwatch.XXXXXX")"
goalwatch_stages+=("$goalwatch_bin_stage")
install -m 755 "$goalwatch_root/packaging/bin/goalwatch" "$goalwatch_bin_stage"

goalwatch_unit_stage="$(mktemp --suffix=.service "$goalwatch_config_home/systemd/user/.goalwatch.XXXXXX")"
goalwatch_stages+=("$goalwatch_unit_stage")
install -m 644 "$goalwatch_root/packaging/systemd/goalwatch.service" "$goalwatch_unit_stage"

goalwatch_doc_stage="$(mktemp -d "$(dirname -- "$goalwatch_doc")/.goalwatch-doc.XXXXXX")"
goalwatch_stages+=("$goalwatch_doc_stage")
install -m 644 "$goalwatch_root/README.md" "$goalwatch_doc_stage/README.md"
install -m 644 "$goalwatch_root/LICENSE" "$goalwatch_doc_stage/LICENSE"
cp -a "$goalwatch_root/docs" "$goalwatch_doc_stage/docs"

if [[ $goalwatch_manage_plugin == true ]]; then
  goalwatch_plugin_stage="$(mktemp -d "$goalwatch_config_home/omarchy/plugins/.goalwatch.XXXXXX")"
  goalwatch_stages+=("$goalwatch_plugin_stage")
  cp -a "$goalwatch_root/integrations/omarchy/com.goalwatch/." "$goalwatch_plugin_stage/"
  omarchy plugin validate "$goalwatch_plugin_stage"
else
  omarchy plugin validate "$goalwatch_plugin"
fi
systemd-analyze --user verify "$goalwatch_unit_stage"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$goalwatch_app_stage" \
  python3 -c 'import goalwatch, goalwatch.cli, goalwatch.daemon'

if systemctl --user is-active --quiet goalwatch.service 2>/dev/null; then
  goalwatch_was_active=true
  systemctl --user stop goalwatch.service
fi
goalwatch_transaction_started=true

swap_target "$goalwatch_app" "$goalwatch_app_stage"
swap_target "$goalwatch_bin" "$goalwatch_bin_stage"
swap_target "$goalwatch_unit" "$goalwatch_unit_stage"
swap_target "$goalwatch_doc" "$goalwatch_doc_stage"
if [[ $goalwatch_manage_plugin == true ]]; then
  swap_target "$goalwatch_plugin" "$goalwatch_plugin_stage"
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
  goalwatch_widget_added=true
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
      exit 1
    fi
  else
    goalwatch_obsidian_ready=true
  fi
fi

if [[ $goalwatch_was_active == true ]]; then
  systemctl --user start goalwatch.service
fi

goalwatch_committed=true

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
