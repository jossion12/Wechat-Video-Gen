# 03 · API 接口规范

所有接口 base URL 为 `http://<host>:8000`,开发环境 Vite 代理转发。

## 3.1 接口清单

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/upload` | 上传头像/图片 |
| POST | `/api/preview-html` | 接收 ChatConfig,返回拼好的 HTML |
| POST | `/api/render` | 接收 ChatConfig,入队,返回 job_id |
| GET | `/api/jobs/{id}` | 查询任务状态(JSON) |
| GET | `/api/jobs/{id}/events` | SSE 流式进度 |
| GET | `/uploads/{file}` | 静态资源(头像/图片) |
| GET | `/outputs/{file}` | 静态资源(生成的 MP4) |
| GET | `/health` | 健康检查 |

## 3.2 `POST /api/upload`

**Request**: `multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | binary | ✓ | 文件二进制 |
| `kind` | string | ✗ | `avatar` 或 `image`,仅做语义标签 |

**约束**:
- 单文件 ≤ 2MB
- 允许 MIME:`image/png`、`image/jpeg`、`image/webp`、`image/gif`
- 后端重命名为 `{uuid}.{ext}`,避免文件名冲突

**Response 200**:
```json
{ "url": "/uploads/3f8a1c92.png", "kind": "avatar" }
```

**错误**:
- 400 文件为空 / 类型不允许
- 413 文件超过 2MB

## 3.3 `POST /api/preview-html`

**Request JSON**: `ChatConfig`(见 [02-data-model.md](./02-data-model.md))

**Response 200**:
```json
{ "html": "<!DOCTYPE html>...<body>...完整 HTML..." }
```

**错误**:
- 422 Pydantic 校验失败(自动返回错误明细)

## 3.4 `POST /api/render`

**Request JSON**: `ChatConfig`

**Response 202**:
```json
{ "job_id": "01HX2J3K9F8ABCDEFGHJKMNPQR" }
```

**错误**:
- 422 配置非法
- 503 队列已满(可配置上限,默认 100)

**副作用**:
- 任务入队
- SSE 端点可立刻订阅

## 3.5 `GET /api/jobs/{job_id}`

**Response 200**:
```json
{
  "id": "01HX2J3K9F8ABCDEFGHJKMNPQR",
  "status": "running",
  "progress": 42,
  "output_url": null,
  "error": null,
  "created_at": 1734567890.12,
  "finished_at": null
}
```

| 状态 | `progress` | `output_url` | `error` |
|---|---|---|---|
| `queued` | 0 | null | null |
| `running` | 0→100 实时推 | null | null |
| `done` | 100 | `/outputs/{id}.mp4` | null |
| `failed` | 0 | null | 异常信息 |

## 3.6 `GET /api/jobs/{job_id}/events` (SSE)

`Content-Type: text/event-stream`

每条事件形如:

```
event: progress
data: {"status":"running","progress":42}

event: done
data: {"status":"done","progress":100,"output_url":"/outputs/01HX2J3K9F8ABCDEFGHJKMNPQR.mp4"}

event: failed
data: {"status":"failed","error":"ffmpeg crashed"}
```

事件类型:
- `progress` — 录制中,周期性(每 500ms)推
- `done` — 录制完成,流关闭
- `failed` — 录制失败,流关闭

## 3.7 静态资源

```
GET /uploads/{filename}   → 头像/图片
GET /outputs/{filename}   → MP4 产物
```

后端用 FastAPI `StaticFiles` 挂载 `storage/uploads/` 和 `storage/outputs/`。

## 3.8 `GET /health`

```json
{ "status": "ok", "workers": 2, "queue_size": 0 }
```

## 3.9 CORS

开发环境(Vite 5173 → 后端 8000)允许跨域:

```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

生产环境前后端同源,无需 CORS。

## 3.10 速率限制

MVP 不引入限流(假设单用户场景)。上线后可选:
- `slowapi`(基于 IP)限制 `/api/render` 每分钟 5 次
- 上传限制单 IP 每天 50 张图片

## 3.11 错误格式

统一:
```json
{ "detail": "human-readable error message" }
```

FastAPI 默认格式;业务异常用 `HTTPException(status_code, detail)`。

## 3.12 OpenAPI 文档

FastAPI 默认暴露 `/docs`(Swagger UI)和 `/openapi.json`,开发时方便调试。
生产环境建议关闭或加 basic auth。