from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, text

from app.database import get_db
from app.models import Article, Feed

router = APIRouter(prefix="/api", tags=["feeds"])


@router.get("/articles/")
async def get_articles(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """获取文章列表（无限滚动分页），按发布时间倒序"""
    stmt = (
        select(
            Article.id,
            Article.title,
            Article.link,
            Article.description,
            Article.published,
            Article.ai_score,
            Article.feedback,
            Article.created_at,
            Feed.category,
        )
        .join(Feed, Article.feed_id == Feed.id)
        .where(Article.status == "active")
        .order_by(Article.published.desc(), Article.id.desc())
        .limit(limit)
        .offset(offset)
    )

    result = await db.execute(stmt)
    rows = result.all()

    return [
        {
            "id": row.id,
            "title": row.title,
            "link": row.link,
            "description": row.description,
            "published": row.published,
            "ai_score": row.ai_score,
            "feedback": row.feedback,
            "created_at": row.created_at,
            "category": row.category,
        }
        for row in rows
    ]


@router.get("/articles/search")
async def search_articles(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """全文检索文章（FTS5 MATCH），返回匹配结果"""
    # 使用原始 SQL：FTS5 MATCH 查询 → 通过 rowid 关联主表 → JOIN feeds 获取分类
    fts_sql = text("""
        SELECT a.id, a.title, a.link, a.description, a.published,
               a.ai_score, a.feedback, a.created_at, f.category
        FROM articles_fts fts
        JOIN articles a ON a.id = fts.rowid
        JOIN feeds f ON a.feed_id = f.id
        WHERE articles_fts MATCH :query
          AND a.status = 'active'
        ORDER BY rank
        LIMIT :limit
    """)

    result = await db.execute(fts_sql, {"query": q, "limit": limit})
    rows = result.all()

    return [
        {
            "id": row.id,
            "title": row.title,
            "link": row.link,
            "description": row.description,
            "published": row.published,
            "ai_score": row.ai_score,
            "feedback": row.feedback,
            "created_at": row.created_at,
            "category": row.category,
        }
        for row in rows
    ]


@router.patch("/articles/{article_id}/feedback")
async def update_feedback(
    article_id: int,
    type: int = Query(..., ge=-1, le=1),
    db: AsyncSession = Depends(get_db),
):
    """更新文章反馈（1=感兴趣，-1=不感兴趣，0=取消）"""
    stmt = (
        update(Article)
        .where(Article.id == article_id)
        .values(feedback=type)
    )
    await db.execute(stmt)
    await db.commit()
    return {"status": "ok", "article_id": article_id, "feedback": type}


@router.post("/feeds/sync")
async def sync_feeds(db: AsyncSession = Depends(get_db)):
    """手动触发 RSS 抓取 + AI 打分流水线"""
    from app.services.rss_fetcher import sync_all_feeds
    from app.services.ai_scorer import score_unscored_articles

    # Step 1: 抓取
    fetch_summary = await sync_all_feeds(db)

    # Step 2: AI 打分（非阻塞，失败不影响抓取结果）
    score_summary = await score_unscored_articles(db)

    msg_parts = [f"抓取 {fetch_summary['total_fetched']} 篇, 新增 {fetch_summary['total_inserted']} 篇"]
    if score_summary.get("scored", 0) > 0:
        msg_parts.append(f"AI 评分 {score_summary['scored']} 篇")
    if score_summary.get("error"):
        msg_parts.append(f"打分提示: {score_summary['error']}")

    return {
        "status": "ok",
        "message": "同步完成: " + ", ".join(msg_parts),
        "fetch_summary": fetch_summary,
        "score_summary": score_summary,
    }
