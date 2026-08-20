# 01 · 总体架构

## 1.1 数据流

```
┌──────────────┐  POST /api/preview-html  ┌──────────────┐
│   前端表单   │ ──────────────────────→ │  FastAPI     │
│  (React)     │ ←─────── HTML ───────── │  · 渲染模板  │
│              │                          │  · 拼 HTML   │
│ ┌──────────┐ │  POST /api/render        └──────────────┘
│ │ iframe   │ │ ──────────────────────────────────→┐
│ │ 预览面板 │ │ ←─────── { job_id } ────────────────┤
│ └──────────┘ │                                    │
│ ┌──────────┐ │  GET /api/jobs/{id}/events (SSE)   │
│ │ 进度面板 │ │ ←──────── progress / done ──────────┤
│ └──────────┘ │                                    ↓
└──────────────┘                              ┌──────────────┐
       ↑                                      │ asyncio.Queue │
       │ GET /outputs/{job_id}.mp4            │  + Worker 池  │
       └─────────────────────────────────────│ (Playwright) │
                                              └──────┬───────┘
                                                     ↓
                                              ┌──────────────┐
                                              │ 本地存储     │
                                              │ /storage/    │
                                              │  uploads/    │
                                              │  outputs/    │
                                              └──────────────┘
```

## 1.2 技术选型

| 层 | 选择 | 替代方案 | 选定理由 |
|---|---|---|---|
| 后端框架 | FastAPI | Flask / Django | 异步原生、自动 OpenAPI、SSE 一等公民 |
| ASGI 服务器 | uvicorn | hypercorn | FastAPI 官方推荐 |
| 模板引擎 | Jinja2 | Mako / 字符串拼接 | 与 Flask 兼容、模板继承、IDE 支持好 |
| 录制 | Playwright(Python) | Selenium / Puppeteer | 与 Node 版 API 完全等价;Chromium 性能稳定 |
| 转码 | ffmpeg(subprocess) | moviepy | 沿用 `record.mjs` 同款参数,无质量损失 |
| 任务队列 | `asyncio.Queue` + 后台 worker | Celery + Redis / RQ | 小规模无需引入外部依赖 |
| 进度推送 | SSE(`text/event-stream`) | WebSocket / 轮询 | 单向通知足够,SSE 实现最简单 |
| 文件存储 | 本地文件系统 | S3 / OSS | 后期可平滑迁移,接口抽象 |
| 前端框架 | React 18 + TypeScript | Vue / Svelte | 主流,生态全 |
| 构建工具 | Vite | webpack / Next.js | 启动快,DX 好 |
| 字体 | Noto Sans CJK SC | PingFang(限 macOS) | Linux 容器可装、跨平台一致 |
| 容器化 | Docker + docker-compose | 手动部署 | Chromium + ffmpeg 依赖复杂,容器化一锅端 |

## 1.3 目录结构

```
wechat-video-gen/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py            # FastAPI app + 路由 + SSE
│   │   ├── models.py          # Pydantic 数据模型
│   │   ├── dsl.py             # VideoDSL / ChatScene 定义
│   │   ├── renderer.py        # Jinja2 渲染 HTML
│   │   ├── recorder.py        # Playwright 录制 + ffmpeg
│   │   ├── queue.py           # asyncio worker pool
│   │   └── storage.py         # 文件管理
│   ├── templates/
│   │   └── cyberpunk_chat.html.j2   # 赛博朋克原创风格
│   ├── assets/
│   │   └── default_avatar.png       # 可选:内置默认头像
│   ├── storage/                     # 运行时(gitignore)
│   │   ├── uploads/
│   │   └── outputs/
│   ├── requirements.txt
│   └── tests/
│       └── test_renderer.py
├── frontend/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── HeaderEditor.tsx
│   │   │   ├── IntentStep.tsx
│   │   │   ├── ParticipantList.tsx
│   │   │   ├── MessageList.tsx
│   │   │   ├── PreviewPanel.tsx
│   │   │   ├── ProgressPanel.tsx
│   │   │   ├── StaticPreview.tsx
│   │   │   └── common/
│   │   ├── hooks/
│   │   │   ├── useDebounce.ts
│   │   │   └── useRenderJob.ts
│   │   ├── api.ts
│   │   ├── types.ts
│   │   └── validate.ts
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
├── deploy/
│   ├── Dockerfile
│   └── docker-compose.yml
├── .gitignore
└── README.md
```

## 1.4 关键设计决策

### D1 · 预览与录制共用同一份 HTML
- **后端 `/api/preview-html`** 接收 `VideoDSL`,返回渲染好的 HTML 字符串（只拼模板，不录制）
- 前端 `<iframe srcDoc={html}>` 直接嵌入 — 改表单 → 防抖 300ms → 重渲染 srcDoc → 重播
- 录制走相同的 `renderer.render_dsl()`,保证所见即所得

### D2 · 不用 Redis / Celery
- 小规模场景(十几个并发)用纯 asyncio.Queue 足够
- 任务状态用本地字典 `jobs: dict[str, Job]`(可序列化为 JSON 落盘,但 MVP 不做持久化)
- 升级路径:后期并发上 50+ 时,worker pool 平滑迁移到 RQ / arq,接口层不变

### D3 · 消息方向规则
- **对谈**:`participants[0]` 视为"我",其消息走 `.msg.self`(右侧霓虹气泡);`participants[1]` 为对方,走左侧半透明气泡
- **群像**:除非 `participant.id == "me"`,否则所有消息都走左侧半透明气泡
- "我" 可以在群像里出现一次(典型场景:用户本人发言后被大家吐槽)

### D4 · 自动算时长
- `duration_ms = 1000 + sum(m.delay_ms for m in messages) + 1500`,其中 1000ms 为片头 AI 声明卡
- 用户可显式覆盖(`ChatScene.duration_ms`),但通常不必

### D5 · 单一原创模板
- 目前只做"赛博朋克"一套原创风格,视觉上与任何真实社交平台无关
- 后续新增原创风格:新增 `templates/<style>_chat.html.j2` + 扩展 `VideoDSL.template` 与 `ChatScene.style_theme`

### D6 · 文件上传直传后端
- 上传走 `POST /api/upload`,后端写到 `storage/users/{user_id}/sessions/{session_id}/uploads/{file_id}.{ext}`
- 返回 `{url: "/api/files/{file_id}"}`,前端存进 ChatConfig
- 不引对象存储,小规模够用;上线后可平滑迁移

## 1.5 与 `html-to-mp4` 主仓库的边界

- 本项目**消费**主仓库的录制范式,不修改主仓库代码
- 模板为完全原创的赛博朋克风格,不再基于任何真实社交平台示例
- 主仓库未来更新录制框架时,本项目只需调整 `recorder.py` 与 `renderer.py` 的调用契约

## 1.6 非功能性需求

| 项 | 要求 |
|---|---|
| 启动延迟 | 冷启动 → 首屏 < 3s(Docker 内) |
| 录制吞吐 | 单 worker 30s 视频约 25s 完成;2 worker 支持 ~3 个并发 |
| 内存峰值 | 单录制 < 800MB(Chromium 主导) |
| 磁盘占用 | 单视频 2-10 MB;头像 + 图片 < 100MB/用户 |
| CJK 字体一致 | Linux / macOS / Windows 显示相同 |
| 错误恢复 | 录制失败时 MP4 不输出,前端显示错误;部分 webm 文件自动清理 |