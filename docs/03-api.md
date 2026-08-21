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
| POST | `/api/import` | ✓ | 导入 zip(DSL + 图片素材)到当前 session |
| GET | `/api/ai/health` | — | 检查 AI 接口连通性（不消耗额度） |
| GET | `/api/ai/quota` | ✓ | 查询 AI 生成额度 |
| POST | `/api/ai/generate-dialogue` | ✓ | 根据剧情概要生成完整对话 DSL |
| POST | `/api/ai/continue-dialogue` | ✓ | 基于已有 DSL 续写候选消息 |
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

## 3.17 `POST /api/import`

把一个 zip 压缩包（DSL + 图片素材）导入到当前 session，详见 [08-import-package.md](./08-import-package.md)。

**Request**: `multipart/form-data`

| 字段 | 必填 | 说明 |
|---|---|---|
| `file` | ✓ | 二进制，≤ 50MB（`IMPORT_MAX_ZIP_SIZE`），必须是合法 zip |
| `session_id` | ✓ | 必须属于当前用户 |

zip 内容：

```
my-dialogue.zip
├── dsl.json          # 必需
├── manifest.json     # 可选
├── avatars/...       # 推荐目录（仅约定）
├── backgrounds/...   # 推荐目录（仅约定）
└── images/...        # 推荐目录（仅约定）
```

**Response 200**：

```json
{
  "dsl": { /* 改写后的 VideoDSL，所有 zip 内图片已替换为 /api/files/{id} */ },
  "uploaded_files": [
    {
      "path_in_zip": "avatars/alice.png",
      "file_id": "01HX...",
      "url": "/api/files/01HX...",
      "kind": "avatar",
      "size": 12345,
      "deduped": false
    }
  ],
  "warnings": []
}
```

**错误**（响应体 `detail` 字段为结构化对象，详见 08-import-package.md §8.7）：

| HTTP | `code` | 触发条件 |
|---|---|---|
| 400 | `illegal_package` | 缺 dsl.json / 路径非法 / symlink |
| 400 | `bad_mime` | 实际 MIME 不在 png/jpeg/webp/gif |
| 400 | `bad_manifest` | manifest 解析失败或引用了不存在的文件 |
| 400 | `missing_files_in_zip` | DSL 引用了 zip 内不存在的文件 |
| 400 | `unsupported_video_url` | `Message.video_url` 指向了 zip 内文件（视频本体不导入） |
| 400 | `schema_version_mismatch` | schema_version 不是 "1.0" |
| 413 | `package_too_large` | zip 本体 > 50MB |
| 413 | `unpacked_too_large` | 解压后总大小 > 20MB |
| 413 | `file_too_large` | 单文件 > 2MB |
| 413 | `too_many_entries` | 条目数 > 1000 |
| 422 | `dsl_validation_failed` | Pydantic 字段校验失败 |
| 404 | — | session 不属于当前用户 |

**安全要点**（实现细节见 [08-import-package.md §8.6](./08-import-package.md)）：

- Zip Slip 防御：每个 entry 解压前校验路径在 safe_root 内
- Zip Bomb 防御：累加 `member.file_size`、限制条目数、限制压缩比
- 文件去重：同 session 内按 md5 复用现有 `file_id`
- 临时目录：用 `tempfile.TemporaryDirectory()`，处理完即清

**前端调用**：

```typescript
import { importZip } from './api';
const result = await importZip(file, sessionId);
// result.dsl → 替换前端 state
// result.uploaded_files.length → toast
// setCurrentStep(5) → 跳到预览
// 不自动触发 /api/render
```

## 3.18 AI 辅助生成

### `GET /api/ai/health`

检查 AI 接口连通性，**不消耗额度，无需鉴权**，方便运维排查。

**Response 200**：

```json
{
  "configured": true,
  "reachable": true,
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o-mini",
  "http_status": 401
}
```

`reachable: true` 只表示网络可到达；`http_status` 是测试请求返回的 HTTP 状态码（常见 401/400，说明地址和端口是对的）。

如果 `reachable: false`，`reason` 会给出排查方向（如 Docker 容器内 localhost 问题、代理未启动等）。

### `GET /api/ai/quota`

查询当前用户今日 AI 生成额度。

**Response 200**：

```json
{
  "daily_limit": 50,
  "used_today": 3,
  "remaining_today": 47
}
```

### `POST /api/ai/generate-dialogue`

根据剧情概要生成完整对话 DSL。

**Request JSON**：

```json
{
  "session_id": "...",
  "synopsis": "两个朋友商量周末计划...",
  "mode": "single",
  "style_theme": "comic",
  "intent": "short_video_drama",
  "num_messages": 8
}
```

**Response 200**：完整 `VideoDSL`。

**错误**：

| HTTP | `code` | 触发条件 |
|---|---|---|
| 400 | `parse_error` | AI 返回无法解析为 JSON |
| 400 | `validation_error` | AI 生成内容未通过 DSL 校验 |
| 429 | `quota_exceeded` | 当日额度已用完 |
| 503 | `not_configured` | 服务端未配置 `AI_API_KEY` |
| 503 | `upstream_error` / `timeout` | AI 接口异常或超时 |

### `POST /api/ai/continue-dialogue`

基于已有 DSL 续写候选消息。

**Request JSON**：

```json
{
  "session_id": "...",
  "dsl": { /* VideoDSL */ },
  "num_candidates": 3
}
```

**Response 200**：

```json
{
  "candidates": [
    { "sender_id": "p1", "kind": "text", "text": "...", "delay_ms": 1500 },
    ...
  ]
}
```

## 3.19 鉴权与 session 隔离（重申）

所有 `/api/import`、`/api/ai/*` 请求同样要求 `X-User-Id` header，且 `session_id` 必须属于该 user。
跨用户访问返回 404（不区分原因，避免泄露存在性）。