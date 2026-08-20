# 对话剧场 / Dialogue Theater — 设计文档

本目录收录"对话剧场"项目的全部设计文档。
该项目基于同仓库的 `html-to-mp4` 录制框架，
允许用户在网页表单里配置原创风格的对话场景（角色、文字、对谈/群像、图片消息、幕间字幕），
实时预览动画效果，再由服务端 Playwright + ffmpeg 录制成 MP4 下载。

> **产品定位**：对话叙事创作工具，而非任何真实社交平台的仿冒界面生成器。
> 当前默认视觉风格为"赛博朋克"，后续可扩展更多原创艺术风格。

## 文档索引

| 编号 | 文件 | 内容 |
|---|---|---|
| 01 | [architecture.md](./01-architecture.md) | 总体架构、技术选型、目录结构 |
| 02 | [data-model.md](./02-data-model.md) | Pydantic 数据模型、字段说明、示例 |
| 03 | [api.md](./03-api.md) | REST 接口规范（请求/响应/SSE） |
| 04 | [template.md](./04-template.md) | Jinja2 原创模板的渲染规则、CSS 约定 |
| 05 | [deployment.md](./05-deployment.md) | Docker 镜像、字体、并发、调优 |
| 06 | [acceptance.md](./06-acceptance.md) | 验收标准、测试用例 |
| 07 | [implementation-steps.md](./07-implementation-steps.md) | 分步实施计划与工时估算 |
| 08 | [import-package.md](./08-import-package.md) | 压缩包导入功能设计（zip 结构 / 安全防护 / API / 前端 UX） |

## 快速总览

- **目标用户**：短视频剧情创作者、小说可视化作者、教学演示制作者、梗图/表情包创作者
- **核心能力**：表单配置 → iframe 实时预览 → 一键生成 1080×1920 MP4
- **技术栈**：FastAPI + Jinja2 + Playwright(Python) + React + Vite + Docker
- **录制原理**：沿用 `html-to-mp4` 录制框架的 Playwright + ffmpeg 流水线
- **当前范围**：固定 1 套原创"赛博朋克"模板、对谈/群像、文/图/系统消息、十几个并发

## 不在范围

- 用户系统、登录、配额计费
- 真实社交平台风格（微信/WhatsApp 等）的仿冒界面
- 视频后期（字幕、配乐、转场）
- 历史记录持久化界面
- 横向扩展到 50+ 并发

## 合规底线

- 生成内容必须带有不可关闭的 AI 生成标识（右下角角标 + 片头 1 秒声明卡）
- 创建项目时必须选择创作意图并勾选合规承诺
- 系统自动拦截高敏感词（转账、红包、密码、验证码等）与真实社交平台名称
