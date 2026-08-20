# 压缩包导入格式说明

> 把一次"对话剧场"任务（DSL 配置 + 所有图片素材）打包成 zip，
> 上传到对话剧场 → 自动解压 → 跳到预览页面。

## 一、zip 结构

一个合法的 zip 至少包含 **`dsl.json`**（在 zip 根目录），其他都是可选的：

```
my-dialogue.zip
├── dsl.json          ← 必需
├── manifest.json     ← 可选
├── avatars/          ← 推荐放头像（仅约定）
│   ├── alice.png
│   └── bob.jpg
├── backgrounds/      ← 推荐放背景图（仅约定）
│   └── bg.jpg
└── images/           ← 推荐放聊天图片 / 视频封面（仅约定）
    ├── chat-1.jpg
    └── chat-2.png
```

> `avatars/` / `backgrounds/` / `images/` 这几个目录名只是"心智锚点"，
> 后端不强制要求。你也可以把全部图片平铺在 zip 根目录，只要 `dsl.json` 里引用对就行。

## 二、`dsl.json` 怎么写

`dsl.json` 是一个完整的 [VideoDSL](../../docs/02-data-model.md) 对象。例如：

```json
{
  "schema_version": "1.0",
  "kind": "chat",
  "template": "cyberpunk",
  "scene": {
    "mode": "single",
    "title": "周末计划",
    "background": "#0a0a12",
    "background_image_url": "backgrounds/bg.jpg",
    "style_theme": "cyberpunk",
    "intent": "short_video_drama",
    "intent_acknowledged": true,
    "participants": [
      { "id": "me",  "name": "我",  "avatar_url": "avatars/me.png",  "persona": "" },
      { "id": "her", "name": "她", "avatar_url": "avatars/her.png", "persona": "" }
    ],
    "messages": [
      { "sender_id": "me",  "kind": "text",  "text": "在吗",     "delay_ms": 1500 },
      { "sender_id": "her", "kind": "text",  "text": "嗯，怎么了", "delay_ms": 1500 },
      { "sender_id": "me",  "kind": "image", "image_url": "images/chat-1.jpg", "delay_ms": 1500 }
    ],
    "watermark": {
      "text": "本内容由 AI 生成 · 仅供创意表达",
      "badge_style": "neon"
    }
  }
}
```

### 图片 URL 的写法

DSL 中凡是引用图片的字段（`background_image_url`、`avatar_url`、`image_url` 等），URL 可以是：

#### 1. zip 内的相对路径（最常见）

```json
"avatar_url": "avatars/me.png"
```

后端会自动把 `avatars/me.png` 这条 zip 内文件上传到当前 session，并把 URL 改写成 `/api/files/{file_id}`。

#### 2. 远程 URL（保留原样）

```json
"avatar_url": "https://cdn.example.com/avatar.png"
```

导入时不动，直接复用线上资源。

#### 3. data URI（保留原样）

```json
"avatar_url": "data:image/png;base64,iVBORw0KGgo..."
```

导入时不动，适合小图标。

#### 4. 之前 session 的 URL（不推荐在新包用）

```json
"avatar_url": "/api/files/01HX2J3K9F8ABCDEFGHJKMN"
```

导入时会**先尝试在当前 session 找**，找不到则报错。

### 写错的常见后果

| 错误 | 现象 |
|---|---|
| `dsl.json` 写在子目录里（如 `config/dsl.json`） | 导入失败："missing dsl.json (must be at zip root)" |
| DSL 引用 `avatars/me.png` 但 zip 里没有 | 导入失败："missing files in zip: avatars/me.png" |
| DSL 引用 `avatars/me.png`，但实际是 `avatars/Me.png` | 导入失败（大小写敏感） |
| `schema_version` 写成 `0.9` 或 `2.0` | 导入失败："schema_version mismatch" |
| DSL 里出现 `kind: "video"` 的消息 | 看 `video_url`：指向 zip 路径 → 拒绝；指向绝对 URL → 成功 |
| DSL `video_url` 是 zip 内相对路径 | 整包拒绝 `unsupported_video_url`（视频本体不能进 zip） |

## 三、可选的 `manifest.json`

当你希望"同一个 DSL 模板复用不同图片组"时，可以把图片路径抽到 `manifest.json`：

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

然后在 `dsl.json` 里写"语义化 key"（不带扩展名，纯英文标识）：

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

导入时优先按 manifest 解析（key → 路径），找不到再退回到"直接当相对路径"。

## 四、限制

| 项 | 上限 | 超了会怎样 |
|---|---|---|
| zip 本体大小 | 50 MB | 整包拒绝 |
| 解压后总大小 | 20 MB | 整包拒绝 |
| 单个文件大小 | 2 MB | 该文件单独拒绝 |
| 条目数（文件 + 目录） | 1000 | 整包拒绝 |
| 嵌套目录深度 | 8 层 | 整包拒绝 |
| 图片格式 | png / jpg / webp / gif | 整包拒绝 |
| 视频本体（`Message.video_url`） | 不允许从 zip 导入 | 见下 |

### 关于视频消息

DSL 里可以有 `kind: "video"` 的消息，但 **视频文件本身不能放进 zip**（体量 / 转码 / 兼容性问题）。

- ✗ 写 `"video_url": "videos/clip.mp4"` → 整包拒绝 `unsupported_video_url`
- ✗ 写 `"video_url": "video_clip"` 且 manifest 指向 zip 内视频 → 整包拒绝
- ✓ 写 `"video_url": "https://cdn.example.com/clip.mp4"` → 保留原样（外部 CDN）
- ✓ 写 `"video_url": "data:video/mp4;base64,..."` → 保留原样
- ✓ 写 `"cover_url": "images/cover.jpg"` → 正常从 zip 导入（封面是图片）

## 五、完整示例

把本目录里现有的任何一个示例（比如 `../comic.json`）作为模板开始打包：

```bash
# 1. 复制示例
cp ../comic.json dsl.json

# 2. 准备图片
mkdir -p avatars backgrounds images
cp /path/to/my-avatar.png avatars/me.png
cp /path/to/bg.jpg backgrounds/bg.jpg
cp /path/to/chat-pic.jpg images/chat-1.jpg

# 3. 编辑 dsl.json，把 URL 改成 zip 内相对路径
#    background_image_url: "backgrounds/bg.jpg"
#    avatar_url: "avatars/me.png"
#    image_url: "images/chat-1.jpg"

# 4. 打包
zip -r my-dialogue.zip dsl.json avatars/ backgrounds/ images/
```

然后在对话剧场页面点"导入"按钮，选这个 zip 即可。

## 六、安全提醒

后端对上传的 zip 做以下防护：

- **Zip Slip**：拒绝任何含 `..` 或绝对路径的条目
- **Zip Bomb**：累加解压前大小 + 限制条目数 + 限制总解压大小
- **MIME 嗅探**：扩展名是 png 但内容是 html 的会被拒绝
- **session 隔离**：所有图片落到你当前登录用户的当前 session，不会污染他人空间
- **去重**：同 session 内相同 md5 的图片复用现有 file_id，不会重复占空间

如果你打包的 zip 被拒绝，请检查上面的限制项，或查看页面顶部的红色错误提示。