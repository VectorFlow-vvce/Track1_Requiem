import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bot"
sys.path.insert(0, str(BOT_DIR))

from categorizer import get_fallback_category


class CategorizerFallbackTests(unittest.TestCase):
    def test_food_terms_map_to_food_categories(self):
        self.assertEqual(get_fallback_category("coffee"), "Coffee & Beverages")
        self.assertEqual(get_fallback_category("two parottas and beef"), "Restaurants")
        self.assertEqual(get_fallback_category("pizza delivery"), "Food Delivery")

    def test_travel_transport_and_fuel_terms_map_to_specific_categories(self):
        self.assertEqual(get_fallback_category("flight ticket to Delhi"), "Travel")
        self.assertEqual(get_fallback_category("uber ride home"), "Transportation")
        self.assertEqual(get_fallback_category("namma yatri auto ride"), "Transportation")
        self.assertEqual(get_fallback_category("nanma yatri ride"), "Transportation")
        self.assertEqual(get_fallback_category("petrol at shell"), "Gas & Fuel")


if __name__ == "__main__":
    unittest.main()
