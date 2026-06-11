"""
Seed script — fetches ~50 recent cs.AI papers from arXiv and indexes them
into PostgreSQL + OpenSearch so the demo deployment has content from day one.

Usage (run once after Railway services are up):
    uv run python scripts/seed_demo_data.py

Environment variables required (same as the API):
    POSTGRES_DATABASE_URL, OPENSEARCH__HOST, JINA_API_KEY (optional, for hybrid)
"""

import asyncio
import logging
import sys
from datetime import datetime, timedelta

# Ensure src/ is importable when run from project root
sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("seed")


async def seed():
    from src.config import get_settings
    from src.db.factory import make_database
    from src.services.arxiv.factory import make_arxiv_client
    from src.services.indexing.factory import make_hybrid_indexing_service
    from src.services.metadata_fetcher import make_metadata_fetcher
    from src.services.opensearch.factory import make_opensearch_client
    from src.services.pdf_parser.factory import make_pdf_parser_service

    settings = get_settings()
    logger.info("Connecting to database and OpenSearch...")

    database = make_database()
    opensearch_client = make_opensearch_client()
    arxiv_client = make_arxiv_client()
    pdf_parser = make_pdf_parser_service()
    metadata_fetcher = make_metadata_fetcher(arxiv_client, pdf_parser)

    # Setup OpenSearch index
    if opensearch_client.health_check():
        opensearch_client.setup_indices(force=False)
        logger.info("OpenSearch index ready")
    else:
        logger.error("Cannot reach OpenSearch — is it running?")
        sys.exit(1)

    # Fetch papers across the last 7 days so we get ~50 papers
    total_fetched = 0
    total_indexed = 0

    for days_ago in range(1, 8):
        date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y%m%d")
        logger.info(f"Fetching papers for {date}...")

        try:
            with database.get_session() as session:
                results = await metadata_fetcher.fetch_and_process_papers(
                    max_results=10,
                    from_date=date,
                    to_date=date,
                    process_pdfs=True,
                    store_to_db=True,
                    db_session=session,
                )
            fetched = results.get("papers_fetched", 0)
            total_fetched += fetched
            logger.info(f"  {date}: fetched {fetched} papers")
        except Exception as e:
            logger.warning(f"  {date}: fetch failed — {e}")
            continue

        if total_fetched >= 50:
            break

    logger.info(f"Fetch complete: {total_fetched} papers stored in PostgreSQL")

    # Now index everything from PostgreSQL into OpenSearch
    logger.info("Indexing papers into OpenSearch (chunking + embeddings)...")
    try:
        indexing_service = make_hybrid_indexing_service()
        from src.models.paper import Paper

        with database.get_session() as session:
            papers = session.query(Paper).all()
            papers_data = [
                {
                    "id": str(p.id),
                    "arxiv_id": p.arxiv_id,
                    "title": p.title,
                    "authors": p.authors,
                    "abstract": p.abstract,
                    "categories": p.categories,
                    "published_date": p.published_date,
                    "raw_text": p.raw_text,
                    "sections": p.sections,
                }
                for p in papers
            ]

        stats = await indexing_service.index_papers_batch(papers=papers_data, replace_existing=False)
        total_indexed = stats.get("total_chunks_indexed", 0)
        logger.info(f"Indexing complete: {stats['papers_processed']} papers → {total_indexed} chunks in OpenSearch")

    except Exception as e:
        logger.error(f"Indexing failed: {e}")
        logger.info("Note: You can still search by abstract/title via BM25 without embeddings.")

    database.teardown()
    logger.info(f"Seed complete. {total_fetched} papers fetched, {total_indexed} chunks indexed.")
    logger.info("Your demo is ready — visit /api/v1/health and /docs")


if __name__ == "__main__":
    asyncio.run(seed())
