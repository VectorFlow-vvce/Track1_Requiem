import logging
import os
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder, CallbackQueryHandler, ContextTypes,
    CommandHandler, MessageHandler, filters,
)
from dotenv import load_dotenv

from ai_processor import (
    extract_expense_details,
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
    get_user_language,
    set_user_language,
    build_category_comparison,
    SUPPORTED_LANGUAGES,
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
    BotCommand("insights", "Get AI financial insights"),
    BotCommand("subscriptions", "View recurring expenses"),
    BotCommand("setbudget", "Set category budget"),
    BotCommand("export", "Export expenses to CSV"),
    BotCommand("stats", "View your streaks and badges"),
    BotCommand("reminders", "Toggle smart reminders on/off"),
    BotCommand("suggestions", "Get spending suggestions per category"),
    BotCommand("dashboard", "Open the dashboard link"),
]

COMMAND_ALIASES = {
    "start": ("start", "restart"),
    "help": ("help", "commands", "menu", "what can you do", "how to use"),
    "language": ("language", "lang", "bhasha", "bhasa"),
    "summary": ("summary", "summarise", "summarize", "report", "snapshot", "spending summary"),
    "insights": ("insights", "insight", "advice", "tips", "financial insights"),
    "subscriptions": ("subscriptions", "recurring", "recurring expenses", "subs"),
    "setbudget": ("setbudget", "set budget", "budget"),
    "export": ("export", "download", "csv", "excel"),
    "stats": ("stats", "statistics", "streak", "badges", "achievements"),
    "reminders": ("reminders", "reminder", "remind me", "toggle reminders"),
    "suggestions": ("suggestions", "suggestion", "suggest", "spending suggestions"),
    "dashboard": ("dashboard", "command center", "open dashboard", "web dashboard"),
}


# ── helpers ──────────────────────────────────────────────────────────

def _lang(update):
    return get_user_language(update.effective_user.id)


async def _reply(update, text, lang=None, **kwargs):
    """Send a translated reply. Markdown parse_mode by default."""
    lang = lang or _lang(update)
    translated = translate_response(text, lang)
    await update.message.reply_text(translated, parse_mode='Markdown', **kwargs)


def _format_amount(amount):
    return f"{amount:,.0f}" if float(amount).is_integer() else f"{amount:,.2f}"


def resolve_text_command(text):
    normalized = " ".join((text or "").strip().lower().split())
    if not normalized:
        return None
    if normalized.startswith("/"):
        command = normalized[1:].split()[0].split("@")[0]
        return command if command in COMMAND_ALIASES else None
    for command, aliases in COMMAND_ALIASES.items():
        if normalized in aliases:
            return command
        if command != "start" and any(normalized.startswith(f"{alias} ") for alias in aliases):
            return command
        if command in {"summary", "insights", "dashboard", "help"} and any(alias in normalized for alias in aliases):
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
        metadata = {
            key: item[key]
            for key in (
                "currency", "original_amount", "original_currency", "fx_rate",
                "split_people", "reimbursable_amount", "status", "confidence",
            )
            if key in item
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


def build_logged_message(logged, prefix="✅ Logged"):
    if len(logged) == 1:
        item = logged[0]
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

    lines = [f"✅ Logged {len(logged)} expenses:"]
    for item in logged:
        detail = f"• ₹{_format_amount(item['amount'])} - **{item['category']}** - {item['description']}"
        original = _format_original_amount(item)
        if item.get("original_currency"):
            detail += f" (converted from {original})"
        if item.get("split_people"):
            detail += f" (split {item['split_people']} ways)"
        lines.append(detail)
    return "\n".join(lines)


# ── command handlers ─────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = _lang(update)
    await _reply(update,
        f"👋 Hello {user.first_name}! Welcome to **FineHance Omni**.\n\n"
        "I am your frictionless financial assistant. You can:\n"
        "🎙️ Send a voice note (e.g., 'Spent 500 on dinner')\n"
        "👁️ Send a photo of a receipt\n"
        "💬 Type your expense\n"
        "🌍 Use /language to change my language\n\n"
        "Try saying: 'I spent 300 on pizza today'",
        lang,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _lang(update)
    await _reply(update,
        "**FineHance Omni Commands**\n\n"
        "/summary - Spending summary and chart\n"
        "/insights - AI financial insights\n"
        "/subscriptions - View recurring expenses\n"
        "/setbudget <category> <amount> - Set budget alerts\n"
        "/export - Download expenses as CSV\n"
        "/stats - View streaks and badges\n"
        "/reminders - Toggle smart reminders on/off\n"
        "/suggestions - Get spending suggestions per category\n"
        "/language - Change bot language\n"
        "/dashboard - Dashboard link\n"
        "/help - Show this menu\n\n"
        "You can also type the same words as normal messages, or just send expenses like:\n"
        "Spent 3000 on dinner, split with 4 people\n"
        "Food-inu 200 spent aayi\n"
        "Spent 50 dollars on lunch\n\n"
        "Or ask questions like:\n"
        "Show me my spending this week\n"
        "How much did I spend on food?",
        lang,
    )


async def language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [InlineKeyboardButton(name, callback_data=f"lang:{code}")]
        for code, name in SUPPORTED_LANGUAGES.items()
    ]
    await update.message.reply_text(
        "🌍 **Choose your language / भाषा चुनें / ഭാഷ തിരഞ്ഞെടുക്കുക**",
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


async def _dispatch_intent(voice_cmd, update, context):
    """Dispatch a classified intent dict to the right handler. Returns True if handled."""
    if not voice_cmd:
        return False
    cmd = voice_cmd['command']
    handler = {
        'start': start, 'help': help_command, 'language': language,
        'summary': summary, 'insights': insights,
        'subscriptions': subscriptions, 'export': export_expenses,
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
    return False


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    lang = _lang(update)

    command = resolve_text_command(text)
    if command:
        handlers = {
            "start": start, "help": help_command, "language": language,
            "summary": summary, "insights": insights,
            "subscriptions": subscriptions, "setbudget": setbudget,
            "export": export_expenses, "stats": stats,
            "reminders": reminders, "suggestions": suggestions, "dashboard": dashboard,
        }
        await handlers[command](update, context)
        return

    # Fast pattern match, then LLM fallback
    voice_cmd = parse_voice_command(text) or classify_intent(text)
    if await _dispatch_intent(voice_cmd, update, context):
        return

    await context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action="typing")

    items, detected = extract_expense_items(text)
    # Auto-set language from expense text
    if detected and detected != "en" and lang == "en":
        set_user_language(user_id, detected)
        lang = detected
    logged = log_expense_items(user_id, items, source="text")
    if logged:
        response = build_logged_message(logged)
        for item in logged:
            alert = check_budget_exceeded(user_id, item['category'])
            if alert:
                response += f"\n\n⚠️ **Budget Alert!**\n{alert['category']}: ₹{alert['spent']:,.0f} / ₹{alert['limit']:,.0f} ({alert['percentage']:.0f}%)"
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
    if not text:
        await _reply(update, "❌ Sorry, I couldn't understand the audio.", lang)
        return

    # Check if it's a voice command first
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
        await update.message.reply_text(f"🧠 **AI Summary**\n\n{advice}", parse_mode='Markdown')
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
    await update.message.reply_text(f"🧠 **AI Financial Insights**\n\n{advice}", parse_mode='Markdown')


async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(update,
        "🖥️ **Your Command Center**\n"
        "View your full financial analytics here:\n"
        "🔗 [Open Dashboard](http://localhost:8501)\n\n"
        "*(Note: Ensure the dashboard is running locally during the demo)*",
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
    await update.message.reply_text(f"💡 **Spending Suggestions**\n\n{advice}", parse_mode='Markdown')


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


async def delete_last_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = _lang(update)
    expenses = load_expenses()
    user_key = str(user_id)

    if user_key not in expenses or not expenses[user_key]:
        await _reply(update, "📭 No expenses to delete!", lang)
        return

    last_expense = expenses[user_key].pop()

    import json
    data_file = os.path.join(os.path.dirname(__file__), '../data/expenses.json')
    with open(data_file, 'w') as f:
        json.dump(expenses, f, indent=4)

    await _reply(update,
        f"✅ Deleted: ₹{last_expense['amount']:,.0f} - {last_expense['description']}",
        lang,
    )


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
