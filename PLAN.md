# GoalWatch MVP — Requirements and Definition of Done

## Product statement

GoalWatch is a lightweight, Omarchy-first focus guard. It runs as a background
user service, reads the latest goal block from the selected Obsidian Markdown
file, periodically judges the visible desktop against that goal with Gemini,
and stays completely silent unless the activity is clearly off goal.

All user-facing copy, settings, commands, notices, logs intended for users, and
documentation shipped with the product will be written in English.

## Confirmed implementation context

- Target system: Omarchy 4.0.2, Quickshell 0.3.1, Hyprland/Wayland.
- Available system dependencies: Python 3.14, `grim`, `secret-tool`, systemd user services.
- The existing `m1kode.obsidian-tasks` plugin and `Omarchy Daily Tasks` Obsidian
  plugin are reference implementations only; GoalWatch will not modify them.
- The current daily-note resolver uses Obsidian's Daily Notes folder and date
  format, then sends the resulting vault-relative file path through
  `omarchy bar set`. GoalWatch will preserve that behavior.
- The repository is prepared as an MIT-licensed open-source project with source,
  tests, integrations, installation tooling, contributor rules, and verified assets.

## MVP boundaries

### Included

- Omarchy/Hyprland background service and CLI.
- Quickshell bar widget, settings panel, status, metrics summary, and alert overlay.
- Obsidian desktop plugin with current-file/daily-note synchronization and goal insertion.
- Gemini multimodal classification with an exact structured response.
- Local, privacy-minimized operational metrics.
- User-local install, update, uninstall, and troubleshooting documentation.

### Not included in the MVP

- A conventional desktop application or cross-platform GUI.
- Browser extensions, content blocking, process termination, or forced app closure.
- Cloud accounts, remote dashboards, screenshot history, or cross-device metric sync.
- Automatic API billing configuration or model-price calculations.
- Personalized model training.

## Proposed architecture

```text
Obsidian plugin ──file/daily path──▶ GoalWatch CLI/config
                                           │
Quickshell eye/gear ──start/stop/config─────┤
                                           ▼
                                systemd --user service
                                Python stdlib daemon
                                  │   │          │
                              Markdown grim   Secret Service
                                  │   │          │
                                  └── prompt + screenshot
                                              │
                                              ▼
                                        Gemini REST API
                                              │
                                      {alert, complement}
                                              │
                         runtime state + local metric events
                                              │
                                              ▼
                             Quickshell all-monitor overlay
```

### 1. Core daemon and CLI

- A small Python package using only the standard library at runtime.
- No Google SDK, web framework, virtual environment, or resident database server.
- A systemd user service is installed but disabled by default. The eye button
  starts and stops it; stopping cancels pending work and sends no more requests.
- The daemon sleeps until the next monotonic deadline. It never busy-polls and
  never allows two checks to overlap.
- `grim` captures the full Wayland desktop as a scaled, compressed JPEG. Bytes
  flow through memory and are never written as a screenshot file.
- A direct Gemini REST request carries the goal, allowed-tools text, and image.
- A tiny local CLI exposes status, start, stop, toggle, run-once, dismiss,
  configuration, secret replacement, and Obsidian file synchronization.

### 2. Local paths and data ownership

- Non-secret config: `${XDG_CONFIG_HOME:-~/.config}/goalwatch/config.json`, mode `0600`.
- Ephemeral UI state: `${XDG_RUNTIME_DIR}/goalwatch/state.json`, written atomically.
- Metrics: `${XDG_STATE_HOME:-~/.local/state}/goalwatch/metrics.sqlite3`, mode `0600`.
- Gemini API key: the desktop Secret Service via `secret-tool`; never config files.
- Runtime source and integrations install beneath user-owned locations only.
- Nothing under `/usr/share/omarchy/` is modified.

### 3. Goal extraction contract

The selected Markdown file may contain several goal blocks. The final valid
occurrence in file order wins:

```markdown
> Current Goal: Finish the GoalWatch MVP
>
> Available Tools: Codex, Browser, Obsidian and any tool useful to the goal.
```

Rules:

- `Current Goal` must contain non-whitespace text.
- `Available Tools` defaults to the exact text above when omitted by the goal
  insertion flow, but a value written by the user in Markdown always wins.
- Whitespace and CRLF are tolerated; unrelated blockquotes are ignored.
- A malformed final block does not erase an earlier valid block.
- Missing file, missing goal, unreadable file, or empty goal produces a quiet
  `SETUP REQUIRED`/`NO GOAL` state and no Gemini request.
- Manual path selection is valid for the rest of the current day. A genuinely
  new daily path on the next date resumes daily-note following automatically.

### 4. Gemini decision contract

Default model: `gemini-flash-lite-latest`, editable by the user.

The response schema has exactly these fields:

```json
{
  "alert": true,
  "complement": "This activity is unrelated to preparing the Q2 report."
}
```

- `alert` is required and boolean.
- `complement` is required and non-empty only when `alert` is true; it is an
  empty string when `alert` is false.
- Screenshot text is explicitly treated as untrusted visual content, never as
  model instructions. This limits prompt-injection from pages visible on screen.
- The classifier is conservative: direct work, relevant research, required
  setup, communication needed for the goal, and ambiguous screens remain silent.
- Clear unrelated entertainment, social browsing, or unrelated work returns an alert.
- Invalid JSON, schema mismatch, network failure, timeout, rate limit, missing
  key, capture failure, locked session, or powered-off outputs fail open: no alert.
- Errors appear only inside settings/status and logs; they never create an intervention.
- The request has a bounded timeout and no immediate retry storm. The next normal
  interval is the retry.

### 5. Scheduling behavior

- Default interval: 5 minutes; accepted range: 1–1440 minutes.
- Enabling GoalWatch starts a fresh countdown instead of immediately capturing.
- Editing the interval atomically saves it and restarts the countdown from zero.
- Editing the model or Markdown path affects the next check without restarting
  the shell. Replacing the API key affects the next check.
- While an alert is visible, checks are paused so GoalWatch never classifies its
  own intervention. Dismissing the alert starts a fresh countdown.
- Suspend/resume and large wall-clock jumps do not trigger a burst of missed checks.
- At most one Gemini request is made per elapsed interval.

## Omarchy plugin Definition of Done

### Bar widget

- A geometric eye is rendered as native vector/QML geometry and remains crisp at
  16, 20, and 24 px.
- `OFF`: canonical eye in dim gray.
- `WATCHING`: open eye with an electric-blue center (`#3A8DFF`).
- `ALERT`: red eye only while a real off-goal result is active (`#FF4D4F`).
- No gradients. Red is never used for configuration or connectivity errors.
- Clicking the eye toggles the systemd user service with optimistic feedback,
  then reconciles with real service state.
- A distinct gear opens the settings/status panel. The widget tooltip always
  communicates the real state: `OFF`, `STARTING`, `WATCHING`, `CHECKING`,
  `SETUP REQUIRED`, or `ALERT`.

### Settings/status panel

- Uses the existing Omarchy panel primitives and theme spacing, with Inter,
  Geist, or the shell's sans-serif fallback.
- Shows `CURRENT GOAL`, service state, current-session duration, focus score,
  last check, next check, checks, alerts, and API latency/usage totals.
- Settings auto-save safely:
  - `Interval (minutes)` defaults to `5`; a valid edit resets the countdown.
  - `Model` defaults to `gemini-flash-lite-latest`.
  - `API Key` is always an empty replacement field with placeholder
    `Enter a new key to replace the saved key`.
  - The current key is never returned to QML, displayed, copied, or logged.
  - Double-clicking the `API Key` label opens
    `https://aistudio.google.com/api-keys` in the default browser.
  - `Markdown File` accepts an absolute path or the file synchronized by Obsidian.
- API-key replacement travels from QML to the CLI over child-process stdin, not
  process arguments. The field clears immediately after a successful save.
- Invalid values remain visibly unsaved and do not corrupt the last valid config.

### Fullscreen alert

- One overlay surface covers every connected monitor at the Wayland overlay layer.
- A charcoal surface completely occludes the desktop. Alert red is reserved for
  the off-goal status, diagnostic accent, canonical eye, and primary action.
- The layout uses a restrained system-HUD hierarchy with a large canonical eye,
  clear goal context, and no gradients or decorative productivity copy.
- Copy is English and minimal: `OFF GOAL`, the current goal, Gemini's complement,
  and one primary button labeled `I’LL GET BACK TO WORK`.
- Clicking outside or pressing Escape does not dismiss it. The overlay consumes
  pointer and keyboard focus while visible.
- The primary button dismisses the current alert, records acknowledgement, and
  resets the interval. A CLI `goalwatch dismiss` remains available as a recovery path.
- When Gemini returns `alert: false`, no window, notification, sound, animation,
  or other interruption is produced.

## Obsidian plugin Definition of Done

- Plugin name and all commands/notices are in English.
- `GoalWatch: Use today's daily note` resolves the file exactly like the current
  integration: Daily Notes folder + configured date format + `.md`.
- It synchronizes the vault path and vault-relative daily path on layout ready,
  checks once per minute for a date change, and does not rewrite unchanged state.
- `GoalWatch: Use current file` sends the active Markdown file to GoalWatch as
  today's manual override.
- `GoalWatch: Add goal` inserts the canonical block at the cursor and positions
  the cursor after `Current Goal:`.
- Typing `@goal` in a Markdown editor atomically replaces only that trigger with
  the canonical block and positions the cursor for the goal description.
- The default tools sentence is centralized as one constant so users/developers
  can change it without hunting through the code.
- The plugin never edits files other than the active note through normal Obsidian
  editor APIs and never reads or exposes the Gemini API key.
- Existing `now-time` and `omarchy-daily-tasks` plugins remain untouched.

## Metrics that are useful without storing screen content

Each check stores only operational metadata:

- Timestamp, outcome (`on_goal`, `off_goal`, `error`, `skipped`).
- Model name, request latency, compressed image byte count.
- Input/output token counts when Gemini returns usage metadata.
- Anonymous SHA-256 goal fingerprint, never the goal text.
- Alert shown, acknowledgement time, and the first later on-goal confirmation.

Derived metrics shown locally:

- `Focus score` = on-goal checks / valid classified checks.
- Watching time for the current session.
- Current on-goal streak.
- Alert count.
- Median Gemini latency.
- Requests, input/output tokens, and image bytes sent today.
- `Return to goal` time = alert creation to the first later on-goal check. This
  is reported separately from button acknowledgement so the UI does not pretend
  a click proves focus.

Privacy rules:

- No screenshots, window titles, visible OCR text, goal text, API keys, or Gemini
  complements are retained in metrics.
- The active complement exists only in the runtime state needed by the overlay
  and is cleared on dismissal or service stop.
- Metrics are local-only and pruned to 90 days by default.
- Documentation clearly states that the screenshot, current goal, and tools text
  are sent to Google's Gemini API while GoalWatch is active.

## Branding and asset plan

- Preserve `assets/concept.png`, `assets/logo.png`, `assets/favicon.png`, and
  `assets/banner.png` as source/reference assets.
- Reconstruct the eye from the reference as deterministic vector geometry for
  Quickshell and Obsidian, rather than shipping a large raster to the bar.
- Export only small favicon sizes needed by packaging/documentation from the
  existing high-resolution favicon.
- Image generation is not needed with the current asset set. If a required raster
  is later found to be missing, generate it from `concept.png`, visually verify it,
  and save the final asset inside the repository.

## Performance and size budgets

The MVP is accepted only if it meets these measured targets on the target machine:

- Installed GoalWatch runtime: less than 1 MiB, excluding Python, `grim`,
  `libsecret`, documentation, tests, and marketing/reference PNGs.
- New runtime dependencies: zero Python packages and no bundled interpreter.
- Daemon steady-state RSS while sleeping: at most 30 MiB.
- Sleeping CPU: at most 0.5% average over 10 minutes; no sub-second polling loop.
- Screenshot: longest edge at most 1920 px, JPEG quality tuned for legibility,
  with a hard request-size guard below Gemini's inline-image limit.
- Network while off or missing a valid goal/key/file: exactly zero Gemini requests.
- Toggle state reflected in the bar within 1 second.
- Valid alert state reflected on every monitor within 300 ms after response parsing.
- Shutdown completes within 2 seconds and leaves no capture or HTTP child process.

## Verification plan

### Automated

- Unit tests for latest-valid goal parsing, multiple blocks, malformed tails,
  missing tools, Unicode, whitespace, and CRLF.
- Scheduler tests with a fake monotonic clock, including interval reset,
  suspend/resume, alert pause, and no-overlap guarantees.
- Gemini client tests against a local fake HTTP server for `true`, `false`, invalid
  schema, timeout, HTTP errors, usage metadata, and payload-size rejection.
- Secret tests prove the key is absent from argv, config, runtime state, metrics,
  and logs.
- Metrics tests validate formulas, alert recovery linking, and 90-day pruning.
- CLI/config tests validate atomic writes, permissions, and concurrent commands.
- Obsidian tests/mocks cover daily resolution, current-file synchronization,
  command insertion, and `@goal` replacement.
- QML syntax/smoke checks and manifest validation.

### AI behavior benchmark

- A labeled, non-sensitive fixture set covers direct work, relevant research,
  setup, communication, ambiguous screens, unrelated social media, unrelated
  video, and unrelated work.
- Release target: at least 90% precision on alerts and no more than 5% false-alert
  rate on clearly on-goal fixtures. Results are recorded with the tested model.
- This benchmark is repeated when the default `latest` model alias changes.

### Manual on Omarchy

- Install only into user-owned paths and add the widget through supported
  `omarchy plugin`/`omarchy bar` mechanisms.
- Verify gray/off and blue/watching states, eye toggle, gear panel, auto-save,
  hidden API key, and browser link.
- Trigger synthetic on-goal and off-goal responses without API spend.
- Verify the dark intervention on every connected monitor, exclusive input, exact copy,
  dismissal, and timer reset.
- Verify real capture/API behavior only as an explicit opt-in test with a locally
  stored key.
- Confirm the existing Obsidian and Omarchy task integrations are unchanged.
- Measure installed size, RSS, CPU, request size, toggle latency, and overlay latency.

## Delivery phases

1. **Scaffold and contracts** — package layout, config/state schemas, CLI surface,
   goal parser, tests, and English documentation.
2. **Daemon** — scheduler, in-memory capture, Gemini structured output, secure
   secret access, metrics, and systemd user unit.
3. **Omarchy integration** — vector eye, bar toggle, settings/status panel, state
   watcher, and all-monitor alert overlay.
4. **Obsidian integration** — daily/current-file commands, goal command, and
   `@goal` editor expansion.
5. **Branding/package** — optimized icons, install/update/uninstall scripts, and
   user-facing setup/privacy docs.
6. **Verification and tuning** — automated tests, synthetic AI benchmark, live
   Omarchy QA, performance measurements, and final acceptance report.

## Final release checklist

- Every item in both plugin Definitions of Done passes.
- The exact Gemini schema is enforced and every failure mode is silent to the user.
- API key and screenshots pass the privacy/security checks.
- Performance budgets are measured, not assumed.
- No existing plugin or file in `/usr/share/omarchy/` was modified.
- The service is disabled/off after first install until the user explicitly enables it.
- The final repository contains source, tests, packaging, English README,
  privacy disclosure, architecture notes, and measured verification results.
