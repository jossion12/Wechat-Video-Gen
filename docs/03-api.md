# 03 · API 接口规范

所有接口 base URL 为 `http://<host>:8000`,开发环境 Vite 代理转发。

> **多用户 / session 隔离**(2024-Q4 引入):除 `GET /health` 外,所有接口都要求请求头携带
> `X-User-Id: <user_id>`(MVP 鉴权,生产替换为 OIDC)。文件与产物不再走全局静态挂载,
> 改为 `/api/files/{file_id}` 和 `/api/jobs/{job_id}/output`,按 `(user_id, file_id)` 校验所有权。

## 3.1 接口清单

| 方法 | 路径 | 鉴权 | 用途 |
|---|---|---|---|
| GET | `/health` | — | 健康检查 |
| GET | `/api/me` | ✓ | 取/创建当前用户 |
| POST | `/api/sessions` | ✓ | 建一个 session(一次任务) |
| GET | `/api/sessions` | ✓ | 列当前用户的所有 session |
| GET | `/api/sessions/{id}` | ✓ | session 详情(含文件 + 任务) |
| DELETE | `/api/sessions/{id}` | ✓ | 删 session + 物理清理文件/产物 |
| POST | `/api/upload` | ✓ | 上传头像/图片(必带 `session_id`) |
| POST | `/api/preview-html` | ✓ | 接收 DSL + session_id,返回 HTML |
| POST | `/api/render` | ✓ | 接收 DSL + session_id,入队,返回 job_id |
| GET | `/api/jobs/{id}` | ✓ | 任务状态(所有权校验) |
| GET | `/api/jobs/{id}/events` | ✓ | SSE 进度(所有权校验) |
| GET | `/api/files/{file_id}` | ✓ | 取素材文件(所有权校验) |
| GET | `/api/jobs/{id}/output` | ✓ | 下载产物 MP4(所有权校验) |

## 3.2 鉴权

所有需鉴权的接口都从 `X-User-Id` header 取当前用户:

| Header | 必填 | 说明 |
|---|---|---|
| `X-User-Id` | ✓ | 用户 id,限 `[a-zA-Z0-9_-]{1,64}`;首次出现即在 `users` 表 upsert |

错误:
- 401 缺 header / 不合法字符
- 401 跨用户访问他人 session/file/job(等同"不存在",不泄露存在性)

## 3.3 `POST /api/sessions`

**Request JSON**(可选 body):
```json
{ "title": "可选标题" }
```

**Response 201**:
```json
{
  "id": "01HX2J3K9F8ABCDEFGHJKMN",
  "user_id": "alice",
  "title": "测试",
  "created_at": 1734567890.12,
  "last_active_at": 1734567890.12,
  "file_count": 0,
  "job_count": 0
}
```

## 3.4 `GET /api/sessions`

**Response 200**: 当前用户所有 session,按 `last_active_at` 倒序。

## 3.5 `GET /api/sessions/{id}`

**Response 200**: 在 3.3 基础上多 `files` / `jobs` 数组。

## 3.6 `DELETE /api/sessions/{id}`

**Response 204**: 同时清空该 session 的 `storage/users/{user_id}/sessions/{id}/` 目录。

## 3.7 `POST /api/upload`

**Request**: `multipart/form-data`

| 字段 | 必填 | 说明 |
|---|---|---|
| `file` | ✓ | 二进制,≤ 2MB,允许 png/jpeg/webp/gif |
| `kind` | ✓ | `avatar` / `image` / `background` |
| `session_id` | ✓ | 必须属于当前用户 |

文件落在 `storage/users/{user_id}/sessions/{session_id}/uploads/{file_id}.{ext}`。

**Response 200**:
```json
{
  "id": "01HX...",
  "session_id": "...",
  "user_id": "alice",
  "kind": "avatar",
  "ext": "png",
  "size": 102400,
  "content_type": "image/png",
  "created_at": 1734567890.12,
  "url": "/api/files/01HX..."
}
```

**错误**:
- 400 文件空 / 类型不允许
- 404 session 不存在或不属于当前用户
- 413 超过 2MB

## 3.8 `POST /api/preview-html`

**Request JSON**:
```json
{
  "dsl": { /* VideoDSL */ },
  "session_id": "01HX..."
}
```

**Response 200**: `{ "html": "<!DOCTYPE html>..." }`

## 3.9 `POST /api/render`

**Request JSON**: 同 3.8

**Response 202**: `{ "job_id": "01HX..." }`

**错误**:
- 404 session 不属于当前用户
- 503 队列已满

## 3.10 `GET /api/jobs/{id}`

**Response 200**:
```json
{
  "id": "01HX...",
  "status": "running",
  "progress": 42,
  "output_url": null,
  "error": null,
  "created_at": 1734567890.12,
  "finished_at": null
}
```

`output_url` 仅 `status == "done"` 时有值,形如 `/api/jobs/{id}/output`。
**404** 表示任务不存在或不属于当前用户(不区分,避免泄露)。

## 3.11 `GET /api/jobs/{id}/events` (SSE)

`Content-Type: text/event-stream`,事件格式与之前一致。
仅返回当前用户任务的事件。

## 3.12 `GET /api/files/{file_id}`

按所有权返回素材二进制。**404** 表示不属于当前用户或文件已被清理。

## 3.13 `GET /api/jobs/{job_id}/output`

返回产物 MP4(`video/mp4`)。仅 `status == "done"` 时可下载,否则 **409**。

## 3.14 `GET /api/me`

返回当前用户信息(`id`, `username`, `created_at`);首次调用会自动注册。

## 3.15 CORS

```python
allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8080"]
```

生产环境前后端同源,无需 CORS。

## 3.16 OpenAPI

`/docs`(Swagger UI)与 `/openapi.json`;生产建议关闭或加 basic auth。