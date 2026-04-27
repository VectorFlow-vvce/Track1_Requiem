import os
import re
import logging
import math
from collections import Counter

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

MERCHANT_DATABASE = {
    "swiggy": "Food Delivery",
    "zomato": "Food Delivery",
    "ubereats": "Food Delivery",
    "uber eats": "Food Delivery",
    "deliveroo": "Food Delivery",
    "doordash": "Food Delivery",
    "starbucks": "Coffee & Beverages",
    "cafe coffee day": "Coffee & Beverages",
    "ccd": "Coffee & Beverages",
    "third wave": "Coffee & Beverages",
    "blue tokai": "Coffee & Beverages",
    "mcdonalds": "Fast Food",
    "mcdonald": "Fast Food",
    "kfc": "Fast Food",
    "burger king": "Fast Food",
    "subway": "Fast Food",
    "dominos": "Fast Food",
    "pizza hut": "Fast Food",
    "dmart": "Groceries",
    "bigbasket": "Groceries",
    "zepto": "Groceries",
    "blinkit": "Groceries",
    "instamart": "Groceries",
    "more supermarket": "Groceries",
    "reliance fresh": "Groceries",
    "shell": "Gas & Fuel",
    "bpcl": "Gas & Fuel",
    "hpcl": "Gas & Fuel",
    "ioc": "Gas & Fuel",
    "indian oil": "Gas & Fuel",
    "essar": "Gas & Fuel",
    "uber": "Transportation",
    "ola": "Transportation",
    "rapido": "Transportation",
    "namma yatri": "Transportation",
    "nammayatri": "Transportation",
    "ksrtc": "Transportation",
    "bmtc": "Transportation",
    "bmrtc": "Transportation",
    "irctc": "Travel",
    "makemytrip": "Travel",
    "goibibo": "Travel",
    "cleartrip": "Travel",
    "oyo": "Travel",
    "airbnb": "Travel",
    "netflix": "Subscriptions",
    "spotify": "Subscriptions",
    "amazon prime": "Subscriptions",
    "prime video": "Subscriptions",
    "hotstar": "Subscriptions",
    "disney": "Subscriptions",
    "youtube premium": "Subscriptions",
    "apple music": "Subscriptions",
    "amazon": "Shopping & Retail",
    "flipkart": "Shopping & Retail",
    "myntra": "Shopping & Retail",
    "ajio": "Shopping & Retail",
    "meesho": "Shopping & Retail",
    "apollo": "Healthcare",
    "netmeds": "Healthcare",
    "pharmeasy": "Healthcare",
    "1mg": "Healthcare",
    "cult fit": "Healthcare",
    "cultfit": "Healthcare",
    "airtel": "Bills & Utilities",
    "jio": "Bills & Utilities",
    "vi": "Bills & Utilities",
    "vodafone": "Bills & Utilities",
    "bsnl": "Bills & Utilities",
    "bescom": "Bills & Utilities",
    "kseb": "Bills & Utilities",
    "tneb": "Bills & Utilities",
    "zerodha": "Transfers",
    "groww": "Transfers",
    "upstox": "Transfers",
    "paytm": "Transfers",
    "phonepe": "Transfers",
    "gpay": "Transfers",
    "google pay": "Transfers",
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
            "mandi",
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
    ("Childcare", ("daycare", "childcare", "baby", "kid", "kids", "school bus", "creche")),
    ("Convenience", ("convenience store", "seven eleven", "7 eleven", "chips", "water bottle", "snacks")),
    ("Entertainment", ("movie", "cinema", "popcorn", "concert", "game", "bowling", "ticket")),
    ("Giving", ("donation", "donated", "charity", "temple", "church", "mosque", "fundraiser")),
    ("Housing", ("rent", "mortgage", "maintenance", "apartment", "house")),
    ("Insurance", ("insurance", "premium")),
    ("Cash & ATM", ("atm", "cash withdrawal", "withdrawal")),
    ("Transfers", ("transfer", "sent to", "upi", "bank transfer")),
    ("Income", ("salary", "income", "received", "credited", "bonus", "freelance", "reimbursement", "cashback", "refund")),
)

TFIDF_CATEGORY_DOCUMENTS = {
    "Coffee & Beverages": (
        "coffee tea chai chaya kaapi juice smoothie beverage cafe starbucks cold coffee iced tea",
        "filter coffee tea shop cafe drink beverage pazham pori lime juice",
    ),
    "Food Delivery": (
        "swiggy zomato ubereats delivery deliveroo doordash online food app",
        "takeaway delivered delivery restaurant app cloud kitchen",
    ),
    "Fast Food": (
        "burger pizza kfc mcdonald subway fries taco sandwich fast food",
        "quick burger pizza fries fried chicken",
    ),
    "Restaurants": (
        "mandi dinner lunch breakfast meal food restaurant bill dine in mess",
        "biryani mandi dosa dosha parotta porotta beef chicken fish meals hotel oonu sapadu saapadu",
        "family restaurant cafe dining thali meals shawarma alfaham biriyani meals mess",
    ),
    "Groceries": (
        "grocery groceries supermarket vegetable fruit milk bread rice provisions dmart zepto bigbasket",
        "mart supermarket store monthly groceries vegetables eggs atta dal oil provisions",
    ),
    "Childcare": (
        "daycare creche babysitter nanny childcare kid kids child baby preschool",
        "school bus child fees daycare fees baby supplies diapers",
    ),
    "Convenience": (
        "convenience store seven eleven 7 eleven corner shop chips water bottle snacks",
        "quick snacks soda biscuits small purchase mini mart",
    ),
    "Entertainment": (
        "movie cinema theatre popcorn concert game bowling arcade event tickets",
        "netflix party amusement park show sports match entertainment",
    ),
    "Giving": (
        "donation donated charity temple church mosque fundraiser gift offering",
        "ngo relief fund religious contribution giving",
    ),
    "Gas & Fuel": (
        "fuel petrol diesel gas shell bpcl hpcl ioc indian oil refill",
        "vehicle car bike petrol pump fuel station diesel refill",
    ),
    "Transportation": (
        "uber ola taxi auto rickshaw metro bus train cab parking namma yatri",
        "ride travel commute auto cab taxi",
    ),
    "Travel": (
        "flight hotel airbnb booking trip travel airport airline resort vacation",
        "railway ticket flight ticket stay hotel",
    ),
    "Subscriptions": (
        "subscription netflix spotify prime hotstar youtube premium saas recurring",
        "monthly plan renewal subscription",
    ),
    "Shopping & Retail": (
        "amazon flipkart myntra shopping clothes shirt shoes retail purchase order",
        "mall apparel electronics accessories headphones gadgets",
    ),
    "Healthcare": (
        "doctor hospital medicine pharmacy clinic medical health consultation netmeds apollo",
        "chemist tablets scan lab cult fit gym fitness physiotherapy",
    ),
    "Education": (
        "school college course tuition book exam education class",
        "fees course learning training",
    ),
    "Bills & Utilities": (
        "electricity water bill internet wifi mobile bill recharge utility airtel jio vi bsnl",
        "broadband bill postpaid prepaid utility payment bescom kseb tneb",
    ),
    "Housing": (
        "rent mortgage maintenance apartment house flat society",
        "home rent maintenance housing",
    ),
    "Insurance": (
        "insurance premium policy renewal",
        "health insurance car insurance bike insurance",
    ),
    "Cash & ATM": (
        "atm cash withdrawal withdraw money",
        "cash from atm",
    ),
    "Transfers": (
        "transfer sent to upi bank transfer paid friend mutual fund sip",
        "money transfer upi payment zerodha groww sip investment",
    ),
    "Income": (
        "salary income received credited bonus reimbursement freelance payment cashback refund",
        "paycheck credited income freelance client payout",
    ),
}

TFIDF_MIN_SCORE = 0.18
TFIDF_MIN_MARGIN = 0.04
_TFIDF_INDEX = None

HIGH_SIGNAL_TFIDF_CATEGORIES = (
    ("Food Delivery", ("swiggy", "zomato", "ubereats", "deliveroo", "doordash", "delivery", "delivered")),
    ("Groceries", ("dmart", "bigbasket", "zepto", "milk", "bread", "eggs", "provisions", "grocery", "groceries")),
    ("Subscriptions", ("netflix", "spotify", "hotstar", "prime video", "youtube premium", "saas", "subscription")),
    ("Shopping & Retail", ("amazon", "flipkart", "myntra", "ajio", "headphones", "electronics", "clothes")),
    ("Childcare", ("daycare", "creche", "babysitter", "nanny", "diaper", "diapers")),
    ("Convenience", ("seven eleven", "7 eleven", "chips", "water bottle", "corner shop", "mini mart")),
    ("Entertainment", ("movie", "cinema", "popcorn", "concert", "bowling", "arcade")),
    ("Giving", ("donated", "donation", "charity", "temple", "church", "mosque", "fundraiser")),
    ("Gas & Fuel", ("petrol", "diesel", "fuel", "refill", "indian oil", "shell", "bpcl", "hpcl")),
    ("Healthcare", ("doctor", "medicine", "medical", "pharmacy", "netmeds", "apollo", "cult fit", "gym")),
    ("Bills & Utilities", ("airtel", "jio", "vi prepaid", "bsnl", "bescom", "kseb", "tneb", "electricity", "recharge")),
    ("Transportation", ("rapido", "ksrtc", "bmrtc", "metro", "bus", "auto", "namma yatri", "uber", "ola")),
    ("Travel", ("irctc", "flight", "airport", "hotel booking", "oyo", "airbnb")),
    ("Transfers", ("zerodha", "groww", "mutual fund", "sip", "upi", "bank transfer")),
    ("Income", ("salary", "freelance", "paycheck", "credited", "bonus", "reimbursement", "cashback", "refund")),
    ("Coffee & Beverages", ("chaya", "chai", "kaapi", "coffee", "juice", "pazham pori")),
    ("Restaurants", ("sapadu", "saapadu", "oonu", "mess", "mandi", "biryani", "parotta", "porotta", "hotel")),
)


def _headers():
    if not HF_TOKEN:
        return {}
    return {"Authorization": f"Bearer {HF_TOKEN}"}


def _tokenize(text):
    return re.findall(r"[a-z0-9]+", str(text or "").casefold())


def _build_tfidf_index():
    global _TFIDF_INDEX

    if _TFIDF_INDEX is not None:
        return _TFIDF_INDEX

    docs = []
    for category, examples in TFIDF_CATEGORY_DOCUMENTS.items():
        for example in examples:
            docs.append((category, Counter(_tokenize(example))))

    doc_count = len(docs)
    document_frequency = Counter()
    for _category, counts in docs:
        document_frequency.update(counts.keys())

    idf = {
        token: math.log((1 + doc_count) / (1 + frequency)) + 1
        for token, frequency in document_frequency.items()
    }

    vectors = []
    for category, counts in docs:
        vector = {token: count * idf[token] for token, count in counts.items()}
        norm = math.sqrt(sum(weight * weight for weight in vector.values())) or 1.0
        vectors.append((category, vector, norm))

    _TFIDF_INDEX = (idf, vectors)
    return _TFIDF_INDEX


def get_tfidf_category(text):
    normalized = f" {str(text or '').casefold()} "
    for category, signals in HIGH_SIGNAL_TFIDF_CATEGORIES:
        if any(f" {signal} " in normalized or signal in normalized for signal in signals):
            return category

    tokens = _tokenize(text)
    if not tokens:
        return "Other"

    idf, vectors = _build_tfidf_index()
    query_counts = Counter(token for token in tokens if token in idf)
    if not query_counts:
        return "Other"

    query_vector = {token: count * idf[token] for token, count in query_counts.items()}
    query_norm = math.sqrt(sum(weight * weight for weight in query_vector.values())) or 1.0

    category_scores = Counter()
    for category, doc_vector, doc_norm in vectors:
        dot_product = sum(weight * doc_vector.get(token, 0) for token, weight in query_vector.items())
        score = dot_product / (query_norm * doc_norm)
        category_scores[category] = max(category_scores[category], score)

    if not category_scores:
        return "Other"

    ranked = category_scores.most_common(2)
    top_category, top_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    if top_score >= TFIDF_MIN_SCORE and top_score - runner_up >= TFIDF_MIN_MARGIN:
        return top_category
    return "Other"


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


def extract_merchant(text):
    """Extract merchant name and return category if found in database."""
    if not text:
        return None
    
    normalized = str(text).lower().strip()
    
    # Check for exact merchant matches
    for merchant, category in MERCHANT_DATABASE.items():
        if merchant in normalized:
            return category
    
    return None


def get_category(text):
    global HF_UNAVAILABLE

    if not text:
        return "Other"
    
    # First check merchant database (highest priority)
    merchant_category = extract_merchant(text)
    if merchant_category:
        return merchant_category

    tfidf_category = get_tfidf_category(text)
    if tfidf_category != "Other":
        return tfidf_category

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
