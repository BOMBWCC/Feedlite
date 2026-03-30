# Feedlite 架构说明 (Architecture)

本文档记录项目中各模块的具体职责。

| 文件/目录 | 职责说明 |
| :--- | :--- |
| memory-bank/ | 项目核心记忆库，存储需求、技术栈、架构与进度。 |
| app/ | FastAPI 后端核心源码目录。 |
| app/database.py | 数据库连接、Session 管理及 WAL 模式配置。 |
| app/models.py | SQLAlchemy 异步模型定义（含 User, Feed, Article, AppConfig）。 |
| app/routers/ | 按照功能划分的 API 路由模块（feeds, sources, profile）。 |
| app/services/ | 核心业务逻辑实现：抓取 (rss_fetcher), 打分 (ai_scorer), 调度 (scheduler)。 |
| static/ | 前端单页面应用 (SPA) 静态资源 (index.html, style.css, app.js)。 |
| data/ | 生产环境下 SQLite 数据库 (feedlite.db) 及 schemas SQL 持久化目录。 |
| scripts/ | 独立测试脚本与运维工具（如 insert_mock.py, test_rss.py）。 |
