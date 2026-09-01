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

## Data never retained by GoalWatch

- Screenshots are held in memory for one request and are never written to disk.
- Visible OCR text and window titles are not collected separately.
- Goal text and Gemini explanations are not stored in the metrics database.
- The API key is never placed in configuration, arguments, runtime JSON,
  metrics, or logs.
- Manual goal text is never placed in process arguments, metrics, or logs.

Manual goal text is stored in the private settings file so it survives a
restart. The active goal and an alert explanation also temporarily exist in the private
runtime-state file because Quickshell needs them. The explanation is removed
when the alert is dismissed or the service stops. Runtime state is stored below
the per-user runtime directory with mode `0600`.

## Local data

The Gemini API key is stored through the desktop Secret Service. Non-secret
settings are saved in a mode-`0600` JSON file. The local SQLite database stores
only timestamps, outcomes, model name, latency, token/byte counts, error codes,
and a SHA-256 fingerprint of the goal. Metrics are pruned after 90 days.

## Safety behavior

- GoalWatch skips capture when the Omarchy session is locked or displays are off.
- Captures are scaled to a maximum 1920-pixel long edge and rejected above 8 MiB.
- Screenshot text is labelled as untrusted content in the Gemini instruction to
  reduce prompt-injection risk.
- The model must return the exact structured schema. The local client validates
  it again before allowing an alert.
- All failures are silent: an error can never be converted into an invasive
  intervention.

Stop GoalWatch at any time from the eye button or with `goalwatch stop`. While it
is off, it performs no capture and makes no Gemini request.

Obsidian is not required and is never modified by a default installation.
Turning on Obsidian Sync explicitly installs the companion into one local vault
and adds only `goalwatch` to that vault's community plugin registry. Turning it
off removes only that entry and directory; Markdown notes are never changed by
the integration manager.
