# Changelog

Every published GoalWatch release is recorded here. Versions follow Semantic
Versioning.

## [1.0.0] - 2026-09-02

First stable release for Omarchy.

- Manual goals work without Obsidian; an empty goal makes no capture or Gemini
  request.
- A lightweight user service checks the visible Wayland desktop against the
  current goal and stays silent for relevant or ambiguous activity.
- Clear off-goal activity opens a keyboard-exclusive intervention on every
  connected display.
- The Omarchy bar provides watching state, auto-saved settings, Secret
  Service-backed API-key replacement, local metrics, and a searchable private
  request audit with screenshots and exact bounded model responses.
- Optional one-tap Obsidian Sync supports Daily Notes, current-file selection,
  goal insertion, and `@goal` expansion without modifying unrelated plugins or
  notes.
- Installation, updates, optional integration, and rollback are transactional
  across user-owned runtime, shell, configuration, and companion state.
- Mutable input, subprocess, Gemini, SQLite snapshot, audit, and retention
  boundaries are bounded and covered by adversarial regression tests.

[1.0.0]: https://github.com/invrnt/goalwatch/releases/tag/v1.0.0
