import unittest

from goalwatch.schedule import IntervalSchedule


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


class ScheduleTests(unittest.TestCase):
    def test_interval_reset_restarts_the_full_countdown(self):
        clock = FakeClock()
        schedule = IntervalSchedule(clock)
        schedule.reset(5)
        clock.value += 120
        schedule.reset(2)
        self.assertEqual(schedule.remaining(), 120)

    def test_large_clock_jump_creates_one_due_event_not_a_backlog(self):
        clock = FakeClock()
        schedule = IntervalSchedule(clock)
        schedule.reset(5)
        clock.value += 3600
        self.assertTrue(schedule.due())
        schedule.reset(5)
        self.assertEqual(schedule.remaining(), 300)

    def test_paused_alert_can_reset_after_dismissal(self):
        clock = FakeClock()
        schedule = IntervalSchedule(clock)
        schedule.reset(1)
        clock.value += 600
        schedule.reset(1)
        self.assertFalse(schedule.due())
        self.assertEqual(schedule.remaining(), 60)
