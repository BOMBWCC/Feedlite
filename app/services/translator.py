"""
Translator Service
核心职责：读取翻译配置，对待评分文章执行标题/简介翻译，并把译文写回数据库。
"""

import json
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppConfig, Article

logger = logging.getLogger("feedlite.translator")


def _to_bool(value: str | bool | None, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


async def get_translation_config(db: AsyncSession) -> dict:
    stmt = select(AppConfig).where(
        AppConfig.key.in_(
            [
                "translation.enabled",
                "translation.target_language",
                "translation.translate_title",
                "translation.translate_description",
            ]
        )
    )
    result = await db.execute(stmt)
    rows = {row.key: row.value for row in result.scalars().all()}
    return {
        "enabled": _to_bool(rows.get("translation.enabled"), True),
        "target_language": rows.get("translation.target_language", "zh-CN") or "zh-CN",
        "translate_title": _to_bool(rows.get("translation.translate_title"), True),
        "translate_description": _to_bool(rows.get("translation.translate_description"), True),
    }


def _matches_target_language(text: str, target_language: str) -> bool:
    text = (text or "").strip()
    if not text:
        return True

    if target_language.lower().startswith("zh"):
        cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
        latin_count = len(re.findall(r"[A-Za-z]", text))
        return cjk_count >= max(2, latin_count)

    if target_language.lower().startswith("ja"):
        return bool(re.search(r"[\u3040-\u30ff]", text))

    if target_language.lower().startswith("en"):
        latin_count = len(re.findall(r"[A-Za-z]", text))
        cjk_or_kana_count = len(re.findall(r"[\u3040-\u30ff\u4e00-\u9fff]", text))
        return latin_count > 0 and latin_count >= cjk_or_kana_count

    return False


def _build_translation_prompt(articles: list[dict], config: dict) -> list[dict]:
    target_language = config["target_language"]
    user_prompt = "\n\n".join(
        [
            (
                f"[ID:{article['id']}]\n"
                f"title: {article['title'] or ''}\n"
                f"description: {article['description'] or ''}"
            )
            for article in articles
        ]
    )
    system_prompt = f"""
你是一个新闻翻译助手。

请将输入文章的标题和简介翻译成目标语言：{target_language}。
要求：
- 只输出严格 JSON 数组，不要输出解释。
- 保留原意，不要总结或扩写。
- 若原文已经是目标语言，也输出原文。
- 返回格式：
  [{{"id": 文章ID, "translated_title": "...", "translated_description": "..."}}]
""".strip()

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _parse_translation_response(raw_response: str) -> dict[int, dict]:
    text = raw_response.strip()
    if "```" in text:
        match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Translator 返回的不是有效 JSON: {text[:200]}") from exc

    result = {}
    for item in payload:
        article_id = item.get("id")
        if article_id is None:
            continue
        result[int(article_id)] = {
            "translated_title": (item.get("translated_title") or "").strip(),
            "translated_description": (item.get("translated_description") or "").strip(),
        }
    return result


async def prepare_articles_for_scoring(db: AsyncSession, articles: list[dict]) -> list[dict]:
    """根据翻译配置准备打分输入，并将译文结果持久化。"""
    if not articles:
        return articles

    config = await get_translation_config(db)
    target_language = config["target_language"]
    now = datetime.now(timezone.utc).isoformat()

    articles_for_translation = []
    prepared_articles = []

    for article in articles:
        translated_title = article.get("translated_title") or ""
        translated_description = article.get("translated_description") or ""
        translation_language = article.get("translation_language") or ""

        title_ready = (
            translated_title
            and translation_language == target_language
            and config["translate_title"]
        )
        description_ready = (
            translated_description
            and translation_language == target_language
            and config["translate_description"]
        )

        title_needs_translation = (
            config["enabled"]
            and config["translate_title"]
            and article.get("title")
            and not title_ready
            and not _matches_target_language(article.get("title", ""), target_language)
        )
        description_needs_translation = (
            config["enabled"]
            and config["translate_description"]
            and article.get("description")
            and not description_ready
            and not _matches_target_language(article.get("description", ""), target_language)
        )

        if title_needs_translation or description_needs_translation:
            articles_for_translation.append(
                {
                    "id": article["id"],
                    "title": article.get("title", "") if title_needs_translation else (translated_title or article.get("title", "")),
                    "description": article.get("description", "") if description_needs_translation else (translated_description or article.get("description", "")),
                    "source_title": article.get("title", ""),
                    "source_description": article.get("description", ""),
                }
            )
        else:
            next_status = "skipped" if config["enabled"] else article.get("translation_status") or "pending"
            await db.execute(
                update(Article)
                .where(Article.id == article["id"])
                .values(
                    translation_status=next_status,
                    translation_language=target_language if config["enabled"] else article.get("translation_language"),
                    translation_updated_at=now if config["enabled"] else article.get("translation_updated_at"),
                )
            )

        prepared_articles.append(
            {
                **article,
                "title": translated_title if title_ready else article.get("title", ""),
                "description": translated_description if description_ready else article.get("description", ""),
            }
        )

    if not articles_for_translation:
        await db.commit()
        return prepared_articles

    from app.services.ai_scorer import _call_llm, _get_ai_config

    ai_config = await _get_ai_config(db, role="scorer")
    messages = _build_translation_prompt(articles_for_translation, config)
    raw_response = _call_llm(messages, ai_config)
    translated_map = _parse_translation_response(raw_response)

    for item in prepared_articles:
        translated = translated_map.get(item["id"])
        if translated:
            title_value = translated["translated_title"] or item.get("title", "")
            desc_value = translated["translated_description"] or item.get("description", "")
            item["title"] = title_value
            item["description"] = desc_value
            await db.execute(
                update(Article)
                .where(Article.id == item["id"])
                .values(
                    translated_title=title_value,
                    translated_description=desc_value,
                    translation_language=target_language,
                    translation_status="done",
                    translation_updated_at=now,
                )
            )
        else:
            await db.execute(
                update(Article)
                .where(Article.id == item["id"])
                .values(
                    translation_language=target_language,
                    translation_status="failed",
                    translation_updated_at=now,
                )
            )

    await db.commit()
    return prepared_articles
