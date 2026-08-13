import unittest
from unittest.mock import patch

from src.adb.device import AdbDevice


class AdbDeviceLaunchTests(unittest.TestCase):
    def test_resolves_launcher_activity_when_config_activity_is_empty(self):
        device = AdbDevice(adb_path="adb", serial="emulator-5554")
        calls = []

        def shell(command, timeout=30):
            calls.append(command)
            if command.startswith("cmd package resolve-activity"):
                return (
                    "priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 "
                    "isDefault=false\ncom.sgbltx.goodgame/com.gamesdk.h5.GameActivity"
                )
            return ""

        device.shell = shell
        with patch("src.adb.device.config.get") as get, patch(
            "src.adb.device.time.sleep"
        ):
            get.side_effect = lambda section, key: {
                ("game", "package"): "com.sgbltx.goodgame",
                ("game", "activity"): "",
                ("game", "launch_wait"): 0,
            }.get((section, key))

            device.start_game()

        self.assertIn(
            "cmd package resolve-activity --brief com.sgbltx.goodgame",
            calls,
        )
        self.assertIn(
            "am start -n com.sgbltx.goodgame/com.gamesdk.h5.GameActivity",
            calls,
        )
        self.assertNotIn(
            "monkey -p com.sgbltx.goodgame -c android.intent.category.LAUNCHER 1",
            calls,
        )


if __name__ == "__main__":
    unittest.main()
