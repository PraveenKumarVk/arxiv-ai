# arXiv AI Paper Curator

> A production-grade RAG system that ingests daily arXiv CS.AI papers, indexes them with hybrid BM25 + semantic search, and answers research questions via a streaming LLM API — deployed on free cloud infrastructure.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-arxiv--ai.onrender.com-brightgreen)](https://arxiv-ai.onrender.com/docs)
[![Health](https://img.shields.io/badge/Health-/api/v1/health-blue)](https://arxiv-ai.onrender.com/api/v1/health)
[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)](https://fastapi.tiangolo.com/)

**Live API:** https://arxiv-ai.onrender.com/docs

---

## What It Does

Ask a natural language question like _"What are the latest approaches to graph neural networks?"_ and get a cited, context-grounded answer sourced from arXiv papers — with hybrid BM25 + semantic retrieval, streaming LLM generation, Redis caching, and full Langfuse observability.

```bash
curl -X POST https://arxiv-ai.onrender.com/api/v1/ask \
  -H "Content-Type: application/json" \
  -d '{"query": "retrieval augmented generation for code", "top_k": 5}'
```

---

## Architecture

![Architecture](static/architecture.png)

The system has two independently deployable layers:

**Data Pipeline (Airflow)** — runs Mon–Fri at 6 AM UTC. Fetches new `cs.AI` papers from arXiv, parses PDFs with Docling (OCR, table extraction), chunks them section-aware, generates Jina passage embeddings, and bulk-indexes into OpenSearch + PostgreSQL.

**Query API (FastAPI)** — stateless, cloud-deployed. Accepts natural language queries, embeds them with Jina, retrieves via BM25/kNN/hybrid search, builds context-grounded prompts, and streams answers from Groq (cloud) or Ollama (local).

---

## Cloud Deployment Stack

| Service | Provider | Free Tier |
|---------|----------|-----------|
| FastAPI (RAG API) | [Render](https://render.com) | 512MB, spins down on idle |
| PostgreSQL | [Render](https://render.com) | 1GB storage |
| OpenSearch (BM25 + kNN) | [Bonsai.io](https://bonsai.io) | 10k docs, 125MB |
| Redis cache | [Upstash](https://upstash.com) | 10k req/day |
| LLM (Groq API) | [Groq](https://console.groq.com) | Free tier, llama-3.1-8b |
| Embeddings | [Jina AI](https://jina.ai) | Free tier |

> **Note:** The free Render instance spins down after 15 minutes of inactivity — first request after idle takes ~50s to cold-start.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **API** | FastAPI 0.115, Python 3.12, `uv` package manager |
| **LLM** | Groq API (llama-3.1-8b-instant) · Ollama for local dev |
| **Embeddings** | Jina Embeddings v3 — 1024-dim, task-aware (query vs passage) |
| **Search** | OpenSearch 2.19 — hybrid BM25 + kNN index, RRF fusion |
| **PDF Parsing** | Docling + Tesseract OCR + Poppler (Airflow pipeline only) |
| **Data Pipeline** | Apache Airflow 2.10 — DAG with retry, concurrency control |
| **Database** | PostgreSQL 16 — paper metadata, full text, SQLAlchemy ORM |
| **Cache** | Redis 7 — SHA-256 keyed exact-match cache, 6h TTL |
| **Observability** | Langfuse v2 — traces every RAG span (embed → search → generate) |
| **UI** | Gradio 4 — real-time SSE streaming chat |
| **Infra** | Docker Compose, Dockerfile, pre-commit, Ruff, mypy |

---

## Key Features

- **Hybrid retrieval** — OpenSearch index combines BM25 keyword scoring with 1024-dim Jina vector search, fused via Reciprocal Rank Fusion. Degrades gracefully to BM25 on managed clusters.
- **Section-aware chunking** — papers split into 600-word overlapping chunks that respect document section boundaries.
- **Streaming RAG** — `/ask` returns complete JSON; `/stream` pushes Server-Sent Events for token-by-token UI streaming. Both check Redis cache first.
- **LLM-provider agnostic** — `LLM_PROVIDER=groq` or `LLM_PROVIDER=ollama` swap the backend with no code changes. Groq uses OpenAI-compatible SSE; Ollama uses NDJSON — both normalized to the same interface.
- **Full observability** — every RAG request traced in Langfuse: embedding latency, search hit scores, prompt construction, generation time, token counts.

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/health` | GET | Health check — PostgreSQL, OpenSearch, LLM |
| `/api/v1/hybrid-search` | POST | BM25 or hybrid vector search with highlights |
| `/api/v1/ask` | POST | RAG Q&A — retrieves chunks, calls LLM, caches result |
| `/api/v1/stream` | POST | Same as `/ask` but streams tokens via SSE |

**`/ask` request:**
```json
{
  "query": "What is chain-of-thought prompting?",
  "top_k": 5,
  "use_hybrid": true,
  "model": "llama-3.1-8b-instant",
  "categories": ["cs.AI"]
}
```

**Response:** `answer`, `sources` (arXiv URLs), `chunks_used`, `search_mode`, `cached`.

---

## Build Journey

This system was built incrementally across 6 weeks, with each week's architecture documented in [`notebooks/`](notebooks/) and captured below.

### Week 1 — Infrastructure Setup
![Week 1](static/week1_infra_setup.png)

Docker Compose stack with FastAPI, PostgreSQL 16, OpenSearch 2.19, Airflow 3.0, and Ollama — all wired with health checks and persistent volumes.

### Week 2 — Data Ingestion Pipeline
![Week 2](static/week2_data_ingestion_flow.png)

Airflow DAG orchestrating arXiv API fetch → Docling PDF parsing → PostgreSQL storage. ArxivClient with rate limiting and retry logic; PDFParserService with OCR and table extraction.

### Week 3 — OpenSearch & BM25 Search
![Week 3](static/week3_opensearch_flow.png)

OpenSearch index with BM25 keyword retrieval. QueryBuilder, section-aware chunker, bulk indexing from the Airflow pipeline.

### Week 4 — Hybrid Search (BM25 + Vector)
![Week 4](static/week4_hybrid_opensearch.png)

Jina Embeddings v3 for passage and query encoding. Hybrid index combining BM25 scores and kNN similarity, fused with Reciprocal Rank Fusion (RRF) pipeline.

### Week 5 — Complete RAG Pipeline
![Week 5](static/week5_complete_rag.png)

LLM generation layer with Ollama integration. `/ask` and `/stream` endpoints, RAGPromptBuilder, context window management, Gradio streaming UI.

### Week 6 — Observability & Caching
![Week 6](static/week6_monitoring_and_caching.png)

Langfuse traces wrapping every RAG span. Redis exact-match cache keyed by SHA-256 of `(query, model, top_k, categories)`. Cache hits skip all 4 pipeline steps and return in < 5ms.

---

## Project Structure

```
arxiv-ai/
├── src/
│   ├── main.py                    # FastAPI app with lifespan service wiring
│   ├── config.py                  # Pydantic Settings — all config via env vars
│   ├── routers/
│   │   ├── ask.py                 # /ask (JSON) and /stream (SSE) RAG endpoints
│   │   ├── hybrid_search.py       # /hybrid-search — BM25/vector/hybrid search
│   │   └── ping.py                # /health — checks all downstream services
│   ├── services/
│   │   ├── arxiv/                 # arXiv Atom API client
│   │   ├── pdf_parser/            # Docling PDF → structured sections
│   │   ├── embeddings/            # Jina async embeddings client
│   │   ├── indexing/              # HybridIndexingService + TextChunker
│   │   ├── opensearch/            # OpenSearch client, query builder, index config
│   │   ├── ollama/                # OllamaClient + GroqClient + RAGPromptBuilder
│   │   ├── cache/                 # Redis exact-match cache
│   │   └── langfuse/              # RAGTracer — wraps every pipeline span
│   ├── models/                    # SQLAlchemy ORM models
│   └── schemas/                   # Pydantic request/response schemas
├── airflow/
│   └── dags/
│       ├── arxiv_paper_ingestion.py   # Main DAG: sync→fetch→index→report→cleanup
│       └── arxiv_ingestion/
│           ├── fetching.py            # arXiv API + concurrent PDF download
│           ├── indexing.py            # Chunking + embedding + OpenSearch bulk
│           └── reporting.py          # Daily run statistics
├── notebooks/                     # Week-by-week experiment notebooks (weeks 1–6)
├── scripts/
│   └── seed_demo_data.py          # Seeds 50 cs.AI papers for demo deployment
├── tests/                         # Pytest: unit, API, integration
├── compose.yml                    # Full Docker Compose stack (10 services)
├── Dockerfile                     # Production image (no torch/docling)
└── pyproject.toml                 # uv/ruff/mypy/pytest config
```

---

## Local Development

### Prerequisites
- Docker + Docker Compose
- Python 3.12 + [uv](https://github.com/astral-sh/uv)
- Jina AI API key (free tier at [jina.ai](https://jina.ai))
- Groq API key (free tier at [console.groq.com](https://console.groq.com)) or Ollama installed locally

### 1. Configure environment

```bash
cp .env.example .env
# Set JINA_API_KEY, GROQ_API_KEY (or leave LLM_PROVIDER=ollama)
```

### 2. Start the full stack

```bash
make start        # builds API image, starts all 10 services
make status       # verify containers are healthy
make logs         # follow aggregated logs
```

| Service | URL |
|---------|-----|
| FastAPI docs | http://localhost:8000/docs |
| Gradio UI | http://localhost:7861 |
| Airflow | http://localhost:8080 |
| Langfuse | http://localhost:3000 |
| OpenSearch Dashboards | http://localhost:5601 |

### 3. Local dev without Docker (API only)

```bash
uv sync
docker compose up postgres redis opensearch -d
LLM_PROVIDER=groq GROQ_API_KEY=... uv run uvicorn src.main:app --reload
```

### 4. Try it

```bash
# Search papers
curl -X POST http://localhost:8000/api/v1/hybrid-search \
  -H "Content-Type: application/json" \
  -d '{"query": "diffusion models for protein folding", "use_hybrid": true}'

# Ask a question
curl -X POST http://localhost:8000/api/v1/ask \
  -H "Content-Type: application/json" \
  -d '{"query": "How does RLHF work?", "top_k": 5}'
```

---

## Cloud Deployment (Render + Bonsai + Upstash)

The API is deployed without Docling or torch — PDF parsing runs in the Airflow pipeline, not in the API image. This keeps the Docker image under 512MB.

```
LLM_PROVIDER=groq
GROQ_API_KEY=...
JINA_API_KEY=...
POSTGRES_DATABASE_URL=postgresql://...
OPENSEARCH__HOST=https://user:pass@cluster.bonsaisearch.net
REDIS__HOST=...upstash.io
REDIS__PORT=6379
REDIS__PASSWORD=...
REDIS__SSL=true
LANGFUSE__ENABLED=false
```

See [`.env.example`](.env.example) for the full list.

---

## Testing

```bash
uv run pytest                     # all tests
uv run pytest --cov=src           # with coverage
uv run pytest tests/unit/         # unit only
uv run pytest tests/integration/  # requires running services
```

```bash
uv run ruff check --fix && uv run ruff format
uv run mypy src/
```

---

## Airflow DAG

The `arxiv_paper_ingestion` DAG runs Mon–Fri and orchestrates:

```
setup_environment
    └── fetch_daily_papers          # arXiv API → PDF download (concurrent, rate-limited)
            └── index_papers_hybrid # Docling parse → section chunk → Jina embed → OS bulk
                    └── generate_daily_report
                            └── cleanup_temp_files
```

- Up to 15 `cs.AI` papers per run, retried 3× with exponential backoff
- 600-word chunks, 100-word overlap, section-boundary aware
- Bulk-indexed with 1024-dim passage embeddings into OpenSearch

---

Built by **[Praveen Kumar Varkala](https://github.com/PraveenKumarVk)** · [reachpraveenvk@gmail.com](mailto:reachpraveenvk@gmail.com)
