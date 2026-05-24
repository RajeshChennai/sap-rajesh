import os
import sqlite3
import logging
from typing import Optional, List

import numpy as np
from sentence_transformers import SentenceTransformer
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from llama_cpp import Llama
from huggingface_hub import hf_hub_download


# -----------------------------
# Logging
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("orders_service")


# -----------------------------
# DB setup
# -----------------------------
DB_PATH = os.getenv("DB_PATH", "db/orders.db")


def get_conn():
    return sqlite3.connect(DB_PATH)


# -----------------------------
# LLM setup (TinyLlama)
# -----------------------------
model_path = hf_hub_download(
    repo_id="TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
    filename="tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
)

llm = Llama(
    model_path=model_path,
    n_ctx=4096,
    n_threads=8,
    n_gpu_layers=0,
    temperature=0.1,
)

SYSTEM_PROMPT = """
You are an expert SQL generator. Convert natural language questions into valid SQLite SQL.

Database schema:
orders(
    order_id TEXT,
    customer_id TEXT,
    order_date TEXT,
    amount_usd REAL
)

Rules:
- Return ONLY a SQL query.
- SQL MUST start with SELECT.
- No markdown, no backticks, no commentary.
- If the question cannot be answered from this schema, respond with: QUERY_NOT_SUPPORTED
"""


# -----------------------------
# Semantic Search Globals
# -----------------------------
embedding_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

orders_cache: list[dict] = []
orders_embeddings: np.ndarray | None = None


# -----------------------------
# Models
# -----------------------------
class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    natural_language_answer: str
    sql_used: str
    rows: list


# -----------------------------
# Semantic Index Builder
# -----------------------------
def build_semantic_index():
    """
    Load all orders from DB, convert each to a short text string,
    embed them, and store embeddings in memory.
    """
    global orders_cache, orders_embeddings

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT order_id, customer_id, order_date, amount_usd FROM orders")
    rows = cur.fetchall()
    conn.close()

    orders_cache = []
    texts = []

    for r in rows:
        order = {
            "order_id": r[0],
            "customer_id": r[1],
            "order_date": r[2],
            "amount_usd": float(r[3]),
        }
        orders_cache.append(order)

        text = f"customer {order['customer_id']}, ${order['amount_usd']} USD, {order['order_date']}"
        texts.append(text)

    if not texts:
        orders_embeddings = None
        return

    embeddings = embedding_model.encode(texts, normalize_embeddings=True)
    orders_embeddings = np.array(embeddings, dtype=np.float32)

    logger.info(f"Semantic index built with {len(orders_cache)} orders.")


# -----------------------------
# Semantic Search Function
# -----------------------------
def semantic_search(query: str, top_k: int = 5) -> list[dict]:
    if orders_embeddings is None or len(orders_cache) == 0:
        return []

    query_emb = embedding_model.encode([query], normalize_embeddings=True)
    query_vec = query_emb[0].astype(np.float32)

    # Cosine similarity = dot product because vectors are normalized
    scores = orders_embeddings @ query_vec

    top_k = min(top_k, len(orders_cache))
    top_indices = np.argsort(-scores)[:top_k]

    results = []
    for idx in top_indices:
        order = orders_cache[idx]
        results.append({
            "order_id": order["order_id"],
            "customer_id": order["customer_id"],
            "amount_usd": order["amount_usd"],
            "order_date": order["order_date"],
            "score": float(scores[idx]),
        })

    return results


# -----------------------------
# Helper: call LLM
# -----------------------------
def call_llm(question: str, error: Optional[str] = None) -> str:
    if error:
        user_prompt = f"Question: {question}\nPrevious SQL error: {error}\nFix the SQL."
    else:
        user_prompt = f"Question: {question}"

    full_prompt = f"<s>[INST]{SYSTEM_PROMPT}\n{user_prompt}[/INST]"
    logger.info(f"LLM prompt: {full_prompt}")

    output = llm(
        full_prompt,
        max_tokens=200,
        temperature=0.1,
    )

    text = output["choices"][0]["text"].strip()
    token_count = output.get("usage", {}).get("total_tokens", None)

    logger.info(f"Generated SQL: {text}")
    logger.info(f"Token count: {token_count}")

    return text


# -----------------------------
# Helper: build NL answer
# -----------------------------
def build_answer(question: str, sql: str, rows: list) -> str:
    if not rows:
        return f"I executed `{sql}` but it returned no rows."

    return f"I executed `{sql}` and found {len(rows)} row(s)."


# -----------------------------
# FastAPI app
# -----------------------------
app = FastAPI(title="Orders Service")

# Build semantic index at startup
build_semantic_index()


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


# -----------------------------
# Part 4b: Semantic Search Endpoint
# -----------------------------
@app.get("/orders/semantic_search")
def semantic_search_endpoint(
    q: str = Query(..., description="Free-text query"),
    top_k: int = Query(5, gt=0, le=50),
):
    logger.info(f"Semantic search query: {q!r}, top_k={top_k}")
    results = semantic_search(q, top_k=top_k)
    return results


# -----------------------------
# Part 4a: /orders/ask
# -----------------------------
@app.post("/orders/ask", response_model=AskResponse)
def ask_orders(req: AskRequest):
    logger.info(f"Received question: {req.question!r}")
    conn = get_conn()
    cur = conn.cursor()

    # First attempt
    sql = call_llm(req.question)

    if sql == "QUERY_NOT_SUPPORTED":
        conn.close()
        raise HTTPException(400, "Question cannot be answered from available schema.")

    # Up to 2 attempts: initial + 1 retry
    for attempt in range(2):
        try:
            cur.execute(sql)
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            conn.close()

            answer = build_answer(req.question, sql, rows)
            return AskResponse(
                natural_language_answer=answer,
                sql_used=sql,
                rows=rows,
            )

        except Exception as e:
            logger.error(f"SQL execution error on attempt {attempt+1}: {e}")

            if attempt == 1:
                conn.close()
                raise HTTPException(400, f"SQL failed after retry: {str(e)}")

            # Retry with error appended
            sql = call_llm(req.question, error=str(e))

            if sql == "QUERY_NOT_SUPPORTED":
                conn.close()
                raise HTTPException(400, "Question cannot be answered from available schema.")


# -----------------------------
# Optional: Admin endpoint to rebuild index after ETL
# -----------------------------
@app.post("/admin/rebuild_index")
def rebuild_index():
    build_semantic_index()
    return {"status": "semantic index rebuilt"}
