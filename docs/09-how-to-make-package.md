# 09 · 如何制作压缩包（用户指南）

> 从零开始，把一次"对话剧场"任务打包成 zip 上传到对话剧场的完整操作手册。
> 如果你只是想确认 zip 的格式规则，直接看 [`examples/import/README.md`](../examples/import/README.md)；
> 本文档是**一步步教你怎么做**。

预计阅读时间：8 分钟。跟着做下来大概 15-30 分钟。

---

## 0. 概述

你需要一个 **zip 压缩包**，里面装两样东西：

1. **`dsl.json`** — 描述对话内容（角色、消息、风格等）
2. **图片文件** — 头像、背景图、聊天图片、视频封面等

把这两样打成一个 zip，上传到对话剧场页面 → 后端自动把图片上传到你的当前 session、改写 DSL 里的 URL → 你直接看到预览。

你不需要懂后端，不需要懂代码；只要会写 JSON 和会用 zip 命令行（或右键压缩）就行。

---

## 1. 你需要准备什么

### 软件

| 软件 | 用来做什么 | 必需吗 |
|---|---|---|
| 文本编辑器（VSCode / Notepad++ / 记事本都行） | 写 `dsl.json` | ✓ |
| zip 工具 | 把文件夹打成 zip | ✓ |
| 浏览器 | 上传 + 预览 | ✓ |

zip 工具如果你不知道在哪：

- **Windows**：右键文件夹 → "发送到" → "压缩(zipped)文件夹"
- **macOS**：右键文件夹 → "压缩"（自动生成 `.zip`）
- **Linux**：`zip -r my.zip ./myfolder/` 命令行

### 文件

| 文件 | 必需？ | 数量参考 |
|---|---|---|
| `dsl.json` | ✓ | 1 个 |
| 头像图 | 看需求 | 2-10 个 |
| 背景图 | 看需求 | 0-1 个 |
| 聊天图片 | 看需求 | 0-20 个 |
| 视频封面图（如果有视频消息） | 看需求 | 0-10 个 |
| `manifest.json` | ✗ | 0 或 1 个 |

> **图片格式限制**：png / jpg / webp / gif。单张 ≤ 10MB；压缩后 zip ≤ 200MB；解压后总大小 ≤ 500MB；总数 ≤ 1000 张。

---

## 2. 准备工作目录

挑一个**空的**文件夹作为工作目录（命名随意）：

```
my-dialogue/         ← 工作目录（名字随意）
├── dsl.json         ← 待写
├── avatars/         ← 头像目录（先建空）
├── backgrounds/     ← 背景图目录（先建空）
└── images/          ← 聊天图片目录（先建空）
```

如果不需要头像 / 背景 / 图片，对应的空目录可以删掉——但建出来放着没坏处，至少结构清晰。

**Windows**：

```cmd
mkdir my-dialogue
cd my-dialogue
mkdir avatars backgrounds images
```

**macOS / Linux**：

```bash
mkdir -p my-dialogue/{avatars,backgrounds,images}
cd my-dialogue
```

---

## 3. 准备图片

把头像 / 背景 / 聊天图片分别放到对应目录：

```
my-dialogue/
└── avatars/
    ├── me.png       ← 你的头像
    └── her.png      ← 对方头像
```

**取名建议**：

- 用小写英文或数字（`alice.png` / `bg.jpg` / `chat-01.png`）
- **避免**大写、空格、中文（虽然技术上能工作，但容易踩大小写敏感的坑）
- **避免**特殊字符（`#`、`?`、`&` 等 URL 保留字符）

如果你的图片原始文件名不规范，先重命名再复制进目录。

---

## 4. 写 `dsl.json`

这是**唯一必需**的文件，且**必须在 zip 根目录**（不在子目录里）。

### 4.1 最简单的版本

下面是一个"两个人一条消息"的最小示例，把它复制到 `my-dialogue/dsl.json`：

```json
{
  "schema_version": "1.0",
  "kind": "chat",
  "template": "cyberpunk",
  "transparent": false,
  "transparent_format": null,
  "scene": {
    "mode": "single",
    "title": "周末计划",
    "background": "#0a0a12",
    "style_theme": "cyberpunk",
    "intent": "short_video_drama",
    "intent_acknowledged": true,
    "participants": [
      { "id": "me",  "name": "我",  "avatar_url": "avatars/me.png",  "persona": "" },
      { "id": "her", "name": "她", "avatar_url": "avatars/her.png", "persona": "" }
    ],
    "messages": [
      { "sender_id": "me",  "kind": "text", "text": "在吗",        "delay_ms": 1500 },
      { "sender_id": "her", "kind": "text", "text": "嗯，怎么了",  "delay_ms": 1500 },
      { "sender_id": "me",  "kind": "text", "text": "周末吃饭？",  "delay_ms": 1500 }
    ],
    "watermark": {
      "text": "本内容由 AI 生成 · 仅供创意表达",
      "badge_style": "neon"
    }
  }
}
```

> `"transparent": false` + `"transparent_format": null` 是默认值，产物走传统不透明 `MP4 (H.264)`。想做透明背景请参考 §4.3。

### 4.2 字段说明（速查）

只列**和图片引用相关**的字段。其他字段看 [02-data-model.md](./02-data-model.md)。

| 字段路径 | 写什么 | 示例 |
|---|---|---|
| `scene.background_image_url` | 整页背景图的 zip 内路径 | `"backgrounds/bg.jpg"` |
| `scene.participants[i].avatar_url` | 第 i 个角色的头像 zip 内路径 | `"avatars/alice.png"` |
| `scene.messages[i].sender_id` | 发送者 id；必须是 `participants` 里的 id，或 `__system__` | `"alice"` / `"__system__"` |
| `scene.messages[i].image_url` | 第 i 条图片消息的图片 zip 内路径 | `"images/chat-1.jpg"` |
| `scene.messages[i].cover_url` | 第 i 条视频消息的封面 zip 内路径 | `"images/video-cover.jpg"` |
| `scene.messages[i].video_url` | 第 i 条视频消息的视频本体 | 见下方 §4.5 视频消息特殊处理 |

> **关于 `__system__` 的严格限制**：`sender_id` 写成 `__system__` 时，`kind` **只能是** `"sys"` 或 `"timestamp"`。`kind` 为 `"text"` / `"image"` / `"video"` / `"emoji"` 的消息必须由真实参与者发送，否则会报 `dsl_validation_failed`。

### 4.2.1 其他常用字段（速查）

| 字段路径 | 写什么 | 示例 |
|---|---|---|
| `scene.intro_effect` | 开场特效 | `"none"` / `"scanline"` / `"typewriter"` |
| `scene.duration_ms` | 视频总时长（毫秒）；不填则自动计算 | `30000` |
| `scene.opacity` | 整体透明度 `0.0` ~ `1.0` | `1.0` |
| `scene.background_visible` | 纯 UI 层模式开关；false 时只渲染聊天元素，隐藏背景色 / 背景图 / 主题装饰层 | `true` |
| `scene.watermark.badge_style` | AI 角标样式 | `"neon"` / `"minimal"` / `"retro"` |
| `messages[i].align` | 强制消息方向 | `"left"` / `"right"` |
| `messages[i].reply_to` | 回复引用的消息序号（从 1 开始） | `1` |

完整字段说明见 [02-data-model.md](./02-data-model.md)。

**关键约定**：zip 内的"虚拟 URL" 用**正斜杠分隔的相对路径**，不带 `/uploads/` 前缀：

```json
"avatar_url": "avatars/alice.png"        // ✓ 推荐
"avatar_url": "alice.png"                // ✓ 也可以（平铺在根目录）
"avatar_url": "/avatars/alice.png"       // ✗ 不要加前导斜杠
"avatar_url": "C:\\Users\\me\\alice.png" // ✗ 不要用绝对路径
"avatar_url": "https://cdn.../alice.png" // ✓ 远程 URL，按原样用
```

### 4.3 透明背景输出

想要透明背景视频（叠加到其他视频上、网页 GIF 背景、PNG 序列二次处理），可以在 DSL 顶层加这两个字段：

| 字段路径 | 写什么 | 示例 |
|---|---|---|
| `transparent` | 是否输出透明背景 | `true` / `false` |
| `transparent_format` | 透明视频的封装格式（`transparent=true` 时必填；不填后端按 `webm_vp9_alpha` 兜底） | `"webm_vp9_alpha"` / `"mov_prores4444"` |

最简示例（10 秒钟"半透明对话框"动画，用于叠在风景视频上）：

```json
{
  "schema_version": "1.0",
  "kind": "chat",
  "template": "cyberpunk",
  "transparent": true,
  "transparent_format": "webm_vp9_alpha",
  "scene": {
    "...": "和 §4.1 一样，省略"
  }
}
```

#### 选哪个 format？

| 格式 | 体积 | 浏览器播放 | alpha 是否确定 | 适用场景 |
|---|---|---|---|---|
| `webm_vp9_alpha`（推荐） | 小 | `<video>` 直接播放（Chrome / Edge / Firefox） | ⚠️ Chromium 默认把页面画在不透明 backdrop 上，CSS 注入 + ffmpeg `-pix_fmt yuva420p` 后仍可能有不完全透明的风险 | 想直接在网页里嵌入播放、或对体积敏感 |
| `mov_prores4444` | 大 | ❌ 浏览器兼容差，需要下载后用 QuickTime / VLC / FFmpeg 播放 | ✅ 通过逐帧 PNG 截图（`omit_background=True`）+ ProRes 4444 封装，alpha 通道确定 | 二次剪辑（Premiere / Final Cut / DaVinci）、专业合成 |

**结论**：

- **绝大多数场景用 `webm_vp9_alpha`**：体积小、能在浏览器里直接 `<video>` 播放。
- **专业剪辑 / 需要确定 alpha 的合成**用 `mov_prores4444`：alpha 通道确定，但浏览器内联播放兼容性差，请下载后用本地播放器打开。

> `transparent=true` 时，前端 UI 在「step 5 预览生成」页面底部会显示下载按钮，文案与文件名按实际产物走（`video.webm` / `video.mov`）。

### 4.4 纯 UI 层模式（纯聊天元素）

这是一个**纯 UI 层**的开关（`scene.background_visible`），跟 §4.3 的"透明背景输出"是两回事：

- §4.3 关心的是**输出格式**（MP4 / WebM / MOV、要不要 alpha 通道），是产物层的事
- §4.4 关心的是**渲染什么**——背景色 / 背景图 / 主题装饰层要不要画，是 UI 层的事

开关设成 `false` 时，页面里只保留聊天元素：

- 隐藏：`scene.background` 整页背景色、`scene.background_image_url` 整页背景图
- 隐藏主题装饰层（赛博朋克扫描线、水彩纸张纹理、漫画半调网点、pixel 扫描线、noir 颗粒 / 暗角 / 齿孔、ink 宣纸纤维 / 笔触 / 远山）
- 保留：消息气泡、头像、发送者昵称、时间戳、系统消息、片头声明卡、AI 角标

**默认值是 `true`**，不写这个字段就等于"显示背景层"，旧配置行为完全不变。

#### 使用场景

- 把对话剧场输出**叠加到其他视频上**（自己后期抠图/合成时，不需要任何背景干扰）
- 做**表情包 / 贴纸 / GIF**——只要中间的对话气泡和头像
- 在网页里把对话剧场当成**半透明浮层**嵌进去（搭配 §4.3 的透明背景输出使用）
- 跟 `opacity` 配合，把整个对话剧场做成字幕条式的可叠加素材

> **三种"可叠加素材"实现路径速查**：
>
> | 路径 | 关键字段 | 产物 | 抠图工具 |
> |---|---|---|---|
> | §4.3 透明背景输出 | `transparent: true` + `transparent_format` | 带 alpha 通道的 WebM / MOV | 必须用支持 alpha 的播放器 / 剪辑工具 |
> | §4.4 纯 UI 层模式 | `scene.background_visible: false` | 普通不透明 MP4，但里面只画聊天元素（仍是实色背景） | 用任何工具把 MP4 当贴纸 / 浮层 |
> | **§9.7 绿幕风格** | `template/style_theme: "green_screen"` | 普通不透明 MP4，整页是 `#00ff00` 纯绿 | 任何支持色键 / chroma key 的工具（PR / 剪映 / FFmpeg `chromakey` 滤镜） |
>
> 三种可以组合使用，最常见的组合是 `template: "green_screen"` + `scene.background_visible: false`（用绿幕 + 隐藏声明卡/标题栏），导出后再用色键扣掉绿色。

#### 最简示例

在 §4.1 的基础上只加一行 `"background_visible": false`：

```json
{
  "schema_version": "1.0",
  "kind": "chat",
  "template": "cyberpunk",
  "transparent": false,
  "transparent_format": null,
  "scene": {
    "mode": "single",
    "title": "周末计划",
    "background": "#0a0a12",
    "background_image_url": null,
    "background_visible": false,
    "style_theme": "cyberpunk",
    "intent": "short_video_drama",
    "intent_acknowledged": true,
    "participants": [
      { "id": "me",  "name": "我",  "avatar_url": "avatars/me.png",  "persona": "" },
      { "id": "her", "name": "她", "avatar_url": "avatars/her.png", "persona": "" }
    ],
    "messages": [
      { "sender_id": "me",  "kind": "text", "text": "在吗",        "delay_ms": 1500 },
      { "sender_id": "her", "kind": "text", "text": "嗯，怎么了",  "delay_ms": 1500 },
      { "sender_id": "me",  "kind": "text", "text": "周末吃饭？",  "delay_ms": 1500 }
    ],
    "watermark": {
      "text": "本内容由 AI 生成 · 仅供创意表达",
      "badge_style": "neon"
    }
  }
}
```

#### 渲染对照

| 元素 | `background_visible: true`（默认） | `background_visible: false` |
|---|---|---|
| `scene.background`（整页背景色） | 显示 | 隐藏（透明） |
| `scene.background_image_url`（整页背景图） | 显示（如有设置） | 隐藏（不渲染） |
| 主题装饰层（扫描线 / 噪点 / 网点 / 颗粒 / 宣纸 / 远山 等） | 显示 | 隐藏 |
| 消息气泡 / 头像 / 发送者昵称 | 显示 | 显示 |
| 时间戳 / 系统消息 / 片头声明卡 | 显示 | 显示 |
| AI 角标（右下角） | 显示 | 显示（合规标识不可关闭） |

> 这个开关只影响 UI 层是否绘制。输出格式仍由 `transparent` / `transparent_format` 决定（见 §4.3）。两者可以组合用——例如 `background_visible: false` + `transparent: true` + `transparent_format: "webm_vp9_alpha"` 就得到"只有聊天元素 + 透明背景"的可叠加素材。

### 4.5 视频消息特殊处理

视频**本体不能放进 zip**。但你可以把视频消息放在 DSL 里，视频 URL 写远程地址，封面图放 zip 里：

```json
{
  "sender_id": "alice",
  "kind": "video",
  "video_url": "https://cdn.example.com/clip.mp4",
  "cover_url": "images/clip-cover.jpg",
  "duration": "0:10",
  "delay_ms": 2500
}
```

`video_url` 必须是：

- `https://...` / `http://...` 远程 URL
- `data:video/...` 内嵌的 data URI
- `/api/files/...` 之前 session 的视频文件

**任何指向 zip 内文件的 `video_url` 都会被整包拒绝**。

---

## 5. （可选）写 `manifest.json`

只有一种情况需要 `manifest.json`：**你希望用一个 DSL 模板切换不同图片组**。

跳过本节，如果你只是打包一次性的 zip。

### 什么时候用

- 同一个对话脚本，换一套角色头像（不同演员演同一个剧本）
- 你想给图片起"语义化名字"（而不是文件路径）

### 写法

`my-dialogue/manifest.json`：

```json
{
  "files": {
    "alice_avatar":   "avatars/alice.png",
    "bob_avatar":     "avatars/bob.jpg",
    "background":     "backgrounds/bg.jpg",
    "first_chat_img": "images/chat-1.jpg"
  }
}
```

然后 `dsl.json` 里 URL 写 key：

```json
{
  "scene": {
    "background_image_url": "background",
    "participants": [
      { "id": "alice", "name": "Alice", "avatar_url": "alice_avatar" },
      { "id": "bob",   "name": "Bob",   "avatar_url": "bob_avatar"   }
    ],
    "messages": [
      { "sender_id": "alice", "kind": "image", "image_url": "first_chat_img", "delay_ms": 1500 }
    ]
  }
}
```

key 必须是纯英文标识（不带 `.png` 等扩展名）。manifest 找不到 key 时，后端会回退到"把 URL 当作 zip 内相对路径"。

---

## 6. 打包成 zip

### 6.1 方法 A：命令行（最稳）

**macOS / Linux / Git Bash**：

```bash
cd my-dialogue        # 进入工作目录
zip -r ../my-dialogue.zip .
cd ..
ls -la my-dialogue.zip
```

**Windows PowerShell**：

```powershell
cd my-dialogue
Compress-Archive -Path * -DestinationPath ..\my-dialogue.zip
cd ..
dir my-dialogue.zip
```

### 6.2 方法 B：图形界面

**Windows**：

1. 进入 `my-dialogue` 文件夹
2. `Ctrl + A` 全选
3. 右键 → "发送到" → "压缩(zipped)文件夹"
4. 把生成的 `.zip` 改名（可选）

**macOS**：

1. 进入 `my-dialogue` 文件夹
2. `Cmd + A` 全选
3. 右键 → "压缩 N 项"，生成 `Archive.zip`

### 6.3 打包后自检

解压出来看一下结构对不对：

```bash
unzip -l my-dialogue.zip
```

预期输出（节选）：

```
Archive:  my-dialogue.zip
  Length      Date    Time    Name
---------  ---------- -----   ----
      817  2024-01-01 00:00   dsl.json
        0  2024-01-01 00:00   avatars/
    12345  2024-01-01 00:00   avatars/me.png
    23456  2024-01-01 00:00   avatars/her.png
     8901  2024-01-01 00:00   backgrounds/bg.jpg
        0  2024-01-01 00:00   images/
---------                     -------
   ...
```

**确认两点**：

- [ ] `dsl.json` 在根目录（不在子目录里）
- [ ] 所有图片文件路径与 `dsl.json` 里的 URL 一一对应（拼写、大小写完全一致）

---

## 7. 上传到对话剧场

1. 浏览器打开对话剧场（默认 `http://localhost:8080`）
2. 点击页面顶部 header 里的"导入 zip"按钮
3. 选择刚才打好的 `my-dialogue.zip`
4. 也可以直接把 zip **拖拽**到页面任意位置（更省事）
5. 等待几秒（一般 < 2 秒）

成功的话：

- 自动跳到第 5 步（预览生成）
- 预览面板显示你刚才配置的对话场景
- 顶部可能显示一行绿色 toast（如果有图片重复，会提示 X 张去重）

失败的话：

- 顶部红色 banner 显示具体错误（如 "missing files in zip: avatars/me.png"）
- 不修改当前编辑器里的内容
- 你可以根据错误回到第 3-6 步修正后重新打包上传

---

## 8. 上传前自检清单

在点"导入"之前，对照下面清单检查一遍，能避开 95% 的失败：

- [ ] `dsl.json` 在 zip **根目录**（不是 `config/dsl.json` 或 `package/dsl.json`）
- [ ] `dsl.json` 是合法 JSON（用编辑器打开没有红色波浪线；或 `python -c "import json; json.load(open('dsl.json'))"` 能跑通）
- [ ] `schema_version` 字段值是 `"1.0"`（带引号，字符串）
- [ ] `intent_acknowledged` 字段值是 `true`（不带引号，布尔值）
- [ ] `participants` 数组里所有 `id` 都不重复
- [ ] 所有 `messages[].sender_id` 都能在 `participants` 里找到对应 `id`
- [ ] `sender_id` 为 `__system__` 时，`kind` 必须是 `"sys"` 或 `"timestamp"`（不能是 text / image / video / emoji）
- [ ] 所有图片 URL（`avatar_url` / `image_url` / `cover_url` / `background_image_url`）的相对路径在 zip 内**确实存在**对应文件
- [ ] 路径大小写一致（`avatars/Me.png` ≠ `avatars/me.png`）
- [ ] 没有用到 zip 内视频（`video_url` 用远程 URL）
- [ ] 每张图片 ≤ 10MB，整包解压后 ≤ 500MB

---

## 9. 七个常用模板（可直接复制）

### 9.1 纯文字对谈

最快上手。完全不用图片。

```json
{
  "schema_version": "1.0",
  "kind": "chat",
  "template": "cyberpunk",
  "scene": {
    "mode": "single",
    "title": "对话",
    "background": "#0a0a12",
    "style_theme": "cyberpunk",
    "intent": "short_video_drama",
    "intent_acknowledged": true,
    "participants": [
      { "id": "me",  "name": "我",  "avatar_url": null, "persona": "" },
      { "id": "her", "name": "她", "avatar_url": null, "persona": "" }
    ],
    "messages": [
      { "sender_id": "me",  "kind": "text", "text": "你好", "delay_ms": 1500 },
      { "sender_id": "her", "kind": "text", "text": "你好呀", "delay_ms": 1500 }
    ],
    "watermark": {
      "text": "本内容由 AI 生成 · 仅供创意表达",
      "badge_style": "neon"
    }
  }
}
```

打包只需要一个文件：

```bash
zip -r ../my-dialogue.zip dsl.json
```

### 9.2 含头像的对谈

`avatars/me.png` 和 `avatars/her.png` 两个图片。

```json
{
  "schema_version": "1.0",
  "kind": "chat",
  "template": "watercolor",
  "scene": {
    "mode": "single",
    "title": "咖啡馆偶遇",
    "background": "#f7f4ed",
    "background_image_url": "backgrounds/cafe.jpg",
    "style_theme": "watercolor",
    "intent": "story_visualization",
    "intent_acknowledged": true,
    "participants": [
      { "id": "me",  "name": "我",    "avatar_url": "avatars/me.png",  "persona": "" },
      { "id": "her", "name": "陌生女孩", "avatar_url": "avatars/her.png", "persona": "温柔" }
    ],
    "messages": [
      { "sender_id": "me",  "kind": "text", "text": "请问这里有人吗",  "delay_ms": 1500 },
      { "sender_id": "her", "kind": "text", "text": "没有，请坐",       "delay_ms": 1500 },
      { "sender_id": "me",  "kind": "text", "text": "谢谢",             "delay_ms": 1200 },
      { "sender_id": "her", "kind": "text", "text": "不客气 😊",        "delay_ms": 1200 }
    ],
    "watermark": {
      "text": "本内容由 AI 生成 · 仅供创意表达",
      "badge_style": "minimal"
    }
  }
}
```

### 9.3 群聊含图片消息

适合"分享图片"的场景。

```json
{
  "schema_version": "1.0",
  "kind": "chat",
  "template": "comic",
  "scene": {
    "mode": "group",
    "title": "朋友群",
    "background": "#ffffff",
    "style_theme": "comic",
    "intent": "meme_sticker",
    "intent_acknowledged": true,
    "participants": [
      { "id": "me",    "name": "我",   "avatar_url": "avatars/me.png",    "persona": "" },
      { "id": "alice", "name": "Alice", "avatar_url": "avatars/alice.png", "persona": "" },
      { "id": "bob",   "name": "Bob",   "avatar_url": "avatars/bob.png",   "persona": "" }
    ],
    "messages": [
      { "sender_id": "__system__", "kind": "timestamp", "text": "今天 14:30", "delay_ms": 1500 },
      { "sender_id": "alice", "kind": "text",  "text": "看这个",          "delay_ms": 1500 },
      { "sender_id": "alice", "kind": "image", "image_url": "images/funny.jpg", "delay_ms": 1800 },
      { "sender_id": "bob",   "kind": "text",  "text": "哈哈哈哈哈",      "delay_ms": 1500 },
      { "sender_id": "me",    "kind": "emoji", "text": "🤣",                "delay_ms": 1200 }
    ],
    "watermark": {
      "text": "本内容由 AI 生成 · 仅供创意表达",
      "badge_style": "neon"
    }
  }
}
```

### 9.4 含视频消息（视频用远程 URL）

```json
{
  "schema_version": "1.0",
  "kind": "chat",
  "template": "cyberpunk",
  "scene": {
    "mode": "group",
    "title": "推荐视频",
    "background": "#0a0a12",
    "style_theme": "cyberpunk",
    "intent": "short_video_drama",
    "intent_acknowledged": true,
    "participants": [
      { "id": "me",    "name": "我",   "avatar_url": null, "persona": "" },
      { "id": "alice", "name": "Alice", "avatar_url": null, "persona": "" }
    ],
    "messages": [
      { "sender_id": "alice", "kind": "video",
        "video_url": "https://cdn.example.com/clip.mp4",
        "cover_url": "images/clip-cover.jpg",
        "duration": "0:10",
        "delay_ms": 2500 },
      { "sender_id": "alice", "kind": "text", "text": "看这个视频",  "delay_ms": 1500 },
      { "sender_id": "me",    "kind": "text", "text": "有意思",      "delay_ms": 1500 }
    ],
    "watermark": {
      "text": "本内容由 AI 生成 · 仅供创意表达",
      "badge_style": "neon"
    }
  }
}
```

### 9.5 黑白胶片风格

适合怀旧、纪实、访谈类场景。

```json
{
  "schema_version": "1.0",
  "kind": "chat",
  "template": "noir",
  "scene": {
    "mode": "single",
    "title": "午夜讲堂",
    "background": "#f5f0e1",
    "style_theme": "noir",
    "intent": "teaching_simulation",
    "intent_acknowledged": true,
    "participants": [
      { "id": "me", "name": "我", "avatar_url": null, "persona": "哲学讲师" },
      { "id": "student", "name": "学生", "avatar_url": null, "persona": "求知者" }
    ],
    "messages": [
      { "sender_id": "__system__", "kind": "sys", "text": "第一幕：关于自由", "delay_ms": 1800 },
      { "sender_id": "student", "kind": "text", "text": "老师，什么是自由？", "delay_ms": 1600 },
      { "sender_id": "me", "kind": "text", "text": "自由不是想做什么就做什么。", "delay_ms": 1700 },
      { "sender_id": "student", "kind": "text", "text": "那是什么？", "delay_ms": 1600 },
      { "sender_id": "me", "kind": "text", "text": "自由是，不想做什么时，可以说不。", "delay_ms": 1800 }
    ],
    "watermark": {
      "text": "本内容由 AI 生成 · 仅供创意表达",
      "badge_style": "minimal"
    }
  }
}
```

### 9.6 水墨风格

适合古风、武侠、意境类故事。

```json
{
  "schema_version": "1.0",
  "kind": "chat",
  "template": "ink",
  "scene": {
    "mode": "single",
    "title": "风起云隐",
    "background": "#f4ecd8",
    "style_theme": "ink",
    "intent": "story_visualization",
    "intent_acknowledged": true,
    "participants": [
      { "id": "me", "name": "我", "avatar_url": null, "persona": "剑宗长老" },
      { "id": "disciple", "name": "弟子", "avatar_url": null, "persona": "守山弟子" }
    ],
    "messages": [
      { "sender_id": "__system__", "kind": "sys", "text": "风起云隐", "delay_ms": 1800 },
      { "sender_id": "disciple", "kind": "text", "text": "师父，山门有变。", "delay_ms": 1600 },
      { "sender_id": "me", "kind": "text", "text": "何事惊慌？", "delay_ms": 1700 },
      { "sender_id": "disciple", "kind": "text", "text": "后山禁地，有剑气冲天。", "delay_ms": 1800 },
      { "sender_id": "me", "kind": "text", "text": "带我去看看。", "delay_ms": 1700 }
    ],
    "watermark": {
      "text": "本内容由 AI 生成 · 仅供创意表达",
      "badge_style": "retro"
    }
  }
}
```

### 9.7 绿幕风格（方便后期抠像）

整页背景统一 `#00ff00`、顶部标题栏和片头声明卡都使用同色背景 + 黑字、没有任何主题装饰层。导出普通不透明 MP4 后，用 PR / 剪映 / FFmpeg 的色键（chroma key）功能把绿色扣掉，就能把"对话气泡 + 头像"合成到任意背景上。

实现成本最低：不需要 alpha 通道，不需要特殊播放器，任何能处理视频的工具都能用。

```json
{
  "schema_version": "1.0",
  "kind": "chat",
  "template": "green_screen",
  "scene": {
    "mode": "single",
    "title": "可合成对白",
    "background": "#00ff00",
    "style_theme": "green_screen",
    "intent": "short_video_drama",
    "intent_acknowledged": true,
    "participants": [
      { "id": "me",   "name": "我",   "avatar_url": null, "persona": "" },
      { "id": "her",  "name": "她",   "avatar_url": null, "persona": "" }
    ],
    "messages": [
      { "sender_id": "her", "kind": "text", "text": "周末有空吗？", "delay_ms": 1500 },
      { "sender_id": "me",  "kind": "text", "text": "有，怎么了",   "delay_ms": 1500 },
      { "sender_id": "her", "kind": "text", "text": "想请你吃饭",   "delay_ms": 1500 },
      { "sender_id": "me",  "kind": "text", "text": "好呀",         "delay_ms": 1500 }
    ],
    "watermark": {
      "text": "本内容由 AI 生成 · 仅供创意表达",
      "badge_style": "minimal"
    }
  }
}
```

**关键设计点**：

- `template` 与 `style_theme` 都写 `"green_screen"`，后端校验器会自动同步
- `background` 可以不写（默认就是 `#00ff00`）；写别的颜色反而会破坏抠像效果
- 顶部标题栏 / 片头声明卡都用同色背景 + 黑字，抠像后这两块会**整块消失**，只剩下气泡和 AI 角标
- 自己气泡黑底白字，他人气泡白底黑字，任何合成背景都能清晰阅读
- AI 角标用 `badge_style: "minimal"`（白底黑边）最稳，避免被绿幕吞掉

**和 §4.3 / §4.4 怎么选**：

- 想要**色键抠像（最通用）** → 用 `template: "green_screen"`（本节），产物是普通 MP4
- 想要**程序化 alpha 通道** → 用 `transparent: true` + `transparent_format: "webm_vp9_alpha"`（§4.3），但浏览器 / 剪辑工具必须支持 alpha
- 想要**纯聊天元素、不要主题装饰** → 加 `scene.background_visible: false`（§4.4），但气泡本身仍是不透明的
- 想要"绿幕 + 不显示标题栏/声明卡" → 三者组合：`template: "green_screen"` + `scene.background_visible: false`

---

## 10. 常见错误 FAQ

### Q: 点"导入"后弹出 nginx "413 Request Entity Too Large" 错误页

A: zip 体积超过 nginx 反代的 `client_max_body_size`（默认 1MB）。当前 docker-compose 部署已设为 220MB，确保你的 zip **压缩后** ≤ 200MB。如果你用 nginx 反代自己部署，改 `deploy/nginx.conf`：

```nginx
client_max_body_size 220m;   # ≥ importer 的 IMPORT_MAX_ZIP_SIZE + buffer
```

调整后必须重启 nginx（`docker compose restart frontend`）。**注意**：这是 nginx 的标准 HTML 错误页，不是对话剧场的结构化 banner，所以看不到"友好提示"。

### Q: 点"导入"后顶部红字 "missing dsl.json"

A: `dsl.json` 不在 zip 根目录。检查 zip 内是不是 `my-dialogue/dsl.json` 这种带子目录的层级。修复：把 `dsl.json` 提到 zip 第一层。

### Q: 红字 "missing files in zip: avatars/me.png"

A: `dsl.json` 引用了 `avatars/me.png`，但 zip 内实际没有这个文件。常见原因：
- 文件名打错了（拼写、大小写）
- 文件确实没放进 zip（用 `unzip -l my-dialogue.zip` 看一下文件清单）
- 路径用了反斜杠 `avatars\me.png`（应改用正斜杠）

### Q: 红字 "dsl_validation_failed: sender_id '__system__' does not match any participant id"

A: 你把 `__system__` 用在了不支持的消息类型上。`__system__` 只能用于 `kind` 为 `"sys"` 或 `"timestamp"` 的消息，例如：

```json
{ "sender_id": "__system__", "kind": "timestamp", "text": "今天 14:30", "delay_ms": 1500 }
{ "sender_id": "__system__", "kind": "sys",      "text": "【系统公告】...", "delay_ms": 1500 }
```

下面这种写法会报这个错：

```json
{ "sender_id": "__system__", "kind": "text",  "text": "..." }   // ✗
{ "sender_id": "__system__", "kind": "image", "image_url": "..." } // ✗
```

修复：把 `text` / `image` / `video` / `emoji` 消息的 `sender_id` 改成某个真实参与者的 `id`；如果想做"系统提示"样式，把 `kind` 改成 `"sys"` 并只保留 `text`（`sys` 消息不能带图片）。

### Q: 红字 "schema_version mismatch"

A: `schema_version` 不是 `"1.0"`。检查：

- 是否带了引号（应是字符串 `"1.0"`，不是数字 `1.0`）
- 是否写成了 `"0.9"` / `"2.0"` / `"v1"` 之类

### Q: 红字 "视频文件不能导入，请使用绝对 URL"

A: 你把 `video_url` 写成了 zip 内的路径，比如 `videos/clip.mp4`。视频本体不能进 zip，把 `video_url` 改成 `https://...` 远程地址。

### Q: 成功导入但预览里头像/图片显示空白

A: 可能图片真实格式与扩展名不符（比如把 jpg 改后缀为 png）。用图片查看器打开确认能正常显示，或重新导出为 png/jpg/webp/gif。

### Q: zip 本身体积超过 200MB 报错

A: 压缩后体积过大。常见原因：
- 图片未压缩（用 tinypng.com / squoosh.app 压缩）
- 有视频文件混在 zip 里（视频不能用，必须移除）

### Q: 同一张图片在 zip 里出现两次（不同文件名）

A: 这是允许的。后端会按 md5 去重，**第一次**的图片会上传，**第二次**会复用同一个 `file_id`，节省空间。

### Q: 想替换已经导入过的图（覆盖）

A: 替换 = 删除旧 file_id 再上传新 file_id。当前不支持"覆盖模式"，需要你在导入前手动删除旧图片，或在网页端用 UI 重新上传。

### Q: zip 里多塞了 `README.md` / `LICENSE` / `.DS_Store` 之类的文件

A: 没影响。后端会忽略 zip 内所有没被 DSL 引用的文件，最多在响应 `warnings` 数组里告诉你哪些被忽略了。

### Q: 想要透明背景视频（合成到其他视频里），怎么操作？

A: 在 `dsl.json` 顶层加 `"transparent": true` 并指定 `"transparent_format"`。推荐 `"webm_vp9_alpha"`（体量小、浏览器友好）。专业剪辑场景用 `"mov_prores4444"`，alpha 通道确定但浏览器内联播放差，需要下载后用 QuickTime / VLC 播放。详见 §4.3。

### Q: 想要纯 UI 模式（只显示聊天元素、不要背景）怎么操作？

A: 在 `dsl.json` 的 `scene` 顶层加 `"background_visible": false`。开关关闭后渲染时只画聊天元素（消息气泡、头像、发送者昵称、时间戳、系统消息、片头声明卡、AI 角标），背景色、背景图和主题装饰层（扫描线 / 噪点 / 网点 / 颗粒 / 宣纸 / 远山 等）全部隐藏。详见 §4.4。

### Q: 想要"绿幕背景"方便后期抠像，怎么操作？

A: 在 `dsl.json` 里把 `"template"` 和 `"scene.style_theme"` 都设成 `"green_screen"`，导出就是不透明 MP4，整页是 `#00ff00` 纯绿。后期用 PR / 剪映 / FFmpeg 的色键（chroma key）功能扣掉绿色，就能把对话气泡合成到任意背景上。实现成本最低，详见 §9.7。

---

## 11. 导入成功之后

1. 你已经在第 5 步（预览生成），iframe 里能看到刚才 DSL 配置的对话动画
2. 想再调整？手动编辑表单或重新拖一个 zip 进来（**会覆盖**当前 DSL）
3. 满意了？点右下角"生成视频"按钮 → 后端开始录制 → 完成后点下载得到 MP4 / WebM / MOV（取决于你在 §4.3 里选的格式）

> 视频生成视频的限制与"零基础编辑"完全一致：单聊 2 角色、群聊 2+ 角色、消息 ≤ 300 条、首条消息间隔 ≥ 500ms。
> 详见 [06-acceptance.md](./06-acceptance.md)。

---

## 12. 进阶

- 想做"模板化 DSL + 不同图片组" → 看第 5 节 manifest
- 想理解后端到底做了什么 → 看 [08-import-package.md](./08-import-package.md)
- 想看 VideoDSL 全部字段 → 看 [02-data-model.md](./02-data-model.md)
- 调试时想看后端日志 → 看 [05-deployment.md](./05-deployment.md)

---

## 附录 A：完整可复制的目录示例

```
my-dialogue/
├── dsl.json
├── manifest.json          ← 可选,这里没有用
├── avatars/
│   ├── me.png
│   └── her.png
├── backgrounds/
│   └── bg.jpg
└── images/
    └── chat-1.jpg
```

对应打包命令：

```bash
cd my-dialogue
zip -r ../my-dialogue.zip .
```

---

## 附录 B：JSON 校验小技巧

如果你不确定 `dsl.json` 是否合法 JSON，可以用以下方法校验：

**Python**：

```bash
python -c "import json; json.load(open('dsl.json')); print('OK')"
```

**Node.js**：

```bash
node -e "require('./dsl.json'); console.log('OK')"
```

**在线工具**：搜索 "JSON validator"，把文件内容粘进去。

---

如果按本文档操作下来还有问题，**请把错误 banner 的红字原文** + 你 `dsl.json` 的内容（不要含远程 URL）一起发出来，方便排查。