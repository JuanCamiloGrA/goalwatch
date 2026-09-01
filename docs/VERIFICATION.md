# GoalWatch 0.2.0 verification report

Verified on 2026-09-01 with Omarchy 4.0.2, Quickshell 0.3.1, and Python 3.14.

## Acceptance results

| Check | Result | Budget |
|---|---:|---:|
| Executable install size, including both plugins | 135,321 bytes | < 1 MiB |
| Sleeping daemon CPU over 60 seconds | 0.15% | <= 0.5% |
| Maximum daemon RSS during that sample | 28,184 KiB | <= 30 MiB |
| Real desktop capture | 145,758 bytes, 1920×1080, 69 ms | <= 1920 px long edge, < 8 MiB |
| Service start to readable active state | 217 ms | <= 1 second |
| Service stop to readable off state | 238 ms | <= 2 seconds |
| Runtime alert state to Wayland overlay surface | 98 ms | <= 300 ms |
| Overlay coverage on connected test displays | 1 surface / 1 monitor | One per monitor |

The CPU/RSS sample used a private temporary configuration with an empty manual
goal. No capture or Gemini request was made. The service remained one Python
process while sleeping.

## Automated checks

- 48 Python unit/integration tests pass.
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
- The repository-root marketplace manifest and packaged runtime manifest both
  validate, share public metadata, and resolve every declared entry point.

Run them with:

```bash
./scripts/test.sh
```

## Live integration checks

- A complete uninstall/reinstall cycle succeeded and preserved config, keyring,
  and metrics data by default.
- The final install is disabled and off until the user clicks the eye.
- A fresh configuration starts in manual mode and an empty goal produces
  `NO GOAL` without a capture, request, or alert.
- The GoalWatch widget is present once in the right bar section.
- Manual goal and tools fields render correctly, auto-save through stdin, and
  keep their live session/countdown values reactive through `SystemClock`.
- Obsidian Sync disabled and re-enabled in one command each. The source changed
  immediately, the companion directory and registry entry were removed and
  restored, and all nine unrelated community plugins remained unchanged.
- Re-running the default installer updated an already-authorized Obsidian
  companion to 0.2.0 without requiring `--with-obsidian` again.
- The fresh Quickshell process loaded GoalWatch without GoalWatch QML warnings.
- Gray idle eye, blue active state, settings panel, charcoal intervention,
  canonical eye, exact English alert copy, and dismissal path were visually inspected.
- A synthetic alert created one `goalwatch-alert` overlay-layer surface per
  connected monitor and cleared through the same CLI action used by the button.
- The API-key field is password-masked, starts empty, sends its replacement over
  child-process stdin, and never receives the current key from the daemon.
- The public GitHub repository was installed through `omarchy plugin add`, then
  completed with the checkout-local setup script. The Git checkout remained
  clean and updateable, the service remained disabled/off, and the nested QML
  entry points produced and cleared the expected overlay.

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
