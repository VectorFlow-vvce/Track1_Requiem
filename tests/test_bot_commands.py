import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bot"
sys.path.insert(0, str(BOT_DIR))

from bot import BOT_COMMANDS, resolve_text_command


class BotCommandTests(unittest.TestCase):
    def test_bot_commands_include_user_facing_actions(self):
        command_names = [command.command for command in BOT_COMMANDS]

        self.assertEqual(
            command_names,
            ["start", "help", "language", "summary", "insights", "subscriptions", "setbudget", "export", "stats", "reminders", "suggestions", "dashboard"],
        )

    def test_resolve_text_command_accepts_slash_and_plain_text(self):
        self.assertEqual(resolve_text_command("/summary"), "summary")
        self.assertEqual(resolve_text_command("summary"), "summary")
        self.assertEqual(resolve_text_command("show my summary"), "summary")
        self.assertEqual(resolve_text_command("open dashboard"), "dashboard")
        self.assertEqual(resolve_text_command("help me"), "help")

    def test_resolve_text_command_ignores_expense_messages(self):
        self.assertIsNone(resolve_text_command("spent 500 on coffee"))
        self.assertIsNone(resolve_text_command("dinner 3000 split with 4 people"))


if __name__ == "__main__":
    unittest.main()
