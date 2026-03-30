# Feedlite 实施计划 (Implementation Plan)

> 基于 README.md v2.4 需求文档生成，严格按照"先基础后业务，先后端后前端"的顺序推进。
> 每一步必须小而具体，严禁跳步。

---

## 第 1 步：数据库与 ORM 基础搭建

**目标**：确保 SQLite 数据库能正确初始化，WAL 模式生效，FTS5 触发器正常工作。

**指令**：
- 检查 `data/schemas.sql` 中的建表语句、索引、FTS5 虚拟表和三个触发器（INSERT/UPDATE/DELETE）是否完整
- 检查 `app/database.py` 中的异步引擎配置、WAL PRAGMA 设置、`init_db()` 冷启动逻辑
- 检查 `app/models.py` 中的 SQLAlchemy ORM 模型是否与 `schemas.sql` 表结构一一映射

**验证方法**：
- 删除 `data/feedlite.db`，运行 `init_db()`，确认数据库文件和 WAL 文件生成
- 执行 `PRAGMA journal_mode;` 确认返回 `wal`
- 手动插入一条 articles 记录，查询 `articles_fts` 确认触发器同步生效

---

## 第 2 步：FastAPI 应用主入口与静态文件挂载

**目标**：`app/main.py` 能启动 Web 服务，正确挂载前端静态页面，注册 API 路由。

**指令**：
- 在 `app/main.py` 中创建 FastAPI 实例
- 使用 `StaticFiles` 挂载 `static/` 目录
- 注册 `startup` 事件调用 `init_db()` 初始化数据库
- 挂载 `routers/feeds.py` 和 `routers/sources.py` 路由

**验证方法**：
- 运行 `uvicorn app.main:app --reload`，访问 `http://localhost:8000/static/index.html` 确认页面加载
- 访问 `http://localhost:8000/docs` 确认 Swagger 文档页面正常

---

## 第 3 步：信息流 API（文章列表与分页）

**目标**：前端能通过 API 获取文章列表，支持无限滚动分页。

**指令**：
- 在 `routers/feeds.py` 中实现 `GET /api/articles/` 接口
- 支持 `limit` 和 `offset` 参数，按 `published DESC, id DESC` 排序
- 只返回 `status='active'` 的文章
- 返回字段：id, title, link, description, published, ai_score, feedback, category（通过 JOIN feeds 表获取）

**验证方法**：
- 用 `insert_mock.py` 插入测试数据
- 访问 `GET /api/articles/?limit=5&offset=0` 确认返回 5 条文章
- 访问 `GET /api/articles/?limit=5&offset=5` 确认返回后续 5 条
- 打开前端页面确认卡片正常渲染

---

## 第 4 步：文章反馈 API（👍👎）

**目标**：前端点赞/踩操作能同步到后端数据库。

**指令**：
- 在 `routers/feeds.py` 中实现 `PATCH /api/articles/{id}/feedback` 接口
- 接收 `type` 参数（1 = 感兴趣，-1 = 不感兴趣），更新 articles 表的 `feedback` 字段

**验证方法**：
- 调用 `PATCH /api/articles/1/feedback?type=1`，确认返回成功
- 查询数据库确认 `feedback` 字段已更新
- 在前端点击 👍，刷新后确认状态保持

---

## 第 5 步：全文检索 API（FTS5）

**目标**：前端搜索框能通过 API 进行全文检索。

**指令**：
- 在 `routers/feeds.py` 中实现 `GET /api/articles/search` 接口
- 接收 `q` 参数，使用 FTS5 的 `MATCH` 语法查询 `articles_fts`
- 通过 `rowid` 关联回 `articles` 主表返回完整数据
- 前端 `app.js` 中搜索回车时调用此接口并渲染结果

**验证方法**：
- 搜索已有文章的关键词，确认返回匹配结果
- 搜索不存在的词，确认返回空数组
- 在前端搜索框输入关键词回车，确认页面刷新为搜索结果

---

## 第 6 步：订阅源管理 API（增删查 + 预览）

**目标**：前端弹窗能管理 RSS 订阅源。

**指令**：
- 在 `routers/sources.py` 中实现：
  - `GET /api/sources/` — 获取所有 active 状态的订阅源列表
  - `POST /api/sources/` — 添加新订阅源（url, category）
  - `DELETE /api/sources/{id}` — 软删除（status 改为 deleted）
  - `POST /api/sources/preview` — 接收 URL，调用 RSS 抓取逻辑返回前 3 条文章预览
- 前端 `app.js` 中订阅弹窗对接这些 API

**验证方法**：
- 添加一个 RSS URL，确认数据库中新增记录
- 预览一个 RSS URL，确认返回 3 条文章
- 软删除一个源，确认 status 变为 deleted 且前端不再显示

---

## 第 7 步：RSS 抓取引擎（核心爬虫）

**目标**：`services/rss_fetcher.py` 能抓取 RSS、清洗数据、执行时间过滤和 URL 查重。

**指令**：
- 实现 `fetch_and_clean(feed_url)` 函数：
  - 使用 `requests` + `feedparser` 抓取并解析
  - HTML 标签清洗、实体解码
  - 发布时间标准化为 UTC
  - 时间窗口过滤（丢弃超过 12 小时的旧文章）
- 实现 `deduplicate_and_store(articles, feed_id)` 函数：
  - 利用 `link` 字段的 UNIQUE 约束进行查重
  - 仅新文章入库（status 为 `unfiltered` 待打分）
- 实现源熔断：连续失败 5 次则标记为 `hibernated`

**验证方法**：
- 对测试 RSS URL 运行抓取，确认文章入库
- 再次运行同一 URL，确认不会重复插入
- 模拟网络错误 5 次，确认源被标记为休眠

---

## 第 8 步：AI 打分引擎

**目标**：`services/ai_scorer.py` 能批量调用大模型对新文章打分。

**指令**：
- 实现 `score_articles(articles)` 函数：
  - 从 `app_config` 表读取 AI 模型配置（API Key, 模型名, 接口地址）
  - 从 `users` 表读取 `base_prompt` 和 `active_tags`
  - 将待打分文章批量组装为 Prompt（每 50 篇一组）
  - 三级漏斗：偏好匹配 → 去噪过滤 → 推荐打分（0-100）
  - 解析返回的 JSON，更新 articles 表的 `ai_score` 和 `status`
- 支持 HTTP 代理配置（从 `config.yml` 读取）

**验证方法**：
- 手动插入几条 `status='unfiltered'` 的文章
- 运行打分函数，确认 `ai_score` 被更新且 `status` 变为 `active`
- 检查低于阈值的文章是否被标记为 `filtered`

---

## 第 9 步：定时任务调度器

**目标**：`services/scheduler.py` 按周期自动触发抓取 + 打分流水线。

**指令**：
- 使用 APScheduler 创建 `AsyncIOScheduler`
- 注册定时任务：按 `config.yml` 中的间隔（默认 12 小时）执行全量抓取与打分
- 在 `app/main.py` 的 `startup` 事件中启动调度器
- 实现 `POST /api/feeds/sync` 手动触发接口（Logo 点击刷新用）

**验证方法**：
- 启动服务，查看日志确认调度器注册成功
- 调用 `POST /api/feeds/sync`，确认手动触发抓取打分流水线
- 等待一个周期，确认自动触发执行

---

## 第 10 步：AI 画像管理 API

**目标**：前端弹窗能管理用户画像（Tags 和 System Prompt）。

**指令**：
- 在 `routers/feeds.py` 或新建 `routers/profile.py` 中实现：
  - `GET /api/profile/` — 获取当前用户的 `active_tags` 和 `base_prompt`
  - `PUT /api/profile/` — 更新 Tags 和 Prompt
- 前端 `app.js` 对接画像弹窗的保存和加载逻辑

**验证方法**：
- 在前端添加/删除 Tag，确认后端数据库同步
- 修改 System Prompt 并保存，确认下次打开弹窗时内容正确

---

## 第 11 步：Docker 化部署

**目标**：项目可通过 `docker-compose up` 一键启动。

**指令**：
- 完善 `Dockerfile`：安装依赖、复制代码、配置启动命令
- 完善 `docker-compose.yml`：端口映射、数据卷挂载、代理环境变量
- 确保 `data/` 目录通过 Volume 持久化

**验证方法**：
- 运行 `docker-compose up --build`，确认服务启动
- 访问 `http://localhost:8000` 确认功能正常
- 重启容器，确认数据库数据持久化
