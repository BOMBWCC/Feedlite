import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import Article, ArticleChunk, Feed
from app.services.rss_fetcher import deduplicate_and_store


class RssFetcherTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with self.session_factory() as session:
            feed = Feed(url="https://example.com/rss.xml", title="Example", category=2)
            session.add(feed)
            await session.commit()
            await session.refresh(feed)
            self.feed_id = feed.id

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_deduplicate_and_store_generates_chunks_for_new_articles_only(self):
        published = datetime.now(timezone.utc).isoformat()
        article_payload = {
            "title": "OpenAI ships new API",
            "link": "https://example.com/openai-api",
            "description": "English summary for ranking",
            "content": " ".join(f"detail{i:03d}" for i in range(160)),
            "published": published,
        }

        async with self.session_factory() as session:
            inserted = await deduplicate_and_store(session, [article_payload], self.feed_id)

        self.assertEqual(inserted, 1)

        async with self.session_factory() as session:
            article_rows = (await session.execute(select(Article))).scalars().all()
            chunk_rows = (
                await session.execute(
                    select(ArticleChunk).order_by(ArticleChunk.article_id.asc(), ArticleChunk.chunk_index.asc())
                )
            ).scalars().all()

        self.assertEqual(len(article_rows), 1)
        self.assertGreater(len(chunk_rows), 0)
        self.assertEqual(chunk_rows[0].article_id, article_rows[0].id)
        self.assertIn("openai", chunk_rows[0].search_text)
        self.assertIn("detail000", chunk_rows[0].content)

        async with self.session_factory() as session:
            inserted_again = await deduplicate_and_store(session, [article_payload], self.feed_id)

        self.assertEqual(inserted_again, 0)

        async with self.session_factory() as session:
            final_article_count = (
                await session.execute(select(Article.id))
            ).scalars().all()
            final_chunk_count = (
                await session.execute(select(ArticleChunk.id))
            ).scalars().all()

        self.assertEqual(len(final_article_count), 1)
        self.assertEqual(len(final_chunk_count), len(chunk_rows))


if __name__ == "__main__":
    unittest.main()
