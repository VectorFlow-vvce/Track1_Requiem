from openai import OpenAI
import os
import json
import base64
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("LLM_MODEL", "gpt-4o")


def normalize_expense_items(raw_details):
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
            items.append({"amount": amount, "description": description})
    return items


def extract_expense_items(text):
    prompt = f"""
    Extract every separate expense from this text: "{text}"
    If the text contains multiple expenses, return one item per expense.
    If one total amount covers multiple items together, return it as one expense.
    If the text is in Malayalam, Tamil, Telugu, Kannada, Hindi, or mixed English,
    translate each description to concise English.
    Return ONLY JSON in this exact shape:
    {{
      "expenses": [
        {{"amount": 356, "description": "Rapido travel from Yelahanka to Madiwala"}},
        {{"amount": 554, "description": "Uber ride"}}
      ]
    }}
    """
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={ "type": "json_object" }
        )
        return normalize_expense_items(json.loads(response.choices[0].message.content))
    except Exception as e:
        print(f"Error extracting expense items: {e}")
        return []


def extract_expense_details(text):
    prompt = f"""
    Extract the amount and a short description of the expense from this text: "{text}"
    If the text is in Malayalam, Tamil, Telugu, or Kannada, translate the description to English.
    Return ONLY a JSON object with keys "amount" (number) and "description" (string).
    Example: {{"amount": 500, "description": "Pizza dinner"}}
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
                        {"type": "text", "text": "Extract the total amount and a brief summary of items from this receipt. Return ONLY JSON: {\"amount\": float, \"description\": string}"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ],
                }
            ],
            response_format={ "type": "json_object" }
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"Error extracting from receipt: {e}")
        return {"amount": 0, "description": "Receipt extraction failed"}

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
        prompt = f"""
        Write a concise financial summary for a Telegram expense bot user.
        Keep it under 900 characters. Use INR/Rs wording.
        Include:
        1. One sentence on overall spending.
        2. The biggest category or risk.
        3. One practical next action.

        Total spend: {summary_stats.get("total_spend")}
        Transactions: {summary_stats.get("transaction_count")}
        Average spend: {summary_stats.get("average_spend")}
        Top category: {summary_stats.get("top_category")}
        Category totals:
        {category_lines}
        Recent expenses:
        {recent_lines}
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
