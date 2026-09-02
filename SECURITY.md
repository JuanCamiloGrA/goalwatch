# Security policy

## Supported versions

Security fixes are released for the latest stable GoalWatch version. Users
should update the marketplace checkout and rerun its bundled installer before
reporting a problem already fixed upstream.

## Report a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/JuanCamiloGrA/goalwatch/security/advisories/new).
Do not open a public issue for a suspected vulnerability.

Include the affected GoalWatch version and commit, the relevant Omarchy and
Quickshell versions, reproducible steps, expected impact, and whether the issue
requires a malicious local process or external provider response. Redact API
keys, screenshots, goals, audit content, home-directory paths, and other private
user data.

Reports involving screen capture, Secret Service, Gemini request boundaries,
the local audit, installer rollback, Obsidian registries, or filesystem races
are especially useful when they include a minimal non-sensitive reproducer.
The maintainer will acknowledge a complete report, investigate it privately,
and coordinate disclosure after a fix is available.
