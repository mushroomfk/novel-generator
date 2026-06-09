#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
  sys.path.insert(0, str(BACKEND_DIR))

from novel_backend.config import Settings, default_data_dir
from novel_backend.models import (
  ChapterUpdateRequest,
  ChapterWorkflowRequest,
  ExistingNovelImportRequest,
  ModelConfigTestRequest,
  ProjectMemoryEntryInput,
  ProjectMemoryUpdateRequest,
)
from novel_backend.services.chapter_auto_repair_service import auto_repair_chapter_after_review
from novel_backend.services.config_service import (
  app_config_path,
  initialize_app_storage,
  license_path,
  load_config,
  run_model_config_test,
)
from novel_backend.services.context_builder import build_project_context_bundle
from novel_backend.services.generation_service import _generate_chapter_workflow
from novel_backend.services.license_service import validate_license
from novel_backend.services.project_service import (
  get_project_detail,
  search_project_knowledge,
  summarize_chapter_review_status,
  update_chapter_content_with_review_status,
  update_project_memory,
)
from novel_backend.services.project_takeover_service import (
  import_existing_novel,
  split_existing_novel_chapters,
)

DEFAULT_SOURCE_FILE = (
  "/Users/liuqingxing/Desktop/围城续写/.claude/skills/weicheng/resources/original-text.md"
)


def now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def log(message: str) -> None:
  print(f"[weicheng-original-continuation] {message}", flush=True)


def timed(started: float) -> str:
  return f"{round(time.perf_counter() - started, 3)}s"


def chapter_id(index: int) -> str:
  return f"chapter-{index:03d}"


def copy_runtime_files(source_data_dir: Path, target_settings: Settings) -> list[str]:
  copied: list[str] = []
  source_settings = Settings(data_dir=source_data_dir)
  for source_path, target_path in (
    (app_config_path(source_settings), app_config_path(target_settings)),
    (license_path(source_settings), license_path(target_settings)),
  ):
    if source_path.exists():
      target_path.parent.mkdir(parents=True, exist_ok=True)
      shutil.copy2(source_path, target_path)
      copied.append(source_path.name)
  return copied


def ensure_model_config_passed(settings: Settings) -> dict[str, object]:
  config = load_config(settings)
  result = run_model_config_test(
    settings,
    ModelConfigTestRequest(
      target="all",
      model=config.model,
      embedding=config.embedding,
      review_model=config.review_model,
    ),
  )
  for item in result.items:
    log(f"{item.target}: {item.status} - {item.message} ({item.elapsed}s)")
  failed = [item for item in result.items if item.status == "failed"]
  if failed:
    raise RuntimeError("模型配置测试失败：" + "；".join(item.message for item in failed))
  if not any(item.target == "model" and item.status == "passed" for item in result.items):
    raise RuntimeError("写作模型没有通过测试")
  if not any(item.target == "embedding" and item.status == "passed" for item in result.items):
    raise RuntimeError("知识检索模型没有通过测试")
  return result.model_dump(mode="json")


def assert_original_split(source_text: str) -> dict[str, object]:
  chapters, warnings, checks = split_existing_novel_chapters(source_text)
  if len(chapters) != 9:
    raise RuntimeError(f"原文拆章数量不对：期望 9，实际 {len(chapters)}")
  titles = [str(item.get("title") or "") for item in chapters]
  expected = ["第一章", "第二章", "第三章", "第四章", "第五章", "第六章", "第七章", "第八章", "第九章"]
  missing = [title for title in expected if title not in titles]
  if missing:
    raise RuntimeError("原文拆章标题缺失：" + "、".join(missing))
  if not all(int(item.get("character_count") or 0) > 500 for item in chapters):
    raise RuntimeError("原文拆章存在异常短章节")
  return {
    "chapter_count": len(chapters),
    "titles": titles,
    "warnings": warnings,
    "quality_checks": checks,
    "character_counts": [int(item.get("character_count") or 0) for item in chapters],
  }


def seed_memory(settings: Settings, project_id: str) -> None:
  update_project_memory(
    settings,
    project_id,
    ProjectMemoryUpdateRequest(
      entries=[
        ProjectMemoryEntryInput(
          id="weicheng-protagonist",
          title="续写主线人物",
          category="硬规则",
          content="第十章续写必须延续方鸿渐的主视角，不能把主角换成赵辛楣、唐晓芙、苏文纨或新人物。",
        ),
        ProjectMemoryEntryInput(
          id="weicheng-marriage",
          title="婚姻关系",
          category="硬规则",
          content="原文结尾时方鸿渐与孙柔嘉已经成婚且刚发生争执，不能写成方鸿渐与唐晓芙、苏文纨或其他人已婚。",
        ),
        ProjectMemoryEntryInput(
          id="weicheng-tail",
          title="接续位置",
          category="连续性",
          content="续写应接在第九章末尾之后，承认孙柔嘉离开住处去陆家、方鸿渐独自回到空房间的状态。",
        ),
        ProjectMemoryEntryInput(
          id="weicheng-no-cross-project",
          title="禁止测试项目污染",
          category="硬规则",
          content="正文不能出现林追、顾临、沈砚、铜钥匙、白石商会、灰港、旧船队账册、灯塔旧库等其他验证项目元素。",
        ),
        ProjectMemoryEntryInput(
          id="weicheng-tone",
          title="续写风格",
          category="偏好",
          content="续写应保持讽刺、克制、日常细节推进，不使用现代网络语言，不直接引用大段原文。",
        ),
      ],
    ),
  )


def import_original(settings: Settings, source_path: Path, source_text: str) -> dict[str, object]:
  started = time.perf_counter()
  result = import_existing_novel(
    settings,
    ExistingNovelImportRequest(
      name=f"围城原文导入续写验证-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
      genre="现代讽刺长篇",
      target_chapters=12,
      target_words=700000,
      source_filename=source_path.name,
      content=source_text,
    ),
  )
  report = result.report
  if report.detected_chapter_count != 9 or report.applied_chapter_count != 9:
    raise RuntimeError(
      f"旧稿接管章节数异常：detected={report.detected_chapter_count}, applied={report.applied_chapter_count}"
    )
  if report.next_chapter_index != 10:
    raise RuntimeError(f"接续章号异常：期望第 10 章，实际第 {report.next_chapter_index} 章")
  log(f"imported project {result.project.id}, {timed(started)}")
  return {
    "project_id": result.project.id,
    "project_path": result.path,
    "report": compact_takeover_report(report.model_dump(mode="json")),
  }


def compact_takeover_report(report: dict[str, object]) -> dict[str, object]:
  compact = dict(report)
  compact.pop("source_hash", None)
  compact.pop("last_chapter_tail", None)
  return compact


def contains_fang(text: str) -> bool:
  return "方鸿渐" in text or "鸿渐" in text


def contains_sun(text: str) -> bool:
  return "孙柔嘉" in text or "柔嘉" in text


def verify_imported_project(settings: Settings, project_id: str) -> dict[str, object]:
  detail = get_project_detail(settings, project_id)
  non_empty = [item for item in detail.chapters if item.exists and item.content.strip()]
  if len(non_empty) != 9:
    raise RuntimeError(f"导入后非空章节数异常：{len(non_empty)}")
  ninth = next(item for item in detail.chapters if item.id == "chapter-009")
  if not contains_fang(ninth.content):
    raise RuntimeError("第九章缺少方鸿渐或鸿渐")
  if not contains_sun(ninth.content):
    raise RuntimeError("第九章缺少孙柔嘉或柔嘉")

  query = "方鸿渐 孙柔嘉 赵辛楣 唐晓芙 苏文纨"
  hits = search_project_knowledge(
    settings,
    project_id,
    query,
    limit=8,
    include_semantic=True,
    chapter_index=10,
  )
  if len(hits) < 4:
    raise RuntimeError(f"原文知识检索命中过少：{len(hits)}")
  fang_hits = search_project_knowledge(
    settings,
    project_id,
    "方鸿渐",
    limit=4,
    include_semantic=True,
    chapter_index=10,
  )
  sun_hits = search_project_knowledge(
    settings,
    project_id,
    "孙柔嘉",
    limit=4,
    include_semantic=True,
    chapter_index=10,
  )
  if not any(contains_fang(item.preview) for item in fang_hits):
    raise RuntimeError("知识检索没有覆盖方鸿渐或鸿渐")
  if not any(contains_sun(item.preview) for item in sun_hits):
    raise RuntimeError("知识检索没有覆盖孙柔嘉或柔嘉")

  bundle = build_project_context_bundle(
    settings,
    project_id,
    chapter_id="chapter-010",
    knowledge_query=query,
    knowledge_limit=8,
    task_instruction="续写第 10 章，接在原文第九章之后",
  )
  context = bundle.context_text
  for marker in ("旧稿接续简报", "第 10 章"):
    if marker not in context:
      raise RuntimeError(f"第 10 章上下文缺少：{marker}")
  if not contains_fang(context):
    raise RuntimeError("第 10 章上下文缺少方鸿渐或鸿渐")
  if not contains_sun(context):
    raise RuntimeError("第 10 章上下文缺少孙柔嘉或柔嘉")

  return {
    "non_empty_chapters": len(non_empty),
    "knowledge_hit_count": len(hits),
    "fang_hit_count": len(fang_hits),
    "sun_hit_count": len(sun_hits),
    "knowledge_sources": [
      {"source": item.source, "section": item.section, "match_type": item.match_type}
      for item in hits
    ],
    "context_length": len(context),
  }


def strip_negated_safe_phrases(text: str) -> str:
  safe_patterns = [
    r"(?:没有|并未|未曾|不是|不能|不该|不应|不会).{0,12}(?:林追|顾临|沈砚|铜钥匙|白石商会|灰港|旧船队账册|灯塔旧库)",
    r"(?:林追|顾临|沈砚|铜钥匙|白石商会|灰港|旧船队账册|灯塔旧库).{0,12}(?:没有|并未|未曾|不是|不能|不该|不应|不会)",
  ]
  cleaned = text
  for pattern in safe_patterns:
    cleaned = re.sub(pattern, "", cleaned)
  return cleaned


def contains_wrong_spouse(text: str) -> bool:
  spouse_words = r"(?:妻子|太太|夫人|爱人|老婆|结婚|成婚|婚后|婚姻)"
  wrong_names = r"(?:唐晓芙|苏文纨|鲍小姐)"
  patterns = [
    rf"方鸿渐.{{0,18}}{wrong_names}.{{0,18}}{spouse_words}",
    rf"{wrong_names}.{{0,18}}方鸿渐.{{0,18}}{spouse_words}",
    rf"方鸿渐.{{0,18}}(?:娶了|嫁给|迎娶).{{0,8}}{wrong_names}",
    rf"{wrong_names}.{{0,18}}(?:嫁给|嫁了).{{0,8}}方鸿渐",
  ]
  for pattern in patterns:
    for match in re.finditer(pattern, text):
      context = text[max(0, match.start() - 12):match.end() + 12]
      if re.search(r"没有|并未|未曾|不是|不能|不该|不应|不会|假如|如果|仿佛|好像", context):
        continue
      return True
  return False


def confusion_violations(text: str) -> list[str]:
  violations: list[str] = []
  if not re.search(r"方鸿渐|鸿渐", text):
    violations.append("续写没有出现方鸿渐或鸿渐")
  if not re.search(r"孙柔嘉|柔嘉", text):
    violations.append("续写没有出现孙柔嘉或柔嘉")
  if contains_wrong_spouse(text):
    violations.append("续写把方鸿渐和其他女性写成婚姻关系")

  cleaned = strip_negated_safe_phrases(text)
  pollution_markers = ["林追", "顾临", "沈砚", "铜钥匙", "白石商会", "灰港", "旧船队账册", "灯塔旧库"]
  polluted = [marker for marker in pollution_markers if marker in cleaned]
  if polluted:
    violations.append("续写混入其他验证项目元素：" + "、".join(polluted))

  continuity_markers = ["陆家", "李妈", "周太太", "争吵", "空房", "钟", "报馆", "赵辛楣", "慎余里", "孙家"]
  matched = [marker for marker in continuity_markers if marker in text]
  if len(matched) < 2:
    violations.append("续写缺少第九章结尾后的接续标记")
  return violations


def review_status_count(review_status: dict[str, object], key: str) -> int:
  value = review_status.get(key)
  if isinstance(value, bool):
    return int(value)
  if isinstance(value, (int, float)):
    return int(value)
  try:
    return int(str(value or "").strip() or "0")
  except ValueError:
    return 0


def strict_review_gate_failures(review_status: dict[str, object]) -> list[str]:
  failures: list[str] = []
  if review_status.get("status") == "risk":
    failures.append(f"核验状态为有风险：{review_status.get('message')}")
  for key, label in (
    ("critical_issue_count", "critical 问题"),
    ("obsidian_required_issue_count", "Obsidian 必写问题"),
    ("obsidian_forbidden_issue_count", "Obsidian 禁写问题"),
    ("continuity_contract_issue_count", "连续性合同问题"),
    ("must_repair_issue_count", "必须修订问题"),
  ):
    count = review_status_count(review_status, key)
    if count > 0:
      failures.append(f"{label} {count} 个")
  return failures


def is_chapter_10_hit(item) -> bool:
  return (
    item.source_key in {"chapter-010", "chapter:chapter-010"}
    or "第 10 章" in item.section
    or "第十章" in item.section
  )


def post_save_index_query(content: str) -> str:
  for sentence in re.split(r"[。！？；;!\?\n]+", content):
    compact = re.sub(r"[^\w\u4e00-\u9fff]+", "", sentence)
    if len(compact) >= 24:
      return compact[:36]
  compact_content = re.sub(r"[^\w\u4e00-\u9fff]+", "", content)
  if len(compact_content) >= 12:
    return compact_content[:36]
  raise RuntimeError("第 10 章正文过短，无法构造索引验证查询")


def chapter_review_issue_summary(detail, chapter_id_value: str) -> list[str]:
  review = next(
    (item for item in detail.story_overview.chapter_reviews if item.chapter_id == chapter_id_value),
    None,
  )
  if review is None:
    return []
  lines: list[str] = []
  for dimension in review.dimensions:
    for issue in dimension.issues:
      lines.append(f"{dimension.label}/{issue.level}/{issue.title}: {issue.detail}")
  return lines


def generate_and_verify_continuation(
  settings: Settings,
  project_id: str,
  target_words: int,
  *,
  skip_auto_repair: bool,
) -> dict[str, object]:
  cid = "chapter-010"
  instruction = (
    "续写第 10 章，直接接在原文第九章末尾之后。"
    "必须延续方鸿渐与孙柔嘉婚后争执后的状态，承认柔嘉已去陆家，方鸿渐独自面对空房和旧钟。"
    "可以让赵辛楣作为旧关系被想起或联系，但不能把主角换成赵辛楣。"
    "不要把唐晓芙、苏文纨或鲍小姐写成方鸿渐现任妻子。"
    "不要引用大段原文，不要出现林追、铜钥匙、白石商会、灰港等其他项目元素。"
  )

  started = time.perf_counter()
  log("chapter 10: generating real-model draft")
  result = _generate_chapter_workflow(
    settings,
    ChapterWorkflowRequest(
      project_id=project_id,
      chapter_id=cid,
      mode="draft",
      instruction=instruction,
      target_words=target_words,
    ),
    task_id=f"weicheng-continuation-{uuid4().hex[:10]}",
  )
  draft = result.draft.strip()
  if len(draft) < 500:
    raise RuntimeError(f"第 10 章续写正文过短：{len(draft)} 字符")
  draft_violations = confusion_violations(draft)
  if draft_violations:
    raise RuntimeError("第 10 章初稿混淆检查失败：" + "；".join(draft_violations))
  log(f"chapter 10: draft returned {len(draft)} chars, {timed(started)}")

  review_started = time.perf_counter()
  log("chapter 10: saving draft and running review")
  detail, review_error = update_chapter_content_with_review_status(
    settings,
    project_id,
    cid,
    ChapterUpdateRequest(content=draft),
  )
  repair_result = None
  if not skip_auto_repair:
    log("chapter 10: checking auto repair")
    detail, review_error, repair_result = auto_repair_chapter_after_review(
      settings,
      project_id,
      cid,
      detail,
      review_error=review_error,
      instruction=instruction,
    )
  log(f"chapter 10: review finished, {timed(review_started)}")

  review_status = summarize_chapter_review_status(detail, cid, review_error)
  chapter = next(item for item in detail.chapters if item.id == cid)
  final_content = chapter.content.strip()
  final_violations = confusion_violations(final_content)
  if final_violations:
    raise RuntimeError("第 10 章保存后混淆检查失败：" + "；".join(final_violations))
  if review_error:
    raise RuntimeError(f"第 10 章核验失败：{review_error}")
  if not review_status.get("ok"):
    raise RuntimeError(f"第 10 章没有核验报告：{review_status.get('message')}")
  gate_failures = strict_review_gate_failures(review_status)
  if gate_failures and not skip_auto_repair:
    issue_summary = "；".join(chapter_review_issue_summary(detail, cid)[:8])
    suffix = f"。问题明细：{issue_summary}" if issue_summary else ""
    raise RuntimeError("第 10 章自动修订后仍未通过质量门：" + "；".join(gate_failures) + suffix)
  if gate_failures and skip_auto_repair:
    log("chapter 10: review gate warnings with auto repair skipped: " + "；".join(gate_failures))

  post_hits = search_project_knowledge(
    settings,
    project_id,
    post_save_index_query(final_content),
    limit=20,
    include_semantic=False,
    chapter_index=10,
  )
  if not any(is_chapter_10_hit(item) for item in post_hits):
    raise RuntimeError("保存续写后知识检索没有命中新章节")

  return {
    "chapter_id": cid,
    "draft_chars": len(draft),
    "final_chars": len(final_content),
    "matched_continuity_markers": [
      marker
      for marker in ["陆家", "李妈", "周太太", "争吵", "空房", "钟", "报馆", "赵辛楣", "慎余里", "孙家"]
      if marker in final_content
    ],
    "review": review_status,
    "auto_repair": asdict(repair_result) if repair_result else None,
    "post_save_knowledge_hit_count": len(post_hits),
    "generated_elapsed": round(time.perf_counter() - started, 3),
  }


def main() -> int:
  parser = argparse.ArgumentParser(
    description="Import the Weicheng original text, continue chapter 10 with real models, and check continuity confusion."
  )
  parser.add_argument("--allow-real-model-calls", action="store_true", help="Required because this script calls paid model APIs.")
  parser.add_argument("--source-file", default=DEFAULT_SOURCE_FILE, help="Path to original-text.md.")
  parser.add_argument("--source-data-dir", default=str(default_data_dir()), help="Existing app data dir containing app_config.json.")
  parser.add_argument("--target-words", type=int, default=900, help="Target length hint for generated continuation.")
  parser.add_argument("--skip-auto-repair", action="store_true", help="Skip post-review auto repair.")
  parser.add_argument("--keep-temp-dir", action="store_true", help="Keep temporary data dir after the run.")
  args = parser.parse_args()

  if not args.allow_real_model_calls:
    print("Refusing to call real models. Re-run with --allow-real-model-calls.", file=sys.stderr)
    return 2

  source_file = Path(args.source_file).expanduser().resolve()
  if not source_file.exists():
    print(f"Missing source file: {source_file}", file=sys.stderr)
    return 2
  source_data_dir = Path(args.source_data_dir).expanduser().resolve()
  if not (source_data_dir / "app_config.json").exists():
    print(f"Missing app_config.json in {source_data_dir}", file=sys.stderr)
    return 2

  temp_root = Path(tempfile.mkdtemp(prefix="novel-weicheng-continuation-")).resolve()
  settings = Settings(
    data_dir=temp_root,
    self_evolution_worker_enabled=False,
    auxiliary_worker_enabled=False,
  )
  summary: dict[str, object] = {
    "started_at": now_iso(),
    "source_file": str(source_file),
    "source_data_dir": str(source_data_dir),
    "temp_data_dir": str(temp_root),
  }
  try:
    copied = copy_runtime_files(source_data_dir, settings)
    log("copied runtime files: " + ", ".join(copied))
    initialize_app_storage(settings)

    license_status = validate_license(settings)
    summary["license"] = license_status.model_dump(mode="json")
    if not license_status.valid:
      raise RuntimeError(f"许可证不可用：{license_status.reason}")
    log(f"license: valid, expires_at={license_status.expires_at or 'permanent'}")

    summary["model_config_test"] = ensure_model_config_passed(settings)

    source_text = source_file.read_text(encoding="utf-8")
    summary["split"] = assert_original_split(source_text)
    import_summary = import_original(settings, source_file, source_text)
    summary.update(import_summary)
    project_id = str(import_summary["project_id"])
    seed_memory(settings, project_id)
    summary["import_verification"] = verify_imported_project(settings, project_id)
    summary["continuation"] = generate_and_verify_continuation(
      settings,
      project_id,
      args.target_words,
      skip_auto_repair=args.skip_auto_repair,
    )
    summary["finished_at"] = now_iso()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0
  except Exception as error:
    summary["failed_at"] = now_iso()
    summary["error"] = str(error)
    print(json.dumps(summary, ensure_ascii=False, indent=2), file=sys.stderr)
    return 1
  finally:
    if args.keep_temp_dir:
      log(f"kept temp dir: {temp_root}")
    else:
      shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
  raise SystemExit(main())
