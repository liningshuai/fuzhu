import unittest
import threading
from unittest.mock import patch

from src.bot.engine import BotEngine
from src.session.recovery import GameSessionGuard
from src.session.startup import GameStartupTimeout


class FakeDevice:
    serial = "emulator-5554"

    def stop_game(self):
        pass

    def start_game(self):
        pass

    def is_online(self):
        return True

    def is_game_foreground(self):
        return True


class FakeMatcher:
    pass


class BlockingThread:
    def __init__(self):
        self.start_called = threading.Event()
        self.release = threading.Event()
        self.started = False

    def start(self):
        self.start_called.set()
        self.release.wait(2)
        self.started = True

    def is_alive(self):
        return False


class AliveThread:
    def is_alive(self):
        return True

    def join(self, timeout=None):
        pass


class StartupIntegrationTests(unittest.TestCase):
    def test_session_guard_delegates_restart_ready_check_to_startup_flow(self):
        device = FakeDevice()
        matcher = FakeMatcher()
        guard = GameSessionGuard(device, matcher)

        with patch("src.session.recovery.GameStartupFlow") as flow_cls:
            guard._restart_game_and_wait_for_main_city()

        flow_cls.assert_called_once()
        args, kwargs = flow_cls.call_args
        self.assertEqual(args, (device, matcher))
        self.assertEqual(kwargs["timeout_seconds"], guard.startup_timeout)
        self.assertEqual(kwargs["poll_interval"], guard.poll_interval)
        flow_cls.return_value.wait_until_main_city.assert_called_once_with()

    def test_bot_start_waits_for_main_city_before_starting_thread(self):
        engine = BotEngine()
        engine.device = FakeDevice()
        engine.matcher = FakeMatcher()

        with patch.object(engine, "refresh_device"), patch(
            "src.bot.engine.GameStartupFlow"
        ) as flow_cls, patch("src.bot.engine.threading.Thread") as thread_cls:
            result = engine.start()

        self.assertEqual(result, "挂机已启动")
        flow_cls.assert_called_once_with(engine.device, engine.matcher)
        flow_cls.return_value.wait_until_main_city.assert_called_once_with()
        thread_cls.return_value.start.assert_called_once_with()

    def test_bot_start_does_not_start_thread_when_startup_times_out(self):
        engine = BotEngine()
        engine.device = FakeDevice()
        engine.matcher = FakeMatcher()

        with patch.object(engine, "refresh_device"), patch(
            "src.bot.engine.GameStartupFlow"
        ) as flow_cls, patch("src.bot.engine.threading.Thread") as thread_cls:
            flow_cls.return_value.wait_until_main_city.side_effect = GameStartupTimeout(
                "not ready"
            )
            result = engine.start()

        self.assertIn("启动游戏失败", result)
        thread_cls.assert_not_called()
        self.assertFalse(engine.state.running)

    def test_status_and_stop_are_not_blocked_while_startup_waits(self):
        engine = BotEngine()
        engine.device = FakeDevice()
        engine.matcher = FakeMatcher()
        startup_entered = threading.Event()
        startup_release = threading.Event()
        real_thread = threading.Thread

        def wait_until_main_city():
            startup_entered.set()
            startup_release.wait(2)

        with patch.object(engine, "refresh_device"), patch(
            "src.bot.engine.GameStartupFlow"
        ) as flow_cls, patch("src.bot.engine.threading.Thread"):
            flow_cls.return_value.wait_until_main_city.side_effect = wait_until_main_city
            start_thread = real_thread(target=engine.start)
            start_thread.start()
            self.assertTrue(startup_entered.wait(1))

            status_done = threading.Event()
            status_thread = real_thread(
                target=lambda: (engine.status(), status_done.set())
            )
            status_thread.start()
            self.assertTrue(status_done.wait(0.5))

            stop_done = threading.Event()
            stop_thread = real_thread(
                target=lambda: (engine.stop(), stop_done.set())
            )
            stop_thread.start()
            self.assertTrue(stop_done.wait(0.5))

            startup_release.set()
            start_thread.join(1)
            status_thread.join(1)
            stop_thread.join(1)

    def test_stop_cannot_finish_before_new_thread_start_is_committed(self):
        engine = BotEngine()
        engine.device = FakeDevice()
        engine.matcher = FakeMatcher()
        probe = BlockingThread()
        real_thread = threading.Thread

        with patch.object(engine, "refresh_device"), patch(
            "src.bot.engine.GameStartupFlow"
        ), patch("src.bot.engine.threading.Thread", return_value=probe):
            start_thread = real_thread(target=engine.start)
            start_thread.start()
            self.assertTrue(probe.start_called.wait(1))

            stop_done = threading.Event()
            stop_thread = real_thread(
                target=lambda: (engine.stop(), stop_done.set())
            )
            stop_thread.start()
            self.assertFalse(stop_done.wait(0.2))

            probe.release.set()
            start_thread.join(1)
            stop_thread.join(1)

        self.assertTrue(probe.started)
        self.assertTrue(stop_done.is_set())
        self.assertFalse(engine.state.running)

    def test_start_refuses_when_previous_thread_is_still_alive(self):
        engine = BotEngine()
        engine.device = FakeDevice()
        engine.matcher = FakeMatcher()
        engine._thread = AliveThread()
        engine.state.running = True

        self.assertEqual(engine.stop(), "已停止挂机")
        with patch.object(engine, "refresh_device") as refresh, patch(
            "src.bot.engine.GameStartupFlow"
        ), patch("src.bot.engine.threading.Thread"):
            result = engine.start()

        self.assertEqual(result, "上一轮挂机线程仍在停止中")
        refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
