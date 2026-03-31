"""
Profiler Service
核心职责：读取最近一周正负反馈文章与上一版画像，调用 Profiler 模型生成新的用户画像。
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Article, Feed, ProfileHistory, User, UserProfile
from app.services.ai_scorer import _get_ai_config

logger = logging.getLogger("feedlite.profiler")

PROFILE_WINDOW_DAYS = 7
PROFILE_HISTORY_LIMIT = 4
MAX_DESCRIPTION_LEN = 240


def _normalize_utc_text(value: str) -> str:
    """将数据库中的 ISO 时间统一转为 UTC 文本，避免部署机器时区干扰。"""
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return value


async def _get_profile_samples(db: AsyncSession, days: int = PROFILE_WINDOW_DAYS) -> dict:
    """读取最近 N 天的正负反馈文章样本，仅保留画像生成所需字段。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = (
        select(
            Article.title,
            Article.description,
            Article.feedback,
            Article.published,
            Article.feedback_updated_at,
            Feed.category,
        )
        .join(Feed, Feed.id == Article.feed_id)
        .where(Article.feedback.in_([1, -1]))
        .where(Article.feedback_updated_at.is_not(None))
        .where(Article.feedback_updated_at >= cutoff.isoformat())
        .order_by(Article.feedback_updated_at.desc(), Article.id.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    samples = {"liked": [], "disliked": []}
    for row in rows:
        item = {
            "title": row.title or "无标题",
            "description": (row.description or "")[:MAX_DESCRIPTION_LEN],
            "category": row.category,
            "published": _normalize_utc_text(row.published or row.feedback_updated_at or ""),
        }
        bucket = "liked" if row.feedback == 1 else "disliked"
        samples[bucket].append(item)
    return samples


async def _get_profile_history(db: AsyncSession, user_id: int, limit: int = PROFILE_HISTORY_LIMIT) -> list[dict]:
    """读取最近几次画像历史快照，按时间倒序返回。"""
    stmt = (
        select(ProfileHistory.profile_text, ProfileHistory.created_at)
        .where(ProfileHistory.user_id == user_id)
        .order_by(ProfileHistory.created_at.desc(), ProfileHistory.id.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.all()
    return [
        {
            "profile": row.profile_text,
            "created_at": _normalize_utc_text(row.created_at or ""),
        }
        for row in rows
    ]


def _build_profile_prompt(
    liked_articles: list[dict],
    disliked_articles: list[dict],
    previous_profile: str,
    profile_history: list[dict] | None = None,
) -> list[dict]:
    """组装 Profiler 提示词，基于正负反馈、上一版画像和最近几周画像历史生成新的用户画像。"""
    previous_profile = (previous_profile or "").strip()
    profile_history = profile_history or []

    def _render_articles(title: str, articles: list[dict]) -> str:
        if not articles:
            return f"{title}：无"
        lines = [title + "："]
        for idx, article in enumerate(articles, start=1):
            lines.append(
                (
                    f"{idx}. 标题: {article['title']}\n"
                    f"   简介: {article['description'] or '无'}\n"
                    f"   category: {article['category']}\n"
                    f"   published(UTC): {article['published']}"
                )
            )
        return "\n".join(lines)

    def _render_history(histories: list[dict]) -> str:
        if not histories:
            return "最近几周画像历史：无"
        lines = ["最近几周画像历史："]
        for idx, item in enumerate(histories, start=1):
            lines.append(
                f"{idx}. generated_at(UTC): {item['created_at']}\n"
                f"   profile: {item['profile']}"
            )
        return "\n".join(lines)

    system_prompt = """
你是一个用户兴趣画像分析助手。

你的任务是根据：
1. 最近一周用户明确喜欢的文章
2. 最近一周用户明确不喜欢的文章
3. 上一版用户画像
4. 最近几周画像历史

生成一版更新后的“用户画像”。

要求：
- 只输出用户画像，不要输出解释、摘要、标签列表或其他字段。
- 新画像要继承上一版画像中仍然成立的偏好，不要每次都完全推翻。
- 要把最近几周稳定出现的兴趣方向视为长期偏好，避免因单周样本波动导致画像漂移过大。
- 要根据喜欢与不喜欢的样本，明确用户偏好和排斥方向。
- 画像应该适合后续给新闻筛选模型直接使用。
- 返回必须是严格 JSON，格式如下：
  {"profile": "..."}
""".strip()

    user_prompt = "\n\n".join(
        [
            f"上一版用户画像：{previous_profile or '无'}",
            _render_history(profile_history),
            _render_articles("最近一周喜欢的文章", liked_articles),
            _render_articles("最近一周不喜欢的文章", disliked_articles),
        ]
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _call_profiler(messages: list[dict], config: dict) -> str:
    """单独调用 Profiler 模型，避免与文章打分链路混用。"""
    api_key = config.get("api_key", "")
    if not api_key:
        raise ValueError("Profiler API Key 未配置。")

    api_base = config.get("api_base", "").rstrip("/")
    model = config.get("model", "gpt-4o-mini")
    provider = config.get("provider", "openai").lower()

    if provider in ["gemini", "google"]:
        provider = "gemini"

    if provider == "anthropic":
        if not api_base:
            api_base = "https://api.anthropic.com"
        endpoint = api_base
        if "/v1/messages" not in endpoint and "/messages" not in endpoint:
            endpoint = f"{endpoint}/v1/messages" if "api.anthropic.com" in endpoint else f"{endpoint}/messages"

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        system_prompt = ""
        anthropic_msgs = []
        for m in messages:
            if m["role"] == "system":
                system_prompt += m["content"] + "\n"
            else:
                anthropic_msgs.append({"role": m["role"], "content": m["content"]})

        payload = {"model": model, "messages": anthropic_msgs, "max_tokens": 2000, "temperature": 0.2}
        if system_prompt.strip():
            payload["system"] = system_prompt.strip()

        resp = requests.post(endpoint, headers=headers, json=payload, timeout=60, proxies=config.get("proxies"))
        if resp.status_code != 200:
            raise ValueError(f"Anthropic API Error {resp.status_code}: {resp.text}")
        return resp.json()["content"][0]["text"]

    if provider == "gemini":
        if not api_base:
            api_base = "https://generativelanguage.googleapis.com"
        if ":generateContent" in api_base:
            endpoint = api_base
        else:
            base_url = api_base.rstrip("/")
            if "/v1beta" not in base_url and "googleapis.com" in base_url:
                base_url = f"{base_url}/v1beta"
            endpoint = f"{base_url}/models/{model}:generateContent"

        sep = "&" if "?" in endpoint else "?"
        endpoint = f"{endpoint}{sep}key={api_key}"

        contents = []
        system_instruction = None
        for m in messages:
            if m["role"] == "system":
                system_instruction = {"parts": [{"text": m["content"]}]}
            else:
                role = "user" if m["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": m["content"]}]})

        payload = {"contents": contents, "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2000}}
        if system_instruction:
            payload["systemInstruction"] = system_instruction

        headers = {"Content-Type": "application/json"}
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=60, proxies=config.get("proxies"))
        if resp.status_code != 200:
            raise ValueError(f"Gemini API Error {resp.status_code}: {resp.text}")

        data = resp.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise ValueError("Gemini Profiler 返回格式异常")

    if not api_base:
        api_base = "https://api.openai.com/v1"
    endpoint = api_base if "/chat/completions" in api_base else f"{api_base}/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 2000,
    }
    resp = requests.post(endpoint, headers=headers, json=payload, timeout=60, proxies=config.get("proxies"))
    if resp.status_code != 200:
        raise ValueError(f"OpenAI API Error {resp.status_code}: {resp.text}")
    return resp.json()["choices"][0]["message"]["content"]


def _parse_profile_response(raw_response: str) -> str:
    """解析 Profiler 返回，只接受严格 JSON 中的 profile 字段。"""
    text = raw_response.strip()
    if "```" in text:
        match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Profiler 返回的不是有效 JSON: {text[:200]}") from exc

    profile = (payload.get("profile") or "").strip()
    if not profile:
        raise ValueError("Profiler 返回缺少 profile 字段")
    return profile


async def generate_user_profile(db: AsyncSession, days: int = PROFILE_WINDOW_DAYS) -> dict:
    """生成并写回新的用户画像。"""
    summary = {
        "updated": False,
        "liked_count": 0,
        "disliked_count": 0,
        "history_count": 0,
        "message": "",
        "profile": "",
    }

    samples = await _get_profile_samples(db, days=days)
    liked_articles = samples["liked"]
    disliked_articles = samples["disliked"]
    summary["liked_count"] = len(liked_articles)
    summary["disliked_count"] = len(disliked_articles)

    if not liked_articles and not disliked_articles:
        summary["message"] = "最近一周没有正负反馈文章，跳过画像生成。"
        return summary

    result = await db.execute(select(User).limit(1))
    user = result.scalar_one_or_none()
    profile = await db.get(UserProfile, user.id) if user else None
    previous_profile = profile.base_prompt if profile else ""
    history_items = await _get_profile_history(db, user.id, limit=PROFILE_HISTORY_LIMIT) if user else []
    summary["history_count"] = len(history_items)

    profiler_config = await _get_ai_config(db, role="profiler")
    messages = _build_profile_prompt(
        liked_articles,
        disliked_articles,
        previous_profile,
        profile_history=history_items,
    )
    raw_response = _call_profiler(messages, profiler_config)
    new_profile = _parse_profile_response(raw_response)

    if not user:
        user = User(username="default", password_hash="")
        db.add(user)
        await db.flush()

    profile = await db.get(UserProfile, user.id)
    if not profile:
        profile = UserProfile(
            user_id=user.id,
            base_prompt=new_profile,
            active_tags="",
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        db.add(profile)
    else:
        await db.execute(
            update(UserProfile)
            .where(UserProfile.user_id == user.id)
            .values(
                base_prompt=new_profile,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
        )

    db.add(
        ProfileHistory(
            user_id=user.id,
            profile_text=new_profile,
        )
    )
    await db.commit()

    summary["updated"] = True
    summary["profile"] = new_profile
    summary["message"] = "用户画像已更新"
    logger.info(
        "用户画像更新完成: 喜欢 %s 篇, 不喜欢 %s 篇",
        summary["liked_count"],
        summary["disliked_count"],
    )
    return summary
