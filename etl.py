import argparse
import pandas as pd
import sqlite3
from datetime import datetime
import os

DB_PATH = os.getenv("DB_PATH", "db/orders.db")

FX_RATES = {
    "USD": 1.0,
    "EUR": 1.1,
}

def parse_date(x):
    if pd.isna(x):
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(x), fmt).date().isoformat()
        except ValueError:
            continue
    return None

def transform(df: pd.DataFrame) -> pd.DataFrame:
    # 1) Drop rows with missing order_id or customer_id
    df = df.dropna(subset=["order_id", "customer_id"])

    # 2) Fix dates
    df["order_date"] = df["order_date"].apply(parse_date)
    df = df.dropna(subset=["order_date"])

    # 3) Fix amounts
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)

    # 4) Fix currency
    df["currency"] = df["currency"].fillna("USD")

    # 5) Convert to USD
    def to_usd(row):
        rate = FX_RATES.get(row["currency"], 1.0)
        return row["amount"] * rate

    df["amount_usd"] = df.apply(to_usd, axis=1)

    # 6) Keep only clean columns
    return df[["order_id", "customer_id", "order_date", "amount_usd"]]

def load_to_sqlite(df: pd.DataFrame, db_path: str = DB_PATH):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    df.to_sql("orders", conn, if_exists="replace", index=False)
    conn.close()

def cmd_load(csv_path: str):
    df = pd.read_csv(csv_path)
    df_clean = transform(df)
    load_to_sqlite(df_clean)
    print(f"Loaded {len(df_clean)} rows into SQLite at {DB_PATH}")

def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    load_parser = subparsers.add_parser("load")
    load_parser.add_argument("csv_path")

    args = parser.parse_args()

    if args.command == "load":
        cmd_load(args.csv_path)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
