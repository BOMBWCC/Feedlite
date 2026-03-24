"""
Scheduler Service
核心职责：使用 APScheduler 定时触发 RSS 抓取 + AI 打分流水线
"""

import os
import logging

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger("feedlite.scheduler")

# ─── 全局调度器实例 ───────────────────────────────────
scheduler = AsyncIOScheduler()


def _get_interval_hours() -> int:
    """从 config.yml 读取抓取间隔（小时）"""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "config.yml"
    )
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("fetch", {}).get("interval_hours", 12)
    except Exception:
        return 12


async def _sync_job():
    """定时任务：抓取 + 打分"""
    from app.database import AsyncSessionLocal
    from app.services.rss_fetcher import sync_all_feeds
    from app.services.ai_scorer import score_unscored_articles

    logger.info("⏰ 定时同步任务开始...")

    async with AsyncSessionLocal() as db:
        fetch_summary = await sync_all_feeds(db)
        score_summary = await score_unscored_articles(db)

    logger.info(
        f"⏰ 定时同步完成: "
        f"抓取 {fetch_summary['total_fetched']} 篇, "
        f"新增 {fetch_summary['total_inserted']} 篇, "
        f"评分 {score_summary.get('scored', 0)} 篇"
    )


def start_scheduler():
    """启动定时调度器"""
    interval = _get_interval_hours()

    scheduler.add_job(
        _sync_job,
        trigger=IntervalTrigger(hours=interval),
        id="rss_sync",
        name=f"RSS 同步 (每 {interval} 小时)",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(f"✅ 调度器已启动，同步间隔: {interval} 小时")


def stop_scheduler():
    """关闭调度器"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("🛑 调度器已关闭")
