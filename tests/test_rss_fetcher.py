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

    async def test_same_article_link_is_scoped_to_each_feed(self):
        published = datetime.now(timezone.utc).isoformat()
        shared_link = "https://publisher.example/shared-story"
        article_payload = {
            "title": "Shared story",
            "link": shared_link,
            "description": "Same canonical link published by two configured sources",
            "content": "body",
            "published": published,
        }

        async with self.session_factory() as session:
            second_feed = Feed(url="https://second.example/rss.xml", title="Second", category=2)
            session.add(second_feed)
            await session.commit()
            await session.refresh(second_feed)
            second_feed_id = second_feed.id

            first_inserted = await deduplicate_and_store(session, [article_payload], self.feed_id)
            second_inserted = await deduplicate_and_store(session, [article_payload], second_feed_id)

        self.assertEqual(first_inserted, 1)
        self.assertEqual(second_inserted, 1)

        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(Article).where(Article.link == shared_link).order_by(Article.feed_id)
                )
            ).scalars().all()

        self.assertEqual([row.feed_id for row in rows], [self.feed_id, second_feed_id])


class RssParsingBoundsTestCase(unittest.TestCase):
    def test_feed_entry_count_and_fields_are_bounded_before_storage(self):
        from app.services.rss_fetcher import parse_feed_content

        oversized_item = f"""
            <item>
                <title>{'t' * 900}</title>
                <link>https://example.com/{'a' * 3000}</link>
                <description>{'d' * 120000}</description>
            </item>
        """
        ordinary_items = "".join(
            f"<item><title>item-{index}</title><link>https://example.com/{index}</link><description>body</description></item>"
            for index in range(200)
        )
        payload = f"""
            <rss version="2.0">
                <channel>
                    <title>{'f' * 400}</title>
                    {oversized_item}
                    {ordinary_items}
                </channel>
            </rss>
        """.encode()

        parsed = parse_feed_content(payload, enforce_retention=False)

        self.assertEqual(len(parsed["articles"]), 200)
        self.assertEqual(len(parsed["feed_title"]), 200)
        first = parsed["articles"][0]
        self.assertEqual(len(first["title"]), 500)
        self.assertEqual(len(first["link"]), 2048)
        self.assertEqual(len(first["description"]), 1000)
        self.assertEqual(len(first["content"]), 100000)

    def test_feed_parser_ignores_non_http_article_links(self):
        from app.services.rss_fetcher import parse_feed_content

        payload = b"""
            <rss version="2.0">
                <channel>
                    <title>Links</title>
                    <item><title>Unsafe</title><link>javascript:alert(1)</link><description>bad</description></item>
                    <item><title>Safe</title><link>https://example.com/safe</link><description>good</description></item>
                </channel>
            </rss>
        """

        parsed = parse_feed_content(payload, enforce_retention=False)

        self.assertEqual([article["title"] for article in parsed["articles"]], ["Safe"])


if __name__ == "__main__":
    unittest.main()
