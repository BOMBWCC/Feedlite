import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import Article, Feed
from app.routers.feeds import search_articles
from app.services.search_index import build_search_query, build_search_text


class SearchOptimizationTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text("""
                CREATE VIRTUAL TABLE articles_fts USING fts5(
                    search_text,
                    content='articles',
                    content_rowid='id',
                    tokenize='unicode61'
                )
            """))
            await conn.execute(text("""
                CREATE TRIGGER articles_ai AFTER INSERT ON articles BEGIN
                  INSERT INTO articles_fts(rowid, search_text) VALUES (new.id, new.search_text);
                END;
            """))
            await conn.execute(text("""
                CREATE TRIGGER articles_au AFTER UPDATE ON articles BEGIN
                  INSERT INTO articles_fts(articles_fts, rowid, search_text) VALUES ('delete', old.id, old.search_text);
                  INSERT INTO articles_fts(rowid, search_text) VALUES (new.id, new.search_text);
                END;
            """))
            await conn.execute(text("""
                CREATE TRIGGER articles_ad AFTER DELETE ON articles BEGIN
                  INSERT INTO articles_fts(articles_fts, rowid, search_text) VALUES ('delete', old.id, old.search_text);
                END;
            """))

        async with self.session_factory() as session:
            feed_a = Feed(url="https://example.com/a.xml", title="Tech", category=2)
            feed_b = Feed(url="https://example.com/b.xml", title="World", category=1)
            session.add_all([feed_a, feed_b])
            await session.commit()
            await session.refresh(feed_a)
            await session.refresh(feed_b)
            self.feed_a_id = feed_a.id
            self.feed_b_id = feed_b.id

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def _create_article(self, *, feed_id: int, title: str, description: str = "", content: str = "", status: str = "active") -> int:
        async with self.session_factory() as session:
            article = Article(
                feed_id=feed_id,
                title=title,
                link=f"https://example.com/{title}-{feed_id}",
                description=description,
                content=content,
                search_text=build_search_text(title, description),
                published=datetime.now(timezone.utc).isoformat(),
                status=status,
            )
            session.add(article)
            await session.commit()
            await session.refresh(article)
            return article.id

    def test_build_search_helpers_support_chinese_mixed_text_and_sanitized_query(self):
        search_text = build_search_text(
            "<b>OpenAI 发布 GPT-5.4</b>",
            "面向中文搜索优化 &amp; ranking",
            "支持 RSS 正文检索。",
        )
        query = build_search_query('  OpenAI (GPT-5.4) "中文搜索" !!!  ')

        self.assertIn("openai", search_text)
        self.assertIn("gpt", search_text)
        self.assertIn("中文", search_text)
        self.assertIn("搜索", search_text)
        self.assertIn("正文", search_text)
        self.assertEqual(query.split(), ["openai", "gpt", "5", "4", "中文", "搜索", "中文搜索"])

    async def test_search_articles_matches_title_description_and_category(self):
        await self._create_article(
            feed_id=self.feed_a_id,
            title="OpenAI 发布搜索优化方案",
            description="中文搜索召回显著提升",
            content="正文提到 jieba 分词与 FTS5 相关改造",
        )
        await self._create_article(
            feed_id=self.feed_b_id,
            title="国际局势观察",
            description="关注伊朗局势变化",
            content="正文包含 OpenAI 但分类不同",
        )

        async with self.session_factory() as session:
            tech_rows = await search_articles(q='OpenAI !!!', limit=20, category=2, db=session)
            world_rows = await search_articles(q="伊朗局势", limit=20, category=1, db=session)
            content_rows = await search_articles(q="jieba", limit=20, category=None, db=session)

        self.assertEqual(len(tech_rows), 1)
        self.assertEqual(tech_rows[0]["category"], 2)
        self.assertIn("openai", tech_rows[0]["search_excerpt"].lower())
        self.assertEqual(len(world_rows), 1)
        self.assertEqual(world_rows[0]["category"], 1)
        self.assertEqual(content_rows, [])

    async def test_fts_triggers_keep_search_results_in_sync_after_insert_update_delete(self):
        article_id = await self._create_article(
            feed_id=self.feed_a_id,
            title="初始标题",
            description="初始简介",
            content="最初正文",
        )

        async with self.session_factory() as session:
            inserted = await search_articles(q="初始标题", limit=20, category=None, db=session)
        self.assertEqual(len(inserted), 1)

        async with self.session_factory() as session:
            await session.execute(
                update(Article)
                .where(Article.id == article_id)
                .values(
                    title="更新后的中文标题",
                    content="现在正文包含深度搜索能力",
                    search_text=build_search_text("更新后的中文标题", "初始简介"),
                )
            )
            await session.commit()

        async with self.session_factory() as session:
            updated_rows = await search_articles(q="深度搜索", limit=20, category=None, db=session)
            old_rows = await search_articles(q="最初", limit=20, category=None, db=session)
        self.assertEqual(updated_rows, [])
        self.assertEqual(old_rows, [])

        async with self.session_factory() as session:
            article = await session.get(Article, article_id)
            await session.delete(article)
            await session.commit()

        async with self.session_factory() as session:
            deleted_rows = await search_articles(q="深度搜索", limit=20, category=None, db=session)
        self.assertEqual(deleted_rows, [])


if __name__ == "__main__":
    unittest.main()
