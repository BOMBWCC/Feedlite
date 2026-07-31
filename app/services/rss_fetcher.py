"""
RSS Fetcher Service
核心职责：抓取 RSS → 清洗 HTML → 时间过滤 → URL 查重入库 → 源熔断
"""

import asyncio
import html as html_module
import calendar
import logging
import os
from urllib.parse import urlsplit

import feedparser
import yaml
from datetime import datetime, timezone, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models import Feed, Article
from app.services.chunk_indexer import rebuild_article_chunks_for_article
from app.services.search_index import build_search_text, strip_markup
from app.services.safe_http import fetch_public_bytes

logger = logging.getLogger("feedlite.rss_fetcher")

# ─── 常量 ────────────────────────────────────────────
DEFAULT_RETENTION_HOURS = 24
MAX_ERROR_COUNT = 5       # 连续失败达此次数后进入休眠
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
FETCH_TIMEOUT = 15        # 秒
RSS_CONNECT_TIMEOUT = 3
RSS_TOTAL_TIMEOUT = 25
MAX_RSS_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_FEED_REDIRECTS = 3
MAX_FEED_ENTRIES = 200
MAX_FEED_TITLE_CHARS = 200
MAX_ARTICLE_TITLE_CHARS = 500
MAX_ARTICLE_LINK_CHARS = 2048
MAX_DESCRIPTION_CHARS = 1000
MAX_CONTENT_CHARS = 100000


# ─── 工具函数 ────────────────────────────────────────

_config_cache = None


def _load_config() -> dict:
    """从 config.yml 加载静态配置（带缓存）。"""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "config.yml",
    )
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            _config_cache = yaml.safe_load(f) or {}
    except Exception:
        _config_cache = {}
    return _config_cache


def _get_retention_hours(override: int | None = None) -> int:
    """优先使用显式传参，否则回退到 config.yml，再回退到代码默认值。"""
    if override is not None:
        return override

    cfg = _load_config()
    try:
        return int(cfg.get("fetch", {}).get("retention_hours", DEFAULT_RETENTION_HOURS))
    except (TypeError, ValueError):
        return DEFAULT_RETENTION_HOURS

def clean_html(raw: str) -> str:
    """清洗 HTML 标签并解码实体字符"""
    if not raw:
        return ""
    text = strip_markup(raw)
    text = html_module.unescape(text)
    return " ".join(text.split())


def _clean_bounded(raw: object, max_chars: int) -> str:
    bounded_raw = str(raw or "")[:max_chars]
    return clean_html(bounded_raw)[:max_chars]


def _normalize_article_link(raw: object) -> str:
    link = str(raw or "").strip()[:MAX_ARTICLE_LINK_CHARS]
    try:
        parsed = urlsplit(link)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    return link


def parse_published_time(entry) -> datetime | None:
    """从 feedparser entry 中提取 UTC 发布时间"""
    if hasattr(entry, 'published_parsed') and entry.published_parsed:
        try:
            ts = calendar.timegm(entry.published_parsed)
            return datetime.fromtimestamp(ts, timezone.utc)
        except Exception:
            pass
    if hasattr(entry, 'updated_parsed') and entry.updated_parsed:
        try:
            ts = calendar.timegm(entry.updated_parsed)
            return datetime.fromtimestamp(ts, timezone.utc)
        except Exception:
            pass
    return None


# ─── 核心：抓取并清洗 ─────────────────────────────────

def parse_feed_content(
    content: bytes,
    retention_hours: int | None = None,
    max_desc_len: int = MAX_DESCRIPTION_CHARS,
    max_content_len: int = MAX_CONTENT_CHARS,
    *,
    max_entries: int = MAX_FEED_ENTRIES,
    enforce_retention: bool = True,
) -> dict:
    """Parse already-bounded feed bytes and constrain fields before storage."""
    retention_hours = _get_retention_hours(retention_hours)
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=retention_hours)
    description_limit = max(1, min(max_desc_len, MAX_DESCRIPTION_CHARS))
    content_limit = max(1, min(max_content_len, MAX_CONTENT_CHARS))
    entry_limit = max(1, min(max_entries, MAX_FEED_ENTRIES))

    feed = feedparser.parse(content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"RSS 解析失败: {feed.bozo_exception}")

    feed_title = _clean_bounded(
        getattr(feed.feed, "title", ""),
        MAX_FEED_TITLE_CHARS,
    )
    results = []
    for entry in feed.entries[:entry_limit]:
        title = _clean_bounded(
            getattr(entry, "title", "无标题"),
            MAX_ARTICLE_TITLE_CHARS,
        ) or "无标题"
        link = _normalize_article_link(getattr(entry, "link", ""))
        if not link:
            continue

        raw_desc = getattr(entry, "summary", getattr(entry, "description", ""))
        desc = _clean_bounded(raw_desc, description_limit)

        if hasattr(entry, "content") and entry.content:
            raw_content = entry.content[0].value
        else:
            raw_content = raw_desc
        article_content = _clean_bounded(raw_content, content_limit)

        pub_time = parse_published_time(entry) or now_utc
        if enforce_retention and pub_time < cutoff:
            continue

        results.append(
            {
                "title": title,
                "link": link,
                "description": desc,
                "content": article_content,
                "published": pub_time.isoformat(),
            }
        )

    return {"feed_title": feed_title, "articles": results}

def fetch_and_clean(
    feed_url: str,
    retention_hours: int | None = None,
    max_desc_len: int = MAX_DESCRIPTION_CHARS,
    max_content_len: int = MAX_CONTENT_CHARS,
) -> dict:
    """
    抓取单个 RSS 源，返回清洗后的文章列表。
    自动过滤超过 retention_hours 的旧文章。
    """
    headers = {"User-Agent": USER_AGENT}
    content = fetch_public_bytes(
        feed_url,
        max_bytes=MAX_RSS_RESPONSE_BYTES,
        timeout=(RSS_CONNECT_TIMEOUT, FETCH_TIMEOUT),
        max_redirects=MAX_FEED_REDIRECTS,
        headers=headers,
    )
    return parse_feed_content(
        content,
        retention_hours=retention_hours,
        max_desc_len=max_desc_len,
        max_content_len=max_content_len,
    )


# ─── 核心：查重入库 ──────────────────────────────────

async def deduplicate_and_store(
    db: AsyncSession,
    articles: list[dict],
    feed_id: int,
) -> int:
    """
    将文章去重后写入数据库。
    利用 link 字段的 UNIQUE 约束，使用 INSERT OR IGNORE 避免重复。
    返回实际新增的文章数量。
    """
    inserted = 0
    inserted_links: list[str] = []
    for art in articles:
        stmt = (
            sqlite_insert(Article)
            .values(
                feed_id=feed_id,
                title=art["title"],
                link=art["link"],
                description=art["description"],
                content=art["content"],
                search_text=build_search_text(
                    title=art["title"],
                    description=art["description"],
                ),
                published=art["published"],
                ai_score=0,
                status="active",
            )
            .on_conflict_do_nothing(index_elements=["feed_id", "link"])
        )
        result = await db.execute(stmt)
        if result.rowcount > 0:
            inserted += 1
            inserted_links.append(art["link"])

    await db.commit()

    if not inserted_links:
        return inserted

    inserted_rows = await db.execute(
        select(Article.id)
        .where(Article.link.in_(inserted_links))
        .order_by(Article.id.asc())
    )
    inserted_article_ids = list(inserted_rows.scalars().all())

    for article_id in inserted_article_ids:
        try:
            await rebuild_article_chunks_for_article(db, article_id)
        except Exception as exc:
            logger.exception("chunk 生成失败 [article_id=%s]: %s", article_id, exc)

    return inserted


# ─── 核心：单源抓取流程（含熔断）────────────────────

async def fetch_single_feed(db: AsyncSession, feed: Feed, retention_hours: int | None = None) -> dict:
    """
    抓取单个订阅源的完整流程：
    1. 调用 fetch_and_clean 抓取并清洗
    2. 调用 deduplicate_and_store 去重入库
    3. 成功时重置 error_count，更新最后成功时间，如果 title 为空则补全
    返回 {"feed_id", "url", "fetched", "inserted", "error"} 摘要
    """
    result = {"feed_id": feed.id, "url": feed.url, "fetched": 0, "inserted": 0, "error": None}

    try:
        data = await asyncio.wait_for(
            asyncio.to_thread(
                fetch_and_clean,
                feed.url,
                retention_hours=retention_hours,
            ),
            timeout=RSS_TOTAL_TIMEOUT,
        )
        articles = data["articles"]
        feed_title = data["feed_title"]
        result["fetched"] = len(articles)

        if articles:
            inserted = await deduplicate_and_store(db, articles, feed.id)
            result["inserted"] = inserted

        # 成功：重置错误计数，更新最后成功时间，并视情况补全 title
        update_values = {
            "error_count": 0,
            "last_success_time": datetime.now(timezone.utc).isoformat(),
        }
        if not feed.title and feed_title:
            update_values["title"] = feed_title

        await db.execute(
            update(Feed)
            .where(Feed.id == feed.id)
            .values(**update_values)
        )
        await db.commit()


    except Exception as e:
        result["error"] = str(e)
        logger.warning(f"抓取失败 [{feed.url}]: {e}")

        # 累加错误计数
        new_count = (feed.error_count or 0) + 1
        new_status = "hibernated" if new_count >= MAX_ERROR_COUNT else feed.status

        await db.execute(
            update(Feed)
            .where(Feed.id == feed.id)
            .values(error_count=new_count, status=new_status)
        )
        await db.commit()

        if new_status == "hibernated":
            logger.warning(f"源已熔断休眠 [{feed.url}]，连续失败 {new_count} 次")

    return result


# ─── 顶层：全量同步 ──────────────────────────────────

async def sync_all_feeds(db: AsyncSession, retention_hours: int | None = None) -> dict:
    """
    遍历所有 active 状态的订阅源，依次抓取并入库。
    返回总体摘要 {"total_feeds", "total_fetched", "total_inserted", "errors": [...]}
    """
    retention_hours = _get_retention_hours(retention_hours)

    # 查询所有活跃源
    stmt = select(Feed).where(Feed.status == "active")
    result = await db.execute(stmt)
    feeds = result.scalars().all()

    summary = {
        "total_feeds": len(feeds),
        "total_fetched": 0,
        "total_inserted": 0,
        "errors": [],
        "details": [],
    }

    for feed in feeds:
        r = await fetch_single_feed(db, feed, retention_hours)
        summary["total_fetched"] += r["fetched"]
        summary["total_inserted"] += r["inserted"]
        summary["details"].append(r)
        if r["error"]:
            summary["errors"].append({"feed_id": feed.id, "url": feed.url, "error": r["error"]})

    logger.info(
        f"同步完成: {summary['total_feeds']} 源, "
        f"抓取 {summary['total_fetched']} 篇, "
        f"新增 {summary['total_inserted']} 篇, "
        f"失败 {len(summary['errors'])} 源"
    )

    return summary
