import asyncio
import logging
import sys
import os

# 设置日志显示
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger("debug_sync")

# 确保能导入 app
sys.path.append(os.getcwd())

async def run_sync():
    from app.database import AsyncSessionLocal
    from app.services.rss_fetcher import sync_all_feeds
    from app.services.ai_scorer import score_unscored_articles
    
    logger.info("🚀 开始手动调试同步任务...")
    
    try:
        async with AsyncSessionLocal() as db:
            logger.info("Step 1: 正在尝试 RSS 抓取...")
            fetch_summary = await sync_all_feeds(db)
            logger.info(f"RSS 抓取完成: 抓取 {fetch_summary['total_fetched']} 篇, 新增 {fetch_summary['total_inserted']} 篇")
            
            logger.info("Step 2: 正在尝试 AI 打分...")
            score_summary = await score_unscored_articles(db)
            
            if score_summary.get("error"):
                logger.error(f"❌ AI 打分返回错误: {score_summary['error']}")
            
            logger.info(
                f"✅ 同步完成: "
                f"评分 {score_summary.get('scored', 0)} 篇, "
                f"跳过 {score_summary.get('skipped', 0)} 篇, "
                f"过滤 {score_summary.get('filtered', 0)} 篇"
            )
    except Exception:
        logger.exception("❌ 同步过程中发生非预期崩溃")

if __name__ == "__main__":
    asyncio.run(run_sync())
