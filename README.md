# sap-rajesh
Solution to the sap-cxii-tech-ex-o2
Model Choice
I used TinyLlama-1.1B-Chat-GGUF via llama-cpp-python because:
It runs locally with no external API dependency
It is small enough to run on CPU
It supports instruction-tuned prompting
It is deterministic and fast for SQL generation


System Prompt Template
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
- 
Retry Loop Example
Bad SQL generated
SELECT SUM(amount_usd) FROM order;
Error:
no such table: order
Retry prompt included error:
Previous SQL error: no such table: order
Fix the SQL.
Corrected SQL:
SELECT SUM(amount_usd) FROM orders;
Part 4b — Semantic Order Search
Embedding Model
I used sentence-transformers/all-MiniLM-L6-v2 as the embedding model.
This model is well‑suited for this task because:

It is optimized for short text similarity

It produces high‑quality embeddings for structured text like
"customer C001, $320 USD, 2024-03-15"

It is lightweight and fast enough for real‑time inference on CPU

It is widely used and well‑supported in production environments| Approach | Pros | Cons |
| --- | --- | --- |
| **NumPy (chosen)** | Simple, zero dependencies, fast for small datasets | Not ideal for millions of vectors |
| **FAISS** | Extremely fast for large-scale vector search | Heavier dependency, more complex setup |

Given the dataset size in this exercise (hundreds or thousands of orders), NumPy provides excellent performance with minimal overhead.
Index Rebuild Strategy
The semantic index is built at service startup via:
build_semantic_index()
When etl.py loads new data, the index can be rebuilt by calling:
POST /admin/rebuild_index
This keeps the index fresh without restarting the service.

Concurrency note:  
Rebuilds are fast (milliseconds for small datasets).
If a rebuild overlaps with in‑flight requests, the impact is negligible.
For production, a read‑write lock or background worker would be used.
Query Flow
Convert the user query into an embedding

Compute cosine similarity against all order embeddings

Return the top‑k most similar orders with similarity scores

Example:
GET /orders/semantic_search?q=high+value+recent+orders&top_k=5
Response:
[
  {
    "order_id": "1007",
    "customer_id": "C001",
    "amount_usd": 320.0,
    "order_date": "2024-03-15",
    "score": 0.91
  }
]
