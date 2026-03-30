# Feedlite 项目技术风险与演进策略 (v1.0)

本文档旨在记录系统设计中已知的边界情况、技术债务及对应的演进策略，供测试与维护参考。

---

## 1. 核心风险：抓取时间窗漏抓 (The 12-Hour Gap)

### 风险描述
当前 `rss_fetcher.py` 采用硬编码的 `DEFAULT_RETENTION_HOURS = 12` 过滤规则。
- **场景 A (宕机延迟)**：若服务器宕机或由于网络原因停止同步超过 12 小时，恢复后的第一次同步将跳过这段时间内的所有文章。
- **场景 B (低频更新源)**：对于某些周更或月更的源，12 小时的时间窗可能导致在非活跃期间发布的文章被永久忽略。
- **场景 C (时区偏移)**：若 RSS 源提供的 `published` 时间存在严重时区偏移（例如未标明时区且系统误认），文章可能因“早于 12 小时前”被直接丢弃。

### 应对策略 (演进方案)
1. **[短期] 扩大冗余**：将默认冗余时间从 12 小时扩大至 24 或 48 小时。由于系统具备 `URL UNIQUE` 查重机制，扩大时间窗不会导致重复入库，仅会略微增加 `deduplicate_and_store` 的循环开销。
2. **[长期] 动态基准线**：在 `feeds` 表中引入 `last_fetched_article_time` 字段。每次同步时，过滤条件改为 `pub_time > last_fetched_article_time`，彻底摆脱硬编码的时间窗限制。

---

### 2. 定时任务中的同步 IO 阻塞

### 风险描述
`rss_fetcher.py` 使用了 `requests` 库进行网络请求。
- **影响**：由于 `requests` 是同步阻塞的，在 `AsyncIOScheduler` 触发同步任务时，如果某个源响应极慢（15秒超时），整个 Python 事件循环会被挂起。这可能导致前端 API 响应变慢，甚至导致其他定时任务错过触发点。

### 应对策略
1. **[推荐] 更换异步库**：将 `requests` 替换为 `httpx` (推荐，接口兼容性好) 或 `aiohttp`。
2. **[折中] 线程池运行**：在 `sync_all_feeds` 中使用 `asyncio.to_thread(fetch_and_clean, ...)` 将阻塞任务派发到后台线程。

---

## 3. SQLite FTS5 索引与物理删除

### 风险描述
目前的 FTS5 搜索通过触发器同步。
- **风险**：如果未来为了清理过期数据进行了 `DELETE FROM articles` 物理删除操作，必须确保 `schemas.sql` 中的触发器覆盖了 `DELETE` 场景，否则索引表 (`articles_fts`) 会出现悬空记录，导致搜索结果指向不存在的 ID。

### 应对策略
- **软删除优先**：坚持使用 `status = 'deleted'`。
- **清理脚本**：若确需清理，编写专门的 `OPTIMIZE` 脚本，执行 `INSERT INTO articles_fts(articles_fts) VALUES('rebuild')` 重建索引。

---

## 4. AI 打分 Token 消耗与成本管理

### 风险描述
虽然目前仅对“标题”进行批量打分，但：
- **场景**：若用户订阅了大量高产出的源（如资讯快报类），每次同步可能产生上百篇文章。
- **风险**：即使是 gpt-4o-mini，在极大规模的标题堆叠下也会消耗显著 Token，且单次请求过长可能触及 4096 的上下文限制（Context Window）。

### 应对策略
1. **分批次处理**：目前的 `batch_size=50` 是合理的。
2. **前置去噪**：在 AI 打分前，通过简单的关键词黑名单（如“广告”、“日报”）在代码层面先过滤掉一部分垃圾信息，减少无效 Token 支出。

---

## 5. 近期改进实施计划 (Action Plan)

针对上述评估的技术风险，建议在项目的下一次小版本迭代中采用以下即插即用的落地方案：

### 行动项 A：全异步网络引擎重构 (解决 IO 阻塞)
- **目标文件**: `app/services/rss_fetcher.py`
- **实施路线**: 
  1. 移除 `requests` 依赖，引入已经安装好的 `httpx.AsyncClient`。
  2. 将 `fetch_and_clean(feed_url)` 升级为异步函数 `async def fetch_and_clean(feed_url, client)`，内部使用 `await client.get(...)` 无阻塞抓取并挂起，让出 CPU 给其他任务。
  3. `sync_all_feeds()` 使用 `asyncio.gather` 并发调度多个源的抓取，极大提升多源同步时的吞吐量，彻底解决单线程事件循环锁死问题。

### 行动项 B：增量更新水印溯源 (解决漏抓 Gap)
- **目标文件**: `app/models.py` & `app/services/rss_fetcher.py`
- **实施路线**: 
  1. 在 `Feed` 数据库模型中新增字段 `latest_article_pub_time = Column(Text)`。
  2. 原本硬链接的 `DEFAULT_RETENTION_HOURS = 12` 仅作为全新源第一次抓取的保底初始边界。
  3. 抓取并过滤入库后，计算本批次最新一篇文章的 `published` 锚点并刷入该字段。下次抓取只筛选严格大于该锚点时间戳的文章，彻底实现跨宕机的无缝衔接。

### 行动项 C：本地前置降噪守门员 (解决 Token 成本)
- **目标文件**: `app/services/ai_scorer.py`
- **实施路线**: 
  1. 在 `app_config` 中开辟一条通用级黑名单词距（如 `black_keywords = "广告,带货,推销,日报"`）。
  2. 在未打分文章数组送往 LLM 组装 Prompt 之前，使用纯 Python 层面的正则快速匹配，一旦命中黑名单，直接就地修改 `ai_score = -1, status = 'filtered'` 并执行一波 `db.commit()`。
  3. **不发出不花钱**，让大模型只去处理真正有价值的中性文章，省下极大的过路费。
