import logging
import os
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, CallbackQueryHandler, ContextTypes,
    CommandHandler, MessageHandler, filters,
)
from dotenv import load_dotenv

from ai_processor import (
    extract_expense_items,
    transcribe_voice,
    extract_from_receipt,
    generate_insights,
    generate_suggestions,
    generate_summary_insight,
    normalize_expense_items,
    receipt_needs_clarification,
    parse_voice_command,
    classify_intent,
    translate_response,
)
from categorizer import get_category
from utils import (
    save_expense,
    generate_pie_chart,
    load_expenses,
    build_summary_stats,
    detect_subscriptions,
    save_budget,
    check_budget_exceeded,
    generate_csv_export,
    get_gamification_stats,
    toggle_reminders,
    get_reminder_users,
    user_logged_today,
    pop_last_expense,
    get_user_language,
    set_user_language,
    build_category_comparison,
    check_duplicate,
    filter_expenses_by_range,
    check_spending_velocity,
    edit_last_expense,
    SUPPORTED_LANGUAGES,
    add_wallet,
    get_wallets,
    transfer_between_wallets,
    add_ledger_entry,
    get_outstanding_debts,
    generate_pdf_report,
    build_hierarchical_summary,
)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand("start", "Start the assistant"),
    BotCommand("help", "Show what I can do"),
    BotCommand("language", "Change bot language"),
    BotCommand("summary", "View spending summary and chart"),
    BotCommand("treesummary", "Hierarchical spending breakdown"),
    BotCommand("insights", "Get AI financial insights"),
    BotCommand("subscriptions", "View recurring expenses"),
    BotCommand("setbudget", "Set category budget"),
    BotCommand("export", "Export expenses to CSV"),
    BotCommand("report", "Generate PDF expense report"),
    BotCommand("balance", "View wallet balances"),
    BotCommand("wallet", "Add a wallet (e.g. /wallet cash 5000)"),
    BotCommand("transfer", "Transfer between wallets"),
    BotCommand("lend", "Record money lent (e.g. /lend John 500)"),
    BotCommand("borrow", "Record money borrowed"),
    BotCommand("debts", "View outstanding debts"),
    BotCommand("stats", "View your streaks and badges"),
    BotCommand("reminders", "Toggle smart reminders on/off"),
    BotCommand("suggestions", "Get spending suggestions per category"),
    BotCommand("dashboard", "Open the dashboard link"),
]

COMMAND_ALIASES = {
    "start": ("start", "restart", "shuru", "thudangu", "aarambham"),
    "help": ("help", "commands", "menu", "what can you do", "how to use",
             "madad", "sahayam", "udavi", "sahaya"),
    "language": ("language", "lang", "bhasha", "bhasa"),
    "summary": ("summary", "summarise", "summarize", "snapshot", "spending summary",
                "saransh", "saaram", "surukkam", "sangrahamu"),
    "treesummary": ("treesummary", "tree summary", "tree", "category tree", "hierarchical summary", "breakdown",
                    "vibhajan", "vargeekaranam", "pirivu"),
    "insights": ("insights", "insight", "advice", "tips", "financial insights",
                 "sujhav", "nirdeshangal", "yosanai", "salahalu"),
    "subscriptions": ("subscriptions", "recurring", "recurring expenses", "subs",
                      "avritti", "aavarthanam", "meelameelavaru"),
    "setbudget": ("setbudget", "set budget", "budget", "bajat", "budget set cheyyuka"),
    "export": ("export", "download", "csv", "excel", "niryat", "irakkam"),
    "report": ("report", "pdf report", "generate report", "expense report",
               "vivaran", "report undakkuka", "arikkai"),
    "balance": ("balance", "balances", "wallet balance", "show balance", "my balance", "how much money",
                "bakaya", "shesh", "balance kanikku", "iruppu", "migilindi"),
    "wallet": ("wallet", "add wallet", "new wallet", "create wallet",
               "batua", "purse", "wallet undakkuka", "panam pai"),
    "transfer": ("transfer", "move money", "send money", "transfer money",
                 "bhejein", "panam maaruka", "panam anuppu", "badili"),
    "lend": ("lend", "lent", "gave", "loan to", "lend money",
             "udhar diya", "panam koduthu", "kadan koduthu", "appichanu"),
    "borrow": ("borrow", "borrowed", "took loan", "borrow money",
               "udhar liya", "panam vanghi", "kadan vanghi", "appichanu vanghi"),
    "debts": ("debts", "debt", "who owes", "owe", "outstanding", "lending", "borrowing",
              "karz", "kadam", "kadan", "appukal", "aappu"),
    "stats": ("stats", "statistics", "streak", "badges", "achievements",
              "ankde", "kanakku", "pulli", "sankhyalu"),
    "reminders": ("reminders", "reminder", "remind me", "toggle reminders",
                  "yaad dilao", "ormapaduthu", "ninaivuppaduthu"),
    "suggestions": ("suggestions", "suggestion", "suggest", "spending suggestions",
                    "sujhav", "nirdeshangal", "parinaamangal"),
    "dashboard": ("dashboard", "command center", "open dashboard", "web dashboard",
                  "niyantran kaksha", "dashboard thurakku", "dashboard tira"),
}

# Categories that represent money coming IN (not expenses)
INCOME_CATEGORIES = {"Income"}


# ── helpers ──────────────────────────────────────────────────────────

def _lang(update):
    return get_user_language(update.effective_user.id)


async def _reply(update, text, lang=None, **kwargs):
    lang = lang or _lang(update)
    translated = translate_response(text, lang)
    await update.message.reply_text(translated, parse_mode='Markdown', **kwargs)


def _format_amount(amount):
    return f"{amount:,.0f}" if float(amount).is_integer() else f"{amount:,.2f}"


def resolve_text_command(text):
    normalized = " ".join((text or "").strip().lower().split())
    if not normalized:
        return None
    # Exact greetings → help
    if normalized in ("hi", "hello", "hey", "hii", "helo", "yo", "hola"):
        return "help"
    if normalized.startswith("/"):
        command = normalized[1:].split()[0].split("@")[0]
        return command if command in COMMAND_ALIASES else None
    for command, aliases in COMMAND_ALIASES.items():
        if normalized in aliases:
            return command
        if command != "start" and any(normalized.startswith(f"{alias} ") for alias in aliases):
            return command
        if command in {"summary", "insights", "dashboard", "help", "balance", "debts", "report", "treesummary"} and any(alias in normalized for alias in aliases):
            return command
    return None


def log_expense_items(user_id, items, source):
    logged = []
    for item in items:
        amount = item.get("amount", 0)
        description = item.get("description", "")
        if amount <= 0 or not description:
            continue
        category = get_category(description)
        # Override category for income/salary/loan types detected by LLM
        item_type = item.get("type", "expense")
        if item_type in ("income", "salary", "credit"):
            category = "Income"
        metadata = {
            key: item[key]
            for key in (
                "currency", "original_amount", "original_currency", "fx_rate",
                "split_people", "reimbursable_amount", "status", "confidence",
                "type", "date",
            )
            if key in item and item[key] is not None
        }
        save_expense(user_id, amount, category, description, source=source, metadata=metadata)
        logged.append({"amount": amount, "category": category, "description": description, **metadata})
    return logged


def _format_original_amount(item):
    original_amount = item.get("original_amount")
    original_currency = item.get("original_currency")
    if original_amount is None:
        return None
    if original_currency:
        return f"{original_currency} {_format_amount(float(original_amount))}"
    return f"₹{_format_amount(float(original_amount))}"


def build_logged_message(logged, prefix=None):
    if len(logged) == 1:
        item = logged[0]
        item_type = item.get("type", "expense")
        if item_type in ("income", "salary", "credit"):
            icon = "💰"
            prefix = prefix or "💰 Received"
        elif item_type in ("loan", "debt", "emi"):
            icon = "🏦"
            prefix = prefix or "🏦 Logged"
        else:
            icon = "✅"
            prefix = prefix or "✅ Logged"
        lines = [
            f"{prefix} ₹{_format_amount(item['amount'])} under **{item['category']}**\n"
            f"📝 *{item['description']}*"
        ]
        original = _format_original_amount(item)
        if item.get("original_currency"):
            lines.append(f"🌍 Converted from {original}")
        if item.get("split_people"):
            lines.append(
                f"👥 Split {original or 'the bill'} with {item['split_people']} people; "
                f"₹{_format_amount(item.get('reimbursable_amount', 0))} tagged as reimbursable/settled."
            )
        return "\n".join(lines)

    total = sum(item['amount'] for item in logged)
    lines = [f"✅ Logged **{len(logged)} items** — Total: **₹{_format_amount(total)}**\n"]
    shown = logged if len(logged) <= 20 else logged[:18]
    for item in shown:
        item_type = item.get("type", "expense")
        icon = "💰" if item_type in ("income", "salary", "credit") else "🏦" if item_type in ("loan", "debt", "emi") else "•"
        detail = f"{icon} ₹{_format_amount(item['amount'])} - **{item['category']}** - {item['description']}"
        original = _format_original_amount(item)
        if item.get("original_currency"):
            detail += f" (converted from {original})"
        if item.get("split_people"):
            detail += f" (split {item['split_people']} ways)"
        lines.append(detail)
    if len(logged) > 20:
        lines.append(f"\n_...and {len(logged) - 18} more items_")
    return "\n".join(lines)


# ── intent dispatch ──────────────────────────────────────────────────

async def _dispatch_intent(voice_cmd, update, context):
    if not voice_cmd:
        return False
    cmd = voice_cmd['command']
    handler = {
        'start': start, 'help': help_command, 'language': language,
        'summary': summary, 'treesummary': treesummary, 'insights': insights,
        'subscriptions': subscriptions, 'export': export_expenses,
        'report': report_pdf, 'balance': balance, 'debts': debts,
        'stats': stats, 'reminders': reminders, 'dashboard': dashboard,
        'suggestions': suggestions,
    }.get(cmd)
    if handler:
        await handler(update, context)
        return True
    if cmd == 'category_query':
        await handle_category_query(update, context, voice_cmd.get('category', ''))
        return True
    if cmd == 'delete_last':
        await delete_last_expense(update, context)
        return True
    if cmd == 'setbudget':
        cat = voice_cmd.get('category', '')
        amt = voice_cmd.get('amount')
        if cat and amt:
            context.args = cat.split() + [str(amt)]
        else:
            context.args = []
        await setbudget(update, context)
        return True
    if cmd == 'date_range_query':
        await handle_date_range_query(update, context, voice_cmd.get('period', 'this_month'), voice_cmd.get('category', ''))
        return True
    if cmd == 'edit_expense':
        await handle_edit_expense(update, context, voice_cmd.get('field', 'amount'), voice_cmd.get('value', ''))
        return True
    return False


# ── command handlers ─────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await _reply(update,
        f"👋 Hello {user.first_name}! Welcome to **FineHance Omni**.\n\n"
        "I am your frictionless financial assistant. You can:\n"
        "🎙️ Send a voice note (e.g., 'Spent 500 on dinner')\n"
        "👁️ Send a photo of a receipt\n"
        "💬 Type your expense or income\n"
        "💰 Track salary, loans, EMIs and debts\n"
        "🌍 Use /language to change my language\n\n"
        "Try: 'I spent 300 on pizza today'\n"
        "Or: 'Received 50000 salary'\n"
        "Or: 'Paid 5000 EMI for home loan'",
        _lang(update),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    await _reply(update,
        "👋 **Welcome to FineHance Omni!**\n"
        "I'm your AI financial assistant. Here's everything I can do:\n\n"

        "━━━ 💬 *Just Talk to Me* ━━━\n"
        "Send a voice note or text in *any language*:\n"
        "• _\"Spent 500 on coffee\"_\n"
        "• _\"Dinner 3000, split with 4 people\"_\n"
        "• _\"Food-inu 200 spent aayi\"_ (Malayalam)\n"
        "• _\"50 dollars lunch\"_\n"
        "📸 Or snap a photo of a receipt!\n\n"

        "━━━ 📊 *View Your Finances* ━━━\n"
        "/summary — Spending chart + AI analysis\n"
        "/treesummary — Category breakdown as a tree\n"
        "/insights — AI-powered financial advice\n"
        "/report — Download PDF expense report\n"
        "/export — Download CSV spreadsheet\n"
        "/dashboard — Open the web dashboard\n\n"

        "━━━ 💰 *Wallets & Money* ━━━\n"
        "/wallet cash 5000 — Create a wallet\n"
        "/balance — See all wallet balances\n"
        "/transfer cash hdfc 3000 — Move money\n\n"

        "━━━ 🤝 *Lending & Borrowing* ━━━\n"
        "/lend John 500 dinner — Record money lent\n"
        "/borrow Sarah 1000 tickets — Record borrowed\n"
        "/debts — See who owes whom\n\n"

        "━━━ 🎯 *Budgets & Tracking* ━━━\n"
        "/setbudget Food 5000 — Set a monthly limit\n"
        "/subscriptions — Spot recurring charges\n"
        "/stats — Your streaks & badges\n"
        "/suggestions — Smart saving tips\n\n"

        "━━━ ⚙️ *Settings* ━━━\n"
        "/language — Switch language (EN/HI/ML/TA/TE/KN)\n"
        "/reminders — Evening nudge on/off\n\n"

        "💡 *Tip:* You don't need slash commands! Just type naturally:\n"
        "_\"show my balance\"_ · _\"who owes me\"_ · _\"generate report\"_",
        lang,
    )


async def language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [InlineKeyboardButton(name, callback_data=f"lang:{code}")]
        for code, name in SUPPORTED_LANGUAGES.items()
    ]
    await update.message.reply_text(
        "🌍 **Choose your language / भाषा चुनें / ഭാഷ തിരഞ്ഞെടുക്കുക / மொழியைத் தேர்ந்தெடுங்கள் / భాషను ఎంచుకోండి / ಭಾಷೆಯನ್ನು ಆಯ್ಕೆಮಾಡಿ**",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode='Markdown',
    )


async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    code = query.data.split(":")[1]
    if code not in SUPPORTED_LANGUAGES:
        return
    set_user_language(query.from_user.id, code)
    lang_name = SUPPORTED_LANGUAGES[code]
    confirm = translate_response(f"✅ Language set to **{lang_name}**!\n\nAll my responses will now be in {lang_name}.", code)
    await query.edit_message_text(confirm, parse_mode='Markdown')


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    lang = _lang(update)

    command = resolve_text_command(text)
    if command:
        handlers = {
            "start": start, "help": help_command, "language": language,
            "summary": summary, "treesummary": treesummary, "insights": insights,
            "subscriptions": subscriptions, "setbudget": setbudget,
            "export": export_expenses, "report": report_pdf,
            "balance": balance, "wallet": wallet_cmd, "transfer": transfer_cmd,
            "lend": lend, "borrow": borrow, "debts": debts,
            "stats": stats, "reminders": reminders, "suggestions": suggestions,
            "dashboard": dashboard,
        }
        await handlers[command](update, context)
        return

    # If text contains numbers (amounts), skip intent classification — go straight to expense extraction
    import re
    has_amounts = bool(re.search(r'\d{2,}', text))
    voice_cmd = None if has_amounts else (parse_voice_command(text) or classify_intent(text))
    if await _dispatch_intent(voice_cmd, update, context):
        return

    await context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action="typing")

    items, detected = extract_expense_items(text)
    if detected and detected != "en" and lang == "en":
        set_user_language(user_id, detected)
        lang = detected

    logged = log_expense_items(user_id, items, source="text")
    if logged:
        response = build_logged_message(logged)
        for item in logged:
            alert = check_budget_exceeded(user_id, item['category'])
            if alert:
                if alert.get('exceeded'):
                    response += f"\n\n🚨 **Budget Exceeded!**\n{alert['category']}: ₹{alert['spent']:,.0f} / ₹{alert['limit']:,.0f} ({alert['percentage']:.0f}%)"
                else:
                    response += f"\n\n⚠️ **Budget Warning!**\n{alert['category']}: ₹{alert['spent']:,.0f} / ₹{alert['limit']:,.0f} ({alert['percentage']:.0f}%)"
        velocity = check_spending_velocity(user_id)
        if velocity:
            response += f"\n\n🏎️ **Spending Alert:** You've spent ₹{velocity['today']:,.0f} today — {velocity['ratio']}x your daily average of ₹{velocity['average']:,.0f}"
        await _reply(update, response, lang)
    else:
        await _reply(update, "🤔 I couldn't catch the amount. Try saying something like 'Spent 500 on coffee'.", lang)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action="record_voice")
    lang = _lang(update)

    voice_file = await update.message.voice.get_file()
    os.makedirs("assets", exist_ok=True)
    file_path = f"assets/{update.effective_user.id}_{update.message.message_id}.ogg"
    await voice_file.download_to_drive(file_path)

    text = transcribe_voice(file_path)
    os.remove(file_path)
    if not text:
        await _reply(update, "❌ Sorry, I couldn't understand the audio.", lang)
        return

    voice_cmd = parse_voice_command(text) or classify_intent(text)
    if await _dispatch_intent(voice_cmd, update, context):
        return

    items, detected = extract_expense_items(text)
    if detected and detected != "en" and lang == "en":
        set_user_language(update.effective_user.id, detected)
        lang = detected
    logged = log_expense_items(update.effective_user.id, items, source="voice")
    if logged:
        await _reply(update, f"🎙️ Heard: \"{text}\"\n{build_logged_message(logged)}", lang)
    else:
        await _reply(update, f"🎙️ I heard: \"{text}\"\nBut I couldn't find an amount. Try again?", lang)


async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action="upload_photo")
    lang = _lang(update)

    photo_file = await update.message.photo[-1].get_file()
    os.makedirs("assets", exist_ok=True)
    file_path = f"assets/{update.effective_user.id}_{update.message.message_id}.jpg"
    await photo_file.download_to_drive(file_path)

    details = extract_from_receipt(file_path)
    os.remove(file_path)
    if receipt_needs_clarification(details):
        await _reply(update, "I'm having trouble reading that receipt. Can you just tell me the total amount?", lang)
        return

    items = normalize_expense_items(details)
    logged = log_expense_items(update.effective_user.id, items, source="image")
    if logged:
        await _reply(update, f"👁️ Receipt Scanned!\n{build_logged_message(logged)}", lang)
    else:
        await _reply(update, "I'm having trouble reading that receipt. Can you just tell me the total amount?", lang)


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action="upload_photo")
    user_id = update.effective_user.id
    lang = _lang(update)
    expenses = load_expenses().get(str(user_id), [])
    if not expenses:
        await _reply(update, "📉 No data yet! Log some expenses first to see your summary.", lang)
        return

    chart_path = generate_pie_chart(user_id)
    if chart_path and os.path.exists(chart_path):
        stats_data = build_summary_stats(expenses)
        advice = generate_summary_insight(stats_data)
        advice = translate_response(advice, lang)
        with open(chart_path, 'rb') as chart_file:
            caption = translate_response("📊 **Your Financial Snapshot**", lang)
            await update.message.reply_photo(photo=chart_file, caption=caption, parse_mode='Markdown')
        header = translate_response("🧠 **AI Summary**", lang)
        await update.message.reply_text(f"{header}\n\n{advice}", parse_mode='Markdown')
    else:
        await _reply(update, "📉 No data yet! Log some expenses first to see your summary.", lang)


async def insights(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = _lang(update)
    expenses = load_expenses().get(str(user_id), [])

    if len(expenses) < 3:
        await _reply(update, "📉 I need at least 3 expenses to give you meaningful insights. Keep logging!", lang)
        return

    await context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action="typing")
    advice = generate_insights(expenses)
    advice = translate_response(advice, lang)
    header = translate_response("🧠 **AI Financial Insights**", lang)
    await update.message.reply_text(f"{header}\n\n{advice}", parse_mode='Markdown')


async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    link = f"http://localhost:5173?user={user_id}"
    await _reply(update,
        "🖥️ **Your Command Center**\n"
        "View your full financial analytics here:\n\n"
        f"🔗 [Open Dashboard]({link})\n\n"
        "Make sure both the **API server** (`python bot/api_server.py`) and "
        "**frontend** (`cd frontend && npx vite`) are running.",
        _lang(update),
    )


async def subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = _lang(update)
    subs = detect_subscriptions(user_id)

    if not subs:
        await _reply(update, "📭 No recurring expenses detected yet. Keep logging to discover subscriptions!", lang)
        return

    lines = ["🔄 **Recurring Expenses Detected**\n"]
    total_monthly = 0
    for sub in subs:
        monthly_cost = (sub['amount'] * 30) / sub['frequency_days']
        total_monthly += monthly_cost
        lines.append(
            f"• **{sub['description'][:40]}**\n"
            f"  ₹{sub['amount']:,.0f} every ~{sub['frequency_days']} days\n"
            f"  (~₹{monthly_cost:,.0f}/month)\n"
        )
    lines.append(f"\n💸 **Total Monthly Drain:** ₹{total_monthly:,.0f}")
    await _reply(update, "\n".join(lines), lang)


async def setbudget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    if not context.args or len(context.args) < 2:
        await _reply(update,
            "Usage: /setbudget <category> <amount>\n"
            "Example: /setbudget Restaurants 5000",
            lang,
        )
        return

    category = " ".join(context.args[:-1])
    try:
        amount = float(context.args[-1])
    except ValueError:
        await _reply(update, "❌ Invalid amount. Please use a number.", lang)
        return

    save_budget(update.effective_user.id, category, amount)
    await _reply(update,
        f"✅ Budget set!\n**{category}**: ₹{amount:,.0f}/month\n\n"
        "I'll alert you when you exceed this budget.",
        lang,
    )


async def export_expenses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = _lang(update)
    csv_path = generate_csv_export(user_id)

    if not csv_path:
        await _reply(update, "📭 No expenses to export yet!", lang)
        return

    await context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action="upload_document")
    caption = translate_response("📊 Your expense data exported successfully!", lang)
    with open(csv_path, 'rb') as csv_file:
        await update.message.reply_document(
            document=csv_file,
            filename=f"finehance_expenses_{user_id}.csv",
            caption=caption,
        )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = _lang(update)
    stats_data = get_gamification_stats(user_id)

    if not stats_data:
        await _reply(update, "📊 Start logging expenses to see your stats!", lang)
        return

    streak = stats_data.get('streak', 0)
    total_logs = stats_data.get('total_logs', 0)
    badges = stats_data.get('badges', [])
    mom_change = stats_data.get('month_over_month_change')

    badge_emojis = {
        '7-day-streak': '🔥 7-Day Streak',
        '50-logs': '⭐ 50 Logs',
        '100-logs': '🏆 100 Logs',
    }

    lines = [
        "📊 **Your FineHance Stats**\n",
        f"🔥 **Current Streak:** {streak} day{'s' if streak != 1 else ''}",
        f"📝 **Total Logs:** {total_logs}",
    ]
    if mom_change is not None:
        emoji = "📉" if mom_change < 0 else "📈"
        lines.append(f"{emoji} **Month-over-Month:** {abs(mom_change):.1f}% {'less' if mom_change < 0 else 'more'}")
    if badges:
        lines.append("\n🏅 **Badges Earned:**")
        for badge in badges:
            lines.append(f"  {badge_emojis.get(badge, badge)}")
    else:
        lines.append("\n🎯 Keep logging to earn badges!")

    await _reply(update, "\n".join(lines), lang)


async def reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = _lang(update)
    chat_id = update.effective_message.chat_id
    enabled = toggle_reminders(user_id, chat_id)
    if enabled:
        await _reply(update,
            "🔔 **Smart Reminders ON**\n\n"
            "I'll nudge you at 9 PM if you haven't logged any expenses today.\n"
            "Use /reminders again to turn off.",
            lang,
        )
    else:
        await _reply(update, "🔕 Smart Reminders turned **OFF**.", lang)


async def suggestions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = _lang(update)
    cat_stats = build_category_comparison(user_id)

    if not cat_stats:
        await _reply(update, "📭 No expenses logged yet! Start logging to get personalized suggestions.", lang)
        return

    await context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action="typing")
    advice = generate_suggestions(cat_stats)
    advice = translate_response(advice, lang)
    header = translate_response("💡 **Spending Suggestions**", lang)
    await update.message.reply_text(f"{header}\n\n{advice}", parse_mode='Markdown')


async def send_evening_reminders(context: ContextTypes.DEFAULT_TYPE):
    users = get_reminder_users()
    for user_id, info in users.items():
        if not info.get("enabled"):
            continue
        if user_logged_today(user_id):
            continue
        try:
            lang = get_user_language(user_id)
            msg = translate_response(
                "🌙 Hey! It's evening — did you spend anything today that you forgot to log?\n\n"
                "Just tell me, e.g. *'Spent 200 on dinner'*",
                lang,
            )
            await context.bot.send_message(chat_id=info["chat_id"], text=msg, parse_mode='Markdown')
        except Exception:
            pass


async def handle_category_query(update: Update, context: ContextTypes.DEFAULT_TYPE, category_text: str):
    user_id = update.effective_user.id
    lang = _lang(update)
    expenses = load_expenses().get(str(user_id), [])

    if not expenses:
        await _reply(update, "📭 No expenses logged yet!", lang)
        return

    category_text = category_text.lower().strip()
    matching_expenses = [e for e in expenses if category_text in e['category'].lower()]

    if not matching_expenses:
        await _reply(update, f"🤔 No expenses found for '{category_text}'", lang)
        return

    total = sum(e['amount'] for e in matching_expenses)
    count = len(matching_expenses)
    await _reply(update,
        f"💰 You spent **₹{total:,.0f}** on {matching_expenses[0]['category']}\n"
        f"({count} transaction{'s' if count != 1 else ''})",
        lang,
    )


async def handle_date_range_query(update: Update, context: ContextTypes.DEFAULT_TYPE, period: str, category: str = ''):
    user_id = update.effective_user.id
    lang = _lang(update)
    expenses = load_expenses().get(str(user_id), [])
    if not expenses:
        await _reply(update, "📭 No expenses logged yet!", lang)
        return
    filtered = filter_expenses_by_range(expenses, period)
    if category:
        filtered = [e for e in filtered if category.lower() in e.get('category', '').lower()]
    if not filtered:
        label = period.replace('_', ' ')
        await _reply(update, f"📭 No expenses found for {label}" + (f" on {category}" if category else ""), lang)
        return
    total = sum(e['amount'] for e in filtered)
    count = len(filtered)
    label = period.replace('_', ' ')
    cats = {}
    for e in filtered:
        cats[e.get('category', 'Other')] = cats.get(e.get('category', 'Other'), 0) + e['amount']
    top_cats = sorted(cats.items(), key=lambda x: x[1], reverse=True)[:5]
    lines = [f"📊 **Spending {label}**" + (f" on {category}" if category else "") + "\n",
             f"💰 Total: **₹{total:,.0f}** ({count} transaction{'s' if count != 1 else ''})\n"]
    if not category:
        for cat, amt in top_cats:
            lines.append(f"• {cat}: ₹{amt:,.0f}")
    await _reply(update, "\n".join(lines), lang)


async def handle_edit_expense(update: Update, context: ContextTypes.DEFAULT_TYPE, field: str, value: str):
    user_id = update.effective_user.id
    lang = _lang(update)
    result = edit_last_expense(user_id, field, value)
    if not result:
        await _reply(update, "📭 No expenses to edit!", lang)
        return
    await _reply(update, f"✏️ Updated last expense:\n**{result['field']}**: {result['old']} → {result['new']}", lang)


async def delete_last_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = _lang(update)
    last = pop_last_expense(user_id)
    if not last:
        await _reply(update, "📭 No expenses to delete!", lang)
        return
    await _reply(update, f"✅ Deleted: ₹{last['amount']:,.0f} - {last['description']}", lang)


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = _lang(update)
    wallets = get_wallets(user_id)
    if not wallets:
        await _reply(update, "📭 No wallets yet! Add one with /wallet cash 5000", lang)
        return
    lines = ["💰 **Wallet Balances**\n"]
    total = 0
    for name, info in wallets.items():
        bal = info["balance"]
        total += bal
        lines.append(f"• **{name}**: ₹{bal:,.0f}")
    lines.append(f"\n**Total**: ₹{total:,.0f}")
    await _reply(update, "\n".join(lines), lang)


async def wallet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    if not context.args or len(context.args) < 1:
        await _reply(update, "Usage: /wallet <name> [initial_balance]\nExample: /wallet hdfc 10000", lang)
        return
    name = context.args[0]
    initial = float(context.args[1]) if len(context.args) > 1 else 0
    add_wallet(update.effective_user.id, name, initial_balance=initial)
    await _reply(update, f"✅ Wallet **{name}** created with ₹{initial:,.0f}", lang)


async def transfer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    if not context.args or len(context.args) < 3:
        await _reply(update, "Usage: /transfer <from> <to> <amount>\nExample: /transfer cash hdfc 5000", lang)
        return
    from_w, to_w = context.args[0], context.args[1]
    try:
        amount = float(context.args[2])
    except ValueError:
        await _reply(update, "❌ Invalid amount.", lang)
        return
    transfer_between_wallets(update.effective_user.id, from_w, to_w, amount)
    await _reply(update, f"✅ Transferred ₹{amount:,.0f} from **{from_w}** → **{to_w}**", lang)


async def lend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    if not context.args or len(context.args) < 2:
        await _reply(update, "Usage: /lend <person> <amount> [note]\nExample: /lend John 500 dinner", lang)
        return
    person = context.args[0]
    try:
        amount = float(context.args[1])
    except ValueError:
        await _reply(update, "❌ Invalid amount.", lang)
        return
    note = " ".join(context.args[2:]) if len(context.args) > 2 else ""
    add_ledger_entry(update.effective_user.id, "lend", person, amount, note)
    await _reply(update, f"✅ Recorded: You lent **₹{amount:,.0f}** to **{person}**" + (f" ({note})" if note else ""), lang)


async def borrow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    if not context.args or len(context.args) < 2:
        await _reply(update, "Usage: /borrow <person> <amount> [note]\nExample: /borrow Sarah 1000 tickets", lang)
        return
    person = context.args[0]
    try:
        amount = float(context.args[1])
    except ValueError:
        await _reply(update, "❌ Invalid amount.", lang)
        return
    note = " ".join(context.args[2:]) if len(context.args) > 2 else ""
    add_ledger_entry(update.effective_user.id, "borrow", person, amount, note)
    await _reply(update, f"✅ Recorded: You borrowed **₹{amount:,.0f}** from **{person}**" + (f" ({note})" if note else ""), lang)


async def debts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = _lang(update)
    outstanding = get_outstanding_debts(user_id)
    if not outstanding:
        await _reply(update, "✅ No outstanding debts!", lang)
        return
    lines = ["📋 **Outstanding Debts**\n"]
    for person, amount in sorted(outstanding.items(), key=lambda x: -abs(x[1])):
        if amount > 0:
            lines.append(f"• **{person}** owes you ₹{amount:,.0f}")
        else:
            lines.append(f"• You owe **{person}** ₹{abs(amount):,.0f}")
    await _reply(update, "\n".join(lines), lang)


async def report_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = _lang(update)
    days = 30
    if context.args:
        try:
            days = int(context.args[0])
        except ValueError:
            pass
    await context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action="upload_document")
    path = generate_pdf_report(user_id, days)
    if not path:
        await _reply(update, "📭 No expenses to report!", lang)
        return
    caption = translate_response(f"📊 Expense report — last {days} days", lang)
    with open(path, 'rb') as f:
        await update.message.reply_document(document=f, filename=f"finehance_report_{days}d.pdf", caption=caption)


async def treesummary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = _lang(update)
    text = build_hierarchical_summary(user_id)
    if not text:
        await _reply(update, "📭 No expenses logged yet!", lang)
        return
    await _reply(update, text, lang)


async def setup_bot_commands(application):
    await application.bot.set_my_commands(BOT_COMMANDS)


if __name__ == '__main__':
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables.")
    else:
        from datetime import time as dt_time, timezone, timedelta
        IST = timezone(timedelta(hours=5, minutes=30))

        application = ApplicationBuilder().token(TOKEN).post_init(setup_bot_commands).build()

        application.add_handler(CommandHandler('start', start))
        application.add_handler(CommandHandler('help', help_command))
        application.add_handler(CommandHandler('language', language))
        application.add_handler(CommandHandler('summary', summary))
        application.add_handler(CommandHandler('insights', insights))
        application.add_handler(CommandHandler('subscriptions', subscriptions))
        application.add_handler(CommandHandler('setbudget', setbudget))
        application.add_handler(CommandHandler('export', export_expenses))
        application.add_handler(CommandHandler('stats', stats))
        application.add_handler(CommandHandler('reminders', reminders))
        application.add_handler(CommandHandler('suggestions', suggestions))
        application.add_handler(CommandHandler('dashboard', dashboard))
        application.add_handler(CommandHandler('balance', balance))
        application.add_handler(CommandHandler('wallet', wallet_cmd))
        application.add_handler(CommandHandler('transfer', transfer_cmd))
        application.add_handler(CommandHandler('lend', lend))
        application.add_handler(CommandHandler('borrow', borrow))
        application.add_handler(CommandHandler('debts', debts))
        application.add_handler(CommandHandler('report', report_pdf))
        application.add_handler(CommandHandler('treesummary', treesummary))
        application.add_handler(CallbackQueryHandler(language_callback, pattern=r"^lang:"))
        application.add_handler(MessageHandler(filters.TEXT, handle_text))
        application.add_handler(MessageHandler(filters.VOICE, handle_voice))
        application.add_handler(MessageHandler(filters.PHOTO, handle_image))

        application.job_queue.run_daily(
            send_evening_reminders,
            time=dt_time(hour=21, minute=0, tzinfo=IST),
            name="evening_reminders",
        )

        logger.info("Bot started...")
        application.run_polling()
