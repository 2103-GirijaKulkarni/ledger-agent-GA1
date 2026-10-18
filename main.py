import re
import json
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

with open("data.json", encoding="utf-8") as f:
    raw_data = json.load(f)

orders = pd.DataFrame(raw_data["orders"])
rates = raw_data["rates"]

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


@app.get("/")
async def health_check():
    return {
        "status": "ok",
        "total_orders": len(orders)
    }


def parse_question(question: str):
    text = question.lower()

    parsed = {
        "metric": "revenue",
        "month": None,
        "date": None,
        "region": None,
        "product": None,
        "customer": None,
        "currency": None,
    }

    if (
        "which product" in text
        or "top product" in text
        or "best selling product" in text
        or "best-selling product" in text
        or "highest revenue product" in text
    ):
        parsed["metric"] = "top_product"

    elif "refund" in text:
        parsed["metric"] = "refunds"

    elif "how many orders" in text or "number of orders" in text:
        parsed["metric"] = "orders"

    elif (
        "how many products" in text
        or "number of products" in text
        or "distinct products" in text
    ):
        parsed["metric"] = "products"

    elif (
        "how many customers" in text
        or "number of customers" in text
        or "distinct customers" in text
    ):
        parsed["metric"] = "customers"

    else:
        parsed["metric"] = "revenue"

    date_match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if date_match:
        parsed["date"] = date_match.group(0)

    month_match = re.search(
        r"(" + "|".join(MONTHS.keys()) + r")\s+(\d{4})",
        text
    )

    if month_match:
        month_name = month_match.group(1)
        year = month_match.group(2)
        parsed["month"] = f"{year}-{MONTHS[month_name]}"

    region_match = re.search(
        r"\b(north|south|east|west|central)\b(?:\s+region)?",
        text
    )

    if region_match:
        parsed["region"] = region_match.group(1).title()

    product_names = sorted(
        orders["product"].dropna().unique().tolist(),
        key=len,
        reverse=True
    )

    for product in product_names:
        if product.lower() in text:
            parsed["product"] = product
            break

    customer_match = re.search(r"\b([A-Za-z]*\d{3,})\b", text)

    if customer_match:
        possible_customer = customer_match.group(1)

        if possible_customer in orders["customer"].unique():
            parsed["customer"] = possible_customer

    currency_match = re.search(r"\b(USD|EUR|INR)\b", text.upper())

    if currency_match:
        parsed["currency"] = currency_match.group(1)

    if "in usd" in text:
        parsed["currency"] = None

    return parsed


def filter_orders(parsed):
    filtered = orders

    if parsed["month"]:
        filtered = filtered[filtered["month"] == parsed["month"]]

    if parsed["date"]:
        filtered = filtered[filtered["date"] == parsed["date"]]

    if parsed["region"]:
        filtered = filtered[
            filtered["region"].str.lower() == parsed["region"].lower()
        ]

    if parsed["product"]:
        filtered = filtered[
            filtered["product"].str.lower() == parsed["product"].lower()
        ]

    if parsed["customer"]:
        filtered = filtered[
            filtered["customer"].str.lower() == parsed["customer"].lower()
        ]

    if parsed["currency"]:
        filtered = filtered[
            filtered["currency"].str.lower() == parsed["currency"].lower()
        ]

    return filtered


def calculate_answer(parsed):
    filtered = filter_orders(parsed)
    metric = parsed["metric"]

    if metric == "revenue":
        paid = filtered[filtered["status"] == "paid"]
        return round(float(paid["usd_amount"].sum()), 2)

    if metric == "refunds":
        refunded = filtered[filtered["status"] == "refunded"]
        return round(float(refunded["usd_amount"].sum()), 2)

    if metric == "orders":
        return int(len(filtered))

    if metric == "products":
        return int(filtered["product"].nunique())

    if metric == "customers":
        return int(filtered["customer"].nunique())

    if metric == "top_product":
        paid = filtered[filtered["status"] == "paid"]

        if paid.empty:
            return ""

        revenue_by_product = (
            paid.groupby("product")["usd_amount"]
            .sum()
            .sort_values(ascending=False)
        )

        return revenue_by_product.index[0]

    return 0


@app.post("/")
async def answer_question(request: Request):
    try:
        body = await request.json()
        question = body.get("question", "")

        if not question:
            return JSONResponse(
                status_code=400,
                content={"error": "Missing 'question' in request body"}
            )

        parsed = parse_question(question)
        answer = calculate_answer(parsed)

        return {"answer": answer}

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )