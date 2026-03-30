# Feedlite 用户测试报告 (USER_TEST_RESULTS.md)

本报告记录了 Feedlite 在实际使用和部署过程中发现的问题及处理结果。

## 1 添加订阅 没有正确辨别订阅源的名称 [✅已处理]
- **现象**：添加订阅（如 https://www.polygon.com/rss/index.xml）后，数据库中 `feeds.title` 字段为空。
- **处理**：
  1. 后端 `add_source` 接口已支持接收 `title` 参数。
  2. 后端同步服务 `rss_fetcher.py` 增加了自动补全逻辑，若标题为空则从 RSS 元数据中提取。
  3. 前端已在添加订阅前增加预览步骤，并自动提取标题发送给后端。

## 2 添加订阅 缺少选择类型 [✅已处理]
- **建议**：添加订阅时应强制选择分类。
- **处理**：前端已改为“输入 URL -> 点击预览 -> 展示预览内容并显示必选分类下拉框 -> 点击添加”的流程。

## 3 订阅列表 缺少查看订阅预览按钮 [✅已处理]
- **建议**：订阅列表应能直接查看最新内容预览。
- **处理**：在“我的订阅”列表中为每个订阅源增加了“预览”图标按钮，点击可展开/折叠显示该源最新的 3 条文章。

## 4 Docker 部署时 AI 配置未从 .env 导入数据库 [✅已处理]
- **现象**：在 VPS 使用 Docker 部署时，`.env` 中配置的 `SCORER_*` 和 `PROFILER_*` 相关 AI 参数没有自动同步到数据库的 `ai_models` 表中，导致 AI 功能不可用。
- **处理**：
  1. 修改了 `app/database.py` 中的 `init_db` 函数。
  2. 增加了“冷启动自动注入”逻辑：当检测到 `ai_models` 表为空时，自动从环境变量读取配置并注入。
  3. 修正了 Provider 命名：将环境变量中可能存在的 `google` 统一转换为 `gemini` 存入数据库。
  4. 同时增加了默认管理员账户（`ADMIN_USERNAME`/`ADMIN_PASSWORD`）的自动初始化逻辑。

## 5 AI 请求组装逻辑不稳健及缺失 Gemini 原生支持 [✅已处理]
- **现象**：
  1. `api_base` 手动拼接 `/chat/completions` 容易导致 404（如果用户填写的地址已带后缀）。
  2. 缺乏 Google Gemini 原生 API（`:generateContent`）的组装逻辑。
- **处理**：
  1. **Gemini 支持**：在 `app/services/ai_scorer.py` 中增加了 `provider == "gemini"` 分支，支持原生 URL 格式和内容 JSON 结构。兼容 `google` 与 `gemini` 标识。
  2. **模型验证**：已确认支持 `gemini-3.1-flash-lite-preview` 模型（及其他 1.5/2.0 系列）。
  3. **URL 自动修正**：增加了对 `api_base` 的清洗逻辑，自动移除已有的重复后缀，并根据 Provider 自动补全缺失的路径（如 `/v1/messages` 或 `/chat/completions`）。

  3. **单元测试**：新增 `tests/test_ai_assembly.py` 用于验证不同 Provider 的请求组装正确性。

## 6 每周自动化用户画像分析缺失 [ ] 待处理
- **建议**：应按原计划每周运行一次，提取用户过去一周的“感兴趣”文章，由 AI (Profiler) 总结并更新用户画像。
- **状态**：已记录到 Backlog 项 #5。

## 7 RSS 自动抓取无法灵活配置 [ ] 待处理
- **建议**：目前抓取依赖应用启动时间，建议改为可配置 UTC 时间点（如每天 0:00, 12:00）及自定义周期。
- **状态**：已记录到 Backlog 项 #6。
