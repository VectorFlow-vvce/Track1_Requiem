import logging
import os
import asyncio
import base64
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from dotenv import load_dotenv

from ai_processor import extract_expense_details, extract_expense_items, transcribe_voice, extract_from_receipt, generate_insights, generate_summary_insight
from categorizer import get_category
from utils import save_expense, generate_pie_chart, load_expenses, build_summary_stats

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

def _format_amount(amount):
    return f"{amount:,.0f}" if float(amount).is_integer() else f"{amount:,.2f}"


def log_expense_items(user_id, items, source):
    logged = []
    for item in items:
        amount = item.get("amount", 0)
        description = item.get("description", "")
        if amount <= 0 or not description:
            continue
        category = get_category(description)
        save_expense(user_id, amount, category, description, source=source)
        logged.append({
            "amount": amount,
            "category": category,
            "description": description,
        })
    return logged


def build_logged_message(logged, prefix="✅ Logged"):
    if len(logged) == 1:
        item = logged[0]
        return (
            f"{prefix} ₹{_format_amount(item['amount'])} under **{item['category']}**\n"
            f"📝 *{item['description']}*"
        )

    lines = [f"✅ Logged {len(logged)} expenses:"]
    for item in logged:
        lines.append(
            f"• ₹{_format_amount(item['amount'])} - **{item['category']}** - {item['description']}"
        )
    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Hello {user.first_name}! Welcome to **FineHance Omni**.\n\n"
        "I am your frictionless financial assistant. You can:\n"
        "🎙️ Send a voice note (e.g., 'Spent 500 on dinner')\n"
        "👁️ Send a photo of a receipt\n"
        "💬 Type your expense\n\n"
        "Try saying: 'I spent 300 on pizza today'",
        parse_mode='Markdown'
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text.startswith('/'):
        return

    # Indicate typing
    await context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action="typing")
    
    items = extract_expense_items(text)
    logged = log_expense_items(update.effective_user.id, items, source="text")
    if logged:
        await update.message.reply_text(build_logged_message(logged), parse_mode='Markdown')
    else:
        await update.message.reply_text("🤔 I couldn't catch the amount. Try saying something like 'Spent 500 on coffee'.")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Indicate processing
    await context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action="record_voice")
    
    voice_file = await update.message.voice.get_file()
    os.makedirs("assets", exist_ok=True)
    file_path = f"assets/{update.effective_user.id}_{update.message.message_id}.ogg"
    await voice_file.download_to_drive(file_path)
    
    text = transcribe_voice(file_path)
    if not text:
        await update.message.reply_text("❌ Sorry, I couldn't understand the audio.")
        return

    items = extract_expense_items(text)
    logged = log_expense_items(update.effective_user.id, items, source="voice")
    if logged:
        await update.message.reply_text(
            f"🎙️ Heard: \"{text}\"\n"
            f"{build_logged_message(logged)}",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(f"🎙️ I heard: \"{text}\"\nBut I couldn't find an amount. Try again?")

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Indicate processing
    await context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action="upload_photo")
    
    photo_file = await update.message.photo[-1].get_file()
    os.makedirs("assets", exist_ok=True)
    file_path = f"assets/{update.effective_user.id}_{update.message.message_id}.jpg"
    await photo_file.download_to_drive(file_path)
    
    details = extract_from_receipt(file_path)
    if details.get('amount', 0) > 0:
        category = get_category(details['description'])
        save_expense(update.effective_user.id, details['amount'], category, details['description'], source="image")
        await update.message.reply_text(
            f"👁️ Receipt Scanned!\n"
            f"✅ Logged ₹{details['amount']} under **{category}**\n"
            f"📝 *{details['description']}*",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ I couldn't extract the amount from this receipt. Make sure the total is clear.")

async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action="upload_photo")
    user_id = update.effective_user.id
    expenses = load_expenses().get(str(user_id), [])
    if not expenses:
        await update.message.reply_text("📉 No data yet! Log some expenses first to see your summary.")
        return

    chart_path = generate_pie_chart(update.effective_user.id)
    if chart_path and os.path.exists(chart_path):
        stats = build_summary_stats(expenses)
        advice = generate_summary_insight(stats)
        with open(chart_path, 'rb') as chart_file:
            await update.message.reply_photo(
                photo=chart_file,
                caption="📊 **Your Financial Snapshot**",
                parse_mode='Markdown'
            )
        await update.message.reply_text(f"🧠 **AI Summary**\n\n{advice}", parse_mode='Markdown')
    else:
        await update.message.reply_text("📉 No data yet! Log some expenses first to see your summary.")

async def insights(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    expenses = load_expenses().get(str(user_id), [])
    
    if len(expenses) < 3:
        await update.message.reply_text("📉 I need at least 3 expenses to give you meaningful insights. Keep logging!")
        return

    await context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action="typing")
    
    advice = generate_insights(expenses)
    await update.message.reply_text(f"🧠 **AI Financial Insights**\n\n{advice}", parse_mode='Markdown')

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # In a real app, this would be a hosted URL. For hackathon, we show local/placeholder.
    await update.message.reply_text(
        "🖥️ **Your Command Center**\n"
        "View your full financial analytics here:\n"
        "🔗 [Open Dashboard](http://localhost:8501)\n\n"
        "*(Note: Ensure the dashboard is running locally during the demo)*",
        parse_mode='Markdown'
    )

if __name__ == '__main__':
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables.")
    else:
        application = ApplicationBuilder().token(TOKEN).build()
        
        application.add_handler(CommandHandler('start', start))
        application.add_handler(CommandHandler('summary', summary))
        application.add_handler(CommandHandler('insights', insights))
        application.add_handler(CommandHandler('dashboard', dashboard))
        application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
        application.add_handler(MessageHandler(filters.VOICE, handle_voice))
        application.add_handler(MessageHandler(filters.PHOTO, handle_image))
        
        logger.info("Bot started...")
        application.run_polling()
