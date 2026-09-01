<p align="center">
  <img src="assets/banner.png" alt="GoalWatch — Stay on goal" width="100%">
</p>

<p align="center">
  <strong>A silent, screen-aware focus guard for Omarchy and Obsidian.</strong>
</p>

GoalWatch runs as a small systemd user service. At a configurable interval it
reads the latest goal from an Obsidian note, captures the visible Wayland
desktop in memory, and asks Gemini whether the screen is useful to that goal.
On-goal and ambiguous activity stay silent. A clear deviation opens a blocking
intervention on every display.

GoalWatch is Omarchy-first software, not a conventional desktop application.
Its controls live in the Omarchy bar and its goal workflow lives in Obsidian.

## What ships

- A Python standard-library daemon with no virtual environment or Python package dependencies.
- A native Omarchy/Quickshell eye that toggles the service and exposes settings and status.
- A full-screen, keyboard-exclusive alert that cannot be dismissed by Escape or an outside click.
- An Obsidian plugin for Daily Notes, current-file selection, goal insertion, and `@goal` expansion.
- Exact Gemini structured output with conservative classification and fail-open error handling.
- Local, content-free metrics for focus score, checks, alerts, latency, usage, and return-to-goal time.
- User-local install, update, and uninstall scripts. Nothing under `/usr/share/omarchy` is modified.

## The intervention

![GoalWatch off-goal intervention](assets/alert-preview.png)

The charcoal surface completely occludes the desktop. Alert red is limited to
the off-goal signal, diagnosis, and acknowledgement action. The eye uses the
same canonical geometry at bar, panel, and alert sizes.

## How it works

```text
Obsidian note ── goal/file path ──▶ GoalWatch CLI/config
                                           │
Omarchy eye ── start/stop/settings ─────────┤
                                           ▼
                                 systemd user service
                              Markdown  grim  Secret Service
                                  └──── prompt + JPEG ────▶ Gemini
                                                            │
                             Quickshell overlay ◀── runtime state
                             Local metrics      ◀── metadata only
```

Checks run on monotonic deadlines and never overlap. Screenshots are read from
`grim` through stdout, sent once, and discarded without being written to disk.
Invalid model output, network problems, missing setup, capture failures, and a
locked session never create an alert.

## Requirements

- Omarchy with its Quickshell bar and a Wayland session.
- A systemd user session.
- Obsidian desktop for the companion workflow; optional for a manually selected Markdown file.
- A [Gemini API key](https://aistudio.google.com/api-keys).

The installer supplies missing Arch packages for Python, `grim`, and
`secret-tool` through Omarchy's package command.

## Install

Add the public repository through Omarchy, then run the included setup script:

```bash
omarchy plugin add https://github.com/JuanCamiloGrA/goalwatch.git --yes
~/.config/omarchy/plugins/com.goalwatch/install.sh
```

Omarchy deliberately clones third-party plugins disabled and never runs install
hooks. The second command is the explicit setup step for this hybrid plugin: it
installs missing system packages through Omarchy, copies the Python runtime,
adds the systemd user service, discovers and enables the Obsidian companion,
validates and enables the bar widget, and preserves the Git checkout for future
`omarchy plugin update` operations. GoalWatch remains off after a first install.

To install from a development checkout instead:

```bash
git clone https://github.com/JuanCamiloGrA/goalwatch.git
cd goalwatch
./install.sh
```

Useful installer options:

```bash
./install.sh --vault /absolute/path/to/vault
./install.sh --vault /vault/one --vault /vault/two
./install.sh --skip-obsidian
./install.sh --skip-packages
```

Use `--vault` when Obsidian has not registered the intended vault.
`--skip-packages` turns missing dependencies into an error instead of installing
them.

## Update

For a marketplace checkout, review and pull the update with Omarchy, then
rerun setup so the background runtime and integrations match the new QML:

```bash
omarchy plugin update com.goalwatch
~/.config/omarchy/plugins/com.goalwatch/install.sh
```

For a development checkout, pull the repository and rerun `./install.sh`.

## First run

1. Reload Obsidian once after installation.
2. Open the gear beside the GoalWatch eye in the Omarchy bar.
3. Enter a Gemini API key. The field replaces the stored key and never reveals it.
4. Type `@goal` in a Markdown note or run **GoalWatch: Add goal**.
5. Write the goal after `Current Goal:` and click the gray eye.

The eye turns electric blue while the service is watching. No screenshot or
request is made until the first full interval has elapsed.

## Goal format

```markdown
> Current Goal: Finish the GoalWatch release
>
> Available Tools: Codex, Browser, Obsidian and any tool useful to the goal.
```

The final valid block in the selected file wins. The tools sentence is editable
and is sent with the goal so relevant setup and research are not misclassified.

The Obsidian companion provides:

- **GoalWatch: Use today's daily note** — follows the configured Daily Notes folder and date format.
- **GoalWatch: Use current file** — uses the active Markdown file for the current date.
- **GoalWatch: Add goal** — inserts the canonical block at the cursor.
- `@goal` — expands to the same block while typing in a Markdown editor.

Manual file selection remains active for the current date. A new Daily Notes
path on the next date resumes automatic daily-note following.

## Settings

| Setting | Behavior |
|---|---|
| Interval | `5` minutes by default; accepts `1–1440` and restarts the countdown when changed. |
| Model | `gemini-flash-lite-latest` by default; applied on the next check. |
| API Key | Empty replacement field backed by Secret Service; double-click the label to open Google AI Studio. |
| Markdown File | Daily path supplied by Obsidian or an absolute manual path. |

Changes save automatically. Invalid values remain unsaved and visible in the
panel. When an alert is active, checks pause until **I’LL GET BACK TO WORK** is
pressed; acknowledgement starts a fresh countdown.

## Privacy and local data

Each enabled check sends the current goal, available-tools sentence, and one
compressed screenshot directly to Google's Gemini API. GoalWatch has no proxy,
account service, telemetry endpoint, or screenshot history.

- Screenshots stay in memory and are never saved by GoalWatch.
- The Gemini key is stored in the desktop Secret Service and never appears in config, argv, UI state, metrics, or logs.
- Metrics never retain goal text, screenshots, visible text, window titles, or Gemini explanations.
- Local metric rows are pruned after 90 days.
- Stopping GoalWatch cancels future captures and requests.

See [docs/PRIVACY.md](docs/PRIVACY.md) for the exact data boundary and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for component ownership.

## CLI and diagnostics

```bash
goalwatch start                 # enable watching
goalwatch stop                  # disable watching
goalwatch toggle                # toggle the service
goalwatch status                # current runtime state as JSON
goalwatch metrics               # local aggregate metrics
goalwatch run-once              # one credentialed check now
goalwatch dismiss               # recovery path for an active alert
goalwatch doctor                # dependency and session diagnostics
goalwatch config show           # public configuration; never the key
```

Set or replace the key through stdin so it never enters the process arguments:

```bash
printf '%s\n' "$GEMINI_API_KEY" | goalwatch config set-api-key
```

Test the alert without taking a screenshot or spending API quota:

```bash
goalwatch debug alert --goal "Ship the release" \
  --complement "The current screen does not contribute to the release."
goalwatch debug clear
```

Service diagnostics:

```bash
systemctl --user status goalwatch.service
journalctl --user -u goalwatch.service -n 100
omarchy plugin validate ~/.config/omarchy/plugins/com.goalwatch
```

## Development

Run the complete offline verification suite:

```bash
./scripts/test.sh
```

It covers the Python core, Gemini schema and failure paths, scheduling,
configuration safety, local metrics, shell/JSON/QML checks, and the Obsidian
integration. The optional `./scripts/ai_benchmark.py` makes eight labelled live
Gemini requests using the locally stored key; it reports precision and false
alert rate without retaining responses.

Repository map:

```text
manifest.json, preview.png               Omarchy marketplace contract
src/goalwatch/                         daemon, CLI, capture, Gemini, state, metrics
integrations/omarchy/com.goalwatch/    Quickshell bar, panel, and alert
integrations/obsidian/goalwatch/       Obsidian desktop companion
packaging/                             CLI launcher and systemd user unit
scripts/                               installer support, tests, AI benchmark
tests/                                 offline tests and non-sensitive AI fixtures
docs/                                  architecture, privacy, measured verification
assets/                                canonical brand and UI previews
```

Before contributing, read [AGENTS.md](AGENTS.md). Its constraints apply equally
to human-written and AI-assisted changes. The full product contract is in
[PLAN.md](PLAN.md), and measured acceptance results are in
[docs/VERIFICATION.md](docs/VERIFICATION.md).

## Uninstall

For a marketplace installation, run the bundled uninstaller rather than
`omarchy plugin remove` alone. Omarchy removes only the Git checkout and cannot
know about GoalWatch's user service or Obsidian integration.

```bash
~/.config/omarchy/plugins/com.goalwatch/uninstall.sh
```

This removes the runtime and both integrations while preserving config, key,
and metrics. From a development checkout, use `./uninstall.sh` instead. Remove
local data too with:

```bash
~/.config/omarchy/plugins/com.goalwatch/uninstall.sh --purge
```

Uninstalling never edits or deletes Markdown notes.

## License

[MIT](LICENSE) © 2026 Juan Camilo Grisales Arias.
