from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from novel_backend.config import Settings
from novel_backend.models import AppConfig, AppConfigUpdateRequest, EmbeddingConfig, ModelConfig, ReviewModelConfig
from novel_backend.utils.jsonfile import atomic_write_json, atomic_write_text, read_json


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def _model_family(model_config: ModelConfig) -> str:
  base_url = model_config.base_url.strip().lower()
  model_name = model_config.model_name.strip().lower()

  if "dashscope.aliyuncs.com" in base_url:
    return "aliyun"
  if "ark.cn-beijing.volces.com" in base_url:
    return "volcengine"
  if "api.openai.com" in base_url:
    return "openai-compatible"

  if model_name.startswith("qwen"):
    return "aliyun"
  if model_name.startswith("doubao-"):
    return "volcengine"
  if model_name.startswith("gpt-") or model_name.startswith("text-embedding-"):
    return "openai-compatible"

  return ""


def resolve_embedding_config(
  model_config: ModelConfig,
  current_embedding: EmbeddingConfig | None = None,
) -> EmbeddingConfig:
  family = _model_family(model_config)
  retrieval_k = current_embedding.retrieval_k if current_embedding is not None else 6
  batch_size = current_embedding.batch_size if current_embedding is not None else 8
  api_key = model_config.api_key.strip() or (current_embedding.api_key.strip() if current_embedding is not None else "")

  if family == "aliyun":
    return EmbeddingConfig(
      provider="aliyun-bailian",
      base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
      api_key=api_key,
      model_name="text-embedding-v4",
      dimensions=2048,
      retrieval_k=retrieval_k,
      batch_size=batch_size,
    )

  if family == "volcengine":
    return EmbeddingConfig(
      provider="volcengine-ark",
      base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
      api_key=api_key,
      model_name="doubao-embedding-vision",
      dimensions=None,
      retrieval_k=retrieval_k,
      batch_size=batch_size,
    )

  if family == "openai-compatible":
    return EmbeddingConfig(
      provider="openai-compatible",
      base_url=model_config.base_url.strip() or "https://api.openai.com/v1",
      api_key=api_key,
      model_name="text-embedding-3-small",
      dimensions=None,
      retrieval_k=retrieval_k,
      batch_size=batch_size,
    )

  return current_embedding.model_copy() if current_embedding is not None else EmbeddingConfig()


def app_config_path(settings: Settings) -> Path:
  return settings.data_dir / "app_config.json"


def app_log_path(settings: Settings) -> Path:
  return settings.data_dir / "logs" / "app.log"


def prompt_history_path(settings: Settings) -> Path:
  return settings.data_dir / "logs" / "prompt_history.jsonl"


def license_path(settings: Settings) -> Path:
  return settings.data_dir / "license.json"


def project_index_path(settings: Settings) -> Path:
  return settings.data_dir / "projects" / "index.json"


def prompt_presets_dir(settings: Settings) -> Path:
  return settings.data_dir / "prompts"


def active_prompt_preset_path(settings: Settings) -> Path:
  return prompt_presets_dir(settings) / "_active.json"


def styles_dir(settings: Settings) -> Path:
  return settings.data_dir / "styles"


def skills_dir(settings: Settings) -> Path:
  return settings.data_dir / "skills"


def character_replica_profiles_dir(settings: Settings) -> Path:
  return settings.data_dir / "character_replica_profiles"


def xp_presets_path(settings: Settings) -> Path:
  return settings.data_dir / "xp_presets.json"


def initialize_app_storage(settings: Settings) -> None:
  required_dirs = [
    settings.data_dir,
    settings.data_dir / "projects",
    settings.data_dir / "logs",
    settings.data_dir / "prompts",
    settings.data_dir / "styles",
    settings.data_dir / "skills",
    settings.data_dir / "character_replica_profiles",
    settings.data_dir / "cache",
  ]

  for directory in required_dirs:
    directory.mkdir(parents=True, exist_ok=True)

  if not app_config_path(settings).exists():
    save_config(settings, AppConfigUpdateRequest())

  if not project_index_path(settings).exists():
    atomic_write_json(project_index_path(settings), [])

  if not app_log_path(settings).exists():
    atomic_write_text(app_log_path(settings), "")
  if not prompt_history_path(settings).exists():
    atomic_write_text(prompt_history_path(settings), "")

  preset_files: dict[str, dict[str, object]] = {
    "网络小说.json": {
      "name": "网络小说",
      "description": "偏强钩子、偏快节奏、章节结尾强调悬念推进。",
      "prompts": {
        "architecture": "先明确核心卖点、主线冲突和适合连载展开的章节引擎。",
        "brainstorm": "优先给出连载向的强冲突、强钩子和可持续展开的问题。",
        "blueprint": "章节设计要强调悬念、推进和结尾牵引，适合连载阅读。",
        "chapter": "正文保持连载节奏，段落清楚，场景推进明确，结尾留有钩子。",
        "finalize": "定稿时压缩解释句，让冲突和情绪更直接。",
        "polish": "润色时增加画面感和对白张力，但不要拖慢节奏。",
        "humanize": "弱化模型腔，避免总结式表达和空泛抒情。",
      },
    },
    "严肃文学.json": {
      "name": "严肃文学",
      "description": "强调心理层次、叙述细密和意象组织。",
      "prompts": {
        "architecture": "先梳理人物处境、主题命题和叙事结构，不只给爽点和反转。",
        "brainstorm": "优先讨论人物处境、心理层次和叙事结构，不只给情节点子。",
        "blueprint": "章节设计要兼顾情节推进和意象递进，允许留白和层次。",
        "chapter": "正文要重视叙述质感、人物内在运动和场景细节。",
        "finalize": "定稿时保留细部观察和语言节奏，避免写成套路爽文。",
        "polish": "润色时加强意象、动作和心理之间的呼应。",
        "humanize": "保留自然节奏和停顿感，避免模板化总结。",
      },
    },
  }
  for filename, payload in preset_files.items():
    path = prompt_presets_dir(settings) / filename
    if not path.exists():
      atomic_write_json(path, payload)

  if not active_prompt_preset_path(settings).exists():
    atomic_write_json(
      active_prompt_preset_path(settings),
      {"name": "网络小说", "updated_at": _now_iso()},
    )

  if not xp_presets_path(settings).exists():
    atomic_write_json(
      xp_presets_path(settings),
      [
        {
          "name": "悬疑推进",
          "content": "优先强化误导、追索、反转和信息延迟释放。",
        },
        {
          "name": "人物拉扯",
          "content": "优先强化人物欲望冲突、关系张力和情绪回收。",
        },
      ],
    )

  default_skill_behaviors: dict[str, dict[str, str]] = {
    "chapter-scenes": {
      "panel": "chapter-workflow",
      "mode": "scenes",
      "input_label": "拆场要求",
      "submit_label": "开始拆场",
    },
    "chapter-diagnose": {
      "panel": "chapter-workflow",
      "mode": "diagnose",
      "input_label": "诊断要求",
      "submit_label": "开始诊断",
    },
    "chapter-draft": {
      "panel": "chapter-workflow",
      "mode": "draft",
      "input_label": "续写要求",
      "submit_label": "开始续写",
    },
    "chapter-finalize": {
      "panel": "chapter-rewrite",
      "mode": "finalize",
      "input_label": "改稿要求",
      "submit_label": "开始定稿",
    },
    "chapter-polish": {
      "panel": "chapter-rewrite",
      "mode": "polish",
      "input_label": "改稿要求",
      "submit_label": "开始润色",
    },
    "chapter-humanize": {
      "panel": "chapter-rewrite",
      "mode": "humanize",
      "input_label": "改稿要求",
      "submit_label": "开始去 AI",
    },
  }

  default_skills = [
    {
      "id": "brainstorm",
      "badge": "聊",
      "name": "创意讨论",
      "description": "像编辑一样和你多轮讨论当前问题，先把该解决的事说透。",
      "category": "灵感",
      "scenes": ["开书", "卡文", "方向"],
      "accent": "sand",
      "section_id": "core",
      "section_title": "核心技能",
      "section_description": "围绕开书、卡文、整本推进和问题判断的主工具。",
      "section_order": 1,
      "order": 10,
      "requires_project": True,
      "requires_chapter": False,
    },
    {
      "id": "blueprint",
      "badge": "蓝",
      "name": "蓝图生成",
      "description": "把整本结构和章节推进重新排清楚，给出可写的章节蓝图。",
      "category": "章节",
      "scenes": ["蓝图", "主线", "章节"],
      "accent": "olive",
      "section_id": "core",
      "section_title": "核心技能",
      "section_description": "围绕开书、卡文、整本推进和问题判断的主工具。",
      "section_order": 1,
      "order": 20,
      "requires_project": True,
      "requires_chapter": False,
    },
    {
      "id": "architecture-stepper",
      "badge": "构",
      "name": "分步架构",
      "description": "按模块逐步生成核心种子、人物、世界、骨架和蓝图，适合边改边写回。",
      "category": "工具",
      "scenes": ["架构", "分步", "续写"],
      "accent": "olive",
      "section_id": "core",
      "section_title": "核心技能",
      "section_description": "围绕开书、卡文、整本推进和问题判断的主工具。",
      "section_order": 1,
      "order": 30,
      "requires_project": True,
      "requires_chapter": False,
    },
    {
      "id": "continue-project",
      "badge": "续",
      "name": "续写扩展",
      "description": "在现有项目基础上继续往后扩章，直接更新整本规划。",
      "category": "续写",
      "scenes": ["扩写", "后续", "整本"],
      "accent": "sand",
      "section_id": "core",
      "section_title": "核心技能",
      "section_description": "围绕开书、卡文、整本推进和问题判断的主工具。",
      "section_order": 1,
      "order": 40,
      "requires_project": True,
      "requires_chapter": False,
    },
    {
      "id": "consistency",
      "badge": "检",
      "name": "一致性检查",
      "description": "检查人物动机、设定前后、空间时间和信息揭示顺序。",
      "category": "人物",
      "scenes": ["检查", "前后", "逻辑"],
      "accent": "slate",
      "section_id": "core",
      "section_title": "核心技能",
      "section_description": "围绕开书、卡文、整本推进和问题判断的主工具。",
      "section_order": 1,
      "order": 50,
      "requires_project": True,
      "requires_chapter": True,
    },
    {
      "id": "character-replica",
      "badge": "像",
      "name": "人物复刻",
      "description": "提炼某个人物的判断框架、语气和边界，再按这个视角回答你的问题。",
      "category": "人物",
      "scenes": ["人物", "视角", "复刻"],
      "accent": "smoke",
      "section_id": "core",
      "section_title": "核心技能",
      "section_description": "围绕开书、卡文、整本推进和问题判断的主工具。",
      "section_order": 1,
      "order": 55,
      "requires_project": False,
      "requires_chapter": False,
    },
    {
      "id": "chapter-scenes",
      "badge": "拆",
      "name": "章节拆场",
      "description": "把一章拆成 4 到 6 个场景，明确目标、冲突和转折。",
      "category": "章节",
      "scenes": ["场景", "结构", "钩子"],
      "accent": "olive",
      "section_id": "chapter-workflow",
      "section_title": "章节工作流",
      "section_description": "直接围绕当前章节处理拆场、生成、定稿和批量推进。",
      "section_order": 2,
      "order": 10,
      "requires_project": True,
      "requires_chapter": True,
    },
    {
      "id": "chapter-diagnose",
      "badge": "诊",
      "name": "章节诊断",
      "description": "先判断这一章最该改哪里，适合卡在节奏、冲突或结尾时使用。",
      "category": "章节",
      "scenes": ["诊断", "节奏", "问题"],
      "accent": "slate",
      "section_id": "chapter-workflow",
      "section_title": "章节工作流",
      "section_description": "直接围绕当前章节处理拆场、生成、定稿和批量推进。",
      "section_order": 2,
      "order": 20,
      "requires_project": True,
      "requires_chapter": True,
    },
    {
      "id": "chapter-generate",
      "badge": "写",
      "name": "章节生成",
      "description": "围绕当前章节上下文生成一版可直接保存的正文。",
      "category": "章节",
      "scenes": ["正文", "初稿", "推进"],
      "accent": "sand",
      "section_id": "chapter-workflow",
      "section_title": "章节工作流",
      "section_description": "直接围绕当前章节处理拆场、生成、定稿和批量推进。",
      "section_order": 2,
      "order": 30,
      "requires_project": True,
      "requires_chapter": True,
    },
    {
      "id": "chapter-draft",
      "badge": "续",
      "name": "续写正文",
      "description": "沿着当前章节状态继续往下写，适合已经有场景方向时直接开写。",
      "category": "续写",
      "scenes": ["续写", "正文", "承接"],
      "accent": "sand",
      "section_id": "chapter-workflow",
      "section_title": "章节工作流",
      "section_description": "直接围绕当前章节处理拆场、生成、定稿和批量推进。",
      "section_order": 2,
      "order": 40,
      "requires_project": True,
      "requires_chapter": True,
    },
    {
      "id": "chapter-finalize",
      "badge": "定",
      "name": "定稿整理",
      "description": "把当前章节整理成更完整的稿子，收紧结构和重复信息。",
      "category": "章节",
      "scenes": ["定稿", "重写", "结构"],
      "accent": "slate",
      "section_id": "chapter-workflow",
      "section_title": "章节工作流",
      "section_description": "直接围绕当前章节处理拆场、生成、定稿和批量推进。",
      "section_order": 2,
      "order": 50,
      "requires_project": True,
      "requires_chapter": True,
    },
    {
      "id": "chapter-polish",
      "badge": "润",
      "name": "场景润色",
      "description": "加强对白、画面和节奏，不改大方向，只改读感。",
      "category": "风格",
      "scenes": ["润色", "对白", "节奏"],
      "accent": "smoke",
      "section_id": "chapter-workflow",
      "section_title": "章节工作流",
      "section_description": "直接围绕当前章节处理拆场、生成、定稿和批量推进。",
      "section_order": 2,
      "order": 60,
      "requires_project": True,
      "requires_chapter": True,
    },
    {
      "id": "chapter-humanize",
      "badge": "人",
      "name": "去 AI",
      "description": "按去痕规则压掉模板腔和说明腔，并给出前后评分变化。",
      "category": "风格",
      "scenes": ["去AI", "语气", "自然"],
      "accent": "smoke",
      "section_id": "chapter-workflow",
      "section_title": "章节工作流",
      "section_description": "直接围绕当前章节处理拆场、生成、定稿和批量推进。",
      "section_order": 2,
      "order": 70,
      "requires_project": True,
      "requires_chapter": True,
    },
    {
      "id": "batch-generate",
      "badge": "批",
      "name": "批量生成",
      "description": "连续生成多个章节并自动写回项目，适合快速铺量。",
      "category": "续写",
      "scenes": ["批量", "多章", "连写"],
      "accent": "olive",
      "section_id": "chapter-workflow",
      "section_title": "章节工作流",
      "section_description": "直接围绕当前章节处理拆场、生成、定稿和批量推进。",
      "section_order": 2,
      "order": 80,
      "requires_project": True,
      "requires_chapter": False,
    },
    {
      "id": "style-dna",
      "badge": "风",
      "name": "文风与DNA",
      "description": "分析样文、融合文风、维护作者参考库，并保存成可复用方案。",
      "category": "风格",
      "scenes": ["文风", "DNA", "参考"],
      "accent": "smoke",
      "section_id": "styles-and-tools",
      "section_title": "风格与工具",
      "section_description": "把文风、提示词、项目文件和运行记录都收进当前技能区。",
      "section_order": 3,
      "order": 10,
      "requires_project": False,
      "requires_chapter": False,
    },
    {
      "id": "prompt-presets",
      "badge": "词",
      "name": "提示词方案",
      "description": "管理不同写作预设，切换当前全局提示词策略。",
      "category": "工具",
      "scenes": ["预设", "提示词", "切换"],
      "accent": "slate",
      "section_id": "styles-and-tools",
      "section_title": "风格与工具",
      "section_description": "把文风、提示词、项目文件和运行记录都收进当前技能区。",
      "section_order": 3,
      "order": 20,
      "requires_project": False,
      "requires_chapter": False,
    },
    {
      "id": "xp-presets",
      "badge": "XP",
      "name": "XP 预设",
      "description": "存放偏好的戏感方向，比如悬疑推进、人物拉扯、反转控制。",
      "category": "工具",
      "scenes": ["XP", "偏好", "强化"],
      "accent": "sand",
      "section_id": "styles-and-tools",
      "section_title": "风格与工具",
      "section_description": "把文风、提示词、项目文件和运行记录都收进当前技能区。",
      "section_order": 3,
      "order": 30,
      "requires_project": False,
      "requires_chapter": False,
    },
    {
      "id": "knowledge-search",
      "badge": "知",
      "name": "知识检索",
      "description": "直接在技能区里导入资料、检索设定和正文片段。",
      "category": "工具",
      "scenes": ["资料", "检索", "设定"],
      "accent": "olive",
      "section_id": "styles-and-tools",
      "section_title": "风格与工具",
      "section_description": "把文风、提示词、项目文件和运行记录都收进当前技能区。",
      "section_order": 3,
      "order": 40,
      "requires_project": True,
      "requires_chapter": False,
    },
    {
      "id": "web-research",
      "badge": "考",
      "name": "联网考据",
      "description": "查询历史典故、史实出处和可借鉴的写作素材。",
      "category": "工具",
      "scenes": ["典故", "史实", "联网"],
      "accent": "slate",
      "section_id": "styles-and-tools",
      "section_title": "风格与工具",
      "section_description": "把文风、提示词、项目文件和运行记录都收进当前技能区。",
      "section_order": 3,
      "order": 45,
      "requires_project": True,
      "requires_chapter": False,
    },
    {
      "id": "reader",
      "badge": "读",
      "name": "小说阅读",
      "description": "按章节顺着读当前项目正文，不切出技能页也能通读。",
      "category": "工具",
      "scenes": ["阅读", "章节", "通读"],
      "accent": "slate",
      "section_id": "styles-and-tools",
      "section_title": "风格与工具",
      "section_description": "把文风、提示词、项目文件和运行记录都收进当前技能区。",
      "section_order": 3,
      "order": 50,
      "requires_project": True,
      "requires_chapter": True,
    },
    {
      "id": "file-browser",
      "badge": "文",
      "name": "文件浏览",
      "description": "查看项目里的设定文件、章节文件和导出文件。",
      "category": "工具",
      "scenes": ["文件", "查看", "项目"],
      "accent": "slate",
      "section_id": "styles-and-tools",
      "section_title": "风格与工具",
      "section_description": "把文风、提示词、项目文件和运行记录都收进当前技能区。",
      "section_order": 3,
      "order": 60,
      "requires_project": True,
      "requires_chapter": False,
    },
    {
      "id": "logs",
      "badge": "志",
      "name": "运行日志",
      "description": "查看 backend 当前日志，出问题时直接在这里看。",
      "category": "工具",
      "scenes": ["日志", "排查", "运行"],
      "accent": "slate",
      "section_id": "styles-and-tools",
      "section_title": "风格与工具",
      "section_description": "把文风、提示词、项目文件和运行记录都收进当前技能区。",
      "section_order": 3,
      "order": 70,
      "requires_project": False,
      "requires_chapter": False,
    },
    {
      "id": "prompt-history",
      "badge": "史",
      "name": "Prompt 历史",
      "description": "查看模型请求和返回记录，便于复盘和调预设。",
      "category": "工具",
      "scenes": ["历史", "Prompt", "复盘"],
      "accent": "smoke",
      "section_id": "styles-and-tools",
      "section_title": "风格与工具",
      "section_description": "把文风、提示词、项目文件和运行记录都收进当前技能区。",
      "section_order": 3,
      "order": 80,
      "requires_project": False,
      "requires_chapter": False,
    },
  ]

  for payload in default_skills:
    skill_payload = dict(payload)
    behavior = default_skill_behaviors.get(str(skill_payload["id"]))
    if behavior and "behavior" not in skill_payload:
      skill_payload["behavior"] = behavior

    section_dir = skills_dir(settings) / str(skill_payload["section_id"])
    section_dir.mkdir(parents=True, exist_ok=True)
    path = section_dir / f"{skill_payload['id']}.json"
    existing_payload = read_json(path, None)
    if isinstance(existing_payload, dict) and behavior and "behavior" not in existing_payload:
      atomic_write_json(path, {**existing_payload, "behavior": behavior})
      continue
    if not path.exists():
      atomic_write_json(path, skill_payload)


def load_config(settings: Settings) -> AppConfig:
  payload = read_json(app_config_path(settings), None)
  if payload is None:
    return save_config(settings, AppConfigUpdateRequest())

  if isinstance(payload, dict) and "model" not in payload:
    return save_config(
      settings,
      AppConfigUpdateRequest(
        model=ModelConfig.model_validate(payload),
        embedding=EmbeddingConfig(),
      ),
    )

  parsed = AppConfig.model_validate(payload)
  normalized = parsed.model_copy(
    update={"embedding": resolve_embedding_config(parsed.model, parsed.embedding)}
  )
  if normalized.model_dump(mode="json") != parsed.model_dump(mode="json"):
    atomic_write_json(app_config_path(settings), normalized.model_dump(mode="json"))
  return normalized


def _existing_review_model_config(settings: Settings) -> ReviewModelConfig:
  payload = read_json(app_config_path(settings), None)
  if isinstance(payload, dict) and isinstance(payload.get("review_model"), dict):
    return ReviewModelConfig.model_validate(payload["review_model"])
  return ReviewModelConfig()


def save_config(settings: Settings, config_update: AppConfigUpdateRequest | ModelConfig) -> AppConfig:
  if isinstance(config_update, ModelConfig):
    model_config = config_update
    embedding_config = resolve_embedding_config(model_config)
    review_model_config = _existing_review_model_config(settings)
  else:
    model_config = config_update.model
    embedding_config = resolve_embedding_config(model_config, config_update.embedding)
    review_model_config = ReviewModelConfig.model_validate(config_update.review_model)
  payload = AppConfig(
    model=model_config,
    embedding=embedding_config,
    review_model=review_model_config,
    updated_at=_now_iso(),
  )
  atomic_write_json(app_config_path(settings), payload.model_dump(mode="json"))
  return payload
