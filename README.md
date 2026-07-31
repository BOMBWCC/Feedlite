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
复制模板并生成本地配置文件：

```bash
cp .env.example .env
cp config.example.yml config.yml
```

编辑 `.env` 填写管理员凭据、JWT 密钥、AI API、代理和 RAG Key。编辑 `config.yml` 调整抓取、调度和翻译策略。各字段说明写在对应的 `.env.example` 和 `config.example.yml` 注释里。

生产环境至少生成以下随机值，并限制配置文件权限：

```bash
openssl rand -hex 24  # ADMIN_PASSWORD
openssl rand -hex 32  # JWT_SECRET
openssl rand -hex 32  # RAG_API_KEY（不用 RAG 时留空）
chmod 600 .env
```

应用会拒绝缺失、过短或仍为公开示例值的管理员密码和密钥。更换
`JWT_SECRET` 会使现有登录令牌失效；更换 `RAG_API_KEY` 后需要同步更新调用方。

### 3. Docker 部署
```bash
docker-compose up -d --build
```

Compose 默认只监听 `127.0.0.1:8000`。本机可访问
`http://127.0.0.1:8000`；远程访问必须通过启用 HTTPS 的反向代理，不要把
8000 端口直接暴露到公网。

### 4. 本地运行
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
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

## 生产安全要求

- 使用 Caddy、Nginx、Traefik 或同类反向代理终止 TLS，并只将 FastAPI
  监听在回环地址或受保护的容器网络。
- 防火墙只开放反向代理的 80/443；不要直接开放 8000。
- 保持 `DISABLE_AUTH=false`，并建议设置 `DISABLE_DOCS=true`。
- `.env` 必须保持 `0600` 权限，且不要进入 Git、普通语料备份或日志。
- 登录接口包含适用于默认单进程部署的内存限速。多 worker、多副本部署必须
  在反向代理或共享存储层增加统一限速。
- 反向代理场景下，只有在代理来源可信并正确清理转发头时，才能使用真实客户端
  IP 做限速；不要无条件信任来自公网的 `X-Forwarded-For`。
- 建议通过主机或云防火墙限制容器出站访问。应用会阻止 RSS 访问回环、私网、
  链路本地和保留地址，但网络层出口策略仍是防御 DNS 重绑定的必要补充。
- 定期轮换管理员密码、JWT 密钥、RAG Key 和 AI API Key。轮换后重新登录并更新
  所有 RAG 客户端。

## 技术栈

- **Backend**: Python, FastAPI, SQLAlchemy, APScheduler
- **Database**: SQLite (WAL, FTS5)
- **AI**: OpenAI-compatible APIs, Gemini, Anthropic
- **NLP/Search**: jieba, SQLite FTS5
- **Frontend**: Vanilla JS, CSS Variables (Dark Mode ready)
- **Deployment**: Docker, Docker Compose

---
MIT License. Enjoy your personalized news stream.
