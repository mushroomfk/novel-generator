from __future__ import annotations

import base64
import hashlib
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from novel_backend.config import Settings
from novel_backend.models import (
  CreateProjectRequest,
  ExistingNovelImportRequest,
  ExistingNovelTakeoverChapter,
  ExistingNovelTakeoverImportResult,
  ExistingNovelTakeoverReport,
  ExistingNovelTakeoverStateResult,
  ProjectSummary,
)
from novel_backend.services.import_service import extract_import_text
from novel_backend.services.project_service import (
  _chapter_file_path,
  _project_summary_or_404,
  _project_dir,
  _rebuild_project_knowledge,
  _touch_project_timestamp,
  _write_snapshot,
  create_project,
  update_project_targets,
)
from novel_backend.utils.jsonfile import atomic_write_json, atomic_write_text, read_json


_TAKEOVER_SCHEMA_VERSION = "1"
_TAKEOVER_DIRNAME = "takeover"
_TAKEOVER_STATE_FILENAME = "state.json"
_TAKEOVER_SOURCE_FILENAME = "source.txt"
_TAKEOVER_CHAPTERS_FILENAME = "chapters.json"
_TAKEOVER_REPORT_FILENAME = "report.md"
_MAX_PREVIEW_LENGTH = 260
_MAX_IMPORTED_CHAPTERS = 1000
_RECENT_HANDOFF_CHAPTERS = 3
_HEADING_PATTERNS = (
  re.compile(
    r"^\s{0,4}(?:#{1,6}\s*)?"
    r"(第\s*[零〇一二三四五六七八九十百千万两\d]+\s*[章节回幕篇卷集部][^\n]{0,80})\s*$"
  ),
  re.compile(r"^\s{0,4}(?:#{1,6}\s*)?((?:Chapter|CHAPTER|chapter)\s+\d+[^\n]{0,80})\s*$"),
)
_CHAPTER_NUMBER_PATTERN = re.compile(
  r"(?:第\s*([零〇一二三四五六七八九十百千万两\d]+)\s*[章节回幕篇卷集部]|(?:Chapter|CHAPTER|chapter)\s+(\d+))"
)
_CN_DIGITS = {
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
_CN_UNITS = {
  "十": 10,
  "百": 100,
  "千": 1000,
}


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def _takeover_dir(project_dir: Path) -> Path:
  return Path(project_dir) / ".gaoxia" / _TAKEOVER_DIRNAME


def _takeover_state_path(project_dir: Path) -> Path:
  return _takeover_dir(project_dir) / _TAKEOVER_STATE_FILENAME


def _takeover_source_path(project_dir: Path) -> Path:
  return _takeover_dir(project_dir) / _TAKEOVER_SOURCE_FILENAME


def _takeover_chapters_path(project_dir: Path) -> Path:
  return _takeover_dir(project_dir) / _TAKEOVER_CHAPTERS_FILENAME


def _takeover_report_path(project_dir: Path) -> Path:
  return _takeover_dir(project_dir) / _TAKEOVER_REPORT_FILENAME


def _save_state(project_dir: Path, state: dict[str, object]) -> dict[str, object]:
  state["schema_version"] = _TAKEOVER_SCHEMA_VERSION
  state["updated_at"] = _now_iso()
  atomic_write_json(_takeover_state_path(project_dir), state)
  return state


def _load_state(project_dir: Path) -> dict[str, object]:
  data = read_json(_takeover_state_path(project_dir), {})
  return data if isinstance(data, dict) else {}


def _decode_source_text(request: ExistingNovelImportRequest) -> str:
  direct_content = request.content.replace("\r\n", "\n").replace("\r", "\n").strip("\ufeff").strip()
  if direct_content:
    return direct_content

  encoded = request.content_base64.strip()
  if not encoded:
    raise HTTPException(
      status_code=400,
      detail={"code": "existing_novel_empty", "message": "旧稿内容不能为空"},
    )
  try:
    data = base64.b64decode(encoded.encode("utf-8"), validate=True)
  except Exception as error:
    raise HTTPException(
      status_code=400,
      detail={"code": "existing_novel_invalid_file", "message": "旧稿文件编码无效"},
    ) from error

  content = extract_import_text(request.source_filename or "旧稿.txt", data, settings=None).strip()
  if not content:
    raise HTTPException(
      status_code=400,
      detail={"code": "existing_novel_empty_file", "message": "旧稿文件没有可导入正文"},
    )
  return content.replace("\r\n", "\n").replace("\r", "\n").strip("\ufeff").strip()


def _cn_number_to_int(value: str) -> int | None:
  text = value.strip()
  if not text:
    return None
  if text.isdigit():
    try:
      return int(text)
    except ValueError:
      return None

  total = 0
  section = 0
  number = 0
  for char in text:
    if char in _CN_DIGITS:
      number = _CN_DIGITS[char]
      continue
    if char == "万":
      section += number
      total += (section or 1) * 10000
      section = 0
      number = 0
      continue
    unit = _CN_UNITS.get(char)
    if unit is None:
      return None
    section += (number or 1) * unit
    number = 0
  return total + section + number


def _heading_number(heading: str) -> int | None:
  match = _CHAPTER_NUMBER_PATTERN.search(heading)
  if match is None:
    return None
  raw_value = match.group(1) or match.group(2) or ""
  parsed = _cn_number_to_int(raw_value)
  return parsed if parsed and parsed > 0 else None


def _clean_heading(raw_line: str, fallback_index: int) -> str:
  line = raw_line.strip()
  line = re.sub(r"^#{1,6}\s*", "", line).strip()
  return line[:80] or f"第 {fallback_index} 章"


def _find_heading(line: str) -> str:
  if len(line.strip()) > 100:
    return ""
  for pattern in _HEADING_PATTERNS:
    match = pattern.match(line)
    if match:
      return _clean_heading(match.group(1), 1)
  return ""


def _compact_preview(content: str, limit: int = _MAX_PREVIEW_LENGTH) -> str:
  collapsed = " ".join(line.strip() for line in content.splitlines() if line.strip())
  return collapsed[:limit]


def _content_hash(content: str) -> str:
  return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _chapter_warning_for_size(character_count: int) -> list[str]:
  warnings: list[str] = []
  if character_count < 500:
    warnings.append("章节很短，可能是标题、序言或拆章误判")
  if character_count > 35_000:
    warnings.append("章节很长，建议检查是否漏拆")
  return warnings


def split_existing_novel_chapters(content: str) -> tuple[list[dict[str, object]], list[str], list[str]]:
  normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
  if not normalized:
    return [], ["旧稿内容为空"], []

  headings: list[dict[str, object]] = []
  cursor = 0
  line_number = 1
  for raw_line in normalized.splitlines(keepends=True):
    line_text = raw_line.rstrip("\n")
    heading = _find_heading(line_text)
    if heading:
      headings.append(
        {
          "offset": cursor,
          "heading": heading,
          "source_heading": line_text.strip(),
          "line": line_number,
          "number": _heading_number(heading),
        }
      )
    cursor += len(raw_line)
    if raw_line.endswith("\n"):
      line_number += 1
  total_line_count = max(1, line_number)

  warnings: list[str] = []
  quality_checks: list[str] = []
  if not headings:
    chapter = {
      "index": 1,
      "title": "第 1 章",
      "source_heading": "",
      "content": normalized,
      "character_count": len(normalized.strip()),
      "start_line": 1,
      "end_line": total_line_count,
      "source_chapter_number": None,
      "warnings": ["没有识别到章节标题，已把全文作为第 1 章"],
      "content_hash": _content_hash(normalized),
      "opening_preview": _compact_preview(normalized[:800]),
      "ending_preview": _compact_preview(normalized[-1000:]),
    }
    return [chapter], ["没有识别到章节标题"], ["全文已作为单章导入"]

  quality_checks.append(f"识别到 {len(headings)} 个章节标题")
  chapters: list[dict[str, object]] = []
  first_offset = int(headings[0]["offset"])
  if first_offset > 0 and normalized[:first_offset].strip():
    warnings.append("首个章节标题前存在正文，已并入第 1 章")

  seen_numbers: dict[int, int] = {}
  parsed_numbers: list[int] = []
  for index, heading in enumerate(headings, start=1):
    start = 0 if index == 1 else int(heading["offset"])
    next_offset = int(headings[index]["offset"]) if index < len(headings) else len(normalized)
    next_line = int(headings[index]["line"]) if index < len(headings) else total_line_count + 1
    section = normalized[start:next_offset].strip()
    source_number = heading.get("number")
    chapter_warnings = _chapter_warning_for_size(len(section))
    if isinstance(source_number, int):
      parsed_numbers.append(source_number)
      seen_numbers[source_number] = seen_numbers.get(source_number, 0) + 1
      if source_number != index:
        chapter_warnings.append(f"标题章号是 {source_number}，系统导入顺序是 {index}")

    chapters.append(
      {
        "index": index,
        "title": str(heading["heading"])[:80] or f"第 {index} 章",
        "source_heading": str(heading["source_heading"])[:120],
        "content": section,
        "character_count": len(section),
        "start_line": int(heading["line"]) if index > 1 else 1,
        "end_line": max(int(heading["line"]), next_line - 1),
        "source_chapter_number": source_number,
        "warnings": chapter_warnings,
        "content_hash": _content_hash(section),
        "opening_preview": _compact_preview(section[:800]),
        "ending_preview": _compact_preview(section[-1000:]),
      }
    )

  duplicate_numbers = sorted(number for number, count in seen_numbers.items() if count > 1)
  if duplicate_numbers:
    warnings.append(f"存在重复章号：{', '.join(str(item) for item in duplicate_numbers[:12])}")

  if parsed_numbers:
    sorted_numbers = sorted(set(parsed_numbers))
    missing = [
      number
      for number in range(sorted_numbers[0], sorted_numbers[-1] + 1)
      if number not in seen_numbers
    ]
    if missing:
      warnings.append(f"标题章号不连续，缺少：{', '.join(str(item) for item in missing[:12])}")
    if sorted_numbers and sorted_numbers[0] != 1:
      warnings.append(f"首个标题章号是 {sorted_numbers[0]}，请确认是否只导入了中段正文")

  if any(item["warnings"] for item in chapters):
    warnings.append("部分章节长度或章号需要人工确认")

  quality_checks.append("已记录每章标题、行号、字数、开头片段和结尾片段")
  return chapters, warnings, quality_checks


def _estimate_target_chapters(chapter_count: int, requested: int | None) -> tuple[int, list[str]]:
  warnings: list[str] = []
  if requested and requested > 0:
    target = max(requested, chapter_count)
    if requested < chapter_count:
      warnings.append(f"预计总章数小于已识别章数，已改为 {chapter_count} 章")
    return min(1000, target), warnings
  if chapter_count >= 20:
    return min(1000, chapter_count + 1), warnings
  return max(20, chapter_count + 1), warnings


def _estimate_target_words(content_length: int, requested: int | None) -> int:
  if requested and requested > 0:
    return min(2_000_000, max(1000, requested))
  estimated = max(200_000, int(math.ceil(content_length * 1.6)))
  return min(2_000_000, max(1000, estimated))


def _confidence(chapters: list[dict[str, object]], warnings: list[str]) -> float:
  if not chapters:
    return 0.0
  score = 0.92 if len(chapters) >= 2 else 0.58
  if any("没有识别到章节标题" in item for item in warnings):
    score -= 0.22
  if any("不连续" in item for item in warnings):
    score -= 0.12
  if any("重复章号" in item for item in warnings):
    score -= 0.12
  issue_chapters = sum(1 for item in chapters if item.get("warnings"))
  score -= min(0.25, issue_chapters * 0.025)
  return round(min(1.0, max(0.1, score)), 2)


def _report_chapter_model(chapter: dict[str, object]) -> ExistingNovelTakeoverChapter:
  return ExistingNovelTakeoverChapter(
    index=int(chapter.get("index") or 1),
    title=str(chapter.get("title") or ""),
    source_heading=str(chapter.get("source_heading") or ""),
    character_count=int(chapter.get("character_count") or 0),
    start_line=int(chapter.get("start_line") or 0),
    end_line=int(chapter.get("end_line") or 0),
    warnings=[
      str(item)
      for item in chapter.get("warnings", [])
      if str(item).strip()
    ] if isinstance(chapter.get("warnings"), list) else [],
  )


def _state_text_list(state: dict[str, object], key: str) -> list[str]:
  raw_items = state.get(key)
  if not isinstance(raw_items, list):
    return []
  return [str(item) for item in raw_items if str(item).strip()]


def _append_unique(items: list[str], value: str) -> None:
  cleaned = str(value or "").strip()
  if cleaned and cleaned not in items:
    items.append(cleaned)


def _build_report(
  *,
  task_id: str,
  state: dict[str, object],
  summary: ProjectSummary,
  chapters: list[dict[str, object]],
  warnings: list[str],
  quality_checks: list[str],
) -> ExistingNovelTakeoverReport:
  written_chapters = [item for item in chapters if str(item.get("content") or "").strip()]
  last_chapter = written_chapters[-1] if written_chapters else {}
  next_chapter_index = len(written_chapters) + 1 if len(written_chapters) < summary.target_chapters else None
  return ExistingNovelTakeoverReport(
    task_id=task_id,
    status=str(state.get("status") or "completed"),
    source_filename=str(state.get("source_filename") or ""),
    source_hash=str(state.get("source_hash") or ""),
    original_character_count=int(state.get("original_character_count") or 0),
    detected_chapter_count=len(chapters),
    applied_chapter_count=len(written_chapters),
    target_chapters=summary.target_chapters,
    confidence=_confidence(chapters, warnings),
    next_chapter_index=next_chapter_index,
    last_chapter_title=str(last_chapter.get("title") or ""),
    last_chapter_tail=str(last_chapter.get("ending_preview") or ""),
    warnings=warnings[:80],
    quality_checks=quality_checks[:80],
    chapters=[_report_chapter_model(item) for item in chapters],
    updated_at=str(state.get("updated_at") or _now_iso()),
  )


def _recent_written_chapters(chapters: list[dict[str, object]], limit: int = _RECENT_HANDOFF_CHAPTERS) -> list[dict[str, object]]:
  written = [item for item in chapters if str(item.get("content") or "").strip()]
  return written[-limit:]


def _chapter_handoff_line(chapter: dict[str, object]) -> str:
  title = str(chapter.get("title") or f"第 {chapter.get('index')} 章")
  ending = str(chapter.get("ending_preview") or "").strip()
  opening = str(chapter.get("opening_preview") or "").strip()
  preview = ending or opening
  suffix = f"；结尾：{preview}" if preview else ""
  return f"- 第 {chapter.get('index')} 章《{title}》：约 {chapter.get('character_count', 0)} 字{suffix}"


def _handoff_next_chapter_line(applied_count: int, target_chapters: int, next_chapter_index: int | None = None) -> str:
  if next_chapter_index:
    return f"第 {next_chapter_index} 章"
  if applied_count < target_chapters:
    return f"第 {applied_count + 1} 章"
  return "已达到当前目标章数；继续扩展前需要先增加目标章数"


def _build_core_seed(report: ExistingNovelTakeoverReport) -> str:
  lines = [
    "# 旧稿接管核心",
    "",
    "- 本项目由已有小说旧稿导入创建；已导入章节正文是后续写作的事实基础。",
    "- 后续生成必须沿用已导入章节中的人物姓名、关系、事件结果、地点和物件，不得重写既有剧情。",
    f"- 当前已导入 {report.applied_chapter_count} 章；目标总章数 {report.target_chapters} 章。",
  ]
  if report.next_chapter_index:
    lines.append(f"- 接续位置：第 {report.next_chapter_index} 章。")
  return "\n".join(lines).strip() + "\n"


def _build_blueprint(chapters: list[dict[str, object]], target_chapters: int) -> str:
  written_count = len([item for item in chapters if str(item.get("content") or "").strip()])
  next_chapter_text = _handoff_next_chapter_line(written_count, target_chapters)
  lines = [
    "# 旧稿接续蓝图",
    "",
    "## 接续位置",
    f"- 已导入前 {written_count} 章；接续位置：{next_chapter_text}。",
    "- 已导入章节不可重写、改名或改事件结果；新章节必须承接最近章节结尾。",
    "",
    "## 最近章节",
    *[_chapter_handoff_line(chapter) for chapter in _recent_written_chapters(chapters)],
    "",
    "## 全部旧稿章节清单",
  ]
  for chapter in chapters:
    title = str(chapter.get("title") or f"第 {chapter.get('index')} 章")
    ending = str(chapter.get("ending_preview") or "").strip()
    suffix = f" 结尾：{ending}" if ending else ""
    lines.append(f"- 第 {chapter.get('index')} 章《{title}》：约 {chapter.get('character_count', 0)} 字。{suffix}")
  if len(chapters) < target_chapters:
    lines.append(f"- 第 {len(chapters) + 1} 章：待续写。")
  return "\n".join(lines).strip() + "\n"


def _build_global_summary(report: ExistingNovelTakeoverReport, chapters: list[dict[str, object]]) -> str:
  next_chapter_text = _handoff_next_chapter_line(
    report.applied_chapter_count,
    report.target_chapters,
    report.next_chapter_index,
  )
  lines = [
    "# 旧稿接续简报",
    "",
    f"- 已有正文：前 {report.applied_chapter_count} 章已导入系统章节。",
  ]
  if report.next_chapter_index or report.applied_chapter_count < report.target_chapters:
    lines.append(f"- 接续要求：下一次生成必须从{next_chapter_text}继续，不得推翻旧稿内容。")
  else:
    lines.append("- 接续要求：当前旧稿已达到目标总章数；如需继续扩展，先增加目标章数，再从旧稿末尾继续。")
  if report.next_chapter_index:
    lines.append(f"- 下一章：第 {report.next_chapter_index} 章。")
  if report.last_chapter_title:
    lines.append(f"- 上一章：{report.last_chapter_title}")
  if report.last_chapter_tail:
    lines.append(f"- 上一章结尾：{report.last_chapter_tail}")
  lines.append(f"- 拆章置信度：{int(report.confidence * 100)}%。")
  recent_lines = [_chapter_handoff_line(chapter) for chapter in _recent_written_chapters(chapters)]
  if recent_lines:
    lines.extend(["", "## 最近章节", *recent_lines])
  if report.warnings:
    lines.extend(["", "## 需要确认", *[f"- {item}" for item in report.warnings[:12]]])
  return "\n".join(lines).strip() + "\n"


def _build_character_state(report: ExistingNovelTakeoverReport) -> str:
  next_chapter_text = _handoff_next_chapter_line(
    report.applied_chapter_count,
    report.target_chapters,
    report.next_chapter_index,
  )
  lines = [
    "# 旧稿接管人物状态",
    "",
    "- 人物名单、关系、立场变化和伤病状态以已导入章节正文为准。",
    "- 续写时不得把旧稿中已成立的人物关系改成另一套设定；不确定时优先检索章节正文。",
    f"- 当前接续位置：{next_chapter_text}。",
  ]
  if report.last_chapter_title:
    lines.append(f"- 上一章：{report.last_chapter_title}")
  if report.last_chapter_tail:
    lines.append(f"- 上一章结尾：{report.last_chapter_tail}")
  lines.extend(
    [
      "",
      "## 后续整理建议",
      "- 导入后建议执行人物状态诊断，把核心人物、关系变化和未解决压力整理成正式人物状态。",
    ]
  )
  return "\n".join(lines).strip() + "\n"


def _build_plot_structure(report: ExistingNovelTakeoverReport, chapters: list[dict[str, object]]) -> str:
  lines = [
    "# 旧稿接管情节骨架",
    "",
    f"- 前 {report.applied_chapter_count} 章来自旧稿，作为已经发生的剧情。",
    "- 后续章节需要延续旧稿已经建立的冲突、线索和人物目标。",
  ]
  if report.next_chapter_index:
    lines.append(f"- 接续位置：第 {report.next_chapter_index} 章。")
  recent_lines = [_chapter_handoff_line(chapter) for chapter in _recent_written_chapters(chapters)]
  if recent_lines:
    lines.extend(["", "## 最近推进", *recent_lines])
  return "\n".join(lines).strip() + "\n"


def _render_report_markdown(report: ExistingNovelTakeoverReport) -> str:
  lines = [
    "# 旧稿接管报告",
    "",
    f"- 任务 ID：{report.task_id}",
    f"- 来源文件：{report.source_filename or '粘贴文本'}",
    f"- 原文长度：{report.original_character_count}",
    f"- 已导入章节：{report.applied_chapter_count} / {report.target_chapters}",
    f"- 拆章置信度：{int(report.confidence * 100)}%",
  ]
  if report.next_chapter_index:
    lines.append(f"- 下一章：第 {report.next_chapter_index} 章")
  if report.last_chapter_tail:
    lines.extend(["", "## 最近章节结尾", report.last_chapter_tail])
  if report.warnings:
    lines.extend(["", "## 风险提示", *[f"- {item}" for item in report.warnings]])
  if report.quality_checks:
    lines.extend(["", "## 已完成检查", *[f"- {item}" for item in report.quality_checks]])
  lines.append("")
  lines.append("## 章节")
  for chapter in report.chapters:
    warning_text = f"；提醒：{'；'.join(chapter.warnings)}" if chapter.warnings else ""
    lines.append(
      f"- 第 {chapter.index} 章《{chapter.title}》：{chapter.character_count} 字，"
      f"来源行 {chapter.start_line}-{chapter.end_line}{warning_text}"
    )
  return "\n".join(lines).strip() + "\n"


def _write_text_document(project_dir: Path, filename: str, content: str, *, overwrite: bool) -> None:
  path = project_dir / filename
  if not overwrite and path.exists() and path.read_text(encoding="utf-8").strip():
    return
  atomic_write_text(path, content)


def _write_takeover_documents(
  project_dir: Path,
  report: ExistingNovelTakeoverReport,
  chapters: list[dict[str, object]],
  *,
  overwrite: bool,
) -> None:
  _write_text_document(project_dir, "core_seed.txt", _build_core_seed(report), overwrite=overwrite)
  _write_text_document(project_dir, "plot_structure.txt", _build_plot_structure(report, chapters), overwrite=overwrite)
  _write_text_document(project_dir, "character_state.txt", _build_character_state(report), overwrite=overwrite)
  _write_text_document(project_dir, "blueprint.txt", _build_blueprint(chapters, report.target_chapters), overwrite=overwrite)
  _write_text_document(project_dir, "global_summary.txt", _build_global_summary(report, chapters), overwrite=overwrite)
  checkpoint_path = project_dir / "checkpoint.json"
  checkpoint_payload = {
    "step": "takeover_completed",
    "chapter_index": report.applied_chapter_count,
    "status": "ready",
    "task_id": report.task_id,
    "updated_at": report.updated_at,
  }
  existing_checkpoint = read_json(checkpoint_path, {}) if checkpoint_path.exists() else {}
  if overwrite or not isinstance(existing_checkpoint, dict) or existing_checkpoint.get("step") != "takeover_completed":
    atomic_write_json(checkpoint_path, checkpoint_payload)
  report_path = _takeover_report_path(project_dir)
  if overwrite or not report_path.exists() or not report_path.read_text(encoding="utf-8").strip():
    atomic_write_text(report_path, _render_report_markdown(report))


def _load_chapters(project_dir: Path) -> list[dict[str, object]]:
  data = read_json(_takeover_chapters_path(project_dir), [])
  if isinstance(data, list):
    return [item for item in data if isinstance(item, dict)]
  return []


def _save_chapters(project_dir: Path, chapters: list[dict[str, object]]) -> None:
  stored: list[dict[str, object]] = []
  for chapter in chapters:
    stored.append(
      {
        key: value
        for key, value in chapter.items()
        if key != "content"
      }
    )
  atomic_write_json(_takeover_chapters_path(project_dir), stored)


def _load_chapters_with_source(project_dir: Path) -> list[dict[str, object]]:
  stored = _load_chapters(project_dir)
  source = _takeover_source_path(project_dir).read_text(encoding="utf-8")
  chapters, _warnings, _checks = split_existing_novel_chapters(source)
  content_by_index = {int(item.get("index") or 0): str(item.get("content") or "") for item in chapters}
  for item in stored:
    index = int(item.get("index") or 0)
    item["content"] = content_by_index.get(index, "")
  return stored


def _apply_takeover_to_project(
  settings: Settings,
  summary: ProjectSummary,
  *,
  task_id: str,
  initial_warnings: list[str],
  initial_quality_checks: list[str],
) -> ExistingNovelTakeoverImportResult:
  project_dir = _project_dir(summary)
  state = _load_state(project_dir)
  chapters = _load_chapters_with_source(project_dir)
  if not chapters:
    raise HTTPException(
      status_code=409,
      detail={"code": "takeover_chapters_missing", "message": "旧稿拆章结果缺失，无法继续接管"},
    )

  state["status"] = "running"
  state["stage"] = "writing_chapters"
  _save_state(project_dir, state)

  applied = set()
  raw_applied = state.get("applied_chapter_indexes")
  if isinstance(raw_applied, list):
    applied = {int(item) for item in raw_applied if str(item).isdigit()}

  for chapter in chapters:
    chapter_index = int(chapter.get("index") or 0)
    if chapter_index <= 0 or chapter_index in applied:
      continue
    content = str(chapter.get("content") or "").strip()
    if not content:
      continue
    chapter_path = _chapter_file_path(project_dir, chapter_index)
    if chapter_path.exists():
      existing_content = chapter_path.read_text(encoding="utf-8").strip()
      if existing_content:
        if _content_hash(existing_content) != _content_hash(content):
          warnings = _state_text_list(state, "warnings")
          _append_unique(warnings, f"第 {chapter_index} 章已有正文，恢复时已保留现有章节，未用旧稿覆盖")
          state["warnings"] = warnings
        applied.add(chapter_index)
        state["applied_chapter_indexes"] = sorted(applied)
        state["stage"] = f"chapter_{chapter_index}_preserved"
        _save_state(project_dir, state)
        continue
    atomic_write_text(chapter_path, content + "\n")
    applied.add(chapter_index)
    state["applied_chapter_indexes"] = sorted(applied)
    state["stage"] = f"chapter_{chapter_index}_written"
    _save_state(project_dir, state)

  state["stage"] = "refreshing_knowledge"
  _save_state(project_dir, state)
  knowledge_result = _rebuild_project_knowledge(project_dir, summary.target_chapters, settings)

  state["stage"] = "writing_report"
  state["status"] = "running"
  warnings = _state_text_list(state, "warnings")
  quality_checks = _state_text_list(state, "quality_checks")
  for item in initial_warnings:
    _append_unique(warnings, item)
  for item in initial_quality_checks:
    _append_unique(quality_checks, item)
  _append_unique(quality_checks, "已逐章写入项目章节文件")
  embedding_error = str(knowledge_result.get("embedding_error") or "").strip()
  if embedding_error:
    _append_unique(warnings, f"知识库文本索引已完成，向量索引失败：{embedding_error}")
  else:
    _append_unique(quality_checks, "已刷新本地知识库索引")
  _append_unique(quality_checks, "已写入接管报告和章节清单")
  state["warnings"] = warnings
  state["quality_checks"] = quality_checks
  _save_state(project_dir, state)
  final_summary = _project_summary_or_404(settings, summary.id)
  report_state = dict(state)
  report_state["status"] = "completed"
  report_state["updated_at"] = _now_iso()
  report = _build_report(
    task_id=task_id,
    state=report_state,
    summary=final_summary,
    chapters=chapters,
    warnings=warnings,
    quality_checks=quality_checks,
  )
  _write_takeover_documents(project_dir, report, chapters, overwrite=True)
  state["stage"] = "completed"
  state["status"] = "completed"
  state["completed_at"] = report.updated_at
  state["report"] = report.model_dump(mode="json")
  _save_state(project_dir, state)
  _touch_project_timestamp(settings, summary.id, report.updated_at)
  try:
    _write_snapshot(
      project_dir,
      kind="system",
      message="旧稿接管导入",
      created_at=report.updated_at,
      allow_empty=False,
    )
  except HTTPException as error:
    if getattr(error, "status_code", 0) != 409:
      raise

  final_summary = _project_summary_or_404(settings, summary.id)
  return ExistingNovelTakeoverImportResult(
    project=final_summary,
    report=report,
    path=str(project_dir),
  )


def import_existing_novel(settings: Settings, request: ExistingNovelImportRequest) -> ExistingNovelTakeoverImportResult:
  source_content = _decode_source_text(request)
  if len(source_content.strip()) < 20:
    raise HTTPException(
      status_code=400,
      detail={"code": "existing_novel_too_short", "message": "旧稿正文太短，无法作为已有小说接管"},
    )

  chapters, warnings, quality_checks = split_existing_novel_chapters(source_content)
  if not chapters:
    raise HTTPException(
      status_code=400,
      detail={"code": "existing_novel_split_failed", "message": "旧稿没有可导入章节"},
    )
  if len(chapters) > _MAX_IMPORTED_CHAPTERS:
    raise HTTPException(
      status_code=400,
      detail={
        "code": "existing_novel_too_many_chapters",
        "message": f"旧稿识别到 {len(chapters)} 章，当前项目最多支持 {_MAX_IMPORTED_CHAPTERS} 章，请分卷导入或先整理章节范围",
      },
    )
  target_chapters, target_warnings = _estimate_target_chapters(len(chapters), request.target_chapters)
  target_words = _estimate_target_words(len(source_content), request.target_words)
  warnings.extend(item for item in target_warnings if item not in warnings)

  summary = create_project(
    settings,
    CreateProjectRequest(
      name=request.name.strip(),
      base_path=request.base_path,
      genre=request.genre.strip() or "未定题材",
      target_chapters=target_chapters,
      target_words=target_words,
    ),
  )
  project_dir = _project_dir(summary)
  task_id = uuid4().hex
  source_hash = _content_hash(source_content)
  state = {
    "schema_version": _TAKEOVER_SCHEMA_VERSION,
    "task_id": task_id,
    "project_id": summary.id,
    "status": "running",
    "stage": "source_saved",
    "source_filename": request.source_filename.strip() or "粘贴文本",
    "source_hash": source_hash,
    "original_character_count": len(source_content),
    "detected_chapter_count": len(chapters),
    "target_chapters": target_chapters,
    "warnings": warnings,
    "quality_checks": quality_checks,
    "applied_chapter_indexes": [],
    "created_at": _now_iso(),
  }
  _save_state(project_dir, state)
  atomic_write_text(_takeover_source_path(project_dir), source_content)
  _save_chapters(project_dir, chapters)
  state["stage"] = "chapters_parsed"
  _save_state(project_dir, state)
  return _apply_takeover_to_project(
    settings,
    summary,
    task_id=task_id,
    initial_warnings=warnings,
    initial_quality_checks=quality_checks,
  )


def get_existing_novel_takeover_state(settings: Settings, project_id: str) -> ExistingNovelTakeoverStateResult:
  summary = _project_summary_or_404(settings, project_id)
  state = _load_state(_project_dir(summary))
  return ExistingNovelTakeoverStateResult(project_id=project_id, state=state)


def resume_existing_novel_takeover(settings: Settings, project_id: str) -> ExistingNovelTakeoverImportResult:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  state = _load_state(project_dir)
  if not state:
    raise HTTPException(
      status_code=404,
      detail={"code": "takeover_state_missing", "message": "这个作品没有旧稿接管状态"},
    )
  if not _takeover_source_path(project_dir).exists():
    raise HTTPException(
      status_code=409,
      detail={"code": "takeover_source_missing", "message": "旧稿原文缺失，无法继续接管"},
    )
  if not _takeover_chapters_path(project_dir).exists():
    source_content = _takeover_source_path(project_dir).read_text(encoding="utf-8")
    chapters, warnings, quality_checks = split_existing_novel_chapters(source_content)
    _save_chapters(project_dir, chapters)
    state["warnings"] = warnings
    state["quality_checks"] = quality_checks
    state["detected_chapter_count"] = len(chapters)
    _save_state(project_dir, state)
  else:
    warnings = [
      str(item)
      for item in state.get("warnings", [])
      if str(item).strip()
    ] if isinstance(state.get("warnings"), list) else []
    quality_checks = [
      str(item)
      for item in state.get("quality_checks", [])
      if str(item).strip()
    ] if isinstance(state.get("quality_checks"), list) else []

  task_id = str(state.get("task_id") or uuid4().hex)
  if str(state.get("task_id") or "") != task_id:
    state["task_id"] = task_id
    _save_state(project_dir, state)
  if str(state.get("status") or "") == "completed" and isinstance(state.get("report"), dict):
    report = ExistingNovelTakeoverReport.model_validate(state["report"])
    chapters = _load_chapters_with_source(project_dir)
    _write_takeover_documents(project_dir, report, chapters, overwrite=False)
    return ExistingNovelTakeoverImportResult(project=summary, report=report, path=str(project_dir))
  return _apply_takeover_to_project(
    settings,
    update_project_targets(settings, project_id, target_chapters=summary.target_chapters),
    task_id=task_id,
    initial_warnings=warnings,
    initial_quality_checks=quality_checks,
  )
