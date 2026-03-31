import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import Article, Feed, User
from app.routers.feeds import update_feedback
from app.routers.profile import add_tag, delete_tag
from app.services.profiler import _get_profile_samples, generate_user_profile


class ProfileLogicTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with self.session_factory() as session:
            user = User(username="tester", password_hash="x", active_tags="AI, RSS", base_prompt="旧画像")
            feed = Feed(url="https://example.com/rss.xml", title="Example Feed", category=7)
            session.add_all([user, feed])
            await session.commit()
            await session.refresh(feed)
            self.feed_id = feed.id

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def _create_article(
        self,
        title: str,
        feedback: int = 0,
        created_at: str | None = None,
        feedback_updated_at: str | None = None,
        published: str | None = None,
    ) -> int:
        async with self.session_factory() as session:
            article = Article(
                feed_id=self.feed_id,
                title=title,
                link=f"https://example.com/{title}",
                description=f"{title} description",
                content="",
                published=published or datetime.now(timezone.utc).isoformat(),
                feedback=feedback,
                feedback_updated_at=feedback_updated_at,
                created_at=created_at or datetime.now(timezone.utc).isoformat(),
            )
            session.add(article)
            await session.commit()
            await session.refresh(article)
            return article.id

    async def test_update_feedback_writes_feedback_updated_at(self):
        article_id = await self._create_article("feedback-write")

        async with self.session_factory() as session:
            payload = await update_feedback(article_id=article_id, type=1, db=session)
            self.assertEqual(payload["feedback"], 1)
            self.assertIsNotNone(payload["feedback_updated_at"])

        async with self.session_factory() as session:
            article = await session.get(Article, article_id)
            self.assertEqual(article.feedback, 1)
            self.assertIsNotNone(article.feedback_updated_at)

        async with self.session_factory() as session:
            payload = await update_feedback(article_id=article_id, type=0, db=session)
            self.assertEqual(payload["feedback"], 0)
            self.assertIsNone(payload["feedback_updated_at"])

        async with self.session_factory() as session:
            article = await session.get(Article, article_id)
            self.assertEqual(article.feedback, 0)
            self.assertIsNone(article.feedback_updated_at)

    async def test_get_profile_samples_uses_feedback_window_and_category(self):
        now = datetime.now(timezone.utc)
        within_window = (now - timedelta(days=2)).isoformat()
        outside_window = (now - timedelta(days=10)).isoformat()

        await self._create_article(
            "liked-recent",
            feedback=1,
            created_at=outside_window,
            feedback_updated_at=within_window,
            published=within_window,
        )
        await self._create_article(
            "disliked-recent",
            feedback=-1,
            created_at=within_window,
            feedback_updated_at=within_window,
            published=within_window,
        )
        await self._create_article(
            "liked-old-feedback",
            feedback=1,
            created_at=within_window,
            feedback_updated_at=outside_window,
            published=outside_window,
        )

        async with self.session_factory() as session:
            samples = await _get_profile_samples(session, days=7)

        self.assertEqual(len(samples["liked"]), 1)
        self.assertEqual(len(samples["disliked"]), 1)
        self.assertEqual(samples["liked"][0]["title"], "liked-recent")
        self.assertEqual(samples["liked"][0]["category"], 7)
        self.assertTrue(samples["liked"][0]["published"].endswith("Z"))
        self.assertEqual(samples["disliked"][0]["title"], "disliked-recent")

    async def test_generate_user_profile_updates_base_prompt(self):
        now = datetime.now(timezone.utc).isoformat()
        await self._create_article("liked", feedback=1, feedback_updated_at=now, published=now)
        await self._create_article("disliked", feedback=-1, feedback_updated_at=now, published=now)

        with patch("app.services.profiler._get_ai_config", return_value={"provider": "gemini", "api_key": "x"}), \
             patch("app.services.profiler._call_profiler", return_value=json.dumps({"profile": "新的用户画像"})):
            async with self.session_factory() as session:
                summary = await generate_user_profile(session, days=7)

        self.assertTrue(summary["updated"])
        self.assertEqual(summary["liked_count"], 1)
        self.assertEqual(summary["disliked_count"], 1)
        self.assertEqual(summary["profile"], "新的用户画像")

        async with self.session_factory() as session:
            result = await session.execute(select(User).limit(1))
            user = result.scalar_one()
            self.assertEqual(user.base_prompt, "新的用户画像")

    async def test_add_and_delete_tag(self):
        async with self.session_factory() as session:
            added = await add_tag(type("TagPayload", (), {"tag": "伊朗战争"})(), db=session)
            self.assertIn("伊朗战争", added["active_tags"])

        async with self.session_factory() as session:
            duplicate = await add_tag(type("TagPayload", (), {"tag": "伊朗战争"})(), db=session)
            tags = [tag for tag in duplicate["active_tags"].split(",") if tag]
            self.assertEqual(tags.count("伊朗战争"), 1)

        async with self.session_factory() as session:
            deleted = await delete_tag(tag="伊朗战争", db=session)
            self.assertNotIn("伊朗战争", deleted["active_tags"])


if __name__ == "__main__":
    unittest.main()
