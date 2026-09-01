from __future__ import annotations

import time
from collections.abc import Callable


class IntervalSchedule:
    """A one-shot monotonic interval that never accumulates missed checks."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.deadline = clock()

    def reset(self, interval_minutes: int) -> None:
        self.deadline = self._clock() + max(1, int(interval_minutes)) * 60

    def remaining(self) -> float:
        return max(0.0, self.deadline - self._clock())

    def due(self) -> bool:
        return self.remaining() == 0.0
