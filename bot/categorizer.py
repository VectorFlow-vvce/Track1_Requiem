import os
import re
import logging

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

HF_TOKEN = os.getenv("HF_TOKEN")
MODEL_ID = "CyberKunju/finehance-categorizer-minilm"
LOCAL_MODEL_ENABLED = os.getenv("LOCAL_HF_MODEL_ENABLED", "true").lower() != "false"
HF_URLS = (
    f"https://router.huggingface.co/hf-inference/models/{MODEL_ID}",
    f"https://api-inference.huggingface.co/models/{MODEL_ID}",
)
HF_UNAVAILABLE = False
LOCAL_CLASSIFIER = None
LOCAL_UNAVAILABLE = False

CATEGORIES = {
    "Bills & Utilities",
    "Cash & ATM",
    "Childcare",
    "Coffee & Beverages",
    "Convenience",
    "Education",
    "Entertainment",
    "Fast Food",
    "Food Delivery",
    "Gas & Fuel",
    "Giving",
    "Groceries",
    "Healthcare",
    "Housing",
    "Income",
    "Insurance",
    "Other",
    "Restaurants",
    "Shopping & Retail",
    "Subscriptions",
    "Transfers",
    "Transportation",
    "Travel",
}

KEYWORD_CATEGORIES = (
    ("Coffee & Beverages", ("coffee", "tea", "chai", "juice", "smoothie", "beverage", "cafe", "starbucks")),
    ("Food Delivery", ("swiggy", "zomato", "ubereats", "delivery", "deliveroo", "doordash")),
    ("Fast Food", ("burger", "pizza", "kfc", "mcdonald", "subway", "fries", "taco")),
    (
        "Restaurants",
        (
            "restaurant",
            "dinner",
            "lunch",
            "breakfast",
            "meal",
            "food",
            "biryani",
            "dosa",
            "dosha",
            "parotta",
            "porotta",
            "beef",
            "chicken",
            "fish",
        ),
    ),
    ("Groceries", ("grocery", "groceries", "supermarket", "vegetable", "fruit", "milk", "bread", "rice")),
    ("Gas & Fuel", ("fuel", "petrol", "diesel", "gas", "shell", "bpcl", "hpcl", "ioc", "indian oil")),
    (
        "Transportation",
        (
            "uber",
            "ola",
            "taxi",
            "auto",
            "rickshaw",
            "metro",
            "bus",
            "train",
            "cab",
            "parking",
            "namma yatri",
            "nammayatri",
            "nanma yatri",
        ),
    ),
    ("Travel", ("flight", "hotel", "airbnb", "booking", "trip", "travel", "airport", "airline", "resort")),
    ("Subscriptions", ("subscription", "netflix", "spotify", "prime", "hotstar", "youtube premium", "saas")),
    ("Shopping & Retail", ("amazon", "flipkart", "myntra", "shopping", "clothes", "shirt", "shoes", "retail")),
    ("Healthcare", ("doctor", "hospital", "medicine", "pharmacy", "clinic", "medical", "health")),
    ("Education", ("school", "college", "course", "tuition", "book", "exam", "education")),
    ("Bills & Utilities", ("electricity", "water bill", "internet", "wifi", "mobile bill", "recharge", "utility")),
    ("Housing", ("rent", "mortgage", "maintenance", "apartment", "house")),
    ("Insurance", ("insurance", "premium")),
    ("Cash & ATM", ("atm", "cash withdrawal", "withdrawal")),
    ("Transfers", ("transfer", "sent to", "upi", "bank transfer")),
    ("Income", ("salary", "income", "received", "credited", "bonus")),
)


def _headers():
    if not HF_TOKEN:
        return {}
    return {"Authorization": f"Bearer {HF_TOKEN}"}


def _get_local_classifier():
    global LOCAL_CLASSIFIER, LOCAL_UNAVAILABLE

    if LOCAL_UNAVAILABLE or not LOCAL_MODEL_ENABLED:
        return None

    if LOCAL_CLASSIFIER is not None:
        return LOCAL_CLASSIFIER

    try:
        from transformers import pipeline

        kwargs = {
            "model": MODEL_ID,
            "top_k": None,
            "device": -1,
        }
        if HF_TOKEN:
            kwargs["token"] = HF_TOKEN

        LOCAL_CLASSIFIER = pipeline("text-classification", **kwargs)
        logger.info("Loaded local categorizer model: %s", MODEL_ID)
        return LOCAL_CLASSIFIER
    except Exception as exc:
        LOCAL_UNAVAILABLE = True
        logger.warning("Local categorizer model unavailable: %s", exc)
        return None


def _normalize_label(label):
    if not label:
        return "Other"

    cleaned = str(label).replace("_", " ").replace("-", " ").strip()
    compact = re.sub(r"\s+", " ", cleaned).casefold()

    for category in CATEGORIES:
        if compact == category.casefold():
            return category

    label_aliases = {
        "bills utilities": "Bills & Utilities",
        "coffee beverages": "Coffee & Beverages",
        "fast food": "Fast Food",
        "food delivery": "Food Delivery",
        "gas fuel": "Gas & Fuel",
        "shopping retail": "Shopping & Retail",
        "cash atm": "Cash & ATM",
    }
    return label_aliases.get(compact, "Other")


def _extract_prediction(results):
    if isinstance(results, dict):
        if "label" in results:
            return _normalize_label(results.get("label"))
        if "error" in results:
            return None

    if not isinstance(results, list) or not results:
        return None

    predictions = results[0] if isinstance(results[0], list) else results
    if not predictions or not all(isinstance(item, dict) for item in predictions):
        return None

    top_prediction = max(predictions, key=lambda item: item.get("score", 0))
    return _normalize_label(top_prediction.get("label"))


def get_fallback_category(text):
    normalized = f" {str(text or '').casefold()} "
    for category, keywords in KEYWORD_CATEGORIES:
        if any(f" {keyword} " in normalized or keyword in normalized for keyword in keywords):
            return category
    return "Other"


def get_category(text):
    global HF_UNAVAILABLE

    if not text:
        return "Other"

    local_classifier = _get_local_classifier()
    if local_classifier:
        try:
            category = _extract_prediction(local_classifier(text))
            if category and category != "Other":
                return category
        except Exception as exc:
            logger.warning("Local categorizer inference failed: %s", exc)

    if HF_UNAVAILABLE:
        return get_fallback_category(text)

    payload = {"inputs": text}
    failures = 0
    for url in HF_URLS:
        try:
            response = requests.post(url, headers=_headers(), json=payload, timeout=20)
            if response.status_code == 200:
                category = _extract_prediction(response.json())
                if category and category != "Other":
                    return category
                failures += 1
            else:
                failures += 1
                logger.warning("HF API error at %s: %s - %s", url, response.status_code, response.text[:300])
        except Exception as exc:
            failures += 1
            logger.warning("Error calling HF categorizer at %s: %s", url, exc)

    if failures == len(HF_URLS):
        HF_UNAVAILABLE = True

    return get_fallback_category(text)
