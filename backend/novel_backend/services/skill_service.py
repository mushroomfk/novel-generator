from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import difflib
import re

from fastapi import HTTPException

from novel_backend.config import Settings
from novel_backend.models import (
  BrainstormMessage,
  SkillBehavior,
  SkillCatalog,
  SkillItem,
  SkillMaterializeRequest,
  SkillMaterializeResult,
  SkillPackageImportRequest,
  SkillSection,
  SkillSuggestion,
  SkillVerificationReport,
)
from novel_backend.services.config_service import skills_dir
from novel_backend.services.generation_service import (
  _compact_text,
  _extract_json_object,
  _invoke_model,
  _string_from_keys,
  _string_list_from_keys,
)
from novel_backend.services.log_service import append_app_log
from novel_backend.services.project_service import get_project_detail
from novel_backend.services.skill_usage_service import record_skill_patch
from novel_backend.utils.jsonfile import atomic_write_json, atomic_write_text, read_json

_USER_SKILL_SECTION_ID = "user-skills"
_USER_SKILL_SECTION_TITLE = "用户沉淀"
_USER_SKILL_SECTION_DESCRIPTION = "聊天里沉淀下来的可复用技能，会跟着你的新要求继续迭代。"
_SKILL_BODY_SECTION_TITLES = ("适用场景", "输入要求", "执行步骤", "输出要求", "边界")
_SKILL_VERSION_LIMIT = 40
_SKILL_DRAFT_SYSTEM_PROMPT = """
你是技能设计器。你的任务是参考 OpenHarness 的 SKILL.md 风格，把一段已经验证过的聊天工作流整理成可以长期复用的用户技能。

输出要求：
1. 只输出一个 JSON 对象。
2. JSON 字段固定为：name、description、category、scenes、usage、limitations、requires_project、requires_chapter、body_markdown。
3. body_markdown 必须是 Markdown，第一行用一级标题，必须包含这些二级标题：适用场景、输入要求、执行步骤、输出要求、边界。
4. 执行步骤写成 3 到 5 条编号步骤，必须具体，不能写空话。
5. description 控制在 80 字以内，说明这个技能到底替用户做什么。
6. limitations 至少 2 条，明确这版还没覆盖到哪里。
7. 如果已有技能正文，请把这轮新要求合并进去，不要把旧技能推翻重写。
""".strip()
_FRONTMATTER_LIST_KEYS = {"scenes", "usage", "limitations"}
_FRONTMATTER_BOOL_KEYS = {"requires_project", "requires_chapter"}
_SIMILARITY_CUTOFF_BUILTIN = 0.22
_SIMILARITY_CUTOFF_CUSTOM = 0.17
_REUSABLE_SIGNAL_CUTOFF = 0.58


@dataclass
class _SkillRecord:
  item: SkillItem
  path: Path
  section_meta: tuple[str, str, int]
  body: str = ""
  frontmatter: dict[str, object] | None = None


def _default_skill_behavior(skill_id: str) -> SkillBehavior:
  defaults = {
    "chapter-scenes": SkillBehavior(
      panel="chapter-workflow",
      mode="scenes",
      input_label="拆场要求",
      submit_label="开始拆场",
    ),
    "chapter-diagnose": SkillBehavior(
      panel="chapter-workflow",
      mode="diagnose",
      input_label="诊断要求",
      submit_label="开始诊断",
    ),
    "chapter-draft": SkillBehavior(
      panel="chapter-workflow",
      mode="draft",
      input_label="续写要求",
      submit_label="开始续写",
    ),
    "chapter-finalize": SkillBehavior(
      panel="chapter-rewrite",
      mode="finalize",
      input_label="改稿要求",
      submit_label="开始定稿",
    ),
    "chapter-polish": SkillBehavior(
      panel="chapter-rewrite",
      mode="polish",
      input_label="改稿要求",
      submit_label="开始润色",
    ),
    "chapter-humanize": SkillBehavior(
      panel="chapter-rewrite",
      mode="humanize",
      input_label="改稿要求",
      submit_label="开始去 AI",
    ),
  }
  return defaults.get(skill_id, SkillBehavior(panel=skill_id))


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def _version_id() -> str:
  return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")


def _safe_skill_id(skill_id: str) -> str:
  return re.sub(r"[^A-Za-z0-9._-]+", "-", skill_id.strip()).strip(".-_") or "skill"


def _skill_versions_dir(settings: Settings, skill_id: str) -> Path:
  return skills_dir(settings) / ".versions" / _safe_skill_id(skill_id)


def _skill_versions_index_path(settings: Settings, skill_id: str) -> Path:
  return _skill_versions_dir(settings, skill_id) / "versions.json"


def _ordered_unique(items: list[str]) -> list[str]:
  seen: set[str] = set()
  ordered: list[str] = []
  for raw in items:
    value = str(raw).strip()
    if not value or value in seen:
      continue
    seen.add(value)
    ordered.append(value)
  return ordered


def _as_bool(value: object, default: bool = False) -> bool:
  if isinstance(value, bool):
    return value
  if isinstance(value, str):
    lowered = value.strip().lower()
    if lowered in {"true", "yes", "1"}:
      return True
    if lowered in {"false", "no", "0"}:
      return False
  return default


def _section_meta(payload: dict[str, object], default_section_id: str) -> tuple[str, str, int]:
  return (
    str(payload.get("section_title") or default_section_id).strip() or default_section_id,
    str(payload.get("section_description") or "").strip(),
    int(payload.get("section_order") or 0),
  )


def _skill_record_from_json(path: Path) -> _SkillRecord | None:
  payload = read_json(path, None)
  if not isinstance(payload, dict):
    return None

  skill_id = str(payload.get("id") or "").strip()
  section_id = str(payload.get("section_id") or "").strip()
  name = str(payload.get("name") or "").strip()
  badge = str(payload.get("badge") or "").strip()
  if not skill_id or not section_id or not name or not badge:
    return None

  item = SkillItem(
    id=skill_id,
    badge=badge,
    name=name,
    description=str(payload.get("description") or "").strip(),
    category=str(payload.get("category") or "工具").strip() or "工具",
    scenes=[str(item).strip() for item in payload.get("scenes") or [] if str(item).strip()],
    accent=str(payload.get("accent") or "slate").strip() or "slate",
    requires_project=bool(payload.get("requires_project", True)),
    requires_chapter=bool(payload.get("requires_chapter", False)),
    order=int(payload.get("order") or 0),
    behavior=SkillBehavior.model_validate(payload.get("behavior") or _default_skill_behavior(skill_id)),
    source="builtin",
    scope=str(payload.get("scope") or "").strip(),
    updated_at=None,
    usage=[],
    limitations=[],
    instruction_preview="",
  )
  return _SkillRecord(
    item=item,
    path=path,
    section_meta=_section_meta(payload, section_id),
    body="",
    frontmatter=payload,
  )


def _split_frontmatter(text: str) -> tuple[dict[str, object], str]:
  if not text.startswith("---"):
    return {}, text.strip()

  lines = text.splitlines()
  frontmatter_lines: list[str] = []
  closing_index = None
  for index, line in enumerate(lines[1:], start=1):
    if line.strip() == "---":
      closing_index = index
      break
    frontmatter_lines.append(line)

  if closing_index is None:
    return {}, text.strip()

  payload: dict[str, object] = {}
  current_list_key = ""
  for raw_line in frontmatter_lines:
    line = raw_line.rstrip()
    stripped = line.strip()
    if not stripped:
      current_list_key = ""
      continue
    if stripped.startswith("- ") and current_list_key:
      payload.setdefault(current_list_key, [])
      if isinstance(payload[current_list_key], list):
        payload[current_list_key].append(stripped[2:].strip())
      continue
    if ":" not in line:
      current_list_key = ""
      continue
    key, value = line.split(":", 1)
    normalized_key = key.strip()
    normalized_value = value.strip()
    if not normalized_key:
      current_list_key = ""
      continue
    if normalized_value:
      if normalized_key in _FRONTMATTER_LIST_KEYS:
        payload[normalized_key] = [item.strip() for item in normalized_value.split("|") if item.strip()]
      elif normalized_key in _FRONTMATTER_BOOL_KEYS:
        payload[normalized_key] = _as_bool(normalized_value)
      else:
        payload[normalized_key] = normalized_value
      current_list_key = ""
      continue
    payload[normalized_key] = []
    current_list_key = normalized_key

  body = "\n".join(lines[closing_index + 1 :]).strip()
  return payload, body


def _preview_from_body(body: str) -> str:
  cleaned = re.sub(r"^#+\s*", "", body, flags=re.MULTILINE)
  cleaned = cleaned.split("## 最近一次回归", 1)[0]
  return _compact_text(cleaned, 240)


def _frontmatter_list(payload: dict[str, object], key: str) -> list[str]:
  raw = payload.get(key)
  if isinstance(raw, list):
    return [str(item).strip() for item in raw if str(item).strip()]
  if isinstance(raw, str) and raw.strip():
    return [item.strip() for item in raw.split("|") if item.strip()]
  return []


def _skill_record_from_markdown(path: Path) -> _SkillRecord | None:
  frontmatter, body = _split_frontmatter(path.read_text(encoding="utf-8"))
  skill_id = str(frontmatter.get("skill_id") or path.parent.name).strip()
  section_id = str(frontmatter.get("section_id") or _USER_SKILL_SECTION_ID).strip() or _USER_SKILL_SECTION_ID
  name = str(frontmatter.get("name") or "").strip()
  description = str(frontmatter.get("description") or "").strip()
  if not skill_id or not name:
    return None

  item = SkillItem(
    id=skill_id,
    badge=str(frontmatter.get("badge") or "沉").strip() or "沉",
    name=name,
    description=description,
    category=str(frontmatter.get("category") or "用户技能").strip() or "用户技能",
    scenes=_frontmatter_list(frontmatter, "scenes"),
    accent=str(frontmatter.get("accent") or "smoke").strip() or "smoke",
    requires_project=_as_bool(frontmatter.get("requires_project"), True),
    requires_chapter=_as_bool(frontmatter.get("requires_chapter"), False),
    order=int(frontmatter.get("order") or 0),
    behavior=SkillBehavior(
      panel=str(frontmatter.get("panel") or "conversation-skill").strip() or "conversation-skill",
      input_label=str(frontmatter.get("input_label") or "").strip(),
      submit_label=str(frontmatter.get("submit_label") or "").strip(),
    ),
    source=str(frontmatter.get("source") or "custom").strip() or "custom",
    scope=str(frontmatter.get("scope") or "").strip(),
    updated_at=str(frontmatter.get("updated_at") or "").strip() or None,
    usage=_frontmatter_list(frontmatter, "usage"),
    limitations=_frontmatter_list(frontmatter, "limitations"),
    instruction_preview=_preview_from_body(body),
  )
  return _SkillRecord(
    item=item,
    path=path,
    section_meta=(
      str(frontmatter.get("section_title") or _USER_SKILL_SECTION_TITLE).strip() or _USER_SKILL_SECTION_TITLE,
      str(frontmatter.get("section_description") or _USER_SKILL_SECTION_DESCRIPTION).strip(),
      int(frontmatter.get("section_order") or 4),
    ),
    body=body,
    frontmatter=frontmatter,
  )


def _iter_skill_records(settings: Settings) -> list[_SkillRecord]:
  records: list[_SkillRecord] = []
  for path in sorted(skills_dir(settings).rglob("*.json")):
    record = _skill_record_from_json(path)
    if record is not None:
      records.append(record)
  for path in sorted(skills_dir(settings).rglob("SKILL.md")):
    record = _skill_record_from_markdown(path)
    if record is not None:
      records.append(record)
  return records


def _find_skill_record(settings: Settings, skill_id: str) -> _SkillRecord | None:
  target = skill_id.strip()
  if not target:
    return None
  for record in _iter_skill_records(settings):
    if record.item.id == target:
      return record
  return None


def _load_skill_version_index(settings: Settings, skill_id: str) -> dict[str, object]:
  payload = read_json(_skill_versions_index_path(settings, skill_id), None)
  if not isinstance(payload, dict):
    return {"schema_version": 1, "updated_at": _now_iso(), "items": []}
  if not isinstance(payload.get("items"), list):
    payload["items"] = []
  payload.setdefault("schema_version", 1)
  payload.setdefault("updated_at", _now_iso())
  return payload


def _save_skill_version_index(settings: Settings, skill_id: str, payload: dict[str, object]) -> None:
  payload["updated_at"] = _now_iso()
  atomic_write_json(_skill_versions_index_path(settings, skill_id), payload)


def _snapshot_skill_version(settings: Settings, skill_id: str, markdown: str, *, reason: str) -> dict[str, object] | None:
  content = str(markdown or "").strip()
  if not skill_id.strip() or not content:
    return None
  versions_dir = _skill_versions_dir(settings, skill_id)
  versions_dir.mkdir(parents=True, exist_ok=True)
  version_id = _version_id()
  filename = f"{version_id}.md"
  version_path = versions_dir / filename
  atomic_write_text(version_path, f"{content}\n")
  index = _load_skill_version_index(settings, skill_id)
  items = index.get("items")
  if not isinstance(items, list):
    items = []
  entry = {
    "id": version_id,
    "skill_id": skill_id,
    "reason": reason,
    "created_at": _now_iso(),
    "path": str(version_path),
    "size": len(content),
  }
  items.insert(0, entry)
  index["items"] = items[:_SKILL_VERSION_LIMIT]
  _save_skill_version_index(settings, skill_id, index)
  return entry


def _read_skill_version_markdown(entry: dict[str, object]) -> str:
  path = Path(str(entry.get("path") or ""))
  if not path.exists():
    return ""
  return path.read_text(encoding="utf-8")


def _diff_text(before: str, after: str, from_label: str, to_label: str, limit: int = 12000) -> str:
  diff = "\n".join(
    difflib.unified_diff(
      before.splitlines(),
      after.splitlines(),
      fromfile=from_label,
      tofile=to_label,
      lineterm="",
    )
  )
  if len(diff) <= limit:
    return diff
  return f"{diff[:limit].rstrip()}\n... diff truncated ..."


def _markdown_preview(text: str, limit: int = 12000) -> str:
  normalized = str(text or "")
  if len(normalized) <= limit:
    return normalized
  return f"{normalized[:limit].rstrip()}\n... markdown truncated ..."


def list_skill_versions(settings: Settings, skill_id: str) -> dict[str, object]:
  record = _find_skill_record(settings, skill_id)
  if record is None or record.item.source == "builtin":
    raise HTTPException(status_code=404, detail={"code": "skill_not_found", "message": "用户技能不存在"})
  current_markdown = record.path.read_text(encoding="utf-8") if record.path.exists() else ""
  index = _load_skill_version_index(settings, skill_id)
  items = []
  for raw_item in index.get("items") or []:
    if not isinstance(raw_item, dict):
      continue
    markdown = _read_skill_version_markdown(raw_item)
    items.append(
      {
        **raw_item,
        "diff_from_current": _diff_text(markdown, current_markdown, str(raw_item.get("id") or "version"), "current"),
        "version_markdown": _markdown_preview(markdown),
        "current_markdown": _markdown_preview(current_markdown),
      }
    )
  return {
    "skill_id": skill_id,
    "skill_name": record.item.name,
    "current_path": str(record.path),
    "items": items,
  }


def rollback_skill_version(settings: Settings, skill_id: str, version_id: str) -> dict[str, object]:
  record = _find_skill_record(settings, skill_id)
  if record is None or record.item.source == "builtin":
    raise HTTPException(status_code=404, detail={"code": "skill_not_found", "message": "用户技能不存在"})
  index = _load_skill_version_index(settings, skill_id)
  matched = next(
    (
      item for item in index.get("items") or []
      if isinstance(item, dict) and str(item.get("id") or "") == version_id
    ),
    None,
  )
  if matched is None:
    raise HTTPException(status_code=404, detail={"code": "skill_version_not_found", "message": "技能版本不存在"})
  target_markdown = _read_skill_version_markdown(matched)
  if not target_markdown.strip():
    raise HTTPException(status_code=404, detail={"code": "skill_version_missing", "message": "技能版本文件不存在"})
  current_markdown = record.path.read_text(encoding="utf-8") if record.path.exists() else ""
  _snapshot_skill_version(settings, skill_id, current_markdown, reason="before_rollback")
  atomic_write_text(record.path, target_markdown.strip() + "\n")
  record_skill_patch(settings, skill_id, action="rollback")
  refreshed = _find_skill_record(settings, skill_id)
  if refreshed is None:
    raise RuntimeError("技能回滚后没有被目录识别")
  return {
    "skill_id": skill_id,
    "skill_name": refreshed.item.name,
    "rolled_back_to": version_id,
    "saved_path": str(record.path),
    "diff": _diff_text(current_markdown, target_markdown, "before_rollback", version_id),
  }


def promote_skill_to_global(settings: Settings, skill_id: str) -> dict[str, object]:
  record = _find_skill_record(settings, skill_id)
  if record is None or record.item.source == "builtin":
    raise HTTPException(status_code=404, detail={"code": "skill_not_found", "message": "用户技能不存在"})
  if not record.path.exists():
    raise HTTPException(status_code=404, detail={"code": "skill_file_not_found", "message": "技能文件不存在"})

  current_markdown = record.path.read_text(encoding="utf-8")
  _snapshot_skill_version(settings, skill_id, current_markdown, reason="before_promote_global")
  frontmatter, body = _split_frontmatter(current_markdown)
  next_payload = dict(frontmatter)
  next_payload["name"] = str(next_payload.get("name") or record.item.name)
  next_payload["description"] = str(next_payload.get("description") or record.item.description)
  next_payload["version"] = _bump_version(str(next_payload.get("version") or "0.1.0"))
  next_payload["skill_id"] = skill_id
  next_payload["section_id"] = _USER_SKILL_SECTION_ID
  next_payload["section_title"] = _USER_SKILL_SECTION_TITLE
  next_payload["section_description"] = _USER_SKILL_SECTION_DESCRIPTION
  next_payload["category"] = "全局技能"
  next_payload["badge"] = str(next_payload.get("badge") or "沉")
  next_payload["accent"] = str(next_payload.get("accent") or "smoke")
  next_payload["source"] = "custom"
  next_payload["scope"] = "global"
  next_payload["panel"] = "conversation-skill"
  next_payload["updated_at"] = _now_iso()
  next_payload["promoted_at"] = _now_iso()
  next_payload["requires_project"] = _as_bool(next_payload.get("requires_project"), True)
  next_payload["requires_chapter"] = _as_bool(next_payload.get("requires_chapter"), False)
  next_payload["scenes"] = _ordered_unique(["跨项目", *_coerce_list(next_payload.get("scenes"))])[:4]
  next_payload["usage"] = _ordered_unique(
    [
      "适合在多个小说项目之间复用。",
      *_coerce_list(next_payload.get("usage")),
    ]
  )[:4]
  next_payload["limitations"] = _ordered_unique(_coerce_list(next_payload.get("limitations")))[:4]
  final_markdown = f"{_build_frontmatter(next_payload)}\n{body.strip()}\n"
  atomic_write_text(record.path, final_markdown)
  record_skill_patch(settings, skill_id, action="promote_global")
  refreshed = _find_skill_record(settings, skill_id)
  if refreshed is None:
    raise RuntimeError("技能提升为全局后没有被目录识别")
  return {
    "skill_id": skill_id,
    "skill_name": refreshed.item.name,
    "scope": "global",
    "saved_path": str(record.path),
    "diff": _diff_text(current_markdown, final_markdown, "before_promote_global", "global"),
  }


def export_skill_package(settings: Settings, skill_id: str) -> dict[str, object]:
  record = _find_skill_record(settings, skill_id)
  if record is None or record.item.source == "builtin":
    raise HTTPException(status_code=404, detail={"code": "skill_not_found", "message": "用户技能不存在"})
  if not record.path.exists():
    raise HTTPException(status_code=404, detail={"code": "skill_file_not_found", "message": "技能文件不存在"})
  markdown = record.path.read_text(encoding="utf-8")
  versions = list_skill_versions(settings, skill_id)
  return {
    "schema_version": 1,
    "exported_at": _now_iso(),
    "type": "gaoxia_skill_package",
    "skill": record.item.model_dump(mode="json"),
    "markdown": markdown,
    "version_count": len(versions.get("items") or []),
  }


def import_skill_package(settings: Settings, payload: SkillPackageImportRequest) -> dict[str, object]:
  package = payload.package
  if not isinstance(package, dict) or package.get("type") != "gaoxia_skill_package":
    raise HTTPException(status_code=400, detail={"code": "skill_package_invalid", "message": "技能包格式无效"})
  markdown = str(package.get("markdown") or "").strip()
  if not markdown:
    raise HTTPException(status_code=400, detail={"code": "skill_package_empty", "message": "技能包缺少技能正文"})

  frontmatter, body = _split_frontmatter(markdown)
  package_skill = package.get("skill") if isinstance(package.get("skill"), dict) else {}
  source_skill_id = str(frontmatter.get("skill_id") or package_skill.get("id") or "").strip()
  source_name = str(frontmatter.get("name") or package_skill.get("name") or "导入技能").strip()
  if not source_skill_id:
    source_skill_id = _slugify_skill_id(source_name)
  existing = _find_skill_record(settings, source_skill_id)
  if payload.strategy == "overwrite" and existing is not None and existing.item.source == "builtin":
    raise HTTPException(status_code=400, detail={"code": "skill_builtin", "message": "内置技能不能被技能包覆盖"})

  target_skill_id = source_skill_id
  action = "import"
  target_path: Path
  if payload.strategy == "overwrite" and existing is not None:
    target_path = existing.path
    current_markdown = target_path.read_text(encoding="utf-8") if target_path.exists() else ""
    _snapshot_skill_version(settings, target_skill_id, current_markdown, reason="before_import_package")
    action = "import_overwrite"
  else:
    target_skill_id = _ensure_unique_skill_id(settings, _safe_skill_id(source_skill_id), None)
    target_path = _next_skill_path(settings, target_skill_id)
    if target_skill_id != source_skill_id:
      action = "import_copy"

  next_payload = dict(frontmatter)
  next_payload["name"] = source_name
  next_payload["description"] = str(next_payload.get("description") or package_skill.get("description") or "").strip()
  next_payload["version"] = str(next_payload.get("version") or "0.1.0")
  next_payload["skill_id"] = target_skill_id
  next_payload["section_id"] = _USER_SKILL_SECTION_ID
  next_payload["section_title"] = _USER_SKILL_SECTION_TITLE
  next_payload["section_description"] = _USER_SKILL_SECTION_DESCRIPTION
  next_payload["category"] = str(next_payload.get("category") or package_skill.get("category") or "用户技能")
  next_payload["badge"] = str(next_payload.get("badge") or package_skill.get("badge") or "沉")
  next_payload["accent"] = str(next_payload.get("accent") or package_skill.get("accent") or "smoke")
  next_payload["source"] = "custom"
  next_payload["panel"] = "conversation-skill"
  next_payload["updated_at"] = _now_iso()
  next_payload["requires_project"] = _as_bool(next_payload.get("requires_project"), True)
  next_payload["requires_chapter"] = _as_bool(next_payload.get("requires_chapter"), False)
  next_payload["scenes"] = _ordered_unique(_coerce_list(next_payload.get("scenes")) or _coerce_list(package_skill.get("scenes")))[:4]
  next_payload["usage"] = _ordered_unique(_coerce_list(next_payload.get("usage")) or _coerce_list(package_skill.get("usage")))[:4]
  next_payload["limitations"] = _ordered_unique(_coerce_list(next_payload.get("limitations")) or _coerce_list(package_skill.get("limitations")))[:4]
  final_markdown = f"{_build_frontmatter(next_payload)}\n{body.strip()}\n"

  target_path.parent.mkdir(parents=True, exist_ok=True)
  atomic_write_text(target_path, final_markdown)
  _snapshot_skill_version(settings, target_skill_id, final_markdown, reason="after_import_package")
  record_skill_patch(settings, target_skill_id, action=action)
  refreshed = _find_skill_record(settings, target_skill_id)
  if refreshed is None:
    raise RuntimeError("技能包导入后没有被目录识别")
  return {
    "skill_id": target_skill_id,
    "skill_name": refreshed.item.name,
    "action": action,
    "saved_path": str(target_path),
  }


def list_skill_catalog(settings: Settings) -> SkillCatalog:
  section_items: dict[str, list[SkillItem]] = defaultdict(list)
  section_meta: dict[str, tuple[str, str, int]] = {}

  for record in _iter_skill_records(settings):
    section_id = str(record.frontmatter.get("section_id") if record.frontmatter else "") or record.path.parent.name
    section_items[section_id].append(record.item)
    section_meta[section_id] = record.section_meta

  sections = [
    SkillSection(
      id=section_id,
      title=meta[0],
      description=meta[1],
      order=meta[2],
      items=sorted(
        section_items[section_id],
        key=lambda item: (item.order, item.name, item.id),
      ),
    )
    for section_id, meta in sorted(
      section_meta.items(),
      key=lambda item: (item[1][2], item[1][0], item[0]),
    )
  ]

  categories = sorted(
    {
      item.category
      for section in sections
      for item in section.items
      if item.category.strip()
    }
  )
  return SkillCatalog(filters=["全部", *categories], sections=sections)


def get_custom_skill_prompt(settings: Settings, skill_id: str) -> str:
  record = _find_skill_record(settings, skill_id)
  if record is None or record.item.source == "builtin" or not record.body.strip():
    return ""
  skill_body = record.body.split("## 最近一次回归", 1)[0].strip()
  if not skill_body:
    return ""
  return (
    f"当前启用用户技能：{record.item.name}\n"
    f"技能说明：{record.item.description or '无'}\n"
    "请把下面这份技能当成固定工作流来执行，既保留判断，也保留输出格式。\n\n"
    f"{skill_body}"
  ).strip()


def get_custom_skill_prompt_block(settings: Settings, skill_ids: list[str]) -> str:
  blocks: list[str] = []
  for skill_id in _ordered_unique(skill_ids):
    prompt = get_custom_skill_prompt(settings, skill_id)
    if prompt:
      blocks.append(prompt)
  return "\n\n---\n\n".join(blocks).strip()


def custom_skill_names(settings: Settings, skill_ids: list[str]) -> list[str]:
  names: list[str] = []
  for skill_id in _ordered_unique(skill_ids):
    record = _find_skill_record(settings, skill_id)
    if record is not None and record.item.source == "custom":
      names.append(record.item.name)
  return names


def match_custom_skill_ids(settings: Settings, query: str, active_skill_ids: list[str] | None = None, limit: int = 3) -> list[str]:
  records = _iter_skill_records(settings)
  selected: list[str] = []
  active_ids = _ordered_unique(list(active_skill_ids or []))
  for skill_id in active_ids:
    record = _find_skill_record(settings, skill_id)
    if record is not None and record.item.source == "custom":
      selected.append(record.item.id)

  normalized_query = query.strip()
  if not normalized_query:
    return selected[:limit]

  scored: list[tuple[float, _SkillRecord]] = []
  normalized_compact = _normalize_for_similarity(normalized_query)
  for record in records:
    if record.item.source != "custom" or record.item.id in selected:
      continue
    candidate_text = "\n".join(
      [
        record.item.name,
        record.item.description,
        " ".join(record.item.scenes),
        " ".join(record.item.usage),
        record.item.instruction_preview,
      ]
    )
    score = _similarity_score(normalized_query, candidate_text)
    direct_hit = record.item.name and _normalize_for_similarity(record.item.name) in normalized_compact
    scene_hit = any(_normalize_for_similarity(scene) in normalized_compact for scene in record.item.scenes if scene.strip())
    if direct_hit:
      score = max(score, 0.9)
    elif scene_hit:
      score = max(score, 0.22)
    if score >= 0.12:
      scored.append((score, record))

  for _score, record in sorted(scored, key=lambda item: item[0], reverse=True):
    selected.append(record.item.id)
    if len(selected) >= limit:
      break
  return selected[:limit]


def _latest_message(messages: list[BrainstormMessage], role: str) -> str:
  for item in reversed(messages):
    if item.role == role and item.content.strip():
      return item.content.strip()
  return ""


def _normalize_for_similarity(text: str) -> str:
  return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.lower())


def _character_ngrams(text: str) -> set[str]:
  normalized = _normalize_for_similarity(text)
  if len(normalized) < 2:
    return {normalized} if normalized else set()
  return {normalized[index : index + 2] for index in range(len(normalized) - 1)}


def _similarity_score(left: str, right: str) -> float:
  left_grams = _character_ngrams(left)
  right_grams = _character_ngrams(right)
  if not left_grams or not right_grams:
    return 0.0
  union = left_grams | right_grams
  if not union:
    return 0.0
  return len(left_grams & right_grams) / len(union)


def _best_skill_match(records: list[_SkillRecord], query: str, *, source: str) -> tuple[_SkillRecord | None, float]:
  best_record = None
  best_score = 0.0
  for record in records:
    if source != "*" and record.item.source != source:
      continue
    candidate_text = "\n".join(
      [
        record.item.name,
        record.item.description,
        " ".join(record.item.scenes),
        " ".join(record.item.usage),
      ]
    )
    score = _similarity_score(query, candidate_text)
    if score > best_score:
      best_record = record
      best_score = score
  return best_record, best_score


def _reusable_signal_score(user_text: str, assistant_text: str) -> float:
  score = min(len(user_text.strip()) / 140.0, 0.2)
  cue_groups = [
    ("以后", "每次", "固定", "沉淀", "模板", "复用"),
    ("先", "再", "然后", "最后", "分成", "步骤"),
    ("检查", "整理", "改写", "提炼", "输出", "保留"),
  ]
  combined = f"{user_text}\n{assistant_text}"
  for group in cue_groups:
    if any(keyword in combined for keyword in group):
      score += 0.17
  if "\n" in combined or any(token in assistant_text for token in ("1.", "2.", "3.", "一、", "二、")):
    score += 0.12
  if len(re.findall(r"[，。；：:\n]", user_text)) >= 3:
    score += 0.08
  return min(score, 0.95)


def _generic_skill_highlights(user_text: str, assistant_text: str) -> list[str]:
  highlights: list[str] = []
  if any(token in user_text for token in ("先", "再", "然后", "最后")) or any(
    token in assistant_text for token in ("先", "再", "然后", "最后")
  ):
    highlights.append("这轮已经有稳定的步骤顺序。")
  if any(token in assistant_text for token in ("输出", "建议", "清单", "要点")):
    highlights.append("输出口径已经比较清楚。")
  highlights.append("下次可以直接从主对话复用，不用重新解释。")
  return _ordered_unique(highlights)[:3]


def suggest_reusable_skill(settings: Settings, messages: list[BrainstormMessage], reply: str, active_skill_id: str = "") -> SkillSuggestion | None:
  latest_user = _latest_message(messages, "user")
  latest_assistant = reply.strip() or _latest_message(messages, "assistant")
  if len(latest_user) < 18:
    return None

  query = f"{latest_user}\n{latest_assistant}".strip()
  records = _iter_skill_records(settings)
  best_builtin, builtin_score = _best_skill_match(records, query, source="builtin")
  best_custom, custom_score = _best_skill_match(records, query, source="custom")

  if active_skill_id.strip():
    active_record = _find_skill_record(settings, active_skill_id)
    if active_record is not None and active_record.item.source == "custom":
      best_custom = active_record
      custom_score = max(custom_score, _similarity_score(query, f"{active_record.item.name}\n{active_record.item.description}\n{active_record.body}"))
      if custom_score >= 0.08 or any(token in latest_user for token in ("再", "补", "加", "继续", "顺便", "加强")):
        return SkillSuggestion(
          action="iterate",
          summary=f"这轮是在给「{active_record.item.name}」补新规则，可以直接更新旧技能。",
          reason="你已经选中了对应的用户技能，而且这轮内容明显是在补边界或补口径。",
          highlights=_generic_skill_highlights(latest_user, latest_assistant),
          confidence=min(0.92, 0.5 + custom_score),
          target_skill_id=active_record.item.id,
          target_skill_name=active_record.item.name,
        )

  if best_custom is not None and custom_score >= _SIMILARITY_CUTOFF_CUSTOM:
    return SkillSuggestion(
      action="iterate",
      summary=f"这轮和「{best_custom.item.name}」还是同一类任务，可以把新要求并进旧技能。",
      reason="系统找到了足够接近的用户技能，这轮更像是在补边界和补规则。",
      highlights=_generic_skill_highlights(latest_user, latest_assistant),
      confidence=min(0.95, 0.45 + custom_score),
      target_skill_id=best_custom.item.id,
      target_skill_name=best_custom.item.name,
    )

  if best_builtin is not None and builtin_score >= _SIMILARITY_CUTOFF_BUILTIN:
    return None

  reusable_score = _reusable_signal_score(latest_user, latest_assistant)
  if reusable_score < _REUSABLE_SIGNAL_CUTOFF:
    return None

  return SkillSuggestion(
    action="create",
    summary="这轮已经形成一套可重复的处理方式，可以沉淀成新技能。",
    reason="当前目录里没有足够接近的现成技能，而且这轮任务已经有固定步骤和输出口径。",
    highlights=_generic_skill_highlights(latest_user, latest_assistant),
    confidence=reusable_score,
  )


def _conversation_transcript(messages: list[BrainstormMessage]) -> str:
  return "\n".join(f"{'用户' if item.role == 'user' else '助手'}：{item.content.strip()}" for item in messages if item.content.strip())


def _derive_skill_name(messages: list[BrainstormMessage], fallback: str = "") -> str:
  if fallback.strip():
    return fallback.strip()[:40]
  latest_user = _latest_message(messages, "user")
  if not latest_user:
    return "用户沉淀技能"
  cleaned = re.sub(r"[“”\"'（）()，。！？!?:：；;、]", " ", latest_user)
  cleaned = re.sub(r"\s+", " ", cleaned).strip()
  fragments = [fragment.strip() for fragment in re.split(r"[，。；;:\n]", cleaned) if fragment.strip()]
  for fragment in fragments:
    if 4 <= len(fragment) <= 18:
      return fragment
  compact = cleaned[:16]
  return compact or "用户沉淀技能"


def _derive_description(messages: list[BrainstormMessage], name: str) -> str:
  latest_user = _latest_message(messages, "user")
  latest_assistant = _latest_message(messages, "assistant")
  base = latest_assistant or latest_user or name
  return _compact_text(base, 72) or f"围绕「{name}」整理固定工作流。"


def _derive_scenes(messages: list[BrainstormMessage]) -> list[str]:
  latest_user = _latest_message(messages, "user")
  tokens = [
    "开书", "卡文", "续写", "蓝图", "章节", "设定", "角色", "对白", "去 AI", "润色",
    "检查", "诊断", "改稿", "风格", "资料", "提炼", "整理",
  ]
  matched = [token for token in tokens if token in latest_user]
  if matched:
    return matched[:3]
  return ["复用", "工作流", "主对话"]


def _coerce_list(value: object) -> list[str]:
  if isinstance(value, list):
    return [str(item).strip() for item in value if str(item).strip()]
  if isinstance(value, str) and value.strip():
    return [item.strip() for item in value.split("|") if item.strip()]
  return []


def _split_candidate_sentences(text: str) -> list[str]:
  sentences = [
    item.strip(" -0123456789.、）)")
    for item in re.split(r"[\n。；;]", text)
    if item.strip()
  ]
  return [item for item in sentences if 6 <= len(item) <= 56]


def _derive_steps(messages: list[BrainstormMessage], existing_body: str = "") -> list[str]:
  latest_assistant = _latest_message(messages, "assistant")
  latest_user = _latest_message(messages, "user")
  candidates = _split_candidate_sentences(latest_assistant) + _split_candidate_sentences(latest_user)
  steps = _ordered_unique(candidates)[:4]
  if len(steps) >= 3:
    return steps
  inherited = _split_candidate_sentences(existing_body)
  steps = _ordered_unique(steps + inherited)[:4]
  while len(steps) < 3:
    steps.append(
      [
        "先判断这轮任务真正要解决的目标和边界。",
        "再只抽取和当前问题有关的项目上下文。",
        "按固定格式给出可以直接执行的建议或结果。",
      ][len(steps)]
    )
  return steps[:4]


def _default_skill_scope(payload: SkillMaterializeRequest, existing_record: _SkillRecord | None) -> tuple[bool, bool]:
  if existing_record is None:
    return True, bool(payload.selected_chapter_id.strip())
  return existing_record.item.requires_project, existing_record.item.requires_chapter


def _fallback_skill_payload(payload: SkillMaterializeRequest, existing_record: _SkillRecord | None) -> dict[str, object]:
  default_requires_project, default_requires_chapter = _default_skill_scope(payload, existing_record)
  name = _derive_skill_name(payload.messages, payload.skill_name or (existing_record.item.name if existing_record else ""))
  usage = _ordered_unique(
    (existing_record.item.usage if existing_record else [])
    + [
      "适合在主对话里直接复用这类处理方式。",
      "适合把本轮要求整理成稳定步骤再执行。",
    ]
  )[:3]
  limitations = _ordered_unique(
    (existing_record.item.limitations if existing_record else [])
    + [
      "这版主要覆盖当前对话里出现过的边界，没包含所有变体。",
      "如果后面新增了更细的输出格式，还需要继续补。",
    ]
  )[:3]
  steps = _derive_steps(payload.messages, existing_record.body if existing_record else "")
  body_markdown = (
    f"# {name}\n\n"
    "## 适用场景\n"
    + "\n".join(f"- {item}" for item in usage)
    + "\n\n## 输入要求\n"
    "- 先说清本轮要处理的对象、目标和不能动的部分。\n"
    "- 如果这轮只针对某一章或某个片段，直接点明范围。\n\n"
    "## 执行步骤\n"
    + "\n".join(f"{index}. {item}" for index, item in enumerate(steps, start=1))
    + "\n\n## 输出要求\n"
    "- 先给明确判断，再给可直接执行的建议。\n"
    "- 如果这轮涉及改写，说明哪些内容必须保留。\n"
    "- 结尾补 1 到 3 条下一轮还值得继续追问的点。\n\n"
    "## 边界\n"
    + "\n".join(f"- {item}" for item in limitations)
  )
  return {
    "name": name,
    "description": _derive_description(payload.messages, name),
    "category": "用户技能",
    "scenes": _derive_scenes(payload.messages),
    "usage": usage,
    "limitations": limitations,
    "requires_project": default_requires_project,
    "requires_chapter": default_requires_chapter,
    "body_markdown": body_markdown,
  }


def _fallback_or_raise_on_update(
  payload: SkillMaterializeRequest,
  existing_record: _SkillRecord | None,
  message: str,
) -> dict[str, object]:
  if existing_record is None:
    return _fallback_skill_payload(payload, existing_record)
  raise HTTPException(
    status_code=502,
    detail={
      "code": "skill_materialize_failed",
      "message": f"{message}，原技能未改动",
    },
  )


def _generate_skill_payload(settings: Settings, payload: SkillMaterializeRequest, existing_record: _SkillRecord | None) -> dict[str, object]:
  default_requires_project, default_requires_chapter = _default_skill_scope(payload, existing_record)
  project_detail = get_project_detail(settings, payload.project_id)
  transcript = _conversation_transcript(payload.messages)
  existing_names = [
    record.item.name
    for record in _iter_skill_records(settings)
    if existing_record is None or record.item.id != existing_record.item.id
  ]
  user_prompt = (
    f"当前项目：{project_detail.name}\n"
    f"题材：{project_detail.genre}\n"
    f"操作：{'更新已有技能' if existing_record is not None and payload.action == 'iterate' else '创建新技能'}\n"
    f"已有技能名称：{', '.join(existing_names[:18]) or '无'}\n"
    f"建议技能名：{payload.skill_name.strip() or '未指定'}\n"
    f"聊天记录：\n{transcript}\n"
  )
  if existing_record is not None:
    user_prompt += f"\n当前技能正文：\n{existing_record.body}\n"

  try:
    content = _invoke_model(
      settings,
      [
        {"role": "system", "content": _SKILL_DRAFT_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt.strip()},
      ],
      task_name="skill_materialize",
      temperature=0.4,
      max_tokens=2600,
    )
  except Exception:
    return _fallback_or_raise_on_update(payload, existing_record, "技能更新失败，模型没有返回可用草稿")

  parsed = _extract_json_object(content)
  if not isinstance(parsed, dict):
    return _fallback_or_raise_on_update(payload, existing_record, "技能更新失败，模型返回的草稿格式不正确")

  name = _string_from_keys(parsed, "name", "title") or _derive_skill_name(payload.messages, payload.skill_name)
  body_markdown = _string_from_keys(parsed, "body_markdown", "markdown", "content")
  if not body_markdown:
    return _fallback_or_raise_on_update(payload, existing_record, "技能更新失败，模型草稿缺少正文")
  return {
    "name": name,
    "description": _string_from_keys(parsed, "description", "summary") or _derive_description(payload.messages, name),
    "category": _string_from_keys(parsed, "category", "type") or "用户技能",
    "scenes": _string_list_from_keys(parsed, "scenes", "scene_tags") or _derive_scenes(payload.messages),
    "usage": _string_list_from_keys(parsed, "usage", "applicable_scenarios") or _fallback_skill_payload(payload, existing_record)["usage"],
    "limitations": _string_list_from_keys(parsed, "limitations", "boundaries") or _fallback_skill_payload(payload, existing_record)["limitations"],
    "requires_project": bool(parsed.get("requires_project", default_requires_project)),
    "requires_chapter": bool(parsed.get("requires_chapter", default_requires_chapter)),
    "body_markdown": body_markdown,
  }


def _normalize_heading_body(name: str, body_markdown: str) -> str:
  body = body_markdown.strip()
  if not body.startswith("# "):
    body = f"# {name}\n\n{body}"
  sections = {title: f"## {title}" in body for title in _SKILL_BODY_SECTION_TITLES}
  if sections["适用场景"] is False:
    body += "\n\n## 适用场景\n- 适合在主对话里直接复用这类工作流。"
  if sections["输入要求"] is False:
    body += "\n\n## 输入要求\n- 先把对象、目标和不能动的部分说清楚。"
  if sections["执行步骤"] is False:
    body += "\n\n## 执行步骤\n1. 先判断目标和边界。\n2. 再抽取必要上下文。\n3. 最后给出可直接执行的结论。"
  if sections["输出要求"] is False:
    body += "\n\n## 输出要求\n- 先给判断，再给建议。"
  if sections["边界"] is False:
    body += "\n\n## 边界\n- 这版还需要继续迭代。"
  return body.strip()


def _slugify_skill_id(name: str, fallback: str = "") -> str:
  normalized = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
  if normalized:
    return f"user-{normalized}"
  if fallback.strip():
    return fallback.strip()
  return f"user-skill-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"


def _ensure_unique_skill_id(settings: Settings, skill_id: str, existing_record: _SkillRecord | None) -> str:
  candidate = skill_id
  if existing_record is not None:
    return candidate
  suffix = 2
  while _find_skill_record(settings, candidate) is not None:
    candidate = f"{skill_id}-{suffix}"
    suffix += 1
  return candidate


def _next_skill_path(settings: Settings, skill_id: str) -> Path:
  return skills_dir(settings) / _USER_SKILL_SECTION_ID / skill_id / "SKILL.md"


def _bump_version(version: str) -> str:
  match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", version.strip())
  if not match:
    return "0.1.0"
  major, minor, patch = [int(item) for item in match.groups()]
  return f"{major}.{minor}.{patch + 1}"


def _build_frontmatter(payload: dict[str, object]) -> str:
  lines = ["---"]
  scalar_keys = [
    "name",
    "description",
    "version",
    "skill_id",
    "section_id",
    "section_title",
    "section_description",
    "category",
    "badge",
    "accent",
    "source",
    "scope",
    "panel",
    "updated_at",
    "promoted_at",
    "verification_summary",
  ]
  for key in scalar_keys:
    value = str(payload.get(key) or "").strip()
    if value:
      lines.append(f"{key}: {value}")
  lines.append(f"requires_project: {'true' if payload.get('requires_project', True) else 'false'}")
  lines.append(f"requires_chapter: {'true' if payload.get('requires_chapter', False) else 'false'}")
  for list_key in ("scenes", "usage", "limitations"):
    lines.append(f"{list_key}:")
    for item in payload.get(list_key) or []:
      value = str(item).strip()
      if value:
        lines.append(f"  - {value}")
  lines.append("---")
  return "\n".join(lines)


def _skill_overlap_note(records: list[_SkillRecord], item: SkillItem) -> str:
  siblings = [record for record in records if record.item.id != item.id]
  best_match, best_score = _best_skill_match(siblings, f"{item.name}\n{item.description}", source="*")
  if best_match is None or best_score < 0.16:
    return "和现有技能没有明显重叠。"
  return f"和「{best_match.item.name}」有部分交叉，后面可以继续把边界写得更窄。"


def _verify_skill(records: list[_SkillRecord], item: SkillItem, body_markdown: str) -> SkillVerificationReport:
  body = body_markdown.strip()
  checks = [
    "SKILL.md 已生成并能被本地目录识别。",
    "适用场景、输入要求、执行步骤、输出要求、边界五个区块都已具备。",
    "这个技能会在主对话里直接作为 conversation-skill 启用。",
    _skill_overlap_note(records, item),
  ]
  strengths = _ordered_unique(
    [
      "已经把执行步骤固定下来。",
      "已经把输出口径收成可复用版本。",
      "可以随着后续对话继续迭代。",
      "适用边界已经单独写出来，后面排查会更直接。",
    ]
  )[:3]
  improvement_points = _ordered_unique(item.limitations or ["后面可以继续补更极端的边界样例。"])
  if len(body) < 360:
    improvement_points.append("正文还可以再补一到两个更具体的执行样例。")
  summary = (
    f"已完成一次本地自检：结构完整，目录可读，"
    f"{'当前没有明显重叠。' if '没有明显重叠' in checks[-1] else '但和现有技能还有一点交叉。'}"
  )
  return SkillVerificationReport(
    summary=summary,
    checks=checks,
    strengths=strengths,
    improvement_points=_ordered_unique(improvement_points)[:4],
  )


def _attach_verification_section(body_markdown: str, verification: SkillVerificationReport) -> str:
  body = body_markdown.split("## 最近一次回归", 1)[0].strip()
  section_lines = [
    "## 最近一次回归",
    f"- 结论：{verification.summary}",
  ]
  for item in verification.checks:
    section_lines.append(f"- 已检查：{item}")
  for item in verification.improvement_points:
    section_lines.append(f"- 还可加强：{item}")
  return f"{body}\n\n" + "\n".join(section_lines)


def materialize_skill(settings: Settings, payload: SkillMaterializeRequest) -> SkillMaterializeResult:
  existing_record = _find_skill_record(settings, payload.skill_id)
  if payload.action == "iterate" and payload.skill_id.strip() and existing_record is None:
    raise HTTPException(status_code=404, detail={"code": "skill_not_found", "message": "要更新的技能不存在"})
  if existing_record is not None and existing_record.item.source == "builtin":
    raise HTTPException(status_code=400, detail={"code": "skill_builtin", "message": "内置技能不能直接覆写，请新建用户技能"})

  draft = _generate_skill_payload(settings, payload, existing_record)
  skill_name = str(draft.get("name") or "").strip() or _derive_skill_name(payload.messages, payload.skill_name)
  body_markdown = _normalize_heading_body(skill_name, str(draft.get("body_markdown") or ""))
  skill_id = existing_record.item.id if existing_record is not None else _ensure_unique_skill_id(settings, _slugify_skill_id(skill_name), existing_record)
  current_version = str(existing_record.frontmatter.get("version") or "0.1.0") if existing_record and existing_record.frontmatter else "0.1.0"
  version = _bump_version(current_version) if existing_record is not None else "0.1.0"
  frontmatter_payload = {
    "name": skill_name,
    "description": _compact_text(str(draft.get("description") or _derive_description(payload.messages, skill_name)), 80),
    "version": version,
    "skill_id": skill_id,
    "section_id": _USER_SKILL_SECTION_ID,
    "section_title": _USER_SKILL_SECTION_TITLE,
    "section_description": _USER_SKILL_SECTION_DESCRIPTION,
    "category": str(draft.get("category") or "用户技能").strip() or "用户技能",
    "badge": "沉",
    "accent": "smoke",
    "source": "custom",
    "panel": "conversation-skill",
    "requires_project": bool(draft.get("requires_project", True)),
    "requires_chapter": bool(draft.get("requires_chapter", bool(payload.selected_chapter_id.strip()))),
    "updated_at": _now_iso(),
    "scenes": _ordered_unique(_coerce_list(draft.get("scenes")))[:4],
    "usage": _ordered_unique(_coerce_list(draft.get("usage")))[:4],
    "limitations": _ordered_unique(_coerce_list(draft.get("limitations")))[:4],
    "verification_summary": "",
  }
  provisional_markdown = f"{_build_frontmatter(frontmatter_payload)}\n{body_markdown.strip()}\n"
  temp_path = existing_record.path if existing_record is not None else _next_skill_path(settings, skill_id)
  if existing_record is not None and temp_path.exists():
    _snapshot_skill_version(settings, skill_id, temp_path.read_text(encoding="utf-8"), reason="before_update")
  temp_path.parent.mkdir(parents=True, exist_ok=True)
  atomic_write_text(temp_path, provisional_markdown)

  refreshed_record = _find_skill_record(settings, skill_id)
  if refreshed_record is None:
    raise RuntimeError("技能写入后没有被目录重新识别")
  verification = _verify_skill(_iter_skill_records(settings), refreshed_record.item, body_markdown)
  frontmatter_payload["verification_summary"] = verification.summary
  final_body = _attach_verification_section(body_markdown, verification)
  final_markdown = f"{_build_frontmatter(frontmatter_payload)}\n{final_body.strip()}\n"
  atomic_write_text(temp_path, final_markdown)
  _snapshot_skill_version(settings, skill_id, final_markdown, reason="after_materialize")

  final_record = _find_skill_record(settings, skill_id)
  if final_record is None:
    raise RuntimeError("技能二次写回后没有被目录识别")
  action = "iterate" if existing_record is not None or payload.action == "iterate" else "create"
  try:
    record_skill_patch(settings, skill_id, action=action, project_id=payload.project_id)
  except Exception as error:
    append_app_log(settings, f"技能统计写入失败：{error}", level="WARNING")
  message = f"已{'更新' if action == 'iterate' else '沉淀'}技能「{final_record.item.name}」。"
  return SkillMaterializeResult(
    action=action,
    message=message,
    skill=final_record.item,
    saved_path=str(temp_path),
    skill_markdown=final_markdown,
    verification=verification,
  )
