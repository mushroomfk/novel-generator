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

### GitHub README 展示优化

- 修改摘要：重写 README 首屏和主体结构，新增状态 badges、项目价值点、适用场景、功能表、架构图、快速开始、常用命令表和路线图，让访问者能更快判断项目定位和关注价值。
- 影响范围：GitHub 仓库首页展示，不改变运行代码、接口、配置或数据结构。
- 验证结果：`git diff --check` 通过；Markdown 本地链接检查通过，覆盖 16 个文档文件；当前文件敏感信息扫描未发现本机路径、个人标识或常见密钥格式。本次仅改文档，未重新跑单测。

### 联网考据改用阿里百炼优先

- 修改摘要：联网考据优先调用阿里百炼联网搜索，`qwen3.6` / `qwen3.5` 系列走 Responses API `web_search` 和 `web_extractor`，其他阿里百炼模型走 Chat Completions `enable_search`；博查 Web Search 保留为备用搜索源。
- 影响范围：联网考据后端服务、未配置 Key 提示、技能库结果来源显示、环境变量说明、README 和技能/核心引擎文档；已配置阿里百炼写作模型时可复用模型 Key，也可使用 `DASHSCOPE_API_KEY`。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/web_research_service.py backend/tests/test_web_research_service.py` 通过；`.venv/bin/python -m unittest backend.tests.test_web_research_service -v` 通过，4 个用例通过；`npm run backend:test -- --failfast` 通过，112 个用例通过；`npm run build` 通过；`git diff --check` 通过。

### README 截图和技术方案补充

- 修改摘要：README 新增桌面截图、使用流程、相对常见 AI 写作工具的优势对比和技术方案说明；新增演示截图生成脚本和三张虚构项目截图。
- 影响范围：GitHub 仓库首页展示、`docs/assets/` 演示图片、`npm run docs:screenshots` 文档截图命令，不改变运行接口、配置格式或用户数据结构。
- 验证结果：`npm run docs:screenshots` 通过，生成的截图来自临时演示项目和本地模拟模型；`git diff --check` 通过；Markdown 本地链接检查通过；当前文件敏感信息扫描未发现本机路径、个人标识或常见密钥格式。本次没有重新执行完整单测。

### 章节写回核验反馈

- 修改摘要：Agent 章节生成、章节草稿写回、章节改写和批量生成都会把章节核验结果带回执行反馈；核验成功时返回分数、状态和摘要，核验失败时明确显示失败原因，并保留重新运行章节核验的建议。
- 影响范围：Agent 执行结果 `reply / changes / artifacts.metadata`、批量生成单章结果字段、章节写回后的核验状态摘要，不改变章节正文保存规则。
- 验证结果：`.venv/bin/python -m unittest -v backend.tests.test_agent_service backend.tests.test_studio_service backend.tests.test_project_service` 通过，63 个用例通过；`npm run backend:test` 通过，113 个用例通过。

### 章节核验自动修订

- 修改摘要：章节写回后若核验状态为 `risk` 或总分低于 65，系统会按核验报告自动修订一轮，重新写回正文并再次核验；核验失败时不会自动修订，避免没有问题清单时改偏正文。
- 影响范围：新增章节自动修订服务；Agent 章节生成、章节草稿写回、章节改写和批量生成会返回自动修订尝试状态、写入状态、修订摘要和复查结果；批量生成单章结果新增自动修订字段。
- 验证结果：`.venv/bin/python -m unittest -v backend.tests.test_agent_service backend.tests.test_studio_service backend.tests.test_project_service` 通过，66 个用例通过；`npm run backend:test` 通过，117 个用例通过；`npm run build` 通过；`git diff --check` 通过。

### 章节自动修订配置

- 修改摘要：AI 写作设置新增章节核验自动修订配置，可关闭自动修订、调整触发分数，并把最多修订轮数设置为 0 到 3；自动修订服务按配置多轮执行，每轮修订后重新核验，达标后停止。
- 影响范围：应用配置 `chapter_auto_repair`、设置页、Agent 执行反馈、批量生成结果字段、章节自动修订服务和配置回归用例。
- 验证结果：`.venv/bin/python -m unittest -v backend.tests.test_config_service backend.tests.test_agent_service backend.tests.test_studio_service` 通过，40 个用例通过；`npm run backend:test` 通过，119 个用例通过；`npm run build` 通过；`npm run verify:ui` 通过；`git diff --check` 通过。

### 架构总览人物识别修正

- 修改摘要：故事总览里自动发现新人物时，不再只按“中文姓氏 + 出现次数”判断；新增人物语境证据检查，并在打开架构总览时通过模型复核候选人物，模型只能在候选词里选择人物和非人物。`石虎称` 会归并为 `石虎`，`方式`、`封王`、`国北方`、`王境` 等短语不会进入人物列表。
- 影响范围：`StoryOverview` 后端构建逻辑、`GET /api/projects/{project_id}?review_characters=true`、架构总览打开动作、人物列表和关联人物统计；新增项目内缓存 `.gaoxia/story_overview_character_review.json`，不改变项目文件正文、用户配置或普通项目详情读取路径的模型调用行为。
- 验证结果：`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_service.ProjectServiceTestCase.test_story_overview_uses_model_review_and_cache_for_ambiguous_character_candidates backend.tests.test_project_service.ProjectServiceTestCase.test_story_overview_filters_historical_phrases_from_character_names backend.tests.test_generation_service.GenerationServiceTestCase.test_chapter_workflow_draft_uses_single_partial_continuation` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_service` 通过，34 个用例通过；`PYTHONPATH=backend python3 -m unittest discover backend/tests` 通过，117 个用例通过；`npm run build` 通过；`npm run verify:ui` 通过，包含架构总览打开回归。

### 架构总览世界要素模型复核

- 修改摘要：架构总览打开时不再只让模型复核人物，也会把事件、地点、组织/势力、道具和技能候选连同证据句交给模型判断；模型只能在本地候选词里确认或剔除，结果写入 `.gaoxia/story_overview_entity_review.json`。章节标题保留在场景里，纯环境描写不再进入事件。普通项目详情读取仍不主动调用模型，未配置模型时继续使用本地规则结果。
- 影响范围：`StoryOverview` 后端构建逻辑、架构总览的事件、地点、组织/势力、道具、技能列表和人物时间线关联项；不改变项目正文、资料库、接口返回结构或用户配置格式。
- 验证结果：`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_service.ProjectServiceTestCase.test_story_overview_keeps_scene_title_out_of_chapter_events backend.tests.test_project_service.ProjectServiceTestCase.test_story_overview_filters_research_material_noise_when_architecture_has_characters backend.tests.test_project_service.ProjectServiceTestCase.test_story_overview_uses_model_review_for_world_entity_candidates backend.tests.test_project_service.ProjectServiceTestCase.test_story_overview_uses_model_review_and_cache_for_ambiguous_character_candidates` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_service` 通过，37 个用例通过，过程里仍有既有 `ResourceWarning` 输出；`PYTHONPATH=backend python3 -m unittest discover backend/tests` 通过，139 个用例通过，过程里仍有既有 `ResourceWarning` 输出；`npm run build` 通过；`npm run verify:ui` 通过，包含架构总览检查；实际作品《邺天录》抽取结果已核查，人物 16 个，事件仅 `石季龙跪在一块黑石前。`，地点仅 `邺城` 和 `长安城门`，场景仅章节标题，组织仅 `龙城燕庭`。

## 2026-05-05

### 架构总览抽取复查

- 修改摘要：复查架构总览的关系总览、世界要素、架构原文、项目记忆、梦境整理和知识检索；修正人物、地点、道具、技能、组织/势力里由历史短语、考据资料长句、单字道具、技能描述和组织后缀造成的误判。已有正式人物设定时，导入资料仍用于资料库和蒸馏上下文，但不会批量进入人物图谱和世界要素。
- 影响范围：`StoryOverview` 后端抽取逻辑、架构总览人物列表、人物关系节点、世界要素、人物时间线关联节点；不改用户作品正文、资料库保存流程或普通项目详情接口格式。
- 验证结果：`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_service.ProjectServiceTestCase.test_story_overview_normalizes_entities_and_links_single_character backend.tests.test_project_service.ProjectServiceTestCase.test_story_overview_filters_historical_phrases_from_character_names backend.tests.test_project_service.ProjectServiceTestCase.test_story_overview_filters_research_material_noise_when_architecture_has_characters backend.tests.test_project_service.ProjectServiceTestCase.test_imported_source_material_populates_reference_characters_and_events` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_service` 通过，35 个用例通过；`PYTHONPATH=backend python3 -m unittest discover backend/tests` 通过，120 个用例通过，过程里仍有既有 `ResourceWarning` 输出；`npm run build` 通过；`npm run verify:ui` 通过，包含架构总览检查；`git diff --check` 通过；实际作品《邺天录》抽取结果已核查，人物列表不再出现 `石虎称`、`方式`、`封王`、`国北方`、`连续性规则`、`国家修`、`龙城燕` 等噪声项。

### Hermes 风格多 agent 执行增强

- 修改摘要：章节生成改为 3 个候选正文并行生成，每个候选并行执行承接事实、人物口气、可读性三类审校，主流程择优后可自动修订并复审；Agent 计划动作新增 `parallel_group / subtask_id / role / capability`，执行流新增 `subtask_started / subtask_result / subtask_failed` 事件；批量生成改为可恢复任务队列，按章节顺序执行并保存任务状态、人工评论、失败重试和已完成章节跳过；前端 Agent 时间线展示父子任务，批量生成面板支持任务 ID、失败重试和人工评论。
- 影响范围：章节生成流水线、Agent SSE 事件协议、`AgentPlanAction` 数据结构、批量生成请求参数和 `batch_tasks/{task_id}.json` 状态文件、技能库批量生成面板、Agent 时间线展示、相关后端回归用例和文档。
- 验证结果：`.venv/bin/python -m unittest -v backend.tests.test_generation_service backend.tests.test_agent_service backend.tests.test_studio_service` 通过，43 个用例通过；`npm run backend:test` 通过，123 个用例通过；`npm run build` 通过；`npm run verify:ui` 通过；`git diff --check` 通过。

### 自我进化报告与技能维护

- 修改摘要：技能库新增“自我进化”入口，汇总项目经验候选、失败执行样本、Prompt 失败样本、章节核验低分样本和技能维护建议；章节低分核验和自动修订会进入技能候选；技能维护记录新增使用次数和沉淀次数，长时间未使用的用户技能会提示复查或归档。
- 影响范围：新增 `backend/novel_backend/services/self_evolution_service.py`、`GET /api/studio/self-evolution`、`GET /api/studio/skills/curation`、`SkillCurationReport / SelfEvolutionReport` 数据结构、技能区 `自我进化` 面板、默认技能目录、学习记录、执行轨迹、Prompt 历史和技能使用记录读取逻辑。
- 验证结果：`.venv/bin/python -m unittest -v backend.tests.test_skill_service backend.tests.test_self_evolution_service` 通过，7 个用例通过；`npm run backend:test` 通过，136 个用例通过；`npm run build` 通过；`npm run verify:ui` 通过；`git diff --check` 通过。

### macOS 测试包整理路径修正

- 修改摘要：`package:test:macos` 改为从 `docs/macOS测试版安装说明.md` 和 `docs/测试反馈清单.md` 复制分发文档，避免公开版文档迁移后测试包整理脚本读取根目录旧路径失败。
- 影响范围：macOS 测试包整理流程和 `dist/test-release/macos/稿匣_0.1.0_测试包` 分发目录内容；不改变应用代码、接口、配置或用户数据结构。
- 验证结果：`npm run verify:release` 通过，覆盖浏览器 smoke、123 个后端用例、前端生产构建、Python sidecar 打包、sidecar 健康检查、Tauri debug `.app` / `.dmg` 构建、签名修复校验和应用内 sidecar 健康检查；`npm run package:test:macos` 通过，重新生成 `稿匣_0.1.0_测试包`；`shasum -a 256 -c SHA256SUMS.txt` 通过。

### 外部测试离线签名许可证

- 修改摘要：测试许可证改为 Ed25519 离线签名格式，App 只内置公钥并在导入和使用时验签；新增设备码读取接口、许可证面板复制设备码、密钥生成脚本和许可证签发脚本。生成、改稿、联网考据、做梦整理、架构总览模型复核和模型类技能接口在执行前检查许可证；前端 SSE 建连失败时显示后端返回的许可证提示。
- 影响范围：`/api/license/import`、`/api/license/device-fingerprints`、`/api/generate/*`、`/api/studio/*/stream`、`/api/projects/{project_id}/research/historical`、`/api/projects/{project_id}/dreams/run`、`GET /api/projects/{project_id}?review_characters=true`、许可证签发脚本、README、macOS 测试版安装说明、测试反馈清单和桌面发布说明；不改变本地项目查看、手动编辑、导出、模型配置保存和资料导入。
- 验证结果：`scripts/create-license.py` 使用本机私钥签发许可证后，当前 App 内置公钥验签通过；`.venv/bin/python -m unittest -v backend.tests.test_license_service` 通过，10 个用例通过；`python3 -m py_compile` 通过；`node --check scripts/verify-ui-smoke.mjs` 通过；`npm run verify:ui` 通过；`npm run backend:test` 通过，134 个用例通过；`npm run verify:desktop` 通过，包含前端构建、Python sidecar 打包、`cryptography` PyInstaller hook、sidecar 健康检查、Tauri debug `.app` / `.dmg` 构建、签名修复校验和应用内 sidecar 健康检查；`npm run package:test:macos` 通过，重新生成测试包；`shasum -a 256 -c SHA256SUMS.txt` 通过。

### 章节容量自动校验

- 修改摘要：项目上下文新增章节容量校验，按目标总字数和目标章节数计算单章均值；Agent 规划、章节生成和续写正文在默认目标明显偏短时，会自动改用当前章节的一段容量，避免把短稿当完整章。用户明确要求短稿、片段、开头或具体字数时，仍按用户要求处理。
- 影响范围：`context_builder` 上下文组装、Agent 章节 action 的目标字数、`chapter_generate` 和 `chapter_workflow draft` 的续写目标、`ChapterGenerateRequest.target_words`、相关后端回归用例和章节工作流文档。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/context_builder.py backend/novel_backend/services/generation_service.py backend/novel_backend/services/agent_service.py backend/novel_backend/services/studio_service.py backend/novel_backend/models.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder backend.tests.test_agent_service.AgentServiceTestCase.test_write_request_returns_confirm_plan_when_architecture_missing backend.tests.test_agent_service.AgentServiceTestCase.test_write_request_respects_explicit_word_count backend.tests.test_generation_service.GenerationServiceTestCase.test_chapter_workflow_draft_uses_single_partial_continuation` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder backend.tests.test_generation_service backend.tests.test_agent_service backend.tests.test_studio_service` 通过，48 个用例通过；`npm run backend:test -- --failfast` 通过，128 个用例通过；`git diff --check` 通过。

### 超长章节分段生成

- 修改摘要：章节续写目标超过单次安全长度时，后端会按不超过 5500 字均分为多段执行；每段继承上一段正文、独立生成和审校，最后合并为完整章节。Agent 能识别“完整章”“按目标字数”“扩到完整”等表达，并按单章剩余容量设置目标字数；常见中文字数写法如“1万字”“一万五千字”“三千五字”也会正确识别。
- 影响范围：`generation_service` 续写流水线、Agent 意图识别和章节 action 字数规划、`ChapterGenerateRequest / ChapterWorkflowRequest / AgentPlanAction.target_words` 上限、章节生成与本章工作流文档、相关后端回归用例。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/context_builder.py backend/novel_backend/services/generation_service.py backend/novel_backend/services/agent_service.py backend/novel_backend/models.py backend/tests/test_context_builder.py backend/tests/test_generation_service.py backend/tests/test_agent_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder.ContextBuilderTestCase.test_explicit_length_target_accepts_common_chinese_word_counts backend.tests.test_generation_service.GenerationServiceTestCase.test_continuation_segment_targets_are_balanced backend.tests.test_generation_service.GenerationServiceTestCase.test_run_continuation_pipeline_splits_oversized_target backend.tests.test_agent_service.AgentServiceTestCase.test_write_request_full_chapter_uses_remaining_project_capacity` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder backend.tests.test_generation_service backend.tests.test_agent_service backend.tests.test_studio_service` 通过，52 个用例通过；`npm run backend:test -- --failfast` 通过，134 个用例通过；`git diff --check` 通过。

## 2026-05-06

### 外部测试干净安装包

- 修改摘要：重新生成 macOS arm64 测试包 `dist/test-release/macos/稿匣_0.1.0_测试包`；分发包只包含 DMG、安装说明、测试反馈清单、`SHA256SUMS.txt` 和包信息，许可证签发私钥继续保存在仓库外的本机目录。
- 影响范围：外部测试分发产物和测试交付记录；不改变应用代码、接口、配置格式或用户数据结构。
- 验证结果：`npm run verify:desktop` 通过，包含 136 个 backend 用例、前端生产构建、Python sidecar 打包、`cryptography` PyInstaller hook、sidecar 健康检查、Tauri debug `.app` / `.dmg` 构建、签名修复校验和应用内 sidecar 健康检查；`npm run package:test:macos` 通过；包目录、`.app` 和挂载后的 `.dmg` 私钥特征扫描通过，未发现私钥内容、`private_key`、`ed25519-private-key` 或 `.gaoxia-license`；`shasum -a 256 -c SHA256SUMS.txt` 通过；`hdiutil verify` 确认 DMG 校验有效。

## 2026-05-07

### 永久离线许可证

- 修改摘要：离线许可证新增永久授权模式，签名载荷可使用 `permanent: true` 代替 `expires_at`；签发脚本改为 `--expires-at` 和 `--permanent` 二选一；许可证面板对永久许可证显示“永久”。永久许可证仍可追加 `--device-fingerprint` 绑定设备。
- 影响范围：许可证导入和校验、`scripts/create-license.py` 签发参数、许可证面板显示、macOS 测试版安装说明、桌面发布回归说明和桌面版方案文档；不改变已有限时许可证格式。
- 验证结果：`.venv/bin/python -m unittest -v backend.tests.test_license_service` 通过，11 个用例通过；`.venv/bin/python -m py_compile backend/novel_backend/services/license_service.py scripts/create-license.py` 通过；限时、永久、永久绑定设备三种签发命令通过；用本机私钥生成的永久许可证可被当前内置公钥导入并显示为有效；`npm run build` 通过；`npm run verify:desktop` 通过，包含 143 个 backend 用例、前端构建、Python sidecar 打包、sidecar 健康检查、Tauri debug `.app` / `.dmg` 构建、签名修复校验和应用内 sidecar 健康检查；`npm run package:test:macos` 通过；`shasum -a 256 -c SHA256SUMS.txt` 通过；`hdiutil verify` 确认 DMG 校验有效；包目录、`.app` 和挂载后的 `.dmg` 私钥特征扫描通过。

### Agent 改稿保存校验、自动补足与正文刷新

- 修改摘要：`rewrite_chapter` 写回后改为用保存后的正文长度复算章节容量，并和用户字数要求、项目单章均值比较；重写、改写、定稿整章时，低于完整章容量会自动从当前正文末尾分段续写。补足过程中任一请求失败，或最终仍未达到容量阈值，都会恢复本轮改稿前正文，避免把不合格短稿或半截扩写留在章节里。执行反馈会过滤模型自报的“约 15000 字”“完整章节”等未经验证的修改说明；去 AI、短稿、片段、开头等明确短文本请求不触发扩写。Agent 前端同时会从 `session_result.project_detail` 刷新项目详情；最终结果没有项目详情时，会重新读取项目详情，避免章节文件已更新但正文面板仍显示旧内容。
- 影响范围：Agent 改稿执行反馈、`rewrite_report` 产物 `metadata`、章节正文写回、章节正文面板刷新、`useAgentSession` 结果处理、`NovelWorkflowPanel` 执行完成后的项目详情同步；不改变章节正文保存路径、导出按钮或模型调用配置。
- 验证结果：`.venv/bin/python -m unittest backend.tests.test_agent_service.AgentServiceTestCase.test_rewrite_auto_completes_when_model_overclaims_length backend.tests.test_agent_service.AgentServiceTestCase.test_rewrite_restores_original_when_length_completion_fails_before_any_saved_chunk backend.tests.test_agent_service.AgentServiceTestCase.test_rewrite_restores_empty_original_when_length_completion_fails backend.tests.test_agent_service.AgentServiceTestCase.test_rewrite_restores_original_when_length_completion_fails_after_partial_chunk -v` 通过；`.venv/bin/python -m unittest backend.tests.test_agent_service -v` 通过，25 个用例通过；`npm run backend:test` 通过，142 个用例通过；`npm run build` 通过；`git diff --check` 通过。

### Agent 执行中打开技能库状态保留

- 修改摘要：打开技能库时，作品工作台改为隐藏而不是销毁；Agent 对话面板会继续保留运行状态、计时条和停止按钮，返回工作台后仍能看到正在执行的任务。
- 影响范围：`src/App.vue` 主区域渲染条件；不改变 Agent 后端执行、SSE 协议、线程存储、项目文件写回或模型配置。
- 验证结果：`npm run build` 通过；`npm run verify:ui` 通过。

### 架构总览统计卡片跳转

- 修改摘要：架构总览顶部的人物、事件、地点、道具、技能、组织/势力和时间线统计卡片改为可点击控件；点击事件、地点、道具、技能和组织/势力会进入世界要素并定位到对应分区，点击时间线会回到人物关系页的时间线区域。世界要素新增全局技能分区。
- 影响范围：`StoryOverviewPanel` 前端交互、世界要素展示内容、浏览器 smoke 的架构总览检查；不改变后端抽取结果、项目文件、接口或用户数据结构。
- 验证结果：`npm run build` 通过；`npm run verify:ui` 通过，包含点击“事件”“技能”“时间线”统计卡片的检查。

### macOS 首次打开无响应说明

- 修改摘要：`docs/macOS测试版安装说明.md` 新增“安装后点击没有反应”处理步骤，说明先确认 App 已拖进“应用程序”，再用 `xattr -dr com.apple.quarantine "/Applications/稿匣.app"` 清除测试包隔离标记，并通过右键“打开”放行。
- 影响范围：macOS 测试包安装说明和重新整理后的 `dist/test-release/macos/稿匣_0.1.0_测试包/安装说明-先看这个.md`；不改变应用代码、接口、配置或 DMG 内容。
- 验证结果：`npm run package:test:macos` 通过；测试包内安装说明已包含新章节和 `xattr` 命令；`shasum -a 256 -c SHA256SUMS.txt` 通过。

### Windows 安装包 CI 打包通道

- 修改摘要：新增手动触发的 `Windows Desktop Release` GitHub Actions 工作流；补充 Windows PowerShell 版 sidecar 打包脚本和发布验证脚本；新增 `backend:test:windows`、`backend:bundle:windows`、`verify:desktop:windows` 命令；补充 Windows 打包说明和 README 状态说明。
- 影响范围：Windows 安装包生成流程、CI 产物上传、Windows sidecar `novel-backend-x86_64-pc-windows-msvc.exe`、发布文档和常用命令；不改变应用接口、运行时数据结构或 macOS 打包流程。
- 验证结果：`npm run verify` 通过，包含 143 个 backend 用例和前端生产构建；`git diff --check` 通过；`package.json` JSON 解析通过；`.github/workflows/windows-release.yml` YAML 解析通过；`npm run verify:desktop:windows` 未在本机执行，当前环境是 macOS arm64，不是 Windows runner。

## 2026-05-08

### macOS 测试包输出目录迁移

- 修改摘要：`package:test:macos` 的测试包输出目录从 `dist/test-release/macos/` 改为 `release/test-release/macos/`，避免前端构建清空 `dist/` 时删除已整理的外部分发包；`.gitignore` 同步忽略 `release/`。
- 影响范围：macOS 测试包整理脚本、桌面发布回归说明、外部测试包本地存放路径；不改变应用代码、接口、许可证格式或 DMG 内部内容。
- 验证结果：`npm run verify:desktop` 通过，包含 143 个 backend 用例、前端构建、Python sidecar 打包、sidecar 健康检查、Tauri debug `.app` / `.dmg` 构建、签名修复校验和应用内 sidecar 健康检查；`npm run package:test:macos` 通过，测试包生成到 `release/test-release/macos/稿匣_0.1.0_测试包`；`npm run build` 后测试包仍保留在 `release/`；`shasum -a 256 -c SHA256SUMS.txt` 通过；`hdiutil verify` 确认 DMG 校验有效；包目录、`.app` 和挂载后的 `.dmg` 私钥特征扫描通过。

### macOS zsh 权限修复命令

- 修改摘要：`docs/macOS测试版安装说明.md` 的“安装后点击没有反应”章节新增 zsh 命令组，除了清除 `com.apple.quarantine`，还会给 `novel-generator` 和 `novel-backend` 恢复执行权限，并用 `open "$APP"` 启动应用。
- 影响范围：macOS 测试包安装说明和重新整理后的 `release/test-release/macos/稿匣_0.1.0_测试包/安装说明-先看这个.md`；不改变应用代码、接口、许可证格式或 DMG 内容。
- 验证结果：`npm run package:test:macos` 通过；测试包内安装说明已包含 zsh 命令组；`shasum -a 256 -c SHA256SUMS.txt` 通过。

### macOS 闪退诊断说明

- 修改摘要：macOS 测试版安装说明的 zsh 权限修复命令新增本机 ad-hoc 重签名步骤，避免修改 App 内部二进制权限后签名状态不一致；新增“仍然闪退时导出日志”章节，把系统版本、架构、App 内部文件权限、签名校验和直接启动输出写到桌面日志文件。
- 影响范围：macOS 测试包安装说明和重新整理后的 `release/test-release/macos/稿匣_0.1.0_测试包/安装说明-先看这个.md`；不改变应用代码、接口、许可证格式或 DMG 内容。
- 验证结果：`npm run package:test:macos` 通过；测试包内安装说明已包含 `codesign --force --deep --sign -` 和 `稿匣启动日志.txt` 导出命令；`shasum -a 256 -c SHA256SUMS.txt` 通过。

### Windows GitHub Actions 打包验证

- 修改摘要：Windows 发布工作流改为只构建并上传 NSIS `setup.exe` 和 Windows sidecar；`ProjectServiceTestCase` 的临时目录清理在 Windows 上允许忽略数据库文件锁清理错误，避免测试结束阶段被 `knowledge.db` 句柄占用中断。
- 影响范围：Windows CI 安装包产物、Windows 发布验证脚本、Windows 打包说明和桌面发布回归说明；不改变应用接口、运行时数据结构或 macOS 打包流程。
- 验证结果：GitHub Actions `Windows Desktop Release` 于 2026-05-08 成功完成，包含 110 个 backend 用例、前端生产构建、Windows sidecar 生成和健康检查、Tauri NSIS release 构建，以及 `gaoxia-windows-3e70c42d0d09fea933c6443ff17ef00752da48d9` 产物上传；MSI 构建未纳入当前 CI，需后续处理 WiX `light.exe` 失败后再恢复。

### macOS 26.3 启动闪退修复和测试包重建

- 修改摘要：外部测试机崩溃报告显示 App 在 `tao::platform_impl::platform::app_delegate::did_finish_launching` 阶段触发 Rust panic；Tauri 相关依赖升级到 `@tauri-apps/cli 2.11.1`、`@tauri-apps/api 2.11.0`、Rust `tauri 2.11.1`、`tao 0.35.2`、`wry 0.55.1`，安装说明保留必要权限检查且不再要求测试用户导出启动日志，并重新生成 macOS arm64 干净测试包。
- 影响范围：macOS 桌面壳启动流程、Tauri/Wry/Tao 依赖锁定版本、测试版安装说明、`release/test-release/macos/稿匣_0.1.0_测试包` 分发产物；不改变许可证格式、接口协议、用户项目数据或私钥存放方式。
- 验证结果：`cargo check --manifest-path src-tauri/Cargo.toml` 通过；`npm run build` 通过；`npm run verify:desktop` 通过，包含 143 个 backend 用例、前端构建、Python sidecar 打包、sidecar 健康检查、Tauri debug `.app` / `.dmg` 构建、签名修复校验和应用内 sidecar 健康检查；升级后的 `.app` 本机直接启动 5 秒未退出并成功拉起 backend；`npm run package:test:macos` 通过；`shasum -a 256 -c SHA256SUMS.txt` 通过；`hdiutil verify` 确认 DMG 校验有效；包目录、`.app` 和挂载后的 `.dmg` 私钥特征扫描通过。

## 2026-05-15

### macOS debug 测试包启动路径修复

- 修改摘要：Tauri setup hook 改为只在 `tauri dev` 构建中查找开发环境 `.venv/bin/novel-backend`；`tauri build --debug` 和 release 打包产物统一通过 `app.shell().sidecar("novel-backend")` 启动内置 backend，避免外部测试机器读取编译机绝对路径后启动崩溃。桌面发布回归脚本新增 `.app` 主程序启动检查，能发现 setup 阶段 panic 或 sidecar 查找失败。
- 影响范围：macOS 桌面壳 backend 启动路径、debug `.app` / `.dmg` 测试包验证流程、README、桌面版方案和桌面发布回归说明；不改变前端接口、backend HTTP 协议、项目数据或许可证格式。
- 验证结果：`cargo check --manifest-path src-tauri/Cargo.toml` 通过；`bash -n scripts/verify-desktop-release.sh` 通过；`npm run verify:desktop` 通过，包含 143 个 backend 用例、前端构建、Python sidecar 打包、sidecar 健康检查、Tauri debug `.app` / `.dmg` 构建、签名修复校验、应用内 sidecar 健康检查和 `.app` 主程序 10 秒启动检查；`npm run package:test:macos` 通过，测试包生成到 `release/test-release/macos/稿匣_0.1.0_测试包`；`shasum -a 256 -c SHA256SUMS.txt` 通过；`hdiutil verify` 确认 DMG 校验有效；`cargo fmt --manifest-path src-tauri/Cargo.toml --check` 未执行成功，当前 `stable-aarch64-apple-darwin` toolchain 的 `cargo-fmt` 不可用。

### 飞书外部测试发布中心

- 修改摘要：在飞书创建 `稿匣 外部测试发布中心` 多维表，新增 `文档` 表集中记录安装包、安装说明、FAQ 和更新进度，并保留安装包、安装说明与 FAQ、更新进度三张分表作备份；新增一份飞书汇总文档 `稿匣 0.1.0 外部测试说明`，把下载入口、安装步骤、许可证和模型配置、常见问题、反馈格式、更新进度放到同一份可分享文档中；整理 Windows 0.1.0 测试包到 `release/test-release/windows/稿匣_0.1.0_测试包`，新增 Windows 安装说明和测试反馈清单，并上传到飞书云空间。
- 文档整理：飞书汇总文档改为面向测试用户的安装说明页，删除内部验证命令、飞书多维表维护过程、上传失败细节和维护者视角的进度说明，只保留下载、安装、首次使用、常见问题、反馈格式和版本说明。
- 激活配置说明：外部测试说明新增激活码发放模板、20 个短期未绑定设备测试激活码、设备码绑定和导入签名许可证步骤；新增阿里云百炼 API Key 获取、稿匣内填写字段、常见地域 Base URL 和 Key 泄露处理说明。
- 影响范围：外部测试分发记录、Windows 测试包说明文件、飞书云空间安装包目录、`release/test-release/稿匣_0.1.0_外部测试说明.md` 汇总文档源文件；不改变应用代码、接口、配置格式或用户项目数据。
- 验证结果：Windows `SHA256SUMS.txt` 校验通过；飞书 `drive +push` 上传 Windows 安装程序、sidecar、安装说明和反馈清单成功；飞书多维表 `文档` 读取确认记录已写入，安装包、说明与 FAQ、更新进度筛选视图可用；飞书汇总文档通过 `docs +create` 创建成功，`docs +update --command overwrite --doc-format markdown` 更新成功，`docs +fetch --scope outline` 确认新版目录可读取，`docs +fetch --scope keyword` 确认激活码和百炼 Key 章节已写入；本地解析外部测试说明中的 20 个激活码并逐条导入验证通过。macOS DMG 已通过本机验证，但 28.3MB 文件经飞书 CLI/OpenAPI 和网页端上传均失败，飞书提示当前企业版本文件大小超过上限，后续需换 GitHub Release、网盘链接或升级飞书版本后再更新下载地址。

### Agent 对话长线程处理

- 修改摘要：Agent 对话发送前会保存完整线程到项目目录，SSE 请求只提交最近 50 条历史，并把超长单条历史压缩到接口允许长度内；线程消息新增 `id / content_hash / original_length / summary` 元数据，后端同步生成 `.gaoxia/thread_context/{thread_id}.json` 片段索引，执行时按当前输入取回相关长历史内容；backend 对请求体验证失败新增统一错误包装，前端能显示具体字段原因，不再只看到 `SSE 建连失败: 422`。
- 影响范围：`/api/studio/agent/stream` 的建连错误提示、Agent 对话请求体、线程保存格式、项目目录 `.gaoxia/thread_context` 索引、长线程继续对话体验、接口层校验测试和 Agent 长历史取回测试；不改变 SSE 事件协议、模型配置或章节正文保存路径。
- 验证结果：`.venv/bin/python -m unittest backend.tests.test_app -v` 通过，3 个用例通过；`.venv/bin/python -m unittest backend.tests.test_project_service.ProjectServiceTestCase.test_save_project_agent_threads_keeps_long_message_and_builds_context_index backend.tests.test_agent_service.AgentServiceTestCase.test_agent_session_recovers_relevant_chunks_from_long_thread_message -v` 通过，2 个用例通过；`npm run build` 通过；`npm run backend:test` 通过，146 个用例通过；`git diff --check` 通过。

## 2026-05-16

### Agent 长线程完整性复查

- 修改摘要：前端新增长线程保存保护：当本轮历史超过 50 条，或任意单条历史超过 6000 字时，如果完整线程保存到 backend 失败，会停止本轮 SSE 执行并提示错误，避免只拿压缩后的历史继续生成。长线程回归测试文本提升到真实超过 6000 字，并直接断言后端能从索引里取回尾部关键句。
- 影响范围：Agent 对话发送保护、长线程上下文回归测试、Agent 执行架构说明；不改变 SSE 事件协议、线程文件路径、模型配置或章节正文保存路径。
- 验证结果：`.venv/bin/python -m unittest backend.tests.test_project_service.ProjectServiceTestCase.test_save_project_agent_threads_keeps_long_message_and_builds_context_index backend.tests.test_agent_service.AgentServiceTestCase.test_agent_session_recovers_relevant_chunks_from_long_thread_message -v` 通过，2 个用例通过；`npm run build` 通过；`npm run backend:test` 通过，146 个用例通过；`npm run verify:ui` 通过；`git diff --check` 通过。

## 2026-05-19

### 章节完整章小节生成

- 修改摘要：章节生成目标超过单次安全长度时，后端会按章节目标字数规划小节，每节生成后按实际正文长度判断是否接近目标；如果模型单节写短，会继续追加小节，直到达到目标比例或到达安全次数上限。技能库 `chapter_generate` 未指定目标字数时，改为按当前章节距离单章均值的缺口生成完整章。改稿补足的尝试轮数也改为按章节目标容量计算，避免固定 4 轮导致长章提前失败。
- 影响范围：`generation_service` 小节生成流程、技能库章节生成默认目标、Agent 改稿完整章补足轮数、章节生成/改稿反馈摘要和相关文档；不改变章节保存路径、SSE 协议、模型配置或项目数据格式。
- 验证结果：`.venv/bin/python -m unittest backend.tests.test_generation_service -v` 通过，12 个用例通过；`.venv/bin/python -m unittest backend.tests.test_agent_service -v` 通过，26 个用例通过；`npm run backend:test` 通过，147 个用例通过；`npm run build` 通过；`git diff --check` 通过。

### macOS 测试包重建

- 修改摘要：基于当前工作区重新执行 macOS 测试版验证和打包，生成 `release/test-release/macos/稿匣_0.1.0_测试包`，包内包含 DMG、安装说明、测试反馈清单、`SHA256SUMS.txt` 和包信息。
- 影响范围：macOS arm64 测试包分发产物；不改变应用接口、项目数据格式、许可证格式或模型配置。
- 验证结果：`npm run release:test:macos` 通过，包含 147 个 backend 用例、前端生产构建、Python sidecar 打包、sidecar 健康检查、Tauri debug `.app` / `.dmg` 构建、签名修复校验、应用内 sidecar 健康检查和 `.app` 主程序 10 秒启动检查；测试包内 `shasum -a 256 -c SHA256SUMS.txt` 通过；`hdiutil verify` 确认 DMG 校验有效。

### 模型网络断连重试

- 修改摘要：模型请求新增统一网络传输层，对 SSL EOF、远端提前断开、连接重置、429 和 5xx 短时错误进行重试；错误分类新增 `network`，不再把 SSL EOF 显示成未知模型错误。
- 影响范围：聊天模型调用、Embedding、重排序、项目愿景、Prompt 历史错误字段和模型错误提示。
- 验证结果：`python3 -m py_compile` 通过；`.venv/bin/python -m unittest backend.tests.test_model_transport_service backend.tests.test_model_error_service -v` 通过；`npm run backend:test` 通过，150 个用例通过。
