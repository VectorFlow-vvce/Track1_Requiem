const CATEGORY_COLORS = [
  "#6366F1",
  "#F59E0B",
  "#10B981",
  "#EC4899",
  "#0EA5E9",
  "#8B5CF6",
  "#EF4444",
  "#14B8A6",
];

const CATEGORY_ALIASES = [
  [/food|delivery|swiggy|zomato/i, "Food"],
  [/restaurant|dining|parotta|cafe|coffee/i, "Dining"],
  [/bill|utilit|upi|electric|water|gas/i, "Bills"],
  [/salary|income|credit/i, "Income"],
  [/shop|store|amazon|flipkart/i, "Shopping"],
  [/travel|uber|ola|cab|flight/i, "Travel"],
];

function startOfDay(date) {
  const next = new Date(date);
  next.setHours(0, 0, 0, 0);
  return next;
}

function isIncomeExpense(expense) {
  return expense?.type === "income" || expense?.type === "salary" || expense?.category === "Income";
}

export function normalizeCategory(category = "") {
  const match = CATEGORY_ALIASES.find(([pattern]) => pattern.test(category));
  return match ? match[1] : category || "Other";
}

function dayLabel(date) {
  return date.toLocaleDateString("en-US", { weekday: "short" });
}

export function buildDashboardMetrics(expenses = [], now = new Date()) {
  const days = Array.from({ length: 7 }, (_, index) => {
    const date = startOfDay(now);
    date.setDate(date.getDate() - (6 - index));
    return {
      key: date.toISOString().slice(0, 10),
      day: dayLabel(date),
      spent: 0,
      income: 0,
      balance: 0,
    };
  });
  const dayMap = new Map(days.map((day) => [day.key, day]));
  const categoryTotals = new Map();

  let totalSpent = 0;
  let totalIncome = 0;

  for (const expense of expenses) {
    const amount = Number(expense?.amount) || 0;
    const date = new Date(expense?.timestamp || now);
    const key = startOfDay(date).toISOString().slice(0, 10);
    const bucket = dayMap.get(key);
    const income = isIncomeExpense(expense);

    if (income) {
      totalIncome += amount;
      if (bucket) bucket.income += amount;
      continue;
    }

    const category = normalizeCategory(expense?.category);
    totalSpent += amount;
    categoryTotals.set(category, (categoryTotals.get(category) || 0) + amount);
    if (bucket) bucket.spent += amount;
  }

  let runningBalance = 0;
  const trendData = days.map((day) => {
    runningBalance += day.income - day.spent;
    return {
      ...day,
      balance: runningBalance,
    };
  });

  const categoryData = Array.from(categoryTotals.entries())
    .sort(([, a], [, b]) => b - a)
    .map(([name, value], index) => ({
      name,
      value,
      color: CATEGORY_COLORS[index % CATEGORY_COLORS.length],
    }));

  const netCashflow = totalIncome - totalSpent;

  return {
    totalSpent,
    totalIncome,
    netCashflow,
    trendData,
    categoryData,
    monthlySummary: {
      month: now.toISOString().slice(0, 7),
      totalSpent,
      totalIncome,
      netCashflow,
      categoryBreakdown: Object.fromEntries(categoryData.map(({ name, value }) => [name, value])),
      comparisonToPreviousMonth: {
        spentChange: 0,
        incomeChange: 0,
        cashflowChange: 0,
      },
      anomalies: [],
      generatedAt: now,
    },
    sparkBalance: trendData.map((day, i) => ({ i, v: day.balance })),
    sparkSpent: trendData.map((day, i) => ({ i, v: day.spent })),
    sparkIncome: trendData.map((day, i) => ({ i, v: day.income })),
  };
}
