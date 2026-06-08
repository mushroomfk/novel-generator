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

## 2026-06-09

### Obsidian 图谱草稿 Windows 路径修复

- 修改摘要：修复 Windows 环境下 Obsidian 图谱维护草稿里的 wikilink 会被写成反斜杠路径的问题，例如 `[[Characters\林追]]`；现在统一按 Obsidian Vault 路径写成 `[[Characters/林追]]`，孤立笔记索引、未解析链接图谱草稿和章节档案草稿里的来源笔记链接都会使用正斜杠。
- 影响范围：Obsidian 图谱维护草稿、孤立笔记整理草稿、章节档案来源笔记 wikilink 和 Windows 后端单测；不改变 Vault 文件路径、frontmatter `source_notes`、图谱关系解析、章节上下文或前端展示结构。
- 验证结果：GitHub Actions `Windows Desktop Release` run `27164681108` 在修复前失败于 `test_orphan_obsidian_notes_generate_graph_index_draft`，日志显示草稿含 `[[Characters\林追]]` 而不是 `[[Characters/林追]]`；修复后 `.venv/bin/python -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_orphan_obsidian_notes_generate_graph_index_draft backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_obsidian_link_target_uses_vault_slashes_on_windows_paths -v` 通过；`npm run backend:test` 通过，419 个后端 unittest 通过。Windows 桌面发布验证需要在当前分支重新触发后确认。

### 打包配置静态检查

- 修改摘要：新增 `verify:packaging-static`，检查内置 Embedding 模型文件、macOS / Linux 和 Windows sidecar 打包脚本、Windows 发布验证脚本以及 GitHub Actions 工作流关键步骤；`npm run verify`、macOS 桌面发布验证和 Windows 桌面发布验证都会先执行这项检查。桌面发布验证现在还会在打包后的 sidecar 和 `.app` 内 sidecar 上调用 `POST /api/config/test`，确认内置本地 Embedding 能加载并返回 512 维向量，防止内置本地模型或关键打包步骤被遗漏。
- 影响范围：`package.json`、`scripts/verify-packaging-static.mjs`、`scripts/verify-desktop-release.sh`、`scripts/verify-windows-release.ps1`、README、桌面发布回归说明、Windows 打包说明、技能流程回归清单和打包验证流程；不改变模型配置结构、sidecar 输出路径、Tauri 配置、前端设置页或真实写作模型调用链路。
- 验证结果：`node --check scripts/verify-packaging-static.mjs` 通过；`bash -n scripts/verify-desktop-release.sh scripts/build-backend-sidecar.sh scripts/prepare-macos-test-release.sh scripts/repair-tauri-app-signature.sh` 通过；`npm run verify:packaging-static` 通过；`npm run verify` 通过，包含打包脚本静态检查、418 个后端 unittest 和前端生产构建；`npm run verify:ui` 通过，覆盖 Agent、章节写回、Obsidian、自学习面板、架构总览、章节核验项目记忆展示、提示词、XP、文件浏览、人物复刻和项目迁移包导出导入；增强后的 `npm run verify:desktop` 通过，包含打包配置静态检查、418 个后端 unittest、前端生产构建、Python sidecar 打包、打包后 sidecar 健康检查和本地 Embedding 测试、Tauri debug `.app` / `.dmg` 构建、签名修复校验、应用内 sidecar 健康检查和本地 Embedding 测试、`.app` 启动检查；`npm run package:test:macos` 通过，重新生成 `release/test-release/macos/稿匣_0.1.2_测试包`；在测试包目录执行 `shasum -a 256 -c SHA256SUMS.txt` 通过，返回 `稿匣_0.1.2_aarch64.dmg: OK`；`hdiutil verify release/test-release/macos/稿匣_0.1.2_测试包/稿匣_0.1.2_aarch64.dmg` 通过。Windows PowerShell 脚本仍未在本机执行，本机没有 `pwsh` 或 `powershell`，当前本地改动还需要重新触发 `Windows Desktop Release` 或在 Windows 本机执行 `npm run verify:desktop:windows` 才能确认进入 Windows 安装包。

### 章节核验详情展示

- 修改摘要：架构总览新增“章节核验”页签，作者可以直接查看每章核验分数、状态、维度、问题、建议和过期标记；项目记忆规则触发项会在对应维度中显示，避免核验报告只存在于后端数据里。
- 影响范围：架构总览界面、章节核验报告展示、UI smoke、README、技能流程回归清单、测试反馈清单和项目 Agent 指令；不改变后端章节核验数据结构、章节保存接口、项目记忆格式或模型配置。
- 验证结果：`node --check scripts/verify-ui-smoke.mjs` 通过；`npm run build` 通过；`npm run verify:ui` 通过，覆盖设置页 Embedding 配置入口移除、Agent、Obsidian、自学习面板、章节核验项目记忆展示、架构总览、提示词、XP、文件浏览、人物复刻和项目迁移包导出导入；`npm run release:test:macos` 通过，包含 418 个后端 unittest、前端生产构建、Python sidecar 打包、sidecar 健康检查、Tauri debug `.app` / `.dmg` 构建、签名修复校验、应用内 sidecar 健康检查、`.app` 启动检查和测试包整理，生成 `release/test-release/macos/稿匣_0.1.2_测试包`；在测试包目录执行 `shasum -a 256 -c SHA256SUMS.txt` 通过，返回 `稿匣_0.1.2_aarch64.dmg: OK`；`hdiutil verify release/test-release/macos/稿匣_0.1.2_测试包/稿匣_0.1.2_aarch64.dmg` 通过；用当前 `.app` 内 `Contents/MacOS/novel-backend` 启动临时服务后，`POST /api/config/test` 的本地 Embedding 测试通过，返回 `BAAI/bge-small-zh-v1.5 可用，向量维度 512`；使用临时数据目录复制真实配置和许可证后，`POST /api/config/test` 真实调用通过，写作模型 `qwen3-max`、知识检索模型 `BAAI/bge-small-zh-v1.5` 和第二审查模型 `qwen/qwen3.7-max` 均为 passed；真实章节链路通过，`qwen3-max` 为 6 章 6000 字临时悬疑项目生成第 1 章 804 字，保存后 `qwen/qwen3.7-max` 生成章节核验，状态 `good`、87 分，`项目记忆规则` 维度 `good`、94 分且 0 个问题，知识检索返回 5 条命中。

### 项目记忆关键物品归属规则

- 修改摘要：真实后端 HTTP 端到端冒烟发现，项目记忆写“铜钥匙不能被交给白石商会”时，章节正文“林追把铜钥匙交给白石商会”没有被 `项目记忆规则` 捕获。章节核验现在会识别“X 不能被交给 / 交出 / 移交 / 转交 / 交付给 Y”这类关键物品、线索或账册归属禁写，正文命中时显示为“铜钥匙 / 交给 / 白石商会”；正文写成“没有把铜钥匙交给白石商会”不会误报。
- 影响范围：章节保存核验、项目记忆规则维度、长篇关键物品归属连续性、项目服务回归、真实后端 HTTP 冒烟、README、核心引擎说明、技能流程回归清单、测试反馈清单和项目 Agent 指令；不改变项目记忆文件格式、前端接口、Obsidian 规则或模型配置。
- 验证结果：真实 backend 服务使用临时数据目录启动后，通过 HTTP 覆盖 `GET /api/config`、`POST /api/config/test` 本地 Embedding、`POST /api/projects` 创建作品、`PUT /api/projects/{id}/memory` 写入项目记忆、`POST /api/projects/{id}/knowledge/import`、`GET /api/projects/{id}/knowledge/search`、`PUT /api/projects/{id}/chapters/chapter-001` 保存违规和安全正文、`POST /api/projects/{id}/snapshots`、`POST /api/projects/{id}/export`、`POST /api/projects/{id}/migration/export` 和 `GET /api/projects/{id}`，结果通过；`.venv/bin/python -m py_compile backend/novel_backend/services/chapter_review_service.py backend/tests/test_project_service.py` 通过；`.venv/bin/python -m unittest backend.tests.test_project_service -v` 通过，75 个用例通过；`npm run verify` 通过，418 个后端 unittest 和前端生产构建通过；`npm run verify:ui` 通过，覆盖工作台、Agent 章节计划 / 执行、章节生成写回、架构优先、Obsidian 同步 / 检索 / 维护产物跳转、自学习面板、架构总览、提示词、XP、文件浏览、人物复刻和项目迁移包导出导入；`npm run release:test:macos` 通过，包含 418 个后端 unittest、前端生产构建、Python sidecar 打包、sidecar 健康检查、Tauri debug `.app` / `.dmg` 构建、签名修复校验、应用内 sidecar 健康检查、`.app` 启动检查和测试包整理，生成 `release/test-release/macos/稿匣_0.1.2_测试包`；用新生成的 `.app` 内 `Contents/MacOS/novel-backend` 启动临时服务后，`POST /api/config/test` 本地 Embedding 返回 `BAAI/bge-small-zh-v1.5 可用，向量维度 512`，并通过 `PUT /api/projects/{id}/chapters/chapter-001` 验证“铜钥匙 / 交给 / 白石商会”和“账册 / 交给 / 顾临”会报风险，否定句不误报；在测试包目录执行 `shasum -a 256 -c SHA256SUMS.txt` 通过，返回 `稿匣_0.1.2_aarch64.dmg: OK`；`hdiutil verify release/test-release/macos/稿匣_0.1.2_测试包/稿匣_0.1.2_aarch64.dmg` 通过；`bash -n scripts/build-backend-sidecar.sh scripts/verify-desktop-release.sh scripts/prepare-macos-test-release.sh scripts/repair-tauri-app-signature.sh` 通过；`node --check scripts/verify-ui-smoke.mjs scripts/fix-macos-native-binaries.mjs scripts/patch-vite-fsevents.mjs scripts/capture-readme-screenshots.mjs` 通过；`cargo test --manifest-path src-tauri/Cargo.toml` 通过，Rust 侧当前 0 个测试用例；本机没有 `pwsh` 或 `powershell`，Windows PowerShell 打包 / 验证脚本未在本机执行，已在 Windows 打包说明中标明需要重新触发 Windows 验证后才能确认当前本地改动进入 Windows 安装包。

### macOS 测试包校验说明

- 修改摘要：macOS 测试版安装说明新增 SHA256 校验步骤，明确需要先进入测试包目录再执行 `shasum -a 256 -c SHA256SUMS.txt`，避免测试人员从其它目录执行时因为相对路径误判校验失败。
- 影响范围：`docs/macOS测试版安装说明.md` 和重新整理后的 `release/test-release/macos/稿匣_0.1.2_测试包/安装说明-先看这个.md`；不改变 DMG、`.app`、sidecar、签名或打包脚本逻辑。
- 验证结果：`npm run package:test:macos` 通过；在测试包目录执行 `shasum -a 256 -c SHA256SUMS.txt` 通过，返回 `稿匣_0.1.2_aarch64.dmg: OK`；`hdiutil verify release/test-release/macos/稿匣_0.1.2_测试包/稿匣_0.1.2_aarch64.dmg` 通过。

### Obsidian 保存结果刷新

- 修改摘要：技能库里的 `Obsidian 知识库` 保存配置或手动重新同步后，会主动重新读取 `/api/projects/{project_id}/obsidian` 的最新同步状态，再恢复按钮可用状态；同步结果区会立刻显示新 Vault 的笔记、双链、考据链接和重复命名问题，避免保存接口已完成但界面仍停留在旧状态或空状态。
- 影响范围：技能库 Obsidian 配置保存、手动重新同步、同步结果区刷新和 UI smoke；不改变 Obsidian 配置结构、Vault 解析规则、知识库索引格式或后端接口。
- 验证结果：`npm run verify:ui` 通过，已覆盖配置测试 Vault、保存并索引、结果区显示 `灯塔议会`、考据链接、重复命名、歧义双链、反向链接和章节范围；`npm run release:test:macos` 通过，包含 414 个后端 unittest、前端生产构建、Python sidecar 打包、sidecar 健康检查、Tauri debug `.app` / `.dmg` 构建、签名修复校验、应用内 sidecar 健康检查、`.app` 启动检查和测试包整理；`npm run verify` 复验通过，包含 414 个后端 unittest 和前端生产构建。

### 项目记忆状态禁写规则扩展

- 修改摘要：`项目记忆规则` 章节核验增加状态类禁写识别，作者在项目记忆“硬规则 / 警告”中写“不会 / 不能 / 禁止 / 避免”等规则时，系统现在能反查关键人物死亡、被杀、叛变、背叛、黑化、离队和主动暴露身份这类长篇状态变化冲突；“沈砚不能被提前揭示为主谋”“某人不能提前暴露为真凶”“林追不能被提前揭示为卧底”“苏青不能提前暴露为潮师”这类人物在否定词前、身份在后面的写法也会被识别，正文命中时显示为“沈砚 / 主谋”“林追 / 卧底”这类清晰项。正文写成“没有暴露身份”“并不是主谋”“并不是卧底”这类否定表述时不再误判为违规。自动修订提示会携带项目记忆规则问题，让模型改稿时知道必须遵守哪些硬规则；作者修改项目记忆后，已有章节核验报告会标记过期，刷新后按新规则重新检查。
- 影响范围：章节保存核验、项目记忆规则维度、章节核验过期签名、自动修订触发判断、自动修订提示、项目记忆状态变化和提前揭示身份回归测试、README、核心引擎说明、技能流程回归清单、测试反馈清单和项目 Agent 指令；不改变项目记忆文件格式、前端接口、Obsidian 规则或模型配置。
- 验证结果：`.venv/bin/python -m py_compile backend/novel_backend/services/chapter_review_service.py backend/tests/test_project_service.py` 通过；`.venv/bin/python -m unittest backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_catches_project_memory_custom_identity_reveal_rules backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_catches_project_memory_reveal_rule_with_subject_before_marker backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_catches_project_memory_forbidden_rules backend.tests.test_project_service.ProjectServiceTestCase.test_auto_repair_uses_project_memory_reveal_rule_issues backend.tests.test_project_service.ProjectServiceTestCase.test_auto_repair_uses_project_memory_state_rule_issues -v` 通过；`.venv/bin/python -m unittest backend.tests.test_project_service -v` 通过，74 个用例通过；`npm run backend:test` 通过，417 个后端 unittest 通过；`npm run build` 通过；`npm run verify:ui` 通过，覆盖工作台、Agent、Obsidian、项目迁移、提示词、XP、文件浏览和人物复刻等浏览器流程；`npm run release:test:macos` 通过，包含 417 个后端 unittest、前端生产构建、Python sidecar 打包、sidecar 健康检查、Tauri debug `.app` / `.dmg` 构建、签名修复校验、应用内 sidecar 健康检查、`.app` 启动检查和测试包整理，生成 `release/test-release/macos/稿匣_0.1.2_测试包`；用新生成的 `.app` 内 `Contents/MacOS/novel-backend` 启动临时服务后调用 `POST /api/config/test`，本地 Embedding 返回 `BAAI/bge-small-zh-v1.5 可用，向量维度 512`，服务返回耗时 11.652 秒；`cargo test` 通过，Rust 侧当前 0 个测试用例；`bash -n scripts/build-backend-sidecar.sh scripts/verify-desktop-release.sh scripts/prepare-macos-test-release.sh scripts/repair-tauri-app-signature.sh` 通过；`node --check scripts/verify-ui-smoke.mjs scripts/fix-macos-native-binaries.mjs scripts/patch-vite-fsevents.mjs scripts/capture-readme-screenshots.mjs` 通过。Windows PowerShell 打包 / 验证脚本仍未在本机执行。

## 2026-06-08

### 项目记忆规则参与章节核验

- 修改摘要：章节保存后的核验报告新增 `项目记忆规则` 维度，会读取作者项目记忆里的“硬规则 / 警告”，对“不要 / 不能 / 禁止 / 避免”等禁写表达做本地短语反查；正文命中“不要提前揭示某人是主谋”“不要把 A 改名为 B”这类规则时记为 critical，并参与章节自动修订判断。
- 影响范围：章节保存核验、核验报告维度、自动修订触发判断、项目记忆规则回归测试、README、核心引擎说明、技能流程回归清单、测试反馈清单和项目 Agent 指令；不改变项目记忆文件格式、章节正文保存路径、Obsidian 规则、模型配置或前端接口。
- 验证结果：`.venv/bin/python -m py_compile backend/novel_backend/services/chapter_review_service.py backend/tests/test_project_service.py` 通过；`.venv/bin/python -m unittest backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_catches_project_memory_forbidden_rules backend.tests.test_project_service.ProjectServiceTestCase.test_update_chapter_content_generates_chapter_review_report backend.tests.test_project_service.ProjectServiceTestCase.test_auto_repair_uses_chapter_scoped_obsidian_required_phrase -v` 通过；`.venv/bin/python -m unittest backend.tests.test_project_service -v` 通过，68 个用例通过；`npm run backend:test` 通过，411 个后端 unittest 通过；`npm run build` 通过；`git diff --check` 通过；`node --check scripts/verify-ui-smoke.mjs` 通过；`npm run verify:ui` 通过；`npm run release:test:macos` 通过，包含 411 个后端 unittest、前端生产构建、Python sidecar 打包、sidecar 健康检查、Tauri debug `.app` / `.dmg` 构建、签名修复校验、应用内 sidecar 健康检查、`.app` 启动检查和测试包整理，生成 `release/test-release/macos/稿匣_0.1.2_测试包`；用新生成的 `src-tauri/binaries/novel-backend-aarch64-apple-darwin` 启动临时服务后调用 `POST /api/config/test`，本地 Embedding 返回 `BAAI/bge-small-zh-v1.5 可用，向量维度 512`，首次加载耗时 16.057 秒。

### 桌面发布冷启动验证加固

- 修改摘要：macOS 和 Windows 桌面发布回归脚本的 sidecar 健康检查等待上限从 30 秒调整为 120 秒；如果打包后的 backend 在健康检查前提前退出，脚本会立即打印退出码和日志，避免 PyInstaller onefile 首次解包较慢时被误判为失败，也避免真实崩溃时只看到超时。
- 影响范围：`npm run verify:desktop`、`npm run release:test:macos` 和 `npm run verify:desktop:windows` 的 sidecar / 应用内 sidecar 冒烟检查；不改变应用启动参数、Tauri 配置、模型配置、项目数据或安装包结构。
- 验证结果：第一次执行 `npm run release:test:macos` 时，打包后的 sidecar 在 30 秒内尚未完成冷启动，健康检查误失败；脚本调整后重新执行 `npm run release:test:macos` 通过，包含 410 个后端 unittest、前端生产构建、Python sidecar 打包、sidecar 健康检查、Tauri debug `.app` / `.dmg` 构建、签名修复校验、应用内 sidecar 健康检查、`.app` 启动检查和测试包整理，生成 `release/test-release/macos/稿匣_0.1.2_测试包`。`bash -n scripts/verify-desktop-release.sh scripts/build-backend-sidecar.sh scripts/prepare-macos-test-release.sh` 通过；`node --check scripts/verify-ui-smoke.mjs` 通过。Windows PowerShell 脚本已同步修改，但未在本机执行。

### 真实模型连续章节复查

- 修改摘要：基于真实测试工程继续执行第 2 章生成、保存、章节核验、知识检索和一致性检查，确认第 1 章保存后的正文、章节合同、知识库和叙事状态会进入后续章节上下文。测试中临时输入的人物名与项目资料库不一致时，生成结果优先沿用项目资料里的既有人物名，符合长篇一致性优先级。
- 影响范围：真实写作模型链路、第二审查模型链路、本地 Embedding 检索、章节保存后知识索引刷新、叙事状态和连续性检查结果记录；不改变代码、接口或项目数据格式。
- 验证结果：测试工程 `真实模型长篇链路测试` 中，第 1 章已有 1256 字符正文；真实 `qwen3-max` 生成第 2 章，用时 330.5 秒，正文 1259 字符并保存成功；保存触发真实第二审查模型 `qwen/qwen3.7-max`，章节核验 73/100、状态“需关注”，指出短稿相对 6 章 60000 字目标严重不足、顾临权限铺垫需要更严谨、控制室权限伏笔需后续呼应；知识检索返回 5 条命中，包含第 2 章正文、核心种子和写作边界资料；真实一致性检查返回 3 条问题，确认未提前揭示主谋、人物关系和港口制度基本承接，但短稿不能当完整章上线。

### 章节显式字数目标修复

- 修改摘要：Studio 章节生成和章节工作流 draft 入口在用户传入 `target_words` 时，会按调用方目标生成，不再被项目单章均值覆盖；只有 `target_words=0` 的完整章节生成才使用项目篇幅预算。设置页内部同步删除已无用的 Embedding 表单状态，前端仍固定发送内置本地 Embedding 配置。
- 影响范围：`chapter_generate_stream`、`chapter_workflow:draft`、章节续写模型输出预算、设置页内部状态和相关回归测试；不改变未传字数时的完整长章节预算、批量生成、知识库 schema 或写作模型配置结构。
- 验证结果：真实模型链路修复前，6 章 60000 字测试项目里传入 `target_words=900` 仍被提示词改成“目标长度：约 3500 字”，随后 `qwen3-max` 章节生成在 226.332 秒后因供应商断连失败；修复后同一项目真实调用 `qwen3-max` 生成第 1 章，prompt 记录 `continuation_brief` 和 `chapter_generate:partial` 都为 `target_words_in_prompt=900`，生成正文 1256 字并保存成功；保存后真实第二审查模型 `qwen/qwen3.7-max` 生成章节核验，结果 82/100、状态“需关注”；真实 `qwen3-max` 一致性检查完成，指出正文未提前揭示主谋但篇幅偏短；真实去 AI 改稿完成，本地评分 90 → 100。`.venv/bin/python -m unittest backend.tests.test_studio_service.StudioServiceTestCase.test_chapter_generate_stream_respects_explicit_target_words backend.tests.test_generation_service.GenerationServiceTestCase.test_chapter_workflow_draft_respects_explicit_target_words -v` 通过；`.venv/bin/python -m unittest backend.tests.test_generation_service backend.tests.test_studio_service -v` 通过，38 个用例通过；`npm run backend:test` 通过，410 个后端 unittest 通过；`npm run build` 通过；`npm run verify:ui` 通过；`npm run backend:bundle` 通过并更新 `src-tauri/binaries/novel-backend-aarch64-apple-darwin`，新 sidecar 启动后 `GET /api/app/health` 通过，`POST /api/config/test` 的本地 Embedding 测试通过，返回 `BAAI/bge-small-zh-v1.5 可用，向量维度 512`；`git diff --check` 通过。

### 内置本地 Embedding 模型

- 修改摘要：Embedding 默认改为随 sidecar 打包的本地 `local-fastembed` / `BAAI/bge-small-zh-v1.5`，维度 512，模型文件放在 `backend/novel_backend/assets/embedding_models/fast-bge-small-zh-v1.5`；后端新增本地模型加载路径，知识库向量生成和“测试当前配置”不再要求 Embedding API Key；设置页移除 Embedding 配置入口，保存写作模型时不再按服务商自动改成云端 Embedding；macOS / Linux 和 Windows sidecar 打包脚本会把内置模型目录以及 `fastembed / onnxruntime / tokenizers` 运行依赖收进产物。
- 影响范围：新项目默认 Embedding 配置、知识库向量生成、模型配置测试、设置页高级区、Python backend 依赖、PyInstaller sidecar 打包脚本、README、核心引擎说明、桌面版方案、桌面发布回归说明、界面回归说明、测试反馈清单和项目 Agent 指令；不改变写作模型配置、章节正文生成接口、后端 OpenAI-compatible `/embeddings` 兼容路径或知识库 schema。
- 验证结果：`.venv/bin/python -m py_compile backend/novel_backend/models.py backend/novel_backend/services/local_embedding_service.py backend/novel_backend/services/embedding_service.py backend/novel_backend/services/config_service.py backend/tests/test_config_service.py backend/tests/test_embedding_service.py` 通过；`HF_HUB_OFFLINE=1` 下直接加载内置模型生成 2 条 512 维向量通过，确认不依赖外部下载；`.venv/bin/python -m unittest backend.tests.test_config_service backend.tests.test_embedding_service -v` 通过，14 个用例通过；`npm run backend:test` 通过，408 个后端 unittest 通过；`npm run build` 通过；`npm run verify:ui` 通过，包含设置页旧 Embedding 入口不存在的检查；`bash -n scripts/build-backend-sidecar.sh` 通过；`npm run backend:bundle` 通过并生成 `src-tauri/binaries/novel-backend-aarch64-apple-darwin`；启动打包后的 sidecar 后，`GET /api/app/health` 通过，`POST /api/config/test` 的本地 Embedding 测试通过，返回 `BAAI/bge-small-zh-v1.5 可用，向量维度 512`。Windows PowerShell 打包脚本未在本机执行。

### AI 写作设置页误关闭修复

- 修改摘要：AI 写作设置页不再通过点击背景关闭；在输入框、文本框、下拉框等编辑控件内按 Escape 也不会关闭设置页，避免复制、选择或修改模型配置时误关页面。设置页仍可通过“关闭”按钮，或在非编辑区按 Escape 关闭。
- 影响范围：设置页关闭逻辑、浏览器层 smoke 的设置页检查、界面回归说明和测试反馈清单；不改变模型配置保存、配置测试、设置字段或后端接口。
- 验证结果：`node --check scripts/verify-ui-smoke.mjs` 通过；`git diff --check` 通过；`npm run build` 通过，前端生产构建通过；`npm run verify:ui` 通过，已覆盖设置页背景点击不关闭、输入框内 Escape 不关闭、显式关闭按钮可关闭；`npm run release:test:macos` 通过，完成 406 个 backend unittest、前端生产构建、Python sidecar 打包和健康检查、Tauri debug `.app` / dmg 构建、签名修复、应用内 sidecar 健康检查、`.app` 启动检查和测试包整理，生成 `release/test-release/macos/稿匣_0.1.2_测试包`，DMG SHA256 为 `02d758af68179f8259194ce8ae607ea8186a0aac3d19037bc0528d34965dffb7`。

### 模型配置测试真实调用复查

- 修改摘要：模型设置的“测试当前配置”现在沿用模型请求助手的短暂网络错误重试，避免一次 SSL EOF 直接盖过后续真实错误；模型错误分类新增 `no available channels for model ...` 识别，供应商提示模型无可用通道时会显示为“模型不可用”。
- 影响范围：模型配置测试接口、模型错误分类、设置页测试当前配置的失败提示；不改变模型配置结构、保存语义、模型端点、真实生成流程或前端设置页结构。
- 验证结果：`.venv/bin/python -m py_compile backend/novel_backend/services/config_service.py backend/novel_backend/services/model_error_service.py backend/tests/test_config_service.py backend/tests/test_model_error_service.py` 通过；`.venv/bin/python -m unittest backend.tests.test_config_service.ConfigServiceTestCase.test_model_config_test_uses_current_payload_without_saving backend.tests.test_config_service.ConfigServiceTestCase.test_model_config_test_reports_model_error backend.tests.test_model_error_service.ModelErrorServiceTestCase.test_classifies_common_model_errors backend.tests.test_model_error_service.ModelErrorServiceTestCase.test_request_json_retries_transient_ssl_eof -v` 通过，4 个用例通过；真实模型调用确认写作模型 `qwen3-max` 返回“真实写作模型调用成功。”，第二审查模型 `qwen/qwen3.7-max` 返回“审查模型调用成功。”；“测试当前配置”真实结果为写作模型通过、知识检索模型失败并返回百炼 `401 invalid_api_key`、第二审查模型通过；`https://api.qnaigc.com/v1/models` 带重试查询通过，返回 60 个模型，`qwen3-max` 和 `qwen/qwen3.7-max` 都在列表中；`npm run backend:test` 通过，406 个后端 unittest 通过；`git diff --check` 通过。

### 本地启动配置与隐藏导入控件修正

- 修改摘要：`NOVEL_CORS_ORIGINS` 现在同时支持 JSON 数组和逗号分隔来源列表，避免开发者按常见环境变量写法启动 backend 时直接失败；工作台里的迁移包文件输入保留给“导入迁移包”按钮调用，但从可访问树和键盘焦点中移除，不再出现裸露的 `Choose File` 控件。
- 影响范围：backend 启动配置解析、`.env.example`、README 本地启动说明、工作台迁移包导入隐藏 input；不改变默认 CORS 来源、迁移包格式、迁移包导入导出逻辑或旧稿接管入口。
- 验证结果：`.venv/bin/python -m unittest backend.tests.test_app.AppCorsTestCase -v` 通过，4 个用例通过；`npm run build` 通过；使用 `NOVEL_CORS_ORIGINS="http://localhost:1420,http://127.0.0.1:1420"` 启动 `npm run backend:dev` 成功并通过 `/api/app/health`；浏览器检查确认隐藏 input 不再出现在可访问树中且控制台无 error / warning；`npm run backend:test` 通过，406 个后端 unittest 通过；`npm run verify:ui` 通过，覆盖项目迁移包导出导入。

### 作品入口与迁移包菜单调整

- 修改摘要：作品列表顶部只保留“旧稿”和“新建”，旧稿入口取消高亮底色并增加 hover 提示，说明旧稿文件只支持 `.txt`；迁移包导入入口移动到右上角“更多”菜单，旧稿接管弹窗的文件选择和前端校验同步限制为 `.txt`。
- 影响范围：作品列表入口、右上角项目工具菜单、旧稿接管弹窗、README、项目 Agent 指令、核心引擎说明、技能流程回归清单、测试反馈清单和浏览器层 smoke 检查；不改变迁移包导出、迁移包格式、旧稿粘贴正文接管或后端章节接管流程。
- 验证结果：`node --check scripts/verify-ui-smoke.mjs` 通过；`git diff --check` 通过；`npm run build` 通过，前端生产构建通过；`npm run verify:ui` 前两次暴露 smoke 从技能库返回工作台时等待错元素，修正后第三次通过，已验证旧稿入口不再高亮、旧稿提示包含 `.txt`、侧栏不再显示迁移包导入入口、右上角“更多”菜单可导出并导入迁移包；文档同步后 `git diff --check` 再次通过；`npm run release:test:macos` 通过，完成 404 个 backend unittest、前端生产构建、Python sidecar 打包和健康检查、Tauri debug `.app` / dmg 构建、签名修复、应用内 sidecar 健康检查、`.app` 启动检查和测试包整理，生成 `release/test-release/macos/稿匣_0.1.2_测试包`，DMG SHA256 为 `39c6fefba3e09ab6e8e6c7b0d54354ed6ff7ed27d85ab77d0069550355cad597`。

### 界面 smoke 设置页适配与重新打包

- 修改摘要：模型设置页已有二级折叠区后，浏览器层 smoke 会先展开“知识检索模型”再检查“单独设置 Embedding”，并对“第二审查模型”标题使用精确匹配，避免把“启用第二审查模型”标签一起命中导致 strict mode 失败。
- 影响范围：`scripts/verify-ui-smoke.mjs` 的设置页检查步骤；不改变模型配置保存、模型测试接口、前端设置页结构或桌面打包参数。
- 验证结果：`npm run verify` 通过，404 个后端 unittest 通过，前端生产构建通过；`npm run verify:ui` 前两次暴露设置页折叠区和文本匹配问题，修正 smoke 后第三次通过；`npm run release:test:macos` 通过，完成 backend 回归、前端构建、Python sidecar 打包和健康检查、Tauri debug `.app` / dmg 构建、签名修复、应用内 sidecar 健康检查、`.app` 启动检查和测试包整理；`git diff --check` 通过。

### 模型总览失败倒计时移除

- 修改摘要：模型版故事总览失败后不再写入或返回 `retry_after`。作者手动打开架构总览或刷新模型总览时，会直接再次请求模型并返回真实错误；失败状态仍写入 `.gaoxia/story_overview_model_failure.json`，用于界面展示上次失败原因。全局模型状态行不再显示后台失败暂停秒数倒计时，设置项名称改为“后台失败暂停秒数”。
- 影响范围：项目详情 `story_overview.model_overview` 状态、模型总览失败文件、架构总览状态展示、全局模型状态行、模型设置高级区、前端 `StoryOverview` 类型和相关说明文档；不改变模型总览缓存文件 `.gaoxia/story_overview_model.json`、整书架构生成、章节生成或后台辅助任务队列的通用重试机制。
- 验证结果：`python3 -m py_compile backend/novel_backend/models.py backend/novel_backend/services/project_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_service.ProjectServiceTestCase.test_story_overview_model_failure_is_reported_without_local_entities -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_service.ProjectServiceTestCase.test_story_overview_without_model_cache_keeps_entities_empty backend.tests.test_project_service.ProjectServiceTestCase.test_story_overview_uses_validated_model_cache_for_all_sections backend.tests.test_project_service.ProjectServiceTestCase.test_story_overview_uses_primary_model_when_review_model_disabled backend.tests.test_project_service.ProjectServiceTestCase.test_story_overview_review_request_allows_model_overview backend.tests.test_project_service.ProjectServiceTestCase.test_refresh_story_overview_raises_when_no_model_cache_is_created backend.tests.test_project_service.ProjectServiceTestCase.test_story_overview_model_failure_is_reported_without_local_entities backend.tests.test_project_service.ProjectServiceTestCase.test_story_overview_model_reads_every_source_chunk backend.tests.test_project_service.ProjectServiceTestCase.test_story_overview_without_model_cache_does_not_backfill_main_character backend.tests.test_project_service.ProjectServiceTestCase.test_imported_source_material_without_model_cache_does_not_populate_graph -v` 通过，9 个用例通过；`npm run build` 通过，前端生产构建通过；`npm run verify` 通过，404 个后端 unittest 通过，前端生产构建通过；`git diff --check` 通过。`PYTHONPATH=backend python3 -m pytest backend/tests/test_project_service.py -k "story_overview"` 在 pytest 收集阶段超过 3 分钟没有输出，已停止并改用 unittest 验证。

## 2026-06-06

### 模型总览错误直报与配置测试

- 修改摘要：按产品要求撤销架构总览的本地结构化抽取路径。架构总览的关系、事件和世界要素只来自 `.gaoxia/story_overview_model.json` 模型版总览；模型未配置、调用失败、返回非 JSON 或证据校验失败时，会写入失败状态并在打开架构总览时直接显示错误，不再从本地架构文件抽取人物、事件、地点、道具、技能或组织。模型设置页新增“测试当前配置”，使用当前表单值测试写作模型、知识检索模型和已启用的第二审查模型，不需要先保存配置。
- 影响范围：项目详情 `story_overview` 数据结构、模型总览辅助任务错误处理、架构总览状态展示、模型配置 API 和模型设置页；不改变整书架构七步生成、章节正文生成、已有架构文件写回或模型总览缓存格式。
- 验证结果：`PYTHONPATH=backend python3 -m pytest backend/tests/test_config_service.py backend/tests/test_project_service.py -k "model_config_test or story_overview"` 通过，10 个测试通过；`PYTHONPATH=backend python3 -m pytest backend/tests/test_config_service.py backend/tests/test_project_service.py` 通过，79 个测试通过；`npm run build` 通过，前端生产构建通过；本地浏览器打开 `http://127.0.0.1:1420/` 检查模型设置弹窗，确认“测试当前配置”按钮存在，后端不可用时按钮会恢复；`npm run verify` 通过，404 个后端 unittest 通过，前端生产构建通过；`git diff --check` 通过。

## 2026-06-05

### 架构总览空白修复

- 修改摘要：检查 `她刃` 2026-06-05 20:42-20:44 的生成记录后，确认整书架构七个步骤已完成并写入项目文件，但后续模型版架构总览辅助任务在 20:46 失败，导致默认“关系总览 / 世界要素”页签看起来没有内容。当时曾让模型总览不可用时从本地架构文件抽取基础人物、事件、地点、道具、技能和组织，避免架构已写回但总览默认页签空白；滚动摘要步骤如果模型返回截断的 JSON 外壳，会优先保存摘要正文，不再把坏 JSON 写进 `global_summary.txt`。本地结构化抽取路径已在 2026-06-06 撤销，当前行为以 2026-06-06 记录为准。
- 影响范围：架构步骤结果解析、`global_summary.txt` 写回内容、当时的项目详情 `story_overview` 本地结构化抽取、架构总览默认页签、相关 backend 回归；不改变整书架构生成步骤、模型端点、辅助模型配置、章节正文生成或已有架构文件内容。
- 验证结果：`PYTHONPATH=backend python3 -m pytest backend/tests/test_generation_service.py -k "architecture_step or global_summary"` 通过，5 个测试通过；`PYTHONPATH=backend python3 -m pytest backend/tests/test_project_service.py -k "story_overview"` 通过，7 个测试通过；`PYTHONPATH=backend python3 -m pytest backend/tests/test_generation_service.py backend/tests/test_project_service.py` 通过，85 个测试通过；`npm run verify` 通过，401 个后端 unittest 通过，前端生产构建通过；`git diff --check` 通过；用当前 `她刃` 项目数据读取 `get_project_detail(..., allow_model_overview=False)`，确认返回 7 个非空架构文件、8 个人物和章节事件；已把本次被截断的 `global_summary.txt` 修复为模型返回的摘要正文。

### 模型设置简化与侧栏入口按钮调整

- 修改摘要：AI 写作设置面向普通作者简化为常用模型预设、自定义接口、API Key 和篇幅能力，不再暴露温度这类采样输入；Embedding、第二审查模型、自动修订和运行调度改到高级区展开。后端把 `ModelConfig.temperature` 和 `ReviewModelConfig.temperature` 保留为旧配置兼容字段，新保存配置不再写入；聊天模型请求在传输层移除 `temperature / top_p`，避免部分 OpenAI-compatible 模型拒收不支持的可选采样项。作品列表顶部“旧稿 / 迁移包 / 新建”入口改为同宽三段工具条，避免按钮在侧栏里漂移或挤压。
- 影响范围：模型设置页、配置保存载荷、模型请求传输层、第二审查模型调用、侧栏作品入口按钮、README、项目 Agent 指令、界面回归说明、测试反馈清单和桌面版方案文档；不改变模型服务商、接口地址、API Key 环境变量、Embedding 配置字段、章节生成流程或作品数据格式。
- 验证结果：`.venv/bin/python -m unittest backend.tests.test_model_transport_service backend.tests.test_config_service -v` 通过，15 个用例通过；`npm run verify` 通过，399 个后端 unittest 通过，前端生产构建通过；`npm run build` 通过；本地浏览器打开 `http://localhost:1421/` 检查模型设置弹窗，确认不再显示温度相关文字；本地浏览器检查作品列表入口按钮，确认三个按钮同为 92px 宽、32px 高，文字完整显示。

### 最近改动审查修复

- 修改摘要：审查本地分支提交 `0dfe133ea8b755346d222c8a69373ebdcd21ba15` 和全部未提交改动后，修正三处边界问题。旧稿导入弹窗允许 30 MiB 文件，后端 `content_base64` 校验上限现在按 30 MiB 转 base64 后的 41943040 字符计算，避免前端允许但接口拒绝；Agent workflow 子任务文件名除了替换 `:` 等非法字符，也会避开 `CON / PRN / AUX / NUL / COM1-9 / LPT1-9` 这类 Windows 保留名；macOS 测试包签名修复脚本会在 `.app` 签名后单独重签应用内 `novel-backend` sidecar，避免桌面发布回归在应用内 sidecar 健康检查阶段被系统直接终止。
- 影响范围：`ExistingNovelImportRequest` 的旧稿文件 base64 长度校验、Agent workflow 子任务状态文件名、macOS 测试包签名修复脚本、对应 backend 和桌面发布回归；不改变旧稿正文拆章、项目章节写入、workflow 状态结构、前端文件大小限制、模型配置或 Tauri 打包参数。
- 验证结果：`.venv/bin/python -m unittest backend.tests.test_agent_workflow_service.AgentWorkflowServiceTestCase.test_subtask_filename_avoids_windows_reserved_names backend.tests.test_agent_workflow_service.AgentWorkflowServiceTestCase.test_subtask_filename_is_cross_platform_safe -v` 通过；`.venv/bin/python -m unittest backend.tests.test_project_service.ProjectServiceTestCase.test_existing_novel_file_base64_limit_matches_frontend_file_limit backend.tests.test_project_service.ProjectServiceTestCase.test_existing_novel_takeover_imports_chapters_and_report -v` 通过；`npm run verify` 通过，398 个后端 unittest 通过，前端生产构建通过；`git diff --check` 通过。审查过程中 `npm run verify:ui` 通过，覆盖 Agent 章节计划、Obsidian 同步、Agent 维护产物跳转、架构总览、提示词、XP、人物复刻和项目迁移包导出导入。首次执行 `npm run release:test:macos` 时，`.app` 内 `novel-backend` 被 `Killed: 9`，应用内 sidecar 健康检查失败；签名脚本修复后重新执行 `npm run release:test:macos` 通过，完成 backend 回归、前端构建、Python sidecar 打包和健康检查、Tauri debug `.app` / dmg 构建、签名修复、应用内 sidecar 健康检查、`.app` 启动检查和测试包整理。

### 旧稿接管落地加固

- 修改摘要：旧稿接管现在会把接续位置、上一章结尾、最近章节和写作边界写入 `core_seed.txt`、`plot_structure.txt`、`character_state.txt`、`blueprint.txt`、`global_summary.txt` 与 `checkpoint.json`，让后续章节生成能直接读取接续简报和既有正文边界。恢复接管时会保留已有非空章节正文，不用旧稿覆盖作者已改内容；完成状态下如果报告或接续文档缺失，会自动补齐。拆章行号计算改为随扫描累计，避免长稿按章节反复扫描全文；超过 1000 章的旧稿会给出明确报错；前端会在读取前拒绝 30MB 以上旧稿文件。
- 影响范围：`project_takeover_service` 的拆章、报告、接续文档、恢复和知识库刷新结果记录；旧稿导入弹窗的文件大小检查；旧稿接管相关 backend 回归；README、项目 Agent 指令、核心引擎说明和技能流程回归清单。导入阶段仍不逐章触发模型核验，不改变普通资料导入、项目迁移包格式、章节生成接口、模型端点或 Obsidian 同步规则。
- 验证结果：`PYTHONPATH=backend python3 -m pytest backend/tests/test_project_service.py -k "existing_novel_takeover or existing_novel_split" -q` 通过，6 个测试通过；`PYTHONPATH=backend python3 -m pytest backend/tests/test_project_service.py -q` 通过，65 个测试通过；`python3 -m compileall -q backend/novel_backend/services/project_takeover_service.py backend/novel_backend/models.py backend/novel_backend/api/projects.py` 通过；`npm run build` 通过，前端生产构建通过；`npm run verify` 通过，396 个后端 unittest 通过，前端生产构建通过；本地服务函数烟测通过，确认 3 章旧稿导入后状态为 completed、下一章为第 4 章、章节文件和接续文档写入；约 221 万字、1000 章旧稿拆章用时 0.012 秒。端口级浏览器 / API 烟测未执行，当前沙箱禁止本地端口监听和本地 HTTP 访问，Vite / Uvicorn 启动与 `urllib` 访问均返回 `Operation not permitted`。

## 2026-06-04

### 旧稿接管导入

- 修改摘要：新增“旧稿”入口，用于把已经写了一部分的小说接入系统继续创作。导入支持粘贴正文或上传 `txt / md / markdown / docx / pdf` 单个旧稿文件，后端按章节标题拆分正文，新建作品后逐章写入 `chapters/`，生成旧稿章节清单、接管状态和接管报告，并刷新本地知识库。接管状态保存在 `.gaoxia/takeover/`，包含原稿副本、拆章结果、任务状态和报告；中断后可通过恢复接口继续处理。
- 影响范围：`projects` API 新增旧稿接管导入 / 状态 / 恢复接口；新增 `project_takeover_service`；作品列表新增“旧稿”和“迁移包”两个独立入口；新增旧稿导入弹窗和报告展示；README、核心引擎说明、技能流程与回归清单同步更新。导入阶段不逐章触发模型核验，不改变普通资料导入、项目迁移包格式、章节工作流、模型端点或 Obsidian 同步规则。
- 验证结果：`PYTHONPATH=backend python3 -m pytest backend/tests/test_project_service.py -k "existing_novel_takeover or existing_novel_split" -q` 通过，2 个测试通过；`PYTHONPATH=backend python3 -m pytest backend/tests/test_project_service.py -q` 通过，61 个测试通过；`python3 -m compileall -q backend/novel_backend/services/project_takeover_service.py backend/novel_backend/models.py backend/novel_backend/api/projects.py` 通过；`npm run build` 通过，前端生产构建通过；浏览器烟测使用临时 `NOVEL_DATA_DIR=/tmp/gaoxia-takeover-smoke` 打开 `http://127.0.0.1:1420/`，完成旧稿弹窗打开、两章示例旧稿提交、接管报告回显、`.gaoxia/takeover/` 状态和 `chapters/001.md / 002.md` 写入检查，浏览器控制台无 error / warning。

### 长篇章节连续性合同

- 修改摘要：章节生成、候选审校、章节核验和自动修订现在共用“章节连续性合同”。生成第 50/80 章这类中段章节时，后端会把目标位置、人物状态、滚动摘要、蓝图锚点、近期章节尾段、叙事状态账本、剧情债务、人物弧线、Obsidian 约束、项目记忆和资料证据整理为同一份约束输入；生成提示词会把合同视为优先约束，章节核验新增 `章节连续性合同` 维度，明确合同项缺失会计入自动修订触发条件，自动修订提示也会读取这份合同。
- 影响范围：`continuity_guard_service` 的连续性证据包、章节续写 / 候选审校 / 冲突检查共享上下文、`generation_service` 的续写提示词、`chapter_review_service` 的核验维度、`project_service` 的核验状态摘要、`chapter_auto_repair_service` 的修订提示、长篇叙事状态回归、README、核心引擎说明、技能流程与回归清单和项目 Agent 指令；不改变 Obsidian 同步规则、知识库 schema、模型端点或前端界面。
- 验证结果：`PYTHONPATH=backend pytest backend/tests/test_project_narrative_state_service.py::ProjectNarrativeStateServiceTestCase::test_chapter_50_continuity_contract_merges_internal_state_and_recent_history backend/tests/test_project_service.py::ProjectServiceTestCase::test_update_chapter_content_generates_chapter_review_report backend/tests/test_project_service.py::ProjectServiceTestCase::test_auto_repair_uses_chapter_scoped_obsidian_required_phrase` 通过，3 个测试通过；`PYTHONPATH=backend pytest backend/tests/test_generation_service.py::GenerationServiceTestCase::test_continuation_prompts_treat_continuity_contract_as_constraint backend/tests/test_project_narrative_state_service.py::ProjectNarrativeStateServiceTestCase::test_chapter_50_continuity_contract_merges_internal_state_and_recent_history` 通过，2 个测试通过；`PYTHONPATH=backend pytest backend/tests/test_context_builder.py backend/tests/test_generation_service.py backend/tests/test_project_narrative_state_service.py backend/tests/test_project_service.py` 通过，155 个测试通过；`npm run verify` 通过，389 个后端 unittest 通过，前端生产构建通过。

### 阿里百炼欠费错误提示修正

- 修改摘要：模型错误分类现在会把阿里百炼 / DashScope 返回的 `Arrearage`、`overdue-payment` 和 `account is in good standing` 识别为账单额度问题，不再误报为“模型请求格式不被接受”。
- 影响范围：模型请求失败分类、Prompt 历史里的 `error_kind / error_title / error_user_action`、前端展示的模型错误文案和相关 backend 回归；不改变模型请求参数、重试策略、模型端点或生成流程。
- 验证结果：`PYTHONPATH=backend python3 -m pytest backend/tests/test_model_error_service.py` 通过，5 个测试通过。

### 整书架构生成耗时优化

- 修改摘要：整书架构执行现在会在七个架构步骤之间保持前台模型会话，避免后台辅助巡检插入步骤间隙；每个步骤按当前模块裁剪无关 workspace 和超长上下文，并使用对应的输出 token 上限；知识库索引、模型版故事总览和系统记忆刷新改为整轮完成后统一排队，失败续跑进度仍按步骤保存。
- 影响范围：Agent `generate_architecture` 执行、分步架构模型提示、模型运行调度、辅助任务排队、整书架构续跑进度、相关 backend 回归、核心引擎说明和 Agent 执行架构说明；不改变架构步骤顺序、写回文件、模型端点、资料检索章节安全规则或章节生成质量约束。
- 验证结果：`PYTHONPATH=backend python3 -m pytest backend/tests/test_model_runtime_service.py` 通过，4 个测试通过；`PYTHONPATH=backend python3 -m pytest backend/tests/test_generation_service.py -k "architecture_step"` 通过，3 个测试通过；`PYTHONPATH=backend python3 -m pytest backend/tests/test_agent_service.py -k "full_architecture"` 通过，3 个测试通过；`PYTHONPATH=backend python3 -m pytest backend/tests/test_generation_service.py` 通过，16 个测试通过；`PYTHONPATH=backend python3 -m pytest backend/tests/test_agent_service.py` 通过，46 个测试通过；`PYTHONPATH=backend python3 -m pytest backend/tests/test_project_auxiliary_service.py` 通过，3 个测试通过；`PYTHONPATH=backend python3 -m pytest backend/tests/test_context_builder.py -k "ignores_model_overview_cache_for_chapter_scope"` 通过，1 个测试通过；`npm run verify` 通过，384 个后端 unittest 通过，前端生产构建通过。

### Agent 主对话长文本输入

- 修改摘要：Agent 主对话现在可直接提交长文本。`AgentMessage.content` 与线程消息保存上限统一为 1000000 字符；前端会保留最新用户长输入，只压缩旧历史；后端对超过 20000 字符的用户输入先筛掉明显无关、技术日志或网页样板段落，再按约 50000 字符分段导入项目资料库，并把资料标题加入本轮引用；如果全部候选段都不适合进入小说资料库，本轮只返回跳过提示，不创建 `Agent长输入-*` 资料；路由、规划、brainstorm、技能整理和执行轨迹使用“摘要 + 原文头尾 + 资料引用”的压缩文本，避免完整长文本直接进入模型上下文导致请求过大。
- 影响范围：Agent 主对话请求模型、线程历史请求构造、路由 / 规划模型上下文、长输入资料库自动导入和本地筛选、资料库 FTS5 检索、brainstorm 请求、用户技能整理请求、Agent 执行轨迹、请求校验错误测试、README、项目 Agent 指令、核心引擎说明和 Agent 执行架构说明；不改变作品正文、Obsidian Vault 写入策略、模型端点或桌面打包逻辑。
- 验证结果：`python3 -m py_compile backend/novel_backend/models.py backend/novel_backend/services/agent_service.py backend/tests/test_agent_service.py backend/tests/test_app.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_agent_service.AgentServiceTestCase.test_long_agent_message_is_accepted_and_compacted_for_planner backend.tests.test_agent_service.AgentServiceTestCase.test_long_agent_message_filters_unrelated_noise_before_importing_materials backend.tests.test_agent_service.AgentServiceTestCase.test_unrelated_long_agent_message_is_not_imported_as_material -v` 通过，3 个测试通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_agent_service -v` 通过，48 个测试通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_app -v` 通过，3 个测试通过；`npm run build` 通过。

### 项目迁移包完整迁移核查

- 修改摘要：项目迁移包导出继续保留完整作品目录和项目内 Obsidian Vault；外部 Obsidian Vault 场景下，除 `knowledge.db`、`obsidian_sync.json`、`narrative_state.json`、`project_distillation.json`、Agent 线程和 workflow 外，现在还会清理 `.gaoxia/learning/*.json/.jsonl` 以及其它 `.gaoxia` 状态文件里的外部 Obsidian 资料分析、自学习复盘和失败案例文本。遇到多段 JSON / JSONL 形式的状态文件时，迁移清理会按行写入迁移提示，不再让导出接口返回 500。导入路由也加入 API 路由级回归，确保 `/api/projects/migration/import` 能注册作品并保留章节正文。
- 影响范围：`project_service` 的迁移包外部 Vault 清理、`projects` API 静态导入路由、迁移相关 backend 回归、UI smoke 架构等待阈值、README、项目 Agent 指令、核心引擎说明和技能流程回归清单；不改变迁移包格式、项目内 Vault 迁移策略、章节正文复制、作品 ID 冲突处理或导入包路径安全校验。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_service.py backend/novel_backend/api/projects.py backend/tests/test_project_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_service.ProjectServiceTestCase.test_migration_package_scrubs_external_obsidian_index_but_keeps_project_state backend.tests.test_project_service.ProjectServiceTestCase.test_project_migration_import_api_route_registers_project -v` 通过，2 个测试通过；`npm run verify:ui` 通过，覆盖项目迁移包导出和导入；`npm run verify` 通过，390 个后端 unittest 通过，前端生产构建通过；`node --check scripts/verify-ui-smoke.mjs` 通过；`git diff --check` 通过。

### 迁移包导入成功提示保留

- 修改摘要：迁移包导入成功后，前端会在项目切换和仪表盘刷新完成后再显示“已导入《作品名》”提示，避免提示被项目切换监听器清空。导入数据、作品 ID 冲突处理和迁移包内容逻辑不变。
- 影响范围：`App.vue` 的迁移包导入成功提示显示时机、UI smoke 的迁移包导出导入检查；不改变后端迁移包导入导出、作品列表注册、章节文件复制或 Obsidian 外部 Vault 清理策略。
- 验证结果：`npm run verify:ui` 通过，覆盖临时后端、假模型、Vite preview、Obsidian 同步和检索、Agent Obsidian 维护产物跳转、项目迁移包导出导入；`npm run verify` 通过，379 个后端 unittest 通过，前端生产构建通过；`npm run verify:desktop` 通过，完成 backend 回归、前端构建、Python sidecar 打包和健康检查、Tauri debug `.app` / dmg 构建、签名修复、应用内 sidecar 健康检查和 `.app` 启动检查。

### Canvas Obsidian URI 内部链接节点

- 修改摘要：Canvas `type: link` 节点里的 `obsidian://open` 和 `obsidian://advanced-uri` URL 现在按 Vault 内部链接解析。URI 查询参数里的 `file / filepath / filename / path` 会作为目标笔记，`heading / header / section / block / blockid / block_id` 或 URI fragment 会保留为小节 / 块引用；这些节点会进入可解析链接、反向链接、图谱关系和 Canvas 内部链接节点正文。没有 `label / text` 的内部 URI link 节点作为 Canvas 边端点时，会使用目标笔记名生成关系标签，不再显示节点 id。目标是未来笔记时，章节安全内容会隐藏 URI、link 标签、目标路径和关系语义；HTTP(S) link 节点仍作为外部考据来源处理。
- 影响范围：`obsidian_service` 的 Canvas link 节点解析、Canvas 边和分组目标解析、Canvas 节点标签、links / resolved_links / backlinks / graph_relations、章节安全 Canvas 正文、Obsidian 回归测试、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 HTTP(S) 外部考据入口、Vault 写入策略、章节安全过滤规则或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "canvas_uri_link_nodes or canvas_link_nodes or uri_links" -q` 通过，3 passed, 68 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，71 passed；`npm run verify` 通过，379 个后端 unittest 通过，前端生产构建通过；`git diff --check` 通过，未跟踪的 `backend/novel_backend/services/obsidian_service.py` 和 `backend/tests/test_obsidian_service.py` 用 `git diff --no-index --check` 检查无空白问题；相对日期扫描只命中 `docs/去AI技能说明.md` 中的固定套版画面词例句，不是日期引用。

## 2026-06-03

### Obsidian URI 内部链接解析

- 修改摘要：Obsidian 同步现在会把 `obsidian://open` 和 `obsidian://advanced-uri` 这类从 Obsidian 复制出来的内部 URI 当作 Vault 内链接解析。URI 查询参数里的 `file / filepath / filename / path` 会作为 Vault 根路径目标，`heading / header / section / block / blockid / block_id` 或 URI fragment 会保留为小节 / 块引用；frontmatter 关系字段、正文 Markdown 链接和 HTML `<a>` 链接都会生成可解析链接、反向链接和图谱关系。目标是未来笔记时，章节安全内容会隐藏链接标签、路径和关系语义。
- 影响范围：`obsidian_service` 的 URI 目标解析、Markdown / HTML 内链归一化、frontmatter 关系图谱、backlinks、章节安全预览、Obsidian 回归测试、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 HTTP(S) 考据入口、其它 URL scheme 处理、Vault 写入策略、章节安全过滤规则或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "uri_links or html_anchor or markdown_links_unescape" -q` 通过，3 passed, 67 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，70 passed；`npm run verify` 通过，378 个后端 unittest 通过，前端生产构建通过；`git diff --check` 通过，未跟踪的 `backend/novel_backend/services/obsidian_service.py` 和 `backend/tests/test_obsidian_service.py` 用 `git diff --no-index --check` 检查无空白问题；相对日期扫描只命中 `docs/去AI技能说明.md` 中的固定套版画面词例句，不是日期引用。

### Obsidian 章节计划类层级标签章节范围

- 修改摘要：Obsidian `tags` 里的章节计划类层级标签现在会同时提供类型和章节范围。作者只写 `#章节计划/58`、`#章节合同/58-60`、`#场景卡/59` 或 `#scene-plan/59`，不写 `chapter_range`、文件名也不带章节号时，系统仍会把笔记识别为章节计划 / 章节合同 / 场景计划，并按标签里的章节过滤知识检索和章节上下文。普通 `#人物/主角`、`#剧情债务/伏笔` 不会被当成章节范围。
- 影响范围：`obsidian_service` 的标签章节范围解析、Obsidian 知识检索章节过滤、层级标签类型推断相关回归、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变显式 `chapter_range` 优先级、Vault 写入策略、章节安全过滤规则或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "chapter_scope or nested_tags" -q` 通过，7 passed, 62 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，69 passed；`npm run verify` 通过，377 个后端 unittest 通过，前端生产构建通过；`git diff --check` 通过。

### Obsidian frontmatter 未引号井号标签

- 修改摘要：Obsidian frontmatter 的 `tags / tag / 标签` 字段现在会保留未加引号的井号标签。作者手写 `tags: #章节/44-45 #剧透/43`，或多行写 `tags:` 下的 `- #人物/配角`、`- #第58章` 时，会解析成真实标签，并继续参与类型推断、章节范围和剧透边界；非标签字段里的 `#` 仍按行尾注释处理。
- 影响范围：`obsidian_service` 的 frontmatter 标签字段解析、行尾注释处理、层级标签类型推断、章节范围 / 剧透边界标签解析、相关 backend 回归、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变普通字段的 YAML 注释规则、显式 type 优先级、显式章节范围优先级、Vault 写入策略、章节安全过滤规则或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "extracts_chapter_scope or nested_tags or inline_comments" -q` 通过，3 passed, 66 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，69 passed；`npm run verify` 通过，377 个后端 unittest 通过，前端生产构建通过；`git diff --check` 通过。

### Obsidian 正文标签全角分层

- 修改摘要：Obsidian Markdown 正文标签现在支持全角斜杠、`+`、中文全角波浪线和常见长横线范围符。作者只在正文写 `#人物／主角`、`#适用章节／40～42`、`#剧透／39` 或 `#Ch58+` 时，也会进入类型推断、章节范围和剧透边界解析；正文标签会与 frontmatter / inline Properties 标签合并参与类型和结构化上下文解析。
- 影响范围：`obsidian_service` 的正文标签识别、层级标签类型推断、章节范围 / 剧透边界标签解析、Markdown 笔记结构化上下文、相关 backend 回归、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变显式 type 优先级、显式章节范围优先级、Vault 写入策略、章节安全过滤规则或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "extracts_chapter_scope or nested_tags" -q` 通过，2 passed, 67 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，69 passed；`npm run verify` 通过，377 个后端 unittest 通过，前端生产构建通过；`git diff --check` 通过。

### Obsidian Properties 分号列表

- 修改摘要：Obsidian 普通列表型 Properties 现在支持半角分号和中文分号分隔。作者在 `aliases / keywords / source_notes / required_phrases / forbidden_phrases / tags` 里写 `潮师；守账人`、`当前线索；未建笔记` 或 `tags: "人物；第58章"` 时，会解析成多个别名、检索词、关系目标、写作约束或标签；YAML flow sequence 仍保留引号内逗号，不会破坏带逗号的别名、关键词和链接标签。
- 影响范围：`obsidian_service` 的 frontmatter / 内联属性列表解析、Obsidian 标签解析、图谱关系、必写 / 禁写约束、章节范围标签识别、相关 backend 回归、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变显式章节范围优先级、Vault 写入策略、章节安全过滤规则或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "frontmatter_flow_lists" -q` 通过，1 passed, 68 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，69 passed；`git diff --check` 通过；`npm run verify` 通过，377 个后端 unittest 通过，前端生产构建通过。

### Obsidian 来源章节字段别名

- 修改摘要：Obsidian 章节档案的来源章节字段现在支持 `source_chapter_indexes / chapter_sources / 章节来源 / 来源章 / 来源章节号` 等写法；正文里写 `来源章：第 58 章、第 60 章` 也会按来源章节解析。保留这些别名的作者整理版章节档案仍按最晚来源章开放，早期章节不会提前检索到后段档案。
- 影响范围：`obsidian_service` 的来源章节字段解析、章节档案可见范围、知识检索章节过滤、相关 backend 回归、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统与蒸馏接入说明、技能流程回归清单和测试反馈清单；不改变显式 `chapter_range` 优先级、Vault 写入策略、章节安全过滤规则或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "source_chapters" -q` 通过，1 passed, 68 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，69 passed；`git diff --check` 通过；`npm run verify` 通过，377 个后端 unittest 通过，前端生产构建通过。

### Obsidian source_ids 章节缩写识别

- 修改摘要：Obsidian 章节档案的 `source_ids` 现在支持 `chapter-058`、`chap-058`、`ch058`、`Chapter 58` 这类章节来源 ID。多个来源 ID 仍按最晚来源章节开放，普通 `archive-ch061` 这类业务 ID 不会被误当成章节。
- 影响范围：`obsidian_service` 的来源章节推断、章节档案可见范围、知识检索章节过滤、相关 backend 回归、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统与蒸馏接入说明、技能流程回归清单和测试反馈清单；不改变显式 `chapter_range` 优先级、Vault 写入策略、章节安全过滤规则或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "source_id" -q` 通过，4 passed, 65 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，69 passed；`git diff --check` 通过；`npm run verify` 通过，377 个后端 unittest 通过，前端生产构建通过。

### Obsidian 嵌套隐藏 Callout 隔离

- 修改摘要：Obsidian Markdown 和 Canvas 文本里的隐藏 callout 现在会按引用层级处理。普通 `note / info` callout 内部嵌套 `> > [!spoiler]`、`> > [!private]`、`> > [!draft]`、`> > [!no-ai]` 或中文隐藏类型时，只排除嵌套隐藏块里的双链、标签、关系字段、必写项和剧透词，外层公开 callout 内容仍会进入知识索引、图谱关系和章节上下文。
- 影响范围：`obsidian_service` 的 AI 可见正文清理、隐藏 callout 层级识别、Markdown / Canvas 知识同步、正文内联属性解析、图谱关系、必写 / 禁写约束、章节安全内容、相关 backend 回归、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变普通公开 callout 的正文解析、同一隐藏引用块的延续规则、Vault 写入策略、章节安全过滤规则或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "hidden_callouts" -q` 通过，1 passed, 67 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，68 passed；`git diff --check` 通过；`npm run verify` 通过，376 个后端 unittest 通过，前端生产构建通过。

### Obsidian details 正文状态隔离

- 修改摘要：Obsidian Markdown 和 Canvas 文本里的 HTML `<details>` 折叠块现在会读取正文内联状态声明。普通折叠标题下如果正文写了 `draft:: true`、`private:: true`、`archived:: true` 或项目配置里的过滤状态，只排除这一段折叠内容，不会让整篇 Markdown 笔记或整张 Canvas 失效；公开 details 里的 `draft:: false` 仍按正文解析。
- 影响范围：`obsidian_service` 的 AI 可见正文清理、HTML details 正文状态识别、Markdown / Canvas 知识同步、正文内联属性解析、Obsidian 来源知识索引、章节化知识检索、章节安全内容、相关 backend 回归、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 frontmatter 状态优先级、普通公开 details 的正文解析、Vault 写入策略、章节安全过滤规则或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "ignores_comments_and_code_blocks or canvas_hidden_nodes" -q` 通过，2 passed, 66 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，68 passed；`git diff --check` 通过；`npm run verify` 通过，376 个后端 unittest 通过，前端生产构建通过。

### Obsidian details 正文级 AI 可见性隔离

- 修改摘要：Obsidian Markdown 和 Canvas 文本里的 HTML `<details>` 折叠块现在会读取正文内联 AI 可见性声明。普通折叠标题下如果正文写了 `no_ai:: true`、`AI不可用:: 是`、`#no-ai` 或 `#AI不可用`，只排除这一段折叠内容，不会让整篇 Markdown 笔记或整张 Canvas 失效；公开 `<details>` 仍按正文解析。Canvas 文本节点里的 `no_ai:: false` 也会按明确可用处理，不再因为出现 `no_ai` 字样而被误删。
- 影响范围：`obsidian_service` 的 AI 可见正文清理、HTML details 隐藏内容识别、正文内联属性解析、Canvas 文本节点 AI 可见性判断、Obsidian 来源知识索引、章节化知识检索、章节安全内容、相关 backend 回归、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 frontmatter 解析、普通公开 details 的正文解析、Vault 写入策略、章节安全过滤规则或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "ignores_comments_and_code_blocks or canvas_hidden_nodes" -q` 通过，2 passed, 66 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，68 passed；`git diff --check` 通过；`npm run verify` 通过，376 个后端 unittest 通过，前端生产构建通过。

### Obsidian Canvas 节点级 AI 可见性隔离

- 修改摘要：Obsidian Canvas 同步现在按节点处理 AI 可见性和过滤状态。单个 `no_ai:: true`、`AI不可用:: 是`、`#no-ai`、`draft:: true` 或过滤状态的 Canvas 文本 / group 节点会从 Canvas 正文、标签、关系、必写 / 禁写约束和检索内容中排除；隐藏 group 内部 file 节点也会排除；同一张 Canvas 里的公开节点仍会进入知识索引、图谱关系、章节上下文和反向链接。
- 影响范围：`obsidian_service` 的 Canvas 记录构建、Canvas 文本节点 AI 可见性、Canvas group 节点过滤、Canvas 边关系过滤、Obsidian 来源知识索引、章节化知识检索、章节安全内容、相关 backend 回归、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 Markdown 笔记过滤规则、Vault 写入策略、`knowledge.db` 表结构或公开 Canvas 节点解析规则。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "canvas_hidden_nodes" -q` 通过，1 passed, 67 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，68 passed；`git diff --check` 通过；`npm run verify` 通过，376 个后端 unittest 通过，前端生产构建通过。

### Obsidian HTML details 隐藏折叠块隔离

- 修改摘要：Obsidian Markdown 和 Canvas 文本里的隐藏 HTML `<details>` 折叠块现在会从 AI 可见正文中排除；当 `summary` 或 `class` 等属性带 `spoiler / future / private / hidden / draft / todo / no-ai`，或带 `剧透 / 未来 / 隐藏 / 私密 / 草稿 / 待定 / 勿用 / 不引用` 时，折叠块里的 `[[未来笔记]]`、`#标签`、`source_notes:: ...`、`required_phrases:: ...` 或 `[summary:: ...]` 不再进入图谱关系、反向链接、标签章节范围、必写 / 禁写约束、知识检索预览或章节上下文；普通公开 HTML details 仍按正文解析。
- 影响范围：`obsidian_service` 的 AI 可见正文清理、Markdown / Canvas 知识同步、Obsidian 图谱关系、标签、正文内联属性、必写 / 禁写约束、章节安全内容、相关 backend 回归、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 frontmatter 解析、普通 HTML details 的公开正文解析、Vault 写入策略、章节安全过滤规则或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "ignores_comments_and_code_blocks_for_ai_context_and_graph" -q` 通过，1 passed, 66 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，67 passed；`npm run verify` 通过，375 个后端 unittest 通过，前端生产构建通过。

### Obsidian 删除线和删除标签隔离

- 修改摘要：Obsidian Markdown 和 Canvas 文本里的 Markdown 删除线以及 HTML `<del> / <s> / <strike>` 删除标签现在会从 AI 可见正文中排除；废弃内容中的 `[[未来笔记]]`、`#标签`、`source_notes:: ...`、`required_phrases:: ...` 或 `[summary:: ...]` 不再进入图谱关系、反向链接、标签章节范围、必写 / 禁写约束、知识检索预览或章节上下文。
- 影响范围：`obsidian_service` 的 AI 可见正文清理、Markdown / Canvas 知识同步、Obsidian 图谱关系、标签、正文内联属性、必写 / 禁写约束、章节安全内容、相关 backend 回归、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 frontmatter 解析、Vault 写入策略、章节安全过滤规则或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "ignores_comments_and_code_blocks_for_ai_context_and_graph" -q` 通过，1 passed, 66 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，67 passed；`git diff --check` 通过；尾随空白扫描无输出；`npm run verify` 通过，375 个后端 unittest 通过，前端生产构建通过。

### Obsidian inline code 隔离

- 修改摘要：Obsidian Markdown 和 Canvas 文本里的 inline code 现在会从 AI 可见正文中排除；代码片段中的 `[[未来笔记]]`、`#标签`、`source_notes:: ...`、`required_phrases:: ...` 或 `[summary:: ...]` 不再进入图谱关系、反向链接、标签章节范围、必写 / 禁写约束、知识检索预览或章节上下文。
- 影响范围：`obsidian_service` 的 AI 可见正文清理、Markdown / Canvas 知识同步、Obsidian 图谱关系、标签、正文内联属性、必写 / 禁写约束、章节安全内容、相关 backend 回归、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 frontmatter 解析、Vault 写入策略、章节安全过滤规则或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "ignores_comments_and_code_blocks_for_ai_context_and_graph" -q` 通过，1 passed, 66 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，67 passed；`git diff --check` 通过；尾随空白扫描无输出；`npm run verify` 通过，375 个后端 unittest 通过，前端生产构建通过。

### Obsidian 章节范围全角波浪线

- 修改摘要：Obsidian 章节范围推断现在支持 `#第58～60章`、`#Ch58～60`、`第58～60章-计划.md` 和 `ch58～60-plan.md` 这类中文全角波浪线及常见长横线分隔符；不写 frontmatter 时，也会按第 58 到 60 章过滤标签、文件名和路径推断出的章节范围。
- 影响范围：`obsidian_service` 的章节标签和文件名 / 路径范围推断、知识检索过滤、章节上下文选择、相关 backend 回归、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变显式 `chapter_range` 优先级、Vault 写入策略、章节安全过滤规则或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "infers_chapter_scope_from_note_and_canvas_paths" -q` 通过，1 passed, 66 deselected；`git diff --check` 通过；尾随空白扫描无输出；`npm run verify` 通过，375 个后端 unittest 通过，前端生产构建通过。

### Obsidian frontmatter block scalar 缩进标记

- 修改摘要：Obsidian frontmatter 的多行属性现在支持 `summary: >2-`、`keywords: |2-` 这类带缩进标记和 chomping 标记的 YAML block scalar。作者把摘要、检索词、来源笔记或必写 / 禁写短语写成这种格式时，同步会读取真实正文，链接、反向链接、图谱关系和章节约束会进入章节上下文；指向未来笔记的内容仍按目标章节隐藏。
- 影响范围：`obsidian_service` 的 frontmatter block scalar 标记识别、Obsidian 元数据同步、知识检索内容、章节约束、图谱关系、相关 backend 回归、README、项目 Agent 指令、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略、章节安全过滤规则或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "frontmatter_block_scalars_feed_summary_terms_and_links or frontmatter_sequence_block_scalars_feed_metadata" -q` 通过，2 passed, 65 deselected；`git diff --check` 通过；`npm run verify` 通过，375 个后端 unittest 通过，前端生产构建通过。

### Obsidian frontmatter 列表项多行文本

- 修改摘要：Obsidian frontmatter 的列表字段现在支持单项写成 `- >` 或 `- |`。作者把 `keywords / source_notes / required_phrases / forbidden_phrases` 里的某一项写成多行文本时，同步会读取真实正文，检索词、来源关系、必写 / 禁写约束、链接和反向链接都会进入章节上下文；指向未来笔记的内容仍按目标章节隐藏。
- 影响范围：`obsidian_service` 的 frontmatter 序列解析、Obsidian 元数据同步、知识检索内容、章节约束、图谱关系、相关 backend 回归、README、项目 Agent 指令、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略、章节安全过滤规则或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "frontmatter_sequence_block_scalars_feed_metadata or frontmatter_block_scalars_feed_summary_terms_and_links" -q` 通过，2 passed, 65 deselected；`git diff --check` 通过；`npm run verify` 通过，375 个后端 unittest 通过，前端生产构建通过。

### Obsidian frontmatter 顶层嵌套对象

- 修改摘要：Obsidian frontmatter 现在会保留 `chapter_contract:` 这类顶层嵌套对象，不再把缩进下的字段误读成同级字段；对象里的 `chapter_range / objective / required_beats / acceptance_checks / evidence_sources / related_characters` 等直接子字段会进入章节范围、章节上下文、知识检索、链接、反向链接和图谱关系，未来笔记仍按目标章节隐藏。
- 影响范围：`obsidian_service` 的 frontmatter 解析、Obsidian 章节计划 / 章节合同上下文、知识检索内容、章节范围识别、图谱关系、相关 backend 回归、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略、章节安全过滤规则或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "frontmatter_nested_mapping_feeds_chapter_plan_context or frontmatter_object_lists_feed_chapter_plan_context" -q` 通过，2 passed, 64 deselected；`git diff --check` 通过；`npm run verify` 通过，374 个后端 unittest 通过，前端生产构建通过。

### 可见 callout 表格进入 Obsidian 章节上下文

- 修改摘要：Obsidian 普通 `note / info` 等可见 callout 里的 Markdown 表格现在会按表格解析，行首 `>` 不再阻止 `章节目标 / 验收项 / 证据来源 / 相关人物` 等列进入章节合同上下文、知识检索和图谱关系；单元格里的 `\|` 仍会还原为普通 `|`，未来笔记仍按目标章节隐藏。
- 影响范围：`obsidian_service` 的 Markdown 表格行解析、可见 callout 中的 Obsidian 章节计划 / 章节合同上下文、知识检索内容、图谱关系、相关 backend 回归、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变隐藏 callout 过滤、Vault 写入策略、章节安全过滤规则或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "tables_feed_chapter_contract_context_and_graph" -q` 通过，3 passed, 62 deselected；`git diff --check` 通过；`npm run verify` 通过，373 个后端 unittest 通过，前端生产构建通过。

### Canvas 文本节点表格进入 Obsidian 章节上下文

- 修改摘要：Obsidian Canvas 文本节点里的 Markdown 表格现在会复用 Markdown 笔记的表格解析，`章节目标 / 必须节拍 / 禁写动作 / 验收项 / 证据来源 / 相关人物` 等列会进入章节合同上下文、知识检索和图谱关系；单元格里的 `\|` 仍会还原为普通 `|`，未来笔记仍按目标章节隐藏。
- 影响范围：`obsidian_service` 的 Canvas 记录构建、Obsidian Canvas 章节计划 / 章节合同上下文、知识检索内容、图谱关系、相关 backend 回归、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略、章节安全过滤规则或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "canvas_text_tables_feed_chapter_contract_context_and_graph" -q` 通过，1 passed, 63 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "markdown_tables_feed_chapter_contract_context_and_graph or canvas_text_tables_feed_chapter_contract_context_and_graph" -q` 通过，2 passed, 62 deselected；`git diff --check` 通过；`npm run verify` 通过，372 个后端 unittest 通过，前端生产构建通过。

### Obsidian 合同表格转义竖线

- 修改摘要：Obsidian Markdown 表格单元格里的 `\|` 现在会还原为普通 `|` 后再进入章节合同、章节计划和知识上下文，避免验收项、节拍或关系描述带着 Markdown 转义符进入生成提示；表格列拆分仍会把 `\|` 保留在同一个单元格内。
- 影响范围：`obsidian_service` 的 Markdown 表格单元格清理、Obsidian 章节合同 / 章节计划上下文、知识检索内容、相关 backend 回归、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略、章节安全过滤规则或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "markdown_tables_feed_chapter_contract_context_and_graph" -q` 通过，1 passed, 62 deselected；`git diff --check` 通过；`npm run verify` 通过，371 个后端 unittest 通过，前端生产构建通过。

### Agent Obsidian 维护产物精准打开维护队列

- 修改摘要：Agent 结果里的 `obsidian_maintenance` 产物打开自学习面板时，现在会把产物 `metadata.suggestion_ids` 一起传给维护队列；自学习面板会在来源章节筛选之外叠加产物关联项筛选，并显示“清除产物筛选”按钮。这样从结果产物进入维护队列时，只看到这次产物对应的待审草稿，而不是同章节的全部维护项；UI smoke 脚本会验证清除产物筛选后仍保留来源章节筛选并显示本章维护队列。
- 影响范围：Agent 产物跳转、自学习面板 Obsidian 维护队列筛选、UI smoke 的 Agent Obsidian 维护产物跳转检查、README、项目 Agent 指令、Agent 执行架构说明、技能流程回归清单和测试反馈清单；不改变后端维护建议生成、Obsidian Vault 写入策略、维护草稿保存 / 发布接口或章节安全过滤规则。
- 验证结果：`node --check scripts/verify-ui-smoke.mjs` 通过；`node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` 通过；`git diff --check` 通过；`npm run verify` 通过，371 个后端 unittest 通过，前端生产构建通过；`npm run verify:ui` 未跑起来，当前环境拒绝监听 `127.0.0.1`，报错为 `listen EPERM: operation not permitted 127.0.0.1`。

### 主对话快捷技能接入 Agent action 元数据

- 修改摘要：主对话的“看现状 / 完善架构 / 判断本章 / 续写本章”快捷按钮现在会把对应内置技能 ID 写入 `active_skill_ids`；后端会读取内置技能的 `agent_action_kind / agent_action_mode / agent_requires_confirmation` 修正计划动作，例如把 `chapter-draft` 路由为 `chapter_workflow/draft`，把 `chapter-humanize` 路由为 `rewrite_chapter/humanize`。内置技能 ID 只参与计划动作选择，不会当成用户自定义技能 prompt 注入执行。
- 影响范围：Agent 计划生成、模型规划回退、本地主对话快捷按钮、`NovelWorkflowPanel` 请求参数、Agent 后端回归、README、项目 Agent 指令、Agent 执行架构说明、技能流程回归清单和测试反馈清单；不改变技能库专用面板接口、章节正文写回规则、Obsidian Vault 写入策略或用户自定义技能 prompt 注入方式。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/agent_service.py backend/tests/test_agent_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_agent_service.py -k "active_builtin or model_planner_receives_skill_catalog_context or draft_workflow_uses_longform_supervision_steps" -q` 通过，4 passed, 39 deselected；`node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` 通过；`git diff --check` 通过；`npm run verify` 通过，371 个后端 unittest 通过，前端生产构建通过；`npm run verify:ui` 未跑起来，当前环境拒绝监听 `127.0.0.1`，报错为 `listen EPERM: operation not permitted 127.0.0.1`。

### 技能目录和 Agent action 元数据统一

- 修改摘要：内置技能行为新增 `agent_action_kind / agent_action_mode / agent_requires_confirmation`，后端用统一注册表维护默认行为；初始化内置技能和读取旧版技能 JSON 时会补齐缺失字段。Agent planner 的技能目录上下文现在会显示对应 action 和确认要求，前端本地技能目录 fallback 也同步这些字段。
- 影响范围：`SkillBehavior` 模型、内置技能配置初始化、技能目录读取、Agent planner 技能目录提示、前端技能目录 fallback、技能库面板行为归一化、相关后端回归、README、项目 Agent 指令、Agent 执行架构说明、技能流程回归清单和测试反馈清单；不改变现有专用技能接口、章节正文写回规则、Obsidian Vault 写入策略或自定义技能默认执行面板。
- 验证结果：`python3 -m py_compile backend/novel_backend/models.py backend/novel_backend/services/skill_registry.py backend/novel_backend/services/config_service.py backend/novel_backend/services/skill_service.py backend/novel_backend/services/agent_service.py backend/tests/test_skill_service.py backend/tests/test_agent_service.py` 通过；`node --check src/lib/skillCatalog.js` 通过；`PYTHONPATH=backend pytest backend/tests/test_skill_service.py -q` 通过，7 passed；`PYTHONPATH=backend pytest backend/tests/test_agent_service.py -k "model_planner_receives_skill_catalog_context or draft_workflow_uses_longform_supervision_steps or rewrite_request_gets_continuity_review_step" -q` 通过，3 passed, 38 deselected；`node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` 通过；`git diff --check` 通过；`npm run verify` 通过，369 个后端 unittest 通过，前端生产构建通过；`npm run verify:ui` 未跑起来，当前环境拒绝监听 `127.0.0.1`，报错为 `listen EPERM: operation not permitted 127.0.0.1`。

### Agent workflow 恢复和中断

- 修改摘要：Agent workflow 状态新增 `CANCELLING / CANCELLED`，前端 `useAgentSession` 可按 `task_id` 读取 workflow 摘要恢复 action timeline；停止当前长任务时会调用后端 interrupt 接口并写入项目运行状态，Agent 执行循环在动作边界停止后续动作。断线后的恢复读取项目目录里的 workflow 文件，不伪装成重新接入原 SSE。
- 影响范围：`agent_workflow_service` 的状态文件、`agent_service` 执行动作边界、`studio` Agent workflow 查询和中断接口、`useAgentSession`、前端 API、Agent 工作台停止按钮、相关后端回归、README、项目 Agent 指令、Agent 执行架构说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变模型同步调用本身，不强行终止已经进入线程内的单次模型请求，不改变 Obsidian Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/agent_workflow_service.py backend/novel_backend/services/agent_service.py backend/novel_backend/api/studio.py backend/tests/test_agent_workflow_service.py backend/tests/test_agent_service.py` 通过；`node --check src/composables/useAgentSession.js` 和 `node --check src/lib/api.js` 通过；`PYTHONPATH=backend pytest backend/tests/test_agent_workflow_service.py -q` 通过，4 passed；`PYTHONPATH=backend pytest backend/tests/test_agent_service.py -k "approved_plan_stops_after_workflow_interrupt_request or approved_plan_executes_and_updates_chapter" -q` 通过，2 passed, 39 deselected；`node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` 通过；`git diff --check` 通过；`npm run verify` 通过，368 个后端 unittest 通过，前端生产构建通过；最终前端恢复状态处理小修后，`npm run build` 通过；`npm run verify:ui` 未跑起来，当前环境拒绝监听 `127.0.0.1`，报错为 `listen EPERM: operation not permitted 127.0.0.1`。

### Agent 执行阶段摘要分组

- 修改摘要：Agent 执行结果现在会追加最终 `session_result` 事件；前端新增 Agent 阶段摘要展示，把 `event_blocks` 按计划阶段、执行阶段和结果阶段分组显示。历史线程里即使已有 action timeline 和产物卡片，也会保留这层阶段概览，方便作者回看长任务的计划、动作和最终结果。
- 影响范围：`agent_service` 的执行结果事件、`AgentEventBlockSummary` 前端组件、Agent 工作台历史消息展示、UI smoke 的 Agent 执行断言、相关 Agent 后端单测、README、项目 Agent 指令、Agent 执行架构说明和技能流程回归清单；不改变 SSE 事件协议、workflow 状态文件结构、章节正文保存规则或 Obsidian Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/agent_service.py backend/tests/test_agent_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_agent_service.py -k "approved_plan_executes_and_updates_chapter" -q` 通过，1 passed, 39 deselected；`node --check scripts/verify-ui-smoke.mjs` 通过；`node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` 通过；`npm run verify` 通过，366 个后端 unittest 通过，前端生产构建通过；`npm run verify:ui` 未跑起来，当前沙箱拒绝监听 `127.0.0.1`，报错为 `listen EPERM: operation not permitted 127.0.0.1`。

### Obsidian 外部考据字段别名扩展

- 修改摘要：Obsidian Markdown / Canvas 的外部考据入口新增 `references / sources / citations / 资料来源 / 参考资料 / 考据来源 / 外部来源` 等 Properties 别名；这些字段里的 HTTP(S) 会进入 `external_links`，可读来源名会进入 `external_references`，但不会写入 Vault 内部 `links / backlinks / graph_relations` 或生成未解析链接维护建议。
- 影响范围：`obsidian_service` 的外部考据字段识别、Obsidian 同步摘要、知识索引内容、章节上下文考据来源展示、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构、Vault 写入策略或内部图谱关系。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "markdown_external_links" -q` 通过，1 passed, 62 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，63 passed；`git diff --check` 通过；`npm run verify` 通过，366 个后端 unittest 通过，前端生产构建通过。

### Obsidian 考据来源进入任务蒸馏

- 修改摘要：任务蒸馏材料备注现在会携带目标章节可见 Obsidian 笔记里的 `external_references`，在 Agent 资料分析和章节任务准备阶段显示“考据来源”；项目蒸馏签名也会记录 `external_references / external_links`，来源名或 URL 变化后会刷新对应蒸馏资料。
- 影响范围：`project_distillation_service` 的 Obsidian 材料备注和蒸馏签名、`test_project_service` 的任务蒸馏回归、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 Obsidian 同步格式、Vault 写入策略、`knowledge.db` 表结构或前端接口。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_distillation_service.py backend/tests/test_project_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_project_service.py -k "task_distillation_prompt_filters_obsidian_summary_by_chapter_scope or distillation_signature_includes_obsidian_external_references" -q` 通过，2 passed, 56 deselected；`git diff --check` 通过；`npm run verify` 通过，366 个后端 unittest 通过，前端生产构建通过。

### Obsidian 考据来源进入章节任务卡和 Agent 规划

- 修改摘要：目标章节可见 Obsidian 笔记里的 `external_references` 现在会进入叙事状态账本章节任务卡，并写入模型叙事编辑提示、Agent 路由 / 规划能力上下文和自学习面板最新章节任务卡。章节计划、资料考据和写作执行会看到同一批“考据来源”，避免来源只停留在 Obsidian 笔记卡片或章节上下文里。
- 影响范围：`project_narrative_state_service` 的 Obsidian 章节指导和章节任务卡字段、`self_evolution_service` 的 Agent 能力上下文、技能库自学习面板最新章节任务卡、UI smoke、自学习和叙事状态 backend 回归、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 Obsidian 同步格式、Vault 写入策略或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/novel_backend/services/self_evolution_service.py backend/tests/test_project_narrative_state_service.py backend/tests/test_self_evolution_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_project_narrative_state_service.py -k "chapter_scoped_obsidian_guidance" -q` 通过，1 passed, 56 deselected；`PYTHONPATH=backend pytest backend/tests/test_self_evolution_service.py -k "target_chapter_obsidian_tasks" -q` 通过，2 passed, 12 deselected；`node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` 通过；`node --check scripts/verify-ui-smoke.mjs` 通过；`npm run verify` 通过，365 个后端 unittest 通过，前端生产构建通过；`npm run verify:ui` 未能启动，当前沙箱拒绝监听 `127.0.0.1`，报错为 `listen EPERM: operation not permitted 127.0.0.1`。

### 架构总览 Obsidian 考据来源展示

- 修改摘要：架构总览的“知识检索”页签里，Obsidian 笔记卡片现在会优先显示 `external_references` 里的可读考据来源；没有来源名时继续显示外部链接。UI smoke 的架构总览检查会进入知识检索页签，验证测试 Vault 的“考据来源”能在架构总览中出现。
- 影响范围：`StoryOverviewPanel` 的 Obsidian 笔记卡片、`scripts/verify-ui-smoke.mjs` 的架构总览检查、README、项目 Agent 指令、核心引擎说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 Obsidian 同步格式、Vault 写入策略、`knowledge.db` 表结构或章节上下文内容。
- 验证结果：`node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` 通过；`node --check scripts/verify-ui-smoke.mjs` 通过；`git diff --check` 通过；`npm run verify` 通过，365 个后端 unittest 通过，前端生产构建通过；`npm run verify:ui` 未能启动，当前沙箱拒绝监听 `127.0.0.1`，报错为 `listen EPERM: operation not permitted 127.0.0.1`。

### Obsidian 外部考据来源进入章节上下文和同步统计

- 修改摘要：Markdown 笔记和 Canvas 里的 HTTP(S) 考据入口现在会写入 `external_links`，Markdown 链接标题、HTML `<a>` 文本、Canvas link 标签和结构化来源名会写入 `external_references`；支持 `source_url / reference_links / research_links / external_links / url / 资料链接 / 参考链接 / 考据链接` 等 Properties、正文内联属性、Markdown 外部链接、引用式链接定义、裸 URL、HTML `<a>` 和 Canvas link 节点 URL；同步状态会计算 `external_link_count`，同步面板会显示考据链接数量，笔记卡片、章节上下文和设定检查清单会优先显示“考据来源”。YAML 列表项里的 `https://` 不再被误当成对象字段分隔符。
- 影响范围：`ObsidianNoteSummary` / `ObsidianVaultState` 模型、`obsidian_service` 的 frontmatter 列表解析 / 外部链接和来源名提取 / 知识内容头部 / 同步状态统计、`context_builder` 的 Obsidian 设定笔记和检查清单渲染、`SkillLibraryPanel` 的 Obsidian 同步指标和笔记卡片、UI smoke Vault 样本、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略、`knowledge.db` 表结构或 Vault 内部 links / backlinks / graph_relations。
- 验证结果：`python3 -m py_compile backend/novel_backend/models.py backend/novel_backend/services/obsidian_service.py backend/novel_backend/services/context_builder.py backend/tests/test_obsidian_service.py backend/tests/test_context_builder.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "external_links or canvas_link_nodes" -q` 通过，2 passed, 61 deselected；`PYTHONPATH=backend pytest backend/tests/test_context_builder.py -q` 通过，22 passed；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，63 passed；`node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` 通过；`node --check scripts/verify-ui-smoke.mjs` 通过；`git diff --check` 通过；`npm run verify` 通过，365 个后端 unittest 通过，前端生产构建通过；`npm run verify:ui` 未能启动，当前沙箱拒绝监听 `127.0.0.1`，报错为 `listen EPERM: operation not permitted 127.0.0.1`。

### Obsidian 笔记嵌入进入章节上下文预览

- 修改摘要：Obsidian `![[...]]` 指向 Markdown 或 Canvas 笔记时会写入 `embedded_links`；章节上下文和设定检查清单会展示目标章节可见嵌入笔记的短预览，让章节计划、场景卡或合同嵌入直接参与写作提示。图片、PDF、音频等附件嵌入以及 Markdown 图片、HTML 媒体标签仍会从 AI 可见正文、图谱关系和章节上下文中排除；未来嵌入目标不会在早期章节预览里显示。
- 影响范围：`ObsidianNoteSummary` 模型、`obsidian_service` 的嵌入链接提取 / 章节安全记录 / 知识内容头部、`context_builder` 的 Obsidian 设定笔记和检查清单渲染、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/models.py backend/novel_backend/services/obsidian_service.py backend/novel_backend/services/context_builder.py backend/tests/test_obsidian_service.py backend/tests/test_context_builder.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_context_builder.py -k "safe_obsidian_embed_previews" -q` 通过，1 passed, 20 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "attachment_embeds" -q` 通过，1 passed, 61 deselected；`PYTHONPATH=backend pytest backend/tests/test_context_builder.py -q` 通过，21 passed；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，62 passed；`git diff --check` 通过；`npm run verify` 通过，363 个后端 unittest 通过，前端生产构建通过。

### Obsidian 关系字段小节引用进入章节安全上下文

- 修改摘要：Obsidian frontmatter 和正文内联关系字段里的 `#小节` 或 `^block` 现在会进入“关系小节”上下文，知识检索和章节安全内容能命中作者维护的具体段落；Vault 内部 links、resolved links、backlinks 和 graph_relations 仍按笔记文件记录，不把小节当作独立笔记。目标章节不可见的关系小节会随未来笔记隐藏，早期章节不会通过关系字段小节名提前看到后段设定。
- 影响范围：`obsidian_service` 的 frontmatter / 正文内联关系字段上下文生成、Obsidian 来源知识索引、章节安全内容、关系字段回归测试、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 Vault 图谱目标、反向链接统计、`knowledge.db` 表结构或 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "frontmatter_relationship_subpaths" -q` 通过，1 passed, 61 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，62 passed；`git diff --check` 通过；`npm run verify` 通过，362 个后端 unittest 通过，前端生产构建通过。

### Obsidian Canvas file subpath 进入章节安全上下文

- 修改摘要：Obsidian 同步 Canvas 时，会读取 file 节点的 `subpath` 或文件路径里的 `#小节`，在 Canvas 正文、知识检索和章节安全上下文里保留作者指向的笔记小节；内部 links、resolved links 和 backlinks 仍按 Vault 笔记文件记录，不把小节当成独立笔记。章节化知识检索和证据检索会在替换成安全内容后要求查询词有足够有效匹配，避免只命中未来 subpath 或弱相关短词时返回早期章节不可见的 Obsidian 命中。
- 影响范围：`obsidian_service` 的 Canvas file 节点正文生成、Canvas file 节点章节安全内容、`project_service` 的章节化 Obsidian 知识检索 / 证据检索过滤、Obsidian 来源知识索引、Canvas 回归测试、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 Vault 内部图谱目标、反向链接统计、`knowledge.db` 表结构或 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/novel_backend/services/project_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "canvas_file_node_subpaths or canvas_relative_file_nodes or canvas_file_nodes_enter_graph or canvas_link_nodes" -q` 通过，4 passed, 57 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，61 passed；`PYTHONPATH=backend pytest backend/tests/test_project_service.py -q` 通过，57 passed；`git diff --check` 通过；`npm run verify` 通过，361 个后端 unittest 通过，前端生产构建通过。

### Obsidian Canvas link 节点进入检索和章节上下文

- 修改摘要：Obsidian 同步 Canvas 时，会读取 Canvas link 节点的 URL 和标签，把外部考据入口写入 Canvas 正文、知识检索和章节安全上下文。外部 URL 不会写入 Vault 内部 links / backlinks，也不会生成未解析链接维护建议；link 标签或边关系里提到目标章节不可见的未来笔记名时，章节安全内容仍会隐藏。
- 影响范围：`obsidian_service` 的 Canvas 同步、Canvas link 节点正文生成、Obsidian 来源知识索引、章节化知识检索、章节安全内容、Canvas 回归测试、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 Vault 内部链接图谱、反向链接统计、`knowledge.db` 表结构或 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "canvas_link_nodes" -q` 通过，1 passed, 59 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，60 passed；`git diff --check` 通过；`npm run verify` 通过，360 个后端 unittest 通过，前端生产构建通过。

### Obsidian Canvas 分组进入图谱和章节上下文

- 修改摘要：Obsidian 同步 Canvas 时，会按画布坐标识别 Canvas group 分组节点内部的 file 节点，把分组标题和分组内 file 节点关系写入 Canvas 正文、图谱关系、知识检索和章节安全上下文。目标章节不可见的分组目标或分组标题里的未来笔记名会继续被隐藏，早期章节不会通过关系图分组提前看到后段设定。
- 影响范围：`obsidian_service` 的 Canvas 同步、Canvas group 分组关系、Obsidian 来源知识索引、章节化知识检索、章节安全内容、Canvas 回归测试、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略、`knowledge.db` 表结构或 Canvas 边关系解析规则。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "canvas_group_nodes" -q` 通过，1 passed, 58 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，59 passed；`git diff --check` 通过；`npm run verify` 通过，359 个后端 unittest 通过，前端生产构建通过。

### Obsidian Canvas 文本标题进入笔记标题

- 修改摘要：Obsidian 同步 Canvas 时，会读取文本节点里的 `title / 标题 / name / 名称` 作为 Canvas 笔记标题；没有这些字段时仍使用文件名。这个标题会进入同步摘要、`knowledge.db` 的 Obsidian 知识内容、关键词检索、章节安全内容和章节上下文，让作者在关系图、时间线或章节板里维护展示标题，不必把 Canvas 文件名改成最终展示名。
- 影响范围：`obsidian_service` 的 Canvas 同步、Obsidian 来源知识索引、章节化知识检索、章节安全内容、Canvas 回归测试、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略、`knowledge.db` 表结构或 Canvas file 节点关系解析规则。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "canvas_inline_title" -q` 通过，1 passed, 57 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，58 passed；`git diff --check` 通过；`npm run verify` 通过，358 个后端 unittest 通过，前端生产构建通过。

### Obsidian Canvas 关系在章节上下文显示笔记标题

- 修改摘要：章节上下文展示 Obsidian 图谱关系时，如果 Canvas file 节点关系目标或来源节点能解析到当前章节可见笔记，会显示笔记标题，不再把 `Plans/plan-002.md` 这类原始路径直接放进写作提示。全书同步摘要和 `knowledge.db` 仍保留原始关系路径，方便图谱解析和反向链接继续使用。
- 影响范围：章节上下文 Obsidian 关系展示、Canvas file 节点关系提示、上下文构建回归测试、README、项目 Agent 指令、核心引擎说明、记忆系统与蒸馏接入说明、技能流程回归清单和测试反馈清单；不改变 Vault 同步格式、`knowledge.db` 表结构或章节安全过滤规则。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/context_builder.py backend/tests/test_context_builder.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_context_builder.py -k "renders_canvas_relations_with_note_titles" -q` 通过，1 passed, 19 deselected；`PYTHONPATH=backend pytest backend/tests/test_context_builder.py -q` 通过，20 passed；`git diff --check` 通过；`npm run verify` 通过，357 个后端 unittest 通过，前端生产构建通过。

### 项目迁移包移除外部 Obsidian 索引、同步摘要、维护草稿、蒸馏摘要和执行资料分析

- 修改摘要：导出项目迁移包时，如果 Obsidian Vault 位于项目目录外，打包用的 `knowledge.db` 副本会移除 `Obsidian` 来源的索引行、FTS 行和向量，并清空索引签名；包内 `.gaoxia/obsidian_sync.json` 会写成空笔记状态，只保留配置、空统计和重新同步提示，不携带外部笔记列表、摘要或预览；包内 `.gaoxia/learning/narrative_state.json` 会清空 `obsidian_maintenance_suggestions / obsidian_maintenance_actions / obsidian_maintenance_summary`，`.gaoxia/obsidian_drafts/` 维护草稿不会进入迁移包；包内 `project_distillation.json` 会移除 `Obsidian:` 蒸馏条目并标记为需要重建；包内 Agent 线程和 `.gaoxia/runs/` workflow 状态会保留对话壳、执行状态和非敏感字段，但 Obsidian 资料分析 artifact、维护 artifact、相关 trace / event 摘要以及 action / subtask 摘要会改成迁移提示，`.gaoxia/thread_context/` 索引不会进入迁移包。真实项目目录里的 `knowledge.db`、同步文件、维护队列、草稿、蒸馏报告、Agent 线程和 workflow run 不会被改动。项目目录内的 Obsidian Vault 会随项目迁移并保留索引、同步摘要、维护草稿、蒸馏报告、线程记录和 workflow 状态。迁移包仍保留项目内 `.gaoxia/obsidian.json` 和章节学习状态，导入后按当前环境重新建索引。
- 影响范围：项目迁移导出、迁移包内 `knowledge.db`、迁移包内 `.gaoxia/obsidian_sync.json`、迁移包内 `.gaoxia/learning/narrative_state.json`、迁移包内 `.gaoxia/obsidian_drafts/`、迁移包内 `project_distillation.json`、迁移包内 `.gaoxia/threads/`、迁移包内 `.gaoxia/thread_context/`、迁移包内 `.gaoxia/runs/`、外部 Obsidian Vault 隐私边界、迁移回归测试、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、技能流程回归清单和测试反馈清单；不改变项目内 Vault 或项目内 Obsidian 草稿的打包规则。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_service.py backend/tests/test_project_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_project_service.py -k "migration_package_scrubs_external_obsidian_index_but_keeps_project_state or migration_package_keeps_project_internal_obsidian_vault_index" -q` 通过，2 passed, 56 deselected；`PYTHONPATH=backend pytest backend/tests/test_project_service.py -k "migration_package or migration" -q` 通过，5 passed, 53 deselected；`git diff --check` 通过；`npm run verify` 通过，366 个后端 unittest 通过，前端生产构建通过。

### 自学习动作响应同步最新状态

- 修改摘要：自学习候选状态更新、草案状态更新、草案应用、技能维护、写作回归、模型审查、排程设置和排程执行接口会在 `meta.self_evolution` 返回最新自学习状态；前端优先使用响应里的状态更新候选、草案、趋势、失败案例、Obsidian 维护摘要和章节任务卡，响应缺少状态时才重新读取自学习状态。
- 影响范围：自学习项目 API 响应、前端 API 解包、技能库 `Agent 自学习` 面板的候选 / 草案 / 回归 / 模型审查 / 排程动作状态同步、README、项目 Agent 指令、技能流程回归清单和界面回归说明；不改变 Vault 写入规则或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/api/projects.py backend/tests/test_self_evolution_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_self_evolution_service.py -k "self_evolution_project_api_reads_updates_and_curates" -q` 通过，1 passed, 13 deselected；`node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` 通过；`git diff --check` 通过；`npm run verify` 通过，354 个后端 unittest 通过，前端生产构建通过；`npm run verify:ui` 未能启动，当前沙箱拒绝监听 `127.0.0.1`，报错为 `listen EPERM: operation not permitted 127.0.0.1`。

### Obsidian 配置、同步和维护动作同步作品详情

- 修改摘要：自学习面板保存 Obsidian 配置或手动同步 Vault 后，接口会随作品详情在 `meta.self_evolution` 返回最新自学习状态；新增 Vault 笔记触发的图谱风险、维护摘要和章节任务卡会立即更新。保存草稿、批量保存、发布到 Vault、批量发布、确认 Vault 合并、批量确认、忽略和恢复 Obsidian 维护建议后，维护接口也会返回最新自学习状态；前端优先用响应里的状态更新维护摘要和章节任务卡，并重新读取作品详情；发布和确认合并仍会刷新 Obsidian 同步状态。维护动作已成功但自学习状态或作品详情刷新失败时，界面会保留成功提示并附带失败原因。
- 影响范围：Obsidian 配置保存接口响应、Obsidian 同步接口响应、Obsidian 维护接口响应、前端 API 解包、技能库 `Agent 自学习` 面板的 Obsidian 配置保存、同步和维护动作状态同步、父级作品详情刷新、README、项目 Agent 指令、技能流程回归清单和界面回归说明；不改变 Vault 写入规则或 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/api/projects.py backend/tests/test_project_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_project_service.py -k "obsidian_config_response_includes_self_evolution_state or obsidian_sync_response_includes_self_evolution_state or project_action_response_includes_self_evolution_state or chapter_mutation_response_includes_self_evolution_state" -q` 通过，4 passed, 51 deselected；`node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` 通过；`git diff --check` 通过；`npm run verify` 通过，354 个后端 unittest 通过，前端生产构建通过；`npm run verify:ui` 未能启动，当前沙箱拒绝监听 `127.0.0.1`，报错为 `listen EPERM: operation not permitted 127.0.0.1`。

### 章节保存响应同步自学习状态

- 修改摘要：章节保存和章节核验刷新响应现在会在 `meta.self_evolution` 返回最新自学习状态；技能库保存生成章或改稿章后会直接更新自学习面板里的章节任务卡和 Obsidian 维护摘要。技能库写回章节时也会把当前 XP 预设作为 `xp_preset` 传给后端，让系统学习版 XP 记录使用作者实际选择。
- 影响范围：章节保存接口响应、前端 API 解包、技能库生成章 / 改稿章保存流程、自学习面板状态同步、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明和技能流程回归清单；不改变 `knowledge.db` 表结构，不改变 Vault 发布策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/api/projects.py backend/tests/test_project_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_project_service.py -k "chapter_mutation_response_includes_self_evolution_state" -q` 通过，1 passed, 51 deselected；`npm run verify` 通过，351 个后端 unittest 通过，前端生产构建通过；`git diff --check` 通过。

### Agent 资料分析读取目标章节上下文

- 修改摘要：`review_knowledge` 在继承后续章节范围时，现在会调用 `build_project_context_bundle()` 读取同一目标章节的章节任务卡、章节合同、Obsidian 待审软约束和项目学习版文风 / XP，再放入资料分析模型提示和无资料时的返回文本；多章节执行中，后续章节动作仍会按各自章节重新生成资料摘要并缓存给同章生成、改稿和复查使用。
- 影响范围：`agent_service` 的资料分析上下文装配、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明和技能流程回归清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/agent_service.py backend/tests/test_agent_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_agent_service.py -k "knowledge_review" -q` 通过，6 passed, 34 deselected；`PYTHONPATH=backend pytest backend/tests/test_agent_service.py -q` 通过，40 passed；`npm run verify` 通过，350 个后端 unittest 通过，前端生产构建通过；`git diff --check` 通过。

### Brainstorm 复用章节级 Obsidian 上下文

- 修改摘要：`brainstorm` 现在支持显式 `chapter_id`，并在目标章节存在时直接复用 `build_project_context_bundle()` 的完整章节安全上下文，不再只靠手工拼接的摘要块；目标章节可见的 `Obsidian 待审软约束` 会进入讨论提示，项目学习版文风 / XP 规则也会进入 `brainstorm` 的 prompt support。Agent 讨论动作和技能库讨论面板都会把当前章节透传到后端。
- 影响范围：`studio_service` 的讨论提示装配、`agent_service` 的讨论请求章节透传、`project_style_xp_evolution_service` 的 `brainstorm` 文风 / XP 支持、讨论面板请求参数、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明和技能流程回归清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/models.py backend/novel_backend/services/studio_service.py backend/novel_backend/services/project_style_xp_evolution_service.py backend/novel_backend/services/agent_service.py backend/tests/test_studio_service.py backend/tests/test_agent_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_studio_service.py -k "brainstorm" -q` 通过，3 passed, 14 deselected；`PYTHONPATH=backend pytest backend/tests/test_agent_service.py -k "brainstorm_request_resolves_target_chapter_from_user_message" -q` 通过，1 passed, 38 deselected。

### Obsidian 待审软约束进入正文和规划上下文

- 修改摘要：目标章节可见的 `create_chapter_note`、`create_chapter_contract_note`、`create_style_rule_note` 和 `create_xp_rule_note` 待审草稿现在会进入单独的 `Obsidian 待审软约束` 区，给正文生成上下文和 Agent 能力上下文提供更短的结构化补充提示；章节档案草稿的摘要、交接和未完成必写项会更直接地进入后续章节承接；这组提示仍明确标记为非正式、低优先级资料，优先级低于作者明确要求和正式 Vault 设定。
- 影响范围：`project_narrative_state_service` 的章节上下文提示、`self_evolution_service` 的 Agent 能力上下文、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明和技能流程回归清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/novel_backend/services/self_evolution_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_project_narrative_state_service.py -k "saved_chapter_generates_obsidian_chapter_note_draft_visible_to_later_chapters or pending_style_xp_draft_preview_enters_agent_context or model_chapter_contract_becomes_obsidian_plan_draft" -q` 通过，3 passed, 54 deselected；`PYTHONPATH=backend pytest backend/tests/test_self_evolution_service.py -k "capability_context" -q` 通过，6 passed, 8 deselected；`PYTHONPATH=backend pytest backend/tests/test_project_narrative_state_service.py -q` 通过，57 passed；`npm run verify` 通过，347 个后端测试通过，前端构建通过；`git diff --check` 通过。

### Obsidian 待审草稿复用完整 YAML 解析

- 修改摘要：项目内 `.gaoxia/obsidian_drafts/` 的待审草稿 frontmatter 现在复用正式 Obsidian Vault 笔记同一套 YAML 解析。作者手工把章节合同、文风规则或其它维护草稿改成 `required_beats: [{goal: ...}]`、`- {action: ...}`、`objective: >`、多行 `tags:` 或带行尾注释的 YAML 时，章节范围过滤、合同短预览和 Agent 能力上下文仍会读取真实结构化字段。
- 影响范围：`project_narrative_state_service` 的待审草稿 frontmatter 读取、章节范围过滤、合同 / 文风短预览、Agent 能力上下文、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明和技能流程回归清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_project_narrative_state_service.py -k "pending_style_xp_draft_preview_enters_agent_context or model_chapter_contract_becomes_obsidian_plan_draft or obsidian_maintenance_source_chapters_open_after_latest_source" -q` 通过，3 passed, 54 deselected；`PYTHONPATH=backend pytest backend/tests/test_project_narrative_state_service.py -q` 通过，57 passed；`npm run verify` 通过，347 个后端测试通过，前端构建通过。

## 2026-06-01

### Obsidian 列表项 flow mapping

- 修改摘要：Obsidian frontmatter 的 YAML 对象列表现在支持列表项直接写 flow mapping。章节合同、场景卡或剧情债务把 `scenes` 的某项写成 `- {goal: ..., evidence_sources: [{source_note: ...}], payoff: ...}` 时，同步会把该项作为结构化对象读取，字段、嵌套证据来源、链接和图谱关系都会进入章节上下文。
- 影响范围：`obsidian_service` 的 frontmatter 对象列表解析、Obsidian 来源知识索引、章节上下文资料来源、Agent 资料分析、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明和技能流程回归清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`npm run verify` 通过，347 个后端测试通过，前端构建通过；其中包含 Obsidian 对象列表回归用例。

### Obsidian YAML flow mapping 对象列表

- 修改摘要：Obsidian frontmatter 的 YAML 对象列表现在支持 flow mapping 写法。章节合同、场景卡或剧情债务把 `required_beats` 写成 `[{goal: ..., evidence_sources: [{source_note: ...}]}]` 时，同步会把紧凑对象解析成结构化字段，嵌套证据来源也会进入章节上下文、链接和图谱关系。
- 影响范围：`obsidian_service` 的 frontmatter flow sequence / flow mapping 解析、Obsidian 来源知识索引、章节上下文资料来源、Agent 资料分析、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "frontmatter_object_lists" -q` 通过，1 passed, 56 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，57 passed；`npm run verify` 通过，347 个后端测试通过，前端构建通过。

### Obsidian 单独列表标记对象项

- 修改摘要：Obsidian frontmatter 的 YAML 对象列表现在支持单独 `-` 后换行维护对象字段。章节合同、场景卡或剧情债务把 `scenes` 写成 `-` 后下一行再写 `goal / conflict / evidence_sources` 时，同步会把这些字段作为同一个对象读取；嵌套 `evidence_sources` 里单独 `-` 后换行写 `source_note / reason` 也会进入章节上下文、链接和图谱关系。
- 影响范围：`obsidian_service` 的 frontmatter 对象列表解析、Obsidian 来源知识索引、章节上下文资料来源、Agent 资料分析、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "frontmatter_object_lists" -q` 通过，1 passed, 56 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，57 passed；`npm run verify` 通过，347 个后端测试通过，前端构建通过。

### Obsidian 对象列表内多行文本

- 修改摘要：Obsidian frontmatter 的 YAML 对象列表现在支持对象字段内的 YAML block scalar。章节合同、场景卡或剧情债务把 `scenes` 里的 `goal: >`、`reason: |` 写成多行场景目标、理由或验收说明时，同步会读取真实正文并转成章节上下文可读内容，不再把字段值误当成 `>` 或 `|`。
- 影响范围：`obsidian_service` 的 frontmatter 对象列表解析、Obsidian 来源知识索引、章节上下文资料来源、Agent 资料分析、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "frontmatter_object_lists" -q` 通过，1 passed, 56 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，57 passed；`npm run verify` 通过，347 个后端测试通过，前端构建通过。

### Obsidian 嵌套对象列表递归解析

- 修改摘要：Obsidian frontmatter 的 YAML 对象列表支持继续嵌套对象列表。章节合同或场景卡在 `scenes` 的单个场景项里继续维护 `character_checks / evidence_sources` 等对象列表时，同步会递归保留字段和值，转成章节上下文可读内容；嵌套对象里的 `source_note / evidence_sources` 双链和 Markdown 内链会进入图谱关系、链接和反向链接统计，并继续按目标章节隐藏未来笔记。
- 影响范围：`obsidian_service` 的 frontmatter 嵌套列表解析、递归图谱关系提取、Obsidian 来源知识索引、章节上下文资料来源、Agent 资料分析、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "frontmatter_object_lists" -q` 通过，1 passed, 56 deselected；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，57 passed；`npm run verify` 通过，347 个后端测试通过，前端构建通过。

### Obsidian YAML 对象列表进入章节上下文

- 修改摘要：Obsidian frontmatter 现在能解析 `scenes / required_beats / character_checks / debts_to_advance` 这类 YAML 对象列表。章节计划、章节合同、剧情债务和人物弧线笔记把每项写成 `goal / conflict / payoff / evidence_sources` 等多字段对象时，同步会保留字段名和值，把它们转成章节上下文可读的结构化行；对象里的双链和 Markdown 内链会继续进入链接与反向链接统计，并按目标章节隐藏未来笔记。
- 影响范围：`obsidian_service` 的 frontmatter 解析、结构化 Properties 正文生成、Obsidian 来源知识索引、章节上下文资料来源、Agent 资料分析、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "frontmatter_object_lists" -q` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，57 个用例；`npm run verify` 通过，包含 347 个后端 unittest 和前端生产构建。

### Obsidian Tasks 状态任务项解析

- 修改摘要：Obsidian 同步会把可见 callout 或正文任务列表里的 `[!] / [?] / [>] / [/] / [-]` 等常见 Obsidian Tasks 状态当作任务标记处理；这些任务项里的 `status::`、`source_notes::`、`related_characters::`、`required_phrases::`、`forbidden_phrases::`、`chapter_range::` 以及“必须包含 / 禁止出现”小节内容会继续进入元数据、图谱关系、章节约束和章节安全内容。
- 影响范围：`obsidian_service` 的正文任务标记清理、可见 callout 任务列表、Obsidian 来源知识索引、章节上下文资料来源、Agent 资料分析、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "visible_callout_tasks" -q` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，56 个用例；`npm run verify` 通过，包含 346 个后端 unittest 和前端生产构建。

### Obsidian max_notes 稳定候选顺序

- 修改摘要：Obsidian 同步会先收集所有符合 `include_patterns / exclude_patterns` 的候选笔记，按 Vault 相对路径稳定排序后再应用 `max_notes` 数量上限；超过上限的候选会计入跳过数量，并在同步警告里提示作者收窄路径过滤或提高 `max_notes`。候选总数和 `max_notes` 会进入来源签名，排在上限后的候选增删也会刷新同步摘要里的 skipped 和警告。
- 影响范围：`obsidian_service` 的 Vault 文件候选筛选、同步摘要、来源签名、Obsidian 来源知识索引、章节上下文资料来源、Agent 资料分析、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "max_notes" -q` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，56 个用例；`npm run verify` 通过，包含 346 个后端 unittest 和前端生产构建。

### Obsidian 布尔状态 Properties 过滤

- 修改摘要：Obsidian 同步会在缺少显式 `status / 状态` 字段时读取布尔状态 Properties。`canonical: true`、`published: yes`、正文或 Canvas 文本节点 `canonical:: true` 会按正式可用状态参与 `allowed_statuses` 过滤；`draft: true`、`private: true`、`archived: true`、正文或 Canvas 文本节点 `draft:: true` 会按过滤状态处理。显式 `status` 字段优先，不会被布尔属性、标签或目录覆盖。
- 影响范围：`obsidian_service` 的 Markdown / Canvas 笔记同步、状态过滤、Obsidian 来源知识索引、章节上下文资料来源、Agent 资料分析、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "status_boolean_properties" -q` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，55 个用例；`npm run verify` 通过，包含 345 个后端 unittest 和前端生产构建。

### Obsidian 路径过滤大小写兼容

- 修改摘要：Obsidian 同步的 `include_patterns / exclude_patterns` 改为大小写不敏感匹配。默认 `.obsidian/**`、`.trash/**` 和 `templates/**` 会同时排除 `.OBSIDIAN/`、`.Trash/`、`Templates/` 等常见 Vault 目录写法；作者自定义 `drafts/**` 这类规则时也能排除 `Drafts/`，避免模板、插件状态和草稿目录进入知识索引、章节上下文或连续性证据包。
- 影响范围：`obsidian_service` 的 Vault 文件候选筛选、Obsidian 来源知识索引、章节上下文资料来源、Agent 资料分析、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "exclude_patterns_match_common_vault_folder_casing" -q` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，54 个用例；`npm run verify` 通过，包含 344 个后端 unittest 和前端生产构建。

### Obsidian 状态别名、标签与目录过滤

- 修改摘要：Obsidian 同步会把显式 `status / 状态` 字段先按常见别名归一，再参与状态过滤。`status: 正式设定 / official / final`、`#canonical / #正式 / #已发布` 或 `正式设定/`、`Published/` 等按正式可用状态参与 `allowed_statuses` 过滤；`status: wip / archived`、`#draft / #草稿 / #private / #私密 / #废案` 或 `Drafts/`、`草稿/`、`Private/` 等按过滤状态处理。显式 `status` 字段优先，不会被标签或目录覆盖。Markdown frontmatter 标签、正文标签、Canvas 文本节点标签和 Vault 目录使用同一状态过滤规则。
- 影响范围：`obsidian_service` 的 Markdown / Canvas 笔记同步、状态过滤、Obsidian 来源知识索引、章节上下文资料来源、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -k "status_tags_fill_missing_status or explicit_status_values" -q` 通过；`PYTHONPATH=backend pytest backend/tests/test_obsidian_service.py -q` 通过，53 个用例；`npm run verify` 通过，包含 343 个后端 unittest 和前端生产构建；`git diff --check` 通过；未跟踪文件空白检查通过；相对日期表述检查无新增命中。

### Obsidian AI 可见性标签过滤

- 修改摘要：Obsidian AI 可见性判断继续覆盖标签写法。`tags: [AI可用]`、正文 `#AI可用` 会在启用 `require_usable_by_ai` 时视为明确可用；`tags: [no-ai]`、`#no-ai` 或 `#AI不可用` 会排除笔记，并且反向标签优先于正向 Properties，避免作者用标签标记“不要给 AI”后仍被知识索引和章节上下文引用。
- 影响范围：`obsidian_service` 的 Markdown / Canvas 笔记同步、`require_usable_by_ai` 过滤、Obsidian 来源知识索引、章节上下文资料来源、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_ai_visibility_accepts_aliases_and_no_ai_flags -v` 通过；`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，51 个用例；`npm run verify` 通过，包含 341 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查无新增命中。

### Obsidian AI 可见性正反向属性

- 修改摘要：Obsidian 同步的 AI 可见性判断支持正向和反向 Properties。`usable_by_ai / ai_usable / AI可用 / 可供AI使用 / 可供模型使用 / 写作可用` 为真时视为明确可用；`no_ai / not_for_ai / exclude_from_ai / AI不可用 / 不供AI使用 / 不允许AI使用 / 勿用AI` 为真时排除笔记；`no_ai: false` 或 `AI不可用: 否` 会被视为明确可用。Markdown frontmatter、正文内联属性和 Canvas 文本节点属性使用同一规则。
- 影响范围：`obsidian_service` 的 Markdown / Canvas 笔记同步、`require_usable_by_ai` 过滤、Obsidian 来源知识索引、章节上下文资料来源、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_ai_visibility_accepts_aliases_and_no_ai_flags -v` 通过；`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，51 个用例；`npm run verify` 通过，包含 341 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查无新增命中。

### Obsidian 显式 type 多选属性识别

- 修改摘要：Obsidian Markdown 笔记的 `type / kind / 类型` 支持多选 Properties。`type: [主角, 人物]`、`type: [临时, 章节计划]` 会扫描整个列表并识别系统已知类型；`type: [自定义分类]` 这类完全未知的显式 type 会保留作者写法，并且不会被 `Characters/` 等目录覆盖。
- 影响范围：`obsidian_service` 的笔记类型整理、同步摘要、知识索引内容、章节计划类 Obsidian 笔记预览、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_scans_explicit_type_multiselect_before_folder_fallback backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_infers_note_type_from_nested_tags_without_title_guessing backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_infers_note_type_from_common_folders_when_type_is_missing -v` 通过；`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，50 个用例；`npm run verify` 通过，包含 340 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查无新增命中。

### Obsidian 层级标签推断笔记类型

- 修改摘要：Obsidian Markdown 笔记没有显式 `type / kind / 类型` 时，层级标签会按 `/` 分段参与类型推断；`#人物/主角`、`#章节计划/58`、`#剧情债务/伏笔` 可识别为人物、章节计划和剧情债务，`#非人物/主题` 不会被误判成人物，仍不从文件名或标题猜类型。
- 影响范围：`obsidian_service` 的标签类型整理、同步摘要、知识索引内容、章节计划和剧情债务类 Obsidian 笔记预览、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_infers_note_type_from_nested_tags_without_title_guessing backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_infers_note_type_from_common_folders_when_type_is_missing -v` 通过；`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，49 个用例；`npm run verify` 通过，包含 339 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查无新增命中。

### Obsidian 常见目录推断笔记类型

- 修改摘要：Obsidian Markdown 笔记没有显式 `type / kind / 类型` 时，会按常见目录或标签推断类型；`Characters/`、`Locations/`、`Plans/`、`Debts/`、`CharacterArcs/`、`Style/`、`XP/` 等会分别显示为人物、地点、章节计划、剧情债务、人物弧线、文风规则和 XP 规则，显式 type 不会被目录覆盖。
- 影响范围：`obsidian_service` 的笔记类型整理、同步摘要、知识索引内容、章节计划 / 剧情债务 / 人物弧线 / 文风 / XP 类 Obsidian 笔记预览、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_infers_note_type_from_common_folders_when_type_is_missing -v` 通过；`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，48 个用例；`npm run verify` 通过，包含 338 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查无新增命中。

### Obsidian 可见 callout 任务列表进入上下文

- 修改摘要：Obsidian 同步会解析普通 `note / info` callout 里的任务列表字段，例如 `> - [ ] status:: canonical`、`source_notes:: [[当前线索]]`、`related_characters:: [[林追]]`、`required_phrases:: 潮声异常`，并把 `> ## 必须包含`、`> ## 禁止出现` 下的任务项转成必写 / 禁写约束；指向未来笔记的双链和关系仍按章节安全内容隐藏。
- 影响范围：`obsidian_service` 的正文标记清理、正文内联属性解析、关系字段解析、必写 / 禁写约束解析、章节安全内容、Obsidian 知识索引、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_visible_callout_tasks_drive_inline_metadata_and_constraints -v` 通过；`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，47 个用例；`npm run verify` 通过，包含 337 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查无新增命中。

### Obsidian Markdown 表格进入章节上下文

- 修改摘要：Obsidian 同步会解析 Markdown 表格列名，把章节合同、章节计划、剧情债务和人物弧线笔记中的 `章节目标 / 必须节拍 / 禁写动作 / 验收项 / 证据来源 / 相关人物` 等列转成现有上下文行；表格里的双链和 Markdown 内链会进入图谱关系、可解析链接和反向链接，目标是未来笔记时仍按章节安全内容隐藏标题、路径和关系目标。
- 影响范围：`obsidian_service` 的 AI 可见正文增强、Markdown 表格解析、章节合同 / 章节计划类 Obsidian 笔记、图谱关系、章节上下文、知识检索预览、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_markdown_tables_feed_chapter_contract_context_and_graph -v` 通过；`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，46 个用例；`npm run verify` 通过，包含 336 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查无新增命中。

### Obsidian HTML 链接、脚注隔离和附件过滤

- 修改摘要：Obsidian 同步的 AI 可见正文会把 HTML `<a href="...">` 链接按 Markdown 内链处理；目标是 Markdown 或 Canvas 笔记时进入图谱关系、可解析链接和反向链接，目标是未来笔记时按章节安全内容隐藏标签和路径，目标是本地附件时按附件过滤。Markdown 脚注定义、缩进续行和正文脚注标记会从 AI 可见正文中排除，脚注里的双链、标签或约束不会进入图谱关系、未解析链接、检索预览和章节上下文。指向本地非笔记附件的普通 Markdown 链接、引用式链接和 HTML 媒体标签仍会从图谱关系、未解析链接、检索预览和章节上下文中排除。
- 影响范围：`obsidian_service` 的 AI 可见正文清理、HTML `<a href>` 链接、Markdown 直接链接、引用式链接、Markdown 脚注和 HTML 媒体标签处理、Obsidian 知识索引、章节上下文、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_markdown_shortcut_reference_links_resolve_and_stay_chapter_safe -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_html_anchor_links_resolve_and_stay_chapter_safe backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_ignores_comments_and_code_blocks_for_ai_context_and_graph -v` 通过；`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，45 个用例；`npm run verify` 通过，包含 335 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查无新增命中。

### Obsidian 隔离 Markdown HTML 注释

- 修改摘要：Obsidian 同步的 AI 可见正文会排除 Markdown HTML 注释 `<!-- ... -->`。作者把未来双链、关系字段、标签、必写项或剧透词放在 HTML 注释里时，这些内容不会进入图谱关系、反向链接、检索预览、章节上下文或写作约束。
- 影响范围：`obsidian_service` 的 AI 可见正文清理、正文内联属性、双链、标签、关系小节、必写 / 禁写约束、检索预览、章节上下文、相关后端单测、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统与蒸馏接入说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_ignores_comments_and_code_blocks_for_ai_context_and_graph -v` 通过；`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，44 个用例；`npm run verify` 通过，包含 334 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查无新增命中。

### Obsidian 正文内联关系保留嵌套链接

- 修改摘要：Obsidian / Dataview 正文内联属性会用成对括号解析关系字段，避免 `[source_notes:: [当前线索, 潮标](当前线索.md)]`、`(related_characters:: [林追, 主角](林追.md))` 里的 Markdown 内链被提前截断；`depends_on:: [[线索甲|账册, 初证]]` 这类未加引号的双链也会按双链字符串处理，不再被当作 YAML 数组误拆。
- 影响范围：`obsidian_service` 的正文内联属性解析、正文内联关系字段、Markdown 内链和双链关系字段、图谱关系、`resolved_links` / `backlinks`、相关后端单测、README、项目 Agent 指令、核心引擎说明、记忆系统与蒸馏接入说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_inline_properties_drive_metadata_graph_and_scope -v` 通过；`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，44 个用例；`npm run verify` 通过，包含 334 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查无新增命中。

### Obsidian 关系字段保留链接标签逗号

- 修改摘要：Obsidian frontmatter 和正文关系字段在拆分多值时，会识别 Markdown 内链、双链、引号和括号范围；`source_notes: "[线索乙, 潮账](../Clues/线索乙.md)"`、`related_characters: ["[林追, 主角](../Characters/林追.md)"]`、`depends_on: "[[线索甲|账册, 初证]]"` 这类写法不会被逗号拆成错误关系目标，仍会生成关系语义、可解析链接和反向链接。
- 影响范围：`obsidian_service` 的 frontmatter / 正文关系字段列表拆分、Markdown 内链和双链关系字段、图谱关系、`resolved_links` / `backlinks`、相关后端单测、README、项目 Agent 指令、核心引擎说明、记忆系统与蒸馏接入说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_extracts_frontmatter_relationship_links -v` 通过；`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，44 个用例；`npm run verify` 通过，包含 334 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查无新增命中。

### Agent 自学习维护摘要跟随筛选

- 修改摘要：Agent 自学习面板的 Obsidian 维护摘要在没有筛选时继续显示后端全局摘要；存在状态、来源章节或搜索筛选时，前端会按可见维护项重新统计待处理、高优先级、自动草稿和状态数量，并显示“当前筛选”。从 Agent 结果区 `obsidian_maintenance` 产物打开第 N 章维护队列后，摘要总数会跟列表显示数一致。
- 影响范围：`SkillLibraryPanel` 的 Obsidian 维护摘要展示、Agent 产物卡片跳转后的维护面板体验、UI smoke 断言、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统说明、界面回归说明、技能流程回归清单和测试反馈清单；不改变后端接口、`narrative_state.json` 存储结构、`knowledge.db` 表结构或 Vault 写入逻辑。
- 验证结果：`npm run build` 通过；`npm run verify` 通过，包含 334 个后端 unittest 和前端生产构建；`node --check scripts/verify-ui-smoke.mjs` 通过；`git diff --check` 通过；相对日期表述检查无新增命中。`npm run verify:ui` 未通过，失败点是沙箱禁止监听 `127.0.0.1`，报 `listen EPERM: operation not permitted 127.0.0.1`，因此本次没有实际跑完浏览器 smoke。

### Agent 维护摘要按目标章节重算

- 修改摘要：Agent 路由 / 规划上下文在有目标章节时，不再直接使用全局 Obsidian 维护摘要；系统会先按目标章节可见范围筛选维护项，再重新统计待处理、高优先级、自动草稿和状态数量。当前章节没有可见维护项但全书仍有维护压力时，规划上下文会显示当前章节统计为 0，而不是让后段章节维护项影响当前章。
- 影响范围：`self_evolution_service` 的 Agent 能力上下文、模型路由 / 规划可见的 Obsidian 维护摘要和维护建议、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `narrative_state.json` 存储结构，不改变 `knowledge.db` 表结构，不自动写入作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/self_evolution_service.py backend/tests/test_self_evolution_service.py backend/tests/test_agent_service.py` 通过；新增目标用例 `test_capability_context_scopes_obsidian_maintenance_summary_to_target_chapter` 通过；Agent 规划范围目标用例通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_self_evolution_service backend.tests.test_agent_service -v` 通过，52 个用例；`npm run verify` 通过，包含 334 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查无新增命中。

### Obsidian 文风 / XP 规则按目标章节优先

- 修改摘要：项目级 Obsidian 文风 / XP 提示现在会先收集全部目标章节可见规则，再按章节范围、剧透边界和来源章节计算相关性；当 Vault 中全局规则很多、超过提示容量时，目标章节专属文风和 XP 规则仍会优先进入提示，容量允许时两类规则各保留最相关条目。
- 影响范围：`project_style_xp_evolution_service` 的 Obsidian 文风 / XP 规则选择顺序、章节生成 / 改稿 / 诊断提示、Agent 路由 / 规划上下文复用的文风 / XP 参考、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动写入作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_style_xp_evolution_service.py backend/tests/test_project_style_xp_evolution_service.py` 通过；新增目标用例 `test_chapter_scoped_obsidian_style_xp_rules_outrank_crowded_global_rules` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_style_xp_evolution_service -v` 通过，4 个用例；章节提示和 Agent 规划相关目标用例通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_style_xp_evolution_service backend.tests.test_context_builder backend.tests.test_self_evolution_service -v` 通过，36 个用例；`npm run verify` 通过，包含 333 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查只命中 `docs/去AI技能说明.md:23` 的既有示例短语。

### Agent 规划读取 Obsidian 文风 / XP 规则

- 修改摘要：Agent 路由 / 规划上下文现在会读取目标章节可见的正式 Obsidian 文风 / XP 规则，并复用项目级文风 / XP 提示的 Properties 解析和章节边界过滤；没有目标章节时只展示无章节边界的全局规则，后段规则不会提前进入规划提示。
- 影响范围：`self_evolution_service` 的 Agent 能力上下文、`project_style_xp_evolution_service` 的 Obsidian 文风 / XP 参考公开构建入口、Agent 路由 / 规划模型可见资料、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动写入作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_style_xp_evolution_service.py backend/novel_backend/services/self_evolution_service.py backend/tests/test_project_style_xp_evolution_service.py backend/tests/test_self_evolution_service.py` 通过；新增目标用例 `test_capability_context_includes_obsidian_style_xp_rules` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_style_xp_evolution_service -v` 通过，3 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_self_evolution_service -v` 通过，13 个用例；`npm run verify` 通过，包含 332 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查只命中 `docs/去AI技能说明.md:23` 的既有示例短语。

### Obsidian 全局文风 / XP Properties 提示读取

- 修改摘要：没有明确目标章节的文风 / XP 提示现在也会读取 Obsidian 同步记录中的无章节边界全局规则，并从 Properties 生成结构化提示内容；带章节范围或剧透边界的后段规则仍不会进入全局任务提示。
- 影响范围：`project_style_xp_evolution_service` 的无目标章节 Obsidian 规则读取、全局文风 / XP 提示、只写 Properties 的正式 Vault 规则笔记、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动写入作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_style_xp_evolution_service.py backend/tests/test_project_style_xp_evolution_service.py` 通过；新增目标用例 `test_global_obsidian_style_xp_properties_enter_prompt_without_target_chapter` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_style_xp_evolution_service -v` 通过，3 个用例；`npm run verify` 通过，包含 331 个后端 unittest 和前端生产构建。

### Obsidian 文风 / XP Properties 提示读取增强

- 修改摘要：目标章节可见的正式 Obsidian `style_rule / xp_rule` 笔记如果只写 Properties，项目级文风 / XP 提示现在会读取同步后的结构化正文，稳定带入文风规则、句式节奏、意象、对白、禁用写法、示例、适用场景、XP 规则、生成前后检查、推进方法和禁用做法，不再只依赖摘要或短预览。
- 影响范围：`project_style_xp_evolution_service` 的 Obsidian 文风 / XP 参考整理、正式 Vault 规则笔记的目标章节提示、章节范围过滤、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动写入作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_style_xp_evolution_service.py backend/tests/test_project_style_xp_evolution_service.py` 通过；新增目标用例 `test_obsidian_style_xp_properties_enter_prompt_without_body` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_style_xp_evolution_service -v` 通过，2 个用例；文风 / XP 维护相关叙事状态目标用例 2 个通过；`npm run verify` 通过，包含 330 个后端 unittest 和前端生产构建。

### Obsidian 待审文风 / XP 规则预览

- 修改摘要：目标章节可见的 `Style/` 和 `XP/` 待审规则草稿现在会在章节上下文和 Agent 规划上下文里显示非正式“文风预览”或“XP预览”，摘取规则、适用范围、检查项、证据数和置信度。作者删除 frontmatter 但保留“文风规则 / XP规则 / 使用建议”等正文行时，预览仍能读取真实草稿内容。
- 影响范围：`project_narrative_state_service` 的待审草稿预览、`build_agent_capability_context` 复用的维护建议预览、系统学习版文风 / XP 到 Obsidian 待审草稿的过渡、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动发布到作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；新增目标用例 `test_pending_style_xp_draft_preview_enters_agent_context` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service -v` 通过，57 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_self_evolution_service -v` 通过，12 个用例；`npm run verify` 通过，包含 329 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查只命中 `docs/去AI技能说明.md:23` 的既有示例短语。

### Obsidian 待审合同进入 Agent 规划上下文

- 修改摘要：Agent 能力上下文展示 Obsidian 维护建议时，会复用待审草稿预览逻辑读取对应真实草稿；目标章节可见的 `create_chapter_contract_note` 草稿会把合同目标、必须节拍、禁写动作和验收项写进 Agent 规划上下文。作者把合同草稿改成只保留正文小节时，规划上下文仍能读到这些非正式合同预览；章节档案和章节合同以外的草稿不会误显示合同预览。
- 影响范围：`self_evolution_service` 的 Agent 能力上下文、`project_narrative_state_service` 的待审草稿预览复用、模型路由 / 规划可见的 Obsidian 维护建议、相关后端单测、项目 Agent 指令、Agent 执行架构说明和测试反馈清单；不改变 `knowledge.db` 表结构，不自动发布到作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/novel_backend/services/self_evolution_service.py backend/tests/test_project_narrative_state_service.py` 通过；目标用例 `test_model_chapter_contract_becomes_obsidian_plan_draft` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_self_evolution_service -v` 通过，12 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service -v` 通过，56 个用例；`npm run verify` 通过，包含 328 个后端 unittest 和前端生产构建。

### Obsidian 待审章节合同预览

- 修改摘要：目标章节可见的 `Plans/` 章节合同待审草稿现在会在 Obsidian 待审草稿提醒里显示非正式“合同预览”，摘取章节目标、必须节拍、禁写动作和验收项；作者删除 frontmatter 但保留合同正文小节时仍能读取。待审草稿提示渲染时会逐条读取对应真实草稿，并校验维护 ID / 类型，避免一条维护建议误用其它草稿正文。
- 影响范围：`project_narrative_state_service` 的待审草稿读取、章节合同草稿预览、章节生成上下文、Agent 规划上下文、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动发布到作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；目标用例 `test_model_chapter_contract_becomes_obsidian_plan_draft` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service -v` 通过，56 个用例；`npm run verify` 通过，包含 328 个后端 unittest 和前端生产构建。

### Obsidian 章节档案草稿正文预览

- 修改摘要：`ChapterNotes/` 待审章节档案草稿的短预览不再只依赖 frontmatter。作者手工整理草稿、删除属性块但保留“章节摘要 / 下一章交接 / 未完成的 Obsidian 必写项 / 章节正文摘录”正文小节时，章节生成上下文和 Agent 规划上下文仍会显示摘要、交接和未完成必写项预览；非章节档案草稿不会显示章节档案预览。
- 影响范围：`project_narrative_state_service` 的待审草稿提示、章节生成上下文、Agent 规划上下文、手工改动的 `ChapterNotes/` 待审草稿、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动发布到作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；目标用例 `test_saved_chapter_generates_obsidian_chapter_note_draft_visible_to_later_chapters` 和 `test_obsidian_maintenance_source_chapters_open_after_latest_source` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service -v` 通过，56 个用例；`npm run verify` 通过，包含 328 个后端 unittest 和前端生产构建。

### Obsidian 待审章节档案预览

- 修改摘要：章节生成上下文里的 Obsidian 待审草稿提醒，会对目标章节可见的 `ChapterNotes/` 自动章节档案草稿显示短预览，包含章节摘要、下一章交接和未完成 Obsidian 必写项。未发布到 Vault 前，后续章节也能承接上一章，但提示仍标明不能当作 Vault 正式设定引用；人物、剧情债务和图谱等其它草稿不会被误当作章节档案预览。
- 影响范围：`project_narrative_state_service` 的待审草稿提示、章节生成上下文、Agent 规划上下文、自动章节档案草稿、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动发布到作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；目标用例 `test_saved_chapter_generates_obsidian_chapter_note_draft_visible_to_later_chapters` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service -v` 通过，56 个用例；`npm run verify` 通过，包含 328 个后端 unittest 和前端生产构建。

### Obsidian 自动章节档案交接写入

- 修改摘要：系统自动生成 `ChapterNotes/` 章节档案草稿时，会把下一章交接写入 `handoff_to_next` 和正文“下一章交接”小节；发布到 Vault 后，后续章节可通过正式 Obsidian 章节档案读取这条承接提示。自动草稿里的“下一章关注本章后果”类提示不会触发自动修订，作者或系统写成“下一章必须 / 需要 / 追问 ……”的强制类交接才会进入 Obsidian 必需设定核验。
- 影响范围：`project_narrative_state_service` 的章节档案草稿生成、`chapter_review_service` 的交接核验行为回归、`ChapterNotes/` 待审草稿、发布后的 Obsidian 章节档案、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动发布到作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py backend/tests/test_project_service.py` 通过；目标用例 `test_saved_chapter_generates_obsidian_chapter_note_draft_visible_to_later_chapters`、`test_chapter_review_checks_obsidian_chapter_archive_handoff` 和 `test_chapter_review_ignores_soft_obsidian_chapter_archive_handoff` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service -v` 通过，56 个用例；章节核验相关 4 个用例通过；`npm run verify` 通过，包含 328 个后端 unittest 和前端生产构建。

### Obsidian 章节档案交接核验

- 修改摘要：章节档案带 `source_ids` 或 `source_chapters` 时，`第058章-银潮灯回顾.md` 这类单章文件名不再把档案限制成只在来源章可见，后续章节仍可检索和引用；章节核验会读取明确指向当前章的 `handoff_to_next`，缺少可核验关键词时作为 Obsidian 必需设定问题进入自动修订判定，写入关键词后关闭，后续章节不会重复提示同一条下一章交接。
- 影响范围：`obsidian_service` 的来源章节范围合并、`chapter_review_service` 的 Obsidian 设定核验、章节自动修订触发条件、`chapter_note / chapter_summary / chapter_archive / author_archive` 笔记、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动发布到作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/novel_backend/services/chapter_review_service.py backend/tests/test_obsidian_service.py backend/tests/test_project_service.py` 通过；新增目标用例 `test_obsidian_chapter_source_ids_override_single_chapter_filename_scope` 和 `test_chapter_review_checks_obsidian_chapter_archive_handoff` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，44 个用例；章节核验与自动修订相关 3 个用例通过；`npm run verify` 通过，包含 327 个后端 unittest 和前端生产构建。

### Obsidian 章节档案进入 Agent 规划上下文

- 修改摘要：Agent 能力上下文会读取目标章节可见的 Obsidian 章节档案，把章节摘要、状态变化和 `handoff_to_next` 交接提醒写进“目标章节 Obsidian 任务”。规划第 3 章时可以看到第 2 章档案的后续追问，规划第 1 章时仍看不到后段档案。
- 影响范围：`self_evolution_service` 的 Agent 能力上下文、模型路由 / 规划可见的目标章节 Obsidian 任务、`chapter_note / chapter_summary / chapter_archive / author_archive` 笔记、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动发布到作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/self_evolution_service.py backend/tests/test_self_evolution_service.py` 通过；新增目标用例 `test_capability_context_includes_obsidian_chapter_archive_handoff` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_self_evolution_service -v` 通过，12 个用例；Agent 规划范围相关 3 个用例通过；`npm run verify` 通过，包含 325 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查只命中 `docs/去AI技能说明.md:23` 的既有示例短语。

### Obsidian 章节档案承接提示

- 修改摘要：叙事状态账本会从目标章节可见的 Obsidian 章节档案中读取 `chapter_summary / chapter_events / state_changes / handoff_to_next / chapter_excerpt`，生成独立的“Obsidian 章节档案”提示。写第 59 章时可以直接看到第 58 章档案里的摘要、关键事件、状态变化和交接提醒；早期章节仍按来源章节和剧透边界过滤。
- 影响范围：`project_narrative_state_service` 的章节任务卡和账本提示、章节生成上下文里的叙事状态块、作者维护的 `chapter_note / chapter_summary / chapter_archive / author_archive` 笔记、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动发布到作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；新增目标用例 `test_narrative_state_prompt_uses_obsidian_chapter_archive_handoff` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service -v` 通过，56 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder -v` 通过，19 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，43 个用例；`npm run verify` 通过，包含 324 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查只命中 `docs/去AI技能说明.md:23` 的既有示例短语。

### Obsidian 章节档案 Properties

- 修改摘要：自动生成 `ChapterNotes/` 章节档案草稿时，会写入 `chapter_index / chapter_title / chapter_summary / chapter_excerpt` 和 Obsidian 必写 / 禁写执行状态；Obsidian 同步也会把 `chapter_note / chapter_summary / chapter_archive / author_archive` 笔记里的 `chapter_title / chapter_summary / chapter_events / state_changes / handoff_to_next / chapter_excerpt` 转成 AI 可见正文。作者只用 Properties 维护章节回顾时，后续章节也能通过知识索引和章节上下文读取摘要、关键事件、状态变化和交接提醒。
- 影响范围：`obsidian_service` 的章节档案 Properties 上下文正文生成、`project_narrative_state_service` 的章节档案草稿生成、章节档案发布后的知识索引、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动发布到作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/novel_backend/services/obsidian_service.py backend/tests/test_project_narrative_state_service.py backend/tests/test_obsidian_service.py` 通过；目标用例 `test_saved_chapter_generates_obsidian_chapter_note_draft_visible_to_later_chapters` 和 `test_obsidian_chapter_note_properties_feed_context_body` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，43 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service -v` 通过，55 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder -v` 通过，19 个用例；`npm run verify` 通过，包含 323 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查只命中 `docs/去AI技能说明.md:23` 的既有示例短语。

### Obsidian 债务与人物草稿结构化

- 修改摘要：系统生成剧情债务和人物状态 Obsidian 待审草稿时，会把债务内容、处理状态、风险等级、下一步动作，以及人物、阶段、当前状态、未解压力和后续检查项写入 Properties；人物状态草稿会带 `人物状态` 标签。作者发布草稿后，这些笔记可按正式 Vault 剧情债务或人物弧线来源进入目标章节提示。
- 影响范围：`project_narrative_state_service` 的剧情债务 / 人物状态维护草稿生成、Obsidian 维护建议发布链路、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动发布到作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；目标用例 `test_narrative_state_suggests_obsidian_notes_for_untracked_debts` 和 `test_character_maintenance_draft_uses_source_chapter_boundary` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service -v` 通过，55 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，42 个用例；`npm run verify` 通过，包含 322 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查只命中 `docs/去AI技能说明.md:23` 的既有示例短语。

### Obsidian 文风 / XP 维护草稿结构化

- 修改摘要：系统学习版文风 / XP 规则生成 `Style/` 或 `XP/` Obsidian 待审草稿时，会把规则内容写入 `style_rule` 或 `xp_rule` Properties；文风草稿还会写入 `applies_to / evidence_count / confidence`，XP 草稿会写入 `postcheck`。作者发布草稿后，规则仍能通过结构化 Properties 进入目标章节的文风 / XP 提示。
- 影响范围：`project_narrative_state_service` 的 Style/XP 维护草稿生成、Obsidian 维护建议发布链路、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动发布到作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；目标用例 `test_active_style_xp_rules_generate_obsidian_maintenance_suggestions` 和 `test_style_xp_maintenance_uses_latest_source_chapter_boundary` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service -v` 通过，55 个用例；文风 / XP 提示相关 3 个用例通过；`npm run verify` 通过，包含 322 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查只命中 `docs/去AI技能说明.md:23` 的既有示例短语。

### Obsidian 文风 / XP Properties 读取

- 修改摘要：Obsidian `style_rule / xp_rule` 笔记只写 `style_rule / voice_rule / tone_rule / sentence_rhythm / imagery / dialogue_rule / avoid_style / examples / applies_to`，或 `xp_rule / precheck / postcheck / workflow / technique / avoid_xp` 等 Properties 时，系统也会把这些字段转成 AI 可见正文和目标章节的项目级文风 / XP 提示；摘要存在时，结构化规则内容也会保留在提示里。
- 影响范围：`obsidian_service` 的文风 / XP Properties 上下文正文生成、`project_style_xp_evolution_service` 的 Obsidian 规则提示整理、章节安全的 prompt support、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动写入作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/novel_backend/services/project_style_xp_evolution_service.py backend/tests/test_context_builder.py` 通过；新增目标用例 `test_prompt_support_reads_properties_only_obsidian_style_xp_notes` 和相邻文风 / XP 提示用例通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder -v` 通过，19 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_style_xp_evolution_service -v` 通过，1 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，42 个用例；`npm run verify` 通过，包含 322 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查只命中 `docs/去AI技能说明.md:23` 的既有示例短语。

### Obsidian 债务与人物弧线 Properties 读取

- 修改摘要：Obsidian `narrative_debt / plot_debt` 笔记只写 `debt_content / debt_status / risk_level / expected_payoff_range / next_required_action / related_characters`，或 `character_arc / character_state` 笔记只写 `character / phase / current_state / unresolved_pressure / required_next_check` 时，系统也会把这些 Properties 转成 AI 可见正文、知识索引、叙事状态账本、章节任务卡和目标章节提示；章节保存后会按结构化字段写入 `obsidian_debt` 或 `obsidian_arc` 来源。
- 影响范围：`obsidian_service` 的债务 / 人物弧线 Properties 上下文正文生成、`project_narrative_state_service` 的 Obsidian 债务和人物弧线结构化读取、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动写入作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；新增目标用例 `test_narrative_state_reads_obsidian_debt_and_arc_properties` 和相邻 Obsidian 债务 / 人物弧线用例通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，42 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service -v` 通过，55 个用例；`npm run verify` 通过，包含 321 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查只命中 `docs/去AI技能说明.md:23` 的既有示例短语。

### Obsidian 章节合同 Properties 读取

- 修改摘要：Obsidian `chapter_contract / chapter_plan / scene_plan` 笔记会把 `objective / required_beats / debts_to_advance / debts_to_protect / character_checks / style_checks / forbidden_moves / acceptance_checks / evidence_sources / risk_notes` 等 Properties 转成章节计划正文行。作者只用 Obsidian 属性维护第 58 章合同时，叙事状态账本和模型叙事编辑也能读取章节目标、节拍、禁写动作和验收项；`evidence_sources` 会参与图谱链接和反向链接。
- 影响范围：`obsidian_service` 的 Obsidian frontmatter 上下文正文生成、证据来源图谱关系、叙事状态账本里的 Obsidian 章节计划输入、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动写入作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_project_narrative_state_service.py` 通过；新增目标用例 `test_narrative_state_prompt_reads_obsidian_chapter_contract_properties` 先暴露 Properties 版章节合同只进入标题的问题，修正后通过；相邻章节计划用例和新增用例通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service -v` 通过，54 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，42 个用例；`npm run verify` 通过，包含 320 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查只命中 `docs/去AI技能说明.md:23` 的既有示例短语。

### Obsidian 章节安全图谱风险保留

- 修改摘要：目标章节安全记录会保留不涉及未来笔记的 `unresolved_links` 和 `ambiguous_links`。当前章节可见笔记里的未解析双链和可见范围内的歧义双链，会继续出现在章节上下文和 Obsidian 内容预览里；如果歧义名称同时命中目标章节不可见的笔记，则仍按章节安全规则隐藏。
- 影响范围：`obsidian_service` 的章节安全笔记记录、Obsidian 内容读取、章节上下文图谱风险提示、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；目标用例 `test_obsidian_sync_reports_duplicate_labels_and_ambiguous_links` 和 `test_obsidian_sync_does_not_count_unresolved_links_as_orphans` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，42 个用例；`npm run verify` 通过，包含 319 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查只命中 `docs/去AI技能说明.md:23` 的既有示例短语。

### Obsidian 图谱关系标签章节安全

- 修改摘要：目标章节安全记录会处理 Obsidian 图谱关系标签。Canvas 边或关系小节生成的关系目标即使对当前章节可见，只要关系标签里写到未来笔记名、未来双链或 Markdown 内链，早期章节上下文会改写为“未开放设定”；全书总览仍保留作者写入的原始关系标签。
- 影响范围：`obsidian_service` 的章节安全图谱关系构建、Canvas 章节安全内容、知识检索预览、连续性证据正文、章节上下文、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；目标用例 `test_obsidian_canvas_file_nodes_enter_graph_and_stay_chapter_safe` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，42 个用例；`npm run verify` 通过，包含 319 个后端 unittest 和前端生产构建。

### Obsidian 标签元数据章节安全

- 修改摘要：目标章节安全记录会对 Obsidian `tags` 使用与 `aliases / keywords / required_phrases / forbidden_phrases` 相同的章节安全处理。标签里写到未来双链、Markdown 内链或已知未来笔记纯文本标题 / 路径名 / 文件名时，早期章节上下文会改写为“未开放设定”；全书总览里的原始笔记摘要仍保留作者写入的真实标签。
- 影响范围：`obsidian_service` 的章节安全笔记记录、知识检索预览、连续性证据正文、章节上下文、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，42 个用例；`npm run verify` 通过，包含 319 个后端 unittest 和前端生产构建；`git diff --check` 通过；相对日期表述检查只命中 `docs/去AI技能说明.md:23` 的既有示例短语。

### Obsidian 同笔记内部链接过滤

- 修改摘要：Obsidian 同步会过滤指向当前笔记自己的内部链接。`[[当前线索#内部索引]]`、`[[当前线索^scene-a]]` 和 `[回看](当前线索.md#内部索引)` 这类 heading / block 导航不会生成跨笔记 links、resolved_links、backlinks 或 graph_relations；同一笔记里的外部链接仍正常进入图谱。
- 影响范围：`obsidian_service` 的图谱关系富集、links / resolved_links / backlinks / graph_relations 统计、孤立笔记判断、Obsidian 维护建议、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；目标用例 `test_obsidian_same_note_links_do_not_create_graph_noise` 和相邻块引用用例通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，42 个用例；`npm run verify` 通过，包含 319 个后端 unittest 和前端生产构建。

### Obsidian Markdown 快捷引用解析

- 修改摘要：Obsidian Markdown 正文会解析快捷引用式链接。`[林追旧档]` 配合同一笔记里的 `[林追旧档]: ../Characters/林追\(旧\).md "旧档"` 会生成可解析链接、反向链接和关系语义；快捷引用指向未来笔记时，章节安全内容会隐藏正文引用、定义路径和 title；Markdown 脚注 `[^id]: ...` 不会被误当成知识图谱链接。
- 影响范围：`obsidian_service` 的 Markdown 引用式链接扫描、正文关系小节、章节安全 Markdown 链接改写、图谱关系、反向链接、未解析链接统计、Obsidian 维护建议、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；目标用例 `test_obsidian_markdown_reference_links_resolve_and_stay_chapter_safe` 和 `test_obsidian_markdown_shortcut_reference_links_resolve_and_stay_chapter_safe` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，41 个用例；`npm run verify` 通过，包含 318 个后端 unittest 和前端生产构建；`git diff --check` 通过。

### Obsidian Markdown 引用式链接解析

- 修改摘要：Obsidian Markdown 正文会解析引用式链接。`[林追旧档][old]` 和 `[old]: ../Characters/林追\(旧\).md "旧档"` 会生成可解析链接、反向链接和关系语义；引用定义指向未来笔记时，章节安全内容会同时隐藏正文引用、定义路径和 title，避免早期章节通过引用定义看到后段设定。
- 影响范围：`obsidian_service` 的 Markdown 链接扫描、正文关系小节、章节安全 Markdown 链接改写、图谱关系、反向链接、未解析链接统计、Obsidian 维护建议、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；目标用例 `test_obsidian_markdown_reference_links_resolve_and_stay_chapter_safe` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，40 个用例；`npm run verify` 通过，包含 317 个后端 unittest 和前端生产构建。

### Obsidian Markdown 转义目标和标题解析

- 修改摘要：Obsidian Markdown 内链目标会按 Markdown 语义处理转义字符和 title。`[林追旧档](../Characters/林追\(旧\).md "旧档")` 会解析到 `Characters/林追(旧).md`，不会把转义括号误写成路径分隔；`[终局答案](../Secrets/未来真相 "终局")` 会去掉 title 后解析到目标笔记。指向未来笔记时，章节安全内容仍会隐藏链接标签、目标路径和对应关系语义。
- 影响范围：`obsidian_service` 的 Markdown 内链目标清理、frontmatter / 正文内联关系字段、正文关系小节、章节安全 Markdown 链接改写、图谱关系、反向链接、未解析链接统计、Obsidian 维护建议、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；目标用例 `test_obsidian_markdown_links_unescape_targets_and_strip_titles` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，39 个用例；`npm run verify` 通过，包含 316 个后端 unittest 和前端生产构建。

### Obsidian Markdown 括号文件名解析

- 修改摘要：Obsidian Markdown 内链改为扫描完整链接目标，支持文件名里包含英文括号。`[林追旧档](../Characters/林追(旧).md)` 会解析到 `Characters/林追(旧).md`，不会截断成不存在的 `林追(旧`；指向未来笔记时，章节安全内容仍会隐藏链接标签、目标路径和对应关系语义。
- 影响范围：`obsidian_service` 的 Markdown 内链目标扫描、frontmatter / 正文内联关系字段、正文关系小节、章节安全 Markdown 链接改写、图谱关系、反向链接、未解析链接统计、Obsidian 维护建议、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；目标用例 `test_obsidian_markdown_links_with_parentheses_resolve_and_stay_chapter_safe` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，38 个用例；`npm run verify` 通过，包含 315 个后端 unittest 和前端生产构建。

### Obsidian 根路径链接解析

- 修改摘要：Obsidian wiki 双链和 Markdown 内链会区分 Vault 根路径与当前笔记相对路径。`[[/Characters/林追]]`、`[林追](/Characters/林追.md)` 会解析到 Vault 内部目标；`[[/../Outside/旧设定]]`、`[外部](/../Outside/旧设定.md)` 这类越出 Vault 根目录的目标不会误连到当前笔记目录，也不会进入图谱链接、未解析链接、图谱关系或维护建议。Markdown 同目录文件名链接会按当前笔记目录解析。
- 影响范围：`obsidian_service` 的 wiki 双链目标解析、Markdown 内链目标解析、frontmatter / 正文内联关系字段、正文关系小节、图谱关系、反向链接、未解析链接统计、Obsidian 维护建议、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：新增目标用例 `test_obsidian_root_relative_links_resolve_and_cannot_escape_vault` 第一次失败，暴露 `[[/../Outside/旧设定]]` 会误连到已存在的 `Outside/旧设定.md`，修正后通过；`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，37 个用例；`npm run verify` 通过，包含 314 个后端 unittest 和前端生产构建。

### Obsidian 双链路径段归一化

- 修改摘要：Obsidian wiki 双链会归一化目标路径里的 `.` 和 `..` 路径段。`[[Clues/../Characters/林追]]` 会解析为 Vault 内部的 `Characters/林追`，进入可解析链接、反向链接和关系语义；`[[Clues/../../Outside/旧设定]]` 这类越出 Vault 的目标不会进入图谱链接、未解析链接、图谱关系或维护建议。
- 影响范围：`obsidian_service` 的 wiki 双链目标解析、frontmatter / 正文内联关系字段、正文关系小节、图谱关系、反向链接、未解析链接统计、Obsidian 维护建议、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；目标用例 `test_obsidian_wiki_dot_segments_normalize_and_cannot_escape_vault` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，36 个用例；`npm run verify` 通过，包含 313 个后端 unittest 和前端生产构建。

## 2026-05-31

### Obsidian 越界相对链接隔离

- 修改摘要：Obsidian 同步会排除越出 Vault 的相对链接。根目录笔记里的 `[[../Outside/旧设定]]`、`[外部](../Outside/旧设定.md)` 不再进入图谱链接、未解析链接、图谱关系或维护建议；子目录中仍指向 Vault 内部的相对路径继续正常解析。
- 影响范围：`obsidian_service` 的双链目标解析、Markdown 内链目标解析、frontmatter / 正文内联关系字段、正文关系小节、图谱关系、未解析链接统计、Obsidian 维护建议、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；目标用例 `test_obsidian_links_outside_vault_do_not_create_graph_noise` 第一次失败，暴露关系字段文本回退仍把外部链接语法当成普通标题，修正后通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，35 个用例；`npm run verify` 通过，包含 312 个后端 unittest 和前端生产构建。

### Obsidian URL 编码保留字符路径解析

- 修改摘要：Obsidian 双链和 Markdown 内链会先识别真实分隔符，再解码路径本体。`[[Characters/林%23追]]`、`[线索](Secrets/未来%5E真相.md)` 这类文件名里的编码保留字符不会被误拆成 heading、query 或 block 引用，图谱链接、反向链接和章节安全预览会按真实目标处理。
- 影响范围：`obsidian_service` 的双链目标解析、Markdown 内链目标解析、frontmatter / 正文内联关系字段、正文关系小节、图谱关系、反向链接、章节安全正文、Obsidian 知识检索、连续性证据正文、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；目标用例 `test_obsidian_percent_encoded_reserved_path_chars_do_not_split_targets` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，34 个用例；`npm run verify` 通过，包含 311 个后端 unittest 和前端生产构建。

### Obsidian URL 编码双链解析

- 修改摘要：Obsidian 双链目标会先做 URL 解码再参与路径归一化。`[[Characters/林%20追]]`、`[[../Secrets/未来%20真相]]` 这类 Vault 链接会生成可解析链接、反向链接和关系语义；目标是未来笔记时，早期章节安全预览、知识检索和连续性证据正文不会暴露未来标题、路径或别名。
- 影响范围：`obsidian_service` 的双链目标解析、frontmatter / 正文内联关系字段、正文关系小节、图谱关系、反向链接、章节安全正文、Obsidian 知识检索、连续性证据正文、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；目标用例 `test_obsidian_percent_encoded_wiki_links_resolve_and_stay_chapter_safe` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，33 个用例；`npm run verify` 通过，包含 310 个后端 unittest 和前端生产构建。

### Obsidian Canvas 相对 file 节点解析

- 修改摘要：Obsidian Canvas 的 file 节点会按 Canvas 所在路径解析 `../Clues/当前线索.md` 这类相对目标，并生成可解析链接、反向链接和关系语义。Canvas 相对 file 节点指向未来笔记时，早期章节安全预览、检索结果和证据正文不会暴露未来节点标题或边标签。
- 影响范围：`obsidian_service` 的 Canvas file 节点解析、Canvas 图谱关系、反向链接、章节安全正文、Obsidian 知识检索、连续性证据正文、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；目标用例 `test_obsidian_canvas_relative_file_nodes_resolve_and_stay_chapter_safe` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，32 个用例；`npm run verify` 通过，包含 309 个后端 unittest 和前端生产构建。

### Obsidian 相对路径双链解析

- 修改摘要：Obsidian 同步会按来源笔记路径解析 `[[../Characters/林追]]`、`[[./当前线索]]` 这类 Vault 内相对路径双链，并让正文、frontmatter / 正文内联关系字段、正文关系小节、章节安全预览和证据正文共用同一套目标归一化。相对路径指向未来笔记时，早期章节不会通过链接目标、关系语义、检索结果或别名看到后段设定。
- 影响范围：`obsidian_service` 的双链目标解析、图谱关系、可解析链接、反向链接、章节安全正文、Obsidian 知识检索、连续性证据正文、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；目标用例 `test_obsidian_relative_wiki_links_resolve_and_stay_chapter_safe` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，31 个用例；`npm run verify` 通过，包含 308 个后端 unittest 和前端生产构建。

### Obsidian 块引用图谱解析

- 修改摘要：Obsidian 同步会把 `[[笔记^block-id]]`、`[[笔记#小节^block-id]]` 这类块引用按对应笔记解析，不再把块 ID 当成笔记标题的一部分。块引用会进入可解析链接、反向链接、关系语义、章节安全预览和证据正文；如果目标笔记对当前章节不可见，仍会改写为“未开放设定”。
- 影响范围：`obsidian_service` 的双链解析、知识索引内容、图谱链接、反向链接、关系字段、章节安全正文、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；目标用例 `test_obsidian_block_references_resolve_and_stay_chapter_safe` 通过；相邻章节安全用例 `test_obsidian_summary_and_keywords_are_searchable_and_chapter_safe` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，30 个用例；`npm run verify` 通过，包含 307 个后端 unittest 和前端生产构建。

### Obsidian 纯文本剧透标题章节安全

- 修改摘要：目标章节上下文会把当前章不可见的已知 Obsidian 笔记标题、路径名和文件名，从章节安全摘要、正文、别名、关键词、必写项和禁写项中改写为“未开放设定”。如果当前可见笔记把未来标题误写成 alias，系统不会再把这个 alias 当作可见标签，避免早期章节通过纯文本元数据、检索预览、证据正文或图谱关系看到后段笔记标题。
- 影响范围：`obsidian_service` 的章节可见标签表、纯文本改写、scoped Obsidian 记录生成、章节上下文选择、知识检索预览、连续性证据正文、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py backend/tests/test_context_builder.py` 通过；扩展目标用例 `test_obsidian_summary_and_keywords_are_searchable_and_chapter_safe` 通过；扩展目标用例 `test_project_context_bundle_filters_obsidian_notes_by_chapter_scope` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，29 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder -v` 通过，18 个用例；`npm run verify` 通过，包含 306 个后端 unittest 和前端生产构建。

### 去 AI 智能巡检触发

- 修改摘要：去 AI 裁判从手动模型审查扩展为后台智能巡检。章节正文保存和做梦完成会排队 `humanize_review` 辅助任务；自学习心跳在排程开启且包含 `model_review` 时，会按真实章节样本池、历史 `chapter_humanize` 输出、项目规则、样本签名、12 小时冷却时间和 7 天同样本复查窗口决定是否触发裁判模型。巡检结果继续写入 `self_evolution_model_reviews.jsonl`，有效改法写入 `humanize_evolution_rules.json`，巡检状态写入 `humanize_review_patrol.json`，自学习面板显示去 AI 巡检状态和触发来源。
- 影响范围：`self_evolution_service` 的去 AI 巡检状态、触发决策和裁判记录，`self_evolution_scheduler_service` 的心跳触发，`project_auxiliary_service` 的 `humanize_review` 辅助任务，`project_service` 的章节保存和做梦排队，`SkillLibraryPanel` 的巡检状态展示，相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、去 AI 技能说明、记忆系统说明和技能流程回归清单；不改变章节正文写回格式、去 AI 接口路径或模型配置结构。
- 验证结果：`.venv/bin/python -m py_compile backend/novel_backend/services/self_evolution_service.py backend/novel_backend/services/self_evolution_scheduler_service.py backend/novel_backend/services/project_auxiliary_service.py backend/novel_backend/services/project_service.py backend/tests/test_self_evolution_service.py backend/tests/test_project_auxiliary_service.py backend/tests/test_project_service.py` 通过；`.venv/bin/python -m unittest backend.tests.test_self_evolution_service -v` 通过，11 个用例；`.venv/bin/python -m unittest backend.tests.test_project_auxiliary_service -v` 通过，3 个用例；`.venv/bin/python -m unittest backend.tests.test_project_service.ProjectServiceTestCase.test_run_project_dream_auto_promotes_candidate_to_system_memory backend.tests.test_project_service.ProjectServiceTestCase.test_story_change_refreshes_dream_report_automatically -v` 通过；`node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` 通过；`npm run build` 通过；`git diff --check` 通过；`npm run verify` 未通过，失败点为 `test_context_builder.ContextBuilderTestCase.test_project_context_bundle_filters_obsidian_notes_by_chapter_scope` 和 `test_obsidian_service.ObsidianServiceTestCase.test_obsidian_summary_and_keywords_are_searchable_and_chapter_safe`，失败内容是 Obsidian 章节安全文本仍出现“未来真相”或关系文本格式不符合断言；这两个失败点不在本次去 AI 巡检改动文件内。

### Obsidian 元数据章节安全

- 修改摘要：目标章节上下文会对 `aliases / keywords / required_phrases / forbidden_phrases` 里的 Obsidian 双链和 Markdown 内链执行章节安全改写。早期章节的检索预览、证据正文、“本章 Obsidian 设定检查清单”和“本章 Obsidian 写作约束”不会因为元数据字段提前显示后段笔记标题。
- 影响范围：`obsidian_service` 的 scoped Obsidian 记录生成、章节上下文选择、Obsidian 写作约束、连续性证据正文、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py backend/tests/test_context_builder.py` 通过；扩展目标用例 `test_obsidian_summary_and_keywords_are_searchable_and_chapter_safe` 通过；扩展目标用例 `test_project_context_bundle_filters_obsidian_notes_by_chapter_scope` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，29 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder -v` 通过，18 个用例；`npm run verify` 通过，包含 304 个后端 unittest 和前端生产构建。

### PDF 资料导入 LiteParse 本地增强

- 修改摘要：PDF 文件导入在 `qwen-doc-turbo` 不可用或失败后，会先尝试 LiteParse 本地解析，返回内容按页加入 `【第 N 页】` 标记；LiteParse 未安装、解析失败或无正文时继续回到 `pypdf`，只有本地文本为空时才尝试 LiteParse OCR。OCR 语言可通过 `NOVEL_LITEPARSE_OCR_LANGUAGE` 配置。
- 影响范围：`import_service` 的 PDF 导入顺序、资料库 PDF 文本内容、LiteParse 平台依赖、macOS / Windows sidecar 打包脚本、相关导入解析单测、README、项目 Agent 指令、核心引擎说明和桌面发布回归说明；不改变前端上传接口、资料库 JSON 文件结构或 `knowledge.db` 表结构。
- 验证结果：`.venv/bin/python -m py_compile backend/novel_backend/services/import_service.py backend/tests/test_import_service.py` 通过；`.venv/bin/python -m unittest backend.tests.test_import_service -v` 通过，11 个用例；`bash -n scripts/build-backend-sidecar.sh` 通过；`PYTHONPATH=/tmp/liteparse-py312-target:backend .venv/bin/python` 临时 LiteParse 解析 PDF 通过并返回页码标记；`.venv/bin/python -m pip install -e backend --dry-run --no-deps` 通过；当前环境没有 `pwsh`，Windows 打包脚本只做了静态语法调整，未在 PowerShell 中验证。

### Obsidian Canvas 边标签章节安全

- 修改摘要：章节安全内容处理 Canvas 关系行时，如果边指向目标章节不可见的已知笔记，会把边标签改成 `未开放关系`，同时隐藏未来 file 节点。早期章节不会通过“揭示沉船真相”这类 Canvas 边标签提前看到后段信息。
- 影响范围：`obsidian_service` 的章节安全正文改写、Canvas file 节点关系展示、章节上下文和证据正文、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；扩展目标用例 `test_obsidian_canvas_file_nodes_enter_graph_and_stay_chapter_safe` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，29 个用例；`npm run verify` 通过，包含 300 个后端 unittest 和前端生产构建。

### Obsidian 章节证据检索安全

- 修改摘要：章节化证据检索命中 Obsidian 候选后，会先替换为目标章节安全内容，再确认查询词仍存在。只因为未来标题、双链或 Markdown 内链命中的候选会被丢弃，避免第 1 章的连续性证据包带入只指向未来设定的无效证据。
- 影响范围：`search_project_knowledge_evidence` 的 Obsidian 章节过滤、连续性证据正文、相关后端单测、README、项目 Agent 指令、核心引擎说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_service.py backend/tests/test_obsidian_service.py` 通过；扩展目标用例 `test_obsidian_summary_and_keywords_are_searchable_and_chapter_safe` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，29 个用例；`npm run verify` 通过，包含 300 个后端 unittest 和前端生产构建。

### Obsidian 异常草稿来源章节边界

- 修改摘要：章节生成、改稿和诊断上下文展示 Obsidian 待审草稿时，如果项目内草稿文件已经缺失且无法读取 frontmatter，系统会继续使用维护项里的 `source_chapters` / 正文“来源章节”判断可见范围；如果作者手工删除草稿 frontmatter，但正文仍保留 `source_chapters::` 或“来源章节：...”，系统也会按正文来源章节过滤。含第 58 章和第 60 章来源的异常草稿不会出现在第 59 章提示里，第 60 章才显示草稿缺失或建议路径。
- 影响范围：`project_narrative_state_service` 的待审草稿提示过滤、叙事状态账本章节提示、README、项目 Agent 指令、Agent 执行架构说明、核心引擎说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；扩展目标用例 `test_obsidian_maintenance_source_chapters_open_after_latest_source` 通过，覆盖草稿缺失和无 frontmatter 正文来源章节两种异常草稿；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service -v` 通过，53 个用例；`npm run verify` 通过，包含 300 个后端 unittest 和前端生产构建。

### Obsidian 来源章节剧透边界

- 修改摘要：系统生成 Obsidian 维护草稿时，`source_chapters` 对应的 `reveal_after_chapter` 改为按最晚来源章计算。系统学习版文风 / XP 规则如果来自第 58 章和第 60 章，第 59 章不会提前看到由第 60 章参与沉淀出的规则；发布到 Vault 后，项目级文风 / XP 提示也按同一边界过滤。
- 影响范围：文风 / XP、剧情债务、人物状态和章节档案维护草稿的来源章节剧透边界、发布后 Vault 笔记可见性、项目级文风 / XP 提示、相关后端单测、README、项目 Agent 指令、核心引擎说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；新增目标用例 `test_style_xp_maintenance_uses_latest_source_chapter_boundary` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service -v` 通过，53 个用例；`npm run verify` 通过，包含 300 个后端 unittest 和前端生产构建。

### Obsidian Graph 开放来源边界

- 修改摘要：未解析双链生成 Graph 待审草稿时，如果来源笔记都是开放式章节范围但开放起点不同，例如 `chapter_range: 58+` 与 `chapter_range: 60+`，系统会按较晚来源写入 `reveal_after_chapter`，不再生成从较早章节起可见的草稿。第 59 章不会看到带第 60 章来源路径的 `Graph/潮汐账本.md` 待审项，发布到 Vault 后也按同一边界过滤。
- 影响范围：`project_narrative_state_service` 的 Graph 维护草稿章节边界生成、待审草稿提示、Agent 能力上下文、发布后 Vault 笔记可见性、README、项目 Agent 指令、核心引擎说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；新增目标用例 `test_graph_maintenance_draft_uses_latest_boundary_for_open_source_scopes` 通过；相邻 Graph 边界用例通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service -v` 通过，52 个用例；`npm run verify` 通过，包含 299 个后端 unittest 和前端生产构建。

### Obsidian 待审草稿来源章节边界

- 修改摘要：Obsidian 待审草稿和维护建议在没有显式 `chapter_range` 或 `reveal_after_chapter` 时，会读取 frontmatter 与正文里的 `source_chapters` / “来源章节”，并按最晚来源章节进入 Agent 上下文。含第 58 章和第 60 章来源的维护项不会出现在第 59 章规划提示里。
- 影响范围：叙事状态账本维护建议可见性、Agent 能力上下文、待审草稿章节过滤、相关后端单测、README、项目 Agent 指令、技能流程回归清单和测试反馈清单；不改变 Vault 正式笔记同步规则、不写入作者 Vault、不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；新增目标用例 `test_obsidian_maintenance_source_chapters_open_after_latest_source` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service -v` 通过，51 个用例；`npm run verify` 通过，包含 298 个后端 unittest 和前端生产构建。

### Obsidian 来源章节界面展示

- 修改摘要：技能库 `Obsidian 知识库` 面板和架构总览的 Obsidian 笔记卡片会显示 `source_chapters` 来源章节。作者查看 Vault 笔记时，可以直接看到资料来自哪些章节，不需要打开 Markdown 原文确认来源。
- 影响范围：`StoryOverviewPanel`、`SkillLibraryPanel`、UI smoke、README、项目 Agent 指令、界面回归说明、技能流程回归清单和测试反馈清单；不改变后端接口、知识库索引或 Vault 写入策略。
- 验证结果：`node --check scripts/verify-ui-smoke.mjs` 通过；`npm run build` 通过；`npm run verify` 通过，包含 297 个后端 unittest 和前端生产构建；`npm run verify:ui` 在当前沙箱因 `listen EPERM: operation not permitted 127.0.0.1` 无法启动本地服务，未进入页面检查阶段。

### Obsidian 章节档案来源章节移动识别

- 修改摘要：已发布章节档案移动或改名后，维护动作会同时读取 `gaoxia_maintenance_kind` 和 `source_chapters`。作者把章节档案类型改成 `author_archive`，删除 `source_ids`，但保留 `source_chapters` 时，系统仍能按来源章节识别移动后的 Vault 笔记，不再重复生成同一章档案建议。
- 影响范围：Obsidian 章节档案匹配、已发布维护动作路径识别、`source_chapters` frontmatter 解析、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动写入作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/models.py backend/novel_backend/services/obsidian_service.py backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_obsidian_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_chapter_note_source_ids_match_after_author_reorganizes_vault_note backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_chapter_note_source_chapters_match_after_author_removes_source_ids` 通过，31 个用例；`npm run verify` 通过，包含 297 个后端 unittest 和前端生产构建。

### Obsidian 来源章节摘要元数据

- 修改摘要：Obsidian 同步摘要新增 `source_chapters` 字段，Markdown frontmatter、Markdown 正文“来源章节”和 Canvas 文本属性解析出的来源章节会进入 `ObsidianNoteSummary`；知识内容头部也会写入来源章节，方便界面、章节上下文和后续维护逻辑读取同一份来源章节元数据。
- 影响范围：`ObsidianNoteSummary`、Obsidian Markdown / Canvas 同步、知识内容构建、章节安全检索内容、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动写入作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/models.py backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service` 通过，29 个用例；`npm run verify` 通过，包含 297 个后端 unittest 和前端生产构建。

### Obsidian 来源章节推断保护

- 修改摘要：Obsidian 同步器会读取 `source_chapters` 和正文“来源章节”来推断章节档案开放范围。作者删除 `reveal_after_chapter` 但保留来源章节时，档案仍会按来源章节过滤；文件名或路径章节早于来源章节时，系统按更晚的开放章节处理。
- 影响范围：Obsidian Markdown / Canvas 同步、章节安全检索、章节档案 `source_ids / source_chapters` 约定、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动写入作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service` 通过，29 个用例；`npm run verify` 通过，包含 296 个后端 unittest 和前端生产构建。

### Obsidian 多章节来源 ID 剧透保护

- 修改摘要：Obsidian 同步器在从 `source_ids` 推断章节范围时，会读取全部 `chapter-*` 来源 ID，并以最晚来源章节作为开放起点。包含 `source_ids: [chapter-058, chapter-060]` 的合并档案会从第 60 章起可见，第 59 章不会通过知识检索提前看到第 60 章资料。
- 影响范围：Obsidian Markdown / Canvas 同步、章节安全检索、章节档案 `source_ids` 约定、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动写入作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service` 通过，28 个用例；`npm run verify` 通过，包含 295 个后端 unittest 和前端生产构建。

### Obsidian 章节档案来源 ID 识别

- 修改摘要：章节档案草稿会把来源章节写入 `source_ids`，Obsidian 同步器会在没有显式章节范围或剧透边界时，从 `source_ids: [chapter-058]` 推断第 58 章起可见。作者把已发布章节档案移到自定义目录、改名或重写标题后，只要保留来源 ID，系统仍会按来源章节过滤早期 / 后续章节，也不会重复生成同一章档案维护建议。
- 影响范围：`ObsidianNoteSummary`、Obsidian frontmatter / 内联属性解析、章节安全检索、章节档案维护匹配、已发布维护动作路径重绑定、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动写入作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/models.py backend/novel_backend/services/obsidian_service.py backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_obsidian_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service backend.tests.test_project_narrative_state_service` 通过，76 个用例；`npm run verify` 通过，包含 294 个后端 unittest 和前端生产构建。

### 小说项目迁移包

- 修改摘要：新增作品迁移包能力。当前作品可以导出为 `.gaoxia-project.zip`，迁移包包含完整作品目录、章节、设定、`.gaoxia` 状态、`.novel-history` 本地历史和 `knowledge.db`；导入迁移包会复制到当前工作区并注册到作品列表，同机重复导入不会覆盖原作品，会生成新的作品 ID。项目目录外的 Obsidian Vault 原文不会复制进迁移包，导出 / 导入结果会给出提醒。
- 影响范围：`POST /api/projects/{project_id}/migration/export`、`POST /api/projects/migration/import`、作品列表导入入口、作品菜单和工作台更多菜单里的“导出迁移包”、项目服务迁移包校验与导入注册逻辑、UI smoke 脚本、项目服务测试、README、项目 Agent 指令、核心引擎说明、技能流程回归清单、界面回归说明、测试反馈清单和 macOS 测试说明；不改变原有 Markdown / 纯文本整本导出接口。
- 验证结果：`python3 -m py_compile backend/novel_backend/models.py backend/novel_backend/services/project_service.py backend/novel_backend/api/projects.py backend/tests/test_project_service.py` 通过；`node --check src/lib/api.js` 通过；迁移包 3 个目标后端用例通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_service -v` 通过，49 个用例通过，仍有既有 sqlite `ResourceWarning` 输出；`npm run build` 通过；`node --check scripts/verify-ui-smoke.mjs` 通过。`npm run verify` 未通过，失败点为 `test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_saved_chapter_generates_obsidian_chapter_note_draft_visible_to_later_chapters`，实际章节范围为 `(58, 0, 57)`，测试期望为 `(0, 0, 57)`；`npm run verify:ui` 未通过，脚本在进入迁移校验前等待“整书架构已经补齐并写回项目”超时。

### 去 AI A/B 自动回归

- 修改摘要：Agent 自学习写作回归新增 `humanize_ab_benchmark`。系统会用固定小说差评片段做 A/B，对比原文和预期改写后的本地评分、平均提升、通过率、正文长度比例和残留问题；同时扫描真实章节生成 `project_sample_pool`，把项目内风险章节、主要问题和片段纳入蒸馏规则。Agent 自学习模型审查新增去 AI 裁判，会回放历史 `chapter_humanize` 输出，让模型按自然度、人物声音、叙事张力、非模板化和误报风险评分，并把有效改法写入 `.gaoxia/learning/humanize_evolution_rules.json`。后续章节去 AI prompt 会读取这些项目规则。
- 影响范围：`self_evolution_service` 的写作回归结果、真实章节项目样本池、低频去 AI 模型裁判、历史去 AI 输出回放、项目去 AI 自学习规则、能力看板趋势、模型审查启发式建议、`studio_service` 去 AI prompt、`SkillLibraryPanel` 自学习面板、相关后端单测、README、项目 Agent 指令、去 AI 技能说明、记忆系统说明和技能流程回归清单；不改变章节正文写回格式、模型配置、知识库结构或去 AI 接口路径。
- 验证结果：`.venv/bin/python -m py_compile backend/novel_backend/services/self_evolution_service.py backend/novel_backend/services/studio_service.py backend/tests/test_self_evolution_service.py` 通过；`.venv/bin/python -m unittest backend.tests.test_self_evolution_service.SelfEvolutionServiceTestCase.test_cycle_records_candidates_rules_usage_and_writing_evaluation -v` 通过；`.venv/bin/python -m unittest backend.tests.test_self_evolution_service -v` 通过，10 个用例；`node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` 通过；`npm run build` 通过；`git diff --check` 通过；80 章模拟目录下项目样本池扫描约 `38.75ms`，完整去 AI A/B benchmark 约 `37.65ms`；`npm run verify` 通过，包含 300 个后端 unittest 和前端生产构建。

### Obsidian 文风 / XP 规则来源识别

- 修改摘要：系统学习版文风 / XP 规则发布到 Vault 后，维护匹配会读取正式笔记 frontmatter 里的 `source_ids`。作者在 Obsidian 中改名、移动、改写标题、摘要或规则正文后，只要保留来源 ID，系统仍会识别为同一条规则，不重复生成维护建议，同时改写后的规则内容继续进入目标章节文风 / XP 提示。
- 影响范围：`project_narrative_state_service` 的文风 / XP 规则匹配、Vault 来源 ID 读取、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动写入作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_active_style_xp_rules_generate_obsidian_maintenance_suggestions` 通过；`npm run verify` 通过，包含 289 个后端 unittest 和前端生产构建。

### 小说去 AI 规则扩展

- 修改摘要：去 AI 改稿从通用模板腔扫描扩展为小说正文专用处理。新增套版画面词、抽象情绪直说、潜台词解释、对白标签模板化、句长 / 段长过齐和句首主语重复等本地规则；去 AI prompt 会先保剧情事实、人物声音、信息顺序和伏笔，再处理句式、画面、节奏和结尾。完整章节修订稿如果明显短于原文，会拒绝本次结果，避免把章节缩成摘要。
- 影响范围：`humanize_service` 的本地评分和 prompt、`studio_service` 的去 AI 修订长度检查、Agent 去 AI 改稿产物的评分 metadata、去 AI 后端回归测试、README、项目 Agent 指令、去 AI 技能说明、Agent 执行架构说明、记忆系统说明和技能流程回归清单；不改变模型配置、章节文件格式、知识库结构或前端接口路径。
- 验证结果：`.venv/bin/python -m unittest backend.tests.test_humanize_service backend.tests.test_studio_service.StudioServiceTestCase.test_chapter_humanize_stream_returns_quality_report backend.tests.test_studio_service.StudioServiceTestCase.test_chapter_humanize_stream_rejects_summary_like_revision -v` 通过；`.venv/bin/python -m unittest backend.tests.test_agent_service.AgentServiceTestCase.test_rewrite_request_gets_continuity_review_step backend.tests.test_agent_service.AgentServiceTestCase.test_execution_suggests_saving_reusable_skill_from_natural_language -v` 通过；`npm run verify` 通过，包含 289 个后端 unittest 和前端生产构建。

### Obsidian 剧情债务和人物状态来源识别

- 修改摘要：剧情债务和人物状态维护建议现在会读取已发布 Vault 笔记 frontmatter 里的 `source_ids`。作者把自动生成的剧情债务或人物状态笔记发布后，即使在 Obsidian 中改名、移动或改写标题，只要保留来源 ID，系统仍会识别为同一条账本来源，不再重复生成同一条维护建议。
- 影响范围：`project_narrative_state_service` 的剧情债务匹配、人物状态匹配、Vault 来源 ID 读取、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明和测试反馈清单；不改变 `knowledge.db` 表结构，不自动写入作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_narrative_state_suggests_obsidian_notes_for_untracked_debts backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_character_maintenance_draft_uses_source_chapter_boundary` 通过；`npm run verify` 通过，包含 289 个后端 unittest 和前端生产构建。

### Obsidian 章节合同作者改写识别

- 修改摘要：模型章节合同发布到 Vault 后，维护匹配会先读取已发布笔记 frontmatter 里的 `gaoxia_maintenance_id`；如果作者整理笔记时删掉该字段，但保留 `source_ids` 里的原始合同 ID，系统仍会把它识别为同一份合同。作者在 Obsidian 中改写合同目标或节拍措辞后，改写后的合同小节继续进入目标章节提示。
- 影响范围：`project_narrative_state_service` 的章节合同匹配、Obsidian 章节计划记录筛选、Vault 笔记身份与来源 ID 读取、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明和测试反馈清单；不改变 `knowledge.db` 表结构，不自动写入作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_model_chapter_contract_becomes_obsidian_plan_draft` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_model_chapter_contract_becomes_obsidian_plan_draft backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_narrative_state_prompt_includes_obsidian_chapter_plan_notes backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_model_editor_adds_chapter_contract_to_next_chapter_prompt` 通过；`npm run verify` 通过，包含 286 个后端 unittest 和前端生产构建。

### Obsidian 章节合同结构化读取

- 修改摘要：已发布的 Obsidian `chapter_contract` 笔记不再按普通计划正文截取前几行，而是按合同小节提取章节目标、必须完成的节拍、必须推进的债务、不能提前揭开的债务、人物检查、文风检查、禁止动作和验收项。模型生成合同发布到 Vault 后，第 58 章这类目标章节提示可以继续看到保护债务、禁止动作和验收项。
- 影响范围：`project_narrative_state_service` 的 Obsidian 章节计划正文解析、章节计划提示行数、章节合同发布后提示内容、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动写入作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_model_chapter_contract_becomes_obsidian_plan_draft` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_model_chapter_contract_becomes_obsidian_plan_draft backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_narrative_state_prompt_includes_obsidian_chapter_plan_notes backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_model_editor_adds_chapter_contract_to_next_chapter_prompt` 通过；`npm run verify` 通过，包含 286 个后端 unittest 和前端生产构建。

### 模型章节合同生成 Obsidian 计划草稿

- 修改摘要：模型叙事编辑生成的下一章章节合同如果没有匹配到可用 Vault 章节计划或章节合同笔记，会进入 Obsidian 维护队列，生成 `Plans/` 中优先级待审草稿。草稿包含 `type: chapter_contract`、目标章节 `chapter_range`、来源章节、合同目标、必须完成的节拍、债务推进、人物检查、文风检查、禁止动作、验收项、证据来源和 `gaoxia_maintenance_id`；作者发布后，笔记会作为 Vault 正式章节计划进入目标章节提示，并停止显示同一合同维护建议。
- 影响范围：`project_narrative_state_service` 的 Obsidian 维护建议生成、章节合同草稿 Markdown、发布后匹配判断、叙事状态提示、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动写入作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_model_chapter_contract_becomes_obsidian_plan_draft` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_model_editor_adds_chapter_contract_to_next_chapter_prompt backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_model_chapter_contract_becomes_obsidian_plan_draft backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_pending_obsidian_drafts_prioritize_target_chapter` 通过；`npm run verify` 通过，包含 286 个后端 unittest 和前端生产构建。

### 系统学习版文风 / XP 生成 Obsidian 待审草稿

- 修改摘要：系统学习版文风 / XP 规则在至少两个章节重复出现并变为 `active` 后，如果没有匹配到可用 Vault 规则笔记，会进入 Obsidian 维护队列，生成 `Style/` 或 `XP/` 低优先级待审草稿。草稿带来源规则、来源章节、剧透边界和 `gaoxia_maintenance_id`；作者显式发布后，才作为 Vault 正式文风 / XP 规则进入后续章节提示。
- 影响范围：`project_style_xp_evolution_service` 的 Obsidian 规则识别公开入口、`project_narrative_state_service` 的维护建议生成和排序、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不自动写入作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/novel_backend/services/project_style_xp_evolution_service.py backend/tests/test_project_narrative_state_service.py` 通过；未设置 `PYTHONPATH` 直接执行目标 unittest 时出现 `ModuleNotFoundError: No module named 'novel_backend'`，改用 `PYTHONPATH=backend` 后通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_active_style_xp_rules_generate_obsidian_maintenance_suggestions` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_style_xp_evolution_service` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_pending_obsidian_drafts_prioritize_target_chapter` 通过；`npm run verify` 通过，包含 285 个后端 unittest 和前端生产构建。

### Agent Obsidian 维护产物按来源章节过滤

- 修改摘要：Agent 结果区的 `obsidian_maintenance` 产物卡片打开 Agent 自学习面板时，不再把章节号写进文本搜索框，而是设置专门的来源章节过滤；维护列表也显示每条建议的来源章节。80 章长篇里查看第 3 章维护产物时，不会因为搜索数字 `3` 混入第 13 章、第 30 章或路径编号命中的维护项。
- 影响范围：`NovelWorkflowPanel` 的产物跳转参数、`SkillLibraryPanel` 的 Obsidian 维护来源章节过滤和列表展示、UI smoke、README、项目 Agent 指令、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Obsidian Vault 写入策略。
- 验证结果：`node --check scripts/verify-ui-smoke.mjs` 通过；`node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` 通过；`npm run verify` 通过，包含 284 个后端 unittest 和前端生产构建；`npm run verify:ui` 授权本地端口监听后通过；`git diff --check` 通过；文档相对时间检查无命中。

## 2026-05-30

### Agent 章节写回展示 Obsidian 维护产物

- 修改摘要：Agent 执行章节生成、`chapter_workflow(mode=draft)` 或章节改稿写回后，会对比保存前后的 Obsidian 维护动作；如果当前保存生成或更新了当前章节相关的待审草稿，执行结果会追加 `obsidian_maintenance` 产物，列出待审草稿状态和路径，并在 `changes` 中提示已生成第 N 章相关 Obsidian 维护产物。作者不需要打开自学习面板才能知道系统已经整理了哪些 Vault 候选资料；从产物卡片也可以直接打开 Agent 自学习面板，并按来源章节筛选 Obsidian 维护项。
- 影响范围：`agent_service` 的章节写回、draft 写回和改稿写回执行反馈、`AgentArtifactSummary` 的产物标签、预览文案和维护队列入口，`NovelWorkflowPanel` 到 `App` 的技能打开事件，`SkillLibraryPanel` 的外部打开和维护项筛选、Agent 执行单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Obsidian Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/agent_service.py backend/tests/test_agent_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_agent_service.AgentServiceTestCase.test_chapter_generate_reports_obsidian_maintenance_artifact` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_agent_service` 通过，38 个用例；`node --check scripts/verify-ui-smoke.mjs` 通过；`node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` 通过；`npm run verify` 通过，包含 284 个后端 unittest 和前端生产构建；`npm run verify:ui` 直接执行因沙箱禁止监听 `127.0.0.1` 失败，授权本地端口监听后第一次在 Obsidian 结果等待 `灯塔议会` 超时，重试通过；新增 Agent 结果 `obsidian_maintenance` 产物卡片跳转覆盖时，授权 UI smoke 曾因章节选择未切到第 3 章导致等待 `chapter-003` 超时，后改为写入真实 Agent 线程产物验证；又因脚本只等待章节工作台输入框而没有接受整书架构输入框导致超时，更新等待条件后 `npm run verify:ui` 授权执行通过；`git diff --check` 通过；文档相对时间检查无命中。

### Agent 章节范围生成计划展开

- 修改摘要：用户明确要求生成 2 到 3 章范围正文时，Agent 规划提示会要求每章独立动作；如果规划模型只返回一个 `chapter_generate` 或 `chapter_workflow(mode=draft)`，后端会按章节范围展开成逐章生成动作，再让每章进入去 AI 和一致性复查。模型不可用时，本地规则也会识别“写第 2 到 3 章正文”这类范围指令；超过 3 章的直接正文生成请求会提示分批或先整理章节蓝图，避免计划缩水成单章。
- 影响范围：`agent_service` 的章节范围解析、模型规划结果本地校验、本地规则回退规划、Agent 规划单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Obsidian Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/agent_service.py backend/tests/test_agent_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_agent_service.AgentServiceTestCase.test_model_planner_capability_scope_reads_chapter_range backend.tests.test_agent_service.AgentServiceTestCase.test_heuristic_write_plan_expands_chapter_range backend.tests.test_agent_service.AgentServiceTestCase.test_heuristic_write_plan_rejects_large_chapter_range` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_agent_service` 通过，37 个用例；`npm run verify` 通过，包含 283 个后端 unittest 和前端生产构建。

### Agent 多章节资料分析按章节刷新

- 修改摘要：Agent 执行多章节计划时，如果 `review_knowledge` 先继承第一个目标章节，后续章节动作切到另一个章节会重新生成该目标章的资料库和 Obsidian 分析摘要，并缓存给同章生成、改稿和一致性复查使用；第 59 章不会复用第 58 章的资料分析结论。
- 影响范围：`AgentExecutionState` 的资料摘要状态、`agent_service` 的章节生成 / draft / 改稿 / 一致性检查执行链路、Agent 执行单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Obsidian Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/agent_runtime/registry.py backend/novel_backend/services/agent_service.py backend/tests/test_agent_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_agent_service.AgentServiceTestCase.test_approved_multi_chapter_plan_refreshes_knowledge_summary_per_chapter` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_agent_service` 通过，37 个用例；`npm run verify` 通过，包含 283 个后端 unittest 和前端生产构建。

### Agent 多章节 Obsidian 目标上下文

- 修改摘要：Agent 能力上下文现在支持多个目标章节；路由 / 规划会识别“第 58 到 60 章”“第 58 章到第 60 章”这类范围目标，也会在“先检查第一章，再生成第二章”中优先使用生成、改稿、拆场或诊断目标；包含“蓝图 / 架构”等词但明确写了章节范围时，也会优先读取目标章节 Obsidian 任务。上下文最多展开前 3 个目标章节的 Obsidian 任务摘要，维护建议按这些目标章节共同筛选和排序。
- 影响范围：`agent_service` 的章节范围识别和规划上下文传参、`self_evolution_service` 的多章节 Obsidian 任务摘要与维护建议排序、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/self_evolution_service.py backend/novel_backend/services/agent_service.py backend/tests/test_self_evolution_service.py backend/tests/test_agent_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_self_evolution_service.SelfEvolutionServiceTestCase.test_capability_context_includes_multiple_target_chapter_obsidian_tasks` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_agent_service.AgentServiceTestCase.test_model_planner_capability_scope_reads_chapter_range` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_agent_service.AgentServiceTestCase.test_model_planner_capability_scope_keeps_chapter_range_for_blueprint_request` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_self_evolution_service` 通过，10 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_agent_service` 通过，34 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_self_evolution_service backend.tests.test_agent_service` 通过，44 个用例；`npm run verify` 通过，包含 280 个后端 unittest 和前端生产构建。

## 2026-05-29

### Obsidian 待审草稿按目标章节排序

- 修改摘要：章节生成上下文和 Agent 规划上下文展示 Obsidian 待审草稿时，会按来源章节与目标章节的相关性排序，并显示来源章节；当前目标章的章节档案会优先出现，同时 Graph 图谱风险草稿不会被普通章节档案、剧情债务或人物草稿淹没。
- 影响范围：`project_narrative_state_service` 的待审草稿提示排序和提示文本、`self_evolution_service` 的 Agent 规划上下文、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/novel_backend/services/self_evolution_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_pending_obsidian_drafts_prioritize_target_chapter backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_narrative_state_turns_repeated_unresolved_obsidian_links_into_drafts` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service` 通过，46 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_self_evolution_service` 通过，9 个用例；`npm run verify` 通过，包含 277 个后端 unittest 和前端生产构建。

### Obsidian 章节档案记录任务来源

- 修改摘要：自动生成的 `ChapterNotes/` 章节档案草稿现在会把本章命中的 Obsidian 章节计划、剧情债务和人物弧线来源加入 `source_notes`，正文也会列出本章 Obsidian 章节计划、剧情债务和人物弧线；发布到 Vault 后，这些来源会进入图谱关系，后续章节能追溯本章写作依据。
- 影响范围：`project_narrative_state_service` 的章节档案草稿生成、章节档案发布后的 Obsidian 图谱关系、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，也不会自动写回作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_saved_chapter_generates_obsidian_chapter_note_draft_visible_to_later_chapters` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service` 通过，45 个用例；`npm run verify` 通过，包含 276 个后端 unittest 和前端生产构建。

### Agent 规划上下文读取目标章节 Obsidian 任务

- 修改摘要：Agent 能力上下文现在会按目标章节生成 Obsidian 任务摘要，包含来源、章节计划、必写项、禁写项、剧情债务、人物弧线和图谱风险；即使该章节还没有保存过章节任务卡，路由 / 规划模型也能在决定执行步骤前看到 Vault 约束。
- 影响范围：`project_narrative_state_service` 的章节任务卡公开构建入口、`self_evolution_service` 的 Agent 能力上下文、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，也不写回作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/novel_backend/services/self_evolution_service.py backend/tests/test_self_evolution_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_self_evolution_service.SelfEvolutionServiceTestCase.test_capability_context_includes_target_chapter_obsidian_tasks` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_self_evolution_service` 通过，9 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service` 通过，45 个用例；`npm run verify` 通过，包含 276 个后端 unittest 和前端生产构建。

### Obsidian 债务和人物弧线进入章节任务卡

- 修改摘要：章节任务卡现在会保存目标章节可见的 Obsidian `narrative_debts` 和 `character_arcs`，叙事状态提示会单独展示 `Obsidian 剧情债务` 和 `Obsidian 人物弧线`；Agent 自学习面板的最新章节任务卡会显示这些 Vault 条目，作者能看到当前章引用了哪些剧情债务和人物状态。
- 影响范围：`project_narrative_state_service` 的章节任务卡和叙事状态提示、`SkillLibraryPanel` 的自学习面板展示、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，也不写回作者 Obsidian Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py backend/tests/test_self_evolution_service.py` 通过；直接用未设置 `PYTHONPATH` 的 `python3 -m unittest ...` 执行两个目标用例时出现 `ModuleNotFoundError: No module named 'novel_backend'`，改用项目测试环境变量后通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_saved_chapter_persists_obsidian_debt_and_arc_notes` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_self_evolution_service.SelfEvolutionServiceTestCase.test_state_refreshes_narrative_cards_from_current_obsidian` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service` 通过，45 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_self_evolution_service` 通过，8 个用例；`npm run verify` 通过，包含 275 个后端 unittest 和前端生产构建。

### Obsidian 债务和人物弧线进入下一章合同输入

- 修改摘要：模型叙事编辑收到的 `obsidian_next_chapter` 现在包含下一章可见的 `narrative_debts` 和 `character_arcs`，生成下一章章节合同时会明确读取这些 Vault 正式笔记；原有章节计划、必写项、禁写项和图谱风险仍按章节范围过滤。
- 影响范围：`project_narrative_state_service` 的 Obsidian 指导载荷、模型叙事编辑系统提示、下一章合同输入、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明和记忆系统说明；不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_model_editor_receives_obsidian_guidance_for_next_chapter -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service -v` 通过，45 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，26 个用例；`npm run verify` 通过，包含 275 个后端 unittest 和前端生产构建。

### Obsidian 剧情债务和人物弧线进入叙事账本

- 修改摘要：目标章节可见的 Obsidian 剧情债务和人物弧线正式笔记现在会进入叙事状态账本；识别 `type: narrative_debt / plot_debt / character_arc / character_state`、`Debts/`、`PlotDebts/`、`CharacterArcs/`、`剧情债务/`、`人物弧线/` 和相关标签。章节生成前会把这些 Vault 笔记作为上下文约束，章节保存后会写入 `.gaoxia/learning/narrative_state.json` 的 `obsidian_debt` 或 `obsidian_arc` 来源。
- 影响范围：`project_narrative_state_service` 的 Obsidian 笔记识别、叙事账本提示、章节保存后的债务 / 人物弧线维护、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明和记忆系统说明；不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_narrative_state_prompt_imports_obsidian_debt_and_arc_notes backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_saved_chapter_persists_obsidian_debt_and_arc_notes -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service -v` 通过，45 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，26 个用例；`npm run verify` 通过，包含 275 个后端 unittest 和前端生产构建。

### Obsidian 章节计划进入叙事账本和章节合同

- 修改摘要：目标章节可见的 Obsidian 章节计划、场景卡和章节合同笔记现在会进入叙事状态账本提示，并写入模型叙事编辑的下一章合同输入；识别 `type: chapter_plan / scene_plan / chapter_contract`、`Plans/`、`Scenes/`、`章节计划/`、`场景卡/` 和相关标签，且只接受明确绑定目标章节或窄范围章节的计划，避免后段章节计划进入早期章节。
- 影响范围：`project_narrative_state_service` 的 Obsidian 章节计划识别、叙事账本提示、模型叙事编辑输入、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明和记忆系统说明；不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_narrative_state_prompt_includes_obsidian_chapter_plan_notes backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_model_editor_receives_obsidian_guidance_for_next_chapter -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service -v` 通过，43 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，26 个用例；`npm run verify` 通过，包含 273 个后端 unittest 和前端生产构建。

### Obsidian 文风 / XP 笔记进入章节提示

- 修改摘要：项目级文风 / XP 提示现在会读取目标章节可见的 Obsidian 写作规则；`type: style_rule / xp_rule`、`Style/`、`XP/`、`文风/`、`写作规则/` 路径和相关标签会被识别，生成、改稿、诊断、Agent 自动续写和 Studio 章节流程都会传入目标章节。
- 影响范围：`project_style_xp_evolution_service`、`context_builder`、`generation_service`、`agent_service`、`studio_service`、上下文构建单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明和记忆系统说明；不改变 `.gaoxia/learning/style_xp_evolution.json` 结构，也不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_style_xp_evolution_service.py backend/novel_backend/services/context_builder.py backend/novel_backend/services/generation_service.py backend/novel_backend/services/agent_service.py backend/novel_backend/services/studio_service.py backend/tests/test_context_builder.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder.ContextBuilderTestCase.test_prompt_support_reads_chapter_safe_obsidian_style_xp_notes -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder -v` 通过，18 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_style_xp_evolution_service -v` 通过，1 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，26 个用例；`npm run verify` 通过，包含 272 个后端 unittest 和前端生产构建。

### Obsidian 剧透边界笔记排序

- 修改摘要：Obsidian 笔记选择现在会把 `reveal_after_chapter`、`#剧透/57` 和 `#第57章后可用` 这类剧透边界作为章节相关性信号；目标章节开放后，即使笔记没有显式 `chapter_range`，章节档案和后段设定也会优先于普通全局资料进入上下文选择。
- 影响范围：`obsidian_service` 的章节相关性评分、Obsidian 章节安全笔记选择、章节档案和后段设定进入后续章节上下文的排序、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_reveal_after_notes_rank_for_unlocked_chapters -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，26 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service -v` 通过，42 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder -v` 通过，17 个用例；`npm run verify` 通过，包含 271 个后端 unittest 和前端生产构建。

### Obsidian 待审草稿标签范围过滤

- 修改摘要：章节生成提示现在会读取项目 `.gaoxia/obsidian_drafts/` 中真实待审草稿的 frontmatter；作者手工加入 `tags: [第58章起, 剧透/57]`、`tags: [Ch58+]`，或保留系统生成的多行 `tags:` 列表时，会按正式 Obsidian 笔记相同的标签章节范围和剧透边界过滤待审草稿提醒，早期章节不会看到范围外草稿。
- 影响范围：`project_narrative_state_service` 的待审草稿 frontmatter 解析、Obsidian 维护建议进入章节生成提示的范围过滤、相关 backend 单测、README、项目 Agent 指令、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_pending_obsidian_draft_prompt_respects_manual_frontmatter_scope -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service -v` 通过，42 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，25 个用例；`npm run verify` 通过，包含 270 个后端 unittest 和前端生产构建。

### Obsidian 开放式章节范围

- 修改摘要：Obsidian 章节范围现在支持开放式写法；`chapter_range: 58+`、`chapter_range:: 第59章以后`、`tags: [第58章起]`、`tags: [Ch58+]` 会记录为起始章节且不写截止章节，早于起始章节不可见，起始章节和后续章节可继续引用；`#第58章` 仍保持单章绑定。
- 影响范围：`obsidian_service` 的章节范围解析、标签式章节范围解析、正文内联章节范围解析、Obsidian 章节安全检索排序、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_infers_chapter_scope_from_note_and_canvas_paths -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，25 个用例；`npm run verify` 通过，包含 270 个后端 unittest 和前端生产构建。

### Obsidian 关系字段 Markdown 内链解析

- 修改摘要：Obsidian `source_notes / related_characters / depends_on / foreshadows` 等关系字段现在支持 Markdown 内链；`source_notes: "[当前线索](Clues/当前线索.md)"`、`related_characters:: [林追](../Characters/林追.md)` 会按当前笔记路径解析相对链接，并生成关系语义、可解析链接和反向链接。
- 影响范围：`obsidian_service` 的 frontmatter 与正文内联关系字段解析、Obsidian 图谱关系、可解析链接、反向链接、章节上下文关系语义、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_extracts_frontmatter_relationship_links -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，25 个用例；`npm run verify` 通过，包含 270 个后端 unittest 和前端生产构建。

### Obsidian 空格分隔标签解析

- 修改摘要：Obsidian `tags` / `tag` / `标签` 属性现在支持空格分隔写法；`tags: "#人物 #第58章 #剧透/57"`、`tags: 人物 主角` 和 `tags:: #支线 #第59章` 会拆成单个标签，前导 `#` 会去掉后参与标签展示、章节范围、剧透边界、检索预览和章节上下文过滤。别名、关键词、必写 / 禁写短语仍按原字段规则解析，不会因为空格被误拆。
- 影响范围：`obsidian_service` 的 frontmatter 与正文内联标签解析、Obsidian 标签展示、章节范围和剧透边界识别、章节安全检索、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_infers_chapter_scope_from_note_and_canvas_paths -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，25 个用例；`npm run verify` 通过，包含 270 个后端 unittest 和前端生产构建。

### Obsidian 隐藏 Callout 隔离

- 修改摘要：Obsidian Markdown 和 Canvas 文本里的隐藏 callout 会从 AI 可见正文中排除；`spoiler / future / private / hidden / draft / todo / no-ai` 和 `剧透 / 未来 / 隐藏 / 私密 / 草稿 / 待定 / 勿用 / 不引用` 类型里的双链、标签、正文内联属性、关系字段、必写项和剧透词不会进入图谱关系、检索预览、章节上下文或反向链接；同一引用块内后续普通 callout 仍隐藏，结束引用块后重新开始的普通 `note / info` callout 仍按正文解析。
- 影响范围：`obsidian_service` 的 AI 可见正文清理、Markdown 与 Canvas 知识同步、Obsidian 图谱关系、必写 / 禁写约束、检索预览、章节安全内容、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_hidden_callouts_do_not_feed_ai_context_and_graph -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，25 个用例；`npm run verify` 通过，包含 270 个后端 unittest 和前端生产构建。

### Obsidian frontmatter 行尾注释隔离

- 修改摘要：Obsidian frontmatter 现在会忽略字段值后的 YAML 行尾注释；`status: canonical # 正式设定`、`chapter_range: 58-60 # 中段`、缩进列表项后的 `# 说明` 不会污染状态过滤、章节范围、图谱关系、反向链接或写作约束，引号里的 `#` 和双链 heading 仍会保留。
- 影响范围：`obsidian_service` 的 frontmatter 标量、数组、列表项解析，Obsidian 状态过滤、标题、别名、章节范围、来源关系、必写 / 禁写约束、章节安全检索、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_frontmatter_inline_comments_do_not_pollute_values -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，24 个用例；`npm run verify` 通过，包含 269 个后端 unittest 和前端生产构建。

### Obsidian 多行 Properties 解析

- 修改摘要：Obsidian frontmatter 现在支持 YAML block scalar；`summary: >`、`description: |` 这类多行摘要会进入知识索引、笔记选择和章节安全预览，多行 `keywords / source_notes / required_phrases` 等列表型字段会按行进入检索词、图谱关系、反向链接和写作约束。
- 影响范围：`obsidian_service` 的 frontmatter 解析、Obsidian 摘要、关键词、来源关系、必写项、章节安全预览、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_frontmatter_block_scalars_feed_summary_terms_and_links -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，23 个用例；`npm run verify` 通过，包含 268 个后端 unittest 和前端生产构建。

### Obsidian Properties 数组逗号解析

- 修改摘要：Obsidian frontmatter 的 YAML flow sequence 现在会保留引号里的逗号；`aliases: ["潮师, 守账人"]`、`keywords: ["旧船队, 暗账"]`、`required_phrases: ["潮声异常, 不得提前解释"]` 不会再被误拆成多条别名、检索词或写作约束，正文内联属性仍保留按逗号拆分多值的行为。
- 影响范围：`obsidian_service` 的 frontmatter 数组解析、Obsidian 摘要、别名、关键词、图谱关系、必写 / 禁写约束、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_frontmatter_flow_lists_keep_quoted_commas_and_wiki_links -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，22 个用例；`npm run verify` 通过，包含 267 个后端 unittest 和前端生产构建。

### Obsidian 附件嵌入过滤

- 修改摘要：Obsidian `![[...]]` 嵌入会区分笔记和附件；Markdown / Canvas 笔记嵌入继续进入图谱关系、已解析链接和反向链接，图片、PDF、音频等附件嵌入以及 Markdown 图片会从 AI 可见正文、图谱关系、未解析链接、检索预览和章节上下文中排除。
- 影响范围：`obsidian_service` 的 wiki 嵌入解析、Markdown 与 Canvas 知识同步、图谱关系、未解析链接统计、检索预览、章节安全内容、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_ignores_attachment_embeds_but_keeps_note_embeds -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，21 个用例；`npm run verify` 通过，包含 266 个后端 unittest 和前端生产构建。

### Obsidian 注释和代码块隔离

- 修改摘要：Obsidian Markdown 和 Canvas 文本里的 `%%...%%` 注释与 fenced code block 会从 AI 可见正文中排除；隐藏区域里的双链、Markdown 内链、标签、正文内联属性、关系小节、必写 / 禁写和章节范围不会进入图谱、检索预览、证据正文或章节上下文。
- 影响范围：`obsidian_service` 的 AI 可见正文清理、Markdown 与 Canvas 知识同步、Obsidian 图谱关系、检索预览、章节安全内容、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_ignores_comments_and_code_blocks_for_ai_context_and_graph -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，20 个用例；`npm run verify` 通过，包含 265 个后端 unittest 和前端生产构建。

### Obsidian 正文关系小节解析

- 修改摘要：Obsidian Markdown 和 Canvas 文本里的 `## 来源笔记`、`## 相关人物`、`## 伏笔`、`## 兑现` 等关系小节列表，以及 `相关地点：[[旧码头]]` 这类关系行会参与同步；系统会把这些自然写法转成图谱关系、可解析链接和反向链接，并按目标章节隐藏未来关系目标。
- 影响范围：`obsidian_service` 的正文关系小节解析、Markdown 与 Canvas 知识同步、Obsidian 图谱关系、章节安全过滤、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_body_relationship_sections_drive_graph_links -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，19 个用例；`npm run verify` 通过，包含 264 个后端 unittest 和前端生产构建。

### Obsidian 正文内联属性解析

- 修改摘要：Obsidian Markdown 和 Canvas 正文里的 `summary:: / keywords:: / aliases:: / tags:: / status:: / usable_by_ai:: / source_notes:: / related_characters:: / chapter_range:: / reveal_after_chapter:: / required_phrases:: / forbidden_phrases::` 等内联属性会参与同步，也支持 Dataview 常见的 `[summary:: ...]`、`(chapter_range:: ...)` 段落内写法；摘要、检索词、关系字段、章节范围、剧透边界和必写 / 禁写项不再必须写进 frontmatter，降低作者维护 Vault 属性区的压力。
- 影响范围：`obsidian_service` 的正文内联属性和 Dataview 段落内属性解析、Markdown 与 Canvas 知识同步、Obsidian 图谱关系、章节安全过滤、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_dataview_inline_fields_inside_paragraphs_drive_metadata -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_inline_properties_drive_metadata_graph_and_scope -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_canvas_file_nodes_enter_graph_and_stay_chapter_safe backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_inline_properties_drive_metadata_graph_and_scope -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，18 个用例；`npm run verify` 通过，包含 263 个后端 unittest 和前端生产构建。

### Obsidian 常见章节标签识别

- 修改摘要：Obsidian Markdown 和 Canvas 笔记的标签章节识别新增 `#第58章`、`#第58-60章`、`#Ch58-60` 和 `#第57章后可用` 这类常见写法；作者不写 frontmatter 章节字段时，系统也能按标签把笔记限制在目标章节或剧透边界之后，降低长篇项目维护 Vault 属性的压力。
- 影响范围：`obsidian_service` 的标签章节范围解析、Obsidian 知识检索和章节安全过滤、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明和技能流程回归清单；不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_infers_chapter_scope_from_note_and_canvas_paths -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过；`npm run verify` 通过，包含 261 个后端 unittest 和前端生产构建。

### Obsidian 已发布 Vault 笔记移动识别

- 修改摘要：发布过的 Obsidian 维护笔记被作者在 Vault 内移动或改名后，如果当前 Vault 中只有一份笔记与旧发布内容签名完全一致，或新生成维护笔记里的 `gaoxia_maintenance_id` 唯一匹配，且发布到 Vault 前会恢复缺失的身份字段，叙事状态账本会追加新的发布动作并改到新的 Vault 路径，不再误报 Vault 笔记缺失，也不会引导作者重复发布同一条设定。若没有唯一匹配或文件被删除，仍保留 Vault 笔记缺失和重新发布流程。自学习面板可显示仍在维护列表中的已移动 Vault 路径，并在维护摘要里统计这类项。
- 影响范围：`project_narrative_state_service` 的维护动作刷新、Obsidian 已发布内容签名比对、维护笔记身份字段、维护摘要状态字段，`SkillLibraryPanel` 的维护状态筛选和摘要展示，相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 Vault 自动覆盖策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_publish_readds_missing_maintenance_identity_before_vault_write backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_moved_and_edited_published_obsidian_note_rebinds_by_identity backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_moved_and_edited_published_obsidian_note_keeps_missing_when_identity_is_duplicated backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_moved_published_obsidian_note_rebinds_vault_path_without_missing -v` 通过；`node --check scripts/verify-ui-smoke.mjs` 通过；`npm run verify` 通过，包含 261 个后端 unittest 和前端生产构建；`npm run verify:ui` 在沙箱内因 `listen EPERM: operation not permitted 127.0.0.1` 无法启动本地服务，授权本地端口监听后通过。

### Obsidian Vault 合并批量确认

- 修改摘要：自学习面板新增“确认当前 Vault 合并”批量入口，当前筛选结果里的 Vault 合并草稿在作者完成 Obsidian 正式笔记合并后，可一次记录为已确认。后端新增批量确认服务和 API，批量确认只记录已人工合并后的 Vault 当前内容，随后刷新 Obsidian 摘要、`knowledge.db` 和叙事状态账本。
- 影响范围：`project_narrative_state_service` 的批量确认动作、`project_service` 和项目 API 的批量确认入口、前端 API 封装、`SkillLibraryPanel` 的确认当前 Vault 合并按钮、UI smoke、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 Vault 自动覆盖策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/novel_backend/services/project_service.py backend/novel_backend/api/projects.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_confirm_obsidian_maintenance_merges_handles_visible_batch backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_published_chapter_note_reports_outdated_after_saved_chapter_changes -v` 通过；`node --check scripts/verify-ui-smoke.mjs` 通过；`node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` 通过；`npm run verify` 通过，包含 257 个后端 unittest 和前端生产构建；`npm run verify:ui` 在沙箱内因 `listen EPERM: operation not permitted 127.0.0.1` 无法启动本地服务，授权本地端口监听后通过。

### Obsidian Vault 合并确认

- 修改摘要：Vault 待更新维护项生成合并草稿时，会标出正式 Vault 笔记路径和系统建议路径；作者在 Obsidian 完成正式笔记合并后，可在自学习面板点击“确认 Vault 已合并”，系统记录当前 Vault 内容、刷新 Obsidian 摘要和知识库，并关闭对应维护项。Vault 正式笔记仍不被系统自动覆盖。
- 影响范围：`project_narrative_state_service` 的合并草稿生成和合并确认动作、`project_service` 和项目 API 的确认入口、前端 API 封装、`SkillLibraryPanel` 的确认按钮、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/novel_backend/services/project_service.py backend/novel_backend/api/projects.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_published_chapter_note_reports_outdated_after_saved_chapter_changes backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_published_generated_obsidian_note_reports_outdated_without_flagging_manual_vault_edits -v` 通过；`node --check scripts/verify-ui-smoke.mjs` 通过；`node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` 通过；`npm run verify` 通过，包含 256 个后端 unittest 和前端生产构建；`npm run verify:ui` 在沙箱内因 `listen EPERM: operation not permitted 127.0.0.1` 无法启动本地服务，授权本地端口监听后通过。

### Obsidian Vault 待更新合并草稿

- 修改摘要：Vault 待更新维护项保存新版草稿时，会在项目 `.gaoxia/obsidian_drafts/_updates/` 生成合并草稿，内容包含当前 Vault 正文和系统新版草稿，帮助作者对照处理章节档案、图谱笔记等过期正式笔记。系统仍不覆盖 Vault 既有笔记，带合并草稿的维护项不会进入批量发布。
- 影响范围：`project_narrative_state_service` 的保存草稿流程和维护建议状态字段、前端自学习面板的合并草稿展示与发布禁用、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_published_chapter_note_reports_outdated_after_saved_chapter_changes backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_published_generated_obsidian_note_reports_outdated_without_flagging_manual_vault_edits -v` 通过；`node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` 通过；`npm run verify` 通过，包含 256 个后端 unittest 和前端生产构建；`npm run verify:ui` 在沙箱内因 `listen EPERM: operation not permitted 127.0.0.1` 失败，授权本地端口监听后通过。

### Obsidian 维护建议批量恢复

- 修改摘要：新增 Obsidian 维护建议批量恢复能力，自学习面板可以把当前筛选结果里的已忽略建议一次恢复为待处理。批量恢复只处理已忽略项，跳过其它状态，不删除项目草稿或 Vault 笔记；恢复后同路径建议重新进入待处理和自动草稿流程。
- 影响范围：`project_narrative_state_service` 的批量恢复动作、`project_service` 和项目 API 的批量恢复入口、前端 API 封装、`SkillLibraryPanel` 的恢复当前结果按钮、UI smoke、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/api/projects.py backend/novel_backend/services/project_service.py backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_reopen_obsidian_maintenance_notes_restores_visible_backlog backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_ignore_obsidian_maintenance_notes_hides_visible_backlog backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_reopened_obsidian_maintenance_reenters_auto_stage -v` 通过；`node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` 通过；`npm run verify` 通过，包含 256 个后端 unittest 和前端生产构建；`npm run verify:ui` 在沙箱内因 `listen EPERM: operation not permitted 127.0.0.1` 失败，授权本地端口监听后通过。

### Obsidian 维护建议批量忽略

- 修改摘要：新增 Obsidian 维护建议批量忽略能力，自学习面板可以把当前筛选结果里暂不处理的维护建议一次标为已忽略。批量忽略会跳过已发布和已忽略项，不删除项目草稿或 Vault 笔记，后续仍可单条恢复处理；同路径新建议继续继承忽略状态，减少长篇队列里的误报和低优先级干扰。
- 影响范围：`project_narrative_state_service` 的批量忽略动作、`project_service` 和项目 API 的批量忽略入口、前端 API 封装、`SkillLibraryPanel` 的忽略当前结果按钮、UI smoke、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/api/projects.py backend/novel_backend/services/project_service.py backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_ignore_obsidian_maintenance_notes_hides_visible_backlog backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_ignored_obsidian_maintenance_inherits_by_path_and_skips_auto_stage backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_reopened_obsidian_maintenance_reenters_auto_stage -v` 通过；`node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` 通过；`npm run verify` 通过，包含 255 个后端 unittest 和前端生产构建；`npm run verify:ui` 在沙箱内因 `listen EPERM: operation not permitted 127.0.0.1` 失败，授权本地端口监听后通过。

### Obsidian 维护草稿批量发布

- 修改摘要：新增 Obsidian 维护建议批量发布能力，自学习面板可以把当前筛选结果里已保存的草稿显式发布到 Vault。批量发布会跳过未保存、已发布、已忽略、草稿缺失和 Vault 待更新的维护项，继续检查目标路径在 Vault 内且不覆盖已有笔记；章节档案草稿的 `source_notes` 不再引用其它章节档案，避免批量发布后章节档案互相触发待更新。
- 影响范围：`project_narrative_state_service` 的批量发布动作和章节档案来源过滤、`project_service` 和项目 API 的批量发布入口、前端 API 封装、`SkillLibraryPanel` 的发布当前草稿到 Vault 按钮、UI smoke、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构，不改变自动覆盖策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/api/projects.py backend/novel_backend/services/project_service.py backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_stage_obsidian_maintenance_drafts_saves_visible_backlog backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_publish_obsidian_maintenance_notes_publishes_staged_drafts_to_vault backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_published_chapter_note_reports_outdated_after_saved_chapter_changes -v` 通过；`node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` 通过；`npm run verify` 通过，包含 254 个后端 unittest 和前端生产构建；`npm run verify:ui` 在沙箱内因 `listen EPERM: operation not permitted 127.0.0.1` 失败，授权本地端口监听后通过。

### Obsidian 维护草稿批量保存

- 修改摘要：新增 Obsidian 维护建议批量保存能力，自学习面板可以把当前筛选结果里的维护建议一次保存为项目 `.gaoxia/obsidian_drafts/` 待审草稿。批量保存会跳过已发布、已忽略、已保存且未缺失的草稿，不自动写入 Vault；正式发布仍需作者显式操作。
- 影响范围：`project_narrative_state_service` 的批量保存动作、`project_service` 和项目 API 的批量保存入口、前端 API 封装、`SkillLibraryPanel` 的保存当前结果草稿按钮、UI smoke、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 Vault 自动写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/api/projects.py backend/novel_backend/services/project_service.py backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_stage_obsidian_maintenance_drafts_saves_visible_backlog -v` 通过；`node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` 通过；`npm run verify` 通过，包含 253 个后端 unittest 和前端生产构建；`npm run verify:ui` 授权本地端口监听后通过。

### Obsidian 长篇维护队列

- 修改摘要：Obsidian 维护队列改为按 80 章长篇规模保留章节档案建议和操作记录，章节很多时早期已保存章节也会继续出现在待审清单里。自动保存待审草稿的单次数量提高，自学习面板会展示完整维护列表，并支持按状态筛选和按标题、路径、章节或动作搜索。
- 影响范围：`project_narrative_state_service` 的维护建议上限、章节档案建议上限、自动草稿数量和维护动作历史保留；`SkillLibraryPanel` 的 Obsidian 维护建议展示、筛选和搜索；相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 Vault 自动写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_obsidian_chapter_note_backlog_keeps_many_saved_chapters_visible -v` 通过；`node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` 通过；`npm run verify` 通过，包含 252 个后端 unittest 和前端生产构建；`npm run verify:ui` 在沙箱内因 `listen EPERM: operation not permitted 127.0.0.1` 失败，授权本地端口监听后通过。

### Obsidian 章节档案来源正文签名

- 修改摘要：系统生成的 `ChapterNotes/` 章节档案会写入 `source_chapter_hash`，同步 Obsidian 时会把该签名读入章节档案摘要。章节正文或标题变化后，即使本地维护动作记录缺失，只要 Vault 里的章节档案仍带旧签名，叙事状态账本也会重新生成待审草稿并显示 Vault 待更新；同章节已发布档案不会被列回本章来源笔记。
- 影响范围：`ObsidianNoteSummary`、Obsidian frontmatter 解析、章节档案草稿生成、已发布章节档案陈旧判断、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 Vault 自动写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/models.py backend/novel_backend/services/obsidian_service.py backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_generated_chapter_note_hash_detects_outdated_vault_note_without_action backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_published_chapter_note_reports_outdated_after_saved_chapter_changes backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_saved_chapter_generates_obsidian_chapter_note_draft_visible_to_later_chapters -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service backend.tests.test_project_narrative_state_service -v` 通过，共 48 个用例；`npm run verify` 通过，包含 251 个后端 unittest 和前端生产构建。

### Obsidian 已发布章节档案待更新

- 修改摘要：自动发布过的 `ChapterNotes/` 章节档案在章节正文或标题变化后，会重新进入维护建议并显示 Vault 待更新，提示作者保存新版草稿后合并到已发布笔记。章节档案草稿生成时会排除同章节已发布档案，避免章节档案把自己列为来源笔记并刚发布就误判为待更新。
- 影响范围：`project_narrative_state_service` 的章节档案维护建议、已发布 Obsidian 笔记待更新判断、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 Vault 自动写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_published_chapter_note_reports_outdated_after_saved_chapter_changes -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service backend.tests.test_project_narrative_state_service -v` 通过，共 47 个用例；`npm run verify` 通过，包含 250 个后端 unittest 和前端生产构建。

### Obsidian 自动章节档案草稿刷新保护

- 修改摘要：自动生成的 `ChapterNotes/` 章节档案草稿会在章节正文变化后刷新；如果章节标题变化，系统会把未人工改动的自动草稿迁移到新的章节档案文件名，并移除旧自动草稿。作者已经编辑过的章节档案草稿保留原文件和人工状态，不会被自动覆盖。
- 影响范围：`project_narrative_state_service` 的 Obsidian 自动草稿刷新逻辑、章节档案待审草稿、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 Vault 自动写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_auto_staged_chapter_note_draft_updates_when_saved_chapter_changes backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_auto_staged_chapter_note_draft_preserves_manual_edits -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service backend.tests.test_project_narrative_state_service -v` 通过，共 46 个用例；`npm run verify` 通过，包含 249 个后端 unittest 和前端生产构建。

## 2026-05-28

### Obsidian 自动章节档案草稿

- 修改摘要：章节保存后，启用 Obsidian 的作品会检查已保存章节是否已有可用章节档案；缺失时自动生成 `ChapterNotes/第XXX章-标题.md` 待审草稿。草稿包含章节摘要、来源章节、相关人物、本章命中的 Vault 来源笔记、正文里命中的地点 / 道具 / 组织、Obsidian 执行状态和正文摘录，frontmatter 使用 `type: chapter_note`、`source_chapters`、`source_notes`、`related_locations / related_props / related_organizations` 和 `reveal_after_chapter`，发布到 Vault 后会重新同步为正式 Obsidian 笔记，并只在可见章节范围内参与后续检索、上下文和图谱关系。
- 影响范围：`project_narrative_state_service` 的 Obsidian 维护建议、章节档案待审草稿、Obsidian 发布后的章节可见性、`obsidian_service` 文件路径章节推断优先级、相关 backend 单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 Vault 自动写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_obsidian_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_infers_chapter_scope_from_note_and_canvas_paths -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_saved_chapter_generates_obsidian_chapter_note_draft_visible_to_later_chapters -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service backend.tests.test_project_narrative_state_service -v` 通过，共 44 个用例；`npm run verify` 通过，包含 247 个后端 unittest 和前端生产构建。新增章节档案地点 / 道具 / 组织图谱关系后，`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_saved_chapter_generates_obsidian_chapter_note_draft_visible_to_later_chapters -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service backend.tests.test_project_narrative_state_service -v` 通过，共 44 个用例。新增章节档案 `source_notes` 来源笔记关系后，`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_saved_chapter_generates_obsidian_chapter_note_draft_visible_to_later_chapters -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service backend.tests.test_project_narrative_state_service -v` 通过，共 44 个用例。

### Obsidian 按文件名和路径推断章节范围

- 修改摘要：Obsidian Markdown 和 Canvas 同步会从文件名或路径识别章节范围，例如 `第58章-线索.md`、`第59-60章-后续.md`、`Chapters/58/设定.md`、`chapter-61.canvas`。没有 frontmatter 或正文“适用章节”标注时，系统也会按推断出的章节范围过滤早期章节上下文、知识检索和证据正文。
- 影响范围：`obsidian_service` 的章节范围解析、Markdown / Canvas 章节安全内容、知识检索和证据过滤、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_infers_chapter_scope_from_note_and_canvas_paths -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，共 16 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service backend.tests.test_context_builder -v` 通过，共 33 个用例；`npm run verify` 通过，包含 246 个后端 unittest 和前端生产构建。

### Obsidian Canvas 进入章节安全图谱

- 修改摘要：Obsidian 默认同步范围新增 `**/*.canvas`。Canvas file 节点会进入可解析链接和反向链接，Canvas 边会进入图谱关系；Canvas 文本节点里的章节范围、剧透边界、必写和禁写短语会参与章节上下文。按目标章节生成安全内容时，指向未来笔记的 Canvas file 节点和边会隐藏，避免关系图提前暴露后段设定。
- 影响范围：`ObsidianVaultConfig.include_patterns` 默认值、技能库 Obsidian 表单默认路径规则、`obsidian_service` 的 Canvas 解析与章节安全内容、知识检索和证据过滤、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/models.py backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_canvas_file_nodes_enter_graph_and_stay_chapter_safe -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，共 15 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service backend.tests.test_context_builder -v` 通过，共 32 个用例；`npm run verify` 通过，包含 245 个后端 unittest 和前端生产构建。

### Obsidian Markdown 内链进入章节安全图谱

- 修改摘要：Obsidian 同步现在会解析正文里的 Markdown 内链，例如 `[潮声异常](未来真相.md)`，并把它们纳入已解析链接和反向链接。按目标章节构建上下文、检索预览和证据正文时，指向未来笔记的 Markdown 内链会按章节安全内容隐藏；如果作者写了安全替代表达，会保留替代表达，不再把后段笔记路径或同名标题交给早期章节写作模型。
- 影响范围：`obsidian_service` 的 Markdown 内链解析、章节安全内容改写、图谱 backlinks、知识检索和证据过滤；`context_builder` 的章节上下文回归；README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_markdown_internal_links_are_graph_safe_by_chapter -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder.ContextBuilderTestCase.test_project_context_bundle_filters_obsidian_notes_by_chapter_scope -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service backend.tests.test_context_builder -v` 通过，共 31 个用例；`npm run verify` 通过，包含 244 个后端 unittest 和前端生产构建。

### Obsidian 摘要和关键词进入章节安全检索

- 修改摘要：Obsidian 同步会读取 `summary / description / abstract / keywords / search_terms / 关键词` 等常见 Properties。摘要和关键词会进入 `ObsidianNoteSummary`、知识索引、章节上下文选择、Agent 资料分析和章节安全预览；摘要里的未来 `[[双链]]` 会按目标章节改写为“未开放设定”，避免早期章节通过摘要预览看到后段笔记标题。
- 影响范围：`ObsidianNoteSummary` 数据结构、Obsidian Markdown 同步、知识检索、章节安全笔记内容、Agent 资料分析的 Obsidian 笔记选择、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 Vault 写入策略，不改变现有 API 路径。
- 验证结果：`python3 -m py_compile backend/novel_backend/models.py backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_summary_and_keywords_are_searchable_and_chapter_safe -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，共 13 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder -v` 通过，共 17 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_agent_service.AgentServiceTestCase.test_knowledge_review_filters_obsidian_notes_for_target_chapter backend.tests.test_agent_service.AgentServiceTestCase.test_model_planner_hides_future_obsidian_suggestions_for_chapter_task -v` 通过；`npm run verify` 通过，包含 243 个后端 unittest 和前端生产构建。

### Agent 规划上下文按目标章节过滤 Obsidian 维护建议

- 修改摘要：Agent 路由和模型规划读取自学习能力上下文时，会把当前请求的目标章节传给 Obsidian 维护建议过滤器。明示第 N 章、下一章或当前选中章节时，只给模型对应章节可见的建议明细；没有明确目标章节的非架构任务只保留维护摘要，不暴露后段建议标题、路径或动作；整书架构和后续规划任务保持全书视角。图谱、剧情债务和人物维护建议同步记录来源章节，带草稿的建议继续按草稿 frontmatter 的章节范围和剧透边界判断可见性；Agent 计划步骤里的资料分析数量也会按目标章节统计，不把后段 Obsidian 笔记计入早期章节资料规模；用户同时提到参考章节和生成章节时，能力上下文会优先跟随生成 / 改稿 / 拆场 / 诊断等动作目标章节，不再简单使用句子里第一个章节号。
- 影响范围：`agent_service` 的路由 / 规划能力上下文、`self_evolution_service` 的 Obsidian 建议筛选、`project_narrative_state_service` 的维护建议章节可见性判断、Agent 和叙事状态回归测试、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构，不改变前端接口参数。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/novel_backend/services/self_evolution_service.py backend/novel_backend/services/agent_service.py backend/tests/test_project_narrative_state_service.py backend/tests/test_agent_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_graph_maintenance_draft_uses_spoiler_boundary_for_disjoint_source_scopes -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_agent_service.AgentServiceTestCase.test_model_planner_hides_future_obsidian_suggestions_for_chapter_task -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_agent_service.AgentServiceTestCase.test_model_planner_review_step_counts_only_target_chapter_obsidian_notes -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_agent_service.AgentServiceTestCase.test_model_planner_capability_scope_prefers_generation_target_chapter -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_agent_service -v` 通过，共 32 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_agent_service backend.tests.test_project_narrative_state_service backend.tests.test_self_evolution_service -v` 通过，共 65 个用例；`npm run verify` 通过，包含 242 个后端 unittest 和前端生产构建；`git diff --check` 通过；文档相对日期检查无命中。

### 章节写作关闭模型总览和蒸馏旁路

- 修改摘要：章节生成、改稿、诊断上下文和项目级文风 / XP 提示读取项目详情时会关闭模型版故事总览缓存；项目记忆自动条目只从章节安全的本地文档和章节摘要生成，不再从模型总览里的全书实体反写。续写、改稿、仿写和人物任务的项目蒸馏包不会从模型总览实体生成；没有目标章节时也不会默认带入 Obsidian 后段笔记。架构总览和整书架构蒸馏仍可读取全书资料。
- 影响范围：`project_service` 的模型总览缓存读取开关和蒸馏来源选择、`project_distillation_service` 的章节安全签名与任务包资料过滤、`context_builder` 的章节上下文和文风 / XP 提示、章节续写检索查询、Obsidian 章节范围回归测试、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变前端接口参数。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_service.py backend/novel_backend/services/project_distillation_service.py backend/novel_backend/services/context_builder.py backend/novel_backend/services/generation_service.py backend/tests/test_context_builder.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder.ContextBuilderTestCase.test_project_context_bundle_ignores_model_overview_cache_for_chapter_scope -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder -v` 通过，共 17 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_service.ProjectServiceTestCase.test_story_overview_uses_validated_model_cache_for_all_sections -v` 通过；`git diff --check` 通过；`npm run verify` 通过，包含 239 个后端 unittest 和前端生产构建。

### 章节上下文知识检索继承目标章节

- 修改摘要：章节生成、改稿和诊断上下文里的项目知识检索会把目标章节传给后端。后端会先扩大候选池，再按 Obsidian 章节范围过滤；当大量后段笔记命中同一关键词时，当前章节可见笔记仍能进入写作上下文。
- 影响范围：`context_builder` 的知识检索调用、Obsidian 章节范围回归测试、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变前端接口参数。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/context_builder.py backend/tests/test_context_builder.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder.ContextBuilderTestCase.test_project_context_bundle_passes_chapter_to_knowledge_search_before_filtering -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder -v` 通过，共 16 个用例；`npm run verify` 通过，包含 238 个后端 unittest 和前端生产构建。

### 联网考据继承选中章节边界

- 修改摘要：技能库执行联网考据时会把当前选中章节传给后端；后端本地资料预查会按目标章节过滤 Obsidian 命中，并在阿里百炼 / 博查整理提示里标明目标章节，避免早期章节考据结果引用后段专用笔记。
- 影响范围：联网考据接口、`web_research_service`、技能库前端调用、相关后端单测、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/web_research_service.py backend/novel_backend/api/projects.py backend/tests/test_web_research_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_web_research_service -v` 通过，共 4 个用例；`npm run verify` 通过，包含 237 个后端 unittest 和前端生产构建；`npm run verify:ui` 在沙箱内因 `listen EPERM: operation not permitted 127.0.0.1` 失败，授权本地端口监听后通过；`git diff --check` 通过；文档相对时间检查无命中。

### Obsidian 章节检索扩大候选池

- 修改摘要：目标章节存在时，知识检索和连续性证据检索会先读取更大的候选池，再按 Obsidian 章节范围过滤并返回请求数量。大 Vault 中如果很多后段笔记命中同一关键词，早期章节仍能拿到当前章节可见的笔记，不会因为前几条结果全被过滤而显示为空。
- 影响范围：`project_service` 的知识检索和证据检索、Obsidian 章节范围回归测试、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 `knowledge.db` 表结构，不改变前端接口参数。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_extracts_chapter_scope_and_filters_by_target_chapter -v` 首次失败并暴露证据检索内部 20 条截断，修正后通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，共 12 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_service.ProjectServiceTestCase.test_search_project_knowledge_returns_documents_and_chapters backend.tests.test_project_service.ProjectServiceTestCase.test_search_project_knowledge_supports_semantic_ranking backend.tests.test_context_builder.ContextBuilderTestCase.test_project_context_bundle_drops_unmatched_obsidian_knowledge_hits_for_target_chapter -v` 通过，共 3 个用例；`npm run verify` 通过，包含 237 个后端 unittest 和前端生产构建。

### Obsidian 知识检索按选中章节过滤

- 修改摘要：`/api/projects/{project_id}/knowledge/search` 新增 `chapter_index` 参数；技能库和架构总览执行知识检索时会传入当前选中章节。命中的 Obsidian 结果会按该章节重新读取安全内容，未来章节专用笔记会被过滤，当前可见笔记正文里的未来 `[[双链]]` 和关系预览不会进入界面检索结果。
- 影响范围：项目知识检索接口、`project_service` 的 Obsidian 检索结果过滤、技能库检索、架构总览检索、Obsidian 章节范围回归测试、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 `knowledge.db` 表结构，不改变 Vault 写入策略。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_service.py backend/novel_backend/api/projects.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_extracts_chapter_scope_and_filters_by_target_chapter -v` 通过；`npm run verify` 通过，包含 237 个后端 unittest 和前端生产构建；`npm run verify:ui` 在沙箱内首次因 `listen EPERM: operation not permitted 127.0.0.1` 失败，授权本地端口监听后通过。

### Obsidian 章节安全内容覆盖正文双链

- 修改摘要：按目标章节读取 Obsidian 笔记时，系统会重新生成章节安全内容。当前章节可见笔记如果在正文 `[[双链]]` 或 frontmatter 关系里指向未来章节笔记，章节上下文、Agent 资料分析、任务蒸馏、连续性证据正文和章节核验都会隐藏该未来目标；真正未解析或歧义的双链仍会作为图谱风险提示保留，方便作者维护 Vault。
- 影响范围：`obsidian_service` 的章节化笔记内容生成、`context_builder` 的 Obsidian 笔记来源、`project_distillation_service` 的任务蒸馏资料、`project_narrative_state_service` 的章节任务卡、`chapter_review_service` 的 Obsidian 核验、相关后端测试、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/novel_backend/services/context_builder.py backend/novel_backend/services/project_distillation_service.py backend/novel_backend/services/project_narrative_state_service.py backend/novel_backend/services/chapter_review_service.py backend/tests/test_obsidian_service.py backend/tests/test_context_builder.py backend/tests/test_agent_service.py backend/tests/test_project_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_extracts_chapter_scope_and_filters_by_target_chapter backend.tests.test_context_builder.ContextBuilderTestCase.test_project_context_bundle_filters_obsidian_notes_by_chapter_scope backend.tests.test_project_service.ProjectServiceTestCase.test_task_distillation_prompt_filters_obsidian_summary_by_chapter_scope backend.tests.test_agent_service.AgentServiceTestCase.test_knowledge_review_filters_obsidian_notes_for_target_chapter -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service backend.tests.test_context_builder backend.tests.test_project_narrative_state_service -v` 通过，共 54 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_service.ProjectServiceTestCase.test_task_distillation_prompt_filters_obsidian_summary_by_chapter_scope backend.tests.test_agent_service.AgentServiceTestCase.test_knowledge_review_filters_obsidian_notes_for_target_chapter backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_checks_obsidian_forbidden_phrases_and_staleness backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_staleness_ignores_future_scoped_obsidian_note backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_respects_obsidian_chapter_scope backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_checks_required_phrase_for_obsidian_evidence_hit backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_checks_required_phrase_for_chapter_scoped_obsidian_note backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_obsidian_evidence_prefers_source_key -v` 通过；`npm run verify` 通过，包含 237 个后端 unittest 和前端生产构建。

### Obsidian 关系语义按目标章节过滤

- 修改摘要：章节上下文里的 `graph_relations` 会按目标章节重新过滤。可见笔记如果用 `foreshadows`、`reveals` 等关系指向后段限定笔记，早期章节不会显示“伏笔 -> 未来真相”这类关系标题；指向当前章节可见笔记的关系仍会保留。
- 影响范围：`context_builder` 的 Obsidian 设定笔记和检查清单、章节上下文的关系语义显示、上下文构建回归测试、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/context_builder.py backend/tests/test_context_builder.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder -v` 通过，共 15 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_obsidian_service backend.tests.test_context_builder backend.tests.test_self_evolution_service -v` 通过，共 62 个用例；`npm run verify` 通过，包含 237 个后端 unittest 和前端生产构建；`git diff --check` 通过。

### Obsidian 图谱关系保留语义标签

- 修改摘要：Obsidian 同步不再只把 frontmatter 关系字段折成普通链接；系统会新增 `graph_relations` 摘要字段，把 `depends_on / foreshadows / payoffs / reveals / related_locations / related_props / related_organizations` 等 Properties 转成“依赖 -> 目标”“伏笔 -> 目标”“兑现 -> 目标”“相关地点 -> 目标”等关系语义，并写入知识索引、章节上下文和 Obsidian 面板预览。
- 影响范围：`ObsidianNoteSummary`、`obsidian_service` 的 frontmatter 关系解析、`context_builder` 的 Obsidian 设定笔记和检查清单、`StoryOverviewPanel`、`SkillLibraryPanel`、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/models.py backend/novel_backend/services/obsidian_service.py backend/novel_backend/services/context_builder.py backend/tests/test_obsidian_service.py backend/tests/test_context_builder.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service backend.tests.test_context_builder -v` 通过，共 27 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_obsidian_service backend.tests.test_context_builder backend.tests.test_self_evolution_service -v` 通过，共 62 个用例；`npm run verify` 通过，包含 237 个后端 unittest 和前端生产构建；`npm run verify:ui` 在沙箱内首次因 `listen EPERM: operation not permitted 127.0.0.1` 失败，授权本地端口监听后通过；`git diff --check` 通过；文档相对时间检查无命中。

### Obsidian 常见 Properties 进入图谱解析

- 修改摘要：Obsidian 同步会把 `depends_on / foreshadows / payoffs / reveals / related_locations / related_props / related_organizations / characters / locations / props / organizations` 以及对应中文字段作为图谱关系来源。作者在 Obsidian Properties 里维护前置笔记、伏笔、兑现、揭示、地点、道具和组织关系时，不需要额外在正文重复写双链，也能形成 `resolved_links` 和 `backlinks`。
- 影响范围：`obsidian_service` 的 frontmatter 关系解析、Obsidian 正式笔记同步、图谱统计、章节上下文的一跳关联、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，共 12 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_obsidian_service backend.tests.test_context_builder backend.tests.test_self_evolution_service -v` 通过，共 62 个用例；`npm run verify` 通过，包含 237 个后端 unittest 和前端生产构建；`git diff --check` 通过；文档相对时间检查无命中。

### Obsidian 陈旧检索命中章节过滤

- 修改摘要：章节上下文有目标章节时，来自 `knowledge.db` 的 Obsidian 检索命中必须能对应到当前架构总览里的可见笔记；找不到对应笔记的旧索引命中会被丢弃，避免 Vault 变更或旧索引把后段设定带入早期章节。
- 影响范围：`context_builder` 的 Obsidian 检索命中过滤、上下文构建回归测试、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/context_builder.py backend/tests/test_context_builder.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder.ContextBuilderTestCase.test_project_context_bundle_drops_unmatched_obsidian_knowledge_hits_for_target_chapter -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder -v` 通过，共 15 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_obsidian_service backend.tests.test_context_builder backend.tests.test_self_evolution_service -v` 通过，共 61 个用例；`npm run verify` 通过，包含 236 个后端 unittest 和前端生产构建；`git diff --check` 通过。

### Obsidian 已解析双链章节范围校验

- 修改摘要：Obsidian 同步会检查已解析双链的章节可见性。来源笔记可见范围没有被目标笔记章节范围或剧透边界覆盖时，系统会生成 `scope_mismatch` 图谱问题，并进入叙事状态账本的高优先级 Obsidian 维护建议和 Agent 规划上下文；全书可见来源链接后段限定目标也会被识别，避免早期章节通过全局笔记看到后段关系标题。自学习面板新增 Vault 待更新状态；自动发布过的维护笔记如果后续自动草稿变化，且 Vault 文件仍等于当初自动发布内容，会提示作者人工合并新版；作者手工改过的 Vault 内容不会被标记为待更新。
- 影响范围：`obsidian_service` 的图谱关系校验，`project_narrative_state_service` 的 Obsidian 维护建议、维护摘要和发布状态，`SkillLibraryPanel` 的维护摘要状态显示，README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 Vault 自动写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/models.py backend/novel_backend/services/obsidian_service.py backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_obsidian_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_sync_reports_chapter_scope_mismatch_for_resolved_links backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_sync_reports_scope_mismatch_when_global_source_links_scoped_target backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_narrative_state_reports_obsidian_scope_mismatch_as_graph_repair backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_published_generated_obsidian_note_reports_outdated_without_flagging_manual_vault_edits -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_obsidian_service backend.tests.test_context_builder backend.tests.test_self_evolution_service -v` 通过，共 60 个用例；`npm run verify` 通过，包含 235 个后端 unittest 和前端生产构建；`npm run verify:ui` 在沙箱内首次因 `listen EPERM: operation not permitted 127.0.0.1` 失败，授权本地端口监听后通过。

### Obsidian 孤立笔记不再混入未解析双链

- 修改摘要：Obsidian 图谱同步里的孤立笔记判定改为只统计没有正文双链、frontmatter 关系、已解析外链、未解析外链、歧义外链和反向链接的正式笔记。带未解析或歧义双链的笔记只进入对应图谱修复问题，不再额外计入孤立笔记，也不会生成重复的孤立索引维护建议。
- 影响范围：`obsidian_service` 的孤立笔记统计和结构化图谱问题，`project_narrative_state_service` 的 Obsidian 图谱维护建议，README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_sync_does_not_count_unresolved_links_as_orphans backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_narrative_state_turns_repeated_unresolved_obsidian_links_into_drafts -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_obsidian_service backend.tests.test_context_builder backend.tests.test_self_evolution_service -v` 通过，共 56 个用例；`npm run verify` 通过，包含 231 个后端 unittest 和前端生产构建；`git diff --check` 通过；文档相对时间检查无命中。

### Obsidian 自动 Graph 草稿刷新同来源内容变化

- 修改摘要：未人工改动的自动 Graph 待审草稿不再只在来源列表变化时更新；同一批来源笔记的正文、章节范围或剧透边界变化后，系统会刷新项目内 `.gaoxia/obsidian_drafts/` 中对应草稿，保留最新 `source_notes`、章节范围和剧透边界。人工改动过的草稿仍不会被自动覆盖。
- 影响范围：`project_narrative_state_service` 的 Obsidian 自动草稿刷新逻辑、孤立笔记 Graph 索引草稿、未解析双链 Graph 草稿，README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_auto_staged_orphan_graph_index_updates_when_source_scope_changes -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_obsidian_service backend.tests.test_context_builder backend.tests.test_self_evolution_service -v` 通过，共 55 个用例；`npm run verify` 通过，包含 230 个后端 unittest 和前端生产构建；`git diff --check` 通过；文档相对时间检查无命中。

### Obsidian 孤立笔记生成来源区分的 Graph 索引草稿

- 修改摘要：两篇以上没有外链和反向链接的正式 Obsidian 笔记会生成 `Graph/孤立笔记整理-{来源摘要}.md` 待审索引草稿。草稿会继承来源笔记章节范围或剧透边界，发布到 Vault 后通过 `source_notes` 和正文双链连接原笔记，让这些设定进入 backlinks 和后续图谱检索。路径按来源集合区分，旧索引发布后新增孤立笔记会生成新的待审草稿，不会继承旧索引的已发布状态。
- 影响范围：`project_narrative_state_service` 的 Obsidian 图谱维护建议、自动草稿保存、维护建议发布后的图谱关系解析，README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_orphan_obsidian_notes_generate_graph_index_draft -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_new_orphan_notes_after_published_graph_index_get_new_draft -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_obsidian_service backend.tests.test_context_builder backend.tests.test_self_evolution_service -v` 通过，共 54 个用例；`npm run verify` 通过，包含 229 个后端 unittest 和前端生产构建；`git diff --check` 通过；文档相对时间检查无命中。

### Obsidian 剧情债务草稿区分计划区间和可见范围

- 修改摘要：剧情债务维护草稿不再把预计处理区间写成 `chapter_range`，改写为 `expected_payoff_range`。`chapter_range` 保持只表示 Obsidian 笔记可见范围；发布到 Vault 后，来源章节之后、正式兑现之前的中间章节仍能读取这条债务笔记。
- 影响范围：`project_narrative_state_service` 的剧情债务草稿生成、维护建议发布后的 Obsidian 章节可见性，README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_published_plot_debt_note_visible_after_source_before_payoff -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_narrative_state_suggests_obsidian_notes_for_untracked_debts -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_obsidian_service backend.tests.test_context_builder backend.tests.test_self_evolution_service -v` 通过，共 52 个用例；`npm run verify` 通过，包含 227 个后端 unittest 和前端生产构建；`git diff --check` 通过；文档相对时间检查无命中。

### Obsidian 自动维护草稿按来源章节设置剧透边界

- 修改摘要：剧情债务和人物状态维护草稿会根据 `source_chapters` 自动写入 `reveal_after_chapter`。作者把这些草稿发布到 Vault 后，后段章节产生的自动维护笔记会继续按目标章节过滤，早期章节上下文不会提前读到这些后段资料。
- 影响范围：`project_narrative_state_service` 的剧情债务草稿、人物状态草稿、维护建议发布后的 Obsidian 可见性，README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_character_maintenance_draft_uses_source_chapter_boundary -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_obsidian_service backend.tests.test_context_builder backend.tests.test_self_evolution_service -v` 通过，共 51 个用例；`npm run verify` 通过，包含 226 个后端 unittest 和前端生产构建；`git diff --check` 通过；文档相对时间检查无命中。

### Obsidian frontmatter 关系字段进入图谱解析

- 修改摘要：Obsidian 同步会把 frontmatter 里的 `source_notes / related_characters / related_notes / links` 等字段作为图谱关系来源。发布到 Vault 的维护笔记即使正文没有重复写 `[[双链]]`，只在 frontmatter 里保留来源笔记或相关人物，也会形成 `resolved_links` 和 `backlinks`，进入章节上下文的一跳关联和图谱统计。
- 影响范围：`obsidian_service` 的正式笔记同步、图谱关系解析、知识索引内容，README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_extracts_frontmatter_relationship_links -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service backend.tests.test_context_builder backend.tests.test_project_narrative_state_service backend.tests.test_self_evolution_service -v` 通过，共 50 个用例；`npm run verify` 通过，包含 225 个后端 unittest 和前端生产构建。

### Obsidian 待审草稿字段名兼容常见属性写法

- 修改摘要：章节生成、改稿和诊断上下文过滤 `Obsidian 待审草稿` 时，项目内 `.gaoxia/obsidian_drafts/` 草稿 frontmatter 的字段名会按大小写、空格、连字符和下划线做归一化匹配。作者手工把草稿写成 `Reveal After Chapter: 57`、`Chapter-Range: 58-60` 等常见属性名时，早期章节不会看到范围外待审提醒，目标章节仍可看到。
- 影响范围：`project_narrative_state_service` 的待审草稿章节可见性、手工草稿 frontmatter 解析，README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变自动草稿保存策略，不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_pending_obsidian_draft_prompt_respects_manual_frontmatter_scope -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_obsidian_service backend.tests.test_context_builder backend.tests.test_self_evolution_service -v` 通过，共 49 个用例；`npm run verify` 通过，包含 224 个后端 unittest 和前端生产构建。

### Obsidian frontmatter 字段名兼容常见属性写法

- 修改摘要：Obsidian 同步解析 frontmatter 时，字段名会按大小写、空格、连字符和下划线做归一化匹配。作者在 Vault 中写 `Status`、`Usable By AI`、`Chapter-Range`、`Reveal After Chapter`、`Required Phrases`、`Forbidden-Phrases` 等常见属性名，也能识别状态、AI 可用标记、章节范围、剧透边界、必写项和禁写项，并继续按目标章节过滤知识检索证据。
- 影响范围：`obsidian_service` 的 frontmatter 字段读取、Obsidian 正式笔记同步、章节范围和写作约束解析，README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_obsidian_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_frontmatter_keys_accept_common_property_name_variants -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service backend.tests.test_context_builder backend.tests.test_project_narrative_state_service backend.tests.test_self_evolution_service -v` 通过，共 49 个用例；`npm run verify` 通过，包含 224 个后端 unittest 和前端生产构建。

### Obsidian 待审草稿尊重手工章节范围

- 修改摘要：章节生成、改稿和诊断上下文里的 `Obsidian 待审草稿` 提示会读取 `.gaoxia/obsidian_drafts/` 中真实草稿文件的 frontmatter。作者手工给待审草稿加入或调整 `chapter_range / chapter_start / chapter_end / reveal_after_chapter` 后，早期章节不会再看到范围外的待审提醒，后续章节仍可看到。
- 影响范围：`project_narrative_state_service` 的章节上下文提示生成、Obsidian 维护建议待审草稿的章节可见性，README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变自动草稿保存策略，不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_pending_obsidian_draft_prompt_respects_manual_frontmatter_scope` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_self_evolution_service backend.tests.test_obsidian_service backend.tests.test_context_builder -v` 通过，共 48 个用例；`npm run verify` 通过，包含 223 个后端 unittest 和前端生产构建。

### Obsidian 待审草稿提示按章节过滤

- 修改摘要：叙事状态账本里的 `Obsidian 待审草稿` 提示会读取草稿 frontmatter 的 `chapter_range / chapter_start / chapter_end / reveal_after_chapter`，只把目标章节可见的草稿写入章节生成、改稿和诊断上下文。未来章节专用的 Graph 待审草稿不会在早期章节提示里提前暴露标题和建议路径。
- 影响范围：`project_narrative_state_service` 的章节上下文提示生成、Obsidian 维护建议待审草稿的章节可见性，README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变自动草稿保存策略，不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_graph_maintenance_draft_uses_spoiler_boundary_for_disjoint_source_scopes -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_self_evolution_service backend.tests.test_obsidian_service backend.tests.test_context_builder -v` 通过，共 47 个用例；`npm run verify` 通过，包含 222 个后端 unittest 和前端生产构建。

### Obsidian Graph 不连续来源防剧透

- 修改摘要：未解析双链生成 `Graph/` 待审草稿时，如果来源 Obsidian 笔记的章节范围相隔很远，不再合成“第 1-60 章”这类过宽连续范围，而是改用较晚可见的 `reveal_after_chapter`。发布到 Vault 后，Graph 新笔记不会把后段来源提前带入早期章节上下文。
- 影响范围：`project_narrative_state_service` 的 Graph 维护草稿章节边界生成、Obsidian 维护建议发布后的章节可见性，README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_graph_maintenance_draft_inherits_source_chapter_scope backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_graph_maintenance_draft_uses_spoiler_boundary_for_disjoint_source_scopes -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_self_evolution_service backend.tests.test_obsidian_service backend.tests.test_context_builder -v` 通过，共 47 个用例；`npm run verify` 通过，包含 222 个后端 unittest 和前端生产构建。

### Obsidian Graph 草稿继承章节边界

- 修改摘要：未解析双链生成的 `Graph/` 待审草稿会继承来源 Obsidian 笔记的 `chapter_range / chapter_start / chapter_end / reveal_after_chapter`。作者发布草稿到 Vault 后，新 Graph 笔记继续按章节范围和剧透边界参与检索、上下文和章节核验，避免后段线索变成全书可见设定。
- 影响范围：`project_narrative_state_service` 的图谱维护草稿生成、Obsidian 维护建议发布后的知识库同步、章节上下文里的 Obsidian 可见性，README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_graph_maintenance_draft_inherits_source_chapter_scope -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_self_evolution_service backend.tests.test_obsidian_service backend.tests.test_context_builder -v` 通过，共 46 个用例；`node --check scripts/verify-ui-smoke.mjs` 通过；`npm run verify` 通过，包含 221 个后端 unittest 和前端生产构建；`git diff --check` 通过；文档相对时间检查无命中。

### Obsidian 维护建议支持恢复处理

- 修改摘要：Obsidian 维护建议新增恢复处理动作和后端 `reopen` 接口，作者误忽略或后续剧情需要重新处理时，可以把已忽略建议恢复为待处理。同一路径的新建议会在恢复后重新进入 Agent 优先处理和自动草稿流程；自学习面板对已忽略项显示恢复处理按钮。
- 影响范围：`project_narrative_state_service` 的维护动作状态、同路径状态继承和自动草稿判断，`project_service` 与项目 Obsidian API 新增恢复入口，技能库 `Agent 自学习` 面板，README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/novel_backend/services/project_service.py backend/novel_backend/api/projects.py backend/tests/test_project_narrative_state_service.py` 通过；`node --check scripts/verify-ui-smoke.mjs` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_reopened_obsidian_maintenance_reenters_auto_stage backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_ignored_obsidian_maintenance_inherits_by_path_and_skips_auto_stage -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_self_evolution_service backend.tests.test_obsidian_service backend.tests.test_context_builder -v` 通过，共 45 个用例；`npm run verify` 通过，包含 220 个后端 unittest 和前端生产构建；`git diff --check` 通过；文档相对时间检查无命中。

### Obsidian 维护建议支持忽略

- 修改摘要：Obsidian 维护建议新增 `ignored` 状态和后端忽略接口，作者可以把暂不处理的图谱或资料维护项移出 Agent 优先处理列表。同一路径的新建议会继承忽略状态，避免来源笔记变化后又自动生成草稿；维护摘要会统计已忽略数量，自学习面板新增忽略按钮和已忽略状态展示。
- 影响范围：`project_narrative_state_service` 的维护动作状态、同路径状态继承、自动草稿判断和维护摘要，`project_service` 与项目 Obsidian API 新增忽略入口，`self_evolution_service` 的 Agent 能力上下文，技能库 `Agent 自学习` 面板，README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/novel_backend/services/project_service.py backend/novel_backend/api/projects.py backend/novel_backend/services/self_evolution_service.py backend/tests/test_project_narrative_state_service.py` 通过；`node --check scripts/verify-ui-smoke.mjs` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_ignored_obsidian_maintenance_inherits_by_path_and_skips_auto_stage backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_obsidian_sync_refreshes_graph_maintenance_without_chapter_save backend.tests.test_self_evolution_service.SelfEvolutionServiceTestCase.test_capability_context_refreshes_obsidian_graph_maintenance_from_project_detail -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_self_evolution_service backend.tests.test_obsidian_service backend.tests.test_context_builder -v` 通过，共 44 个用例；`npm run verify` 通过，包含 219 个后端 unittest 和前端生产构建；`git diff --check` 通过；文档相对时间检查无命中。

### Obsidian 维护摘要进入 Agent 规划

- 修改摘要：叙事状态账本新增 `obsidian_maintenance_summary`，会把 Obsidian 维护建议聚合为总数、待处理数、高优先级数、自动草稿数、人工改动 / 保留草稿数、草稿缺失数、Vault 笔记缺失数和优先处理项。Agent 能力上下文会先写入维护摘要，再列维护建议；自学习面板也会显示维护摘要，让作者和 Agent 先看到资料维护压力，而不是只看零散建议列表。
- 影响范围：`project_narrative_state_service` 的维护建议状态聚合、`.gaoxia/learning/narrative_state.json` 新增 `obsidian_maintenance_summary` 字段、`self_evolution_service` 的 Agent 能力上下文、技能库 `Agent 自学习` 面板、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/novel_backend/services/self_evolution_service.py backend/tests/test_project_narrative_state_service.py backend/tests/test_self_evolution_service.py` 通过；`node --check scripts/verify-ui-smoke.mjs` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_narrative_state_suggests_obsidian_notes_for_untracked_debts backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_published_graph_maintenance_reports_missing_vault_note_and_can_publish_again backend.tests.test_self_evolution_service.SelfEvolutionServiceTestCase.test_capability_context_refreshes_obsidian_graph_maintenance_from_project_detail -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_self_evolution_service backend.tests.test_obsidian_service backend.tests.test_context_builder -v` 通过，共 43 个用例；`npm run build` 通过；`npm run verify` 通过，包含 218 个后端 unittest 和前端生产构建。

### Obsidian 草稿人工状态可见化

- 修改摘要：Obsidian 维护建议会把已保存草稿的 `draft_content_hash` 与当前草稿文件比对，识别作者是否改过 `.gaoxia/obsidian_drafts/` 下的待审 Markdown；保存草稿遇到同路径既有人工内容时，会在维护建议里标记 `preserved_existing_draft` 和 `manual_draft_edits`。同一路径的维护建议即使因来源变化产生新 ID，也会沿用已有草稿状态；未人工改动的自动草稿仍会随来源更新，人工改动过的草稿不会被覆盖；直接发布同路径新建议时会读取已有人工草稿。草稿文件被移动或删除时，维护建议会显示 `draft_missing`，自学习面板提示草稿缺失并允许重新保存。发布过的 Vault 笔记被移动或删除时，维护建议会显示 `published_missing`，自学习面板提示 Vault 笔记缺失并允许重新发布。自学习面板现在区分自动草稿、人工改动草稿、保留人工草稿、草稿缺失和 Vault 笔记缺失，并在保存草稿后提示是否保留了原文；章节生成上下文里的待审草稿状态也会显示人工改动、保留人工内容、草稿缺失和 Vault 笔记缺失。
- 影响范围：`project_narrative_state_service` 的 Obsidian 维护建议状态生成、同路径草稿动作继承、草稿缺失检测、Vault 已发布笔记缺失检测和发布草稿读取、`.gaoxia/learning/narrative_state.json` 的 `obsidian_maintenance_suggestions` 展示字段、技能库 `Agent 自学习` 面板、章节上下文里的 Obsidian 待审草稿提示、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_published_graph_maintenance_reports_missing_vault_note_and_can_publish_again backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_auto_staged_graph_draft_reports_missing_file_and_can_be_saved_again backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_auto_staged_graph_draft_updates_when_unedited_source_list_changes backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_auto_staged_graph_draft_preserves_manual_edits_when_source_list_changes -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_self_evolution_service backend.tests.test_obsidian_service backend.tests.test_context_builder -v` 通过，共 43 个用例；`npm run build` 通过；`npm run verify` 通过，包含 218 个后端 unittest 和前端生产构建；`git diff --check` 通过；文档相对时间检查无命中。

### Obsidian 图谱问题进入维护建议

- 修改摘要：叙事状态账本的 Obsidian 维护建议现在会读取 Vault 同步摘要里的结构化图谱问题；重复出现的未解析双链会生成 `Graph/` 待审 Markdown 草稿，草稿包含 `aliases`、`source_notes` 和来源笔记双链，重名和歧义链接会形成修复提醒。图谱维护建议会进入 Agent 规划上下文和自学习面板，Agent 路由 / 规划、自学习状态和 Studio 自学习接口读取当前项目详情时会刷新这些建议，并可自动写入中高优先级待审草稿；中高优先级建议会在章节保存、Obsidian 同步或章节上下文生成时自动写入项目 `.gaoxia/obsidian_drafts/`，自动 Graph 草稿未被人工改动时会随来源笔记变化更新 `source_notes`，人工改动过的草稿和保存草稿时遇到的同路径既有人工内容不会被自动覆盖；章节生成上下文仍按待审草稿处理并标明不能当作 Vault 正式设定引用。
- 影响范围：`project_narrative_state_service`、`project_service` 的 Obsidian 配置保存和同步入口、`self_evolution_service` 的 Agent 能力上下文和自学习状态读取、`agent_service` 的模型路由 / 规划上下文、`studio` 自学习状态接口、`.gaoxia/learning/narrative_state.json` 的 `obsidian_maintenance_suggestions` 和 `obsidian_maintenance_actions`、`.gaoxia/obsidian_drafts/Graph/`、Agent 规划上下文、自学习面板维护建议、章节生成上下文里的 Obsidian 待审草稿提示、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明和技能流程回归清单；不改变 `knowledge.db` 表结构，不自动写回 Obsidian Vault，只有用户显式发布时才会创建 Vault 笔记。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；新增 Obsidian 同步后刷新账本后，`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/novel_backend/services/project_service.py backend/tests/test_project_narrative_state_service.py` 通过；新增章节上下文生成刷新账本后，`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；新增 Agent 能力上下文刷新图谱维护建议后，`python3 -m py_compile backend/novel_backend/services/self_evolution_service.py backend/novel_backend/services/agent_service.py backend/tests/test_self_evolution_service.py` 通过；新增 Studio 自学习接口刷新和自动草稿更新策略后，`python3 -m py_compile backend/novel_backend/api/studio.py backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_self_evolution_service.py backend/tests/test_project_narrative_state_service.py` 通过；新增保存草稿保护既有人工内容后，`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_narrative_state_turns_repeated_unresolved_obsidian_links_into_drafts -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_obsidian_sync_refreshes_graph_maintenance_without_chapter_save -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_context_generation_refreshes_graph_maintenance_after_vault_change -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_self_evolution_service.SelfEvolutionServiceTestCase.test_capability_context_refreshes_obsidian_graph_maintenance_from_project_detail -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_self_evolution_service.SelfEvolutionServiceTestCase.test_studio_self_evolution_api_refreshes_obsidian_maintenance_from_project_detail backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_auto_staged_graph_draft_updates_when_unedited_source_list_changes backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_auto_staged_graph_draft_preserves_manual_edits_when_source_list_changes -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_stage_obsidian_maintenance_draft_preserves_existing_manual_edits -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_self_evolution_service backend.tests.test_agent_service -v` 通过，共 50 个用例；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_self_evolution_service backend.tests.test_obsidian_service backend.tests.test_context_builder -v` 通过，共 41 个用例；`npm run verify` 通过，包含 216 个后端 unittest 和前端生产构建。

## 2026-05-27

### Obsidian 维护建议进入自学习

- 修改摘要：叙事状态账本新增 `obsidian_maintenance_suggestions`，启用 Obsidian 时会根据当前剧情债务、人物弧线和已有 Vault 笔记判断哪些信息还没有进入可用笔记；系统会生成建议笔记路径、处理动作，以及带来源 ID、来源章节、相关人物字段和人物双链的 Markdown 草稿。Agent 规划上下文会读取高优先级维护建议，自学习面板会展示这些建议；中高优先级建议会在章节保存后自动把待审 Markdown 写入项目 `.gaoxia/obsidian_drafts/`，自学习面板显示“自动草稿”状态，作者也可以显式保存或更新草稿。章节生成、改稿和诊断上下文会显示 Obsidian 待审草稿提醒，并标明不能当作 Vault 正式设定引用。用户显式发布维护建议时，系统会把草稿写入配置的 Vault，检查目标路径在 Vault 内且不覆盖已有笔记，并重新同步 Obsidian 摘要和 `knowledge.db`；发布后的维护笔记会进入 Obsidian 双链解析，人物双链可进入已解析 / 未解析链接统计；自学习面板提供发布按钮，Obsidian 保存 / 同步按钮在并发状态读取后也会正常恢复，帮助长篇项目在作者不频繁维护 Vault 时仍保持资料整理方向。
- 影响范围：`obsidian_service`、`project_narrative_state_service`、`project_service`、项目 Obsidian API、新增维护建议发布接口、`self_evolution_service`、维护建议草稿 frontmatter 和正文双链、自动草稿状态、章节生成上下文的 Obsidian 待审草稿提示、`.gaoxia/learning/narrative_state.json`、`.gaoxia/obsidian_drafts/`、作者配置的 Obsidian Vault、`knowledge.db` 内容刷新、Agent 规划上下文、技能库 `Agent 自学习` 面板、`verify-ui-smoke`、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不自动写回 Obsidian Vault，只有用户显式发布时创建新笔记，不覆盖已有笔记，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/novel_backend/services/self_evolution_service.py backend/tests/test_project_narrative_state_service.py` 通过；新增保存项目内 Obsidian 草稿后，`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/novel_backend/services/project_service.py backend/novel_backend/api/projects.py backend/tests/test_project_narrative_state_service.py` 通过；新增显式发布到 Vault 后，`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/novel_backend/services/project_narrative_state_service.py backend/novel_backend/services/project_service.py backend/novel_backend/api/projects.py backend/tests/test_project_narrative_state_service.py` 通过；新增维护草稿来源字段、人物双链、自动草稿和待审草稿上下文提示后，`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_narrative_state_suggests_obsidian_notes_for_untracked_debts -v` 通过，覆盖自动草稿、待审草稿进入章节上下文和发布后人物双链解析到 `resolved_links`；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_self_evolution_service -v` 通过，共 13 个用例，期间出现既有 `HTTPError 405` ResourceWarning；`node --check scripts/verify-ui-smoke.mjs` 通过；`npm run build` 通过；`npm run verify` 通过，包含 208 个后端 unittest 和前端生产构建；`npm run verify:ui` 通过。

### Obsidian 章节范围优先级与必写核验

- 修改摘要：Obsidian 笔记选择评分新增章节范围权重，明确绑定目标章节的笔记会优先进入章节上下文、“本章 Obsidian 写作约束”和 Agent 写前资料分析，即使章节标题、任务说明或上一章尾段还没有出现该笔记标题。章节核验也会检查少量连续章节范围明确绑定的必写项；如果正文没有写出正式笔记里的 `required_phrases / 必须出现`，会给出 `Obsidian 设定` 警告，并计入自动修订触发条件，避免总体分数未低于阈值时漏修作者在 Vault 里写明的本章要求。
- 影响范围：`obsidian_service` 笔记选择评分、`project_service.load_project_obsidian_note_contents`、`project_service.summarize_chapter_review_status`、`chapter_auto_repair_service` 自动修订判断、Agent `review_knowledge` 资料分析、`context_builder` Obsidian 设定笔记和写作约束、`chapter_review_service` Obsidian 核验维度、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明和技能流程回归清单；不改变 Vault 写入策略，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/novel_backend/services/chapter_review_service.py backend/tests/test_obsidian_service.py backend/tests/test_context_builder.py backend/tests/test_project_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_extracts_chapter_scope_and_filters_by_target_chapter backend.tests.test_context_builder.ContextBuilderTestCase.test_project_context_bundle_prioritizes_chapter_scoped_obsidian_notes backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_checks_required_phrase_for_chapter_scoped_obsidian_note -v` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service backend.tests.test_context_builder backend.tests.test_project_service -v` 通过，共 65 个用例，期间出现既有 sqlite ResourceWarning；新增 Agent 资料分析按章节选择笔记后，`python3 -m py_compile backend/novel_backend/services/project_service.py backend/novel_backend/services/agent_service.py backend/tests/test_agent_service.py` 通过，`PYTHONPATH=backend python3 -m unittest backend.tests.test_agent_service.AgentServiceTestCase.test_knowledge_review_prioritizes_chapter_scoped_obsidian_notes backend.tests.test_agent_service.AgentServiceTestCase.test_knowledge_review_filters_obsidian_notes_for_target_chapter backend.tests.test_agent_service.AgentServiceTestCase.test_review_knowledge_action_inherits_next_chapter_scope -v` 通过；新增 Obsidian 章节范围必写项触发自动修订后，`python3 -m py_compile backend/novel_backend/services/project_service.py backend/novel_backend/services/chapter_auto_repair_service.py backend/tests/test_project_service.py` 通过，`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_checks_required_phrase_for_chapter_scoped_obsidian_note backend.tests.test_project_service.ProjectServiceTestCase.test_auto_repair_uses_chapter_scoped_obsidian_required_phrase backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_catches_obsidian_forbidden_phrase_without_note_label` 通过，`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_service backend.tests.test_studio_service -v` 通过，共 61 个用例，期间出现既有 ResourceWarning；`npm run verify` 通过，包含 206 个后端 unittest 和前端生产构建。

### Obsidian 章节任务执行状态

- 修改摘要：叙事状态账本的章节任务卡新增 Obsidian 执行状态，章节已有正文时会记录已满足必写项、未完成必写项和已触犯禁写项；未完成或触犯项会转成后续章节可见的高优先级叙事债务，修订满足后关闭；生成上下文和 Agent 自学习面板会展示这些状态，让后续章节知道上一章哪些 Vault 要求已经兑现、哪些还需要修订或延后处理。
- 影响范围：`project_narrative_state_service`、`narrative_state.json` 章节任务卡字段和叙事债务、自学习面板章节任务卡展示、README、项目 Agent 指令、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程回归清单、界面回归说明和测试反馈清单；不写回作者 Obsidian Vault，不改变 `knowledge.db` 表结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_narrative_state_records_obsidian_completion_status -v` 通过；`node --check scripts/verify-ui-smoke.mjs` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_self_evolution_service -v` 通过，共 12 个用例，期间出现既有 `HTTPError 405` ResourceWarning；`npm run build` 通过；`npm run verify` 通过，包含 207 个后端 unittest 和前端生产构建。

### Obsidian 叙事状态账本接入

- 修改摘要：叙事状态账本的章节任务卡会读取目标章节可见的 Obsidian 笔记，记录来源笔记、必写项、禁写项和歧义 / 未解析双链风险；模型叙事编辑生成下一章合同时，会读取当前章和下一章按章节过滤后的 Obsidian 约束，避免下一章合同遗漏作者 Vault 里的正式设定，也避免后段剧透进入早期章节合同。技能库 `Agent 自学习` 面板会在章节任务卡里展示这些 Obsidian 任务约束，作者能直接看到下一章生产链路引用了哪些 Vault 要求。新项目即使还没有蓝图、剧情债务、人物弧线或章节合同，只要目标章节有可用 Obsidian 约束，叙事状态账本也会输出章节任务卡。自学习状态接口会用当前项目详情刷新已有章节任务卡里的 Obsidian 约束，避免 Vault 修改后继续展示旧要求。
- 影响范围：`project_narrative_state_service`、`self_evolution_service`、项目自学习 API、`narrative_state.json` 章节任务卡内容、模型叙事编辑输入、章节生成上下文里的叙事状态账本、技能库自学习面板、UI smoke、README、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程说明、界面回归说明和项目 Agent 指令；不写回作者 Obsidian Vault，不改变 `knowledge.db` 存储结构。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/tests/test_project_narrative_state_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_narrative_state_prompt_includes_chapter_scoped_obsidian_guidance backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_model_editor_receives_obsidian_guidance_for_next_chapter -v` 通过；新增“无蓝图 / 无债务时仍输出 Obsidian 章节任务卡”回归后，`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service.ProjectNarrativeStateServiceTestCase.test_narrative_state_prompt_keeps_obsidian_guidance_without_blueprint_or_debts -v` 通过，`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service -v` 通过，共 5 个用例；新增“自学习状态按当前 Vault 刷新章节任务卡”回归后，`python3 -m py_compile backend/novel_backend/services/project_narrative_state_service.py backend/novel_backend/services/self_evolution_service.py backend/novel_backend/api/projects.py backend/tests/test_self_evolution_service.py` 通过，`PYTHONPATH=backend python3 -m unittest backend.tests.test_self_evolution_service.SelfEvolutionServiceTestCase.test_state_refreshes_narrative_cards_from_current_obsidian -v` 通过，期间出现既有 `HTTPError 405` ResourceWarning，`PYTHONPATH=backend python3 -m unittest backend.tests.test_self_evolution_service -v` 通过，共 6 个用例；新增自学习面板 Obsidian 任务约束展示后，`node --check scripts/verify-ui-smoke.mjs` 通过，`npm run build` 通过，`npm run verify:ui` 通过；最终 `npm run verify` 通过，包含 202 个后端 unittest 和前端生产构建。

## 2026-05-26

### Obsidian 知识库接入

- 修改摘要：新增可选 Obsidian Vault 只读接入，支持配置 Vault 路径、路径过滤、状态过滤、`usable_by_ai` 标记过滤，解析 Markdown frontmatter、`[[双链]]`、标签、别名、`required_phrases / 必须出现` 和 `forbidden_phrases / 禁止出现`；必需和禁止短语也能从正文里的“必须出现 / 必须包含 / 禁止出现 / 禁止包含”行及同名小节列表提取，减少作者维护 YAML 的成本；同步摘要保存到 `.gaoxia/obsidian_sync.json`，可用笔记以 `Obsidian` 来源写入项目 `knowledge.db`，并进入知识检索、架构总览、项目蒸馏、Agent 资料分析和章节写作上下文。同步会生成可解析外链、反向链接、未解析链接和歧义链接，章节上下文和任务蒸馏会按当前任务、目标章节、当前章尾段和上一章尾段带入相关笔记及一跳关系；Obsidian 选择评分会把必需 / 禁止短语和中文词组重合度纳入匹配。命中的笔记会进入“本章 Obsidian 设定检查清单”，列出来源、必写项、禁写项、关联笔记和图谱注意项；命中的必需 / 禁止短语会进入“本章 Obsidian 写作约束”，和普通资料摘要分开给写作模型。连续性证据包也会用这些章节线索检索 Obsidian 正式笔记。章节核验新增 `Obsidian 设定` 维度，正文触犯正式笔记的禁止短语会记为高风险，即使正文没有提到笔记标题；正文提到笔记，或连续性证据命中笔记但缺少必需短语时会记为警告。Obsidian 来源签名进入核验签名，Vault 笔记变化后旧核验会标记为过期。重复命名不会自动解析到任意笔记。同步摘要记录来源签名，读取项目详情时会自动感知 Vault 文件变化并刷新摘要；同步结果会生成结构化 `issues`，列出重复命名、歧义链接、未解析链接和孤立笔记。技能面板打开后，如果用户已经编辑 Obsidian 表单，稍晚返回的旧状态不会覆盖当前输入。
- 影响范围：新增 `obsidian_service`、Obsidian API、`StoryOverview.obsidian`、`ObsidianNoteSummary.required_phrases / forbidden_phrases`、Obsidian 正文约束提取、Obsidian 约束字段选择评分、Obsidian 中文重合度选择评分、Obsidian 本章设定检查清单、Obsidian 本章写作约束、章节核验禁用短语扫描、证据命中时的必需短语检查、项目知识索引来源签名、模型总览来源签名、章节核验来源签名、Obsidian 同步摘要来源签名、Agent 资料分析、动作契约、整书架构执行入口的资料分析判断、Obsidian 图谱关系、重复命名和歧义链接提示、结构化图谱问题、任务上下文图谱筛选、续写管线检索语句、连续性证据包、中文 FTS 检索权重、章节核验 Obsidian 设定维度、技能库 `Obsidian 知识库` 面板及其表单状态、架构总览知识区、UI smoke、README、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程说明、界面回归说明和测试反馈清单；不自动写回作者的 Obsidian Vault，不替代 `.gaoxia/learning/narrative_state.json`、`.gaoxia/learning/style_xp_evolution.json` 或项目设定文件。
- 验证结果：`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service backend.tests.test_context_builder` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_agent_service backend.tests.test_obsidian_service backend.tests.test_context_builder` 通过，期间出现既有 HTTPError ResourceWarning；`node --check scripts/verify-ui-smoke.mjs` 通过；`npm run verify:ui` 第一次失败，原因是后端默认技能目录缺少 `obsidian-vault`，已补齐后通过；图谱统计、重复命名统计和结构化问题列表加入 smoke 后 `npm run verify:ui` 通过；新增“上一章尾段驱动 Obsidian 资料进入下一章上下文和证据包”回归后，第一次三文件回归失败，原因是连续性证据包仍可能命中无关 Obsidian 笔记，修正中文 FTS 关键词选择和重合度评分后通过；新增“章节核验触犯 Obsidian 禁用设定与 Vault 变化后核验过期”回归后，`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_service backend.tests.test_obsidian_service backend.tests.test_context_builder backend.tests.test_generation_service -v` 通过，期间出现既有 sqlite ResourceWarning；新增 Obsidian 表单状态保护后，`npm run verify:ui` 第一次失败并暴露旧状态覆盖当前输入的问题，修正后通过；新增正文约束提取后，`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service -v` 通过，`npm run verify` 通过，包含 184 个后端 unittest 和前端生产构建；`npm run verify:ui` 通过，测试 Vault 使用正文里的“必须出现 / 禁止出现”格式；新增未出现笔记标题时的禁用短语扫描后，`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_checks_obsidian_forbidden_phrases_and_staleness backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_catches_obsidian_forbidden_phrase_without_note_label -v` 通过，`npm run verify` 通过，包含 185 个后端 unittest 和前端生产构建；新增 frontmatter 约束驱动上下文选择后，`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder.ContextBuilderTestCase.test_project_context_bundle_selects_obsidian_notes_by_frontmatter_constraints -v` 通过，`npm run verify` 通过，包含 186 个后端 unittest 和前端生产构建；新增连续性证据命中笔记时的必需短语检查后，针对性用例第一次因为断言期望 `risk` 而失败，实际行为是 `watch` 警告，调整断言后 `PYTHONPATH=backend python3 -m unittest backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_checks_required_phrase_for_obsidian_evidence_hit backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_catches_obsidian_forbidden_phrase_without_note_label -v` 通过；`python3 -m py_compile backend/novel_backend/services/chapter_review_service.py backend/tests/test_project_service.py` 通过；`npm run verify` 通过，包含 187 个后端 unittest 和前端生产构建；新增中文近似关联驱动 Obsidian 笔记选择后，`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/tests/test_context_builder.py` 通过，`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service backend.tests.test_context_builder -v` 通过，`npm run verify` 通过，包含 188 个后端 unittest 和前端生产构建；新增本章 Obsidian 设定检查清单后，`python3 -m py_compile backend/novel_backend/services/context_builder.py backend/tests/test_context_builder.py` 通过，`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder.ContextBuilderTestCase.test_project_context_bundle_expands_obsidian_graph_notes backend.tests.test_context_builder.ContextBuilderTestCase.test_project_context_bundle_includes_obsidian_graph_warnings_in_checklist -v` 通过，`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service backend.tests.test_context_builder -v` 通过，`npm run verify` 通过，包含 189 个后端 unittest 和前端生产构建；`git diff --check` 通过。

### Obsidian 章节范围与剧透边界

- 修改摘要：Obsidian 笔记摘要新增 `chapter_start`、`chapter_end` 和 `reveal_after_chapter`，可从 frontmatter 的 `chapter_range / chapter_start / chapter_end / reveal_after_chapter`、正文里的“适用章节：第 58-60 章”“第 57 章后可用”，或 `#章节/58-60`、`#剧透/57` 这类标签提取；章节上下文、知识检索、任务蒸馏、连续性证据包和章节核验会按目标章节过滤尚未可用的 Obsidian 笔记，避免早期章节提前引用或误报后段真相；章节核验命中证据时优先使用 `source_key` 识别 Obsidian 笔记，减少依赖展示标题格式；技能库和架构总览会显示笔记的适用章节和剧透边界；技能库 Obsidian 面板会忽略过期状态请求，避免打开面板时的旧读取结果覆盖保存后的同步结果。
- 影响范围：`ObsidianNoteSummary`、`obsidian_service` 标签解析、`context_builder`、`project_service` 知识检索结果、`project_distillation_service`、`continuity_guard_service`、`chapter_review_service`、续写证据检索、技能库 `Obsidian 知识库` 面板状态请求、架构总览 Obsidian 笔记卡片、UI smoke、README、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程说明和项目 Agent 指令；不改变作者 Vault 写入策略，也不把 Obsidian 变成剧情债务或文风学习的存储源。
- 验证结果：`python3 -m py_compile backend/novel_backend/models.py backend/novel_backend/services/obsidian_service.py backend/novel_backend/services/context_builder.py backend/novel_backend/services/project_service.py backend/novel_backend/services/project_distillation_service.py backend/novel_backend/services/continuity_guard_service.py backend/novel_backend/services/generation_service.py backend/tests/test_obsidian_service.py backend/tests/test_context_builder.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service backend.tests.test_context_builder -v` 通过，共 19 个用例；`python3 -m py_compile backend/novel_backend/services/chapter_review_service.py backend/tests/test_project_service.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_respects_obsidian_chapter_scope backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_catches_obsidian_forbidden_phrase_without_note_label backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_checks_obsidian_forbidden_phrases_and_staleness -v` 通过；新增标签式章节范围和 `source_key` 证据匹配后，`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/novel_backend/services/chapter_review_service.py backend/tests/test_obsidian_service.py backend/tests/test_project_service.py` 通过，`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_extracts_chapter_scope_and_filters_by_target_chapter backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_obsidian_evidence_prefers_source_key backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_checks_required_phrase_for_obsidian_evidence_hit -v` 通过；`npm run verify` 通过，包含 193 个后端 unittest 和前端生产构建；`npm run verify:ui` 第一次失败，原因是 Obsidian 面板较早的状态读取覆盖了保存后的同步结果，新增状态请求序号后 `node --check scripts/verify-ui-smoke.mjs && npm run verify:ui` 通过；`git diff --check` 通过。

### Obsidian 章节安全签名与检索预览

- 修改摘要：章节核验的 Obsidian 签名改为按目标章节可见笔记计算；编辑只在后段章节可用的笔记，不再让早期章节核验报告标记为过期。章节上下文中的一跳反向关联、知识检索预览、连续性证据正文、任务蒸馏摘要、Agent 资料分析和 Agent 动作契约也按目标章节处理，避免未来笔记通过“反向链接”、检索摘要、写章前资料分析、全局蒸馏摘要或契约资料数量进入早期章节判断。`review_knowledge` 紧跟章节生成、改稿或一致性检查时会继承后续章节范围；紧跟整书架构时保留全书资料视角。
- 影响范围：`obsidian_service` 章节签名和章节安全记录构建、`project_service` 连续性证据返回和 Obsidian 内容读取、`project_distillation_service` 资料分析蒸馏文本、`agent_service` 的 `review_knowledge` 范围继承、`agent_contract_service` 的资料数量检查、`chapter_review_service` 核验过期判断、`context_builder` Obsidian 图谱展示和知识检索预览、README、核心引擎说明、Agent 执行架构说明、记忆系统说明、技能流程说明和项目 Agent 指令；不改变 Obsidian 同步摘要的全局来源签名，不改变 `knowledge.db` 的存储结构，也不写回作者 Vault。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/novel_backend/services/chapter_review_service.py backend/novel_backend/services/context_builder.py backend/tests/test_project_service.py backend/tests/test_context_builder.py` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_checks_obsidian_forbidden_phrases_and_staleness backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_staleness_ignores_future_scoped_obsidian_note backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_respects_obsidian_chapter_scope backend.tests.test_project_service.ProjectServiceTestCase.test_chapter_review_checks_required_phrase_for_obsidian_evidence_hit backend.tests.test_context_builder.ContextBuilderTestCase.test_project_context_bundle_filters_obsidian_notes_by_chapter_scope backend.tests.test_context_builder.ContextBuilderTestCase.test_project_context_bundle_expands_obsidian_graph_notes` 通过，共 12 个用例；直接用 `python3 -m unittest ...` 执行时曾因缺少 `PYTHONPATH=backend` 导致 `ModuleNotFoundError`，改用项目测试环境变量后通过；新增章节安全证据正文后，`python3 -m py_compile backend/novel_backend/services/obsidian_service.py backend/novel_backend/services/project_service.py backend/tests/test_obsidian_service.py` 通过，`PYTHONPATH=backend python3 -m unittest backend.tests.test_obsidian_service.ObsidianServiceTestCase.test_obsidian_extracts_chapter_scope_and_filters_by_target_chapter` 通过；新增 Agent 资料分析章节范围后，`python3 -m py_compile backend/novel_backend/services/agent_service.py backend/novel_backend/services/project_service.py backend/novel_backend/services/project_distillation_service.py backend/tests/test_agent_service.py` 通过，`PYTHONPATH=backend python3 -m unittest backend.tests.test_agent_service.AgentServiceTestCase.test_knowledge_review_filters_obsidian_notes_for_target_chapter backend.tests.test_agent_service.AgentServiceTestCase.test_review_knowledge_action_inherits_next_chapter_scope backend.tests.test_agent_service.AgentServiceTestCase.test_knowledge_review_reuses_distillation_report_before_model_analysis` 通过，期间出现既有 HTTPError ResourceWarning；新增任务蒸馏摘要范围用例后，`python3 -m py_compile backend/novel_backend/services/project_distillation_service.py backend/tests/test_project_service.py` 通过，`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_service.ProjectServiceTestCase.test_task_distillation_prompt_filters_obsidian_summary_by_chapter_scope -v` 通过；新增 Agent 动作契约资料数量范围用例后，`python3 -m py_compile backend/novel_backend/services/agent_contract_service.py backend/tests/test_agent_service.py` 通过，`PYTHONPATH=backend python3 -m unittest backend.tests.test_agent_service.AgentServiceTestCase.test_review_knowledge_contract_counts_only_target_chapter_obsidian_notes -v` 第一次因测试构造 `AgentPlan` 缺少必填 `id / title` 失败，修正测试后通过；`npm run verify` 通过，包含 198 个后端 unittest 和前端生产构建。

### 项目 Agent 说明

- 修改摘要：新增项目根 `AGENTS.md`，记录本项目的 Agent 协作要求、验证要求、文档同步规则和当前项目事实，方便后续会话直接按项目约定工作。
- 影响范围：项目根 Agent 指令和 `CHANGELOG.md`；不改变应用运行逻辑、接口或数据结构。
- 验证结果：`git diff --check` 通过。

### 系统学习版文风 / XP

- 修改摘要：章节保存后新增项目级文风 / XP 学习状态 `.gaoxia/learning/style_xp_evolution.json`，从最终正文、章节核验、文风名和 XP 预设中整理可复用规则；同一规则至少出现在两个不同章节后才进入后续生成提示词。
- 影响范围：`project_service` 章节保存、`context_builder.build_prompt_support()`、Studio 章节生成 / 改稿 / 蓝图任务、Agent 章节生成和章节工作流、自学习状态接口、技能库 `Agent 自学习` 面板、UI smoke 脚本、README、核心引擎说明、Agent 执行架构说明、技能流程说明和记忆系统说明；不改变章节正文保存路径、作者记忆、手工文风方案或 XP 预设。
- 验证结果：`PYTHONPATH=backend python3 -m unittest backend.tests.test_context_builder backend.tests.test_project_style_xp_evolution_service` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_service` 通过，期间出现既有 sqlite ResourceWarning；`PYTHONPATH=backend python3 -m unittest backend.tests.test_self_evolution_service` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_studio_service` 通过；`PYTHONPATH=backend python3 -m unittest backend.tests.test_generation_service backend.tests.test_agent_service` 通过；`npm run build` 通过；`node --check scripts/verify-ui-smoke.mjs` 通过；`npm run verify:ui` 通过；`git diff --check` 通过。

### 剧情债务与人物弧线

- 修改摘要：章节保存后新增项目级叙事状态 `.gaoxia/learning/narrative_state.json`，记录伏笔、承诺、关系变化、世界规则、主要人物弧线和章节任务卡；设置页保存主模型 Key 或启用第二审查模型后，会在保存后执行模型版叙事审查，输出带证据的债务更新、人物弧线变化、合同执行回看和下一章章节合同；后续生成目标章节时，`build_project_context_bundle()` 会把章节合同、必须处理、可轻触、不要提前揭开的剧情债务加入上下文。
- 影响范围：`project_narrative_state_service`、`project_service` 章节保存、`context_builder` 章节上下文、自学习状态接口、技能库 `Agent 自学习` 面板、UI smoke 脚本、README、核心引擎说明、Agent 执行架构说明、技能流程说明、记忆系统说明、界面回归说明和测试反馈清单；不改变章节正文保存路径、用户手工设定、作者记忆或现有知识索引格式。
- 验证结果：`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_narrative_state_service backend.tests.test_context_builder backend.tests.test_self_evolution_service backend.tests.test_project_style_xp_evolution_service` 通过，期间出现既有 `HTTPError 405` ResourceWarning；`PYTHONPATH=backend python3 -m unittest backend.tests.test_project_service backend.tests.test_studio_service backend.tests.test_generation_service backend.tests.test_agent_service` 通过，期间出现既有 sqlite ResourceWarning 和既有模型请求 ResourceWarning；`npm run build` 通过；`node --check scripts/verify-ui-smoke.mjs` 通过；`npm run verify:ui` 通过；`npm run verify` 通过，包含 175 个后端 unittest 和前端生产构建；`git diff --check` 通过。

## 2026-05-25

### Agent 执行工作流与评审门禁

- 修改摘要：Agent 执行新增 workflow 状态文件和 action 契约检查，每次执行会写入 `.gaoxia/runs/{task_id}/workflow.json` 和子任务状态文件，记录预检、`DISPATCHED / ACKED / RUNNING / SUCCEEDED / FAILED / BLOCKED / TIMED_OUT / STALLED` 状态、心跳、历史失败门禁、预期产物和产物校验；旧的确认超时和心跳停滞任务会在后续执行前被标记为超时状态；子任务文件名会转换成跨平台安全格式，避免 Windows 文件名限制影响 Agent 执行。
- 增强摘要：章节核验优先使用第二审查模型或 `NOVEL_REVIEW_MODEL_API_KEY / NOVEL_REVIEW_MODEL_BASE_URL / NOVEL_REVIEW_MODEL_NAME`，未配置时使用当前写作模型；自学习失败案例新增 `severity` 和 `gate` 信息，写作回归新增内置黄金样本评测，用于检查模板腔、对白同质、连续性冲突和正常场景的识别能力。
- 影响范围：`agent_service` 执行链路、章节核验模型选择、自学习失败案例和写作回归报告、项目目录 `.gaoxia/runs/` 状态文件、README、核心引擎说明、Agent 执行架构说明和记忆系统说明；不改变章节正文保存路径、SSE 兼容事件或现有模型主配置字段。
- 验证结果：`npm run verify` 通过，包含 169 个后端 unittest 和前端生产构建；`git diff --check` 通过。

## 2026-05-24

### 0.1.2 Windows 测试包发布

- 修改摘要：在 `main` 当前提交 `7051ada` 触发 GitHub Actions `Windows Desktop Release`，生成 Windows x64 NSIS 安装包和 Windows sidecar，并上传到 GitHub Release `v0.1.2`；本地整理 `release/test-release/windows/稿匣_0.1.2_测试包`，安装说明和反馈清单改为 Windows 内容。
- 影响范围：GitHub Release 资产、Windows 测试包整理目录、README 项目状态和 Windows 打包说明；不改变应用代码、版本号、接口或数据结构。
- 验证结果：GitHub Actions run `26353093355` 通过，包含 Windows backend 单测、前端生产构建、Windows sidecar 打包与健康检查、Tauri NSIS 安装包构建和 artifact 上传；本地 `SHA256SUMS.txt` 校验通过。Windows setup SHA256：`3dbb1e170036c1ff50ec7a02c592793d5ffa2f395fda760caf182e0472780cea`；Windows sidecar SHA256：`b7e871b5c62ab4a2aff00c10fc8d2c76a3e55a9219971eed90d5efd3b9a3f0aa`。Windows 实机安装、卸载和首次启动仍未人工验收。

### Agent 章节目标字数修正

- 修改摘要：Agent 对话里普通“写第一章 / 生成第 N 章”请求，在作品架构齐全且用户没有指定短稿或具体字数时，会按作品目标字数和目标章节数计算本章目标容量；例如 200000 字 / 30 章会把单章目标设为约 6667 字，不再沿用 1800 字默认短目标。
- 影响范围：`agent_service` 章节生成计划目标字数、章节生成说明文档；保留用户明确指定字数、短稿、片段、开头、试写等短文本请求的处理方式，不改变 Studio 章节生成接口和章节保存路径。
- 验证结果：`PYTHONPATH=backend python3 -m unittest backend.tests.test_agent_service` 通过，25 个用例通过。

### 0.1.2 测试版发布

- 修改摘要：发布版本号更新为 `0.1.2`，用于打包包含模型运行调度、辅助任务状态修正、模型总览生成状态修正、章节生成计划后续动作解析修正和 Agent 章节目标字数修正的测试版；同步 Tauri Rust crate 版本，并修正 macOS `.app` 启动验证方式，按真实 app bundle 启动并清理应用内 sidecar。
- 影响范围：`package.json`、`package-lock.json`、`src-tauri/tauri.conf.json`、`src-tauri/Cargo.toml`、`src-tauri/Cargo.lock`、`scripts/verify-desktop-release.sh`、README Release 链接、桌面发布回归说明和 macOS 测试包命名。
- 验证结果：`npm run verify:ui` 通过；`npm run release:test:macos` 通过，包含 166 个后端 unittest、前端生产构建、Python sidecar 打包与健康检查、Tauri debug app/dmg 构建、签名修复、应用内 sidecar 健康检查、`.app` 启动检查和测试包整理。测试包路径：`release/test-release/macos/稿匣_0.1.2_测试包`；DMG SHA256：`5190c083650e3838996c8214677839165d36efcd0af1b28486879416c5930da8`。

### 架构总览打开触发模型总览修正

- 修改摘要：打开架构总览时，`review_characters=true` 请求会允许后端生成或读取模型总览；移除本地规则后，前端按钮不再只拿到空人物关系图。界面 smoke 的假模型也补齐模型总览结构化返回，并改用非占位模型名。
- 影响范围：`project_service` 项目详情、架构总览弹窗、UI smoke 假模型和总览回归检查；不改变 `.gaoxia/story_overview_model.json` 缓存格式。
- 验证结果：`PYTHONPATH=backend python3 -m pytest backend/tests/test_project_service.py backend/tests/test_agent_service.py` 通过，60 个用例通过；`npm run verify:ui` 通过；`npm run release:test:macos` 通过。

### 章节生成计划后续动作解析修正

- 修改摘要：Agent 计划里如果先生成一个新章节，后续同一计划里的去 AI、润色或一致性检查会绑定到前面即将生成的章节；不会因为执行前还没有“既有已写章节”而拒绝执行。
- 影响范围：`agent_service` 计划解析和章节生成后的后续处理；不改变章节正文生成、改稿、核验接口或前端 SSE 协议。
- 验证结果：新增 Agent 计划回归用例；`PYTHONPATH=backend python3 -m pytest backend/tests` 通过，164 个用例通过。

### 模型总览生成状态修正

- 修改摘要：模型版故事总览优先使用第二审查模型；第二审查模型不可用时，改用当前写作模型生成 `.gaoxia/story_overview_model.json`。模型总览请求超时时间改为 240 秒，来源分片上限改为约 4500 字符，并限制每个分片输出的核心节点数量；人物关系图只接收稳定人物，排除单一旧设定里的旧名、职务泛称和临时配角。强制刷新会绕过已有缓存重新请求模型。如果没有生成缓存文件，`story_overview_model` 辅助任务会记录为失败并等待重试，不再显示完成。架构分步生成也新增人物名单一致性要求，情节骨架、人物状态和章节蓝图不得默默替换核心人物或改名。
- 影响范围：`generation_service` 架构分步提示词、`project_service` 模型总览生成、`project_auxiliary_service` 辅助任务状态、关系总览数据来源、README、核心引擎说明和 Agent 执行架构说明；不改变架构文件、章节正文、资料库文本索引或模型总览缓存格式。
- 验证结果：`PYTHONPATH=backend python3 -m pytest backend/tests` 通过，163 个用例通过；`npm run build` 通过；`git diff --check` 通过。

## 2026-05-23

### 分支合并与文档同步

- 修改摘要：当前开发分支已合入 `origin/main` 和 `origin/codex/xianyu/windows-package-20260519`，并同步 Agent 自学习文档中的主接口说明。
- 影响范围：主线文档、Windows 打包发布流程、模型请求重试、章节自动修订、Agent 长篇逐章生产、Agent 自学习说明；接口行为不变。
- 验证结果：合并后 `npm run verify` 通过，后端 156 个 unittest 和前端生产构建通过；文档同步后 `git diff --check` 通过。

### 提交前检查修正

- 修改摘要：`release/` 发布测试输出目录加入 `.gitignore`，避免本地测试包、`.DS_Store` 和外部测试说明被误提交。
- 修复摘要：旧的 `ModelConfig` 保存路径现在会保留已配置的 `review_model`，避免只保存主模型时清空第二审查模型配置；架构生成解析支持模型返回嵌套 JSON 段落，人物名自动识别减少把“项目文档、关键词、养老金、封口费”等词片段误判成人物。
- 影响范围：`.gitignore`、`config_service.save_config()`、`generation_service` 架构解析、`project_service` 人物名识别，以及对应回归测试。
- 补充摘要：架构总览新增大模型结构化总览缓存，模型会整理人物、关系、事件、地点、道具、技能、场景和组织；项目来源较长时分片交给模型整理，再合并通过证据校验的节点；缓存保存在 `.gaoxia/story_overview_model.json`，项目来源变化后自动失效。
- Agent 长篇生产：章节正文写回计划默认扩展为 `生成/续写正文 -> rewrite_chapter(mode=humanize) -> consistency_check`，`chapter_generate`、`chapter_workflow(mode=draft)` 和单独改稿都会进入这套作者确认后的逐章生产流程；作者明确只要初稿、不改稿或不检查时保留单步生成；章节核验报告可作为 Agent 产物返回。
- 测试修正：Agent、生成服务和 Studio 单测屏蔽不属于目标的章节审查、Embedding 和 rerank 外部请求，避免回归测试误连真实模型。
- 验证结果：`npm run verify` 通过，后端 128 个 unittest 和前端生产构建通过；`git diff --check` 通过。

### Embedding 单独配置恢复

- 修改摘要：设置页恢复“单独设置 Embedding”开关和独立输入项。默认仍按当前写作模型推导 Embedding；勾选后可单独填写 Embedding 服务商、模型、接口地址、API Key、向量维度、检索数量和批量大小。后端保存完整配置时保留传入的 `embedding`，不再按写作模型强制覆盖；旧的单独 `ModelConfig` 保存路径仍会自动推导 Embedding。
- 影响范围：模型设置页、`AppConfigUpdateRequest` 保存语义、Embedding 配置持久化、界面 smoke 设置页检查、README、核心引擎说明、界面回归说明和测试反馈清单；不改变知识库索引文件格式、模型请求接口或环境变量名称。
- 验证结果：`.venv/bin/python -m unittest backend.tests.test_config_service -v` 通过，7 个用例通过；`npm run backend:test` 通过，123 个后端用例通过；`npm run build` 通过；`npm run verify` 通过；`npm run verify:ui` 通过，包含设置页“单独设置 Embedding”检查；`git diff --check` 通过。

### 架构生成分步保存与辅助任务后台化

- 修改摘要：Agent 整书架构改为七个步骤逐步保存，任务开始时只构建一次项目上下文快照，后续步骤复用快照并通过 workspace 使用前面步骤刚生成的内容；每完成一个步骤就写入对应设定文件，并把进度记录到 `.gaoxia/architecture_progress.json`；中途失败后，同一指令再次执行会重新读取项目文件和进度，跳过已经保存且仍有内容的步骤，从失败步骤继续执行。知识库索引刷新、模型版故事总览和系统记忆刷新改为 `.gaoxia/auxiliary_tasks.json` 后台辅助任务，FastAPI lifespan 启动巡检，失败会记录错误并按重试时间再次处理。
- 影响范围：`agent_service` 整书架构执行、`project_service` 设定文件轻量写入、架构进度文件、辅助任务队列、项目详情故事总览读取、架构上下文知识检索、第二审查模型使用方式和相关说明文档；不改变章节正文保存路径、SSE 事件协议或主模型配置格式。
- 配置变化：新增 `NOVEL_AUXILIARY_WORKER_ENABLED` 和 `NOVEL_AUXILIARY_WORKER_INTERVAL_SECONDS`；模型版故事总览、人物候选和世界要素复核使用第二审查模型配置及 `NOVEL_REVIEW_MODEL_API_KEY / NOVEL_REVIEW_MODEL_BASE_URL / NOVEL_REVIEW_MODEL_NAME`。
- 验证结果：`python3 -m compileall backend/novel_backend backend/tests/test_agent_service.py backend/tests/test_project_service.py` 通过；定向 pytest 4 个用例通过；`npm run verify` 通过，159 个后端 unittest 和前端生产构建通过；`git diff --check` 通过。

### 模型运行调度与后台闲时执行

- 修改摘要：新增 `model_runtime_service` 统一管理聊天模型和检索模型运行通道，默认主模型并发为 1、Embedding/rerank 并发为 1；Prompt 历史新增运行时任务 ID、通道、优先级和排队等待时间。章节候选默认改为 `standard` 单候选，`fast` 减少审校请求，`deep` 保留 3 候选但经调度通道顺序执行。设置页新增模型运行调度配置，工作台顶部会显示当前模型任务和队列状态。
- 影响范围：主模型调用、辅助模型、项目愿景、Embedding、rerank、qwen-doc 文档抽取、章节候选生成、章节审校、自学习后台排程、辅助任务巡检、模型设置页、Studio 运行状态接口和相关测试；不改变章节保存路径、SSE 事件格式或现有模型服务商配置字段。
- 后台策略：辅助任务巡检在前台模型或检索任务忙时延后；自学习排程只有包含 `model_review` 时受空闲窗口限制，纯技能整理和写作回归仍可按原排程执行。
- 验证结果：`python3 -m compileall backend/novel_backend` 通过；`PYTHONPATH=backend python3 -m pytest backend/tests` 通过，162 个用例通过；`npm run build` 通过；`curl -fsS http://127.0.0.1:1420/` 确认可读取本地 Vite 页面。未用真实外部模型做联网联调。

### 辅助知识索引失败状态修正

- 修改摘要：知识库向量刷新失败时，`knowledge_index` 辅助任务不再被误记为完成；队列会把失败原因写入 `.gaoxia/auxiliary_tasks.json`，保留重试次数和下次处理时间，后续巡检按原机制再次处理。
- 影响范围：辅助任务队列、项目知识索引刷新结果、Embedding 网络异常记录；不改变架构文件、章节正文、知识库文本索引或模型配置字段。
- 验证结果：`.venv/bin/python -m unittest backend.tests.test_project_auxiliary_service -v` 通过；`npm run verify` 通过，163 个后端 unittest 和前端生产构建通过；`git diff --check` 通过。

### 关系总览移除本地规则生成

- 修改摘要：项目详情里的关系总览只读取 `.gaoxia/story_overview_model.json` 模型总览缓存；没有可用缓存时，人物、事件、地点、组织、道具、技能和场景列表保持为空，不再用本地文本规则从架构文件、资料或章节中猜测节点。
- 影响范围：`project_service` 故事总览构建、项目详情返回数据、项目记忆中的自动人物/要素条目、关系总览空状态文案、README、核心引擎说明和 Agent 执行架构说明；不改变架构文件、章节正文、资料库文本索引、模型总览缓存格式或第二审查模型配置字段。
- 验证结果：`PYTHONPATH=backend python3 -m pytest backend/tests` 通过，160 个用例通过；`npm run build` 通过。

## 2026-05-22

### 模型网络中断处理

- 修改摘要：模型请求错误分类新增 `network_connection`，会把 `SSL: UNEXPECTED_EOF_WHILE_READING`、远端提前断开、连接重置等场景显示为“模型网络连接中断”，不再泛化成未知模型请求失败。
- 影响范围：主模型生成、做梦整理、Embedding 检索和阿里百炼 `qwen3-rerank` 重排序共用新的 JSON 请求助手；临时连接中断会做短重试，HTTP 认证、额度、模型名、请求格式类错误仍直接返回。
- 文档变化：《核心引擎说明》同步更新模型错误分类和请求重试说明。
- 验证结果：`.venv/bin/python -m unittest backend.tests.test_model_error_service backend.tests.test_rerank_service -v` 通过，7 个用例通过；`npm run verify` 通过，117 个后端用例和前端生产构建通过；`git diff --check` 通过；已重启本地后端并确认 `/api/app/health` 返回 `status: ok`。

### Agent 自学习复盘

- 修改摘要：Agent 执行完成后新增 `self_evolution_review`，会记录经验候选、调用规则候选、技能使用统计、技能整理报告和写作评价；高置信调用规则和失败案例会进入后续模型路由和模型规划上下文；技能库新增 `Agent 自学习` 面板，用于查看能力看板、确认草案、候选、规则、评价、写作回归、模型审查、技能统计、长期趋势、细分质量维度、失败案例和技能版本记录；显式技能优化创建或更新用户技能时，会同步更新技能统计和技能版本快照。
- 增强摘要：新增自学习后台排程 worker，应用启动后会扫描已启用排程的作品；设置页新增第二审查模型配置；技能版本区新增左右 diff、技能包导出和技能包导入；失败案例库新增按动作聚合的重复失败视图。
- 影响范围：新增 `self_evolution_service.py`、`skill_usage_service.py`、`self_evolution_scheduler_service.py`、项目目录 `.gaoxia/learning/self_evolution_candidates.json`、`.gaoxia/learning/self_evolution_reviews.jsonl`、`.gaoxia/learning/agent_capability_rules.json`、`.gaoxia/learning/writing_evaluations.jsonl`、`.gaoxia/learning/self_evolution_drafts.json`、`.gaoxia/learning/writing_regression_runs.jsonl`、`.gaoxia/learning/self_evolution_model_reviews.jsonl`、`.gaoxia/learning/failure_cases.jsonl`、`.gaoxia/learning/self_evolution_schedule.json`，以及应用数据目录 `skills/.usage.json`、`skills/.curator_reports.jsonl`、`skills/.versions/{skill_id}/versions.json`；`app_config.json` 新增 `review_model` 配置；更新技能库面板、设置页、前端 API 封装、Agent 产物摘要和 UI smoke。
- 接口变化：新增 `GET /api/projects/{project_id}/self-evolution`、`PATCH /api/projects/{project_id}/self-evolution/candidates/{candidate_id}`、`POST /api/projects/{project_id}/self-evolution/curate`、`POST /api/projects/{project_id}/self-evolution/regression`、`POST /api/projects/{project_id}/self-evolution/model-review`、`PUT /api/projects/{project_id}/self-evolution/schedule`、`POST /api/projects/{project_id}/self-evolution/schedule/run`、`PATCH /api/projects/{project_id}/self-evolution/drafts/{draft_id}`、`POST /api/projects/{project_id}/self-evolution/drafts/{draft_id}/apply`、`GET /api/studio/skills/{skill_id}/versions`、`GET /api/studio/skills/{skill_id}/package`、`POST /api/studio/skills/import-package`、`POST /api/studio/skills/{skill_id}/versions/{version_id}/rollback`、`POST /api/studio/skills/{skill_id}/promote-global`。
- 安全边界：自学习复盘不会自动改章节正文；候选采纳后只生成确认草案，草案应用后才写入作者侧项目记忆、创建或更新用户技能，或把调用规则标为作者采纳；自学习排程默认关闭，手动启用后才按间隔执行；后台 worker 只处理已启用排程且到达间隔的作品；第二审查模型只有设置页启用并填写完整配置，或配置 `NOVEL_REVIEW_MODEL_API_KEY`、`NOVEL_REVIEW_MODEL_BASE_URL`、`NOVEL_REVIEW_MODEL_NAME` 后才会参与。
- 验证结果：`.venv/bin/python -m unittest backend.tests.test_config_service backend.tests.test_self_evolution_service -v` 通过，9 个用例通过；`npm run build` 通过；`npm run verify` 通过，包含 115 个 backend 用例和前端生产构建；`npm run verify:ui` 第一次因设置面板折叠区文本不可见而失败，已调整 smoke 打开折叠区后检查，第二次通过。

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

- 修改摘要：`rewrite_chapter` 写回后改为用保存后的正文长度复算章节容量，并和用户字数要求、项目单章均值比较；重写、改写、定稿整章时，低于完整章容量会自动从当前正文末尾分段续写。补足过程中任一请求失败，或最终仍未达到容量阈值，都会恢复当前改稿开始前的正文，避免把不合格短稿或半截扩写留在章节里。执行反馈会过滤模型自报的“约 15000 字”“完整章节”等未经验证的修改说明；去 AI、短稿、片段、开头等明确短文本请求不触发扩写。Agent 前端同时会从 `session_result.project_detail` 刷新项目详情；最终结果没有项目详情时，会重新读取项目详情，避免章节文件已更新但正文面板仍显示旧内容。
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

- 修改摘要：Agent 对话发送前会保存完整线程到项目目录，SSE 请求只提交末尾 50 条历史，并把超长单条历史压缩到接口允许长度内；线程消息新增 `id / content_hash / original_length / summary` 元数据，后端同步生成 `.gaoxia/thread_context/{thread_id}.json` 片段索引，执行时按当前输入取回相关长历史内容；backend 对请求体验证失败新增统一错误包装，前端能显示具体字段原因，不再只看到 `SSE 建连失败: 422`。
- 影响范围：`/api/studio/agent/stream` 的建连错误提示、Agent 对话请求体、线程保存格式、项目目录 `.gaoxia/thread_context` 索引、长线程继续对话体验、接口层校验测试和 Agent 长历史取回测试；不改变 SSE 事件协议、模型配置或章节正文保存路径。
- 验证结果：`.venv/bin/python -m unittest backend.tests.test_app -v` 通过，3 个用例通过；`.venv/bin/python -m unittest backend.tests.test_project_service.ProjectServiceTestCase.test_save_project_agent_threads_keeps_long_message_and_builds_context_index backend.tests.test_agent_service.AgentServiceTestCase.test_agent_session_recovers_relevant_chunks_from_long_thread_message -v` 通过，2 个用例通过；`npm run build` 通过；`npm run backend:test` 通过，146 个用例通过；`git diff --check` 通过。

## 2026-05-16

### Agent 长线程完整性复查

- 修改摘要：前端新增长线程保存保护：当当前线程历史超过 50 条，或任意单条历史超过 6000 字时，如果完整线程保存到 backend 失败，会停止当前 SSE 执行并提示错误，避免只拿压缩后的历史继续生成。长线程回归测试文本提升到真实超过 6000 字，并直接断言后端能从索引里取回尾部关键句。
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

## 2026-05-20

### 完整章目标字数识别与小节补足复查

- 修改摘要：核查运行日志后确认，2026-05-19 的一次第一章重写把“当前正文约 3870 字”误识别成用户目标，导致 `length_target_words=3870` 且未触发 15000 字完整章补足。本次修正字数识别：状态描述、保存校验、现有正文长度不会作为目标；“15000 字目标”“单章均值约 15000 字”这类表达才会作为章节目标。架构完整、单章均值较高的项目里，Agent 收到“继续写第一章”这类未指定短稿的写作请求时，会按当前章节距离单章均值的缺口生成完整章。改稿补足也会把完整剩余缺口交给小节生成流程，超过 5500 字时按小节追加，并在日志里记录小节计划和完成状态。
- 影响范围：`context_builder` 字数目标解析、Agent 章节生成目标规划、`rewrite_chapter` 自动补足、`generation_service` 小节生成日志、章节生成/改稿说明文档；不改变章节保存路径、SSE 协议、模型配置或项目数据格式。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/context_builder.py backend/novel_backend/services/agent_service.py backend/novel_backend/services/generation_service.py backend/tests/test_context_builder.py backend/tests/test_agent_service.py` 通过；定向回归 4 个用例通过；`npm run backend:test` 通过，152 个用例通过；`npm run build` 通过；`git diff --check` 通过。

### 模型请求传输机制扩展

- 修改摘要：统一 JSON 传输层支持自定义 method、headers、原始 body 和空响应，除聊天模型、Embedding、重排序和项目愿景外，联网考据与 qwen-doc 文档抽取也改为使用同一套超时、短暂错误重试和 JSON 校验机制。
- 影响范围：模型相关 HTTP 请求、联网考据、导入资料时的 qwen-doc 文件上传 / 状态查询 / 删除；不改变前端接口、模型配置或项目数据格式。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/model_transport_service.py backend/novel_backend/services/web_research_service.py backend/novel_backend/services/import_service.py backend/tests/test_model_transport_service.py` 通过；`.venv/bin/python -m unittest backend.tests.test_model_transport_service -v` 通过，4 个用例通过；`.venv/bin/python -m unittest backend.tests.test_web_research_service backend.tests.test_import_service -v` 通过，11 个用例通过；`npm run backend:test` 通过，154 个用例通过；`git diff --check` 通过。

### Agent 线程并发保存修复

- 修改摘要：整体核验时发现界面 smoke 在并发保存 Agent 线程时偶发 `FileNotFoundError`，原因是原子写文件固定复用同一个 `.tmp` 临时文件名。本次改为每次写入使用唯一临时文件名，避免同一路径并发写入时互相移除临时文件；Windows 上同一路径并发 `os.replace` 偶发 `PermissionError` 时会做有限短暂重试。
- 影响范围：所有通过 `atomic_write_text` / `atomic_write_json` 写入的本地 JSON 和文本文件，重点影响 Agent 线程、上下文索引、配置、历史记录、技能和预设保存；不改变文件路径、文件格式或接口协议。
- 验证结果：`python3 -m py_compile backend/novel_backend/utils/jsonfile.py backend/tests/test_jsonfile.py` 通过；`.venv/bin/python -m unittest backend.tests.test_jsonfile backend.tests.test_project_service.ProjectServiceTestCase.test_save_and_load_project_agent_threads backend.tests.test_project_service.ProjectServiceTestCase.test_save_project_agent_threads_keeps_long_message_and_builds_context_index backend.tests.test_project_service.ProjectServiceTestCase.test_save_project_agent_threads_removes_stale_thread_files -v` 通过；`npm run verify` 通过，156 个后端用例通过且前端生产构建通过；`npm run verify:ui` 首次失败并暴露并发保存问题，修复后重跑通过；`npm run release:test:macos` 通过；Windows `verify:desktop:windows` 首次发现并发 `os.replace` 的 `PermissionError`，加入重试后在 GitHub Actions 复验通过；`git diff --check` 通过。

### Embedding 单独配置

- 修改摘要：设置页 Embedding 默认继续按当前写作模型推导，并补正阿里 `text-embedding-v4` 默认维度为 2048；新增“单独设置 Embedding”开关，可以独立填写 Embedding 服务商、模型、接口地址、API Key、维度、检索数量和批量大小。后端保存完整配置时保留传入的 `embedding`，不再按写作模型强制覆盖；旧的单独模型保存路径仍会自动推导 Embedding。
- 影响范围：模型设置页、`AppConfigUpdateRequest` 保存语义、Embedding 配置持久化、README 和核心引擎说明；不改变知识库索引文件格式、模型请求接口或环境变量名称。
- 验证结果：`python3 -m py_compile backend/novel_backend/services/config_service.py backend/tests/test_config_service.py` 通过；`.venv/bin/python -m unittest backend.tests.test_config_service -v` 通过，8 个用例通过；`npm run verify` 通过，156 个后端用例通过且前端生产构建通过；`npm run verify:ui` 首次等待联网考据未配置提示超时，立即重跑通过；`git diff --check` 通过。

### 0.1.1 测试版发布准备

- 修改摘要：版本号提升到 `0.1.1`，同步 `package.json`、`package-lock.json`、Tauri 配置、Cargo 配置和 README Release 链接；Windows 打包说明中的测试包路径和安装程序名同步到 0.1.1；重新生成 macOS arm64 测试包 `release/test-release/macos/稿匣_0.1.1_测试包`，并整理 Windows x64 测试包 `release/test-release/windows/稿匣_0.1.1_测试包`。
- 影响范围：应用版本号、macOS / Windows 测试包输出目录、README Release 链接、Windows 打包说明；不改变运行时接口、项目数据格式或许可证格式。
- 验证结果：`npm run release:test:macos` 通过，包含 156 个后端用例、前端生产构建、Python sidecar 打包、sidecar 健康检查、Tauri debug `.app` / `.dmg` 构建、签名修复校验、应用内 sidecar 健康检查和 `.app` 启动检查；macOS `shasum -a 256 -c SHA256SUMS.txt` 通过；`hdiutil verify 稿匣_0.1.1_aarch64.dmg` 通过；Windows `verify:desktop:windows` 在 GitHub Actions 通过，整理出的 Windows 测试包 SHA256 校验通过。Windows 实机安装、卸载和首次启动尚未人工验收。
