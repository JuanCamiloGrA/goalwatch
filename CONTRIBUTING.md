# Contributing to GoalWatch

These rules apply to human and AI-assisted contributions. This is ordinary
project documentation: it is intentionally not named as an automatic coding
agent instruction file.

## Preserve the product contract

- Keep all user-facing UI, commands, logs, and documentation in English.
- Keep GoalWatch Omarchy-first and user-local. Never write to
  `/usr/share/omarchy`.
- Keep the resident Python runtime standard-library-only. A new runtime
  dependency requires a measured reason and updated size and privacy docs.
- Preserve fail-open behavior: only an exact, locally validated `alert: true`
  Gemini result may show the intervention.
- Keep the request audit complete within its documented retention limits:
  screenshots, goals, sanitized request documents, and bounded raw Gemini
  responses belong only in the private audit archive. Never persist the API key.
- Keep API-key replacement on stdin and storage in Secret Service.
- A first install must leave the service disabled and off.
- Keep the alert on every display with exclusive keyboard focus. Escape and
  outside clicks must not dismiss it.
- Obsidian changes must use its normal editor APIs and must not modify unrelated
  notes or plugins.
- Reuse the canonical eye in `assets/goalwatch-eye.svg` and
  `integrations/omarchy/com.goalwatch/EyeIcon.qml`.
- Keep the root and packaged Omarchy manifests aligned except for their
  intentionally different entry-point paths.

## Keep changes reviewable

- Read `README.md` and the nearest component files before changing behavior.
- Preserve unrelated work and avoid broad formatting passes.
- Update tests and relevant documentation when behavior, data flow,
  installation, UI copy, privacy, or defaults change.
- Never commit secrets, local configuration, databases, logs, caches,
  temporary captures, or generated QA artifacts.
- Use one coherent commit purpose and a message that states its outcome.

## Required verification

Run:

```bash
./scripts/test.sh
omarchy plugin validate .
omarchy plugin validate integrations/omarchy/com.goalwatch
systemd-analyze --user verify packaging/systemd/goalwatch.service
```

For Omarchy UI changes, install locally, reload the shell if needed, inspect the
panel and every connected alert surface, dismiss the test alert, and leave no
synthetic record, overlay, or running service behind.

Privacy and Gemini changes require regression tests for both sides of the data
boundary: intended audit content must be present, while secrets and audit
content must remain absent from config, argv, runtime metrics, and logs. Never
use a real API key in automated tests.
