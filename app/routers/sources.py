from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.database import get_db
from app.models import Feed

import re
import html as html_module
import feedparser
import requests
import calendar
from datetime import datetime, timezone

router = APIRouter(prefix="/api/sources", tags=["sources"])


def _clean_html(raw: str) -> str:
    """清洗 HTML 标签并解码实体字符"""
    if not raw:
        return ""
    text = re.sub(r'<.*?>', '', raw)
    text = html_module.unescape(text)
    return " ".join(text.split())


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
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=400, detail=f"抓取失败: {e}")

    feed = feedparser.parse(resp.content)

    if feed.bozo and not feed.entries:
        raise HTTPException(status_code=400, detail=f"RSS 解析失败: {feed.bozo_exception}")

    articles = []
    for entry in feed.entries[:3]:
        title = getattr(entry, "title", "无标题")
        link = getattr(entry, "link", "")
        raw_desc = getattr(entry, "summary", getattr(entry, "description", ""))
        desc = _clean_html(raw_desc)
        if len(desc) > 200:
            desc = desc[:200] + "..."

        pub = ""
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                ts = calendar.timegm(entry.published_parsed)
                pub = datetime.fromtimestamp(ts, timezone.utc).isoformat()
            except Exception:
                pub = ""

        articles.append({"title": title, "link": link, "description": desc, "published": pub})

    feed_title = getattr(feed.feed, "title", "")
    return {"status": "ok", "url": url, "feed_title": feed_title, "articles": articles}
