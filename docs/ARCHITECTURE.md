# GoalWatch architecture

GoalWatch is split into three deliberately small components. The systemd user
service owns goal-source selection, scheduling, capture, Gemini requests, and
metrics. The Omarchy plugin is the manual goal editor, integration control,
status surface, and alert renderer. The optional Obsidian plugin only resolves
note paths and inserts goal blocks.

```text
Manual goal ── private stdin ─────────────┐
Optional Obsidian ── note path ───────────┴──▶ goalwatch CLI
                                              │
Omarchy bar ── toggle/settings ───────────────┤
                                              ▼
                                   systemd user service
                              Markdown ──▶ goal parser
                              grim ──────▶ JPEG in memory
                              keyring ───▶ Gemini API
                                              │
                              runtime JSON ◀──┴──▶ SQLite metrics
                                   │
                                   ▼
                         Quickshell panel/overlay
```

## Process and data boundaries

- `goalwatch.service` runs one Python process and has no third-party Python
  dependencies. A monotonic one-shot interval prevents polling and request
  overlap.
- `grim` is the only capture child process. It writes a scaled JPEG to stdout;
  GoalWatch reads those bytes directly and never creates a screenshot file.
- Gemini receives one stateless `generateContent` request per due check. The
  response uses a JSON schema with exactly `alert` and `complement`.
- Quickshell watches an atomic runtime-state file. It never receives the API key
  and does not call Gemini itself.
- Manual goal text is written to the CLI over stdin, never argv. It is stored
  only in the private mode-`0600` config and ephemeral runtime state.
- Obsidian invokes the CLI with an argument array, never a shell command. Note
  paths are resolved inside the vault before being accepted. The core rejects
  stale companion calls whenever Obsidian Sync is off.
- Enabling Obsidian Sync chooses the most recent valid registered vault,
  atomically installs the companion, preserves every unrelated community
  plugin entry, and only then changes the active source. Disabling changes the
  source first, then performs idempotent companion cleanup.

## State machine

```text
OFF ── enable ──▶ SETUP REQUIRED / NO GOAL / WATCHING
                                      │
                               interval elapsed
                                      ▼
                                  CHECKING
                                 ╱        ╲
                           on goal          off goal
                              │                │
                              ▼                ▼
                          WATCHING          ALERT
                              ▲                │
                              └──── dismiss ───┘
```

Every error fails open. Capture, keyring, network, HTTP, timeout, or schema
failures update status and metrics but cannot create the blocking intervention. Checks are
paused while an alert is visible so the overlay is never classified as desktop
activity.

## Installed paths

- Runtime: `~/.local/share/goalwatch/app`
- CLI: `~/.local/bin/goalwatch`
- systemd unit: `~/.config/systemd/user/goalwatch.service`
- Omarchy plugin: `~/.config/omarchy/plugins/com.goalwatch`
- Optional Obsidian plugin: `<vault>/.obsidian/plugins/goalwatch`
- Config: `${XDG_CONFIG_HOME:-~/.config}/goalwatch/config.json`
- Metrics: `${XDG_STATE_HOME:-~/.local/state}/goalwatch/metrics.sqlite3`
- Ephemeral state: `${XDG_RUNTIME_DIR}/goalwatch/state.json`

Nothing under `/usr/share/omarchy` is changed.
