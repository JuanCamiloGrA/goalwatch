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
- Keep installation one outer transaction. A failure after widget or optional
  companion changes must restore exact prior core, shell, runtime, config,
  registry, companion, and service state.
- Persistent reads must be nonblocking, no-follow, descriptor-bound, bounded,
  and restricted to owned single-link regular files. SQLite must remain
  in-memory with one locked atomic snapshot; do not reintroduce pathname-opened
  database sidecars.
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

## Release process

Only maintainers publish releases. For a release version `X.Y.Z`:

1. Update `manifest.json`, `integrations/omarchy/com.goalwatch/manifest.json`,
   `integrations/obsidian/goalwatch/manifest.json`, and
   `src/goalwatch/__init__.py` to the same SemVer value.
2. Add the dated release to `CHANGELOG.md` and update measured documentation
   when behavior, size, privacy, or dependencies changed.
3. Run the required verification commands and wait for repository CI to pass.
4. Commit and push the release tree, then create the immutable release point:

   ```bash
   git tag -a "vX.Y.Z" -m "GoalWatch X.Y.Z"
   git push origin main "vX.Y.Z"
   gh release create "vX.Y.Z" --verify-tag --title "GoalWatch X.Y.Z" --generate-notes
   ```

5. Submit that exact 40-character commit through the Omarchy marketplace's
   **Verify and publish a newer upstream commit** workflow. Never move a
   published version tag.
