import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import AiModel, AppConfig, Article, Feed, User, UserProfile
from app.services.ai_scorer import _build_scoring_prompt, score_unscored_articles
from app.services.translator import prepare_articles_for_scoring


class AiScorerTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with self.session_factory() as session:
            user = User(username="tester", password_hash="x")
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
            session.add(
                UserProfile(
                    user_id=user.id,
                    active_tags="伊朗战争,AI",
                    base_prompt="用户长期关注国际局势与技术趋势，对无关娱乐新闻兴趣较低。",
                )
            )
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

    async def _set_translation_config(self, *, enabled: str = "true", target_language: str = "zh-CN"):
        async with self.session_factory() as session:
            session.add_all(
                [
                    AppConfig(key="translation.enabled", value=enabled),
                    AppConfig(key="translation.target_language", value=target_language),
                    AppConfig(key="translation.translate_title", value="true"),
                    AppConfig(key="translation.translate_description", value="true"),
                ]
            )
            await session.commit()

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
        high_id = await self._create_article("高优先新闻", "与用户偏好相关的重要科技快讯")
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
        self.assertIn("简介: 与用户偏好相关的重要科技快讯", captured["messages"][1]["content"])

        async with self.session_factory() as session:
            rows = (await session.execute(select(Article).order_by(Article.id.asc()))).scalars().all()

        by_id = {row.id: row for row in rows}
        self.assertEqual(by_id[min(high_id, low_id)].ai_score, 12)
        self.assertEqual(by_id[min(high_id, low_id)].status, "filtered")
        self.assertEqual(by_id[min(high_id, low_id)].decision_type, "filtered")
        self.assertEqual(by_id[min(high_id, low_id)].recommend_level, "low")
        self.assertEqual(by_id[max(high_id, low_id)].ai_score, 88)
        self.assertEqual(by_id[max(high_id, low_id)].status, "active")
        self.assertEqual(by_id[max(high_id, low_id)].decision_type, "profile")
        self.assertEqual(by_id[max(high_id, low_id)].recommend_level, "high")

    async def test_score_unscored_articles_prefers_translated_content_for_scoring(self):
        article_id = await self._create_article("OpenAI ships new API", "English summary for translation")
        await self._set_translation_config(enabled="true", target_language="zh-CN")

        captured = {}

        async def fake_prepare_articles_for_scoring(db, batch):
            translated = []
            for item in batch:
                translated.append(
                    {
                        **item,
                        "title": "OpenAI 发布新 API",
                        "description": "面向中文用户的翻译简介",
                    }
                )
            return translated

        def fake_call_llm(messages, config):
            captured["messages"] = messages
            return json.dumps([{"id": article_id, "score": 91}])

        with patch("app.services.translator.prepare_articles_for_scoring", side_effect=fake_prepare_articles_for_scoring), \
             patch("app.services.ai_scorer._call_llm", side_effect=fake_call_llm):
            async with self.session_factory() as session:
                summary = await score_unscored_articles(session)

        self.assertEqual(summary["scored"], 1)
        self.assertIn("标题: OpenAI 发布新 API", captured["messages"][1]["content"])
        self.assertIn("简介: 面向中文用户的翻译简介", captured["messages"][1]["content"])

    async def test_tag_matched_article_stays_active_even_with_low_model_score(self):
        article_id = await self._create_article("伊朗战争局势再升级", "中东局势出现新进展")

        def fake_call_llm(messages, config):
            return json.dumps([{"id": article_id, "score": 12}])

        with patch("app.services.ai_scorer._call_llm", side_effect=fake_call_llm):
            async with self.session_factory() as session:
                summary = await score_unscored_articles(session)

        self.assertEqual(summary["scored"], 1)
        self.assertEqual(summary["filtered"], 0)

        async with self.session_factory() as session:
            article = await session.get(Article, article_id)

        self.assertEqual(article.status, "active")
        self.assertEqual(article.ai_score, 60)
        self.assertEqual(article.decision_type, "tag")
        self.assertEqual(article.recommend_level, "medium")

    async def test_prepare_articles_for_scoring_retries_with_smaller_batches_when_json_is_truncated(self):
        first_id = await self._create_article("OpenAI launches agent tools", "A long English summary for the first article.")
        second_id = await self._create_article("Anthropic updates Claude", "A long English summary for the second article.")
        await self._set_translation_config(enabled="true", target_language="zh-CN")

        calls = []

        def fake_call_llm(messages, config):
            user_prompt = messages[1]["content"]
            calls.append(
                {
                    "prompt": user_prompt,
                    "max_tokens": config.get("max_tokens"),
                }
            )

            if f"[ID:{first_id}]" in user_prompt and f"[ID:{second_id}]" in user_prompt:
                return '[{"id": 1, "translated_title": "截断'

            if f"[ID:{first_id}]" in user_prompt:
                return json.dumps(
                    [
                        {
                            "id": first_id,
                            "translated_title": "OpenAI 发布代理工具",
                            "translated_description": "第一篇文章的中文简介",
                        }
                    ]
                )

            return json.dumps(
                [
                    {
                        "id": second_id,
                        "translated_title": "Anthropic 更新 Claude",
                        "translated_description": "第二篇文章的中文简介",
                    }
                ]
            )

        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(Article).where(Article.id.in_([first_id, second_id])).order_by(Article.id.asc())
                )
            ).scalars().all()
            batch = [
                {
                    "id": row.id,
                    "title": row.title,
                    "description": row.description or "",
                    "translated_title": row.translated_title or "",
                    "translated_description": row.translated_description or "",
                    "translation_language": row.translation_language or "",
                    "translation_status": row.translation_status or "",
                    "translation_updated_at": row.translation_updated_at,
                    "matched_tags": [],
                }
                for row in rows
            ]

            with patch("app.services.ai_scorer._call_llm", side_effect=fake_call_llm):
                translated_batch = await prepare_articles_for_scoring(session, batch)

        self.assertEqual(len(calls), 3)
        self.assertTrue(all(call["max_tokens"] == 4000 for call in calls))

        by_id = {item["id"]: item for item in translated_batch}
        self.assertEqual(by_id[first_id]["title"], "OpenAI 发布代理工具")
        self.assertEqual(by_id[first_id]["description"], "第一篇文章的中文简介")
        self.assertEqual(by_id[second_id]["title"], "Anthropic 更新 Claude")
        self.assertEqual(by_id[second_id]["description"], "第二篇文章的中文简介")

        async with self.session_factory() as session:
            refreshed = (
                await session.execute(
                    select(Article).where(Article.id.in_([first_id, second_id])).order_by(Article.id.asc())
                )
            ).scalars().all()

        refreshed_by_id = {row.id: row for row in refreshed}
        self.assertEqual(refreshed_by_id[first_id].translation_status, "done")
        self.assertEqual(refreshed_by_id[second_id].translation_status, "done")
        self.assertEqual(refreshed_by_id[first_id].translated_title, "OpenAI 发布代理工具")
        self.assertEqual(refreshed_by_id[second_id].translated_title, "Anthropic 更新 Claude")


if __name__ == "__main__":
    unittest.main()
