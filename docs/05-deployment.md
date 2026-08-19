# 05 · 部署方案

## 5.1 运行时依赖

| 依赖 | 版本 | 说明 |
|---|---|---|
| Python | 3.11+ | 后端 |
| Node.js | 18+ | 前端构建(仅构建时需要,运行时不需要) |
| Chromium | Playwright 自带 | 录制 |
| ffmpeg | 4.4+ | 转码 |
| fonts-noto-cjk | 任意 | Docker 镜像内置 |

## 5.2 Dockerfile

```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

# 装 ffmpeg + CJK 字体
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖,利用 Docker 缓存
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝应用代码
COPY backend/ .

# 创建运行时目录(也可挂载 volume)
RUN mkdir -p storage
ENV WORKER_COUNT=2 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD curl -fs http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

镜像大小估算:
- playwright 基础镜像:~300MB
- ffmpeg + fonts-noto-cjk:~200MB
- Python 依赖:~50MB
- **总计约 550MB**(可接受)

## 5.3 docker-compose.yml

```yaml
version: "3.9"

services:
  backend:
    build:
      context: .
      dockerfile: deploy/Dockerfile
    container_name: wechat-video-gen
    ports:
      - "8000:8000"
    volumes:
      - ./storage:/app/storage      # 持久化上传与产物
    environment:
      - WORKER_COUNT=2
      - LOG_LEVEL=info
      # - BASE_URL=http://localhost:8000  # 上传资源转绝对 URL;部署到域名时修改
    restart: unless-stopped

  # 可选:用 nginx 服务前端静态文件
  frontend:
    image: nginx:1.27-alpine
    container_name: wechat-video-gen-web
    ports:
      - "8080:80"
    volumes:
      - ./frontend/dist:/usr/share/nginx/html:ro
      - ./deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      - backend
    restart: unless-stopped
```

## 5.4 nginx 配置(前端代理到后端)

```nginx
# deploy/nginx.conf
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    # 前端静态资源
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API 反代
    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_buffering off;           # SSE 必须
        proxy_cache off;               # SSE 必须
        proxy_read_timeout 86400;       # SSE 长连接
    }

    # 上传/产物静态文件
    location /uploads/ { proxy_pass http://backend:8000; }
    location /outputs/ { proxy_pass http://backend:8000; }
}
```

## 5.5 单机部署(最简)

无 Docker,直接 systemd 服务:

```ini
# /etc/systemd/system/wechat-video-gen.service
[Unit]
Description=Wechat Video Generator
After=network.target

[Service]
WorkingDirectory=/opt/wechat-video-gen/backend
ExecStart=/opt/wechat-video-gen/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
Environment=WORKER_COUNT=2
Environment=BASE_URL=http://localhost:8000

[Install]
WantedBy=multi-user.target
```

需要单独安装:Python 3.11、ffmpeg、fonts-noto-cjk、playwright + `playwright install chromium`。

## 5.6 资源评估

### 内存

| 组件 | 占用 |
|---|---|
| FastAPI/uvicorn 基线 | ~80MB |
| 单个 Chromium 实例 | ~300-500MB |
| ffmpeg 转码 | ~50MB |
| **2 worker 峰值** | ~1.2GB |

建议最小 2GB RAM,推荐 4GB。

### CPU

Chromium 渲染对 CPU 敏感。2 worker 并发录制会接近 2 核饱和。
建议 4 核以上。

### 磁盘

- 单视频:2-10MB(取决于消息数)
- 单用户头像/图片:平均 1-5MB
- 50 次录制 / 5 个用户 / 一天:约 1GB

挂载 `storage/` 到独立 volume,方便备份与扩容。

## 5.7 字体一致性

为避免 Linux 容器与 macOS 浏览器预览字体差异:

- **预览**(iframe 内):用浏览器本地字体栈(`PingFang SC` / `Hiragino Sans GB`)
- **录制**(Playwright 内):用容器内置 `Noto Sans CJK SC`

CSS 字体栈顺序:
```css
font-family: -apple-system, "PingFang SC", "Hiragino Sans GB",
             "Microsoft YaHei", "Noto Sans CJK SC", "Segoe UI", sans-serif;
```

预览看起来"差不多",录制出来始终一致。

## 5.8 并发调优

环境变量 `WORKER_COUNT` 控制并发 worker 数:

| 配置 | 推荐值 | 适用 |
|---|---|---|
| 4 核 / 8GB | 2 | 单机小规模 |
| 8 核 / 16GB | 4 | 中等负载 |
| 16 核 / 32GB | 6-8 | 高负载 |

**注意**:
- 录制任务平均 25-35s(取决于 `duration_ms`)
- 队列堆积上限建议 100(超过则 `/api/render` 返回 503)
- CPU 是瓶颈,超过 worker 数再多也无意义

## 5.9 日志

```python
# main.py
import logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "info").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
```

关键事件:
- `Job {id} queued`
- `Worker {name} picked up {id}`
- `Recording started for {id}`
- `Job {id} done in {elapsed}s`
- `Job {id} failed: {error}`

## 5.10 备份策略

`storage/` 挂载到 volume,定期快照:

```bash
# crontab - 每天凌晨打包
0 3 * * * tar czf /backup/wechat-video-gen-$(date +\%F).tar.gz /opt/wechat-video-gen/storage
```

## 5.11 升级路径

**短期**(并发增长):
- 调大 `WORKER_COUNT`
- 升级单机 CPU/内存

**中期**(并发 50+):
- 把 `queue.py` 从 `asyncio.Queue` 迁移到 Redis + RQ
- 接口层不变,只换 worker 进程

**长期**(多机):
- 多副本部署,worker 进程从 backend API 拆出来
- 引入对象存储(S3/OSS)替换本地文件系统
- 引入 CDN 分发 `/outputs/`

## 5.12 环境变量清单

| 变量 | 默认 | 说明 |
|---|---|---|
| `WORKER_COUNT` | 2 | 并发 worker 数 |
| `LOG_LEVEL` | info | 日志级别 |
| `MAX_QUEUE_SIZE` | 100 | 队列上限,超过返回 503 |
| `MAX_UPLOAD_SIZE` | 2097152 | 单文件 2MB |
| `STORAGE_DIR` | `./storage` | 文件存储根；DB 与分用户文件夹都在此目录下 |
| `DEBUG` | false | 调试模式(写 preview.html 到 /tmp) |
| `AUTH_REQUIRED` | `true` | 是否强制鉴权。**生产必须保持 `true`**；本地 dev / demo 可设 `false` 跳过鉴权(详见 §5.14) |
| `ANONYMOUS_USER_ID` | `anonymous` | `AUTH_REQUIRED=false` 时所有匿名请求归属的 user_id |
| `ANONYMOUS_USER_NAME` | `anonymous` | 同上的 username |

## 5.13 多用户 / session 隔离

后端不做鉴权逻辑(仅凭 header 取 user_id);生产应反向代理一层(OIDC / cookie)
向 `X-User-Id` header 注入已验证的用户 ID，所有文件/产物仍落在
`storage/users/{user_id}/sessions/{session_id}/{uploads|outputs}/` 下，跨用户物理隔离。

SQLite 文件位置:`{STORAGE_DIR}/wechat-video-gen.db`(WAL 模式)。
多副本部署时需迁移到集中式 DB(PostgreSQL/MySQL),可保持 `app/db.py` 的接口不变。

## 5.14 AUTH_REQUIRED 鉴权开关

| 环境 | 推荐设置 | 说明 |
|---|---|---|
| 生产 | `AUTH_REQUIRED=true` (默认) | 强制鉴权 — 没带 cookie / header → 401 |
| 本地 dev | `AUTH_REQUIRED=false` | 跳过鉴权，所有请求归 `ANONYMOUS_USER_ID`（默认 `anonymous`） |
| CI / demo | `AUTH_REQUIRED=false` | 同上 |

设 `AUTH_REQUIRED=false` 启动时,日志会打:

```
WARNING auth: AUTH_REQUIRED=false: running in LOCAL DEV mode with user 'anonymous'.
        All requests are anonymous — NO user isolation. Do NOT use in production.
```

**不要在生产设 false。**即使已有反向代理层挡鉴权，也应保留后端二次校验作为 defense in depth。

设置示例：

```bash
# 生产
docker run -e AUTH_REQUIRED=true ... wechat-video-gen

# 本地开发
export AUTH_REQUIRED=false
uvicorn app.main:app --reload
```