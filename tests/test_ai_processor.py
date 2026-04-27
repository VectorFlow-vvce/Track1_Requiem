import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bot"
sys.path.insert(0, str(BOT_DIR))

from ai_processor import normalize_expense_items


class AiProcessorTests(unittest.TestCase):
    def test_normalize_expense_items_accepts_multiple_expenses(self):
        raw = {
            "expenses": [
                {"amount": 356, "description": "Rapido travel from Yelhanka to Madivala"},
                {"amount": 554, "description": "Uber ride"},
            ]
        }

        items = normalize_expense_items(raw)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["amount"], 356)
        self.assertEqual(items[1]["description"], "Uber ride")

    def test_normalize_expense_items_keeps_legacy_single_expense_shape(self):
        items = normalize_expense_items({"amount": 500, "description": "coffee"})

        self.assertEqual(items, [{"amount": 500.0, "description": "coffee"}])


if __name__ == "__main__":
    unittest.main()
