# GoalWatch privacy and security

GoalWatch necessarily observes the desktop while it is enabled. Its data flow is
kept narrow and explicit.

## Data sent to Gemini

At each configured interval, and only when the service is enabled with a valid
goal and API key, GoalWatch sends:

- the current goal description;
- the available-tools sentence from the goal block;
- one compressed JPEG capture of the full visible desktop.

The request is sent directly to Google's Gemini API. Google's terms and data
handling apply to that request. GoalWatch does not proxy it through another
server.

## Local request audit

GoalWatch intentionally retains every Gemini request attempt so the user can
inspect the model boundary. Before opening the network connection, it writes:

- the exact JPEG screenshot;
- the goal and available-tools text;
- model, endpoint, timestamp, and a readable representation of the request;
- an explicit placeholder where the inline base64 screenshot would appear.

The API key header is omitted. After the request completes, the same record
receives the HTTP status, bounded response headers, exact raw response body,
SHA-256 digest, byte count, latency, token counts, parsed outcome, and error
code. A response larger than the 512 KiB safety cap stores its exact 512 KiB
prefix and is visibly marked as truncated. A network failure has no response
body; a `PENDING` record means the process ended before it could complete the
record.

The archive is `${XDG_STATE_HOME:-~/.local/state}/goalwatch/audit/`. Its
directory is mode `0700`; its bounded SQLite snapshot, JPEGs, and exact raw
response files are mode `0600`. Screenshots and new responses are each stored
once next to the database; responses created by older releases remain readable
in their original inline records without a destructive migration. The oldest
completed records and their attachments are removed when any limit is reached:
7 days, 2,000 records, or 512 MiB of indexed screenshot/response content.
Response content is capped at 224 MiB, the database snapshot at 256 MiB, each
response at 512 KiB, each image at 8 MiB, and the archive directory at 10,000
entries. An in-flight request is never evicted to admit another request.
Use **Request Audit → Clear All** while
GoalWatch is stopped, or `uninstall.sh --purge`, to remove the retained data.
Ordinary uninstall preserves it.

This is operating-system permission protection, not application-level
encryption. The local account and root can read the archive. Anyone backing up
the state directory should treat it as sensitive desktop history.

## Data excluded from other stores

- Visible OCR text and window titles are not collected separately.
- Goal text, screenshots, raw requests, and Gemini explanations are not stored
  in the metrics database or logs.
- The API key is never placed in the audit archive, configuration, arguments,
  runtime JSON, metrics, or logs.
- Manual goal and audit search text are never placed in process arguments,
  metrics, or logs.

Manual goal text is stored in the private settings file so it survives a
restart. The active goal and an alert explanation also temporarily exist in the private
runtime-state file because Quickshell needs them. The explanation is removed
when the alert is dismissed or the service stops. Runtime state is stored below
the per-user runtime directory with mode `0600`.

## Local data

The Gemini API key is stored through the desktop Secret Service. Non-secret
settings are saved in a mode-`0600` JSON file. The separate metrics SQLite
database stores only timestamps, outcomes, model name, latency, token/byte
counts, error codes, and a SHA-256 fingerprint of the goal. It is limited to 90
days, 30,000 checks, 5,000 sessions, and a 16 MiB database snapshot. Private
application directories are opened with `O_NOFOLLOW`; config and runtime-state
operations are descriptor-relative. Every mutable file read opens with
`O_NONBLOCK|O_NOFOLLOW` and validates owner, regular-file type, size, and a
single link before consuming bounded bytes. This includes Markdown and all
Obsidian registries, whose object counts and field lengths are also capped.

Persistent SQLite path handling is deliberately absent. Audit and metrics load
a bounded, descriptor-validated SQLite byte snapshot into `:memory:`, serialize
under a per-store lock, and atomically replace one mode-`0600` file. SQLite
therefore never receives a persistent pathname and never creates or reopens
WAL, SHM, or rollback-journal sidecars. A path replaced with a symlink or
hardlink can be rejected or atomically displaced, but its target inode is never
opened for modification.

## Safety behavior

- GoalWatch skips capture when the Omarchy session is locked or displays are off.
- Captures are scaled to a maximum 1920-pixel long edge and rejected above 8 MiB.
- `grim`, `hyprctl`, `secret-tool`, systemd, and Obsidian CLI subprocesses have
  hard stdout/stderr limits, total deadlines, and process-group cleanup.
- Gemini response bodies are capped at 512 KiB. Redirects are rejected, so the
  API-key header is never replayed to a redirect target.
- Each request attempt has a deadline computed from the monotonic clock and
  enforced with a real-time process timer. One check makes at most three
  attempts inside a 60-second budget, with bounded backoff for transient
  failures only. Client setup, DNS, connect, TLS, response headers, and bounded
  body reads remain covered, and timeout state is restored after every attempt.
- Provider-controlled HTTP status, response shape, and usage-token metadata are
  type- and range-validated inside the fail-open error boundary.
- If the request and screenshot cannot be durably added to the audit archive,
  the Gemini request is not sent. If the response cannot be attached, no alert
  is allowed.
- Screenshot text is labelled as untrusted content in the Gemini instruction to
  reduce prompt-injection risk.
- The model must return the exact structured schema. The local client validates
  it again before allowing an alert.
- All failures are silent: an error can never be converted into an invasive
  intervention.
- Goal and explanation strings are capped and rendered as plain text in
  Quickshell.

Stop GoalWatch at any time from the eye button or with `goalwatch stop`. While it
is off, it performs no capture and makes no Gemini request. Existing audit
records remain readable until they reach a documented quota or are explicitly
cleared.

Obsidian is not required and is never modified by a default installation.
Turning on Obsidian Sync explicitly installs the companion into one local vault
and adds only `goalwatch` to that vault's community plugin registry. Turning it
off removes only that entry and directory; Markdown notes are never changed by
the integration manager.
