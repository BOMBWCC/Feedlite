from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.database import get_db
from app.models import Feed
from app.services.rss_fetcher import (
    MAX_RSS_RESPONSE_BYTES,
    RSS_CONNECT_TIMEOUT,
    USER_AGENT,
    parse_feed_content,
)
from app.services.safe_http import async_fetch_public_bytes

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("/")
async def get_sources(db: AsyncSession = Depends(get_db)):
    """获取所有 active 状态的订阅源"""
    stmt = (
        select(Feed)
        .where(Feed.status == "active")
        .order_by(Feed.created_at.desc())
    )
    result = await db.execute(stmt)
    feeds = result.scalars().all()

    return [
        {
            "id": f.id,
            "url": f.url,
            "title": f.title,
            "category": f.category,
            "error_count": f.error_count,
            "status": f.status,
            "created_at": f.created_at,
        }
        for f in feeds
    ]


@router.post("/")
async def add_source(
    url: str = Query(...),
    title: str = Query(None),
    category: int = Query(default=5),
    db: AsyncSession = Depends(get_db),
):
    """添加新订阅源"""
    new_feed = Feed(url=url, title=title, category=category)
    db.add(new_feed)
    try:
        await db.commit()
        await db.refresh(new_feed)
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=400, detail="该 URL 已存在")

    return {"status": "ok", "id": new_feed.id, "url": new_feed.url}


@router.delete("/{source_id}")
async def delete_source(source_id: int, db: AsyncSession = Depends(get_db)):
    """软删除订阅源（status -> deleted）"""
    stmt = (
        update(Feed)
        .where(Feed.id == source_id)
        .values(status="deleted")
    )
    result = await db.execute(stmt)
    await db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="订阅源不存在")

    return {"status": "ok", "id": source_id, "message": "已删除"}


@router.post("/preview")
async def preview_source(url: str = Query(...)):
    """预览 RSS 源最新 3 条内容（实时抓取）"""
    try:
        content = await async_fetch_public_bytes(
            url,
            max_bytes=MAX_RSS_RESPONSE_BYTES,
            timeout=(RSS_CONNECT_TIMEOUT, 10),
            total_timeout=20,
            headers={"User-Agent": USER_AGENT},
        )
        parsed = parse_feed_content(
            content,
            max_desc_len=200,
            max_content_len=200,
            max_entries=3,
            enforce_retention=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail="抓取失败或目标不允许") from exc

    articles = [
        {
            "title": article["title"],
            "link": article["link"],
            "description": article["description"],
            "published": article["published"],
        }
        for article in parsed["articles"]
    ]
    return {
        "status": "ok",
        "url": url,
        "feed_title": parsed["feed_title"],
        "articles": articles,
    }
