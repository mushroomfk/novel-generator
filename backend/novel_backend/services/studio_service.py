from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException

from novel_backend.config import Settings
from novel_backend.models import (
  BatchGenerateChapterResult,
  BatchGenerateRequest,
  BatchGenerateResult,
  BlueprintChapterOutline,
  BlueprintGenerateRequest,
  BlueprintGenerateResult,
  BrainstormRequest,
  BrainstormResult,
  CharacterReplicaRequest,
  CharacterReplicaResult,
  ChapterGenerateRequest,
  ChapterGenerateResult,
  ChapterRewriteRequest,
  ChapterRewriteResult,
  ChapterUpdateRequest,
  ConsistencyCheckRequest,
  ConsistencyCheckResult,
  ConsistencyIssue,
  ContinueProjectRequest,
  ContinueProjectResult,
  StoryDocumentBatchUpdateRequest,
  StoryDocumentPatch,
  StyleAnalysisResult,
  StyleAnalyzeRequest,
  StyleCalibrateRequest,
  StyleDNAAnalyzeRequest,
  StyleDetail,
  StyleMergeRequest,
)
from novel_backend.services.context_builder import (
  build_project_context_bundle,
  build_prompt_support,
  project_documents_map,
)
from novel_backend.services.chapter_auto_repair_service import auto_repair_chapter_after_review
from novel_backend.services.project_dream_service import build_project_dream_prompt_block
from novel_backend.services.generation_service import (
  _compact_text,
  _extract_json_object,
  _invoke_model,
  _run_continuation_pipeline,
  _string_from_keys,
  _string_list_from_keys,
  _strip_code_fence,
)
from novel_backend.services.humanize_service import (
  build_humanize_fallback_changes,
  build_humanize_prompt_block,
  build_humanize_quality_report,
)
from novel_backend.services.log_service import append_app_log
from novel_backend.services.project_service import (
  get_project_detail,
  summarize_chapter_review_status,
  update_chapter_content_with_review_status,
  update_project_targets,
  update_story_documents,
)
from novel_backend.services.skill_service import get_custom_skill_prompt, suggest_reusable_skill
from novel_backend.services.style_service import get_style
from novel_backend.services.style_service import rollback_style_calibration, save_style_detail, style_calibration_snapshot
from novel_backend.utils.jsonfile import atomic_write_json, read_json
from novel_backend.utils.sse import encode_sse


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


_BRAINSTORM_SYSTEM_PROMPT = """
你是中文长篇小说的陪跑编辑，负责在创作过程中和作者一起推进问题。

输出要求：
1. 只输出一个 JSON 对象。
2. JSON 字段固定为：reply、suggestions。
3. reply 用自然中文直接回答作者问题，给出明确判断和可执行方向。
4. suggestions 给 2 到 4 条下一轮值得继续追问的问题。
""".strip()

_CHARACTER_REPLICA_SYSTEM_PROMPT = """
你是人物视角提炼编辑，负责根据公开信息和用户补充资料，整理一个人物的判断方式，并把它用于当前问题。

输出要求：
1. 只输出一个 JSON 对象。
2. JSON 字段固定为：headline、summary、voice_profile、mental_models、heuristics、boundaries、answer、disclaimer。
3. mental_models 给 3 到 5 条，只保留真正有辨识度的认知框架。
4. heuristics 给 3 到 6 条，写成可执行的判断原则。
5. boundaries 至少 2 条，说明资料不足、适用边界或容易误判的地方。
6. answer 用自然中文回答用户问题，语气可以贴近人物，但不要写成夸张模仿秀。
7. disclaimer 要明确说明这是基于公开表达和用户补充资料做的推断，不是假装当事人本人。
""".strip()

_CONSISTENCY_SYSTEM_PROMPT = """
你是中文小说一致性检查编辑。

输出要求：
1. 只输出一个 JSON 对象。
2. JSON 字段固定为：summary、issues、suggestions。
3. issues 是数组，每项包含 level、title、detail。
4. level 只能是 info、warning、critical。
5. 重点检查人物动机、设定前后、信息揭示顺序、空间时间连续性。
""".strip()

_BLUEPRINT_SYSTEM_PROMPT = """
你是中文长篇小说蓝图策划编辑。

输出要求：
1. 只输出一个 JSON 对象。
2. JSON 字段固定为：headline、summary、blueprint、chapters。
3. blueprint 是可直接写入章节蓝图文件的正文。
4. chapters 是数组，每项包含 chapter_id、title、goal、hook。
5. chapter_id 使用 chapter-001 这种格式。
""".strip()

_CHAPTER_GENERATE_SYSTEM_PROMPT = """
你是中文小说章节写手。

输出要求：
1. 只输出一个 JSON 对象。
2. JSON 字段固定为：headline、summary、content、next_action。
3. content 必须是可直接保存的章节正文，第一行使用 Markdown 标题。
4. 正文不要再输出额外说明。
5. 如果上下文里已经给出参考资料、原作承接、参考人物、参考事件或上一章末尾，正文必须沿着这些事实往后接，不能改名、改关系、改事件结果，也不能另起一套剧情。
""".strip()

_CHAPTER_REWRITE_SYSTEM_PROMPT = """
你是中文小说改稿编辑。

输出要求：
1. 只输出一个 JSON 对象。
2. JSON 字段固定为：headline、summary、revised、changes、updated_summary、updated_character_state。
3. revised 是可直接保存的修订正文，第一行使用 Markdown 标题。
4. changes 是 3 到 6 条修改说明。
5. updated_summary 和 updated_character_state 只有在确实需要时才填写。
""".strip()

_CHAPTER_HUMANIZE_SYSTEM_PROMPT = """
你是中文小说去 AI 改稿编辑，参考内置中文去痕规则处理小说正文。

输出要求：
1. 只输出一个 JSON 对象。
2. JSON 字段固定为：headline、summary、revised、changes、updated_summary、updated_character_state。
3. revised 是可直接保存的修订正文，第一行保留 Markdown 标题。
4. changes 是 3 到 6 条真实做过的语言层修改。
5. 只改语言和结构，不改剧情事实、信息顺序、人物关系和事件结果。
6. 不要输出解释报告、评分表或额外附言。
""".strip()

_CONTINUE_SYSTEM_PROMPT = """
你是长篇小说项目总编，负责在已有作品基础上继续扩写整本规划。

输出要求：
1. 只输出一个 JSON 对象。
2. JSON 字段固定为：headline、summary、plot_structure、world_building、character_design、character_state、blueprint。
3. 内容要和现有项目衔接，不要推翻已经写出的正文。
4. 如果项目里有参考资料或原作信息，规划必须写成承接版，沿用既有人物、关系和事件，不要另造设定。
""".strip()

_STYLE_ANALYZE_SYSTEM_PROMPT = """
你是中文叙事风格分析编辑。

输出要求：
1. 只输出一个 JSON 对象。
2. JSON 字段固定为：instruction、analysis、dna_analysis、narrative_for_architecture、narrative_for_blueprint、narrative_for_chapter、calibration_notes。
3. instruction 写成一段后续可直接喂给模型的文风指令。
4. analysis 要说清句法、节奏、视角距离、意象偏好、人物书写方式。
""".strip()

_STYLE_DNA_SYSTEM_PROMPT = """
你是中文小说文风 DNA 分析编辑。

输出要求：
1. 只输出一个 JSON 对象。
2. JSON 字段固定为：instruction、analysis、dna_analysis、narrative_for_architecture、narrative_for_blueprint、narrative_for_chapter、calibration_notes。
3. dna_analysis 要明确叙述视角、镜头距离、信息释放方式、对白密度、动作与心理的比例。
4. calibration_notes 写这次分析最值得后续校准的 2 到 4 个点。
5. 其他字段保持可直接保存和复用。
""".strip()

_STYLE_CALIBRATE_SYSTEM_PROMPT = """
你是中文小说文风校准编辑。

输出要求：
1. 只输出一个 JSON 对象。
2. JSON 字段固定为：instruction、analysis、dna_analysis、narrative_for_architecture、narrative_for_blueprint、narrative_for_chapter、calibration_notes。
3. 你要根据现有文风、样文和补充要求，把文风方案往样文靠拢，但不能丢掉可复用性。
4. calibration_notes 要写清本轮校准后还剩什么偏差。
""".strip()

_STYLE_NARRATIVE_CALIBRATE_SYSTEM_PROMPT = """
你是中文小说叙事 DNA 校准编辑。

输出要求：
1. 只输出一个 JSON 对象。
2. JSON 字段固定为：instruction、analysis、dna_analysis、narrative_for_architecture、narrative_for_blueprint、narrative_for_chapter、calibration_notes。
3. 本轮重点是修正文风方案中的叙事要求，让架构、蓝图、正文三个阶段各自有清楚约束。
4. instruction 和 analysis 只做必要微调，主要更新 narrative_* 字段。
""".strip()


def _documents_map(project_detail) -> dict[str, str]:
  return project_documents_map(project_detail)


def _project_context_text(
  settings: Settings,
  project_id: str,
  *,
  include_blueprint: bool = True,
  include_character_state: bool = True,
  chapter_id: str = "",
  knowledge_query: str = "",
  knowledge_limit: int = 5,
  task_pack_kind: str = "",
  task_instruction: str = "",
  rewrite_mode: str = "",
) -> tuple[object, dict[str, str], object | None, str]:
  bundle = build_project_context_bundle(
    settings,
    project_id,
    include_blueprint=include_blueprint,
    include_character_state=include_character_state,
    chapter_id=chapter_id,
    knowledge_query=knowledge_query,
    knowledge_limit=knowledge_limit,
    task_pack_kind=task_pack_kind,
    task_instruction=task_instruction,
    rewrite_mode=rewrite_mode,
  )
  if chapter_id and bundle.chapter is None:
    raise HTTPException(
      status_code=404,
      detail={"code": "chapter_not_found", "message": "章节不存在"},
    )
  return bundle.project_detail, bundle.documents, bundle.chapter, bundle.context_text


def _apply_preset_and_style(
  settings: Settings,
  *,
  task_key: str,
  style_name: str = "",
  style_task_type: str = "chapter",
  style_query: str = "",
  xp_name: str = "",
) -> str:
  return build_prompt_support(
    settings,
    task_key=task_key,
    style_name=style_name,
    style_task_type=style_task_type,
    style_query=style_query,
    xp_name=xp_name,
  )


def _outline_list(payload: dict[str, object]) -> list[BlueprintChapterOutline]:
  raw_items = payload.get("chapters")
  if not isinstance(raw_items, list):
    return []
  outlines: list[BlueprintChapterOutline] = []
  for index, item in enumerate(raw_items, start=1):
    if not isinstance(item, dict):
      continue
    chapter_id = _string_from_keys(item, "chapter_id", "id") or f"chapter-{index:03d}"
    title = _string_from_keys(item, "title", "章节", "name") or f"第 {index} 章"
    goal = _string_from_keys(item, "goal", "目标") or "推进主线"
    hook = _string_from_keys(item, "hook", "钩子", "转折") or "留出下一章悬念"
    outlines.append(
      BlueprintChapterOutline(
        chapter_id=chapter_id,
        title=title,
        goal=goal,
        hook=hook,
      )
    )
  return outlines


def _parse_brainstorm_result(text: str, task_id: str) -> BrainstormResult:
  payload = _extract_json_object(text)
  if isinstance(payload, dict):
    reply = _string_from_keys(payload, "reply", "answer", "content")
    suggestions = _string_list_from_keys(payload, "suggestions", "next_questions", "questions")
    if reply:
      return BrainstormResult(task_id=task_id, reply=reply, suggestions=suggestions)

  cleaned = _strip_code_fence(text)
  lines = [item.strip(" -0123456789.、）)") for item in cleaned.splitlines() if item.strip()]
  reply = lines[0] if lines else cleaned
  suggestions = [item for item in lines[1:4] if item]
  return BrainstormResult(task_id=task_id, reply=reply, suggestions=suggestions)


def _parse_character_replica_result(text: str, task_id: str) -> CharacterReplicaResult:
  payload = _extract_json_object(text)
  if isinstance(payload, dict):
    headline = _string_from_keys(payload, "headline", "title", "name")
    summary = _string_from_keys(payload, "summary", "analysis", "说明")
    voice_profile = _string_from_keys(payload, "voice_profile", "voice", "表达特征")
    mental_models = _string_list_from_keys(payload, "mental_models", "models", "认知框架")
    heuristics = _string_list_from_keys(payload, "heuristics", "principles", "判断原则")
    boundaries = _string_list_from_keys(payload, "boundaries", "limits", "边界")
    answer = _string_from_keys(payload, "answer", "reply", "content")
    disclaimer = _string_from_keys(payload, "disclaimer", "note", "说明")
    if answer or summary or mental_models:
      return CharacterReplicaResult(
        task_id=task_id,
        headline=headline or "人物视角已经整理好",
        summary=summary or "已提炼这个人物的判断方式和适用边界。",
        voice_profile=voice_profile,
        mental_models=mental_models,
        heuristics=heuristics,
        boundaries=boundaries,
        answer=answer or summary or _strip_code_fence(text),
        disclaimer=disclaimer,
      )

  cleaned = _strip_code_fence(text)
  return CharacterReplicaResult(
    task_id=task_id,
    headline="人物视角已经整理好",
    summary=_compact_text(cleaned, 120),
    voice_profile="",
    mental_models=[],
    heuristics=[],
    boundaries=["模型没有按结构化格式返回，当前结果更适合人工复核。"],
    answer=cleaned,
    disclaimer="这是基于公开信息和输入内容整理出的近似视角，不等于人物本人。",
  )


def _parse_consistency_result(text: str, task_id: str) -> ConsistencyCheckResult:
  payload = _extract_json_object(text)
  if isinstance(payload, dict):
    issues: list[ConsistencyIssue] = []
    raw_issues = payload.get("issues")
    if isinstance(raw_issues, list):
      for item in raw_issues:
        if not isinstance(item, dict):
          continue
        title = _string_from_keys(item, "title", "问题")
        detail = _string_from_keys(item, "detail", "说明", "analysis")
        if not title and not detail:
          continue
        issues.append(
          ConsistencyIssue(
            level=_string_from_keys(item, "level") or "warning",
            title=title or "潜在一致性问题",
            detail=detail or title,
          )
        )
    summary = _string_from_keys(payload, "summary", "headline", "结论")
    suggestions = _string_list_from_keys(payload, "suggestions", "actions", "checklist")
    if summary or issues or suggestions:
      return ConsistencyCheckResult(
        task_id=task_id,
        summary=summary or "已整理当前章节的一致性风险。",
        issues=issues,
        suggestions=suggestions,
      )

  cleaned = _strip_code_fence(text)
  return ConsistencyCheckResult(
    task_id=task_id,
    summary=_compact_text(cleaned, 120),
    issues=[ConsistencyIssue(level="warning", title="模型返回未结构化", detail=cleaned)],
    suggestions=[],
  )


def _parse_blueprint_result(text: str, task_id: str) -> BlueprintGenerateResult:
  payload = _extract_json_object(text)
  if isinstance(payload, dict):
    headline = _string_from_keys(payload, "headline", "title", "判断")
    summary = _string_from_keys(payload, "summary", "说明")
    blueprint = _string_from_keys(payload, "blueprint", "content", "正文")
    outlines = _outline_list(payload)
    if headline or summary or blueprint:
      return BlueprintGenerateResult(
        task_id=task_id,
        headline=headline or "已生成章节蓝图",
        summary=summary or headline or "可直接写回项目蓝图文件。",
        blueprint=blueprint or _strip_code_fence(text),
        chapters=outlines,
      )

  cleaned = _strip_code_fence(text)
  return BlueprintGenerateResult(
    task_id=task_id,
    headline="已生成章节蓝图",
    summary=_compact_text(cleaned, 120),
    blueprint=cleaned,
    chapters=[],
  )


def _parse_chapter_generate_result(text: str, task_id: str) -> ChapterGenerateResult:
  payload = _extract_json_object(text)
  if isinstance(payload, dict):
    headline = _string_from_keys(payload, "headline", "title", "判断")
    summary = _string_from_keys(payload, "summary", "说明")
    content = _string_from_keys(payload, "content", "draft", "正文")
    next_action = _string_from_keys(payload, "next_action", "下一步")
    if content:
      return ChapterGenerateResult(
        task_id=task_id,
        headline=headline or "章节初稿已生成",
        summary=summary or headline or "可以继续修改后保存。",
        content=content,
        next_action=next_action,
      )

  cleaned = _strip_code_fence(text)
  return ChapterGenerateResult(
    task_id=task_id,
    headline="章节初稿已生成",
    summary=_compact_text(cleaned, 120),
    content=cleaned,
    next_action="先检查本章目标和结尾钩子。",
  )


def _parse_rewrite_result(text: str, task_id: str) -> ChapterRewriteResult:
  payload = _extract_json_object(text)
  if isinstance(payload, dict):
    headline = _string_from_keys(payload, "headline", "title", "判断")
    summary = _string_from_keys(payload, "summary", "说明")
    revised = _string_from_keys(payload, "revised", "content", "正文")
    changes = _string_list_from_keys(payload, "changes", "checklist", "points")
    updated_summary = _string_from_keys(payload, "updated_summary", "summary_update")
    updated_character_state = _string_from_keys(payload, "updated_character_state", "state_update")
    original = _string_from_keys(payload, "original")
    if revised:
      return ChapterRewriteResult(
        task_id=task_id,
        headline=headline or "已生成修订稿",
        summary=summary or headline or "正文已经按要求重写。",
        original=original,
        revised=revised,
        changes=changes,
        updated_summary=updated_summary,
        updated_character_state=updated_character_state,
      )

  cleaned = _strip_code_fence(text)
  return ChapterRewriteResult(
    task_id=task_id,
    headline="已生成修订稿",
    summary=_compact_text(cleaned, 120),
    original="",
    revised=cleaned,
    changes=[],
    updated_summary="",
    updated_character_state="",
  )


def _parse_continue_result(text: str, task_id: str, target_chapters: int) -> ContinueProjectResult:
  payload = _extract_json_object(text)
  if isinstance(payload, dict):
    headline = _string_from_keys(payload, "headline", "title", "判断")
    summary = _string_from_keys(payload, "summary", "说明")
    plot_structure = _string_from_keys(payload, "plot_structure", "plot")
    world_building = _string_from_keys(payload, "world_building", "world")
    character_design = _string_from_keys(payload, "character_design", "characters")
    character_state = _string_from_keys(payload, "character_state", "state")
    blueprint = _string_from_keys(payload, "blueprint", "content")
    if any([plot_structure, world_building, character_design, blueprint]):
      return ContinueProjectResult(
        task_id=task_id,
        headline=headline or "整本规划已扩写",
        summary=summary or headline or "新的章节规划已经整理好。",
        target_chapters=target_chapters,
        plot_structure=plot_structure,
        world_building=world_building,
        character_design=character_design,
        character_state=character_state,
        blueprint=blueprint,
      )

  cleaned = _strip_code_fence(text)
  return ContinueProjectResult(
    task_id=task_id,
    headline="整本规划已扩写",
    summary=_compact_text(cleaned, 120),
    target_chapters=target_chapters,
    plot_structure=cleaned,
    world_building="",
    character_design="",
    character_state="",
    blueprint="",
  )


def _parse_style_result(text: str, task_id: str) -> StyleAnalysisResult:
  payload = _extract_json_object(text)
  if isinstance(payload, dict):
    instruction = _string_from_keys(payload, "instruction", "style_instruction")
    analysis = _string_from_keys(payload, "analysis", "summary")
    dna_analysis = _string_from_keys(payload, "dna_analysis", "dna", "style_dna")
    narrative_for_architecture = _string_from_keys(payload, "narrative_for_architecture")
    narrative_for_blueprint = _string_from_keys(payload, "narrative_for_blueprint")
    narrative_for_chapter = _string_from_keys(payload, "narrative_for_chapter")
    calibration_notes = _string_from_keys(payload, "calibration_notes", "notes")
    if instruction or analysis:
      return StyleAnalysisResult(
        task_id=task_id,
        instruction=instruction,
        analysis=analysis,
        dna_analysis=dna_analysis,
        narrative_for_architecture=narrative_for_architecture,
        narrative_for_blueprint=narrative_for_blueprint,
        narrative_for_chapter=narrative_for_chapter,
        calibration_notes=calibration_notes,
      )

  cleaned = _strip_code_fence(text)
  return StyleAnalysisResult(
    task_id=task_id,
    instruction=_compact_text(cleaned, 300),
    analysis=cleaned,
    dna_analysis="",
    narrative_for_architecture="",
    narrative_for_blueprint="",
    narrative_for_chapter="",
    calibration_notes="",
  )


def _brainstorm_messages(settings: Settings, payload: BrainstormRequest) -> list[dict[str, str]]:
  bundle = build_project_context_bundle(
    settings,
    payload.project_id,
    include_blueprint=payload.include_blueprint,
    include_character_state=payload.include_character_state,
    knowledge_query=payload.extra_context,
  )
  project_detail = bundle.project_detail
  documents = bundle.documents
  context_lines = [f"作品：{project_detail.name}", f"类型：{project_detail.genre}"]
  if payload.include_core_seed:
    context_lines.append(f"核心种子：{_compact_text(documents.get('core_seed', ''), 260) or '无'}")
  if payload.include_characters:
    context_lines.append(f"人物设定：{_compact_text(documents.get('character_design', ''), 320) or '无'}")
  if payload.include_world_building:
    context_lines.append(f"世界设定：{_compact_text(documents.get('world_building', ''), 320) or '无'}")
  if payload.include_plot:
    context_lines.append(f"情节骨架：{_compact_text(documents.get('plot_structure', ''), 320) or '无'}")
  if payload.include_blueprint:
    context_lines.append(f"章节蓝图：{_compact_text(documents.get('blueprint', ''), 320) or '无'}")
  if payload.include_character_state:
    context_lines.append(f"人物状态：{_compact_text(documents.get('character_state', ''), 320) or '无'}")
  memory_line = next(
    (line for line in bundle.context_lines if str(line).startswith("项目记忆：")),
    "",
  )
  if memory_line and not memory_line.endswith("无"):
    context_lines.append(memory_line)
  dream_text = build_project_dream_prompt_block(project_detail)
  if dream_text:
    context_lines.append(dream_text)
  if payload.extra_context.strip():
    context_lines.append(f"额外上下文：{payload.extra_context.strip()}")

  messages = [{"role": "system", "content": _BRAINSTORM_SYSTEM_PROMPT}]
  messages.append({"role": "system", "content": "\n".join(context_lines)})
  active_skill_prompt = get_custom_skill_prompt(settings, payload.skill_id)
  if active_skill_prompt:
    messages.append({"role": "system", "content": active_skill_prompt})
  for item in payload.messages:
    messages.append({"role": item.role, "content": item.content})
  support = build_prompt_support(settings, task_key="brainstorm")
  if support:
    messages.append({"role": "system", "content": f"额外要求：{support}"})
  return messages


def _character_replica_messages(settings: Settings, payload: CharacterReplicaRequest) -> list[dict[str, str]]:
  context_blocks: list[str] = []
  if payload.project_id.strip() and payload.include_project_context:
    project_detail, _documents, chapter, context_text = _project_context_text(
      settings,
      payload.project_id.strip(),
      include_blueprint=True,
      include_character_state=True,
      chapter_id=payload.chapter_id.strip() if payload.include_chapter_context else "",
      knowledge_query=" ".join(
        item for item in [
          payload.persona_name,
          payload.question,
          payload.focus,
        ] if item.strip()
      ),
      task_pack_kind="persona",
      task_instruction=" ".join(
        item for item in [
          payload.persona_name,
          payload.question,
          payload.focus,
        ] if item.strip()
      ),
    )
    context_blocks.append(f"当前作品：{project_detail.name}")
    if payload.include_chapter_context and chapter is not None:
      context_blocks.append(f"当前章节：第 {chapter.index} 章《{chapter.title}》")
    context_blocks.append(context_text)

  context_block = "\n\n".join(block.strip() for block in context_blocks if block.strip())
  project_context_text = f"项目上下文：\n{context_block}" if context_block else "项目上下文：无"
  return [
    {"role": "system", "content": _CHARACTER_REPLICA_SYSTEM_PROMPT},
    {
      "role": "user",
      "content": (
        f"人物名称：{payload.persona_name.strip()}\n"
        f"当前问题：{payload.question.strip()}\n"
        f"希望强调：{payload.focus.strip() or '无'}\n"
        f"补充资料：\n{payload.source_notes.strip() or '无'}\n\n"
        f"{project_context_text}\n\n"
        "请先提炼这个人物的表达特征、判断框架和边界，再用这个视角回答当前问题。"
      ).strip(),
    },
  ]


def _consistency_messages(settings: Settings, payload: ConsistencyCheckRequest) -> list[dict[str, str]]:
  _project_detail, _documents, chapter, context_text = _project_context_text(
    settings,
    payload.project_id,
    include_blueprint=True,
    include_character_state=True,
    chapter_id=payload.chapter_id,
    knowledge_query=f"{payload.focus} {payload.chapter_id}",
    task_pack_kind="continuation",
    task_instruction=payload.focus,
  )
  return [
    {"role": "system", "content": _CONSISTENCY_SYSTEM_PROMPT},
    {
      "role": "user",
      "content": (
        f"{context_text}\n\n"
        f"本次检查重点：{payload.focus.strip() or '人物动机、设定前后、信息揭示顺序、空间时间连续性'}\n"
        f"请围绕《{chapter.title}》给出一致性检查。"
      ),
    },
  ]


def _blueprint_messages(settings: Settings, payload: BlueprintGenerateRequest) -> list[dict[str, str]]:
  project_detail, documents, _chapter, context_text = _project_context_text(
    settings,
    payload.project_id,
    include_blueprint=True,
    include_character_state=True,
    knowledge_query=payload.instruction,
    task_pack_kind="architecture",
    task_instruction=payload.instruction,
  )
  target_count = payload.chapter_count or project_detail.target_chapters
  style_pack = _apply_preset_and_style(
    settings,
    task_key="blueprint",
    style_name=payload.style_name,
    style_task_type="blueprint",
    style_query=payload.instruction or documents.get("blueprint", ""),
    xp_name=payload.xp_preset,
  )
  dream_text = build_project_dream_prompt_block(project_detail)
  dream_block = f"{dream_text}\n\n" if dream_text else ""
  return [
    {"role": "system", "content": _BLUEPRINT_SYSTEM_PROMPT},
    {
      "role": "user",
      "content": (
        f"{context_text}\n\n"
        f"{dream_block}"
        f"请为这部作品重新整理章节蓝图。\n"
        f"目标章节数：{target_count}\n"
        f"用户补充：{payload.instruction.strip() or '无'}\n"
        f"{style_pack or ''}"
      ).strip(),
    },
  ]


def _chapter_generate_messages(settings: Settings, payload: ChapterGenerateRequest) -> list[dict[str, str]]:
  project_detail, documents, chapter, context_text = _project_context_text(
    settings,
    payload.project_id,
    include_blueprint=True,
    include_character_state=True,
    chapter_id=payload.chapter_id,
    knowledge_query=" ".join(
      item for item in [
        payload.instruction,
        payload.characters_involved,
        payload.key_items,
        payload.scene_location,
      ] if item.strip()
    ),
    task_pack_kind="continuation",
    task_instruction=payload.instruction,
  )
  style_pack = _apply_preset_and_style(
    settings,
    task_key="chapter",
    style_name=payload.style_name,
    style_task_type="chapter",
    style_query=f"{chapter.title} {payload.instruction}",
    xp_name=payload.xp_preset,
  )
  return [
    {"role": "system", "content": _CHAPTER_GENERATE_SYSTEM_PROMPT},
    {
      "role": "user",
      "content": (
        f"{context_text}\n\n"
        f"请为《{project_detail.name}》生成第 {chapter.index} 章《{chapter.title}》的正文。\n"
        "如果项目里已经导入原著或前文资料，这一章必须接着那些已确认事实继续写，不要自己改人物和事件走向。\n"
        f"写作补充：{payload.instruction.strip() or '无'}\n"
        f"涉及人物：{payload.characters_involved.strip() or '无'}\n"
        f"关键道具或线索：{payload.key_items.strip() or '无'}\n"
        f"场景地点：{payload.scene_location.strip() or '无'}\n"
        f"时间限制：{payload.time_constraint.strip() or '无'}\n"
        f"{style_pack or ''}"
      ).strip(),
    },
  ]


def _chapter_rewrite_messages(settings: Settings, payload: ChapterRewriteRequest, mode: str) -> list[dict[str, str]]:
  project_detail, documents, chapter, context_text = _project_context_text(
    settings,
    payload.project_id,
    include_blueprint=True,
    include_character_state=True,
    chapter_id=payload.chapter_id,
    knowledge_query=payload.instruction,
    task_pack_kind="imitation" if mode == "humanize" else "continuation",
    task_instruction=payload.instruction,
    rewrite_mode=mode,
  )
  if not chapter.content.strip():
    raise RuntimeError("当前章节还没有正文，不能直接改稿")
  if mode == "humanize":
    return _chapter_humanize_messages(settings, payload, project_detail, chapter, context_text)
  task_key = "finalize" if mode == "finalize" else "polish" if mode == "polish" else "humanize"
  mode_text = {
    "finalize": "请把这一章整理成定稿，统一叙事方向，删掉松散句和重复信息。",
    "polish": "请重点润色节奏、对白和画面感，但不要改变主事件。",
    "humanize": "请去掉模板腔和解释腔，让语言更像自然写作。",
  }[mode]
  style_pack = _apply_preset_and_style(
    settings,
    task_key=task_key,
    style_name=payload.style_name,
    style_task_type="chapter",
    style_query=f"{chapter.title} {payload.instruction}",
    xp_name=payload.xp_preset,
  )
  return [
    {"role": "system", "content": _CHAPTER_REWRITE_SYSTEM_PROMPT},
    {
      "role": "user",
      "content": (
        f"{context_text}\n\n"
        f"当前模式：{mode}\n"
        f"{mode_text}\n"
        f"用户补充：{payload.instruction.strip() or '无'}\n"
        f"原正文：\n{chapter.content.strip()}\n\n"
        f"如果这一章改完后需要更新滚动摘要或人物状态，再写入对应字段。\n"
        f"{style_pack or ''}"
      ).strip(),
    },
  ]


def _chapter_humanize_messages(settings: Settings, payload: ChapterRewriteRequest, project_detail, chapter, context_text: str) -> list[dict[str, str]]:
  style_pack = _apply_preset_and_style(
    settings,
    task_key="humanize",
    style_name=payload.style_name,
    style_task_type="chapter",
    style_query=f"{chapter.title} {payload.instruction}",
    xp_name=payload.xp_preset,
  )
  prompt_block = build_humanize_prompt_block(chapter.content.strip())
  return [
    {"role": "system", "content": _CHAPTER_HUMANIZE_SYSTEM_PROMPT},
    {
      "role": "user",
      "content": (
        f"{context_text}\n\n"
        f"请处理《{project_detail.name}》第 {chapter.index} 章《{chapter.title}》的正文。\n"
        f"{prompt_block}\n"
        f"用户补充：{payload.instruction.strip() or '无'}\n"
        f"原正文：\n{chapter.content.strip()}\n\n"
        f"如果这一章改完后确实需要更新滚动摘要或人物状态，再写入对应字段。\n"
        f"{style_pack or ''}"
      ).strip(),
    },
  ]


def _continue_messages(settings: Settings, payload: ContinueProjectRequest) -> list[dict[str, str]]:
  project_detail, documents, _chapter, context_text = _project_context_text(
    settings,
    payload.project_id,
    include_blueprint=True,
    include_character_state=True,
    knowledge_query=payload.instruction,
    task_pack_kind="architecture",
    task_instruction=payload.instruction,
  )
  target_chapters = project_detail.target_chapters + payload.new_chapters
  style_pack = _apply_preset_and_style(
    settings,
    task_key="blueprint",
    style_name=payload.style_name,
    style_task_type="blueprint",
    style_query=payload.instruction or documents.get("blueprint", ""),
    xp_name=payload.xp_preset,
  )
  dream_text = build_project_dream_prompt_block(project_detail)
  dream_block = f"{dream_text}\n\n" if dream_text else ""
  return [
    {"role": "system", "content": _CONTINUE_SYSTEM_PROMPT},
    {
      "role": "user",
      "content": (
        f"{context_text}\n\n"
        f"{dream_block}"
        f"请把这部作品从 {project_detail.target_chapters} 章扩到 {target_chapters} 章。\n"
        f"用户补充：{payload.instruction.strip() or '无'}\n"
        f"要求保持已写章节成立，不要推翻既有设定。\n"
        f"{style_pack or ''}"
      ).strip(),
    },
  ]


def _style_analyze_messages(settings: Settings, payload: StyleAnalyzeRequest) -> list[dict[str, str]]:
  return [
    {"role": "system", "content": _STYLE_ANALYZE_SYSTEM_PROMPT},
    {
      "role": "user",
      "content": (
        f"文风名称：{payload.style_name}\n"
        f"用户偏好：{payload.user_preference.strip() or '无'}\n\n"
        f"请分析下面这段样文，并提炼成可复用的文风 DNA。\n\n"
        f"{payload.sample_text.strip()}"
      ),
    },
  ]


def _style_merge_messages(settings: Settings, payload: StyleMergeRequest) -> list[dict[str, str]]:
  source_blocks: list[str] = []
  for name in payload.selected_styles:
    try:
      detail = get_style(settings, name)
    except HTTPException:
      continue
    source_blocks.append(
      (
        f"文风：{detail.name}\n"
        f"说明：{detail.instruction or '无'}\n"
        f"分析：{_compact_text(detail.analysis, 320) or '无'}\n"
        f"章节叙事：{_compact_text(detail.narrative_for_chapter, 240) or '无'}"
      )
    )
  return [
    {"role": "system", "content": _STYLE_ANALYZE_SYSTEM_PROMPT},
    {
      "role": "user",
      "content": (
        f"目标文风名称：{payload.style_name}\n"
        f"用户偏好：{payload.user_preference.strip() or '无'}\n\n"
        f"请融合下面这些已有文风，整理成一个新的文风方案：\n\n"
        + "\n\n".join(source_blocks)
      ),
    },
  ]


def _style_detail_prompt(detail: StyleDetail) -> str:
  reference_lines = [
    f"- {item.title}：{item.preview}"
    for item in detail.reference_materials[:4]
  ]
  return (
    f"文风名称：{detail.name}\n"
    f"当前指令：{detail.instruction or '无'}\n"
    f"当前分析：{detail.analysis or '无'}\n"
    f"当前 DNA：{detail.dna_analysis or '无'}\n"
    f"架构叙事要求：{detail.narrative_for_architecture or '无'}\n"
    f"蓝图叙事要求：{detail.narrative_for_blueprint or '无'}\n"
    f"章节叙事要求：{detail.narrative_for_chapter or '无'}\n"
    f"参考库蒸馏：\n{detail.reference_distillate or '无'}\n"
    f"样文：\n{detail.source_sample.strip() or '无'}\n"
    f"校准参考：\n{detail.calibration_reference.strip() or '无'}\n"
    f"作者参考资料：\n{chr(10).join(reference_lines) if reference_lines else '无'}"
  )


def _style_analyze_dna_messages(settings: Settings, payload: StyleDNAAnalyzeRequest) -> list[dict[str, str]]:
  return [
    {"role": "system", "content": _STYLE_DNA_SYSTEM_PROMPT},
    {
      "role": "user",
      "content": (
        f"文风名称：{payload.style_name}\n"
        f"用户偏好：{payload.user_preference.strip() or '无'}\n\n"
        f"请做更细的文风 DNA 分析，重点说清楚叙事视角、镜头距离、信息释放和对白/动作比例。\n\n"
        f"{payload.sample_text.strip()}"
      ),
    },
  ]


def _style_calibrate_messages(detail: StyleDetail, payload: StyleCalibrateRequest, mode: str) -> list[dict[str, str]]:
  system_prompt = _STYLE_CALIBRATE_SYSTEM_PROMPT if mode == "style" else _STYLE_NARRATIVE_CALIBRATE_SYSTEM_PROMPT
  focus_text = (
    "这轮重点是整体文风指令和分析说明。"
    if mode == "style"
    else "这轮重点是 narrative_for_architecture / narrative_for_blueprint / narrative_for_chapter 三个字段。"
  )
  return [
    {"role": "system", "content": system_prompt},
    {
      "role": "user",
      "content": (
        f"{_style_detail_prompt(detail)}\n\n"
        f"用户补充：{payload.user_preference.strip() or '无'}\n"
        f"{focus_text}\n"
        "请输出一版更贴近样文的修订结果。"
      ),
    },
  ]


def _style_result_to_detail(detail: StyleDetail, result: StyleAnalysisResult) -> StyleDetail:
  return detail.model_copy(
    update={
      "instruction": result.instruction or detail.instruction,
      "analysis": result.analysis or detail.analysis,
      "dna_analysis": result.dna_analysis or detail.dna_analysis,
      "narrative_for_architecture": result.narrative_for_architecture or detail.narrative_for_architecture,
      "narrative_for_blueprint": result.narrative_for_blueprint or detail.narrative_for_blueprint,
      "narrative_for_chapter": result.narrative_for_chapter or detail.narrative_for_chapter,
      "calibration_notes": result.calibration_notes or detail.calibration_notes,
    }
  )


def _generate_brainstorm(settings: Settings, payload: BrainstormRequest, task_id: str) -> BrainstormResult:
  content = _invoke_model(settings, _brainstorm_messages(settings, payload), task_name="brainstorm")
  result = _parse_brainstorm_result(content, task_id)
  skill_candidate = suggest_reusable_skill(settings, payload.messages, result.reply, payload.skill_id)
  if skill_candidate is None:
    return result
  return result.model_copy(update={"skill_candidate": skill_candidate})


def _generate_character_replica(settings: Settings, payload: CharacterReplicaRequest, task_id: str) -> CharacterReplicaResult:
  content = _invoke_model(
    settings,
    _character_replica_messages(settings, payload),
    task_name="character_replica",
  )
  return _parse_character_replica_result(content, task_id)


def _generate_consistency(settings: Settings, payload: ConsistencyCheckRequest, task_id: str) -> ConsistencyCheckResult:
  content = _invoke_model(settings, _consistency_messages(settings, payload), task_name="consistency")
  return _parse_consistency_result(content, task_id)


def _generate_blueprint(settings: Settings, payload: BlueprintGenerateRequest, task_id: str) -> BlueprintGenerateResult:
  content = _invoke_model(settings, _blueprint_messages(settings, payload), task_name="blueprint")
  return _parse_blueprint_result(content, task_id)


def _generate_chapter(settings: Settings, payload: ChapterGenerateRequest, task_id: str) -> ChapterGenerateResult:
  support = _apply_preset_and_style(
    settings,
    task_key="chapter",
    style_name=payload.style_name,
    style_task_type="chapter",
    style_query=payload.instruction,
    xp_name=payload.xp_preset,
  )
  pipeline = _run_continuation_pipeline(
    settings,
    project_id=payload.project_id,
    chapter_id=payload.chapter_id,
    instruction=payload.instruction,
    target_words=payload.target_words or 1800,
    support_text=support,
    characters_involved=payload.characters_involved,
    key_items=payload.key_items,
    scene_location=payload.scene_location,
    time_constraint=payload.time_constraint,
    task_name_prefix="chapter_generate",
    candidate_count=3,
    prefer_project_budget=True,
    complete_chapter=payload.target_words <= 0,
  )
  return ChapterGenerateResult(
    task_id=task_id,
    headline=str(pipeline["headline"] or "章节初稿已生成"),
    summary=str(pipeline["summary"]),
    content=str(pipeline["content"]),
    next_action=str(pipeline["next_action"]),
  )


def _rewrite_chapter(settings: Settings, payload: ChapterRewriteRequest, task_id: str, mode: str) -> ChapterRewriteResult:
  content = _invoke_model(
    settings,
    _chapter_rewrite_messages(settings, payload, mode),
    task_name=f"chapter_{mode}",
  )
  result = _parse_rewrite_result(content, task_id)
  project_detail = get_project_detail(settings, payload.project_id)
  chapter = next((item for item in project_detail.chapters if item.id == payload.chapter_id), None)
  if chapter is None:
    raise HTTPException(status_code=404, detail="章节不存在")
  updates: dict[str, object] = {"original": chapter.content.strip()}
  if mode == "humanize":
    quality_report = build_humanize_quality_report(chapter.content.strip(), result.revised)
    updates["quality_report"] = quality_report
    if not result.changes:
      updates["changes"] = build_humanize_fallback_changes(quality_report)
  return result.model_copy(update=updates)


def _continue_project(settings: Settings, payload: ContinueProjectRequest, task_id: str) -> ContinueProjectResult:
  project_detail = get_project_detail(settings, payload.project_id)
  target_chapters = project_detail.target_chapters + payload.new_chapters
  content = _invoke_model(settings, _continue_messages(settings, payload), task_name="continue_project")
  result = _parse_continue_result(content, task_id, target_chapters)
  update_project_targets(settings, payload.project_id, target_chapters=target_chapters)
  update_story_documents(
    settings,
    payload.project_id,
    StoryDocumentBatchUpdateRequest(
      documents=[
        StoryDocumentPatch(key="plot_structure", content=result.plot_structure),
        StoryDocumentPatch(key="world_building", content=result.world_building),
        StoryDocumentPatch(key="character_design", content=result.character_design),
        StoryDocumentPatch(key="character_state", content=result.character_state),
        StoryDocumentPatch(key="blueprint", content=result.blueprint),
      ]
    ),
  )
  append_app_log(settings, f"continue_project applied to {payload.project_id}, target chapters -> {target_chapters}")
  return result


def _style_analyze(settings: Settings, payload: StyleAnalyzeRequest, task_id: str, task_name: str) -> StyleAnalysisResult:
  content = _invoke_model(settings, _style_analyze_messages(settings, payload), task_name=task_name)
  return _parse_style_result(content, task_id)


def _style_merge(settings: Settings, payload: StyleMergeRequest, task_id: str) -> StyleAnalysisResult:
  content = _invoke_model(settings, _style_merge_messages(settings, payload), task_name="style_merge")
  return _parse_style_result(content, task_id)


def _style_detail_to_result(detail: StyleDetail, task_id: str) -> StyleAnalysisResult:
  return StyleAnalysisResult(
    task_id=task_id,
    instruction=detail.instruction,
    analysis=detail.analysis,
    dna_analysis=detail.dna_analysis,
    narrative_for_architecture=detail.narrative_for_architecture,
    narrative_for_blueprint=detail.narrative_for_blueprint,
    narrative_for_chapter=detail.narrative_for_chapter,
    calibration_notes=detail.calibration_notes,
  )


def _style_analyze_dna(settings: Settings, payload: StyleDNAAnalyzeRequest, task_id: str) -> StyleAnalysisResult:
  content = _invoke_model(settings, _style_analyze_dna_messages(settings, payload), task_name="style_analyze_dna")
  return _parse_style_result(content, task_id)


def _calibrate_style(settings: Settings, payload: StyleCalibrateRequest, task_id: str, mode: str) -> StyleAnalysisResult:
  detail = get_style(settings, payload.style_name)
  if not detail.source_sample.strip() and not detail.calibration_reference.strip() and not detail.reference_materials:
    raise RuntimeError("当前文风还没有样文或参考资料，先分析样文再校准。")

  snapshot = None if detail.has_calibration_snapshot else style_calibration_snapshot(detail)
  current_detail = detail
  for iteration in range(payload.max_iterations):
    content = _invoke_model(
      settings,
      _style_calibrate_messages(current_detail, payload, mode),
      task_name=f"style_calibrate:{mode}:{iteration + 1}",
    )
    result = _parse_style_result(content, task_id)
    current_detail = _style_result_to_detail(current_detail, result)

  current_detail = current_detail.model_copy(
    update={
      "last_calibrated_at": datetime.now(timezone.utc).isoformat(),
    }
  )
  saved = save_style_detail(settings, current_detail, snapshot=snapshot)
  return _style_detail_to_result(saved, task_id)


async def _simple_stream(settings: Settings, stream_name: str, steps: list[str], worker, result_dump):
  task_id = str(uuid4())
  append_app_log(settings, f"{stream_name} started task_id={task_id}")
  yield encode_sse("started", {"task_id": task_id})

  try:
    for index, message in enumerate(steps[:-1], start=1):
      yield encode_sse("progress", {"step": index, "total": len(steps), "message": message})
      await asyncio.sleep(0.08)

    result = await asyncio.to_thread(worker, task_id)
  except asyncio.CancelledError:
    append_app_log(settings, f"{stream_name} cancelled by client task_id={task_id}", level="WARNING")
    raise
  except Exception as error:
    append_app_log(settings, f"{stream_name} failed task_id={task_id}: {error}", level="ERROR")
    yield encode_sse("error", {"task_id": task_id, "message": str(error)})
    yield encode_sse("done", {"task_id": task_id, "status": "failed"})
    return

  yield encode_sse(
    "progress",
    {"step": len(steps), "total": len(steps), "message": steps[-1]},
  )
  yield encode_sse("result", result_dump(result))
  yield encode_sse("done", {"task_id": task_id, "status": "completed"})
  append_app_log(settings, f"{stream_name} completed task_id={task_id}")


async def brainstorm_stream(settings: Settings, payload: BrainstormRequest):
  async for item in _simple_stream(
    settings,
    "brainstorm_stream",
    ["整理项目上下文", "拼接对话记录", "向模型发起讨论请求", "输出本轮建议"],
    lambda task_id: _generate_brainstorm(settings, payload, task_id),
    lambda result: result.model_dump(mode="json"),
  ):
    yield item


async def character_replica_stream(settings: Settings, payload: CharacterReplicaRequest):
  async for item in _simple_stream(
    settings,
    "character_replica_stream",
    ["整理人物资料", "提炼判断框架", "向模型生成视角回答", "输出人物复刻结果"],
    lambda task_id: _generate_character_replica(settings, payload, task_id),
    lambda result: result.model_dump(mode="json"),
  ):
    yield item


async def consistency_stream(settings: Settings, payload: ConsistencyCheckRequest):
  async for item in _simple_stream(
    settings,
    "consistency_stream",
    ["读取章节正文", "检索设定与前文", "向模型发起检查请求", "整理一致性问题"],
    lambda task_id: _generate_consistency(settings, payload, task_id),
    lambda result: result.model_dump(mode="json"),
  ):
    yield item


async def blueprint_stream(settings: Settings, payload: BlueprintGenerateRequest):
  async for item in _simple_stream(
    settings,
    "blueprint_stream",
    ["读取项目架构", "整理章节目标", "向模型生成蓝图", "输出章节规划"],
    lambda task_id: _generate_blueprint(settings, payload, task_id),
    lambda result: result.model_dump(mode="json"),
  ):
    yield item


async def chapter_generate_stream(settings: Settings, payload: ChapterGenerateRequest):
  async for item in _simple_stream(
    settings,
    "chapter_generate_stream",
    ["读取本章上下文", "检索人物与线索", "向模型生成正文", "输出章节初稿"],
    lambda task_id: _generate_chapter(settings, payload, task_id),
    lambda result: result.model_dump(mode="json"),
  ):
    yield item


async def chapter_rewrite_stream(settings: Settings, payload: ChapterRewriteRequest, mode: str):
  label = {
    "finalize": "定稿",
    "polish": "润色",
    "humanize": "去 AI",
  }[mode]
  async for item in _simple_stream(
    settings,
    f"chapter_rewrite_stream:{mode}",
    [f"读取当前正文", "整理项目上下文", f"向模型发起{label}请求", "输出修订稿"],
    lambda task_id: _rewrite_chapter(settings, payload, task_id, mode),
    lambda result: result.model_dump(mode="json"),
  ):
    yield item


async def continue_project_stream(settings: Settings, payload: ContinueProjectRequest):
  async for item in _simple_stream(
    settings,
    "continue_project_stream",
    ["读取整本设定", "规划新增章节", "向模型扩写后续蓝图", "写回项目规划"],
    lambda task_id: _continue_project(settings, payload, task_id),
    lambda result: result.model_dump(mode="json"),
  ):
    yield item


async def style_analyze_stream(settings: Settings, payload: StyleAnalyzeRequest):
  async for item in _simple_stream(
    settings,
    "style_analyze_stream",
    ["整理样文", "分析句法与节奏", "提炼文风 DNA", "输出文风方案"],
    lambda task_id: _style_analyze(settings, payload, task_id, "style_analyze"),
    lambda result: result.model_dump(mode="json"),
  ):
    yield item


async def style_analyze_dna_stream(settings: Settings, payload: StyleDNAAnalyzeRequest):
  async for item in _simple_stream(
    settings,
    "style_analyze_dna_stream",
    ["整理样文", "提取叙事 DNA", "对齐三段式叙事要求", "输出 DNA 分析结果"],
    lambda task_id: _style_analyze_dna(settings, payload, task_id),
    lambda result: result.model_dump(mode="json"),
  ):
    yield item


async def _style_calibration_stream(settings: Settings, payload: StyleCalibrateRequest, mode: str):
  task_id = str(uuid4())
  yield encode_sse("started", {"task_id": task_id})

  try:
    detail = await asyncio.to_thread(get_style, settings, payload.style_name)
  except Exception as error:
    yield encode_sse("error", {"task_id": task_id, "message": str(error)})
    yield encode_sse("done", {"task_id": task_id, "status": "failed"})
    return

  if not detail.source_sample.strip() and not detail.calibration_reference.strip() and not detail.reference_materials:
    yield encode_sse("error", {"task_id": task_id, "message": "当前文风还没有样文或参考资料，先分析样文再校准。"})
    yield encode_sse("done", {"task_id": task_id, "status": "failed"})
    return

  snapshot = None if detail.has_calibration_snapshot else style_calibration_snapshot(detail)
  current_detail = detail
  total = payload.max_iterations + 1

  for iteration in range(payload.max_iterations):
    yield encode_sse(
      "progress",
      {
        "step": iteration + 1,
        "total": total,
        "message": f"第 {iteration + 1} 轮{mode == 'style' and '文风' or '叙事'}校准",
      },
    )
    try:
      content = await asyncio.to_thread(
        _invoke_model,
        settings,
        _style_calibrate_messages(current_detail, payload, mode),
        task_name=f"style_calibrate:{mode}:{iteration + 1}",
      )
    except Exception as error:
      yield encode_sse("error", {"task_id": task_id, "message": str(error)})
      yield encode_sse("done", {"task_id": task_id, "status": "failed"})
      return
    result = _parse_style_result(content, task_id)
    current_detail = _style_result_to_detail(current_detail, result)

  current_detail = current_detail.model_copy(
    update={"last_calibrated_at": datetime.now(timezone.utc).isoformat()}
  )
  saved = await asyncio.to_thread(save_style_detail, settings, current_detail, snapshot=snapshot)
  yield encode_sse(
    "progress",
    {
      "step": total,
      "total": total,
      "message": "保存校准后的文风方案",
    },
  )
  yield encode_sse("result", _style_detail_to_result(saved, task_id).model_dump(mode="json"))
  yield encode_sse("done", {"task_id": task_id, "status": "completed"})


async def style_calibrate_stream(settings: Settings, payload: StyleCalibrateRequest):
  async for item in _style_calibration_stream(settings, payload, "style"):
    yield item


async def style_calibrate_narrative_stream(settings: Settings, payload: StyleCalibrateRequest):
  async for item in _style_calibration_stream(settings, payload, "narrative"):
    yield item


async def style_merge_stream(settings: Settings, payload: StyleMergeRequest):
  async for item in _simple_stream(
    settings,
    "style_merge_stream",
    ["读取已保存文风", "对齐叙事要求", "向模型融合风格", "输出新文风方案"],
    lambda task_id: _style_merge(settings, payload, task_id),
    lambda result: result.model_dump(mode="json"),
  ):
    yield item


def _batch_task_path(settings: Settings, task_id: str):
  task_dir = settings.data_dir / "batch_tasks"
  task_dir.mkdir(parents=True, exist_ok=True)
  return task_dir / f"{task_id}.json"


def _batch_task_request_payload(payload: BatchGenerateRequest) -> dict[str, object]:
  return {
    "project_id": payload.project_id,
    "start_chapter": payload.start_chapter,
    "end_chapter": payload.end_chapter,
    "instruction": payload.instruction,
    "style_name": payload.style_name,
    "xp_preset": payload.xp_preset,
  }


def _load_or_create_batch_task(settings: Settings, payload: BatchGenerateRequest, task_id: str) -> dict[str, object]:
  path = _batch_task_path(settings, task_id)
  existing = read_json(path, None)
  request_payload = _batch_task_request_payload(payload)
  if isinstance(existing, dict) and existing.get("request") == request_payload:
    if payload.comment.strip():
      comments = existing.get("comments")
      if not isinstance(comments, list):
        comments = []
      comments.append({"at": _now_iso(), "comment": payload.comment.strip()})
      existing["comments"] = comments
      existing["updated_at"] = _now_iso()
      atomic_write_json(path, existing)
    return existing

  state = {
    "task_id": task_id,
    "status": "running",
    "created_at": _now_iso(),
    "updated_at": _now_iso(),
    "request": request_payload,
    "comments": [{"at": _now_iso(), "comment": payload.comment.strip()}] if payload.comment.strip() else [],
    "chapters": [
      {
        "chapter_index": chapter_index,
        "chapter_id": f"chapter-{chapter_index:03d}",
        "status": "pending",
        "attempts": 0,
        "last_error": "",
        "result": None,
      }
      for chapter_index in range(payload.start_chapter, payload.end_chapter + 1)
    ],
  }
  atomic_write_json(path, state)
  return state


def _save_batch_task(settings: Settings, state: dict[str, object]) -> None:
  state["updated_at"] = _now_iso()
  atomic_write_json(_batch_task_path(settings, str(state["task_id"])), state)


async def batch_generate_stream(settings: Settings, payload: BatchGenerateRequest):
  if payload.end_chapter < payload.start_chapter:
    raise RuntimeError("结束章节不能小于起始章节")

  task_id = payload.task_id.strip() or str(uuid4())
  task_state = _load_or_create_batch_task(settings, payload, task_id)
  yield encode_sse("started", {"task_id": task_id, "resumable": True})
  generated: list[BatchGenerateChapterResult] = []
  chapters = task_state.get("chapters")
  if not isinstance(chapters, list):
    chapters = []
  total = len(chapters)

  for offset, task_item in enumerate(chapters, start=1):
    if not isinstance(task_item, dict):
      continue
    chapter_index = int(task_item.get("chapter_index") or offset)
    chapter_id = str(task_item.get("chapter_id") or f"chapter-{chapter_index:03d}")
    previous_status = str(task_item.get("status") or "")
    previous_result = task_item.get("result")
    if previous_status == "completed" and isinstance(previous_result, dict):
      generated.append(BatchGenerateChapterResult.model_validate(previous_result))
      yield encode_sse(
        "progress",
        {"step": offset, "total": total, "message": f"第 {chapter_index} 章已完成，跳过"},
      )
      continue
    if previous_status == "failed" and not payload.retry_failed and isinstance(previous_result, dict):
      generated.append(BatchGenerateChapterResult.model_validate(previous_result))
      yield encode_sse(
        "progress",
        {"step": offset, "total": total, "message": f"第 {chapter_index} 章上次失败，等待重试"},
      )
      continue

    task_item["status"] = "running"
    task_item["attempts"] = int(task_item.get("attempts") or 0) + 1
    _save_batch_task(settings, task_state)
    yield encode_sse(
      "progress",
      {"step": offset, "total": total, "message": f"正在生成第 {chapter_index} 章"},
    )
    request_payload = ChapterGenerateRequest(
      project_id=payload.project_id,
      chapter_id=chapter_id,
      instruction=payload.instruction,
      style_name=payload.style_name,
      xp_preset=payload.xp_preset,
    )
    try:
      result = await asyncio.to_thread(_generate_chapter, settings, request_payload, f"{task_id}-{chapter_index}")
      detail, review_error = await asyncio.to_thread(
        update_chapter_content_with_review_status,
        settings,
        payload.project_id,
        chapter_id,
        ChapterUpdateRequest(content=result.content, style_name=payload.style_name, xp_preset=payload.xp_preset),
      )
      detail, review_error, repair_result = await asyncio.to_thread(
        auto_repair_chapter_after_review,
        settings,
        payload.project_id,
        chapter_id,
        detail,
        review_error=review_error,
        style_name=payload.style_name,
        xp_preset=payload.xp_preset,
        instruction=payload.instruction,
      )
      review_status = summarize_chapter_review_status(detail, chapter_id, review_error)
      review_score = review_status.get("score")
      review_label = str(review_status.get("status_label") or "").strip()
      status = "completed"
      if review_error:
        status = f"completed_with_review_error: {review_error}"
      elif isinstance(review_score, int):
        status = f"completed: 核验 {review_score}/100"
        if review_label:
          status = f"{status}（{review_label}）"
        if repair_result.applied:
          status = f"{status}，已自动修订"
        elif repair_result.attempted:
          status = f"{status}，自动修订未写入"
      final_chapter = next((item for item in detail.chapters if item.id == chapter_id), None)
      preview_content = final_chapter.content if final_chapter is not None and final_chapter.content.strip() else result.content
      generated.append(
        BatchGenerateChapterResult(
          chapter_id=chapter_id,
          title=result.headline or f"第 {chapter_index} 章",
          status=status,
          preview=_compact_text(preview_content, 100),
          review_status=str(review_status.get("status") or ""),
          review_score=review_score if isinstance(review_score, int) else None,
          review_summary=str(review_status.get("summary") or ""),
          review_error=str(review_status.get("error") or ""),
          review_auto_repair_attempted=repair_result.attempted,
          review_auto_repair_applied=repair_result.applied,
          review_auto_repair_rounds_attempted=repair_result.rounds_attempted,
          review_auto_repair_rounds_applied=repair_result.rounds_applied,
          review_auto_repair_summary=repair_result.summary,
          review_auto_repair_error=repair_result.error,
        )
      )
      task_item["status"] = "completed"
      task_item["last_error"] = ""
      task_item["result"] = generated[-1].model_dump(mode="json")
      _save_batch_task(settings, task_state)
    except Exception as error:
      generated.append(
        BatchGenerateChapterResult(
          chapter_id=chapter_id,
          title=f"第 {chapter_index} 章",
          status=f"failed: {error}",
          preview="",
        )
      )
      task_item["status"] = "failed"
      task_item["last_error"] = str(error)
      task_item["result"] = generated[-1].model_dump(mode="json")
      _save_batch_task(settings, task_state)

  task_state["status"] = "completed" if all(
    isinstance(item, dict) and str(item.get("status") or "") == "completed"
    for item in chapters
  ) else "partial"
  _save_batch_task(settings, task_state)
  yield encode_sse(
    "result",
    BatchGenerateResult(task_id=task_id, generated=generated).model_dump(mode="json"),
  )
  yield encode_sse("done", {"task_id": task_id, "status": str(task_state["status"])})
