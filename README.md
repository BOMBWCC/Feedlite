# FeedLite

AI 驱动的极简个人 RSS 阅读器。专为部署在 VPS 上设计，通过 AI 自动过滤和打分，从海量信息中提取高价值内容。

## 核心特性

- **AI 智能筛选**：基于 AI 画像与手工 Tag，自动为 RSS 文章打分（0-100），过滤噪音。
- **双层画像机制**：`base_prompt` 由 AI 根据最近反馈自动演进，`active_tags` 由用户手工维护且优先级更高。
- **多模型支持**：原生支持 Google Gemini、OpenAI 及 Anthropic Claude。
- **翻译与打分联动**：可按目标语言配置对标题和简介进行翻译，评分阶段优先使用译文、原文兜底。
- **极致轻量**：单用户架构，SQLite 存储（开启 WAL 模式），原生 JS/CSS 前端，资源占用极低。
- **强健网络**：支持专属 AI 代理（SOCKS5/HTTP）。
- **高效检索**：集成 SQLite FTS5 + 中文预分词，支持标题 / 简介 / 正文搜索、相关度排序和关键词高亮。
- **一键部署**：全 Docker 化，几分钟即可在 VPS 完成搭建。

## 快速开始

### 1. 克隆项目
```bash
git clone https://github.com/BOMBWCC/Feedlite.git
cd Feedlite
```

### 2. 配置环境变量与静态默认值
创建 `.env` 并填写基础凭据：

```env
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your-password

SCORER_PROVIDER=openai
SCORER_MODEL=gpt-4o-mini
SCORER_API_BASE=https://api.openai.com/v1
SCORER_API_KEY=your-scorer-key

PROFILER_PROVIDER=openai
PROFILER_MODEL=gpt-4o-mini
PROFILER_API_BASE=https://api.openai.com/v1
PROFILER_API_KEY=your-profiler-key

# 可选：给 OpenClaw / 内部 AI 检索接口使用
RAG_API_KEY=your-rag-api-key

# 可选：仅 AI 请求走代理
AI_SPECIFIC_PROXY=
```

编辑 `config.yml` 可调整默认行为：
- `fetch`: 抓取频率、固定 UTC 时间点、批次大小、保留窗口
- `profile`: 每周画像任务的 UTC 调度时间
- `translation`: 是否启用翻译、目标语言、是否翻译标题 / 简介

说明：
- `config.yml` 提供默认值
- `app_config` / `ai_models` 提供运行时生效值
- 应用启动时会将部分默认配置同步到数据库，便于后续持久化调整

### 3. Docker 部署
```bash
docker-compose up -d --build
```
访问 http://你的IP:8000 即可开始使用。

### 4. 本地运行
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. OpenClaw 接入

如果要把 Feedlite 当作 OpenClaw 的私有 RAG 知识源，最少只需要配置一个额外环境变量：

```env
RAG_API_KEY=your-rag-api-key
```

OpenClaw 调用时带上请求头：

```text
X-API-Key: <RAG_API_KEY>
```

第一版建议按这条链路接入：

1. 调用 `/api/rag/search?q=...` 获取候选 chunk
2. 取前几个 `chunk_id` 调用 `/api/rag/context`
3. 将返回的上下文拼进 OpenClaw prompt
4. 用模型生成最终回答，并附来源链接

示例：

```bash
curl -H "X-API-Key: ${RAG_API_KEY}" \
  "http://127.0.0.1:8000/api/rag/search?q=openai&limit=8&days=30"

curl -H "X-API-Key: ${RAG_API_KEY}" \
  "http://127.0.0.1:8000/api/rag/context?chunk_id=11&chunk_id=12&window=1"
```

## 使用说明

1. **添加订阅**：点击“订阅管理”，输入 URL 后先点击“预览”，确认内容无误后选择分类并添加。
2. **AI 画像**：在“AI 画像设置”中手工维护 `Tag`；系统会根据最近一周的喜欢 / 不喜欢反馈自动更新画像文本。
3. **自动同步**：系统会定时抓取 RSS、按需翻译标题 / 简介，并执行 AI 打分。
4. **搜索**：搜索框支持中文关键词、中英混合文本、正文命中和搜索态高亮展示。
5. **调度时间**：RSS 抓取支持 `config.yml` 中配置固定 UTC 时间点；用户画像默认每周一 UTC `00:00` 生成，也可在 `config.yml` 中调整。
6. **RAG 检索接口**：可通过 `RAG_API_KEY` 保护 `/api/rag/search`，供 OpenClaw 等内部 AI 调用；支持 `category` 过滤，默认按最近 30 天窗口检索，传 `days=0` 可关闭时间窗口。

## 技术栈

- **Backend**: Python, FastAPI, SQLAlchemy, APScheduler
- **Database**: SQLite (WAL, FTS5)
- **AI**: OpenAI-compatible APIs, Gemini, Anthropic
- **NLP/Search**: jieba, SQLite FTS5
- **Frontend**: Vanilla JS, CSS Variables (Dark Mode ready)
- **Deployment**: Docker, Docker Compose

---
MIT License. Enjoy your personalized news stream.
