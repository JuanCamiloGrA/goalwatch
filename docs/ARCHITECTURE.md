# GoalWatch architecture

GoalWatch is split into three deliberately small components. The systemd user
service owns goal-source selection, scheduling, capture, Gemini requests,
request auditing, and metrics. The Omarchy plugin is the manual goal editor,
integration control, audit browser, status surface, and alert renderer. The
optional Obsidian plugin only resolves note paths and inserts goal blocks.

```text
Manual goal ── private stdin ─────────────┐
Optional Obsidian ── note path ───────────┴──▶ goalwatch CLI
                                              │
Omarchy bar ── toggle/settings ───────────────┤
                                              ▼
                                   systemd user service
                              Markdown ──▶ goal parser
                              grim ──────▶ JPEG ───▶ private audit archive
                              keyring ───▶ Gemini API ───▶ raw response audit
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
  GoalWatch reads those bytes directly and stores them in the private request
  audit before the network call.
  Every child process has a wall-clock deadline, byte-limited stdout/stderr,
  and an isolated process group that is killed as a unit on timeout or overflow.
- Gemini receives one stateless `generateContent` request per due check. The
  response uses a JSON schema with exactly `alert` and `complement`. Response
  bodies are capped at 512 KiB, HTTP redirects are never followed, and one
  monotonic deadline budget, enforced by `ITIMER_REAL`, covers client setup and
  the complete urllib exchange.
  Provider-controlled HTTP and usage metadata are validated before a decision
  can leave the client.
- The audit store owns a descriptor-anchored SQLite index plus one mode-`0600`
  JPEG per request. A shared file lock spans each request and viewer query; the
  explicit clear operation requires an exclusive lock and a stopped service.
  Request persistence is a precondition for network I/O, while response
  persistence is a precondition for an alert. Retention is bounded by age, row,
  content, database-page, and WAL quotas.
- Quickshell watches an atomic runtime-state file. It never receives the API key
  and does not call Gemini itself. Dynamic runtime text is length-capped and
  rendered explicitly as plain text.
- Manual goal text is written to the CLI over stdin, never argv. It is stored
  only in the private mode-`0600` config and ephemeral runtime state.
- Obsidian invokes the CLI with an argument array, never a shell command. Note
  paths are resolved inside the vault before being accepted. The core rejects
  stale companion calls whenever Obsidian Sync is off.
- Enabling Obsidian Sync chooses the most recent valid registered vault,
  atomically installs the companion, preserves every unrelated community
  plugin entry, and only then changes the active source. Disabling changes the
  source first, then performs idempotent companion cleanup.
- Config, runtime state, metrics, and audit paths are anchored to no-follow
  directory descriptors. SQLite main files are opened with `O_NOFOLLOW`,
  checked by inode, and connected through `/proc/self/fd`; they are never
  checked and then reopened by their mutable pathname. Atomic replacements
  cannot traverse a substituted file symlink, and Markdown is read from one
  no-follow descriptor after size/type checks.

## Installation transaction

The installer stages and validates runtime, CLI, unit, documentation, and QML
before stopping the service. Each existing target is moved to a same-filesystem
backup and no backup is discarded until daemon reload, runtime initialization,
shell rescan, plugin validation, bar enablement, optional Obsidian setup, and
restart of a previously active service all succeed. Any late failure removes
the staged targets in reverse order, restores every backup, reloads systemd and
the shell, normalizes runtime state, and restarts the old service when needed.

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
- Request audit: `${XDG_STATE_HOME:-~/.local/state}/goalwatch/audit/`
- Ephemeral state: `${XDG_RUNTIME_DIR}/goalwatch/state.json`

Nothing under `/usr/share/omarchy` is changed.

The deadline uses Python's documented
[`signal.setitimer`](https://docs.python.org/3/library/signal.html#signal.setitimer)
real-time timer. Descriptor paths use the documented
[`sqlite3.connect(..., uri=True)`](https://docs.python.org/3/library/sqlite3.html#sqlite3.connect)
URI mode after the Linux file descriptor has been opened and validated.
