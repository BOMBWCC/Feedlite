# FeedLite 待办与优化清单 (Backlog)

本文档用于记录项目在核心功能（11步计划）完成之后，规划新增的功能模块或架构优化。

## 1. 简易登录系统 (Authentication) [x] 已完成
**目的**：为项目公网部署做准备，提供最基本的访问隔离（针对单用户）。
**实现思路**：
- **认证方式**：轻量级 JWT Token 认证（不使用 Session）。
- **凭据来源**：初始化时从 `.env` 读取 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD`。
- **后端改造**：
  - 新增 `POST /api/auth/login` 接口返回 JWT Token（有效期可配）。
  - 给所有核心的 `/api/*` 路由加上依赖倒置的 Token 拦截校验 (`Depends(verify_token)`)。
- **前端改造**：
  - 增加一个全屏的简洁登录页，未获取有效 Token 时强制渲染此页面。
  - 获取 Token 后存入 `localStorage`，并在后续全局 `fetch` 请求时带入 `Authorization: Bearer <token>` 头部。

## 2. 双重 AI 角色架构 (Dual AI Models) [x] 已完成
**目的**：由于打分和处理用户画像对模型能力的要求不同，需要分离配置。
**实现思路**：
- **角色划分**：
  - **Scorer (打分引擎)**：专门负责海量 feed 信息流的高频过滤打分（适合廉价/高并发模型，如 GPT-4o-mini 或 DeepSeek）。 
  - **Profiler (画像引擎)**：负责整理用户画像、生成复杂的检索 Prompt（适合高推理级别的模型，如 GPT-4o 或 Claude 3.5 Sonnet）。
- **数据结构演进**：
  - 抛弃原先扁平的 `app_config` 中的零散 AI 配置。
  - 新建一张专门的 `ai_models` 表：
    ```sql
    CREATE TABLE ai_models (
        role TEXT PRIMARY KEY,        -- 'scorer' / 'profiler'
        provider TEXT NOT NULL,       -- 'openai' / 'anthropic' / 等
        model TEXT NOT NULL,
        api_base TEXT NOT NULL,
        api_key TEXT NOT NULL
    );
    ```
- **接口适配**：在 `app/services/ai_scorer.py` 等模块中，向下层 `_call_llm` 暴露的时候明确区分 `provider` 以做响应体结 构的兼容（尤其是针对非 OpenAI 协议的厂商）。

## 3. 分层配置体系与环境变量 (.env 集成) [x] 已完成
**目的**：让服务部署更加安全、规范，避免敏感 API Key 硬编码或仅能在系统启动后手动填入。
**实现思路**：
- **层级设计**：文件默认值 (`config.yml`) -> 部署环境变量 (`.env`) -> 运行时热调整 (`SQLite ai_models`)。
- **`.env` 管理**：禁止提交入 Git，放置运维级参数，格式参考：
  ```env
  ADMIN_USERNAME=admin
  ADMIN_PASSWORD=strongpassword123
  JWT_SECRET=generate-a-strong-jwt-secret

  # AI 初始下发环境变量（如果没有记录会自动写入 DB）
  SCORER_API_BASE=https://api.openai.com/v1
  SCORER_API_KEY=sk-xxxxxx
  SCORER_MODEL=gpt-4o-mini

  PROFILER_API_BASE=https://api.anthropic.com
  PROFILER_API_KEY=sk-ant-xxxx
  PROFILER_MODEL=claude-3-5-sonnet
  ```
- **Docker 集成**：在 `docker-compose.yml` 中声明 `- env_file: .env` 即可注入容器。FastAPI 启动时（冷启动）根据环境变量进行安全配置的自举。

---
*注：上述各项任务可以在界面迭代和 Docker（Step 11）准备过程中逐步开展。建议优先级：前端迭代 > 登录鉴权及环境变量注入 > Docker Compose 化 > 双 AI 角色拆分。*

## 4. 取消“感兴趣/不感兴趣”的交互支持 [x] 已完成
**目的**：提供用户反悔的机制，允许取消已经点过的 👍 或 👎。
**实现思路**：
- **后端支持**：后端 `PATCH /api/articles/{id}/feedback` 接口其实已经原生支持了 `type=0` 代表取消反馈，所以后端只需确认可用即可。
- **前端改造**：
  - 修改 `app.js` 里的点击事件逻辑：如果在点击时，该按钮**已经**有了 `active` 的类名，代表用户是想取消。
  - 此时发送 `type=0` 给 API，并双向移除卡片上所有反馈按钮的 `active` 状态。

## 5. 每周自动化用户画像分析 (Weekly Profiling) [ ] 待处理
**目的**：根据用户的实际点击反馈，动态自我进化，让 AI 筛选越来越准。
**实现思路**：
- **定时触发**：使用 APScheduler 增加一个周级任务（Weekly）。
- **数据提取**：抓取数据库中过去 7 天所有 `feedback = 1` (点赞) 的文章标题、简介及分类。
- **AI 处理 (Profiler)**：
  - 调用 `profiler` 角色模型。
  - 将点赞文章打包发送，要求 AI 总结用户本周的关注重点、兴趣迁移和核心关键词。
- **画像更新**：将 AI 总结的关键词自动追加或合并到用户的 `active_tags` 和 `base_prompt` 中。

## 6. 增强型 RSS 抓取配置 (Configurable Scheduling) [ ] 待处理
**目的**：摆脱目前依赖应用启动时间的相对间隔，支持更可控的定时抓取（如 UTC 定时）。
**实现思路**：
- **配置扩展**：在 `config.yml` 或 `.env` 中支持 Cron 表达式或固定时间点设置。
  - 例：`FETCH_SCHEDULE_UTC="0,12"` 代表每天 UTC 0点和 12点运行。
- **调度器改造**：修改 `app/services/scheduler.py`，根据配置决定使用 `interval` 模式还是 `cron` 模式启动任务。

## 7. 全文搜索优化 (Search Optimization) [ ] 待处理
**目的**：解决当前搜索功能对中文支持差、检索范围有限以及缺乏过滤功能的问题。
**优化建议**：
- **中文分词支持**：引入 `jieba` 分词库。在文章存入数据库前进行预分词，或者在 FTS5 中使用支持中文的分词器（如 `simple` 配合预分词或第三方插件）。
- **扩大检索范围**：修改 `articles_fts` 定义，将 `content` (正文) 纳入索引范围，目前仅索引了 `title` 和 `description`。
- **排序与相关度**：优化搜索结果排序，结合 `rank` (相关度) 和 `published` (发布时间) 进行双重排序。
- **分类过滤支持**：在搜索接口 `/api/articles/search` 中增加 `category` 参数，支持在特定分类下进行搜索。
- **搜索体验提升**：
  - **搜索高亮**：利用 FTS5 的 `snippet()` 函数实现搜索结果中的关键词高亮。
  - **查询预处理**：对用户输入进行清洗和转义，防止特殊字符导致 FTS 语法错误或查询崩溃。
- **自动化测试**：完善搜索功能的单元测试，涵盖中文关键词、特殊字符和分类过滤等场景。
