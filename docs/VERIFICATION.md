# GoalWatch 0.1.0 verification report

Verified on 2026-09-01 with Omarchy 4.0.2, Quickshell 0.3.1, and Python 3.14.

## Acceptance results

| Check | Result | Budget |
|---|---:|---:|
| Executable install size, including both plugins | 98,751 bytes | < 1 MiB |
| Sleeping daemon CPU over 600 seconds | 0.0017% | <= 0.5% |
| Maximum daemon RSS during that sample | 27,424 KiB | <= 30 MiB |
| Real desktop capture | 145,758 bytes, 1920×1080, 69 ms | <= 1920 px long edge, < 8 MiB |
| Service start to readable active state | 217 ms | <= 1 second |
| Service stop to readable off state | 238 ms | <= 2 seconds |
| Runtime alert state to Wayland overlay surface | 98 ms | <= 300 ms |
| Overlay coverage on connected test displays | 1 surface / 1 monitor | One per monitor |

The 10-minute CPU/RSS sample included the normal missing-key recheck. No capture
or Gemini request was made because the key was absent. The service remained one
Python process while sleeping.

## Automated checks

- 31 Python unit/integration tests pass.
- Node-based Obsidian tests pass for daily-note resolution, canonical goal
  insertion, and `@goal` replacement.
- Gemini tests use a local HTTP server and cover alert true/false, exact schema,
  extra fields, semantic mismatch, HTTP 429, network failure, usage metadata,
  and image-size rejection.
- Goal parsing covers latest-valid selection, malformed tails, default tools,
  CRLF, Unicode, symlinks, invalid UTF-8, path escape, and input bounds.
- Scheduler tests use a fake monotonic clock for interval reset, a large resume
  jump without a backlog, and alert-dismiss reset.
- Metrics tests cover focus score, latency, recovery linking, current streak,
  retention pruning, and cascade deletion.
- Shell syntax, JavaScript syntax, JSON manifests, Omarchy plugin validation,
  and systemd unit verification pass.

Run them with:

```bash
./scripts/test.sh
```

## Live integration checks

- A complete uninstall/reinstall cycle succeeded and preserved config, keyring,
  and metrics data by default.
- The final install is disabled and off until the user clicks the eye.
- The GoalWatch widget is present once in the right bar section.
- The Obsidian plugin is copied and enabled without touching existing plugins.
- The fresh Quickshell process loaded GoalWatch without GoalWatch QML warnings.
- Gray idle eye, blue active state, settings panel, charcoal intervention,
  canonical eye, exact English alert copy, and dismissal path were visually inspected.
- A synthetic alert created one `goalwatch-alert` overlay-layer surface per
  connected monitor and cleared through the same CLI action used by the button.
- The API-key field is password-masked, starts empty, sends its replacement over
  child-process stdin, and never receives the current key from the daemon.

## Credentialed Gemini acceptance

The live model-quality benchmark was not executed as part of release QA so the
verification process would not spend user API quota or capture the user's
desktop. No test key was invented or exposed. The repository includes eight
non-sensitive, labelled synthetic screens and `./scripts/ai_benchmark.py`; when
run explicitly, it reports precision and false-alert rate using the configured
model.

The client follows Google's current `generateContent` authentication and inline
image contract and uses `responseJsonSchema`, then independently validates the
two-field result. See the official [Gemini API reference](https://ai.google.dev/api)
and [structured output documentation](https://ai.google.dev/gemini-api/docs/structured-output).
