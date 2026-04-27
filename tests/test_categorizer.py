import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bot"
sys.path.insert(0, str(BOT_DIR))

from categorizer import get_fallback_category, get_tfidf_category


class CategorizerFallbackTests(unittest.TestCase):
    def test_food_terms_map_to_food_categories(self):
        self.assertEqual(get_fallback_category("coffee"), "Coffee & Beverages")
        self.assertEqual(get_fallback_category("two parottas and beef"), "Restaurants")
        self.assertEqual(get_fallback_category("pizza delivery"), "Food Delivery")
        self.assertEqual(get_tfidf_category("mandi"), "Restaurants")
        self.assertEqual(get_tfidf_category("ate mandi total bill"), "Restaurants")
        self.assertEqual(get_tfidf_category("ate my budget"), "Other")
        self.assertEqual(get_tfidf_category("ordered mandi from zomato"), "Food Delivery")

    def test_travel_transport_and_fuel_terms_map_to_specific_categories(self):
        self.assertEqual(get_fallback_category("flight ticket to Delhi"), "Travel")
        self.assertEqual(get_fallback_category("uber ride home"), "Transportation")
        self.assertEqual(get_fallback_category("namma yatri auto ride"), "Transportation")
        self.assertEqual(get_fallback_category("nanma yatri ride"), "Transportation")
        self.assertEqual(get_fallback_category("petrol at shell"), "Gas & Fuel")

    def test_tfidf_maps_real_world_scenarios_across_categories(self):
        scenarios = {
            "paid electricity bill for apartment": "Bills & Utilities",
            "jio fiber wifi recharge": "Bills & Utilities",
            "atm cash withdrawal near office": "Cash & ATM",
            "withdrew cash from hdfc atm": "Cash & ATM",
            "daycare fees for kid": "Childcare",
            "bought diapers and baby wipes": "Childcare",
            "filter coffee at cafe": "Coffee & Beverages",
            "chai and lime juice": "Coffee & Beverages",
            "bought chips and water at seven eleven": "Convenience",
            "quick snacks from corner shop": "Convenience",
            "udemy python course": "Education",
            "paid college exam fee": "Education",
            "movie tickets and popcorn": "Entertainment",
            "bowling and arcade games": "Entertainment",
            "burger and fries at mcdonalds": "Fast Food",
            "kfc fried chicken meal": "Fast Food",
            "donated to temple charity": "Giving",
            "ngo relief fund contribution": "Giving",
            "monthly supermarket groceries": "Groceries",
            "vegetables rice milk and bread": "Groceries",
            "petrol at indian oil pump": "Gas & Fuel",
            "diesel refill for car": "Gas & Fuel",
            "doctor consultation and medicines": "Healthcare",
            "apollo pharmacy tablets": "Healthcare",
            "monthly rent for flat": "Housing",
            "apartment maintenance payment": "Housing",
            "life insurance premium renewal": "Insurance",
            "bike insurance policy": "Insurance",
            "mandi restaurant bill": "Restaurants",
            "parotta and beef from hotel": "Restaurants",
            "amazon order for headphones": "Shopping & Retail",
            "myntra shoes and shirt": "Shopping & Retail",
            "netflix monthly plan": "Subscriptions",
            "spotify premium renewal": "Subscriptions",
            "sent money to rahul through upi": "Transfers",
            "bank transfer to landlord": "Transfers",
            "uber ride to airport": "Transportation",
            "namma yatri auto fare": "Transportation",
            "flight ticket to dubai": "Travel",
            "hotel booking in goa": "Travel",
            "salary credited this month": "Income",
            "freelance payment received": "Income",
        }

        for text, category in scenarios.items():
            with self.subTest(text=text):
                self.assertEqual(get_tfidf_category(text), category)

    def test_tfidf_handles_indian_and_mixed_language_scenarios(self):
        scenarios = {
            "chaya and pazham pori": "Coffee & Beverages",
            "sapadu at mess": "Restaurants",
            "oonu meals at hotel": "Restaurants",
            "ordered biryani on swiggy": "Food Delivery",
            "dmart monthly provisions": "Groceries",
            "zepto milk bread eggs": "Groceries",
            "recharged airtel prepaid": "Bills & Utilities",
            "paid bescom electricity": "Bills & Utilities",
            "rapido bike ride": "Transportation",
            "ksrtc bus ticket": "Transportation",
            "irctc train ticket": "Travel",
            "oyo room booking": "Travel",
            "netmeds medicine order": "Healthcare",
            "cult fit membership": "Healthcare",
            "zerodha fund transfer": "Transfers",
            "mutual fund sip": "Transfers",
        }

        for text, category in scenarios.items():
            with self.subTest(text=text):
                self.assertEqual(get_tfidf_category(text), category)


if __name__ == "__main__":
    unittest.main()
