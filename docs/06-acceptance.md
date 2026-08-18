# 06 · 验收标准

## 6.1 端到端核心场景

### E2E-1 · 群聊 5 条消息生成

**前置**:浏览器打开 `http://localhost:8080`,页面为空配置(无 demo 数据)

**步骤**:
1. 上传 3 张头像(尺寸任意,≤ 2MB)
2. 添加 3 个参与者:我 / 小美 / 阿强,各绑定头像
3. 添加 5 条消息:
   - 小美发图片:`assets/plum.jpg` + 文案"周末去爬山吗"
   - 阿强发文本:"可以,我周六有空"
   - 小美发文本:"那就周六早上见"
   - 我发文本:"好的,我来定集合地点"
   - 系统消息:"小美已将群名改为「周末活动群」"
4. 在右侧 iframe 中**实时看到**上述内容按时间顺序出现
5. 点"生成视频"按钮
6. 等待进度条到 100%
7. 出现"下载 MP4"按钮

**验收**:
- [ ] 预览与最终视频一致(无内容差异)
- [ ] 视频时长与 `duration_ms` 一致
- [ ] 中文显示正常,无方块字
- [ ] 头像清晰,图片消息显示
- [ ] 系统消息居中显示,带红色脉冲
- [ ] MP4 用播放器打开流畅

### E2E-2 · 单聊自己右侧

**步骤**:
1. 添加 2 个参与者:`id="me", name="我"` 和 `id="her", name="她"`
2. 消息列表:自己发"在吗",她回"嗯",自己发"周末吃饭?"
3. 预览确认

**验收**:
- [ ] "我" 的消息在右侧,绿色背景,文字深色
- [ ] "她" 的消息在左侧,白色背景
- [ ] "我" 的消息不显示发送者名字

### E2E-3 · 图片消息

**步骤**:
1. 上传一张 ≥ 100KB 的图片
2. 添加一条图片消息,带图注

**验收**:
- [ ] 气泡内图片完整显示,等比例
- [ ] 图注文字在图片下方

### E2E-4 · 上传校验

**步骤**:
1. 尝试上传 3MB 文件
2. 尝试上传 `.exe` 文件

**验收**:
- [ ] 3MB 返回 413 或前端阻止
- [ ] `.exe` 返回 400,前端提示

## 6.2 性能与稳定性

### PERF-1 · 录制时长准确性

**验收**:
- 5 条消息,每条 `delay_ms=1500`,总 `duration_ms = 1200 + 5*1500 + 1500 = 10200`
- 录制的 MP4 时长与 `duration_ms` 偏差 < 500ms

### PERF-2 · 2 worker 并发

**步骤**:
1. 同时提交 4 个 render 任务
2. 前 2 个并行,后 2 个排队

**验收**:
- [ ] 任务状态正确:`queued` → `running` → `done`
- [ ] 所有任务最终 `done`,MP4 可下载
- [ ] SSE 进度推送流畅(每 500ms 一次)

### PERF-3 · 失败恢复

**步骤**:
1. 故意传入 `duration_ms=-1`(非法值)
2. 提交 render

**验收**:
- [ ] 接口返回 422
- [ ] 前端表单红字提示

### PERF-4 · 字体一致性

**验收**:
- [ ] 在 macOS Chrome 预览,中文显示正常(用 PingFang)
- [ ] Docker 内录制出来的视频,中文显示正常(用 Noto CJK)
- [ ] 两者肉眼接近

## 6.3 UI 验收

### UI-1 · 实时预览同步

**步骤**:
- 编辑群名 → iframe 顶部 300ms 内更新
- 增删消息 → iframe 同步
- 修改头像 URL → iframe 重新拉取图片

**验收**:
- [ ] 编辑 → 预览同步延迟 ≤ 500ms
- [ ] 不会因为频繁编辑卡顿(防抖生效)

### UI-2 · 任务进度

**验收**:
- [ ] 提交后立即看到"录制中..."状态
- [ ] 进度条平滑推进到 100%
- [ ] 完成后 5s 内自动出现下载按钮

### UI-3 · 响应式布局

**验收**:
- [ ] 1280×800 浏览器视口下,左表单 / 右预览合理布局
- [ ] 移动端视口(iPad)可用(可选优化)

## 6.4 代码质量

### CODE-1 · 后端

- [ ] `models.py` 100% 类型注解
- [ ] `recorder.py` 录制失败时清理 webm 临时文件
- [ ] `queue.py` worker 异常不导致整个进程退出
- [ ] 日志清晰,带 `job_id`
- [ ] 没有未捕获的 `except:`

### CODE-2 · 前端

- [ ] 关键组件有 PropTypes/TS 类型
- [ ] `api.ts` 集中管理所有 HTTP 调用
- [ ] 无 `any` 类型滥用
- [ ] 没有 console.log 残留(开发模式除外)

### CODE-3 · 测试

- [ ] `backend/tests/test_renderer.py` 至少 6 个用例(见 [04-template.md §4.10](./04-template.md#410-模板测试))
- [ ] 关键 API 有手动 curl 测试用例(见下文)

## 6.5 手动 curl 测试

```bash
# 1. 健康检查
curl http://localhost:8000/health

# 2. 上传
curl -F file=@avatar.png -F kind=avatar http://localhost:8000/api/upload
# → {"url":"/uploads/xxx.png","kind":"avatar"}

# 3. 预览
curl -X POST http://localhost:8000/api/preview-html \
  -H 'Content-Type: application/json' \
  -d @examples/minimal.json | jq -r .html | head -50

# 4. 提交 render
curl -X POST http://localhost:8000/api/render \
  -H 'Content-Type: application/json' \
  -d @examples/minimal.json
# → {"job_id":"..."}

# 5. 查询
curl http://localhost:8000/api/jobs/<job_id>

# 6. 下载
curl -o result.mp4 http://localhost:8000/outputs/<job_id>.mp4
```

## 6.6 部署验收

### DEPLOY-1 · docker-compose up

```bash
docker compose up -d
curl http://localhost:8000/health  # → {"status":"ok"}
```

**验收**:
- [ ] 容器启动 < 30s(含首次 Chromium 预热)
- [ ] 健康检查通过
- [ ] `storage/` 挂载正常,文件持久化

### DEPLOY-2 · 字体就绪

```bash
docker exec wechat-video-gen fc-list :lang=zh | head
```

**验收**:
- [ ] 输出包含 `Noto Sans CJK SC`

### DEPLOY-3 · ffmpeg 可用

```bash
docker exec wechat-video-gen ffmpeg -version | head -1
```

**验收**:
- [ ] 输出 ffmpeg 版本号

## 6.7 验收清单(汇总)

- [ ] 浏览器打开 `/`,看到表单 + 右侧预览(空配置时显示占位提示,无 demo 数据)
- [ ] 上传头像、编辑消息,iframe 实时同步
- [ ] 单聊模式"自己"消息在右侧
- [ ] 群聊模式所有消息在左侧(默认)
- [ ] 图片消息正确显示
- [ ] 系统消息显示并带 flash
- [ ] 点"生成视频" → 30s 内拿到 MP4
- [ ] MP4 文字清晰、CJK 字体一致
- [ ] MP4 时长准确
- [ ] `docker compose up` 一条命令起服务
- [ ] 后端单元测试全绿
- [ ] `storage/` 数据持久化
- [ ] 错误任务有清晰错误提示