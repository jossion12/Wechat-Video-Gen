# 04 · Jinja2 模板规范

## 4.1 文件位置

已上线 4 种视觉风格；另计划新增 3 种（详细设计见 [`10-new-themes-design.md`](./10-new-themes-design.md)）：

| 风格 | 模板文件 | 定位 | 状态 |
|---|---|---|---|
| 赛博朋克 cyberpunk | `backend/templates/cyberpunk_chat.html.j2` | 深色模式 + 霓虹蓝/紫/粉 | 已上线 |
| 手绘 watercolor | `backend/templates/watercolor_chat.html.j2` | 莫兰迪色系 + 纸张纹理 + 楷体 | 已上线 |
| 复古 pixel | `backend/templates/pixel_chat.html.j2` | 黑底绿字 + 硬边矩形 + 扫描线 | 已上线 |
| 漫画 comic | `backend/templates/comic_chat.html.j2` | 粗黑边框 + 半调网点 + 拟声词风格 | 已上线 |
| 黑白胶片 noir | `backend/templates/noir_chat.html.j2` | 纯灰阶 + 衬线 + 菲林颗粒 + 胶片孔 | 设计完成，待实现 |
| 水墨 ink | `backend/templates/ink_chat.html.j2` | 宣纸 + 墨韵 + 朱印 + 笔触毛边 | 设计完成，待实现 |
| 蒸汽波 vaporwave | `backend/templates/vaporwave_chat.html.j2` | 落日渐变 + 透视网格 + 片假名 + 铬金属 | 设计完成，待实现 |

实现顺序：**noir → ink → vaporwave**（理由见设计文档 §10.8）。

- 渲染入口：`backend/app/renderer.py::render_chat()` / `render_dsl()`
- 分发逻辑：按 `VideoDSL.template` 加载对应 `<template>_chat.html.j2`

**设计原则**：
- 不使用任何真实社交平台（微信/WhatsApp/iMessage 等）的视觉元素
- 每种风格都有高度原创的配色、头像、气泡与系统消息样式
- 强制片头 AI 声明卡 + 右下角 AI 生成角标

## 4.2 模板上下文（Context）

Jinja2 渲染时收到如下变量（由 `renderer.py` 注入）：

```python
{
    "config": ChatScene,                 # 原始配置
    "mode": str,                         # config.mode ('single' / 'group')
    "title": str,                        # config.title
    "background": str,                   # config.background
    "background_image_url": str | None,  # config.background_image_url
    "style_theme": str,                  # config.style_theme
    "intro_effect": str,                 # config.intro_effect ("none" / "scanline" / "typewriter")
    "intent_label": str,                 # config.intent
    "participants": list[dict],          # [{id, name, avatar_url, persona, css_class}]
    "messages": list[dict],              # 渲染好的消息列表（已加 css_class / is_self）
    "timeline": list[dict],              # [{id, at_ms, type}]
    "duration_ms": int,                  # 录制总时长
    "disclaimer_text": str,              # 片头声明卡文字
    "ai_badge_style": str,               # "neon" / "minimal" / "retro"
    "watermark_text": str,               # AI 生成标识文字
}
```

`renderer.py` 负责把 `ChatScene` 转换成上面的"扁平化"结构，
模板里只做展示用 for 循环和条件判断，不写复杂逻辑。

## 4.3 模板骨架

模板自上而下包含：

1. **片头声明卡** — 全屏显示 1 秒："本对话由 AI 生成，仅供创意表达"
2. **顶部标题栏** — 标题 + 对谈/群像标签，无返回键、状态栏、人数、铃铛
3. **聊天区** — 时间戳、文本/图片/视频/表情消息、幕间字幕式系统消息
4. **AI 角标** — 右下角固定标识，样式可选但不可关闭
5. **动画脚本** — 按 `TIMELINE` 逐条显示消息并自动滚动，声明卡 1 秒后淡出

消息循环大致结构：

```jinja2
{% for m in messages %}
  {% if m.kind == 'sys' %}
    <div class="sys-msg" id="{{ m.dom_id }}">...</div>
  {% elif m.kind == 'timestamp' %}
    <div class="time-stamp" id="{{ m.dom_id }}">...</div>
  {% elif m.kind == 'emoji' %}
    <div class="msg emoji {{ m.css_class }}" id="{{ m.dom_id }}">...</div>
  {% elif m.kind == 'image' %}
    <div class="msg {{ m.css_class }}" id="{{ m.dom_id }}">...</div>
  {% elif m.kind == 'video' %}
    <div class="msg {{ m.css_class }}" id="{{ m.dom_id }}">...</div>
  {% else %}
    <div class="msg {{ m.css_class }}" id="{{ m.dom_id }}">...</div>
  {% endif %}
{% endfor %}
```

## 4.4 消息字典（`messages` 元素）

`renderer.py` 为每条消息生成：

| 键 | 类型 | 说明 |
|---|---|---|
| `dom_id` | string | 形如 `m1`、`m2`，唯一 |
| `kind` | enum | `text` / `image` / `sys` / `timestamp` / `video` / `emoji` |
| `sender_id` | string | `__system__` 表示系统/时间戳消息 |
| `sender_name` | string | 系统/时间戳消息为空字符串 |
| `sender_avatar` | string 或 null | 系统/时间戳消息为 `None` |
| `persona` | string 或 null | 角色设定（当前仅保存） |
| `text` | string 或 null | 文字/时间戳/emoji/图片说明内容 |
| `image_url` | string 或 null | 图片 URL |
| `video_url` | string 或 null | 视频 URL |
| `cover_url` | string 或 null | 视频封面 URL |
| `duration` | string 或 null | 视频时长，如 `0:10` |
| `css_class` | string | `self` / `""` / `__system__` / `__timestamp__` |
| `is_self` | bool | 是否"自己"发言；由 `message.align` 显式指定或按默认规则推断 |
| `show_name` | bool | 是否显示发送者昵称（自己消息不显示） |
| `reply_to_dom_id` | string 或 null | 回复目标的消息 dom_id，例如 `m2`；无效时为 `None` |
| `reply_to_sender_name` | string 或 null | 回复目标的发送者名；无效时为 `None` |
| `reply_to_text` | string 或 null | 回复目标的首行文本；无效时为 `None` |

## 4.5 参与者字典（`participants` 元素）

| 键 | 类型 | 说明 |
|---|---|---|
| `id` | string | 同 Pydantic |
| `name` | string | 同 Pydantic |
| `avatar_url` | string 或 null | 头像图；若 `None` 用六边形首字母占位 |
| `persona` | string 或 null | 角色设定 |
| `css_class` | string | 等于 `id`（供 `.avatar.<id>` 选择器使用） |

## 4.6 头像

- 所有头像统一使用六边形 `clip-path: polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)`
- 未上传头像时显示参与者名字首字母 + 随机霓虹色背景

## 4.7 TIMELINE 生成规则

`renderer.py` 构造：

```python
timeline = [{"id": "__disclaimer__", "at": 0, "type": "disclaimer"}]
intro_duration = INTRO_DURATION_MS if config.intro_effect != "none" else 0
start_idx = 0
t = 1000 + intro_duration  # 声明卡显示 1s, 再播放 intro

if intro_duration:
    timeline.append({"id": "__intro__", "at": 1000, "type": "intro", "effect": config.intro_effect})

first_msg = messages[0] if messages else None
if first_msg and first_msg.kind == "timestamp" and first_msg.text:
    timeline.append({"id": "m1", "at": t, "type": "timestamp"})
    start_idx = 1
    t += 700

for i, m in enumerate(messages[start_idx:], start=start_idx + 1):
    timeline.append({
        "id": f"m{i}",
        "at": t,
        "type": "sys" if m.kind == "sys"
                else "timestamp" if m.kind == "timestamp"
                else "msg",
    })
    t += m.delay_ms
```

`TIMELINE` 第一条固定是 `__disclaimer__`，对应片片 AI 声明卡，1 秒后淡出。
若 `config.intro_effect != "none"`，则在 `t = 1000` 时插入一条 `type: "intro"` 事件，
由模板中的 `#intro-overlay` 播放对应特效；intro 默认持续 `INTRO_DURATION_MS = 1000ms`，
之后第一条消息才会出现。

## 4.8 时长计算

```python
def auto_duration(messages, first_delay_ms=1000):
    return first_delay_ms + sum(m.delay_ms for m in messages) + 1500
```

若用户显式传 `config.duration_ms`，以用户值为准。

## 4.9 样式约定

| 项 | 值 | 说明 |
|---|---|---|
| 画布 | 1080×1920 | `body` width/height |
| 背景色 | `config.background` | 默认 `#ffffff` |
| 自己气泡 | 蓝紫渐变半透明 + 霓虹蓝边框 | `clip-path` 不规则多边形 |
| 他人气泡 | 白色半透明 + 淡白边框 | `clip-path` 不规则多边形 |
| 系统消息 | 紫色半透明 + 左右霓虹紫边框 | 幕间字幕风格 |
| 时间戳 | 霓虹蓝半透明胶囊 | 无头像 |
| 单独 emoji 大小 | `130px` | 带霓虹投影 |
| 视频封面最大宽度 | `500px` | 与图片消息一致 |
| 字体栈 | `Noto Sans CJK SC` → `PingFang SC` → `Microsoft YaHei` | 跨平台兜底 |
| 头像 | 六边形 | `clip-path` |
| AI 角标 | 右下角固定 | 三种视觉样式可选 |

## 4.10 回复引用块

当 `m.reply_to_dom_id` 非空时，文本 / 图片 / 视频 / 表情气泡内应渲染一个 `.reply-quote` 引用预览块：

- 位于气泡上方、发送者名字（`.sender-row`）下方
- 左侧一道彩色竖条（主题强调色）
- 上面一行发送者名 `.reply-quote-sender`（粗体小字）
- 下面一行首行文本 `.reply-quote-text`，截断为 30 字并加 `…`
- 携带 `data-reply-to="mN"` 属性，便于后续实现点击跳转原消息（MVE 仅渲染）
- 自己消息（右侧）时，竖条改在右侧，颜色使用主题 secondary 强调色

## 4.11 添加新视觉风格

未来新增第 5 种风格时：

1. 新建 `backend/templates/<style>_chat.html.j2`
2. 在 `backend/app/dsl.py` 扩展 `ChatScene.style_theme` 与 `VideoDSL.template` 的 `Literal`
3. 在 `backend/app/renderer.py` 的 `render_dsl()` 分支中增加新 `template`
4. 前端 `frontend/src/types.ts` 同步扩展 `VideoTemplate` / `StyleTheme` / `STYLE_THEME_LABELS`
5. 前端 `HeaderEditor` 与 `StaticPreview` 增加对应主题样式
6. 若该风格支持 `intro_effect`，在模板中加入 `#intro-overlay` 及 `scanline / typewriter` 的 CSS/JS
7. 跑 `backend/tests/test_renderer.py` 验证渲染产物

## 4.12 模板测试

`backend/tests/test_renderer.py` 应包含：

- ✅ 最小配置（2 参与者 / 1 文本消息）在 4 种风格下都能渲染出合法 HTML
- ✅ 对谈模式"自己"消息带 `.msg.self`
- ✅ 图片消息生成 `<img>` 标签
- ✅ 视频消息渲染播放按钮和时长
- ✅ emoji 消息渲染为大表情
- ✅ 时间戳（`timestamp`）消息渲染为 `.time-stamp`
- ✅ 系统消息渲染为幕间字幕且不显示头像
- ✅ 连续消息每次都显示头像
- ✅ TIMELINE 包含片头 AI 声明卡
- ✅ AI 生成角标始终存在
- ✅ 缺少 `text` 的 text 类消息报错
- ✅ 缺头像 URL 的消息用默认占位（风格决定形状）
- ✅ 高敏感词与真实平台名触发校验错误
- ✅ 带 `reply_to` 的消息在 4 种风格下渲染出 `.reply-quote` 引用块
- ✅ 启用 `intro_effect` 时 TIMELINE 包含 `__intro__` 并顺延后续消息
- ✅ 6 种风格在 `scanline / typewriter` 下渲染出 `#intro-overlay`
- ✅ `intro_effect == "none"` 时不渲染 `#intro-overlay`

## 4.13 调试技巧

预览阶段可在 `renderer.py` 加 `render_chat_cyberpunk()` 末尾：

```python
if settings.DEBUG_PREVIEW:
    Path("/tmp/preview.html").write_text(html, encoding="utf-8")
```

浏览器直接打开本地文件看效果；或用 `python -m http.server` 起个静态服务。

## 4.14 时间码导出（timeline.json）

每次渲染成功都会额外落一份 `timeline.json`，记录 disclaimer / intro / 每条消息
的精确出现 / 消失时刻（毫秒，相对视频起点 0）。前端通过
`GET /api/jobs/{job_id}/timeline` 拉取并展示（见
[`docs/03-api.md §3.x`](./03-api.md) 与 [`docs/02-data-model.md §2.8`](./02-data-model.md)）。

### 数据来源

`backend/app/renderer.py` 同时维护两个并列函数：

- `build_timeline()`（老）：返回 `[{id, at, type, ...}]`，被模板末尾的 JS 用来
  `TIMELINE.forEach(t => setTimeout(..., t.at))` 逐条显示消息。
  **签名与返回值不变**，所有现有调用方继续工作。
- `build_timeline_with_durations()`（新）：返回 `[{id, at, appeared_at,
  disappeared_at, duration_ms, ...}]`，每条事件额外带 sender_id / sender_name
  / summary / text / image_url / video_url / duration 等渲染字段，供
  `recorder._write_timeline_json()` 落盘与前端表格展示。

两个函数都基于同一个 ChatScene + 同一个 `resolve_intro_duration_ms()` /
`resolve_duration_ms()` 公式，**`appeared_at` 与模板 JS 用的 `at` 完全一致**——
模板动画与时间码逐帧对齐。

### 消失语义

- 一条消息在 **下一条事件出现**时消失（对应模板里"新消息把上一条顶出聊天区"的视觉）
- 最后一条事件（disclaimer / intro / 末条消息）在场景总时长 `total_duration_ms` 处消失
- 首条为 `timestamp` 消息时，timestamp 与下一条消息之间固定 700ms 间隔（与
  `build_timeline()` 的 `t += 700` 保持一致）

### 适用范围

- **透明 / 不透明两条产物线都支持**：`_write_timeline_json()` 在 `render_video()`
  与 `render_video_transparent()` 两条路径里都被调用，时间码数据完全在 DSL 层
  算出，不依赖 Playwright 录制的像素 — WebM-VP9-alpha / MOV-ProRes 4444 与
  MP4 走同一份 timeline.json。
- **7 种风格通用**：cyberpunk / watercolor / pixel / comic / noir / ink / green_screen
  共用同一套时间戳算法，差异只在于视觉层。
- **失败清理**：渲染失败时 `timeline.json` 与 `mp4/webm/mov` 一起被
  `try/except` 块 unlink，不留半成品。
- **bg_visible: false / 透明产物线兼容**：时间码来源只依赖 DSL + 渲染时长，
  不读取像素，与背景可见性 / 透明设置无关。

### 与前端对接

- `JobStatus.timeline_url`（新增字段，可空）— 仅 done 且 timeline.json 存在时有值，
  前端据此显示「查看时间码」按钮
- `GET /api/jobs/{job_id}/timeline` 返回 `application/json`，所有权校验与
  `serve_output` 一致（跨用户 404，不泄露存在性）
- 前端 `TimelinePanel` 组件列出每条消息、过滤、可选时间轴预览，点击按钮在 App 顶层
  切换视图（路由或内部 state 切换，本项目用 App 内部 state，详见
  `frontend/src/App.tsx`）
