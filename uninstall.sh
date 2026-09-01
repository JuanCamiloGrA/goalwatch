#!/usr/bin/env bash
set -euo pipefail

goalwatch_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
goalwatch_data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
goalwatch_config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
goalwatch_purge=false
goalwatch_skip_obsidian=false
goalwatch_vault_args=()

while (( $# > 0 )); do
  case "$1" in
    --purge) goalwatch_purge=true; shift ;;
    --skip-obsidian) goalwatch_skip_obsidian=true; shift ;;
    --vault)
      [[ $# -ge 2 ]] || { echo "--vault requires a path" >&2; exit 2; }
      goalwatch_vault_args+=(--vault "$2")
      shift 2
      ;;
    -h|--help)
      echo "Usage: ./uninstall.sh [--purge] [--skip-obsidian] [--vault PATH]"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

systemctl --user disable --now goalwatch.service >/dev/null 2>&1 || true

if command -v omarchy >/dev/null 2>&1; then
  omarchy plugin disable com.goalwatch >/dev/null 2>&1 || true
fi

if [[ $goalwatch_skip_obsidian == false ]]; then
  python3 "$goalwatch_root/scripts/obsidian_plugin.py" uninstall "${goalwatch_vault_args[@]}" || true
fi

rm -f -- "$goalwatch_config_home/systemd/user/goalwatch.service"
rm -f -- "$HOME/.local/bin/goalwatch"
rm -rf -- "$goalwatch_data_home/goalwatch/app"
rm -rf -- "$goalwatch_config_home/omarchy/plugins/com.goalwatch"
rm -rf -- "$goalwatch_data_home/doc/goalwatch"
rm -rf -- "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/goalwatch"
systemctl --user daemon-reload
omarchy-shell shell rescanPlugins >/dev/null 2>&1 || true

if [[ $goalwatch_purge == true ]]; then
  secret-tool clear service goalwatch account gemini >/dev/null 2>&1 || true
  rm -rf -- "$goalwatch_config_home/goalwatch"
  rm -rf -- "${XDG_STATE_HOME:-$HOME/.local/state}/goalwatch"
  echo "GoalWatch and its local configuration, secret, and metrics were removed."
else
  echo "GoalWatch was removed. Configuration, API key, and metrics were preserved."
fi
