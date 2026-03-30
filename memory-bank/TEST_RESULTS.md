# Feedlite 项目测试报告 (v1.2)

本报告记录了 Feedlite 项目功能模块的单元测试与集成测试结果。

---

## 1. 测试环境
- **测试框架**：Pytest 9.0.2
- **环境**：Python 3.12.10 (win32)
- **核心插件**：
  - `pytest-asyncio`: 异步测试支持
  - `pytest-mock`: Mock 模拟支持
  - `respx`: HTTP Mock 模拟
  - `httpx`: 异步 HTTP 客户端（用于集成测试）

---

## 2. 测试覆盖范围

### 2.1 核心逻辑 (`tests/test_core.py`) - [通过]
1. `test_clean_html`: HTML 标签剥离、实体字符解码。
2. `test_parse_published_time`: RSS 时间结构解析。
3. `test_build_scoring_prompt`: AI 打分 Prompt 模板构建。
4. `test_parse_scores`: AI 返回 JSON 数据解析。

### 2.2 业务服务 (`tests/test_services.py`) - [通过]
1. `test_deduplicate_and_store`: 数据库唯一约束去重逻辑。
2. `test_fetch_and_clean_with_mocker`: 爬虫引擎抓取与清洗流程。
3. `test_verify_token_valid`: 合法 JWT 鉴权通过。
4. `test_verify_token_invalid`: 非法 JWT 鉴权拦截。
5. `test_get_ai_config_env_priority`: AI 配置环境变量覆盖优先级。
6. `test_build_scoring_prompt_with_tags`: 动态用户标签注入打分 Prompt。

### 2.3 深度集成测试 (`tests/test_api.py`) - [通过]
1. `test_full_auth_flow`: 真实 `/api/auth/login` 网络层鉴权全流程。
2. `test_sources_crud_flow`: 订阅源“增、删、查”网络层闭环逻辑。
3. `test_profile_flow`: 用户画像（Tags/Prompt）持久化与回显。
4. `test_article_feedback_flow`: 文章反馈（点赞/踩）的端到端状态变更。

---

## 3. 测试执行统计 (2026-03-23)
| 模块 | 测试函数数量 | 状态 |
| :--- | :--- | :--- |
| **深度集成测试 (API)** | **4** | ✅ 100% |
| **核心工具逻辑 (Core)** | **4** | ✅ 100% |
| **业务逻辑服务 (Service)** | **6** | ✅ 100% |
| **总计** | **14 个用例** | **全部通过** |

---

## 4. 改进建议
1. **时区警告 (已修复)**：代码中 `datetime.utcnow()` 已全部迁移至 `datetime.now(timezone.utc)`。
2. **Token 安全 (已修复)**：JWT 密钥已升级为 64 字符强随机密钥。
3. **FTS5 专项测试**：目前搜索逻辑依赖于 SQLite 插件，建议在部署到真实环境后增加大数据量下的性能压测。
