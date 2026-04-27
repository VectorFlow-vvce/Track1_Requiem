import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bot"
sys.path.insert(0, str(BOT_DIR))

from utils import build_summary_stats, build_spend_forecast


class SummaryAnalyticsTests(unittest.TestCase):
    def test_build_summary_stats_calculates_key_metrics(self):
        expenses = [
            {
                "amount": 300,
                "category": "Restaurants",
                "description": "pizza",
                "timestamp": "2026-04-25T10:00:00",
            },
            {
                "amount": 1200,
                "category": "Gas & Fuel",
                "description": "petrol",
                "timestamp": "2026-04-26T11:00:00",
            },
            {
                "amount": 500,
                "category": "Restaurants",
                "description": "dinner",
                "timestamp": "2026-04-26T20:00:00",
            },
        ]

        stats = build_summary_stats(expenses)

        self.assertEqual(stats["total_spend"], 2000)
        self.assertEqual(stats["transaction_count"], 3)
        self.assertEqual(stats["top_category"], "Gas & Fuel")
        self.assertEqual(stats["category_totals"]["Restaurants"], 800)
        self.assertEqual(stats["daily_totals"]["2026-04-26"], 1700)
        self.assertEqual(stats["largest_expense"]["description"], "petrol")

    def test_build_summary_stats_handles_empty_expenses(self):
        stats = build_summary_stats([])

        self.assertEqual(stats["total_spend"], 0)
        self.assertEqual(stats["transaction_count"], 0)
        self.assertEqual(stats["top_category"], "None")
        self.assertEqual(stats["category_totals"], {})
        self.assertEqual(stats["forecast"]["method"], "insufficient_data")

    def test_build_spend_forecast_returns_seven_future_days(self):
        daily_totals = {
            "2026-04-20": 500,
            "2026-04-21": 650,
            "2026-04-22": 700,
            "2026-04-23": 850,
            "2026-04-24": 900,
            "2026-04-25": 1050,
            "2026-04-26": 1200,
        }

        forecast = build_spend_forecast(daily_totals, periods=7)

        self.assertEqual(len(forecast["daily"]), 7)
        self.assertEqual(forecast["daily"][0]["date"], "2026-04-27")
        self.assertGreater(forecast["next_7_days_total"], 0)
        self.assertIn(forecast["method"], {"arima", "advanced_arima_fallback"})


if __name__ == "__main__":
    unittest.main()
