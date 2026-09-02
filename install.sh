#!/usr/bin/env bash
set -euo pipefail

goalwatch_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
goalwatch_data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
goalwatch_config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
goalwatch_runtime_home="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
goalwatch_app_parent="$goalwatch_data_home/goalwatch"
goalwatch_app="$goalwatch_app_parent/app"
goalwatch_bin="$HOME/.local/bin/goalwatch"
goalwatch_unit="$goalwatch_config_home/systemd/user/goalwatch.service"
goalwatch_plugin="$goalwatch_config_home/omarchy/plugins/com.goalwatch"
goalwatch_doc="$goalwatch_data_home/doc/goalwatch"
goalwatch_with_obsidian=false
goalwatch_skip_obsidian=false
goalwatch_skip_packages=false
goalwatch_requested_vault=""
goalwatch_transaction_vault=""
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
      [[ -z $goalwatch_requested_vault ]] || {
        echo "--vault may only be provided once" >&2
        exit 2
      }
      if [[ ${#2} -gt 4096 || $2 == *$'\n'* || $2 == *$'\r'* || $2 == *$'\t'* ]]; then
        echo "--vault contains an invalid or excessive path" >&2
        exit 2
      fi
      goalwatch_requested_vault="$2"
      goalwatch_with_obsidian=true
      shift 2
      ;;
    --with-obsidian)
      goalwatch_with_obsidian=true
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
  path_exists "$target" && had_old=true
  goalwatch_targets+=("$target")
  goalwatch_backups+=("$backup")
  goalwatch_had_old+=("$had_old")
  if [[ $had_old == true ]]; then
    mv -- "$target" "$backup"
  fi
  mv -- "$staged" "$target"
}

snapshot_target() {
  local target="$1"
  local backup="${target}.goalwatch-previous.$$"
  local had_old=false
  if path_exists "$backup"; then
    echo "Refusing to overwrite transaction backup: $backup" >&2
    return 1
  fi
  path_exists "$target" && had_old=true
  goalwatch_targets+=("$target")
  goalwatch_backups+=("$backup")
  goalwatch_had_old+=("$had_old")
  if [[ $had_old == true ]]; then
    mv -- "$target" "$backup"
    if ! cp -a -- "$backup" "$target"; then
      path_exists "$target" && remove_exact_path "$target"
      mv -- "$backup" "$target"
      return 1
    fi
  fi
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
  for (( index=${#goalwatch_targets[@]}-1; index>=0; index-- )); do
    target="${goalwatch_targets[$index]}"
    backup="${goalwatch_backups[$index]}"
    had_old="${goalwatch_had_old[$index]}"
    if [[ $had_old == true ]] && path_exists "$backup"; then
      path_exists "$target" && remove_exact_path "$target"
      mv -- "$backup" "$target"
    elif [[ $had_old == false ]]; then
      path_exists "$target" && remove_exact_path "$target"
    fi
  done
  systemctl --user daemon-reload >/dev/null 2>&1 || true
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

if [[ $goalwatch_skip_obsidian == false ]]; then
  if [[ -z $goalwatch_requested_vault ]]; then
    goalwatch_obsidian_status="$({
      PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$goalwatch_app_stage" \
        python3 -m goalwatch obsidian status
    } 2>/dev/null || true)"
    readarray -t goalwatch_obsidian_fields < <(
      python3 -c '
import json, sys
try:
    raw = sys.stdin.buffer.read(262145)
    if len(raw) > 262144:
        raise ValueError
    value = json.loads(raw)
    enabled = value.get("enabled") is True
    installed = value.get("installed") is True
    vault = value.get("vault", "")
    if not isinstance(vault, str) or len(vault) > 4096 or any(ord(c) < 32 for c in vault):
        raise ValueError
except (OSError, ValueError, AttributeError):
    print("false")
    print("false")
    print("")
else:
    print("true" if enabled else "false")
    print("true" if installed else "false")
    print(vault)
' <<<"$goalwatch_obsidian_status"
    )
    if [[ $goalwatch_with_obsidian == false \
        && ${goalwatch_obsidian_fields[0]:-false} == true \
        && ${goalwatch_obsidian_fields[1]:-false} == true ]]; then
      goalwatch_with_obsidian=true
    fi
    if [[ $goalwatch_with_obsidian == true ]]; then
      goalwatch_transaction_vault="${goalwatch_obsidian_fields[2]:-}"
    fi
  else
    goalwatch_transaction_vault="$({
      PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$goalwatch_app_stage" python3 - \
        "$goalwatch_requested_vault" <<'PY'
import os
import sys
from pathlib import Path

raw = sys.argv[1]
if len(raw) > 4096 or any(ord(character) < 32 for character in raw):
    raise SystemExit(2)
candidate = Path(os.path.abspath(os.path.expanduser(raw))).resolve()
if not candidate.is_dir() or not (candidate / ".obsidian").is_dir():
    raise SystemExit("--vault is not an Obsidian vault")
if (candidate / ".obsidian").is_symlink():
    raise SystemExit("--vault has a symlinked .obsidian directory")
print(candidate)
PY
    })"
  fi
  if [[ $goalwatch_with_obsidian == true && -z $goalwatch_transaction_vault ]]; then
    echo "No safe local Obsidian vault is available for the requested integration." >&2
    exit 1
  fi
  if [[ $goalwatch_with_obsidian == true ]]; then
    goalwatch_transaction_vault="$({
      PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$goalwatch_app_stage" python3 - \
        "$goalwatch_transaction_vault" <<'PY'
import os
import sys
from pathlib import Path

raw = sys.argv[1]
if len(raw) > 4096 or any(ord(character) < 32 for character in raw):
    raise SystemExit("Obsidian vault path is invalid")
candidate = Path(os.path.abspath(os.path.expanduser(raw))).resolve()
obsidian = candidate / ".obsidian"
if not candidate.is_dir() or not obsidian.is_dir() or obsidian.is_symlink():
    raise SystemExit("Obsidian vault is unavailable or unsafe")
print(candidate)
PY
    })"
  fi
fi

if systemctl --user is-active --quiet goalwatch.service 2>/dev/null; then
  goalwatch_was_active=true
  systemctl --user stop goalwatch.service
fi
goalwatch_transaction_started=true

snapshot_target "$goalwatch_config_home/omarchy/shell.json"
snapshot_target "$goalwatch_runtime_home/goalwatch"
if [[ $goalwatch_with_obsidian == true ]]; then
  snapshot_target "$goalwatch_config_home/goalwatch"
  snapshot_target "$goalwatch_transaction_vault/.obsidian/plugins/goalwatch"
  snapshot_target "$goalwatch_transaction_vault/.obsidian/community-plugins.json"
fi

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

if python3 - "$goalwatch_config_home/omarchy/shell.json" <<'PY'
import fcntl
import json
import os
import stat
import sys

try:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(sys.argv[1], flags)
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_size > 1024 * 1024
        ):
            raise OSError("unsafe shell configuration")
        current = fcntl.fcntl(descriptor, fcntl.F_GETFL)
        fcntl.fcntl(descriptor, fcntl.F_SETFL, current & ~os.O_NONBLOCK)
        raw = os.read(descriptor, 1024 * 1024 + 1)
    finally:
        os.close(descriptor)
    if len(raw) > 1024 * 1024:
        raise OSError("oversized shell configuration")
    data = json.loads(raw)
except FileNotFoundError:
    raise SystemExit(1)
except (OSError, ValueError, AttributeError):
    raise SystemExit(2)
for section in (data.get("bar", {}).get("layout", {}) or {}).values():
    if isinstance(section, list) and any(isinstance(item, dict) and item.get("id") == "com.goalwatch" for item in section):
        raise SystemExit(0)
raise SystemExit(1)
PY
then
  :
else
  goalwatch_shell_status=$?
  if [[ $goalwatch_shell_status -eq 2 ]]; then
    echo "Refusing unsafe or oversized Omarchy shell configuration." >&2
    exit 1
  fi
  omarchy plugin enable com.goalwatch --section right
fi

if [[ $goalwatch_with_obsidian == true ]]; then
  if ! "$goalwatch_bin" obsidian enable --defer-live-reload \
      --vault "$goalwatch_transaction_vault"; then
    echo "Obsidian Sync could not be updated safely; the entire installation will be restored." >&2
    exit 1
  fi
  goalwatch_obsidian_ready=true
fi

if [[ $goalwatch_was_active == true ]]; then
  systemctl --user start goalwatch.service
  sleep 0.15
  if ! systemctl --user is-active --quiet goalwatch.service; then
    echo "The replacement GoalWatch service did not remain active." >&2
    exit 1
  fi
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
