# 02 · 数据模型

所有数据模型用 [Pydantic v2](https://docs.pydantic.dev/) 定义，
位于 `backend/app/models.py` 与 `backend/app/dsl.py`。

## 2.1 `Participant` — 对话角色

```python
class Participant(BaseModel):
    id: str                    # 唯一 id，前端生成，如 'me' / 'alice' / 'bob'
    name: str                  # 显示名，例如 '小美'
    avatar_url: str | None     # '/uploads/<uuid>.png' 或 None
    persona: str | None = None # 角色设定 / 性格标签（MVE 仅保存，不启用 AI）
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | ✓ | 在 `ChatScene` 内唯一；消息通过 `sender_id` 引用 |
| `name` | string | ✓ | 气泡上方的小字，最多 16 个字符 |
| `avatar_url` | string 或 null | ✗ | 头像图；若为 `null` 则显示六边形首字母占位 |
| `persona` | string 或 null | ✗ | 角色设定 / 性格标签，最多 200 字符 |

**约定**：
- 对谈模式时 `id == "me"` 表示自己，放第一位
- 群像模式时 `id` 可自由命名；若希望自己的发言走右侧，把 `id == "me"` 的参与者放在列表里
- 头像文件大小 ≤ 2MB，后端 `POST /api/upload` 自动校验

## 2.2 `Message` — 一条对话消息

```python
class Message(BaseModel):
    sender_id: str                                  # 引用 Participant.id
    kind: Literal["text", "image", "sys", "timestamp", "video", "emoji"]
    text: str | None = None
    image_url: str | None = None
    video_url: str | None = None
    cover_url: str | None = None
    duration: str | None = None                     # 视频/语音时长，如 "0:10"
    delay_ms: int = 1500                            # 距上一条的间隔
    align: Literal["left", "right"] | None = None   # 显式指定消息方向；None 时按规则推断
    reply_to: int | None = None                     # 回复目标的 1-based 序号；None 表示普通消息
```

| 字段 | 类型 | 必填 | 适用 kind | 说明 |
|---|---|---|---|---|
| `sender_id` | string | ✓ | 全部 | 必须匹配某个 `Participant.id`；系统消息(`sys`)和时间戳(`timestamp`)可填 `'__system__'` |
| `kind` | enum | ✓ | — | `text` / `image` / `sys` / `timestamp` / `video` / `emoji` |
| `text` | string 或 null | ✗ | text / sys / timestamp / emoji | 文字内容；`sys`、`timestamp`、`emoji` 必填 |
| `image_url` | string 或 null | ✗ | image | 图片 URL（气泡图片） |
| `video_url` | string 或 null | ✗ | video | 视频 URL |
| `cover_url` | string 或 null | ✗ | video | 视频封面图 URL；为空时 fallback 到 `video_url` |
| `duration` | string 或 null | ✗ | video | 视频时长，如 `0:10` |
| `delay_ms` | int | ✗ | 全部 | 默认 1500ms，第一条消息的 `delay_ms` 视为"距声明卡的间隔" |
| `align` | `"left"` \| `"right"` \| `null` | ✗ | text / image / video / emoji | 显式指定消息方向；`null` 时按规则推断（对谈 `participants[0]` 走右侧，群像 `id == "me"` 走右侧） |
| `reply_to` | int 或 null | ✗ | text / image / video / emoji | 回复目标的 1-based 序号，必须小于当前消息序号且不能指向 `sys` / `timestamp` |

**校验**：
- `text` 类消息必须有非空 `text`
- `image` 类消息必须有 `image_url`
- `video` 类消息必须有 `video_url` 和 `duration`
- `emoji` 类消息必须有非空 `text`
- `timestamp` 类消息必须有非空 `text`
- `sys` 类消息必须有非空 `text`，不能有 `image_url`
- 第一条消息的 `delay_ms` 至少 500ms（留给声明卡显示）
- `reply_to` 必须是 ≥ 1 的整数，且小于当前消息的 1-based 序号，不能指向 `sys` / `timestamp` 消息
- 消息文本不得包含高敏感词（转账、红包、密码、验证码、银行卡等）或真实社交平台名称（微信、WhatsApp 等）

## 2.3 `ChatScene` — 一次完整配置

```python
class ChatScene(BaseModel):
    mode: Literal["single", "group"] = "group"
    title: str = "对话剧场"
    background: str = "#ffffff"
    background_image_url: str | None = None
    background_visible: bool = True        # False 仅显示聊天元素,隐藏背景色/背景图/装饰层
    duration_ms: int | None = None         # None = 自动算
    opacity: float = 1.0                   # 0-1，整个内容透明度
    style_theme: Literal["cyberpunk", "watercolor", "pixel", "comic"] = "cyberpunk"
    intent: str                            # 创作意图，必填
    intent_acknowledged: bool = False      # 合规承诺勾选
    participants: list[Participant]        # 至少 2 个
    messages: list[Message]                # 至少 1 条
    watermark: WatermarkConfig             # AI 生成标识
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `mode` | enum | ✗ | `group` | `single` 启用"右侧霓虹气泡"机制 |
| `title` | string | ✗ | `对话剧场` | 顶部居中标题 |
| `background` | hex color | ✗ | `#ffffff` | 整页背景色（漫画主题浅色底） |
| `background_image_url` | string 或 null | ✗ | `null` | 整页背景图（`/uploads/<uuid>.png`）；有值时以低透明度叠加于背景色之上 |
| `background_visible` | bool | ✗ | `true` | 纯 UI 层模式开关；`false` 时渲染时隐藏背景色 / 背景图 / 主题装饰层（赛博朋克扫描线、水墨宣纸纤维等），仅保留聊天元素（消息、头像、气泡） |
| `duration_ms` | int 或 null | ✗ | 自动 | 总录制时长(ms)；`None` 时后端按消息数算 |
| `opacity` | float | ✗ | `1.0` | 整个内容透明度，0-1 |
| `style_theme` | enum | ✗ | `cyberpunk` | 视觉风格：`cyberpunk` / `watercolor` / `pixel` / `comic` |
| `intent` | string | ✓ | — | 创作意图，必须为 `short_video_drama` / `story_visualization` / `teaching_simulation` / `meme_sticker` |
| `intent_acknowledged` | bool | ✓ | `false` | 必须显式勾选合规承诺 |
| `participants` | 数组 | ✓ | — | 至少 2 项 |
| `messages` | 数组 | ✓ | — | 至少 1 项，建议 ≤ 100 条 |
| `watermark` | WatermarkConfig | ✗ | 见下 | AI 生成标识配置，不可关闭 |

### `WatermarkConfig`

```python
class WatermarkConfig(BaseModel):
    text: str = "本内容由 AI 生成 · 仅供创意表达"
    badge_style: Literal["neon", "minimal", "retro"] = "neon"
```

- `text` 固定，用户不可编辑
- `badge_style` 仅控制右下角角标视觉样式，不可关闭

**自动时长公式**（含 1 秒片头声明卡）：
```python
def auto_duration(messages: list[Message], first_delay_ms: int = 1000) -> int:
    base = first_delay_ms + sum(m.delay_ms for m in messages)
    return base + 1500  # 结尾 buffer
```

## 2.4 `VideoDSL` — 顶层 DSL

```python
class VideoDSL(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    kind: Literal["chat"] = "chat"
    template: Literal["cyberpunk", "watercolor", "pixel", "comic"] = "cyberpunk"
    scene: ChatScene
```

- `kind` 预留未来扩展 `slide`、`subtitle` 等场景
- `template` 与 `scene.style_theme` 必须保持一致；后端校验器会自动同步

## 2.5 `User` / `Session` / `File`（多用户 / 隔离）

为了支撑多用户与任务隔离，后端引入三张 SQLite 表（见 `backend/app/db.py`）：

```sql
CREATE TABLE users (
    id          TEXT PRIMARY KEY,
    username    TEXT NOT NULL UNIQUE,
    created_at  REAL NOT NULL
);

CREATE TABLE sessions (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    title           TEXT,
    created_at      REAL NOT NULL,
    last_active_at  REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE files (
    id           TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    kind         TEXT NOT NULL,           -- 'avatar' | 'image' | 'background'
    ext          TEXT NOT NULL,
    size         INTEGER NOT NULL,
    content_type TEXT,
    created_at   REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (user_id)    REFERENCES users(id)
);
```

| 表 | 关键字段 | 说明 |
|---|---|---|
| `users` | `id` 唯一 | 首次带 `X-User-Id` 请求即自动 upsert，后续换成 OIDC 时只改 auth 依赖 |
| `sessions` | `(user_id, last_active_at)` 索引 | 一次"任务"=一个 session；前端启动时调 `POST /api/sessions` 建 |
| `files` | `(session_id, kind)` | 一次上传产生一行；文件名 = `{id}.{ext}`，落 `storage/users/{user_id}/sessions/{session_id}/uploads/` |

**存储布局**（实际落盘）：

```
storage/
  wechat-video-gen.db
  users/
    {user_id}/
      sessions/
        {session_id}/
          uploads/{file_id}.{ext}    # 头像 / 图片 / 背景
          outputs/{job_id}.mp4       # 渲染产物
```

`jobs` 表与上面的关系是 `jobs.session_id -> sessions.id`、`jobs.user_id -> users.id`，
渲染进程从 `jobs` 读配置 / 写状态，完成后由 `/api/jobs/{id}/output` 提供下载。

## 2.6 `Job` — 录制任务（后端内部状态）

```python
class Job(BaseModel):
    id: str                                # ULID 或 uuid4
    status: Literal["queued", "running", "done", "failed"]
    progress: int = 0                      # 0-100
    config: VideoDSL
    output_url: str | None = None          # '/api/jobs/{id}/output'
    error: str | None = None
    created_at: float                      # time.time()
    finished_at: float | None = None
```

| 字段 | 说明 |
|---|---|
| `status` | `queued`（等待 worker）、`running`（正在录）、`done`（成功）、`failed`（失败） |
| `progress` | 录制时按 `DURATION_MS` 推 0→100（估算） |
| `config` | 入队时的原始配置快照 |
| `output_url` | 成功后填 `/api/jobs/{id}/output` |
| `error` | 失败时填异常信息 |

## 2.7 完整示例

```json
{
  "schema_version": "1.0",
  "kind": "chat",
  "template": "cyberpunk",
  "scene": {
    "mode": "group",
    "title": "霓虹都市夜谈",
    "background": "#0a0a12",
    "background_image_url": null,
    "style_theme": "cyberpunk",
    "intent": "meme_sticker",
    "intent_acknowledged": true,
    "participants": [
      { "id": "me", "name": "我", "avatar_url": null, "persona": "" },
      { "id": "inview", "name": "InVIEW", "avatar_url": null, "persona": "" },
      { "id": "kelly", "name": "刘雨昕 Kelly Liu", "avatar_url": null, "persona": "乐观的创作者" }
    ],
    "messages": [
      { "sender_id": "__system__", "kind": "timestamp", "text": "星期五 18:27", "delay_ms": 1500 },
      { "sender_id": "inview", "kind": "video", "video_url": "/uploads/video.mp4", "cover_url": "/uploads/cover.jpg", "duration": "0:10", "delay_ms": 2000 },
      { "sender_id": "inview", "kind": "text", "text": "🤔提示词堪比论文", "delay_ms": 1500 },
      { "sender_id": "kelly", "kind": "text", "text": "哈哈哈", "delay_ms": 1200 },
      { "sender_id": "kelly", "kind": "text", "text": "但其实只要找到参考文献。", "delay_ms": 1500, "reply_to": 4 },
      { "sender_id": "kelly", "kind": "emoji", "text": "🤔", "delay_ms": 1200 }
    ],
    "watermark": {
      "text": "本内容由 AI 生成 · 仅供创意表达",
      "badge_style": "neon"
    }
  }
}
```

预期产出：约 13s 的赛博朋克风格群像对话视频，带片头 AI 声明卡与右下角 AI 角标。

## 2.8 `timeline.json` — 时间码导出

每次渲染成功（不透明 mp4 / 透明 webm / 透明 mov 任一产物线）都会在
`storage/users/{user_id}/sessions/{session_id}/outputs/{job_id}.timeline.json`
落一份时间码 JSON，记录 disclaimer / intro / 每条消息的精确出现 / 消失时刻
（毫秒，相对视频起点 0）。前端通过 `GET /api/jobs/{job_id}/timeline` 拉取，
详见 `docs/03-api.md §3.x 时间码导出` 与 `docs/04-template.md §4.14`。

```python
class TimelineEntry:
    id: str                          # 事件 id:disclaimer/intro 取固定值,消息取 "mN"
    at: int                          # 出现时刻(毫秒,相对视频起点 0)
    type: Literal["disclaimer", "intro", "msg", "sys", "timestamp"]
    kind: str                        # 渲染字段:disclaimer / intro / text / image /
                                    # sys / timestamp / video / emoji
    sender_id: str                   # "__system__" 或 participant.id
    sender_name: str                 # 显示名,系统消息为空
    summary: str                     # 表格用摘要:文字取首行,图片/视频/emoji 加类型前缀
    text: str | None
    image_url: str | None            # 已用 BASE_URL 补成绝对 URL
    video_url: str | None
    duration: str | None             # 视频消息的时长字符串,如 "0:10"
    appeared_at: int                 # = at(冗余字段,方便前端排序/过滤)
    disappeared_at: int              # 消失时刻(毫秒)
    duration_ms: int                 # disappeared_at - appeared_at
```

```json
{
  "schema_version": "1.0",
  "kind": "chat",
  "job_id": "abc123",
  "total_duration_ms": 5500,
  "entries": [
    {
      "id": "__disclaimer__",
      "at": 0,
      "type": "disclaimer",
      "kind": "disclaimer",
      "sender_id": "__system__",
      "sender_name": "",
      "summary": "本对话由 AI 生成,仅供创意表达",
      "text": "本对话由 AI 生成,仅供创意表达",
      "image_url": null,
      "video_url": null,
      "duration": null,
      "appeared_at": 0,
      "disappeared_at": 1000,
      "duration_ms": 1000
    },
    {
      "id": "m1",
      "at": 1000,
      "type": "msg",
      "kind": "text",
      "sender_id": "me",
      "sender_name": "我",
      "summary": "在吗",
      "text": "在吗",
      "image_url": null,
      "video_url": null,
      "duration": null,
      "appeared_at": 1000,
      "disappeared_at": 2500,
      "duration_ms": 1500
    }
  ]
}
```

**消失语义**：
- 一条消息在**下一条事件出现**时消失（对应模板里"新消息把上一条顶出聊天区"的视觉）
- 最后一条事件（disclaimer / intro / 末条消息）在场景总时长 `total_duration_ms` 处消失
- `duration_ms` 永远 ≥ 0；`disappeared_at - appeared_at` 严格对应消息在屏幕上停留的时长

**生成时机**：
- `backend/app/renderer.py::build_timeline_with_durations()` 是数据来源（与 `build_timeline()`
  并列、互不影响；后者继续驱动模板 JS 动画时间轴）
- `backend/app/recorder.py::_write_timeline_json()` 在 `render_video()` /
  `render_video_transparent()` 两条产物线里都调用 — 转码成功后才落盘
- 渲染失败时 `timeline.json` 与 `mp4/webm/mov` 一起被 `try/except` 清理

**适用范围**：
- 透明 / 不透明两条产物线都支持（同一份 timeline 数据，不依赖像素）
- 7 种风格（cyberpunk / watercolor / pixel / comic / noir / ink / green_screen）通用
- 数据来源完全在 DSL 层（不依赖 Playwright 录制帧），跨平台 / 跨环境结果一致

## 2.9 字段约束与错误码

`/api/preview-html` 与 `/api/render` 收到非法 `ChatScene` 时，FastAPI 自动返回 422 + 校验错误明细。
前端应在编辑时做客户端预校验，服务端再校验一次。

## 2.10 与前端的类型同步

`frontend/src/types.ts` 内定义等价的 TS 类型，与 Pydantic 字段一一对应。
后端变更模型时，前端同步修改。**不做自动生成**（避免引入额外构建复杂度）。
