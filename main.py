import re
import json
import sqlite3
import pandas as pd
import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

RATES_URL = "https://exam.sanand.workers.dev/questionData?email=23f3000791%40ds.study.iitm.ac.in&quizSign=ArAKYc0tGuV%2FcWgPbHBBzgjgaHiONGk4aUY%2BCbO7nZlmePIKsrj6k%2FZV1Y6qY%2FY2FF1WlNZg45hiBA5HBix25%2BP2q5KdW0CB%2BEUl54ONHdVYNSLiJQn85LU4YHaNcC8ayx9clcmT1%2BgjYGenEVC0ICdVTisnSQBUFTPXRhSPnHJ5%2BGe5%2BfjPHDUNpahYnKSCUNwi5XAVefOd%2FTFK6d0E9Gbtp%2FqRR0WEoNrChIU5ts2zaxjbwyM0Xi0BHJmPnGn2LU0Dg1OS9Sts4tbup%2F1m9kQDC2oYy%2FLCkjqLmH%2BEcSRwst2ft93VJLrUuEtXKCXwizcCPPX89PsERXBRZraEow%3D%3D&questionId=q-ledger-agent-server&path=%2Frates"

EXPORT_URL = "https://exam.sanand.workers.dev/questionData?email=23f3000791%40ds.study.iitm.ac.in&quizSign=ArAKYc0tGuV%2FcWgPbHBBzgjgaHiONGk4aUY%2BCbO7nZlmePIKsrj6k%2FZV1Y6qY%2FY2FF1WlNZg45hiBA5HBix25%2BP2q5KdW0CB%2BEUl54ONHdVYNSLiJQn85LU4YHaNcC8ayx9clcmT1%2BgjYGenEVC0ICdVTisnSQBUFTPXRhSPnHJ5%2BGe5%2BfjPHDUNpahYnKSCUNwi5XAVefOd%2FTFK6d0E9Gbtp%2FqRR0WEoNrChIU5ts2zaxjbwyM0Xi0BHJmPnGn2LU0Dg1OS9Sts4tbup%2F1m9kQDC2oYy%2FLCkjqLmH%2BEcSRwst2ft93VJLrUuEtXKCXwizcCPPX89PsERXBRZraEow%3D%3D&questionId=q-ledger-agent-server&path=%2Fexport"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

db_conn = sqlite3.connect(":memory:", check_same_thread=False)

MONTH_MAP = {
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

REGIONS = ["North", "South", "East", "West", "Central"]


def init_database():
    with httpx.Client(timeout=30.0) as client:
        print("Fetching currency rates from /rates...")

        rates_response = client.get(RATES_URL, headers=HEADERS)
        rates_response.raise_for_status()

        usd_rates = rates_response.json()["usd_per_unit"]
        print("Currency rates:", usd_rates)

        print("Fetching order ledger from /export...")

        export_response = client.get(EXPORT_URL, headers=HEADERS)
        export_response.raise_for_status()

        raw_lines = export_response.text.strip().splitlines()
        rows = [json.loads(line) for line in raw_lines if line.strip()]

        print(f"Raw records downloaded: {len(rows)}")

    df = pd.DataFrame(rows)

    df["created_at_utc"] = pd.to_datetime(
        df["created_at"], format="ISO8601", utc=True
    )

    df["updated_at_utc"] = pd.to_datetime(
        df["updated_at"], format="ISO8601", utc=True
    )

    # Keep only the latest version of each order ID.
    df = (
        df.sort_values("updated_at_utc", kind="mergesort")
        .drop_duplicates(subset=["id"], keep="last")
        .copy()
    )

    print(f"Current orders after deduplication: {len(df)}")

    ist_created = df["created_at_utc"].dt.tz_convert("Asia/Kolkata")

    df["created_date"] = ist_created.dt.strftime("%Y-%m-%d")
    df["created_month"] = ist_created.dt.strftime("%Y-%m")
    df["created_year"] = ist_created.dt.year

    df["rate_to_usd"] = df["currency"].map(usd_rates)
    df["amount_usd"] = df["amount"] * df["rate_to_usd"]

    df_sql = df.drop(columns=["created_at_utc", "updated_at_utc"])
    df_sql.to_sql("orders", db_conn, index=False, if_exists="replace")

    print("In-memory SQLite database ready.")


init_database()


def parse_question_to_sql(question: str):
    q_low = question.lower()
    conditions = []

    # Status: refunds, voids, or paid revenue
    if re.search(r"\brefund(ed|s)?\b", q_low):
        conditions.append("status = 'refunded'")
    elif re.search(r"\b(void|voided|cancel|cancelled)\b", q_low):
        conditions.append("status = 'void'")
    else:
        conditions.append("status = 'paid'")

    # Region
    for region in REGIONS:
        if re.search(rf"\b{region.lower()}\b", q_low):
            conditions.append(f"region = '{region}'")
            break

    # Product: match against actual product names in the database
    cursor = db_conn.cursor()
    cursor.execute("SELECT DISTINCT product FROM orders")
    products = [row[0] for row in cursor.fetchall()]

    for product in sorted(products, key=len, reverse=True):
        pattern = rf"\b{re.escape(product.lower())}s?\b"

        if re.search(pattern, q_low):
            conditions.append(f"product = '{product}'")
            break

    # Customer ID, e.g. C1183
    customer_match = re.search(r"\b([A-Za-z]*\d{3,})\b", q_low)

    if customer_match:
        possible_customer = customer_match.group(1).upper()

        cursor.execute(
            "SELECT 1 FROM orders WHERE customer = ? LIMIT 1",
            (possible_customer,),
        )

        if cursor.fetchone():
            conditions.append(f"customer = '{possible_customer}'")

    # Exact date
    date_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", q_low)

    if date_match:
        conditions.append(f"created_date = '{date_match.group(1)}'")

    # Month and year
    year_match = re.search(r"\b(20\d{2})\b", q_low)
    year = year_match.group(1) if year_match else None

    month_number = None

    for month_name, month_value in MONTH_MAP.items():
        if re.search(rf"\b{month_name}\b", q_low):
            month_number = month_value
            break

    if month_number and year:
        conditions.append(f"created_month = '{year}-{month_number}'")
    elif month_number:
        conditions.append(f"created_month LIKE '____-{month_number}'")
    elif year:
        conditions.append(f"created_year = {year}")

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    # Top product
    if any(
        phrase in q_low
        for phrase in [
            "which product",
            "what product",
            "top product",
            "top-selling product",
            "best-selling product",
            "product earned the most",
        ]
    ):
        sql = f"""
            SELECT product
            FROM orders
            WHERE {where_clause}
            GROUP BY product
            ORDER BY SUM(amount_usd) DESC
            LIMIT 1
        """
        return sql, "string"

    # Top customer
    if any(
        phrase in q_low
        for phrase in [
            "which customer",
            "what customer",
            "top customer",
            "customer spent the most",
        ]
    ):
        sql = f"""
            SELECT customer
            FROM orders
            WHERE {where_clause}
            GROUP BY customer
            ORDER BY SUM(amount_usd) DESC
            LIMIT 1
        """
        return sql, "string"

    # Top region
    if any(
        phrase in q_low
        for phrase in [
            "which region",
            "what region",
            "top region",
            "region earned the most",
        ]
    ):
        sql = f"""
            SELECT region
            FROM orders
            WHERE {where_clause}
            GROUP BY region
            ORDER BY SUM(amount_usd) DESC
            LIMIT 1
        """
        return sql, "string"

    # Distinct customers
    if any(
        phrase in q_low
        for phrase in [
            "distinct customer",
            "different customer",
            "unique customer",
            "how many customer",
        ]
    ):
        sql = f"""
            SELECT COUNT(DISTINCT customer)
            FROM orders
            WHERE {where_clause}
        """
        return sql, "int"

    # Average order value
    if "average" in q_low:
        sql = f"""
            SELECT ROUND(COALESCE(AVG(amount_usd), 0), 2)
            FROM orders
            WHERE {where_clause}
        """
        return sql, "money"

    # Number of orders
    if any(
        phrase in q_low
        for phrase in [
            "how many orders",
            "number of orders",
            "count the",
        ]
    ):
        sql = f"""
            SELECT COUNT(*)
            FROM orders
            WHERE {where_clause}
        """
        return sql, "int"

    # Total units
    if any(
        phrase in q_low
        for phrase in [
            "how many units",
            "total quantity",
            "total units",
        ]
    ):
        sql = f"""
            SELECT COALESCE(SUM(qty), 0)
            FROM orders
            WHERE {where_clause}
        """
        return sql, "int"

    # Default: revenue / earnings / sales
    sql = f"""
        SELECT ROUND(COALESCE(SUM(amount_usd), 0), 2)
        FROM orders
        WHERE {where_clause}
    """
    return sql, "money"


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def health_check():
    cursor = db_conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM orders")
    count = cursor.fetchone()[0]

    return {
        "status": "ok",
        "orders": count,
    }


@app.post("/")
async def answer_question(request: Request):
    body = await request.json()
    question = body.get("question", "")

    print(f"Incoming question: {question}")

    sql_query, answer_type = parse_question_to_sql(question)
    print(f"SQL: {sql_query}")

    cursor = db_conn.cursor()
    cursor.execute(sql_query)
    row = cursor.fetchone()

    value = row[0] if row and row[0] is not None else 0

    if answer_type == "string":
        result = str(value)
    elif answer_type == "int":
        result = int(value)
    else:
        result = round(float(value), 2)

    print(f"Answer: {result}")

    return {"answer": result}
