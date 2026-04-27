import json
import os
from datetime import datetime, timedelta
import tempfile
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import FuncFormatter

DATA_FILE = os.path.join(os.path.dirname(__file__), '../data/expenses.json')
BUDGETS_FILE = os.path.join(os.path.dirname(__file__), '../data/budgets.json')
GAMIFICATION_FILE = os.path.join(os.path.dirname(__file__), '../data/gamification.json')
REMINDERS_FILE = os.path.join(os.path.dirname(__file__), '../data/reminders.json')
LANG_FILE = os.path.join(os.path.dirname(__file__), '../data/languages.json')
FORECAST_PERIODS = 7

SUPPORTED_LANGUAGES = {
    "en": "English",
    "hi": "हिन्दी (Hindi)",
    "ml": "മലയാളം (Malayalam)",
    "ta": "தமிழ் (Tamil)",
    "te": "తెలుగు (Telugu)",
    "kn": "ಕನ್ನಡ (Kannada)",
}
DEFAULT_LANGUAGE = "en"


def _atomic_write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=4)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def load_languages():
    if not os.path.exists(LANG_FILE):
        return {}
    with open(LANG_FILE, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def get_user_language(user_id):
    return load_languages().get(str(user_id), DEFAULT_LANGUAGE)


def set_user_language(user_id, lang_code):
    data = load_languages()
    data[str(user_id)] = lang_code
    _atomic_write(LANG_FILE, data)

def load_expenses():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_expense(user_id, amount, category, description, source="text", metadata=None):
    data = load_expenses()
    user_key = str(user_id)
    if user_key not in data:
        data[user_key] = []

    expense = {
        "amount": amount,
        "category": category,
        "description": description,
        "source": source,
        "timestamp": datetime.now().isoformat()
    }
    if metadata:
        expense.update(metadata)

    data[user_key].append(expense)

    _atomic_write(DATA_FILE, data)
    
    # Update gamification
    update_gamification(user_id)


def check_duplicate(user_id, amount, description, window_minutes=10):
    expenses = load_expenses().get(str(user_id), [])
    if not expenses:
        return None
    now = datetime.now()
    for i, e in enumerate(reversed(expenses)):
        ts = datetime.fromisoformat(e['timestamp'])
        if (now - ts).total_seconds() > window_minutes * 60:
            break
        if abs(e['amount'] - amount) < 0.01 and e['description'].lower().strip() == description.lower().strip():
            return e
    return None


def _empty_forecast(method="insufficient_data"):
    return {
        "method": method,
        "daily": [],
        "next_7_days_total": 0,
        "average_daily_forecast": 0,
    }


def _forecast_with_statsmodels(series, periods):
    from statsmodels.tsa.arima.model import ARIMA

    # A compact ARIMA(1,1,1) handles short personal-spend histories without
    # requiring seasonal data or a long training window.
    model = ARIMA(series.astype(float), order=(1, 1, 1), enforce_stationarity=False, enforce_invertibility=False)
    fitted = model.fit()
    forecast = fitted.forecast(steps=periods)
    return [max(0, round(float(value), 2)) for value in forecast]


def _forecast_with_trend_fallback(series, periods):
    values = [float(value) for value in series.tolist()]
    if len(values) < 2:
        return [max(0, round(values[0], 2))] * periods if values else []

    recent_window = values[-min(7, len(values)):]
    recent_average = sum(recent_window) / len(recent_window)
    deltas = [values[index] - values[index - 1] for index in range(1, len(values))]
    recent_deltas = deltas[-min(5, len(deltas)):]
    trend = sum(recent_deltas) / len(recent_deltas) if recent_deltas else 0
    trend = max(min(trend, recent_average * 0.35), -recent_average * 0.35)

    return [
        max(0, round(recent_average + trend * (step + 1), 2))
        for step in range(periods)
    ]


def build_spend_forecast(daily_totals, periods=FORECAST_PERIODS):
    if not daily_totals:
        return _empty_forecast()

    series = pd.Series(daily_totals, dtype="float64")
    series.index = pd.to_datetime(series.index, errors="coerce")
    series = series[series.index.notna()].sort_index()
    if series.empty:
        return _empty_forecast()

    full_index = pd.date_range(series.index.min(), series.index.max(), freq="D")
    series = series.reindex(full_index, fill_value=0).astype(float)
    if len(series) < 3:
        return _empty_forecast()

    method = "arima"
    try:
        forecast_values = _forecast_with_statsmodels(series, periods)
    except Exception:
        method = "advanced_arima_fallback"
        forecast_values = _forecast_with_trend_fallback(series, periods)

    start_date = series.index.max() + pd.Timedelta(days=1)
    forecast_dates = pd.date_range(start_date, periods=periods, freq="D")
    daily = [
        {"date": date.date().isoformat(), "amount": amount}
        for date, amount in zip(forecast_dates, forecast_values)
    ]
    total = round(sum(item["amount"] for item in daily), 2)
    return {
        "method": method,
        "daily": daily,
        "next_7_days_total": total,
        "average_daily_forecast": round(total / len(daily), 2) if daily else 0,
    }


def build_summary_stats(expenses):
    if not expenses:
        return {
            "total_spend": 0,
            "transaction_count": 0,
            "average_spend": 0,
            "top_category": "None",
            "category_totals": {},
            "daily_totals": {},
            "largest_expense": None,
            "recent_expenses": [],
            "forecast": _empty_forecast(),
        }

    normalized = []
    for expense in expenses:
        amount = float(expense.get("amount", 0) or 0)
        timestamp = expense.get("timestamp") or datetime.now().isoformat()
        normalized.append({
            **expense,
            "amount": amount,
            "category": expense.get("category") or "Other",
            "description": expense.get("description") or "Expense",
            "timestamp": timestamp,
        })

    df = pd.DataFrame(normalized)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["date"] = df["timestamp"].dt.date.astype(str)

    category_totals = df.groupby("category")["amount"].sum().sort_values(ascending=False)
    daily_totals = df.groupby("date")["amount"].sum().sort_index()
    largest = max(normalized, key=lambda item: item["amount"])
    recent = sorted(normalized, key=lambda item: item["timestamp"], reverse=True)[:5]

    return {
        "total_spend": float(df["amount"].sum()),
        "transaction_count": int(len(df)),
        "average_spend": float(df["amount"].mean()),
        "top_category": category_totals.index[0] if not category_totals.empty else "None",
        "category_totals": category_totals.to_dict(),
        "daily_totals": daily_totals.to_dict(),
        "largest_expense": largest,
        "recent_expenses": recent,
        "forecast": build_spend_forecast(daily_totals.to_dict()),
    }


def _rupee(value, _position=None):
    return f"Rs {value:,.0f}"


def generate_pie_chart(user_id):
    expenses = load_expenses().get(str(user_id), [])
    if not expenses:
        return None

    stats = build_summary_stats(expenses)
    if stats["transaction_count"] == 0:
        return None

    category_totals = pd.Series(stats["category_totals"]).sort_values(ascending=False)
    daily_totals = pd.Series(stats["daily_totals"])
    recent_expenses = stats["recent_expenses"][:4]

    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "axes.titleweight": "bold",
        "axes.labelcolor": "#475569",
        "xtick.color": "#64748b",
        "ytick.color": "#64748b",
    })

    fig = plt.figure(figsize=(14, 9), dpi=180)
    fig.patch.set_facecolor("#f8fafc")
    grid = fig.add_gridspec(3, 4, height_ratios=[0.8, 2.2, 1.8], hspace=0.58, wspace=0.44)

    ax_header = fig.add_subplot(grid[0, :])
    ax_header.axis("off")
    ax_header.text(0.0, 0.82, "FineHance Omni", fontsize=25, fontweight="bold", color="#0f172a")
    ax_header.text(0.0, 0.36, "AI-ready spending snapshot", fontsize=11, color="#64748b")
    ax_header.text(
        0.99,
        0.70,
        f"Total: Rs {stats['total_spend']:,.0f}",
        ha="right",
        fontsize=24,
        fontweight="bold",
        color="#166534",
    )
    ax_header.text(
        0.99,
        0.30,
        f"{stats['transaction_count']} txns  |  Avg Rs {stats['average_spend']:,.0f}  |  Top: {stats['top_category']}",
        ha="right",
        fontsize=11,
        color="#475569",
    )

    ax_donut = fig.add_subplot(grid[1, :2])
    colors = ["#2563eb", "#16a34a", "#f97316", "#9333ea", "#dc2626", "#0f766e", "#64748b"]
    wedges, _texts, autotexts = ax_donut.pie(
        category_totals.values,
        labels=None,
        startangle=90,
        colors=colors[:len(category_totals)],
        autopct=lambda pct: f"{pct:.0f}%" if pct >= 8 else "",
        pctdistance=0.78,
        wedgeprops={"width": 0.42, "edgecolor": "#f8fafc", "linewidth": 3},
    )
    for autotext in autotexts:
        autotext.set_color("white")
        autotext.set_fontweight("bold")
        autotext.set_fontsize(9)
    ax_donut.set_title("Category Mix", loc="left", fontsize=15, color="#0f172a")
    ax_donut.legend(
        wedges,
        category_totals.index,
        loc="center left",
        bbox_to_anchor=(1.0, 0.5),
        frameon=False,
        fontsize=9,
    )

    ax_trend = fig.add_subplot(grid[1, 2:])
    ax_trend.set_title("Daily Spend", loc="left", fontsize=15, color="#0f172a")
    ax_trend.plot(daily_totals.index, daily_totals.values, color="#2563eb", linewidth=3, marker="o")
    ax_trend.fill_between(daily_totals.index, daily_totals.values, color="#dbeafe", alpha=0.8)
    ax_trend.yaxis.set_major_formatter(FuncFormatter(_rupee))
    ax_trend.grid(axis="y", color="#e2e8f0", linewidth=1)
    ax_trend.spines[["top", "right", "left"]].set_visible(False)
    ax_trend.tick_params(axis="x", rotation=15)

    ax_bars = fig.add_subplot(grid[2, :2])
    ax_bars.set_title("Top Categories", loc="left", fontsize=15, color="#0f172a")
    top_categories = category_totals.head(5).sort_values()
    ax_bars.barh(top_categories.index, top_categories.values, color="#16a34a", alpha=0.88)
    ax_bars.xaxis.set_major_formatter(FuncFormatter(_rupee))
    ax_bars.grid(axis="x", color="#e2e8f0", linewidth=1)
    ax_bars.spines[["top", "right", "left"]].set_visible(False)

    ax_recent = fig.add_subplot(grid[2, 2:])
    ax_recent.axis("off")
    ax_recent.set_title("Recent Activity", loc="left", fontsize=15, color="#0f172a")
    y = 0.82
    for expense in recent_expenses:
        ax_recent.text(0.02, y, expense["category"], fontsize=11, fontweight="bold", color="#0f172a")
        ax_recent.text(0.02, y - 0.13, expense["description"][:42], fontsize=9, color="#64748b")
        ax_recent.text(0.98, y, f"Rs {expense['amount']:,.0f}", ha="right", fontsize=12, fontweight="bold", color="#166534")
        y -= 0.22

    os.makedirs("assets", exist_ok=True)
    file_path = f"assets/{user_id}_summary.png"
    fig.savefig(file_path, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return file_path


def detect_subscriptions(user_id):
    expenses = load_expenses().get(str(user_id), [])
    if len(expenses) < 2:
        return []
    
    df = pd.DataFrame(expenses)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['date'] = df['timestamp'].dt.date
    df = df.sort_values('timestamp')
    
    subscriptions = []
    seen = set()
    
    for desc in df['description'].unique():
        desc_key = desc[:20].lower().strip()
        if desc_key in seen:
            continue
        
        matching = df[df['description'].str.lower().str.contains(desc_key[:15], regex=False)]
        if len(matching) < 2:
            continue
        
        amounts = matching['amount'].values
        if len(amounts) < 2 or amounts.std() > amounts.mean() * 0.15:
            continue
        
        dates = sorted(matching['date'].values)
        if len(dates) < 2:
            continue
        
        gaps = [int((pd.Timestamp(dates[i+1]) - pd.Timestamp(dates[i])).days) for i in range(len(dates)-1)]
        avg_gap = sum(gaps) / len(gaps)
        
        if 20 <= avg_gap <= 40:
            seen.add(desc_key)
            subscriptions.append({
                'description': desc,
                'amount': float(amounts.mean()),
                'frequency_days': int(avg_gap),
                'occurrences': len(matching),
                'category': matching.iloc[0]['category']
            })
    
    return sorted(subscriptions, key=lambda x: x['amount'], reverse=True)


def load_budgets():
    if not os.path.exists(BUDGETS_FILE):
        return {}
    with open(BUDGETS_FILE, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_budget(user_id, category, amount):
    budgets = load_budgets()
    user_key = str(user_id)
    if user_key not in budgets:
        budgets[user_key] = {}
    budgets[user_key][category] = float(amount)
    
    _atomic_write(BUDGETS_FILE, budgets)


def check_budget_exceeded(user_id, category):
    budgets = load_budgets().get(str(user_id), {})
    if category not in budgets:
        return None
    limit = budgets[category]
    expenses = load_expenses().get(str(user_id), [])
    current_month = datetime.now().month
    current_year = datetime.now().year
    month_total = sum(
        e['amount'] for e in expenses
        if e['category'] == category
        and datetime.fromisoformat(e['timestamp']).month == current_month
        and datetime.fromisoformat(e['timestamp']).year == current_year
    )
    percentage = (month_total / limit) * 100 if limit > 0 else 0
    if percentage >= 80:
        return {
            'category': category, 'spent': month_total, 'limit': limit,
            'exceeded_by': max(0, month_total - limit), 'percentage': percentage,
            'exceeded': month_total > limit,
        }
    return None


def get_user_budgets(user_id):
    return load_budgets().get(str(user_id), {})

def delete_budget(user_id, category):
    budgets = load_budgets()
    user_key = str(user_id)
    if user_key in budgets and category in budgets[user_key]:
        del budgets[user_key][category]
        _atomic_write(BUDGETS_FILE, budgets)
        return True
    return False


def generate_csv_export(user_id):
    expenses = load_expenses().get(str(user_id), [])
    if not expenses:
        return None
    
    df = pd.DataFrame(expenses)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp', ascending=False)
    
    os.makedirs("assets", exist_ok=True)
    file_path = f"assets/{user_id}_expenses.csv"
    df.to_csv(file_path, index=False)
    return file_path


def load_gamification():
    if not os.path.exists(GAMIFICATION_FILE):
        return {}
    with open(GAMIFICATION_FILE, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def update_gamification(user_id):
    data = load_gamification()
    user_key = str(user_id)
    
    if user_key not in data:
        data[user_key] = {
            'streak': 0,
            'last_log_date': None,
            'total_logs': 0,
            'badges': []
        }
    
    user_data = data[user_key]
    today = datetime.now().date().isoformat()
    last_date = user_data.get('last_log_date')
    
    if last_date != today:
        if last_date:
            last = datetime.fromisoformat(last_date).date()
            diff = (datetime.now().date() - last).days
            if diff == 1:
                user_data['streak'] += 1
            elif diff > 1:
                user_data['streak'] = 1
        else:
            user_data['streak'] = 1
        
        user_data['last_log_date'] = today
    
    user_data['total_logs'] += 1
    
    # Award badges
    if user_data['streak'] >= 7 and '7-day-streak' not in user_data['badges']:
        user_data['badges'].append('7-day-streak')
    if user_data['total_logs'] >= 50 and '50-logs' not in user_data['badges']:
        user_data['badges'].append('50-logs')
    if user_data['total_logs'] >= 100 and '100-logs' not in user_data['badges']:
        user_data['badges'].append('100-logs')
    
    os.makedirs(os.path.dirname(GAMIFICATION_FILE), exist_ok=True)
    _atomic_write(GAMIFICATION_FILE, data)
    
    return user_data


def get_gamification_stats(user_id):
    data = load_gamification().get(str(user_id))
    if not data:
        return None
    
    expenses = load_expenses().get(str(user_id), [])
    if len(expenses) < 2:
        return data
    
    df = pd.DataFrame(expenses)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    current_month = datetime.now().month
    last_month = current_month - 1 if current_month > 1 else 12
    
    current_month_expenses = df[df['timestamp'].dt.month == current_month]
    last_month_expenses = df[df['timestamp'].dt.month == last_month]
    
    current_total = current_month_expenses['amount'].sum()
    last_total = last_month_expenses['amount'].sum()
    
    if last_total > 0:
        change = ((current_total - last_total) / last_total) * 100
        data['month_over_month_change'] = round(change, 1)
    
    return data


def load_reminders():
    if not os.path.exists(REMINDERS_FILE):
        return {}
    with open(REMINDERS_FILE, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_reminders(data):
    _atomic_write(REMINDERS_FILE, data)


def toggle_reminders(user_id, chat_id):
    data = load_reminders()
    user_key = str(user_id)
    if user_key in data:
        del data[user_key]
        save_reminders(data)
        return False
    data[user_key] = {"chat_id": chat_id, "enabled": True}
    save_reminders(data)
    return True


def get_reminder_users():
    return load_reminders()


def filter_expenses_by_range(expenses, range_key):
    if not expenses or not range_key:
        return expenses
    now = datetime.now()
    today = now.date()
    if range_key == 'today':
        start = today
        end = today
    elif range_key == 'this_week':
        start = today - timedelta(days=today.weekday())
        end = today
    elif range_key == 'last_week':
        start = today - timedelta(days=today.weekday() + 7)
        end = start + timedelta(days=6)
    elif range_key == 'this_month':
        start = today.replace(day=1)
        end = today
    elif range_key == 'last_month':
        first_of_month = today.replace(day=1)
        last_month_end = first_of_month - timedelta(days=1)
        start = last_month_end.replace(day=1)
        end = last_month_end
    else:
        return expenses
    return [e for e in expenses if start <= datetime.fromisoformat(e['timestamp']).date() <= end]


def check_spending_velocity(user_id):
    expenses = load_expenses().get(str(user_id), [])
    if len(expenses) < 5:
        return None
    today = datetime.now().date()
    today_total = sum(e['amount'] for e in expenses if datetime.fromisoformat(e['timestamp']).date() == today)
    past_days = {}
    for e in expenses:
        d = datetime.fromisoformat(e['timestamp']).date()
        if d < today:
            past_days.setdefault(d, 0)
            past_days[d] += e['amount']
    if not past_days:
        return None
    avg_daily = sum(past_days.values()) / len(past_days)
    if avg_daily > 0 and today_total > avg_daily * 2:
        return {'today': today_total, 'average': avg_daily, 'ratio': round(today_total / avg_daily, 1)}
    return None


def edit_last_expense(user_id, field, value):
    data = load_expenses()
    user_key = str(user_id)
    if user_key not in data or not data[user_key]:
        return None
    expense = data[user_key][-1]
    old_value = expense.get(field)
    if field == 'amount':
        value = float(value)
    expense[field] = value
    _atomic_write(DATA_FILE, data)
    return {'field': field, 'old': old_value, 'new': value, 'expense': expense}


def pop_last_expense(user_id):
    """Remove and return the last expense for a user. Returns the expense dict or None."""
    data = load_expenses()
    user_key = str(user_id)
    if user_key not in data or not data[user_key]:
        return None
    last = data[user_key].pop()
    _atomic_write(DATA_FILE, data)
    return last


def user_logged_today(user_id):
    expenses = load_expenses().get(str(user_id), [])
    if not expenses:
        return False
    today = datetime.now().date().isoformat()
    return any(e.get("timestamp", "").startswith(today) for e in expenses)


def build_category_comparison(user_id):
    """Build current vs previous month spending per category."""
    expenses = load_expenses().get(str(user_id), [])
    if not expenses:
        return {}

    now = datetime.now()
    cur_month, cur_year = now.month, now.year
    prev_month = cur_month - 1 if cur_month > 1 else 12
    prev_year = cur_year if cur_month > 1 else cur_year - 1

    stats = {}
    for e in expenses:
        ts = datetime.fromisoformat(e.get("timestamp", now.isoformat()))
        cat = e.get("category", "Other")
        amt = float(e.get("amount", 0))
        if cat not in stats:
            stats[cat] = {"current": 0, "previous": 0, "txn_count": 0}
        if ts.month == cur_month and ts.year == cur_year:
            stats[cat]["current"] += amt
            stats[cat]["txn_count"] += 1
        elif ts.month == prev_month and ts.year == prev_year:
            stats[cat]["previous"] += amt

    for info in stats.values():
        prev = info["previous"]
        cur = info["current"]
        info["change"] = ((cur - prev) / prev * 100) if prev > 0 else (100 if cur > 0 else 0)

    return dict(sorted(stats.items(), key=lambda x: x[1]["current"], reverse=True))
