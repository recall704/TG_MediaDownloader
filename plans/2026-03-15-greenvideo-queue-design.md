# GreenVideo 下载队列设计方案

## 1. 架构概览

```
用户发送URL → text_message → 入队到 GreenVideo 队列 → 通知用户"已排队"
                                              ↓
                                     GreenVideo Worker (串行)
                                              ↓
                                     执行下载 → 通知用户完成
```

## 2. 核心组件

| 组件 | 职责 |
|------|------|
| `greenvideo_queue` | 专用队列，存储待下载的任务 |
| `greenvideo_worker` | 单个 worker，串行处理队列中的任务 |
| `enqueue_greenvideo_job` | 入队函数，将任务添加到队列 |

## 3. 数据结构

```python
# 队列项 (queue_item)
{
    "url": str,           # 视频链接
    "download_dir": str,  # 下载目录
    "message": Message,  # Telegram 消息对象（用于回复进度）
    "reply": Message,     # 状态消息（入队/下载中/完成）
    "enqueue_time": float # 入队时间戳
}
```

## 4. 实现步骤

### 4.1 添加队列和 Worker

在 `tg_downloader.py` 中：

1. 添加全局队列变量：
```python
greenvideo_queue: Queue = asyncio.Queue()
greenvideo_worker_task: Task | None = None
```

2. 添加入队函数 `enqueue_greenvideo_job`

3. 添加 worker 函数 `greenvideo_worker`

4. 在 `generate_workers` 中创建 greenvideo worker

### 4.2 修改 text_message

将直接调用 `await download_greenvideo(...)` 改为调用 `await enqueue_greenvideo_job(...)`

## 5. 用户体验

| 状态 | 消息内容 |
|------|----------|
| 入队 | "⏳ 已加入下载队列，前面还有 X 个任务" |
| 开始下载 | "🔍 正在解析视频链接..." |
| 下载中 | "📥 下载中... 进度: X%" |
| 完成 | "✅ 下载完成！..." |
| 失败 | "❌ 下载失败: 原因" |

## 6. 错误处理

- **FloodWait**: 使用现有的 `safe_edit_message` 处理
- **下载失败**: 通知用户错误
- **超时**: 继承现有的超时配置 `TG_DL_TIMEOUT`

## 7. 任务状态追踪

使用 `safe_edit_message` 更新状态消息，参考现有的 `download_greenvideo` 实现。