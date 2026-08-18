# 04 · Jinja2 模板规范

## 4.1 文件位置

- 模板文件:`backend/templates/wechat_chat.html.j2`
- 渲染入口:`backend/app/renderer.py::render_template()`
- 视觉基准:仓库内 `examples/05-chat-wechat-style/index.html`

**不修改**主仓库的 `index.html`,模板是基于它参数化的副本。

## 4.2 模板上下文(Context)

Jinja2 渲染时收到如下变量(由 `renderer.py` 注入):

```python
{
    "config": ChatConfig,                # 原始配置
    "mode": str,                         # config.mode ('single' / 'group')
    "title": str,                        # config.title
    "subtitle": str | None,              # config.subtitle(单聊副标题)
    "background": str,                   # config.background
    "background_image_url": str | None,  # config.background_image_url
    "status_bar": StatusBar,             # config.status_bar
    "member_count": int | None,          # config.member_count(群聊人数)
    "muted": bool,                       # config.muted(群聊免打扰)
    "participants": list[dict],          # [{id, name, avatar_url, label, css_class}]
    "messages": list[dict],              # 渲染好的消息列表(已加 css_class / is_self / show_avatar)
    "timeline": list[dict],              # [{id, at_ms, type, flash?}]
    "duration_ms": int,                  # 录制总时长
}
```

`renderer.py` 负责把 `ChatConfig` 转换成上面的"扁平化"结构,
模板里只做展示用 for 循环和条件判断,不写复杂逻辑。

## 4.3 模板骨架

模板自上而下包含:

1. **状态栏** — 时间、左侧应用图标、网速/NFC/闹钟/蓝牙/双卡/电池
2. **头部** — 返回键、标题(单聊可带副标题,群聊可带人数和免打扰铃铛)、更多按钮
3. **聊天区** — 时间戳、文本/图片/视频/表情消息、系统消息
4. **输入栏** — 语音、输入框、表情、+
5. **底部手势条** — iPhone 风格 home indicator
6. **动画脚本** — 按 `TIMELINE` 逐条显示消息并自动滚动

消息循环大致结构:

```jinja2
{% for m in messages %}
  {% if m.kind == 'sys' %}
    <div class="sys-msg {{ 'flash' if m.flash else '' }}" id="{{ m.dom_id }}">...</div>
  {% elif m.kind == 'timestamp' %}
    <div class="time-stamp" id="{{ m.dom_id }}">...</div>
  {% elif m.kind == 'emoji' %}
    <div class="msg emoji {{ m.css_class }} {{ 'no-avatar' if not m.show_avatar else '' }}">...</div>
  {% elif m.kind == 'image' %}
    <div class="msg {{ m.css_class }} {{ 'no-avatar' if not m.show_avatar else '' }}">...</div>
  {% elif m.kind == 'video' %}
    <div class="msg {{ m.css_class }} {{ 'no-avatar' if not m.show_avatar else '' }}">...</div>
  {% else %}
    <div class="msg {{ m.css_class }} {{ 'no-avatar' if not m.show_avatar else '' }}">...</div>
  {% endif %}
{% endfor %}
```

## 4.4 消息字典(`messages` 元素)

`renderer.py` 为每条消息生成:

| 键 | 类型 | 说明 |
|---|---|---|
| `dom_id` | string | 形如 `m1`、`m2`,唯一 |
| `kind` | enum | `text` / `image` / `sys` / `timestamp` / `video` / `emoji` |
| `sender_id` | string | `__system__` 表示系统/时间戳消息 |
| `sender_name` | string | 系统/时间戳消息为空字符串 |
| `sender_avatar` | string 或 null | 系统/时间戳消息为 `None` |
| `label` | string 或 null | 参与者 label,群聊时显示在昵称旁 |
| `text` | string 或 null | 文字/时间戳/emoji/图片说明内容 |
| `image_url` | string 或 null | 图片 URL |
| `video_url` | string 或 null | 视频 URL |
| `cover_url` | string 或 null | 视频封面 URL |
| `duration` | string 或 null | 视频时长,如 `0:10` |
| `css_class` | string | `self` / `""` / `__system__` / `__timestamp__` |
| `is_self` | bool | 是否"自己"发言 |
| `flash` | bool | 系统消息是否带红色脉冲 |
| `show_avatar` | bool | 是否显示头像(连续消息只显示一次) |
| `show_name` | bool | 是否显示发送者昵称(自己消息和连续消息不显示) |

## 4.5 参与者字典(`participants` 元素)

| 键 | 类型 | 说明 |
|---|---|---|
| `id` | string | 同 Pydantic |
| `name` | string | 同 Pydantic |
| `avatar_url` | string 或 null | 头像图;若 `None` 用默认灰色占位 |
| `label` | string 或 null | 单聊副标题 / 群聊企业标签 |
| `css_class` | string | 等于 `id`(供 `.avatar.<id>` 选择器使用) |

## 4.6 连续消息合并头像

`renderer.build_messages()` 会记录上一个普通聊天消息的发送者。
同一 `sender_id` 连续发送时,后续消息的 `show_avatar` 与 `show_name` 为 `False`,模板通过 `no-avatar` 类隐藏头像并去掉左侧留白,模拟真实微信效果。

系统消息(`sys`)和时间戳(`timestamp`)会重置合并状态。

## 4.7 TIMELINE 生成规则

`renderer.py` 构造:

```python
# 若用户第一条消息是 timestamp,则用它替换默认时间戳
if first_msg.kind == "timestamp":
    timeline = [{"id": "m1", "at": 500, "type": "timestamp"}]
    start_idx = 1
else:
    timeline = [{"id": "t1", "at": 500, "type": "stamp"}]
    start_idx = 0

t = 1200
for i, m in enumerate(messages[start_idx:], start=start_idx + 1):
    timeline.append({
        "id": f"m{i}",
        "at": t,
        "type": "sys" if m.kind == "sys"
                else "timestamp" if m.kind == "timestamp"
                else "msg",
        "flash": m.kind == "sys" and "移出" in (m.text or ""),
    })
    t += m.delay_ms
```

`flash` 启发式:系统消息文本含 "移出" 时启用红色脉冲。

## 4.8 时长计算

```python
def auto_duration(messages, first_delay_ms=1200):
    return first_delay_ms + sum(m.delay_ms for m in messages) + 1500
```

若用户显式传 `config.duration_ms`,以用户值为准(用于"我想录长一点"场景)。

## 4.9 样式约定

| 项 | 值 | 来源 |
|---|---|---|
| 画布 | 1080×1920 | `body` width/height |
| 背景色 | `config.background` | 默认 `#ededed` |
| 自己气泡背景 | `#95ec69`(微信绿) | 与真实微信一致 |
| 他人气泡背景 | `#ffffff` | 与 05 示例一致 |
| 单独 emoji 大小 | `120px` | 接近真实微信大表情 |
| 视频封面最大宽度 | `500px` | 与图片消息一致 |
| 字体栈 | `PingFang SC` → `Hiragino Sans GB` → `Microsoft YaHei` → `Noto Sans CJK SC` | 跨平台兜底 |
| 头像圆角 | `12px` | iOS 微信风格(不是正圆) |
| 气泡圆角 | `14px` | 微信默认 |
| 气泡箭头 | `::before` border 三角 | 经典 CSS 技巧 |
| 底部手势条 | `44px`, 280×8px 横线 | iPhone 风格 |

## 4.10 与 05-chat-wechat-style 同步

主仓库的 `examples/05-chat-wechat-style/` 升级样式时:

1. 复制新版 `index.html`
2. 把 CSS 中 `body { background: ... }` 改为 `{{ background }}`
3. 把 `.avatar.zhen { background-image: url("assets/zhen.png") }` 等改为内联 `style="background-image: url({{ ... }})"`
4. 把硬编码 HTML 结构(`<div class="msg" id="m1">甄嬛</div>`)替换为 `{% for m in messages %}...` 循环
5. 把硬编码 TIMELINE 替换为 `{{ timeline | tojson }}`
6. 跑 `tests/test_renderer.py` 验证渲染产物

## 4.11 模板测试

`backend/tests/test_renderer.py` 应包含:

- ✅ 最小配置(2 参与者 / 1 文本消息)能渲染出合法 HTML
- ✅ 单聊模式"自己"消息带 `.msg.self`
- ✅ 图片消息生成 `<img>` 标签
- ✅ 视频消息渲染播放按钮和时长
- ✅ emoji 消息渲染为大表情
- ✅ 时间戳(`timestamp`)消息渲染为 `.time-stamp`
- ✅ 系统消息不显示头像
- ✅ 连续消息只显示一次头像
- ✅ 状态栏时间/网速/电池可配置
- ✅ 单聊副标题、群聊人数、免打扰铃铛可配置
- ✅ TIMELINE JSON 合法可被 `JSON.parse` 解析
- ✅ 缺少 `text` 的 text 类消息报错
- ✅ 缺头像 URL 的消息用默认占位图(灰色 div)

## 4.12 调试技巧

预览阶段可在 `renderer.py` 加 `render_template()` 末尾:

```python
if settings.DEBUG_PREVIEW:
    Path("/tmp/preview.html").write_text(html, encoding="utf-8")
```

浏览器直接打开本地文件看效果;或用 `python -m http.server` 起个静态服务。
