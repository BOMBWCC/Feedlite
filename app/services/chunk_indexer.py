"""
Chunk indexing service.
核心职责：将文章原文切成适合 RAG 的 chunk，并写入 article_chunks。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Article, ArticleChunk
from app.services.search_index import build_search_text

DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 120
DEFAULT_MIN_CHUNK_SIZE = 120
_SOFT_BREAK_CHARS = " \n\t。！？；.!?;,，、:"
_TOKEN_ESTIMATE_RE = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+")


def _normalize_chunk_content(text: str) -> str:
    """压缩空白，保留适合上下文拼接的可读正文。"""
    return " ".join((text or "").split()).strip()


def _estimate_token_count(text: str) -> int:
    """粗略估算 token 数，足够支持第一版上下文长度控制。"""
    return len(_TOKEN_ESTIMATE_RE.findall(text or ""))


def _find_soft_break(text: str, start: int, end: int) -> int:
    """优先在窗口尾部附近寻找更自然的断点。"""
    scan_start = max(start + 1, end - 80)
    for idx in range(end, scan_start, -1):
        if text[idx - 1] in _SOFT_BREAK_CHARS:
            return idx
    return end


def split_text_into_chunks(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    min_chunk_size: int = DEFAULT_MIN_CHUNK_SIZE,
) -> list[str]:
    """使用固定窗口 + overlap 切块。"""
    normalized = _normalize_chunk_content(text)
    if not normalized:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must be non-negative")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    chunks: list[str] = []
    start = 0
    length = len(normalized)

    while start < length:
        end = min(length, start + chunk_size)
        if end < length:
            end = _find_soft_break(normalized, start, end)

        piece = normalized[start:end].strip()
        if piece:
            if chunks and len(piece) < min_chunk_size:
                chunks[-1] = f"{chunks[-1]} {piece}".strip()
            else:
                chunks.append(piece)

        if end >= length:
            break

        next_start = max(end - chunk_overlap, start + 1)
        start = next_start

    return chunks


def build_article_chunk_payloads(
    *,
    title: str,
    description: str,
    content: str,
    published: str,
    translated_title: str = "",
    translated_description: str = "",
    language: str = "",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    min_chunk_size: int = DEFAULT_MIN_CHUNK_SIZE,
) -> list[dict]:
    """根据文章内容构造待写入的 chunk payload。"""
    normalized_title = _normalize_chunk_content(title)
    normalized_description = _normalize_chunk_content(description)
    normalized_content = _normalize_chunk_content(content)

    body_text = normalized_content or normalized_description or normalized_title
    if not body_text:
        return []

    pieces = split_text_into_chunks(
        body_text,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        min_chunk_size=min_chunk_size,
    )
    now = datetime.now(timezone.utc).isoformat()
    title_for_search = "\n".join(filter(None, [normalized_title, _normalize_chunk_content(translated_title)]))
    description_for_search = "\n".join(
        filter(None, [normalized_description, _normalize_chunk_content(translated_description)])
    )

    return [
        {
            "chunk_index": idx,
            "content": piece,
            "search_text": build_search_text(
                title=title_for_search,
                description=description_for_search,
                content=piece,
            ),
            "language": language or None,
            "char_count": len(piece),
            "token_count": _estimate_token_count(piece),
            "source_title": normalized_title,
            "source_description": normalized_description,
            "published": published,
            "created_at": now,
        }
        for idx, piece in enumerate(pieces)
    ]


async def rebuild_article_chunks_for_article(
    db: AsyncSession,
    article_id: int,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    min_chunk_size: int = DEFAULT_MIN_CHUNK_SIZE,
) -> int:
    """重建单篇文章的 chunk。"""
    result = await db.execute(
        select(
            Article.id,
            Article.title,
            Article.description,
            Article.content,
            Article.published,
            Article.translated_title,
            Article.translated_description,
            Article.translation_language,
        ).where(Article.id == article_id)
    )
    article = result.one_or_none()
    if article is None:
        return 0

    payloads = build_article_chunk_payloads(
        title=article.title or "",
        description=article.description or "",
        content=article.content or "",
        published=article.published,
        translated_title=article.translated_title or "",
        translated_description=article.translated_description or "",
        language=article.translation_language or "",
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        min_chunk_size=min_chunk_size,
    )

    await db.execute(delete(ArticleChunk).where(ArticleChunk.article_id == article_id))
    if payloads:
        db.add_all([ArticleChunk(article_id=article_id, **payload) for payload in payloads])
    await db.commit()
    return len(payloads)


async def rebuild_all_article_chunks(
    db: AsyncSession,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    min_chunk_size: int = DEFAULT_MIN_CHUNK_SIZE,
) -> dict:
    """全量重建文章 chunk。"""
    result = await db.execute(select(Article.id).order_by(Article.id.asc()))
    article_ids = list(result.scalars().all())

    summary = {
        "articles": len(article_ids),
        "chunked_articles": 0,
        "chunks": 0,
    }
    for article_id in article_ids:
        count = await rebuild_article_chunks_for_article(
            db,
            article_id,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            min_chunk_size=min_chunk_size,
        )
        if count > 0:
            summary["chunked_articles"] += 1
            summary["chunks"] += count

    return summary
