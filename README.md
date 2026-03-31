# FeedLite

AI 驱动的极简个人 RSS 阅读器。专为部署在 VPS 上设计，通过 AI 自动过滤和打分，从海量信息中提取高价值内容。

## 核心特性

- **AI 智能筛选**：基于用户画像和动态标签，自动为 RSS 文章打分（0-100），过滤噪音。
- **多模型支持**：原生支持 Google Gemini (1.5/2.0/3.1)、OpenAI 及 Anthropic Claude。
- **极致轻量**：单用户架构，SQLite 存储（开启 WAL 模式），原生 JS/CSS 前端，资源占用极低。
- **强健网络**：支持专属 AI 代理（SOCKS5/HTTP），解决 VPS IP 被 AI 供应商封锁的问题。
- **高效检索**：集成 SQLite FTS5，支持毫秒级全文搜索。
- **一键部署**：全 Docker 化，几分钟即可在 VPS 完成搭建。

## 快速开始

### 1. 克隆项目
```bash
git clone https://github.com/BOMBWCC/Feedlite.git
cd Feedlite
```

### 2. 配置环境变量
复制 .env.example 为 .env 并填写 API Key：
```bash
cp .env.example .env
```
编辑 .env：
- SCORER_API_KEY: 你的 AI API 密钥。
- ADMIN_PASSWORD: 设置你的登录密码。
- AI_SPECIFIC_PROXY: (可选) 如果 VPS IP 被封，填入代理地址。

### 3. Docker 部署
```bash
docker-compose up -d --build
```
访问 http://你的服务器IP:8000 即可开始使用。

## 使用说明

1. **添加订阅**：点击“订阅管理”，输入 URL 后先点击“预览”，确认内容无误后选择分类并添加。
2. **AI 画像**：在“AI 画像设置”中输入你的职业、兴趣点或当前关注的关键词，AI 将根据这些信息为你筛选新闻。
3. **手动同步**：系统会定时自动抓取，也可以通过点击页面左上角的 Logo 触发手动更新。
4. **调度时间**：RSS 抓取支持 `config.yml` 中配置固定 UTC 时间点；用户画像默认每周一 UTC `00:00` 生成，也可在 `config.yml` 中调整。

## 技术栈

- **Backend**: Python (FastAPI), SQLAlchemy, APScheduler
- **Database**: SQLite (FTS5 + WAL)
- **Frontend**: Vanilla JS, CSS Variables (Dark Mode ready)
- **Deployment**: Docker, Docker Compose

---
MIT License. Enjoy your personalized news stream.
