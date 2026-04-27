from openai import OpenAI
import os
import json
import base64
import time
import requests
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("LLM_MODEL", "gpt-4o")
BASE_CURRENCY = os.getenv("BASE_CURRENCY", "INR").upper()
FX_API_URL = os.getenv("FX_API_URL", "https://open.er-api.com/v6/latest/{currency}")
FX_CACHE_SECONDS = int(os.getenv("FX_CACHE_SECONDS", "21600"))
RECEIPT_CONFIDENCE_THRESHOLD = float(os.getenv("RECEIPT_CONFIDENCE_THRESHOLD", "0.55"))
_FX_CACHE = {}

_CURRENCY_ALIASES = {
    "₹": "INR",
    "RS": "INR",
    "RUPEE": "INR",
    "RUPEES": "INR",
    "INR": "INR",
    "$": "USD",
    "DOLLAR": "USD",
    "DOLLARS": "USD",
    "USD": "USD",
    "AED": "AED",
    "DIRHAM": "AED",
    "DIRHAMS": "AED",
    "د.إ": "AED",
    "€": "EUR",
    "EURO": "EUR",
    "EUROS": "EUR",
    "EUR": "EUR",
    "£": "GBP",
    "POUND": "GBP",
    "POUNDS": "GBP",
    "GBP": "GBP",
}


def normalize_currency(currency):
    if not currency:
        return BASE_CURRENCY
    return _CURRENCY_ALIASES.get(str(currency).strip().upper(), str(currency).strip().upper())


def get_inr_rate(currency):
    currency = normalize_currency(currency)
    if currency == BASE_CURRENCY:
        return 1.0

    cached = _FX_CACHE.get(currency)
    if cached and time.time() - cached["fetched_at"] < FX_CACHE_SECONDS:
        return cached["rate"]

    response = requests.get(FX_API_URL.format(currency=currency), timeout=5)
    response.raise_for_status()
    payload = response.json()
    rate = float(payload.get("rates", {}).get(BASE_CURRENCY, 0) or 0)
    if rate <= 0:
        raise ValueError(f"No {BASE_CURRENCY} exchange rate for {currency}")

    _FX_CACHE[currency] = {"rate": rate, "fetched_at": time.time()}
    return rate


def convert_to_inr(amount, currency, rates=None):
    currency = normalize_currency(currency)
    amount = float(amount or 0)
    if currency == BASE_CURRENCY:
        return {"amount": amount}

    rate = float((rates or {}).get(currency) or get_inr_rate(currency))
    converted = round(amount * rate, 2)
    return {
        "amount": converted,
        "currency": BASE_CURRENCY,
        "original_amount": amount,
        "original_currency": currency,
        "fx_rate": rate,
    }


def _split_people(item):
    split = item.get("split")
    if isinstance(split, dict):
        people = split.get("people") or split.get("count") or split.get("total_people")
    else:
        people = item.get("split_people") or item.get("people")
    try:
        people = int(people or 0)
    except (TypeError, ValueError):
        return None
    return people if people > 1 else None


def normalize_expense_items(raw_details, rates=None):
    if not raw_details:
        return []

    raw_items = raw_details.get("expenses") if isinstance(raw_details, dict) else raw_details
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    elif not isinstance(raw_items, list):
        raw_items = [raw_details]

    items = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        try:
            amount = float(item.get("amount", 0) or 0)
        except (TypeError, ValueError):
            amount = 0
        description = str(item.get("description") or "").strip()
        if amount > 0 and description:
            normalized = {"amount": amount, "description": description}

            people = _split_people(item)
            if people:
                normalized["original_amount"] = amount
                normalized["split_people"] = people
                normalized["amount"] = round(amount / people, 2)
                normalized["status"] = item.get("status") or "settled"
                normalized["reimbursable_amount"] = round(amount - normalized["amount"], 2)

            currency = normalize_currency(item.get("currency") or item.get("original_currency"))
            converted = convert_to_inr(normalized["amount"], currency, rates=rates)
            normalized.update(converted)

            if item.get("confidence") is not None:
                normalized["confidence"] = item.get("confidence")
            if item.get("needs_clarification") is not None:
                normalized["needs_clarification"] = bool(item.get("needs_clarification"))
            items.append(normalized)
    return items


def extract_expense_items(text):
    prompt = f"""
    Extract every separate expense from this text: "{text}"
    If the text contains multiple expenses, return one item per expense.
    If one total amount covers multiple items together, return it as one expense.
    If a bill was split, keep the paid total in amount and set split.people to the
    total number of people sharing it, including the user.
    Detect currency words or symbols. Use INR unless the user clearly says another
    currency such as USD, AED, EUR, or GBP.
    If the text is in Malayalam, Tamil, Telugu, Kannada, Hindi, or mixed English,
    translate each description to concise English before categorization.

    Regional mixed-language and slang examples:
    - "Food-inu 200 spent aayi" means 200 INR on food (Malayalam).
    - "Njan 350 petrol inu koduthu" means 350 INR on petrol (Malayalam).
    - "Chaaya kudichu 40 roopa" means 40 INR on tea (Malayalam).
    - "Groceries-nu 1500 aayi" means 1500 INR on groceries (Malayalam).
    - "Ola-yil 180 koduthu" means 180 INR on Ola cab (Malayalam).
    - "Swiggy-yil 300 order cheythu" means 300 INR on food delivery (Malayalam slang).
    - "Recharge-inu 199 poyi" means 199 INR on phone recharge (Malayalam slang).
    - "Sapadu ku 180 spend panninen" means 180 INR on meals (Tamil).
    - "Auto ku 120 kuduthen" means 120 INR on auto transport (Tamil).
    - "Zomato la 250 order potten" means 250 INR on food delivery (Tamil slang).
    - "Petrol potta 500" means 500 INR on petrol (Tamil slang).
    - "Aaj chai aur snacks pe 90 kharch hua" means 90 INR on tea and snacks (Hindi).
    - "Bhai 200 udaa diye chai pe" means 200 INR on tea (Hindi slang).
    - "Ola pe 150 laga" means 150 INR on Ola cab (Hindi slang).
    - "Oota ge 200 kharch aaythu" means 200 INR on food (Kannada).
    - "Auto ge 80 kotte" means 80 INR on auto transport (Kannada).
    - "Swiggy alli 350 order maadde" means 350 INR on food delivery (Kannada slang).
    - "Chai ki 50 icha" means 50 INR on tea (Telugu slang).
    - "Petrol ki 600 poyindi" means 600 INR on petrol (Telugu slang).
    - "Dinner 3000 split with 4 people" means amount 3000 and split.people 4.
    - "Spent 50 dollars on lunch" means amount 50 and currency USD.

    Return ONLY JSON in this exact shape:
    {{
      "detected_language": "ml",
      "expenses": [
        {{"amount": 356, "currency": "INR", "description": "Rapido travel from Yelahanka to Madiwala"}},
        {{"amount": 3000, "currency": "INR", "description": "Dinner with friends", "split": {{"people": 4}}}},
        {{"amount": 50, "currency": "USD", "description": "Lunch"}}
      ]
    }}
    detected_language must be one of: en, hi, ml, ta, te, kn.
    If the text mixes a regional language with English, return the regional language code.
    """
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={ "type": "json_object" }
        )
        parsed = json.loads(response.choices[0].message.content)
        detected_lang = parsed.get("detected_language", "en") if isinstance(parsed, dict) else "en"
        return normalize_expense_items(parsed), detected_lang
    except Exception as e:
        print(f"Error extracting expense items: {e}")
        return [], "en"


def extract_expense_details(text):
    prompt = f"""
    Extract the amount and a short description of the expense from this text: "{text}"
    If a bill was split, keep the paid total in amount and set split.people to the
    total number of people sharing it, including the user.
    Detect currency words or symbols. Use INR unless another currency is clear.
    If the text is in Malayalam, Tamil, Telugu, Kannada, Hindi, or mixed English,
    translate the description to English.
    Examples:
    - "Food-inu 200 spent aayi" -> {{"amount": 200, "currency": "INR", "description": "Food"}}
    - "Sapadu ku 180 spend panninen" -> {{"amount": 180, "currency": "INR", "description": "Meal"}}
    - "Dinner 3000 split with 4 people" -> {{"amount": 3000, "currency": "INR", "description": "Dinner with friends", "split": {{"people": 4}}}}
    - "Spent 50 dollars on lunch" -> {{"amount": 50, "currency": "USD", "description": "Lunch"}}
    Return ONLY a JSON object with keys "amount" (number), "currency" (string), and "description" (string). Include "split" only when applicable.
    """
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={ "type": "json_object" }
        )
        details = json.loads(response.choices[0].message.content)
        items = normalize_expense_items(details)
        return items[0] if items else {"amount": 0, "description": text}
    except Exception as e:
        print(f"Error extracting expense details: {e}")
        return {"amount": 0, "description": text}

def transcribe_voice(file_path):
    try:
        with open(file_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file
            )
            return transcript.text
    except Exception as e:
        print(f"Error transcribing voice: {e}")
        return ""

def extract_from_receipt(image_path):
    try:
        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')
        
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract the total amount and a brief summary of items from this receipt. If the image is blurry, handwritten, cropped, or the total is uncertain, set needs_clarification to true and confidence below 0.55. Return ONLY JSON: {\"amount\": float, \"currency\": \"INR\", \"description\": string, \"confidence\": float, \"needs_clarification\": boolean}"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ],
                }
            ],
            response_format={ "type": "json_object" }
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"Error extracting from receipt: {e}")
        return {"amount": 0, "description": "Receipt extraction failed", "confidence": 0, "needs_clarification": True}


def receipt_needs_clarification(details):
    if not isinstance(details, dict):
        return True
    try:
        amount = float(details.get("amount", 0) or 0)
    except (TypeError, ValueError):
        amount = 0
    try:
        confidence = float(details.get("confidence", 1) if details.get("confidence") is not None else 1)
    except (TypeError, ValueError):
        confidence = 0
    return amount <= 0 or bool(details.get("needs_clarification")) or confidence < RECEIPT_CONFIDENCE_THRESHOLD

def generate_insights(expenses):
    try:
        expense_summary = "\n".join([f"- {e['amount']} on {e['category']} ({e['description']})" for e in expenses[-10:]])
        prompt = f"Analyze these recent expenses and give 3 short, professional financial tips. Be specific to the spending pattern if possible:\n{expense_summary}"
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error generating insights: {e}")
        return "Could not generate insights at this time."


def generate_suggestions(category_stats):
    """Generate personalized spending suggestions per category using GPT."""
    try:
        lines = []
        for cat, info in category_stats.items():
            cur = info["current"]
            prev = info["previous"]
            change = f"+{info['change']:.0f}%" if info["change"] > 0 else f"{info['change']:.0f}%"
            lines.append(f"- {cat}: ₹{cur:,.0f} this month, ₹{prev:,.0f} last month ({change}), {info['txn_count']} transactions")

        prompt = (
            "You are a personal finance advisor for an Indian user. "
            "Based on their real spending data below, give one specific, actionable suggestion per category. "
            "Use real numbers from the data. Be concise (1-2 lines per category). "
            "Use emojis. If a category is well-controlled, say so. "
            "If spending increased, suggest a concrete way to cut back with estimated savings. "
            "End with one overall tip.\n\n"
            f"Category spending (current month vs last month):\n" + "\n".join(lines)
        )
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error generating suggestions: {e}")
        return "Could not generate suggestions at this time."


def generate_summary_insight(summary_stats):
    try:
        category_lines = "\n".join(
            f"- {category}: {amount}"
            for category, amount in list(summary_stats.get("category_totals", {}).items())[:6]
        )
        recent_lines = "\n".join(
            f"- {expense.get('amount')} on {expense.get('category')} ({expense.get('description')})"
            for expense in summary_stats.get("recent_expenses", [])[:5]
        )
        forecast = summary_stats.get("forecast", {})
        forecast_lines = "\n".join(
            f"- {item.get('date')}: {item.get('amount')}"
            for item in forecast.get("daily", [])[:7]
        )
        prompt = f"""
        Write a concise financial summary for a Telegram expense bot user.
        Keep it under 900 characters. Use INR/Rs wording.
        Include:
        1. One sentence on overall spending.
        2. The biggest category or risk.
        3. A brief next-7-days forecast if available.
        4. One practical next action.

        Total spend: {summary_stats.get("total_spend")}
        Transactions: {summary_stats.get("transaction_count")}
        Average spend: {summary_stats.get("average_spend")}
        Top category: {summary_stats.get("top_category")}
        Category totals:
        {category_lines}
        Recent expenses:
        {recent_lines}
        Forecast method: {forecast.get("method")}
        Forecast next 7 days total: {forecast.get("next_7_days_total")}
        Forecast average daily spend: {forecast.get("average_daily_forecast")}
        Forecast daily:
        {forecast_lines}
        """
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error generating summary insight: {e}")
        return (
            f"You spent Rs {summary_stats.get('total_spend', 0):,.0f} across "
            f"{summary_stats.get('transaction_count', 0)} transactions. "
            f"Your top category is {summary_stats.get('top_category', 'None')}. "
            "Review the largest category first for quick savings."
        )


LANG_NAMES = {
    "en": "English", "hi": "Hindi", "ml": "Malayalam",
    "ta": "Tamil", "te": "Telugu", "kn": "Kannada",
}


def translate_response(text, lang):
    """Translate a bot response to the user's language. Passthrough for English."""
    if not text or lang == "en":
        return text
    lang_name = LANG_NAMES.get(lang, "English")
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": (
                f"Translate the following Telegram bot message to {lang_name}. "
                "Keep emojis, numbers, currency symbols (₹), markdown formatting (**bold**, etc), "
                "and command names (like /summary) exactly as-is. Only translate the natural language parts. "
                "Return ONLY the translated text, nothing else.\n\n"
                f"{text}"
            )}],
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return text


def detect_language(text):
    """Quick detect of language from user text. Returns lang code or None."""
    if not text:
        return None
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": (
                "Detect the language of this text. Return ONLY one of these codes: "
                "en, hi, ml, ta, te, kn. If unsure or mixed with English, return the "
                "non-English language code. If purely English, return en.\n\n"
                f'"{text}"'
            )}],
        )
        code = response.choices[0].message.content.strip().lower()[:2]
        return code if code in LANG_NAMES else None
    except Exception:
        return None


def classify_intent(text):
    """Use LLM to classify user text into a bot command intent or expense."""
    if not text:
        return None
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": (
                "You are an intent classifier for a Telegram expense-tracking bot.\n"
                "Classify the following user message into exactly ONE intent.\n\n"
                "Possible intents:\n"
                "- summary: user wants to see spending summary, chart, report, overview\n"
                "- insights: user wants financial advice, tips, analysis\n"
                "- help: user asks what the bot can do, how to use it\n"
                "- start: user wants to restart or begin fresh\n"
                "- category_query: user asks how much they spent on a specific category (extract the category)\n"
                "- delete_last: user wants to undo/remove/delete their last expense\n"
                "- subscriptions: user asks about recurring expenses\n"
                "- setbudget: user wants to set a spending budget/limit for a category (extract category and amount)\n"
                "- export: user wants to download/export their data\n"
                "- stats: user asks about streaks, badges, achievements\n"
                "- reminders: user wants to toggle reminders on/off\n"
                "- dashboard: user wants to open the web dashboard\n"
                "- language: user wants to change the bot language\n"
                "- suggestions: user wants spending suggestions or tips per category\n"
                "- expense: user is logging a new expense (contains an amount or describes spending)\n"
                "- unknown: message is unclear or unrelated\n\n"
                "Return ONLY JSON: {\"intent\": \"<intent>\", \"category\": \"<category if category_query or setbudget else null>\", \"amount\": <number if setbudget else null>}\n\n"
                f"Message: \"{text}\""
            )}],
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
        intent = result.get("intent", "unknown")
        if intent in ("expense", "unknown"):
            return None
        out = {"command": intent}
        if intent == "category_query" and result.get("category"):
            out["category"] = result["category"]
        if intent == "setbudget":
            if result.get("category"):
                out["category"] = result["category"]
            if result.get("amount") is not None:
                out["amount"] = result["amount"]
        return out
    except Exception as e:
        print(f"Error classifying intent: {e}")
        return None


def parse_voice_command(text):
    """Parse voice commands for queries — supports English and regional languages."""
    if not text:
        return None
    
    normalized = text.lower().strip()
    
    patterns = {
        'category_query': [
            # English / slang
            'how much on', 'how much did i spend on', 'spend on', 'spent on', 'spending on',
            'how much went to', 'total on',
            # Hindi / slang
            'kitna on', 'kitna gaya', 'kitna laga',
            # Malayalam / slang
            'ethrayayi', 'entha chelavu', 'ethre poyi', 'ethre aayi',
            # Tamil / slang
            'evvalavu', 'entha selavu', 'evlo pochu', 'evlo aachi',
            # Telugu / slang
            'entha kharchu', 'entha ayyindi', 'entha poyindi',
            # Kannada / slang
            'eshtu kharchu', 'eshtu aaythu', 'eshtu hogidhe',
        ],
        'summary': [
            # English / slang
            'show spending', 'show my spending', 'spending summary', 'how much spent',
            'total spending', 'show summary', 'where did my money go',
            'how much did i blow', 'money gone where',
            # Hindi / slang
            'kitna kharch', 'kharch dikhao', 'kharcha dikha', 'spending dikhao',
            'paisa kidhar gaya', 'kitna udaya', 'kitna laga total',
            # Malayalam / slang
            'chelavu kanikku', 'chelavu kaanikku', 'ethrayayi chelavu',
            'chelav kanikk', 'chelavu entha', 'paisa evde poyi',
            'kaash engott poyi', 'total chelavu entha',
            # Tamil / slang
            'chelavu kaattu', 'chelavu ennavaa', 'enna chelavu', 'selavu kaattu',
            'selavu enna', 'panam enga pochu', 'motta selavu',
            # Telugu / slang
            'kharchu chupinchu', 'kharchu entha', 'dabbu ekkadiki poyindi',
            'total kharchu entha',
            # Kannada / slang
            'kharchu toorisu', 'kharchu eshtu', 'duddu elli hogidhe',
            'total kharchu eshtu',
        ],
        'insights': [
            # English / slang
            'give insights', 'financial advice', 'spending advice', 'tips', 'suggestions',
            'where am i wasting', 'am i spending too much',
            # Hindi / slang
            'salah do', 'paisa tips', 'kya zyada kharcha ho raha',
            'paisa bacha kaise', 'kahan zyada ud raha',
            # Malayalam / slang
            'upadesha thaa', 'nirdeshangal', 'paisa upadesha',
            'evde aanu kooduthal chelavu', 'paisa enga save cheyyam',
            # Tamil / slang
            'yoosana', 'enga athigam selavu', 'panam mikkam pannuvathu eppadi',
            # Telugu / slang
            'salaha ivvu', 'ekkada ekkuva kharchu', 'dabbu aadaa cheyyali',
            # Kannada / slang
            'salaha', 'salaha kodi', 'elli jasthi kharchu', 'duddu ulisi hege',
        ],
        'delete_last': [
            # English / slang
            'delete last', 'remove last', 'undo last', 'cancel last', 'last delete',
            'take that back', 'wrong entry',
            # Hindi / slang
            'aakhri hatao', 'galat entry', 'woh wala hatao', 'last wala delete',
            # Malayalam / slang
            'last maayu', 'kadha neekkku', 'avasaanam maayu',
            'athu thettaanu', 'last entry maayu',
            # Tamil / slang
            'kadaisiya neekkku', 'thappu entry', 'last entry delete pannu',
            # Telugu / slang
            'last teeseyyi', 'tappu entry', 'adi cancel cheyyi',
            # Kannada / slang
            'last delete maadu', 'tappu entry', 'adu cancel maadu',
        ],
        'help': [
            # English / slang
            'what can you do', 'help me', 'commands', 'how to use',
            'what all can you do', 'how does this work',
            # Hindi / slang
            'kya kar sakte', 'kaise use kare', 'kya kya hota hai',
            # Malayalam / slang
            'sahayam', 'entha cheyyan kazhiyum', 'engane upayogikkum',
            'entha okke cheyyan pattum', 'engane use cheyyum',
            # Tamil / slang
            'enna seyyum', 'eppadi use pannuvathu', 'enna ellam seyyum',
            # Telugu / slang
            'help cheyyi', 'emi cheyagalavu', 'ela vadali',
            # Kannada / slang
            'sahaya', 'enu maadbahudu', 'hege use maadodu',
        ],
    }
    
    # Words that mean "expense/spending" in regional languages — not real categories
    _generic_expense_words = {
        'chelavu', 'chelav', 'selavu', 'kharchu', 'kharcha', 'kharch', 'spending',
        'panam', 'paisa', 'dabbu', 'duddu', 'kaash', 'money',
    }

    for command, keywords in patterns.items():
        if any(keyword in normalized for keyword in keywords):
            if command == 'category_query':
                for keyword in keywords:
                    if keyword in normalized:
                        category_part = normalized.split(keyword)[-1].strip().rstrip('?')
                        if category_part and category_part not in _generic_expense_words:
                            return {'command': 'category_query', 'category': category_part}
                # No real category found after keyword — treat as summary
                return {'command': 'summary'}
            return {'command': command}
    
    return None
