# 生产环境排查说明：定时 RSS 正常、AI 自动打分未生效

## 结论

代码层面最核心的问题不是“定时任务没有调用 AI 打分”，而是：

- 定时任务确实调用了 AI 打分
- 但 AI 打分失败时，`scheduler` 没有把失败原因打出来
- 最终在生产上表现成“RSS 正常执行，AI 打分像是没有执行”

手动执行之所以看起来正常，是因为手动接口会把 `score_summary["error"]` 返回出来；而定时任务不会。

## 关键代码位置

### 1. 定时任务里调用了 AI 打分

文件：`app/services/scheduler.py`

```python
async with AsyncSessionLocal() as db:
    fetch_summary = await sync_all_feeds(db)
    score_summary = await score_unscored_articles(db)
```

对应位置：

- `app/services/scheduler.py:41`
- `app/services/scheduler.py:43`

说明：

- 自动任务和手动任务都调用同一个 `score_unscored_articles(db)`
- 所以问题不在“自动”和“手动”走了不同业务逻辑

### 2. 定时任务没有输出 AI 打分失败原因

文件：`app/services/scheduler.py`

当前代码只记录：

```python
logger.info(
    f"⏰ 定时同步完成: "
    f"抓取 {fetch_summary['total_fetched']} 篇, "
    f"新增 {fetch_summary['total_inserted']} 篇, "
    f"评分 {score_summary.get('scored', 0)} 篇"
)
```

问题：

- 没有处理 `score_summary.get("error")`
- 所以 AI 打分即使失败，日志里也只会看到“评分 0 篇”之类的信息

对应位置：

- `app/services/scheduler.py:45`

### 3. AI 打分函数本身是“失败后返回 error，不抛异常”

文件：`app/services/ai_scorer.py`

关键逻辑：

```python
if not ai_config.get("api_key"):
    summary["error"] = "AI API Key 未配置，跳过打分"
    logger.warning(summary["error"])
    return summary
```

以及：

```python
except Exception as e:
    logger.error(f"批次打分失败 (batch {i // batch_size + 1}): {e}")
    summary["error"] = str(e)
```

说明：

- AI Key 缺失时，不会抛异常，只会返回 `summary["error"]`
- 某一批调用 LLM 失败时，也只是写 `summary["error"]`
- 如果上层 `scheduler` 不记录这个 error，生产上就无法直接看出根因

对应位置：

- `app/services/ai_scorer.py:318`
- `app/services/ai_scorer.py:371`

### 4. 手动接口会把错误带出来，定时任务不会

文件：`app/routers/feeds.py`

手动接口里有：

```python
if score_summary.get("error"):
    msg_parts.append(f"打分提示: {score_summary['error']}")
```

对应位置：

- `app/routers/feeds.py:127`

说明：

- 手动触发时，你更容易看到 AI 打分失败信息
- 定时触发时，失败信息被隐藏

## 可能出现的真实错误类型

补完日志后，生产环境大概率会暴露出以下某一种实际错误：

- `AI API Key 未配置，跳过打分`
- `OpenAI API Error 401/403/500`
- `Gemini API Error 400/401/403/500`
- `Gemini API 返回格式异常`
- `无法解析 LLM 返回的 JSON`

## 额外注意事项

### 1. 当前配置文件不是每 12 小时，而是 24 小时

文件：`config.yml`

```yaml
fetch:
  interval_hours: 24
```

对应位置：

- `config.yml:5`

如果你生产环境希望每 12 小时执行一次，需要确认生产实际加载到的配置是否已经同步。

### 2. 异步任务里使用了同步 requests

文件：

- `app/services/rss_fetcher.py`
- `app/services/ai_scorer.py`

示例位置：

- `app/services/rss_fetcher.py:74`
- `app/services/ai_scorer.py:190`
- `app/services/ai_scorer.py:229`
- `app/services/ai_scorer.py:264`

说明：

- 这不是这次现象最直接的根因
- 但会导致 async 定时任务阻塞事件循环
- 在生产环境中会增加超时、卡住、调度不稳定的概率

这个问题建议后续修，但第一优先级不是它

## 最小改动建议

### 必改 1：在 scheduler 中记录 AI 打分错误

修改文件：`app/services/scheduler.py`

建议改成：

```python
async def _sync_job():
    from app.database import AsyncSessionLocal
    from app.services.rss_fetcher import sync_all_feeds
    from app.services.ai_scorer import score_unscored_articles

    logger.info("⏰ 定时同步任务开始...")

    try:
        async with AsyncSessionLocal() as db:
            fetch_summary = await sync_all_feeds(db)
            score_summary = await score_unscored_articles(db)

        if score_summary.get("error"):
            logger.error(f"⏰ 定时 AI 打分失败: {score_summary['error']}")

        logger.info(
            f"⏰ 定时同步完成: "
            f"抓取 {fetch_summary['total_fetched']} 篇, "
            f"新增 {fetch_summary['total_inserted']} 篇, "
            f"评分 {score_summary.get('scored', 0)} 篇, "
            f"跳过 {score_summary.get('skipped', 0)} 篇, "
            f"过滤 {score_summary.get('filtered', 0)} 篇"
        )
    except Exception:
        logger.exception("⏰ 定时同步任务异常退出")
```

目的：

- 把 AI 打分失败信息明确输出到生产日志
- 给定时任务加完整 traceback

### 建议 2：AI 打分批次失败时打印 traceback

修改文件：`app/services/ai_scorer.py`

把：

```python
logger.error(f"批次打分失败 (batch {i // batch_size + 1}): {e}")
```

改成：

```python
logger.exception(f"批次打分失败 (batch {i // batch_size + 1}): {e}")
```

目的：

- 直接在生产日志中看到完整调用栈
- 方便快速确认是鉴权失败、网络失败、返回格式错误还是别的问题

### 建议 3：API Key 缺失时输出更多上下文

修改文件：`app/services/ai_scorer.py`

把：

```python
summary["error"] = "AI API Key 未配置，跳过打分"
```

改成类似：

```python
summary["error"] = (
    f"AI API Key 未配置，跳过打分 "
    f"(role={ai_config.get('role')}, provider={ai_config.get('provider')}, model={ai_config.get('model')})"
)
```

目的：

- 直接从日志看出生产上实际拿到了什么 AI 配置
- 方便核对数据库配置、环境变量配置和配置文件配置的优先级结果

## 上线后应重点观察

代码同步后，下一次定时执行请重点查看日志中是否出现以下内容：

- `定时 AI 打分失败`
- `定时同步任务异常退出`
- `AI API Key 未配置`
- `OpenAI API Error`
- `Gemini API Error`
- `Gemini API 返回格式异常`
- `无法解析 LLM 返回的 JSON`

## 配置优先级说明

`_get_ai_config()` 的优先级是：

1. 数据库 `ai_models`
2. 环境变量
3. `config.yml`

文件位置：

- `app/services/ai_scorer.py:43`

所以排查时不要只看 `config.yml`，要同时确认：

- 生产数据库里的 `ai_models`
- 容器 / 服务启动时注入的环境变量
- 当前挂载进去的 `config.yml`

## 最终判断

单看当前代码，最直接的根因不是“自动任务没有触发 AI 打分”，而是：

**自动任务触发了 AI 打分，但失败信息在 scheduler 层被隐藏了。**

先补日志，再看下一次定时执行的真实报错，才能确认最终是：

- 配置问题
- 鉴权问题
- 网络问题
- provider 接口兼容问题
- LLM 返回格式问题
