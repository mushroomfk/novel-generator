# 稿匣

`稿匣` 是面向长篇小说创作的本地桌面工作台。它把作品文件夹、章节正文、设定资料、知识检索、模型生成、改稿技能和桌面打包流程放在同一个应用里，适合需要长期维护世界观、人物线和章节上下文的个人作者。

应用由 `Tauri 2 + Vue 3 + FastAPI` 组成：前端负责写作工作台，本地 Python backend 负责项目文件、资料索引、模型调用和技能流程，桌面壳负责拉起 sidecar 并回收进程。项目数据默认保存在本地，模型调用走 OpenAI-compatible 云模型配置。

更新记录见 [CHANGELOG.md](./CHANGELOG.md)。

## 适合谁

- 正在写长篇、连载或系列作品，需要管理章节、设定、资料和版本
- 希望把模型生成放进可审阅的写作流程，而不是只拿一次性聊天结果
- 想在本地保存作品资料，不把模型 API Key 和项目数据交给在线平台托管
- 想二次开发一个桌面写作工具，前端、backend、Tauri 壳层都能本地运行

## 功能概览

- 作品管理：创建、重命名、删除作品，打开本地作品目录
- 章节工作台：编辑章节正文、自动保存、本地版本管理、章节概览提取
- 架构生成：通过 OpenAI-compatible `chat/completions` 生成故事架构，并写入设定文件
- 资料库：导入 `txt / md / json / csv / html / docx / pdf`，建立 `knowledge.db` 索引
- 知识检索：按来源增量刷新索引，支持项目资料库、作者参考库和国内联网考据
- 写作技能：人物复刻、去 AI、文风参考、提示词预设、XP 预设、文件浏览
- Agent 执行：统一处理讨论、资料分析、章节写作和整书架构，保留执行轨迹并产出需确认的经验候选
- 桌面运行：Tauri 启动时拉起本地 backend，并把实际 backend 地址下发给前端
- 发布回归：提供浏览器 smoke、backend 单测、桌面打包检查和 macOS 测试包整理脚本

## 项目状态

- 前端工作台、Python backend 和 Tauri 桌面壳都已可运行
- macOS arm64 调试包和测试分发流程已跑通
- 后端单测覆盖核心项目服务、生成服务、资料导入、许可证、技能流程和记忆系统
- 浏览器层 UI smoke 可走完建作品、写章节、Agent 计划执行、整书架构、技能检索等主链路
- 当前是公开预览版，正式分发仍需要补充签名、公证、安装包渠道和版本升级策略

## 许可

本项目使用自定义许可，不是 MIT、Apache-2.0 或 GPL。允许个人复制、学习和引用项目内容；引用代码、文档或界面说明时，需要注明项目名称和来源链接。未经授权，不得商用、改名发布或打包分发。第三方依赖仍按各自许可证执行。

完整条款见 [LICENSE](./LICENSE)。

## 技术栈

- 桌面壳：`Tauri 2`
- 前端：`Vue 3`、`Vite`
- backend：`FastAPI`、`Uvicorn`、`Python 3.12`
- 本地索引：`SQLite / FTS5`
- 模型接口：OpenAI-compatible chat、embedding、rerank
- 回归：`unittest`、`vue-tsc`、`vite build`、浏览器 smoke、桌面发布脚本

## 目录

```text
.
├── backend/       # Python sidecar 服务源码
├── docs/          # 架构、技能、回归和桌面发布说明
├── scripts/       # 本地构建、回归和打包脚本
├── src/           # Vue 前端
├── src-tauri/     # Tauri 壳层
└── CHANGELOG.md
```

## 环境要求

- `Node.js 20+`
- `npm 10+`
- `Python 3.12`
- macOS 下建议安装 Xcode Command Line Tools，供 `codesign`、`xattr` 等命令使用

## 安装依赖

安装前端依赖：

```bash
npm run deps:install
```

创建虚拟环境并安装 backend 依赖：

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e backend
```

## 本地运行

启动 backend：

```bash
npm run backend:dev
```

启动前端：

```bash
npm run dev
```

也可以同时启动：

```bash
npm run dev:all
```

默认端口：

- 前端：`http://127.0.0.1:1420`
- backend：`http://127.0.0.1:18181`
- 健康检查：`http://127.0.0.1:18181/api/app/health`

浏览器预览模式下，前端默认连接 `http://127.0.0.1:18181`。可通过 `.env` 或环境变量覆盖 `VITE_NOVEL_BACKEND_URL`。Tauri 模式下，客户端会在启动时拉起 backend，并把实际地址下发给前端，不需要手动固定端口。

## 配置

复制 `.env.example` 后按需填写：

```bash
cp .env.example .env
```

模型调用默认走 OpenAI-compatible `chat/completions`。`API Key` 可直接保存在设置里，也可以通过环境变量提供：

- `NOVEL_MODEL_API_KEY`
- `NOVEL_API_KEY`
- `DASHSCOPE_API_KEY`
- `ARK_API_KEY`
- `OPENAI_API_KEY`

Embedding 检索默认走 OpenAI-compatible `/embeddings`，可在设置里单独配置，也可以使用：

- `NOVEL_EMBEDDING_API_KEY`
- `DASHSCOPE_API_KEY`
- `ARK_API_KEY`
- `NOVEL_API_KEY`
- `OPENAI_API_KEY`

联网考据用于查询历史典故、史实出处和可借鉴的写作素材，搜索源使用博查 Web Search API，整理报告仍走当前设置里的写作模型：

- `BOCHA_API_KEY`
- `BOCHA_SEARCH_ENDPOINT`，可选，默认 `https://api.bochaai.com/v1/web-search`

## 验证和构建

常用命令：

```bash
npm run build
npm run backend:test
npm run verify
npm run verify:ui
```

backend 可单独启动为本地服务：

```bash
npm run backend:serve
```

需要为 Tauri 发布版准备 sidecar 时：

```bash
npm run backend:bundle
```

桌面版发布前建议执行：

```bash
npm run verify:desktop
```

完整交付回归可执行：

```bash
npm run verify:release
```

整理 macOS 测试包：

```bash
npm run package:test:macos
```

如果要从回归到打包一次完成：

```bash
npm run release:test:macos
```

## 文档

- [文档索引](./docs/README.md)
- [界面回归说明](./docs/界面回归说明.md)
- [桌面发布回归说明](./docs/桌面发布回归说明.md)
- [人物复刻技能说明](./docs/人物复刻技能说明.md)
- [去 AI 技能说明](./docs/去AI技能说明.md)
- [macOS 测试版安装说明](./docs/macOS测试版安装说明.md)

## 参与

欢迎提交 issue 或 pull request。提交前请阅读 [CONTRIBUTING.md](./CONTRIBUTING.md)。安全问题请按 [SECURITY.md](./SECURITY.md) 说明处理。
