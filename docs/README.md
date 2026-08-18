# 微信聊天视频生成器 — 设计文档

本目录收录"微信聊天视频生成器"项目的全部设计文档。
该项目基于同仓库的 `html-to-mp4` 录制框架,
允许用户在网页表单里配置微信聊天(头像、文字、单聊/群聊、图片消息),
实时预览动画效果,再由服务端 Playwright + ffmpeg 录制成 MP4 下载。

## 文档索引

| 编号 | 文件 | 内容 |
|---|---|---|
| 01 | [architecture.md](./01-architecture.md) | 总体架构、技术选型、目录结构 |
| 02 | [data-model.md](./02-data-model.md) | Pydantic 数据模型、字段说明、示例 |
| 03 | [api.md](./03-api.md) | REST 接口规范(请求/响应/SSE) |
| 04 | [template.md](./04-template.md) | Jinja2 微信模板的渲染规则、CSS 约定 |
| 05 | [deployment.md](./05-deployment.md) | Docker 镜像、字体、并发、调优 |
| 06 | [acceptance.md](./06-acceptance.md) | 验收标准、测试用例 |
| 07 | [implementation-steps.md](./07-implementation-steps.md) | 分步实施计划与工时估算 |

## 快速总览

- **目标用户**:想做"微信群聊短视频"的内容创作者 / 营销人员
- **核心能力**:表单配置 → iframe 实时预览 → 一键生成 1080×1920 MP4
- **技术栈**:FastAPI + Jinja2 + Playwright(Python) + React + Vite + Docker
- **录制原理**:沿用 `examples/05-chat-wechat-style/record.mjs` 的 Playwright + ffmpeg 流水线
- **当前范围**:固定 1 套微信风格模板、单聊/群聊、文/图/系统消息、十几个并发

## 不在范围

- 用户系统、登录、配额计费
- 多种 UI 风格(iMessage / WhatsApp 等)
- 视频后期(字幕、配乐、转场)
- 历史记录持久化界面
- 横向扩展到 50+ 并发

## 与 `html-to-mp4` 主仓库的关系

本项目**复用**主仓库的录制范式:
- `examples/05-chat-wechat-style/index.html` → 改造成 Jinja2 模板
- `record.mjs` 流水线 → 改写成 Python 异步版本(`recorder.py`)
- 字体规范、视口约定、CJK 处理方式 → 直接沿用

不修改主仓库代码,本项目是独立的应用项目。