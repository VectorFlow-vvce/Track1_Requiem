"""Tests for new features: undo, wallets, lending, PDF reports,
hierarchical summaries, duplicate detection, date-range filtering,
spending velocity, and edit-last-expense."""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "bot"
sys.path.insert(0, str(BOT_DIR))

import utils


class _TempDataMixin:
    """Redirect all data files to a temp directory so tests don't touch real data."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_data = utils.DATA_FILE
        self._orig_budgets = utils.BUDGETS_FILE
        self._orig_wallets = utils.WALLETS_FILE
        self._orig_ledger = utils.LEDGER_FILE
        self._orig_gamification = utils.GAMIFICATION_FILE
        utils.DATA_FILE = os.path.join(self._tmpdir, "expenses.json")
        utils.BUDGETS_FILE = os.path.join(self._tmpdir, "budgets.json")
        utils.WALLETS_FILE = os.path.join(self._tmpdir, "wallets.json")
        utils.LEDGER_FILE = os.path.join(self._tmpdir, "ledger.json")
        utils.GAMIFICATION_FILE = os.path.join(self._tmpdir, "gamification.json")

    def tearDown(self):
        utils.DATA_FILE = self._orig_data
        utils.BUDGETS_FILE = self._orig_budgets
        utils.WALLETS_FILE = self._orig_wallets
        utils.LEDGER_FILE = self._orig_ledger
        utils.GAMIFICATION_FILE = self._orig_gamification
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)


# ── 1. Undo / pop_last_expense ──────────────────────────────────────

class UndoTests(_TempDataMixin, unittest.TestCase):
    def test_pop_last_expense_returns_none_when_empty(self):
        self.assertIsNone(utils.pop_last_expense(999))

    def test_pop_last_expense_removes_and_returns_last(self):
        utils.save_expense(1, 500, "Food", "lunch")
        utils.save_expense(1, 200, "Coffee", "chai")

        popped = utils.pop_last_expense(1)

        self.assertEqual(popped["amount"], 200)
        self.assertEqual(popped["description"], "chai")
        remaining = utils.load_expenses().get("1", [])
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["amount"], 500)

    def test_pop_last_expense_leaves_empty_list(self):
        utils.save_expense(1, 100, "Other", "test")
        utils.pop_last_expense(1)

        remaining = utils.load_expenses().get("1", [])
        self.assertEqual(remaining, [])


# ── 2. Wallet System ────────────────────────────────────────────────

class WalletTests(_TempDataMixin, unittest.TestCase):
    def test_add_wallet_creates_with_initial_balance(self):
        name = utils.add_wallet(1, "HDFC Bank", wallet_type="bank", initial_balance=50000)

        wallets = utils.get_wallets(1)
        self.assertIn(name, wallets)
        self.assertEqual(wallets[name]["balance"], 50000)
        self.assertEqual(wallets[name]["type"], "bank")

    def test_save_expense_deducts_from_wallet(self):
        utils.add_wallet(1, "cash", initial_balance=10000)
        utils.save_expense(1, 500, "Food", "lunch", wallet="cash")

        wallets = utils.get_wallets(1)
        self.assertEqual(wallets["cash"]["balance"], 9500)

    def test_transfer_between_wallets_moves_balance(self):
        utils.add_wallet(1, "bank", initial_balance=20000)
        utils.add_wallet(1, "cash", initial_balance=1000)

        utils.transfer_between_wallets(1, "bank", "cash", 5000)

        wallets = utils.get_wallets(1)
        self.assertEqual(wallets["bank"]["balance"], 15000)
        self.assertEqual(wallets["cash"]["balance"], 6000)

    def test_wallet_auto_created_on_expense(self):
        utils.save_expense(1, 300, "Food", "snack", wallet="upi")

        wallets = utils.get_wallets(1)
        self.assertIn("upi", wallets)
        self.assertEqual(wallets["upi"]["balance"], -300)

    def test_get_wallets_returns_empty_for_new_user(self):
        self.assertEqual(utils.get_wallets(999), {})


# ── 3. Lending & Borrowing Ledger ───────────────────────────────────

class LendingTests(_TempDataMixin, unittest.TestCase):
    def test_lend_creates_positive_debt(self):
        utils.add_ledger_entry(1, "lend", "Karim", 5000, note="for rent")

        debts = utils.get_outstanding_debts(1)
        self.assertEqual(debts["Karim"], 5000)

    def test_borrow_creates_negative_debt(self):
        utils.add_ledger_entry(1, "borrow", "Priya", 3000)

        debts = utils.get_outstanding_debts(1)
        self.assertEqual(debts["Priya"], -3000)

    def test_lend_and_partial_repay_nets_correctly(self):
        utils.add_ledger_entry(1, "lend", "Rahul", 10000)
        utils.add_ledger_entry(1, "borrow", "Rahul", 4000)  # Rahul paid back 4k

        debts = utils.get_outstanding_debts(1)
        self.assertEqual(debts["Rahul"], 6000)

    def test_fully_settled_person_not_in_debts(self):
        utils.add_ledger_entry(1, "lend", "Amit", 2000)
        utils.add_ledger_entry(1, "borrow", "Amit", 2000)

        debts = utils.get_outstanding_debts(1)
        self.assertNotIn("Amit", debts)

    def test_multiple_people_tracked_independently(self):
        utils.add_ledger_entry(1, "lend", "A", 1000)
        utils.add_ledger_entry(1, "borrow", "B", 2000)

        debts = utils.get_outstanding_debts(1)
        self.assertEqual(debts["A"], 1000)
        self.assertEqual(debts["B"], -2000)

    def test_empty_ledger_returns_empty(self):
        self.assertEqual(utils.get_outstanding_debts(999), {})


# ── 4. PDF Report Generation ────────────────────────────────────────

class PDFReportTests(_TempDataMixin, unittest.TestCase):
    def test_pdf_returns_none_for_empty_user(self):
        self.assertIsNone(utils.generate_pdf_report(999))

    def test_pdf_generates_file(self):
        utils.save_expense(1, 500, "Food", "lunch")
        utils.save_expense(1, 200, "Coffee", "chai")

        path = utils.generate_pdf_report(1, days=30)

        self.assertIsNotNone(path)
        self.assertTrue(os.path.exists(path))
        self.assertTrue(path.endswith(".pdf"))
        # Cleanup
        os.remove(path)

    def test_pdf_filters_by_date_range(self):
        # Save an old expense outside the range
        data = utils.load_expenses()
        data["1"] = [{
            "amount": 999, "category": "Old", "description": "ancient",
            "source": "text", "wallet": "cash",
            "timestamp": (datetime.now() - timedelta(days=60)).isoformat(),
        }]
        utils._atomic_write(utils.DATA_FILE, data)

        path = utils.generate_pdf_report(1, days=30)
        # Old expense is outside 30-day window → no report
        self.assertIsNone(path)


# ── 5. Hierarchical Category Summary ────────────────────────────────

class HierarchicalSummaryTests(_TempDataMixin, unittest.TestCase):
    def test_returns_none_for_empty_user(self):
        self.assertIsNone(utils.build_hierarchical_summary(999))

    def test_groups_subcategories_under_parents(self):
        utils.save_expense(1, 500, "Restaurants", "dinner")
        utils.save_expense(1, 300, "Fast Food", "burger")
        utils.save_expense(1, 200, "Gas & Fuel", "petrol")

        result = utils.build_hierarchical_summary(1)

        self.assertIn("Food", result)
        self.assertIn("Restaurants", result)
        self.assertIn("Fast Food", result)
        self.assertIn("Transport", result)
        self.assertIn("Gas & Fuel", result)

    def test_tree_connectors_present(self):
        utils.save_expense(1, 100, "Restaurants", "food")
        utils.save_expense(1, 50, "Coffee & Beverages", "chai")

        result = utils.build_hierarchical_summary(1)

        self.assertTrue(any(c in result for c in ("├──", "└──")))

    def test_grand_total_in_header(self):
        utils.save_expense(1, 1000, "Shopping & Retail", "shoes")
        utils.save_expense(1, 500, "Entertainment", "movie")

        result = utils.build_hierarchical_summary(1)

        self.assertIn("₹1,500", result)


# ── 6. Duplicate Detection ──────────────────────────────────────────

class DuplicateDetectionTests(_TempDataMixin, unittest.TestCase):
    def test_detects_duplicate_within_window(self):
        utils.save_expense(1, 500, "Food", "lunch at office")

        dup = utils.check_duplicate(1, 500, "lunch at office", window_minutes=10)

        self.assertIsNotNone(dup)
        self.assertEqual(dup["amount"], 500)

    def test_no_duplicate_for_different_amount(self):
        utils.save_expense(1, 500, "Food", "lunch")

        dup = utils.check_duplicate(1, 600, "lunch", window_minutes=10)

        self.assertIsNone(dup)

    def test_no_duplicate_for_different_description(self):
        utils.save_expense(1, 500, "Food", "lunch")

        dup = utils.check_duplicate(1, 500, "dinner", window_minutes=10)

        self.assertIsNone(dup)

    def test_no_duplicate_outside_time_window(self):
        # Manually insert an old expense
        data = {"1": [{
            "amount": 500, "category": "Food", "description": "lunch",
            "source": "text", "wallet": "cash",
            "timestamp": (datetime.now() - timedelta(minutes=30)).isoformat(),
        }]}
        utils._atomic_write(utils.DATA_FILE, data)

        dup = utils.check_duplicate(1, 500, "lunch", window_minutes=10)

        self.assertIsNone(dup)

    def test_no_duplicate_for_empty_user(self):
        self.assertIsNone(utils.check_duplicate(999, 100, "test"))


# ── 7. Date Range Filtering ─────────────────────────────────────────

class DateRangeFilterTests(unittest.TestCase):
    def _make_expense(self, days_ago, amount=100, category="Food"):
        return {
            "amount": amount, "category": category, "description": "test",
            "timestamp": (datetime.now() - timedelta(days=days_ago)).isoformat(),
        }

    def test_today_filter(self):
        expenses = [self._make_expense(0), self._make_expense(1), self._make_expense(5)]

        result = utils.filter_expenses_by_range(expenses, "today")

        self.assertEqual(len(result), 1)

    def test_this_month_filter(self):
        expenses = [self._make_expense(0), self._make_expense(10), self._make_expense(60)]

        result = utils.filter_expenses_by_range(expenses, "this_month")

        # Day 0 and day 10 should be in current month (unless near month boundary)
        self.assertGreaterEqual(len(result), 1)
        self.assertLessEqual(len(result), 2)

    def test_empty_expenses_returns_empty(self):
        self.assertEqual(utils.filter_expenses_by_range([], "today"), [])

    def test_unknown_range_returns_all(self):
        expenses = [self._make_expense(0), self._make_expense(100)]

        result = utils.filter_expenses_by_range(expenses, "all_time")

        self.assertEqual(len(result), 2)

    def test_none_range_returns_all(self):
        expenses = [self._make_expense(0)]
        self.assertEqual(utils.filter_expenses_by_range(expenses, None), expenses)


# ── 8. Spending Velocity ────────────────────────────────────────────

class SpendingVelocityTests(_TempDataMixin, unittest.TestCase):
    def test_returns_none_with_few_expenses(self):
        utils.save_expense(1, 100, "Food", "a")
        self.assertIsNone(utils.check_spending_velocity(1))

    def test_detects_high_velocity_day(self):
        # Create past expenses: 5 days, ₹500/day average
        data = {"1": []}
        for d in range(1, 6):
            data["1"].append({
                "amount": 500, "category": "Food", "description": "daily",
                "source": "text", "wallet": "cash",
                "timestamp": (datetime.now() - timedelta(days=d)).isoformat(),
            })
        # Today: ₹5000 (10x average)
        data["1"].append({
            "amount": 5000, "category": "Shopping", "description": "big purchase",
            "source": "text", "wallet": "cash",
            "timestamp": datetime.now().isoformat(),
        })
        utils._atomic_write(utils.DATA_FILE, data)

        result = utils.check_spending_velocity(1)

        self.assertIsNotNone(result)
        self.assertEqual(result["today"], 5000)
        self.assertAlmostEqual(result["average"], 500, places=0)
        self.assertGreater(result["ratio"], 2)

    def test_no_alert_for_normal_spending(self):
        data = {"1": []}
        for d in range(1, 6):
            data["1"].append({
                "amount": 500, "category": "Food", "description": "daily",
                "source": "text", "wallet": "cash",
                "timestamp": (datetime.now() - timedelta(days=d)).isoformat(),
            })
        data["1"].append({
            "amount": 400, "category": "Food", "description": "normal",
            "source": "text", "wallet": "cash",
            "timestamp": datetime.now().isoformat(),
        })
        utils._atomic_write(utils.DATA_FILE, data)

        self.assertIsNone(utils.check_spending_velocity(1))


# ── 9. Edit Last Expense ────────────────────────────────────────────

class EditLastExpenseTests(_TempDataMixin, unittest.TestCase):
    def test_edit_amount(self):
        utils.save_expense(1, 500, "Food", "lunch")

        result = utils.edit_last_expense(1, "amount", "750")

        self.assertEqual(result["old"], 500)
        self.assertEqual(result["new"], 750)
        expenses = utils.load_expenses()["1"]
        self.assertEqual(expenses[-1]["amount"], 750)

    def test_edit_description(self):
        utils.save_expense(1, 500, "Food", "lunch")

        result = utils.edit_last_expense(1, "description", "dinner with friends")

        self.assertEqual(result["old"], "lunch")
        self.assertEqual(result["new"], "dinner with friends")

    def test_edit_returns_none_for_empty_user(self):
        self.assertIsNone(utils.edit_last_expense(999, "amount", "100"))


# ── 10. Known Subscription Detection ────────────────────────────────

class SubscriptionDetectionTests(_TempDataMixin, unittest.TestCase):
    def test_single_netflix_detected_as_subscription(self):
        utils.save_expense(1, 749, "Subscriptions", "Netflix")

        subs = utils.detect_subscriptions(1)

        self.assertEqual(len(subs), 1)
        self.assertIn("Netflix", subs[0]["description"])
        self.assertEqual(subs[0]["frequency_days"], 30)

    def test_single_spotify_detected(self):
        utils.save_expense(1, 119, "Subscriptions", "Spotify premium")

        subs = utils.detect_subscriptions(1)

        names = [s["description"].lower() for s in subs]
        self.assertTrue(any("spotify" in n for n in names))

    def test_non_subscription_not_detected(self):
        utils.save_expense(1, 500, "Food", "lunch at restaurant")

        subs = utils.detect_subscriptions(1)

        self.assertEqual(len(subs), 0)

    def test_empty_user_returns_empty(self):
        self.assertEqual(utils.detect_subscriptions(999), [])


# ── 11. Budget Alert Threshold ──────────────────────────────────────

class BudgetAlertTests(_TempDataMixin, unittest.TestCase):
    def test_alert_at_80_percent(self):
        utils.save_budget(1, "Food", 1000)
        utils.save_expense(1, 850, "Food", "big meal")

        alert = utils.check_budget_exceeded(1, "Food")

        self.assertIsNotNone(alert)
        self.assertEqual(alert["category"], "Food")
        self.assertGreaterEqual(alert["percentage"], 80)

    def test_no_alert_below_80_percent(self):
        utils.save_budget(1, "Food", 1000)
        utils.save_expense(1, 500, "Food", "lunch")

        alert = utils.check_budget_exceeded(1, "Food")

        self.assertIsNone(alert)

    def test_exceeded_flag_when_over_100_percent(self):
        utils.save_budget(1, "Food", 1000)
        utils.save_expense(1, 1200, "Food", "feast")

        alert = utils.check_budget_exceeded(1, "Food")

        self.assertTrue(alert["exceeded"])

    def test_no_alert_for_unset_category(self):
        utils.save_expense(1, 500, "Food", "lunch")

        self.assertIsNone(utils.check_budget_exceeded(1, "Food"))


if __name__ == "__main__":
    unittest.main()
