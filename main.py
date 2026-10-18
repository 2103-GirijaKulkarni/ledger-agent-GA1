import json
import re
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

with open("data.json", encoding="utf-8") as f:
    DATA = json.load(f)

ORDERS = DATA["orders"]


class Question(BaseModel):
    question: str


MONTHS = {
    "january": "01",
    "february": "02",
    "march": "03",
    "april": "04",
    "may": "05",
    "june": "06",
    "july": "07",
    "august": "08",
    "september": "09",
    "october": "10",
    "november": "11",
    "december": "12",
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
        "currency": None,
    }

    # What kind of answer is needed?
    if (
        "which product" in text
        or "top product" in text
        or "best-selling product" in text
        or "highest revenue product" in text
    ):
        q["metric"] = "top_product"

    elif "refund" in text:
        q["metric"] = "refunds"

    elif "how many orders" in text or "number of orders" in text:
        q["metric"] = "orders"

    elif (
        "how many products" in text
        or "number of products" in text
        or "distinct products" in text
    ):
        q["metric"] = "products"

    elif (
        "how many customers" in text
        or "number of customers" in text
        or "distinct customers" in text
    ):
        q["metric"] = "customers"

    else:
        q["metric"] = "revenue"

    # Exact date, e.g. 2026-03-05
    date_match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if date_match:
        q["date"] = date_match.group(0)

    # Month and year, e.g. March 2026
    month_match = re.search(
        r"(" + "|".join(MONTHS.keys()) + r")\s+(\d{4})",
        text,
    )
    if month_match:
        month_name = month_match.group(1)
        year = month_match.group(2)
        q["month"] = f"{year}-{MONTHS[month_name]}"

    # Region, e.g. North region
    region_match = re.search(
        r"\b(north|south|east|west)\b(?:\s+region)?",
        text,
    )
    if region_match:
        q["region"] = region_match.group(1).title()

    # Product name, matched against actual product names in the data
    products = sorted(
        {order["product"] for order in ORDERS},
        key=len,
        reverse=True,
    )

    for product in products:
        if product.lower() in text:
            q["product"] = product
            break

    # Customer ID, e.g. C1183
    customer_match = re.search(r"\b([A-Za-z]*\d{3,})\b", text)
    if customer_match:
        possible_customer = customer_match.group(1)

        if any(order["customer"] == possible_customer for order in ORDERS):
            q["customer"] = possible_customer

    # Currency filter
    currency_match = re.search(r"\b(USD|EUR|INR)\b", text.upper())
    if currency_match:
        q["currency"] = currency_match.group(1)

    # "in USD" means convert to USD, not filter to USD orders
    if "in usd" in text:
        q["currency"] = None

    return q


def matches(order, q):
    if q["month"] and order["month"] != q["month"]:
        return False

    if q["date"] and order["date"] != q["date"]:
        return False

    if q["region"] and order["region"].lower() != q["region"].lower():
        return False

    if q["product"] and order["product"].lower() != q["product"].lower():
        return False

    if q["customer"] and order["customer"].lower() != q["customer"].lower():
        return False

    if q["currency"] and order["currency"].lower() != q["currency"].lower():
        return False

    return True


def calculate(q):
    rows = [order for order in ORDERS if matches(order, q)]

    if q["metric"] == "revenue":
        return round(
            sum(
                order["usd_amount"]
                for order in rows
                if order["status"] == "paid"
            ),
            2,
        )

    if q["metric"] == "refunds":
        return round(
            sum(
                order["usd_amount"]
                for order in rows
                if order["status"] == "refunded"
            ),
            2,
        )

    if q["metric"] == "orders":
        return len(rows)

    if q["metric"] == "products":
        return len({order["product"] for order in rows})

    if q["metric"] == "customers":
        return len({order["customer"] for order in rows})

    if q["metric"] == "top_product":
        revenue_by_product = {}

        for order in rows:
            if order["status"] == "paid":
                product = order["product"]
                revenue_by_product[product] = (
                    revenue_by_product.get(product, 0)
                    + order["usd_amount"]
                )

        if not revenue_by_product:
            return ""

        return max(revenue_by_product, key=revenue_by_product.get)

    return 0


@app.post("/")
async def answer(question: Question):
    q = parse_question(question.question)
    return {"answer": calculate(q)}