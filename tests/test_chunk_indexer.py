import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import Article, ArticleChunk, Feed
from app.services.chunk_indexer import (
    build_article_chunk_payloads,
    rebuild_all_article_chunks,
    rebuild_article_chunks_for_article,
)


class ChunkIndexerTestCase(unittest.IsolatedAsyncioTestCase):
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

    async def _create_article(
        self,
        *,
        title: str,
        description: str,
        content: str,
        translated_title: str = "",
        translated_description: str = "",
    ) -> int:
        async with self.session_factory() as session:
            article = Article(
                feed_id=self.feed_id,
                title=title,
                description=description,
                content=content,
                translated_title=translated_title,
                translated_description=translated_description,
                translation_language="zh-CN" if translated_title or translated_description else None,
                link=f"https://example.com/{title}",
                published=datetime.now(timezone.utc).isoformat(),
                status="active",
            )
            session.add(article)
            await session.commit()
            await session.refresh(article)
            return article.id

    def test_build_article_chunk_payloads_splits_content_and_enriches_search_text(self):
        content = " ".join(f"segment{i:03d}" for i in range(220))

        payloads = build_article_chunk_payloads(
            title="OpenAI ships new API",
            description="English summary for ranking",
            content=content,
            translated_title="OpenAI 发布新 API",
            translated_description="面向中文用户的简介",
            published=datetime.now(timezone.utc).isoformat(),
            chunk_size=180,
            chunk_overlap=30,
            min_chunk_size=40,
        )

        self.assertGreater(len(payloads), 1)
        self.assertEqual(payloads[0]["chunk_index"], 0)
        self.assertEqual(payloads[0]["source_title"], "OpenAI ships new API")
        self.assertIn("openai", payloads[0]["search_text"])
        self.assertIn("发布", payloads[0]["search_text"])
        self.assertGreater(payloads[0]["char_count"], 0)
        self.assertGreater(payloads[0]["token_count"], 0)

    async def test_rebuild_article_chunks_for_article_replaces_existing_chunks(self):
        article_id = await self._create_article(
            title="OpenAI ships new API",
            description="English summary for ranking",
            content=" ".join(f"detail{i:03d}" for i in range(180)),
            translated_title="OpenAI 发布新 API",
            translated_description="面向中文用户的简介",
        )

        async with self.session_factory() as session:
            first_count = await rebuild_article_chunks_for_article(
                session,
                article_id,
                chunk_size=200,
                chunk_overlap=40,
                min_chunk_size=50,
            )

        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(ArticleChunk).where(ArticleChunk.article_id == article_id).order_by(ArticleChunk.chunk_index.asc())
                )
            ).scalars().all()
            self.assertEqual(len(rows), first_count)
            self.assertIn("发布", rows[0].search_text)

            article = await session.get(Article, article_id)
            article.content = "short body only"
            await session.commit()

            second_count = await rebuild_article_chunks_for_article(
                session,
                article_id,
                chunk_size=200,
                chunk_overlap=40,
                min_chunk_size=50,
            )

        self.assertLessEqual(second_count, first_count)

        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(ArticleChunk).where(ArticleChunk.article_id == article_id).order_by(ArticleChunk.chunk_index.asc())
                )
            ).scalars().all()
            self.assertEqual(len(rows), second_count)
            self.assertEqual(rows[0].content, "short body only")

    async def test_rebuild_all_article_chunks_returns_summary(self):
        await self._create_article(
            title="Article One",
            description="Short summary",
            content=" ".join(f"block{i:03d}" for i in range(80)),
        )
        await self._create_article(
            title="Article Two",
            description="Another short summary",
            content="fallback body",
        )

        async with self.session_factory() as session:
            summary = await rebuild_all_article_chunks(
                session,
                chunk_size=220,
                chunk_overlap=40,
                min_chunk_size=40,
            )

        self.assertEqual(summary["articles"], 2)
        self.assertEqual(summary["chunked_articles"], 2)
        self.assertGreaterEqual(summary["chunks"], 2)


if __name__ == "__main__":
    unittest.main()
