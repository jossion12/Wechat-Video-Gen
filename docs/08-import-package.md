# 08 · 压缩包导入设计

> 让用户把一次"对话剧场"任务（DSL + 所有图片素材）打包成一个 zip 上传，导入到当前 session，
> 然后在第 5 步直接看到预览（**不自动触发 MP4 渲染**，由用户手动决定是否生成视频）。

本设计文档回答以下问题：

- zip 包应该长什么样
- 后端如何安全解压、解析、改写 DSL
- 前端如何呈现导入按钮、把导入结果应用到当前 state
- 哪些坑必须防（Zip Slip / Zip Bomb / session 越权 / schema 错位）

## 8.1 范围与非目标

**在本期范围内**：

- `POST /api/import` 接 zip（multipart/form-data），把图片批量上传到当前 session、改写 DSL、返回改写后的 DSL
- 前端在 Header 增加按钮 + 主区域拖拽支持
- 单文件 2MB、解压后总大小 20MB、zip 本体 50MB 的硬限制
- 安全防护：Zip Slip、解压炸弹、缺失文件、schema 版本校验
- 一份说明文档（`docs/08-import-package.md` + 用户向的 `examples/import/README.md`）

**不在本期范围**（明确推迟）：

- ❌ 导出当前 session 为 zip（`/api/export`）—— 等真有"分享/备份"需求再做
- ❌ "下载示例 zip"按钮 —— 改为 `examples/import/README.md` 说明文档
- ❌ 自动触发 MP4 渲染 —— 导入后只跳到第 5 步预览，让用户自己点"生成视频"
- ❌ 多 DSL / 多场景合并导入 —— 1 个 zip = 1 个 DSL
- ❌ 向前兼容旧 schema —— 严格只接受 `schema_version: "1.0"`，旧版明确报错
- ❌ **导入视频本体**（`Message.video_url`）—— 视频文件不进 zip，只能引用绝对 URL / data URI / `/api/files/...`（详见 §8.3.3）；视频封面图 `cover_url` 作为图片可以正常导入

## 8.2 压缩包结构

### 8.2.1 推荐目录布局

```
my-dialogue.zip
├── dsl.json          # 必需；顶层 VideoDSL（详见 docs/02-data-model.md）
├── manifest.json     # 可选；显式声明 DSL 中 URL → zip 内文件路径的映射
├── avatars/          # 推荐放头像（仅约定，不强制）
│   ├── alice.png
│   └── bob.jpg
├── backgrounds/      # 推荐放背景图（仅约定，不强制）
│   └── bg.jpg
└── images/           # 推荐放聊天图片 / 视频封面（仅约定，不强制）
    ├── chat-1.jpg
    └── chat-2.png
```

> **约定而非强制**：后端不校验 `avatars/`、`backgrounds/`、`images/` 这几个目录的存在或用法。
> 这些只是给用户的"心智锚点"，让他们打开 zip 时一眼看出哪里放什么。
> 真正的引用关系靠 8.3 节的 URL 解析规则决定。

### 8.2.2 必需文件

| 文件 | 必需 | 说明 |
|---|---|---|
| `dsl.json` | ✓ | 顶层 `VideoDSL`；必须是 `schema_version: "1.0"`；MIME = `application/json` |
| 其他文件名 | ✗ | 全部视为"附加素材"，按 8.3 规则匹配 |

### 8.2.3 缺失 `dsl.json` 的处理

返回 `400 illegal_package` + 错误明细：

```json
{
  "detail": {
    "code": "illegal_package",
    "reason": "missing dsl.json (case-sensitive, must be at zip root)"
  }
}
```

**不**试图自动猜测（避免"看起来像 dsl"但其实是别的配置文件导致后续错误难排查）。

## 8.3 URL 引用规则（核心约定）

DSL 中凡是引用**图片**的字段（`scene.background_image_url`、`scene.participants[*].avatar_url`、`scene.messages[*].image_url`、`scene.messages[*].cover_url`），URL 的解析按以下优先级：

| 优先级 | 形态 | 含义 | 示例 |
|---|---|---|---|
| 1 | `manifest.json` 中声明的映射 | 用 `path_in_zip` 在 zip 内查找 | 见 8.3.1 |
| 2 | zip 内**存在的相对路径**（不含 `http://`、`https://`、`data:`、以 `/uploads/` 或 `/api/files/` 开头） | 当作"虚拟路径"，从 zip 根目录按路径读 | `avatars/alice.png`、`images/chat-1.jpg` |
| 3 | 绝对 URL / `data:` URI / `/uploads/...` / `/api/files/...` | 保留不动 | `https://cdn.example.com/xxx.png`、`/uploads/abc.png` |
| 4 | 相对路径但 zip 内不存在 | **整包拒绝**（见 8.6） | — |

`Message.video_url` 不在上述规则范围内——视频本体不导入，详见 §8.3.3。

### 8.3.1 `manifest.json`（可选）

用于把"语义化 URL"映射到 zip 内路径，避免在 DSL 里写一大串相对路径。结构：

```json
{
  "files": {
    "alice_avatar":    "avatars/alice.png",
    "bob_avatar":      "avatars/bob.jpg",
    "background":      "backgrounds/bg.jpg",
    "first_chat_img":  "images/chat-1.jpg"
  }
}
```

**优先级最高**：如果 `manifest.json` 存在且声明了某 key，DSL 里 URL 写 `"alice_avatar"` 也会被解析。

**用途**：用户可以做"模板化 DSL"——同一个 DSL 配不同的 manifest + 图片就能复用。

### 8.3.2 URL 形态的判定

```python
def is_zip_relative_path(url: str) -> bool:
    lower = url.lower()
    if lower.startswith(("http://", "https://", "data:")):
        return False
    if url.startswith("/"):  # /uploads/, /api/files/, /xxx 等
        return False
    return True
```

- 不允许 zip 内文件路径含 `..` 段（避免 Zip Slip）
- 不允许绝对路径段（如 `/etc/passwd`）
- 大小写敏感（zip 在 Linux 服务器上区分大小写，统一按**原始大小写**匹配）

### 8.3.3 DSL 中所有需要改写的字段

后端递归遍历以下字段，遇到 8.3 优先级 1/2 的情况就改写成 `/api/files/{file_id}`：

| 字段路径 | 元素 | 处理 |
|---|---|---|
| `scene.background_image_url` | 整页背景图 | 正常改写 |
| `scene.participants[*].avatar_url` | 头像 | 正常改写 |
| `scene.messages[*].image_url` | 图片消息 | 正常改写 |
| `scene.messages[*].cover_url` | 视频封面图 | **作为图片正常改写**（封面是图） |
| `scene.messages[*].video_url` | 视频本体 | **不允许从 zip 导入**（见下） |

#### 视频消息的特殊处理

**视频本体不进入 zip**，因为：

- 视频体积远超 2MB / 20MB 限制
- 需转码、跨浏览器兼容复杂
- 本期不做专门的"视频上传"接口

具体规则：

| `video_url` 形态 | 处理 |
|---|---|
| zip 内相对路径（如 `videos/clip.mp4`） | **整包拒绝** `unsupported_video_url`（不允许把视频塞进 zip） |
| `https://...` / `http://...` | 保留原样（指向外部 CDN / 现有资源） |
| `data:video/...` | 保留原样 |
| `/uploads/...` / `/api/files/...` | 保留原样（指向之前 session 的产物或素材） |
| `manifest.json` 中声明的 key 指向视频文件 | **整包拒绝** `unsupported_video_url` |

**视频消息本身可以出现在 DSL 中**：即 `kind: "video"` 的消息不会被整包拒绝，只要它的 `video_url` 不是 zip 内路径；`cover_url` 作为图片正常从 zip 导入。

错误示例（整包拒绝）：

```json
{
  "detail": {
    "code": "unsupported_video_url",
    "reason": "Message[2].video_url points to a file inside the zip; video body is not importable in this release",
    "message_index": 2,
    "offending_path": "videos/clip.mp4"
  }
}
```

## 8.4 导入流程（端到端）

```
┌─────── 前端 ─────────────────────────────┐     ┌─────── 后端 ──────────────────────────────┐
│ 1. 用户点 [导入 zip] 按钮                  │     │                                           │
│   或拖拽 zip 进主区域                      │     │                                           │
│ 2. 校验扩展名 == .zip / mime == zip        │     │                                           │
│ 3. 禁用预览 / 显示 loading                 │     │                                           │
│ 4. fetch POST /api/import                  │────▶│ 5. 鉴权(get_current_user)                 │
│   file: File                               │     │ 6. 校验 session 归属                      │
│   session_id: 当前 session                 │     │ 7. 读 zip 到临时目录(Zip Slip / Bomb 防护) │
│   overwrite: false (UI 不暴露,默认追加)     │     │ 8. 解析 dsl.json → Pydantic 校验          │
│                                            │     │ 9. 解析 manifest.json(若有)                │
│                                            │     │ 10. 递归遍历 DSL 中所有 URL 字段           │
│                                            │     │ 11. 对每个 zip 内文件:                     │
│                                            │     │     - md5 去重(复用现有 file_id)           │
│                                            │     │     - 调内部 upload_path() 落盘            │
│                                            │     │     - 写 files 表                          │
│                                            │     │ 12. 改写 DSL 中的 URL                      │
│                                            │     │ 13. 清理临时目录                            │
│                                            │     │ 14. 返回 {dsl, uploaded_files, warnings}    │
│ 15. 用返回的 dsl 替换 state                │◀────│                                           │
│ 16. setCurrentStep(5) 跳到预览生成步骤      │     │                                           │
│ 17. setJobId(null) 清空旧 job              │     │                                           │
│ 18. 重新触发预览(iframe srcDoc 防抖刷新)   │     │                                           │
│ 19. 显示导入摘要 toast(成功 X 张 / 跳过 Y)  │     │                                           │
└────────────────────────────────────────────┘     └───────────────────────────────────────────┘
```

## 8.5 大小与数量限制

所有阈值通过环境变量配置（见 8.10），默认值：

| 项 | 默认值 | 环境变量 | 说明 |
|---|---|---|---|
| zip 本体大小 | 200 MB | `IMPORT_MAX_ZIP_SIZE` | FastAPI 层校验 |
| 解压后总大小 | 500 MB | `IMPORT_MAX_UNPACKED_SIZE` | 累加 `member.file_size`；预留 2.5x buffer 给图片解压 |
| 单文件大小 | 10 MB | `MAX_UPLOAD_SIZE`（复用） | 与现有 `/api/upload` 一致 |
| 条目数 | 1000 | `IMPORT_MAX_ENTRIES` | 防解压炸弹 / 慢攻击 |
| 单层目录深度 | 8 | `IMPORT_MAX_DEPTH` | 防 `a/a/a/.../file.png` 攻击 |

**任何一项超限 → 立即终止，`413 / 400 illegal_package`**。

> **生产部署注意**：`docker-compose.yml` 部署时，浏览器 → nginx → uvicorn → importer，请求体大小在 nginx 层被 `client_max_body_size` 截断（默认 1MB）。**`deploy/nginx.conf` 必须设置 `client_max_body_size ≥ IMPORT_MAX_ZIP_SIZE + 20MB`（预留 multipart buffer）**，否则超过限制的 zip 在 nginx 层返回 `413 Request Entity Too Large`（nginx 标准 HTML 错误页，不是 importer 的结构化 JSON 响应）。详见 [05-deployment.md §5.4.1](./05-deployment.md)。

## 8.6 安全防护（必读）

### 8.6.1 Zip Slip 防护

恶意 zip 用 `../../etc/passwd` 这类条目逃出解压目录。**必须**在解压前对每个 entry 校验：

```python
safe_root = Path(temp_dir).resolve()
for member in zf.infolist():
    target = (safe_root / member.filename).resolve()
    if not (target == safe_root or str(target).startswith(str(safe_root) + os.sep)):
        raise PackageError(f"illegal path in zip: {member.filename}")
```

同时拒绝以下条目：

- `member.filename` 含 `..` 段
- `member.filename` 是绝对路径（Windows `C:\...` 或 Unix `/...`）
- `member.filename` 是符号链接（`member.external_attr` 标记）

### 8.6.2 Zip Bomb 防护

- 解压前累加所有 `member.file_size`（解压**前**大小，zip bomb 通常压缩比极高），超 `IMPORT_MAX_UNPACKED_SIZE` 立即拒
- 限制条目数 `IMPORT_MAX_ENTRIES`（1000）
- 解压过程中实时监控已写入字节数，每写一个文件累加，超限即停 + 清临时目录
- 限制压缩比（可选，单文件压缩后/压缩前 < 100，否则拒）

### 8.6.3 session 越权

导入必须挂到当前 session：

- 鉴权依赖 `get_current_user`（与其他 `/api/*` 一致）
- `db.get_session(session_id)` 后必须 `sess["user_id"] == user.id`，否则 404
- 不允许通过 `session_id` form 字段越权操作其他用户的 session

### 8.6.4 schema 版本严格校验

- `dsl.json` 必须能通过 Pydantic `VideoDSL.model_validate_json()`
- `schema_version` 必须 == `"1.0"`，其他值直接 `400 schema_version_mismatch`
- Pydantic 校验失败时，把第一条错误位置 + msg 转成结构化响应（不泄露 traceback）

### 8.6.5 文件去重（防 session 素材膨胀）

同一文件重复导入不应产生冗余 file_id：

- 对每个 zip 内文件计算 md5（hex），先与当前 session 已有 files 比对
- 命中 → 复用现有 `file_id`，不重新写盘，标记 `deduped: true`
- 不命中 → 走正常 upload 流程（生成新 file_id）

> **去重范围**：仅在**当前 session** 内去重。不跨 session、不跨用户。

### 8.6.6 MIME / 大小二次校验

解压后**再校验**一次每个文件的实际 MIME（不是 zip 内声明的）：

- 用前 16 字节嗅探（MIME magic）
- 不在 `ALLOWED_MIME`（png/jpeg/webp/gif）的 → 整包拒绝 `unsupported_file_type`
- 这是为了防止"扩展名是 .png 但其实是 html/script"

### 8.6.7 临时目录清理

- 用 `tempfile.TemporaryDirectory()`（with 上下文保证退出时删）
- 即便中途抛异常，也要在 finally 里手动 `shutil.rmtree(..., ignore_errors=True)`
- 绝不让临时文件落进 `uploads/`（避免和现有素材混在一起）

## 8.7 错误码与响应格式

### 8.7.1 响应体统一结构（成功）

```json
{
  "dsl": { /* 改写后的完整 VideoDSL */ },
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
  "warnings": [
    "README.txt 在 zip 内但未被任何 DSL URL 引用（已忽略）"
  ]
}
```

### 8.7.2 错误响应结构

```json
{
  "detail": {
    "code": "missing_files_in_zip",
    "reason": "DSL 引用了 2 个 zip 内不存在的文件",
    "missing": [
      "avatars/alice.png",
      "images/chat-3.jpg"
    ]
  }
}
```

### 8.7.3 错误码表

| HTTP | `code` | 触发条件 | 附加字段 |
|---|---|---|---|
| 400 | `illegal_package` | zip 结构不合法（缺 dsl.json / 路径非法 / 多 dsl.json） | `reason` |
| 400 | `bad_mime` | 文件实际 MIME 不允许 | `path`, `detected_mime` |
| 400 | `bad_manifest` | manifest.json 解析失败或引用了不存在的文件 | `reason`, `path` |
| 400 | `missing_files_in_zip` | DSL 引用了 zip 内不存在的文件 | `missing: string[]` |
| 400 | `unsupported_video_url` | `Message.video_url` 指向了 zip 内文件 | `message_index`, `offending_path` |
| 400 | `schema_version_mismatch` | schema_version 不是 1.0 | `got`, `expected` |
| 413 | `package_too_large` | zip 本体 > 50MB | `limit` |
| 413 | `unpacked_too_large` | 解压后 > 20MB | `limit` |
| 413 | `file_too_large` | 单个文件 > 2MB | `path`, `limit` |
| 413 | `too_many_entries` | 条目数 > 1000 | `limit` |
| 422 | `dsl_validation_failed` | Pydantic 校验失败 | `errors: ValidationError[]` |
| 404 | — | session 不属于当前用户（不区分错误原因，避免泄露） | — |

## 8.8 后端模块设计

### 8.8.1 新增文件

```
backend/app/
├── importer.py          # 新增：解压 + 解析 + URL 改写
└── tests/
    └── test_importer.py # 新增：单元测试 + 防护测试
```

### 8.8.2 `importer.py` 公共 API

```python
@dataclass
class ImportedFile:
    path_in_zip: str
    file_id: str
    url: str
    kind: Literal["avatar", "image", "background"]
    size: int
    deduped: bool

@dataclass
class ImportResult:
    dsl: VideoDSL
    uploaded_files: list[ImportedFile]
    warnings: list[str]

def import_package(
    zip_bytes: bytes,
    session_id: str,
    user_id: str,
    *,
    max_zip_size: int = ...,
    max_unpacked_size: int = ...,
    max_entries: int = ...,
    max_single_file_size: int = ...,
) -> ImportResult:
    """解压 → 校验 → 改写 → 落盘;失败抛 PackageError."""

class PackageError(Exception):
    """导入失败的领域异常,带 code + detail 字段."""
    code: str
    detail: dict
```

### 8.8.3 `main.py` 新增路由

```python
@app.post("/api/import", response_model=ImportResponse)
async def import_package_route(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    user: CurrentUser = Depends(get_current_user),
):
    # 1. 鉴权 + session 归属
    sess = await asyncio.to_thread(db.get_session, session_id)
    if sess is None or sess["user_id"] != user.id:
        raise HTTPException(404, "session not found")

    # 2. 读 zip
    zip_bytes = await file.read()
    try:
        result = await asyncio.to_thread(
            importer.import_package,
            zip_bytes=zip_bytes,
            session_id=session_id,
            user_id=user.id,
        )
    except importer.PackageError as exc:
        raise HTTPException(exc.http_status, {"code": exc.code, **exc.detail})

    # 3. 落 DSL（不写库，只在前端 state 用;不创建 job）
    # 导入不直接触发 render,前端替换 state 后自己走 /api/render

    return ImportResponse(
        dsl=result.dsl,
        uploaded_files=[...],
        warnings=result.warnings,
    )
```

### 8.8.4 复用现有 upload 逻辑

不引入重复的上传路径计算 / DB 写入代码。`importer.import_package` 内部：

1. 把 zip 解到临时目录
2. 对每个 zip 内文件 → 计算 md5 → 与当前 session 的 files 表去重
3. 未命中 → 调用现有的 `storage.upload_path()` + `db.insert_file_async()`（与 `/api/upload` 一致的路径）
4. 这样**所有文件最终落 `storage/users/{user_id}/sessions/{session_id}/uploads/`**，与现有机制完全一致

> 解耦点：在 `storage.py` 抽一个 `save_upload_bytes(user_id, session_id, data, ext, kind) -> (file_id, url)`，
> 让 `/api/upload` 和 importer 都调用它（小幅重构，避免逻辑分裂）。

## 8.9 前端 UX

### 8.9.1 入口位置

| 位置 | 形式 |
|---|---|
| Header 顶部"导入"按钮 | `App.tsx` header 区加一个 secondary 按钮，旁边一个 `<input type="file" accept=".zip">` |
| 主区域拖拽 | `WizardLayout` 的 form/preview 容器监听 `dragover` / `drop`；仅接受 `.zip` |

### 8.9.2 导入时禁用编辑

- 导入过程中（loading 状态），所有表单控件禁用
- Header "导入"按钮显示 spinner + "导入中…"
- 用户体验：不允许在导入未完成时点"生成视频"

### 8.9.3 成功后行为

```
importZip 成功
    ↓
setDsl(result.dsl)         ← 替换前端 state
setJobId(null)             ← 清掉旧 job（之前的产物/进度都没意义）
setCurrentStep(5)          ← 跳到第 5 步
showToast(`导入 ${uploaded_files.length} 张图片${warnings.length ? `,${warnings.length} 条提示` : ''}`)
```

预览 iframe 会因 `dsl` state 变化自动重渲染（现有防抖机制，300ms）。

### 8.9.4 错误展示

- 4xx 错误 → Header 顶部红色 banner（与现有 `error-banner` 样式统一）
- 5xx → 同样 banner + 提示"请稍后重试"
- `missing_files_in_zip` 这种结构化错误 → banner 内显示明细 + 文件名列表

### 8.9.5 前端新增 `api.ts` 函数

```typescript
export interface ImportResponse {
  dsl: VideoDSL;
  uploaded_files: Array<{
    path_in_zip: string;
    file_id: string;
    url: string;
    kind: 'avatar' | 'image' | 'background';
    size: number;
    deduped: boolean;
  }>;
  warnings: string[];
}

export async function importZip(
  file: File,
  sessionId: string,
): Promise<ImportResponse> {
  const form = new FormData();
  form.append('file', file);
  form.append('session_id', sessionId);
  return requestJson<ImportResponse>('/api/import', {
    method: 'POST',
    body: form,
  });
}
```

## 8.10 配置（环境变量）

在 `backend/app/storage.py`（或新建 `backend/app/importer.py` 顶部）声明：

```python
IMPORT_MAX_ZIP_SIZE = int(os.getenv("IMPORT_MAX_ZIP_SIZE", str(50 * 1024 * 1024)))       # 50MB
IMPORT_MAX_UNPACKED_SIZE = int(os.getenv("IMPORT_MAX_UNPACKED_SIZE", str(20 * 1024 * 1024)))  # 20MB
IMPORT_MAX_ENTRIES = int(os.getenv("IMPORT_MAX_ENTRIES", "1000"))
IMPORT_MAX_DEPTH = int(os.getenv("IMPORT_MAX_DEPTH", "8"))
```

`MAX_UPLOAD_SIZE` 沿用现有值（默认 2MB），不引入新变量。

## 8.11 测试用例（覆盖到验收）

### 8.11.1 单元测试 `backend/tests/test_importer.py`

| 场景 | 预期 |
|---|---|
| 合法 zip（含 dsl.json + 2 张头像 + 1 张背景图） | 成功，DSL 中 URL 改写为 `/api/files/{id}` |
| zip 缺 dsl.json | `PackageError(code="illegal_package")` |
| dsl.json 引用了 zip 内不存在的文件 | `PackageError(code="missing_files_in_zip")`，missing 列出 |
| dsl.json 引用 `https://...` 绝对 URL | 成功，URL 保持不动 |
| dsl.json 引用 `data:image/png;base64,...` | 成功，data URI 保持不动 |
| 带 `manifest.json` 的 zip | 优先用 manifest 解析 |
| dsl.json 含 `kind: "video"`，`video_url` 是 `https://...` | 成功，`video_url` 保留，`cover_url` 正常导入 |
| dsl.json 含 `kind: "video"`，`video_url` 是 zip 内路径 | `PackageError(code="unsupported_video_url")` |
| dsl.json 含 `kind: "video"`，`video_url` 是 manifest key | `PackageError(code="unsupported_video_url")` |
| schema_version 不是 1.0 | `PackageError(code="schema_version_mismatch")` |
| 同文件重复导入 | `deduped: true`，file_id 复用 |
| zip 内有未引用的 README.txt | `warnings: ["README.txt ... 已忽略"]`，不报错 |

### 8.11.2 安全测试

| 场景 | 预期 |
|---|---|
| zip 含 `../../../etc/passwd` 条目 | `PackageError(code="illegal_package", reason="illegal path")` |
| zip 含绝对路径条目 `C:\evil.exe` | `PackageError` |
| zip 含 symlink 条目 | `PackageError` |
| zip 本体 > 50MB | HTTP 413 `package_too_large` |
| zip 解压后 > 20MB | `PackageError(code="unpacked_too_large")` |
| zip 含 10000 个条目 | `PackageError(code="too_many_entries")` |
| 单个文件 > 2MB | `PackageError(code="file_too_large")` |
| 实际 MIME 是 html（扩展名是 png） | `PackageError(code="bad_mime")` |

### 8.11.3 端到端

| 场景 | 预期 |
|---|---|
| 用户点"导入"→ 选合法 zip → 成功 | 第 5 步预览 iframe 正确渲染头像/背景/图片 |
| 用户点"导入"→ 拖拽 .txt 文件 | 前端拦截（accept=".zip"） |
| 用户点"导入"→ 含 video 消息且 video_url 指向 zip 内 | 红色 banner "视频文件不能导入，请使用绝对 URL" |
| 用户点"导入"→ 含 video 消息且 video_url 指向 https | 成功，视频预览正常加载，cover_url 正常导入 |
| 导入后点"生成视频" | 与正常流程一致生成 MP4（导入不应影响后续渲染） |

## 8.12 兼容性

- **schema_version 严格**：只接受 `"1.0"`。未来 `2.0` 引入时，由 importer 按 `schema_version` 分发
- **前向兼容**：本期实现不要假设未来的字段；遇到未知字段应忽略（不要崩）
- **破坏性变更**：本期导入功能上线不影响 `/api/upload`、`/api/render` 的现有行为

## 8.13 工时（参考）

| 模块 | 工作量 |
|---|---|
| 后端 `importer.py`（解压 + 改写 + 防护） | 1.5 人天 |
| 后端 `/api/import` 路由 + storage 重构 | 0.3 人天 |
| 后端测试（单测 + 安全测试） | 0.5 人天 |
| 前端"导入"按钮 + 拖拽 + state 替换 | 0.5 人天 |
| 错误展示 + toast | 0.2 人天 |
| 文档（本文件 + `examples/import/README.md`） | 0.3 人天 |
| **合计** | **3.3 人天** |

不含导出功能、不含示例 zip 下载按钮。

## 8.14 相关文档

- 数据模型：[02-data-model.md](./02-data-model.md)
- API 接口：[03-api.md](./03-api.md)（新增 3.17 节）
- 安全 / 部署：[05-deployment.md](./05-deployment.md)
- 用户向说明：[examples/import/README.md](../examples/import/README.md)