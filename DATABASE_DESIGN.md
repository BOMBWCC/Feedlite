## Feedlite 数据库详细设计文档 (v2.4)

### 1. 用户与画像表 (`users`)
单用户核心表，存储鉴权信息及 AI 偏好画像。

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `id` | Integer | Primary Key | - | 用户唯一标识符 |
| `username` | Text | Unique, Not Null | - | 登录账号 |
| `password_hash` | Text | Not Null | - | 密码哈希值 |
| `base_prompt` | Text | Nullable | - | 核心打分规则与系统提示词 |
| `active_tags` | Text | Nullable | - | 动态话题标签（直接用于 AI Prompt，如："openclaw,AI大模型"） |
| `created_at` | Text | Not Null | - | 账号创建时间 (UTC ISO 格式) |

### 2. 订阅源管理表 (`feeds`)
存储 RSS 频道信息，支持指数退避熔断机制。

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `id` | Integer | Primary Key | - | 订阅源 ID |
| `url` | Text | Unique, Not Null | - | RSS 原始链接 |
| `title` | Text | Nullable | - | 网站名称 |
| `category` | Integer | Not Null | 5 | 预设分类：1-时政商业 / 2-科技开发 / 3-游戏文娱 / 4-生活涉猎 / 5-综合与其他 |
| `error_count` | Integer | - | 0 | 连续失败次数 |
| `next_retry_time` | Text | Nullable | - | 下次允许重试的时间 (UTC ISO 格式，实现指数退避) |
| `last_success_time` | Text | Nullable | - | 最后成功抓取时间 |
| `status` | Text | - | 'active' | `active` (正常), `paused` (熔断中), `deleted` (软删除) |
| `created_at` | Text | Not Null | - | 订阅时间 |

### 3. 文章数据主表 (`articles`)
核心流水线数据表。**复合索引设计：`(status, published DESC, id DESC)`**。

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `id` | Integer | Primary Key | - | 文章 ID |
| `feed_id` | Integer | Foreign Key | - | 关联 `feeds.id` |
| `title` | Text | Not Null | - | 文章标题 |
| `link` | Text | Unique, Not Null | - | **【排重防线】** 文章原始链接 |
| `description`| Text | Nullable | - | 清洗后的简介 |
| `content` | Text | Nullable | - | 正文截取（不索引，仅存储） |
| `published` | Text | Not Null | - | 发布时间 (UTC ISO 格式) |
| `ai_score` | Integer | - | 0 | AI 打分结果 (0-100) |
| `feedback` | Integer | - | 0 | 用户反馈：`1` (👍), `-1` (👎), `0` (无) |
| `status` | Text | - | 'active' | `active` (达标), `filtered` (低分拦截), `deleted` (隐藏) |
| `created_at` | Text | Not Null | - | 抓取入库时间 |

### 4. 常规系统配置表 (`app_config`)
存储非敏感的零散全局系统配置（如：抓取策略间隔、未来可能的前端偏好等）。

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `key` | Text | Primary Key | - | 配置键名 |
| `value` | Text | Not Null | - | 配置内容 |
| `updated_at` | Text | Not Null | - | 最后更新时间 |

### 5. AI 模型角色配置表 (`ai_models`)
存储双引擎独立架构下的专属大模型调用凭证，具备最高优先级，系统读取时将**热覆盖** `.env` 与 `config.yml` 的环境变量。

| 字段名 | 类型 | 约束 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `role` | Text | Primary Key | - | 模型角色：`scorer` (海量筛选打分用) 或 `profiler` (智能生成画像用) |
| `provider` | Text | Not Null | 'openai' | 底层通道：如 `openai` / `anthropic`，核心底层会进行异构格式兼容 |
| `model_name` | Text | Not Null | - | 使用的大模型版本字串，如 `gpt-4o-mini` |
| `api_base` | Text | Not Null | - | 用于代理通道的 Base URL 覆写 |
| `api_key` | Text | Not Null | - | API 通行凭证 |
| `updated_at` | Text | Not Null | - | 动态调整时间 |

### 6. 全文检索虚拟表 (`articles_fts`) 与 同步触发器
采用“外部内容表模式”，仅在 `status = 'active'` 时通过 SQL 关联。

* **虚拟表结构 (`articles_fts`)**：包含 `title`, `description` 文本字段。
* **搜索 SQL**：
  ```sql
  SELECT a.* FROM articles_fts f
  JOIN articles a ON f.rowid = a.id
  WHERE f.title MATCH 'keyword' AND a.status = 'active'
  ORDER BY a.published DESC LIMIT 20;
  ```
* **触发器逻辑**：
    * `articles_ai`：插入新文章时同步分词。
    * `articles_au`：文章更新时同步索引（如标题修改）。
    * `articles_ad`：物理删除数据时清理索引。
