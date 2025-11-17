# arXiv Paper Curator

Personal arXiv CS.AI paper concierge that ingests new submissions every day, parses PDFs with Docling, pushes richly chunked content into PostgreSQL + OpenSearch, and exposes both API and Gradio chat surfaces backed by a Langfuse-instrumented RAG stack running on Ollama.

![Complete architecture](static/week5_complete_rag.png)

## Highlights
- **Automated ingestion pipeline** - Airflow DAG fetches fresh arXiv papers, downloads PDFs, extracts structured text, retries failures, and stores end-to-end artifacts in PostgreSQL.
- **Retrieval built for research** - Section-aware chunking and Jina embeddings drive a hybrid BM25 + vector OpenSearch index with an RRF pipeline for precise recall.
- **LLM answers with provenance** - FastAPI exposes `/ask` and `/stream` endpoints that retrieve supporting chunks, build prompts, call Ollama models, and return citations plus Langfuse traces.
- **Low-latency UX** - A ready-to-run Gradio UI streams responses in real time, shows chunk counts, and links back to arXiv PDFs.
- **Observability-first** - Langfuse, Redis caching, health probes, and Makefile tooling keep the system debuggable as it scales.

## Stack at a Glance

| Layer | Technology | Notes |
| --- | --- | --- |
| API + RAG | FastAPI, Ollama, Langfuse tracer | `src/main.py`, `/api/v1/*`, streaming + tracing |
| Retrieval | PostgreSQL, OpenSearch 2.19, Redis cache | BM25/vector hybrid index, chunk metadata, exact-match caching |
| Embeddings & Parsing | Jina Embeddings v3, Docling, Tesseract/Poppler | Async embedding client, PDF parser with OCR/table extraction |
| Data Pipeline | Apache Airflow 2.10 | `airflow/dags/arxiv_paper_ingestion.py` orchestrates ingestion |
| UI | Gradio 4 | `gradio_launcher.py` exposes RAG chat |
| Observability | Langfuse v2 + ClickHouse + Postgres | Full RAG span tracing, prompt/body logging |

## Repository Layout

| Path | Purpose |
| --- | --- |
| `src/` | FastAPI app, routers (`ask`, `hybrid_search`, `ping`), services (arXiv, embeddings, PDF parser, Langfuse, Ollama, OpenSearch, cache), schemas, and database helpers. |
| `airflow/` | Custom Airflow image, DAGs, and requirements powering the ingestion workflow (see `airflow/README.md`). |
| `compose.yml` | Docker Compose stack for API, vector DB, Redis cache, Airflow, Ollama, Langfuse, and observability stores. |
| `gradio_launcher.py` & `src/gradio_app.py` | Streamed RAG chat UI that consumes `/api/v1/stream`. |
| `notebooks/` | Week-by-week exploratory notebooks capturing experiments for ingestion, indexing, hybrid search, and monitoring. |
| `static/` | Architecture diagrams referenced in docs. |
| `tests/` | Pytest suites (API, unit, integration) bootstrapped via `uv run pytest`. |

## Service Matrix (default ports)

| Service | Port(s) | Description |
| --- | --- | --- |
| FastAPI RAG API | `8000` | `/api/v1/health`, `/api/v1/hybrid-search`, `/api/v1/ask`, `/api/v1/stream`, `/docs` |
| Gradio UI | `7861` | Streams responses from the `/stream` endpoint. |
| PostgreSQL | `5432` | Primary metadata/content store (`rag_db`). |
| OpenSearch & Dashboards | `9200`, `5601` | Hybrid index plus Kibana-style dashboards. |
| Redis | `6379` | Exact-match response cache (6h TTL). |
| Airflow | `8080` | Manage DAGs, logs, and ingestion status. |
| Ollama | `11434` | Local models (default `llama3.2:1b`, configurable per request). |
| Langfuse + ClickHouse | `3000`, `8123` (internal) | Request/trace observability. |

## Getting Started

### 1. Prerequisites
- Docker + Docker Compose, GNU Make
- Python 3.12 with [uv](https://github.com/astral-sh/uv) for local work outside Docker
- Jina AI API key (required for hybrid search embeddings)
- Langfuse project keys if you want tracing

### 2. Configure Environment
```bash
cp .env.example .env
# edit the values that matter for you
```
Key variables:
- `POSTGRES_DATABASE_URL` - SQLAlchemy DSN used by API/Airflow.
- `JINA_API_KEY` - enables 1024-dim query/passage embeddings. Without it the system falls back to BM25.
- `OLLAMA_MODEL` / `OLLAMA_HOST` - default local model & server.
- `LANGFUSE__PUBLIC_KEY` / `LANGFUSE__SECRET_KEY` - optional but unlocks tracing dashboards.
- `OPENSEARCH__*`, `CHUNKING__*`, `PDF_PARSER__*` - advanced tuning knobs with sensible defaults.

### 3. Run the full stack with Docker
```bash
make start      # builds the API image and boots every service in compose.yml
make status     # list containers
make logs       # follow aggregated logs
```
Once healthy:
- FastAPI docs: http://localhost:8000/docs
- Hybrid search playground (curl or HTTP client)
- Gradio UI: `python gradio_launcher.py` (runs on host, talks to Docker API)
- Airflow UI: http://localhost:8080
- Langfuse UI: http://localhost:3000

Shut everything down with `make stop`, or `make clean` to remove volumes.

### 4. Local-only app development
1. Install deps via uv: `uv sync`.
2. Start supporting services (DB, Redis, OpenSearch, Ollama) with Docker Compose: `docker compose up postgres redis opensearch ollama -d`.
3. Launch the API in hot-reload mode:
   ```bash
   uv run uvicorn src.main:app --reload --port 8000
   ```
4. (Optional) Start the Gradio UI locally:
   ```bash
   uv run python gradio_launcher.py
   ```
5. Use `uv run ruff format && uv run ruff check` before pushing changes.

## Data Ingestion Pipeline (Airflow)

The DAG at `airflow/dags/arxiv_paper_ingestion.py` is the backbone of the daily curator:
1. **Environment bootstrap** - sanity-check dependent services, initialize caches.
2. **Daily Paper Fetch** - call the arXiv API (default: previous day, 10-15 `cs.AI` papers) respecting rate limits.
3. **Concurrent downloads** - doclinks cached under `./data/arxiv_pdfs`, retry logic for transient errors.
4. **PDF parsing** - Docling + optional OCR/table extraction convert PDFs into structured sections.
5. **Chunking & storage** - Section-aware chunker (600 words, 100 overlap) saves clean text + metadata to PostgreSQL.
6. **OpenSearch prep** - Index-ready documents emitted for hybrid/BM25/vector search (RRF pipeline placeholders already available).
7. **Reporting** - End-of-run statistics summarizing successes, retries, and any skipped papers.

See `airflow/README.md` for Docker image details, concurrency settings, and roadmap beyond Week 2.

## API Surface

| Endpoint | Method | Description |
| --- | --- | --- |
| `/api/v1/health` | GET | Pings PostgreSQL, OpenSearch, and Ollama; returns service-by-service status with version metadata. |
| `/api/v1/hybrid-search` | POST | Request body: `{ query, size, from, categories, latest, use_hybrid, min_score }`. Returns paginated paper chunks with highlights and scores using BM25 or hybrid retrieval. |
| `/api/v1/ask` | POST | `AskRequest` (`query`, `top_k`, `use_hybrid`, optional `categories`, `model`). Runs retrieval, builds prompts, calls Ollama, caches exact matches in Redis, and responds with answer + sources + chunk counts. |
| `/api/v1/stream` | POST | Same payload as `/ask` but streams Server-Sent Events chunks for a low-latency UX (used by Gradio). |

Interactive docs live under `/docs` and `/redoc`. Example hybrid search request:

```bash
curl -X POST http://localhost:8000/api/v1/hybrid-search \
  -H "Content-Type: application/json" \
  -d '{"query":"graph neural networks for molecules","use_hybrid":true,"size":5}'
```

## Gradio Chat UI
- Launch via `python gradio_launcher.py` once the API is running.
- Streams the `/stream` endpoint, surfaces chunk counts, search mode (BM25 vs Hybrid), and up to three source PDFs.
- Offers knobs for `top_k`, hybrid toggle, LLM choice (`llama3.2:1b`, `llama3.2:3b`, `llama3.1:8b`, `qwen2.5:7b`), and category filters.

## Observability & Caching
- **Langfuse tracing** (`src/services/langfuse`) wraps embedding, search, prompt construction, generation, and streaming spans so you can audit every RAG hop.
- **Redis cache** stores exact query/parameter responses for six hours, drastically lowering latency on repeated requests.
- **OpenSearch dashboards** (port 5601) visualize ingestion state, index sizes, and query trends.
- **Makefile `health`** target hits API, OpenSearch, Airflow, and Ollama health endpoints in one shot.

## Testing, Linting, and Tooling

```bash
uv run pytest               # run unit + integration tests
uv run pytest --cov=src     # coverage report (HTML under htmlcov/)
uv run ruff check --fix     # lint & autofix
uv run mypy src/            # type checks (suppressed errors allowed via config)
uv run ruff format          # opinionated formatting
```

You can also rely on the Make targets (`make test`, `make format`, etc.) which wrap the uv invocations.

## Roadmap & Ideas
- Enable live hybrid indexing inside the Airflow DAG now that OpenSearch clients are wired up.
- Plug additional categories (e.g., `cs.CL`, `cs.CV`) by adjusting `.env` and Airflow params.
- Expand tracing with more cache metrics or Langfuse dashboards.
- Promote notebooks into docs/blog posts for weekly build logs (see `notebooks/week*`).

## License

Distributed under the MIT License. See `LICENSE` for details.
