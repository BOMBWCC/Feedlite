from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth_deps import verify_rag_api_key
from app.database import get_db
from app.models import Article, ArticleChunk, Feed
from app.services.search_index import build_search_query

DEFAULT_RAG_DAYS = 30

router = APIRouter(
    prefix="/api/rag",
    tags=["rag"],
    dependencies=[Depends(verify_rag_api_key)],
)


def _serialize_chunk_row(row, *, is_requested: bool) -> dict:
    return {
        "chunk_id": row.chunk_id,
        "article_id": row.article_id,
        "chunk_index": row.chunk_index,
        "is_requested": is_requested,
        "title": row.source_title,
        "description": row.source_description,
        "content": row.content,
        "link": row.link,
        "published": row.published,
        "category": row.category,
        "ai_score": row.ai_score,
        "article_status": row.status,
        "language": row.language,
        "char_count": row.char_count,
        "token_count": row.token_count,
    }


@router.get("/search")
async def search_rag_chunks(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=8, ge=1, le=20),
    category: int | None = Query(default=None),
    days: int = Query(default=DEFAULT_RAG_DAYS, ge=0, le=3650),
    include_filtered: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    """给 OpenClaw 等调用方使用的 RAG 检索接口。"""
    search_query = build_search_query(q)
    if not search_query:
        return {
            "query": q,
            "count": 0,
            "filters": {
                "category": category,
                "days": days,
                "cutoff": None,
                "include_filtered": include_filtered,
            },
            "items": [],
        }

    first_token = search_query.split()[0].lower()
    title_probe = f"%{first_token}%"
    cutoff = None
    if days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    status_clause = "a.status IN ('active', 'filtered')" if include_filtered else "a.status = 'active'"
    rag_sql = text(
        f"""
        SELECT
            c.id AS chunk_id,
            c.article_id,
            c.chunk_index,
            c.content,
            c.source_title,
            c.source_description,
            c.published,
            c.char_count,
            c.token_count,
            c.language,
            a.link,
            a.ai_score,
            a.status,
            f.category,
            bm25(article_chunks_fts) AS rank_score
        FROM article_chunks_fts fts
        JOIN article_chunks c ON c.id = fts.rowid
        JOIN articles a ON a.id = c.article_id
        JOIN feeds f ON f.id = a.feed_id
        WHERE fts.search_text MATCH :query
          AND {status_clause}
          AND (:category IS NULL OR f.category = :category)
          AND (:cutoff IS NULL OR c.published >= :cutoff)
        ORDER BY
          CASE
            WHEN lower(COALESCE(c.source_title, '')) LIKE :title_probe THEN 0
            ELSE 1
          END,
          bm25(article_chunks_fts),
          a.ai_score DESC,
          c.published DESC,
          c.id DESC
        LIMIT :limit
        """
    )

    result = await db.execute(
        rag_sql,
        {
            "query": search_query,
            "limit": limit,
            "category": category,
            "cutoff": cutoff,
            "title_probe": title_probe,
        },
    )
    rows = result.all()

    return {
        "query": q,
        "count": len(rows),
        "filters": {
            "category": category,
            "days": days,
            "cutoff": cutoff,
            "include_filtered": include_filtered,
        },
        "items": [
            {
                **_serialize_chunk_row(row, is_requested=True),
                "rank_score": row.rank_score,
            }
            for row in rows
        ],
    }


@router.get("/context")
async def get_rag_context(
    chunk_ids: list[int] = Query(..., alias="chunk_id"),
    window: int = Query(default=1, ge=0, le=3),
    include_filtered: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    """根据命中的 chunk_id 拉取更适合拼 prompt 的上下文。"""
    if not chunk_ids:
        return {
            "requested_chunk_ids": [],
            "resolved_chunk_ids": [],
            "missing_chunk_ids": [],
            "window": window,
            "include_filtered": include_filtered,
            "count": 0,
            "items": [],
        }

    input_order = {chunk_id: index for index, chunk_id in enumerate(chunk_ids)}
    status_filter = [Article.status == "active"]
    if include_filtered:
        status_filter = [Article.status.in_(["active", "filtered"])]

    chunk_stmt = (
        select(
            ArticleChunk.id.label("chunk_id"),
            ArticleChunk.article_id,
            ArticleChunk.chunk_index,
            ArticleChunk.content,
            ArticleChunk.source_title,
            ArticleChunk.source_description,
            ArticleChunk.published,
            ArticleChunk.char_count,
            ArticleChunk.token_count,
            ArticleChunk.language,
            Article.link,
            Article.ai_score,
            Article.status,
            Feed.category,
        )
        .join(Article, Article.id == ArticleChunk.article_id)
        .join(Feed, Feed.id == Article.feed_id)
        .where(ArticleChunk.id.in_(chunk_ids))
        .where(*status_filter)
    )
    requested_rows = list((await db.execute(chunk_stmt)).all())
    requested_rows.sort(key=lambda row: input_order.get(row.chunk_id, len(chunk_ids)))

    resolved_chunk_ids = [row.chunk_id for row in requested_rows]
    missing_chunk_ids = [chunk_id for chunk_id in chunk_ids if chunk_id not in set(resolved_chunk_ids)]
    if not requested_rows:
        return {
            "requested_chunk_ids": chunk_ids,
            "resolved_chunk_ids": [],
            "missing_chunk_ids": missing_chunk_ids,
            "window": window,
            "include_filtered": include_filtered,
            "count": 0,
            "items": [],
        }

    article_ids = sorted({row.article_id for row in requested_rows})
    all_rows_stmt = (
        select(
            ArticleChunk.id.label("chunk_id"),
            ArticleChunk.article_id,
            ArticleChunk.chunk_index,
            ArticleChunk.content,
            ArticleChunk.source_title,
            ArticleChunk.source_description,
            ArticleChunk.published,
            ArticleChunk.char_count,
            ArticleChunk.token_count,
            ArticleChunk.language,
            Article.link,
            Article.ai_score,
            Article.status,
            Feed.category,
        )
        .join(Article, Article.id == ArticleChunk.article_id)
        .join(Feed, Feed.id == Article.feed_id)
        .where(ArticleChunk.article_id.in_(article_ids))
        .where(*status_filter)
        .order_by(ArticleChunk.article_id.asc(), ArticleChunk.chunk_index.asc())
    )
    article_chunk_rows = list((await db.execute(all_rows_stmt)).all())
    rows_by_article: dict[int, list] = {}
    for row in article_chunk_rows:
        rows_by_article.setdefault(row.article_id, []).append(row)

    requested_id_set = set(resolved_chunk_ids)
    seen_chunk_ids: set[int] = set()
    items: list[dict] = []
    for requested_row in requested_rows:
        for row in rows_by_article.get(requested_row.article_id, []):
            if abs(row.chunk_index - requested_row.chunk_index) > window:
                continue
            if row.chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(row.chunk_id)
            items.append(_serialize_chunk_row(row, is_requested=row.chunk_id in requested_id_set))

    return {
        "requested_chunk_ids": chunk_ids,
        "resolved_chunk_ids": resolved_chunk_ids,
        "missing_chunk_ids": missing_chunk_ids,
        "window": window,
        "include_filtered": include_filtered,
        "count": len(items),
        "items": items,
    }
