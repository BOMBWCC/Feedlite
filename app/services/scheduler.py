"""
Scheduler Service
核心职责：使用 APScheduler 定时触发 RSS 抓取 + AI 打分流水线
"""

import os
import logging
from datetime import timezone

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger("feedlite.scheduler")

# ─── 全局调度器实例 ───────────────────────────────────
scheduler = AsyncIOScheduler()


def _load_scheduler_config() -> dict:
    """从 config.yml 读取调度配置。"""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "config.yml"
    )
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _get_interval_hours() -> int:
    """从 config.yml 读取抓取间隔（小时）"""
    cfg = _load_scheduler_config()
    return cfg.get("fetch", {}).get("interval_hours", 12)


def _get_fetch_schedule_times() -> list[int]:
    """读取 RSS 固定抓取 UTC 小时点，形如 [0, 12, 18]。"""
    cfg = _load_scheduler_config()
    raw = cfg.get("fetch", {}).get("fixed_times_utc", [])
    if not isinstance(raw, list):
        return []

    normalized = []
    for item in raw:
        try:
            hour = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= hour <= 23 and hour not in normalized:
            normalized.append(hour)
    return sorted(normalized)


def _get_profile_schedule() -> dict:
    """读取用户画像任务的周级 UTC 调度配置。"""
    cfg = _load_scheduler_config()
    profile_cfg = cfg.get("profile", {})
    day_of_week = str(profile_cfg.get("day_of_week", "mon")).strip().lower() or "mon"

    try:
        hour = int(profile_cfg.get("hour_utc", 0))
    except (TypeError, ValueError):
        hour = 0

    try:
        minute = int(profile_cfg.get("minute_utc", 0))
    except (TypeError, ValueError):
        minute = 0

    hour = min(max(hour, 0), 23)
    minute = min(max(minute, 0), 59)

    return {
        "day_of_week": day_of_week,
        "hour_utc": hour,
        "minute_utc": minute,
    }


async def _sync_job():
    """定时任务：抓取 + 打分"""
    from app.database import AsyncSessionLocal
    from app.services.rss_fetcher import sync_all_feeds
    from app.services.ai_scorer import score_unscored_articles

    logger.info("⏰ 定时同步任务开始...")

    try:
        async with AsyncSessionLocal() as db:
            # RSS 抓取
            logger.info("正在执行 RSS 抓取流程...")
            fetch_summary = await sync_all_feeds(db)
            
            # AI 打分
            logger.info("正在执行 AI 打分流程...")
            score_summary = await score_unscored_articles(db)

        if score_summary.get("error"):
            logger.error(f"❌ 定时 AI 打分遇到问题: {score_summary['error']}")

        logger.info(
            f"⏰ 定时同步完成: "
            f"抓取 {fetch_summary['total_fetched']} 篇, "
            f"新增 {fetch_summary['total_inserted']} 篇, "
            f"评分 {score_summary.get('scored', 0)} 篇, "
            f"跳过 {score_summary.get('skipped', 0)} 篇"
        )
    except Exception:
        # 这里使用 logger.exception 会把整个 traceback 打印出来
        logger.exception("❌ 定时同步任务执行过程发生非预期异常")


async def _profile_job():
    """每周定时生成一次用户画像。"""
    from app.database import AsyncSessionLocal
    from app.services.profiler import generate_user_profile

    logger.info("🧠 用户画像更新任务开始...")

    try:
        async with AsyncSessionLocal() as db:
            summary = await generate_user_profile(db)

        if summary.get("updated"):
            logger.info(
                "🧠 用户画像更新完成: 喜欢 %s 篇, 不喜欢 %s 篇",
                summary.get("liked_count", 0),
                summary.get("disliked_count", 0),
            )
        else:
            logger.info("🧠 用户画像更新跳过: %s", summary.get("message", ""))
    except Exception:
        logger.exception("❌ 用户画像更新任务执行过程发生非预期异常")


def start_scheduler():
    """启动定时调度器"""
    interval = _get_interval_hours()
    fixed_times = _get_fetch_schedule_times()
    profile_schedule = _get_profile_schedule()

    if fixed_times:
        scheduler.add_job(
            _sync_job,
            trigger=CronTrigger(hour=",".join(str(hour) for hour in fixed_times), minute=0, timezone=timezone.utc),
            id="rss_sync",
            name=f"RSS 同步 (UTC 固定时点: {', '.join(f'{hour:02d}:00' for hour in fixed_times)})",
            replace_existing=True,
        )
        rss_schedule_text = "UTC 固定时点 " + ", ".join(f"{hour:02d}:00" for hour in fixed_times)
    else:
        scheduler.add_job(
            _sync_job,
            trigger=IntervalTrigger(hours=interval),
            id="rss_sync",
            name=f"RSS 同步 (每 {interval} 小时)",
            replace_existing=True,
        )
        rss_schedule_text = f"每 {interval} 小时"

    scheduler.add_job(
        _profile_job,
        trigger=CronTrigger(
            day_of_week=profile_schedule["day_of_week"],
            hour=profile_schedule["hour_utc"],
            minute=profile_schedule["minute_utc"],
            timezone=timezone.utc,
        ),
        id="weekly_profile",
        name=(
            f"用户画像更新 (每周 {profile_schedule['day_of_week']} "
            f"UTC {profile_schedule['hour_utc']:02d}:{profile_schedule['minute_utc']:02d})"
        ),
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "✅ 调度器已启动，RSS 调度: %s，画像任务: 每周 %s UTC %02d:%02d",
        rss_schedule_text,
        profile_schedule["day_of_week"],
        profile_schedule["hour_utc"],
        profile_schedule["minute_utc"],
    )


def stop_scheduler():
    """关闭调度器"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("🛑 调度器已关闭")
