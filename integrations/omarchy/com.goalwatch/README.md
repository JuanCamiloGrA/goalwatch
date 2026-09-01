# GoalWatch for Omarchy

This plugin is installed by GoalWatch's root `install.sh`. The eye toggles the
background service; the gear opens status and settings. The service entry point
owns the all-monitor alert overlay.

Do not copy this directory alone: the QML calls the `goalwatch` CLI and expects
the systemd user unit installed by the project installer.
