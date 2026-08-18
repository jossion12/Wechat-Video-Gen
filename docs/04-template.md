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
    "title": str,                        # config.title
    "background": str,                   # config.background
    "participants": list[dict],          # [{id, name, avatar_url, css_class}]
    "messages": list[dict],              # 渲染好的消息列表(已加 css_class / msg_type)
    "timeline": list[dict],              # [{id, at_ms, type}]
    "duration_ms": int,                  # 录制总时长
}
```

`renderer.py` 负责把 `ChatConfig` 转换成上面的"扁平化"结构,
模板里只做展示用 for 循环和条件判断,不写复杂逻辑。

## 4.3 模板骨架

```jinja2
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Chat Mockup — WeChat style</title>
<style>
  /* ---- 基础 ---- */
  * { margin: 0; padding: 0; box-sizing: border-box;
      -webkit-font-smoothing: antialiased; }
  html, body {
    overflow: hidden;
    background: {{ background }};
    font-family: -apple-system, "PingFang SC", "Hiragino Sans GB",
                 "Microsoft YaHei", "Noto Sans CJK SC", "Segoe UI", sans-serif;
  }
  body { width: 1080px; height: 1920px; position: relative; color: #111; }

  /* ---- 状态栏 / 头部 / 输入栏 ---- */
  /* (与 05-chat-wechat-style 完全一致) */

  /* ---- 聊天气泡 ---- */
  .msg { display: flex; gap: 18px; max-width: 85%;
         opacity: 0; transform: translateY(30px) scale(0.96);
         transition: opacity .4s ease-out, transform .4s ease-out; }
  .msg.show { opacity: 1; transform: translateY(0) scale(1); }

  .msg.self { flex-direction: row-reverse; align-self: flex-end; }
  .msg.self .body { align-items: flex-end; }
  .msg.self .bubble {
    background: #95ec69; color: #1a1c1f;
    border-radius: 14px 14px 4px 14px;
  }
  .msg.self .bubble::before {
    left: auto; right: -12px;
    border-right: none;
    border-left: 14px solid #95ec69;
  }
  .msg.self .sender { display: none; }  /* 自己发言不显示名字 */

  /* 其余 .avatar / .bubble / .sys-msg 等样式同 05-chat-wechat-style */
</style>
</head>
<body>
  <!-- 状态栏(同 05) -->
  <div class="status-bar">...</div>

  <!-- 头部(标题用 {{ title }}) -->
  <div class="header">
    <div class="back">‹</div>
    <div class="group-title">{{ title }}</div>
    <div class="more">···</div>
  </div>

  <!-- 聊天区 -->
  <div class="chat-wrap">
    <div class="chat-inner" id="chat">
      <div class="time-stamp" id="t1">13:12</div>

      {% for m in messages %}
        {% if m.kind == 'sys' %}
          <div class="sys-msg {% if m.flash %}flash{% endif %}"
               id="{{ m.dom_id }}">{{ m.text }}</div>
        {% elif m.kind == 'image' %}
          <div class="msg {{ m.css_class }}" id="{{ m.dom_id }}">
            <div class="avatar {{ m.sender_id }}"
                 style="background-image: url('{{ m.sender_avatar }}');"></div>
            <div class="body">
              {% if not m.is_self %}<div class="sender">{{ m.sender_name }}</div>{% endif %}
              <div class="bubble img-bubble">
                <div class="img-wrap">
                  <img src="{{ m.image_url }}" alt="{{ m.text or '' }}">
                </div>
                {% if m.text %}<div class="img-caption">{{ m.text }}</div>{% endif %}
              </div>
            </div>
          </div>
        {% else %}
          <div class="msg {{ m.css_class }}" id="{{ m.dom_id }}">
            <div class="avatar {{ m.sender_id }}"
                 style="background-image: url('{{ m.sender_avatar }}');"></div>
            <div class="body">
              {% if not m.is_self %}<div class="sender">{{ m.sender_name }}</div>{% endif %}
              <div class="bubble">{{ m.text }}</div>
            </div>
          </div>
        {% endif %}
      {% endfor %}
    </div>
  </div>

  <!-- 输入栏(同 05) -->
  <div class="input-bar">...</div>

<script>
  const TIMELINE = {{ timeline | tojson }};
  // 自动滚动逻辑(同 05)
  function autoScroll(lastId) { ... }
  window.addEventListener('load', () => {
    setTimeout(() => {
      TIMELINE.forEach(t => setTimeout(() => {
        const el = document.getElementById(t.id);
        if (!el) return;
        el.classList.add('show');
        if (t.type === 'sys' && t.flash) {
          setTimeout(() => el.classList.add('flash'), 120);
        }
        setTimeout(() => autoScroll(t.id), 250);
      }, t.at));
    }, 300);
  });
</script>
</body>
</html>
```

## 4.4 消息字典(`messages` 元素)

`renderer.py` 为每条消息生成:

| 键 | 类型 | 说明 |
|---|---|---|
| `dom_id` | string | 形如 `m1`、`m2`,唯一 |
| `kind` | enum | `text` / `image` / `sys` |
| `sender_id` | string | `__system__` 表示系统消息 |
| `sender_name` | string | 系统消息为空字符串 |
| `sender_avatar` | string 或 null | 系统消息为 `None` |
| `text` | string 或 null | 文字内容 |
| `image_url` | string 或 null | 图片 URL |
| `css_class` | string | `self` / `""` / `__system__` |
| `is_self` | bool | 是否"自己"发言(决定是否显示 sender) |
| `flash` | bool | 系统消息是否带红色脉冲 |

## 4.5 参与者字典(`participants` 元素)

| 键 | 类型 | 说明 |
|---|---|---|
| `id` | string | 同 Pydantic |
| `name` | string | 同 Pydantic |
| `avatar_url` | string 或 null | 头像图;若 `None` 用默认灰色占位 |
| `css_class` | string | 等于 `id`(供 `.avatar.<id>` 选择器使用) |

## 4.6 TIMELINE 生成规则

`renderer.py` 构造:

```python
timeline = [{"id": "t1", "at": 500, "type": "stamp"}]
t = 1200
for i, m in enumerate(messages, start=1):
    timeline.append({
        "id": f"m{i}",
        "at": t,
        "type": "sys" if m.kind == "sys" else "msg",
        "flash": m.kind == "sys" and "移出" in (m.text or ""),
    })
    t += m.delay_ms
```

`flash` 启发式:系统消息文本含 "移出" 时启用红色脉冲。
未来可改为显式 `Message.flash: bool` 字段。

## 4.7 时长计算

```python
def auto_duration(messages, first_delay_ms=1200):
    return first_delay_ms + sum(m.delay_ms for m in messages) + 1500
```

若用户显式传 `config.duration_ms`,以用户值为准(用于"我想录长一点"场景)。

## 4.8 样式约定

| 项 | 值 | 来源 |
|---|---|---|
| 画布 | 1080×1920 | `body` width/height |
| 背景色 | `config.background` | 默认 `#ededed` |
| 自己气泡背景 | `#95ec69`(微信绿) | 与真实微信一致 |
| 他人气泡背景 | `#ffffff` | 与 05 示例一致 |
| 字体栈 | `PingFang SC` → `Hiragino Sans GB` → `Microsoft YaHei` → `Noto Sans CJK SC` | 跨平台兜底 |
| 头像圆角 | `12px` | iOS 微信风格(不是正圆) |
| 气泡圆角 | `14px` | 微信默认 |
| 气泡箭头 | `::before` border 三角 | 经典 CSS 技巧 |

## 4.9 与 05-chat-wechat-style 同步

主仓库的 `examples/05-chat-wechat-style/` 升级样式时:

1. 复制新版 `index.html`
2. 把 CSS 中 `body { background: ... }` 改为 `{{ background }}`
3. 把 `.avatar.zhen { background-image: url("assets/zhen.png") }` 等改为内联 `style="background-image: url({{ ... }})"`
4. 把硬编码 HTML 结构(`<div class="msg" id="m1">甄嬛</div>`)替换为 `{% for m in messages %}...` 循环
5. 把硬编码 TIMELINE 替换为 `{{ timeline | tojson }}`
6. 跑 `tests/test_renderer.py` 验证渲染产物

## 4.10 模板测试

`backend/tests/test_renderer.py` 应包含:

- ✅ 最小配置(2 参与者 / 1 文本消息)能渲染出合法 HTML
- ✅ 单聊模式"自己"消息带 `.msg.self`
- ✅ 图片消息生成 `<img>` 标签
- ✅ 系统消息不显示头像
- ✅ TIMELINE JSON 合法可被 `JSON.parse` 解析
- ✅ 缺少 `text` 的 text 类消息报错
- ✅ 缺头像 URL 的消息用默认占位图(灰色 div)

## 4.11 调试技巧

预览阶段可在 `renderer.py` 加 `render_template()` 末尾:

```python
if settings.DEBUG_PREVIEW:
    Path("/tmp/preview.html").write_text(html, encoding="utf-8")
```

浏览器直接打开本地文件看效果;或用 `python -m http.server` 起个静态服务。