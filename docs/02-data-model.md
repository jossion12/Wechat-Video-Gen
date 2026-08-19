# 02 · 数据模型

所有数据模型用 [Pydantic v2](https://docs.pydantic.dev/) 定义,
位于 `backend/app/models.py`。

## 2.1 `StatusBar` — 顶部状态栏

```python
class StatusBar(BaseModel):
    time: str = "12:34"
    battery_level: int = 61
    signal_type: Literal["5G", "4G"] | None = "5G"
    signal_type_secondary: Literal["5G", "4G"] | None = "5G"
    dual_sim: bool = True
    show_wifi: bool = True
    show_signal: bool = True
    show_bluetooth: bool = True
    show_alarm: bool = True
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `time` | string | ✗ | `12:34` | 左上角时间 |
| `battery_level` | int | ✗ | `61` | 电量百分比,0-100 |
| `signal_type` | `"5G"` \| `"4G"` \| `null` | ✗ | `"5G"` | 主卡信号类型,留空不显示 |
| `signal_type_secondary` | `"5G"` \| `"4G"` \| `null` | ✗ | `"5G"` | 副卡信号类型,`dual_sim=true` 时显示 |
| `dual_sim` | bool | ✗ | `true` | 是否显示双卡(右侧会出现两个信号类型) |
| `show_wifi` | bool | ✗ | `true` | WiFi 图标 |
| `show_signal` | bool | ✗ | `true` | 信号条图标 |
| `show_bluetooth` | bool | ✗ | `true` | 蓝牙图标 |
| `show_alarm` | bool | ✗ | `true` | 闹钟图标 |

## 2.2 `Participant` — 聊天参与者

```python
class Participant(BaseModel):
    id: str                    # 唯一 id,前端生成,如 'me' / 'alice' / 'bob'
    name: str                  # 显示名,例如 '小美'
    avatar_url: str | None     # '/uploads/<uuid>.png' 或 None
    label: str | None = None   # 单聊副标题 / 群聊企业标签
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | ✓ | 在 `ChatConfig` 内唯一;消息通过 `sender_id` 引用 |
| `name` | string | ✓ | 气泡上方的小字(灰底),最多 16 个字符 |
| `avatar_url` | string 或 null | ✗ | 头像图;若为 `null` 则显示默认头像 |
| `label` | string 或 null | ✗ | 单聊时显示为顶部副标题;群聊时显示为昵称旁的企业/地区标签,如 `【OPC圈成都】` |

**约定**:
- 单聊时 `id == "me"` 表示自己,放第一位
- 群聊时 `id` 可自由命名;若希望自己的发言走右侧,把 `id == "me"` 的参与者放在列表里
- 头像文件大小 ≤ 2MB,后端 `POST /api/upload` 自动校验

## 2.3 `Message` — 一条聊天消息

```python
class Message(BaseModel):
    sender_id: str                                  # 引用 Participant.id
    kind: Literal["text", "image", "sys", "timestamp", "video", "emoji"]
    text: str | None = None
    image_url: str | None = None
    video_url: str | None = None
    cover_url: str | None = None
    duration: str | None = None                     # 视频/语音时长,如 "0:10"
    delay_ms: int = 1500                            # 距上一条的间隔
```

| 字段 | 类型 | 必填 | 适用 kind | 说明 |
|---|---|---|---|---|
| `sender_id` | string | ✓ | 全部 | 必须匹配某个 `Participant.id`;系统消息(`sys`)和时间戳(`timestamp`)可填 `'__system__'` |
| `kind` | enum | ✓ | — | `text` / `image` / `sys` / `timestamp` / `video` / `emoji` |
| `text` | string 或 null | ✗ | text / sys / timestamp / emoji | 文字内容;`sys`、`timestamp`、`emoji` 必填 |
| `image_url` | string 或 null | ✗ | image | 图片 URL(气泡图片) |
| `video_url` | string 或 null | ✗ | video | 视频 URL |
| `cover_url` | string 或 null | ✗ | video | 视频封面图 URL;为空时 fallback 到 `video_url` |
| `duration` | string 或 null | ✗ | video | 视频时长,如 `0:10` |
| `delay_ms` | int | ✗ | 全部 | 默认 1500ms,第一条消息的 `delay_ms` 视为"距时间戳的间隔" |

**校验**:
- `text` 类消息必须有非空 `text`
- `image` 类消息必须有 `image_url`
- `video` 类消息必须有 `video_url` 和 `duration`
- `emoji` 类消息必须有非空 `text`(单个或几个 emoji)
- `timestamp` 类消息必须有非空 `text`
- `sys` 类消息必须有非空 `text`,不能有 `image_url`
- 第一条消息的 `delay_ms` 至少 500ms(留给时间戳显示)

## 2.4 `ChatConfig` — 一次完整配置

```python
class ChatConfig(BaseModel):
    mode: Literal["single", "group"] = "group"
    title: str = "群聊"
    subtitle: str | None = None            # 单聊时显示在标题下方的副标题
    background: str = "#ededed"
    background_image_url: str | None = None
    duration_ms: int | None = None         # None = 自动算
    opacity: float = 1.0                   # 0-1,整个内容透明度,方便叠加到其他视频
    status_bar: StatusBar = StatusBar()
    member_count: int | None = None        # 群聊人数,如 221
    muted: bool = False                    # 群聊免打扰铃铛
    participants: list[Participant]        # 至少 2 个
    messages: list[Message]                # 至少 1 条
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `mode` | enum | ✗ | `group` | `single` 启用"右侧绿色气泡"机制 |
| `title` | string | ✗ | `群聊` | 顶部居中标题 |
| `subtitle` | string 或 null | ✗ | `null` | 单聊时显示在标题下方,如企业备注 |
| `background` | hex color | ✗ | `#ededed` | 整页背景色 |
| `background_image_url` | string 或 null | ✗ | `null` | 整页背景图(`/uploads/<uuid>.png`);有值时优先于 `background`,平铺铺满 |
| `duration_ms` | int 或 null | ✗ | 自动 | 总录制时长(ms);`None` 时后端按消息数算 |
| `opacity` | float | ✗ | `1.0` | 整个内容透明度,0-1,方便叠加到其他视频 |
| `status_bar` | StatusBar | ✗ | `StatusBar()` | 顶部状态栏配置 |
| `member_count` | int 或 null | ✗ | `null` | 群聊人数,显示为 `标题(221)` |
| `muted` | bool | ✗ | `false` | 群聊免打扰,显示铃铛图标 |
| `participants` | 数组 | ✓ | — | 至少 2 项 |
| `messages` | 数组 | ✓ | — | 至少 1 项,建议 ≤ 30 条(超出会很长) |

**自动时长公式**:
```python
def auto_duration(messages: list[Message], first_delay_ms: int = 500) -> int:
    base = first_delay_ms + sum(m.delay_ms for m in messages)
    return base + 1500  # 结尾 buffer
```

## 2.5 `User` / `Session` / `File`(多用户 / 隔离)

为了支撑多用户与任务隔离,后端引入三张 SQLite 表(见 `backend/app/db.py`):

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
| `users` | `id` 唯一 | 首次带 `X-User-Id` 请求即自动 upsert,后续换成 OIDC 时只改 auth 依赖 |
| `sessions` | `(user_id, last_active_at)` 索引 | 一次"任务"=一个 session;前端启动时调 `POST /api/sessions` 建 |
| `files` | `(session_id, kind)` | 一次上传产生一行;文件名 = `{id}.{ext}`,落 `storage/users/{user_id}/sessions/{session_id}/uploads/` |

**存储布局**(实际落盘):

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

`jobs` 表与上面的关系是 `jobs.session_id -> sessions.id`、`jobs.user_id -> users.id`,
渲染进程从 `jobs` 读配置 / 写状态,完成后由 `/api/jobs/{id}/output` 提供下载。

## 2.6 `Job` — 录制任务(后端内部状态)

```python
class Job(BaseModel):
    id: str                                # ULID 或 uuid4
    status: Literal["queued", "running", "done", "failed"]
    progress: int = 0                      # 0-100
    config: ChatConfig
    output_url: str | None = None          # '/outputs/{id}.mp4'
    error: str | None = None
    created_at: float                      # time.time()
    finished_at: float | None = None
```

| 字段 | 说明 |
|---|---|
| `status` | `queued`(等待 worker)、`running`(正在录)、`done`(成功)、`failed`(失败) |
| `progress` | 录制时按 `DURATION_MS` 推 0→100(估算) |
| `config` | 入队时的原始配置快照 |
| `output_url` | 成功后填 `/outputs/{id}.mp4` |
| `error` | 失败时填异常信息 |

## 2.7 完整示例

```json
{
  "mode": "group",
  "title": "心引力宇宙-OPC圈成都",
  "member_count": 221,
  "muted": true,
  "background": "#ededed",
  "background_image_url": null,
  "status_bar": {
    "time": "00:00",
    "battery_level": 61,
    "signal_type": "5G",
    "signal_type_secondary": "5G",
    "dual_sim": true,
    "show_wifi": true,
    "show_signal": true,
    "show_bluetooth": true,
    "show_alarm": true
  },
  "participants": [
    { "id": "me", "name": "我", "avatar_url": null },
    { "id": "inview", "name": "InVIEW", "avatar_url": null },
    { "id": "kelly", "name": "刘雨昕 Kelly Liu", "avatar_url": null, "label": "【OPC圈成都】" }
  ],
  "messages": [
    { "sender_id": "__system__", "kind": "timestamp", "text": "星期五 18:27", "delay_ms": 1500 },
    { "sender_id": "inview", "kind": "video", "video_url": "/uploads/video.mp4", "cover_url": "/uploads/cover.jpg", "duration": "0:10", "delay_ms": 2000 },
    { "sender_id": "inview", "kind": "text", "text": "🤔提示词堪比论文", "delay_ms": 1500 },
    { "sender_id": "kelly", "kind": "text", "text": "哈哈哈", "delay_ms": 1200 },
    { "sender_id": "kelly", "kind": "text", "text": "但其实只要找到参考文献。", "delay_ms": 1500 },
    { "sender_id": "kelly", "kind": "emoji", "text": "🤔", "delay_ms": 1200 }
  ]
}
```

预期产出:约 12s 的高还原度微信风格群聊视频。

## 2.8 字段约束与错误码

`/api/preview-html` 与 `/api/render` 收到非法 `ChatConfig` 时,FastAPI 自动返回 422 + 校验错误明细。
前端应在编辑时做客户端预校验,服务端再校验一次。

## 2.9 与前端的类型同步

`frontend/src/types.ts` 内定义等价的 TS 类型,与 Pydantic 字段一一对应。
后端变更模型时,前端同步修改。**不做自动生成**(避免引入额外构建复杂度)。