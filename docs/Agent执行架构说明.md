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
   - workflow action 使用 `DISPATCHED / ACKED / RUNNING / SUCCEEDED / FAILED / BLOCKED / TIMED_OUT / STALLED / CANCELLING / CANCELLED` 状态
   - 执行前会记录预检结果、动作进入条件、失败策略和预期产物
   - 执行中会刷新 action heartbeat；子任务会单独写入 `.gaoxia/runs/{task_id}/subtasks/*.json`
   - 执行后会校验 action 产物是否满足契约，并把 workflow 状态作为 `workflow_run` 产物返回
   - 执行中前端会用实时状态列表展示“已完成 / 正在运行 / 正在思考”、步骤耗时和摘要；执行结束时仍会写入最终 `session_result` event block，但聊天历史只保留结果说明、产物卡片和建议，不展示计划卡、状态标签、执行步骤或阶段摘要
   - `GET /api/studio/agent/{project_id}/runs/{task_id}` 可读取 workflow 摘要；`POST /api/studio/agent/{project_id}/runs/{task_id}/interrupt` 会写入中断请求，Agent 执行循环在动作边界停止后续动作
   - 项目迁移包遇到项目目录外的 Obsidian Vault 时，会保留 workflow 状态结构，但会把其中的 Obsidian 资料分析 action / subtask 摘要改成迁移提示

7. Obsidian 多章节目标上下文
   - Agent 路由 / 规划会识别“第 58 到 60 章”“第 58 章到第 60 章”这类范围目标
   - “先检查第一章，再生成第二章”这类混合指令会优先使用生成、改稿、拆场或诊断目标
   - 包含“蓝图 / 架构”等词但明确写了章节范围时，也会优先读取目标章节 Obsidian 任务
   - 能力上下文最多展开前 3 个目标章节的 Obsidian 来源、考据来源、章节计划、章节档案、必写项、禁写项、剧情债务、人物弧线和图谱风险
   - Obsidian 维护摘要和维护建议会按这些目标章节共同筛选、统计和排序，批量章节规划不会只看到第一个章节的资料
   - 明确要求生成正文的 2 到 3 章范围，如果规划模型只返回一个正文动作，后端会展开成逐章生成动作，再让每章进入去 AI 和一致性复查；超过 3 章的直接正文生成请求会提示分批或先整理章节蓝图
   - 执行阶段如果资料分析先继承第一个目标章节，后续章节动作会按各自目标章重新生成资料摘要，并缓存给同章生成、改稿和复查使用
   - Obsidian URI 内部链接会按目标章节进入同一套图谱和安全上下文；`obsidian://open`、`obsidian://advanced-uri` 里的 `file / filepath / filename / path` 指向 Vault 根路径，URI 小节或块引用会保留，frontmatter 关系字段、Markdown 链接、HTML `<a>` 链接和 Canvas link 节点里的 URI 指向未来笔记时，不会进入早期章节的资料分析、规划上下文或证据正文

8. 技能目录和 Agent action 元数据
   - `SkillBehavior` 现在记录 `agent_action_kind / agent_action_mode / agent_requires_confirmation`
   - 内置技能默认行为集中在 `skill_registry.py`，配置初始化和旧版技能 JSON 读取都会合并缺失字段
   - 前端本地技能目录 fallback 同步保留这些字段，避免后端目录未返回时显示和执行认知不一致
   - Planner 收到的“可用技能目录”会标出对应 action 与确认要求，例如 `chapter_workflow/draft`、`rewrite_chapter/humanize` 和 `consistency_check`
   - 主对话的“看现状 / 完善架构 / 判断本章 / 续写本章”快捷按钮会把对应内置技能 ID 作为 `active_skill_ids` 发送给 Agent
   - 后端会用选中的内置技能元数据修正计划动作，例如 `chapter-draft` 会把章节写作计划改为 `chapter_workflow/draft`，`chapter-humanize` 会把改稿计划改为 `rewrite_chapter/humanize`
   - 自定义技能 ID 仍只作为用户技能 prompt 注入执行；内置技能 ID 只参与计划动作选择，不会被拼进用户技能提示

9. 主对话长文本资料化
   - `AgentMessage.content` 和线程消息最多保存 1000000 字符，前端保留最新用户长输入，旧历史会先压缩再提交
   - 后端进入 `agent_session_stream` 后，会把超过 20000 字符的用户输入先拆成候选段，筛掉明显无关、技术日志或网页样板段落，再按约 50000 字符分段导入项目资料库，标题格式为 `Agent长输入-{hash}` 或 `Agent长输入-{hash}-第NN部分`
   - 导入后的资料会进入 `knowledge.db` 的资料库索引，本轮 `reference_filenames` 会优先携带这些标题；路由、规划、brainstorm、技能整理和执行轨迹继续使用压缩文本和资料引用，不直接把完整长文本送进模型上下文
   - 导入成功会通过 `project_updated` 和结果里的 `project_detail / changes` 返回给前端；如果全部候选段都被判定为不适合进入小说资料库，本轮只返回跳过提示，不创建 `Agent长输入-*` 资料；不会静默写入外部 Obsidian Vault

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
- `review_knowledge` 已继承目标章节时，契约里的资料数量按该章节可用的 Obsidian 笔记统计，不用全局笔记数误判当前章节资料状态

模型路由和模型规划会读取 Agent 自学习能力上下文。这个上下文包含 Obsidian 维护摘要和维护建议；明示第 N 章、下一章或当前选中章节时，摘要会按目标章节可见维护项重新统计，建议明细也只给模型对应章节可见的内容；章节任务摘要会带上目标章节可见笔记的考据来源；如果同一句话同时提到参考章节和生成、改稿、拆场或诊断目标，能力上下文优先跟随动作目标章节；整书架构和后续规划任务保留全书视角；没有明确目标章节的非架构任务只保留全局维护摘要，不把后段建议标题、建议路径或动作交给模型。

契约检查不满足时，workflow action 会记为 `BLOCKED`；执行中异常记为 `FAILED`；长时间无确认或无心跳的旧 workflow 可以被标记为 `TIMED_OUT` 或 `STALLED`。

章节写回类 action 会把保存后的章节核验结果一并写入执行反馈：

- `chapter_generate`、`chapter_workflow` 的 draft 模式、`rewrite_chapter` 会在写回正文后读取章节核验报告
- `chapter_generate` 会按作品目标字数和当前章节长度计算目标容量；用户要求完整章、技能库章节生成未指定目标字数、架构完整且未要求短稿或具体字数时直接说“继续写第一章”，或目标超过单次安全长度时，会交给生成链路按章节容量规划小节并逐节审校。若模型单节写短，后端会按保存前的实际正文长度继续追加小节，直到接近目标容量或达到安全次数上限。
- `rewrite_chapter` 写回后会按保存后的正文长度、用户字数要求和项目单章均值复算章节容量；重写、改写、定稿整章时如果保存正文低于完整章容量，会从当前正文末尾自动扩写。如果剩余缺口超过 5500 字，会把完整缺口交给小节生成流程，而不是只请求一个短段落。补足过程中任一请求失败，或最终仍未达到容量阈值，都会恢复当前改稿开始前的正文，避免把不合格短稿或半截扩写留在章节里。去 AI、短稿、片段、开头等明确短文本请求不会触发扩写。
- 字数识别会区分目标和状态描述；“写 15000 字”“远低于 15000 字目标”会作为目标，“当前正文约 3870 字”“保存校验：当前正文约 3870 字”不会作为用户目标。
- 如果模型把短稿描述成完整章，执行反馈会过滤“约 15000 字”“完整章节”等未经验证的修改说明，并把 `saved_word_count / length_target_words / length_status / length_completion_*` 写入产物 `metadata`
- 核验分数、状态和摘要会进入 `changes`、回复正文和产物 `metadata`
- 核验报告包含 `Obsidian 设定` 维度。已启用 Obsidian 时，后端会先按目标章节过滤笔记，再检查正式笔记里的 `forbidden_phrases / 禁止出现` 和 `required_phrases / 必须出现`；禁用短语只要出现在正文里，即使正文没有出现笔记标题，也会成为高风险问题。正文提到笔记、共享连续性证据命中笔记，或少量连续章节范围明确绑定的笔记缺少必需短语时，会成为警告问题。Obsidian 核验签名按目标章节可见笔记计算，未来章节专用笔记变化不会让早期章节核验标记为过期
- 若核验状态为 `risk`、总分低于配置阈值，或章节核验发现 Obsidian 必写 / 禁写、章节连续性合同、项目记忆规则这类必须修订问题，后端会按核验问题自动修订，重新写回正文后再次生成核验报告
- 自动修订默认启用，默认阈值为 65，默认最多 2 轮；可在 AI 写作设置里关闭、调整触发分数或把最多修订轮数调到 0 到 3
- 自动修订结果会进入回复正文、`changes` 和产物 `metadata`，包括是否尝试、是否写入、修订摘要、修订项和复查结果
- 章节生成、draft 写回或改稿写回后，如果当前保存生成或更新了 Obsidian 维护草稿，Agent 会追加 `obsidian_maintenance` 产物，列出相关待审草稿、状态和路径，并把“已生成第 N 章相关 Obsidian 维护产物”写入 `changes`；前端产物卡片可打开 Agent 自学习面板，并按来源章节和产物里的 `suggestion_ids` 定位对应维护项
- 核验失败时，章节正文仍会保留，但执行结果会明确返回失败原因，并给出重新运行章节核验的建议
- 核验失败不会触发自动修订，因为这时没有可靠的问题清单

### 3. Planner

现在后端入口不再先跑 `_heuristic_route()` 再决定 intent，而是：

1. 用模型根据项目状态和末尾对话直接产出 plan JSON
2. 本地把 plan 里的 action 转成系统内的 `AgentPlanAction`
3. 本地补依赖、校验章节目标、校验可执行性
4. 再交给统一 executor 执行

本地规则还保留，但角色已经变了：

- 模型不可用时的回退
- 计划结果不合法时的备用处理
- 本地约束校验

不再作为主路由。

章节生成计划会按同一计划内的动作顺序解析章节目标：如果第一步会生成一个新章节，后续同一计划里的去 AI、润色或一致性检查可以指向这一步生成的章节。这样“写第一章”这类计划不会因为执行前还没有既有已写章节而被拒绝。

章节范围正文生成会在本地再次校验。用户要求“写第 58 到 60 章正文”这类 2 到 3 章范围时，规划器应给出每章独立动作；如果模型只返回一个 `chapter_generate` 或 `chapter_workflow(mode=draft)`，后端会按章节范围展开成多个生成动作。模型不可用时，本地规则也会识别这类范围指令。超过 3 章的直接正文生成请求会返回提示，要求分批处理或先整理章节蓝图，避免计划缩水成单章。

之前也修了一个实际误判：

- 像“把资料库的资料分析完，再重新弄续写架构”这种混合指令
- 现在会优先规划成 `review_knowledge -> generate_architecture`
- 不会再因为句子里有“续写”两个字就跳去写下一章

章节目标明确时，`review_knowledge` 不只读取资料库和章节安全的 Obsidian 笔记，也会读取同一目标章节的 `build_project_context_bundle()` 输出。资料分析模型能看到章节任务卡、章节合同、Obsidian 待审软约束和项目学习版文风 / XP；如果第 58 章分析后又执行第 59 章正文动作，后端会为第 59 章重新生成资料摘要，避免不同章节的约束混用。

`review_knowledge` 和后续章节生成会读取统一项目知识索引。这个索引现在包含架构文件、章节正文、资料库和可选 Obsidian Vault 笔记；Obsidian 来源在检索结果里标成 `Obsidian`，并保留笔记标题、相对路径、摘要、关键词、标签、可解析外链、反向链接、未解析链接、歧义链接、设定约束和章节范围。章节生成的检索语句会合并目标章节标题、人物、道具、地点、时间限制、当前章尾段和上一章尾段；批量生成后续章节时，上一章刚保存的事实会进入下一章的 Obsidian 选择、连续性证据包和叙事状态账本。Obsidian 选择评分会参考笔记里的 frontmatter、正文内联属性、摘要、关键词、双链、Markdown 内链、章节范围、剧透边界、必需 / 禁止短语和中文词组重合度；明确绑定目标章节的笔记会提高选择优先级，只有 `reveal_after_chapter`、`#剧透/57` 或 `#第57章后可用` 的笔记在目标章节开放后也会获得章节相关性权重。章节范围既可来自 frontmatter、`chapter_range:: / reveal_after_chapter::`、`[chapter_range:: 58-60]`、`(reveal_after_chapter:: 57)` 内联属性，也可来自 `chapter_range: 58+`、`chapter_range:: 第59章以后` 这类开放范围，正文里的“适用章节”行或 `#章节/58-60`、`#第58章`、`#第58章起`、`#Ch58-60`、`#Ch58+`、`#剧透/57`、`#第57章后可用` 这类 Obsidian 标签；frontmatter 字段名支持大小写、空格、连字符和下划线等常见属性写法，`summary / description / abstract / keywords / search_terms / 关键词` 等摘要 / 检索词 Properties 以及 `summary:: / keywords::`、`[summary:: ...]`、`(keywords:: ...)` 内联属性会进入知识索引、笔记选择和章节安全预览；`source_notes / related_characters / related_notes / depends_on / foreshadows / payoffs / reveals / related_locations / related_props / related_organizations` 等字段在 frontmatter 或正文内联属性里都会进入图谱关系，并保留依赖、伏笔、兑现、揭示、相关地点等关系语义。章节上下文只显示目标章节可见的关系目标，不会因为可见笔记的 `foreshadows` 等字段提前暴露后段笔记标题；当前笔记正文或摘要里指向未来笔记的 `[[双链]]` 或 Markdown 内链会改写为“未开放设定”，真正缺失或歧义的双链仍会作为图谱注意项出现。章节上下文、知识检索、任务蒸馏、连续性证据包、叙事状态账本和章节核验会按目标章节过滤未来笔记，检索预览、证据正文、反向关联和来自 Obsidian 的任务蒸馏摘要也按目标章节处理；有目标章节时，知识检索和证据检索会先读取更大的候选池再按章节过滤，章节上下文内部调用知识检索时也会传入目标章节，Obsidian 检索命中如果无法对应到当前总览里的可见笔记，会被丢弃，防止旧索引绕过范围过滤，也防止后段笔记数量太多时压掉当前章节资料；技能库和架构总览里的知识检索会把当前选中章节传给后端，联网考据也会把当前选中章节传给后端，并用章节安全的本地资料命中生成考据提示，因此前端预览、联网考据和写作上下文使用同一套章节边界；命中的笔记会进入“本章 Obsidian 设定检查清单”，列出来源、适用章节、必写项、禁写项、关联笔记、关系语义和图谱注意项；命中的约束会进入“本章 Obsidian 写作约束”，比普通资料摘要更直接地影响本章生成。叙事状态账本的章节任务卡会携带目标章节可见的 Obsidian 来源、必写项、禁写项、图谱风险和执行状态，已有正文时会记录已满足必写项、未完成必写项和已触犯禁写项；缺失或触犯项会转成后续章节可见的高优先级叙事债务，修订满足后关闭；模型叙事编辑生成下一章合同时会读取当前章和下一章的 Obsidian 约束。若 `review_knowledge` 后面紧跟章节生成、改稿或一致性检查，它会继承后续章节作为 Obsidian 过滤范围；没有可用蒸馏摘要时，资料分析模型读取的 Obsidian 笔记也会按任务说明和目标章节选择，避免大 Vault 中的当前章专用笔记被文件顺序挤出。若后面是整书架构，则保持全书资料视角。多章执行时，资料摘要按目标章节隔离：`review_knowledge` 先继承第一个后续章节，后续 `chapter_generate`、`chapter_workflow(mode=draft)`、`rewrite_chapter` 或 `consistency_check` 如果指向另一个章节，会重新调用章节安全的资料分析，并把结果缓存给该章节的后续动作。

正文标签、章节标签和文件名 / 路径里的区间分隔符支持半角连字符、波浪线、中文全角波浪线、长横线和“至 / 到”。作者写 `#第58～60章`、`#Ch58～60`、`#适用章节／40～42`、`第58～60章-计划.md` 或 `ch58～60-plan.md` 时，Agent 资料分析、章节生成、检索预览、证据正文和章节核验都会按对应章节范围过滤。

Obsidian 路径过滤按大小写不敏感匹配。默认 `.obsidian/**`、`.trash/**` 和 `templates/**` 会同时排除 `.OBSIDIAN/`、`.Trash/`、`Templates/`；作者自定义 `drafts/**` 时也会匹配 `Drafts/`，避免模板、插件状态和草稿目录进入 Agent 资料分析、章节上下文或连续性证据包。候选笔记超过 `max_notes` 时，系统会先按 Vault 相对路径稳定排序再应用数量上限，并把未同步候选数量写入同步警告，避免大 Vault 因文件系统遍历顺序不同而得到不同资料集；候选总数和 `max_notes` 会进入来源签名，让界面的 skipped 和警告随 Vault 增删更新。

Obsidian AI 可见性判断会同时识别正向和反向属性 / 标签。`usable_by_ai / ai_usable / AI可用 / 可供AI使用 / 可供模型使用 / 写作可用` 或 `#AI可用` 为真时视为可用；`no_ai / not_for_ai / exclude_from_ai / AI不可用 / 不供AI使用 / 不允许AI使用 / 勿用AI`、`#no-ai` 或 `#AI不可用` 为真时排除笔记；`no_ai: false` 或 `AI不可用: 否` 视为明确可用。Markdown frontmatter、正文内联属性、正文标签、HTML details 正文内联属性 / 标签和 Canvas 文本节点属性使用同一规则；HTML details 正文声明不可用于 AI 或声明过滤状态时只排除该折叠块，因此作者不必把所有 Vault 笔记改成同一个英文字段。

Obsidian 状态过滤会读取显式状态别名、布尔状态 Properties、标签和目录。`status: 正式设定 / official / final` 会视为正式可用状态，`status: wip / archived` 会视为过滤状态；笔记没有显式 `status / 状态` 字段时，`canonical: true / published: yes`、正文或 Canvas 文本节点 `canonical:: true` 视为正式可用状态，`draft: true / private: true / archived: true`、正文或 Canvas 文本节点 `draft:: true` 视为过滤状态；缺少显式状态和布尔状态时，`#canonical / #正式 / #已发布` 或 `正式设定/`、`Published/` 等标签 / 目录视为正式可用状态，`#draft / #草稿 / #private / #私密 / #废案` 或 `Drafts/`、`草稿/`、`Private/` 等标签 / 目录视为过滤状态；显式 `status` 字段优先，不被布尔属性、标签或目录覆盖。

章节化证据检索会在 Obsidian 命中替换成目标章节安全内容后再次检查查询词。只命中未来标题、双链、Markdown 内链、关系字段小节引用或已知未来笔记纯文本标签的候选不会进入连续性证据包，避免资料分析看到无关的“未开放设定”证据。

章节安全内容也会处理 Obsidian 元数据字段。`tags / aliases / keywords / required_phrases / forbidden_phrases` 里的未来双链、Markdown 内链或已知未来笔记纯文本标题 / 路径名 / 文件名会被改写为“未开放设定”，因此标签预览、“本章 Obsidian 写作约束”和“本章 Obsidian 设定检查清单”不会因为元数据提前显示后段笔记标题。

章节安全内容还会处理图谱关系标签。Canvas 边或正文关系小节生成的关系目标即使对当前章节可见，关系标签里提到的未来笔记名、双链或 Markdown 内链也会改写为“未开放设定”，避免“本章 Obsidian 设定检查清单”通过关系名提前暴露后段信息。

章节安全内容会保留安全的图谱风险。目标章节可见笔记里的未解析双链，以及只涉及目标章节可见笔记的歧义双链，会继续进入“本章 Obsidian 设定检查清单”；歧义名称如果同时命中后段不可见笔记，则不会在早期章节显示。

目标章节可见的 Obsidian 剧情债务和人物弧线笔记会进入 Agent 路由 / 规划上下文、叙事状态账本提示、章节任务卡和模型叙事编辑输入。路由 / 规划模型会看到目标章节可见的 Obsidian 来源、章节计划、必写项、禁写项、剧情债务、人物弧线和图谱风险；章节保存后，自学习面板最新章节任务卡会展示这些 Vault 债务和人物弧线条目，作者能看到当前章引用了哪些外部状态。剧情债务笔记只写 `debt_content / debt_status / risk_level / expected_payoff_range / next_required_action / related_characters`，或人物弧线笔记只写 `character / phase / current_state / unresolved_pressure / required_next_check` 时，这些 Properties 也会进入知识索引、账本和任务卡；系统生成的债务 / 人物状态草稿发布后也按这些结构化字段读取，人物状态草稿会带 `人物状态` 标签。

Obsidian frontmatter 数组会按 YAML flow sequence 解析。`aliases: ["潮师, 守账人"]`、`keywords: ["旧船队, 暗账"]` 和 `required_phrases: ["潮声异常, 不得提前解释"]` 会保留引号里的逗号，避免把一个别名或写作约束拆成多项；普通列表型 Properties 和正文内联属性支持按逗号、顿号、半角分号和中文分号维护多值。

Obsidian 笔记没有显式 `type / kind / 类型` 时，系统会按常见目录或标签推断类型。作者只把文件放在 `Characters/`、`Locations/`、`Plans/`、`Debts/`、`CharacterArcs/`、`Style/`、`XP/` 等目录，或只写 `#人物/主角`、正文 `#人物／主角`、`#章节计划/58`、`#剧情债务/伏笔` 这类层级标签时，Agent 能力上下文、章节任务摘要、文风 / XP 参考和图谱预览仍能看到人物、地点、章节计划、剧情债务、人物弧线、文风规则或 XP 规则；作者写了 type 时以作者字段为准。Obsidian 多选 Properties 里的 `type: [主角, 人物]`、`type: [临时, 章节计划]` 会扫描整个列表并识别系统已知类型，完全未知的显式 type 会保留原值。

章节计划类层级标签也会绑定章节范围。作者只写 `#章节计划/58`、`#章节合同/58-60`、`#场景卡/59` 或 `#scene-plan/59` 时，Agent 资料分析、章节任务摘要和下一章合同输入都会按标签里的章节过滤，不需要额外维护 `chapter_range`。

Obsidian frontmatter 多行文本会按 YAML block scalar 解析。作者用 `summary: >`、`description: |` 写出的多行摘要会进入知识索引、笔记选择和章节安全预览；`keywords / source_notes / required_phrases` 等列表型字段用多行文本书写时，会按行进入检索词、图谱关系和写作约束。

Obsidian frontmatter 行尾注释不会当作字段值。`status: canonical # 正式设定`、`chapter_range: 58-60 # 中段`、缩进列表项后的 `# 说明` 会去掉注释后再参与解析，避免状态过滤、章节边界和写作约束被注释文本污染；引号里的 `#` 和双链 heading 会保留。

Obsidian 标签属性和正文标签会按常见 Vault 写法拆成单个标签。`tags: "#人物 #第58章 #剧透/57"`、`tags: #章节/44-45 #剧透/43`、多行 `tags: - #人物/配角`、`tags: 人物 主角`、`tags: "人物；第58章"`、`tags:: #支线 #第59章`、正文 `#人物／主角 #适用章节／40～42 #剧透／39` 会去掉前导 `#` 后参与标签展示、类型推断、章节范围、剧透边界、知识检索和章节上下文选择；别名、关键词和必写 / 禁写短语仍按各自字段规则解析，不会因为空格被拆成碎片，非标签字段里的 `#` 仍按行尾注释处理。

Obsidian 关系字段里的 Markdown 内链会保留关系语义。作者在 frontmatter 或正文内联属性里写 `source_notes: "[当前线索](Clues/当前线索.md)"`、`related_characters:: [林追](../Characters/林追.md)`、`[林追](/Characters/林追.md)` 时，系统会按当前笔记路径、同目录相对路径或 Vault 根路径解析链接，并生成 `来源笔记 -> ...`、`相关人物 -> ...`、可解析链接和反向链接。这样作者不必把所有关系都改成双链写法。

可见 callout 里的任务列表会进入同一套 Obsidian 上下文。作者在普通 `note / info` callout 里写 `> - [ ] status:: canonical`、`> - [!] source_notes:: [[当前线索]]`、`> - [?] required_phrases:: 潮声异常`，或在 `> ## 必须包含`、`> ## 禁止出现` 下写任务项，系统会把它们当作正文内联属性、图谱关系和写作约束处理；`[!] / [?] / [>] / [/] / [-]` 这类常见 Obsidian Tasks 状态也会识别，隐藏 callout 里的同类内容仍会被排除。

Markdown 表格会进入章节合同和图谱上下文。作者把第 58 章计划写在 Markdown 笔记、Canvas 文本节点或普通 `note / info` callout 里，列名包含 `章节目标 / 必须节拍 / 禁写动作 / 验收项 / 证据来源 / 相关人物` 时，系统会把单元格转成现有上下文行；单元格里的 `\|` 会还原为普通 `|`，例如验收项可以写成 `选择A\|选择B` 而不污染章节提示。表格里的链接进入图谱；目标是未来笔记时，章节安全内容仍会隐藏标题、路径和关系目标。

YAML 对象列表和顶层嵌套对象也会进入章节计划上下文。作者把 `scenes / required_beats / character_checks / debts_to_advance` 写成 `- goal: ...`、`conflict: ...`、`payoff: ...` 这类多字段对象，写成单独 `-` 后换行维护对象字段，或用 `required_beats: [{goal: ..., evidence_sources: [{source_note: ...}]}]`、`- {goal: ..., payoff: ...}` 这类 YAML flow mapping 时，系统会保留对象字段并转成章节目标、节拍、人物检查或债务推进行；对象字段值可以用 `goal: >`、`reason: |` 这类 YAML block scalar 维护多行场景目标、理由或验收说明；场景项里再嵌套 `character_checks / evidence_sources` 这类对象列表时也会继续解析，嵌套列表同样支持单独 `-` 后换行写对象字段。作者也可以用 `chapter_contract:` 包住 `chapter_range / objective / required_beats / acceptance_checks / evidence_sources`，系统会保留对象分组并读取这些直接子字段。对象里的双链和 Markdown 内链会进入链接、反向链接和图谱关系统计，未来笔记仍按目标章节隐藏。

Markdown 内链目标里的英文括号会按文件名处理。作者用 `[林追旧档](../Characters/林追(旧).md)` 区分同名或旧版资料时，系统不会在第一个 `)` 截断链接；如果括号文件名指向未来笔记，资料分析、检索预览和证据正文仍会按目标章节隐藏。

Markdown 内链目标里的转义字符和 title 会按链接语义处理。作者用 `[林追旧档](../Characters/林追\(旧\).md "旧档")` 或 `[终局答案](../Secrets/未来真相 "终局")` 时，系统会先还原转义文件名、去掉 title，再进入图谱、反向链接、资料分析和章节安全处理。

Markdown 引用式链接也会进入 Obsidian 图谱。作者把正文写成 `[林追旧档][old]` 或快捷引用 `[林追旧档]`，并在同一笔记定义 `[old]: ../Characters/林追\(旧\).md "旧档"` 或 `[林追旧档]: ../Characters/林追\(旧\).md "旧档"` 时，系统会把引用定义解析成目标笔记，保留关系小节语义；如果 `[future]: ../Secrets/未来真相 "终局"` 指向未来笔记，正文引用和定义行都会按目标章节隐藏。Markdown 脚注 `[^id]: ...`、缩进续行和正文脚注标记不进入 Obsidian 知识图谱、资料分析或章节上下文。

HTML `<a href="...">` 链接会按 Markdown 内链进入 Obsidian 图谱。作者从网页或插件粘贴 `<a href="../Characters/林追.md">林追</a>` 时，系统会生成可解析链接、反向链接和关系语义；如果目标是未来笔记，正文标签和路径会按目标章节隐藏；如果目标是本地 PDF、图片或音频附件，则按附件过滤。

Obsidian 双链也支持 Vault 内相对路径和根路径。作者在子目录笔记里写 `[[../Characters/林追]]`、`[[./当前线索]]`、`[[Clues/../Characters/林追]]`、`[[/Characters/林追]]` 时，系统会按来源笔记路径和路径段解析到目标笔记，并让图谱关系、反向链接、资料分析、检索预览和证据正文共用同一套章节安全处理；相对路径指向未来笔记时，不会在早期章节暴露目标标题或别名。

Obsidian 双链目标会先做 URL 解码。`[[Characters/林%20追]]`、`[[../Secrets/未来%20真相]]` 会按解码后的 Vault 路径参与图谱关系、反向链接、资料分析、检索预览和证据正文；目标是未来笔记时，早期章节仍不会看到未来标题、路径或别名。

URL 编码里的保留字符会作为路径内容处理。`[[Characters/林%23追]]`、`[线索](Secrets/未来%5E真相.md)` 不会被误拆成 heading、query 或 block 引用；解析后的真实目标继续进入章节安全判断，所以未来笔记仍会在早期章节隐藏。

越出 Vault 的相对目标不会进入图谱。根目录笔记里的 `[[../Outside/旧设定]]`、`[[Clues/../../Outside/旧设定]]`、`[[/../Outside/旧设定]]`、`[外部](/../Outside/旧设定.md)` 会被视为非 Vault 知识链接，不会生成未解析链接或维护建议；子目录里回到 Vault 内部的 `../Characters/林追.md` 仍会解析。

Obsidian 块引用会按笔记级链接进入统一知识索引。`[[当前线索^block-id]]`、`[[当前线索#小节^block-id]]` 会指向 `当前线索`，参与图谱链接、反向链接和章节安全处理；块引用目标对当前章节不可见时，资料分析、检索预览和证据正文仍会隐藏未来标题。

Obsidian 同笔记内部链接不会进入跨笔记图谱。`[[当前线索#内部索引]]`、`[[当前线索^scene-a]]`、`[回看](当前线索.md#内部索引)` 这类目标仍是当前笔记的链接，会从 links、resolved_links、backlinks 和 graph_relations 中排除，避免目录、heading 和 block 导航影响资料选择、图谱统计和维护建议。

正文关系小节也会进入统一知识索引。作者在 `## 来源笔记`、`## 相关人物`、`## 伏笔`、`## 兑现` 等小节下列出的 `[[双链]]`，以及 `相关地点：[[旧码头]]` 这类关系行，会生成图谱关系、可解析链接和反向链接；章节上下文仍按目标章节隐藏不可见的关系目标。

Obsidian 注释、代码片段、删除内容和隐藏 details 不会进入统一知识索引的 AI 可见正文。Markdown 和 Canvas 文本里的 `%%...%%`、Markdown HTML 注释 `<!-- ... -->`、fenced code block、inline code、Markdown 删除线、HTML 删除标签和隐藏 HTML details 不参与正文内联属性、双链、标签、关系小节、必写 / 禁写、章节范围、检索预览或章节上下文解析，作者可以把临时想法、模板、废弃设定和后段剧透放在这些区域。

Obsidian 隐藏 callout 不进入统一知识索引的 AI 可见正文。`> [!spoiler]`、`> [!future]`、`> [!private]`、`> [!hidden]`、`> [!draft]`、`> [!todo]`、`> [!no-ai]` 以及 `> [!剧透]`、`> [!未来]`、`> [!隐藏]`、`> [!私密]`、`> [!草稿]`、`> [!待定]`、`> [!勿用]`、`> [!不引用]` 里的双链、标签、正文内联属性、关系小节和必写 / 禁写项都会被排除；同一引用块内后续 `> [!note]` 仍视为隐藏内容，结束引用块后重新开始的普通 `> [!note]`、`> [!info]` 才作为正文参与图谱和章节上下文；普通 callout 里嵌套的隐藏 callout 只排除嵌套块，外层公开内容仍会同步。

Obsidian 隐藏 HTML details 不进入统一知识索引的 AI 可见正文。`<details>` 的 `summary` 或 `class` 等属性带 `spoiler / future / private / hidden / draft / todo / no-ai`，或带 `剧透 / 未来 / 隐藏 / 私密 / 草稿 / 待定 / 勿用 / 不引用` 时，整段折叠内容里的双链、标签、正文内联属性、关系小节和必写 / 禁写项都会被排除；折叠正文里写 `no_ai:: true`、`AI不可用:: 是`、`#no-ai`、`#AI不可用`、`draft:: true`、`private:: true`、`archived:: true` 或过滤状态时，也只排除该折叠块；普通公开 details 仍作为正文参与图谱和章节上下文。

Obsidian 嵌入语法会区分笔记和附件。`![[当前线索]]`、`![[关系图.canvas]]` 会继续作为可解析知识关系，并记录到 `embedded_links`；章节上下文会把目标章节可见的嵌入笔记显示为短预览，让章节计划、场景卡或合同嵌入直接进入写作提示。`![[旧地图.png]]`、`![[访谈.pdf]]`、Markdown 图片、HTML 媒体标签、`[访谈PDF](资料/访谈.pdf)` 和 `[访谈PDF][ref]` / `[ref]: 资料/访谈.pdf` 这类本地附件链接不会进入图谱关系、未解析链接、反向链接、检索预览或章节上下文，避免附件文件名制造图谱噪声；未来笔记嵌入不会在早期章节预览里显示。

Markdown 笔记和 Canvas 的 HTTP(S) 考据入口会写入 `external_links`，Markdown 链接标题、HTML `<a>` 文本、Canvas link 标签和结构化来源名会写入 `external_references`。支持 `source_url / reference_links / research_links / external_links / references / sources / citations / url / 资料链接 / 资料来源 / 参考链接 / 参考资料 / 考据链接 / 考据来源` 等 Properties、正文内联属性、Markdown 外部链接、引用式链接定义、裸 URL、HTML `<a>` 和 Canvas link 节点 HTTP(S) URL；同步状态会计算 `external_link_count`，章节上下文会在 Obsidian 来源行和设定检查清单里优先显示“考据来源”。目标章节可见的考据来源还会进入任务蒸馏材料备注，`external_references / external_links` 变化会改变项目蒸馏签名，让 Agent 资料分析和后续章节任务读取更新后的来源说明。外部 URL 不会写入 Vault 内部 links / backlinks / graph_relations，也不会生成未解析链接维护建议。

Obsidian Canvas 默认进入同步范围，路径规则包含 `**/*.canvas`。Canvas 文本节点可用 `title / 标题 / name / 名称` 声明笔记标题，模型看到的同步摘要、知识检索结果和章节上下文都会使用这个标题；未声明时使用文件名。Canvas link 节点的 HTTP(S) URL 会作为外部考据入口进入 Canvas 正文、知识检索和章节上下文，但不会写入 Vault 内部 links / backlinks；Canvas link 节点的 `obsidian://open` / `obsidian://advanced-uri` URL 会作为 Vault 内部链接进入可解析链接、反向链接和图谱关系，并在 Canvas 正文里列为内部链接节点；没有 `label / text` 的内部 URI link 节点会用目标笔记名作为 Canvas 边关系标签。Canvas file 节点会作为可解析链接进入 backlinks，`../Clues/当前线索.md` 这类相对 file 路径会按 Canvas 所在路径归一化；file 节点的 `subpath` 或文件路径里的 `#小节` 会进入 Canvas 正文和章节安全上下文，但内部 links / backlinks 仍按笔记文件记录。Canvas 边会保留为关系语义；Canvas group 分组会按画布坐标识别内部节点，分组标题和分组内 file 节点关系会进入图谱关系和章节上下文；Canvas 文本节点中的章节范围、剧透边界、必写和禁写短语会进入同一套章节上下文。Canvas 会按节点隔离 AI 不可用内容，带 `no_ai:: true`、`#no-ai`、`AI不可用:: 是`、`draft:: true` 或过滤状态的文本 / group 节点会被排除，隐藏 group 内部节点也会排除，`no_ai:: false` 这类明确可用声明不会误删公开节点，同一张画布里的公开节点仍会同步。目标章节不可见的 file 节点、小节、Canvas 内部链接节点和 URI 关系会在章节安全内容里隐藏，指向这些未来节点的边标签、link 标签和分组关系会改成中性提示；边目标或分组目标可见但关系标签写到未来笔记名时，也会改写为“未开放设定”，避免人物关系图或线索图提前暴露后段设定。

Obsidian Markdown 和 Canvas 会从文件名或路径推断章节范围，例如 `第58章-线索.md`、`第59-60章-后续.md`、`Chapters/58/设定.md`、`chapter-61.canvas`。作者没有写 frontmatter 时，`review_knowledge`、章节上下文、知识检索、证据正文和章节核验仍会按推断出的目标章节过滤。

面向长篇逐章生产的正文写回计划会自动变成受监督流程：

- `chapter_generate` 或 `chapter_workflow(mode=draft)` 生成正文并写回章节
- `rewrite_chapter(mode=humanize)` 保留剧情事实、人物声音、伏笔和信息顺序，只处理模板腔、解释腔、套版画面、抽象情绪直说、潜台词解释、对白同质化和节奏过匀；完整章节修订稿明显短于原文时会拒绝本次结果
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
- `event_blocks` 给计划和阶段性事件；执行中前端按实时状态列表展示步骤，执行完成的历史消息不再展示 `event_blocks`
- `artifacts` 给结果产物和历史回看
- 写回章节后，如果章节核验报告可用，Agent 会把 `chapter_review` 作为产物返回，前端可以直接展示核验摘要、评分和问题数。
- 写回章节后，如果 Obsidian 维护队列因为当前保存产生了新草稿或更新草稿，Agent 会把 `obsidian_maintenance` 作为产物返回，前端可以直接展示待审草稿和目标路径，也可以从产物卡片打开按来源章节和 `suggestion_ids` 筛选后的维护队列。

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
<project-dir>/.gaoxia/learning/humanize_evolution_rules.json
<project-dir>/.gaoxia/learning/humanize_review_patrol.json
<project-dir>/.gaoxia/learning/style_xp_evolution.json
<project-dir>/.gaoxia/learning/narrative_state.json
<app-data>/skills/.usage.json
<app-data>/skills/.curator_reports.jsonl
<app-data>/skills/.versions/{skill_id}/versions.json
<app-data>/app_config.json              # review_model 存在这里
```

`style_xp_evolution.json` 来自章节保存后的正文统计和核验结果。技能库写回生成章或改稿章时会把当前 XP 预设作为 `xp_preset` 传给后端；章节保存响应会把最新 `self_evolution` 状态放在 `meta.self_evolution`，前端可用它立即更新自学习面板里的章节任务卡和 Obsidian 维护摘要。同一条文风或 XP 规则在两个不同章节重复出现后，会进入后续章节生成、改稿和蓝图任务的提示词；它的优先级低于作者明确要求、手工文风和手工 XP。目标章节明确时，项目级文风 / XP 提示和 Agent 路由 / 规划上下文还会读取该章节可见的 Obsidian 文风 / XP 笔记，识别 `type: style_rule / xp_rule`、`Style/`、`XP/`、`文风/`、`写作规则/` 和相关标签；作者只在 Properties 里维护 `style_rule / voice_rule / tone_rule / sentence_rhythm / imagery / dialogue_rule / avoid_style / examples / applies_to`，或 `xp_rule / precheck / postcheck / workflow / technique / avoid_xp` 时，提示构建会读取同步后的结构化正文，不只取摘要或短预览，因此长规则里的禁用写法、检查项和示例也能进入目标章节文风 / XP 参考。可见规则超过提示容量时，会按目标章节相关性优先保留专属规则，并在容量允许时保留文风和 XP 各自最相关条目，避免全局规则挤掉中后段章节规则。没有目标章节时，也会读取同步记录中无章节边界的全局规则，并排除带章节范围或剧透边界的后段规则。这些 Vault 规则只作为提示来源，不写入 `style_xp_evolution.json`，并按章节范围和剧透边界过滤。系统学习版文风 / XP 规则变为 `active` 后，如果没有匹配到 Vault 规则笔记，叙事状态账本会生成 `Style/` 或 `XP/` 低优先级 Obsidian 待审草稿，草稿带来源规则、来源章节、剧透边界、`source_ids`、`style_rule` 或 `xp_rule` Properties；发布前会在章节生成上下文和 Agent 规划上下文显示非正式文风 / XP 预览，作者发布后才进入 Vault 图谱和后续提示。发布后的规则笔记如果保留 `source_ids`，作者改名、移动或重写规则表达后，维护队列仍会识别为同一条系统学习规则。

`narrative_state.json` 来自章节保存后的叙事状态整理。它会记录剧情债务、人物弧线、章节任务卡、模型叙事审查、章节合同、Obsidian 维护建议和维护摘要；章节任务卡也会记录目标章节 Obsidian 必写 / 禁写约束的执行状态，未完成或触犯项会转成下一章可见的叙事债务。目标章节可见的 Obsidian 章节计划、场景卡和章节合同笔记会进入账本提示和模型叙事编辑输入；系统识别 `type: chapter_plan / scene_plan / chapter_contract`、`Plans/`、`Scenes/`、`章节计划/`、`场景卡/` 和相关标签，只接受明确绑定目标章节或窄范围章节的计划；这些笔记只写 Properties 时，`objective / required_beats / debts_to_advance / debts_to_protect / character_checks / style_checks / forbidden_moves / acceptance_checks / evidence_sources / risk_notes` 也会转成章节计划行。目标章节可见的 Obsidian 剧情债务和人物弧线笔记也会进入账本；系统识别 `type: narrative_debt / plot_debt / character_arc / character_state`、`Debts/`、`PlotDebts/`、`CharacterArcs/`、`剧情债务/`、`人物弧线/` 和相关标签，生成章节前作为上下文约束，章节保存后作为 `obsidian_debt` 或 `obsidian_arc` 来源保存在账本里，模型叙事编辑生成下一章合同时也会读取下一章可见的这些结构化条目；剧情债务笔记只写 `debt_content / debt_status / risk_level / expected_payoff_range / next_required_action / related_characters`，或人物弧线笔记只写 `character / phase / current_state / unresolved_pressure / required_next_check` 时，这些 Properties 会作为同等账本字段读取。启用 Obsidian 时，没有匹配到可用 Vault 笔记的剧情债务、人物弧线和图谱问题会生成维护建议，包含建议笔记路径、处理动作，以及带来源 ID、来源章节、相关人物字段、人物双链或来源笔记路径的 Markdown 草稿；剧情债务和人物草稿会按来源章节写入 `reveal_after_chapter`，剧情债务草稿同时写入 `debt_content / debt_status / risk_level / next_required_action`，人物状态草稿写入 `character / phase / current_state / unresolved_pressure / required_next_check` 并带 `人物状态` 标签，发布后按目标章节过滤，不会把后段自动维护笔记带入早期章节；维护摘要会统计待处理、高优先级、自动草稿、草稿缺失、Vault 笔记缺失、Vault 笔记已移动、Vault 待更新和已忽略数量，并列出优先处理项；重复出现的未解析双链会形成 `Graph/` 待审草稿并继承来源笔记的章节范围和剧透边界，来源章节范围不连续时会改用较晚可见的剧透边界，避免生成过宽章节范围，重名和歧义链接会形成修复提醒；已解析双链如果来源笔记可见范围没有被目标笔记可见范围覆盖，会形成章节范围不匹配风险；带未解析或歧义双链的笔记不会被计入孤立笔记；`build_agent_capability_context()` 会把维护摘要和未忽略的维护建议提供给 Agent 规划与路由，传入当前项目详情时会先刷新账本并可自动写入中高优先级待审草稿。中高优先级建议会在章节保存、Obsidian 同步或章节上下文生成时自动写入项目 `.gaoxia/obsidian_drafts/` 待审草稿；未人工改动的自动草稿会随图谱来源列表、来源内容和章节边界变化更新，人工改动过的草稿和保存草稿时遇到的既有人工内容不会被自动覆盖，同一路径建议即使 ID 变化也会沿用已有草稿状态，被忽略的同路径建议不会自动写草稿，也不会进入 Agent 优先处理项，恢复处理后会重新进入待处理和自动草稿流程，草稿文件缺失时会提示可重新保存，发布过的 Vault 笔记被移动或改名后会先按内容签名识别；新生成的维护笔记带 `gaoxia_maintenance_id`，发布到 Vault 前也会恢复缺失的身份字段，内容被作者改过但身份唯一匹配时也会改到新的 Vault 路径；没有唯一匹配或文件被删除时会提示可重新发布，自动发布内容被判定落后时会提示 Vault 待更新，自学习面板会把这些状态显示给作者；用户显式发布时写入配置的 Vault，发布会检查目标路径在 Vault 内且不覆盖已有笔记，并重新同步 Obsidian 摘要和知识库，让新笔记进入图谱解析，Graph 新笔记会按继承的章节边界控制可见范围。设置页保存了主模型 Key，或启用了第二审查模型时，章节保存后会让模型根据当前章节、项目文档和旧账本输出带证据的债务更新、人物弧线变化、合同执行回看和下一章章节合同；模型不可用时保留规则账本。后续章节生成前，`build_project_context_bundle()` 会把目标章节的章节合同、必须处理、可轻触、不要提前揭开的债务写入上下文，也会按目标章节把 Obsidian 待审草稿作为资料维护提醒写入上下文；带章节范围或剧透边界的草稿（包括作者手工改动后的草稿文件）不会进入范围外章节提示，草稿 frontmatter 字段名支持常见写法，并标明不能当作 Vault 正式设定引用。每条提醒会读取对应真实草稿并校验维护 ID / 类型；目标章节可见的 `create_chapter_note` 草稿会附带章节摘要、下一章交接和未完成必写项短预览；frontmatter 缺失时会改读正文小节；目标章节可见的 `create_chapter_contract_note` 草稿会附带合同目标、必须节拍、禁写动作和验收项短预览；目标章节可见的 `create_style_rule_note` / `create_xp_rule_note` 草稿会附带文风 / XP 规则、适用范围、检查项、证据数和置信度短预览。

模型叙事编辑写入的下一章章节合同如果还没有匹配到目标章节可用的 Vault 章节计划或章节合同，维护队列会生成 `Plans/` 待审草稿。草稿会记录 `type: chapter_contract`、目标章节 `chapter_range`、来源章节、合同目标、必须完成的节拍、债务推进、人物检查、文风检查、禁止动作、验收项、证据来源和 `source_ids`；作者发布前，目标章节待审草稿提醒会显示非正式合同预览，作者发布后，它会按 Obsidian 章节计划进入目标章节提示，同一合同不再出现在维护队列里。发布后的合同笔记保留 `gaoxia_maintenance_id` 或 `source_ids` 时，作者改写正文后仍按同一合同识别。已发布的 `chapter_contract` 会按合同小节或 Properties 整理为计划行，保证禁止动作、验收项等后半段内容仍进入目标章节提示；`evidence_sources` 会同时形成图谱关系和反向链接。

章节任务卡会保留目标章节可见的 Obsidian 剧情债务和人物弧线条目。自学习面板读取当前项目详情刷新任务卡时，也会刷新这些条目，让面板展示和实际生成上下文保持一致。Agent 规划阶段即使还没有保存过该章节任务卡，也会按目标章节临时构建 Obsidian 任务摘要，避免到写作阶段才发现 Vault 约束。

剧情债务和人物状态维护草稿会写入 `source_ids`。剧情债务草稿还会写入 `debt_content / debt_status / risk_level / next_required_action`，人物状态草稿会写入 `character / phase / current_state / unresolved_pressure / required_next_check` 并带 `人物状态` 标签。作者发布到 Vault 后，即使把笔记改名、移动或改写标题，只要保留来源 ID，维护队列仍会识别为同一条账本来源，不会重复生成同一条债务或人物状态建议。

待审草稿的章节提示会读取项目 `.gaoxia/obsidian_drafts/` 中真实草稿文件的 frontmatter。待审草稿 frontmatter 复用正式 Vault 笔记同一套 YAML 解析：作者手工改成 `required_beats: [{goal: ...}]`、`- {action: ...}`、`objective: >`、多行 `tags:` 或带行尾注释的写法时，章节范围过滤和非正式短预览仍会读取真实结构化字段。作者手工加入 `tags: [第58章起, 剧透/57]`、`tags: [Ch58+]`，或保留系统生成的多行 `tags:` 列表时，系统会合并标签并按正式 Obsidian 笔记相同的标签章节范围和剧透边界过滤；早期章节不会看到范围外的草稿提醒。对于 `create_chapter_note` 草稿，系统还会从 frontmatter 读取 `chapter_summary / handoff_to_next / obsidian_required_missing`，生成非正式短预览；frontmatter 被作者删除时，会改读正文里的“章节摘要 / 下一章交接 / 未完成的 Obsidian 必写项 / 章节正文摘录”小节。目标章节可见的 `create_chapter_note`、`create_chapter_contract_note`、`create_style_rule_note` 和 `create_xp_rule_note` 会额外进入单独的“Obsidian 待审软约束”区，用更短的结构化提示给正文生成和 Agent 规划使用，但仍明确标记为非正式、低优先级资料。Studio `brainstorm` 在传入目标章节时，也会复用同一套章节安全上下文、待审软约束和项目学习版文风 / XP 提示，不再只靠手工拼接的摘要块讨论。

Agent `review_knowledge` 继承目标章节时，同样会读取这套章节安全上下文、待审软约束和项目学习版文风 / XP，用于资料分析模型提示和无额外资料时的返回文本。

如果项目内待审草稿文件缺失，章节生成上下文不会只凭建议路径显示草稿；系统会改读维护项里的 `source_chapters` / 正文“来源章节”，按最晚来源章节判断是否写入目标章节提示。

如果作者手工删除待审草稿 frontmatter，系统也会继续扫描正文里的 `source_chapters::` 或“来源章节：...”，避免无 frontmatter 草稿被当成全局维护项。

已保存章节没有可用 Obsidian 章节档案时，账本会生成 `ChapterNotes/` 待审草稿。草稿记录章节摘要、来源章节、来源正文签名、来源笔记、相关人物、相关地点 / 道具 / 组织、Obsidian 执行状态、下一章交接和正文摘录，frontmatter 使用 `type: chapter_note`、`chapter_index / chapter_title / chapter_summary / handoff_to_next / chapter_excerpt / obsidian_required_satisfied / obsidian_required_missing / obsidian_forbidden_violations`、`source_ids`、`source_chapter_hash`、`source_notes`、`related_locations / related_props / related_organizations` 与 `reveal_after_chapter` 控制章节回顾、下一章交接、Obsidian 要求执行状态、来源正文版本、来源关系、图谱关系和后续可见范围；`source_notes` 会包含本章命中的 Vault 笔记、章节计划、剧情债务和人物弧线来源，但不引用其它章节档案；正文会列出本章 Obsidian 章节计划、剧情债务、人物弧线和下一章交接；显式发布后才写入 Vault，并重新同步到知识索引。未发布前，目标章节可见的 `create_chapter_note` 草稿也会在章节生成上下文和 Agent 规划上下文显示短预览，帮助后续章节承接上一章摘要、交接和未完成必写项，但提示仍按待审资料处理。发布后的章节档案如果保留 `source_ids`，作者改名、移动或重写标题后，系统仍会按来源章节控制可见范围，并识别为同一章档案。作者只用 `chapter_title / chapter_summary / chapter_events / state_changes / handoff_to_next / chapter_excerpt` 维护章节档案时，这些 Properties 也会进入知识索引、章节上下文、Agent 能力上下文和账本里的“Obsidian 章节档案”提示；章节核验会检查明确指向当前章的强制类交接提醒，缺少可核验关键词时作为 Obsidian 必需设定问题处理；系统自动草稿里的关注类交接只进入上下文。

自动章节档案草稿没有人工改动时，会随章节正文变化刷新；章节标题变化时迁移到新的 `ChapterNotes/` 文件名并移除旧自动草稿。人工改动过的章节档案草稿保留原文件和状态，不会被自动覆盖。自动发布过的章节档案在章节正文或标题变化后会进入 Vault 待更新状态，且不会把已发布的章节档案当成本章来源笔记引用自己。同步器会读取 `source_chapter_hash`，即使本地维护动作记录缺失，也能识别由系统生成但对应旧正文的章节档案；同步器也会读取章节档案保留的 `source_ids`、`source_chapters`、`章节来源 / 来源章` 和正文“来源章节 / 来源章”，把来源章节保存到 `ObsidianNoteSummary` 和知识内容头部，并在作者移动、改名或重写标题后继续识别同一章档案；`source_ids` 支持 `chapter-058 / chap-058 / ch058 / Chapter 58` 这类章节 ID 写法，但只在整段 ID 匹配章节格式时推断来源章节；作者把类型改成 `author_archive` 并删除 `source_ids` 时，只要保留 `source_chapters` 或中文来源章节别名，已发布维护动作也会按来源章节重新找到移动后的 Vault 笔记；同一档案有多个章节来源 ID 或来源章节时，按最晚来源章节开放；文件名、路径和来源章节冲突时按更晚的开放章节处理，来源标记和单章文件名指向同一章时保留来源标记的后续可见语义。章节档案维护队列按 80 章长篇规模保留，章节很多时早期已保存章节也会继续出现在待审清单里。

自学习面板的维护摘要在没有筛选时显示后端全局 Obsidian 摘要；存在状态、来源章节、搜索或产物 ID 筛选时，会按可见维护项重新统计。Agent 结果区 `obsidian_maintenance` 产物打开指定章节维护队列后，会先按来源章节过滤，再用产物 `metadata.suggestion_ids` 只显示该产物关联的维护项，界面提供“清除产物筛选”按钮；摘要总数与列表显示数一致。自学习面板可以把当前筛选结果里的 Obsidian 维护建议批量保存为项目内待审草稿，也可以把当前筛选结果里已保存的草稿显式批量发布到 Vault、批量确认当前筛选结果里的 Vault 合并项、批量忽略暂不处理的维护建议，或批量恢复当前筛选结果里的已忽略建议。章节生成上下文和 Agent 规划上下文展示维护建议时，会按来源章节与目标章节的相关性排序，并显示来源章节；其中 `create_chapter_note` 草稿会显示章节档案短预览，`create_chapter_contract_note` 草稿会显示合同目标、必须节拍、禁写动作和验收项短预览，`create_style_rule_note` / `create_xp_rule_note` 草稿会显示规则、适用范围、检查项、证据数和置信度短预览，其它草稿只显示维护状态。批量保存只写 `.gaoxia/obsidian_drafts/`，不会自动写入 Vault；Vault 待更新项保存新版草稿时，会额外生成一份合并草稿，标出正式 Vault 笔记和系统建议路径，对照当前 Vault 正文和系统新版草稿；作者在 Obsidian 完成合并后可在面板单条或批量确认，系统会记录当前 Vault 内容并刷新 Obsidian 摘要和知识库；批量发布只处理已保存草稿，继续检查目标路径在 Vault 内且不覆盖已有笔记；批量确认只记录已人工合并后的 Vault 当前内容；批量忽略不会删除草稿或 Vault 笔记，批量恢复只改变维护建议状态。

剧情债务草稿会把预计处理区间写成 `expected_payoff_range`，不会写成 `chapter_range`。`chapter_range` 只用于 Obsidian 笔记可见范围，避免债务在正式兑现前的中间章节从 Vault 上下文里消失。

两篇以上没有正文双链、frontmatter 关系、未解析或歧义双链和反向链接的正式 Obsidian 笔记会生成 `Graph/孤立笔记整理-{来源摘要}.md` 待审索引草稿。作者发布后，索引笔记会通过 `source_notes` 和正文双链连接原笔记，让这些孤立设定进入 backlinks 和后续图谱检索；后续新增孤立笔记会使用新的来源摘要路径，不会被旧索引的已发布状态隐藏。

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

失败案例现在也会参与 action 契约。遇到相同 action 时，契约检查会把历史失败案例作为门禁提示写入 workflow，要求执行前复核项目状态、章节目标和上一步产物。

前端技能库 `Agent 自学习` 面板会读取这些接口展示能力看板、确认草案、草案差异预览、系统学习版文风 / XP、剧情债务与人物弧线、模型叙事审查、章节合同、写作回归、模型审查、经验候选、调用规则、写作评价、细分质量维度、长期趋势、失败案例、重复失败聚合、技能统计、技能版本和技能包迁移。技能版本会同时显示历史版本、当前版本和 unified diff。写作回归使用同一章样本检查续写、改稿、去 AI、资料调用四类任务的输入条件和自学习信号，并额外运行内置黄金样本，评估本地评审规则对模板腔、对白同质、连续性冲突和正常片段的识别能力，不直接改正文。

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
- 维护 workflow 恢复状态 `recoveryStatus`
- 维护当前 `timelineItems`
- 维护当前执行的 `latestResult`
- 结构化 `project_updated` 和最终 `session_result.project_detail` 都会触发项目详情更新，避免章节文件已写回但正文面板仍显示旧内容
- 停止当前执行时，会在已有 `task_id` 的情况下请求后端 interrupt 接口，再断开当前 SSE
- 连接异常且已有 `task_id` 时，会读取 workflow 摘要，把 action 和 subtask 状态恢复到时间线；这不是重新接入原 SSE，而是读取项目目录里的运行状态
- Agent 对话发起前，前端会先保存完整线程到项目目录，再向 backend 提交末尾 50 条历史；单条历史超过 6000 字时只在请求体里保留开头和末尾，原文仍保存在项目文件里
- 如果当前线程历史超过 50 条，或任意单条历史超过 6000 字，而完整线程保存失败，前端会停止当前执行并显示错误，避免只拿压缩历史继续生成
- 每条线程消息保存 `id / content_hash / original_length / summary`，用于后端确认请求体里的压缩消息对应哪条完整历史

`NovelWorkflowPanel.vue` 不再自己解析每条 SSE。

### 2. 结构化展示

当前消息展示分成四块：

- `AgentPlanCard`
  - 展示计划标题、摘要、步骤、动作标签
- 运行中状态卡
  - 只在当前线程执行时显示，展示当前步骤、耗时、任务上下文和实时状态列表
- `AgentActionTimeline`
  - 保留给未完成或历史兼容消息使用；当前执行中的聊天卡改用轻量状态列表
- `AgentEventBlockSummary`
  - 保留给非执行完成消息使用；完成后的执行消息不再展示阶段摘要
- `AgentArtifactSummary`
  - 展示产物标题、类别、摘要、预览

运行中卡片展示轻量状态列表；完成后的执行消息回到结果说明和产物卡片。

另外补了一条交互规则：

- 用户发的是明确执行命令时，章节续写、补架构这类计划会直接开始执行
- 计划卡仍然会保留在聊天记录里，但不再卡在「待确认」
- 只有用户表达不明确，或者只是想先看方案时，才停在计划态等手动执行
- 如果当前执行实际写回的是别的章节，右侧预览会自动切到被写回的章节
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

如果项目里已经有资料库内容或 Obsidian 笔记，会自动先加一条 `review_knowledge`，再执行 `generate_architecture`。

后端执行 `generate_architecture` 时不再等七个步骤全部完成后才统一保存。任务开始时只构建一次项目上下文快照，后续步骤复用这份快照，并通过内存里的 workspace 传递前面步骤刚生成的内容。每个步骤会按当前模块裁剪无关 workspace 和超长上下文，并使用对应的输出 token 上限；章节蓝图仍保留较大的输出空间，世界设定、人物设定等短模块不会默认占用同样的预算。每个架构步骤完成后会立即写入项目文件，并更新 `.gaoxia/architecture_progress.json`。如果模型或网络在中途失败，下一次同一指令会重新读取项目文件和进度，从失败步骤继续执行。情节骨架、人物状态和章节蓝图步骤必须沿用人物设定里已经确定的核心人物名单；新增配角不能替换核心人物或改名。

整书架构主流程只负责关键文本生成。执行期间会保持前台模型会话，避免后台巡检插入多个架构步骤之间；知识库索引刷新、模型版故事总览、系统记忆刷新和去 AI 智能巡检会写入 `.gaoxia/auxiliary_tasks.json`，由后台巡检执行，整书架构完成后统一排队需要刷新的辅助任务。前台模型或检索任务忙时，后台巡检会延后到后续巡检。章节保存和做梦完成会排队 `humanize_review`，自学习心跳在排程开启且包含 `model_review` 时也会检查去 AI 风险信号；同一批样本默认 12 小时内不重复调用裁判模型。失败会记录错误并按重试时间再次处理，不会阻断架构生成或章节写作。关系总览优先读取模型版故事总览缓存；模型版故事总览优先使用第二审查模型，第二审查模型不可用时使用当前写作模型。两个模型都不可用、模型调用失败或模型结果没有通过证据校验时，模型总览辅助任务不会记为完成；项目详情会返回模型总览状态和失败原因，结构化关系、事件和世界要素不会从本地架构文件抽取。手动打开架构总览或刷新模型总览会直接再次请求模型，不使用失败倒计时拦截。Obsidian 笔记变化会让模型总览来源签名失效，下一次允许模型总览时重新生成结构化缓存。章节生成、改稿、诊断上下文和项目级文风 / XP 提示会关闭模型总览缓存，项目记忆自动条目和续写 / 改稿类项目蒸馏包也不会从模型总览里的全书实体生成；没有目标章节时，续写、改稿、仿写和人物任务默认不带入 Obsidian 后段笔记，整书架构任务仍可使用全书资料，避免后段 Obsidian 设定绕过章节边界。章节和架构上下文会按当前任务匹配 Obsidian 笔记，再带入目标章节可见的一跳外链和反向链接，不按文件顺序塞入无关笔记；带章节范围或剧透边界的笔记不会进入尚未到达的目标章节。重复命名产生的双链会作为歧义提示进入上下文，不会自动指向任意笔记。读取项目详情时会比对 Obsidian 来源签名，Vault 文件变化会刷新同步摘要后再进入上下文。

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

项目目录还会生成 `.gaoxia/thread_context/{thread_id}.json`。该文件把长消息分成带 hash 的片段索引；Agent session 建立时会根据当前输入和当前已提交 message id，取回相关片段并插入系统上下文。这样请求体保持可控，模型仍可使用长历史里的关键信息。

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

1. 把其它专用流分批并到同一套 session/runtime 里
2. 让前端技能执行入口分阶段使用 `agent_action_*` 元数据，减少 panel 到 stream API 的手写分支
