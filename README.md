# 微信聊天视频生成器

在网页表单里配置微信聊天(头像、文字、单聊/群聊、图片消息、系统消息),
实时预览动画效果,一键生成 1080×1920 的 MP4 短视频。

> 技术栈:FastAPI + Jinja2 + Playwright(Python) + ffmpeg + React 18 + Vite + Docker
> 设计文档见 [`docs/README.md`](./docs/README.md)。

## 功能

- 单聊 / 群聊两种模式(单聊"我"在右侧绿色气泡,群聊默认左侧)
- 文字 / 图片 / 系统消息三种类型,系统消息含"移出"字样时带红色脉冲动画
- 头像、图片直传后端(`/api/upload`),自动校验大小与类型
- iframe 实时预览,表单编辑 300ms 防抖后自动重播
- 提交后 SSE 实时推送进度,完成后一键下载 MP4
- 录制时长自动计算,可与 `duration_ms` 精确对齐

## 快速开始(Docker)

```bash
# 0. 先构建前端产物(需要 Node 18+)
cd frontend && npm install && npm run build && cd ..

# 1. 一键起服务(后端 8000 + 前端 8080)
docker compose up -d

# 2. 浏览器打开
open http://localhost:8080
```

- 健康检查:`curl http://localhost:8000/health` → `{"status":"ok","workers":2,"queue_size":0}`
- 上传与产物持久化在 `./storage/`

## 开发模式(前后端分别启动)

前置依赖:Python 3.11+、Node 18+、ffmpeg(Playwright Chromium 首次运行自动下载)。

```bash
# 后端
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows;macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
uvicorn app.main:app --reload --port 8000

# 前端(另开终端)
cd frontend
npm install
npm run dev                       # http://localhost:5173,Vite 代理 /api → 8000
```

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `WORKER_COUNT` | 2 | 并发录制 worker 数 |
| `LOG_LEVEL` | info | 日志级别 |
| `MAX_QUEUE_SIZE` | 100 | 队列上限,超过 `/api/render` 返回 503 |
| `MAX_UPLOAD_SIZE` | 2097152 | 单文件 2MB |
| `STORAGE_DIR` | `./storage` | 文件存储根 + SQLite DB |
| `AUTH_REQUIRED` | `true` | 强制鉴权开关;本地 dev / demo 设 `false` 跳过鉴权 |

## 多用户 / Session

- 所有接口(除 `/health`)都需要 `X-User-Id` header 或 `user_id` cookie 标识当前用户;
  MVP 阶段首次出现即自动注册,生产请反向代理一层(OIDC)写 header / cookie。
- 一次"任务"=一个 session:前端启动调 `POST /api/sessions` 拿到 `session_id`,
  后续上传 / 预览 / 渲染都挂到这个 session。
- 文件落在 `storage/users/{user_id}/sessions/{session_id}/uploads/`,
  产物落在 `storage/users/{user_id}/sessions/{session_id}/outputs/`,跨用户物理隔离。
- 访问文件用 `/api/files/{file_id}`,下载产物用 `/api/jobs/{job_id}/output` —
  后端按所有权校验后才返回内容,不再用全局静态挂载。

## 本地开发 / Demo 跳过鉴权

设环境变量 `AUTH_REQUIRED=false`,后端会跳过 cookie / header 校验,
所有请求归一个匿名用户(默认 `anonymous`,可改 `ANONYMOUS_USER_ID`)。启动会打 WARNING。
**生产必须保持 `AUTH_REQUIRED=true` (默认值)**。

## 测试

```bash
cd backend
.venv\Scripts\python -m pytest tests -q
```

## 手动验证

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/api/preview-html \
  -H 'Content-Type: application/json' -d @examples/minimal.json

curl -X POST http://localhost:8000/api/render \
  -H 'Content-Type: application/json' -d @examples/minimal.json
# → {"job_id":"..."} 然后:
curl -N http://localhost:8000/api/jobs/<job_id>/events   # SSE 进度
curl -o out.mp4 http://localhost:8000/outputs/<job_id>.mp4
```

## 目录结构

```
backend/        FastAPI 应用(models / renderer / recorder / queue / storage)
  templates/    微信风格 Jinja2 模板
  tests/        pytest 用例
frontend/       React + TS + Vite 前端
deploy/         Dockerfile、nginx.conf
examples/       示例配置 JSON
docs/           设计文档
```

## 常见问题

- **录出来的视频中文是方块字?** 容器内需安装 `fonts-noto-cjk`(Dockerfile 已内置);本地开发用系统字体即可。
- **生成很慢?** 单个任务约 25-35s(取决于消息数),可调大 `WORKER_COUNT` 提升并发,注意 CPU/内存上限。
- **上传被拒?** 单文件 ≤ 2MB,仅支持 png / jpeg / webp / gif。
- **预览与视频不一致?** 预览走浏览器本地字体,录制走 Noto CJK,视觉效果接近但非逐像素一致。
