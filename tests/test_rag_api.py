import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.auth_deps import verify_rag_api_key
from app.database import Base
from app.models import Article, ArticleChunk, Feed
from app.routers.rag import get_rag_context, search_rag_chunks
from app.services.search_index import build_search_text


class RagApiTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.rag_key = "test-rag-key"
        self.previous_rag_key = os.environ.get("RAG_API_KEY")
        os.environ["RAG_API_KEY"] = self.rag_key

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text("""
                CREATE VIRTUAL TABLE article_chunks_fts USING fts5(
                    search_text,
                    content='article_chunks',
                    content_rowid='id',
                    tokenize='unicode61'
                )
            """))
            await conn.execute(text("""
                CREATE TRIGGER article_chunks_ai AFTER INSERT ON article_chunks BEGIN
                  INSERT INTO article_chunks_fts(rowid, search_text) VALUES (new.id, new.search_text);
                END;
            """))
            await conn.execute(text("""
                CREATE TRIGGER article_chunks_au AFTER UPDATE ON article_chunks BEGIN
                  INSERT INTO article_chunks_fts(article_chunks_fts, rowid, search_text) VALUES ('delete', old.id, old.search_text);
                  INSERT INTO article_chunks_fts(rowid, search_text) VALUES (new.id, new.search_text);
                END;
            """))
            await conn.execute(text("""
                CREATE TRIGGER article_chunks_ad AFTER DELETE ON article_chunks BEGIN
                  INSERT INTO article_chunks_fts(article_chunks_fts, rowid, search_text) VALUES ('delete', old.id, old.search_text);
                END;
            """))

        async with self.session_factory() as session:
            feed = Feed(url="https://example.com/rss.xml", title="Example", category=2)
            world_feed = Feed(url="https://example.com/world.xml", title="World", category=1)
            session.add_all([feed, world_feed])
            await session.commit()
            await session.refresh(feed)
            await session.refresh(world_feed)

            active_article = Article(
                feed_id=feed.id,
                title="OpenAI ships new API",
                description="English summary",
                content="long body",
                link="https://example.com/openai",
                published=datetime.now(timezone.utc).isoformat(),
                ai_score=88,
                status="active",
            )
            filtered_article = Article(
                feed_id=feed.id,
                title="Filtered report",
                description="Only for internal RAG checks",
                content="filtered body",
                link="https://example.com/filtered",
                published=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
                ai_score=12,
                status="filtered",
            )
            old_world_article = Article(
                feed_id=world_feed.id,
                title="OpenAI old report",
                description="Historical archive item",
                content="old body",
                link="https://example.com/openai-old",
                published=(datetime.now(timezone.utc) - timedelta(days=45)).isoformat(),
                ai_score=52,
                status="active",
            )
            session.add_all([active_article, filtered_article, old_world_article])
            await session.commit()
            await session.refresh(active_article)
            await session.refresh(filtered_article)
            await session.refresh(old_world_article)

            session.add_all(
                [
                    ArticleChunk(
                        article_id=active_article.id,
                        chunk_index=0,
                        content="OpenAI overview and release context",
                        search_text=build_search_text(
                            title="OpenAI ships new API",
                            description="English summary",
                            content="OpenAI overview and release context",
                        ),
                        char_count=35,
                        token_count=5,
                        source_title="OpenAI ships new API",
                        source_description="English summary",
                        published=active_article.published,
                    ),
                    ArticleChunk(
                        article_id=active_article.id,
                        chunk_index=1,
                        content="OpenAI ships new API for agents and workflows",
                        search_text=build_search_text(
                            title="OpenAI ships new API",
                            description="English summary",
                            content="OpenAI ships new API for agents and workflows",
                        ),
                        char_count=48,
                        token_count=9,
                        source_title="OpenAI ships new API",
                        source_description="English summary",
                        published=active_article.published,
                    ),
                    ArticleChunk(
                        article_id=active_article.id,
                        chunk_index=2,
                        content="Follow-up details about rollout and tooling support",
                        search_text=build_search_text(
                            title="OpenAI ships new API",
                            description="English summary",
                            content="Follow-up details about rollout and tooling support",
                        ),
                        char_count=50,
                        token_count=7,
                        source_title="OpenAI ships new API",
                        source_description="English summary",
                        published=active_article.published,
                    ),
                    ArticleChunk(
                        article_id=filtered_article.id,
                        chunk_index=0,
                        content="filtered body for internal checks",
                        search_text=build_search_text(
                            title="Filtered report",
                            description="Only for internal RAG checks",
                            content="filtered body for internal checks",
                        ),
                        char_count=31,
                        token_count=5,
                        source_title="Filtered report",
                        source_description="Only for internal RAG checks",
                        published=filtered_article.published,
                    ),
                    ArticleChunk(
                        article_id=old_world_article.id,
                        chunk_index=0,
                        content="OpenAI old report kept for archive lookups",
                        search_text=build_search_text(
                            title="OpenAI old report",
                            description="Historical archive item",
                            content="OpenAI old report kept for archive lookups",
                        ),
                        char_count=42,
                        token_count=7,
                        source_title="OpenAI old report",
                        source_description="Historical archive item",
                        published=old_world_article.published,
                    ),
                ]
            )
            await session.commit()

            active_chunk_rows = (
                await session.execute(
                    select(ArticleChunk)
                    .where(ArticleChunk.article_id == active_article.id)
                    .order_by(ArticleChunk.chunk_index.asc())
                )
            ).scalars().all()
            self.active_chunk_ids = [row.id for row in active_chunk_rows]
            self.filtered_chunk_id = (
                await session.execute(
                    select(ArticleChunk.id).where(ArticleChunk.article_id == filtered_article.id)
                )
            ).scalar_one()

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp_dir.cleanup()
        if self.previous_rag_key is None:
            os.environ.pop("RAG_API_KEY", None)
        else:
            os.environ["RAG_API_KEY"] = self.previous_rag_key

    def _build_request(self, headers: list[tuple[bytes, bytes]] | None = None) -> Request:
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/rag/search",
                "headers": headers or [],
            }
        )

    async def test_verify_rag_api_key_requires_header(self):
        with self.assertRaises(HTTPException) as ctx:
            await verify_rag_api_key(self._build_request())
        self.assertEqual(ctx.exception.status_code, 401)

    async def test_search_rag_chunks_returns_active_rows(self):
        async with self.session_factory() as session:
            payload = await search_rag_chunks(
                q="openai",
                limit=1,
                category=None,
                days=30,
                include_filtered=False,
                db=session,
            )

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["items"][0]["title"], "OpenAI ships new API")
        self.assertEqual(payload["items"][0]["article_status"], "active")
        self.assertEqual(payload["filters"]["days"], 30)
        self.assertIsNotNone(payload["filters"]["cutoff"])

    async def test_search_rag_chunks_can_filter_by_category_and_disable_time_window(self):
        async with self.session_factory() as session:
            payload = await search_rag_chunks(
                q="openai",
                limit=1,
                category=1,
                days=0,
                include_filtered=False,
                db=session,
            )

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["items"][0]["title"], "OpenAI old report")
        self.assertEqual(payload["items"][0]["category"], 1)
        self.assertIsNone(payload["filters"]["cutoff"])

    async def test_search_rag_chunks_can_include_filtered_rows(self):
        async with self.session_factory() as session:
            payload = await search_rag_chunks(
                q="internal",
                limit=1,
                category=None,
                days=30,
                include_filtered=True,
                db=session,
            )

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["items"][0]["article_status"], "filtered")

    async def test_get_rag_context_returns_requested_chunk_with_neighbors(self):
        async with self.session_factory() as session:
            payload = await get_rag_context(
                chunk_ids=[self.active_chunk_ids[1]],
                window=1,
                include_filtered=False,
                db=session,
            )

        self.assertEqual(payload["requested_chunk_ids"], [self.active_chunk_ids[1]])
        self.assertEqual(payload["resolved_chunk_ids"], [self.active_chunk_ids[1]])
        self.assertEqual(payload["missing_chunk_ids"], [])
        self.assertEqual(payload["count"], 3)
        self.assertEqual(
            [item["chunk_index"] for item in payload["items"]],
            [0, 1, 2],
        )
        requested_flags = [item["is_requested"] for item in payload["items"]]
        self.assertEqual(requested_flags, [False, True, False])

    async def test_get_rag_context_respects_filtered_flag(self):
        async with self.session_factory() as session:
            hidden_payload = await get_rag_context(
                chunk_ids=[self.filtered_chunk_id],
                window=0,
                include_filtered=False,
                db=session,
            )
            visible_payload = await get_rag_context(
                chunk_ids=[self.filtered_chunk_id],
                window=0,
                include_filtered=True,
                db=session,
            )

        self.assertEqual(hidden_payload["count"], 0)
        self.assertEqual(hidden_payload["missing_chunk_ids"], [self.filtered_chunk_id])
        self.assertEqual(visible_payload["count"], 1)
        self.assertEqual(visible_payload["items"][0]["article_status"], "filtered")


if __name__ == "__main__":
    unittest.main()
