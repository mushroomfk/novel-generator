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

## 后端结构

### 1. 事件协议

`AgentEventEmitter` 现在负责统一发出结构化 SSE 事件，同时保留旧事件做兼容。

当前结构化事件：

- `session_started`
- `plan_generated`
- `plan_confirm_required`
- `action_started`
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

用途：

- `execution_trace` 给执行链路
- `event_blocks` 给计划和阶段性事件
- `artifacts` 给结果产物和历史回看
- 写回章节后，如果章节核验报告可用，Agent 会把 `chapter_review` 作为产物返回，前端可以直接展示核验摘要、评分和问题数。

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

`agent_capability_rules.json` 和 `failure_cases.jsonl` 不是只做归档。后续 Agent 进入模型规划和模型路由时，会把高置信调用规则和失败案例提醒作为 system context 一起传入，用来影响 action 顺序、工具选择和失败前检查。

前端技能库 `Agent 自学习` 面板会读取这些接口展示能力看板、确认草案、草案差异预览、写作回归、模型审查、经验候选、调用规则、写作评价、细分质量维度、长期趋势、失败案例、重复失败聚合、技能统计、技能版本和技能包迁移。技能版本会同时显示历史版本、当前版本和 unified diff。写作回归使用同一章样本检查续写、改稿、去 AI、资料调用四类任务的输入条件和自学习信号，不直接改正文。

自学习排程默认关闭，只有通过面板或接口开启后才按 `interval_hours` 检查；面板里的“执行一次”会强制执行当前任务组。后台 worker 由 FastAPI lifespan 启动，每隔 `NOVEL_SELF_EVOLUTION_WORKER_INTERVAL_SECONDS` 扫描一次已启用排程的作品；`NOVEL_SELF_EVOLUTION_WORKER_ENABLED=false` 可以关闭 worker。多模型交叉审查可以在设置页启用，也可以通过 `NOVEL_REVIEW_MODEL_API_KEY`、`NOVEL_REVIEW_MODEL_BASE_URL`、`NOVEL_REVIEW_MODEL_NAME` 配置；环境变量优先级高于本地配置。

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

`NovelWorkflowPanel.vue` 不再自己解析每条 SSE。

### 2. 结构化展示

当前消息展示分成三块：

- `AgentPlanCard`
  - 展示计划标题、摘要、步骤、动作标签
- `AgentActionTimeline`
  - 展示每一步的状态、任务包、摘要、变更
- `AgentArtifactSummary`
  - 展示产物标题、类别、摘要、预览

运行中卡片也改成了同一套时间线展示，不再只是「第几步 + 一句文本」。

另外补了一条交互规则：

- 用户发的是明确执行命令时，章节续写、补架构这类计划会直接开始执行
- 计划卡仍然会保留在聊天记录里，但不再卡在「待确认」
- 只有用户表达不明确，或者只是想先看方案时，才停在计划态等手动执行
- 如果本轮实际写回的是别的章节，右侧预览会自动切到被写回的章节

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

这样 `NovelWorkflowPanel.vue` 里只剩一套执行状态：

- `useAgentSession`
- `sessionTimeline`
- `latestResult`
- 消息里的 `executionTrace / eventBlocks / artifacts`

### 4. 线程持久化

线程消息现在会一起保存：

- `execution_trace`
- `event_blocks`
- `artifacts`

所以重新打开线程后，不只是能看到回复文本，还能看到当次计划和执行记录。

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

- `npm run backend:test`

结果：

- 108 个测试通过

### 额外验证

- `backend.tests.test_agent_service`
- `backend.tests.test_project_service`
- `backend.tests.test_context_builder`
- `backend.tests.test_model_error_service`

其中补了一条线程持久化回归，确认 `event_blocks` 和 `artifacts` 能写入并读回。

## 后续建议

下一步如果继续往前做，顺序建议是：

1. 把 `event_blocks` 在前端做成更明确的“计划阶段/执行阶段/结果阶段”分组
2. 给 `useAgentSession` 增加重连和中断能力
3. 再把别的专用流逐步并到同一套 session/runtime 里
4. 再考虑把技能面板和 agent capability 做统一注册
