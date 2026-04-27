import assert from "node:assert/strict";
import { buildDashboardMetrics } from "./dashboard-data.js";

const expenses = [
  { timestamp: "2026-04-25T10:00:00.000Z", category: "Food Delivery", description: "2 puffs", amount: 6838 },
  { timestamp: "2026-04-25T11:00:00.000Z", category: "Income", description: "Salary credited", amount: 45000, type: "income" },
  { timestamp: "2026-04-26T12:00:00.000Z", category: "Bills & Utilities", description: "UPI payment", amount: 810 },
  { timestamp: "2026-04-27T12:00:00.000Z", category: "Restaurants", description: "Parotta", amount: 600 },
];

const metrics = buildDashboardMetrics(expenses, new Date("2026-04-27T18:00:00.000Z"));

assert.equal(metrics.totalSpent, 8248);
assert.equal(metrics.totalIncome, 45000);
assert.equal(metrics.netCashflow, 36752);
assert.equal(metrics.totalIncome - metrics.totalSpent, metrics.netCashflow);
assert.deepEqual(
  metrics.categoryData.map(({ name, value }) => ({ name, value })),
  [
    { name: "Food", value: 6838 },
    { name: "Bills", value: 810 },
    { name: "Dining", value: 600 },
  ],
);
assert.equal(metrics.trendData.length, 7);
assert.equal(metrics.trendData.at(-1).spent, 600);
assert.equal(metrics.trendData.at(-1).income, 0);
assert.equal(metrics.trendData.at(-1).balance, 36752);
assert.equal(metrics.monthlySummary.categoryBreakdown.Food, 6838);
