# 更新记录

这份文档统一记录 `稿匣` 已落地的产品变更。

历史上已经做完、但没有单独留日期的内容，不补编日期，先按“基线能力”归档；后续新改动按日期继续追加。

## 基线能力（日期未补录）

这部分能力在建立本记录前已经存在：

- 本地小说工作台界面、作品创建和章节编辑
- 架构文件在线编辑、知识检索和资料导入
- 本地版本管理、自动保存和架构总览
- 技能库、提示词预设、XP 预设、文件浏览
- 人物复刻、去 AI、文风参考等技能
- 模型配置、许可证导入校验、整本导出
- Tauri 桌面壳、sidecar backend、浏览器层 smoke 和桌面发布回归

## 2026-04-16

### 小说文件夹管理

- 左侧“小说文件夹”新增 `⋯` 管理菜单
- 支持直接打开作品目录
- 支持重命名作品，并同步更新作品名、本地目录名、`project.json` 和 `projects/index.json`
- 支持删除作品，并同步移除本地目录和项目索引
- 重命名后会同步更新本地历史 watcher 的监听目录，避免版本管理失联
- 修正章节抽屉展开后的左栏挤压问题，作品名不再被压成竖排，`⋯` 菜单也不再被裁掉
- 调整作品卡片密度，标题保持单行省略，按钮和上下留白更紧凑
- 修正作品列表被容器纵向拉伸的问题，未展开时的项目间距恢复正常，不再浪费大段空白
- 左上品牌区改成横排紧凑头部，进一步压缩左栏顶部占用；作品列表行距继续收紧，减少项目名之间的空白
- 左上说明文字缩小，并与“稿匣”放到同一行，继续压缩左栏头部空间
- 左上说明文案改成更短的“小说工作台”，取消省略号显示

### 回归补充

- `backend/tests/test_project_service.py` 新增项目重命名、删除、打开目录回归
- `scripts/verify-ui-smoke.mjs` 新增作品重命名、删除的浏览器层 smoke
- `界面回归说明.md`、`测试反馈清单.md`、`README.md` 已同步更新

### 本次验证

- `npm run backend:test`
- `npm run build`
- `npm run verify:ui`

## 2026-04-30

### 知识索引性能

- 修改摘要：项目知识库新增 `source_key` 级别的增量刷新，保存章节、保存设定文件、导入资料时只更新变化来源；向量从 JSON 文本解析改为二进制列读取，并保留旧数据迁移。
- 影响范围：`backend/novel_backend/services/project_service.py`、`backend/novel_backend/services/file_service.py`、项目本地 `knowledge.db` 的 `knowledge_sources`、`knowledge_chunks`、`knowledge_vectors` 表结构。
- 详情读取：`get_project_detail` 不再在读取路径持久化新生成的蒸馏报告，自动记忆刷新等写入动作会负责保存需要复用的派生结果。
- 验证结果：临时样本 80 章、60 份资料、1680 个 chunk 下，2048 维模拟向量的混合检索平均约 8.9ms，单章索引刷新平均约 11.4ms；`npm run backend:test` 通过，102 个用例通过。

## 2026-05-01

### GitHub 发布前隐私清理

- 修改摘要：补充本地环境、Agent 本机配置、证书、数据库、作品数据和 sidecar 二进制的忽略规则；移除 Tauri 元数据里的个人标识；把回归文档里的本机绝对路径改为相对路径；移除发布文档、README、prompt 和测试中的外部仓库显式引用。
- 权限声明：新增自定义 `LICENSE`，并在 `README.md` 写明本项目允许个人复制、学习和引用，但引用时必须注明项目名称和来源链接；未经授权不得商用、改名发布或打包分发。
- 影响范围：仓库发布内容、Tauri 应用标识、README 使用权限说明、回归说明文档链接、去 AI 技能说明和相关 prompt 文案。
- 验证结果：隐私和密钥特征扫描未发现本机路径、个人标识或常见密钥格式；`npm run backend:test` 通过，102 个用例通过；`npm run build` 通过；`npm run tauri -- info` 可读取项目配置，本机提示未安装完整 Xcode。

### GitHub 首页说明优化

- 修改摘要：重写 `README.md` 首屏项目介绍，把内部进度列表改为面向访问者的项目定位、适用人群、功能范围、项目状态、技术栈和验证命令。
- 影响范围：GitHub 仓库首页展示和仓库一行描述，不改变运行代码、接口、配置或数据结构。
- 验证结果：执行 `git diff --check` 通过；隐私和外部仓库显式引用扫描未发现新增风险。本次仅改文档和 GitHub 仓库描述，未重新跑单测。

## 2026-05-02

### 国内联网考据

- 修改摘要：技能库新增“联网考据”，用于查询历史典故、史实出处和小说写作借鉴；联网搜索源使用国内博查 Web Search API，报告整理继续使用当前项目配置的写作模型。
- 影响范围：新增 `/api/projects/{project_id}/research/historical` 接口、联网考据后端服务、技能库入口、结果展示、来源列表和“存入资料库”流程；新增 `BOCHA_API_KEY` 和可选 `BOCHA_SEARCH_ENDPOINT` 配置说明。
- 验证结果：`npm run backend:test -- --failfast` 通过，108 个用例通过；`npm run build` 通过。

### 模型错误提示核查

- 修改摘要：模型错误分类补充无 HTTP 状态码的 `invalid model` 场景，避免模型名错误被归为普通请求格式错误。
- 影响范围：模型调用失败提示、Prompt 历史里的结构化错误字段、相关模型错误分类测试。
- 验证结果：`npm run backend:test -- --failfast` 通过，108 个用例通过；`python3 -m py_compile` 和 `git diff --check` 通过。

### AI 生成 Agent 交付回归

- 修改摘要：资料检索重排序改用阿里百炼 `qwen3-rerank` 官方 OpenAI 兼容端点 `/compatible-api/v1/reranks`；设置页阿里预设和空表单默认模型统一为 `qwen3.6-plus`，与 backend 默认配置一致。
- 桌面图标：用 `src/assets/gaoxia-mark.svg` 重新生成 Tauri 桌面图标集，确保 `.app`、`.dmg` 和 Windows 图标资源使用当前品牌图标。
- 影响范围：知识库混合检索的 rerank 请求地址、模型设置页默认预设、桌面打包图标、相关后端回归用例、`README.md` 和《核心引擎说明》的接口说明。
- 验证结果：`npm run verify:release` 通过，包含浏览器 smoke、103 个 backend 单测、前端生产构建、Python sidecar 打包、sidecar 独立健康检查、Tauri debug `.app` / `.dmg` 构建、签名修复校验和应用内 sidecar 健康检查；图标更新后再次执行 `npm run verify:desktop` 通过。

### 轻量自学习与上下文预算

- 修改摘要：Agent 执行完成后记录结构化轨迹，并把讨论结论、资料分析结果和可复用技能建议整理成 `经验候选` 产物；生成链路增加上下文预算报告和超长章节正文压缩；模型调用失败会写入结构化错误类型。
- 影响范围：新增 `logs/agent_trajectories.jsonl`、项目目录 `.gaoxia/learning/reviews.jsonl`、`GET /api/studio/agent-trajectories`、`learning_review` 产物展示、`ProjectContextBundle.budget_report`、prompt history 错误分类字段，以及对应后端回归用例。
- 验证结果：`npm run verify` 通过，包含 108 个后端用例和前端生产构建；`npm run verify:ui` 通过，覆盖 Agent 章节计划、混合命令、整书架构、讨论结果、提示词方案、XP 预设、文件浏览和人物复刻。

## 2026-05-03

### 对话发送输入框状态

- 修改摘要：Agent 对话消息发送成功后，输入框会立即清空，不再等执行结果返回；已选择的参考资料仍会随本次请求传给 backend。
- 影响范围：工作台对话输入框交互、参考资料随消息发送的前端状态、浏览器 smoke 回归检查。
- 验证结果：`npm run build` 通过；`npm run verify:ui` 通过，包含新增的发送后输入框清空检查。

### 工作区核查修正

- 修改摘要：联网考据服务兼容博查根级 `webPages.value` 返回结构；未拿到有效联网结果时不允许把失败提示保存进项目资料库；`.env.example` 补充可选的 `BOCHA_SEARCH_ENDPOINT`；浏览器 smoke 覆盖未配置 Key 时的提示和禁用保存状态。
- 影响范围：联网考据解析、技能库“存入资料库”按钮状态、环境变量示例、界面回归脚本。
- 验证结果：`npm run backend:test -- --failfast` 通过，108 个用例通过；`npm run build` 通过；`npm run verify:ui` 通过，包含联网考据未配置 Key 回归；`npm run verify:desktop` 通过。

### Agent 指定章节写回

- 修改摘要：用户在当前章节界面明确要求生成其他章节时，后端会优先使用用户原话里的章节号，不再被模型计划里的 `selected` 覆盖；执行指令也保留用户原话，避免目标章节正确但写作要求仍指向当前章节；当原话里先提参考章节、后提生成章节时，章节生成会优先使用“生成/写/续写”对应的章节号。
- 影响范围：Agent 计划解析、章节生成 action 的 `chapter_id` 和执行指令、浏览器 smoke 中“当前第一章生成第二章”的回归。
- 验证结果：`npm run backend:test -- --failfast` 通过，110 个用例通过；`npm run verify:ui` 通过，覆盖当前第一章界面生成第二章并写回 `chapter-002`。

## 2026-05-04

### GitHub 公开版整理

- 修改摘要：根目录保留公开入口文件，专项说明移动到 `docs/`；`更新记录.md` 改为 `CHANGELOG.md`；新增文档索引、贡献说明、安全说明和 issue 配置；README 改成公开访问者可直接使用的项目介绍。
- 影响范围：GitHub 首页展示、文档路径、环境变量示例、npm 包元数据、忽略规则和公开协作说明。
- 验证结果：`git diff --check` 通过；Markdown 本地链接检查通过，覆盖 16 个文档文件；当前文件和 `origin/main` 可见历史的敏感信息扫描未发现本机路径、个人标识或常见密钥格式；`npm run verify` 通过，包含 110 个 backend 用例和前端生产构建。
