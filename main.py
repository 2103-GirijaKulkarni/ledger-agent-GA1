import json, re
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

with open("data.json", encoding="utf-8") as f:
    DATA = json.load(f)

ORDERS = DATA["orders"]

class Question(BaseModel):
    question: str

MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12"
}

def parse_question(text: str):
    text = text.lower()

    q = {
        "metric": "revenue",
        "month": None,
        "date": None,
        "region": None,
        "product": None,
        "customer": None,
        "currency": None
    }

    # Metric
    if "refund" in text:
        q["metric"] = "refunds"
    elif "how many orders" in text or "number of orders" in text:
        q["metric"] = "orders"
    elif "how many products" in text or "number of products" in text or "distinct products" in text:
        q["metric"] = "products"
    elif "how many customers" in text or "number of customers" in text or "distinct customers" in text:
        q["metric"] = "customers"
    else:
        q["metric"] = "revenue"

    # Exact date: March 5, 2026 / 5 March 2026 / 2026-03-05
    date_match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if date_match:
        q["date"] = date_match.group(0)

    # Month and year: March 2026
    month_match = re.search(
        r"(" + "|".join(MONTHS) + r")\s+(\d{4})", text
    )
    if month_match:
        q["month"] = f"{month_match.group(2)}-{MONTHS[month_match.group(1)]}"

    # Region
    region_match = re.search(r"\b(north|south|east|west)\b(?:\s+region)?", text)
    if region_match:
        q["region"] = region_match.group(1).title()

    # Product: find a product name present in the data
    for product in sorted({o["product"] for o in ORDERS}, key=len, reverse=True):
        if product.lower() in text:
            q["product"] = product
            break

    # Customer: C1183, customer C1183, etc.
    customer_match = re.search(r"\b([A-Za-z]*\d{3,})\b", text)
    if customer_match:
        possible = customer_match.group(1)
        if any(o["customer"] == possible for o in ORDERS):
            q["customer"] = possible

    # Currency
    currency_match = re.search(r"\b(USD|EUR|INR)\b", text.upper())
    if currency_match:
        q["currency"] = currency_match.group(1)

    # "in USD" means convert to USD, so do not filter by currency.
    if "in usd" in text:
        q["currency"] = None

    return q

def matches(o, q):
    if q["month"] and o["month"] != q["month"]:
        return False
    if q["date"] and o["date"] != q["date"]:
        return False
    if q["region"] and o["region"].lower() != q["region"].lower():
        return False
    if q["product"] and o["product"].lower() != q["product"].lower():
        return False
    if q["customer"] and o["customer"].lower() != q["customer"].lower():
        return False
    if q["currency"] and o["currency"].lower() != q["currency"].lower():
        return False
    return True

def calculate(q):
    rows = [o for o in ORDERS if matches(o, q)]

    if q["metric"] == "revenue":
        return round(sum(o["usd_amount"] for o in rows if o["status"] == "paid"), 2)

    if q["metric"] == "refunds":
        return round(sum(o["usd_amount"] for o in rows if o["status"] == "refunded"), 2)

    if q["metric"] == "orders":
        return len(rows)

    if q["metric"] == "products":
        return len({o["product"] for o in rows})

    if q["metric"] == "customers":
        return len({o["customer"] for o in rows})

    return 0

@app.post("/")
async def answer(question: Question):
    q = parse_question(question.question)
    return {"answer": calculate(q)}