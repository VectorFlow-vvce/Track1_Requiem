import logging
import os
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from dotenv import load_dotenv

from ai_processor import extract_expense_details
from categorizer import get_category
from utils import save_expense

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Hello {user.first_name}! Welcome to **FineHance Omni**.\n\n"
        "I am your frictionless financial assistant. You can:\n"
        "🎙️ Send a voice note (e.g., 'Spent 500 on dinner')\n"
        "👁️ Send a photo of a receipt\n"
        "💬 Type your expense\n\n"
        "Try saying: 'I spent 300 on pizza today'"
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text.startswith('/'):
        return

    # Indicate typing
    await context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action="typing")
    
    details = extract_expense_details(text)
    if details.get('amount', 0) > 0:
        category = get_category(details['description'])
        save_expense(update.effective_user.id, details['amount'], category, details['description'], source="text")
        await update.message.reply_text(f"✅ Logged ₹{details['amount']} under **{category}**\n📝 *{details['description']}*")
    else:
        await update.message.reply_text("🤔 I couldn't catch the amount. Try saying something like 'Spent 500 on coffee'.")

if __name__ == '__main__':
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables.")
    else:
        application = ApplicationBuilder().token(TOKEN).build()
        
        application.add_handler(CommandHandler('start', start))
        application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
        
        logger.info("Bot started...")
        application.run_polling()
