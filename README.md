# sap-rajesh
Solution to the sap-cxii-tech-ex-o2
Model Choice: I used TinyLlama-1.1B-Chat-GGUF via llama-cpp-python because:
It runs locally with no external API dependency
It is small enough to run on CPU
It supports instruction-tuned prompting
It is deterministic and fast for SQL generation


System Prompt Template
"You are an expert SQL generator. Convert natural language questions into valid SQLite SQL.

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
- If the question cannot be answered from this schema, respond with: QUERY_NOT_SUPPORTED"
  
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
Part 4d – Architectural extension (multi-tenant, 50 enterprise customers)
1. Tenant isolation for the vector index
Choice: One index per tenant (per-region), not a single shared FAISS/NumPy index.

Why:

Strongest data isolation guarantees (no cross-tenant leakage via bugs or misconfigured filters).

Easier to satisfy data residency (EU, US, KSA) by placing each tenant’s index in the correct region.

Memory trade-off:

Per-tenant index: Higher total memory (N tenants × index size), but each index is small (orders per customer are limited).

Shared index: Better memory efficiency, but requires strict namespace filtering and careful multi-tenant ACL logic.

Latency trade-off:

Per-tenant index: Slightly better latency—smaller index, fewer vectors to scan.

Shared index: Potentially slower queries as the index grows, unless sharded.

Data-leakage trade-off:

Per-tenant index: Very low risk—no shared structure.

Shared index: Higher blast radius if a bug bypasses namespace filters.

Conclusion: For 50 enterprise customers with strict residency and isolation requirements, per-tenant index per region is the safer and still operationally manageable choice.
2. LLM backend per tenant
Some tenants want on‑prem Llama, others are fine with cloud APIs (OpenAI, Anthropic, etc.).

Where routing lives
I introduce a “Model Gateway” layer between the API and the actual LLM providers:
Client → API (FastAPI) → Model Gateway → { OpenAI | Anthropic | Tenant Llama Cluster }
The API only calls model_gateway.generate_sql(tenant_id, prompt, ...).

The Model Gateway:

Looks up tenant config (LLM provider, region, allowed models).

Routes to the correct backend (cloud vs on‑prem).

Handles auth, retries, rate limits, logging.

Keeping prompts model-agnostic
The prompt template layer lives inside the API service, not in the provider-specific clients.

The API builds a normalized prompt object (e.g. {role: system, content: ...}, {role: user, content: ...}) and passes it to the Model Gateway.

The Model Gateway adapts this to each provider’s format (OpenAI chat, local Llama, etc.).

This keeps business logic + prompt design independent of the underlying LLM vendor.
3. PII in the NL→SQL pipeline
Order data includes customer IDs and amounts—both sensitive in many contexts.

Guardrails before sending to LLM
Schema minimization:

Only send the orders schema (no user names, emails, addresses).

Use abstract column names where possible (e.g. customer_id instead of customer_email).

Question sanitization:

Strip or mask obvious PII in the user question (emails, phone numbers, full names) before sending to a third-party LLM.

Example: "customer john.doe@example.com" → "customer [EMAIL_REDACTED]".

Row-level data never leaves the service:

The LLM only sees schema + question, not actual row values.

SQL execution happens locally against the tenant’s DB.
4. One high-leverage architectural decision & trade-off
Decision:  
I chose per-tenant, per-region data plane (DB + vector index + LLM routing) with a shared control plane.
               ┌────────────────────────────┐
               │        Control Plane       │
               │  (config, routing, auth)   │
               └─────────────┬──────────────┘
                             │
      ┌──────────────────────┼─────────────────────────┐
      │                      │                         │
┌─────▼─────┐          ┌─────▼─────┐             ┌─────▼─────┐
│ EU Tenant │          │ US Tenant │             │ KSA Tenant│
│  Stack    │          │  Stack    │             │  Stack    │
│ (eu-west) │          │ (us-east) │             │ (local)   │
└───────────┘          └───────────┘             └───────────┘
 DB + index + LLM   DB + index + LLM         DB + index + LLM
Trade-off accepted:

Pros:

Strong data residency guarantees (each tenant’s data + embeddings stay in-region).

Clear isolation boundaries (per-tenant blast radius).

Easier to reason about compliance (EU, US, KSA regulations).

Cons:

Higher operational overhead: more deployments to manage (per-region stacks).

Slightly more complex routing logic in the control plane.

Some duplication of infrastructure (multiple small indexes instead of one big one).

I accepted higher operational complexity in exchange for strong isolation, clear residency guarantees, and reduced data-leakage risk—which is the right trade-off for 50 enterprise customers with strict compliance requirements.
