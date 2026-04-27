import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bot"
sys.path.insert(0, str(BOT_DIR))

from ai_processor import (
    convert_to_inr,
    normalize_expense_items,
    receipt_needs_clarification,
    classify_intent,
)


def _mock_classify(return_json):
    """Patch ai_processor.client to return a canned JSON response."""
    import ai_processor, types, json

    class FakeChoice:
        def __init__(self, content):
            self.message = types.SimpleNamespace(content=content)

    class FakeResponse:
        def __init__(self, content):
            self.choices = [FakeChoice(content)]

    class FakeCompletions:
        def __init__(self, content):
            self._content = content
        def create(self, **_kw):
            return FakeResponse(self._content)

    class FakeChat:
        def __init__(self, content):
            self.completions = FakeCompletions(content)

    original = ai_processor.client
    ai_processor.client = types.SimpleNamespace(chat=FakeChat(json.dumps(return_json)))
    return original


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

    def test_normalize_expense_items_applies_split_logic(self):
        raw = {
            "amount": 3000,
            "description": "Dinner with friends",
            "split": {"people": 4},
        }

        items = normalize_expense_items(raw)

        self.assertEqual(items[0]["amount"], 750)
        self.assertEqual(items[0]["original_amount"], 3000)
        self.assertEqual(items[0]["split_people"], 4)
        self.assertEqual(items[0]["status"], "settled")

    def test_convert_to_inr_uses_supplied_exchange_rates(self):
        converted = convert_to_inr(50, "USD", rates={"USD": 83})

        self.assertEqual(converted["amount"], 4150)
        self.assertEqual(converted["currency"], "INR")
        self.assertEqual(converted["original_amount"], 50)
        self.assertEqual(converted["original_currency"], "USD")

    def test_normalize_expense_items_converts_foreign_currency(self):
        raw = {
            "amount": 50,
            "currency": "USD",
            "description": "Airport lunch",
        }

        items = normalize_expense_items(raw, rates={"USD": 83})

        self.assertEqual(items[0]["amount"], 4150)
        self.assertEqual(items[0]["original_amount"], 50)
        self.assertEqual(items[0]["original_currency"], "USD")

    def test_receipt_needs_clarification_for_low_confidence_or_failed_amount(self):
        self.assertTrue(receipt_needs_clarification({"amount": 0, "description": "Receipt extraction failed"}))
        self.assertTrue(receipt_needs_clarification({"amount": 125, "description": "unclear bill", "confidence": 0.35}))
        self.assertFalse(receipt_needs_clarification({"amount": 125, "description": "restaurant bill", "confidence": 0.8}))

    def test_classify_intent_returns_command_for_known_intent(self):
        import ai_processor
        original = _mock_classify({"intent": "summary", "category": None})
        try:
            result = classify_intent("show me my spending overview")
            self.assertEqual(result, {"command": "summary"})
        finally:
            ai_processor.client = original

    def test_classify_intent_returns_category_for_category_query(self):
        import ai_processor
        original = _mock_classify({"intent": "category_query", "category": "food"})
        try:
            result = classify_intent("how much did I spend on food?")
            self.assertEqual(result, {"command": "category_query", "category": "food"})
        finally:
            ai_processor.client = original

    def test_classify_intent_returns_none_for_expense(self):
        import ai_processor
        original = _mock_classify({"intent": "expense", "category": None})
        try:
            result = classify_intent("spent 500 on coffee")
            self.assertIsNone(result)
        finally:
            ai_processor.client = original

    def test_classify_intent_returns_none_for_empty_text(self):
        self.assertIsNone(classify_intent(""))
        self.assertIsNone(classify_intent(None))


if __name__ == "__main__":
    unittest.main()
