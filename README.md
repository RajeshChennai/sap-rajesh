**📘 SAP CXII Tech Exercise — AI Architect Solution**
This repository contains my implementation of the sap-cxii-tech-ex-02 assignment.
It includes:

A complete ETL pipeline

A FastAPI query service

Semantic search

An LLM‑powered natural language SQL endpoint

A multi‑tenant architectural extension

**🚀 Setup Instructions**
1. Create virtual environment
bash
python3 -m venv venv
source venv/bin/activate
2. Install dependencies
bash
pip install -r requirements.txt
3. Run ETL
bash
python etl.py load data/orders.csv
This:
* Loads raw CSV
* Normalizes dates
* Converts currencies
* Cleans missing values
* Stores cleaned data in db/orders.db
4. Start API
bash
uvicorn app:app --reload
API will be available at:
Code
http://localhost:8000
**🧱 Project Structure**
Code
sap-rajesh/
│
├── etl.py
├── app.py
├── requirements.txt
├── Dockerfile
├── k8s/
│   ├── deployment.yaml
│   ├── service.yaml
│   └── configmap.yaml
└── db/
    └── orders.db
**🧪 API Endpoints**
Part 2 — Core Endpoints
Endpoint	Description
GET /orders/customer/{id}	Orders for a customer
GET /orders/stats	Revenue, AOV, orders/day
GET /orders/recent?days=N	Orders in last N days
GET /healthz	Liveness check


**🤖 Part 4a — Natural Language SQL Endpoint**
Endpoint
Code
POST /orders/ask
{
  "question": "What is the total revenue from customer C001?"
}
Model Choice
I used TinyLlama‑1.1B‑Chat‑GGUF via llama-cpp-python because:

Runs locally (no external API dependency)

Small enough for CPU inference

Instruction‑tuned

Deterministic and fast for SQL generation

**System Prompt Template**
Code
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
Retry Loop Example
Bad SQL generated:

Code
SELECT SUM(amount_usd) FROM order;
Error:

Code
no such table: order
Retry prompt:

Code
Previous SQL error: no such table: order
Fix the SQL.
Corrected SQL:

Code
SELECT SUM(amount_usd) FROM orders;
**🔍 Part 4b — Semantic Order Search**
Endpoint
Code
GET /orders/semantic_search?q=high+value+recent+orders&top_k=5
Embedding Model
I used sentence-transformers/all-MiniLM-L6-v2 because:

Optimized for short text similarity

Excellent for structured snippets like
"customer C001, $320 USD, 2024-03-15"

Fast CPU inference

Lightweight and production‑ready

Vector Index Choice
I used NumPy instead of FAISS.

Approach	Pros	Cons
NumPy (chosen)	Simple, zero dependencies, fast for small datasets	Not ideal for millions of vectors
FAISS	Extremely fast for large-scale search	Heavier dependency, more complex setup


Given dataset size (hundreds–thousands of orders), NumPy is ideal.

Index Rebuild Strategy
Index is built at API startup via build_semantic_index().

After ETL loads new data, index can be refreshed via:

Code
POST /admin/rebuild_index
Concurrency note:  
Rebuilds are fast (milliseconds).
If a rebuild overlaps with in‑flight requests, impact is negligible.
Production systems would use a read‑write lock or background worker.

Query Flow
Convert query → embedding

Compute cosine similarity

Return top‑k most similar orders

Example Response:

json
[
  {
    "order_id": "1007",
    "customer_id": "C001",
    "amount_usd": 320.0,
    "order_date": "2024-03-15",
    "score": 0.91
  }
]
**🏗️ Part 4d — Architectural Extension (Multi‑Tenant, 50 Customers)**
Your service now includes:

An LLM

An embedding model

A vector index

You must scale this to 50 enterprise customers with data residency:

EU → eu‑west

US → us‑east

KSA → local cloud

1. Tenant Isolation for Vector Index
Decision: One index per tenant per region (not a shared FAISS index).

Why?
Strongest isolation

Zero cross‑tenant leakage

Easy residency compliance

Smaller, faster indexes

Trade-offs
Option	Pros	Cons
Per-tenant index (chosen)	Strong isolation, residency compliance, low leakage risk	More infra, more memory
Shared index	Lower memory	Higher leakage risk, complex ACLs


2. LLM Backend per Tenant
Some tenants require on‑prem Llama, others allow cloud APIs.

Solution: Model Gateway Layer
Code
Client → API → Model Gateway → { OpenAI | Anthropic | Tenant Llama Cluster }
API calls: model_gateway.generate_sql(tenant_id, prompt)

Gateway handles:

Routing

Auth

Rate limits

Logging

Provider selection

Keeping prompts model‑agnostic
Prompt templates live in API

Gateway adapts them to each provider’s format

Business logic stays independent of vendor

3. PII Guardrails in NL→SQL Pipeline
Guardrails
Schema minimization (only send column names)

Question sanitization (mask emails, phone numbers)

Never send row-level data to LLM

SQL executes locally inside tenant’s region

Cloud vs On‑Prem
Deployment	PII Handling
Cloud LLM	Aggressive masking, strict redaction
On‑prem LLM	More flexibility, but still avoid unnecessary PII


4. High-Leverage Architectural Decision
Decision:  
Adopt a per-tenant, per-region data plane with a shared control plane.

Diagram
Code
               ┌────────────────────────────┐
               │        Control Plane       │
               │  (config, routing, auth)   │
               └─────────────┬──────────────┘
                             │
      ┌──────────────────────┼─────────────────────────┐
      │                      │                         │
┌─────▼─────┐          ┌─────▼─────┐             ┌─────▼─────┐
│ EU Tenant │          │ US Tenant │             │ KSA Tenant │
│  Stack    │          │  Stack    │             │  Stack     │
│ (eu-west) │          │ (us-east) │             │ (local)    │
└───────────┘          └───────────┘             └───────────┘
 DB + index + LLM   DB + index + LLM         DB + index + LLM
Trade-off Accepted
Pros:

Strong residency guarantees

Clear isolation

Reduced leakage risk

Cons:

More infra to manage

Slightly more complex routing

Why accepted:  
Enterprise customers prioritize security + compliance over infra simplicity.
