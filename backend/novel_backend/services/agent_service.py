from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from novel_backend.agent_runtime import (
  AgentActionExecutionContext,
  AgentEventEmitter,
  AgentExecutionState,
  get_action_handler,
  register_action_handler,
)
from novel_backend.config import Settings
from novel_backend.models import (
  AgentArtifact,
  AgentChatRequest,
  AgentChatResult,
  AgentEventBlock,
  AgentExecutionTrace,
  AgentMessage,
  AgentPlan,
  AgentPlanAction,
  AgentStateSummary,
  ArchitectureStepRequest,
  ArchitectureWorkspace,
  BrainstormMessage,
  BrainstormRequest,
  ChapterGenerateRequest,
  ChapterRewriteRequest,
  ChapterUpdateRequest,
  ChapterWorkflowRequest,
  ConsistencyCheckRequest,
  ContinueProjectRequest,
  KnowledgeImportItem,
  KnowledgeImportRequest,
  KNOWLEDGE_IMPORT_CONTENT_MAX_LENGTH,
  SkillMaterializeRequest,
  StoryDocumentBatchUpdateRequest,
  StoryDocumentPatch,
)
from novel_backend.services.context_builder import (
  build_project_context_bundle,
  build_prompt_support,
  chapter_average_word_target,
  chapter_text_length,
  explicit_length_target,
  full_chapter_generation_target,
  instruction_requests_explicit_length,
  instruction_requests_full_chapter,
  project_documents_map,
  recommended_chapter_generation_target,
)
from novel_backend.services.agent_trajectory_service import append_agent_trajectory
from novel_backend.services.config_service import load_config
from novel_backend.services.agent_contract_service import (
  build_agent_preflight_report,
  evaluate_agent_action_contract,
  validate_agent_action_outputs,
)
from novel_backend.services.chapter_auto_repair_service import (
  ChapterAutoRepairResult,
  auto_repair_chapter_after_review,
)
from novel_backend.services.generation_service import (
  _extract_json_object,
  _generate_architecture_step,
  _generate_chapter_workflow,
  _invoke_model,
  _run_continuation_pipeline,
  _string_from_keys,
)
from novel_backend.services.project_distillation_service import build_distillation_review_text, resolve_task_pack_kind
from novel_backend.services.project_learning_service import build_learning_review_artifact
from novel_backend.services.project_auxiliary_service import enqueue_project_auxiliary_tasks
from novel_backend.services.model_runtime_service import model_runtime_foreground_session
from novel_backend.services.obsidian_service import obsidian_note_available_for_chapter
from novel_backend.services.project_narrative_state_service import (
  load_project_narrative_state,
  obsidian_maintenance_suggestion_sort_key,
)
from novel_backend.services.project_service import (
  build_project_agent_thread_context,
  clear_architecture_progress,
  get_project_detail,
  import_project_knowledge,
  load_architecture_progress,
  load_project_knowledge_material_contents,
  load_project_obsidian_note_contents,
  save_architecture_progress,
  save_story_document_incremental,
  summarize_chapter_review_status,
  update_chapter_content_with_review_status,
  update_story_documents,
)
from novel_backend.services.self_evolution_service import build_agent_capability_context, run_self_evolution_cycle
from novel_backend.services.agent_workflow_service import (
  agent_workflow_interrupt_message,
  complete_agent_workflow_run,
  create_agent_workflow_run,
  heartbeat_agent_workflow_action,
  mark_stale_agent_workflows,
  record_agent_workflow_subtask,
  update_agent_workflow_action,
  update_agent_workflow_preflight,
  workflow_summary,
)
from novel_backend.services.skill_service import (
  custom_skill_names,
  get_custom_skill_prompt_block,
  list_skill_catalog,
  materialize_skill,
  match_custom_skill_ids,
  suggest_reusable_skill,
)
from novel_backend.services.studio_service import (
  _continue_project,
  _brainstorm_chapter_index_from_text,
  _generate_brainstorm,
  _generate_chapter,
  _generate_consistency,
  _rewrite_chapter,
)
from novel_backend.utils.jsonfile import atomic_write_text
from novel_backend.utils.sse import encode_sse

_ARCHITECTURE_KEYS = [
  "core_seed",
  "character_design",
  "world_building",
  "plot_structure",
  "blueprint",
]

_ARCHITECTURE_STEPS = [
  ("core_seed", "核心种子"),
  ("character_design", "人物设定"),
  ("world_building", "世界设定"),
  ("plot_structure", "情节骨架"),
  ("character_state", "人物状态"),
  ("blueprint", "章节蓝图"),
  ("global_summary", "滚动摘要"),
]

_ROUTE_SYSTEM_PROMPT = """
你是中文小说工作台里的任务路由器。你的职责不是写内容，而是判断用户此刻想让系统做什么。

只输出一个 JSON 对象，不要输出解释、标题或代码块。
JSON 字段固定为：
- intent: discussion | write_chapter | diagnose_chapter | scene_chapter | rewrite_chapter | consistency_check | generate_architecture | continue_project | skill_optimize | unknown
- objective: 对用户目标的简短中文概括
- chapter_index: 整数，没有就填 0
- chapter_title: 没有就填空字符串
- rewrite_mode: finalize | polish | humanize | 空字符串
- new_chapters: 整数，没有就填 0
- use_next_chapter: true 或 false
- reason: 20 字以内，说明你为什么这样判断

判断规则：
1. 用户在聊故事方向、人物关系、题材、冲突、下一步怎么推进，intent 选 discussion。
2. 用户要系统直接写正文、续写、补完本章，intent 选 write_chapter。
3. 用户要判断当前章节问题、看节奏、看哪里不对，intent 选 diagnose_chapter。
4. 用户要拆场景、列场景清单，intent 选 scene_chapter。
5. 用户要润色、改稿、定稿、去 AI，intent 选 rewrite_chapter，并填 rewrite_mode。
6. 用户要查一致性、逻辑漏洞、前后矛盾，intent 选 consistency_check。
7. 用户要搭整书架构、蓝图、大纲、世界观、人物设定，intent 选 generate_architecture。
8. 用户要继续往后规划、新增后续章节、扩写整书蓝图，intent 选 continue_project。
9. 用户要把本轮方法保存成技能、以后都按某套规则处理、优化或更新已有技能，intent 选 skill_optimize。
10. 如果提到“下一章”，use_next_chapter 设为 true。
""".strip()

_PLAN_SYSTEM_PROMPT = """
你是中文小说工作台里的任务规划器。你的职责是理解用户意图，并直接给出本轮最合适的执行计划。

只输出一个 JSON 对象，不要输出解释、标题或代码块。

JSON 结构固定为：
{
  "mode": "plan" | "reply",
  "reply": "当 mode=reply 时使用",
  "title": "计划标题",
  "summary": "一句话说明为什么这么安排",
  "requires_confirmation": true | false,
  "actions": [
    {
      "kind": "brainstorm | review_knowledge | generate_architecture | continue_project | chapter_generate | chapter_workflow | consistency_check | rewrite_chapter | skill_optimize",
      "label": "动作标题",
      "instruction": "这一步执行指令，可为空",
      "chapter_target": "selected | next | last_written | exact | auto | none",
      "chapter_index": 0,
      "chapter_title": "",
      "mode": "diagnose | scenes | draft | finalize | polish | humanize | 空字符串",
      "new_chapters": 0,
      "target_words": 0,
      "skill_ids": ["可选，用户沉淀技能 id"]
    }
  ]
}

规划要求：
1. 先理解整句意思，不要看到某个词就机械分类。
2. 用户要“重写架构、重新整理蓝图、重做整书规划”时，用 generate_architecture，不要误判成 chapter_generate。
3. 用户要求“先分析资料，再做后续工作”时，把 review_knowledge 放在前面。
4. 用户只是讨论方向、人物、冲突、下一步怎么推进时，用 brainstorm，requires_confirmation 设为 false。
5. chapter_generate 只在用户明确要写正文时使用。
6. continue_project 只用于“继续往后规划几章”，不要拿它代替 generate_architecture。
7. 如果请求不适合执行任何动作，就返回 mode=reply，说明原因。
8. 除了 brainstorm、diagnose、scenes、一致性检查，其他会改动项目内容或技能文件的动作默认应该要求确认。
9. 可用技能目录只帮助你理解用户说法；真正执行仍然必须选上面的 action kind。
10. 如果用户明确提到用户沉淀技能，或者技能目录里某个 custom 技能很贴合，把它的 id 放进 action.skill_ids。
11. 用户说“以后都按这个方式”“把这套规则记住”“保存成技能”“优化这个技能”时，用 skill_optimize；如果是在更新某个用户技能，把该技能 id 放进 skill_ids。
12. 用户要生成章节正文、长篇逐章生产、续写下一章或改稿入稿时，把写回后的语言去 AI 和一致性复查纳入执行顺序；用户明确只要初稿、不改稿或不检查时除外。
13. 用户明确要求生成一个章节范围的正文时，每章都要有独立的 chapter_generate 或 chapter_workflow/draft 动作；一次直接生成正文最多安排 3 章，更多章节应返回 reply 要求拆成多批或先整理蓝图。
""".strip()

_NEXT_CHAPTER_HINT_PATTERN = re.compile(r"(下一章|下章|后面一章|下一回|后续一章)")
_TARGET_CHAPTER_NUMBER_PATTERN = re.compile(
  r"(?:生成|续写|写|补写|扩写|重写|改写|润色|修订|定稿|检查|判断|拆(?:场景)?|处理|写回)\s*"
  r"第\s*([0-9零一二三四五六七八九十百两]+)\s*章"
)
_CHAPTER_NUMBER_PATTERN = re.compile(r"第\s*([0-9零一二三四五六七八九十百两]+)\s*章")
_CHAPTER_RANGE_PATTERN = re.compile(
  r"第\s*([0-9零一二三四五六七八九十百两]+)\s*(?:章)?\s*(?:[-~—–]|到|至)\s*"
  r"(?:第)?\s*([0-9零一二三四五六七八九十百两]+)\s*章"
)
_CHAPTER_TITLE_PATTERN = re.compile(r"《([^》]{1,40})》")
_NEW_CHAPTER_COUNT_PATTERN = re.compile(r"(?:新增|增加|扩写|继续规划|后面再加|再加)\s*([0-9零一二三四五六七八九十百两]+)\s*章")
_CAPABILITY_CHAPTER_NUMBER_PATTERNS = (
  r"(?:生成|续写|写|补写|扩写)\s*第\s*([0-9零一二三四五六七八九十百两]+)\s*章",
  r"(?:重写|改写|润色|修订|定稿|处理)\s*第\s*([0-9零一二三四五六七八九十百两]+)\s*章",
  r"(?:拆(?:场景)?|场景规划)\s*第\s*([0-9零一二三四五六七八九十百两]+)\s*章",
  r"(?:诊断|检查|判断|分析)\s*第\s*([0-9零一二三四五六七八九十百两]+)\s*章",
)
_KNOWLEDGE_REVIEW_PATTERN = re.compile(r"(资料库|知识库|参考资料|资料分析|分析资料|先看资料|先读资料|通读资料|吃透资料)")
_ARCHITECTURE_CONTEXT_PATTERN = re.compile(r"(架构|蓝图|大纲|整书规划|整本规划|世界观|人物设定|情节骨架|继续规划|后续规划|往后规划|扩写整书)")
_LONGFORM_SUPERVISION_SKIP_PATTERN = re.compile(
  r"(只(?:要|生成|写).{0,12}初稿|先(?:别|不).{0,8}(?:改稿|去\s*ai|检查|复查)|"
  r"不(?:要|用|需要).{0,8}(?:改稿|去\s*ai|检查|复查)|暂时不(?:改稿|检查|复查))",
  re.IGNORECASE,
)
_LONG_INPUT_MATERIALIZE_THRESHOLD = 20_000
_LONG_INPUT_MATERIAL_CHUNK_LIMIT = min(50_000, KNOWLEDGE_IMPORT_CONTENT_MAX_LENGTH - 1_000)
_LONG_INPUT_MATERIAL_BLOCK_LIMIT = 4_000
_LONG_INPUT_IMPORT_INTENT_PATTERN = re.compile(
  r"(小说|故事|写作|创作|正文|续写|扩写|润色|改稿|章节|场景|人物|角色|剧情|情节|设定|世界观|"
  r"大纲|架构|蓝图|线索|伏笔|冲突|动机|文风|语气|节奏|资料|素材|参考|考据|知识库|Obsidian)",
  re.IGNORECASE,
)
_LONG_INPUT_RELEVANT_PATTERN = re.compile(
  r"(小说|故事|叙事|正文|续写|扩写|章节|章纲|场景|对白|旁白|人物|角色|主角|配角|反派|"
  r"剧情|情节|桥段|设定|世界观|地点|组织|势力|道具|线索|伏笔|悬念|冲突|动机|转折|结局|"
  r"大纲|架构|蓝图|文风|语气|节奏|资料|素材|参考|考据|历史|地理|民俗|神话|案件|证据)",
  re.IGNORECASE,
)
_LONG_INPUT_TECHNICAL_NOISE_PATTERN = re.compile(
  r"(Traceback|Exception|Error:|ERROR|WARN|warning|node_modules|npm\s|pnpm\s|yarn\s|"
  r"stack trace|console\.(?:log|error|warn)|function\s+\w+|class\s+\w+|from\s+\w+\s+import|"
  r"import\s+\{|SELECT\s+|CREATE\s+TABLE|INSERT\s+INTO|curl\s+|HTTP/\d|localhost|127\.0\.0\.1|"
  r"<script|</div>|</span>|TypeError|ReferenceError|SyntaxError|ValidationError|pytest|unittest|vite|FastAPI)",
  re.IGNORECASE,
)
_LONG_INPUT_BOILERPLATE_PATTERN = re.compile(
  r"(cookie|privacy policy|newsletter|subscribe|advertisement|版权所有|ICP备案|登录|注册|导航|菜单|"
  r"联系我们|隐私政策|用户协议|广告|分享到|点击加载)",
  re.IGNORECASE,
)
_MAX_CHAPTER_RANGE_GENERATION_ACTIONS = 3
_SKILL_OPTIMIZE_PATTERN = re.compile(
  r"(记成技能|保存成技能|沉淀成技能|创建技能|新建技能|优化.*技能|更新.*技能|修改.*技能|"
  r"以后.*(按|照|都|就).*(方式|规则|流程|处理|写|改)|每次.*(按|照|都|就).*(方式|规则|流程|处理|写|改)|"
  r"把.*(规则|流程|方法|方式).*(记住|保存|沉淀))"
)


class AgentSessionInterrupted(RuntimeError):
  pass

_KNOWLEDGE_REVIEW_SYSTEM_PROMPT = """
你是小说项目里的资料库分析器。你的任务是先通读资料，再提炼后续架构、蓝图和续写必须遵守的信息。

只输出中文纯文本，结构固定：
已确认事实：
- ...
关键线索：
- ...
对后续执行的硬约束：
- ...
可直接用于架构或续写：
- ...

不要编造资料里没有的内容，拿不准就明确写“不确定”。
""".strip()


@dataclass(slots=True)
class RoutingDecision:
  intent: str = "unknown"
  objective: str = ""
  chapter_index: int = 0
  chapter_title: str = ""
  rewrite_mode: str = ""
  new_chapters: int = 0
  use_next_chapter: bool = False
  reason: str = ""


@dataclass(slots=True)
class RuntimeState:
  detail: object
  documents: dict[str, str]
  discussion_summary: str
  architecture_ready: bool
  architecture_progress: int
  document_status: dict[str, bool]
  selected_chapter: object | None
  last_written_chapter: object | None
  next_chapter: object | None


@dataclass(slots=True)
class LongInputMaterialization:
  titles: list[str]
  original_length: int
  candidate_blocks: int = 0
  imported_blocks: int = 0
  skipped_blocks: int = 0
  project_detail: object | None = None


@dataclass(slots=True, frozen=True)
class _BuiltinSkillActionHint:
  skill_id: str
  name: str
  action_kind: str
  action_mode: str
  requires_confirmation: bool


def _compact_text(text: str, limit: int = 120) -> str:
  normalized = " ".join(str(text or "").split())
  if len(normalized) <= limit:
    return normalized
  return f"{normalized[:limit].rstrip()}…"


def _clip_middle(text: str, limit: int) -> str:
  normalized = str(text or "").strip()
  if len(normalized) <= limit:
    return normalized
  if limit <= 1:
    return normalized[:limit]
  if limit <= 12:
    return normalized[:limit].rstrip()
  marker = "……"
  body_limit = max(1, limit - len(marker))
  head_limit = max(1, int(body_limit * 0.55))
  tail_limit = max(1, body_limit - head_limit)
  return f"{normalized[:head_limit].rstrip()}{marker}{normalized[-tail_limit:].lstrip()}"


def _agent_message_model_content(message: object, limit: int = 1200) -> str:
  content = str(getattr(message, "content", "") or "").strip()
  if len(content) <= limit:
    return content

  original_length = int(getattr(message, "original_length", 0) or 0)
  original_length = max(original_length, len(content))
  summary = " ".join(str(getattr(message, "summary", "") or "").split())
  header = f"[长文本压缩，原文约 {original_length} 字]"

  if summary:
    summary_block = f"{header}\n摘要：{summary}"
    if len(summary_block) >= limit:
      return _clip_middle(summary_block, limit)
    remaining = limit - len(summary_block) - len("\n原文片段：\n")
    if remaining <= 20:
      return _clip_middle(summary_block, limit)
    return f"{summary_block}\n原文片段：\n{_clip_middle(content, remaining)}"

  remaining = limit - len(header) - 1
  if remaining <= 20:
    return _clip_middle(header, limit)
  return f"{header}\n{_clip_middle(content, remaining)}"


def _agent_message_model_messages(messages: list[object], *, limit: int = 3800) -> list[BrainstormMessage]:
  model_messages: list[BrainstormMessage] = []
  for item in messages:
    content = _agent_message_model_content(item, limit=limit).strip()
    if not content:
      continue
    role = str(getattr(item, "role", "") or "")
    model_messages.append(BrainstormMessage(role=role if role in {"user", "assistant", "system"} else "assistant", content=content))
  return model_messages


def _ordered_unique_strings(items: list[str]) -> list[str]:
  seen: set[str] = set()
  ordered: list[str] = []
  for raw in items:
    value = str(raw or "").strip()
    if not value or value in seen:
      continue
    seen.add(value)
    ordered.append(value)
  return ordered


def _append_long_input_sized_blocks(blocks: list[str], text: str, limit: int = _LONG_INPUT_MATERIAL_BLOCK_LIMIT) -> None:
  normalized = str(text or "").strip()
  if not normalized:
    return
  if len(normalized) <= limit:
    blocks.append(normalized)
    return

  lines = [line.strip() for line in normalized.splitlines() if line.strip()]
  if len(lines) > 1:
    buffer = ""
    for line in lines:
      candidate = f"{buffer}\n{line}".strip() if buffer else line
      if len(candidate) > limit and buffer:
        blocks.append(buffer)
        buffer = line
      else:
        buffer = candidate
    if buffer:
      blocks.append(buffer)
    return

  parts = [item.strip() for item in re.split(r"(?<=[。！？!?\.])\s*", normalized) if item.strip()]
  buffer = ""
  for part in parts or [normalized]:
    candidate = f"{buffer}{part}" if buffer else part
    if len(candidate) > limit and buffer:
      blocks.append(buffer)
      buffer = part
    else:
      buffer = candidate
    while len(buffer) > limit:
      blocks.append(buffer[:limit].strip())
      buffer = buffer[limit:].strip()
  if buffer:
    blocks.append(buffer)


def _split_long_input_candidate_blocks(text: str) -> list[str]:
  normalized = str(text or "").replace("\r\n", "\n").strip()
  if not normalized:
    return []
  blocks: list[str] = []
  for raw_block in re.split(r"\n{2,}", normalized):
    _append_long_input_sized_blocks(blocks, raw_block)
  return blocks


def _long_input_pattern_score(pattern: re.Pattern[str], text: str) -> int:
  return len(pattern.findall(str(text or "")[:6_000]))


def _long_input_alnum_blob_ratio(text: str) -> float:
  compact = re.sub(r"\s+", "", str(text or ""))
  if not compact:
    return 0.0
  blobs = "".join(re.findall(r"[A-Za-z0-9+/=_-]{80,}", compact))
  return len(blobs) / max(1, len(compact))


def _long_input_code_symbol_ratio(text: str) -> float:
  compact = re.sub(r"\s+", "", str(text or ""))
  if not compact:
    return 0.0
  symbols = re.findall(r"[{}<>\[\]();=\\]", compact)
  return len(symbols) / max(1, len(compact))


def _long_input_readable_ratio(text: str) -> float:
  compact = re.sub(r"\s+", "", str(text or ""))
  if not compact:
    return 0.0
  readable = re.findall(r"[\w\u4e00-\u9fff，。！？、；：“”‘’（）《》]", compact)
  return len(readable) / max(1, len(compact))


def _long_input_repeated_char_ratio(text: str) -> float:
  compact = re.sub(r"\s+", "", str(text or ""))
  if len(compact) < 80:
    return 0.0
  counts: dict[str, int] = {}
  for char in compact:
    counts[char] = counts.get(char, 0) + 1
  return max(counts.values()) / max(1, len(compact))


def _long_input_has_material_intent(text: str) -> bool:
  head = str(text or "")[:3_000]
  tail = str(text or "")[-1_200:]
  return bool(_LONG_INPUT_IMPORT_INTENT_PATTERN.search(f"{head}\n{tail}"))


def _keep_long_input_material_block(block: str, *, material_intent: bool) -> bool:
  text = str(block or "").strip()
  if len(text) < 24:
    return False

  relevant_score = _long_input_pattern_score(_LONG_INPUT_RELEVANT_PATTERN, text)
  technical_score = _long_input_pattern_score(_LONG_INPUT_TECHNICAL_NOISE_PATTERN, text)
  boilerplate_score = _long_input_pattern_score(_LONG_INPUT_BOILERPLATE_PATTERN, text)
  readable_ratio = _long_input_readable_ratio(text)
  code_symbol_ratio = _long_input_code_symbol_ratio(text)

  if _long_input_repeated_char_ratio(text) >= 0.65:
    return False
  if _long_input_alnum_blob_ratio(text) >= 0.45:
    return False
  if technical_score >= 2 and relevant_score == 0:
    return False
  if technical_score >= 1 and relevant_score == 0 and code_symbol_ratio >= 0.16:
    return False
  if boilerplate_score >= 3 and relevant_score == 0:
    return False
  if readable_ratio < 0.55 and relevant_score == 0:
    return False

  if relevant_score > 0:
    return True
  return material_intent and readable_ratio >= 0.72 and code_symbol_ratio < 0.12


def _pack_long_input_material_blocks(
  blocks: list[str],
  limit: int = _LONG_INPUT_MATERIAL_CHUNK_LIMIT,
) -> list[str]:
  chunk_limit = max(1_000, min(limit, KNOWLEDGE_IMPORT_CONTENT_MAX_LENGTH - 1_000))
  chunks: list[str] = []
  buffer = ""
  for block in blocks:
    text = str(block or "").strip()
    if not text:
      continue
    candidate = f"{buffer}\n\n{text}".strip() if buffer else text
    if len(candidate) > chunk_limit and buffer:
      chunks.append(buffer)
      buffer = text
    else:
      buffer = candidate
    while len(buffer) > chunk_limit:
      chunks.append(buffer[:chunk_limit].strip())
      buffer = buffer[chunk_limit:].strip()
  if buffer:
    chunks.append(buffer)
  return chunks


def _filtered_long_input_material_chunks(content: str) -> tuple[list[str], int, int]:
  blocks = _split_long_input_candidate_blocks(content)
  material_intent = _long_input_has_material_intent(content)
  kept_blocks = [
    block
    for block in blocks
    if _keep_long_input_material_block(block, material_intent=material_intent)
  ]
  skipped_blocks = max(0, len(blocks) - len(kept_blocks))
  return _pack_long_input_material_blocks(kept_blocks), len(kept_blocks), skipped_blocks


def _long_input_material_title(content_hash: str, index: int, total: int) -> str:
  if total <= 1:
    return f"Agent长输入-{content_hash}"
  return f"Agent长输入-{content_hash}-第{index:02d}部分"


def _long_input_material_content(
  message: object,
  content: str,
  chunk: str,
  index: int,
  total: int,
  *,
  skipped_blocks: int = 0,
) -> str:
  message_id = str(getattr(message, "id", "") or "").strip() or "未提供"
  header = "\n".join(
    [
      "来源：Agent 主对话长文本",
      f"消息 ID：{message_id}",
      f"分段：{index}/{total}",
      f"原文总长度：{len(content)} 字",
      "筛选：已排除明显无关、技术日志或网页样板段落" if skipped_blocks > 0 else "筛选：未发现需要排除的段落",
      "",
    ]
  )
  return f"{header}{chunk}".strip()


def _materialize_long_agent_inputs(settings: Settings, payload: AgentChatRequest) -> LongInputMaterialization:
  items: list[KnowledgeImportItem] = []
  titles: list[str] = []
  original_length = 0
  candidate_blocks = 0
  imported_blocks = 0
  skipped_blocks = 0

  for message in payload.messages:
    if str(getattr(message, "role", "") or "") != "user":
      continue
    content = str(getattr(message, "content", "") or "").strip()
    if len(content) < _LONG_INPUT_MATERIALIZE_THRESHOLD:
      continue

    original_length += len(content)
    content_hash = hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]
    chunks, kept_block_count, skipped_block_count = _filtered_long_input_material_chunks(content)
    imported_blocks += kept_block_count
    skipped_blocks += skipped_block_count
    candidate_blocks += kept_block_count + skipped_block_count
    total = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
      title = _long_input_material_title(content_hash, index, total)
      titles.append(title)
      items.append(
        KnowledgeImportItem(
          title=title,
          content=_long_input_material_content(
            message,
            content,
            chunk,
            index,
            total,
            skipped_blocks=skipped_block_count,
          ),
        )
      )

  if not items:
    return LongInputMaterialization(
      titles=[],
      original_length=original_length,
      candidate_blocks=candidate_blocks,
      imported_blocks=0,
      skipped_blocks=skipped_blocks,
    )

  detail = import_project_knowledge(
    settings,
    payload.project_id,
    KnowledgeImportRequest(items=items),
  )
  return LongInputMaterialization(
    titles=_ordered_unique_strings(titles),
    original_length=original_length,
    candidate_blocks=candidate_blocks,
    imported_blocks=imported_blocks,
    skipped_blocks=skipped_blocks,
    project_detail=detail,
  )


def _payload_with_auto_material_references(
  payload: AgentChatRequest,
  materialization: LongInputMaterialization,
) -> AgentChatRequest:
  if not materialization.titles:
    return payload
  references = _ordered_unique_strings([*materialization.titles, *payload.reference_filenames])[:20]
  return payload.model_copy(update={"reference_filenames": references})


def _long_input_materialization_changes(materialization: LongInputMaterialization) -> list[str]:
  if not materialization.titles:
    if materialization.skipped_blocks > 0:
      return [
        (
          "本轮超长输入未写入资料库：没有识别到和作品创作相关的资料段；"
          f"已跳过 {materialization.skipped_blocks} 段。"
        )
      ]
    return []
  filter_text = (
    f"筛选保留 {materialization.imported_blocks}/{materialization.candidate_blocks} 段，"
    f"跳过 {materialization.skipped_blocks} 段；"
    if materialization.candidate_blocks > 0
    else ""
  )
  return [
    (
      f"已把本轮超长输入按 {len(materialization.titles)} 份资料导入项目资料库；"
      f"{filter_text}原文约 {materialization.original_length} 字，执行时通过资料库检索使用。"
    )
  ]


def _plan_with_reference_note(plan: AgentPlan, reference_filenames: list[str]) -> AgentPlan:
  if not reference_filenames:
    return plan
  actions = [
    action.model_copy(
      update={
        "instruction": _preserve_thread_context_text(
          _append_reference_note(action.instruction, reference_filenames),
          3900,
        )
      }
    )
    for action in plan.actions
  ]
  return plan.model_copy(update={"actions": actions})


def _result_with_session_changes(
  result: AgentChatResult,
  changes: list[str],
  project_detail: object | None,
) -> AgentChatResult:
  if not changes and project_detail is None:
    return result
  merged_changes = _ordered_unique_strings([*changes, *result.changes])
  update_payload: dict[str, object] = {"changes": merged_changes}
  if project_detail is not None and result.project_detail is None:
    update_payload["project_detail"] = project_detail
  return result.model_copy(update=update_payload)


def _list_from_raw(value: object) -> list[str]:
  if isinstance(value, list):
    return [str(item).strip() for item in value if str(item).strip()]
  if isinstance(value, str) and value.strip():
    return [item.strip() for item in re.split(r"[,，、|\s]+", value) if item.strip()]
  return []


def _latest_user_text(payload: AgentChatRequest) -> str:
  latest_user_message = next(
    (item for item in reversed(payload.messages) if item.role == "user" and item.content.strip()),
    None,
  )
  return _agent_message_model_content(latest_user_message, limit=1200) if latest_user_message is not None else ""


def _skill_query_text(payload: AgentChatRequest) -> str:
  parts = [_latest_user_text(payload)]
  parts.extend(str(item).strip() for item in payload.skill_hints if str(item).strip())
  parts.extend(str(item).strip() for item in payload.reference_filenames if str(item).strip())
  return "\n".join(item for item in parts if item.strip())


def _chapter_generation_target_for_action(
  runtime: RuntimeState,
  chapter,
  *,
  requested_target: int,
  instruction: str,
) -> int:
  explicit_target = explicit_length_target(instruction)
  explicit_length_requested = instruction_requests_explicit_length(instruction)
  if explicit_target > 0:
    requested_target = explicit_target
  elif instruction_requests_full_chapter(instruction) or (runtime.architecture_ready and not explicit_length_requested):
    full_target = full_chapter_generation_target(runtime.detail, chapter)
    if full_target > 0:
      requested_target = full_target
  return recommended_chapter_generation_target(
    runtime.detail,
    chapter,
    requested_target=requested_target,
    prefer_project_budget=False if runtime.architecture_ready and requested_target > 0 else not explicit_length_requested,
  )


def _build_skill_catalog_context(settings: Settings) -> str:
  try:
    catalog = list_skill_catalog(settings)
  except Exception:
    return ""

  lines = ["可用技能目录："]
  for section in catalog.sections:
    if not section.items:
      continue
    lines.append(f"{section.title}：")
    for item in section.items:
      scenes = "、".join(item.scenes[:4])
      source = "用户技能" if item.source == "custom" else "内置"
      behavior = item.behavior.panel
      if item.behavior.mode:
        behavior = f"{behavior}/{item.behavior.mode}"
      action_hint = ""
      if item.behavior.agent_action_kind:
        agent_action = item.behavior.agent_action_kind
        if item.behavior.agent_action_mode:
          agent_action = f"{agent_action}/{item.behavior.agent_action_mode}"
        confirm_label = "需要确认" if item.behavior.agent_requires_confirmation else "无需确认"
        action_hint = f"，Agent action:{agent_action}，{confirm_label}"
      summary = item.description or item.instruction_preview
      line = f"- {item.name}（id:{item.id}，{source}，{behavior}{action_hint}）：{summary}"
      if scenes:
        line = f"{line}；适用：{scenes}"
      if item.source == "custom" and item.instruction_preview:
        line = f"{line}；规则预览：{_compact_text(item.instruction_preview, 120)}"
      lines.append(line)

  text = "\n".join(lines)
  if len(text) <= 3600:
    return text
  return f"{text[:3600].rstrip()}…"


def _builtin_skill_action_hints(settings: Settings, skill_ids: list[str]) -> list[_BuiltinSkillActionHint]:
  selected_ids = _ordered_unique_strings(skill_ids)
  if not selected_ids:
    return []
  try:
    catalog = list_skill_catalog(settings)
  except Exception:
    return []

  items_by_id = {
    item.id: item
    for section in catalog.sections
    for item in section.items
  }
  hints: list[_BuiltinSkillActionHint] = []
  for skill_id in selected_ids:
    item = items_by_id.get(skill_id)
    if item is None or item.source == "custom":
      continue
    behavior = item.behavior
    action_kind = behavior.agent_action_kind.strip()
    if not action_kind:
      continue
    hints.append(
      _BuiltinSkillActionHint(
        skill_id=item.id,
        name=item.name,
        action_kind=action_kind,
        action_mode=behavior.agent_action_mode.strip(),
        requires_confirmation=behavior.agent_requires_confirmation,
      )
    )
  return hints


def _custom_skill_ids_from_ids(settings: Settings, skill_ids: list[str]) -> list[str]:
  return match_custom_skill_ids(
    settings,
    "",
    active_skill_ids=_ordered_unique_strings(skill_ids),
    limit=5,
  )


def _resolve_agent_skill_ids(settings: Settings, payload: AgentChatRequest) -> list[str]:
  explicit_ids = _ordered_unique_strings(payload.active_skill_ids)
  return match_custom_skill_ids(
    settings,
    _skill_query_text(payload),
    active_skill_ids=explicit_ids,
    limit=5,
  )


def _skill_ids_from_plan(plan: AgentPlan | None) -> list[str]:
  if plan is None:
    return []
  skill_ids: list[str] = []
  for action in plan.actions:
    skill_ids.extend(action.skill_ids)
  return _ordered_unique_strings(skill_ids)


def _apply_skill_ids_to_plan(settings: Settings, plan: AgentPlan | None, skill_ids: list[str]) -> AgentPlan | None:
  if plan is None:
    return None
  resolved_ids = _ordered_unique_strings(skill_ids)
  if not resolved_ids and not _skill_ids_from_plan(plan):
    return plan
  actions = [
    action.model_copy(update={"skill_ids": _custom_skill_ids_from_ids(settings, [*action.skill_ids, *resolved_ids])})
    for action in plan.actions
  ]
  return plan.model_copy(update={"actions": actions})


def _brainstorm_messages_from_agent(payload: AgentChatRequest) -> list[BrainstormMessage]:
  messages: list[BrainstormMessage] = []
  for item in payload.messages[-20:]:
    content = _agent_message_model_content(item, limit=3800).strip()
    if not content or content in {"确认执行", "确认执行。"} or _looks_like_plan_reply(content):
      continue
    messages.append(BrainstormMessage(role=item.role, content=content))
  return messages


def _suggestion_from_skill_candidate(candidate) -> str:
  if candidate is None:
    return ""
  if candidate.action == "iterate" and candidate.target_skill_name.strip():
    return f"更新用户技能「{candidate.target_skill_name.strip()}」，加入这轮新要求。"
  return "把这套处理方式保存成用户技能。"


def _append_skill_suggestion(state: AgentExecutionState, suggestion: str) -> None:
  if not suggestion.strip():
    return
  state.suggestions = _ordered_unique_strings([*state.suggestions, suggestion])[:4]


def _append_reusable_skill_suggestion(settings: Settings, payload: AgentChatRequest, state: AgentExecutionState) -> None:
  if not state.last_reply.strip():
    return
  active_skill_id = state.active_skill_ids[0] if state.active_skill_ids else ""
  candidate = suggest_reusable_skill(
    settings,
    _brainstorm_messages_from_agent(payload),
    state.last_reply,
    active_skill_id,
  )
  _append_skill_suggestion(state, _suggestion_from_skill_candidate(candidate))


def _compose_execution_instruction(
  instruction: str,
  *,
  knowledge_summary: str = "",
  skill_prompt: str = "",
  limit: int = 1900,
) -> str:
  parts = [instruction.strip()] if instruction.strip() else []
  if knowledge_summary.strip():
    parts.append(f"资料库分析结论：\n{_compact_text(knowledge_summary, 700)}")
  if skill_prompt.strip():
    parts.append(f"本轮启用用户技能：\n{_compact_text(skill_prompt, 900)}")
  merged = "\n\n".join(parts).strip()
  if len(merged) <= limit:
    return merged
  return f"{merged[:limit].rstrip()}…"


def _discussion_summary(project_detail) -> str:
  entries = getattr(project_detail.story_overview, "memory_entries", []) or []
  for item in reversed(entries):
    source = str(getattr(item, "source", "manual") or "manual")
    title = str(getattr(item, "title", "") or "")
    entry_id = str(getattr(item, "id", "") or "")
    content = str(getattr(item, "content", "") or "").strip()
    if source == "auto" or not content:
      continue
    if entry_id == "project-discussion-summary" or title == "项目讨论结论":
      return content
  return ""


def _build_runtime_state(settings: Settings, project_id: str, selected_chapter_id: str = "") -> RuntimeState:
  detail = get_project_detail(settings, project_id)
  documents = project_documents_map(detail)
  document_status = {key: bool(documents.get(key, "").strip()) for key in _ARCHITECTURE_KEYS}
  discussion_summary = _discussion_summary(detail)
  selected_chapter = next((item for item in detail.chapters if item.id == selected_chapter_id), None) if selected_chapter_id else None
  written_chapters = [item for item in detail.chapters if item.exists and item.content.strip()]
  last_written = max(written_chapters, key=lambda item: item.index, default=None)
  next_chapter = next((item for item in detail.chapters if not item.exists), None)
  return RuntimeState(
    detail=detail,
    documents=documents,
    discussion_summary=discussion_summary,
    architecture_ready=all(document_status.values()),
    architecture_progress=sum(1 for value in document_status.values() if value),
    document_status=document_status,
    selected_chapter=selected_chapter,
    last_written_chapter=last_written,
    next_chapter=next_chapter,
  )


def _state_summary(runtime: RuntimeState) -> AgentStateSummary:
  selected = runtime.selected_chapter
  last_written = runtime.last_written_chapter
  next_chapter = runtime.next_chapter
  return AgentStateSummary(
    project_name=runtime.detail.name,
    genre=runtime.detail.genre,
    discussion_ready=bool(runtime.discussion_summary),
    architecture_ready=runtime.architecture_ready,
    architecture_progress=runtime.architecture_progress,
    selected_chapter_id=selected.id if selected else "",
    selected_chapter_title=selected.title if selected else "",
    selected_chapter_index=selected.index if selected else None,
    selected_chapter_exists=bool(selected.exists) if selected else False,
    last_written_chapter_id=last_written.id if last_written else "",
    last_written_chapter_title=last_written.title if last_written else "",
    last_written_chapter_index=last_written.index if last_written else None,
    next_chapter_id=next_chapter.id if next_chapter else "",
    next_chapter_title=next_chapter.title if next_chapter else "",
    next_chapter_index=next_chapter.index if next_chapter else None,
    document_status=runtime.document_status,
  )


def _discussion_context_from_messages(messages: list[object], limit: int = 6) -> str:
  collected: list[str] = []
  for item in reversed(messages):
    role = str(getattr(item, "role", "") or "")
    content = _agent_message_model_content(item, limit=900).strip()
    if role not in {"user", "assistant"} or not content:
      continue
    if content == "确认执行。":
      continue
    if _looks_like_plan_reply(content):
      continue
    label = "作者" if role == "user" else "上一轮讨论"
    collected.append(f"{label}：{content}")
    if len(collected) >= limit:
      break
  return "\n".join(reversed(collected))


def _looks_like_plan_reply(content: str) -> bool:
  normalized = str(content or "").strip()
  if not normalized:
    return False
  return (
    "当前状态：" in normalized
    and ("计划步骤：" in normalized or "准备执行：" in normalized)
  )


def _append_reference_note(instruction: str, reference_filenames: list[str]) -> str:
  names = [str(item).strip() for item in reference_filenames if str(item).strip()]
  if not names:
    return instruction.strip()
  parts = [instruction.strip()] if instruction.strip() else []
  shown_names = "、".join(names[:8])
  if len(names) > 8:
    shown_names = f"{shown_names} 等 {len(names)} 份"
  parts.append(
    f"本轮已导入参考资料：{shown_names}。请优先检索并使用这些资料，遇到冲突先指出。"
  )
  return "\n\n".join(parts).strip()


def _thread_context_from_payload(payload: AgentChatRequest) -> str:
  for item in payload.messages:
    if item.role == "system" and item.id == "thread-context":
      return item.content.strip()
  return ""


def _current_message_ids(payload: AgentChatRequest) -> list[str]:
  return _ordered_unique_strings([item.id for item in payload.messages if item.id.strip()])


def _payload_with_thread_context(settings: Settings, payload: AgentChatRequest) -> AgentChatRequest:
  if not payload.thread_id.strip():
    return payload

  try:
    context = build_project_agent_thread_context(
      settings,
      payload.project_id,
      payload.thread_id,
      query=_latest_user_text(payload),
      current_message_ids=_current_message_ids(payload),
      max_chars=3600,
    )
  except Exception:
    return payload

  if not context:
    return payload

  context_message = AgentMessage(
    id="thread-context",
    role="system",
    content=context,
    content_hash="thread-context",
    summary="本地完整对话历史检索",
  )
  recent_messages = payload.messages[-49:]
  if not recent_messages:
    return payload
  messages = [*recent_messages[:-1], context_message, recent_messages[-1]]
  return payload.model_copy(update={"messages": messages})


def _append_thread_context_note(instruction: str, payload: AgentChatRequest) -> str:
  context = _thread_context_from_payload(payload)
  if not context:
    return _preserve_thread_context_text(instruction.strip(), 3900)
  parts = [_preserve_thread_context_text(instruction.strip(), 1200)] if instruction.strip() else []
  parts.append(f"相关对话历史：\n{_preserve_thread_context_text(context, 2500)}")
  return _preserve_thread_context_text("\n\n".join(parts).strip(), 3900)


def _preserve_thread_context_text(text: str, limit: int) -> str:
  normalized = str(text or "").strip()
  if len(normalized) <= limit:
    return normalized
  head_limit = max(600, limit // 2)
  tail_limit = max(600, limit - head_limit - 18)
  return f"{normalized[:head_limit].rstrip()}\n……\n{normalized[-tail_limit:].lstrip()}"


def _instruction_requires_knowledge_review(instruction: str) -> bool:
  return bool(_KNOWLEDGE_REVIEW_PATTERN.search(instruction.strip()))


def _merge_instruction_with_knowledge_summary(instruction: str, knowledge_summary: str) -> str:
  parts = [instruction.strip()] if instruction.strip() else []
  if knowledge_summary.strip():
    parts.append(f"资料库分析结论：\n{knowledge_summary.strip()}")
  return "\n\n".join(parts).strip()


def _task_pack_kind_for_action(action_kind: str, instruction: str = "", mode: str = "") -> str:
  if action_kind in {"generate_architecture", "continue_project"}:
    return "architecture"
  if action_kind in {"chapter_generate", "chapter_workflow", "consistency_check"}:
    return "continuation"
  if action_kind == "rewrite_chapter":
    return resolve_task_pack_kind(
      kind="imitation" if mode == "humanize" else "continuation",
      instruction=instruction,
      rewrite_mode=mode,
    )
  if action_kind == "review_knowledge":
    return resolve_task_pack_kind(instruction=instruction)
  return ""


def _instruction_requests_skill_optimization(instruction: str) -> bool:
  return bool(_SKILL_OPTIMIZE_PATTERN.search(str(instruction or "").strip()))


def _plan_task_pack_kind(plan: AgentPlan | None) -> str:
  if plan is None:
    return ""
  for action in reversed(plan.actions):
    if action.kind == "review_knowledge":
      continue
    if action.task_pack_kind:
      return action.task_pack_kind
  for action in plan.actions:
    if action.task_pack_kind:
      return action.task_pack_kind
  return ""


def _build_execution_trace(
  step: int,
  action: AgentPlanAction,
  *,
  status: str = "completed",
  task_pack_kind: str = "",
  summary: str = "",
  changes: list[str] | None = None,
  material_count: int | None = None,
) -> AgentExecutionTrace:
  return AgentExecutionTrace(
    step=step,
    action_kind=action.kind,
    label=action.label,
    status=status,
    task_pack_kind=task_pack_kind or action.task_pack_kind,
    summary=summary.strip(),
    changes=list(changes or []),
    material_count=material_count,
  )


def _append_event_block(
  state: AgentExecutionState,
  *,
  event_type: str,
  title: str,
  status: str = "",
  summary: str = "",
  step: int | None = None,
  action_kind: str = "",
) -> None:
  state.event_blocks.append(
    AgentEventBlock(
      event_type=event_type,
      title=title,
      status=status,
      summary=summary.strip(),
      step=step,
      action_kind=action_kind,
    )
  )


def _append_artifact(
  state: AgentExecutionState,
  *,
  kind: str,
  title: str = "",
  summary: str = "",
  content_preview: str = "",
  metadata: dict[str, object] | None = None,
) -> None:
  state.artifacts.append(
    AgentArtifact(
      kind=kind,
      title=title.strip(),
      summary=summary.strip(),
      content_preview=_compact_text(content_preview, 600),
      metadata=dict(metadata or {}),
    )
  )


def _append_chapter_review_artifact(state: AgentExecutionState, chapter_id: str) -> None:
  reviews = getattr(getattr(state.runtime.detail, "story_overview", None), "chapter_reviews", []) or []
  review = next((item for item in reviews if getattr(item, "chapter_id", "") == chapter_id), None)
  if review is None:
    return

  issue_lines: list[str] = []
  for dimension in getattr(review, "dimensions", []) or []:
    for issue in getattr(dimension, "issues", []) or []:
      issue_lines.append(
        f"[{getattr(issue, 'level', 'warning')}] {getattr(dimension, 'label', '')}：{getattr(issue, 'title', '')}｜{getattr(issue, 'detail', '')}"
      )
  suggestion_lines = [f"建议：{item}" for item in (getattr(review, "suggestions", []) or [])]
  _append_artifact(
    state,
    kind="chapter_review",
    title=f"章节核验：第 {getattr(review, 'chapter_index', 0)} 章",
    summary=getattr(review, "summary", "") or "章节核验已完成。",
    content_preview="\n".join([getattr(review, "summary", ""), *issue_lines[:8], *suggestion_lines[:6]]),
    metadata={
      "chapter_id": chapter_id,
      "chapter_index": getattr(review, "chapter_index", 0),
      "status": getattr(review, "status", ""),
      "overall_score": getattr(review, "overall_score", 0),
      "issue_count": len(issue_lines),
      "is_stale": bool(getattr(review, "is_stale", False)),
    },
  )


def _obsidian_maintenance_action_signature(action: dict[str, object]) -> tuple[str, ...]:
  return (
    str(action.get("suggestion_id") or ""),
    str(action.get("status") or ""),
    str(action.get("draft_path") or ""),
    str(action.get("draft_content_hash") or ""),
    str(action.get("vault_relative_path") or ""),
    str(action.get("published_content_hash") or ""),
    str(action.get("merge_draft_path") or ""),
  )


def _obsidian_maintenance_action_signatures(project_dir: Path) -> set[tuple[str, ...]]:
  try:
    narrative_state = load_project_narrative_state(project_dir)
  except Exception:
    return set()
  signatures: set[tuple[str, ...]] = set()
  for item in narrative_state.get("obsidian_maintenance_actions", []) if isinstance(narrative_state, dict) else []:
    if isinstance(item, dict):
      signatures.add(_obsidian_maintenance_action_signature(item))
  return signatures


def _obsidian_action_status_label(value: object) -> str:
  status = str(value or "").strip()
  return {
    "staged": "待审草稿",
    "published": "已发布到 Vault",
    "published_outdated": "Vault 待更新",
    "published_missing": "Vault 笔记缺失",
    "draft_missing": "草稿缺失",
    "ignored": "已忽略",
  }.get(status, status or "待处理")


def _append_obsidian_maintenance_delta_artifact(
  state: AgentExecutionState,
  *,
  chapter: object,
  before_signatures: set[tuple[str, ...]],
) -> list[str]:
  obsidian = getattr(getattr(state.runtime.detail, "story_overview", None), "obsidian", None)
  if not bool(getattr(obsidian, "enabled", False)):
    return []
  try:
    chapter_index = int(getattr(chapter, "index", 0) or 0)
  except (TypeError, ValueError):
    chapter_index = 0
  if chapter_index <= 0:
    return []

  project_dir = Path(state.runtime.detail.path)
  try:
    narrative_state = load_project_narrative_state(project_dir)
  except Exception:
    return []
  actions = [
    item
    for item in narrative_state.get("obsidian_maintenance_actions", [])
    if isinstance(item, dict) and _obsidian_maintenance_action_signature(item) not in before_signatures
  ]
  if not actions:
    return []

  suggestions = {
    str(item.get("id") or ""): item
    for item in narrative_state.get("obsidian_maintenance_suggestions", [])
    if isinstance(item, dict)
  }
  related: list[tuple[dict[str, object], dict[str, object]]] = []
  for action in actions:
    suggestion = suggestions.get(str(action.get("suggestion_id") or ""))
    if not suggestion:
      continue
    source_chapters: list[int] = []
    for raw in suggestion.get("source_chapters", []) if isinstance(suggestion.get("source_chapters"), list) else []:
      try:
        source_chapter = int(raw or 0)
      except (TypeError, ValueError):
        continue
      if source_chapter > 0:
        source_chapters.append(source_chapter)
    if source_chapters and chapter_index not in source_chapters:
      continue
    related.append((suggestion, action))

  if not related:
    return []
  related.sort(key=lambda item: obsidian_maintenance_suggestion_sort_key(item[0], chapter_index), reverse=True)
  lines: list[str] = []
  for suggestion, action in related[:6]:
    title = _compact_text(suggestion.get("title") or action.get("title") or "Obsidian 维护建议", 72)
    path_text = _compact_text(
      action.get("relative_path") or action.get("vault_relative_path") or suggestion.get("suggested_path"),
      100,
    )
    status_label = _obsidian_action_status_label(action.get("status") or suggestion.get("status"))
    if path_text:
      lines.append(f"- {title}｜{status_label}｜{path_text}")
    else:
      lines.append(f"- {title}｜{status_label}")
  if not lines:
    return []

  count = len(related)
  change = f"已生成第 {chapter_index} 章相关 Obsidian 维护产物 {count} 条"
  state.changes.append(change)
  _append_artifact(
    state,
    kind="obsidian_maintenance",
    title=f"第 {chapter_index} 章 Obsidian 维护产物",
    summary=f"已生成第 {chapter_index} 章相关 Obsidian 维护产物 {count} 条。",
    content_preview="\n".join(lines),
    metadata={
      "chapter_id": str(getattr(chapter, "id", "") or ""),
      "chapter_index": chapter_index,
      "item_count": count,
      "suggestion_ids": [str(item[0].get("id") or "") for item in related[:12]],
    },
  )
  return [change]


def _review_metadata(review_status: dict[str, object]) -> dict[str, object]:
  metadata: dict[str, object] = {}
  for key in ("score", "status", "status_label", "summary", "is_stale", "updated_at", "error"):
    value = review_status.get(key)
    if value not in (None, ""):
      metadata[f"review_{key}"] = value
  return metadata


def _auto_repair_metadata(repair_result: ChapterAutoRepairResult | None) -> dict[str, object]:
  if repair_result is None:
    return {}
  metadata: dict[str, object] = {
    "review_auto_repair_attempted": repair_result.attempted,
    "review_auto_repair_applied": repair_result.applied,
    "review_auto_repair_rounds_attempted": repair_result.rounds_attempted,
    "review_auto_repair_rounds_applied": repair_result.rounds_applied,
    "review_auto_repair_score_threshold": repair_result.score_threshold,
    "review_auto_repair_max_rounds": repair_result.max_rounds,
  }
  for key, value in (
    ("review_auto_repair_reason", repair_result.reason),
    ("review_auto_repair_summary", repair_result.summary),
    ("review_auto_repair_error", repair_result.error),
    ("review_auto_repair_review_error", repair_result.review_error),
  ):
    if value:
      metadata[key] = value
  if repair_result.changes:
    metadata["review_auto_repair_changes"] = repair_result.changes
  return metadata


def _apply_review_feedback(
  *,
  reply: str,
  changes: list[str],
  suggestions: list[str],
  review_status: dict[str, object],
) -> tuple[str, list[str], list[str]]:
  message = str(review_status.get("message") or "").strip()
  if not message:
    return reply, changes, suggestions

  next_changes = [*changes, message]
  next_suggestions = [*suggestions]
  if review_status.get("error"):
    _append_ordered_unique(next_suggestions, "重新运行章节核验。")
  return f"{reply}\n\n{message}".strip(), next_changes, next_suggestions


def _apply_auto_repair_feedback(
  *,
  reply: str,
  changes: list[str],
  suggestions: list[str],
  repair_result: ChapterAutoRepairResult | None,
) -> tuple[str, list[str], list[str]]:
  if repair_result is None or not repair_result.attempted:
    return reply, changes, suggestions

  next_changes = [*changes]
  next_suggestions = [*suggestions]
  if repair_result.applied:
    review_status = repair_result.review_status or {}
    score = review_status.get("score")
    label = str(review_status.get("status_label") or "").strip()
    rounds_applied = repair_result.rounds_applied or 1
    if isinstance(score, int):
      message = f"已按章节核验自动修订 {rounds_applied} 轮；复查：{score}/100"
      if label:
        message = f"{message}（{label}）"
      message = f"{message}。"
    else:
      message = f"已按章节核验自动修订 {rounds_applied} 轮。"
    next_changes.append(message)
    if repair_result.summary:
      message = f"{message}\n{repair_result.summary}"
    return f"{reply}\n\n{message}".strip(), next_changes, next_suggestions

  reason = repair_result.error or repair_result.reason or "模型没有返回可用改动。"
  message = f"章节自动修订未写入：{reason}"
  next_changes.append(message)
  _append_ordered_unique(next_suggestions, "查看章节核验报告后指定修订重点。")
  return f"{reply}\n\n{message}".strip(), next_changes, next_suggestions


def _record_action_completion(
  state: AgentExecutionState,
  step: int,
  action: AgentPlanAction,
  *,
  task_pack_kind: str = "",
  summary: str = "",
  changes: list[str] | None = None,
  material_count: int | None = None,
) -> None:
  trace = _build_execution_trace(
    step,
    action,
    status="completed",
    task_pack_kind=task_pack_kind,
    summary=summary,
    changes=changes,
    material_count=material_count,
  )
  state.execution_trace.append(trace)
  _append_event_block(
    state,
    event_type="action_result",
    title=action.label,
    status="completed",
    summary=summary,
    step=step,
    action_kind=action.kind,
  )


def _record_action_failure(
  state: AgentExecutionState,
  step: int,
  action: AgentPlanAction,
  *,
  task_pack_kind: str = "",
  message: str,
) -> None:
  trace = _build_execution_trace(
    step,
    action,
    status="failed",
    task_pack_kind=task_pack_kind,
    summary=str(message),
  )
  state.execution_trace.append(trace)
  _append_event_block(
    state,
    event_type="action_failed",
    title=action.label,
    status="failed",
    summary=str(message),
    step=step,
    action_kind=action.kind,
  )


def _knowledge_source_count(detail, chapter_index: int = 0) -> int:
  material_count = len(getattr(detail.story_overview, "materials", []) or [])
  obsidian = getattr(detail.story_overview, "obsidian", None)
  if chapter_index > 0:
    obsidian_count = sum(
      1
      for note in list(getattr(obsidian, "notes", []) or [])
      if obsidian_note_available_for_chapter(note, chapter_index)
    )
  else:
    obsidian_count = int(getattr(obsidian, "included_count", 0) or 0)
  return material_count + obsidian_count


def _target_chapter_id_for_index(runtime: RuntimeState, chapter_index: int) -> str:
  if chapter_index <= 0:
    return ""
  chapter = next(
    (
      item
      for item in runtime.detail.chapters
      if int(getattr(item, "index", 0) or 0) == chapter_index
    ),
    None,
  )
  return str(getattr(chapter, "id", "") or "").strip()


def _knowledge_review_target_context(
  settings: Settings,
  runtime: RuntimeState,
  instruction: str,
  *,
  task_pack_kind: str = "",
  chapter_index: int = 0,
) -> str:
  chapter_id = _target_chapter_id_for_index(runtime, chapter_index)
  if not chapter_id:
    return ""
  try:
    bundle = build_project_context_bundle(
      settings,
      runtime.detail.id,
      include_blueprint=True,
      include_character_state=True,
      chapter_id=chapter_id,
      knowledge_query=instruction,
      knowledge_limit=4,
      task_pack_kind=task_pack_kind or "continuation",
      task_instruction=instruction,
    )
  except Exception:
    return ""
  return _compact_text(bundle.context_text, 4500)


def _review_project_knowledge(
  settings: Settings,
  runtime: RuntimeState,
  instruction: str,
  *,
  task_pack_kind: str = "",
  chapter_index: int = 0,
) -> tuple[str, int]:
  source_count = _knowledge_source_count(runtime.detail, chapter_index=chapter_index)
  target_context = _knowledge_review_target_context(
    settings,
    runtime,
    instruction,
    task_pack_kind=task_pack_kind,
    chapter_index=chapter_index,
  )
  distillation_summary = build_distillation_review_text(
    runtime.detail,
    kind=task_pack_kind,
    instruction=instruction,
    chapter_index=chapter_index,
  )
  if distillation_summary:
    context_block = f"\n\n目标章节上下文：\n{target_context}" if target_context else ""
    if source_count > 0:
      return (
        f"{distillation_summary}{context_block}\n\n资料库统计：当前共整理 {source_count} 份上传资料或 Obsidian 笔记。",
        source_count,
      )
    return (
      f"{distillation_summary}{context_block}\n\n资料库统计：当前没有上传资料或 Obsidian 笔记，已按现有项目文档、记忆和正文整理。",
      0,
    )

  materials = load_project_knowledge_material_contents(settings, runtime.detail.id, limit=10)
  obsidian_notes = load_project_obsidian_note_contents(
    settings,
    runtime.detail.id,
    limit=10,
    chapter_index=chapter_index,
    query=f"{task_pack_kind} {instruction}".strip(),
  )
  sources = [
    {**item, "source": "资料库"}
    for item in materials
  ] + obsidian_notes
  if not sources:
    if target_context:
      return f"资料库当前没有额外资料。\n\n目标章节上下文：\n{target_context}", 0
    return "资料库当前为空，没有可分析的资料。", 0

  material_blocks: list[str] = []
  total_chars = 0
  for index, item in enumerate(sources, start=1):
    content = str(item.get("content") or "").strip()
    snippet = _compact_text(content, 1200)
    source_label = str(item.get("source") or "资料库").strip()
    block = f"资料 {index}｜{source_label}｜{item.get('title') or '未命名'}\n{snippet}"
    material_blocks.append(block)
    total_chars += len(block)
    if total_chars >= 12000:
      break

  content = _invoke_model(
    settings,
    [
      {"role": "system", "content": _KNOWLEDGE_REVIEW_SYSTEM_PROMPT},
      {
        "role": "user",
        "content": (
          f"作品：{runtime.detail.name}\n"
          f"用户要求：{instruction.strip() or '无'}\n\n"
          f"目标章节上下文：\n{target_context or '无'}\n\n"
          f"资料库内容：\n\n{'\n\n'.join(material_blocks)}"
        ).strip(),
      },
    ],
    task_name="agent_knowledge_review",
  ).strip()

  if content:
    return content, len(sources)

  fallback_lines = [
    f"- {item.get('source') or '资料库'}｜{item.get('title') or '未命名'}：{_compact_text(item.get('content') or '', 140)}"
    for item in sources[:6]
  ]
  context_block = f"\n\n目标章节上下文：\n{target_context}" if target_context else ""
  return "已确认事实：\n" + "\n".join(fallback_lines) + context_block, len(sources)


async def _knowledge_summary_for_action(ctx: AgentActionExecutionContext, state: AgentExecutionState) -> str:
  if not state.knowledge_summary.strip():
    return ""
  if not ctx.action.chapter_id:
    return state.knowledge_summary
  if state.knowledge_summary_chapter_id in {"", ctx.action.chapter_id}:
    return state.knowledge_summary
  if ctx.action.chapter_id in state.chapter_knowledge_summaries:
    return state.chapter_knowledge_summaries[ctx.action.chapter_id]

  chapter = next((item for item in state.runtime.detail.chapters if item.id == ctx.action.chapter_id), None)
  chapter_index = int(getattr(chapter, "index", 0) or 0) if chapter is not None else 0
  if chapter_index <= 0:
    return state.knowledge_summary

  knowledge_summary, material_count = await asyncio.to_thread(
    _review_project_knowledge,
    ctx.settings,
    state.runtime,
    ctx.action.instruction,
    task_pack_kind=ctx.task_pack_kind,
    chapter_index=chapter_index,
  )
  state.chapter_knowledge_summaries[ctx.action.chapter_id] = knowledge_summary
  if material_count > 0:
    state.changes.append(f"已按第 {chapter_index} 章刷新资料库和 Obsidian 分析")
  _append_artifact(
    state,
    kind="knowledge_summary",
    title=f"资料库分析：第 {chapter_index} 章",
    summary=f"已按第 {chapter_index} 章刷新资料库和 Obsidian 分析。" if material_count > 0 else "已检查目标章节资料。",
    content_preview=knowledge_summary,
    metadata={"material_count": material_count, "chapter_id": ctx.action.chapter_id, "chapter_index": chapter_index},
  )
  return knowledge_summary


def _build_route_context(runtime: RuntimeState, messages: list[object]) -> str:
  chapter_lines = []
  for item in runtime.detail.chapters[:12]:
    label = "已有正文" if item.exists and item.content.strip() else "待写"
    chapter_lines.append(f"- 第 {item.index} 章《{item.title}》：{label}")

  history_lines = []
  for item in messages[-8:]:
    role = str(getattr(item, "role", "") or "")
    content = _agent_message_model_content(item, limit=650).strip()
    if role and content:
      history_lines.append(f"{role}: {content}")

  selected = runtime.selected_chapter
  return "\n".join(
    [
      f"作品：{runtime.detail.name}",
      f"题材：{runtime.detail.genre}",
      f"已有讨论结论：{'是' if runtime.discussion_summary else '否'}",
      f"架构完整度：{runtime.architecture_progress}/5",
      (
        f"当前选中章节：第 {selected.index} 章《{selected.title}》"
        if selected
        else "当前选中章节：无"
      ),
      (
        f"最近已写章节：第 {runtime.last_written_chapter.index} 章《{runtime.last_written_chapter.title}》"
        if runtime.last_written_chapter
        else "最近已写章节：无"
      ),
      (
        f"下一待写章节：第 {runtime.next_chapter.index} 章《{runtime.next_chapter.title}》"
        if runtime.next_chapter
        else "下一待写章节：无"
      ),
      "章节列表：",
      *chapter_lines,
      "最近对话：",
      *history_lines,
    ]
  ).strip()


def _cn_number_to_int(value: str) -> int:
  stripped = str(value or "").strip()
  if not stripped:
    return 0
  if stripped.isdigit():
    return int(stripped)

  digit_map = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
  }
  unit_map = {"十": 10, "百": 100}
  total = 0
  current = 0
  for char in stripped:
    if char in digit_map:
      current = digit_map[char]
      continue
    if char in unit_map:
      unit = unit_map[char]
      total += (current or 1) * unit
      current = 0
  total += current
  return total


def _chapter_number_from_text(text: str) -> int:
  target_matched = _TARGET_CHAPTER_NUMBER_PATTERN.search(text)
  if target_matched:
    return _cn_number_to_int(target_matched.group(1))

  matched = _CHAPTER_NUMBER_PATTERN.search(text)
  if not matched:
    return 0
  return _cn_number_to_int(matched.group(1))


def _append_chapter_index(indexes: list[int], value: int, limit: int) -> None:
  if value > 0 and value not in indexes and len(indexes) < limit:
    indexes.append(value)


def _chapter_range_indexes_from_text(text: str, limit: int = 6) -> list[int]:
  normalized = str(text or "")
  indexes: list[int] = []
  for matched in _CHAPTER_RANGE_PATTERN.finditer(normalized):
    start = _cn_number_to_int(matched.group(1))
    end = _cn_number_to_int(matched.group(2))
    if start <= 0 or end <= 0:
      continue
    lower, upper = (start, end) if start <= end else (end, start)
    for chapter_index in range(lower, upper + 1):
      _append_chapter_index(indexes, chapter_index, limit)
  return indexes


def _capability_chapter_indexes_from_text(text: str, limit: int = 6) -> list[int]:
  normalized = str(text or "")
  indexes: list[int] = []
  for pattern in _CAPABILITY_CHAPTER_NUMBER_PATTERNS:
    matches = list(re.finditer(pattern, normalized, flags=re.IGNORECASE))
    if matches:
      for matched in reversed(matches):
        _append_chapter_index(indexes, _cn_number_to_int(matched.group(1)), limit)
      break

  for chapter_index in _chapter_range_indexes_from_text(normalized, limit):
    _append_chapter_index(indexes, chapter_index, limit)

  for matched in _CHAPTER_NUMBER_PATTERN.finditer(normalized):
    _append_chapter_index(indexes, _cn_number_to_int(matched.group(1)), limit)
  return indexes


def _capability_chapter_number_from_text(text: str) -> int:
  indexes = _capability_chapter_indexes_from_text(text, limit=1)
  return indexes[0] if indexes else 0


def _capability_context_chapter_indexes(runtime: RuntimeState, instruction: str) -> tuple[list[int], bool]:
  normalized = str(instruction or "").strip()
  chapter_indexes = _capability_chapter_indexes_from_text(normalized)
  if chapter_indexes:
    return chapter_indexes, True
  if _ARCHITECTURE_CONTEXT_PATTERN.search(normalized):
    return [], True
  if _NEXT_CHAPTER_HINT_PATTERN.search(normalized) and runtime.next_chapter is not None:
    return [int(getattr(runtime.next_chapter, "index", 0) or 0)], True
  if runtime.selected_chapter is not None:
    return [int(getattr(runtime.selected_chapter, "index", 0) or 0)], True
  return [], False


def _capability_context_scope(runtime: RuntimeState, instruction: str) -> tuple[int, bool]:
  chapter_indexes, include_obsidian_suggestions = _capability_context_chapter_indexes(runtime, instruction)
  return (chapter_indexes[0] if chapter_indexes else 0), include_obsidian_suggestions


def _chapter_number_from_text_for_action(text: str, kind: str, mode: str = "") -> int:
  normalized = str(text or "")
  action_patterns = {
    "chapter_generate": r"(?:生成|续写|写|补写|扩写)\s*第\s*([0-9零一二三四五六七八九十百两]+)\s*章",
    "rewrite_chapter": r"(?:重写|改写|润色|修订|定稿|去\s*ai|处理)\s*第\s*([0-9零一二三四五六七八九十百两]+)\s*章",
    "consistency_check": r"(?:检查|判断)\s*第\s*([0-9零一二三四五六七八九十百两]+)\s*章",
  }
  if kind == "chapter_workflow":
    if mode == "scenes":
      action_patterns[kind] = r"(?:拆(?:场景)?|场景规划)\s*第\s*([0-9零一二三四五六七八九十百两]+)\s*章"
    elif mode == "draft":
      action_patterns[kind] = action_patterns["chapter_generate"]
    else:
      action_patterns[kind] = r"(?:诊断|判断|检查|分析)\s*第\s*([0-9零一二三四五六七八九十百两]+)\s*章"

  pattern = action_patterns.get(kind)
  if pattern:
    matched = re.search(pattern, normalized)
    if matched:
      return _cn_number_to_int(matched.group(1))

  return _chapter_number_from_text(normalized)


def _chapter_title_from_text(text: str) -> str:
  matched = _CHAPTER_TITLE_PATTERN.search(text)
  return matched.group(1).strip() if matched else ""


def _new_chapter_count_from_text(text: str) -> int:
  matched = _NEW_CHAPTER_COUNT_PATTERN.search(text)
  if not matched:
    return 0
  return _cn_number_to_int(matched.group(1))


def _planner_available(settings: Settings) -> bool:
  try:
    model_config = load_config(settings).model
  except Exception:
    return False

  base_url = model_config.base_url.strip().lower()
  return bool(model_config.api_key.strip() and model_config.model_name.strip() and base_url and "example.com" not in base_url)


def _bool_from_value(value: object, default: bool = False) -> bool:
  if isinstance(value, bool):
    return value
  if isinstance(value, str):
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y", "是"}:
      return True
    if normalized in {"false", "0", "no", "n", "否"}:
      return False
  return default


def _int_from_value(value: object, default: int = 0) -> int:
  try:
    return int(value or default)
  except (TypeError, ValueError):
    return default


def _chapter_step_text(action: AgentPlanAction, runtime: RuntimeState) -> str:
  chapter = next((item for item in runtime.detail.chapters if item.id == action.chapter_id), None)
  chapter_label = (
    f"第 {chapter.index} 章《{chapter.title}》"
    if chapter is not None
    else "目标章节"
  )

  if action.kind == "review_knowledge":
    chapter_index = int(getattr(chapter, "index", 0) or 0) if chapter is not None else 0
    source_count = _knowledge_source_count(runtime.detail, chapter_index=chapter_index)
    if source_count > 0:
      scope_text = f"第 {chapter_index} 章可用的" if chapter_index > 0 else ""
      return f"先通读{scope_text}资料库和 Obsidian 里的 {source_count} 份资料，提炼事实、线索和硬约束"
    return "先检查资料库是否有可用资料，再决定后续怎么执行"

  if action.kind == "generate_architecture":
    return "生成并写回整书架构文件"

  if action.kind == "continue_project":
    return f"基于现有架构继续扩写后续 {action.new_chapters or 5} 章规划"

  if action.kind == "chapter_generate":
    return f"生成{chapter_label}正文并写回项目"

  if action.kind == "chapter_workflow":
    if action.mode == "scenes":
      return f"拆出{chapter_label}的场景清单"
    if action.mode == "draft":
      return f"续写{chapter_label}正文并写回项目"
    return f"判断{chapter_label}当前最该处理的问题"

  if action.kind == "consistency_check":
    return f"检查{chapter_label}的一致性"

  if action.kind == "rewrite_chapter":
    rewrite_label = {
      "finalize": "整理成定稿",
      "humanize": "调整成更自然的写法",
      "polish": "润色表达和节奏",
    }.get(action.mode or "polish", "修订正文")
    return f"{rewrite_label}，并写回{chapter_label}"

  if action.kind == "brainstorm":
    return "读取当前项目上下文，并给出这一轮判断和建议"

  if action.kind == "skill_optimize":
    return "把本轮写作规则整理成可复用的用户技能"

  return action.label or "执行当前动作"


def _plan_summary_from_actions(actions: list[AgentPlanAction], runtime: RuntimeState) -> str:
  kinds = [item.kind for item in actions]
  if not kinds:
    return "已读取当前状态，可以继续处理。"
  if kinds == ["brainstorm"]:
    return "已整理当前项目上下文，可以继续讨论建议。"
  if "generate_architecture" in kinds and "review_knowledge" in kinds:
    return "已读取资料和当前项目，计划重新整理整书架构。"
  if "generate_architecture" in kinds:
    return "已读取当前项目状态，计划重新整理整书架构。"
  if "chapter_generate" in kinds:
    return "已读取当前项目和章节状态，计划生成正文。"
  if "rewrite_chapter" in kinds:
    return "已读取当前章节状态，计划按要求修订正文。"
  if "continue_project" in kinds:
    return "已读取现有架构，计划继续扩写后续规划。"
  if "skill_optimize" in kinds:
    return "已读取当前对话，计划整理或更新用户技能。"
  return "已读取当前状态，建议按下面顺序处理。"


def _review_knowledge_scope_chapter_id(actions: list[AgentPlanAction], start_index: int) -> str:
  for item in actions[start_index + 1:]:
    if item.kind == "generate_architecture":
      return ""
    if item.chapter_id and item.kind in {"chapter_generate", "chapter_workflow", "consistency_check", "rewrite_chapter"}:
      return item.chapter_id
  return ""


def _scope_review_knowledge_actions(actions: list[AgentPlanAction]) -> list[AgentPlanAction]:
  scoped: list[AgentPlanAction] = []
  for index, action in enumerate(actions):
    if action.kind == "review_knowledge" and not action.chapter_id:
      chapter_id = _review_knowledge_scope_chapter_id(actions, index)
      if chapter_id:
        action = action.model_copy(update={"chapter_id": chapter_id})
    scoped.append(action)
  return scoped


def _action_requires_existing_chapter(kind: str, mode: str = "") -> bool:
  return kind in {"rewrite_chapter", "consistency_check"} or (kind == "chapter_workflow" and mode == "diagnose")


def _resolve_target_chapter_from_plan(runtime: RuntimeState, kind: str, payload: dict[str, object]) -> object | None:
  chapter_target = str(payload.get("chapter_target") or "auto").strip().lower()
  chapter_index = _int_from_value(payload.get("chapter_index"), 0)
  chapter_title = str(payload.get("chapter_title") or "").strip()
  mode = str(payload.get("mode") or "").strip()
  require_existing = _action_requires_existing_chapter(kind, mode)

  explicit = _find_chapter(runtime, chapter_index, chapter_title)
  if explicit is not None and (not require_existing or explicit.exists and explicit.content.strip()):
    return explicit

  if chapter_target == "selected" and runtime.selected_chapter is not None:
    chapter = runtime.selected_chapter
    if not require_existing or chapter.exists and chapter.content.strip():
      return chapter
    return None

  if chapter_target == "next" and runtime.next_chapter is not None and not require_existing:
    return runtime.next_chapter

  if chapter_target == "last_written" and runtime.last_written_chapter is not None:
    chapter = runtime.last_written_chapter
    if not require_existing or chapter.exists and chapter.content.strip():
      return chapter
    return None

  decision = RoutingDecision(
    chapter_index=chapter_index,
    chapter_title=chapter_title,
    use_next_chapter=chapter_target == "next",
  )
  return _resolve_target_chapter(runtime, decision, require_existing=require_existing)


def _build_action_from_plan_payload(
  runtime: RuntimeState,
  payload: dict[str, object],
  instruction: str,
  request: AgentChatRequest,
  future_chapter_id: str = "",
) -> tuple[AgentPlanAction | None, str | None]:
  kind = str(payload.get("kind") or "").strip()
  mode = str(payload.get("mode") or "").strip()
  action_instruction = str(payload.get("instruction") or "").strip() or instruction
  action_skill_ids = _list_from_raw(payload.get("skill_ids"))[:5]
  user_chapter_index = _chapter_number_from_text_for_action(instruction, kind, mode)
  user_chapter_title = _chapter_title_from_text(instruction)
  user_explicit_chapter = bool(user_chapter_index or user_chapter_title)
  if user_explicit_chapter:
    action_instruction = instruction

  if kind not in {
    "brainstorm",
    "review_knowledge",
    "generate_architecture",
    "continue_project",
    "chapter_generate",
    "chapter_workflow",
    "consistency_check",
    "rewrite_chapter",
    "skill_optimize",
  }:
    return None, f"规划结果里出现了不支持的动作：{kind or '空'}"

  if kind in {"brainstorm", "review_knowledge", "generate_architecture", "skill_optimize"}:
    default_label = {
      "brainstorm": "继续讨论项目方向",
      "review_knowledge": "分析资料库",
      "generate_architecture": "生成整书架构",
      "skill_optimize": "整理用户技能",
    }[kind]
    return AgentPlanAction(
      kind=kind,
      label=str(payload.get("label") or "").strip() or default_label,
      task_pack_kind=_task_pack_kind_for_action(kind, action_instruction, mode),
      instruction=action_instruction,
      skill_ids=action_skill_ids,
    ), None

  future_chapter = (
    next((item for item in runtime.detail.chapters if item.id == future_chapter_id), None)
    if future_chapter_id
    else None
  )

  if user_explicit_chapter and kind in {
    "chapter_generate",
    "chapter_workflow",
    "consistency_check",
    "rewrite_chapter",
  }:
    payload = dict(payload)
    if user_chapter_index:
      payload["chapter_index"] = user_chapter_index
    if user_chapter_title:
      payload["chapter_title"] = user_chapter_title
    payload["chapter_target"] = "exact"

  if kind == "continue_project":
    return AgentPlanAction(
      kind=kind,
      label=str(payload.get("label") or "").strip() or "扩写后续章节规划",
      task_pack_kind=_task_pack_kind_for_action(kind, action_instruction, mode),
      instruction=action_instruction,
      new_chapters=max(0, _int_from_value(payload.get("new_chapters"), 5)) or 5,
      style_name=request.style_name,
      xp_preset=request.xp_preset,
      skill_ids=action_skill_ids,
    ), None

  chapter = future_chapter or _resolve_target_chapter_from_plan(runtime, kind, payload)
  if chapter is None:
    return None, "当前规划指向了一个不存在或不可处理的章节。"
  payload_label = "" if user_explicit_chapter else str(payload.get("label") or "").strip()

  if kind == "chapter_generate":
    requested_target = max(0, _int_from_value(payload.get("target_words"), 1800)) or 1800
    target_words = _chapter_generation_target_for_action(
      runtime,
      chapter,
      requested_target=requested_target,
      instruction=action_instruction,
    )
    return AgentPlanAction(
      kind=kind,
      label=payload_label or f"生成第 {chapter.index} 章正文",
      task_pack_kind=_task_pack_kind_for_action(kind, action_instruction, mode),
      chapter_id=chapter.id,
      instruction=action_instruction,
      target_words=target_words,
      style_name=request.style_name,
      xp_preset=request.xp_preset,
      characters_involved=request.characters_involved,
      key_items=request.key_items,
      scene_location=request.scene_location,
      time_constraint=request.time_constraint,
      skill_ids=action_skill_ids,
    ), None

  if kind == "chapter_workflow":
    workflow_mode = mode if mode in {"diagnose", "scenes", "draft"} else "diagnose"
    requested_target = (
      max(0, _int_from_value(payload.get("target_words"), 1800 if workflow_mode == "draft" else 1200))
      or (1800 if workflow_mode == "draft" else 1200)
    )
    target_words = (
      _chapter_generation_target_for_action(
        runtime,
        chapter,
        requested_target=requested_target,
        instruction=action_instruction,
      )
      if workflow_mode == "draft"
      else requested_target
    )
    return AgentPlanAction(
      kind=kind,
      label=payload_label or (
        f"拆第 {chapter.index} 章场景" if workflow_mode == "scenes"
        else f"续写第 {chapter.index} 章" if workflow_mode == "draft"
        else f"判断第 {chapter.index} 章"
      ),
      task_pack_kind=_task_pack_kind_for_action(kind, action_instruction, workflow_mode),
      chapter_id=chapter.id,
      mode=workflow_mode,
      instruction=action_instruction,
      target_words=target_words,
      style_name=request.style_name,
      xp_preset=request.xp_preset,
      skill_ids=action_skill_ids,
    ), None

  if kind == "consistency_check":
    return AgentPlanAction(
      kind=kind,
      label=payload_label or f"检查第 {chapter.index} 章一致性",
      task_pack_kind=_task_pack_kind_for_action(kind, action_instruction, mode),
      chapter_id=chapter.id,
      instruction=action_instruction,
      skill_ids=action_skill_ids,
    ), None

  rewrite_mode = mode if mode in {"finalize", "polish", "humanize"} else "polish"
  if future_chapter is None and (not chapter.exists or not chapter.content.strip()):
    return None, "要修订的章节还没有正文，先生成正文，或者先手动写一版。"
  return AgentPlanAction(
    kind="rewrite_chapter",
    label=payload_label or f"修订第 {chapter.index} 章",
    task_pack_kind=_task_pack_kind_for_action("rewrite_chapter", action_instruction, rewrite_mode),
    chapter_id=chapter.id,
    mode=rewrite_mode,
    instruction=action_instruction,
    style_name=request.style_name,
    xp_preset=request.xp_preset,
    skill_ids=action_skill_ids,
  ), None


def _ensure_plan_dependencies(runtime: RuntimeState, instruction: str, actions: list[AgentPlanAction]) -> list[AgentPlanAction]:
  next_actions = list(actions)
  if not next_actions:
    return next_actions

  action_kinds = [item.kind for item in next_actions]
  if _instruction_requires_knowledge_review(instruction) and "review_knowledge" not in action_kinds:
    next_actions.insert(
      0,
      AgentPlanAction(
        kind="review_knowledge",
        label="分析资料库",
        task_pack_kind=_task_pack_kind_for_action("review_knowledge", instruction),
        instruction=instruction,
      ),
    )
    action_kinds = [item.kind for item in next_actions]

  needs_architecture = any(
    item.kind in {"chapter_generate", "rewrite_chapter", "continue_project"}
    or item.kind == "chapter_workflow" and item.mode == "draft"
    for item in next_actions
  )
  if needs_architecture and not runtime.architecture_ready and "generate_architecture" not in action_kinds:
    insert_at = 1 if next_actions and next_actions[0].kind == "review_knowledge" else 0
    next_actions.insert(
      insert_at,
      AgentPlanAction(
        kind="generate_architecture",
        label="补齐整书架构",
        task_pack_kind=_task_pack_kind_for_action("generate_architecture", instruction),
        instruction=instruction,
      ),
    )

  return _scope_review_knowledge_actions(next_actions)


def _longform_generation_action(action: AgentPlanAction) -> bool:
  return action.kind == "chapter_generate" or (action.kind == "chapter_workflow" and action.mode == "draft")


def _chapter_index_for_plan_action(runtime: RuntimeState, action: AgentPlanAction) -> int:
  chapter = next((item for item in runtime.detail.chapters if item.id == action.chapter_id), None)
  return int(getattr(chapter, "index", 0) or 0) if chapter is not None else 0


def _chapter_range_generation_label(action: AgentPlanAction, chapter_index: int) -> str:
  if action.kind == "chapter_workflow" and action.mode == "draft":
    return f"续写第 {chapter_index} 章"
  return f"生成第 {chapter_index} 章正文"


def _expand_chapter_range_generation_actions(
  runtime: RuntimeState,
  instruction: str,
  actions: list[AgentPlanAction],
) -> list[AgentPlanAction]:
  range_indexes = _chapter_range_indexes_from_text(
    instruction,
    limit=_MAX_CHAPTER_RANGE_GENERATION_ACTIONS + 1,
  )
  if len(range_indexes) < 2 or len(range_indexes) > _MAX_CHAPTER_RANGE_GENERATION_ACTIONS:
    return actions

  core_actions = [item for item in actions if item.kind not in {"review_knowledge", "generate_architecture"}]
  if len(core_actions) != 1 or not _longform_generation_action(core_actions[0]):
    return actions

  generation_indexes = [
    _chapter_index_for_plan_action(runtime, item)
    for item in actions
    if _longform_generation_action(item)
  ]
  if set(range_indexes).issubset({item for item in generation_indexes if item > 0}):
    return actions

  base_action = core_actions[0]
  expanded_actions: list[AgentPlanAction] = []
  for chapter_index in range_indexes:
    chapter = _find_chapter(runtime, chapter_index)
    if chapter is None:
      return actions

    requested_target = base_action.target_words or 1800
    target_words = _chapter_generation_target_for_action(
      runtime,
      chapter,
      requested_target=requested_target,
      instruction=base_action.instruction or instruction,
    )
    expanded_actions.append(
      base_action.model_copy(
        update={
          "label": _chapter_range_generation_label(base_action, chapter_index),
          "chapter_id": chapter.id,
          "target_words": target_words,
        }
      )
    )

  next_actions: list[AgentPlanAction] = []
  for action in actions:
    if action is base_action:
      next_actions.extend(expanded_actions)
    else:
      next_actions.append(action)
  return next_actions


def _chapter_range_generation_limit_message(instruction: str, actions: list[AgentPlanAction]) -> str:
  range_indexes = _chapter_range_indexes_from_text(
    instruction,
    limit=_MAX_CHAPTER_RANGE_GENERATION_ACTIONS + 1,
  )
  if len(range_indexes) <= _MAX_CHAPTER_RANGE_GENERATION_ACTIONS:
    return ""
  if any(_longform_generation_action(action) for action in actions):
    return (
      f"一次直接生成正文最多支持 {_MAX_CHAPTER_RANGE_GENERATION_ACTIONS} 章。"
      "请把章节范围分成 2 到 3 章一批，或先整理章节蓝图。"
    )
  return ""


def _longform_rewrite_action(action: AgentPlanAction) -> bool:
  return action.kind == "rewrite_chapter"


def _longform_content_write_action(action: AgentPlanAction) -> bool:
  return _longform_generation_action(action) or _longform_rewrite_action(action)


def _latest_planned_content_chapter_id(actions: list[AgentPlanAction]) -> str:
  for action in reversed(actions):
    if action.chapter_id and _longform_content_write_action(action):
      return action.chapter_id
  return ""


def _future_chapter_id_for_followup_action(
  runtime: RuntimeState,
  instruction: str,
  raw_action: dict[str, object],
  actions: list[AgentPlanAction],
) -> str:
  kind = str(raw_action.get("kind") or "").strip()
  mode = str(raw_action.get("mode") or "").strip()
  if not _action_requires_existing_chapter(kind, mode):
    return ""

  pending_chapter_id = _latest_planned_content_chapter_id(actions)
  if not pending_chapter_id:
    return ""

  pending_chapter = next((item for item in runtime.detail.chapters if item.id == pending_chapter_id), None)
  if pending_chapter is None:
    return ""

  chapter_target = str(raw_action.get("chapter_target") or "auto").strip().lower()
  if chapter_target == "last_written":
    return pending_chapter_id
  if chapter_target == "next" and runtime.next_chapter is not None and runtime.next_chapter.id == pending_chapter_id:
    return pending_chapter_id
  if chapter_target == "selected" and runtime.selected_chapter is not None and runtime.selected_chapter.id == pending_chapter_id:
    return pending_chapter_id

  raw_chapter_index = _int_from_value(raw_action.get("chapter_index"), 0)
  raw_chapter_title = str(raw_action.get("chapter_title") or "").strip()
  raw_chapter = _find_chapter(runtime, raw_chapter_index, raw_chapter_title)
  if raw_chapter is not None:
    return pending_chapter_id if raw_chapter.id == pending_chapter_id else ""

  user_chapter_index = _chapter_number_from_text_for_action(instruction, kind, mode)
  user_chapter_title = _chapter_title_from_text(instruction)
  user_chapter = _find_chapter(runtime, user_chapter_index, user_chapter_title)
  if user_chapter is not None:
    return pending_chapter_id if user_chapter.id == pending_chapter_id else ""

  if chapter_target in {"", "auto"}:
    return pending_chapter_id
  return ""


def _longform_supervision_enabled(action: AgentPlanAction) -> bool:
  if not _longform_content_write_action(action) or not action.chapter_id:
    return False
  return not bool(_LONGFORM_SUPERVISION_SKIP_PATTERN.search(action.instruction or ""))


def _has_later_action_for_chapter(
  actions: list[AgentPlanAction],
  start_index: int,
  *,
  chapter_id: str,
  kind: str,
  mode: str = "",
) -> bool:
  for item in actions[start_index + 1:]:
    if item.kind != kind or item.chapter_id != chapter_id:
      continue
    if mode and item.mode != mode:
      continue
    return True
  return False


def _has_later_content_write_for_chapter(actions: list[AgentPlanAction], start_index: int, chapter_id: str) -> bool:
  for item in actions[start_index + 1:]:
    if item.chapter_id == chapter_id and _longform_content_write_action(item):
      return True
  return False


def _longform_humanize_instruction(action: AgentPlanAction) -> str:
  parts = [
    action.instruction.strip(),
    "生成后按长篇章节入稿标准做去 AI 改稿：保留剧情事实、人物关系、信息顺序和伏笔，只处理解释腔、模板句、总结句、对白同质化和节奏过匀的问题。",
  ]
  return "\n\n".join(item for item in parts if item).strip()


def _longform_consistency_instruction(action: AgentPlanAction) -> str:
  parts = [
    action.instruction.strip(),
    "生成并去 AI 后复查这一章是否和前文、项目记忆、架构总览、人物状态、道具线索、时间地点发生冲突；只报告可被项目来源验证的问题。",
  ]
  return "\n\n".join(item for item in parts if item).strip()


def _supervise_longform_chapter_actions(actions: list[AgentPlanAction]) -> list[AgentPlanAction]:
  supervised: list[AgentPlanAction] = []
  for index, action in enumerate(actions):
    supervised.append(action)
    if not _longform_supervision_enabled(action):
      continue

    has_later_rewrite = _has_later_action_for_chapter(
      actions,
      index,
      chapter_id=action.chapter_id,
      kind="rewrite_chapter",
    )
    has_humanize = _has_later_action_for_chapter(
      actions,
      index,
      chapter_id=action.chapter_id,
      kind="rewrite_chapter",
      mode="humanize",
    )
    has_consistency = _has_later_action_for_chapter(
      actions,
      index,
      chapter_id=action.chapter_id,
      kind="consistency_check",
    )
    has_later_content_write = _has_later_content_write_for_chapter(actions, index, action.chapter_id)
    should_add_humanize = (
      _longform_generation_action(action) and not has_humanize and not has_later_rewrite
      or _longform_rewrite_action(action) and action.mode != "humanize" and not has_humanize and not has_later_rewrite
    )
    if should_add_humanize:
      supervised.append(
        AgentPlanAction(
          kind="rewrite_chapter",
          label="去 AI 并保留剧情事实",
          task_pack_kind=_task_pack_kind_for_action("rewrite_chapter", action.instruction, "humanize"),
          chapter_id=action.chapter_id,
          mode="humanize",
          instruction=_longform_humanize_instruction(action),
          style_name=action.style_name,
          xp_preset=action.xp_preset,
          skill_ids=action.skill_ids,
        )
      )
    if not has_consistency and not has_later_content_write:
      supervised.append(
        AgentPlanAction(
          kind="consistency_check",
          label="复查章节连续性",
          task_pack_kind=_task_pack_kind_for_action("consistency_check", action.instruction),
          chapter_id=action.chapter_id,
          instruction=_longform_consistency_instruction(action),
          skill_ids=action.skill_ids,
        )
      )
  return supervised


def _enhance_longform_plan(runtime: RuntimeState, plan: AgentPlan | None) -> AgentPlan | None:
  if plan is None:
    return None
  next_actions = _supervise_longform_chapter_actions(plan.actions)
  if len(next_actions) == len(plan.actions):
    return plan
  return plan.model_copy(
    update={
      "summary": (
        f"{plan.summary.strip()} 已把章节写回后的语言处理和连续性复查纳入执行顺序。"
        if plan.summary.strip()
        else "已把章节写回后的语言处理和连续性复查纳入执行顺序。"
      ),
      "steps": [_chapter_step_text(action, runtime) for action in next_actions],
      "actions": next_actions,
    }
  )


def _default_requires_confirmation(actions: list[AgentPlanAction]) -> bool:
  return any(
    item.kind in {"generate_architecture", "continue_project", "chapter_generate", "rewrite_chapter", "skill_optimize"}
    or item.kind == "chapter_workflow" and item.mode == "draft"
    for item in actions
  )


def _chapter_for_builtin_skill_action(
  runtime: RuntimeState,
  hint: _BuiltinSkillActionHint,
  base_action: AgentPlanAction | None,
):
  if base_action is not None and base_action.chapter_id:
    chapter = next((item for item in runtime.detail.chapters if item.id == base_action.chapter_id), None)
    if chapter is not None:
      return chapter

  require_existing = _action_requires_existing_chapter(hint.action_kind, hint.action_mode)
  decision = RoutingDecision()
  return _resolve_target_chapter(runtime, decision, require_existing=require_existing)


def _action_from_builtin_skill_hint(
  runtime: RuntimeState,
  request: AgentChatRequest,
  hint: _BuiltinSkillActionHint,
  instruction: str,
  base_action: AgentPlanAction | None = None,
) -> AgentPlanAction | None:
  action_kind = hint.action_kind
  action_mode = hint.action_mode
  base_instruction = str(base_action.instruction if base_action is not None else "").strip()
  action_instruction = base_instruction or instruction
  custom_skill_ids = base_action.skill_ids if base_action is not None else []

  if action_kind in {"brainstorm", "review_knowledge", "generate_architecture", "skill_optimize"}:
    label = {
      "brainstorm": "继续讨论项目方向",
      "review_knowledge": "分析资料库",
      "generate_architecture": "生成整书架构",
      "skill_optimize": "整理用户技能",
    }[action_kind]
    return AgentPlanAction(
      kind=action_kind,
      label=label if base_action is None else base_action.label or label,
      task_pack_kind=_task_pack_kind_for_action(action_kind, action_instruction, action_mode),
      instruction=action_instruction,
      skill_ids=custom_skill_ids,
    )

  if action_kind == "continue_project":
    return AgentPlanAction(
      kind="continue_project",
      label=base_action.label if base_action is not None and base_action.label else "扩写后续章节规划",
      task_pack_kind=_task_pack_kind_for_action("continue_project", action_instruction, action_mode),
      instruction=action_instruction,
      new_chapters=base_action.new_chapters if base_action is not None and base_action.new_chapters else 5,
      style_name=request.style_name,
      xp_preset=request.xp_preset,
      skill_ids=custom_skill_ids,
    )

  chapter = _chapter_for_builtin_skill_action(runtime, hint, base_action)
  if chapter is None:
    return None

  if action_kind == "chapter_generate":
    requested_target = base_action.target_words if base_action is not None and base_action.target_words else 1800
    target_words = _chapter_generation_target_for_action(
      runtime,
      chapter,
      requested_target=requested_target,
      instruction=action_instruction,
    )
    return AgentPlanAction(
      kind="chapter_generate",
      label=f"生成第 {chapter.index} 章正文",
      task_pack_kind=_task_pack_kind_for_action("chapter_generate", action_instruction, action_mode),
      chapter_id=chapter.id,
      instruction=action_instruction,
      target_words=target_words,
      style_name=request.style_name,
      xp_preset=request.xp_preset,
      characters_involved=request.characters_involved,
      key_items=request.key_items,
      scene_location=request.scene_location,
      time_constraint=request.time_constraint,
      skill_ids=custom_skill_ids,
    )

  if action_kind == "chapter_workflow":
    workflow_mode = action_mode if action_mode in {"diagnose", "scenes", "draft"} else "diagnose"
    requested_target = (
      base_action.target_words
      if base_action is not None and base_action.target_words
      else 1800 if workflow_mode == "draft" else 1200
    )
    target_words = (
      _chapter_generation_target_for_action(
        runtime,
        chapter,
        requested_target=requested_target,
        instruction=action_instruction,
      )
      if workflow_mode == "draft"
      else requested_target
    )
    return AgentPlanAction(
      kind="chapter_workflow",
      label=(
        f"拆第 {chapter.index} 章场景" if workflow_mode == "scenes"
        else f"续写第 {chapter.index} 章" if workflow_mode == "draft"
        else f"判断第 {chapter.index} 章"
      ),
      task_pack_kind=_task_pack_kind_for_action("chapter_workflow", action_instruction, workflow_mode),
      chapter_id=chapter.id,
      mode=workflow_mode,
      instruction=action_instruction,
      target_words=target_words,
      style_name=request.style_name,
      xp_preset=request.xp_preset,
      skill_ids=custom_skill_ids,
    )

  if action_kind == "consistency_check":
    return AgentPlanAction(
      kind="consistency_check",
      label=f"检查第 {chapter.index} 章一致性",
      task_pack_kind=_task_pack_kind_for_action("consistency_check", action_instruction, action_mode),
      chapter_id=chapter.id,
      instruction=action_instruction,
      skill_ids=custom_skill_ids,
    )

  rewrite_mode = action_mode if action_mode in {"finalize", "polish", "humanize"} else "polish"
  if not (chapter.exists and chapter.content.strip()):
    return None
  return AgentPlanAction(
    kind="rewrite_chapter",
    label=f"修订第 {chapter.index} 章",
    task_pack_kind=_task_pack_kind_for_action("rewrite_chapter", action_instruction, rewrite_mode),
    chapter_id=chapter.id,
    mode=rewrite_mode,
    instruction=action_instruction,
    style_name=request.style_name,
    xp_preset=request.xp_preset,
    skill_ids=custom_skill_ids,
  )


def _apply_active_builtin_skill_to_plan(
  settings: Settings,
  runtime: RuntimeState,
  instruction: str,
  request: AgentChatRequest,
  plan: AgentPlan | None,
) -> AgentPlan | None:
  if plan is None:
    return None
  hints = _builtin_skill_action_hints(settings, request.active_skill_ids)
  if not hints:
    return plan

  hint = next((item for item in hints if item.action_kind != "brainstorm"), None)
  if hint is None:
    return plan

  actions = list(plan.actions)
  if not actions:
    return plan

  chapter_action_kinds = {"chapter_generate", "chapter_workflow", "consistency_check", "rewrite_chapter"}
  if hint.action_kind in chapter_action_kinds:
    target_kinds = chapter_action_kinds
  elif hint.action_kind in {"continue_project", "generate_architecture", "review_knowledge", "skill_optimize"}:
    target_kinds = {hint.action_kind}
  else:
    target_kinds = {hint.action_kind}
  target_index = next((index for index, action in enumerate(actions) if action.kind in target_kinds), -1)
  if target_index < 0 and hint.action_kind in chapter_action_kinds:
    target_index = next((index for index, action in enumerate(actions) if action.kind not in {"review_knowledge", "generate_architecture"}), -1)
  if target_index < 0:
    target_index = len(actions)
    base_action = None
  else:
    base_action = actions[target_index]

  replacement = _action_from_builtin_skill_hint(runtime, request, hint, instruction, base_action)
  if replacement is None:
    return plan

  if target_index >= len(actions):
    actions.append(replacement)
  else:
    actions[target_index] = replacement

  actions = _ensure_plan_dependencies(runtime, instruction, actions)
  return plan.model_copy(
    update={
      "summary": plan.summary,
      "requires_confirmation": plan.requires_confirmation or hint.requires_confirmation or _default_requires_confirmation(actions),
      "steps": [_chapter_step_text(action, runtime) for action in actions],
      "actions": actions,
    }
  )


def _plan_from_payload(
  settings: Settings,
  runtime: RuntimeState,
  instruction: str,
  request: AgentChatRequest,
  payload: dict[str, object],
) -> tuple[AgentPlan | None, str | None]:
  mode = str(payload.get("mode") or "plan").strip().lower()
  reply = str(payload.get("reply") or "").strip()
  if mode == "reply":
    return None, reply or "当前请求还不适合直接执行，可以继续讨论方向。"

  raw_actions = payload.get("actions")
  if not isinstance(raw_actions, list) or not raw_actions:
    if reply:
      return None, reply
    return None, "当前请求还不够明确，请说明具体要处理什么。"

  actions: list[AgentPlanAction] = []
  for raw_action in raw_actions[:8]:
    if not isinstance(raw_action, dict):
      continue
    future_chapter_id = _future_chapter_id_for_followup_action(runtime, instruction, raw_action, actions)
    action, error_message = _build_action_from_plan_payload(
      runtime,
      raw_action,
      instruction,
      request,
      future_chapter_id=future_chapter_id,
    )
    if error_message:
      return None, error_message
    if action is not None:
      actions.append(action)

  limit_message = _chapter_range_generation_limit_message(instruction, actions)
  if limit_message:
    return None, limit_message
  actions = _expand_chapter_range_generation_actions(runtime, instruction, actions)
  actions = _ensure_plan_dependencies(runtime, instruction, actions)
  if not actions:
    return None, reply or "当前请求还不够明确，请说明具体要处理什么。"

  steps = [_chapter_step_text(action, runtime) for action in actions]
  requires_confirmation = _bool_from_value(
    payload.get("requires_confirmation"),
    default=_default_requires_confirmation(actions),
  )
  summary = str(payload.get("summary") or "").strip() or _plan_summary_from_actions(actions, runtime)
  title = str(payload.get("title") or "").strip() or actions[-1].label or "执行计划"
  return AgentPlan(
    id=f"plan-{uuid4().hex[:10]}",
    title=title,
    summary=summary,
    requires_confirmation=requires_confirmation,
    steps=steps[:10],
    actions=actions[:10],
  ), None


def _plan_with_model(
  settings: Settings,
  runtime: RuntimeState,
  instruction: str,
  payload: AgentChatRequest,
) -> tuple[AgentPlan | None, str | None]:
  latest_user_message = next(
    (item for item in reversed(payload.messages) if item.role == "user" and item.content.strip()),
    payload.messages[-1],
  )
  latest_user_prompt = _agent_message_model_content(latest_user_message, limit=2400)
  planner_messages = [
    {"role": "system", "content": _PLAN_SYSTEM_PROMPT},
    {"role": "system", "content": _build_route_context(runtime, payload.messages)},
  ]
  skill_catalog_context = _build_skill_catalog_context(settings)
  if skill_catalog_context:
    planner_messages.append({"role": "system", "content": skill_catalog_context})
  capability_chapter_indexes, include_obsidian_suggestions = _capability_context_chapter_indexes(
    runtime,
    latest_user_prompt,
  )
  capability_chapter_index = capability_chapter_indexes[0] if capability_chapter_indexes else 0
  capability_context = build_agent_capability_context(
    Path(runtime.detail.path),
    project_detail=runtime.detail,
    auto_stage_obsidian_drafts=True,
    chapter_index=capability_chapter_index,
    chapter_indexes=capability_chapter_indexes,
    include_obsidian_suggestions=include_obsidian_suggestions,
  )
  if capability_context:
    planner_messages.append({"role": "system", "content": capability_context})
  reference_context = _append_reference_note("", payload.reference_filenames)
  if reference_context:
    planner_messages.append({"role": "system", "content": reference_context})
  planner_messages.append({"role": "user", "content": f"当前用户消息：{latest_user_prompt}"})
  content = _invoke_model(
    settings,
    planner_messages,
    task_name="agent_plan",
  )
  planner_payload = _extract_json_object(content)
  if not isinstance(planner_payload, dict):
    raise RuntimeError("规划结果不是合法 JSON")
  return _plan_from_payload(settings, runtime, instruction, payload, planner_payload)


def _heuristic_route(text: str) -> RoutingDecision:
  normalized = str(text or "").strip()
  lower_text = normalized.lower()
  chapter_index = _chapter_number_from_text(normalized)
  chapter_title = _chapter_title_from_text(normalized)
  new_chapters = _new_chapter_count_from_text(normalized)
  use_next_chapter = bool(_NEXT_CHAPTER_HINT_PATTERN.search(normalized))

  if _instruction_requests_skill_optimization(normalized):
    return RoutingDecision(
      intent="skill_optimize",
      objective="整理或更新用户技能",
      chapter_index=chapter_index,
      chapter_title=chapter_title,
      use_next_chapter=use_next_chapter,
      reason="命中技能优化表达",
    )

  if _LONGFORM_SUPERVISION_SKIP_PATTERN.search(normalized) and re.search(r"(续写|生成.*正文|生成第.+章|写正文|写这一章|写第.+章|补写|扩成正文)", normalized):
    return RoutingDecision(
      intent="write_chapter",
      objective="生成章节初稿",
      chapter_index=chapter_index,
      chapter_title=chapter_title,
      use_next_chapter=use_next_chapter,
      reason="用户只要初稿",
    )

  if re.search(r"(去\s*ai|去机器味|去模板味|更像人写|人味)", lower_text):
    return RoutingDecision(
      intent="rewrite_chapter",
      objective="调整语言腔调",
      chapter_index=chapter_index,
      chapter_title=chapter_title,
      rewrite_mode="humanize",
      use_next_chapter=use_next_chapter,
      reason="命中去 AI 关键词",
    )

  if re.search(r"(润色|改稿|修稿|重写|定稿|精修)", normalized):
    rewrite_mode = "finalize" if "定稿" in normalized else "polish"
    return RoutingDecision(
      intent="rewrite_chapter",
      objective="修订当前章节",
      chapter_index=chapter_index,
      chapter_title=chapter_title,
      rewrite_mode=rewrite_mode,
      use_next_chapter=use_next_chapter,
      reason="命中改稿关键词",
    )

  if re.search(r"(一致性|矛盾|逻辑漏洞|逻辑问题|前后对不上|前后不一致)", normalized):
    return RoutingDecision(
      intent="consistency_check",
      objective="检查章节一致性",
      chapter_index=chapter_index,
      chapter_title=chapter_title,
      use_next_chapter=use_next_chapter,
      reason="命中一致性关键词",
    )

  if re.search(r"(拆场景|场景清单|拆成场景|场景规划)", normalized):
    return RoutingDecision(
      intent="scene_chapter",
      objective="拆分章节场景",
      chapter_index=chapter_index,
      chapter_title=chapter_title,
      use_next_chapter=use_next_chapter,
      reason="命中场景关键词",
    )

  if re.search(r"(诊断|判断|看看.*问题|分析.*问题|哪里不对|怎么改|节奏有问题)", normalized):
    return RoutingDecision(
      intent="diagnose_chapter",
      objective="判断章节问题",
      chapter_index=chapter_index,
      chapter_title=chapter_title,
      use_next_chapter=use_next_chapter,
      reason="命中诊断关键词",
    )

  if re.search(r"(续写|生成.*正文|生成第.+章|写正文|补完本章|完整章|整章|写完整|写这一章|写第.+章|补写|扩成正文|扩成完整|扩到完整|按目标字数|补到目标字数)", normalized):
    return RoutingDecision(
      intent="write_chapter",
      objective="生成章节正文",
      chapter_index=chapter_index,
      chapter_title=chapter_title,
      use_next_chapter=use_next_chapter,
      reason="命中正文关键词",
    )

  if re.search(r"(继续规划|后面.*章|新增.*章|再加.*章|后续蓝图|扩写整书|扩写后续)", normalized):
    return RoutingDecision(
      intent="continue_project",
      objective="扩写后续规划",
      new_chapters=new_chapters or 5,
      reason="命中续规划关键词",
    )

  if re.search(r"(架构|蓝图|大纲|整书规划|整本规划|世界观|人物设定|情节骨架)", normalized):
    return RoutingDecision(
      intent="generate_architecture",
      objective="整理整书架构",
      reason="命中架构关键词",
    )

  if re.search(r"(讨论|聊聊|设定|方向|题材|主角|冲突|下一步|怎么推进|梳理一下)", normalized):
    return RoutingDecision(
      intent="discussion",
      objective="继续讨论项目方向",
      reason="命中讨论关键词",
    )

  return RoutingDecision(
    intent="unknown",
    objective=_compact_text(normalized, 40),
    chapter_index=chapter_index,
    chapter_title=chapter_title,
    new_chapters=new_chapters,
    use_next_chapter=use_next_chapter,
    reason="规则未命中",
  )


def _route_with_model(
  settings: Settings,
  runtime: RuntimeState,
  messages: list[object],
  reference_filenames: list[str] | None = None,
) -> RoutingDecision:
  latest_user_message = next(
    (item for item in reversed(messages) if item.role == "user" and item.content.strip()),
    messages[-1],
  )
  latest_user_prompt = _agent_message_model_content(latest_user_message, limit=2400)
  route_messages = [
    {"role": "system", "content": _ROUTE_SYSTEM_PROMPT},
    {"role": "system", "content": _build_route_context(runtime, messages)},
  ]
  capability_chapter_indexes, include_obsidian_suggestions = _capability_context_chapter_indexes(
    runtime,
    latest_user_prompt,
  )
  capability_chapter_index = capability_chapter_indexes[0] if capability_chapter_indexes else 0
  capability_context = build_agent_capability_context(
    Path(runtime.detail.path),
    project_detail=runtime.detail,
    auto_stage_obsidian_drafts=True,
    chapter_index=capability_chapter_index,
    chapter_indexes=capability_chapter_indexes,
    include_obsidian_suggestions=include_obsidian_suggestions,
  )
  if capability_context:
    route_messages.append({"role": "system", "content": capability_context})
  reference_context = _append_reference_note("", reference_filenames or [])
  if reference_context:
    route_messages.append({"role": "system", "content": reference_context})
  route_messages.append({"role": "user", "content": f"当前用户消息：{latest_user_prompt}"})
  content = _invoke_model(
    settings,
    route_messages,
    task_name="agent_route",
  )
  payload = _extract_json_object(content)
  if not isinstance(payload, dict):
    raise RuntimeError("路由结果不是合法 JSON")
  return RoutingDecision(
    intent=_string_from_keys(payload, "intent") or "unknown",
    objective=_string_from_keys(payload, "objective", "goal"),
    chapter_index=int(payload.get("chapter_index") or 0),
    chapter_title=_string_from_keys(payload, "chapter_title", "title"),
    rewrite_mode=_string_from_keys(payload, "rewrite_mode", "mode"),
    new_chapters=int(payload.get("new_chapters") or 0),
    use_next_chapter=bool(payload.get("use_next_chapter")),
    reason=_string_from_keys(payload, "reason", "why"),
  )


def _resolve_decision(
  settings: Settings,
  runtime: RuntimeState,
  messages: list[object],
  reference_filenames: list[str] | None = None,
) -> RoutingDecision:
  latest_user_message = next(
    (item for item in reversed(messages) if item.role == "user" and item.content.strip()),
    None,
  )
  if latest_user_message is None:
    return RoutingDecision(intent="unknown", reason="没有用户输入")

  heuristic = _heuristic_route(latest_user_message.content)
  if heuristic.intent != "unknown":
    return heuristic

  try:
    decision = _route_with_model(settings, runtime, messages, reference_filenames=reference_filenames)
    if decision.intent:
      return decision
  except Exception:
    return heuristic

  return heuristic


def _find_chapter(runtime: RuntimeState, chapter_index: int = 0, chapter_title: str = ""):
  if chapter_index > 0:
    matched = next((item for item in runtime.detail.chapters if item.index == chapter_index), None)
    if matched:
      return matched

  normalized_title = chapter_title.strip()
  if normalized_title:
    for item in runtime.detail.chapters:
      if normalized_title == item.title or normalized_title in item.title:
        return item

  return None


def _resolve_target_chapter(runtime: RuntimeState, decision: RoutingDecision, *, require_existing: bool = False):
  explicit = _find_chapter(runtime, decision.chapter_index, decision.chapter_title)
  if explicit is not None and (not require_existing or explicit.exists and explicit.content.strip()):
    return explicit

  if decision.use_next_chapter and runtime.next_chapter is not None and not require_existing:
    return runtime.next_chapter

  if runtime.selected_chapter is not None:
    if not require_existing or runtime.selected_chapter.exists and runtime.selected_chapter.content.strip():
      return runtime.selected_chapter

  if require_existing and runtime.last_written_chapter is not None:
    return runtime.last_written_chapter

  if not require_existing and runtime.next_chapter is not None:
    return runtime.next_chapter

  return runtime.last_written_chapter


def _state_lines(runtime: RuntimeState, target_chapter) -> list[str]:
  lines = [
    f"作品：{runtime.detail.name}",
    f"讨论结论：{'已存在' if runtime.discussion_summary else '还没有'}",
    f"架构完整度：{runtime.architecture_progress}/5",
  ]
  if target_chapter is not None:
    status = "已有正文" if target_chapter.exists and target_chapter.content.strip() else "待写章节"
    lines.append(f"目标章节：第 {target_chapter.index} 章《{target_chapter.title}》 · {status}")
  return lines


def _plan_reply(runtime: RuntimeState, plan: AgentPlan, target_chapter) -> str:
  state_block = "\n".join(f"- {item}" for item in _state_lines(runtime, target_chapter))
  step_block = "\n".join(f"{index}. {item}" for index, item in enumerate(plan.steps, start=1))
  return (
    f"{plan.summary.strip() or '已读取当前状态。'}\n\n"
    f"当前状态：\n{state_block}\n\n"
    f"计划步骤：\n{step_block}\n\n"
    "如果要改方向，直接发新要求覆盖当前计划。"
  ).strip()


def _prepend_knowledge_review_step(
  runtime: RuntimeState,
  instruction: str,
  steps: list[str],
  actions: list[AgentPlanAction],
) -> tuple[list[str], list[AgentPlanAction]]:
  if not _instruction_requires_knowledge_review(instruction):
    return steps, actions

  review_action = AgentPlanAction(
    kind="review_knowledge",
    label="分析资料库",
    task_pack_kind=_task_pack_kind_for_action("review_knowledge", instruction),
    instruction=instruction,
  )
  scoped_actions = _scope_review_knowledge_actions([review_action, *actions])
  scoped_review_action = scoped_actions[0]
  chapter = (
    next((item for item in runtime.detail.chapters if item.id == scoped_review_action.chapter_id), None)
    if scoped_review_action.chapter_id
    else None
  )
  chapter_index = int(getattr(chapter, "index", 0) or 0) if chapter is not None else 0
  material_count = _knowledge_source_count(runtime.detail, chapter_index=chapter_index)
  scope_text = f"第 {chapter_index} 章可用的" if chapter_index > 0 else ""
  review_step = (
    f"先通读{scope_text}资料库和 Obsidian 里的 {material_count} 份资料，提炼事实、线索和硬约束"
    if material_count > 0
    else "先检查资料库是否有可用资料，再决定后续怎么执行"
  )
  return (
    [review_step, *steps],
    scoped_actions,
  )


def _build_plan(runtime: RuntimeState, decision: RoutingDecision, instruction: str, payload: AgentChatRequest):
  instruction = instruction.strip()
  discussion_context = _discussion_context_from_messages(payload.messages)

  if decision.intent == "discussion":
    return None, None

  if decision.intent == "skill_optimize":
    plan = AgentPlan(
      id=f"plan-{uuid4().hex[:10]}",
      title="整理用户技能",
      summary="已读取当前对话，当前请求更像是在保存或更新一套可复用写作规则。",
      requires_confirmation=True,
      steps=["读取本轮对话和已有用户技能", "生成或更新一份用户技能文件"],
      actions=[
        AgentPlanAction(
          kind="skill_optimize",
          label="整理用户技能",
          task_pack_kind="",
          instruction=instruction,
        )
      ],
    )
    return plan, None

  if decision.intent == "generate_architecture":
    steps = [
      "读取当前项目资料和当前对话",
      "生成并写回整书架构文件",
    ] if discussion_context else ["读取当前项目资料和已写正文", "生成并写回整书架构文件"]
    actions = [
      AgentPlanAction(
        kind="generate_architecture",
        label="生成整书架构",
        task_pack_kind=_task_pack_kind_for_action("generate_architecture", instruction),
        instruction=instruction,
      )
    ]
    steps, actions = _prepend_knowledge_review_step(runtime, instruction, steps, actions)
    plan = AgentPlan(
      id=f"plan-{uuid4().hex[:10]}",
      title="整理整书架构",
      summary=(
        "项目里还没有保存的讨论结论，当前计划会按这段对话整理一版整书架构。"
        if not runtime.discussion_summary and runtime.architecture_progress == 0 and not runtime.last_written_chapter
        else "已检查项目现状，当前计划更适合先完善整书架构。"
      ),
      requires_confirmation=True,
      steps=steps,
      actions=actions,
    )
    return plan, None

  if decision.intent == "continue_project":
    if not runtime.architecture_ready:
      actions = [
        AgentPlanAction(
          kind="generate_architecture",
          label="补齐整书架构",
          task_pack_kind=_task_pack_kind_for_action("generate_architecture", instruction),
          instruction=instruction,
        ),
        AgentPlanAction(
          kind="continue_project",
          label="扩写后续章节规划",
          task_pack_kind=_task_pack_kind_for_action("continue_project", instruction),
          instruction=instruction,
          new_chapters=decision.new_chapters or 5,
          style_name=payload.style_name,
          xp_preset=payload.xp_preset,
        ),
      ]
      steps = ["完善整书架构", f"把后续规划向后扩写 {decision.new_chapters or 5} 章"]
      steps, actions = _prepend_knowledge_review_step(runtime, instruction, steps, actions)
      plan = AgentPlan(
        id=f"plan-{uuid4().hex[:10]}",
        title="完善架构并扩写后续规划",
        summary="当前架构还不完整，直接往后扩写容易偏离设定。",
        requires_confirmation=True,
        steps=steps,
        actions=actions,
      )
      return plan, None

    actions = [
      AgentPlanAction(
        kind="continue_project",
        label="扩写后续章节规划",
        task_pack_kind=_task_pack_kind_for_action("continue_project", instruction),
        instruction=instruction,
        new_chapters=decision.new_chapters or 5,
        style_name=payload.style_name,
        xp_preset=payload.xp_preset,
      )
    ]
    steps = [f"基于现有架构继续扩写后续 {decision.new_chapters or 5} 章"]
    steps, actions = _prepend_knowledge_review_step(runtime, instruction, steps, actions)
    plan = AgentPlan(
      id=f"plan-{uuid4().hex[:10]}",
      title="扩写后续规划",
      summary="当前架构已经足够，可以直接往后扩写蓝图。",
      requires_confirmation=True,
      steps=steps,
      actions=actions,
    )
    return plan, None

  if decision.intent in {"write_chapter", "diagnose_chapter", "scene_chapter", "consistency_check", "rewrite_chapter"}:
    require_existing = decision.intent in {"diagnose_chapter", "consistency_check", "rewrite_chapter"}
    target_chapter = _resolve_target_chapter(runtime, decision, require_existing=require_existing)
    if target_chapter is None:
      return None, "当前还没有可处理的章节。先在左侧选一章，或者先创建正文。"

    if decision.intent == "rewrite_chapter" and not (target_chapter.exists and target_chapter.content.strip()):
      return None, "要改稿的章节还没有正文，先让我生成正文，或者先手动写一版。"

    actions: list[AgentPlanAction] = []
    steps: list[str] = []
    requires_confirmation = decision.intent in {"write_chapter", "rewrite_chapter"}

    if decision.intent in {"write_chapter", "rewrite_chapter"} and not runtime.architecture_ready:
      actions.append(
        AgentPlanAction(
          kind="generate_architecture",
          label="补齐整书架构",
          task_pack_kind=_task_pack_kind_for_action("generate_architecture", instruction),
          instruction=instruction,
        )
      )
      steps.append("先根据当前项目状态补齐整书架构")

    if decision.intent == "write_chapter":
      target_words = _chapter_generation_target_for_action(
        runtime,
        target_chapter,
        requested_target=1800,
        instruction=instruction,
      )
      actions.append(
        AgentPlanAction(
          kind="chapter_generate",
          label=f"生成第 {target_chapter.index} 章正文",
          task_pack_kind=_task_pack_kind_for_action("chapter_generate", instruction),
          chapter_id=target_chapter.id,
          instruction=instruction,
          target_words=target_words,
          style_name=payload.style_name,
          xp_preset=payload.xp_preset,
          characters_involved=payload.characters_involved,
          key_items=payload.key_items,
          scene_location=payload.scene_location,
          time_constraint=payload.time_constraint,
        )
      )
      steps.append(f"生成第 {target_chapter.index} 章《{target_chapter.title}》正文并写回项目")
    elif decision.intent == "diagnose_chapter":
      actions.append(
        AgentPlanAction(
          kind="chapter_workflow",
          label=f"判断第 {target_chapter.index} 章",
          task_pack_kind=_task_pack_kind_for_action("chapter_workflow", instruction, "diagnose"),
          chapter_id=target_chapter.id,
          mode="diagnose",
          instruction=instruction,
          target_words=1200,
        )
      )
      steps.append(f"判断第 {target_chapter.index} 章《{target_chapter.title}》当前最该处理的问题")
      requires_confirmation = False
    elif decision.intent == "scene_chapter":
      actions.append(
        AgentPlanAction(
          kind="chapter_workflow",
          label=f"拆第 {target_chapter.index} 章场景",
          task_pack_kind=_task_pack_kind_for_action("chapter_workflow", instruction, "scenes"),
          chapter_id=target_chapter.id,
          mode="scenes",
          instruction=instruction,
          target_words=1200,
        )
      )
      steps.append(f"拆出第 {target_chapter.index} 章《{target_chapter.title}》的场景清单")
      requires_confirmation = False
    elif decision.intent == "consistency_check":
      actions.append(
        AgentPlanAction(
          kind="consistency_check",
          label=f"检查第 {target_chapter.index} 章一致性",
          task_pack_kind=_task_pack_kind_for_action("consistency_check", instruction),
          chapter_id=target_chapter.id,
          instruction=instruction,
        )
      )
      steps.append(f"检查第 {target_chapter.index} 章《{target_chapter.title}》的一致性")
      requires_confirmation = False
    else:
      actions.append(
        AgentPlanAction(
          kind="rewrite_chapter",
          label=f"修订第 {target_chapter.index} 章",
          task_pack_kind=_task_pack_kind_for_action("rewrite_chapter", instruction, decision.rewrite_mode or "polish"),
          chapter_id=target_chapter.id,
          mode=decision.rewrite_mode or "polish",
          instruction=instruction,
          style_name=payload.style_name,
          xp_preset=payload.xp_preset,
        )
      )
      rewrite_label = {
        "finalize": "整理成定稿",
        "humanize": "调整成更自然的写法",
        "polish": "润色表达和节奏",
      }.get(decision.rewrite_mode or "polish", "修订正文")
      steps.append(f"{rewrite_label}，并写回第 {target_chapter.index} 章《{target_chapter.title}》")

    limit_message = _chapter_range_generation_limit_message(instruction, actions)
    if limit_message:
      return None, limit_message
    actions = _expand_chapter_range_generation_actions(runtime, instruction, actions)
    steps, actions = _prepend_knowledge_review_step(runtime, instruction, steps, actions)
    steps = [_chapter_step_text(action, runtime) for action in actions]
    plan = AgentPlan(
      id=f"plan-{uuid4().hex[:10]}",
      title=actions[-1].label,
      summary="已读取当前项目和章节状态，建议按下面顺序处理。",
      requires_confirmation=requires_confirmation,
      steps=steps,
      actions=actions,
    )
    return plan, None

  reply = (
    "可以处理四类事：讨论方向、完善整书架构、检查当前章节、续写或改稿。"
    "你可以直接说“完善架构”“判断这一章问题”“续写这一章”。"
  )
  return None, reply


def _resolve_plan(settings: Settings, runtime: RuntimeState, instruction: str, payload: AgentChatRequest):
  resolved_skill_ids = _resolve_agent_skill_ids(settings, payload)
  if _planner_available(settings):
    try:
      plan, reply = _plan_with_model(settings, runtime, instruction, payload)
      if plan is not None or reply is not None:
        plan = _apply_active_builtin_skill_to_plan(settings, runtime, instruction, payload, plan)
        plan = _apply_skill_ids_to_plan(settings, plan, resolved_skill_ids)
        return _enhance_longform_plan(runtime, plan), reply
    except Exception:
      pass

  decision = _resolve_decision(settings, runtime, payload.messages, reference_filenames=payload.reference_filenames)
  plan, reply = _build_plan(runtime, decision, instruction, payload)
  plan = _apply_active_builtin_skill_to_plan(settings, runtime, instruction, payload, plan)
  plan = _apply_skill_ids_to_plan(settings, plan, resolved_skill_ids)
  return _enhance_longform_plan(runtime, plan), reply


def _brainstorm_request(
  runtime: RuntimeState,
  payload: AgentChatRequest,
  skill_prompt: str = "",
  active_skill_ids: list[str] | None = None,
) -> BrainstormRequest:
  discussion_text = "\n".join(
    _agent_message_model_content(item, limit=1200)
    for item in payload.messages[-8:]
    if str(getattr(item, "content", "") or "").strip()
  )
  chapter_indexes, _include_obsidian_suggestions = _capability_context_chapter_indexes(runtime, discussion_text)
  chapter_index = chapter_indexes[0] if chapter_indexes else 0
  if chapter_index <= 0:
    chapter_index = _brainstorm_chapter_index_from_text(discussion_text)
  target_chapter = next(
    (
      item
      for item in runtime.detail.chapters
      if int(getattr(item, "index", 0) or 0) == chapter_index
    ),
    None,
  ) if chapter_index > 0 else runtime.selected_chapter
  extra_context = _append_reference_note("", payload.reference_filenames)
  thread_context = _thread_context_from_payload(payload)
  if thread_context:
    extra_context = "\n\n".join(
      item for item in [
        extra_context,
        f"相关对话历史：\n{_preserve_thread_context_text(thread_context, 3400)}",
      ]
      if item.strip()
    )
  if skill_prompt.strip():
    extra_context = "\n\n".join(
      item for item in [
        extra_context,
        f"本轮启用用户技能：\n{_compact_text(skill_prompt, 900)}",
      ]
      if item.strip()
    )
  extra_context = _preserve_thread_context_text(extra_context, 3900)
  return BrainstormRequest(
    project_id=payload.project_id,
    messages=_agent_message_model_messages(payload.messages[-20:], limit=3800),
    include_core_seed=True,
    include_characters=True,
    include_world_building=True,
    include_plot=True,
    include_blueprint=runtime.architecture_ready,
    include_character_state=runtime.architecture_ready,
    chapter_id=str(getattr(target_chapter, "id", "") or "").strip(),
    skill_id=(active_skill_ids or [""])[0],
    extra_context=extra_context,
  )


def _architecture_guidance(runtime: RuntimeState, instruction: str, messages: list[object]) -> str:
  parts = []
  if runtime.discussion_summary:
    parts.append(f"讨论结论：\n{runtime.discussion_summary}")
  else:
    discussion_context = _discussion_context_from_messages(messages)
    if discussion_context:
      parts.append(f"当前对话提要：\n{discussion_context}")
  if instruction.strip():
    parts.append(f"补充要求：\n{instruction.strip()}")
  return "\n\n".join(parts).strip()


def _architecture_resume_signature(runtime: RuntimeState, instruction: str, guidance: str) -> str:
  payload = {
    "project_id": runtime.detail.id,
    "target_chapters": runtime.detail.target_chapters,
    "instruction": instruction.strip(),
    "guidance": guidance.strip(),
    "steps": [step_key for step_key, _label in _ARCHITECTURE_STEPS],
  }
  return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _architecture_completed_steps_from_progress(progress: dict[str, object] | None, signature: str, workspace: ArchitectureWorkspace) -> list[str]:
  if not isinstance(progress, dict) or progress.get("instruction_signature") != signature:
    return []
  raw_steps = progress.get("completed_steps")
  if not isinstance(raw_steps, list):
    return []
  valid_steps = {step_key for step_key, _label in _ARCHITECTURE_STEPS}
  completed_steps: list[str] = []
  for item in raw_steps:
    step_key = str(item or "")
    if step_key in valid_steps and getattr(workspace, step_key, "").strip():
      completed_steps.append(step_key)
  return completed_steps


def _save_architecture_running_progress(
  settings: Settings,
  project_id: str,
  *,
  task_id: str,
  signature: str,
  completed_steps: list[str],
  failed_step: str = "",
  error: str = "",
) -> None:
  save_architecture_progress(
    settings,
    project_id,
    {
      "task_id": task_id,
      "instruction_signature": signature,
      "status": "failed" if failed_step else "running",
      "completed_steps": completed_steps,
      "failed_step": failed_step,
      "error": error,
    },
  )


def _architecture_task_knowledge_query(workspace: ArchitectureWorkspace, guidance: str) -> str:
  parts = [
    " ".join(label for _key, label in _ARCHITECTURE_STEPS),
    guidance.strip(),
  ]
  for step_key, _step_label in _ARCHITECTURE_STEPS:
    value = getattr(workspace, step_key, "")
    if isinstance(value, str) and value.strip():
      parts.append(value.strip()[:1200])
  return "\n\n".join(item for item in parts if item).strip()[:8000]


def _build_architecture_task_context_snapshot(
  settings: Settings,
  runtime: RuntimeState,
  workspace: ArchitectureWorkspace,
  guidance: str,
):
  return build_project_context_bundle(
    settings,
    runtime.detail.id,
    include_blueprint=True,
    include_character_state=True,
    knowledge_query=_architecture_task_knowledge_query(workspace, guidance),
    task_pack_kind="architecture",
    task_instruction=guidance,
    override_documents={
      step_key: getattr(workspace, step_key, "")
      for step_key, _step_label in _ARCHITECTURE_STEPS
    },
  )


def _generate_full_architecture(
  settings: Settings,
  runtime: RuntimeState,
  instruction: str,
  messages: list[object],
  task_id: str,
):
  with model_runtime_foreground_session():
    workspace = ArchitectureWorkspace(**{
      key: runtime.documents.get(key, "")
      for key, _label in _ARCHITECTURE_STEPS
    })
    guidance = _architecture_guidance(runtime, instruction, messages)
    signature = _architecture_resume_signature(runtime, instruction, guidance)
    completed_steps = _architecture_completed_steps_from_progress(
      load_architecture_progress(settings, runtime.detail.id),
      signature,
      workspace,
    )
    _save_architecture_running_progress(
      settings,
      runtime.detail.id,
      task_id=task_id,
      signature=signature,
      completed_steps=completed_steps,
    )
    context_snapshot = _build_architecture_task_context_snapshot(settings, runtime, workspace, guidance)

    for step_key, _step_label in _ARCHITECTURE_STEPS:
      if step_key in completed_steps:
        continue
      try:
        result = _generate_architecture_step(
          settings,
          ArchitectureStepRequest(
            project_id=runtime.detail.id,
            step=step_key,
            mode="initial",
            guidance=guidance,
            workspace=workspace,
          ),
          task_id,
          context_snapshot,
        )
        setattr(workspace, step_key, result.content)
        save_story_document_incremental(settings, runtime.detail.id, step_key, result.content)
        completed_steps.append(step_key)
        _save_architecture_running_progress(
          settings,
          runtime.detail.id,
          task_id=task_id,
          signature=signature,
          completed_steps=completed_steps,
        )
      except Exception as error:
        _save_architecture_running_progress(
          settings,
          runtime.detail.id,
          task_id=task_id,
          signature=signature,
          completed_steps=completed_steps,
          failed_step=step_key,
          error=str(error),
        )
        if completed_steps:
          enqueue_project_auxiliary_tasks(
            settings,
            runtime.detail.id,
            tasks=["knowledge_index", "story_overview_model", "system_memory"],
            reason=f"architecture_failed:{step_key}",
          )
        raise

    clear_architecture_progress(settings, runtime.detail.id)
    enqueue_project_auxiliary_tasks(
      settings,
      runtime.detail.id,
      tasks=["knowledge_index", "story_overview_model", "system_memory"],
      reason="architecture_completed",
    )
    return get_project_detail(settings, runtime.detail.id, allow_model_overview=False), workspace


def _execute_chapter_workflow(
  settings: Settings,
  runtime: RuntimeState,
  action: AgentPlanAction,
  task_id: str,
  knowledge_summary: str = "",
  skill_prompt: str = "",
):
  result = _generate_chapter_workflow(
    settings,
    ChapterWorkflowRequest(
      project_id=runtime.detail.id,
      chapter_id=action.chapter_id,
      mode=action.mode or "diagnose",
      instruction=_compose_execution_instruction(
        action.instruction,
        knowledge_summary=knowledge_summary,
        skill_prompt=skill_prompt,
      ),
      target_words=action.target_words or (1800 if action.mode == "draft" else 1200),
    ),
    task_id,
  )

  if action.mode == "draft" and result.draft.strip():
    detail, review_error = update_chapter_content_with_review_status(
      settings,
      runtime.detail.id,
      action.chapter_id,
      ChapterUpdateRequest(content=result.draft, style_name=action.style_name, xp_preset=action.xp_preset),
    )
    detail, review_error, repair_result = auto_repair_chapter_after_review(
      settings,
      runtime.detail.id,
      action.chapter_id,
      detail,
      review_error=review_error,
      style_name=action.style_name,
      xp_preset=action.xp_preset,
      instruction=_compose_execution_instruction(
        action.instruction,
        knowledge_summary=knowledge_summary,
        skill_prompt=skill_prompt,
      ),
    )
    return result, detail, review_error, repair_result

  return result, runtime.detail, "", None


def _chapter_generate_instruction(action: AgentPlanAction, knowledge_summary: str = "", skill_prompt: str = "") -> str:
  merged_instruction = _compose_execution_instruction(
    action.instruction,
    knowledge_summary=knowledge_summary,
    skill_prompt=skill_prompt,
  )
  parts = [merged_instruction] if merged_instruction else []
  if action.target_words > 0:
    parts.append(f"目标长度约 {action.target_words} 字。")
  return _compose_execution_instruction("\n".join(parts).strip(), limit=2000)


def _execute_chapter_generate(
  settings: Settings,
  runtime: RuntimeState,
  action: AgentPlanAction,
  task_id: str,
  knowledge_summary: str = "",
  skill_prompt: str = "",
):
  result = _generate_chapter(
    settings,
    ChapterGenerateRequest(
      project_id=runtime.detail.id,
      chapter_id=action.chapter_id,
      instruction=_chapter_generate_instruction(action, knowledge_summary, skill_prompt),
      target_words=action.target_words,
      style_name=action.style_name,
      xp_preset=action.xp_preset,
      characters_involved=action.characters_involved,
      key_items=action.key_items,
      scene_location=action.scene_location,
      time_constraint=action.time_constraint,
    ),
    task_id,
  )
  if not result.content.strip():
    raise RuntimeError("章节生成没有返回可保存正文")
  detail, review_error = update_chapter_content_with_review_status(
    settings,
    runtime.detail.id,
    action.chapter_id,
    ChapterUpdateRequest(content=result.content, style_name=action.style_name, xp_preset=action.xp_preset),
  )
  detail, review_error, repair_result = auto_repair_chapter_after_review(
    settings,
    runtime.detail.id,
    action.chapter_id,
    detail,
    review_error=review_error,
    style_name=action.style_name,
    xp_preset=action.xp_preset,
    instruction=_chapter_generate_instruction(action, knowledge_summary, skill_prompt),
  )
  return result, detail, review_error, repair_result


def _render_chapter_generate_reply(result, chapter) -> tuple[str, list[str]]:
  return (
    f"第 {chapter.index} 章《{chapter.title}》已经生成并写回项目。\n\n{result.summary}",
    [f"已更新第 {chapter.index} 章《{chapter.title}》正文"],
  )


def _render_workflow_reply(result, chapter) -> tuple[str, list[str]]:
  if result.mode == "draft":
    return (
      f"第 {chapter.index} 章《{chapter.title}》已经续写并写回项目。\n\n{result.summary}",
      [f"已更新第 {chapter.index} 章《{chapter.title}》正文"],
    )

  if result.mode == "scenes":
    scene_lines = [
      f"{index}. {item.title}｜目标：{item.goal}｜冲突：{item.conflict}｜转折：{item.turn}"
      for index, item in enumerate(result.scenes, start=1)
    ]
    body = "\n".join(scene_lines)
    return (
      f"第 {chapter.index} 章《{chapter.title}》的场景清单已经整理好。\n\n{result.summary}\n\n{body}".strip(),
      [],
    )

  checklist = "\n".join(f"- {item}" for item in result.checklist)
  reply = f"第 {chapter.index} 章《{chapter.title}》的判断已经出来了。\n\n{result.summary}"
  if checklist:
    reply = f"{reply}\n\n建议：\n{checklist}"
  return reply, []


def _render_consistency_reply(result, chapter) -> str:
  issue_lines = [
    f"- [{item.level}] {item.title}：{item.detail}"
    for item in result.issues
  ]
  if not issue_lines:
    issue_lines = ["- 暂时没有明显前后矛盾。"]
  suggestion_lines = [f"- {item}" for item in result.suggestions]
  reply = [
    f"第 {chapter.index} 章《{chapter.title}》的一致性检查已经完成。",
    "",
    result.summary,
    "",
    "问题清单：",
    *issue_lines,
  ]
  if suggestion_lines:
    reply.extend(["", "建议：", *suggestion_lines])
  return "\n".join(reply).strip()


_LENGTH_CLAIM_PATTERN = re.compile(
  r"(完整章|完整章节|整章|目标字数|上、中、下|上中下|扩展为|扩写为|[0-9０-９.．零〇一二三四五六七八九十百千万两]+\s*字)"
)


def _rewrite_instruction_targets_chapter_capacity(instruction: str, mode: str = "") -> bool:
  if instruction_requests_full_chapter(instruction):
    return True
  normalized_mode = str(mode or "").strip().lower()
  if normalized_mode == "humanize":
    return False
  if normalized_mode == "finalize":
    return True
  normalized = str(instruction or "").strip()
  if not normalized:
    return False
  return bool(re.search(r"(重写|改写|定稿|扩写|扩成正文|扩成完整|扩到完整|补完本章|补完整)", normalized))


def _rewrite_target_for_action(runtime: RuntimeState, action: AgentPlanAction, chapter) -> tuple[int, str]:
  instruction = str(action.instruction or "")
  explicit_target = explicit_length_target(instruction)
  if explicit_target > 0:
    return explicit_target, "用户要求"

  if instruction_requests_explicit_length(instruction):
    return 0, ""

  if action.target_words > 0:
    return action.target_words, "计划目标"

  if instruction_requests_full_chapter(instruction):
    target = full_chapter_generation_target(runtime.detail, chapter)
    if target > 0:
      return target, "完整章目标"

  if not _rewrite_instruction_targets_chapter_capacity(instruction, action.mode):
    return 0, ""

  average = chapter_average_word_target(runtime.detail)
  if average >= 9_000:
    return average, "项目单章均值"

  return 0, ""


def _rewrite_length_status(chapter, *, target_words: int, target_basis: str) -> dict[str, object]:
  saved_words = chapter_text_length(chapter)
  status = "checked"
  message = f"保存校验：当前正文约 {saved_words} 字。"
  if target_words > 0:
    basis = f"{target_basis}约" if target_basis else "约"
    if saved_words < int(target_words * 0.9):
      status = "under_target"
      message = (
        f"保存校验：当前正文约 {saved_words} 字，低于{basis} {target_words} 字；"
        "本次不能标为完整章。"
      )
    else:
      message = f"保存校验：当前正文约 {saved_words} 字，已接近{basis} {target_words} 字。"
  return {
    "saved_words": saved_words,
    "target_words": target_words,
    "target_basis": target_basis,
    "status": status,
    "message": message,
  }


def _filter_unverified_rewrite_changes(
  changes: list[str],
  length_status: dict[str, object],
  *,
  force: bool = False,
) -> list[str]:
  if not force and length_status.get("status") != "under_target":
    return list(changes)
  return [
    item
    for item in changes
    if not _LENGTH_CLAIM_PATTERN.search(str(item or ""))
  ]


def _render_rewrite_reply(
  result,
  chapter,
  mode: str,
  *,
  changes: list[str] | None = None,
  length_status: dict[str, object] | None = None,
) -> tuple[str, list[str]]:
  label = {
    "finalize": "定稿",
    "humanize": "去 AI",
    "polish": "润色",
  }.get(mode, "修订")
  status = dict(length_status or {})
  header = f"第 {chapter.index} 章《{chapter.title}》已经完成{label}并写回项目。"
  if status.get("restored_original"):
    header = f"第 {chapter.index} 章《{chapter.title}》本轮未覆盖原章节；自动补足失败，已恢复改稿前正文。"
  elif status.get("status") == "under_target":
    header = f"第 {chapter.index} 章《{chapter.title}》已写回项目；按完整章目标看仍明显偏短。"

  display_changes = list(changes if changes is not None else result.changes)
  status_message = str(status.get("message") or "").strip()
  if status_message:
    display_changes.append(status_message)
  change_lines = [f"- {item}" for item in display_changes]
  summary_text = (
    "本轮模型改稿未提交到章节正文，因为完整章补足没有成功。"
    if status.get("restored_original")
    else result.summary
  )
  reply = [
    header,
    "",
    summary_text,
  ]
  if change_lines:
    reply.extend(["", "本轮处理：", *change_lines])

  changes_for_trace = (
    [f"未覆盖第 {chapter.index} 章《{chapter.title}》；已恢复改稿前正文"]
    if status.get("restored_original")
    else [f"已写回第 {chapter.index} 章《{chapter.title}》{label}稿"]
  )
  if status_message:
    changes_for_trace.append(status_message)
  return "\n".join(reply).strip(), changes_for_trace


def _rewrite_completion_instruction(
  action: AgentPlanAction,
  length_status: dict[str, object],
  *,
  knowledge_summary: str = "",
  skill_prompt: str = "",
) -> str:
  saved_words = int(length_status.get("saved_words") or 0)
  target_words = int(length_status.get("target_words") or 0)
  remaining_words = max(300, target_words - saved_words)
  base_instruction = _compose_execution_instruction(
    action.instruction,
    knowledge_summary=knowledge_summary,
    skill_prompt=skill_prompt,
    limit=1100,
  )
  parts = [
    base_instruction,
    f"上一轮写回后正文长度约 {saved_words}，仍明显不足。",
    f"请保留当前章节标题和已保存正文，从当前正文末尾继续扩写正文，缺口约 {remaining_words} 字。",
    "如果缺口超过单次安全长度，按多个小节持续承接，直到本章接近目标容量。",
    "必须写成连续正文，不要输出梗概、说明、修改报告或章节分析。",
    "补足场景推进、人物行动、冲突升级、信息揭示和段尾钩子，使本章接近项目单章容量。",
  ]
  return _compose_execution_instruction("\n".join(item for item in parts if item.strip()), limit=1900)


def _complete_underfilled_rewrite(
  settings: Settings,
  *,
  project_id: str,
  action: AgentPlanAction,
  original_content: str,
  detail,
  review_error: str,
  repair_result: ChapterAutoRepairResult | None,
  length_status: dict[str, object],
  target_words: int,
  target_basis: str,
  knowledge_summary: str = "",
  skill_prompt: str = "",
) -> tuple[object, str, ChapterAutoRepairResult | None, dict[str, object], dict[str, object]]:
  completion_info: dict[str, object] = {
    "attempted": False,
    "applied": False,
    "rounds_attempted": 0,
    "rounds_applied": 0,
    "summaries": [],
    "error": "",
  }
  current_detail = detail
  current_review_error = review_error
  current_repair_result = repair_result
  current_status = dict(length_status)
  current_chapter = next((item for item in current_detail.chapters if item.id == action.chapter_id), None)
  if current_chapter is None:
    completion_info["error"] = "自动续写前目标章节不存在"
    return current_detail, current_review_error, current_repair_result, current_status, completion_info
  chapter_path = Path(current_detail.path) / "chapters" / f"{current_chapter.index:03d}.md"
  support_text = build_prompt_support(
    settings,
    task_key="chapter",
    style_name=action.style_name,
    style_task_type="chapter",
    style_query=action.instruction,
    xp_name=action.xp_preset,
    project_id=project_id,
    chapter_id=action.chapter_id,
  )

  target_for_rounds = max(0, int(target_words or current_status.get("target_words") or 0))
  max_rounds = min(24, max(4, ((target_for_rounds + 1_199) // 1_200) + 2))
  for round_index in range(1, max_rounds + 1):
    if current_status.get("status") != "under_target":
      break
    saved_words = int(current_status.get("saved_words") or 0)
    target = int(current_status.get("target_words") or target_words or 0)
    if target <= 0:
      break
    remaining_words = max(300, target - saved_words)
    completion_info["attempted"] = True
    completion_info["rounds_attempted"] = int(completion_info["rounds_attempted"] or 0) + 1

    try:
      pipeline = _run_continuation_pipeline(
        settings,
        project_id=project_id,
        chapter_id=action.chapter_id,
        instruction=_rewrite_completion_instruction(
          action,
          current_status,
          knowledge_summary=knowledge_summary,
          skill_prompt=skill_prompt,
        ),
        target_words=remaining_words,
        support_text=support_text,
        task_name_prefix=f"rewrite_completion:{round_index}",
        candidate_count=1,
        prefer_project_budget=False,
      )
    except Exception as error:
      completion_info["error"] = str(error)
      break

    completed_content = str(pipeline.get("content") or "").strip()
    if len(completed_content) <= saved_words + 100:
      completion_info["error"] = "自动续写没有产生足够的新正文"
      break

    atomic_write_text(chapter_path, completed_content)
    current_detail = get_project_detail(settings, project_id)
    completion_info["rounds_applied"] = int(completion_info["rounds_applied"] or 0) + 1
    summary = str(pipeline.get("summary") or "").strip()
    if summary:
      summaries = list(completion_info.get("summaries") or [])
      summaries.append(summary)
      completion_info["summaries"] = summaries[:3]

    chapter = next((item for item in current_detail.chapters if item.id == action.chapter_id), None)
    if chapter is None:
      completion_info["error"] = "自动续写后目标章节不存在"
      break
    current_status = _rewrite_length_status(chapter, target_words=target_words, target_basis=target_basis)

  if completion_info.get("attempted") and current_status.get("status") != "under_target" and int(completion_info.get("rounds_applied") or 0) > 0:
    final_chapter = next((item for item in current_detail.chapters if item.id == action.chapter_id), None)
    final_content = str(getattr(final_chapter, "content", "") or "")
    current_detail, current_review_error = update_chapter_content_with_review_status(
      settings,
      project_id,
      action.chapter_id,
      ChapterUpdateRequest(content=final_content, style_name=action.style_name, xp_preset=action.xp_preset),
    )
    current_detail, current_review_error, current_repair_result = auto_repair_chapter_after_review(
      settings,
      project_id,
      action.chapter_id,
      current_detail,
      review_error=current_review_error,
      style_name=action.style_name,
      xp_preset=action.xp_preset,
      instruction=_rewrite_completion_instruction(
        action,
        current_status,
        knowledge_summary=knowledge_summary,
        skill_prompt=skill_prompt,
      ),
    )
    final_chapter = next((item for item in current_detail.chapters if item.id == action.chapter_id), None)
    current_status = _rewrite_length_status(final_chapter, target_words=target_words, target_basis=target_basis)
    if current_status.get("status") != "under_target":
      completion_info["applied"] = True
    else:
      completion_info["error"] = "自动补足完成后仍未达到完整章容量"

  if completion_info.get("attempted") and not completion_info.get("applied") and not completion_info.get("error"):
    completion_info["error"] = "自动补足后仍未达到完整章容量"

  if completion_info.get("attempted") and not completion_info.get("applied"):
    current_detail, current_review_error = update_chapter_content_with_review_status(
      settings,
      project_id,
      action.chapter_id,
      ChapterUpdateRequest(content=original_content, style_name=action.style_name, xp_preset=action.xp_preset),
    )
    chapter = next((item for item in current_detail.chapters if item.id == action.chapter_id), None)
    current_status = _rewrite_length_status(chapter, target_words=target_words, target_basis=target_basis)
    current_status["restored_original"] = True
    current_repair_result = None
    completion_info["restored_original"] = True

  return current_detail, current_review_error, current_repair_result, current_status, completion_info


@register_action_handler("review_knowledge")
async def _handle_review_knowledge(ctx: AgentActionExecutionContext, state: AgentExecutionState) -> None:
  chapter = next((item for item in state.runtime.detail.chapters if item.id == ctx.action.chapter_id), None) if ctx.action.chapter_id else None
  chapter_index = int(getattr(chapter, "index", 0) or 0)
  knowledge_summary, material_count = await asyncio.to_thread(
    _review_project_knowledge,
    ctx.settings,
    state.runtime,
    ctx.action.instruction,
    task_pack_kind=ctx.action.task_pack_kind,
    chapter_index=chapter_index,
  )
  state.knowledge_summary = knowledge_summary
  state.knowledge_summary_chapter_id = ctx.action.chapter_id
  if ctx.action.chapter_id:
    state.chapter_knowledge_summaries[ctx.action.chapter_id] = knowledge_summary
  if material_count > 0:
    scope_text = f"第 {chapter_index} 章可用的" if chapter_index > 0 else ""
    state.knowledge_review_note = f"已先分析{scope_text}资料库和 Obsidian {material_count} 份资料。"
    state.changes.append(f"已分析{scope_text}资料库和 Obsidian {material_count} 份资料")
  elif "当前没有上传资料或 Obsidian 笔记" in knowledge_summary:
    state.knowledge_review_note = "已先整理当前项目资料，资料库和 Obsidian 当前没有可用资料。"
    state.changes.append("已整理当前项目文档、记忆和正文")
  else:
    state.knowledge_review_note = "已先检查资料库和 Obsidian，当前没有可用资料。"
    state.changes.append("已检查资料库和 Obsidian，当前没有可用资料")

  _append_artifact(
    state,
    kind="knowledge_summary",
    title="资料库分析",
    summary=state.knowledge_review_note,
    content_preview=knowledge_summary,
    metadata={"material_count": material_count},
  )
  _record_action_completion(
    state,
    ctx.step,
    ctx.action,
    task_pack_kind=ctx.task_pack_kind,
    summary=state.knowledge_review_note or "已完成资料分析。",
    changes=[state.changes[-1]] if state.changes else [],
    material_count=material_count,
  )


@register_action_handler("brainstorm")
async def _handle_brainstorm(ctx: AgentActionExecutionContext, state: AgentExecutionState) -> None:
  result = await asyncio.to_thread(
    _generate_brainstorm,
    ctx.settings,
    _brainstorm_request(state.runtime, ctx.payload, state.skill_prompt_block, state.active_skill_ids),
    ctx.task_id,
  )
  state.last_reply = result.reply
  state.suggestions = result.suggestions
  _append_skill_suggestion(state, _suggestion_from_skill_candidate(result.skill_candidate))
  state.can_save_discussion_summary = True
  _append_artifact(
    state,
    kind="discussion_summary",
    title="讨论结果",
    summary="本轮讨论给出了新的推进建议。",
    content_preview=result.reply,
  )
  _record_action_completion(
    state,
    ctx.step,
    ctx.action,
    task_pack_kind=ctx.task_pack_kind,
    summary=result.reply,
    changes=[],
  )


@register_action_handler("skill_optimize")
async def _handle_skill_optimize(ctx: AgentActionExecutionContext, state: AgentExecutionState) -> None:
  selected_skill_ids = _ordered_unique_strings([*ctx.action.skill_ids, *state.active_skill_ids])
  selected_skill_id = selected_skill_ids[0] if selected_skill_ids else ""
  selected_skill_names = custom_skill_names(ctx.settings, selected_skill_ids)
  materialize_messages = [
    BrainstormMessage(role=item.role, content=_agent_message_model_content(item, limit=3800))
    for item in ctx.payload.messages[-20:]
    if item.content.strip()
  ]
  if ctx.action.instruction.strip() and (
    not materialize_messages
    or materialize_messages[-1].content.strip() != ctx.action.instruction.strip()
  ):
    materialize_messages.append(BrainstormMessage(role="user", content=ctx.action.instruction.strip()))

  result = await asyncio.to_thread(
    materialize_skill,
    ctx.settings,
    SkillMaterializeRequest(
      project_id=state.runtime.detail.id,
      messages=materialize_messages,
      action="iterate" if selected_skill_id else "create",
      skill_id=selected_skill_id,
      skill_name=selected_skill_names[0] if selected_skill_names else "",
      selected_chapter_id=ctx.payload.selected_chapter_id,
    ),
  )
  action_label = "更新" if result.action == "iterate" else "创建"
  state.last_reply = (
    f"已{action_label}用户技能「{result.skill.name}」。\n\n"
    f"{result.verification.summary}"
  ).strip()
  skill_change = f"已{action_label}用户技能「{result.skill.name}」"
  state.changes.append(skill_change)
  _append_artifact(
    state,
    kind="user_skill",
    title=result.skill.name,
    summary=result.verification.summary,
    content_preview=result.skill_markdown,
    metadata={
      "skill_id": result.skill.id,
      "action": result.action,
      "saved_path": result.saved_path,
    },
  )
  _record_action_completion(
    state,
    ctx.step,
    ctx.action,
    task_pack_kind=ctx.task_pack_kind,
    summary=result.verification.summary,
    changes=[skill_change],
  )


@register_action_handler("generate_architecture")
async def _handle_generate_architecture(ctx: AgentActionExecutionContext, state: AgentExecutionState) -> None:
  detail, workspace = await asyncio.to_thread(
    _generate_full_architecture,
    ctx.settings,
    state.runtime,
    _compose_execution_instruction(
      ctx.action.instruction,
      knowledge_summary=state.knowledge_summary,
      skill_prompt=state.skill_prompt_block,
      limit=3800,
    ),
    ctx.payload.messages,
    ctx.task_id,
  )
  state.runtime = _build_runtime_state(ctx.settings, detail.id, ctx.payload.selected_chapter_id)
  state.last_reply = (
    f"整书架构已经补齐并写回项目。\n\n"
    f"当前架构完整度：{state.runtime.architecture_progress}/5。"
  )
  architecture_changes = ["已更新核心种子", "已更新人物设定", "已更新世界设定", "已更新情节骨架", "已更新章节蓝图"]
  state.changes.extend(architecture_changes)
  if workspace is None:
    document_map = {
      item.key: item.content
      for item in detail.story_overview.documents
    }
    architecture_preview = "\n\n".join(
      [
        document_map.get("core_seed", ""),
        document_map.get("character_design", ""),
        document_map.get("world_building", ""),
        document_map.get("plot_structure", ""),
        document_map.get("blueprint", ""),
      ]
    )
  else:
    architecture_preview = "\n\n".join(
      [
        workspace.core_seed,
        workspace.character_design,
        workspace.world_building,
        workspace.plot_structure,
        workspace.blueprint,
      ]
    )
  _append_artifact(
    state,
    kind="architecture_workspace",
    title="整书架构",
    summary="整书架构已经写回项目。",
    content_preview=architecture_preview,
    metadata={"architecture_progress": state.runtime.architecture_progress},
  )
  _record_action_completion(
    state,
    ctx.step,
    ctx.action,
    task_pack_kind=ctx.task_pack_kind,
    summary="整书架构已经写回项目。",
    changes=architecture_changes,
  )


@register_action_handler("continue_project")
async def _handle_continue_project(ctx: AgentActionExecutionContext, state: AgentExecutionState) -> None:
  result = await asyncio.to_thread(
    _continue_project,
    ctx.settings,
    ContinueProjectRequest(
      project_id=state.runtime.detail.id,
      new_chapters=ctx.action.new_chapters or 5,
      instruction=_compose_execution_instruction(
        ctx.action.instruction,
        knowledge_summary=state.knowledge_summary,
        skill_prompt=state.skill_prompt_block,
        limit=2900,
      ),
      style_name=ctx.action.style_name,
      xp_preset=ctx.action.xp_preset,
    ),
    ctx.task_id,
  )
  state.runtime = _build_runtime_state(ctx.settings, ctx.payload.project_id, ctx.payload.selected_chapter_id)
  state.last_reply = (
    f"后续规划已经向后扩写到 {result.target_chapters} 章。\n\n"
    f"{result.summary}"
  )
  continue_changes = [f"已扩写后续 {ctx.action.new_chapters or 5} 章规划"]
  state.changes.extend(continue_changes)
  _append_artifact(
    state,
    kind="continuation_plan",
    title="后续规划",
    summary=result.summary,
    content_preview=result.content,
    metadata={"target_chapters": result.target_chapters},
  )
  _record_action_completion(
    state,
    ctx.step,
    ctx.action,
    task_pack_kind=ctx.task_pack_kind,
    summary=result.summary,
    changes=continue_changes,
  )


@register_action_handler("chapter_generate")
async def _handle_chapter_generate(ctx: AgentActionExecutionContext, state: AgentExecutionState) -> None:
  knowledge_summary = await _knowledge_summary_for_action(ctx, state)
  before_obsidian_signatures = _obsidian_maintenance_action_signatures(Path(state.runtime.detail.path))
  result, detail, review_error, repair_result = await asyncio.to_thread(
    _execute_chapter_generate,
    ctx.settings,
    state.runtime,
    ctx.action,
    ctx.task_id,
    knowledge_summary,
    state.skill_prompt_block,
  )
  state.runtime = _build_runtime_state(ctx.settings, detail.id, ctx.payload.selected_chapter_id)
  chapter = next((item for item in state.runtime.detail.chapters if item.id == ctx.action.chapter_id), None)
  if chapter is None:
    raise RuntimeError("目标章节不存在")
  state.last_reply, chapter_changes = _render_chapter_generate_reply(result, chapter)
  review_status = summarize_chapter_review_status(state.runtime.detail, chapter.id, review_error)
  state.last_reply, chapter_changes, state.suggestions = _apply_review_feedback(
    reply=state.last_reply,
    changes=chapter_changes,
    suggestions=[item for item in [result.next_action] if item] or state.suggestions,
    review_status=review_status,
  )
  state.last_reply, chapter_changes, state.suggestions = _apply_auto_repair_feedback(
    reply=state.last_reply,
    changes=chapter_changes,
    suggestions=state.suggestions,
    repair_result=repair_result,
  )
  state.changes.extend(chapter_changes)
  _append_artifact(
    state,
    kind="chapter_content",
    title=f"第 {chapter.index} 章《{chapter.title}》",
    summary=result.summary,
    content_preview=chapter.content or result.content,
    metadata={
      "chapter_id": chapter.id,
      "chapter_index": chapter.index,
      **_review_metadata(review_status),
      **_auto_repair_metadata(repair_result),
    },
  )
  _append_chapter_review_artifact(state, chapter.id)
  obsidian_changes = _append_obsidian_maintenance_delta_artifact(
    state,
    chapter=chapter,
    before_signatures=before_obsidian_signatures,
  )
  _record_action_completion(
    state,
    ctx.step,
    ctx.action,
    task_pack_kind=ctx.task_pack_kind,
    summary=result.summary,
    changes=[*chapter_changes, *obsidian_changes],
  )


@register_action_handler("chapter_workflow")
async def _handle_chapter_workflow_action(ctx: AgentActionExecutionContext, state: AgentExecutionState) -> None:
  knowledge_summary = await _knowledge_summary_for_action(ctx, state)
  before_obsidian_signatures = _obsidian_maintenance_action_signatures(Path(state.runtime.detail.path))
  result, detail, review_error, repair_result = await asyncio.to_thread(
    _execute_chapter_workflow,
    ctx.settings,
    state.runtime,
    ctx.action,
    ctx.task_id,
    knowledge_summary,
    state.skill_prompt_block,
  )
  state.runtime = _build_runtime_state(ctx.settings, detail.id, ctx.payload.selected_chapter_id)
  chapter = next((item for item in state.runtime.detail.chapters if item.id == ctx.action.chapter_id), None)
  if chapter is None:
    raise RuntimeError("目标章节不存在")
  state.last_reply, workflow_changes = _render_workflow_reply(result, chapter)
  if result.mode == "draft":
    review_status = summarize_chapter_review_status(state.runtime.detail, chapter.id, review_error)
    state.last_reply, workflow_changes, state.suggestions = _apply_review_feedback(
      reply=state.last_reply,
      changes=workflow_changes,
      suggestions=result.checklist or state.suggestions,
      review_status=review_status,
    )
    state.last_reply, workflow_changes, state.suggestions = _apply_auto_repair_feedback(
      reply=state.last_reply,
      changes=workflow_changes,
      suggestions=state.suggestions,
      repair_result=repair_result,
    )
  else:
    review_status = {}
    state.suggestions = result.checklist or state.suggestions
    repair_result = None
  state.changes.extend(workflow_changes)
  preview = (chapter.content if result.mode == "draft" else "") or result.draft or "\n".join(
    [
      result.summary,
      *[
        f"{index}. {item.title}｜目标：{item.goal}｜冲突：{item.conflict}｜转折：{item.turn}"
        for index, item in enumerate(result.scenes, start=1)
      ],
    ]
  )
  _append_artifact(
    state,
    kind="chapter_workflow",
    title=f"第 {chapter.index} 章《{chapter.title}》",
    summary=result.summary,
    content_preview=preview,
    metadata={
      "mode": result.mode,
      "chapter_id": chapter.id,
      "chapter_index": chapter.index,
      **_review_metadata(review_status),
      **_auto_repair_metadata(repair_result),
    },
  )
  if result.mode == "draft":
    _append_chapter_review_artifact(state, chapter.id)
  obsidian_changes = []
  if result.mode == "draft":
    obsidian_changes = _append_obsidian_maintenance_delta_artifact(
      state,
      chapter=chapter,
      before_signatures=before_obsidian_signatures,
    )
  _record_action_completion(
    state,
    ctx.step,
    ctx.action,
    task_pack_kind=ctx.task_pack_kind,
    summary=result.summary,
    changes=[*workflow_changes, *obsidian_changes],
  )


@register_action_handler("consistency_check")
async def _handle_consistency_check(ctx: AgentActionExecutionContext, state: AgentExecutionState) -> None:
  knowledge_summary = await _knowledge_summary_for_action(ctx, state)
  result = await asyncio.to_thread(
    _generate_consistency,
    ctx.settings,
    ConsistencyCheckRequest(
      project_id=state.runtime.detail.id,
      chapter_id=ctx.action.chapter_id,
      focus=_compose_execution_instruction(
        ctx.action.instruction,
        knowledge_summary=knowledge_summary,
        skill_prompt=state.skill_prompt_block,
      ),
    ),
    ctx.task_id,
  )
  chapter = next((item for item in state.runtime.detail.chapters if item.id == ctx.action.chapter_id), None)
  if chapter is None:
    raise RuntimeError("目标章节不存在")
  state.last_reply = _render_consistency_reply(result, chapter)
  state.suggestions = result.suggestions
  _append_artifact(
    state,
    kind="consistency_report",
    title=f"第 {chapter.index} 章《{chapter.title}》",
    summary=result.summary,
    content_preview="\n".join(
      [
        *[f"[{item.level}] {item.title}：{item.detail}" for item in result.issues],
        *[f"建议：{item}" for item in result.suggestions],
      ]
    ),
    metadata={"issue_count": len(result.issues), "chapter_id": chapter.id, "chapter_index": chapter.index},
  )
  _record_action_completion(
    state,
    ctx.step,
    ctx.action,
    task_pack_kind=ctx.task_pack_kind,
    summary=result.summary,
    changes=[],
  )


@register_action_handler("rewrite_chapter")
async def _handle_rewrite_chapter(ctx: AgentActionExecutionContext, state: AgentExecutionState) -> None:
  original_chapter = next((item for item in state.runtime.detail.chapters if item.id == ctx.action.chapter_id), None)
  if original_chapter is None:
    raise RuntimeError("目标章节不存在")
  knowledge_summary = await _knowledge_summary_for_action(ctx, state)
  before_obsidian_signatures = _obsidian_maintenance_action_signatures(Path(state.runtime.detail.path))
  target_words, target_basis = _rewrite_target_for_action(state.runtime, ctx.action, original_chapter)
  result = await asyncio.to_thread(
    _rewrite_chapter,
    ctx.settings,
    ChapterRewriteRequest(
      project_id=state.runtime.detail.id,
      chapter_id=ctx.action.chapter_id,
      instruction=_compose_execution_instruction(
        ctx.action.instruction,
        knowledge_summary=knowledge_summary,
        skill_prompt=state.skill_prompt_block,
      ),
      style_name=ctx.action.style_name,
      xp_preset=ctx.action.xp_preset,
    ),
    ctx.task_id,
    ctx.action.mode or "polish",
  )
  detail, review_error = await asyncio.to_thread(
    update_chapter_content_with_review_status,
    ctx.settings,
    state.runtime.detail.id,
    ctx.action.chapter_id,
    ChapterUpdateRequest(content=result.revised, style_name=ctx.action.style_name, xp_preset=ctx.action.xp_preset),
  )
  detail, review_error, repair_result = await asyncio.to_thread(
    auto_repair_chapter_after_review,
    ctx.settings,
    state.runtime.detail.id,
    ctx.action.chapter_id,
    detail,
    review_error=review_error,
    style_name=ctx.action.style_name,
    xp_preset=ctx.action.xp_preset,
    instruction=_compose_execution_instruction(
      ctx.action.instruction,
      knowledge_summary=knowledge_summary,
      skill_prompt=state.skill_prompt_block,
    ),
  )
  patches: list[StoryDocumentPatch] = []
  if result.updated_summary.strip():
    patches.append(StoryDocumentPatch(key="global_summary", content=result.updated_summary))
  if result.updated_character_state.strip():
    patches.append(StoryDocumentPatch(key="character_state", content=result.updated_character_state))
  if patches:
    update_story_documents(
      ctx.settings,
      state.runtime.detail.id,
      StoryDocumentBatchUpdateRequest(documents=patches),
    )
  state.runtime = _build_runtime_state(ctx.settings, detail.id, ctx.payload.selected_chapter_id)
  chapter = next((item for item in state.runtime.detail.chapters if item.id == ctx.action.chapter_id), None)
  if chapter is None:
    raise RuntimeError("目标章节不存在")
  length_status = _rewrite_length_status(chapter, target_words=target_words, target_basis=target_basis)
  completion_info: dict[str, object] = {
    "attempted": False,
    "applied": False,
    "rounds_attempted": 0,
    "rounds_applied": 0,
    "summaries": [],
    "error": "",
  }
  if length_status.get("status") == "under_target":
    detail, review_error, repair_result, length_status, completion_info = await asyncio.to_thread(
      _complete_underfilled_rewrite,
      ctx.settings,
      project_id=state.runtime.detail.id,
      action=ctx.action,
      original_content=original_chapter.content,
      detail=detail,
      review_error=review_error,
      repair_result=repair_result,
      length_status=length_status,
      target_words=target_words,
      target_basis=target_basis,
      knowledge_summary=knowledge_summary,
      skill_prompt=state.skill_prompt_block,
    )
    state.runtime = _build_runtime_state(ctx.settings, detail.id, ctx.payload.selected_chapter_id)
    chapter = next((item for item in state.runtime.detail.chapters if item.id == ctx.action.chapter_id), None)
    if chapter is None:
      raise RuntimeError("目标章节不存在")

  display_changes = _filter_unverified_rewrite_changes(
    result.changes,
    length_status,
    force=bool(completion_info.get("attempted")),
  )
  humanize_quality_metadata: dict[str, object] = {}
  quality_report = getattr(result, "quality_report", None)
  if ctx.action.mode == "humanize" and quality_report is not None and not completion_info.get("restored_original"):
    display_changes.append(quality_report.summary)
    if quality_report.delta <= 0:
      _append_ordered_unique(state.suggestions, "这版本地去 AI 评分没有改善，建议继续按残留问题处理。")
    humanize_quality_metadata = {
      "humanize_before_score": quality_report.before_score,
      "humanize_after_score": quality_report.after_score,
      "humanize_delta": quality_report.delta,
      "humanize_summary": quality_report.summary,
      "humanize_remaining_issues": [
        item.model_dump(mode="json")
        for item in quality_report.remaining_issues
      ],
    }
  if completion_info.get("restored_original"):
    display_changes = []
  if completion_info.get("applied"):
    display_changes.append(f"自动续写补足章节容量：当前正文约 {length_status.get('saved_words', 0)} 字。")
  elif completion_info.get("attempted") and completion_info.get("error"):
    display_changes.append(f"自动续写补足章节容量失败：{completion_info.get('error')}")
    if completion_info.get("restored_original"):
      display_changes.append("自动补足失败，已恢复本轮改稿前正文。")
  if length_status.get("status") == "under_target":
    _append_ordered_unique(state.suggestions, "继续扩展本章正文，再重新核验完整章容量。")
  rewrite_suggestions = [*state.suggestions]
  state.last_reply, rewrite_changes = _render_rewrite_reply(
    result,
    chapter,
    ctx.action.mode or "polish",
    changes=display_changes,
    length_status=length_status,
  )
  review_status = summarize_chapter_review_status(state.runtime.detail, chapter.id, review_error)
  state.last_reply, rewrite_changes, state.suggestions = _apply_review_feedback(
    reply=state.last_reply,
    changes=rewrite_changes,
    suggestions=rewrite_suggestions or state.suggestions,
    review_status=review_status,
  )
  state.last_reply, rewrite_changes, state.suggestions = _apply_auto_repair_feedback(
    reply=state.last_reply,
    changes=rewrite_changes,
    suggestions=state.suggestions,
    repair_result=repair_result,
  )
  state.changes.extend(rewrite_changes)
  length_metadata = {
    "saved_word_count": length_status.get("saved_words", 0),
    "length_target_words": length_status.get("target_words", 0),
    "length_target_basis": length_status.get("target_basis", ""),
    "length_status": length_status.get("status", ""),
    "length_completion_attempted": bool(completion_info.get("attempted")),
    "length_completion_applied": bool(completion_info.get("applied")),
    "length_completion_rounds_attempted": completion_info.get("rounds_attempted", 0),
    "length_completion_rounds_applied": completion_info.get("rounds_applied", 0),
    "length_completion_restored_original": bool(completion_info.get("restored_original")),
  }
  if completion_info.get("error"):
    length_metadata["length_completion_error"] = completion_info.get("error")
  if completion_info.get("summaries"):
    length_metadata["length_completion_summaries"] = completion_info.get("summaries")
  trace_summary = (
    "自动补足失败，已恢复本轮改稿前正文。"
    if completion_info.get("restored_original")
    else result.summary
  )
  if completion_info.get("applied"):
    trace_summary = f"{trace_summary}\n已自动续写补足章节容量。".strip()
  length_message = str(length_status.get("message") or "").strip()
  if length_message:
    trace_summary = f"{trace_summary}\n{length_message}".strip()
  _append_artifact(
    state,
    kind="rewrite_report",
    title=f"第 {chapter.index} 章《{chapter.title}》",
    summary=trace_summary,
    content_preview=chapter.content or result.revised,
    metadata={
      "mode": ctx.action.mode or "polish",
      "chapter_id": chapter.id,
      "chapter_index": chapter.index,
      **length_metadata,
      **humanize_quality_metadata,
      **_review_metadata(review_status),
      **_auto_repair_metadata(repair_result),
    },
  )
  _append_chapter_review_artifact(state, chapter.id)
  obsidian_changes = _append_obsidian_maintenance_delta_artifact(
    state,
    chapter=chapter,
    before_signatures=before_obsidian_signatures,
  )
  _record_action_completion(
    state,
    ctx.step,
    ctx.action,
    task_pack_kind=ctx.task_pack_kind,
    summary=trace_summary,
    changes=[*rewrite_changes, *obsidian_changes],
  )


def _trajectory_record_from_state(
  *,
  payload: AgentChatRequest,
  plan: AgentPlan,
  state: AgentExecutionState,
  task_id: str,
  status: str,
  error: str = "",
) -> dict[str, object]:
  latest_user_message = next(
    (item for item in reversed(payload.messages) if item.role == "user" and item.content.strip()),
    None,
  )
  return {
    "task_id": task_id,
    "project_id": payload.project_id,
    "thread_id": payload.thread_id,
    "status": status,
    "error": error,
    "latest_user_message": _agent_message_model_content(latest_user_message, limit=2000) if latest_user_message else "",
    "plan": {
      "id": plan.id,
      "title": plan.title,
      "task_pack_kind": _plan_task_pack_kind(plan),
      "actions": [
        {
          "kind": action.kind,
          "label": action.label,
          "task_pack_kind": action.task_pack_kind,
          "mode": action.mode,
          "chapter_id": action.chapter_id,
          "skill_ids": action.skill_ids,
        }
        for action in plan.actions
      ],
    },
    "execution_trace": [item.model_dump(mode="json") for item in state.execution_trace],
    "artifacts": [
      {
        "kind": item.kind,
        "title": item.title,
        "summary": item.summary,
        "metadata": item.metadata,
      }
      for item in state.artifacts
    ],
    "changes": list(state.changes),
    "suggestions": list(state.suggestions),
  }


def _append_ordered_unique(target: list[str], value: str) -> None:
  cleaned = value.strip()
  if cleaned and cleaned not in target:
    target.append(cleaned)


def _subtask_specs_for_action(action: AgentPlanAction) -> list[dict[str, str]]:
  action_id = action.subtask_id or action.kind
  group = action.parallel_group or f"{action.kind}:{action.chapter_id or action_id}"
  explicit_role = action.role.strip()
  explicit_capability = action.capability.strip()
  if explicit_role or explicit_capability:
    return [
      {
        "subtask_id": action_id,
        "role": explicit_role or "执行 agent",
        "capability": explicit_capability or "执行当前 action",
        "parallel_group": group,
      }
    ]

  if action.kind in {"chapter_generate", "chapter_workflow"} and (action.kind == "chapter_generate" or action.mode == "draft"):
    return [
      {
        "subtask_id": f"{action_id}:writer",
        "role": "写作 agent",
        "capability": "生成候选正文；允许写正文草稿，不直接写项目记忆",
        "parallel_group": group,
        "allowed_outputs": ["候选正文", "写作说明"],
      },
      {
        "subtask_id": f"{action_id}:continuity",
        "role": "连续性审校 agent",
        "capability": "检查人物关系、事件结果、时间地点和道具状态；只产出报告",
        "parallel_group": group,
        "allowed_outputs": ["连续性审校报告"],
      },
      {
        "subtask_id": f"{action_id}:voice",
        "role": "人物口气审校 agent",
        "capability": "检查人物声音、对白关系和叙述距离；只产出报告",
        "parallel_group": group,
        "allowed_outputs": ["人物口气审校报告"],
      },
      {
        "subtask_id": f"{action_id}:reader",
        "role": "可读性审校 agent",
        "capability": "检查节奏、段尾压力和阅读牵引；只产出报告",
        "parallel_group": group,
        "allowed_outputs": ["可读性审校报告"],
      },
    ]
  if action.kind == "review_knowledge":
    return [
      {
        "subtask_id": f"{action_id}:knowledge",
        "role": "资料分析 agent",
        "capability": "读取资料并产出 artifact；不能写章节、项目记忆或长期记忆",
        "parallel_group": group,
        "allowed_outputs": ["资料分析报告"],
      }
    ]
  if action.kind == "consistency_check":
    return [
      {
        "subtask_id": f"{action_id}:continuity",
        "role": "连续性审校 agent",
        "capability": "只检查一致性并产出报告；不能改正文",
        "parallel_group": group,
        "allowed_outputs": ["一致性报告"],
      }
    ]
  if action.kind == "rewrite_chapter":
    return [
      {
        "subtask_id": f"{action_id}:rewrite",
        "role": "修订 agent",
        "capability": "按用户要求修订正文；写回后仍需章节核验",
        "parallel_group": group,
        "allowed_outputs": ["候选修订正文"],
      },
      {
        "subtask_id": f"{action_id}:review",
        "role": "核验 agent",
        "capability": "核验修订结果；只产出报告",
        "parallel_group": group,
        "allowed_outputs": ["核验报告"],
      },
    ]
  return []


def _contract_failure_message(report: dict[str, object], default: str) -> str:
  checks = report.get("checks")
  if not isinstance(checks, list):
    return default
  messages = [
    str(item.get("message") or "").strip()
    for item in checks
    if isinstance(item, dict) and str(item.get("status") or "") == "blocked"
  ]
  return "；".join([item for item in messages if item]) or default


async def _run_action_handler_with_heartbeat(
  handler,
  context: AgentActionExecutionContext,
  state: AgentExecutionState,
  project_dir: Path,
) -> None:
  stopped = asyncio.Event()

  async def heartbeat_loop() -> None:
    while not stopped.is_set():
      try:
        await asyncio.wait_for(stopped.wait(), timeout=30)
      except asyncio.TimeoutError:
        await asyncio.to_thread(
          heartbeat_agent_workflow_action,
          project_dir,
          context.task_id,
          step=context.step,
        )

  heartbeat_task = asyncio.create_task(heartbeat_loop(), name=f"agent-workflow-heartbeat-{context.task_id}-{context.step}")
  try:
    await handler(context, state)
  finally:
    stopped.set()
    heartbeat_task.cancel()
    try:
      await heartbeat_task
    except asyncio.CancelledError:
      pass


def _raise_if_workflow_interrupted(project_dir: Path, task_id: str) -> None:
  message = agent_workflow_interrupt_message(project_dir, task_id)
  if not message:
    return
  complete_agent_workflow_run(project_dir, task_id, status="CANCELLED", message=message)
  raise AgentSessionInterrupted(message)


async def _execute_plan(settings: Settings, payload: AgentChatRequest, plan: AgentPlan, task_id: str):
  plan = plan.model_copy(update={"actions": _scope_review_knowledge_actions(plan.actions)})
  active_skill_ids = _ordered_unique_strings([
    *_resolve_agent_skill_ids(settings, payload),
    *_skill_ids_from_plan(plan),
  ])[:5]
  skill_prompt_block = get_custom_skill_prompt_block(settings, active_skill_ids)
  state = AgentExecutionState(
    runtime=_build_runtime_state(settings, payload.project_id, payload.selected_chapter_id),
    active_task_pack_kind=_plan_task_pack_kind(plan),
    active_skill_ids=active_skill_ids,
    skill_prompt_block=skill_prompt_block,
  )
  skill_names = custom_skill_names(settings, active_skill_ids)
  if skill_names:
    state.changes.append(f"已启用用户技能：{'、'.join(skill_names[:5])}")
  total = len(plan.actions)
  project_dir = Path(state.runtime.detail.path)
  await asyncio.to_thread(mark_stale_agent_workflows, project_dir)
  preflight_report = build_agent_preflight_report(settings, state.runtime, plan)
  create_agent_workflow_run(
    project_dir,
    task_id=task_id,
    payload=payload,
    plan=plan,
    preflight=preflight_report,
  )
  if preflight_report.get("status") == "blocked":
    update_agent_workflow_preflight(project_dir, task_id, preflight_report)
    complete_agent_workflow_run(
      project_dir,
      task_id,
      status="BLOCKED",
      message=_contract_failure_message(preflight_report, "执行预检未通过。"),
    )
    raise RuntimeError(_contract_failure_message(preflight_report, "执行预检未通过。"))
  completed_action_kinds: list[str] = []

  for index, action in enumerate(plan.actions, start=1):
    _raise_if_workflow_interrupted(project_dir, task_id)
    current_task_pack_kind = action.task_pack_kind or _task_pack_kind_for_action(action.kind, action.instruction, action.mode)
    if current_task_pack_kind:
      state.active_task_pack_kind = current_task_pack_kind
    if current_task_pack_kind and current_task_pack_kind != state.announced_task_pack_kind and action.kind != "review_knowledge":
      state.changes.append(f"本轮按 {current_task_pack_kind} 任务包执行")
      state.announced_task_pack_kind = current_task_pack_kind

    context = AgentActionExecutionContext(
      settings=settings,
      payload=payload,
      task_id=task_id,
      step=index,
      total=total,
      action=action,
      task_pack_kind=current_task_pack_kind,
    )

    contract_report = evaluate_agent_action_contract(
      settings,
      state.runtime,
      plan,
      action,
      completed_action_kinds=completed_action_kinds,
    )
    update_agent_workflow_action(
      project_dir,
      task_id,
      step=index,
      status="ACKED",
      message=str(contract_report.get("summary") or ""),
      contract=contract_report,
    )
    yield {
      "phase": "started",
      "step": index,
      "total": total,
      "action": action,
      "task_pack_kind": current_task_pack_kind,
    }
    subtask_specs = _subtask_specs_for_action(action)
    for spec in subtask_specs:
      record_agent_workflow_subtask(
        project_dir,
        task_id,
        step=index,
        subtask_id=str(spec.get("subtask_id") or ""),
        role=str(spec.get("role") or ""),
        capability=str(spec.get("capability") or ""),
        parallel_group=str(spec.get("parallel_group") or ""),
        status="RUNNING",
        allowed_outputs=[str(item) for item in (spec.get("allowed_outputs") or [])],
      )
      yield {
        "phase": "subtask_started",
        "step": index,
        "total": total,
        "action": action,
        "task_pack_kind": current_task_pack_kind,
        **spec,
      }

    trace_count_before = len(state.execution_trace)
    artifact_count_before = len(state.artifacts)
    failure_status = "FAILED"
    try:
      if contract_report.get("status") == "blocked":
        failure_status = "BLOCKED"
        raise RuntimeError(_contract_failure_message(contract_report, "动作条件未满足。"))
      update_agent_workflow_action(
        project_dir,
        task_id,
        step=index,
        status="RUNNING",
        message="动作执行中。",
        contract=contract_report,
      )
      await _run_action_handler_with_heartbeat(
        get_action_handler(action.kind),
        context,
        state,
        project_dir,
      )
      output_report = validate_agent_action_outputs(
        state.runtime,
        state.artifacts,
        action,
        artifact_count_before=artifact_count_before,
      )
      if output_report.get("status") == "blocked":
        failure_status = "FAILED"
        raise RuntimeError(_contract_failure_message(output_report, "动作产物检查未通过。"))
      update_agent_workflow_action(
        project_dir,
        task_id,
        step=index,
        status="SUCCEEDED",
        message=str(output_report.get("summary") or "动作完成。"),
        contract=contract_report,
        output_validation=output_report,
      )
      completed_action_kinds.append(action.kind)
    except Exception as error:
      update_agent_workflow_action(
        project_dir,
        task_id,
        step=index,
        status=failure_status,
        message=str(error),
        contract=contract_report,
      )
      complete_agent_workflow_run(
        project_dir,
        task_id,
        status=failure_status,
        message=str(error),
      )
      _record_action_failure(
        state,
        index,
        action,
        task_pack_kind=current_task_pack_kind,
        message=str(error),
      )
      failure_result = AgentChatResult(
        task_id=task_id,
        mode="execution",
        reply=state.last_reply or str(error),
        state=_state_summary(state.runtime),
        thread_id=payload.thread_id,
        task_pack_kind=state.active_task_pack_kind,
        suggestions=state.suggestions,
        execution_trace=state.execution_trace,
        event_blocks=state.event_blocks,
        artifacts=state.artifacts,
        changes=state.changes,
        can_save_discussion_summary=state.can_save_discussion_summary,
        project_detail=state.runtime.detail,
      )
      self_evolution_artifact = run_self_evolution_cycle(
        settings,
        Path(state.runtime.detail.path),
        payload=payload,
        plan=plan,
        result=failure_result,
      )
      state.artifacts.append(self_evolution_artifact)
      append_agent_trajectory(
        settings,
        _trajectory_record_from_state(
          payload=payload,
          plan=plan,
          state=state,
          task_id=task_id,
          status="failed",
          error=str(error),
        ),
      )
      yield {
        "phase": "failed",
        "step": index,
        "total": total,
        "action": action,
        "task_pack_kind": current_task_pack_kind,
        "message": str(error),
        "trace": state.execution_trace[-1],
      }
      for spec in subtask_specs:
        record_agent_workflow_subtask(
          project_dir,
          task_id,
          step=index,
          subtask_id=str(spec.get("subtask_id") or ""),
          role=str(spec.get("role") or ""),
          capability=str(spec.get("capability") or ""),
          parallel_group=str(spec.get("parallel_group") or ""),
          status=failure_status,
          summary=str(error),
          allowed_outputs=[str(item) for item in (spec.get("allowed_outputs") or [])],
        )
        yield {
          "phase": "subtask_failed",
          "step": index,
          "total": total,
          "action": action,
          "task_pack_kind": current_task_pack_kind,
          "message": str(error),
          **spec,
        }
      raise

    trace_delta = state.execution_trace[trace_count_before:]
    artifact_delta = state.artifacts[artifact_count_before:]
    action_summary = str(getattr(trace_delta[-1], "summary", "") if trace_delta else "").strip()
    for spec in subtask_specs:
      record_agent_workflow_subtask(
        project_dir,
        task_id,
        step=index,
        subtask_id=str(spec.get("subtask_id") or ""),
        role=str(spec.get("role") or ""),
        capability=str(spec.get("capability") or ""),
        parallel_group=str(spec.get("parallel_group") or ""),
        status="SUCCEEDED",
        summary=action_summary,
        allowed_outputs=[str(item) for item in (spec.get("allowed_outputs") or [])],
      )
      yield {
        "phase": "subtask_completed",
        "step": index,
        "total": total,
        "action": action,
        "task_pack_kind": current_task_pack_kind,
        "summary": action_summary,
        **spec,
      }
    yield {
      "phase": "completed",
      "step": index,
      "total": total,
      "action": action,
      "task_pack_kind": current_task_pack_kind,
      "trace": trace_delta[-1] if trace_delta else None,
      "artifacts": artifact_delta,
      "state": _state_summary(state.runtime),
      "project_detail": state.runtime.detail if action.kind in {"generate_architecture", "continue_project", "chapter_generate", "chapter_workflow", "rewrite_chapter"} else None,
    }

  _raise_if_workflow_interrupted(project_dir, task_id)

  if state.knowledge_review_note:
    state.last_reply = f"{state.knowledge_review_note}\n\n{state.last_reply}".strip()

  if all(action.kind != "skill_optimize" for action in plan.actions):
    _append_reusable_skill_suggestion(settings, payload, state)

  preliminary_result = AgentChatResult(
    task_id=task_id,
    mode="execution",
    reply=state.last_reply or "执行完成。",
    state=_state_summary(state.runtime),
    thread_id=payload.thread_id,
    task_pack_kind=state.active_task_pack_kind,
    suggestions=state.suggestions,
    execution_trace=state.execution_trace,
    event_blocks=state.event_blocks,
    artifacts=state.artifacts,
    changes=state.changes,
    can_save_discussion_summary=state.can_save_discussion_summary,
    project_detail=state.runtime.detail,
  )
  learning_artifact = build_learning_review_artifact(
    project_id=payload.project_id,
    project_dir=Path(state.runtime.detail.path),
    payload=payload,
    plan=plan,
    result=preliminary_result,
  )
  if learning_artifact is not None:
    state.artifacts.append(learning_artifact)
    memory_count = int(learning_artifact.metadata.get("memory_candidate_count") or 0)
    if memory_count > 0:
      _append_ordered_unique(state.suggestions, "查看「经验候选」，确认后再写入项目记忆。")

  self_evolution_input = preliminary_result.model_copy(
    update={
      "suggestions": state.suggestions,
      "artifacts": state.artifacts,
      "changes": state.changes,
    }
  )
  self_evolution_artifact = run_self_evolution_cycle(
    settings,
    Path(state.runtime.detail.path),
    payload=payload,
    plan=plan,
    result=self_evolution_input,
  )
  state.artifacts.append(self_evolution_artifact)
  if int(self_evolution_artifact.metadata.get("candidate_count") or 0) > 0:
    _append_ordered_unique(state.suggestions, "查看「自学习复盘」，处理技能、记忆和调用规则候选。")

  complete_agent_workflow_run(
    project_dir,
    task_id,
    status="SUCCEEDED",
    message="执行完成。",
  )
  workflow_info = workflow_summary(project_dir, task_id)
  _append_artifact(
    state,
    kind="workflow_run",
    title="执行状态文件",
    summary=f"workflow 状态：{workflow_info.get('status', '')}",
    content_preview=str(workflow_info.get("path") or ""),
    metadata=workflow_info,
  )
  _append_event_block(
    state,
    event_type="session_result",
    title="执行结果",
    status="completed",
    summary=_compact_text(state.last_reply or "执行完成。", 360),
  )

  result_payload = AgentChatResult(
    task_id=task_id,
    mode="execution",
    reply=state.last_reply or "执行完成。",
    state=_state_summary(state.runtime),
    thread_id=payload.thread_id,
    task_pack_kind=state.active_task_pack_kind,
    suggestions=state.suggestions,
    execution_trace=state.execution_trace,
    event_blocks=state.event_blocks,
    artifacts=state.artifacts,
    changes=state.changes,
    can_save_discussion_summary=state.can_save_discussion_summary,
    project_detail=state.runtime.detail,
  )
  append_agent_trajectory(
    settings,
    _trajectory_record_from_state(
      payload=payload,
      plan=plan,
      state=state,
      task_id=task_id,
      status="completed",
    ),
  )
  yield result_payload


def _iter_execution_event_chunks(emitter: AgentEventEmitter, item: object):
  if isinstance(item, AgentChatResult):
    for chunk in emitter.session_result(item.model_dump(mode="json")):
      yield chunk
    return

  if not isinstance(item, dict):
    return

  phase = str(item.get("phase") or "")
  action = item.get("action")
  step = int(item.get("step") or 0)
  total = int(item.get("total") or 0)
  task_pack_kind = str(item.get("task_pack_kind") or "")
  action_kind = str(getattr(action, "kind", ""))
  label = str(getattr(action, "label", ""))

  if phase == "subtask_started":
    for chunk in emitter.subtask_started(
      step=step,
      total=total,
      action_kind=action_kind,
      label=label,
      subtask_id=str(item.get("subtask_id") or ""),
      role=str(item.get("role") or ""),
      capability=str(item.get("capability") or ""),
      parallel_group=str(item.get("parallel_group") or ""),
    ):
      yield chunk
    return

  if phase == "subtask_completed":
    for chunk in emitter.subtask_result(
      step=step,
      total=total,
      action_kind=action_kind,
      label=label,
      subtask_id=str(item.get("subtask_id") or ""),
      role=str(item.get("role") or ""),
      capability=str(item.get("capability") or ""),
      parallel_group=str(item.get("parallel_group") or ""),
      summary=str(item.get("summary") or ""),
    ):
      yield chunk
    return

  if phase == "subtask_failed":
    for chunk in emitter.subtask_failed(
      step=step,
      total=total,
      action_kind=action_kind,
      label=label,
      subtask_id=str(item.get("subtask_id") or ""),
      role=str(item.get("role") or ""),
      capability=str(item.get("capability") or ""),
      parallel_group=str(item.get("parallel_group") or ""),
      message=str(item.get("message") or "子任务失败"),
    ):
      yield chunk
    return

  if phase == "started":
    for chunk in emitter.action_started(
      step=step,
      total=total,
      action_kind=action_kind,
      label=label,
      task_pack_kind=task_pack_kind,
    ):
      yield chunk
    return

  if phase == "failed":
    for chunk in emitter.action_failed(
      step=step,
      total=total,
      action_kind=action_kind,
      label=label,
      task_pack_kind=task_pack_kind,
      message=str(item.get("message") or "执行失败"),
    ):
      yield chunk
    return

  if phase != "completed":
    return

  trace = item.get("trace")
  artifacts = item.get("artifacts") or []
  state_summary = item.get("state")
  project_detail = item.get("project_detail")
  for chunk in emitter.action_result(
    step=step,
    total=total,
    action_kind=action_kind,
    label=label,
    task_pack_kind=task_pack_kind,
    trace=trace.model_dump(mode="json") if trace is not None else None,
    artifacts=[artifact.model_dump(mode="json") for artifact in artifacts],
    changes=list(getattr(trace, "changes", []) or []),
  ):
    yield chunk
  if state_summary is not None:
    for chunk in emitter.state_updated(state_summary.model_dump(mode="json")):
      yield chunk
  if project_detail is not None:
    for chunk in emitter.project_updated(project_detail.model_dump(mode="json")):
      yield chunk


async def agent_session_stream(settings: Settings, payload: AgentChatRequest):
  payload = _payload_with_thread_context(settings, payload)
  task_id = str(uuid4())
  emitter = AgentEventEmitter(task_id=task_id, thread_id=payload.thread_id)
  for chunk in emitter.session_started():
    yield chunk

  runtime = _build_runtime_state(settings, payload.project_id, payload.selected_chapter_id)
  materialization = LongInputMaterialization(titles=[], original_length=0)
  session_changes: list[str] = []

  try:
    materialization = await asyncio.to_thread(_materialize_long_agent_inputs, settings, payload)
    session_changes = _long_input_materialization_changes(materialization)
    if materialization.titles:
      payload = _payload_with_auto_material_references(payload, materialization)
      runtime = _build_runtime_state(settings, payload.project_id, payload.selected_chapter_id)
      if materialization.project_detail is not None:
        for chunk in emitter.project_updated(materialization.project_detail.model_dump(mode="json")):
          yield chunk
  except Exception as error:
    for chunk in emitter.session_error(f"长文本自动导入资料库失败：{error}"):
      yield chunk
    for chunk in emitter.session_finished("failed"):
      yield chunk
    return

  if payload.approved_plan is not None:
    approved_plan = payload.approved_plan
    if materialization.titles:
      approved_plan = _plan_with_reference_note(approved_plan, payload.reference_filenames)
    try:
      async for item in _execute_plan(settings, payload, approved_plan, task_id):
        if isinstance(item, AgentChatResult):
          item = _result_with_session_changes(
            item,
            session_changes,
            runtime.detail if materialization.titles else None,
          )
        for chunk in _iter_execution_event_chunks(emitter, item):
          yield chunk
    except AgentSessionInterrupted:
      for chunk in emitter.session_finished("cancelled"):
        yield chunk
      return
    except Exception as error:
      for chunk in emitter.session_error(str(error)):
        yield chunk
      for chunk in emitter.session_finished("failed"):
        yield chunk
      return

    for chunk in emitter.session_finished("completed"):
      yield chunk
    return

  latest_user_message = next(
    (item for item in reversed(payload.messages) if item.role == "user" and item.content.strip()),
    None,
  )
  if latest_user_message is None:
    result_payload = AgentChatResult(
      task_id=task_id,
      mode="reply",
      reply="请说明当前要处理什么。可以讨论方向、完善架构、判断章节，或者直接续写。",
      state=_state_summary(runtime),
      thread_id=payload.thread_id,
      task_pack_kind="",
    )
    for chunk in emitter.session_result(result_payload.model_dump(mode="json")):
      yield chunk
    for chunk in emitter.session_finished("completed"):
      yield chunk
    return

  try:
    for chunk in emitter.action_started(
      step=1,
      total=2,
      action_kind="session_prepare",
      label="读取当前项目状态",
      task_pack_kind="",
    ):
      yield chunk
    instruction = _append_reference_note(latest_user_message.content, payload.reference_filenames)
    instruction = _append_thread_context_note(instruction, payload)
    decision = await asyncio.to_thread(
      _resolve_decision,
      settings,
      runtime,
      payload.messages,
      payload.reference_filenames,
    )
    for chunk in emitter.action_result(
      step=1,
      total=2,
      action_kind="session_prepare",
      label="读取当前项目状态",
      task_pack_kind="",
      changes=session_changes,
    ):
      yield chunk
    for chunk in emitter.action_started(
      step=2,
      total=2,
      action_kind="session_plan",
      label="生成当前执行计划",
      task_pack_kind="",
    ):
      yield chunk
    plan, reply = await asyncio.to_thread(_resolve_plan, settings, runtime, instruction, payload)
    for chunk in emitter.action_result(
      step=2,
      total=2,
      action_kind="session_plan",
      label="生成当前执行计划",
      task_pack_kind="",
    ):
      yield chunk
  except Exception as error:
    for chunk in emitter.session_error(str(error)):
      yield chunk
    for chunk in emitter.session_finished("failed"):
      yield chunk
    return

  if plan is not None and plan.requires_confirmation:
    target_chapter = None
    if plan.actions:
      action = next((item for item in plan.actions if item.chapter_id), None)
      if action is not None:
        target_chapter = next((item for item in runtime.detail.chapters if item.id == action.chapter_id), None)
    result_payload = AgentChatResult(
      task_id=task_id,
      mode="plan",
      reply=_plan_reply(runtime, plan, target_chapter),
      state=_state_summary(runtime),
      thread_id=payload.thread_id,
      task_pack_kind=_plan_task_pack_kind(plan),
      plan=plan,
      changes=session_changes,
      project_detail=runtime.detail if materialization.titles else None,
      event_blocks=[
        AgentEventBlock(
          event_type="plan_generated",
          title=plan.title,
          status="pending",
          summary=plan.summary,
        )
      ],
    )
    for chunk in emitter.plan_generated(
      plan=result_payload.plan.model_dump(mode="json") if result_payload.plan else None,
      reply=result_payload.reply,
      task_pack_kind=result_payload.task_pack_kind,
    ):
      yield chunk
    for chunk in emitter.plan_confirm_required(plan.id):
      yield chunk
    for chunk in emitter.session_result(result_payload.model_dump(mode="json")):
      yield chunk
    for chunk in emitter.session_finished("completed"):
      yield chunk
    return

  if reply is not None:
    result_payload = AgentChatResult(
      task_id=task_id,
      mode="reply",
      reply=reply,
      state=_state_summary(runtime),
      thread_id=payload.thread_id,
      task_pack_kind="",
      changes=session_changes,
      project_detail=runtime.detail if materialization.titles else None,
    )
    for chunk in emitter.session_result(result_payload.model_dump(mode="json")):
      yield chunk
    for chunk in emitter.session_finished("completed"):
      yield chunk
    return

  direct_plan = plan or AgentPlan(
    id=f"plan-{uuid4().hex[:10]}",
    title="继续讨论",
    summary="继续讨论项目方向",
    requires_confirmation=False,
    steps=["读取当前项目上下文", "给出这一轮判断和建议"],
    actions=[
      AgentPlanAction(
        kind="brainstorm",
        label="继续讨论项目方向",
        task_pack_kind="",
        instruction=instruction,
        skill_ids=_resolve_agent_skill_ids(settings, payload),
      )
    ],
  )

  try:
    async for item in _execute_plan(settings, payload, direct_plan, task_id):
      if isinstance(item, AgentChatResult):
        item = _result_with_session_changes(
          item,
          session_changes,
          runtime.detail if materialization.titles else None,
        )
      for chunk in _iter_execution_event_chunks(emitter, item):
        yield chunk
  except AgentSessionInterrupted:
    for chunk in emitter.session_finished("cancelled"):
      yield chunk
    return
  except Exception as error:
    for chunk in emitter.session_error(str(error)):
      yield chunk
    for chunk in emitter.session_finished("failed"):
      yield chunk
    return

  for chunk in emitter.session_finished("completed"):
    yield chunk
