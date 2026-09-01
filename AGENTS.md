# GoalWatch contribution rules

These rules apply to human and AI-assisted contributions throughout the repository.

## Preserve the product contract

- Keep all user-facing UI, commands, logs, and documentation in English.
- Keep GoalWatch Omarchy-first and user-local. Never write to `/usr/share/omarchy`.
- Keep the resident Python runtime standard-library-only. A new runtime dependency requires a measured reason and an update to the size and privacy documentation.
- Preserve fail-open behavior: only an exact, locally validated `alert: true` Gemini result may show the intervention.
- Keep screenshots in memory. Never persist screenshots, OCR, window titles, goal text, API keys, or Gemini explanations in metrics or logs.
- Keep the API key in Secret Service and pass replacements over stdin, never argv.
- A first install must leave the service disabled and off.
- The alert must cover every display, take exclusive keyboard focus, ignore Escape and outside clicks, and dismiss only through its acknowledgement action or the recovery CLI.
- Obsidian changes must use its normal editor APIs and must not modify unrelated notes or plugins.
- Use the canonical eye geometry in `assets/goalwatch-eye.svg` and `integrations/omarchy/com.goalwatch/EyeIcon.qml`; do not introduce a competing logo.

## Make focused changes

- Read `README.md`, `PLAN.md`, and the nearest component files before editing behavior.
- Preserve unrelated work in the tree. Do not run destructive Git commands or broad formatting passes.
- Update tests and the relevant documentation when behavior, data flow, installation, UI copy, or defaults change.
- Do not commit secrets, local configuration, logs, databases, caches, temporary captures, or generated QA artifacts.
- Keep commits reviewable: one coherent purpose, no drive-by refactors, and a message that states the outcome.

## Verify before handing off

Run:

```bash
./scripts/test.sh
omarchy plugin validate integrations/omarchy/com.goalwatch
systemd-analyze --user verify packaging/systemd/goalwatch.service
```

For Omarchy UI changes, also install the local build, restart the shell if hot
reload is stale, trigger `goalwatch debug alert`, inspect every connected
display, dismiss it, and confirm that no `goalwatch-alert` layer remains. Never
leave a synthetic alert or the service running after QA.

For privacy or Gemini changes, add a regression test that proves the relevant
data cannot enter config, argv, runtime metrics, or logs. Do not use a real API
key in automated tests.
