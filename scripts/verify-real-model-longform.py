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
  CreateProjectRequest,
  ModelConfigTestRequest,
  ProjectMemoryEntryInput,
  ProjectMemoryUpdateRequest,
  StoryDocumentBatchUpdateRequest,
  StoryDocumentPatch,
)
from novel_backend.services.chapter_auto_repair_service import auto_repair_chapter_after_review
from novel_backend.services.config_service import (
  app_config_path,
  initialize_app_storage,
  license_path,
  load_config,
  run_model_config_test,
)
from novel_backend.services.generation_service import _generate_chapter_workflow
from novel_backend.services.license_service import validate_license
from novel_backend.services.project_service import (
  create_project,
  refresh_project_knowledge_index,
  search_project_knowledge,
  summarize_chapter_review_status,
  update_chapter_content_with_review_status,
  update_project_memory,
  update_story_documents,
)


def now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def log(message: str) -> None:
  print(f"[real-model-longform] {message}", flush=True)


def timed_stage(label: str, started: float) -> str:
  return f"{label} in {round(time.perf_counter() - started, 3)}s"


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
  failed = [item for item in result.items if item.status == "failed"]
  for item in result.items:
    log(f"{item.target}: {item.status} - {item.message} ({item.elapsed}s)")
  if failed:
    raise RuntimeError("模型配置测试失败：" + "；".join(item.message for item in failed))
  if not any(item.target == "model" and item.status == "passed" for item in result.items):
    raise RuntimeError("写作模型没有通过测试。")
  if not any(item.target == "embedding" and item.status == "passed" for item in result.items):
    raise RuntimeError("知识检索模型没有通过测试。")
  return result.model_dump(mode="json")


def chapter_id(index: int) -> str:
  return f"chapter-{index:03d}"


def seed_project(settings: Settings, target_words: int) -> str:
  summary = create_project(
    settings,
    CreateProjectRequest(
      name=f"真实模型长篇链路验证-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
      genre="悬疑长篇验证",
      target_chapters=6,
      target_words=6000,
    ),
  )
  project_id = summary.id
  log(f"created project {project_id}")

  update_story_documents(
    settings,
    project_id,
    StoryDocumentBatchUpdateRequest(
      documents=[
        StoryDocumentPatch(
          key="core_seed",
          content=(
            "林追在雨夜靠港时得到铜钥匙，铜钥匙能开启旧船队账册。"
            "白石商会追索铜钥匙，沈砚的真实立场要留到后段。"
          ),
        ),
        StoryDocumentPatch(
          key="character_design",
          content=(
            "林追：主角，港口账房出身，守着铜钥匙追查旧船队。不能改名为林逐。"
            "\n顾临：港务巡检，是林追在制度内的证人，不能死亡、叛变或离队。"
            "\n沈砚：表面是账册修复师，真实身份要留到第 5 章以后，前两章不能揭示为主谋。"
            "\n苏青：码头医师，知道潮位旧规但不会直接说破沈砚身份。"
          ),
        ),
        StoryDocumentPatch(
          key="world_building",
          content=(
            "灰港由港务会和白石商会共同控制。旧船队账册记录一条只在特定潮位开放的暗线。"
            "铜钥匙必须留在林追手中，白石商会只能追索，不能得到。"
          ),
        ),
        StoryDocumentPatch(
          key="plot_structure",
          content=(
            "第 1 章：林追拿到铜钥匙，发现旧船队账册线索，顾临出面掩护。"
            "\n第 2 章：白石商会加压，林追和顾临确认账册藏在灯塔旧库。"
            "\n第 3-4 章：苏青提供潮位线索，白石商会制造误导。"
            "\n第 5-6 章：沈砚真实立场逐步揭开，林追用铜钥匙改写港口秩序。"
          ),
        ),
        StoryDocumentPatch(
          key="blueprint",
          content=(
            f"## 第 1 章《雨夜靠港》\n目标约 {target_words} 字。林追得到铜钥匙，顾临掩护，结尾留下白石商会追兵。"
            f"\n\n## 第 2 章《灯塔旧库》\n目标约 {target_words} 字。白石商会逼近，林追和顾临确认账册线索，不能交出铜钥匙。"
            "\n\n## 第 3 章《潮位医案》\n苏青提供潮位旧规。"
            "\n\n## 第 4 章《假账回声》\n白石商会制造假账误导。"
            "\n\n## 第 5 章《沈砚旧名》\n开始揭示沈砚立场。"
            "\n\n## 第 6 章《灰港新规》\n收束铜钥匙和旧船队账册。"
          ),
        ),
        StoryDocumentPatch(
          key="global_summary",
          content="尚未生成正文。当前阶段必须保护铜钥匙归属、顾临存活和沈砚身份悬念。",
        ),
      ],
    ),
  )

  update_project_memory(
    settings,
    project_id,
    ProjectMemoryUpdateRequest(
      entries=[
        ProjectMemoryEntryInput(
          id="keep-linzhui-name",
          title="林追不能改名",
          category="硬规则",
          content="不要把林追改名为林逐，也不要写成林逐。",
        ),
        ProjectMemoryEntryInput(
          id="key-owner",
          title="铜钥匙归属",
          category="硬规则",
          content="铜钥匙不能被交给白石商会，白石商会只能追索，不能得到。",
        ),
        ProjectMemoryEntryInput(
          id="shenyan-hidden",
          title="沈砚身份延后",
          category="硬规则",
          content="沈砚不能在前两章被提前揭示为主谋、真凶或幕后操盘者。",
        ),
        ProjectMemoryEntryInput(
          id="gulin-alive",
          title="顾临状态",
          category="硬规则",
          content="顾临不能死亡、叛变或离队，至少前两章必须仍在局内。",
        ),
      ],
    ),
  )

  index_result = refresh_project_knowledge_index(settings, project_id)
  embedding_error = str(index_result.get("embedding_error") or "").strip()
  if embedding_error:
    raise RuntimeError(f"知识库刷新失败：{embedding_error}")
  log(f"knowledge chunks: {index_result.get('chunk_count', 'unknown')}")
  return project_id


def contains_forbidden_transfer(text: str) -> bool:
  safe_pattern = r"(?:拒绝|没有|未|不曾|不肯|不愿|不能).{0,8}铜钥匙.{0,8}(?:交给|交出|转交|交付).{0,4}白石商会"
  if re.search(safe_pattern, text):
    text = re.sub(safe_pattern, "", text)
  patterns = [
    r"把?铜钥匙交给白石商会",
    r"铜钥匙被交给白石商会",
    r"白石商会(?:得到|拿到|夺得|取得)了?铜钥匙",
  ]
  return any(re.search(pattern, text) for pattern in patterns)


def contains_early_identity_reveal(text: str) -> bool:
  patterns = [
    r"沈砚.{0,8}(?:主谋|真凶|幕后操盘者)",
    r"(?:主谋|真凶|幕后操盘者).{0,8}沈砚",
  ]
  for pattern in patterns:
    for match in re.finditer(pattern, text):
      context_start = max(0, match.start() - 8)
      context_end = min(len(text), match.end() + 8)
      context = text[context_start:context_end]
      if re.search(r"不是|并非|没有|未|尚未|不曾|不能|不要|不可", context):
        continue
      return True
  return False


def hard_rule_violations(content: str) -> list[str]:
  violations: list[str] = []
  if "林逐" in content:
    violations.append("林追被写成林逐")
  if contains_forbidden_transfer(content):
    violations.append("铜钥匙被写成交给或落入白石商会")
  if contains_early_identity_reveal(content):
    violations.append("沈砚身份在前两章提前揭示")
  if re.search(r"顾临.{0,8}(?:死亡|死了|叛变|离队)", content):
    violations.append("顾临状态违反前两章约束")
  return violations


def project_memory_issue_count(detail, chapter_id_value: str) -> int:
  review = next(
    (item for item in detail.story_overview.chapter_reviews if item.chapter_id == chapter_id_value),
    None,
  )
  if review is None:
    return 0
  for dimension in review.dimensions:
    if dimension.id == "project_memory":
      return len(dimension.issues)
  return 0


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
      lines.append(
        f"{dimension.label}/{issue.level}/{issue.title}: {issue.detail}"
      )
  return lines


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


def generate_save_review_chapter(
  settings: Settings,
  project_id: str,
  index: int,
  target_words: int,
  *,
  skip_auto_repair: bool,
) -> dict[str, object]:
  cid = chapter_id(index)
  started = time.perf_counter()
  instruction = (
    f"生成第 {index} 章完整正文，目标约 {target_words} 字。"
    "严格遵守项目记忆和章节蓝图；不要提前揭示沈砚身份；铜钥匙必须仍在林追手中。"
  )
  log(f"chapter {index}: generating draft")
  result = _generate_chapter_workflow(
    settings,
    ChapterWorkflowRequest(
      project_id=project_id,
      chapter_id=cid,
      mode="draft",
      instruction=instruction,
      target_words=target_words,
    ),
    task_id=f"real-model-longform-{uuid4().hex[:10]}",
  )
  draft = result.draft.strip()
  elapsed_generate = round(time.perf_counter() - started, 3)
  log(f"chapter {index}: draft returned {len(draft)} chars, {timed_stage('generated', started)}")
  if len(draft) < 500:
    raise RuntimeError(f"第 {index} 章生成正文过短：{len(draft)} 字符")

  violations = hard_rule_violations(draft)
  if violations:
    raise RuntimeError(f"第 {index} 章初稿触犯硬规则：" + "；".join(violations))

  save_started = time.perf_counter()
  log(f"chapter {index}: saving draft and running chapter review")
  detail, review_error = update_chapter_content_with_review_status(
    settings,
    project_id,
    cid,
    ChapterUpdateRequest(content=draft),
  )
  repair_result = None
  log(f"chapter {index}: save/review finished, {timed_stage('reviewed', save_started)}")
  if skip_auto_repair:
    log(f"chapter {index}: auto repair skipped by script option")
  else:
    repair_started = time.perf_counter()
    log(f"chapter {index}: checking auto repair")
    detail, review_error, repair_result = auto_repair_chapter_after_review(
      settings,
      project_id,
      cid,
      detail,
      review_error=review_error,
      instruction=instruction,
    )
    log(f"chapter {index}: auto repair check finished, {timed_stage('checked', repair_started)}")
  review_status = summarize_chapter_review_status(detail, cid, review_error)
  chapter = next(item for item in detail.chapters if item.id == cid)
  final_content = chapter.content.strip()
  final_violations = hard_rule_violations(final_content)
  memory_issues = project_memory_issue_count(detail, cid)

  if final_violations:
    raise RuntimeError(f"第 {index} 章保存后触犯硬规则：" + "；".join(final_violations))
  if review_error:
    raise RuntimeError(f"第 {index} 章核验失败：{review_error}")
  if not review_status.get("ok"):
    raise RuntimeError(f"第 {index} 章没有核验报告：{review_status.get('message')}")
  if memory_issues > 0:
    raise RuntimeError(f"第 {index} 章项目记忆规则仍有 {memory_issues} 个问题")
  gate_failures = strict_review_gate_failures(review_status)
  if gate_failures and not skip_auto_repair:
    issue_summary = "；".join(chapter_review_issue_summary(detail, cid)[:8])
    suffix = f"。问题明细：{issue_summary}" if issue_summary else ""
    raise RuntimeError(f"第 {index} 章自动修订后仍未通过质量门：" + "；".join(gate_failures) + suffix)
  if gate_failures and skip_auto_repair:
    log(f"chapter {index}: review gate warnings with auto repair skipped: {'; '.join(gate_failures)}")

  log(
    f"chapter {index}: generated {len(draft)} chars in {elapsed_generate}s, "
    f"saved {len(final_content)} chars, review {review_status.get('score')}/100 {review_status.get('status_label')}"
  )
  if repair_result and repair_result.attempted:
    log(
      f"chapter {index}: auto repair attempted={repair_result.rounds_attempted}, "
      f"applied={repair_result.rounds_applied}, reason={repair_result.reason}"
    )

  return {
    "chapter_id": cid,
    "generated_chars": len(draft),
    "saved_chars": len(final_content),
    "generate_elapsed": elapsed_generate,
    "review": review_status,
    "auto_repair": asdict(repair_result) if repair_result else None,
    "skip_auto_repair": skip_auto_repair,
  }


def verify_knowledge_search(settings: Settings, project_id: str) -> list[dict[str, object]]:
  log("knowledge search: querying saved project content")
  hits = search_project_knowledge(
    settings,
    project_id,
    "铜钥匙 林追 白石商会 顾临",
    limit=6,
    include_semantic=True,
    chapter_index=2,
  )
  if len(hits) < 3:
    raise RuntimeError(f"知识检索命中过少：{len(hits)}")
  if not any("铜钥匙" in item.preview for item in hits):
    raise RuntimeError("知识检索没有命中铜钥匙相关内容")
  log(f"knowledge search hits: {len(hits)}")
  return [item.model_dump(mode="json") for item in hits]


def main() -> int:
  parser = argparse.ArgumentParser(description="Run real model longform verification in a temporary project.")
  parser.add_argument("--allow-real-model-calls", action="store_true", help="Required because this script calls paid model APIs.")
  parser.add_argument("--source-data-dir", default=str(default_data_dir()), help="Existing app data dir containing app_config.json.")
  parser.add_argument("--target-words", type=int, default=900, help="Target characters/words hint per generated chapter.")
  parser.add_argument("--chapters", type=int, default=1, choices=[1, 2, 3], help="Number of chapters to generate.")
  parser.add_argument(
    "--skip-auto-repair",
    action="store_true",
    help="Skip post-review auto repair; useful when validating generation, save, review, and retrieval latency.",
  )
  parser.add_argument("--keep-temp-dir", action="store_true", help="Keep temporary data dir after the run.")
  args = parser.parse_args()

  if not args.allow_real_model_calls:
    print("Refusing to call real models. Re-run with --allow-real-model-calls.", file=sys.stderr)
    return 2

  source_data_dir = Path(args.source_data_dir).expanduser().resolve()
  if not (source_data_dir / "app_config.json").exists():
    print(f"Missing app_config.json in {source_data_dir}", file=sys.stderr)
    return 2

  temp_root = Path(tempfile.mkdtemp(prefix="novel-real-model-longform-")).resolve()
  settings = Settings(
    data_dir=temp_root,
    self_evolution_worker_enabled=False,
    auxiliary_worker_enabled=False,
  )
  summary: dict[str, object] = {
    "started_at": now_iso(),
    "source_data_dir": str(source_data_dir),
    "temp_data_dir": str(temp_root),
    "chapters": [],
  }
  try:
    copied = copy_runtime_files(source_data_dir, settings)
    log("copied runtime files: " + ", ".join(copied))
    initialize_app_storage(settings)

    license_status = validate_license(settings)
    summary["license"] = license_status.model_dump(mode="json")
    if not license_status.valid:
      raise RuntimeError(f"许可证不可用：{license_status.reason}")
    expires_at = license_status.expires_at or "permanent"
    log(f"license: valid, expires_at={expires_at}")

    summary["model_config_test"] = ensure_model_config_passed(settings)
    project_id = seed_project(settings, args.target_words)
    summary["project_id"] = project_id

    chapters = []
    for index in range(1, args.chapters + 1):
      chapters.append(
        generate_save_review_chapter(
          settings,
          project_id,
          index,
          args.target_words,
          skip_auto_repair=args.skip_auto_repair,
        )
      )
    summary["chapters"] = chapters
    summary["knowledge_hits"] = verify_knowledge_search(settings, project_id)
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
