import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import AiModel, Article, Feed, User
from app.services.ai_scorer import _build_scoring_prompt, score_unscored_articles


class AiScorerTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with self.session_factory() as session:
            user = User(
                username="tester",
                password_hash="x",
                active_tags="伊朗战争,AI",
                base_prompt="用户长期关注国际局势与技术趋势，对无关娱乐新闻兴趣较低。",
            )
            feed = Feed(url="https://example.com/rss.xml", title="Example Feed", category=2)
            ai_model = AiModel(
                role="scorer",
                provider="gemini",
                model_name="gemini-1.5-flash",
                api_base="https://example.com/v1beta",
                api_key="test-key",
            )
            session.add_all([user, feed, ai_model])
            await session.commit()
            await session.refresh(feed)
            self.feed_id = feed.id

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def _create_article(self, title: str, description: str) -> int:
        async with self.session_factory() as session:
            article = Article(
                feed_id=self.feed_id,
                title=title,
                link=f"https://example.com/{title}",
                description=description,
                content="",
                published=datetime.now(timezone.utc).isoformat(),
                ai_score=0,
                status="active",
            )
            session.add(article)
            await session.commit()
            await session.refresh(article)
            return article.id

    def test_build_scoring_prompt_contains_tags_profile_and_article_summary(self):
        messages = _build_scoring_prompt(
            [
                {
                    "id": 101,
                    "title": "伊朗局势升级",
                    "description": "以色列与伊朗冲突出现新进展，地区风险快速抬升。",
                }
            ],
            {
                "active_tags": "伊朗战争,AI",
                "base_prompt": "用户长期关注国际局势与技术趋势。",
            },
        )

        self.assertEqual(len(messages), 2)
        system_prompt = messages[0]["content"]
        user_prompt = messages[1]["content"]

        self.assertIn("伊朗战争,AI", system_prompt)
        self.assertIn("用户长期关注国际局势与技术趋势。", system_prompt)
        self.assertIn("优先级规则", system_prompt)
        self.assertIn("标签（Tag）优先级最高", system_prompt)
        self.assertIn("标题: 伊朗局势升级", user_prompt)
        self.assertIn("简介: 以色列与伊朗冲突出现新进展", user_prompt)

    async def test_score_unscored_articles_updates_scores_and_statuses(self):
        high_id = await self._create_article("高优先新闻", "与伊朗战争直接相关的重要快讯")
        low_id = await self._create_article("低优先新闻", "普通娱乐内容，与用户偏好无关")

        captured = {}

        def fake_call_llm(messages, config):
            captured["messages"] = messages
            captured["config"] = config
            return json.dumps(
                [
                    {"id": max(high_id, low_id), "score": 88},
                    {"id": min(high_id, low_id), "score": 12},
                ]
            )

        with patch("app.services.ai_scorer._call_llm", side_effect=fake_call_llm):
            async with self.session_factory() as session:
                summary = await score_unscored_articles(session)

        self.assertEqual(summary["scored"], 2)
        self.assertEqual(summary["filtered"], 1)
        self.assertEqual(summary["skipped"], 0)
        self.assertIsNone(summary["error"])
        self.assertIn("标签（Tag）优先级最高", captured["messages"][0]["content"])
        self.assertIn("用户长期关注国际局势与技术趋势", captured["messages"][0]["content"])
        self.assertIn("标题: 高优先新闻", captured["messages"][1]["content"])
        self.assertIn("简介: 与伊朗战争直接相关的重要快讯", captured["messages"][1]["content"])

        async with self.session_factory() as session:
            rows = (await session.execute(select(Article).order_by(Article.id.asc()))).scalars().all()

        by_id = {row.id: row for row in rows}
        self.assertEqual(by_id[min(high_id, low_id)].ai_score, 12)
        self.assertEqual(by_id[min(high_id, low_id)].status, "filtered")
        self.assertEqual(by_id[max(high_id, low_id)].ai_score, 88)
        self.assertEqual(by_id[max(high_id, low_id)].status, "active")


if __name__ == "__main__":
    unittest.main()
