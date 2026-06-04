from __future__ import annotations

import fnmatch
import hashlib
import json
import posixpath
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape as html_unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from pydantic import ValidationError

from novel_backend.models import ObsidianGraphIssue, ObsidianNoteSummary, ObsidianVaultConfig, ObsidianVaultState
from novel_backend.utils.jsonfile import atomic_write_json, read_json


_APP_STATE_DIRNAME = ".gaoxia"
_CONFIG_FILENAME = "obsidian.json"
_SYNC_FILENAME = "obsidian_sync.json"
_DEFAULT_INCLUDE_PATTERNS = ["**/*.md", "**/*.canvas"]
_FRONTMATTER_BOUNDARY = "---"
_INLINE_TAG_PATTERN = re.compile(r"(?<![\w/／])#([\w\-/／+~～〜—–―－−‒‐‑\u4e00-\u9fff]+)")
_WIKI_LINK_WITH_EMBED_PATTERN = re.compile(r"!?\[\[([^\]|#^]+)(?:[#^][^\]|]+)?(?:\|[^\]]+)?\]\]")
_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]\n]*\]\([^)\n]+\)")
_HTML_MEDIA_BLOCK_PATTERN = re.compile(
  r"<\s*(audio|video|picture|object|iframe)\b[^>]*>.*?<\s*/\s*\1\s*>",
  flags=re.IGNORECASE | re.DOTALL,
)
_HTML_DELETED_BLOCK_PATTERN = re.compile(
  r"<\s*(del|s|strike)\b[^>]*>.*?<\s*/\s*\1\s*>",
  flags=re.IGNORECASE | re.DOTALL,
)
_HTML_DETAILS_BLOCK_PATTERN = re.compile(
  r"<\s*details\b(?P<attrs>[^>]*)>(?P<body>.*?)<\s*/\s*details\s*>",
  flags=re.IGNORECASE | re.DOTALL,
)
_HTML_SUMMARY_BLOCK_PATTERN = re.compile(
  r"<\s*summary\b[^>]*>(?P<label>.*?)<\s*/\s*summary\s*>",
  flags=re.IGNORECASE | re.DOTALL,
)
_HTML_MEDIA_SINGLE_PATTERN = re.compile(r"<\s*(?:img|source|track|embed)\b[^>]*>", flags=re.IGNORECASE)
_HTML_ANCHOR_PATTERN = re.compile(r"<\s*a\b(?P<attrs>[^>]*)>(?P<label>.*?)<\s*/\s*a\s*>", flags=re.IGNORECASE | re.DOTALL)
_HTML_ATTRIBUTE_PATTERN = re.compile(r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))""")
_MARKDOWN_FOOTNOTE_REFERENCE_PATTERN = re.compile(r"\[\^[^\]\n]+\]")
_MARKDOWN_FOOTNOTE_DEFINITION_PATTERN = re.compile(r"^\s{0,3}\[\^[^\]\n]+\]:")
_FENCED_CODE_BOUNDARY_PATTERN = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_OBSIDIAN_CALLOUT_PATTERN = re.compile(r"^\s*\[!([^\]\s]+)\]", flags=re.IGNORECASE)
_HIDDEN_OBSIDIAN_CALLOUT_TYPES = {
  "draft",
  "future",
  "hidden",
  "hide",
  "ignore",
  "no-ai",
  "private",
  "secret",
  "spoiler",
  "todo",
  "剧透",
  "未来",
  "隐藏",
  "私密",
  "秘密",
  "草稿",
  "待定",
  "勿用",
  "不引用",
}
_KNOWLEDGE_LINK_SUFFIXES = {".md", ".canvas"}
_MARKDOWN_ESCAPABLE_CHARS = set("\\`*_{}[]()#+-.!\"#$%&'/:;<=>?@^|~ ")
_PATH_CHAPTER_RANGE_PATTERN = re.compile(
  r"第\s*[0-9０-９零〇一二两三四五六七八九十百千]+\s*章\s*[-~～〜—–―－−‒‐‑至到]\s*第?\s*[0-9０-９零〇一二两三四五六七八九十百千]+\s*章"
)
_PATH_CHAPTER_PATTERN = re.compile(
  r"第\s*[0-9０-９零〇一二两三四五六七八九十百千]+\s*(?:[-~～〜—–―－−‒‐‑至到]\s*[0-9０-９零〇一二两三四五六七八九十百千]+)?\s*章"
)
_PATH_ENGLISH_CHAPTER_PATTERN = re.compile(
  r"(?i)(?:^|[^a-z0-9])(?:chapters?|chap|ch)\s*[-_\s]*([0-9０-９]+)(?:\s*[-~～〜—–―－−‒‐‑至到]\s*([0-9０-９]+))?(?:$|[^a-z0-9])"
)
_PLAIN_CHAPTER_TAG_PATTERN = re.compile(
  r"^(?:第)?([0-9０-９零〇一二两三四五六七八九十百千]+)(?:章)?"
  r"(?:[-~～〜—–―－−‒‐‑至到](?:第)?([0-9０-９零〇一二两三四五六七八九十百千]+)(?:章)?)?(?:章)?$"
)
_ENGLISH_CHAPTER_TAG_PATTERN = re.compile(r"(?i)^(?:chapter|chap|ch)[-_\s]*([0-9０-９]+)(?:[-~～〜—–―－−‒‐‑至到_\s]+([0-9０-９]+))?$")
_OPEN_ENDED_CHAPTER_TAG_PATTERN = re.compile(
  r"^(?:第)?([0-9０-９零〇一二两三四五六七八九十百千]+)(?:章)?(?:\+|起|起始|开始|以后|之后|及以后|往后)$"
)
_OPEN_ENDED_ENGLISH_CHAPTER_TAG_PATTERN = re.compile(r"(?i)^(?:chapter|chap|ch)[-_\s]*([0-9０-９]+)\+$")
_OPEN_ENDED_CHAPTER_VALUE_PATTERN = re.compile(
  r"(?:^|[^\w])(?:第\s*)?([0-9０-９零〇一二两三四五六七八九十百千]+)\s*(?:章)?\s*"
  r"(?:\+|起(?:可用|使用|引用)?|起始|开始(?:可用|使用|引用)?|以后(?:可用|使用|引用)?|之后(?:可用|使用|引用)?|及以后(?:可用|使用|引用)?|往后(?:可用|使用|引用)?)(?:$|[^\w])",
  flags=re.IGNORECASE,
)
_OPEN_ENDED_ENGLISH_CHAPTER_VALUE_PATTERN = re.compile(
  r"(?i)(?:^|[^a-z0-9])(?:chapter|chap|ch)\s*[-_\s]*([0-9０-９]+)\s*\+(?:$|[^a-z0-9])"
)
_REVEAL_AFTER_TAG_PATTERN = re.compile(
  r"^(?:第)?([0-9０-９零〇一二两三四五六七八九十百千]+)(?:章)?(?:后|之后)(?:可用|使用|启用|揭示|公开)$"
)
_URL_SCHEME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
_EXTERNAL_URL_PATTERN = re.compile(r"https?://[^\s<>\]\)\"'“”‘’]+", flags=re.IGNORECASE)
_CONSTRAINT_VALUE_SPLIT_PATTERN = re.compile(r"[,，、;；/|]")
_INLINE_PROPERTY_LINE_PATTERN = re.compile(
  r"^\s*(?:[-*+>]|\d+[.)]|[（(]?\d+[）)])?\s*(?:\[[ xX!?>/<*\-+~_=.]\]\s*)?"
  r"([^\[\](){}:\n]{1,80})::\s*(.+?)\s*$"
)
_INLINE_PROPERTY_BRACKET_PATTERN = re.compile(
  r"\[([^\[\](){}:\n]{1,80})::\s*((?:\[\[[^\]]+\]\]|[^\]\n])+?)\]"
)
_INLINE_PROPERTY_PAREN_PATTERN = re.compile(
  r"\(([^\[\](){}:\n]{1,80})::\s*((?:\[\[[^\]]+\]\]|[^)\n])+?)\)"
)
_FULL_WIDTH_DIGIT_TABLE = str.maketrans("０１２３４５６７８９", "0123456789")
_CHAPTER_NUMBER_TOKEN_PATTERN = re.compile(r"[0-9０-９]+|[零〇一二两三四五六七八九十百千]+")
_QUERY_STOP_TERMS = {
  "一个",
  "一些",
  "一下",
  "这一",
  "这个",
  "这里",
  "他们",
  "她们",
  "我们",
  "你们",
  "没有",
  "不能",
  "不要",
  "继续",
  "续写",
  "生成",
  "正文",
  "章节",
  "本章",
  "当前",
  "当前章",
  "目标章",
  "下章",
  "下一",
  "下一章",
  "上一",
  "上一章",
  "第一",
  "第二",
  "第三",
  "第四",
  "第五",
  "第六",
  "第七",
  "第八",
  "第九",
  "第十",
}
_REQUIRED_CONSTRAINT_LABELS = (
  "required_phrases",
  "required_terms",
  "must_include",
  "must",
  "必须出现",
  "必须包含",
  "必需出现",
  "必需包含",
  "写作必须",
  "必须写到",
)
_FORBIDDEN_CONSTRAINT_LABELS = (
  "forbidden_phrases",
  "forbidden_terms",
  "must_not_include",
  "must_not",
  "forbidden",
  "禁止出现",
  "禁止包含",
  "不要出现",
  "不可出现",
  "不允许出现",
  "禁用",
)
_AI_USABLE_LABELS = (
  "usable_by_ai",
  "ai_usable",
  "ai",
  "AI",
  "ai_available",
  "available_to_ai",
  "allow_ai",
  "ai_allowed",
  "可供AI使用",
  "AI可用",
  "可供模型使用",
  "模型可用",
  "写作可用",
  "可用于写作",
  "可被AI读取",
  "AI可读",
)
_AI_BLOCKED_LABELS = (
  "no_ai",
  "not_for_ai",
  "exclude_from_ai",
  "excluded_from_ai",
  "ai_exclude",
  "ai_ignore",
  "ignore_ai",
  "AI不可用",
  "不供AI使用",
  "不允许AI使用",
  "不要给AI",
  "不让AI读取",
  "模型不可用",
  "写作不可用",
  "勿用AI",
  "AI勿用",
)
_AI_USABLE_TAG_LABELS = (
  "usable_by_ai",
  "ai_usable",
  "ai_available",
  "available_to_ai",
  "allow_ai",
  "ai_allowed",
  "AI可用",
  "AI可读",
  "可供AI使用",
  "可供模型使用",
  "模型可用",
  "写作可用",
)
_AI_BLOCKED_TAG_LABELS = (
  "no_ai",
  "not_for_ai",
  "exclude_from_ai",
  "excluded_from_ai",
  "ai_exclude",
  "ai_ignore",
  "ignore_ai",
  "AI不可用",
  "不供AI使用",
  "不允许AI使用",
  "不要给AI",
  "不让AI读取",
  "模型不可用",
  "写作不可用",
  "勿用AI",
  "AI勿用",
)
_STATUS_CANONICAL_TAG_LABELS = (
  "canonical",
  "official",
  "active",
  "published",
  "ready",
  "final",
  "usable",
  "正式",
  "正式设定",
  "已确认",
  "已发布",
  "可用",
  "公开",
  "定稿",
)
_STATUS_DRAFT_TAG_LABELS = (
  "draft",
  "wip",
  "todo",
  "草稿",
  "待定",
  "未定稿",
)
_STATUS_PRIVATE_TAG_LABELS = (
  "private",
  "hidden",
  "hide",
  "secret",
  "私密",
  "私人",
  "隐藏",
  "秘密",
)
_STATUS_DEPRECATED_TAG_LABELS = (
  "deprecated",
  "discarded",
  "archive",
  "archived",
  "废案",
  "弃用",
  "作废",
  "归档",
  "不引用",
  "勿用",
)
_STATUS_CANONICAL_DIRECTORY_LABELS = (
  "canon",
  "canonical",
  "official",
  "published",
  "ready",
  "final",
  "正式",
  "正式设定",
  "已确认",
  "已发布",
  "可用",
  "定稿",
)
_STATUS_DRAFT_DIRECTORY_LABELS = (
  "drafts",
  "draft",
  "wip",
  "草稿",
  "草稿箱",
  "未定稿",
  "待定",
)
_STATUS_PRIVATE_DIRECTORY_LABELS = (
  "private",
  "hidden",
  "secret",
  "私密",
  "隐藏",
  "秘密",
)
_STATUS_DEPRECATED_DIRECTORY_LABELS = (
  "deprecated",
  "discarded",
  "废案",
  "弃用",
  "作废",
)
_CHAPTER_RANGE_LABELS = (
  "chapter_range",
  "chapters",
  "chapter",
  "chapter_scope",
  "available_chapters",
  "usable_chapters",
  "适用章节",
  "章节范围",
  "可用章节",
  "使用章节",
  "写作章节",
  "可引用章节",
)
_CHAPTER_RANGE_TAG_LABELS = (
  "chapter",
  "chapters",
  "chapter-range",
  "chapter_range",
  "chapter-scope",
  "chapter_scope",
  "chapter-contract",
  "chapter_contract",
  "chaptercontract",
  "chapter-plan",
  "chapter_plan",
  "chapterplan",
  "chapter-outline",
  "chapter_outline",
  "chapteroutline",
  "scene-plan",
  "scene_plan",
  "sceneplan",
  "scene-card",
  "scene_card",
  "scenecard",
  "beat-sheet",
  "beat_sheet",
  "beatsheet",
  "章节",
  "章节范围",
  "适用章节",
  "可用章节",
  "章节合同",
  "写作合同",
  "章节计划",
  "章节大纲",
  "章节规划",
  "本章计划",
  "场景计划",
  "场景卡",
  "分场",
  "节拍表",
)
_CHAPTER_START_LABELS = (
  "chapter_start",
  "start_chapter",
  "from_chapter",
  "available_from_chapter",
  "reveal_chapter",
  "first_reveal_chapter",
  "出场章节",
  "首次出场章节",
  "起始章节",
  "开始章节",
  "可用起始章节",
)
_CHAPTER_END_LABELS = (
  "chapter_end",
  "end_chapter",
  "to_chapter",
  "until_chapter",
  "available_until_chapter",
  "截止章节",
  "结束章节",
  "可用截止章节",
)
_REVEAL_AFTER_CHAPTER_LABELS = (
  "reveal_after_chapter",
  "available_after_chapter",
  "usable_after_chapter",
  "spoiler_after_chapter",
  "揭示后章节",
  "第几章后可用",
  "可用章节后",
  "章节后可用",
  "剧透保护到",
  "剧透到",
)
_REVEAL_AFTER_CHAPTER_TAG_LABELS = (
  "spoiler",
  "spoiler-after",
  "spoiler_after",
  "reveal-after",
  "reveal_after",
  "available-after",
  "available_after",
  "剧透",
  "剧透后",
  "剧透到",
  "剧透保护",
  "章后可用",
  "可用章节后",
)
_OBSIDIAN_URI_TARGET_QUERY_KEYS = ("file", "filepath", "filename", "path")
_OBSIDIAN_URI_HEADING_QUERY_KEYS = ("heading", "header", "section")
_OBSIDIAN_URI_BLOCK_QUERY_KEYS = ("block", "blockid", "block_id")
_FRONTMATTER_LINK_LABELS = (
  "links",
  "link",
  "wiki_links",
  "source_notes",
  "source_note",
  "source_note_paths",
  "depends_on",
  "dependency",
  "dependencies",
  "blocked_by",
  "foreshadows",
  "foreshadow",
  "payoffs",
  "payoff",
  "reveals",
  "reveal",
  "related_notes",
  "related_note",
  "related_characters",
  "related_character",
  "related_locations",
  "related_location",
  "related_places",
  "related_place",
  "related_props",
  "related_prop",
  "related_items",
  "related_item",
  "related_organizations",
  "related_organization",
  "related_orgs",
  "related_org",
  "characters",
  "character",
  "locations",
  "location",
  "places",
  "place",
  "props",
  "prop",
  "items",
  "item",
  "organizations",
  "organization",
  "orgs",
  "org",
  "人物",
  "相关人物",
  "地点",
  "相关地点",
  "道具",
  "相关道具",
  "组织",
  "相关组织",
  "来源笔记",
  "关联笔记",
  "前置笔记",
  "依赖笔记",
  "伏笔",
  "兑现",
  "揭示",
)
_FRONTMATTER_RELATION_DISPLAY_LABELS = {
  "links": "关联",
  "link": "关联",
  "wiki_links": "关联",
  "source_notes": "来源笔记",
  "source_note": "来源笔记",
  "source_note_paths": "来源笔记",
  "depends_on": "依赖",
  "dependency": "依赖",
  "dependencies": "依赖",
  "blocked_by": "依赖",
  "foreshadows": "伏笔",
  "foreshadow": "伏笔",
  "payoffs": "兑现",
  "payoff": "兑现",
  "reveals": "揭示",
  "reveal": "揭示",
  "evidence_sources": "证据来源",
  "evidence_source": "证据来源",
  "evidence": "证据来源",
  "related_notes": "关联笔记",
  "related_note": "关联笔记",
  "related_characters": "相关人物",
  "related_character": "相关人物",
  "related_locations": "相关地点",
  "related_location": "相关地点",
  "related_places": "相关地点",
  "related_place": "相关地点",
  "related_props": "相关道具",
  "related_prop": "相关道具",
  "related_items": "相关道具",
  "related_item": "相关道具",
  "related_organizations": "相关组织",
  "related_organization": "相关组织",
  "related_orgs": "相关组织",
  "related_org": "相关组织",
  "characters": "人物",
  "character": "人物",
  "locations": "地点",
  "location": "地点",
  "places": "地点",
  "place": "地点",
  "props": "道具",
  "prop": "道具",
  "items": "道具",
  "item": "道具",
  "organizations": "组织",
  "organization": "组织",
  "orgs": "组织",
  "org": "组织",
  "人物": "人物",
  "相关人物": "相关人物",
  "地点": "地点",
  "相关地点": "相关地点",
  "道具": "道具",
  "相关道具": "相关道具",
  "组织": "组织",
  "相关组织": "相关组织",
  "来源笔记": "来源笔记",
  "关联笔记": "关联笔记",
  "前置笔记": "依赖",
  "依赖笔记": "依赖",
  "伏笔": "伏笔",
  "兑现": "兑现",
  "揭示": "揭示",
  "证据来源": "证据来源",
  "证据": "证据来源",
}
_FRONTMATTER_RELATION_LABEL_BY_KEY = {
  re.sub(r"[\s\-]+", "_", str(key or "").strip().lower()): label
  for key, label in _FRONTMATTER_RELATION_DISPLAY_LABELS.items()
}
_SUMMARY_LABELS = (
  "summary",
  "description",
  "desc",
  "abstract",
  "简介",
  "摘要",
  "说明",
  "概述",
)
_TITLE_LABELS = ("title", "标题", "name", "名称")
_KEYWORD_LABELS = (
  "keywords",
  "keyword",
  "search_terms",
  "searchterms",
  "terms",
  "检索词",
  "检索关键词",
  "关键词",
  "关键字",
  "索引词",
)
_CONTEXT_BODY_PROPERTY_GROUPS = (
  ("章节目标", ("objective", "chapter_objective", "chapter_goal", "goal", "goals", "目标", "章节目标", "合同目标", "写作目标")),
  ("必须完成的节拍", ("required_beats", "required_beat", "beats", "beat", "scene_beats", "scenes", "scene_list", "必须完成的节拍", "必须节拍", "节拍", "场景", "场景列表")),
  ("必须推进的债务", ("debts_to_advance", "debt_to_advance", "advance_debts", "必须推进的债务", "推进债务")),
  ("不能提前揭开的债务", ("debts_to_protect", "debt_to_protect", "protect_debts", "protected_debts", "不能提前揭开的债务", "保护债务")),
  ("人物检查", ("character_checks", "character_check", "character_constraints", "人物检查", "人物约束")),
  ("文风检查", ("style_checks", "style_check", "voice_checks", "tone_checks", "文风检查", "风格检查", "语气检查")),
  ("禁止动作", ("forbidden_moves", "forbidden_move", "forbidden_actions", "forbidden_action", "avoid", "avoidance", "禁止动作", "禁写动作", "避免", "不要写")),
  ("验收项", ("acceptance_checks", "acceptance_check", "checks", "验收项", "验收检查")),
  ("证据来源", ("evidence_sources", "evidence_source", "evidence", "证据来源", "证据")),
  ("风险提示", ("risk_notes", "risk_note", "risks", "risk", "风险提示", "风险")),
)
_DEBT_CONTEXT_BODY_PROPERTY_GROUPS = (
  ("债务内容", ("debt_content", "debt_summary", "debt_detail", "content", "promise", "foreshadow", "plot_debt", "narrative_debt", "剧情债务", "债务内容", "线索内容", "伏笔内容", "承诺内容")),
  ("债务类型", ("debt_kind", "debt_type", "kind", "债务类型", "类型")),
  ("债务状态", ("debt_status", "narrative_status", "payoff_status", "处理状态", "债务状态", "兑现状态")),
  ("风险等级", ("risk_level", "risk_priority", "priority", "风险等级", "风险", "优先级")),
  ("预计处理区间", ("expected_payoff_range", "payoff_range", "planned_payoff", "payoff_chapters", "预计处理区间", "兑现区间", "处理区间")),
  ("下一步动作", ("next_required_action", "next_action", "required_next_action", "下一步动作", "下一步要求", "后续动作", "后续要求")),
  ("相关人物", ("related_characters", "related_character", "characters", "character", "相关人物", "人物", "角色")),
)
_ARC_CONTEXT_BODY_PROPERTY_GROUPS = (
  ("人物", ("character", "character_name", "name", "related_character", "related_characters", "人物", "角色", "角色名", "相关人物")),
  ("弧线阶段", ("arc_phase", "phase", "stage", "人物阶段", "弧线阶段", "阶段")),
  ("当前状态", ("current_state", "character_state", "state", "当前状态", "人物状态", "角色状态")),
  ("未解压力", ("unresolved_pressure", "pressure", "tension", "人物压力", "未解压力", "关系压力")),
  ("下一次检查", ("required_next_check", "next_check", "next_required_check", "下一次检查", "后续检查", "下一步检查")),
)
_CHAPTER_NOTE_CONTEXT_BODY_PROPERTY_GROUPS = (
  ("章节标题", ("chapter_title", "chapter_name", "章节标题", "章节名", "标题")),
  ("章节摘要", ("chapter_summary", "chapter_recap", "chapter_brief", "recap", "正文摘要", "章节摘要", "章节回顾")),
  ("关键事件", ("chapter_events", "chapter_event", "key_events", "key_event", "events", "event", "plot_events", "剧情事件", "关键事件", "本章事件")),
  ("状态变化", ("state_changes", "state_change", "continuity_changes", "character_changes", "world_changes", "状态变化", "连续性变化", "人物变化", "世界变化")),
  ("章节交接", ("handoff_to_next", "next_handoff", "next_chapter_handoff", "handoff", "next_chapter", "章节交接", "下一章交接", "后续交接")),
  ("正文摘录", ("chapter_excerpt", "chapter_excerpts", "excerpt", "excerpts", "body_excerpt", "正文摘录", "章节正文摘录")),
  ("已满足的 Obsidian 必写项", ("obsidian_required_satisfied", "required_satisfied", "satisfied_requirements", "已满足的Obsidian必写项", "已满足必写项")),
  ("未完成的 Obsidian 必写项", ("obsidian_required_missing", "required_missing", "missing_requirements", "未完成的Obsidian必写项", "未完成必写项")),
  ("已触犯的 Obsidian 禁写项", ("obsidian_forbidden_violations", "forbidden_violations", "violated_forbidden", "已触犯的Obsidian禁写项", "已触犯禁写项")),
)
_STYLE_CONTEXT_BODY_PROPERTY_GROUPS = (
  ("文风规则", ("style_rule", "style_rules", "voice_rule", "voice_rules", "tone_rule", "tone_rules", "writing_rule", "writing_rules", "rule", "rules", "guidance", "instruction", "instructions", "文风规则", "风格规则", "语气规则", "写作规则", "规则", "指导")),
  ("句式节奏", ("sentence_rhythm", "rhythm", "sentence_pattern", "sentence_patterns", "prose_rhythm", "句式节奏", "句式", "节奏", "行文节奏")),
  ("意象与感官", ("imagery", "image_system", "sensory", "sensory_detail", "motifs", "motif", "意象", "意象系统", "感官", "感官细节")),
  ("对白规则", ("dialogue_rule", "dialogue_rules", "dialogue", "dialog", "对白规则", "对白", "对话规则", "对话")),
  ("禁用写法", ("avoid_style", "avoid", "avoidance", "forbidden_style", "forbidden_moves", "dont", "do_not", "禁用写法", "避免", "不要写", "禁止写法")),
  ("示例", ("examples", "example", "sample_lines", "sample_line", "样例", "示例", "例句", "范例")),
  ("适用场景", ("applies_to", "usage", "use_when", "task_scope", "适用场景", "适用任务", "适用范围")),
)
_XP_CONTEXT_BODY_PROPERTY_GROUPS = (
  ("XP 规则", ("xp_rule", "xp_rules", "experience_rule", "experience_rules", "writing_xp", "rule", "rules", "guidance", "instruction", "instructions", "经验规则", "写作经验", "XP规则", "XP 规则", "规则", "指导")),
  ("生成前检查", ("before_writing", "precheck", "pre_checks", "pre_generation_checks", "生成前检查", "写前检查", "前置检查")),
  ("生成后检查", ("after_writing", "postcheck", "post_checks", "review_checks", "revision_checks", "生成后检查", "写后检查", "复查项", "检查项")),
  ("推进方法", ("method", "methods", "workflow", "steps", "beats", "technique", "推进方法", "执行步骤", "方法", "步骤", "技巧")),
  ("禁用做法", ("avoid_xp", "avoid", "avoidance", "forbidden_moves", "dont", "do_not", "禁用做法", "避免", "不要做", "禁止做法")),
  ("示例", ("examples", "example", "sample_lines", "sample_line", "样例", "示例", "例句", "范例")),
)
_NESTED_CONTEXT_LABELS = {
  "goal": "目标",
  "chapter_goal": "目标",
  "objective": "目标",
  "purpose": "目的",
  "conflict": "冲突",
  "pressure": "压力",
  "turn": "转折",
  "turning_point": "转折",
  "payoff": "兑现",
  "reveal": "揭示",
  "action": "动作",
  "required_action": "动作",
  "next_action": "动作",
  "check": "检查",
  "acceptance": "验收",
  "risk": "风险",
  "risk_note": "风险",
  "reason": "理由",
  "evidence": "证据来源",
  "evidence_source": "证据来源",
  "evidence_sources": "证据来源",
  "source_note": "来源笔记",
  "source_notes": "来源笔记",
  "related_character": "相关人物",
  "related_characters": "相关人物",
  "character": "人物",
  "characters": "人物",
  "location": "地点",
  "locations": "地点",
  "prop": "道具",
  "props": "道具",
  "organization": "组织",
  "organizations": "组织",
  "debt": "债务",
  "debt_content": "债务内容",
  "debt_status": "债务状态",
  "phase": "阶段",
  "current_state": "当前状态",
}
_CONTEXT_DEBT_NOTE_LABELS = {
  "debt",
  "debts",
  "plotdebt",
  "plotdebts",
  "storydebt",
  "storydebts",
  "narrativedebt",
  "narrativedebts",
  "foreshadow",
  "foreshadows",
  "promise",
  "promises",
  "payoff",
  "payoffs",
  "debts",
  "plotdebts",
  "剧情债务",
  "叙事债务",
  "线索债务",
  "伏笔",
  "承诺",
  "兑现",
}
_CONTEXT_ARC_NOTE_LABELS = {
  "arc",
  "arcs",
  "characterarc",
  "characterarcs",
  "characterstate",
  "characterstates",
  "characterprogress",
  "characterprogression",
  "characterarcs",
  "人物弧线",
  "人物状态",
  "人物进展",
  "角色弧线",
  "角色状态",
}
_CONTEXT_CHAPTER_NOTE_LABELS = {
  "chapter",
  "chapters",
  "chapternote",
  "chapternotes",
  "chaptersummary",
  "chapterarchive",
  "authorarchive",
  "chapterrecap",
  "章节",
  "章节笔记",
  "章节档案",
  "章节摘要",
  "章节回顾",
  "作者档案",
}
_CONTEXT_STYLE_NOTE_LABELS = {
  "style",
  "stylerule",
  "stylerules",
  "styleguide",
  "styleguides",
  "voice",
  "tone",
  "authorstyle",
  "writingrule",
  "writingrules",
  "writingguide",
  "writingguides",
  "writingpreference",
  "writingpreferences",
  "文风",
  "文风规则",
  "风格",
  "风格规则",
  "语气",
  "写作规则",
  "写作偏好",
  "作者偏好",
}
_CONTEXT_XP_NOTE_LABELS = {
  "xp",
  "xprule",
  "xprules",
  "experience",
  "experiences",
  "writingxp",
  "xp规则",
  "经验",
  "经验规则",
  "写作经验",
}
_INFERRED_NOTE_TYPE_GROUPS = (
  ("chapter_contract", ("chaptercontract", "chaptercontracts", "contract", "contracts", "章节合同", "写作合同", "合同")),
  ("chapter_plan", ("chapterplan", "chapterplans", "chapteroutline", "chapteroutlines", "sceneplan", "sceneplans", "scenecard", "scenecards", "beatsheet", "beatsheets", "plan", "plans", "scenes", "outline", "outlines", "章节计划", "章节大纲", "章节规划", "本章计划", "场景计划", "场景卡", "分场", "节拍表", "计划")),
  ("chapter_note", ("chapternote", "chapternotes", "chaptersummary", "chaptersummaries", "chapterarchive", "chapterarchives", "authorarchive", "authorarchives", "chapterrecap", "chapterrecaps", "chapternotes", "章节笔记", "章节档案", "章节摘要", "章节回顾", "作者档案")),
  ("plot_debt", ("plotdebt", "plotdebts", "narrativedebt", "narrativedebts", "storydebt", "storydebts", "debt", "debts", "foreshadow", "foreshadows", "promise", "promises", "payoff", "payoffs", "剧情债务", "叙事债务", "线索债务", "伏笔", "承诺", "兑现")),
  ("character_arc", ("characterarc", "characterarcs", "characterstate", "characterstates", "characterprogress", "characterprogression", "arc", "arcs", "人物弧线", "人物状态", "人物进展", "角色弧线", "角色状态")),
  ("style_rule", ("stylerule", "stylerules", "styleguide", "styleguides", "style", "voice", "tone", "authorstyle", "writingrule", "writingrules", "writingguide", "writingguides", "writingpreference", "writingpreferences", "文风", "文风规则", "风格", "风格规则", "语气", "写作规则", "写作偏好", "作者偏好")),
  ("xp_rule", ("xprule", "xprules", "writingxp", "experience", "experiences", "xp", "xp规则", "经验", "经验规则", "写作经验")),
  ("organization", ("organization", "organizations", "org", "orgs", "faction", "factions", "组织", "势力", "门派", "机构")),
  ("location", ("location", "locations", "place", "places", "setting", "settings", "地点", "场景", "地理", "地名")),
  ("prop", ("prop", "props", "item", "items", "artifact", "artifacts", "道具", "物件", "物品", "器物")),
  ("character", ("character", "characters", "person", "people", "cast", "人物", "角色", "人物卡", "角色卡")),
)
_SOURCE_ID_LABELS = (
  "source_ids",
  "source_id",
  "source ids",
  "source id",
  "来源ID",
  "来源编号",
)
_SOURCE_CHAPTER_LABELS = (
  "source_chapters",
  "source_chapter",
  "source_chapter_indexes",
  "source_chapter_index",
  "source_chapter_indices",
  "source chapters",
  "source chapter",
  "source chapter indexes",
  "source chapter index",
  "source chapter indices",
  "chapter_sources",
  "chapter_source",
  "chapter sources",
  "chapter source",
  "章节来源",
  "来源章节",
  "来源章",
  "来源章节号",
  "来源章号",
)
_EXTERNAL_LINK_LABELS = (
  "source_url",
  "source_urls",
  "source_link",
  "source_links",
  "reference_url",
  "reference_urls",
  "reference_link",
  "reference_links",
  "reference",
  "references",
  "citation",
  "citations",
  "source_reference",
  "source_references",
  "source",
  "sources",
  "research_url",
  "research_urls",
  "research_link",
  "research_links",
  "research",
  "research_sources",
  "external_url",
  "external_urls",
  "external_link",
  "external_links",
  "external_source",
  "external_sources",
  "url",
  "urls",
  "资料来源",
  "资料链接",
  "来源",
  "来源资料",
  "参考链接",
  "参考资料",
  "参考来源",
  "考据链接",
  "考据来源",
  "考据资料",
  "引用来源",
  "来源链接",
  "外部来源",
  "外部链接",
)
_SOURCE_CHAPTER_ID_PATTERN = re.compile(r"(?i)^(?:chapter|chap|ch)[-_\s]*([0-9０-９]+)$")
_SOURCE_CHINESE_CHAPTER_ID_PATTERN = re.compile(r"^第\s*([0-9０-９零〇一二两三四五六七八九十百千]+)\s*章$")
_CHINESE_CHAPTER_DIGITS = {
  "零": 0,
  "〇": 0,
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
_CHINESE_CHAPTER_UNITS = {
  "十": 10,
  "百": 100,
  "千": 1000,
}


@dataclass(slots=True)
class ObsidianNoteRecord:
  summary: ObsidianNoteSummary
  content: str
  body: str = ""


@dataclass(frozen=True, slots=True)
class _MarkdownLinkMatch:
  start: int
  end: int
  label: str
  destination: str
  raw: str


@dataclass(frozen=True, slots=True)
class _MarkdownReferenceDefinition:
  label: str
  target: str
  start: int
  end: int
  raw: str


@dataclass(frozen=True, slots=True)
class _MarkdownReferenceLinkMatch:
  start: int
  end: int
  label: str
  reference: str
  target: str
  raw: str


class _FrontmatterFlowItem(str):
  pass


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def _compact_text(text: str, limit: int = 180) -> str:
  normalized = " ".join(str(text or "").split())
  if len(normalized) <= limit:
    return normalized
  return f"{normalized[:limit].rstrip()}…"


def _strip_fenced_code_blocks(text: str) -> str:
  normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
  visible_lines: list[str] = []
  fence_char = ""
  fence_len = 0
  for line in normalized.split("\n"):
    match = _FENCED_CODE_BOUNDARY_PATTERN.match(line)
    if match:
      marker = match.group(1)
      marker_char = marker[0]
      marker_len = len(marker)
      if not fence_char:
        fence_char = marker_char
        fence_len = marker_len
        continue
      if marker_char == fence_char and marker_len >= fence_len:
        fence_char = ""
        fence_len = 0
        continue
    if fence_char:
      continue
    visible_lines.append(line)
  return "\n".join(visible_lines)


def _strip_markdown_inline_code(text: str) -> str:
  normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
  parts: list[str] = []
  index = 0
  while index < len(normalized):
    start = normalized.find("`", index)
    if start < 0:
      parts.append(normalized[index:])
      break
    if start > 0 and normalized[start - 1] == "\\":
      parts.append(normalized[index:start + 1])
      index = start + 1
      continue
    marker_len = 1
    while start + marker_len < len(normalized) and normalized[start + marker_len] == "`":
      marker_len += 1
    marker = "`" * marker_len
    search_from = start + marker_len
    end = -1
    while True:
      candidate = normalized.find(marker, search_from)
      if candidate < 0:
        break
      if candidate == 0 or normalized[candidate - 1] != "\\":
        end = candidate
        break
      search_from = candidate + marker_len
    if end < 0:
      parts.append(normalized[index:])
      break
    hidden = normalized[start:end + marker_len]
    parts.append(normalized[index:start])
    newline_count = hidden.count("\n")
    parts.append("\n" * newline_count if newline_count else " ")
    index = end + marker_len
  return "".join(parts)


def _strip_markdown_deleted_text(text: str) -> str:
  normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
  parts: list[str] = []
  index = 0
  while index < len(normalized):
    start = normalized.find("~~", index)
    if start < 0:
      parts.append(normalized[index:])
      break
    if start > 0 and normalized[start - 1] == "\\":
      parts.append(normalized[index:start + 2])
      index = start + 2
      continue
    search_from = start + 2
    end = -1
    while True:
      candidate = normalized.find("~~", search_from)
      if candidate < 0:
        break
      if candidate == 0 or normalized[candidate - 1] != "\\":
        end = candidate
        break
      search_from = candidate + 2
    if end < 0:
      parts.append(normalized[index:])
      break
    hidden = normalized[start:end + 2]
    parts.append(normalized[index:start])
    newline_count = hidden.count("\n")
    parts.append("\n" * newline_count if newline_count else " ")
    index = end + 2
  return "".join(parts)


def _strip_html_deleted_tags(text: str) -> str:
  def replacement(match: re.Match[str]) -> str:
    hidden = match.group(0)
    newline_count = hidden.count("\n")
    return "\n" * newline_count if newline_count else " "

  return _HTML_DELETED_BLOCK_PATTERN.sub(replacement, str(text or ""))


def _html_text_content(value: str) -> str:
  without_tags = re.sub(r"<[^>]+>", " ", str(value or ""))
  text = html_unescape(without_tags)
  return re.sub(r"\s+", " ", text).strip()


def _hidden_obsidian_marker_present(value: str) -> bool:
  if _explicit_hidden_obsidian_marker_present(value):
    return True
  normalized = _obsidian_callout_type(_html_text_content(value))
  return any(
    item and re.search(r"[\u4e00-\u9fff]", item) and item in normalized
    for item in _HIDDEN_OBSIDIAN_CALLOUT_TYPES
  )


def _explicit_hidden_obsidian_marker_present(value: str) -> bool:
  text = _html_text_content(value)
  normalized = _obsidian_callout_type(text)
  if normalized in _HIDDEN_OBSIDIAN_CALLOUT_TYPES:
    return True
  if "no-ai" in normalized:
    return True
  parts = [item for item in re.split(r"[^0-9a-z\u4e00-\u9fff]+", normalized) if item]
  return any(item in _HIDDEN_OBSIDIAN_CALLOUT_TYPES for item in parts)


def _html_details_summary_text(body: str) -> str:
  match = _HTML_SUMMARY_BLOCK_PATTERN.search(str(body or ""))
  if not match:
    return ""
  return _html_text_content(match.group("label") or "")


def _html_details_body_text(body: str) -> str:
  cleaned = _strip_markdown_inline_code(_strip_fenced_code_blocks(str(body or "")))
  cleaned = _strip_html_deleted_tags(_strip_markdown_deleted_text(cleaned))
  cleaned = _strip_obsidian_comments(cleaned)
  cleaned = _strip_markdown_html_comments(cleaned)
  cleaned = _strip_hidden_obsidian_callouts(cleaned)
  without_summary = _HTML_SUMMARY_BLOCK_PATTERN.sub(" ", cleaned)
  without_tags = re.sub(r"<[^>]+>", " ", without_summary)
  text = html_unescape(without_tags)
  return text.replace("\r\n", "\n").replace("\r", "\n")


def _html_details_body_blocks_ai(body: str, config: ObsidianVaultConfig | None = None) -> bool:
  text = _html_details_body_text(body)
  inline_fields = _inline_property_payload_from_visible_text(text)
  inline_tags = _frontmatter_tag_list(inline_fields, "tags", "tag", "标签")
  tags = _ordered_unique(inline_tags + [match.group(1).strip() for match in _INLINE_TAG_PATTERN.finditer(text)])
  usable_by_ai, usable_is_explicit = _frontmatter_ai_visibility(inline_fields)
  tag_usable_by_ai, tag_usable_is_explicit = _frontmatter_ai_visibility_from_tags(tags)
  if tag_usable_is_explicit:
    if not tag_usable_by_ai:
      return True
    if not usable_is_explicit:
      usable_by_ai, usable_is_explicit = True, True
  if usable_is_explicit and not usable_by_ai:
    return True
  if config is None:
    return False
  explicit_status = _frontmatter_string(inline_fields, "status", "状态")
  status = explicit_status or _status_from_property_flags(config, inline_fields)
  return bool(status and not _status_allowed(status, config))


def _strip_hidden_html_details(text: str, config: ObsidianVaultConfig | None = None) -> str:
  def replacement(match: re.Match[str]) -> str:
    details = match.group(0)
    attrs = match.group("attrs") or ""
    body = match.group("body") or ""
    summary = _html_details_summary_text(body)
    if not (
      _hidden_obsidian_marker_present(attrs)
      or _hidden_obsidian_marker_present(summary)
      or _html_details_body_blocks_ai(body, config)
    ):
      return details
    newline_count = details.count("\n")
    return "\n" * newline_count if newline_count else " "

  return _HTML_DETAILS_BLOCK_PATTERN.sub(replacement, str(text or ""))


def _strip_obsidian_comments(text: str) -> str:
  normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
  parts: list[str] = []
  index = 0
  while index < len(normalized):
    start = normalized.find("%%", index)
    if start < 0:
      parts.append(normalized[index:])
      break
    parts.append(normalized[index:start])
    end = normalized.find("%%", start + 2)
    if end < 0:
      parts.append("\n" * normalized[start:].count("\n"))
      break
    hidden = normalized[start:end + 2]
    parts.append("\n" * hidden.count("\n"))
    index = end + 2
  return "".join(parts)


def _strip_markdown_html_comments(text: str) -> str:
  normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
  parts: list[str] = []
  index = 0
  while index < len(normalized):
    start = normalized.find("<!--", index)
    if start < 0:
      parts.append(normalized[index:])
      break
    parts.append(normalized[index:start])
    end = normalized.find("-->", start + 4)
    if end < 0:
      parts.append("\n" * normalized[start:].count("\n"))
      break
    hidden = normalized[start:end + 3]
    parts.append("\n" * hidden.count("\n"))
    index = end + 3
  return "".join(parts)


def _strip_html_media_tags(text: str) -> str:
  cleaned = _HTML_MEDIA_BLOCK_PATTERN.sub("", str(text or ""))
  return _HTML_MEDIA_SINGLE_PATTERN.sub("", cleaned)


def _strip_markdown_footnotes(text: str) -> str:
  normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
  visible_lines: list[str] = []
  in_definition = False
  for line in normalized.split("\n"):
    if _MARKDOWN_FOOTNOTE_DEFINITION_PATTERN.match(line):
      visible_lines.append("")
      in_definition = True
      continue
    if in_definition:
      if not line.strip() or line.startswith(("    ", "\t")):
        visible_lines.append("")
        continue
      in_definition = False
    visible_lines.append(_MARKDOWN_FOOTNOTE_REFERENCE_PATTERN.sub("", line))
  return "\n".join(visible_lines)


def _html_attribute_value(attrs: str, name: str) -> str:
  target_name = str(name or "").strip().lower()
  for match in _HTML_ATTRIBUTE_PATTERN.finditer(str(attrs or "")):
    attr_name = match.group(1).strip().lower()
    if attr_name != target_name:
      continue
    value = match.group(2) if match.group(2) is not None else match.group(3)
    if value is None:
      value = match.group(4) or ""
    return html_unescape(value).strip()
  return ""


def _html_anchor_label(raw_label: str, href: str) -> str:
  without_tags = re.sub(r"<[^>]+>", " ", str(raw_label or ""))
  label = html_unescape(without_tags)
  label = re.sub(r"[\[\]\r\n]+", " ", label)
  label = re.sub(r"\s+", " ", label).strip()
  if label:
    return _compact_text(label, 120)
  href_path = re.split(r"[#?]", str(href or "").strip(), maxsplit=1)[0]
  fallback = Path(href_path.replace("\\", "/")).stem
  return _compact_text(fallback or "链接", 120)


def _normalize_html_anchor_links(text: str) -> str:
  def replacement(match: re.Match[str]) -> str:
    href = _html_attribute_value(match.group("attrs") or "", "href")
    if not href:
      return _html_anchor_label(match.group("label") or "", "")
    label = _html_anchor_label(match.group("label") or "", href)
    destination = href.replace(">", "%3E")
    return f"[{label}](<{destination}>)"

  return _HTML_ANCHOR_PATTERN.sub(replacement, str(text or ""))


def _obsidian_callout_type(value: str) -> str:
  return re.sub(r"[\s_]+", "-", str(value or "").strip().lower())


def _obsidian_quote_depth(line: str) -> tuple[int, str]:
  text = str(line or "")
  index = 0
  leading_spaces = 0
  while index < len(text) and text[index] == " ":
    leading_spaces += 1
    index += 1
  if leading_spaces > 3 or index >= len(text) or text[index] != ">":
    return 0, text
  depth = 0
  while index < len(text) and text[index] == ">":
    depth += 1
    index += 1
    while index < len(text) and text[index] == " ":
      index += 1
  return depth, text[index:]


def _strip_hidden_obsidian_callouts(text: str) -> str:
  normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
  visible_lines: list[str] = []
  hidden_quote_depth = 0
  for line in normalized.split("\n"):
    if hidden_quote_depth:
      if not line.strip():
        hidden_quote_depth = 0
        visible_lines.append(line)
        continue
      quote_depth, _quote_body = _obsidian_quote_depth(line)
      if quote_depth >= hidden_quote_depth:
        continue
      hidden_quote_depth = 0
    quote_depth, quote_body = _obsidian_quote_depth(line)
    match = _OBSIDIAN_CALLOUT_PATTERN.match(quote_body)
    if match and quote_depth > 0:
      callout_type = _obsidian_callout_type(match.group(1))
      if callout_type in _HIDDEN_OBSIDIAN_CALLOUT_TYPES:
        hidden_quote_depth = quote_depth
        continue
      visible_lines.append(line)
      continue
    visible_lines.append(line)
  return "\n".join(visible_lines)


def _first_query_value(query: dict[str, list[str]], keys: tuple[str, ...]) -> str:
  for key in keys:
    for value in query.get(key, []):
      cleaned = str(value or "").strip()
      if cleaned:
        return cleaned
  return ""


def _safe_uri_subpath(value: str, prefix: str) -> str:
  cleaned = html_unescape(str(value or "")).strip()
  cleaned = re.sub(r"[\r\n\t]+", " ", cleaned)
  cleaned = re.sub(r"\s+", " ", cleaned).strip()
  cleaned = cleaned.replace("[", "").replace("]", "").replace("|", " ")
  cleaned = cleaned.lstrip("#^").strip()
  if not cleaned:
    return ""
  return f"{prefix}{_compact_text(cleaned, 160)}"


def _obsidian_uri_target_candidate(value: str) -> tuple[str, str]:
  cleaned = html_unescape(str(value or "")).strip().strip("<>").strip("\"'“”‘’").replace("\\", "/")
  if not cleaned or cleaned.startswith("//") or cleaned.startswith("/"):
    return "", ""
  if re.match(r"^[a-zA-Z]:/", cleaned):
    return "", ""
  split_indexes = [index for index in (cleaned.find("#"), cleaned.find("^"), cleaned.find("?")) if index >= 0]
  split_at = min(split_indexes) if split_indexes else -1
  subpath = ""
  if split_at >= 0:
    marker = cleaned[split_at]
    if marker in {"#", "^"}:
      subpath = _safe_uri_subpath(cleaned[split_at + 1:], marker)
    cleaned = cleaned[:split_at].strip()
  return cleaned, subpath


def _obsidian_uri_link_parts(value: str) -> tuple[str, str]:
  raw_value = html_unescape(str(value or "")).strip().strip("<>").strip("\"'“”‘’")
  if not raw_value:
    return "", ""
  try:
    parsed = urlparse(raw_value)
  except ValueError:
    return "", ""
  if parsed.scheme.lower() != "obsidian":
    return "", ""
  query = parse_qs(parsed.query, keep_blank_values=False)
  target, target_subpath = _obsidian_uri_target_candidate(_first_query_value(query, _OBSIDIAN_URI_TARGET_QUERY_KEYS))
  if not target:
    return "", ""
  subpath = target_subpath
  if not subpath:
    heading = _first_query_value(query, _OBSIDIAN_URI_HEADING_QUERY_KEYS)
    if heading:
      subpath = _safe_uri_subpath(heading, "#")
  if not subpath:
    block = _first_query_value(query, _OBSIDIAN_URI_BLOCK_QUERY_KEYS)
    if block:
      subpath = _safe_uri_subpath(block, "^")
  if not subpath and parsed.fragment:
    subpath = _safe_uri_subpath(unquote(parsed.fragment), "#")
  return target, subpath


def _obsidian_uri_link_target(value: str) -> str:
  return _obsidian_uri_link_parts(value)[0]


def _knowledge_link_target(value: str, source_relative_path: str = "") -> str:
  cleaned = str(value or "").strip().replace("\\", "/")
  if not cleaned or cleaned.startswith("#"):
    return ""
  obsidian_target = _obsidian_uri_link_target(cleaned)
  if obsidian_target:
    cleaned = f"/{obsidian_target.lstrip('/')}"
  elif _URL_SCHEME_PATTERN.match(cleaned) or cleaned.startswith("//"):
    return ""
  cleaned = re.split(r"[#?^]", cleaned, maxsplit=1)[0].strip()
  cleaned = unquote(cleaned).strip().replace("\\", "/")
  if not cleaned:
    return ""
  suffix = posixpath.splitext(cleaned)[1].lower()
  if suffix and suffix not in _KNOWLEDGE_LINK_SUFFIXES:
    return ""
  root_relative = cleaned.startswith("/")
  if root_relative:
    cleaned = cleaned.lstrip("/")
  if cleaned.startswith(".") or "/" in cleaned or root_relative:
    source_dir = posixpath.dirname(str(source_relative_path or "").replace("\\", "/"))
    if cleaned.startswith(".") and source_dir and not root_relative:
      cleaned = posixpath.normpath(posixpath.join(source_dir, cleaned))
      if cleaned == "." or cleaned.startswith("../"):
        return ""
    else:
      cleaned = posixpath.normpath(cleaned)
      if cleaned == ".." or cleaned.startswith("../"):
        return ""
  while cleaned.startswith("./"):
    cleaned = cleaned[2:]
  return "" if cleaned in {"", ".", ".."} else cleaned.lstrip("/")


def _strip_non_knowledge_wiki_links(text: str, source_relative_path: str = "") -> str:
  def replacement(match: re.Match[str]) -> str:
    return match.group(0) if _knowledge_link_target(match.group(1), source_relative_path) else ""

  return _WIKI_LINK_WITH_EMBED_PATTERN.sub(replacement, text)


def _is_local_non_knowledge_markdown_destination(raw_value: str) -> bool:
  cleaned = _strip_markdown_link_title(str(raw_value or "").strip())
  if not cleaned:
    return False
  cleaned = cleaned.strip().strip("\"'“”‘’")
  if not cleaned or cleaned.startswith("#"):
    return False
  if _URL_SCHEME_PATTERN.match(cleaned) or cleaned.startswith("//"):
    return False

  cleaned = _strip_markdown_link_fragment(cleaned)
  cleaned = _normalize_markdown_link_path(unquote(cleaned).strip())
  if not cleaned:
    return False
  suffix = posixpath.splitext(cleaned)[1].lower()
  return bool(suffix and suffix not in _KNOWLEDGE_LINK_SUFFIXES)


def _strip_non_knowledge_markdown_links(text: str) -> str:
  body = str(text or "")
  replacements: list[tuple[int, int, str]] = []

  for match in _iter_markdown_link_matches(body):
    if _is_local_non_knowledge_markdown_destination(match.destination):
      replacements.append((match.start, match.end, ""))

  attachment_references: dict[str, str] = {}
  offset = 0
  for line in body.splitlines(keepends=True):
    raw_line = line.rstrip("\r\n")
    match = re.match(r"^\s{0,3}\[([^\]\n]+)\]:\s*(.+?)\s*$", raw_line)
    if match:
      label = match.group(1).strip()
      destination = match.group(2).strip()
      if (
        label
        and not _markdown_reference_label_is_footnote(label)
        and _is_local_non_knowledge_markdown_destination(destination)
      ):
        attachment_references[_markdown_reference_label_key(label)] = "__attachment__"
        replacements.append((offset, offset + len(line), ""))
    offset += len(line)

  for match in _iter_markdown_reference_link_matches(body, attachment_references):
    replacements.append((match.start, match.end, ""))

  if not replacements:
    return body

  parts: list[str] = []
  index = 0
  for start, end, replacement in sorted(replacements, key=lambda item: item[0]):
    if start < index:
      continue
    parts.append(body[index:start])
    parts.append(replacement)
    index = end
  parts.append(body[index:])
  return "".join(parts)


def _ai_visible_body(
  body: str,
  source_relative_path: str = "",
  config: ObsidianVaultConfig | None = None,
) -> str:
  cleaned = _strip_markdown_inline_code(_strip_fenced_code_blocks(body))
  cleaned = _strip_html_deleted_tags(_strip_markdown_deleted_text(cleaned))
  cleaned = _strip_hidden_html_details(cleaned, config)
  cleaned = _strip_obsidian_comments(cleaned)
  cleaned = _strip_markdown_html_comments(cleaned)
  cleaned = _strip_hidden_obsidian_callouts(cleaned)
  cleaned = _strip_markdown_footnotes(cleaned)
  cleaned = _normalize_html_anchor_links(cleaned)
  cleaned = _strip_html_media_tags(cleaned)
  cleaned = _strip_non_knowledge_wiki_links(cleaned, source_relative_path)
  cleaned = _strip_non_knowledge_markdown_links(cleaned)
  cleaned = _MARKDOWN_IMAGE_PATTERN.sub("", cleaned)
  lines = [line.rstrip() for line in cleaned.split("\n")]
  while lines and not lines[0].strip():
    lines.pop(0)
  while lines and not lines[-1].strip():
    lines.pop()
  return "\n".join(lines)


def _ordered_unique(items: list[str]) -> list[str]:
  seen: set[str] = set()
  ordered: list[str] = []
  for item in items:
    cleaned = str(item or "").strip()
    if not cleaned or cleaned in seen:
      continue
    seen.add(cleaned)
    ordered.append(cleaned)
  return ordered


def _stable_json(value: Any) -> str:
  return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _link_lookup_key(value: str) -> str:
  cleaned = str(value or "").strip().replace("\\", "/")
  cleaned = re.sub(r"\s+", " ", cleaned)
  if cleaned.lower().endswith(".md"):
    cleaned = cleaned[:-3]
  return cleaned.lower()


def _add_query_term(terms: list[str], seen: set[str], value: str, *, limit: int = 260) -> bool:
  cleaned = str(value or "").strip().lower()
  if len(cleaned) < 2 or cleaned in _QUERY_STOP_TERMS or cleaned in seen:
    return len(terms) >= limit
  seen.add(cleaned)
  terms.append(cleaned)
  return len(terms) >= limit


def _query_terms(query: str) -> list[str]:
  normalized = str(query or "").lower()
  terms: list[str] = []
  seen: set[str] = set()

  for match in re.finditer(r"[a-z0-9_][a-z0-9_\-]{1,}", normalized):
    if _add_query_term(terms, seen, match.group(0)):
      return terms

  for segment in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
    if len(segment) <= 8 and _add_query_term(terms, seen, segment):
      return terms
    for size in (4, 3, 2):
      if len(segment) < size:
        continue
      for index in range(0, len(segment) - size + 1):
        if _add_query_term(terms, seen, segment[index:index + size]):
          return terms
  return terms


def _note_labels(item: object) -> list[str]:
  relative_path = str(getattr(item, "relative_path", "") or "").strip().replace("\\", "/")
  labels = [
    str(getattr(item, "title", "") or ""),
    relative_path,
    relative_path[:-3] if relative_path.lower().endswith(".md") else relative_path,
    Path(relative_path).stem,
    str(getattr(item, "note_type", "") or ""),
    str(getattr(item, "status", "") or ""),
    str(getattr(item, "summary", "") or ""),
  ]
  labels.extend(str(value or "") for value in getattr(item, "keywords", []) or [])
  labels.extend(str(value or "") for value in getattr(item, "aliases", []) or [])
  labels.extend(str(value or "") for value in getattr(item, "tags", []) or [])
  labels.extend(str(value or "") for value in getattr(item, "links", []) or [])
  labels.extend(str(value or "") for value in getattr(item, "external_links", []) or [])
  labels.extend(str(value or "") for value in getattr(item, "external_references", []) or [])
  labels.extend(str(value or "") for value in getattr(item, "required_phrases", []) or [])
  labels.extend(str(value or "") for value in getattr(item, "forbidden_phrases", []) or [])
  return [value.strip() for value in labels if value.strip()]


def _chapter_scope_score(item: object, chapter_index: int = 0) -> int:
  try:
    target = int(chapter_index or 0)
  except (TypeError, ValueError):
    target = 0
  if target <= 0:
    return 0

  score = 0
  try:
    chapter_start = int(getattr(item, "chapter_start", 0) or 0)
  except (TypeError, ValueError):
    chapter_start = 0
  try:
    chapter_end = int(getattr(item, "chapter_end", 0) or 0)
  except (TypeError, ValueError):
    chapter_end = 0
  try:
    reveal_after = int(getattr(item, "reveal_after_chapter", 0) or 0)
  except (TypeError, ValueError):
    reveal_after = 0

  if chapter_start > 0 and chapter_end > 0 and chapter_start <= target <= chapter_end:
    span = max(1, chapter_end - chapter_start + 1)
    if span == 1:
      score = max(score, 24)
    else:
      score = max(score, max(8, 22 - min(span, 14)))
  elif chapter_start > 0 and chapter_end <= 0 and target >= chapter_start:
    distance = target - chapter_start
    score = max(score, max(6, 16 - min(distance, 10)))
  elif chapter_start > 0 and target == chapter_start:
    score = max(score, 10)
  elif chapter_end > 0 and target == chapter_end:
    score = max(score, 8)

  if reveal_after > 0 and target > reveal_after:
    distance = target - reveal_after - 1
    score = max(score, max(4, 14 - min(distance, 10)))

  return score


def _note_score(item: object, query: str, terms: list[str], *, chapter_index: int = 0) -> int:
  labels = _note_labels(item)
  query_lower = query.lower()
  preview = str(getattr(item, "preview", "") or "").lower()
  label_text = " ".join(labels).lower()
  score = _chapter_scope_score(item, chapter_index)
  for label in labels:
    lowered = label.lower()
    if len(lowered) >= 2 and lowered in query_lower:
      score += 12
  for term in terms:
    if term in label_text:
      score += 4 if len(term) <= 3 else 6
    elif term in preview:
      score += 2 if len(term) <= 3 else 3
  return score


def obsidian_note_available_for_chapter(item: object, chapter_index: int = 0) -> bool:
  try:
    target = int(chapter_index or 0)
  except (TypeError, ValueError):
    target = 0
  if target <= 0:
    return True

  try:
    reveal_after = int(getattr(item, "reveal_after_chapter", 0) or 0)
  except (TypeError, ValueError):
    reveal_after = 0
  if reveal_after > 0 and target <= reveal_after:
    return False

  try:
    chapter_start = int(getattr(item, "chapter_start", 0) or 0)
  except (TypeError, ValueError):
    chapter_start = 0
  if chapter_start > 0 and target < chapter_start:
    return False

  try:
    chapter_end = int(getattr(item, "chapter_end", 0) or 0)
  except (TypeError, ValueError):
    chapter_end = 0
  if chapter_end > 0 and target > chapter_end:
    return False

  return True


def select_obsidian_notes_for_query(
  notes: list[object],
  query: str,
  limit: int = 8,
  *,
  chapter_index: int = 0,
) -> list[object]:
  eligible_notes = [item for item in notes if obsidian_note_available_for_chapter(item, chapter_index)]
  if not eligible_notes:
    return []
  note_by_path = {
    str(getattr(item, "relative_path", "") or "").strip(): item
    for item in eligible_notes
    if str(getattr(item, "relative_path", "") or "").strip()
  }
  terms = _query_terms(query)
  scored = [
    (index, item, _note_score(item, query, terms, chapter_index=chapter_index))
    for index, item in enumerate(eligible_notes)
  ]
  ranked = sorted(scored, key=lambda item: (-item[2], item[0]))
  matched = [item for _index, item, score in ranked if score > 0]
  if not matched:
    return eligible_notes[:limit]

  selected: list[object] = []
  selected_paths: set[str] = set()

  def add_note(item: object) -> None:
    path = str(getattr(item, "relative_path", "") or "").strip()
    if not path or path in selected_paths or len(selected) >= limit:
      return
    selected.append(item)
    selected_paths.add(path)

  for item in matched:
    add_note(item)
    for linked_path in list(getattr(item, "resolved_links", []) or [])[:4]:
      linked = note_by_path.get(str(linked_path))
      if linked is not None:
        add_note(linked)
    for backlink_path in list(getattr(item, "backlinks", []) or [])[:4]:
      linked = note_by_path.get(str(backlink_path))
      if linked is not None:
        add_note(linked)
    if len(selected) >= limit:
      break

  for item in matched:
    add_note(item)
    if len(selected) >= limit:
      break

  return selected


def obsidian_config_path(project_dir: Path) -> Path:
  return project_dir / _APP_STATE_DIRNAME / _CONFIG_FILENAME


def obsidian_sync_path(project_dir: Path) -> Path:
  return project_dir / _APP_STATE_DIRNAME / _SYNC_FILENAME


def obsidian_source_key(relative_path: str) -> str:
  normalized = relative_path.strip().replace("\\", "/")
  return f"obsidian:{normalized}"


def load_obsidian_config(project_dir: Path) -> ObsidianVaultConfig:
  payload = read_json(obsidian_config_path(project_dir), None)
  if not isinstance(payload, dict):
    return ObsidianVaultConfig()
  try:
    return ObsidianVaultConfig.model_validate(payload)
  except ValidationError:
    return ObsidianVaultConfig()


def save_obsidian_config(project_dir: Path, config: ObsidianVaultConfig) -> ObsidianVaultConfig:
  normalized = config.model_copy(
    update={
      "vault_path": config.vault_path.strip(),
      "include_patterns": _ordered_unique(config.include_patterns) or list(_DEFAULT_INCLUDE_PATTERNS),
      "exclude_patterns": _ordered_unique(config.exclude_patterns),
      "allowed_statuses": _ordered_unique(config.allowed_statuses),
      "excluded_statuses": _ordered_unique(config.excluded_statuses),
    }
  )
  obsidian_config_path(project_dir).parent.mkdir(parents=True, exist_ok=True)
  atomic_write_json(obsidian_config_path(project_dir), normalized.model_dump(mode="json"))
  return normalized


def _decode_text_bytes(data: bytes) -> str:
  for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
    try:
      return data.decode(encoding)
    except UnicodeDecodeError:
      continue
  return data.decode("utf-8", errors="ignore")


def resolve_obsidian_vault_dir(project_dir: Path, config: ObsidianVaultConfig | None = None) -> Path | None:
  if config is None:
    config = load_obsidian_config(project_dir)
  raw_path = config.vault_path.strip()
  if not raw_path:
    return None
  path = Path(raw_path).expanduser()
  if not path.is_absolute():
    path = project_dir / path
  return path.resolve()


def _resolve_vault_dir(project_dir: Path, config: ObsidianVaultConfig) -> Path | None:
  return resolve_obsidian_vault_dir(project_dir, config)


def _path_is_inside(path: Path, parent: Path) -> bool:
  try:
    path.resolve().relative_to(parent.resolve())
    return True
  except ValueError:
    return False


def _pattern_variants(pattern: str) -> list[str]:
  cleaned = pattern.strip().replace("\\", "/")
  if not cleaned:
    return []
  variants = [cleaned]
  if cleaned.startswith("**/"):
    variants.append(cleaned[3:])
  if "/" not in cleaned:
    variants.append(f"**/{cleaned}")
  if cleaned.endswith("/**"):
    variants.append(cleaned[:-3])
  return _ordered_unique(variants)


def _matches_any(relative_path: str, patterns: list[str]) -> bool:
  normalized = relative_path.strip().replace("\\", "/")
  normalized_folded = normalized.casefold()
  for pattern in patterns:
    for variant in _pattern_variants(pattern):
      if fnmatch.fnmatch(normalized, variant) or fnmatch.fnmatch(normalized_folded, variant.casefold()):
        return True
  return False


def _split_frontmatter_flow_items(value: str) -> list[str]:
  items: list[str] = []
  current: list[str] = []
  quote = ""
  bracket_depth = 0
  paren_depth = 0
  brace_depth = 0
  index = 0
  text = str(value or "")
  while index < len(text):
    char = text[index]
    if quote:
      current.append(char)
      if char == quote:
        quote = ""
      elif char == "\\" and index + 1 < len(text):
        index += 1
        current.append(text[index])
      index += 1
      continue
    if char in {"'", '"'}:
      quote = char
      current.append(char)
    elif char == "[":
      bracket_depth += 1
      current.append(char)
    elif char == "]" and bracket_depth > 0:
      bracket_depth -= 1
      current.append(char)
    elif char == "(":
      paren_depth += 1
      current.append(char)
    elif char == ")" and paren_depth > 0:
      paren_depth -= 1
      current.append(char)
    elif char == "{":
      brace_depth += 1
      current.append(char)
    elif char == "}" and brace_depth > 0:
      brace_depth -= 1
      current.append(char)
    elif char == "," and bracket_depth == 0 and paren_depth == 0 and brace_depth == 0:
      item = "".join(current).strip()
      if item:
        items.append(item)
      current = []
    else:
      current.append(char)
    index += 1

  item = "".join(current).strip()
  if item:
    items.append(item)
  return items


def _split_frontmatter_list_text(value: str) -> list[str]:
  items: list[str] = []
  current: list[str] = []
  quote = ""
  bracket_depth = 0
  paren_depth = 0
  brace_depth = 0
  delimiters = {"\n", ",", "，", "、", ";", "；"}
  index = 0
  text = str(value or "")
  while index < len(text):
    char = text[index]
    if quote:
      current.append(char)
      if char == quote:
        quote = ""
      elif char == "\\" and index + 1 < len(text):
        index += 1
        current.append(text[index])
      index += 1
      continue
    if char in {"'", '"'}:
      quote = char
      current.append(char)
    elif char == "[":
      bracket_depth += 1
      current.append(char)
    elif char == "]" and bracket_depth > 0:
      bracket_depth -= 1
      current.append(char)
    elif char == "(":
      paren_depth += 1
      current.append(char)
    elif char == ")" and paren_depth > 0:
      paren_depth -= 1
      current.append(char)
    elif char == "{":
      brace_depth += 1
      current.append(char)
    elif char == "}" and brace_depth > 0:
      brace_depth -= 1
      current.append(char)
    elif char in delimiters and bracket_depth == 0 and paren_depth == 0 and brace_depth == 0:
      item = "".join(current).strip()
      if item:
        items.append(item)
      current = []
    else:
      current.append(char)
    index += 1

  item = "".join(current).strip()
  if item:
    items.append(item)
  return items


def _matching_note_paths(vault_dir: Path, config: ObsidianVaultConfig) -> list[Path]:
  include_patterns = config.include_patterns or list(_DEFAULT_INCLUDE_PATTERNS)
  exclude_patterns = config.exclude_patterns or []
  candidates: list[Path] = []
  for path in vault_dir.rglob("*"):
    if not path.is_file():
      continue
    relative = path.relative_to(vault_dir).as_posix()
    if not _matches_any(relative, include_patterns):
      continue
    if _matches_any(relative, exclude_patterns):
      continue
    candidates.append(path)
  return sorted(candidates, key=lambda item: item.relative_to(vault_dir).as_posix())


def _candidate_note_paths(vault_dir: Path, config: ObsidianVaultConfig) -> list[Path]:
  return _matching_note_paths(vault_dir, config)[: config.max_notes]


def _candidate_limit_warning(total_count: int, config: ObsidianVaultConfig) -> str:
  if total_count <= config.max_notes:
    return ""
  return (
    f"Obsidian 匹配到 {total_count} 篇候选笔记，已按路径排序后同步前 {config.max_notes} 篇；"
    "请收窄 include_patterns / exclude_patterns，或提高 max_notes。"
  )


def _parse_frontmatter_flow_mapping(value: str) -> dict[str, Any] | None:
  cleaned = str(value or "").strip()
  if not (cleaned.startswith("{") and cleaned.endswith("}")):
    return None
  inner = cleaned[1:-1].strip()
  if not inner:
    return {}
  payload: dict[str, Any] = {}
  for item in _split_frontmatter_flow_items(inner):
    pair = _parse_frontmatter_key_value(item)
    if not pair:
      return None
    key, raw_value = pair
    payload[key] = _parse_scalar(raw_value)
  return payload


def _parse_scalar(value: str) -> Any:
  cleaned = value.strip()
  if not cleaned:
    return ""
  if cleaned.startswith("[[") and cleaned.endswith("]]"):
    return cleaned
  if cleaned in {"true", "True", "TRUE", "yes", "Yes", "YES", "是"}:
    return True
  if cleaned in {"false", "False", "FALSE", "no", "No", "NO", "否"}:
    return False
  flow_mapping = _parse_frontmatter_flow_mapping(cleaned)
  if flow_mapping is not None:
    return flow_mapping
  if cleaned.startswith("[") and cleaned.endswith("]"):
    inner = cleaned[1:-1].strip()
    if not inner:
      return []
    parsed_items: list[Any] = []
    for item in _split_frontmatter_flow_items(inner):
      parsed = _parse_scalar(item)
      parsed_items.append(_FrontmatterFlowItem(parsed) if isinstance(parsed, str) else parsed)
    return parsed_items
  if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
    return cleaned[1:-1].strip()
  return cleaned


def _strip_frontmatter_inline_comment(value: str) -> str:
  text = str(value or "")
  quote = ""
  bracket_depth = 0
  index = 0
  while index < len(text):
    char = text[index]
    if quote:
      if char == quote:
        quote = ""
      elif quote == '"' and char == "\\" and index + 1 < len(text):
        index += 1
      index += 1
      continue
    if char in {"'", '"'}:
      quote = char
    elif char == "[":
      bracket_depth += 1
    elif char == "]" and bracket_depth > 0:
      bracket_depth -= 1
    elif char == "#" and bracket_depth == 0 and (index == 0 or text[index - 1].isspace()):
      return text[:index].rstrip()
    index += 1
  return text.rstrip()


def _frontmatter_key_token(value: str) -> str:
  return re.sub(r"[\s\-]+", "_", str(value or "").strip().lower())


def _frontmatter_key_is_tag(value: str) -> bool:
  return _frontmatter_key_token(value) in {"tag", "tags", "标签"}


def _strip_frontmatter_value_for_key(value: str, key: str) -> str:
  text = str(value or "")
  if _frontmatter_key_is_tag(key):
    cleaned = text.strip()
    if cleaned.startswith("#") and not cleaned.startswith("# "):
      return text.rstrip()
  return _strip_frontmatter_inline_comment(text)


def _strip_frontmatter_list_item_value(value: str, *, parent_key: str = "") -> str:
  text = str(value or "")
  if _frontmatter_key_is_tag(parent_key):
    cleaned = text.strip()
    if cleaned.startswith("#") and not cleaned.startswith("# "):
      return text.rstrip()
  return _strip_frontmatter_inline_comment(text)


def _frontmatter_indent(line: str) -> int:
  return len(line) - len(line.lstrip(" "))


def _dedent_frontmatter_block(lines: list[str]) -> list[str]:
  non_empty_indents = [
    _frontmatter_indent(line)
    for line in lines
    if line.strip()
  ]
  if not non_empty_indents:
    return ["" for _line in lines]
  indent = min(non_empty_indents)
  return [line[indent:] if len(line) >= indent else "" for line in lines]


def _parse_frontmatter_block_scalar(marker: str, lines: list[str]) -> str:
  dedented = _dedent_frontmatter_block([line.rstrip() for line in lines])
  if marker == "|":
    return "\n".join(dedented).strip()

  paragraphs: list[str] = []
  current: list[str] = []
  for line in dedented:
    if line.strip():
      current.append(line.strip())
      continue
    if current:
      paragraphs.append(" ".join(current).strip())
      current = []
  if current:
    paragraphs.append(" ".join(current).strip())
  return "\n\n".join(item for item in paragraphs if item).strip()


def _frontmatter_block_marker(value: str) -> str:
  match = re.match(r"^([>|])(?:[+-]|[1-9]|[+-][1-9]|[1-9][+-])?$", str(value or "").strip())
  return match.group(1) if match else ""


def _collect_frontmatter_block_lines(
  frontmatter_lines: list[str],
  start_index: int,
  key_indent: int,
) -> tuple[list[str], int]:
  block_lines: list[str] = []
  index = start_index
  while index < len(frontmatter_lines):
    candidate = frontmatter_lines[index].rstrip()
    if candidate.strip() and _frontmatter_indent(frontmatter_lines[index]) <= key_indent:
      break
    block_lines.append(candidate)
    index += 1
  return block_lines, index


def _parse_frontmatter_key_value(line: str) -> tuple[str, str] | None:
  match = re.match(r"^([^:#][^:]{0,80}):\s*(.*)$", str(line or "").strip())
  if not match:
    return None
  key = match.group(1).strip()
  return key, _strip_frontmatter_value_for_key(match.group(2), key).strip()


def _frontmatter_list_item_content(stripped_line: str) -> str | None:
  stripped = str(stripped_line or "").strip()
  if stripped == "-":
    return ""
  if stripped.startswith("- "):
    return stripped[2:].strip()
  return None


def _frontmatter_list_item_prefers_scalar(value: str) -> bool:
  cleaned = str(value or "").strip()
  if not cleaned:
    return False
  if cleaned.startswith(("\"", "'", "[", "[[")):
    return True
  if re.match(r"(?i)^[a-z][a-z0-9+.-]*://", cleaned) or cleaned.startswith("//"):
    return True
  return False


def _frontmatter_child_kind(frontmatter_lines: list[str], start_index: int, parent_indent: int) -> str:
  index = start_index
  while index < len(frontmatter_lines):
    raw_line = frontmatter_lines[index]
    stripped = raw_line.strip()
    if not stripped or stripped.startswith("#"):
      index += 1
      continue
    if _frontmatter_indent(raw_line) <= parent_indent:
      return ""
    if _frontmatter_list_item_content(stripped) is not None:
      return "list"
    if _parse_frontmatter_key_value(stripped):
      return "mapping"
    return ""
  return ""


def _parse_frontmatter_empty_value(
  frontmatter_lines: list[str],
  start_index: int,
  parent_indent: int,
  parent_key: str = "",
) -> tuple[Any, int]:
  child_kind = _frontmatter_child_kind(frontmatter_lines, start_index, parent_indent)
  if child_kind == "mapping":
    return _parse_frontmatter_mapping_block(frontmatter_lines, start_index, parent_indent)
  if child_kind == "list":
    return _parse_frontmatter_sequence(frontmatter_lines, start_index, parent_indent, parent_key=parent_key)
  return [], start_index


def _parse_frontmatter_mapping_list_item(
  frontmatter_lines: list[str],
  start_index: int,
  item_indent: int,
  first_content: str,
) -> tuple[dict[str, Any] | None, int]:
  flow_item = _parse_frontmatter_flow_mapping(first_content)
  if flow_item is not None:
    return flow_item, start_index + 1

  if _frontmatter_list_item_prefers_scalar(first_content):
    return None, start_index

  first_pair = _parse_frontmatter_key_value(first_content)
  if not first_pair:
    if str(first_content or "").strip():
      return None, start_index
    item: dict[str, Any] = {}
    index = start_index + 1
  else:
    item = {}
    key, value = first_pair
    index = start_index + 1
    block_marker = _frontmatter_block_marker(value)
    if block_marker:
      block_lines, index = _collect_frontmatter_block_lines(frontmatter_lines, index, item_indent + 2)
      item[key] = _parse_frontmatter_block_scalar(block_marker, block_lines)
    elif value:
      item[key] = _parse_scalar(value)
    else:
      item[key], index = _parse_frontmatter_empty_value(frontmatter_lines, index, item_indent, key)

  while index < len(frontmatter_lines):
    raw_line = frontmatter_lines[index]
    line = raw_line.rstrip()
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
      index += 1
      continue
    if _frontmatter_indent(raw_line) <= item_indent:
      break
    pair = _parse_frontmatter_key_value(stripped)
    if not pair:
      index += 1
      continue
    nested_key, nested_value = pair
    block_marker = _frontmatter_block_marker(nested_value)
    if block_marker:
      block_lines, index = _collect_frontmatter_block_lines(
        frontmatter_lines,
        index + 1,
        _frontmatter_indent(raw_line),
      )
      item[nested_key] = _parse_frontmatter_block_scalar(block_marker, block_lines)
      continue
    if nested_value:
      item[nested_key] = _parse_scalar(nested_value)
    else:
      item[nested_key], index = _parse_frontmatter_empty_value(
        frontmatter_lines,
        index + 1,
        _frontmatter_indent(raw_line),
        nested_key,
      )
      continue
    index += 1
  return item, index


def _parse_frontmatter_sequence(
  frontmatter_lines: list[str],
  start_index: int,
  parent_indent: int,
  parent_key: str = "",
) -> tuple[list[Any], int]:
  values: list[Any] = []
  index = start_index
  while index < len(frontmatter_lines):
    raw_line = frontmatter_lines[index]
    stripped = raw_line.strip()
    if not stripped or stripped.startswith("#"):
      index += 1
      continue
    if _frontmatter_indent(raw_line) <= parent_indent:
      break
    list_item_content = _frontmatter_list_item_content(stripped)
    if list_item_content is None:
      break
    list_item_value = _strip_frontmatter_list_item_value(list_item_content, parent_key=parent_key)
    block_marker = _frontmatter_block_marker(list_item_value)
    if block_marker:
      block_lines, index = _collect_frontmatter_block_lines(
        frontmatter_lines,
        index + 1,
        _frontmatter_indent(raw_line),
      )
      values.append(_parse_frontmatter_block_scalar(block_marker, block_lines))
      continue
    mapping_item, next_index = _parse_frontmatter_mapping_list_item(
      frontmatter_lines,
      index,
      _frontmatter_indent(raw_line),
      list_item_content,
    )
    if mapping_item is not None:
      values.append(mapping_item)
      index = next_index
      continue
    values.append(_parse_scalar(list_item_value))
    index += 1
  return values, index


def _parse_frontmatter_mapping_block(
  frontmatter_lines: list[str],
  start_index: int,
  parent_indent: int,
) -> tuple[dict[str, Any], int]:
  payload: dict[str, Any] = {}
  index = start_index
  while index < len(frontmatter_lines):
    raw_line = frontmatter_lines[index]
    line = raw_line.rstrip()
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
      index += 1
      continue
    if _frontmatter_indent(raw_line) <= parent_indent:
      break
    pair = _parse_frontmatter_key_value(stripped)
    if not pair:
      index += 1
      continue
    key, value = pair
    block_marker = _frontmatter_block_marker(value)
    if block_marker:
      block_lines, index = _collect_frontmatter_block_lines(
        frontmatter_lines,
        index + 1,
        _frontmatter_indent(raw_line),
      )
      payload[key] = _parse_frontmatter_block_scalar(block_marker, block_lines)
      continue
    if value:
      payload[key] = _parse_scalar(value)
      index += 1
      continue
    payload[key], index = _parse_frontmatter_empty_value(
      frontmatter_lines,
      index + 1,
      _frontmatter_indent(raw_line),
      key,
    )
  return payload, index


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
  normalized = text.replace("\r\n", "\n")
  lines = normalized.split("\n")
  if not lines or lines[0].strip() != _FRONTMATTER_BOUNDARY:
    return {}, normalized.strip()

  end_index = -1
  for index in range(1, len(lines)):
    if lines[index].strip() == _FRONTMATTER_BOUNDARY:
      end_index = index
      break
  if end_index < 0:
    return {}, normalized.strip()

  payload: dict[str, Any] = {}
  current_key = ""
  frontmatter_lines = lines[1:end_index]
  index = 0
  while index < len(frontmatter_lines):
    raw_line = frontmatter_lines[index]
    line = raw_line.rstrip()
    if not line.strip() or line.lstrip().startswith("#"):
      index += 1
      continue
    list_item_content = _frontmatter_list_item_content(line.strip())
    if current_key and list_item_content is not None:
      payload.setdefault(current_key, [])
      if isinstance(payload[current_key], list):
        item_indent = _frontmatter_indent(raw_line)
        mapping_item, next_index = _parse_frontmatter_mapping_list_item(
          frontmatter_lines,
          index,
          item_indent,
          list_item_content,
        )
        if mapping_item is not None:
          payload[current_key].append(mapping_item)
          index = next_index
          continue
        payload[current_key].append(
          _parse_scalar(_strip_frontmatter_list_item_value(list_item_content, parent_key=current_key))
        )
      index += 1
      continue
    match = re.match(r"^([^:#][^:]{0,80}):\s*(.*)$", line)
    if not match:
      current_key = ""
      index += 1
      continue
    key = match.group(1).strip()
    value = _strip_frontmatter_value_for_key(match.group(2), key).strip()
    block_marker = _frontmatter_block_marker(value)
    if block_marker:
      key_indent = _frontmatter_indent(raw_line)
      block_lines, index = _collect_frontmatter_block_lines(frontmatter_lines, index + 1, key_indent)
      payload[key] = _parse_frontmatter_block_scalar(block_marker, block_lines)
      current_key = ""
      continue
    if not value:
      payload[key], index = _parse_frontmatter_empty_value(
        frontmatter_lines,
        index + 1,
        _frontmatter_indent(raw_line),
        key,
      )
      current_key = ""
      continue
    else:
      payload[key] = _parse_scalar(value)
      current_key = ""
    index += 1

  return payload, "\n".join(lines[end_index + 1 :]).strip()


def _frontmatter_key_id(value: str) -> str:
  return _frontmatter_key_token(value)


def _frontmatter_value(payload: dict[str, Any], key: str) -> tuple[bool, Any]:
  if key in payload:
    return True, payload.get(key)
  target = _frontmatter_key_id(key)
  for raw_key, value in payload.items():
    if _frontmatter_key_id(str(raw_key)) == target:
      return True, value
  for value in payload.values():
    if not isinstance(value, dict):
      continue
    for raw_key, child_value in value.items():
      if _frontmatter_key_id(str(raw_key)) == target:
        return True, child_value
  return False, None


def _frontmatter_string(payload: dict[str, Any], *keys: str) -> str:
  for key in keys:
    found, value = _frontmatter_value(payload, key)
    if not found:
      continue
    if isinstance(value, str) and value.strip():
      return value.strip()
    if isinstance(value, (int, float, bool)):
      return str(value)
    if isinstance(value, list):
      for item in value:
        if str(item).strip():
          return str(item).strip()
  return ""


def _frontmatter_list(payload: dict[str, Any], *keys: str) -> list[str]:
  values: list[str] = []
  for key in keys:
    found, value = _frontmatter_value(payload, key)
    if not found:
      continue
    values.extend(_frontmatter_list_from_value(value))
  return _ordered_unique(values)


def _clean_obsidian_tag(value: str) -> str:
  cleaned = str(value or "").strip().strip("\"'“”‘’`")
  cleaned = cleaned.lstrip("#").strip()
  return cleaned


def _frontmatter_tag_list(payload: dict[str, Any], *keys: str) -> list[str]:
  values: list[str] = []
  for key in keys:
    found, value = _frontmatter_value(payload, key)
    if not found:
      continue
    values.extend(_frontmatter_tag_list_from_value(value))
  return _ordered_unique(values)


def _frontmatter_tag_list_from_value(value: Any) -> list[str]:
  if isinstance(value, list):
    values: list[str] = []
    for item in value:
      values.extend(_frontmatter_tag_list_from_value(item))
    return _ordered_unique(values)
  if isinstance(value, str) and value.strip():
    return [
      tag
      for item in re.split(r"[\s\n,，、;；]+", value)
      if (tag := _clean_obsidian_tag(item))
    ]
  return []


def _frontmatter_list_from_value(value: Any) -> list[str]:
  if isinstance(value, _FrontmatterFlowItem):
    cleaned = str(value).strip()
    return [cleaned] if cleaned else []
  if isinstance(value, list):
    values: list[str] = []
    for item in value:
      values.extend(_frontmatter_list_from_value(item))
    return _ordered_unique(values)
  if isinstance(value, dict):
    values: list[str] = []
    for item in value.values():
      values.extend(_frontmatter_list_from_value(item))
    return _ordered_unique(values)
  if isinstance(value, str) and value.strip():
    return _split_frontmatter_list_text(value)
  return []


def _nested_context_label(value: object) -> str:
  key_id = _frontmatter_key_id(str(value or ""))
  if not key_id:
    return ""
  return _NESTED_CONTEXT_LABELS.get(key_id, str(value or "").strip())


def _context_body_values_from_value(value: Any) -> list[str]:
  if isinstance(value, _FrontmatterFlowItem):
    cleaned = str(value).strip()
    return [cleaned] if cleaned else []
  if isinstance(value, list):
    values: list[str] = []
    for item in value:
      values.extend(_context_body_values_from_value(item))
    return _ordered_unique(values)
  if isinstance(value, dict):
    parts: list[str] = []
    for raw_key, raw_item in value.items():
      label = _nested_context_label(raw_key)
      child_values = _context_body_values_from_value(raw_item)
      if not label:
        parts.extend(child_values)
        continue
      parts.extend(f"{label}：{child}" for child in child_values)
    combined = "；".join(part for part in parts if part).strip()
    return [combined] if combined else []
  if isinstance(value, str) and value.strip():
    values: list[str] = []
    for raw_line in value.replace("\r\n", "\n").split("\n"):
      cleaned = re.sub(r"^\s*(?:[-*+]|\d+[.)]|[（(]?\d+[）)])\s*", "", raw_line.strip())
      if cleaned:
        values.append(cleaned)
    return _ordered_unique(values)
  if isinstance(value, (int, float, bool)):
    return [str(value)]
  return []


def _frontmatter_context_values(payload: dict[str, Any], *keys: str) -> list[str]:
  values: list[str] = []
  for key in keys:
    found, value = _frontmatter_value(payload, key)
    if found:
      values.extend(_context_body_values_from_value(value))
  return _ordered_unique(values)


def _context_label_id(value: object) -> str:
  return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").strip().lower())


def _context_label_ids(value: object, *, split_nested_tag: bool = False) -> set[str]:
  raw_value = str(value or "").strip()
  if not raw_value:
    return set()
  labels = {_context_label_id(raw_value)}
  if split_nested_tag:
    labels.update(
      _context_label_id(part)
      for part in re.split(r"[\\/／]+", raw_value)
      if str(part or "").strip()
    )
  return {label for label in labels if label}


def _frontmatter_ai_visibility_from_tags(tags: list[str] | tuple[str, ...]) -> tuple[bool, bool]:
  labels: set[str] = set()
  for tag in tags:
    labels.update(_context_label_ids(tag, split_nested_tag=True))
  if not labels:
    return True, False
  blocked_labels = {_context_label_id(label) for label in _AI_BLOCKED_TAG_LABELS}
  if labels & blocked_labels:
    return False, True
  usable_labels = {_context_label_id(label) for label in _AI_USABLE_TAG_LABELS}
  if labels & usable_labels:
    return True, True
  return True, False


def _tag_labels(tags: list[str] | tuple[str, ...]) -> set[str]:
  labels: set[str] = set()
  for tag in tags:
    labels.update(_context_label_ids(tag, split_nested_tag=True))
  return labels


def _directory_labels(relative_path: str) -> set[str]:
  path_parts = [part for part in str(relative_path or "").replace("\\", "/").split("/") if part]
  directory_parts = path_parts[:-1] if path_parts else []
  labels: set[str] = set()
  for part in directory_parts:
    labels.update(_context_label_ids(part))
  return labels


def _preferred_status_value(
  fallback: str,
  configured_values: list[str] | tuple[str, ...],
  aliases: tuple[str, ...],
) -> str:
  alias_ids = {_context_label_id(alias) for alias in aliases}
  for value in configured_values:
    cleaned = str(value or "").strip()
    if cleaned and _context_label_id(cleaned) in alias_ids:
      return cleaned
  return fallback


def _labels_match_aliases(labels: set[str], aliases: tuple[str, ...]) -> bool:
  alias_ids = {_context_label_id(alias) for alias in aliases}
  return bool(labels & alias_ids)


def _status_alias_groups(
  config: ObsidianVaultConfig,
) -> tuple[tuple[str, list[str], tuple[str, ...]], ...]:
  return (
    ("draft", config.excluded_statuses, _STATUS_DRAFT_TAG_LABELS + _STATUS_DRAFT_DIRECTORY_LABELS),
    ("private", config.excluded_statuses, _STATUS_PRIVATE_TAG_LABELS + _STATUS_PRIVATE_DIRECTORY_LABELS),
    ("deprecated", config.excluded_statuses, _STATUS_DEPRECATED_TAG_LABELS + _STATUS_DEPRECATED_DIRECTORY_LABELS),
    ("canonical", config.allowed_statuses, _STATUS_CANONICAL_TAG_LABELS + _STATUS_CANONICAL_DIRECTORY_LABELS),
  )


def _status_property_groups(
  config: ObsidianVaultConfig,
) -> tuple[tuple[str, list[str], tuple[str, ...]], ...]:
  return (
    ("draft", config.excluded_statuses, _STATUS_DRAFT_TAG_LABELS),
    ("private", config.excluded_statuses, _STATUS_PRIVATE_TAG_LABELS),
    ("deprecated", config.excluded_statuses, _STATUS_DEPRECATED_TAG_LABELS),
    ("canonical", config.allowed_statuses, _STATUS_CANONICAL_TAG_LABELS),
  )


def _normalized_status_value(status: str, config: ObsidianVaultConfig) -> str:
  cleaned = str(status or "").strip()
  if not cleaned:
    return ""
  labels = _context_label_ids(cleaned, split_nested_tag=True)
  for fallback, configured_values, aliases in _status_alias_groups(config):
    if _labels_match_aliases(labels, aliases):
      return _preferred_status_value(fallback, configured_values, aliases)
  return cleaned


def _status_from_context(
  tags: list[str] | tuple[str, ...],
  relative_path: str,
  config: ObsidianVaultConfig,
) -> str:
  tag_labels = _tag_labels(tags)
  directory_labels = _directory_labels(relative_path)
  if not tag_labels and not directory_labels:
    return ""

  status_groups = (
    ("draft", config.excluded_statuses, _STATUS_DRAFT_TAG_LABELS, _STATUS_DRAFT_DIRECTORY_LABELS),
    ("private", config.excluded_statuses, _STATUS_PRIVATE_TAG_LABELS, _STATUS_PRIVATE_DIRECTORY_LABELS),
    ("deprecated", config.excluded_statuses, _STATUS_DEPRECATED_TAG_LABELS, _STATUS_DEPRECATED_DIRECTORY_LABELS),
    ("canonical", config.allowed_statuses, _STATUS_CANONICAL_TAG_LABELS, _STATUS_CANONICAL_DIRECTORY_LABELS),
  )
  for fallback, configured_values, tag_aliases, directory_aliases in status_groups:
    if _labels_match_aliases(tag_labels, tag_aliases) or _labels_match_aliases(directory_labels, directory_aliases):
      return _preferred_status_value(fallback, configured_values, tag_aliases + directory_aliases)
  return ""


def _status_from_property_flags(
  config: ObsidianVaultConfig,
  *payloads: dict[str, Any],
) -> str:
  for fallback, configured_values, aliases in _status_property_groups(config):
    for payload in payloads:
      for alias in aliases:
        flag_value, explicit = _frontmatter_bool(payload, alias)
        if explicit and flag_value:
          return _preferred_status_value(fallback, configured_values, aliases)
  return ""


def _canonical_note_type_value(value: object) -> str:
  labels = _context_label_ids(value, split_nested_tag=True)
  if not labels:
    return ""
  for inferred_type, raw_candidates in _INFERRED_NOTE_TYPE_GROUPS:
    candidates = {_context_label_id(inferred_type)}
    candidates.update(_context_label_id(candidate) for candidate in raw_candidates if str(candidate or "").strip())
    if labels & candidates:
      return inferred_type
  return ""


def _context_body_note_labels(note_type: str, relative_path: str, tags: list[str] | tuple[str, ...]) -> set[str]:
  labels = [note_type, *[part for part in str(relative_path or "").replace("\\", "/").split("/") if part]]
  labels.extend(str(tag or "") for tag in tags)
  if relative_path:
    labels.append(Path(relative_path).stem)
  return {_context_label_id(label) for label in labels if str(label or "").strip()}


def _infer_note_type_from_labels(
  note_type: str | list[str] | tuple[str, ...],
  *,
  relative_path: str = "",
  tags: list[str] | tuple[str, ...] = (),
) -> str:
  explicit_values = list(note_type) if isinstance(note_type, (list, tuple)) else [note_type]
  explicit_values = [str(value or "").strip() for value in explicit_values if str(value or "").strip()]
  for value in explicit_values:
    canonical = _canonical_note_type_value(value)
    if canonical:
      return canonical
  if explicit_values:
    return explicit_values[0]
  path_parts = [part for part in str(relative_path or "").replace("\\", "/").split("/") if part]
  directory_parts = path_parts[:-1] if path_parts else []
  labels: set[str] = set()
  for label in directory_parts:
    labels.update(_context_label_ids(label))
  for tag in tags:
    labels.update(_context_label_ids(tag, split_nested_tag=True))
  for inferred_type, raw_candidates in _INFERRED_NOTE_TYPE_GROUPS:
    candidates = {_context_label_id(inferred_type)}
    candidates.update(_context_label_id(candidate) for candidate in raw_candidates if str(candidate or "").strip())
    if labels & candidates:
      return inferred_type
  return ""


def _frontmatter_context_groups(
  *,
  note_type: str = "",
  relative_path: str = "",
  tags: list[str] | tuple[str, ...] = (),
) -> tuple[tuple[str, tuple[str, ...]], ...]:
  groups: list[tuple[str, tuple[str, ...]]] = list(_CONTEXT_BODY_PROPERTY_GROUPS)
  labels = _context_body_note_labels(note_type, relative_path, tags)
  if labels & _CONTEXT_DEBT_NOTE_LABELS:
    groups.extend(_DEBT_CONTEXT_BODY_PROPERTY_GROUPS)
  if labels & _CONTEXT_ARC_NOTE_LABELS:
    groups.extend(_ARC_CONTEXT_BODY_PROPERTY_GROUPS)
  if labels & _CONTEXT_CHAPTER_NOTE_LABELS:
    groups.extend(_CHAPTER_NOTE_CONTEXT_BODY_PROPERTY_GROUPS)
  if labels & _CONTEXT_STYLE_NOTE_LABELS:
    groups.extend(_STYLE_CONTEXT_BODY_PROPERTY_GROUPS)
  if labels & _CONTEXT_XP_NOTE_LABELS:
    groups.extend(_XP_CONTEXT_BODY_PROPERTY_GROUPS)
  return tuple(groups)


def _frontmatter_context_body(
  *payloads: dict[str, Any],
  note_type: str = "",
  relative_path: str = "",
  tags: list[str] | tuple[str, ...] = (),
) -> str:
  lines: list[str] = []
  for label, keys in _frontmatter_context_groups(note_type=note_type, relative_path=relative_path, tags=tags):
    values: list[str] = []
    for payload in payloads:
      values.extend(_frontmatter_context_values(payload, *keys))
    values = _ordered_unique(values)
    if not values:
      continue
    if len(values) == 1:
      lines.append(f"{label}：{values[0]}")
      continue
    lines.append(f"{label}：")
    lines.extend(f"- {value}" for value in values[:8])
  relation_subpath_lines: list[str] = []
  for payload in payloads:
    relation_subpath_lines.extend(_frontmatter_relation_subpath_lines(payload, relative_path))
  relation_subpath_lines = _ordered_unique(relation_subpath_lines)
  if relation_subpath_lines:
    lines.append("关系小节：")
    lines.extend(f"- {value}" for value in relation_subpath_lines[:12])
  return "\n".join(lines).strip()


def _split_markdown_table_row(line: str) -> list[str]:
  text = str(line or "").strip()
  text = re.sub(r"^(?:>\s*)+", "", text).strip()
  if "|" not in text:
    return []
  cells: list[str] = []
  current: list[str] = []
  escape = False
  bracket_depth = 0
  paren_depth = 0
  for char in text:
    if escape:
      current.append(char)
      escape = False
      continue
    if char == "\\":
      current.append(char)
      escape = True
      continue
    if char == "[":
      bracket_depth += 1
      current.append(char)
      continue
    if char == "]" and bracket_depth > 0:
      bracket_depth -= 1
      current.append(char)
      continue
    if char == "(":
      paren_depth += 1
      current.append(char)
      continue
    if char == ")" and paren_depth > 0:
      paren_depth -= 1
      current.append(char)
      continue
    if char == "|" and bracket_depth == 0 and paren_depth == 0:
      cells.append("".join(current).strip())
      current = []
      continue
    current.append(char)
  cells.append("".join(current).strip())
  if cells and not cells[0]:
    cells = cells[1:]
  if cells and not cells[-1]:
    cells = cells[:-1]
  return cells


def _markdown_table_separator(cells: list[str]) -> bool:
  if not cells:
    return False
  for cell in cells:
    cleaned = re.sub(r"\s+", "", str(cell or ""))
    if not re.fullmatch(r":?-{3,}:?", cleaned):
      return False
  return True


def _table_context_label_for_header(
  header: str,
  *,
  note_type: str = "",
  relative_path: str = "",
  tags: list[str] | tuple[str, ...] = (),
) -> str:
  normalized = _frontmatter_key_id(header)
  if not normalized:
    return ""
  for label, keys in _frontmatter_context_groups(note_type=note_type, relative_path=relative_path, tags=tags):
    if normalized == _frontmatter_key_id(label):
      return label
    if normalized in {_frontmatter_key_id(key) for key in keys}:
      return label
  if normalized in {_frontmatter_key_id(key) for key in _REQUIRED_CONSTRAINT_LABELS}:
    return "必须出现"
  if normalized in {_frontmatter_key_id(key) for key in _FORBIDDEN_CONSTRAINT_LABELS}:
    return "禁止出现"
  return _relation_label_for_name(header)


def _markdown_table_cell_text(cell: str) -> str:
  cleaned = html_unescape(str(cell or ""))
  cleaned = cleaned.replace("\\|", "|")
  cleaned = re.sub(r"<\s*br\s*/?\s*>", "；", cleaned, flags=re.IGNORECASE)
  cleaned = re.sub(r"\s+", " ", cleaned).strip()
  cleaned = cleaned.strip("`")
  if cleaned in {"", "-", "—", "无", "暂无", "none", "None", "N/A"}:
    return ""
  return cleaned


def _markdown_table_context_body(
  body: str,
  *,
  note_type: str = "",
  relative_path: str = "",
  tags: list[str] | tuple[str, ...] = (),
) -> str:
  lines = str(body or "").replace("\r\n", "\n").split("\n")
  context_lines: list[str] = []
  index = 0
  while index + 1 < len(lines):
    headers = _split_markdown_table_row(lines[index])
    separator = _split_markdown_table_row(lines[index + 1])
    if not headers or not separator or not _markdown_table_separator(separator):
      index += 1
      continue
    labels = [
      _table_context_label_for_header(
        header,
        note_type=note_type,
        relative_path=relative_path,
        tags=tags,
      )
      for header in headers
    ]
    index += 2
    while index < len(lines):
      cells = _split_markdown_table_row(lines[index])
      if not cells:
        break
      if _markdown_table_separator(cells):
        index += 1
        continue
      for column, label in enumerate(labels):
        if not label or column >= len(cells):
          continue
        value = _markdown_table_cell_text(cells[column])
        if value:
          context_lines.append(f"{label}：{value}")
      index += 1
    continue
  return "\n".join(_ordered_unique(context_lines[:80])).strip()


def _frontmatter_link_targets(value: str, source_relative_path: str = "") -> list[str]:
  links: list[str] = []
  wiki_links = [
    target
    for match in _WIKI_LINK_WITH_EMBED_PATTERN.finditer(value)
    if (target := _knowledge_link_target(match.group(1), source_relative_path))
  ]
  markdown_links = _markdown_link_targets(str(value or ""), source_relative_path)
  if wiki_links or markdown_links:
    links.extend(wiki_links)
    links.extend(markdown_links)
  else:
    raw_value = str(value or "").strip().strip("\"'“”‘’")
    if "[[" in raw_value or "]]" in raw_value or "](" in raw_value:
      return []
    cleaned = _knowledge_link_target(raw_value, source_relative_path)
    if cleaned:
      links.append(cleaned)
  return _ordered_unique(links)


def _link_subpath_from_target(value: str) -> str:
  cleaned = _strip_markdown_link_title(str(value or "").strip())
  cleaned = cleaned.strip().strip("\"'“”‘’")
  if not cleaned or cleaned.startswith("#"):
    return ""
  obsidian_target, obsidian_subpath = _obsidian_uri_link_parts(cleaned)
  if obsidian_target and obsidian_subpath:
    return obsidian_subpath
  if _URL_SCHEME_PATTERN.match(cleaned) or cleaned.startswith("//"):
    return ""
  split_at = _find_unescaped_char(cleaned, {"#", "^"})
  if split_at < 0:
    return ""
  subpath = unquote(cleaned[split_at:].strip())
  subpath = re.sub(r"[\r\n\t]+", " ", subpath)
  subpath = re.sub(r"\s+", " ", subpath).strip()
  subpath = subpath.replace("[", "").replace("]", "").replace("|", " ")
  if not subpath or subpath == "#":
    return ""
  return _compact_text(subpath, 160)


def _wiki_link_target_part(inner: str) -> str:
  target = str(inner or "").strip()
  if "|" in target:
    target = target.rsplit("|", 1)[0].strip()
  return target


def _frontmatter_link_references_with_subpath(value: str, source_relative_path: str = "") -> list[str]:
  references: list[str] = []
  text = str(value or "")
  for match in re.finditer(r"!?\[\[([^\]]+)\]\]", text):
    raw_target = _wiki_link_target_part(match.group(1))
    target = _knowledge_link_target(raw_target, source_relative_path)
    subpath = _link_subpath_from_target(raw_target)
    if target and subpath:
      references.append(f"{target}{subpath}")
  for match in _iter_markdown_link_matches(text):
    target = _markdown_link_target(match.destination, source_relative_path)
    subpath = _link_subpath_from_target(match.destination)
    if target and subpath:
      references.append(f"{target}{subpath}")
  if references:
    return _ordered_unique(references)
  raw_value = text.strip().strip("\"'“”‘’")
  if "[[" in raw_value or "]]" in raw_value or "](" in raw_value:
    return []
  target = _knowledge_link_target(raw_value, source_relative_path)
  subpath = _link_subpath_from_target(raw_value)
  if target and subpath:
    references.append(f"{target}{subpath}")
  return _ordered_unique(references)


def _find_unescaped_char(value: str, chars: set[str], start: int = 0) -> int:
  escaped = False
  for index in range(max(0, start), len(value)):
    char = value[index]
    if escaped:
      escaped = False
      continue
    if char == "\\":
      escaped = True
      continue
    if char in chars:
      return index
  return -1


def _markdown_title_tail_is_complete(value: str) -> bool:
  tail = str(value or "").strip()
  if not tail:
    return False
  opener = tail[0]
  if opener in {"\"", "'"}:
    end = _find_unescaped_char(tail, {opener}, 1)
    return end > 0 and not tail[end + 1:].strip()
  if opener != "(":
    return False
  depth = 0
  escaped = False
  for index, char in enumerate(tail):
    if escaped:
      escaped = False
      continue
    if char == "\\":
      escaped = True
      continue
    if char == "(":
      depth += 1
    elif char == ")":
      depth -= 1
      if depth <= 0:
        return not tail[index + 1:].strip()
  return False


def _strip_markdown_link_title(raw_value: str) -> str:
  cleaned = str(raw_value or "").strip()
  if cleaned.startswith("<"):
    angle_end = _find_unescaped_char(cleaned, {">"}, 1)
    if angle_end > 0:
      return cleaned[1:angle_end].strip()

  index = 0
  while index < len(cleaned):
    char = cleaned[index]
    if char == "\\":
      index += 2
      continue
    if char.isspace() and _markdown_title_tail_is_complete(cleaned[index:]):
      return cleaned[:index].strip()
    index += 1
  return cleaned


def _strip_markdown_link_fragment(raw_value: str) -> str:
  cleaned = str(raw_value or "").strip()
  split_at = _find_unescaped_char(cleaned, {"#", "?"})
  if split_at >= 0:
    return cleaned[:split_at].strip()
  return cleaned


def _normalize_markdown_link_path(raw_value: str) -> str:
  text = str(raw_value or "")
  result: list[str] = []
  index = 0
  while index < len(text):
    char = text[index]
    if char != "\\":
      result.append(char)
      index += 1
      continue
    if index + 1 >= len(text):
      result.append("/")
      index += 1
      continue
    next_char = text[index + 1]
    if next_char in {"/", "\\"}:
      result.append("/")
      index += 2
      continue
    if next_char in _MARKDOWN_ESCAPABLE_CHARS or next_char.isspace():
      result.append(next_char)
      index += 2
      continue
    result.append("/")
    index += 1
  return "".join(result).strip()


def _markdown_link_destination(raw_value: str) -> str:
  cleaned = _strip_markdown_link_title(str(raw_value or "").strip())
  if not cleaned:
    return ""
  cleaned = cleaned.strip().strip("\"'“”‘’")
  if not cleaned or cleaned.startswith("#"):
    return ""
  obsidian_target = _obsidian_uri_link_target(cleaned)
  if obsidian_target:
    cleaned = f"/{obsidian_target.lstrip('/')}"
  elif _URL_SCHEME_PATTERN.match(cleaned) or cleaned.startswith("//"):
    return ""

  cleaned = _strip_markdown_link_fragment(cleaned)
  cleaned = _normalize_markdown_link_path(unquote(cleaned).strip())
  if not cleaned:
    return ""
  suffix = posixpath.splitext(cleaned)[1].lower()
  if suffix and suffix not in _KNOWLEDGE_LINK_SUFFIXES:
    return ""
  return cleaned


def _iter_markdown_link_matches(body: str) -> list[_MarkdownLinkMatch]:
  text = str(body or "")
  matches: list[_MarkdownLinkMatch] = []
  index = 0
  text_length = len(text)
  while index < text_length:
    label_start = text.find("[", index)
    if label_start < 0:
      break
    if label_start > 0 and text[label_start - 1] == "!":
      index = label_start + 1
      continue
    if label_start > 0 and text[label_start - 1] == "[":
      index = label_start + 1
      continue
    label_end = text.find("]", label_start + 1)
    if label_end < 0:
      break
    if label_end + 1 >= text_length or text[label_end + 1] != "(":
      index = label_start + 1
      continue
    destination_start = label_end + 2
    destination_end = destination_start
    depth = 0
    in_angle = False
    while destination_end < text_length:
      char = text[destination_end]
      if char == "\n":
        break
      if char == "\\":
        destination_end += 2
        continue
      if in_angle:
        if char == ">":
          in_angle = False
        destination_end += 1
        continue
      if char == "<" and destination_end == destination_start:
        in_angle = True
        destination_end += 1
        continue
      if char == "(":
        depth += 1
      elif char == ")":
        if depth <= 0:
          matches.append(_MarkdownLinkMatch(
            start=label_start,
            end=destination_end + 1,
            label=text[label_start + 1:label_end],
            destination=text[destination_start:destination_end],
            raw=text[label_start:destination_end + 1],
          ))
          index = destination_end + 1
          break
        depth -= 1
      destination_end += 1
    else:
      index = label_start + 1
      continue
    if destination_end >= text_length or text[destination_end] == "\n":
      index = label_start + 1
  return matches


def _markdown_link_target(raw_value: str, source_relative_path: str = "") -> str:
  destination = _markdown_link_destination(raw_value)
  if not destination:
    return ""
  root_relative = destination.startswith("/")
  if root_relative:
    destination = destination.lstrip("/")
  source_dir = posixpath.dirname(str(source_relative_path or "").replace("\\", "/"))
  if source_dir and not root_relative:
    destination = posixpath.normpath(posixpath.join(source_dir, destination))
  elif destination.startswith(".") or "/" in destination or root_relative:
    destination = posixpath.normpath(destination)
  while destination.startswith("./"):
    destination = destination[2:]
  if destination in {"", ".", ".."} or destination.startswith("../"):
    return ""
  return destination


def _markdown_link_targets(body: str, source_relative_path: str = "") -> list[str]:
  links: list[str] = []
  for match in _iter_markdown_link_matches(str(body or "")):
    target = _markdown_link_target(match.destination, source_relative_path)
    if target:
      links.append(target)
  return _ordered_unique(links)


def _external_url_value(value: str) -> str:
  cleaned = _strip_markdown_link_title(str(value or "").strip())
  cleaned = html_unescape(cleaned).strip().strip("<>").strip("\"'“”‘’")
  if cleaned.startswith("//"):
    cleaned = f"https:{cleaned}"
  if not re.match(r"(?i)^https?://", cleaned):
    return ""
  cleaned = re.sub(r"[\r\n\t]+", "", cleaned).strip()
  cleaned = cleaned.rstrip(".,;:，。；：、")
  if not cleaned:
    return ""
  return _compact_text(cleaned, 320)


def _external_urls_from_text(value: str) -> list[str]:
  text = _normalize_html_anchor_links(str(value or ""))
  urls: list[str] = []

  for match in _iter_markdown_link_matches(text):
    url = _external_url_value(match.destination)
    if url:
      urls.append(url)

  for raw_line in text.splitlines():
    match = re.match(r"^\s{0,3}\[([^\]\n]+)\]:\s*(.+?)\s*$", raw_line.rstrip("\r\n"))
    if not match or _markdown_reference_label_is_footnote(match.group(1)):
      continue
    url = _external_url_value(match.group(2).strip())
    if url:
      urls.append(url)

  for match in _EXTERNAL_URL_PATTERN.finditer(text):
    url = _external_url_value(match.group(0))
    if url:
      urls.append(url)
  return _ordered_unique(urls)


def _external_reference_label(value: object) -> str:
  label = html_unescape(str(value or ""))
  label = re.sub(r"<[^>]+>", " ", label)
  label = re.sub(r"[\[\]\r\n]+", " ", label)
  label = re.sub(r"\s+", " ", label).strip()
  label = label.strip(" \t:-：—–-\"'“”‘’「」『』<>")
  if not label or re.match(r"(?i)^https?://", label):
    return ""
  return _compact_text(label, 120)


def _external_link_key_display_label(value: object) -> str:
  key = _frontmatter_key_id(str(value or ""))
  if key.startswith("source") or key in {"来源链接", "资料链接", "资料来源", "来源", "来源资料"}:
    return "来源链接"
  if key.startswith("reference") or key.startswith("citation") or key in {"参考链接", "参考资料", "参考来源", "引用来源"}:
    return "参考链接"
  if key.startswith("research") or key in {"考据链接", "考据来源", "考据资料"}:
    return "考据链接"
  if key.startswith("external") or key in {"外部链接", "外部来源"}:
    return "外部链接"
  return ""


def _external_reference_text(label: object, url_value: object) -> str:
  url = _external_url_value(str(url_value or ""))
  if not url:
    return ""
  cleaned_label = _external_reference_label(label)
  if cleaned_label:
    return _compact_text(f"{cleaned_label}：{url}", 420)
  return url


def _external_line_label_before_url(line: str, url_start: int) -> str:
  prefix = str(line or "")[:url_start]
  prefix = re.sub(r"^\s*(?:[-*+]|\d+[.)]|[（(]?\d+[）)])\s*", "", prefix)
  prefix = re.sub(r"\[[^\]\n]*$", "", prefix)
  prefix = prefix.rsplit("]", 1)[-1] if "]" in prefix and "[" not in prefix.rsplit("]", 1)[-1] else prefix
  match = re.search(r"([^：:\n]{1,80})\s*[:：]\s*$", prefix)
  return match.group(1).strip() if match else ""


def _ordered_external_references(items: list[tuple[object, object]]) -> list[str]:
  references: list[str] = []
  labels: list[str] = []
  url_indexes: dict[str, int] = {}
  for raw_label, raw_url in items:
    url = _external_url_value(str(raw_url or ""))
    if not url:
      continue
    label = _external_reference_label(raw_label)
    key = url.casefold()
    if key in url_indexes:
      index = url_indexes[key]
      if label and not labels[index]:
        labels[index] = label
        references[index] = _external_reference_text(label, url)
      continue
    url_indexes[key] = len(references)
    labels.append(label)
    references.append(_external_reference_text(label, url))
  return references


def _external_references_from_text(value: str, fallback_label: str = "") -> list[str]:
  text = _normalize_html_anchor_links(str(value or ""))
  pairs: list[tuple[object, object]] = []

  reference_targets: dict[str, str] = {}
  for raw_line in text.splitlines():
    match = re.match(r"^\s{0,3}\[([^\]\n]+)\]:\s*(.+?)\s*$", raw_line.rstrip("\r\n"))
    if not match or _markdown_reference_label_is_footnote(match.group(1)):
      continue
    url = _external_url_value(match.group(2).strip())
    if url:
      reference_targets[_markdown_reference_label_key(match.group(1))] = url

  for match in _iter_markdown_link_matches(text):
    pairs.append((match.label, match.destination))

  for match in _iter_markdown_reference_link_matches(text, reference_targets):
    pairs.append((match.label, match.target))

  for raw_line in text.splitlines():
    definition = re.match(r"^\s{0,3}\[([^\]\n]+)\]:\s*(.+?)\s*$", raw_line.rstrip("\r\n"))
    if definition and not _markdown_reference_label_is_footnote(definition.group(1)):
      pairs.append((definition.group(1), definition.group(2).strip()))
    for match in _EXTERNAL_URL_PATTERN.finditer(raw_line):
      label = _external_line_label_before_url(raw_line, match.start()) or fallback_label
      pairs.append((label, match.group(0)))

  return _ordered_external_references(pairs)


def _external_links_from_value(value: Any) -> list[str]:
  if isinstance(value, list):
    links: list[str] = []
    for item in value:
      links.extend(_external_links_from_value(item))
    return _ordered_unique(links)
  if isinstance(value, dict):
    links: list[str] = []
    for item in value.values():
      links.extend(_external_links_from_value(item))
    return _ordered_unique(links)
  if isinstance(value, str) and value.strip():
    return _external_urls_from_text(value)
  return []


def _external_references_from_value(value: Any, fallback_label: str = "") -> list[str]:
  if isinstance(value, list):
    references: list[str] = []
    for item in value:
      references.extend(_external_references_from_value(item, fallback_label=fallback_label))
    return _ordered_unique(references)
  if isinstance(value, dict):
    explicit_label = ""
    for key in ("title", "label", "name", "标题", "名称", "来源", "资料名"):
      raw_value = value.get(key)
      if isinstance(raw_value, str) and raw_value.strip():
        explicit_label = raw_value.strip()
        break
    references: list[str] = []
    for key, item in value.items():
      if str(key or "") in {"title", "label", "name", "标题", "名称", "来源", "资料名"}:
        continue
      child_label = explicit_label or _external_link_key_display_label(key)
      if not child_label and isinstance(item, str) and _external_urls_from_text(item):
        child_label = str(key or "")
      references.extend(_external_references_from_value(item, fallback_label=child_label))
    return _ordered_unique(references)
  if isinstance(value, str) and value.strip():
    return _external_references_from_text(value, fallback_label=fallback_label)
  return []


def _frontmatter_external_links(payload: dict[str, Any], *keys: str) -> list[str]:
  links: list[str] = []
  for key in keys:
    found, value = _frontmatter_value(payload, key)
    if found:
      links.extend(_external_links_from_value(value))
  return _ordered_unique(links)


def _frontmatter_external_references(payload: dict[str, Any], *keys: str) -> list[str]:
  references: list[str] = []
  for key in keys:
    found, value = _frontmatter_value(payload, key)
    if found:
      references.extend(_external_references_from_value(value, fallback_label=_external_link_key_display_label(key)))
  return _ordered_unique(references)


def _body_external_links(body: str, source_relative_path: str = "") -> list[str]:
  return _external_urls_from_text(_ai_visible_body(body, source_relative_path))


def _body_external_references(body: str, source_relative_path: str = "") -> list[str]:
  return _external_references_from_text(_ai_visible_body(body, source_relative_path))


def _markdown_reference_label_key(value: str) -> str:
  return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _markdown_reference_label_is_footnote(label: str) -> bool:
  return str(label or "").strip().startswith("^")


def _markdown_reference_definitions(body: str, source_relative_path: str = "") -> list[_MarkdownReferenceDefinition]:
  text = str(body or "")
  definitions: list[_MarkdownReferenceDefinition] = []
  offset = 0
  for line in text.splitlines(keepends=True):
    raw_line = line.rstrip("\r\n")
    match = re.match(r"^\s{0,3}\[([^\]\n]+)\]:\s*(.+?)\s*$", raw_line)
    if match:
      label = match.group(1).strip()
      target = _markdown_link_target(match.group(2).strip(), source_relative_path)
      if label and target and not _markdown_reference_label_is_footnote(label):
        definitions.append(_MarkdownReferenceDefinition(
          label=label,
          target=target,
          start=offset,
          end=offset + len(raw_line),
          raw=raw_line,
        ))
    offset += len(line)
  return definitions


def _markdown_reference_target_map(
  body: str,
  source_relative_path: str = "",
) -> dict[str, str]:
  targets: dict[str, str] = {}
  for item in _markdown_reference_definitions(body, source_relative_path):
    key = _markdown_reference_label_key(item.label)
    if key and key not in targets:
      targets[key] = item.target
  return targets


def _iter_markdown_reference_link_matches(
  body: str,
  reference_targets: dict[str, str],
) -> list[_MarkdownReferenceLinkMatch]:
  if not reference_targets:
    return []
  text = str(body or "")
  matches: list[_MarkdownReferenceLinkMatch] = []
  index = 0
  text_length = len(text)
  while index < text_length:
    label_start = text.find("[", index)
    if label_start < 0:
      break
    if label_start > 0 and text[label_start - 1] == "!":
      index = label_start + 1
      continue
    if label_start > 0 and text[label_start - 1] == "[":
      index = label_start + 1
      continue
    label_end = text.find("]", label_start + 1)
    if label_end < 0:
      index = label_start + 1
      continue
    label = text[label_start + 1:label_end]
    next_char = text[label_end + 1] if label_end + 1 < text_length else ""
    if next_char != "[":
      if (
        label
        and not _markdown_reference_label_is_footnote(label)
        and next_char not in {"(", ":", "]"}
      ):
        target = reference_targets.get(_markdown_reference_label_key(label), "")
        if target:
          matches.append(_MarkdownReferenceLinkMatch(
            start=label_start,
            end=label_end + 1,
            label=label,
            reference=label,
            target=target,
            raw=text[label_start:label_end + 1],
          ))
          index = label_end + 1
          continue
      index = label_start + 1
      continue
    reference_start = label_end + 2
    reference_end = text.find("]", reference_start)
    if reference_end < 0:
      index = label_start + 1
      continue
    reference = text[reference_start:reference_end].strip() or label
    if _markdown_reference_label_is_footnote(reference):
      index = label_start + 1
      continue
    target = reference_targets.get(_markdown_reference_label_key(reference), "")
    if target:
      matches.append(_MarkdownReferenceLinkMatch(
        start=label_start,
        end=reference_end + 1,
        label=label,
        reference=reference,
        target=target,
        raw=text[label_start:reference_end + 1],
      ))
      index = reference_end + 1
      continue
    index = label_start + 1
  return matches


def _markdown_reference_link_targets(
  body: str,
  source_relative_path: str = "",
  reference_targets: dict[str, str] | None = None,
) -> list[str]:
  targets = reference_targets if reference_targets is not None else _markdown_reference_target_map(body, source_relative_path)
  return _ordered_unique([match.target for match in _iter_markdown_reference_link_matches(str(body or ""), targets)])


def _body_wiki_link_targets(body: str, source_relative_path: str = "") -> list[str]:
  return [
    target
    for match in _WIKI_LINK_WITH_EMBED_PATTERN.finditer(str(body or ""))
    if (target := _knowledge_link_target(match.group(1), source_relative_path))
  ]


def _body_embed_link_targets(body: str, source_relative_path: str = "") -> list[str]:
  visible_body = _ai_visible_body(body, source_relative_path)
  return _ordered_unique([
    target
    for match in _WIKI_LINK_WITH_EMBED_PATTERN.finditer(visible_body)
    if match.group(0).startswith("!") and (target := _knowledge_link_target(match.group(1), source_relative_path))
  ])


def _body_link_targets(
  body: str,
  source_relative_path: str = "",
  reference_targets: dict[str, str] | None = None,
) -> list[str]:
  visible_body = _ai_visible_body(body, source_relative_path)
  targets = reference_targets if reference_targets is not None else _markdown_reference_target_map(visible_body, source_relative_path)
  return _ordered_unique(
    _body_wiki_link_targets(visible_body, source_relative_path)
    + _markdown_link_targets(visible_body, source_relative_path)
    + _markdown_reference_link_targets(visible_body, source_relative_path, targets)
  )


def _frontmatter_graph_relation_items(payload: dict[str, Any], source_relative_path: str = "") -> list[tuple[str, str]]:
  relations: list[tuple[str, str]] = []

  def collect(raw_key: object, value: Any) -> None:
    relation_label = _FRONTMATTER_RELATION_LABEL_BY_KEY.get(_frontmatter_key_id(str(raw_key)))
    if relation_label:
      for raw_value in _frontmatter_list_from_value(value):
        for target in _frontmatter_link_targets(raw_value, source_relative_path):
          relations.append((relation_label, target))
    if isinstance(value, dict):
      for child_key, child_value in value.items():
        collect(child_key, child_value)
    elif isinstance(value, list):
      for item in value:
        if isinstance(item, dict):
          for child_key, child_value in item.items():
            collect(child_key, child_value)

  for raw_key, value in payload.items():
    collect(raw_key, value)
  seen: set[tuple[str, str]] = set()
  ordered: list[tuple[str, str]] = []
  for label, target in relations:
    key = (label, target)
    if key in seen:
      continue
    seen.add(key)
    ordered.append(key)
  return ordered


def _frontmatter_link_list(payload: dict[str, Any], source_relative_path: str = "") -> list[str]:
  return _ordered_unique([target for _label, target in _frontmatter_graph_relation_items(payload, source_relative_path)])


def _frontmatter_relation_subpath_lines(payload: dict[str, Any], source_relative_path: str = "") -> list[str]:
  lines: list[str] = []

  def collect(raw_key: object, value: Any) -> None:
    relation_label = _FRONTMATTER_RELATION_LABEL_BY_KEY.get(_frontmatter_key_id(str(raw_key)))
    if relation_label:
      for raw_value in _frontmatter_list_from_value(value):
        for reference in _frontmatter_link_references_with_subpath(raw_value, source_relative_path):
          lines.append(f"{relation_label}：[[{reference}]]")
    if isinstance(value, dict):
      for child_key, child_value in value.items():
        collect(child_key, child_value)
    elif isinstance(value, list):
      for item in value:
        if isinstance(item, dict):
          for child_key, child_value in item.items():
            collect(child_key, child_value)

  for raw_key, value in payload.items():
    collect(raw_key, value)
  return _ordered_unique(lines)


def _frontmatter_graph_relations(payload: dict[str, Any], source_relative_path: str = "") -> list[str]:
  return _ordered_unique([
    f"{label} -> {target}"
    for label, target in _frontmatter_graph_relation_items(payload, source_relative_path)
  ])


def _relation_label_for_name(value: str) -> str:
  cleaned = str(value or "").strip().rstrip(":：")
  return _FRONTMATTER_RELATION_LABEL_BY_KEY.get(_frontmatter_key_id(cleaned), "")


def _strip_body_marker(value: str) -> str:
  cleaned = str(value or "").strip()
  previous = ""
  while cleaned and cleaned != previous:
    previous = cleaned
    cleaned = re.sub(r"^\s*>\s?", "", cleaned)
    cleaned = re.sub(r"^\s*(?:[-*+]|\d+[.)]|[（(]?\d+[）)])\s*", "", cleaned)
    cleaned = re.sub(r"^\s*\[[ xX!?>/<*\-+~_=.]\]\s*", "", cleaned)
    cleaned = cleaned.strip()
  return cleaned


def _clean_relation_target(value: str) -> str:
  cleaned = _strip_body_marker(value)
  cleaned = re.split(r"\s*(?:[:：]|-->|→|=>)\s*", cleaned, maxsplit=1)[0]
  cleaned = re.split(r"\s+[-—–]\s+", cleaned, maxsplit=1)[0]
  cleaned = cleaned.strip(" \t\r\n`\"'“”‘’「」『』[]【】")
  cleaned = re.sub(r"\s+", " ", cleaned)
  if not cleaned or len(cleaned) > 80:
    return ""
  if cleaned in {"无", "暂无", "none", "None", "N/A"}:
    return ""
  return cleaned


def _body_relation_targets(
  value: str,
  source_relative_path: str = "",
  reference_targets: dict[str, str] | None = None,
) -> list[str]:
  text = _strip_body_marker(value)
  link_targets = _body_link_targets(text, source_relative_path, reference_targets)
  if link_targets:
    return link_targets
  if "[[" in text or "]]" in text or "](" in text or "][" in text:
    return []
  targets: list[str] = []
  for item in _frontmatter_list_from_value(text):
    cleaned = _clean_relation_target(item)
    if cleaned:
      targets.append(cleaned)
  return _ordered_unique(targets)


def _body_relation_line(line: str) -> tuple[str, str]:
  cleaned = _strip_body_marker(line)
  match = re.match(r"^([^:\n]{1,80})\s*(?:::|[:：])\s*(.*?)\s*$", cleaned)
  if not match:
    return "", ""
  relation_label = _relation_label_for_name(match.group(1))
  if not relation_label:
    return "", ""
  return relation_label, match.group(2).strip()


def _body_heading_relation_label(line: str) -> str:
  cleaned = re.sub(r"^\s*>\s?", "", str(line or "").strip())
  heading = re.match(r"^#{1,6}\s+(.+?)\s*$", cleaned)
  if not heading:
    return ""
  return _relation_label_for_name(heading.group(1))


def _body_graph_relation_items(body: str, source_relative_path: str = "") -> list[tuple[str, str]]:
  relations: list[tuple[str, str]] = []
  active_label = ""
  in_code_block = False
  visible_body = _ai_visible_body(body, source_relative_path)
  reference_targets = _markdown_reference_target_map(visible_body, source_relative_path)

  for raw_line in visible_body.replace("\r\n", "\n").split("\n"):
    line = raw_line.rstrip()
    if line.strip().startswith("```"):
      in_code_block = not in_code_block
      continue
    if in_code_block:
      continue

    stripped = re.sub(r"^\s*>\s?", "", line).strip()
    if not stripped:
      continue

    heading_label = _body_heading_relation_label(line)
    if heading_label:
      active_label = heading_label
      continue
    if stripped.startswith("#"):
      active_label = ""
      continue

    relation_label, value = _body_relation_line(line)
    if relation_label:
      active_label = relation_label
      if value:
        for target in _body_relation_targets(value, source_relative_path, reference_targets):
          relations.append((relation_label, target))
      continue

    if active_label and re.match(r"^\s*>?\s*(?:[-*+]|\d+[.)]|[（(]?\d+[）)])\s+", line):
      for target in _body_relation_targets(line, source_relative_path, reference_targets):
        relations.append((active_label, target))

  seen: set[tuple[str, str]] = set()
  ordered: list[tuple[str, str]] = []
  for label, target in relations:
    key = (label, target)
    if key in seen:
      continue
    seen.add(key)
    ordered.append(key)
  return ordered


def _body_link_list_from_graph_relations(body: str, source_relative_path: str = "") -> list[str]:
  return _ordered_unique([target for _label, target in _body_graph_relation_items(body, source_relative_path)])


def _body_graph_relations(body: str, source_relative_path: str = "") -> list[str]:
  return _ordered_unique([
    f"{label} -> {target}"
    for label, target in _body_graph_relation_items(body, source_relative_path)
  ])


def _add_inline_property_value(payload: dict[str, Any], key: str, value: str) -> None:
  cleaned_key = str(key or "").strip()
  if not cleaned_key:
    return
  parsed_value = _parse_scalar(str(value or "").strip())
  existing = payload.get(cleaned_key)
  if existing is None:
    payload[cleaned_key] = [parsed_value]
  elif isinstance(existing, list):
    existing.append(parsed_value)
  else:
    payload[cleaned_key] = [existing, parsed_value]


def _find_balanced_inline_property_close(line: str, start: int, opener: str, closer: str) -> int:
  quote = ""
  depth = 0
  index = start
  while index < len(line):
    char = line[index]
    if quote:
      if char == quote:
        quote = ""
      elif char == "\\" and index + 1 < len(line):
        index += 1
      index += 1
      continue
    if char in {"'", '"'}:
      quote = char
    elif char == "\\":
      index += 1
    elif char == opener:
      depth += 1
    elif char == closer:
      depth -= 1
      if depth == 0:
        return index
    index += 1
  return -1


def _inline_property_parts(content: str) -> tuple[str, str]:
  match = re.match(r"^\s*([^\[\](){}:\n]{1,80})::\s*(.*?)\s*$", content)
  if not match:
    return "", ""
  return match.group(1), match.group(2)


def _iter_balanced_inline_properties(line: str) -> list[tuple[str, str]]:
  properties: list[tuple[str, str]] = []
  index = 0
  while index < len(line):
    char = line[index]
    if char not in {"[", "("}:
      index += 1
      continue
    opener, closer = ("[", "]") if char == "[" else ("(", ")")
    close_index = _find_balanced_inline_property_close(line, index, opener, closer)
    if close_index < 0:
      index += 1
      continue
    key, value = _inline_property_parts(line[index + 1 : close_index])
    if key:
      properties.append((key, value))
      index = close_index + 1
      continue
    index += 1
  return properties


def _inline_property_payload_from_visible_text(body: str) -> dict[str, Any]:
  payload: dict[str, Any] = {}
  in_code_block = False
  for raw_line in str(body or "").replace("\r\n", "\n").split("\n"):
    line = raw_line.rstrip()
    if line.strip().startswith("```"):
      in_code_block = not in_code_block
      continue
    if in_code_block:
      continue
    content_line = _strip_body_marker(line)
    match = _INLINE_PROPERTY_LINE_PATTERN.match(content_line)
    if match:
      _add_inline_property_value(payload, match.group(1), match.group(2))
      continue
    for key, value in _iter_balanced_inline_properties(content_line):
      _add_inline_property_value(payload, key, value)
  return payload


def _body_inline_property_payload(body: str, source_relative_path: str = "") -> dict[str, Any]:
  return _inline_property_payload_from_visible_text(_ai_visible_body(body, source_relative_path))


def _parse_chinese_chapter_number(value: str) -> int:
  normalized = str(value or "").strip()
  if not normalized:
    return 0
  total = 0
  number = 0
  for char in normalized:
    if char in _CHINESE_CHAPTER_DIGITS:
      number = _CHINESE_CHAPTER_DIGITS[char]
      continue
    unit = _CHINESE_CHAPTER_UNITS.get(char)
    if unit is None:
      continue
    total += (number or 1) * unit
    number = 0
  return total + number


def _parse_chapter_number(value: object) -> int:
  if isinstance(value, bool):
    return 0
  if isinstance(value, (int, float)):
    number = int(value)
    return number if number > 0 else 0

  normalized = str(value or "").translate(_FULL_WIDTH_DIGIT_TABLE).strip()
  if not normalized:
    return 0
  digit_match = re.search(r"\d+", normalized)
  if digit_match:
    number = int(digit_match.group(0))
    return number if number > 0 else 0
  chinese_match = re.search(r"[零〇一二两三四五六七八九十百千]+", normalized)
  if chinese_match:
    return max(0, _parse_chinese_chapter_number(chinese_match.group(0)))
  return 0


def _chapter_index_from_source_id(value: object) -> int:
  cleaned = str(value or "").strip()
  if not cleaned:
    return 0
  match = _SOURCE_CHAPTER_ID_PATTERN.fullmatch(cleaned)
  if match:
    return _parse_chapter_number(match.group(1))
  match = _SOURCE_CHINESE_CHAPTER_ID_PATTERN.fullmatch(cleaned)
  if match:
    return _parse_chapter_number(match.group(1))
  return 0


def _source_chapter_indexes_from_payload(payload: dict[str, Any]) -> list[int]:
  indexes: list[int] = []
  for key in _SOURCE_CHAPTER_LABELS:
    found, value = _frontmatter_value(payload, key)
    if not found:
      continue
    for chapter_index in _chapter_numbers_from_value(value):
      if chapter_index > 0 and chapter_index not in indexes:
        indexes.append(chapter_index)
  return indexes


def _source_chapter_indexes_from_body(body: str) -> list[int]:
  indexes: list[int] = []
  for raw_line in _ai_visible_body(body).replace("\r\n", "\n").split("\n"):
    line = raw_line.strip()
    if not line:
      continue
    label = _constraint_label_at_line_start(line, _SOURCE_CHAPTER_LABELS)
    if not label:
      continue
    for chapter_index in _chapter_numbers_from_value(_line_value_after_label(line, label)):
      if chapter_index > 0 and chapter_index not in indexes:
        indexes.append(chapter_index)
  return indexes


def _ordered_source_chapter_indexes(*groups: list[int]) -> list[int]:
  indexes: list[int] = []
  for group in groups:
    for chapter_index in group:
      if chapter_index > 0 and chapter_index not in indexes:
        indexes.append(chapter_index)
  return indexes


def _source_chapter_scope(source_ids: list[str], source_chapter_indexes: list[int]) -> tuple[int, int, int]:
  chapter_indexes: list[int] = []
  for source_id in source_ids:
    chapter_index = _chapter_index_from_source_id(source_id)
    if chapter_index > 0:
      chapter_indexes.append(chapter_index)
  chapter_indexes.extend(index for index in source_chapter_indexes if index > 0)
  if chapter_indexes:
    return max(chapter_indexes), 0, 0
  return 0, 0, 0


def _scope_is_empty(scope: tuple[int, int, int]) -> bool:
  return not any(int(item or 0) > 0 for item in scope)


def _scope_open_start(scope: tuple[int, int, int]) -> int:
  chapter_start, chapter_end, reveal_after_chapter = scope
  starts: list[int] = []
  if chapter_start > 0:
    starts.append(chapter_start)
  if reveal_after_chapter > 0:
    starts.append(reveal_after_chapter + 1)
  if not starts and chapter_end > 0:
    starts.append(chapter_end)
  return min(starts) if starts else 0


def _merge_heuristic_scopes(path_scope: tuple[int, int, int], source_scope: tuple[int, int, int]) -> tuple[int, int, int]:
  if _scope_is_empty(source_scope):
    return path_scope
  if _scope_is_empty(path_scope):
    return source_scope
  path_start = _scope_open_start(path_scope)
  source_start = _scope_open_start(source_scope)
  chapter_start = max(path_start, source_start)
  if chapter_start <= 0:
    return path_scope
  source_end = int(source_scope[1] or 0)
  if source_end <= 0 and source_start > 0:
    path_single_chapter = int(path_scope[0] or 0) > 0 and int(path_scope[0] or 0) == int(path_scope[1] or 0)
    if path_single_chapter:
      return chapter_start, 0, 0
  path_end = int(path_scope[1] or 0)
  chapter_end = path_end if path_end >= chapter_start else 0
  return chapter_start, chapter_end, 0


def _scope_with_heuristic_fallbacks(
  primary_scopes: list[tuple[int, int, int]],
  path_scope: tuple[int, int, int],
  source_scope: tuple[int, int, int],
) -> tuple[int, int, int]:
  chapter_start, chapter_end, reveal_after_chapter = _scope_with_path_fallback(primary_scopes, (0, 0, 0))
  if chapter_start or chapter_end or reveal_after_chapter:
    return chapter_start, chapter_end, reveal_after_chapter
  return _merge_heuristic_scopes(path_scope, source_scope)


def _chapter_numbers_from_value(value: object) -> list[int]:
  numbers: list[int] = []
  if isinstance(value, list):
    for item in value:
      numbers.extend(_chapter_numbers_from_value(item))
    ordered: list[int] = []
    seen: set[int] = set()
    for number in numbers:
      if number in seen:
        continue
      seen.add(number)
      ordered.append(number)
    return ordered
  if isinstance(value, (int, float)) and not isinstance(value, bool):
    parsed = _parse_chapter_number(value)
    return [parsed] if parsed > 0 else []

  normalized = str(value or "").strip()
  if not normalized:
    return []
  for match in _CHAPTER_NUMBER_TOKEN_PATTERN.finditer(normalized):
    parsed = _parse_chapter_number(match.group(0))
    if parsed > 0:
      numbers.append(parsed)
  seen: set[int] = set()
  ordered: list[int] = []
  for number in numbers:
    if number in seen:
      continue
    seen.add(number)
    ordered.append(number)
  return ordered


def _open_ended_chapter_start_from_value(value: object) -> int:
  if isinstance(value, list):
    for item in value:
      chapter_start = _open_ended_chapter_start_from_value(item)
      if chapter_start:
        return chapter_start
    return 0
  if isinstance(value, bool) or isinstance(value, (int, float)):
    return 0

  normalized = str(value or "").translate(_FULL_WIDTH_DIGIT_TABLE).strip()
  if not normalized:
    return 0
  for pattern in (_OPEN_ENDED_ENGLISH_CHAPTER_VALUE_PATTERN, _OPEN_ENDED_CHAPTER_VALUE_PATTERN):
    match = pattern.search(normalized)
    if not match:
      continue
    chapter_start = _parse_chapter_number(match.group(1))
    if chapter_start:
      return chapter_start
  return 0


def _chapter_range_from_value(value: object) -> tuple[int, int]:
  open_ended_start = _open_ended_chapter_start_from_value(value)
  if open_ended_start:
    return open_ended_start, 0
  numbers = _chapter_numbers_from_value(value)
  if not numbers:
    return 0, 0
  if len(numbers) == 1:
    return numbers[0], numbers[0]
  start, end = numbers[0], numbers[1]
  if start > end:
    start, end = end, start
  return start, end


def _normalized_scope_tag(raw_tag: str) -> str:
  tag = str(raw_tag or "").strip().lstrip("#").replace("\\", "/").replace("／", "/")
  tag = tag.replace("：", ":")
  tag = re.sub(r"\s+", "", tag)
  return tag


def _tag_scope_value(raw_tag: str, labels: tuple[str, ...]) -> str:
  tag = _normalized_scope_tag(raw_tag)
  lowered = tag.lower()
  for raw_label in labels:
    label = raw_label.lower()
    if lowered.startswith(f"{label}/"):
      return tag[len(raw_label) + 1 :]
    if lowered.startswith(f"{label}:"):
      return tag[len(raw_label) + 1 :]
    if lowered.startswith(label) and len(tag) > len(raw_label):
      tail = tag[len(raw_label) :].lstrip("-_/：:")
      if tail:
        return tail
  return ""


def _plain_chapter_scope_from_tag(raw_tag: str) -> tuple[int, int]:
  tag = _normalized_scope_tag(raw_tag)
  lowered = tag.lower()
  match = _OPEN_ENDED_ENGLISH_CHAPTER_TAG_PATTERN.match(lowered)
  if match:
    chapter_start = _parse_chapter_number(match.group(1))
    if chapter_start:
      return chapter_start, 0

  match = _ENGLISH_CHAPTER_TAG_PATTERN.match(lowered)
  if match:
    chapter_start = _parse_chapter_number(match.group(1))
    chapter_end = _parse_chapter_number(match.group(2))
    if chapter_start and not chapter_end:
      chapter_end = chapter_start
    if chapter_start and chapter_end:
      if chapter_start > chapter_end:
        chapter_start, chapter_end = chapter_end, chapter_start
      return chapter_start, chapter_end

  if not (tag.startswith("第") or "章" in tag):
    match = _OPEN_ENDED_CHAPTER_TAG_PATTERN.match(tag)
    if not match:
      return 0, 0
    chapter_start = _parse_chapter_number(match.group(1))
    return (chapter_start, 0) if chapter_start else (0, 0)
  match = _OPEN_ENDED_CHAPTER_TAG_PATTERN.match(tag)
  if match:
    chapter_start = _parse_chapter_number(match.group(1))
    return (chapter_start, 0) if chapter_start else (0, 0)
  match = _PLAIN_CHAPTER_TAG_PATTERN.match(tag)
  if not match:
    return 0, 0
  chapter_start = _parse_chapter_number(match.group(1))
  chapter_end = _parse_chapter_number(match.group(2))
  if chapter_start and not chapter_end:
    chapter_end = chapter_start
  if chapter_start and chapter_end:
    if chapter_start > chapter_end:
      chapter_start, chapter_end = chapter_end, chapter_start
    return chapter_start, chapter_end
  return 0, 0


def _plain_reveal_after_from_tag(raw_tag: str) -> int:
  tag = _normalized_scope_tag(raw_tag)
  match = _REVEAL_AFTER_TAG_PATTERN.match(tag)
  if not match:
    return 0
  return _parse_chapter_number(match.group(1))


def _tags_chapter_scope(tags: list[str]) -> tuple[int, int, int]:
  chapter_start = 0
  chapter_end = 0
  reveal_after_chapter = 0
  for raw_tag in tags:
    if not chapter_start and not chapter_end:
      value = _tag_scope_value(raw_tag, _CHAPTER_RANGE_TAG_LABELS)
      if value:
        chapter_start, chapter_end = _chapter_range_from_value(value)
      if not chapter_start and not chapter_end:
        chapter_start, chapter_end = _plain_chapter_scope_from_tag(raw_tag)
    if not reveal_after_chapter:
      value = _tag_scope_value(raw_tag, _REVEAL_AFTER_CHAPTER_TAG_LABELS)
      if value:
        reveal_after_chapter = _parse_chapter_number(value)
      if not reveal_after_chapter:
        reveal_after_chapter = _plain_reveal_after_from_tag(raw_tag)
  if chapter_start > 0 and chapter_end > 0 and chapter_start > chapter_end:
    chapter_start, chapter_end = chapter_end, chapter_start
  return chapter_start, chapter_end, reveal_after_chapter


def _chapter_scope_from_path(relative_path: str, title: str = "") -> tuple[int, int, int]:
  normalized = str(relative_path or "").replace("\\", "/").strip()
  title = str(title or "").strip()
  parts = [part for part in normalized.split("/") if part]
  stems = [posixpath.splitext(part)[0] for part in parts]
  candidates = _ordered_unique([normalized, posixpath.splitext(normalized)[0], title, *stems])

  for value in candidates:
    for pattern in (_PATH_CHAPTER_RANGE_PATTERN, _PATH_CHAPTER_PATTERN):
      match = pattern.search(value)
      if not match:
        continue
      chapter_start, chapter_end = _chapter_range_from_value(match.group(0))
      if chapter_start or chapter_end:
        return chapter_start, chapter_end, 0

    match = _PATH_ENGLISH_CHAPTER_PATTERN.search(value)
    if match:
      chapter_start = _parse_chapter_number(match.group(1))
      chapter_end = _parse_chapter_number(match.group(2))
      if chapter_start and not chapter_end:
        chapter_end = chapter_start
      if chapter_start and chapter_end:
        if chapter_start > chapter_end:
          chapter_start, chapter_end = chapter_end, chapter_start
        return chapter_start, chapter_end, 0

  folder_markers = {"chapter", "chapters", "chapter_notes", "chapter-notes", "章节", "章节笔记", "正文"}
  for index, stem in enumerate(stems):
    if index == 0:
      continue
    parent = stems[index - 1].strip().lower()
    if parent not in folder_markers:
      continue
    chapter_start, chapter_end = _chapter_range_from_value(stem)
    if chapter_start or chapter_end:
      return chapter_start, chapter_end, 0

  return 0, 0, 0


def _scope_with_path_fallback(
  primary_scopes: list[tuple[int, int, int]],
  path_scope: tuple[int, int, int],
) -> tuple[int, int, int]:
  chapter_start = 0
  chapter_end = 0
  reveal_after_chapter = 0
  for start, end, reveal_after in primary_scopes:
    chapter_start = chapter_start or start
    chapter_end = chapter_end or end
    reveal_after_chapter = reveal_after_chapter or reveal_after
  if chapter_start or chapter_end or reveal_after_chapter:
    return chapter_start, chapter_end, reveal_after_chapter
  return path_scope


def _frontmatter_chapter_scope(payload: dict[str, Any]) -> tuple[int, int, int]:
  chapter_start = 0
  chapter_end = 0
  reveal_after_chapter = 0

  for key in _CHAPTER_RANGE_LABELS:
    found, value = _frontmatter_value(payload, key)
    if not found:
      continue
    chapter_start, chapter_end = _chapter_range_from_value(value)
    break

  for key in _CHAPTER_START_LABELS:
    found, value = _frontmatter_value(payload, key)
    if not found:
      continue
    chapter_start = _parse_chapter_number(value)
    break

  for key in _CHAPTER_END_LABELS:
    found, value = _frontmatter_value(payload, key)
    if not found:
      continue
    chapter_end = _parse_chapter_number(value)
    break

  for key in _REVEAL_AFTER_CHAPTER_LABELS:
    found, value = _frontmatter_value(payload, key)
    if not found:
      continue
    reveal_after_chapter = _parse_chapter_number(value)
    break

  if chapter_start > 0 and chapter_end > 0 and chapter_start > chapter_end:
    chapter_start, chapter_end = chapter_end, chapter_start
  return chapter_start, chapter_end, reveal_after_chapter


def _line_value_after_label(line: str, label: str) -> str:
  cleaned = _strip_body_marker(line)
  return re.sub(
    rf"^\s*{re.escape(label)}\s*(?:::|[:：])?",
    "",
    cleaned,
    flags=re.IGNORECASE,
  ).strip()


def _extract_body_chapter_scope(body: str) -> tuple[int, int, int]:
  chapter_start = 0
  chapter_end = 0
  reveal_after_chapter = 0

  for raw_line in _ai_visible_body(body).replace("\r\n", "\n").split("\n"):
    line = raw_line.strip()
    if not line:
      continue

    label = _constraint_label_at_line_start(line, _CHAPTER_RANGE_LABELS)
    if label:
      chapter_start, chapter_end = _chapter_range_from_value(_line_value_after_label(line, label))
      continue

    label = _constraint_label_at_line_start(line, _CHAPTER_START_LABELS)
    if label:
      chapter_start = _parse_chapter_number(_line_value_after_label(line, label))
      continue

    label = _constraint_label_at_line_start(line, _CHAPTER_END_LABELS)
    if label:
      chapter_end = _parse_chapter_number(_line_value_after_label(line, label))
      continue

    label = _constraint_label_at_line_start(line, _REVEAL_AFTER_CHAPTER_LABELS)
    if label:
      reveal_after_chapter = _parse_chapter_number(_line_value_after_label(line, label))
      continue

    match = re.search(
      r"第?\s*([0-9０-９零〇一二两三四五六七八九十百千]+)\s*章\s*(?:后|之后)\s*(?:可用|使用|启用|揭示)",
      line,
    )
    if match:
      reveal_after_chapter = _parse_chapter_number(match.group(1))

  if chapter_start > 0 and chapter_end > 0 and chapter_start > chapter_end:
    chapter_start, chapter_end = chapter_end, chapter_start
  return chapter_start, chapter_end, reveal_after_chapter


def _chapter_scope_parts(note: ObsidianNoteSummary) -> list[str]:
  parts: list[str] = []
  if note.chapter_start and note.chapter_end:
    if note.chapter_start == note.chapter_end:
      parts.append(f"适用章节：第 {note.chapter_start} 章")
    else:
      parts.append(f"适用章节：第 {note.chapter_start}-{note.chapter_end} 章")
  elif note.chapter_start:
    parts.append(f"适用章节：第 {note.chapter_start} 章起")
  elif note.chapter_end:
    parts.append(f"适用章节：第 {note.chapter_end} 章前")
  if note.reveal_after_chapter:
    parts.append(f"剧透边界：第 {note.reveal_after_chapter} 章后可用")
  return parts


def _clean_constraint_phrase(value: str) -> str:
  cleaned = _strip_body_marker(value)
  cleaned = cleaned.strip(" \t\r\n`\"'“”‘’「」『』[]【】")
  cleaned = re.sub(r"\s+", " ", cleaned)
  if not cleaned or len(cleaned) > 80:
    return ""
  if cleaned in {"无", "暂无", "none", "None", "N/A"}:
    return ""
  return cleaned


def _split_constraint_phrases(value: str) -> list[str]:
  normalized = str(value or "").replace("[[", "").replace("]]", "")
  pieces = _CONSTRAINT_VALUE_SPLIT_PATTERN.split(normalized)
  if len(pieces) == 1:
    pieces = re.split(r"\s{2,}", normalized)
  return _ordered_unique([_clean_constraint_phrase(item) for item in pieces])


def _constraint_label_at_line_start(line: str, labels: tuple[str, ...]) -> str | None:
  escaped = "|".join(re.escape(label) for label in labels)
  cleaned = _strip_body_marker(line)
  match = re.match(
    rf"^\s*({escaped})\s*(?:::|[:：]|$)",
    cleaned,
    flags=re.IGNORECASE,
  )
  if not match:
    return None
  return match.group(1)


def _extract_body_constraint_phrases(body: str) -> tuple[list[str], list[str]]:
  required: list[str] = []
  forbidden: list[str] = []
  active_section: str | None = None

  for raw_line in _ai_visible_body(body).replace("\r\n", "\n").split("\n"):
    line = raw_line.strip()
    if not line:
      continue

    heading_line = re.sub(r"^\s*(?:>\s*)+", "", line).strip()
    heading = re.match(r"^#{1,6}\s+(.+?)\s*$", heading_line)
    if heading:
      label = heading.group(1).strip().rstrip(":：")
      if label in _REQUIRED_CONSTRAINT_LABELS:
        active_section = "required"
      elif label in _FORBIDDEN_CONSTRAINT_LABELS:
        active_section = "forbidden"
      else:
        active_section = None
      continue

    label = _constraint_label_at_line_start(line, _REQUIRED_CONSTRAINT_LABELS)
    if label:
      value = re.sub(rf"^\s*(?:[-*+>]|\d+[.)]|[（(]?\d+[）)])?\s*(?:\[[ xX!?>/<*\-+~_=.]\]\s*)?{re.escape(label)}\s*(?:::|[:：])?", "", line, flags=re.IGNORECASE)
      required.extend(_split_constraint_phrases(value))
      continue

    label = _constraint_label_at_line_start(line, _FORBIDDEN_CONSTRAINT_LABELS)
    if label:
      value = re.sub(rf"^\s*(?:[-*+>]|\d+[.)]|[（(]?\d+[）)])?\s*(?:\[[ xX!?>/<*\-+~_=.]\]\s*)?{re.escape(label)}\s*(?:::|[:：])?", "", line, flags=re.IGNORECASE)
      forbidden.extend(_split_constraint_phrases(value))
      continue

    if active_section and (
      re.match(r"^\s*(?:>\s*)*(?:[-*+]|\d+[.)]|[（(]?\d+[）)])\s*(?:\[[ xX!?>/<*\-+~_=.]\]\s*)?", raw_line)
      or (raw_line.lstrip().startswith(">") and not _strip_body_marker(line).startswith("[!"))
    ):
      phrases = _split_constraint_phrases(line)
      if active_section == "required":
        required.extend(phrases)
      else:
        forbidden.extend(phrases)

  return _ordered_unique(required), _ordered_unique(forbidden)


def _frontmatter_bool(payload: dict[str, Any], *keys: str) -> tuple[bool, bool]:
  for key in keys:
    found, value = _frontmatter_value(payload, key)
    if not found:
      continue
    if isinstance(value, list):
      for item in value:
        candidates = item if isinstance(item, list) else [item]
        for candidate in candidates:
          parsed, explicit = _frontmatter_bool({key: candidate}, key)
          if explicit:
            return parsed, True
      continue
    if isinstance(value, bool):
      return value, True
    if isinstance(value, str):
      normalized = value.strip().lower()
      if normalized in {"true", "yes", "1", "是", "允许"}:
        return True, True
      if normalized in {"false", "no", "0", "否", "禁止"}:
        return False, True
  return True, False


def _frontmatter_ai_visibility(payload: dict[str, Any]) -> tuple[bool, bool]:
  for key in _AI_BLOCKED_LABELS:
    found, value = _frontmatter_value(payload, key)
    if not found:
      continue
    blocked_by_ai, explicit = _frontmatter_bool({key: value}, key)
    if explicit:
      return not blocked_by_ai, True
  return _frontmatter_bool(payload, *_AI_USABLE_LABELS)


def _first_heading(body: str) -> str:
  for line in body.splitlines():
    stripped = line.strip()
    if stripped.startswith("# "):
      return stripped[2:].strip()
  return ""


def _path_updated_at(path: Path) -> str | None:
  try:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
  except OSError:
    return None


def _file_node_target(value: object, source_relative_path: str = "") -> str:
  target = _markdown_link_target(str(value or ""), source_relative_path)
  if not target:
    return ""
  return target.replace("\\", "/")


def _canvas_file_subpath_from_file_value(value: object) -> str:
  cleaned = _strip_markdown_link_title(str(value or "").strip())
  if not cleaned:
    return ""
  cleaned = cleaned.strip().strip("\"'“”‘’")
  if not cleaned or _URL_SCHEME_PATTERN.match(cleaned) or cleaned.startswith("//"):
    return ""
  split_at = _find_unescaped_char(cleaned, {"#"})
  if split_at < 0:
    return ""
  return cleaned[split_at:].strip()


def _normalize_canvas_file_subpath(value: object) -> str:
  cleaned = unquote(str(value or "")).strip().strip("\"'“”‘’")
  if not cleaned:
    return ""
  cleaned = re.sub(r"[\r\n\t]+", " ", cleaned)
  cleaned = re.sub(r"\s+", " ", cleaned).strip()
  cleaned = cleaned.replace("[", "").replace("]", "").replace("|", " ")
  if not cleaned or cleaned.startswith("?"):
    return ""
  if cleaned.startswith("^"):
    cleaned = f"#{cleaned}"
  elif not cleaned.startswith("#"):
    cleaned = f"#{cleaned.lstrip('#')}"
  if cleaned == "#":
    return ""
  return _compact_text(cleaned, 160)


def _canvas_file_node_subpath(node: dict[str, object]) -> str:
  raw_subpath = node.get("subpath")
  if str(raw_subpath or "").strip():
    return _normalize_canvas_file_subpath(raw_subpath)
  return _normalize_canvas_file_subpath(_canvas_file_subpath_from_file_value(node.get("file")))


def _canvas_file_node_reference(node: dict[str, object], source_relative_path: str = "") -> str:
  target = _file_node_target(node.get("file"), source_relative_path)
  if not target:
    return ""
  return f"{target}{_canvas_file_node_subpath(node)}"


def _canvas_link_node_raw_url(node: dict[str, object]) -> str:
  if str(node.get("type") or "").strip().lower() != "link":
    return ""
  url = str(node.get("url") or "").strip()
  if not url:
    return ""
  url = re.sub(r"[\r\n\t]+", " ", url)
  url = re.sub(r"\s+", " ", url).strip()
  if not (_URL_SCHEME_PATTERN.match(url) or url.startswith("//")):
    return ""
  return url


def _canvas_link_node_url(node: dict[str, object]) -> str:
  url = _canvas_link_node_raw_url(node)
  if not url or _obsidian_uri_link_target(url):
    return ""
  return _compact_text(url, 500)


def _canvas_link_node_internal_target(node: dict[str, object], source_relative_path: str = "") -> str:
  url = _canvas_link_node_raw_url(node)
  if not url or not _obsidian_uri_link_target(url):
    return ""
  return _knowledge_link_target(url, source_relative_path)


def _canvas_link_node_internal_reference(node: dict[str, object], source_relative_path: str = "") -> str:
  target = _canvas_link_node_internal_target(node, source_relative_path)
  if not target:
    return ""
  return f"{target}{_link_subpath_from_target(_canvas_link_node_raw_url(node))}"


def _canvas_node_text(node: dict[str, object]) -> str:
  text = str(node.get("text") or node.get("label") or "").strip()
  return text


def _canvas_node_hidden_by_ai_marker(
  node: dict[str, object],
  source_relative_path: str,
  config: ObsidianVaultConfig,
) -> bool:
  raw_text = _canvas_node_text(node)
  if not raw_text.strip():
    return False
  if "::" not in raw_text and _explicit_hidden_obsidian_marker_present(raw_text):
    return True

  visible_text = _ai_visible_body(raw_text, source_relative_path, config)
  inline_fields = _body_inline_property_payload(visible_text, source_relative_path)
  inline_tags = _frontmatter_tag_list(inline_fields, "tags", "tag", "标签")
  tags = _ordered_unique(inline_tags + [match.group(1).strip() for match in _INLINE_TAG_PATTERN.finditer(visible_text)])
  usable_by_ai, usable_is_explicit = _frontmatter_ai_visibility(inline_fields)
  tag_usable_by_ai, tag_usable_is_explicit = _frontmatter_ai_visibility_from_tags(tags)
  if tag_usable_is_explicit:
    if not tag_usable_by_ai:
      return True
    if not usable_is_explicit:
      usable_by_ai, usable_is_explicit = True, True
  if usable_is_explicit and not usable_by_ai:
    return True

  explicit_status = _frontmatter_string(inline_fields, "status", "状态")
  status = explicit_status or _status_from_property_flags(config, inline_fields)
  return bool(status and not _status_allowed(status, config))


def _canvas_node_label(node: dict[str, object], source_relative_path: str = "") -> str:
  file_target = _file_node_target(node.get("file"), source_relative_path)
  if file_target:
    return Path(file_target).stem or file_target
  text = _ai_visible_body(_canvas_node_text(node))
  if text:
    return _compact_text(text, 40)
  link_url = _canvas_link_node_url(node)
  if link_url:
    return _compact_text(link_url, 40)
  link_target = _canvas_link_node_internal_target(node, source_relative_path)
  if link_target:
    return Path(link_target).stem or link_target
  node_id = str(node.get("id") or "").strip()
  return node_id


def _canvas_edge_label(edge: dict[str, object]) -> str:
  label = _ai_visible_body(str(edge.get("label") or edge.get("text") or "")).strip()
  if not label:
    return "Canvas 关系"
  return _compact_text(label, 40)


def _canvas_node_number(node: dict[str, object], key: str) -> float | None:
  value = node.get(key)
  if isinstance(value, bool):
    return None
  if isinstance(value, (int, float)):
    return float(value)
  if isinstance(value, str):
    try:
      return float(value.strip())
    except ValueError:
      return None
  return None


def _canvas_node_bounds(node: dict[str, object]) -> tuple[float, float, float, float] | None:
  x = _canvas_node_number(node, "x")
  y = _canvas_node_number(node, "y")
  width = _canvas_node_number(node, "width")
  height = _canvas_node_number(node, "height")
  if x is None or y is None or width is None or height is None:
    return None
  if width == 0 or height == 0:
    return None
  left = min(x, x + width)
  right = max(x, x + width)
  top = min(y, y + height)
  bottom = max(y, y + height)
  return left, top, right, bottom


def _canvas_node_center(node: dict[str, object]) -> tuple[float, float] | None:
  x = _canvas_node_number(node, "x")
  y = _canvas_node_number(node, "y")
  if x is None or y is None:
    return None
  width = _canvas_node_number(node, "width") or 0.0
  height = _canvas_node_number(node, "height") or 0.0
  return x + width / 2, y + height / 2


def _canvas_node_inside_bounds(node: dict[str, object], bounds: tuple[float, float, float, float]) -> bool:
  center = _canvas_node_center(node)
  if center is None:
    return False
  x, y = center
  left, top, right, bottom = bounds
  return left <= x <= right and top <= y <= bottom


def _canvas_body_from_payload(
  payload: dict[str, object],
  relative: str,
  config: ObsidianVaultConfig,
) -> tuple[str, list[str], list[str]]:
  raw_nodes = payload.get("nodes") if isinstance(payload.get("nodes"), list) else []
  raw_edges = payload.get("edges") if isinstance(payload.get("edges"), list) else []
  candidate_nodes = [item for item in raw_nodes if isinstance(item, dict)]
  hidden_group_bounds = [
    bounds
    for node in candidate_nodes
    if str(node.get("type") or "").strip().lower() == "group"
    and _canvas_node_hidden_by_ai_marker(node, relative, config)
    and (bounds := _canvas_node_bounds(node)) is not None
  ]
  nodes = [
    item
    for item in candidate_nodes
    if not _canvas_node_hidden_by_ai_marker(item, relative, config)
    and not any(_canvas_node_inside_bounds(item, bounds) for bounds in hidden_group_bounds)
  ]
  edges = [item for item in raw_edges if isinstance(item, dict)]
  node_by_id = {
    str(node.get("id") or "").strip(): node
    for node in nodes
    if str(node.get("id") or "").strip()
  }
  node_labels = {
    node_id: _canvas_node_label(node, relative)
    for node_id, node in node_by_id.items()
  }
  node_file_targets = {
    node_id: _file_node_target(node.get("file"), relative)
    for node_id, node in node_by_id.items()
  }
  node_file_references = {
    node_id: _canvas_file_node_reference(node, relative)
    for node_id, node in node_by_id.items()
  }
  node_link_urls = {
    node_id: _canvas_link_node_url(node)
    for node_id, node in node_by_id.items()
  }
  node_link_targets = {
    node_id: _canvas_link_node_internal_target(node, relative)
    for node_id, node in node_by_id.items()
  }
  node_link_references = {
    node_id: _canvas_link_node_internal_reference(node, relative)
    for node_id, node in node_by_id.items()
  }

  text_nodes: list[str] = []
  link_nodes: list[str] = []
  for node in nodes:
    text = _ai_visible_body(_canvas_node_text(node), relative, config)
    if text:
      text_nodes.append(text)
    node_id = str(node.get("id") or "").strip()
    link_url = node_link_urls.get(node_id, "")
    if link_url:
      link_label = _ai_visible_body(_canvas_node_text(node), relative, config).strip()
      link_nodes.append(f"- {link_label}: {link_url}" if link_label else f"- {link_url}")
  file_targets = _ordered_unique([target for target in node_file_targets.values() if target])
  file_references = _ordered_unique([target for target in node_file_references.values() if target])
  link_targets = _ordered_unique([target for target in node_link_targets.values() if target])
  link_references = _ordered_unique([target for target in node_link_references.values() if target])
  body_links = _ordered_unique(list(file_targets) + list(link_targets))
  graph_relations: list[str] = []
  edge_lines: list[str] = []
  group_lines: list[str] = []

  for edge in edges:
    from_id = str(edge.get("fromNode") or edge.get("from") or "").strip()
    to_id = str(edge.get("toNode") or edge.get("to") or "").strip()
    if (from_id and from_id not in node_by_id) or (to_id and to_id not in node_by_id):
      continue
    from_label = node_labels.get(from_id, from_id)
    to_label = node_labels.get(to_id, to_id)
    from_target = node_file_targets.get(from_id, "") or node_link_targets.get(from_id, "")
    to_target = node_file_targets.get(to_id, "") or node_link_targets.get(to_id, "")
    from_reference = node_file_references.get(from_id, "") or node_link_references.get(from_id, "") or from_target
    to_reference = node_file_references.get(to_id, "") or node_link_references.get(to_id, "") or to_target
    from_link_url = node_link_urls.get(from_id, "")
    to_link_url = node_link_urls.get(to_id, "")
    edge_label = _canvas_edge_label(edge)
    if to_target:
      relation_label = f"{edge_label}：{from_label}" if from_label else edge_label
      graph_relations.append(f"{relation_label} -> {to_target}")
    if from_target or to_target or from_link_url or to_link_url:
      left = f"[[{from_reference}]]" if from_target else (f"<{from_link_url}>" if from_link_url else from_label)
      right = f"[[{to_reference}]]" if to_target else (f"<{to_link_url}>" if to_link_url else to_label)
      edge_lines.append(f"- {left} --{edge_label}--> {right}")

  for group_id, group_node in node_by_id.items():
    if str(group_node.get("type") or "").strip().lower() != "group":
      continue
    group_label = _ai_visible_body(_canvas_node_text(group_node), relative, config).strip()
    if not group_label:
      continue
    group_bounds = _canvas_node_bounds(group_node)
    if group_bounds is None:
      continue
    group_label = _compact_text(group_label, 40)
    group_members: list[str] = []
    for node_id, node in node_by_id.items():
      if node_id == group_id or str(node.get("type") or "").strip().lower() == "group":
        continue
      if not _canvas_node_inside_bounds(node, group_bounds):
        continue
      file_target = node_file_targets.get(node_id, "")
      if file_target:
        file_reference = node_file_references.get(node_id, "") or file_target
        group_members.append(f"[[{file_reference}]]")
        graph_relations.append(f"Canvas 分组：{group_label} -> {file_target}")
        continue
      link_target = node_link_targets.get(node_id, "")
      if link_target:
        link_reference = node_link_references.get(node_id, "") or link_target
        group_members.append(f"[[{link_reference}]]")
        graph_relations.append(f"Canvas 分组：{group_label} -> {link_target}")
        continue
      link_url = node_link_urls.get(node_id, "")
      if link_url:
        group_members.append(f"<{link_url}>")
        continue
      node_label = node_labels.get(node_id, "").strip()
      if node_label:
        group_members.append(node_label)
    group_members = _ordered_unique(group_members)
    if group_members:
      group_lines.append(f"- {group_label}: {'、'.join(group_members[:20])}")

  for text in text_nodes:
    body_links.extend(_body_link_targets(text, relative))

  body_parts: list[str] = []
  if text_nodes:
    body_parts.append("Canvas 文本：\n" + "\n\n".join(text_nodes[:12]))
  if link_nodes:
    body_parts.append("Canvas 链接节点：\n" + "\n".join(_ordered_unique(link_nodes)[:80]))
  if file_references:
    body_parts.append("Canvas 文件节点：\n" + "\n".join(f"- [[{target}]]" for target in file_references[:80]))
  if link_references:
    body_parts.append("Canvas 内部链接节点：\n" + "\n".join(f"- [[{target}]]" for target in link_references[:80]))
  if edge_lines:
    body_parts.append("Canvas 关系：\n" + "\n".join(edge_lines[:80]))
  if group_lines:
    body_parts.append("Canvas 分组：\n" + "\n".join(group_lines[:80]))
  body = "\n\n".join(body_parts).strip()
  return body, _ordered_unique(body_links), _ordered_unique(graph_relations)


def _status_allowed(status: str, config: ObsidianVaultConfig) -> bool:
  normalized = _normalized_status_value(status, config)
  lowered = normalized.lower()
  excluded = {
    _normalized_status_value(item, config).lower()
    for item in config.excluded_statuses
    if str(item or "").strip()
  }
  if lowered and lowered in excluded:
    return False
  allowed = {
    _normalized_status_value(item, config).lower()
    for item in config.allowed_statuses
    if str(item or "").strip()
  }
  if not allowed:
    return True
  if lowered:
    return lowered in allowed
  return config.include_without_status


def _canvas_record_from_path(vault_dir: Path, path: Path, config: ObsidianVaultConfig) -> ObsidianNoteRecord | None:
  try:
    raw_text = _decode_text_bytes(path.read_bytes())
    payload = json.loads(raw_text)
  except (OSError, json.JSONDecodeError):
    return None
  if not isinstance(payload, dict):
    return None

  relative = path.relative_to(vault_dir).as_posix()
  body, links, graph_relations = _canvas_body_from_payload(payload, relative, config)
  if not body and not links:
    return None
  table_context_body = _markdown_table_context_body(
    body,
    note_type="canvas",
    relative_path=relative,
  )
  if table_context_body:
    body = "\n\n".join(part for part in [table_context_body, body] if part).strip()

  inline_fields = _body_inline_property_payload(body, relative)
  inline_tags = _frontmatter_tag_list(inline_fields, "tags", "tag", "标签")
  tags = _ordered_unique(inline_tags + [match.group(1).strip() for match in _INLINE_TAG_PATTERN.finditer(body)])
  usable_by_ai, usable_is_explicit = _frontmatter_ai_visibility(inline_fields)
  tag_usable_by_ai, tag_usable_is_explicit = _frontmatter_ai_visibility_from_tags(tags)
  if tag_usable_is_explicit:
    if not tag_usable_by_ai:
      usable_by_ai, usable_is_explicit = False, True
    elif not usable_is_explicit:
      usable_by_ai, usable_is_explicit = True, True
  if not usable_by_ai:
    return None
  if config.require_usable_by_ai and not usable_is_explicit:
    return None
  explicit_status = _frontmatter_string(inline_fields, "status", "状态")
  status = explicit_status or _status_from_property_flags(config, inline_fields) or _status_from_context(tags, relative, config)
  if not _status_allowed(status, config):
    return None

  source_ids = _ordered_unique(_frontmatter_list(inline_fields, *_SOURCE_ID_LABELS))[:30]
  source_chapter_indexes = _ordered_source_chapter_indexes(
    _source_chapter_indexes_from_payload(inline_fields),
    _source_chapter_indexes_from_body(body),
  )
  body_required_phrases, body_forbidden_phrases = _extract_body_constraint_phrases(body)
  inline_required_phrases = _frontmatter_list(inline_fields, *_REQUIRED_CONSTRAINT_LABELS, "必需")
  inline_forbidden_phrases = _frontmatter_list(inline_fields, *_FORBIDDEN_CONSTRAINT_LABELS)
  body_chapter_start, body_chapter_end, body_reveal_after = _extract_body_chapter_scope(body)
  inline_chapter_start, inline_chapter_end, inline_reveal_after = _frontmatter_chapter_scope(inline_fields)
  tag_chapter_start, tag_chapter_end, tag_reveal_after = _tags_chapter_scope(tags)
  source_chapter_scope = _source_chapter_scope(source_ids, source_chapter_indexes)
  title = _frontmatter_string(inline_fields, *_TITLE_LABELS) or path.stem
  path_chapter_scope = _chapter_scope_from_path(relative, title)
  chapter_start, chapter_end, reveal_after_chapter = _scope_with_heuristic_fallbacks(
    [
      (inline_chapter_start, inline_chapter_end, inline_reveal_after),
      (body_chapter_start, body_chapter_end, body_reveal_after),
      (tag_chapter_start, tag_chapter_end, tag_reveal_after),
    ],
    path_chapter_scope,
    source_chapter_scope,
  )
  summary_text = _frontmatter_string(inline_fields, *_SUMMARY_LABELS) or _compact_text(body, 500)
  keywords = _frontmatter_list(inline_fields, *_KEYWORD_LABELS)
  aliases = _frontmatter_list(inline_fields, "aliases", "alias", "别名")
  inline_links = _frontmatter_link_list(inline_fields, relative)
  body_relation_links = _body_link_list_from_graph_relations(body, relative)
  embedded_links = _body_embed_link_targets(body, relative)
  external_links = _ordered_unique(
    _frontmatter_external_links(inline_fields, *_EXTERNAL_LINK_LABELS) + _body_external_links(body, relative)
  )
  external_references = _ordered_unique(
    _frontmatter_external_references(inline_fields, *_EXTERNAL_LINK_LABELS)
    + _body_external_references(body, relative)
  )
  graph_relations = _ordered_unique(
    graph_relations + _frontmatter_graph_relations(inline_fields, relative) + _body_graph_relations(body, relative)
  )
  summary = ObsidianNoteSummary(
    title=title.strip()[:120] or path.stem,
    relative_path=relative,
    note_type="canvas",
    status=status.strip()[:60],
    summary=summary_text,
    keywords=_ordered_unique(keywords)[:30],
    tags=_ordered_unique(tags)[:30],
    links=_ordered_unique(links + inline_links + body_relation_links)[:80],
    embedded_links=embedded_links[:40],
    external_links=external_links[:40],
    external_references=external_references[:40],
    graph_relations=graph_relations[:80],
    aliases=_ordered_unique(aliases)[:30],
    required_phrases=_ordered_unique(inline_required_phrases + body_required_phrases)[:30],
    forbidden_phrases=_ordered_unique(inline_forbidden_phrases + body_forbidden_phrases)[:30],
    chapter_start=chapter_start,
    chapter_end=chapter_end,
    reveal_after_chapter=reveal_after_chapter,
    preview=_compact_text(body, limit=180),
    updated_at=_path_updated_at(path),
    usable_by_ai=usable_by_ai,
    source_key=obsidian_source_key(relative),
    source_ids=source_ids,
    source_chapters=source_chapter_indexes[:30],
  )
  content = build_obsidian_knowledge_content(summary, body)
  return ObsidianNoteRecord(summary=summary, content=content, body=body)


def _note_record_from_path(vault_dir: Path, path: Path, config: ObsidianVaultConfig) -> ObsidianNoteRecord | None:
  suffix = path.suffix.lower()
  if suffix == ".canvas":
    return _canvas_record_from_path(vault_dir, path, config)
  if suffix != ".md":
    return None

  try:
    raw_text = _decode_text_bytes(path.read_bytes())
  except OSError:
    return None

  frontmatter, body = _parse_frontmatter(raw_text)
  relative = path.relative_to(vault_dir).as_posix()
  body = _ai_visible_body(body, relative, config)
  inline_fields = _body_inline_property_payload(body, relative)
  frontmatter_tags = _frontmatter_tag_list(frontmatter, "tags", "tag", "标签")
  inline_property_tags = _frontmatter_tag_list(inline_fields, "tags", "tag", "标签")
  inline_tags = [match.group(1).strip() for match in _INLINE_TAG_PATTERN.finditer(body)]
  tags = _ordered_unique(frontmatter_tags + inline_property_tags + inline_tags)
  usable_by_ai, usable_is_explicit = _frontmatter_ai_visibility(frontmatter)
  if usable_is_explicit is False:
    usable_by_ai, usable_is_explicit = _frontmatter_ai_visibility(inline_fields)
  tag_usable_by_ai, tag_usable_is_explicit = _frontmatter_ai_visibility_from_tags(tags)
  if tag_usable_is_explicit:
    if not tag_usable_by_ai:
      usable_by_ai, usable_is_explicit = False, True
    elif not usable_is_explicit:
      usable_by_ai, usable_is_explicit = True, True
  if not usable_by_ai:
    return None
  if config.require_usable_by_ai and not usable_is_explicit:
    return None

  explicit_status = _frontmatter_string(frontmatter, "status", "状态") or _frontmatter_string(
    inline_fields, "status", "状态"
  )
  status = (
    explicit_status
    or _status_from_property_flags(config, frontmatter, inline_fields)
    or _status_from_context(tags, relative, config)
  )
  if not _status_allowed(status, config):
    return None

  title = (
    _frontmatter_string(frontmatter, *_TITLE_LABELS)
    or _first_heading(body)
    or _frontmatter_string(inline_fields, *_TITLE_LABELS)
    or path.stem
  )
  note_type_values = _ordered_unique(
    _frontmatter_list(frontmatter, "type", "kind", "类型") + _frontmatter_list(inline_fields, "type", "kind", "类型")
  )
  note_type = _infer_note_type_from_labels(
    note_type_values,
    relative_path=relative,
    tags=tags,
  )
  context_body = _frontmatter_context_body(
    frontmatter,
    inline_fields,
    note_type=note_type,
    relative_path=relative,
    tags=tags,
  )
  table_context_body = _markdown_table_context_body(
    body,
    note_type=note_type,
    relative_path=relative,
    tags=tags,
  )
  if context_body or table_context_body:
    body = "\n\n".join(part for part in [context_body, table_context_body, body] if part).strip()
  summary_text = _frontmatter_string(frontmatter, *_SUMMARY_LABELS) or _frontmatter_string(inline_fields, *_SUMMARY_LABELS)
  keywords = _frontmatter_list(frontmatter, *_KEYWORD_LABELS) + _frontmatter_list(inline_fields, *_KEYWORD_LABELS)
  source_ids = _ordered_unique(
    _frontmatter_list(frontmatter, *_SOURCE_ID_LABELS) + _frontmatter_list(inline_fields, *_SOURCE_ID_LABELS)
  )[:30]
  source_chapter_indexes = _ordered_source_chapter_indexes(
    _source_chapter_indexes_from_payload(frontmatter),
    _source_chapter_indexes_from_payload(inline_fields),
    _source_chapter_indexes_from_body(body),
  )
  body_links = _body_link_targets(body, relative)
  embedded_links = _body_embed_link_targets(body, relative)
  external_links = _ordered_unique(
    _frontmatter_external_links(frontmatter, *_EXTERNAL_LINK_LABELS)
    + _frontmatter_external_links(inline_fields, *_EXTERNAL_LINK_LABELS)
    + _body_external_links(body, relative)
  )
  external_references = _ordered_unique(
    _frontmatter_external_references(frontmatter, *_EXTERNAL_LINK_LABELS)
    + _frontmatter_external_references(inline_fields, *_EXTERNAL_LINK_LABELS)
    + _body_external_references(body, relative)
  )
  body_relation_links = _body_link_list_from_graph_relations(body, relative)
  graph_relations = _ordered_unique(
    _frontmatter_graph_relations(frontmatter, relative)
    + _frontmatter_graph_relations(inline_fields, relative)
    + _body_graph_relations(body, relative)
  )
  links = _ordered_unique(
    body_links + _frontmatter_link_list(frontmatter, relative) + _frontmatter_link_list(inline_fields, relative) + body_relation_links
  )
  aliases = _frontmatter_list(frontmatter, "aliases", "alias", "别名") + _frontmatter_list(inline_fields, "aliases", "alias", "别名")
  body_required_phrases, body_forbidden_phrases = _extract_body_constraint_phrases(body)
  frontmatter_chapter_start, frontmatter_chapter_end, frontmatter_reveal_after = _frontmatter_chapter_scope(frontmatter)
  inline_chapter_start, inline_chapter_end, inline_reveal_after = _frontmatter_chapter_scope(inline_fields)
  body_chapter_start, body_chapter_end, body_reveal_after = _extract_body_chapter_scope(body)
  tag_chapter_start, tag_chapter_end, tag_reveal_after = _tags_chapter_scope(tags)
  source_chapter_scope = _source_chapter_scope(source_ids, source_chapter_indexes)
  path_chapter_scope = _chapter_scope_from_path(relative, title)
  chapter_start, chapter_end, reveal_after_chapter = _scope_with_heuristic_fallbacks(
    [
      (frontmatter_chapter_start, frontmatter_chapter_end, frontmatter_reveal_after),
      (inline_chapter_start, inline_chapter_end, inline_reveal_after),
      (body_chapter_start, body_chapter_end, body_reveal_after),
      (tag_chapter_start, tag_chapter_end, tag_reveal_after),
    ],
    path_chapter_scope,
    source_chapter_scope,
  )
  required_phrases = _ordered_unique(_frontmatter_list(
    frontmatter,
    *_REQUIRED_CONSTRAINT_LABELS,
    "必需",
  ) + _frontmatter_list(
    inline_fields,
    *_REQUIRED_CONSTRAINT_LABELS,
    "必需",
  ) + body_required_phrases)
  forbidden_phrases = _ordered_unique(_frontmatter_list(
    frontmatter,
    *_FORBIDDEN_CONSTRAINT_LABELS,
  ) + _frontmatter_list(
    inline_fields,
    *_FORBIDDEN_CONSTRAINT_LABELS,
  ) + body_forbidden_phrases)
  summary = ObsidianNoteSummary(
    title=title.strip()[:120] or path.stem,
    relative_path=relative,
    note_type=note_type.strip()[:60],
    status=status.strip()[:60],
    summary=summary_text.strip()[:500],
    keywords=_ordered_unique(keywords)[:30],
    tags=tags[:30],
    links=_ordered_unique(links)[:80],
    embedded_links=embedded_links[:40],
    external_links=external_links[:40],
    external_references=external_references[:40],
    graph_relations=graph_relations[:80],
    aliases=_ordered_unique(aliases)[:30],
    required_phrases=_ordered_unique(required_phrases)[:30],
    forbidden_phrases=_ordered_unique(forbidden_phrases)[:30],
    chapter_start=chapter_start,
    chapter_end=chapter_end,
    reveal_after_chapter=reveal_after_chapter,
    preview=_compact_text("\n".join(part for part in [summary_text, body] if part).strip(), limit=180),
    updated_at=_path_updated_at(path),
    usable_by_ai=usable_by_ai,
    source_key=obsidian_source_key(relative),
    source_chapter_hash=_frontmatter_string(
      frontmatter,
      "source_chapter_hash",
      "source_content_hash",
      "source_hash",
      "章节正文签名",
    ).strip()[:80],
    source_ids=source_ids,
    source_chapters=source_chapter_indexes[:30],
  )
  content = build_obsidian_knowledge_content(summary, body)
  return ObsidianNoteRecord(summary=summary, content=content, body=body)


def build_obsidian_knowledge_content(note: ObsidianNoteSummary, body: str) -> str:
  visible_body = _ai_visible_body(body, note.relative_path)
  header = [
    f"Obsidian 笔记：{note.title}",
    f"路径：{note.relative_path}",
  ]
  if note.note_type:
    header.append(f"类型：{note.note_type}")
  if note.status:
    header.append(f"状态：{note.status}")
  if note.summary:
    header.append(f"摘要：{note.summary}")
  if note.keywords:
    header.append(f"关键词：{'、'.join(note.keywords[:16])}")
  if note.aliases:
    header.append(f"别名：{'、'.join(note.aliases[:12])}")
  if note.tags:
    header.append(f"标签：{'、'.join(note.tags[:16])}")
  if note.source_chapters:
    header.append(f"来源章节：{'、'.join(f'第 {index} 章' for index in note.source_chapters[:12])}")
  chapter_scope = _chapter_scope_parts(note)
  if chapter_scope:
    header.append("；".join(chapter_scope))
  if note.required_phrases:
    header.append(f"必须包含：{'、'.join(note.required_phrases[:12])}")
  if note.forbidden_phrases:
    header.append(f"禁止出现：{'、'.join(note.forbidden_phrases[:12])}")
  if note.links:
    header.append(f"双链：{'、'.join(note.links[:24])}")
  if note.embedded_links:
    header.append(f"嵌入笔记：{'、'.join(note.embedded_links[:16])}")
  if note.external_links:
    header.append(f"外部链接：{'、'.join(note.external_links[:8])}")
  if note.external_references:
    header.append(f"外部来源：{'、'.join(note.external_references[:8])}")
  if note.graph_relations:
    header.append(f"图谱关系：{'、'.join(note.graph_relations[:24])}")
  if note.resolved_links:
    header.append(f"已解析双链：{'、'.join(note.resolved_links[:24])}")
  if note.backlinks:
    header.append(f"反向链接：{'、'.join(note.backlinks[:24])}")
  if note.unresolved_links:
    header.append(f"未解析双链：{'、'.join(note.unresolved_links[:12])}")
  if note.ambiguous_links:
    header.append(f"歧义双链：{'、'.join(note.ambiguous_links[:12])}")
  return "\n".join(header + ["", visible_body.strip()]).strip()


def _graph_lookup_labels(note: ObsidianNoteSummary) -> list[str]:
  relative_path = note.relative_path.strip().replace("\\", "/")
  labels = [
    note.title,
    relative_path,
    relative_path[:-3] if relative_path.lower().endswith(".md") else relative_path,
    Path(relative_path).stem,
  ]
  labels.extend(note.aliases)
  return _ordered_unique(labels)


def _graph_label_paths(records: list[ObsidianNoteRecord]) -> dict[str, list[str]]:
  label_paths: dict[str, list[str]] = {}
  for record in records:
    relative_path = record.summary.relative_path
    for label in _graph_lookup_labels(record.summary):
      key = _link_lookup_key(label)
      label_paths.setdefault(key, [])
      if relative_path not in label_paths[key]:
        label_paths[key].append(relative_path)
  return label_paths


def _graph_target_map(records: list[ObsidianNoteRecord]) -> dict[str, str]:
  label_paths = _graph_label_paths(records)
  return {
    key: paths[0]
    for key, paths in label_paths.items()
    if len(paths) == 1
  }


def _graph_relation_target(value: str) -> tuple[str, str]:
  if "->" not in value:
    return "", ""
  label, target = value.split("->", 1)
  return label.strip(), target.strip()


def _scoped_graph_relations(
  relations: list[str],
  target_map: dict[str, str],
  source_relative_path: str,
  visible_label_paths: dict[str, list[str]],
  all_label_paths: dict[str, list[str]],
  hidden_plain_labels: list[str],
) -> list[str]:
  safe_relations: list[str] = []
  for relation in relations:
    label, target = _graph_relation_target(str(relation or ""))
    if not label or not target:
      continue
    if _link_lookup_key(target) not in target_map:
      continue
    safe_label = _sanitize_scoped_links(
      label,
      source_relative_path,
      visible_label_paths,
      all_label_paths,
      hidden_plain_labels,
    ).strip()
    safe_target = _sanitize_scoped_links(
      target,
      source_relative_path,
      visible_label_paths,
      all_label_paths,
      hidden_plain_labels,
    ).strip()
    if safe_label and safe_target:
      safe_relations.append(f"{safe_label} -> {safe_target}")
  return _ordered_unique(safe_relations)


def _scoped_link_values(
  links: list[str],
  visible_label_paths: dict[str, list[str]],
  all_label_paths: dict[str, list[str]],
) -> list[str]:
  safe_links: list[str] = []
  for link in links:
    cleaned = str(link or "").strip()
    if not cleaned:
      continue
    key = _link_lookup_key(cleaned)
    if visible_label_paths.get(key) or not all_label_paths.get(key):
      safe_links.append(cleaned)
  return _ordered_unique(safe_links)


def _plain_text_redaction_label(value: str) -> str:
  cleaned = str(value or "").strip().strip("\"'“”‘’`")
  if not cleaned:
    return ""
  normalized = cleaned.replace("\\", "/")
  if normalized in {"未开放设定", "未开放关系"}:
    return ""
  if len(normalized) < 3:
    return ""
  if re.fullmatch(r"[0-9０-９零〇一二两三四五六七八九十百千.\-_/\\]+", normalized):
    return ""
  return normalized


def _hidden_plain_text_labels(
  records: list[ObsidianNoteRecord],
  visible_records: list[ObsidianNoteRecord],
  visible_label_paths: dict[str, list[str]],
) -> list[str]:
  visible_paths = {
    str(record.summary.relative_path or "").strip()
    for record in visible_records
    if str(record.summary.relative_path or "").strip()
  }
  labels: list[str] = []
  for record in records:
    if str(record.summary.relative_path or "").strip() in visible_paths:
      continue
    for raw_label in _graph_lookup_labels(record.summary):
      label = _plain_text_redaction_label(raw_label)
      if not label:
        continue
      if visible_label_paths.get(_link_lookup_key(label)):
        continue
      labels.append(label)
  return sorted(_ordered_unique(labels), key=len, reverse=True)


def _scope_visible_label_paths(
  records: list[ObsidianNoteRecord],
  visible_records: list[ObsidianNoteRecord],
) -> dict[str, list[str]]:
  all_label_paths = _graph_label_paths(records)
  raw_visible_label_paths = _graph_label_paths(visible_records)
  visible_paths = {
    str(record.summary.relative_path or "").strip()
    for record in visible_records
    if str(record.summary.relative_path or "").strip()
  }
  safe_label_paths: dict[str, list[str]] = {}
  for key, paths in raw_visible_label_paths.items():
    all_paths = all_label_paths.get(key, [])
    if any(path not in visible_paths for path in all_paths):
      continue
    safe_label_paths[key] = paths
  return safe_label_paths


def _target_map_from_label_paths(label_paths: dict[str, list[str]]) -> dict[str, str]:
  return {
    key: paths[0]
    for key, paths in label_paths.items()
    if len(paths) == 1
  }


def _wiki_link_alias(raw_link: str) -> str:
  cleaned = raw_link.strip()
  if cleaned.startswith("![["):
    cleaned = cleaned[1:]
  inner = cleaned[2:-2] if cleaned.startswith("[[") and cleaned.endswith("]]") else cleaned
  if "|" not in inner:
    return ""
  alias = inner.rsplit("|", 1)[1].strip()
  return alias or ""


def _hidden_link_replacement(target: str, alias: str = "") -> str:
  cleaned_alias = str(alias or "").strip()
  if cleaned_alias:
    target_path = str(target or "").strip().replace("\\", "/")
    target_stem = posixpath.splitext(posixpath.basename(target_path))[0]
    unsafe_aliases = {
      _link_lookup_key(target_path),
      _link_lookup_key(target_stem),
    }
    if _link_lookup_key(cleaned_alias) not in unsafe_aliases:
      return cleaned_alias
  return "未开放设定"


def _scoped_metadata_values(
  values: list[str],
  source_relative_path: str,
  visible_label_paths: dict[str, list[str]],
  all_label_paths: dict[str, list[str]],
  hidden_plain_labels: list[str],
) -> list[str]:
  safe_values: list[str] = []
  for value in values:
    cleaned = str(value or "").strip()
    if not cleaned:
      continue
    key = _link_lookup_key(cleaned)
    if all_label_paths.get(key) and not visible_label_paths.get(key):
      safe_values.append("未开放设定")
      continue
    sanitized = _sanitize_scoped_links(
      cleaned,
      source_relative_path,
      visible_label_paths,
      all_label_paths,
      hidden_plain_labels,
    ).strip()
    if sanitized:
      safe_values.append(sanitized)
  return _ordered_unique(safe_values)


def _sanitize_scoped_plain_text_labels(body: str, hidden_plain_labels: list[str]) -> str:
  text = str(body or "")
  for label in hidden_plain_labels:
    cleaned = _plain_text_redaction_label(label)
    if not cleaned or cleaned not in text:
      continue
    text = text.replace(cleaned, "未开放设定")
  return text


def _sanitize_scoped_wiki_links(
  body: str,
  source_relative_path: str,
  visible_label_paths: dict[str, list[str]],
  all_label_paths: dict[str, list[str]],
) -> str:
  def replacement(match: re.Match[str]) -> str:
    target = _knowledge_link_target(match.group(1), source_relative_path)
    if not target:
      return ""
    key = _link_lookup_key(target)
    if visible_label_paths.get(key) or not all_label_paths.get(key):
      return match.group(0)
    return _hidden_link_replacement(target, _wiki_link_alias(match.group(0)))

  return _WIKI_LINK_WITH_EMBED_PATTERN.sub(replacement, body)


def _sanitize_scoped_markdown_links(
  body: str,
  source_relative_path: str,
  visible_label_paths: dict[str, list[str]],
  all_label_paths: dict[str, list[str]],
) -> str:
  text = str(body or "")
  matches = _iter_markdown_link_matches(text)
  if not matches:
    return text

  parts: list[str] = []
  index = 0
  for match in matches:
    parts.append(text[index:match.start])
    target = _markdown_link_target(match.destination, source_relative_path)
    if not target:
      parts.append(match.raw)
      index = match.end
      continue
    key = _link_lookup_key(target)
    if visible_label_paths.get(key) or not all_label_paths.get(key):
      parts.append(match.raw)
    else:
      parts.append(_hidden_link_replacement(target, match.label))
    index = match.end
  parts.append(text[index:])
  return "".join(parts)


def _sanitize_scoped_markdown_reference_links(
  body: str,
  source_relative_path: str,
  visible_label_paths: dict[str, list[str]],
  all_label_paths: dict[str, list[str]],
) -> str:
  text = str(body or "")
  definitions = _markdown_reference_definitions(text, source_relative_path)
  if not definitions:
    return text
  reference_targets: dict[str, str] = {}
  for definition in definitions:
    reference_targets.setdefault(_markdown_reference_label_key(definition.label), definition.target)

  replacements: list[tuple[int, int, str]] = []
  for match in _iter_markdown_reference_link_matches(text, reference_targets):
    key = _link_lookup_key(match.target)
    if visible_label_paths.get(key) or not all_label_paths.get(key):
      continue
    replacements.append((match.start, match.end, _hidden_link_replacement(match.target, match.label)))

  for definition in definitions:
    key = _link_lookup_key(definition.target)
    if visible_label_paths.get(key) or not all_label_paths.get(key):
      continue
    replacements.append((definition.start, definition.end, "未开放设定"))

  if not replacements:
    return text

  parts: list[str] = []
  index = 0
  for start, end, replacement in sorted(replacements, key=lambda item: item[0]):
    if start < index:
      continue
    parts.append(text[index:start])
    parts.append(replacement)
    index = end
  parts.append(text[index:])
  return "".join(parts)


def _sanitize_scoped_canvas_edge_lines(
  body: str,
  source_relative_path: str,
  visible_label_paths: dict[str, list[str]],
  all_label_paths: dict[str, list[str]],
) -> str:
  lines: list[str] = []
  for line in str(body or "").splitlines():
    if "--" not in line or "-->" not in line:
      lines.append(line)
      continue

    has_hidden_target = False

    def replacement(match: re.Match[str]) -> str:
      nonlocal has_hidden_target
      target = _knowledge_link_target(match.group(1), source_relative_path)
      if not target:
        return ""
      key = _link_lookup_key(target)
      if visible_label_paths.get(key) or not all_label_paths.get(key):
        return match.group(0)
      has_hidden_target = True
      return "未开放设定"

    sanitized = _WIKI_LINK_WITH_EMBED_PATTERN.sub(replacement, line)
    if has_hidden_target:
      sanitized = re.sub(r"--.*?-->", "--未开放关系-->", sanitized)
    lines.append(sanitized)
  return "\n".join(lines)


def _sanitize_scoped_links(
  body: str,
  source_relative_path: str,
  visible_label_paths: dict[str, list[str]],
  all_label_paths: dict[str, list[str]],
  hidden_plain_labels: list[str] | None = None,
) -> str:
  canvas_safe = _sanitize_scoped_canvas_edge_lines(body, source_relative_path, visible_label_paths, all_label_paths)
  wiki_safe = _sanitize_scoped_wiki_links(canvas_safe, source_relative_path, visible_label_paths, all_label_paths)
  markdown_safe = _sanitize_scoped_markdown_links(wiki_safe, source_relative_path, visible_label_paths, all_label_paths)
  reference_safe = _sanitize_scoped_markdown_reference_links(markdown_safe, source_relative_path, visible_label_paths, all_label_paths)
  return _sanitize_scoped_plain_text_labels(reference_safe, hidden_plain_labels or [])


def _scoped_record_for_chapter(
  record: ObsidianNoteRecord,
  target_map: dict[str, str],
  visible_label_paths: dict[str, list[str]],
  all_label_paths: dict[str, list[str]],
  hidden_plain_labels: list[str],
) -> ObsidianNoteRecord:
  source_relative_path = str(record.summary.relative_path or "")
  body = _sanitize_scoped_links(
    record.body,
    source_relative_path,
    visible_label_paths,
    all_label_paths,
    hidden_plain_labels,
  )
  summary_text = _sanitize_scoped_links(
    record.summary.summary,
    source_relative_path,
    visible_label_paths,
    all_label_paths,
    hidden_plain_labels,
  )
  summary = record.summary.model_copy(
    update={
      "summary": summary_text,
      "tags": _scoped_metadata_values(
        list(record.summary.tags or []),
        source_relative_path,
        visible_label_paths,
        all_label_paths,
        hidden_plain_labels,
      ),
      "keywords": _scoped_metadata_values(
        list(record.summary.keywords or []),
        source_relative_path,
        visible_label_paths,
        all_label_paths,
        hidden_plain_labels,
      ),
      "aliases": _scoped_metadata_values(
        list(record.summary.aliases or []),
        source_relative_path,
        visible_label_paths,
        all_label_paths,
        hidden_plain_labels,
      ),
      "required_phrases": _scoped_metadata_values(
        list(record.summary.required_phrases or []),
        source_relative_path,
        visible_label_paths,
        all_label_paths,
        hidden_plain_labels,
      ),
      "forbidden_phrases": _scoped_metadata_values(
        list(record.summary.forbidden_phrases or []),
        source_relative_path,
        visible_label_paths,
        all_label_paths,
        hidden_plain_labels,
      ),
      "links": _scoped_link_values(list(record.summary.links or []), visible_label_paths, all_label_paths),
      "embedded_links": _scoped_link_values(
        list(record.summary.embedded_links or []),
        visible_label_paths,
        all_label_paths,
      ),
      "external_links": _scoped_metadata_values(
        list(record.summary.external_links or []),
        source_relative_path,
        visible_label_paths,
        all_label_paths,
        hidden_plain_labels,
      ),
      "external_references": _scoped_metadata_values(
        list(record.summary.external_references or []),
        source_relative_path,
        visible_label_paths,
        all_label_paths,
        hidden_plain_labels,
      ),
      "graph_relations": _scoped_graph_relations(
        list(record.summary.graph_relations or []),
        target_map,
        source_relative_path,
        visible_label_paths,
        all_label_paths,
        hidden_plain_labels,
      ),
      "resolved_links": [],
      "backlinks": [],
      "unresolved_links": _scoped_link_values(
        list(record.summary.unresolved_links or []),
        visible_label_paths,
        all_label_paths,
      ),
      "ambiguous_links": _scoped_link_values(
        list(record.summary.ambiguous_links or []),
        visible_label_paths,
        all_label_paths,
      ),
      "preview": _compact_text("\n".join(part for part in [summary_text, body] if part).strip(), limit=180),
    }
  )
  return ObsidianNoteRecord(summary=summary, content="", body=body)


def _duplicate_label_count(records: list[ObsidianNoteRecord]) -> int:
  label_paths: dict[str, list[str]] = {}
  for record in records:
    for label in _graph_lookup_labels(record.summary):
      key = _link_lookup_key(label)
      label_paths.setdefault(key, [])
      if record.summary.relative_path not in label_paths[key]:
        label_paths[key].append(record.summary.relative_path)
  return sum(1 for paths in label_paths.values() if len(paths) > 1)


def _record_has_graph_relation(record: ObsidianNoteRecord) -> bool:
  summary = record.summary
  return any(
    list(getattr(summary, field, []) or [])
    for field in ("links", "resolved_links", "backlinks", "unresolved_links", "ambiguous_links")
  )


def _note_availability_interval(note: ObsidianNoteSummary) -> tuple[int, int | None]:
  start = 1
  if note.reveal_after_chapter > 0:
    start = max(start, note.reveal_after_chapter + 1)
  if note.chapter_start > 0:
    start = max(start, note.chapter_start)
  end = note.chapter_end if note.chapter_end > 0 else None
  return start, end


def _scope_mismatch_chapters(source: ObsidianNoteSummary, target: ObsidianNoteSummary) -> list[int]:
  source_start, source_end = _note_availability_interval(source)
  target_start, target_end = _note_availability_interval(target)
  if source_end is not None and source_start > source_end:
    return []

  chapters: list[int] = []
  if source_start < target_start:
    chapters.append(source_start)
  if target_end is not None and (source_end is None or source_end > target_end):
    chapters.append(max(source_start, target_end + 1))

  unique_chapters: list[int] = []
  seen: set[int] = set()
  for chapter in chapters:
    if chapter <= 0 or chapter in seen:
      continue
    seen.add(chapter)
    unique_chapters.append(chapter)
  return unique_chapters[:4]


@dataclass(slots=True)
class ObsidianGraphIssueReport:
  warnings: list[str]
  issues: list[ObsidianGraphIssue]
  duplicate_label_count: int = 0
  ambiguous_link_count: int = 0


def _enrich_obsidian_graph(records: list[ObsidianNoteRecord]) -> tuple[list[ObsidianNoteRecord], ObsidianGraphIssueReport]:
  record_by_path = {record.summary.relative_path: record for record in records}
  label_paths: dict[str, list[str]] = {}
  label_names: dict[str, str] = {}
  for record in records:
    relative_path = record.summary.relative_path
    for label in _graph_lookup_labels(record.summary):
      key = _link_lookup_key(label)
      label_names.setdefault(key, label)
      label_paths.setdefault(key, [])
      if relative_path not in label_paths[key]:
        label_paths[key].append(relative_path)

  duplicate_labels = {
    key: paths
    for key, paths in label_paths.items()
    if len(paths) > 1
  }
  target_map = {
    key: paths[0]
    for key, paths in label_paths.items()
    if len(paths) == 1
  }

  backlinks: dict[str, list[str]] = {record.summary.relative_path: [] for record in records}
  graph_updates: dict[str, tuple[list[str], list[str], list[str], list[str], list[str]]] = {}
  scope_mismatches: list[tuple[str, str, str, list[int]]] = []

  for record in records:
    source_path = record.summary.relative_path
    links: list[str] = []
    resolved: list[str] = []
    unresolved: list[str] = []
    ambiguous: list[str] = []
    for raw_link in record.summary.links:
      link_key = _link_lookup_key(raw_link)
      if link_key in duplicate_labels:
        links.append(raw_link)
        ambiguous.append(raw_link)
        continue
      target_path = target_map.get(link_key)
      if not target_path:
        links.append(raw_link)
        unresolved.append(raw_link)
        continue
      if target_path == source_path:
        continue
      links.append(raw_link)
      resolved.append(target_path)
      backlinks.setdefault(target_path, []).append(source_path)
      target_record = record_by_path.get(target_path)
      if target_record is not None:
        mismatch_chapters = _scope_mismatch_chapters(record.summary, target_record.summary)
        if mismatch_chapters:
          scope_mismatches.append((source_path, target_path, raw_link, mismatch_chapters))

    graph_relations: list[str] = []
    for relation in record.summary.graph_relations:
      _label, relation_target = _graph_relation_target(relation)
      relation_key = _link_lookup_key(relation_target)
      if relation_key and relation_key not in duplicate_labels and target_map.get(relation_key) == source_path:
        continue
      graph_relations.append(relation)

    graph_updates[source_path] = (
      _ordered_unique(links),
      _ordered_unique(resolved),
      _ordered_unique(unresolved),
      _ordered_unique(ambiguous),
      _ordered_unique(graph_relations),
    )

  for record in records:
    source_path = record.summary.relative_path
    links, resolved, unresolved, ambiguous, graph_relations = graph_updates.get(source_path, ([], [], [], [], []))
    record.summary = record.summary.model_copy(
      update={
        "links": links,
        "resolved_links": resolved,
        "unresolved_links": unresolved,
        "ambiguous_links": ambiguous,
        "graph_relations": graph_relations,
        "backlinks": _ordered_unique(backlinks.get(source_path, [])),
      }
    )
    record.content = build_obsidian_knowledge_content(record.summary, record.body)
  duplicate_label_count = len(duplicate_labels)
  ambiguous_link_count = sum(len(record.summary.ambiguous_links) for record in records)
  warnings: list[str] = []
  issues: list[ObsidianGraphIssue] = []
  if duplicate_labels:
    examples = []
    for key, paths in sorted(duplicate_labels.items())[:5]:
      examples.append(f"{label_names.get(key, key)} -> {'、'.join(paths[:4])}")
    warnings.append(
      f"存在 {duplicate_label_count} 个重复标题、路径名或别名，相关双链不会自动解析：{'；'.join(examples)}"
    )
    for key, paths in sorted(duplicate_labels.items())[:12]:
      label = label_names.get(key, key)
      issues.append(
        ObsidianGraphIssue(
          kind="duplicate_label",
          severity="warning",
          title=f"重复命名：{label}",
          message="多个笔记共享同一标题、路径名或别名，指向该名称的双链不会自动解析。",
          notes=paths[:8],
          links=[label],
        )
      )
  unresolved_link_count = sum(len(record.summary.unresolved_links) for record in records)
  if unresolved_link_count:
    warnings.append(f"存在 {unresolved_link_count} 条未解析双链，请确认是否缺少对应笔记。")
    unresolved_map: dict[str, list[str]] = {}
    for record in records:
      for link in record.summary.unresolved_links:
        unresolved_map.setdefault(link, []).append(record.summary.relative_path)
    for link, paths in sorted(unresolved_map.items())[:12]:
      issues.append(
        ObsidianGraphIssue(
          kind="unresolved_link",
          severity="info",
          title=f"未解析双链：{link}",
          message="没有找到与该双链对应的可用笔记。若这是正式设定，建议补齐笔记或调整链接名。",
          notes=_ordered_unique(paths)[:8],
          links=[link],
        )
      )
  if ambiguous_link_count:
    warnings.append(f"存在 {ambiguous_link_count} 条歧义双链，请用更完整的路径或调整别名。")
    ambiguous_map: dict[str, list[str]] = {}
    for record in records:
      for link in record.summary.ambiguous_links:
        ambiguous_map.setdefault(link, []).append(record.summary.relative_path)
    for link, paths in sorted(ambiguous_map.items())[:12]:
      issues.append(
        ObsidianGraphIssue(
          kind="ambiguous_link",
          severity="warning",
          title=f"歧义双链：{link}",
          message="该链接命中了重复命名，系统不会把它解析到任意一篇笔记。",
          notes=_ordered_unique(paths)[:8],
          links=[link],
        )
      )
  if scope_mismatches:
    warnings.append(f"存在 {len(scope_mismatches)} 条章节范围不匹配的双链，请调整目标笔记可见范围或拆分关系笔记。")
    for source_path, target_path, link, chapters in scope_mismatches[:12]:
      chapter_text = "、".join(str(item) for item in chapters[:4])
      issues.append(
        ObsidianGraphIssue(
          kind="scope_mismatch",
          severity="warning",
          title=f"章节范围不匹配：{link}",
          message=f"{source_path} 在第 {chapter_text} 章可用，但目标笔记 {target_path} 在这些章节不可用。",
          notes=[source_path, target_path],
          links=[link],
        )
      )
  orphan_notes = [
    record.summary.relative_path
    for record in records
    if not _record_has_graph_relation(record)
  ]
  if orphan_notes:
    issues.append(
      ObsidianGraphIssue(
        kind="orphan_note",
        severity="info",
        title=f"孤立笔记 {len(orphan_notes)} 份",
        message="这些笔记没有可解析外链，也没有被其他可用笔记引用。若它们是正式设定，建议建立至少一条关系。",
        notes=orphan_notes[:20],
      )
    )
  return records, ObsidianGraphIssueReport(
    warnings=warnings,
    issues=issues,
    duplicate_label_count=duplicate_label_count,
    ambiguous_link_count=ambiguous_link_count,
  )


def collect_obsidian_note_records(project_dir: Path) -> tuple[list[ObsidianNoteRecord], int, list[str]]:
  records, skipped, warnings, _issues = collect_obsidian_note_records_with_issues(project_dir)
  return records, skipped, warnings


def collect_obsidian_note_records_with_issues(
  project_dir: Path,
) -> tuple[list[ObsidianNoteRecord], int, list[str], list[ObsidianGraphIssue]]:
  config = load_obsidian_config(project_dir)
  if not config.enabled:
    return [], 0, [], []
  vault_dir = _resolve_vault_dir(project_dir, config)
  if vault_dir is None:
    return [], 0, ["Obsidian Vault 路径为空"], []
  if not vault_dir.exists() or not vault_dir.is_dir():
    return [], 0, [f"Obsidian Vault 不存在：{vault_dir}"], []

  records: list[ObsidianNoteRecord] = []
  skipped = 0
  matching_paths = _matching_note_paths(vault_dir, config)
  limit_warning = _candidate_limit_warning(len(matching_paths), config)
  candidate_paths = matching_paths[: config.max_notes]
  skipped += max(len(matching_paths) - len(candidate_paths), 0)
  for path in candidate_paths:
    record = _note_record_from_path(vault_dir, path, config)
    if record is None:
      skipped += 1
      continue
    records.append(record)
  records, issue_report = _enrich_obsidian_graph(records)
  warnings = ([limit_warning] if limit_warning else []) + issue_report.warnings
  return records, skipped, warnings, issue_report.issues


def obsidian_note_record_for_source_key(project_dir: Path, source_key: str) -> ObsidianNoteRecord | None:
  if not source_key.startswith("obsidian:"):
    return None
  relative = source_key.split(":", 1)[1].strip().replace("\\", "/")
  if not relative:
    return None
  records, _skipped, _warnings = collect_obsidian_note_records(project_dir)
  return next((record for record in records if record.summary.relative_path == relative), None)


def obsidian_source_signature_entries(project_dir: Path) -> list[tuple[str, int, int]]:
  config_path = obsidian_config_path(project_dir)
  entries: list[tuple[str, int, int]] = []
  if config_path.exists():
    stat = config_path.stat()
    entries.append((f"{_APP_STATE_DIRNAME}/{_CONFIG_FILENAME}", stat.st_mtime_ns, stat.st_size))

  config = load_obsidian_config(project_dir)
  if not config.enabled:
    return entries
  vault_dir = _resolve_vault_dir(project_dir, config)
  if vault_dir is None or not vault_dir.exists() or not vault_dir.is_dir():
    return entries
  matching_paths = _matching_note_paths(vault_dir, config)
  entries.append(("obsidian:candidate_count", len(matching_paths), config.max_notes))
  for path in matching_paths[: config.max_notes]:
    try:
      stat = path.stat()
    except OSError:
      continue
    entries.append((f"obsidian:{path.relative_to(vault_dir).as_posix()}", stat.st_mtime_ns, stat.st_size))
  return entries


def obsidian_source_signature(project_dir: Path) -> str:
  digest = hashlib.sha1()
  for source_label, mtime_ns, size in sorted(obsidian_source_signature_entries(project_dir)):
    digest.update(source_label.encode("utf-8"))
    digest.update(str(mtime_ns).encode("utf-8"))
    digest.update(str(size).encode("utf-8"))
  return digest.hexdigest()


def scoped_obsidian_note_records_for_chapter(project_dir: Path, chapter_index: int = 0) -> list[ObsidianNoteRecord]:
  try:
    target = int(chapter_index or 0)
  except (TypeError, ValueError):
    target = 0
  records, _skipped, _warnings = collect_obsidian_note_records(project_dir)
  if target <= 0:
    return records
  raw_eligible_records = [
    record
    for record in records
    if obsidian_note_available_for_chapter(record.summary, target)
  ]
  all_label_paths = _graph_label_paths(records)
  visible_label_paths = _scope_visible_label_paths(records, raw_eligible_records)
  target_map = _target_map_from_label_paths(visible_label_paths)
  hidden_plain_labels = _hidden_plain_text_labels(records, raw_eligible_records, visible_label_paths)
  eligible_records = [
    _scoped_record_for_chapter(record, target_map, visible_label_paths, all_label_paths, hidden_plain_labels)
    for record in raw_eligible_records
  ]
  scoped_records, _issue_report = _enrich_obsidian_graph(eligible_records)
  return scoped_records


def obsidian_source_signature_for_chapter(project_dir: Path, chapter_index: int = 0) -> str:
  try:
    target = int(chapter_index or 0)
  except (TypeError, ValueError):
    target = 0
  if target <= 0:
    return obsidian_source_signature(project_dir)

  config = load_obsidian_config(project_dir)
  digest = hashlib.sha1()
  digest.update(b"config")
  digest.update(_stable_json(config.model_dump(mode="json")).encode("utf-8"))
  if not config.enabled:
    return digest.hexdigest()

  scoped_records = scoped_obsidian_note_records_for_chapter(project_dir, target)
  for record in sorted(scoped_records, key=lambda item: item.summary.relative_path):
    payload = record.summary.model_dump(mode="json")
    payload["updated_at"] = None
    digest.update(record.summary.relative_path.encode("utf-8"))
    digest.update(_stable_json(payload).encode("utf-8"))
    digest.update(hashlib.sha1(record.body.encode("utf-8")).hexdigest().encode("utf-8"))
  return digest.hexdigest()


def sync_obsidian_state(project_dir: Path) -> ObsidianVaultState:
  config = load_obsidian_config(project_dir)
  records, skipped, warnings, issues = collect_obsidian_note_records_with_issues(project_dir)
  link_count = sum(len(record.summary.links) for record in records)
  external_link_count = sum(len(record.summary.external_links) for record in records)
  resolved_link_count = sum(len(record.summary.resolved_links) for record in records)
  unresolved_link_count = sum(len(record.summary.unresolved_links) for record in records)
  ambiguous_link_count = sum(len(record.summary.ambiguous_links) for record in records)
  duplicate_label_count = _duplicate_label_count(records)
  orphan_count = sum(
    1
    for record in records
    if not _record_has_graph_relation(record)
  )
  state = ObsidianVaultState(
    config=config,
    enabled=config.enabled,
    vault_path=config.vault_path.strip(),
    note_count=len(records),
    included_count=len(records),
    skipped_count=skipped,
    link_count=link_count,
    external_link_count=external_link_count,
    resolved_link_count=resolved_link_count,
    unresolved_link_count=unresolved_link_count,
    ambiguous_link_count=ambiguous_link_count,
    duplicate_label_count=duplicate_label_count,
    orphan_count=orphan_count,
    source_signature=obsidian_source_signature(project_dir),
    updated_at=_now_iso(),
    warnings=warnings,
    issues=issues,
    notes=[record.summary for record in records],
  )
  obsidian_sync_path(project_dir).parent.mkdir(parents=True, exist_ok=True)
  atomic_write_json(obsidian_sync_path(project_dir), state.model_dump(mode="json"))
  return state


def load_obsidian_state(project_dir: Path) -> ObsidianVaultState:
  config = load_obsidian_config(project_dir)
  payload = read_json(obsidian_sync_path(project_dir), None)
  if isinstance(payload, dict):
    try:
      state = ObsidianVaultState.model_validate(payload)
      current_signature = obsidian_source_signature(project_dir)
      if (
        state.config.model_dump(mode="json") == config.model_dump(mode="json")
        and state.source_signature
        and state.source_signature == current_signature
      ):
        return state
    except ValidationError:
      pass
  if config.enabled and config.vault_path.strip():
    return sync_obsidian_state(project_dir)
  return ObsidianVaultState(
    config=config,
    enabled=config.enabled,
    vault_path=config.vault_path.strip(),
    warnings=["Obsidian 尚未同步"] if config.enabled else [],
  )
