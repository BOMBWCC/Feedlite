"""
AI Scorer Service
核心职责：读取用户画像 → 批量组装 Prompt → 调用 LLM API → 解析分数 → 更新数据库
"""

import json
import logging
import os

import requests
import yaml
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.models import Article, User, AppConfig

logger = logging.getLogger("feedlite.ai_scorer")

# ─── 配置加载 ────────────────────────────────────────

_config_cache = None

def _load_config() -> dict:
    """从 config.yml 加载静态配置（带缓存）"""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "config.yml"
    )
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            _config_cache = yaml.safe_load(f) or {}
    except Exception:
        _config_cache = {}
    return _config_cache


async def _get_ai_config(db: AsyncSession, role: str = "scorer") -> dict:
    """
    合并 config.yml、环境变量和数据库 ai_models 中的 AI 配置。
    数据库 > 环境变量 > 默认文件配置。
    """
    from app.models import AiModel
    file_cfg = _load_config()
    
    ai_cfg = {
        "role": role,
        "provider": file_cfg.get("ai", {}).get("default_provider", "openai"),
        "model": file_cfg.get("ai", {}).get("default_model", "gpt-3.5-turbo"),
        "api_key": "",
        "api_base": "https://api.openai.com/v1",
        "batch_size": file_cfg.get("fetch", {}).get("batch_size", 50),
    }

    # 1. 从环境变量获取 (.env 注入)
    prefix = role.upper()
    if os.getenv(f"{prefix}_PROVIDER"): ai_cfg["provider"] = os.getenv(f"{prefix}_PROVIDER")
    if os.getenv(f"{prefix}_MODEL"): ai_cfg["model"] = os.getenv(f"{prefix}_MODEL")
    if os.getenv(f"{prefix}_API_KEY"): ai_cfg["api_key"] = os.getenv(f"{prefix}_API_KEY")
    if os.getenv(f"{prefix}_API_BASE"): ai_cfg["api_base"] = os.getenv(f"{prefix}_API_BASE")

    # 2. 从 ai_models 表读取覆盖值 (热更新)
    stmt = select(AiModel).where(AiModel.role == role)
    result = await db.execute(stmt)
    model_row = result.scalar_one_or_none()
    
    if model_row:
        if model_row.provider: ai_cfg["provider"] = model_row.provider
        if model_row.model_name: ai_cfg["model"] = model_row.model_name
        if model_row.api_key: ai_cfg["api_key"] = model_row.api_key
        if model_row.api_base: ai_cfg["api_base"] = model_row.api_base

    # 代理配置：仅供 AI 请求使用的专属代理，避免干扰全局 RSS 抓取
    proxy_cfg = file_cfg.get("proxy", {})
    ai_specific_proxy = os.getenv("AI_SPECIFIC_PROXY", proxy_cfg.get("http_proxy", ""))
    if ai_specific_proxy:
        ai_cfg["proxies"] = {
            "http": ai_specific_proxy,
            "https": ai_specific_proxy,
        }
    else:
        ai_cfg["proxies"] = None

    return ai_cfg


async def _get_user_profile(db: AsyncSession) -> dict:
    """获取第一个用户的画像（Tags + System Prompt）"""
    stmt = select(User).limit(1)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user:
        return {
            "base_prompt": user.base_prompt or "",
            "active_tags": user.active_tags or "",
        }
    return {"base_prompt": "", "active_tags": ""}


# ─── Prompt 构建 ─────────────────────────────────────

def _build_scoring_prompt(articles: list[dict], profile: dict) -> list[dict]:
    """
    构建发送给 LLM 的消息列表。
    三级漏斗策略：偏好匹配 → 去噪过滤 → 推荐打分（0-100）。
    """
    system_prompt = profile.get("base_prompt", "").strip()
    tags = profile.get("active_tags", "").strip()

    if not system_prompt:
        system_prompt = "你是一个专业的新闻筛选助手。请根据文章标题和简介，为每篇文章打出一个 0-100 的相关性与重要性评分。"

    if tags:
        system_prompt += f"\n\n用户关注的核心标签：{tags}"

    system_prompt += """

评分规则：
- 90-100: 与用户兴趣高度相关且具有重要时效性的内容
- 70-89: 与用户兴趣相关的优质内容
- 50-69: 有一定参考价值的一般内容
- 30-49: 与用户兴趣关联较弱
- 0-29: 广告、噪音、无关内容

请严格按照以下 JSON 格式返回，不要包含其他文字：
[{"id": <文章ID>, "score": <0-100整数>}, ...]"""

    # 构建文章列表
    articles_text = "\n".join([
        f"[ID:{a['id']}] 标题: {a['title']}\n简介: {a['description'][:150] if a.get('description') else '无'}"
        for a in articles
    ])

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"请为以下 {len(articles)} 篇文章打分：\n\n{articles_text}"},
    ]


# ─── LLM API 调用 ────────────────────────────────────

def _call_llm(messages: list[dict], config: dict) -> str:
    """调用 OpenAI 兼容 API、Anthropic API 或 Gemini API"""
    api_key = config.get("api_key", "")
    role_flag = config.get("role", "scorer").upper()
    if not api_key:
        raise ValueError(f"AI API Key 未配置。请设定 {role_flag}_API_KEY 环境变量或在 ai_models 表中提供配置。")

    api_base = config.get("api_base", "").rstrip("/")
    model = config.get("model", "gpt-3.5-turbo")
    provider = config.get("provider", "openai").lower()
    
    # 强正名：确保 google 或 gemini 都能进入原生分支
    if provider in ["gemini", "google"]:
        provider = "gemini"

    if provider == "anthropic":
        # 兼容性处理：如果 api_base 已包含 /v1/messages，则不再追加
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
                
        payload = {"model": model, "messages": anthropic_msgs, "max_tokens": 2000, "temperature": 0.3}
        if system_prompt.strip():
            payload["system"] = system_prompt.strip()
            
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=60, proxies=config.get("proxies"))
        if resp.status_code != 200:
            raise ValueError(f"Anthropic API Error {resp.status_code}: {resp.text}")
        return resp.json()["content"][0]["text"]

    elif provider == "gemini":
        # Gemini 原生 API: https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}
        if not api_base:
            api_base = "https://generativelanguage.googleapis.com"
        
        # 组装 URL
        if ":generateContent" in api_base:
            endpoint = api_base
        else:
            base_url = api_base.rstrip("/")
            if "/v1beta" not in base_url and "googleapis.com" in base_url:
                base_url = f"{base_url}/v1beta"
            endpoint = f"{base_url}/models/{model}:generateContent"

        # 拼接 Key
        sep = "&" if "?" in endpoint else "?"
        endpoint = f"{endpoint}{sep}key={api_key}"

        # 组装 Payload (Gemini 结构)
        contents = []
        system_instruction = None
        for m in messages:
            if m["role"] == "system":
                system_instruction = {"parts": [{"text": m["content"]}]}
            else:
                role = "user" if m["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": m["content"]}]})
        
        # 注意：Gemini 官方 REST API 使用 systemInstruction (驼峰)
        payload = {"contents": contents, "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2000}}
        if system_instruction:
            payload["systemInstruction"] = system_instruction

        headers = {"Content-Type": "application/json"}
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=60, proxies=config.get("proxies"))
        
        if resp.status_code != 200:
            error_detail = resp.text
            logger.error(f"Gemini API Error Response: {error_detail}")
            raise ValueError(f"Gemini API Error {resp.status_code}: {error_detail}")
        
        # 解析结果
        data = resp.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            logger.error(f"Gemini 返回解析失败: {data}")
            raise ValueError("Gemini API 返回格式异常")

    else:
        # Default OpenAI format
        if not api_base:
            api_base = "https://api.openai.com/v1"
            
        endpoint = api_base
        if "/chat/completions" not in endpoint:
            endpoint = f"{endpoint}/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 2000,
        }

        resp = requests.post(endpoint, headers=headers, json=payload, timeout=60, proxies=config.get("proxies"))
        if resp.status_code != 200:
            raise ValueError(f"OpenAI API Error {resp.status_code}: {resp.text}")
        return resp.json()["choices"][0]["message"]["content"]


# ─── 解析 LLM 返回 ───────────────────────────────────

def _parse_scores(raw_response: str) -> dict[int, int]:
    """从 LLM 返回的文本中提取 {article_id: score} 映射"""
    # 尝试提取 JSON 块
    text = raw_response.strip()

    # 处理 markdown 代码块包裹
    if "```" in text:
        import re
        match = re.search(r'```(?:json)?\s*(.*?)```', text, re.DOTALL)
        if match:
            text = match.group(1).strip()

    try:
        scores_list = json.loads(text)
    except json.JSONDecodeError:
        logger.error(f"无法解析 LLM 返回的 JSON: {text[:200]}")
        return {}

    result = {}
    for item in scores_list:
        aid = item.get("id")
        score = item.get("score")
        if aid is not None and score is not None:
            result[int(aid)] = max(0, min(100, int(score)))

    return result


# ─── 核心：批量打分 ──────────────────────────────────

SCORE_THRESHOLD = 30  # 低于此分数的文章标记为 filtered

async def score_unscored_articles(db: AsyncSession) -> dict:
    """
    查找所有 status='active' 且 ai_score=0 的文章，批量调用 AI 打分。
    返回 {"scored": N, "filtered": N, "skipped": N, "error": str|None}
    """
    summary = {"scored": 0, "filtered": 0, "skipped": 0, "error": None}

    # 1. 加载配置和用户画像
    try:
        ai_config = await _get_ai_config(db)
    except Exception as e:
        summary["error"] = f"配置加载失败: {e}"
        return summary

    if not ai_config.get("api_key"):
        summary["error"] = "AI API Key 未配置，跳过打分"
        logger.warning(summary["error"])
        return summary

    profile = await _get_user_profile(db)

    # 2. 查找待打分文章
    stmt = (
        select(Article.id, Article.title, Article.description)
        .where(Article.status == "active")
        .where(Article.ai_score == 0)
        .order_by(Article.id.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    if not rows:
        logger.info("没有待打分的文章")
        return summary

    articles = [{"id": r.id, "title": r.title, "description": r.description or ""} for r in rows]
    batch_size = ai_config.get("batch_size", 50)

    # 3. 分批处理
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]

        try:
            messages = _build_scoring_prompt(batch, profile)
            raw_response = _call_llm(messages, ai_config)
            scores = _parse_scores(raw_response)

            # 4. 写入分数
            for art in batch:
                aid = art["id"]
                score = scores.get(aid)

                if score is not None:
                    new_status = "filtered" if score < SCORE_THRESHOLD else "active"
                    await db.execute(
                        update(Article)
                        .where(Article.id == aid)
                        .values(ai_score=score, status=new_status)
                    )
                    summary["scored"] += 1
                    if new_status == "filtered":
                        summary["filtered"] += 1
                else:
                    summary["skipped"] += 1

            await db.commit()

        except Exception as e:
            logger.error(f"批次打分失败 (batch {i // batch_size + 1}): {e}")
            summary["error"] = str(e)
            # 继续处理下一批，不中断

    logger.info(
        f"AI 打分完成: 评分 {summary['scored']} 篇, "
        f"过滤 {summary['filtered']} 篇, "
        f"跳过 {summary['skipped']} 篇"
    )

    return summary
