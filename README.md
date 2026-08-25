# 对话剧场 / Dialogue Theater

在网页表单里配置原创风格的对话场景（角色、文字、单聊/群聊、图片消息、幕间字幕、回复引用、视频、表情），实时预览动画效果，一键生成 1080×1920 的 MP4 短视频。

> 技术栈：FastAPI + Jinja2 + Playwright(Python) + ffmpeg + React 18 + Vite + Docker  
> 设计文档见 [`docs/README.md`](./docs/README.md)。

## 功能

- **单聊（对谈）/ 群聊（群像）** 两种模式，消息可显式指定左右对齐
- **文字 / 图片 / 视频 / 表情 / 系统消息 / 时间戳** 六种消息类型
- **七种原创视觉风格**：赛博朋克、手绘、复古、漫画、黑白胶片、水墨；蒸汽波设计中
- **片头特效**：无 / 扫描线展开 / 打字机标题
- **回复引用**：消息可引用此前消息并显示引用块
- **头像、图片、背景图直传后端**（`/api/upload`），自动校验大小与类型
- **zip 压缩包导入**（`/api/import`）：把 DSL + 图片素材一次性导入当前 session
- **iframe 实时预览**，表单编辑 300ms 防抖后自动重播
- **提交后 SSE 实时推送进度**，完成后一键下载 MP4
- **录制时长自动计算**，可与 `duration_ms` 精确对齐
- **强制 AI 生成标识**：右下角角标 + 片头 1 秒声明卡
- **AI 辅助创作**：输入剧情概要自动生成完整对话，或基于已有对话续写候选消息
- **多用户/session 隔离**：每个用户的素材与产物物理隔离，跨用户不可访问
- **时间码 JSON 导出**：每次渲染落地 `timeline.json`（disclaimer / intro / 每条消息的精确
  出现 / 消失时刻，毫秒），通过 `GET /api/jobs/{id}/timeline` 下载；前端时间码查看页支持按
  类型过滤 + 时间轴预览。透明 / 不透明两条产物线都支持

## 快速开始（Docker）

```bash
# 0. 先构建前端产物（需要 Node 18+）
cd frontend && npm install && npm run build && cd ..

# 1. 复制环境变量模板并按需修改( especially AI_API_KEY )
cp .env.example .env

# 2. 一键起服务（后端 8000 + 前端 8080）
docker compose up -d

# 3. 浏览器打开
open http://localhost:8080
```

- 健康检查：`curl http://localhost:8000/health` → `{"status":"ok","workers":2,"queue_size":0}`
- 上传与产物持久化在 `./storage/`

## 开发模式（前后端分别启动）

前置依赖：Python 3.11+、Node 18+、ffmpeg（Playwright Chromium 首次运行自动下载）。

```bash
# 后端
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows；macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
uvicorn app.main:app --reload --port 8000

# 前端（另开终端）
cd frontend
npm install
npm run dev                       # http://localhost:5173，Vite 代理 /api → 8000
```

## 环境变量

所有变量都支持通过项目根目录的 `.env` 文件设置（`docker compose` 会自动加载），见 `.env.example`。

| 变量 | 默认 | 说明 |
|---|---|---|
| `WORKER_COUNT` | 2 | 并发录制 worker 数 |
| `LOG_LEVEL` | info | 日志级别 |
| `MAX_UPLOAD_SIZE` | 10485760 | 单文件 10MB；importer 也复用此值作为 zip 内单文件上限 |
| `STORAGE_DIR` | `./storage` | 文件存储根 + SQLite DB |
| `AUTH_REQUIRED` | `true` | 强制鉴权开关；本地 dev / demo 设 `false` 跳过鉴权 |
| `BASE_URL` | `http://localhost:8000` | 上传资源转绝对 URL；部署到域名时修改 |
| `IMPORT_MAX_ZIP_SIZE` | 209715200 | zip 本体上限（200MB） |
| `IMPORT_MAX_UNPACKED_SIZE` | 524288000 | 解压后总上限（500MB） |
| `AI_API_KEY` | — | OpenAI 兼容 API Key；未配置时 AI 生成功能不可用 |
| `AI_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容 API 基础 URL |
| `AI_MODEL` | `gpt-4o-mini` | 对话生成使用的模型 |
| `AI_MAX_TOKENS` | `4096` | 单次生成最大 token 数 |
| `AI_TEMPERATURE` | `0.8` | 生成温度 |
| `AI_DAILY_LIMIT` | `50` | 每用户每日 AI 调用额度（内存计数，重启清零） |
| `AI_TIMEOUT_SECONDS` | `60` | AI 接口超时时间 |

## 多用户 / Session

- 所有接口（除 `/health` 和 `/api/ai/health`）都需要 `X-User-Id` header 或 `user_id` cookie 标识当前用户；MVP 阶段首次出现即自动注册，生产请反向代理一层（OIDC）写 header / cookie。两种身份来源同时提供时必须一致。
- 一次"任务"=一个 session：前端启动调 `POST /api/sessions` 拿到 `session_id`，后续上传 / 导入 / 预览 / 渲染都挂到这个 session。
- 文件落在 `storage/users/{user_id}/sessions/{session_id}/uploads/`，产物落在 `storage/users/{user_id}/sessions/{session_id}/outputs/`，跨用户物理隔离。
- 访问文件用 `/api/files/{file_id}`，下载产物用 `/api/jobs/{job_id}/output` — 后端按所有权校验后才返回内容，不再用全局静态挂载。

## 本地开发 / Demo 跳过鉴权

设环境变量 `AUTH_REQUIRED=false`，后端会跳过 cookie / header 校验，所有请求归一个匿名用户（默认 `anonymous`，可改 `ANONYMOUS_USER_ID`）。启动会打 WARNING。  
**生产必须保持 `AUTH_REQUIRED=true`（默认值）。**

## 创作意图与合规

- 创建项目时必须选择创作意图（`short_video_drama`、`story_visualization`、`teaching_simulation`、`meme_sticker`）并勾选合规承诺。
- 系统自动拦截高敏感词（转账、红包、密码、验证码等）与真实社交平台名称（微信、WhatsApp 等）。
- AI 生成标识不可关闭，仅可切换右下角角标视觉样式（`neon` / `minimal` / `retro`）。

## 测试

```bash
cd backend
.venv\Scripts\python -m pytest tests -q
```

> `backend/app/tests/test_importer.py` 是压缩包导入的独立单元测试；需要时可直接运行 `pytest app/tests -q`。

## 手动验证

```bash
curl http://localhost:8000/health

# 创建 session（本地 dev 可跳过 header；生产需 X-User-Id）
curl -X POST http://localhost:8000/api/sessions \
  -H 'Content-Type: application/json' -d '{"title":"test"}'

# 用 examples/minimal.json 预览 HTML
curl -X POST http://localhost:8000/api/preview-html \
  -H 'Content-Type: application/json' \
  -H 'X-User-Id: alice' \
  -d @examples/minimal.json

# 提交渲染任务
curl -X POST http://localhost:8000/api/render \
  -H 'Content-Type: application/json' \
  -H 'X-User-Id: alice' \
  -d @examples/minimal.json
# → {"job_id":"..."} 然后:
curl -N -H 'X-User-Id: alice' http://localhost:8000/api/jobs/<job_id>/events   # SSE 进度
curl -o out.mp4   -H 'X-User-Id: alice' http://localhost:8000/api/jobs/<job_id>/output
curl -o timeline.json -H 'X-User-Id: alice' http://localhost:8000/api/jobs/<job_id>/timeline   # 时间码 JSON
```

## 压缩包导入

支持把 `dsl.json + 图片素材` 打包成 zip，通过 `POST /api/import` 一次性导入当前 session。后端会自动解压、校验、去重、改写 URL，返回改写后的 DSL。详见 [`examples/import/README.md`](./examples/import/README.md) 与 [`docs/08-import-package.md`](./docs/08-import-package.md)。

推荐 zip 结构：

```
my-dialogue.zip
├── dsl.json          # 必需
├── manifest.json     # 可选，声明 URL → zip 内路径映射
├── avatars/...       # 推荐目录
├── backgrounds/...   # 推荐目录
└── images/...        # 推荐目录
```

## AI 辅助生成

配置 `AI_API_KEY` 后可用：

- `POST /api/ai/generate-dialogue`：输入剧情概要，自动生成完整对话 DSL。
- `POST /api/ai/continue-dialogue`：基于已有 DSL 续写候选消息。
- `GET /api/ai/quota`：查询当日剩余额度。
- `GET /api/ai/health`：检查 AI 接口连通性（不消耗额度，无需鉴权）。

## 目录结构

```
backend/          FastAPI 应用（models / dsl / renderer / recorder / queue / storage / ai_service / importer / auth / db）
  app/            业务模块
  templates/      原创风格 Jinja2 模板
  tests/          pytest 用例（主测试目录）
  app/tests/      importer 单元测试
frontend/         React + TS + Vite 前端
  src/            组件、API 封装、类型定义、校验逻辑
deploy/           Dockerfile、nginx.conf
examples/         示例配置 JSON 与 zip 导入说明
docs/             设计文档
storage/          SQLite 数据库、用户上传文件与渲染产物
```

## 常见问题

- **录出来的视频中文是方块字？** 容器内需安装 `fonts-noto-cjk`（Dockerfile 已内置）；本地开发用系统字体即可。
- **生成很慢？** 单个任务约 25–35s（取决于消息数），可调大 `WORKER_COUNT` 提升并发，注意 CPU/内存上限。
- **上传被拒？** 单文件 ≤ 10MB，仅支持 png / jpeg / webp / gif。
- **预览与视频不一致？** 预览走浏览器本地字体，录制走系统字体，视觉效果接近但非逐像素一致。
- **导入 zip 报 413？** 检查 `IMPORT_MAX_ZIP_SIZE` 与 nginx `client_max_body_size`，详见 [`docs/05-deployment.md`](./docs/05-deployment.md)。
