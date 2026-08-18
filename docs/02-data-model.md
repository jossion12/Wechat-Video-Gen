# 02 · 数据模型

所有数据模型用 [Pydantic v2](https://docs.pydantic.dev/) 定义,
位于 `backend/app/models.py`。

## 2.1 `Participant` — 聊天参与者

```python
class Participant(BaseModel):
    id: str                    # 唯一 id,前端生成,如 'me' / 'alice' / 'bob'
    name: str                  # 显示名,例如 '甄嬛'
    avatar_url: str | None     # '/uploads/<uuid>.png' 或 None
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | ✓ | 在 `ChatConfig` 内唯一;消息通过 `sender_id` 引用 |
| `name` | string | ✓ | 气泡上方的小字(灰底),最多 16 个字符 |
| `avatar_url` | string 或 null | ✗ | 头像图;若为 `null` 则显示默认头像 |

**约定**:
- 单聊时 `id == "me"` 表示自己,放第一位
- 群聊时 `id` 可自由命名;若希望自己的发言走右侧,把 `id == "me"` 的参与者放在列表里
- 头像文件大小 ≤ 2MB,后端 `POST /api/upload` 自动校验

## 2.2 `Message` — 一条聊天消息

```python
class Message(BaseModel):
    sender_id: str                                  # 引用 Participant.id
    kind: Literal["text", "image", "sys"]
    text: str | None = None
    image_url: str | None = None
    delay_ms: int = 1500                            # 距上一条的间隔
```

| 字段 | 类型 | 必填 | 适用 kind | 说明 |
|---|---|---|---|---|
| `sender_id` | string | ✓ | 全部 | 必须匹配某个 `Participant.id`;系统消息(`sys`)可填 `'__system__'` |
| `kind` | enum | ✓ | — | `text` / `image` / `sys` |
| `text` | string 或 null | ✗ | text / sys | 文字内容;`sys` 必填 |
| `image_url` | string 或 null | ✗ | image | 图片 URL(气泡图片) |
| `delay_ms` | int | ✗ | 全部 | 默认 1500ms,第一条消息的 `delay_ms` 视为"距时间戳的间隔" |

**校验**:
- `text` 类消息必须有非空 `text`
- `image` 类消息必须有 `image_url`
- `sys` 类消息必须有非空 `text`,不能有 `image_url`
- 第一条消息的 `delay_ms` 至少 500ms(留给时间戳显示)

## 2.3 `ChatConfig` — 一次完整配置

```python
class ChatConfig(BaseModel):
    mode: Literal["single", "group"] = "group"
    title: str = "群聊"
    background: str = "#ededed"
    duration_ms: int | None = None         # None = 自动算
    participants: list[Participant]        # 至少 2 个
    messages: list[Message]                # 至少 1 条
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `mode` | enum | ✗ | `group` | `single` 启用"右侧蓝色气泡"机制 |
| `title` | string | ✗ | `群聊` | 顶部居中标题 |
| `background` | hex color | ✗ | `#ededed` | 整页背景 |
| `duration_ms` | int 或 null | ✗ | 自动 | 总录制时长(ms);`None` 时后端按消息数算 |
| `participants` | 数组 | ✓ | — | 至少 2 项 |
| `messages` | 数组 | ✓ | — | 至少 1 项,建议 ≤ 30 条(超出会很长) |

**自动时长公式**:
```python
def auto_duration(messages: list[Message], first_delay_ms: int = 1200) -> int:
    base = first_delay_ms + sum(m.delay_ms for m in messages)
    return base + 1500  # 前后 buffer
```

## 2.4 `Job` — 录制任务(后端内部状态)

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

## 2.5 完整示例

```json
{
  "mode": "group",
  "title": "后宫风云复盘群 (5)",
  "background": "#ededed",
  "participants": [
    { "id": "zhen", "name": "甄嬛", "avatar_url": "/uploads/zhen.png" },
    { "id": "hua",  "name": "华妃", "avatar_url": "/uploads/hua.png" },
    { "id": "shen", "name": "沈眉庄", "avatar_url": "/uploads/shen.png" }
  ],
  "messages": [
    { "sender_id": "zhen", "kind": "image", "image_url": "/uploads/plum.jpg",
      "text": "倚梅园的梅花开了。", "delay_ms": 1500 },
    { "sender_id": "hua", "kind": "text", "text": "怪不得皇上昨夜又去了碎玉轩。", "delay_ms": 1800 },
    { "sender_id": "shen", "kind": "text", "text": "娘娘息怒,群里说话还是留三分。", "delay_ms": 1500 },
    { "sender_id": "__system__", "kind": "sys", "text": "余答应已被移出群聊", "delay_ms": 1500 }
  ]
}
```

预期产出:14s 微信风格群聊视频,最后一条系统消息带红色脉冲效果。

## 2.6 字段约束与错误码

`/api/preview-html` 与 `/api/render` 收到非法 `ChatConfig` 时,FastAPI 自动返回 422 + 校验错误明细。
前端应在编辑时做客户端预校验,服务端再校验一次。

## 2.7 与前端的类型同步

`frontend/src/types.ts` 内定义等价的 TS 类型,与 Pydantic 字段一一对应。
后端变更模型时,前端同步修改。**不做自动生成**(避免引入额外构建复杂度)。