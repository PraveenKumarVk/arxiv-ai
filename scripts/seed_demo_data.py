"""
Seed script — fetches ~50 recent cs.AI papers from arXiv and indexes them
into PostgreSQL + OpenSearch using abstract text only (no PDF parsing).

Usage:
    POSTGRES_DATABASE_URL=... OPENSEARCH__HOST=... JINA_API_KEY=... \\
        uv run python scripts/seed_demo_data.py
"""

import asyncio
import logging
import sys
from datetime import datetime

sys.path.insert(0, ".")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("seed")


async def seed():
    import httpx

    from src.config import get_settings
    from src.db.factory import make_database
    from src.models.paper import Paper
    from src.services.embeddings.factory import make_embeddings_service
    from src.services.opensearch.factory import make_opensearch_client

    settings = get_settings()
    database = make_database()
    opensearch_client = make_opensearch_client()
    embeddings_service = make_embeddings_service()

    if not opensearch_client.health_check():
        logger.error("Cannot reach OpenSearch")
        sys.exit(1)
    opensearch_client.setup_indices(force=False)
    logger.info("OpenSearch index ready")

    # Fetch papers from arXiv Atom API (no auth needed)
    logger.info("Fetching cs.AI papers from arXiv...")
    papers_raw = []
    for start in range(0, 60, 20):
        url = (
            "https://export.arxiv.org/api/query"
            f"?search_query=cat:cs.AI&sortBy=submittedDate&sortOrder=descending"
            f"&start={start}&max_results=20"
        )
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url)
        # Parse Atom XML minimally
        import xml.etree.ElementTree as ET
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(r.text)
        for entry in root.findall("atom:entry", ns):
            arxiv_id = entry.find("atom:id", ns).text.split("/abs/")[-1]
            title = entry.find("atom:title", ns).text.strip().replace("\n", " ")
            abstract = entry.find("atom:summary", ns).text.strip().replace("\n", " ")
            authors = [a.find("atom:name", ns).text for a in entry.findall("atom:author", ns)]
            published = entry.find("atom:published", ns).text[:10]
            categories = [c.get("term") for c in entry.findall("{http://arxiv.org/schemas/atom}primary_category", ns)]
            papers_raw.append({
                "arxiv_id": arxiv_id,
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "published_date": published,
                "categories": categories or ["cs.AI"],
            })
        logger.info(f"  Fetched {len(papers_raw)} papers so far")
        if len(papers_raw) >= 50:
            break

    papers_raw = papers_raw[:50]

    # Store in PostgreSQL
    logger.info(f"Storing {len(papers_raw)} papers in PostgreSQL...")
    stored_ids = []
    with database.get_session() as session:
        for p in papers_raw:
            existing = session.query(Paper).filter_by(arxiv_id=p["arxiv_id"]).first()
            if existing:
                stored_ids.append(str(existing.id))
                continue
            paper = Paper(
                arxiv_id=p["arxiv_id"],
                title=p["title"],
                abstract=p["abstract"],
                authors=p["authors"],
                categories=p["categories"],
                published_date=datetime.strptime(p["published_date"], "%Y-%m-%d"),
                pdf_url=f"https://arxiv.org/pdf/{p['arxiv_id']}",
                raw_text=p["abstract"],
            )
            session.add(paper)
            session.flush()
            stored_ids.append(str(paper.id))
        session.commit()
    logger.info(f"Stored {len(stored_ids)} papers in PostgreSQL")

    # Index into OpenSearch with embeddings
    logger.info("Generating embeddings and indexing into OpenSearch...")
    indexed = 0
    for i, p in enumerate(papers_raw):
        try:
            text = f"{p['title']}\n\n{p['abstract']}"
            embeddings = await embeddings_service.embed_passages([text])
            embedding = embeddings[0]
            doc = {
                "paper_id": stored_ids[i] if i < len(stored_ids) else p["arxiv_id"],
                "arxiv_id": p["arxiv_id"],
                "title": p["title"],
                "abstract": p["abstract"],
                "authors": p["authors"],
                "categories": p["categories"],
                "published_date": p["published_date"],
                "chunk_text": text,
                "chunk_index": 0,
                "embedding": embedding,
            }
            opensearch_client.client.index(
                index=opensearch_client.index_name,
                body=doc,
                id=f"{p['arxiv_id']}_0",
            )
            indexed += 1
            if (i + 1) % 10 == 0:
                logger.info(f"  Indexed {i+1}/{len(papers_raw)}")
        except Exception as e:
            logger.warning(f"  Failed to index {p['arxiv_id']}: {e}")

    database.teardown()
    logger.info(f"Seed complete: {len(papers_raw)} papers fetched, {indexed} chunks indexed in OpenSearch")
    logger.info("Visit https://arxiv-ai.onrender.com/docs to try the API")


if __name__ == "__main__":
    asyncio.run(seed())
