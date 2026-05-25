# Agent 执行架构说明

## 改动范围

当前改造把原来「一个大 service 直接串起计划、执行、SSE、前端展示」的方式，拆成了三层：

1. 后端运行时层
   - 新增 `backend/novel_backend/agent_runtime/events.py`
   - 新增 `backend/novel_backend/agent_runtime/registry.py`
   - `agent_service.py` 负责调度，不再自己写一整串 action 分支
   - 任务入口已经改成「模型先规划，再校验，再执行」，不是正则先决定 intent

2. 前端会话层
   - 新增 `src/composables/useAgentSession.js`
   - 统一处理 agent SSE 事件、当前执行状态、错误、结果

3. 展示层
   - 新增 `src/components/AgentPlanCard.vue`
   - 新增 `src/components/AgentActionTimeline.vue`
   - 新增 `src/components/AgentArtifactSummary.vue`
   - `NovelWorkflowPanel.vue` 只负责线程、输入和界面组合

后面又补了一步：

4. 整书架构专用执行流并回统一 session
   - 不再单独走 `streamArchitectureStep`
   - 先保存题材、目标章节数、目标字数，再走统一的 `sendConversation -> agent session`
   - 整书架构和普通 agent 执行现在共用同一套状态、时间线和结果展示

5. 执行轨迹、经验候选和自学习复盘
   - Agent 执行完成后会把计划、步骤、产物、建议和状态写入 `logs/agent_trajectories.jsonl`
   - 讨论结论、资料分析结果和可复用技能建议会整理成 `learning_review` 产物
   - `self_evolution_review` 会继续记录技能使用、调用规则候选、写作评价、失败案例和技能整理结果
   - 技能更新会保留版本快照，面板可查看差异、回滚版本或把用户技能提升为全局技能
   - 经验候选只展示和记录，不会直接写入作者侧项目记忆，需要作者确认后再保存

6. workflow 状态、动作契约和子任务隔离记录
   - 新增 `backend/novel_backend/services/agent_workflow_service.py`
   - 新增 `backend/novel_backend/services/agent_contract_service.py`
   - 每次 Agent 执行会在项目目录写入 `.gaoxia/runs/{task_id}/workflow.json`
   - workflow action 使用 `DISPATCHED / ACKED / RUNNING / SUCCEEDED / FAILED / BLOCKED / TIMED_OUT / STALLED` 状态
   - 执行前会记录预检结果、动作进入条件、失败策略和预期产物
   - 执行中会刷新 action heartbeat；子任务会单独写入 `.gaoxia/runs/{task_id}/subtasks/*.json`
   - 执行后会校验 action 产物是否满足契约，并把 workflow 状态作为 `workflow_run` 产物返回

## 后端结构

### 1. 事件协议

`AgentEventEmitter` 现在负责统一发出结构化 SSE 事件，同时保留旧事件做兼容。

当前结构化事件：

- `session_started`
- `plan_generated`
- `plan_confirm_required`
- `action_started`
- `subtask_started`
- `subtask_result`
- `subtask_failed`
- `action_result`
- `action_failed`
- `state_updated`
- `project_updated`
- `session_result`
- `session_error`
- `session_finished`

每条结构化事件都会带：

- `task_id`
- `thread_id`
- `event_id`
- `timestamp`

兼容事件还保留：

- `started`
- `progress`
- `result`
- `error`
- `done`

这样前端可以逐步迁移，不需要一次把旧逻辑全删掉。

`subtask_*` 用来展示 action 内部的父子任务。事件字段包含 `subtask_id`、`parallel_group`、`role`、`capability`、`action_kind` 和当前状态。前端会把它们挂到对应 action 的时间线下面，所以用户能看到“写作 agent、连续性审校 agent、人物口气审校 agent、可读性审校 agent”等子任务状态，而不是只看到一个大步骤。

workflow 文件里还会记录这些子任务的允许产物范围。子任务仍不能直接写项目正文、作者记忆或长期技能，写回动作继续由主 action handler 执行。

### 2. Action Registry

`registry.py` 里新增了统一执行上下文和注册表。

现在这些 action 已经从 `_execute_plan()` 的大分支里拆出来：

- `review_knowledge`
- `brainstorm`
- `generate_architecture`
- `continue_project`
- `chapter_generate`
- `chapter_workflow`
- `consistency_check`
- `rewrite_chapter`

每个 action handler 只处理自己的业务，并把结果写回统一状态：

- `execution_trace`
- `event_blocks`
- `artifacts`
- `changes`
- `last_reply`
- `suggestions`

`_execute_plan()` 现在只做三件事：

1. 计算当前 action 的任务包
2. 调用 registry 里的 handler
3. 把中间状态转换成统一执行结果

现在执行前还会多做两类检查：

- session 预检：项目目录、计划动作、模型配置、第二审查模型配置和失败案例库
- action 契约：目标章节、项目状态、历史失败门禁、预期产物和失败策略

契约检查不满足时，workflow action 会记为 `BLOCKED`；执行中异常记为 `FAILED`；长时间无确认或无心跳的旧 workflow 可以被标记为 `TIMED_OUT` 或 `STALLED`。

章节写回类 action 会把保存后的章节核验结果一并写入执行反馈：

- `chapter_generate`、`chapter_workflow` 的 draft 模式、`rewrite_chapter` 会在写回正文后读取章节核验报告
- `chapter_generate` 会按作品目标字数和当前章节长度计算目标容量；用户要求完整章、技能库章节生成未指定目标字数、架构完整且未要求短稿或具体字数时直接说“继续写第一章”，或目标超过单次安全长度时，会交给生成链路按章节容量规划小节并逐节审校。若模型单节写短，后端会按保存前的实际正文长度继续追加小节，直到接近目标容量或达到安全次数上限。
- `rewrite_chapter` 写回后会按保存后的正文长度、用户字数要求和项目单章均值复算章节容量；重写、改写、定稿整章时如果保存正文低于完整章容量，会从当前正文末尾自动扩写。如果剩余缺口超过 5500 字，会把完整缺口交给小节生成流程，而不是只请求一个短段落。补足过程中任一请求失败，或最终仍未达到容量阈值，都会恢复本轮改稿前正文，避免把不合格短稿或半截扩写留在章节里。去 AI、短稿、片段、开头等明确短文本请求不会触发扩写。
- 字数识别会区分目标和状态描述；“写 15000 字”“远低于 15000 字目标”会作为目标，“当前正文约 3870 字”“保存校验：当前正文约 3870 字”不会作为用户目标。
- 如果模型把短稿描述成完整章，执行反馈会过滤“约 15000 字”“完整章节”等未经验证的修改说明，并把 `saved_word_count / length_target_words / length_status / length_completion_*` 写入产物 `metadata`
- 核验分数、状态和摘要会进入 `changes`、回复正文和产物 `metadata`
- 若核验状态为 `risk` 或总分低于配置阈值，后端会按核验问题自动修订，重新写回正文后再次生成核验报告
- 自动修订默认启用，默认阈值为 65，默认最多 1 轮；可在 AI 写作设置里关闭、调整触发分数或把最多修订轮数调到 0 到 3
- 自动修订结果会进入回复正文、`changes` 和产物 `metadata`，包括是否尝试、是否写入、修订摘要、修订项和复查结果
- 核验失败时，章节正文仍会保留，但执行结果会明确返回失败原因，并给出重新运行章节核验的建议
- 核验失败不会触发自动修订，因为这时没有可靠的问题清单

### 3. Planner

现在后端入口不再先跑 `_heuristic_route()` 再决定 intent，而是：

1. 用模型根据项目状态和最近对话直接产出 plan JSON
2. 本地把 plan 里的 action 转成系统内的 `AgentPlanAction`
3. 本地补依赖、校验章节目标、校验可执行性
4. 再交给统一 executor 执行

本地规则还保留，但角色已经变了：

- 模型不可用时的回退
- 计划结果不合法时的备用处理
- 本地约束校验

不再作为主路由。

章节生成计划会按同一计划内的动作顺序解析章节目标：如果第一步会生成一个新章节，后续同一计划里的去 AI、润色或一致性检查可以指向这一步生成的章节。这样“写第一章”这类计划不会因为执行前还没有最近已写章节而被拒绝。

之前也修了一个实际误判：

- 像“把资料库的资料分析完，再重新弄续写架构”这种混合指令
- 现在会优先规划成 `review_knowledge -> generate_architecture`
- 不会再因为句子里有“续写”两个字就跳去写下一章

面向长篇逐章生产的正文写回计划会自动变成受监督流程：

- `chapter_generate` 或 `chapter_workflow(mode=draft)` 生成正文并写回章节
- `rewrite_chapter(mode=humanize)` 保留剧情事实，只处理模板腔、解释腔、总结句、对白同质化和节奏过匀
- `consistency_check` 在去 AI 后复查人物关系、事件结果、时间地点、道具状态和信息揭示顺序

如果用户先要求普通改稿或定稿，Agent 会在最后一次写回后补上去 AI 或一致性复查；作者明确说“只要初稿”“不要改稿”“不要检查”时，不会自动加入这些后续步骤。

### 4. 执行结果模型

`models.py` 里补了这些结构：

- `AgentEventBlock`
- `AgentArtifact`
- `AgentChatResult.event_blocks`
- `AgentChatResult.artifacts`
- `AgentThreadMessage.event_blocks`
- `AgentThreadMessage.artifacts`
- `AgentExecutionTrace.status`
- `AgentChatRequest.thread_id`
- `AgentPlanAction.subtask_id`
- `AgentPlanAction.parallel_group`
- `AgentPlanAction.role`
- `AgentPlanAction.capability`

用途：

- `execution_trace` 给执行链路
- `event_blocks` 给计划和阶段性事件
- `artifacts` 给结果产物和历史回看
- 写回章节后，如果章节核验报告可用，Agent 会把 `chapter_review` 作为产物返回，前端可以直接展示核验摘要、评分和问题数。

`parallel_group / subtask_id / role / capability` 参考了 Hermes 的 batch subagent 组织方式，但当前实现不让子任务直接改项目文件或长期记忆。写正文、写章节核验结果和写项目记忆仍由主 action handler 统一处理；子任务只通过 artifact、审校报告、执行事件或候选正文把结果交回主流程。

当前内置角色边界：

- 资料分析 agent：只产出资料分析 artifact，不直接改正文或项目记忆
- 写作 agent：负责候选正文和修订正文，写回由主 action handler 执行
- 连续性审校 agent：检查人物关系、事件结果、时间地点和道具状态，只产出报告
- 人物口气审校 agent：检查人物声音、对白关系和叙述距离，只产出报告
- 可读性审校 agent：检查节奏、段尾压力和阅读牵引，只产出报告

### 5. 执行轨迹、经验候选与自学习复盘

Agent session 结束后，后端会追加一条结构化轨迹：

- 文件：应用数据目录下的 `logs/agent_trajectories.jsonl`
- 查询接口：`GET /api/studio/agent-trajectories`
- 记录内容：`task_id`、`project_id`、`thread_id`、计划动作、执行时间线、产物摘要、变更、建议和完成状态

项目内的轻量经验记录保存在：

```text
<project-dir>/.gaoxia/learning/reviews.jsonl
```

当前会生成三类候选：

- 讨论中形成的项目目标、偏好或约束
- 资料分析产物里值得复用的结论
- 可转成用户技能的重复处理方式

自学习复盘会额外维护这些文件：

```text
<project-dir>/.gaoxia/learning/self_evolution_candidates.json
<project-dir>/.gaoxia/learning/self_evolution_reviews.jsonl
<project-dir>/.gaoxia/learning/agent_capability_rules.json
<project-dir>/.gaoxia/learning/writing_evaluations.jsonl
<project-dir>/.gaoxia/learning/self_evolution_drafts.json
<project-dir>/.gaoxia/learning/writing_regression_runs.jsonl
<project-dir>/.gaoxia/learning/self_evolution_model_reviews.jsonl
<project-dir>/.gaoxia/learning/failure_cases.jsonl
<project-dir>/.gaoxia/learning/self_evolution_schedule.json
<app-data>/skills/.usage.json
<app-data>/skills/.curator_reports.jsonl
<app-data>/skills/.versions/{skill_id}/versions.json
<app-data>/app_config.json              # review_model 存在这里
```

它会自动写入调用规则和统计信息，但不会越过作者确认直接改 `project_memory/author/`，也不会自动改章节正文。候选被标为已采纳后会先生成确认草案，草案再由作者在技能库里应用：记忆草案写入作者侧项目记忆，技能草案创建或更新用户技能，调用规则草案标为作者采纳。

相关接口：

- `GET /api/projects/{project_id}/self-evolution`
- `PATCH /api/projects/{project_id}/self-evolution/candidates/{candidate_id}`
- `POST /api/projects/{project_id}/self-evolution/curate`
- `POST /api/projects/{project_id}/self-evolution/regression`
- `POST /api/projects/{project_id}/self-evolution/model-review`
- `PUT /api/projects/{project_id}/self-evolution/schedule`
- `POST /api/projects/{project_id}/self-evolution/schedule/run`
- `PATCH /api/projects/{project_id}/self-evolution/drafts/{draft_id}`
- `POST /api/projects/{project_id}/self-evolution/drafts/{draft_id}/apply`
- `GET /api/studio/skills/{skill_id}/versions`
- `GET /api/studio/skills/{skill_id}/package`
- `POST /api/studio/skills/import-package`
- `POST /api/studio/skills/{skill_id}/versions/{version_id}/rollback`
- `POST /api/studio/skills/{skill_id}/promote-global`
- `GET /api/studio/skills/curation`
- `GET /api/studio/self-evolution?project_id=...`

`agent_capability_rules.json` 和 `failure_cases.jsonl` 不是只做归档。后续 Agent 进入模型规划和模型路由时，会把高置信调用规则和失败案例提醒作为 system context 一起传入，用来影响 action 顺序、工具选择和失败前检查。

失败案例现在也会参与 action 契约。遇到相同 action 时，契约检查会把最近失败案例作为门禁提示写入 workflow，要求执行前复核项目状态、章节目标和上一步产物。

前端技能库 `Agent 自学习` 面板会读取这些接口展示能力看板、确认草案、草案差异预览、写作回归、模型审查、经验候选、调用规则、写作评价、细分质量维度、长期趋势、失败案例、重复失败聚合、技能统计、技能版本和技能包迁移。技能版本会同时显示历史版本、当前版本和 unified diff。写作回归使用同一章样本检查续写、改稿、去 AI、资料调用四类任务的输入条件和自学习信号，并额外运行内置黄金样本，评估本地评审规则对模板腔、对白同质、连续性冲突和正常片段的识别能力，不直接改正文。

自学习排程默认关闭，只有通过面板或接口开启后才按 `interval_hours` 检查；面板里的“执行一次”会强制执行当前任务组。后台 worker 由 FastAPI lifespan 启动，每隔 `NOVEL_SELF_EVOLUTION_WORKER_INTERVAL_SECONDS` 扫描一次已启用排程的作品；`NOVEL_SELF_EVOLUTION_WORKER_ENABLED=false` 可以关闭 worker。多模型交叉审查可以在设置页启用，也可以通过 `NOVEL_REVIEW_MODEL_API_KEY`、`NOVEL_REVIEW_MODEL_BASE_URL`、`NOVEL_REVIEW_MODEL_NAME` 配置；环境变量优先级高于本地配置。

章节核验和自动修订也会参与经验整理。低分章节、自动修订摘要和复查结果会转成写作技能候选，方便后续把“低分修订经验”沉淀成用户技能。

## 前端结构

### 1. useAgentSession

`useAgentSession.js` 负责：

- 发起 `streamAgentConversation`
- 兼容结构化 SSE 和旧 SSE
- 维护 `running`
- 维护 `runtimeError`
- 维护 `sessionStatus`
- 维护当前 `timelineItems`
- 维护本轮 `latestResult`
- 结构化 `project_updated` 和最终 `session_result.project_detail` 都会触发项目详情更新，避免章节文件已写回但正文面板仍显示旧内容
- Agent 对话发起前，前端会先保存完整线程到项目目录，再向 backend 提交最近 50 条历史；单条历史超过 6000 字时只在请求体里保留开头和末尾，原文仍保存在项目文件里
- 如果本轮历史超过 50 条，或任意单条历史超过 6000 字，而完整线程保存失败，前端会停止本轮执行并显示错误，避免只拿压缩历史继续生成
- 每条线程消息保存 `id / content_hash / original_length / summary`，用于后端确认请求体里的压缩消息对应哪条完整历史

`NovelWorkflowPanel.vue` 不再自己解析每条 SSE。

### 2. 结构化展示

当前消息展示分成三块：

- `AgentPlanCard`
  - 展示计划标题、摘要、步骤、动作标签
- `AgentActionTimeline`
  - 展示每一步的状态、任务包、摘要、变更
  - 展示 action 下的子任务列表、角色、能力、运行状态和子任务摘要
- `AgentArtifactSummary`
  - 展示产物标题、类别、摘要、预览

运行中卡片也改成了同一套时间线展示，不再只是「第几步 + 一句文本」。

另外补了一条交互规则：

- 用户发的是明确执行命令时，章节续写、补架构这类计划会直接开始执行
- 计划卡仍然会保留在聊天记录里，但不再卡在「待确认」
- 只有用户表达不明确，或者只是想先看方案时，才停在计划态等手动执行
- 如果本轮实际写回的是别的章节，右侧预览会自动切到被写回的章节
- Agent 执行结束后，如果最终结果没有携带项目详情，前端会重新读取一次项目详情，保证当前章节正文显示保存后的版本

### 3. 整书架构执行

之前 `NovelWorkflowPanel.vue` 里有一条单独的整书架构执行流：

- 手工循环 `streamArchitectureStep`
- 手工维护执行日志
- 手工维护架构专用 loading/error 状态

现在已经改成：

1. 先调用 `persistArchitectureProfile()` 保存题材、目标章节数、目标字数
2. 在前端生成一份 architecture plan
3. 直接把这份 plan 作为 `approved_plan` 送进统一 agent session

如果项目里已经有资料库内容，会自动先加一条 `review_knowledge`，再执行 `generate_architecture`。

后端执行 `generate_architecture` 时不再等七个步骤全部完成后才统一保存。任务开始时只构建一次项目上下文快照，后续步骤复用这份快照，并通过内存里的 workspace 传递前面步骤刚生成的内容。每个架构步骤完成后会立即写入项目文件，并更新 `.gaoxia/architecture_progress.json`。如果模型或网络在中途失败，下一次同一指令会重新读取项目文件和进度，从失败步骤继续执行。情节骨架、人物状态和章节蓝图步骤必须沿用人物设定里已经确定的核心人物名单；新增配角不能替换核心人物或改名。

整书架构主流程只负责关键文本生成。知识库索引刷新、模型版故事总览和系统记忆刷新会写入 `.gaoxia/auxiliary_tasks.json`，由后台巡检执行；前台模型或检索任务忙时，后台巡检会延后到后续巡检。失败会记录错误并按重试时间再次处理，不会阻断架构生成或章节写作。关系总览只读取模型版故事总览缓存；模型版故事总览优先使用第二审查模型，第二审查模型不可用时使用当前写作模型。两个模型都不可用、模型调用失败或模型结果没有通过证据校验时，不再使用本地规则结果，辅助任务也不会记为完成。

这样 `NovelWorkflowPanel.vue` 里只剩一套执行状态：

- `useAgentSession`
- `sessionTimeline`
- `latestResult`
- 消息里的 `executionTrace / eventBlocks / artifacts`

### 4. 线程持久化

线程消息现在会一起保存：

- `id`
- `content_hash`
- `original_length`
- `summary`
- `execution_trace`
- `event_blocks`
- `artifacts`

所以重新打开线程后，不只是能看到回复文本，还能看到当次计划和执行记录。

项目目录还会生成 `.gaoxia/thread_context/{thread_id}.json`。该文件把长消息分成带 hash 的片段索引；Agent session 建立时会根据当前输入和本轮已提交 message id，取回相关片段并插入系统上下文。这样请求体保持可控，模型仍可使用长历史里的关键信息。

## 兼容策略

当前没有直接删掉旧 SSE 事件。

原因：

- 现有前端和测试里还有 `result/progress` 依赖
- 先让结构化协议落地，再逐步清旧逻辑，回归风险更低

## 已验证

### 构建

- `npm run build`

### 界面回归

- `npm run verify:ui`

这条脚本现在会起一套临时环境：

- 临时 backend
- 临时 Vite preview
- 本地假模型服务

当前会实际覆盖这些界面路径：

1. 章节页发起 agent 请求，确认计划卡能正常显示，并且命令式输入会直接执行
2. 验证章节正文写回、时间线和产物卡渲染
3. 验证“资料分析 + 重写架构”这类混合命令会优先走架构路径
4. 项目页直接执行整书架构，验证统一 session 路径可用
5. 项目页继续发讨论消息，验证讨论结果和建议按钮渲染
6. 刷新页面后，验证 agent 线程历史仍能恢复

### 后端回归

- `npm run verify`

结果：

- 后端 169 个 unittest 通过
- 前端生产构建通过

### 额外验证

- `backend.tests.test_agent_service`
- `backend.tests.test_agent_workflow_service`
- `backend.tests.test_generation_service`
- `backend.tests.test_project_service`
- `backend.tests.test_context_builder`
- `backend.tests.test_model_error_service`
- `git diff --check`

其中包含 workflow 状态文件回归，确认 action 契约、产物校验和超时状态能写入并读回。

## 后续建议

下一步如果继续往前做，顺序建议是：

1. 把 `event_blocks` 在前端做成更明确的“计划阶段/执行阶段/结果阶段”分组
2. 给 `useAgentSession` 增加重连和中断能力
3. 再把别的专用流逐步并到同一套 session/runtime 里
4. 再考虑把技能面板和 agent capability 做统一注册
