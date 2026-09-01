from __future__ import annotations

import hashlib
import signal
import threading
import time
from datetime import datetime, timedelta, timezone

from .audit import AuditError, AuditStore
from .capture import CaptureError, capture_desktop
from .config import load_config
from .gemini import GeminiClient, GeminiError
from .goals import Goal, GoalReadError, resolve_goal
from .metrics import Metrics
from .obsidian import integration_status
from .schedule import IntervalSchedule
from .secrets import SecretError, get_api_key
from .state import BASE_STATE, write_off_state, write_state


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def utc_after(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


class GoalWatchDaemon:
    def __init__(self) -> None:
        self.wake = threading.Event()
        self.reload_requested = False
        self.dismiss_requested = False
        self.stopping = False
        self.alert_active = False
        self.alert_id: int | None = None
        self.state = dict(BASE_STATE)
        self.metrics = Metrics()
        self.session_id = self.metrics.start_session()

    def install_signals(self) -> None:
        signal.signal(signal.SIGTERM, self._terminate)
        signal.signal(signal.SIGINT, self._terminate)
        signal.signal(signal.SIGHUP, self._reload)
        signal.signal(signal.SIGUSR1, self._dismiss)

    def _terminate(self, _number, _frame) -> None:
        self.stopping = True
        self.wake.set()
        raise SystemExit(0)

    def _reload(self, _number, _frame) -> None:
        self.reload_requested = True
        self.wake.set()

    def _dismiss(self, _number, _frame) -> None:
        self.dismiss_requested = True
        self.wake.set()

    def _configuration_state(self, config: dict, goal: Goal | None, key_set: bool) -> dict:
        obsidian = integration_status(config)
        return {
            "goal_source": config["goal_source"],
            "manual_goal": config["manual_goal"],
            "manual_tools": config["manual_tools"],
            "obsidian_enabled": config["obsidian_enabled"],
            "obsidian_connected": obsidian["connected"],
            "obsidian_vault": obsidian["vault"],
            "obsidian_message": obsidian["message"],
            "markdown_file": config["markdown_file"],
            "markdown_source": config["markdown_source"],
            "interval_minutes": config["interval_minutes"],
            "model": config["model"],
            "api_key_set": key_set,
            "goal": goal.description if goal else "",
            "tools": goal.tools if goal else "",
        }

    def _write(self, changes: dict) -> None:
        self.state.update(changes)
        self.state["metrics"] = self.metrics.summary(self.session_id)
        self.state = write_state(self.state)

    def _load_inputs(self) -> tuple[dict, Goal | None, str, str]:
        config = load_config()
        goal = None
        error = ""
        try:
            goal = resolve_goal(config)
        except GoalReadError as issue:
            error = str(issue)
        try:
            key = get_api_key()
        except SecretError as issue:
            key = ""
            error = str(issue)
        self.state.update(self._configuration_state(config, goal, bool(key)))
        return config, goal, key, error

    def _setup_state(self, config: dict, goal: Goal | None, key: str, error: str, remaining: float) -> None:
        if error:
            label = "SETUP REQUIRED"
        elif not goal:
            if config["goal_source"] == "obsidian" and not config["markdown_file"]:
                error = "Obsidian has not selected a note yet."
            elif config["goal_source"] == "obsidian":
                error = "No valid Current Goal block was found."
            else:
                error = "Enter a Current Goal."
            label = "NO GOAL"
        elif not key:
            label, error = "SETUP REQUIRED", "Add a Gemini API key."
        else:
            label = "WATCHING"
        self._write(
            {
                "state": label,
                "active": True,
                "error": error,
                "next_check_at": utc_after(remaining),
                "alert": {"active": False, "complement": "", "shown_at": ""},
            }
        )

    def _perform_check(self, config: dict, goal: Goal, key: str) -> None:
        self._write({"state": "CHECKING", "error": "", "next_check_at": ""})
        image = b""
        audit: AuditStore | None = None
        goal_hash = hashlib.sha256(goal.description.encode("utf-8")).hexdigest()
        try:
            image = capture_desktop()
            audit = AuditStore()
            decision = GeminiClient(key, config["model"]).classify(goal, image, audit=audit)
        except CaptureError as issue:
            self.metrics.record_check(
                self.session_id,
                "skipped",
                config["model"],
                image_bytes=len(image),
                goal_hash=goal_hash,
                error_code="capture",
            )
            self._write({"state": "WATCHING", "error": str(issue), "last_outcome": "skipped"})
            return
        except AuditError:
            self.metrics.record_check(
                self.session_id,
                "error",
                config["model"],
                image_bytes=len(image),
                goal_hash=goal_hash,
                error_code="audit_store",
            )
            self._write(
                {
                    "state": "WATCHING",
                    "error": "The audit archive is unavailable, so no request was sent.",
                    "last_outcome": "error",
                }
            )
            return
        except GeminiError as issue:
            self.metrics.record_check(
                self.session_id,
                "error",
                config["model"],
                image_bytes=len(image),
                goal_hash=goal_hash,
                error_code=issue.code,
            )
            self._write({"state": "WATCHING", "error": str(issue), "last_outcome": "error"})
            return
        finally:
            if audit is not None:
                audit.close()

        now = utc_now()
        outcome = "off_goal" if decision.alert else "on_goal"
        check_id = self.metrics.record_check(
            self.session_id,
            outcome,
            config["model"],
            latency_ms=decision.latency_ms,
            image_bytes=len(image),
            prompt_tokens=decision.prompt_tokens,
            output_tokens=decision.output_tokens,
            goal_hash=goal_hash,
        )
        if decision.alert:
            self.alert_active = True
            self.alert_id = self.metrics.create_alert(check_id)
            self._write(
                {
                    "state": "ALERT",
                    "last_check_at": now,
                    "last_outcome": outcome,
                    "next_check_at": "",
                    "error": "",
                    "alert": {
                        "active": True,
                        "complement": decision.complement,
                        "shown_at": now,
                    },
                }
            )
        else:
            self._write(
                {
                    "state": "WATCHING",
                    "last_check_at": now,
                    "last_outcome": outcome,
                    "error": "",
                    "alert": {"active": False, "complement": "", "shown_at": ""},
                }
            )

    def _acknowledge(self) -> None:
        if self.alert_id is not None:
            self.metrics.acknowledge_alert(self.alert_id)
        self.alert_active = False
        self.alert_id = None
        self.dismiss_requested = False
        self._write(
            {
                "state": "WATCHING",
                "error": "",
                "alert": {"active": False, "complement": "", "shown_at": ""},
            }
        )

    def run(self) -> int:
        self.install_signals()
        try:
            self.metrics.prune(90)
            config, goal, key, error = self._load_inputs()
            schedule = IntervalSchedule()
            schedule.reset(config["interval_minutes"])
            self._setup_state(config, goal, key, error, schedule.remaining())
            while not self.stopping:
                if self.alert_active:
                    self.wake.wait()
                    self.wake.clear()
                    if self.dismiss_requested:
                        self._acknowledge()
                        config, goal, key, error = self._load_inputs()
                        schedule.reset(config["interval_minutes"])
                        self._setup_state(config, goal, key, error, schedule.remaining())
                    elif self.reload_requested:
                        self.reload_requested = False
                        config, goal, key, error = self._load_inputs()
                        self.state.update(self._configuration_state(config, goal, bool(key)))
                        self._write({})
                    continue

                woke = self.wake.wait(schedule.remaining())
                self.wake.clear()
                if self.stopping:
                    break
                if woke or self.reload_requested:
                    self.reload_requested = False
                    config, goal, key, error = self._load_inputs()
                    schedule.reset(config["interval_minutes"])
                    self._setup_state(config, goal, key, error, schedule.remaining())
                    continue

                config, goal, key, error = self._load_inputs()
                if error or not goal or not key:
                    schedule.reset(config["interval_minutes"])
                    self._setup_state(config, goal, key, error, schedule.remaining())
                    continue
                self._perform_check(config, goal, key)
                if not self.alert_active:
                    schedule.reset(config["interval_minutes"])
                    self.state["next_check_at"] = utc_after(schedule.remaining())
                    self._write({})
            return 0
        finally:
            self.metrics.stop_session(self.session_id)
            self.metrics.close()
            write_off_state()


def run_daemon() -> int:
    return GoalWatchDaemon().run()
