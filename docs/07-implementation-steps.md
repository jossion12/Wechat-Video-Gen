# 07 · 分步实施计划与工时

## 7.1 总览

| 阶段 | 工作内容 | 工时 |
|---|---|---|
| Day 1 | 后端骨架 + 模板 + `/preview-html` | 1.0 天 |
| Day 2 | 录制 + Worker + `/render` + SSE | 1.0 天 |
| Day 3 | 前端表单(参与者 / 消息 / 头像上传) | 1.0 天 |
| Day 4 | 前端预览 + 进度面板 + 联调 | 1.0 天 |
| Day 5 | Docker 部署 + 测试 + 文档 | 0.5-1.0 天 |
| **合计** | | **4.5-5.0 天** |

**前置依赖**:开发机已安装 Node 18+、Python 3.11+、ffmpeg。
Playwright Chromium 浏览器在第一次运行时自动下载。

---

## 7.2 Day 1 · 后端骨架

**目标**:能在本地起 FastAPI,`/preview-html` 能返回合法 HTML。

### 步骤

1. **创建项目目录**:
   ```bash
   mkdir -p dialogue-theater/{backend/{app,templates,assets,storage,tests},frontend,deploy}
   cd dialogue-theater
   ```

2. **写 `backend/requirements.txt`**:
   ```
   fastapi==0.115.*
   uvicorn[standard]==0.32.*
   jinja2==3.1.*
   playwright==1.47.*
   python-multipart==0.0.*
   ```
   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   playwright install chromium
   ```

3. **写 `backend/app/models.py`** — 见 [02-data-model.md](./02-data-model.md)

4. **写 `backend/app/storage.py`** — 路径常量、`mkdir`、静态挂载:
   ```python
   from pathlib import Path
   STORAGE = Path(__file__).parent.parent / "storage"
   UPLOADS = STORAGE / "uploads"
   OUTPUTS = STORAGE / "outputs"
   for p in (UPLOADS, OUTPUTS):
       p.mkdir(parents=True, exist_ok=True)
   ```

5. **复制并改写 `examples/cyberpunk-original/index.html`**
   → `backend/templates/cyberpunk_chat.html.j2`
   按 [04-template.md §4.3](./04-template.md#43-模板骨架) 改造。

6. **写 `backend/app/renderer.py`**:
   - `load_template()` 加载 j2
   - `build_participants(config)` 展平参与者
   - `build_messages(config)` 展平消息、加 `css_class` / `is_self` / `flash`
   - `build_timeline(config)` 生成 TIMELINE 数组
   - `render_template(config) -> str` 返回 HTML 字符串

7. **写 `backend/app/main.py`(最小版)**:
   ```python
   from fastapi import FastAPI
   from fastapi.middleware.cors import CORSMiddleware
   from app.models import ChatConfig
   from app.renderer import render_template

   app = FastAPI()
   app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"])

   @app.post("/api/preview-html")
   def preview_html(config: ChatConfig):
       return {"html": render_template(config)}

   @app.get("/health")
   def health():
       return {"status": "ok"}
   ```

8. **验证**:
   ```bash
   uvicorn app.main:app --reload
   curl -X POST http://localhost:8000/api/preview-html \
     -H 'Content-Type: application/json' \
     -d @examples/minimal.json | jq -r .html > /tmp/preview.html
   # 浏览器打开 /tmp/preview.html 看效果
   ```

---

## 7.3 Day 2 · 录制 + Worker + SSE

**目标**:点 `/api/render` 后能拿到 MP4 下载链接,SSE 实时推进度。

### 步骤

1. **写 `backend/app/recorder.py`**:
   - 异步函数 `render_chat(config, job_id, progress_callback)`
   - 用 `playwright.async_api.async_playwright`
   - 写 HTML → `playwright.chromium.launch()` → 录制 → ffmpeg 转码
   - 录制期间按 500ms 间隔调 `progress_callback(percent)`

2. **写 `backend/app/queue.py`**:
   - `jobs: dict[str, Job]` 内存存储
   - `asyncio.Queue` 任务队列
   - `async def worker(name)` 循环处理任务
   - `@asynccontextmanager async def lifespan(app)` 启动/关闭 worker

3. **扩展 `main.py`**:
   - 引入 lifespan
   - `POST /api/render` → 入队 → 返回 `job_id`
   - `GET /api/jobs/{id}` → 查 jobs 字典
   - `GET /api/jobs/{id}/events` → SSE 端点
   - `POST /api/upload` → 写文件到 `UPLOADS`

4. **验证**:
   ```bash
   # 提交 render
   curl -X POST http://localhost:8000/api/render \
     -H 'Content-Type: application/json' \
     -d @examples/minimal.json
   # → {"job_id": "01HX..."}
   
   # 监听 SSE
   curl -N http://localhost:8000/api/jobs/01HX.../events
   
   # 等待 done,下载
   curl -o out.mp4 http://localhost:8000/outputs/01HX....mp4
   ```

---

## 7.4 Day 3 · 前端表单

**目标**:能编辑配置,看到实时预览。

### 步骤

1. **Vite 脚手架**:
   ```bash
   cd frontend
   npm create vite@latest . -- --template react-ts
   npm install
   ```

2. **`src/types.ts`** — 镜像 Pydantic 模型

3. **`src/api.ts`** — `previewHtml(config)` / `uploadFile(file)` / `render(config)` / `subscribeJobEvents(jobId, onEvent)`

4. **`src/App.tsx`** — 左右两栏布局:
   - 左:HeaderEditor + ParticipantList + MessageList + "生成视频" 按钮
   - 右:PreviewPanel(iframe)

5. **`src/components/HeaderEditor.tsx`**:
   - 模式切换(Single / Group)
   - 标题输入

6. **`src/components/ParticipantList.tsx`**:
   - 参与者列表(增删改)
   - 头像上传(调 `api.uploadFile`)
   - 名字输入

7. **`src/components/MessageList.tsx`**:
   - 消息列表(增删改、上下移)
   - 类型切换(text / image / sys)
   - text / image_url 输入
   - delay_ms 输入(默认 1500)

8. **`src/hooks/useDebounce.ts`** — 通用防抖 hook

9. **`src/components/PreviewPanel.tsx`** — 见 [01-architecture.md §D1](./01-architecture.md#d1--预览与录制共用同一份-html)
   - `<iframe srcDoc={html} />`
   - 防抖 300ms 拉 `previewHtml`

10. **验证**:
    ```bash
    npm run dev
    # 浏览器打开 http://localhost:5173
    # 编辑表单 → 右侧 iframe 应同步
    ```

---

## 7.5 Day 4 · 进度面板 + 联调

**目标**:点"生成视频" → 看到进度 → 下载 MP4。

### 步骤

1. **`src/hooks/useRenderJob.ts`**:
   ```typescript
   export function useRenderJob(jobId: string | null) {
     const [job, setJob] = useState<Job | null>(null);
     useEffect(() => {
       if (!jobId) return;
       const es = new EventSource(`/api/jobs/${jobId}/events`);
       es.addEventListener('progress', e => setJob(JSON.parse(e.data)));
       es.addEventListener('done', e => { setJob(JSON.parse(e.data)); es.close(); });
       es.addEventListener('failed', e => { setJob(JSON.parse(e.data)); es.close(); });
       return () => es.close();
     }, [jobId]);
     return job;
   }
   ```

2. **`src/components/ProgressPanel.tsx`**:
   - 进度条
   - 下载按钮(`<a href={output_url} download>`)
   - 错误提示

3. **`src/App.tsx`** 集成:点"生成视频" → 调 `api.render(config)` → 拿到 `jobId` → 传给 ProgressPanel

4. **联调**:从编辑 → 预览 → 提交 → 下载完整链路跑通

5. **样式打磨**:统一按钮、间距、配色;预览 iframe 居中显示

---

## 7.6 Day 5 · 部署与文档

**目标**:`docker compose up` 一键起;`README.md` 完整。

### 步骤

1. **`deploy/Dockerfile`**(见 [05-deployment.md §5.2](./05-deployment.md#52-dockerfile))

2. **`deploy/docker-compose.yml`**(见 [05-deployment.md §5.3](./05-deployment.md#53-docker-composeyml))

3. **`deploy/nginx.conf`**(见 [05-deployment.md §5.4](./05-deployment.md#54-nginx-配置前端代理到后端))

4. **`README.md`**:
   - 项目简介
   - 截图
   - 快速开始(docker-compose 一条命令)
   - 开发模式(前后端分别启动)
   - 配置说明
   - 常见问题

5. **`.gitignore`**:
   ```
   __pycache__/
   *.pyc
   .venv/
   storage/
   node_modules/
   dist/
   .env
   *.mp4
   *.webm
   ```

6. **端到端验收**:跑 [06-acceptance.md](./06-acceptance.md) 的所有 E2E 用例

7. **修小问题**:
   - 时长偏差微调
   - 字体一致性
   - 错误提示文案

---

## 7.7 风险与备选

### 风险 1 · Chromium 启动慢

**现象**:首屏拉起需 3-5s。

**缓解**:
- Worker 常驻,Chromium 启动后不退出
- 加 `/health` 端点,k8s/Docker 用作 readiness probe

### 风险 2 · iframe srcDoc 体积

**现象**:消息很多时 HTML > 1MB,iframe 渲染慢。

**缓解**:
- 限制消息 ≤ 100 条(前端校验)
- 单消息文本 ≤ 500 字符

### 风险 3 · Docker 镜像大

**现象**:镜像 ~550MB,部署慢。

**缓解**:
- 接受现状(单镜像,部署频率不高)
- 后期可用多阶段构建瘦身

### 风险 4 · 多用户并发抢资源

**现象**:CPU 100% 时长剧增。

**缓解**:
- `WORKER_COUNT` 限制并发
- 队列上限保护(`/api/render` 返回 503)
- 监控 + 告警

---

## 7.8 里程碑检查点

| 时间 | 可演示成果 |
|---|---|
| Day 1 末 | `curl preview-html` 能拿到合法 HTML,浏览器打开能看到效果 |
| Day 2 末 | `curl render` 能拿到 MP4 下载链接 |
| Day 3 末 | 浏览器表单编辑,iframe 实时预览 |
| Day 4 末 | 端到端跑通(编辑 → 预览 → 提交 → 下载) |
| Day 5 末 | `docker compose up` 启动,文档齐全 |

每个里程碑都可以独立停下来,跟用户/产品方确认方向。

---

## 7.9 不在本期的事

明确告知"不在范围",避免范围蔓延:

- ❌ 用户系统、登录、注册
- ❌ 配额、计费、付费
- ❌ 多种 UI 风格(iMessage / WhatsApp / Telegram)
- ❌ 视频后期(字幕、配乐、特效)
- ❌ 历史记录浏览界面(MP4 留在磁盘,URL 自己拿)
- ❌ 国际化(英文 UI)
- ❌ 多租户隔离
- ❌ 移动端适配(响应式布局仅做基础)

如需追加,放到下一版本,接口层基本不用改。