from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from novel_backend.config import Settings
from novel_backend.models import AgentPlan, AgentPlanAction
from novel_backend.services.config_service import load_config
from novel_backend.services.obsidian_service import obsidian_note_available_for_chapter

_MODEL_ACTIONS = {
  "brainstorm",
  "review_knowledge",
  "generate_architecture",
  "continue_project",
  "chapter_generate",
  "chapter_workflow",
  "consistency_check",
  "rewrite_chapter",
  "skill_optimize",
}
_CHAPTER_ACTIONS = {"chapter_generate", "chapter_workflow", "consistency_check", "rewrite_chapter"}
_WRITING_ACTIONS = {"chapter_generate", "chapter_workflow", "rewrite_chapter"}
_ARCHITECTURE_KEYS = ("core_seed", "character_design", "world_building", "plot_structure", "blueprint")


def _check(check_id: str, status: str, message: str, *, severity: str = "info") -> dict[str, object]:
  return {
    "id": check_id,
    "status": status,
    "severity": severity,
    "message": message,
  }


def _has_model_config(settings: Settings) -> bool:
  config = load_config(settings).model
  return bool(config.api_key.strip() and config.base_url.strip() and config.model_name.strip())


def _has_review_model_config(settings: Settings) -> bool:
  config = load_config(settings).review_model
  return bool(config.enabled and config.api_key.strip() and config.base_url.strip() and config.model_name.strip())


def _project_dir(runtime: object) -> Path:
  return Path(str(getattr(getattr(runtime, "detail", None), "path", "") or ""))


def _chapter_by_id(runtime: object, chapter_id: str):
  detail = getattr(runtime, "detail", None)
  return next((item for item in getattr(detail, "chapters", []) or [] if getattr(item, "id", "") == chapter_id), None)


def _chapter_index_for_action(runtime: object, action: AgentPlanAction) -> int:
  chapter = _chapter_by_id(runtime, action.chapter_id)
  try:
    return int(getattr(chapter, "index", 0) or 0)
  except (TypeError, ValueError):
    return 0


def _project_documents(runtime: object) -> dict[str, str]:
  detail = getattr(runtime, "detail", None)
  overview = getattr(detail, "story_overview", None)
  return {
    str(getattr(item, "key", "") or ""): str(getattr(item, "content", "") or "")
    for item in getattr(overview, "documents", []) or []
  }


def _architecture_ready(runtime: object) -> bool:
  docs = _project_documents(runtime)
  return all(bool(docs.get(key, "").strip()) for key in _ARCHITECTURE_KEYS)


def _latest_failure_cases(project_dir: Path, limit: int = 30) -> list[dict[str, object]]:
  path = project_dir / ".gaoxia" / "learning" / "failure_cases.jsonl"
  if not path.exists():
    return []
  items: list[dict[str, object]] = []
  for raw in path.read_text(encoding="utf-8").splitlines()[-limit:]:
    line = raw.strip()
    if not line:
      continue
    try:
      parsed = json.loads(line)
    except json.JSONDecodeError:
      continue
    if isinstance(parsed, dict):
      items.append(parsed)
  return list(reversed(items))


def _failure_gate_checks(project_dir: Path, action: AgentPlanAction) -> list[dict[str, object]]:
  cases = [item for item in _latest_failure_cases(project_dir) if str(item.get("action_kind") or "") == action.kind]
  if not cases:
    return []
  repeated = Counter(str(item.get("summary") or "")[:120] for item in cases)
  top_count = max(repeated.values()) if repeated else 1
  severity = "warning" if top_count < 2 else "major"
  prevention = str(cases[0].get("prevention") or "执行前需要确认输入条件、章节选择和上一步产物。")
  return [
    _check(
      "failure_case_gate",
      "warning",
      f"同类动作有 {len(cases)} 条历史失败记录，执行前采用失败案例门禁：{prevention}",
      severity=severity,
    )
  ]


def action_contract_spec(action: AgentPlanAction) -> dict[str, object]:
  expected_outputs = {
    "brainstorm": ["discussion_summary"],
    "review_knowledge": ["knowledge_summary"],
    "generate_architecture": ["architecture_workspace", "project_documents"],
    "continue_project": ["continuation_plan"],
    "chapter_generate": ["chapter_content", "chapter_review"],
    "chapter_workflow": ["chapter_workflow"],
    "consistency_check": ["consistency_report"],
    "rewrite_chapter": ["rewrite_report", "chapter_review"],
    "skill_optimize": ["user_skill"],
  }.get(action.kind, [])
  failure_policy = {
    "on_condition_failed": "BLOCKED",
    "on_execution_failed": "FAILED",
    "on_output_missing": "FAILED",
    "retry": "manual_or_next_run",
  }
  if action.kind in {"review_knowledge", "brainstorm", "consistency_check"}:
    failure_policy["retry"] = "safe_to_retry"
  return {
    "action_kind": action.kind,
    "label": action.label,
    "expected_outputs": expected_outputs,
    "failure_policy": failure_policy,
  }


def build_agent_preflight_report(settings: Settings, runtime: object, plan: AgentPlan) -> dict[str, object]:
  checks: list[dict[str, object]] = []
  project_dir = _project_dir(runtime)
  checks.append(
    _check(
      "project_dir",
      "pass" if project_dir.exists() else "blocked",
      f"项目目录：{project_dir}",
      severity="critical",
    )
  )
  checks.append(
    _check(
      "plan_actions",
      "pass" if plan.actions else "blocked",
      f"计划动作数量：{len(plan.actions)}",
      severity="critical",
    )
  )
  if any(action.kind in _MODEL_ACTIONS for action in plan.actions):
    checks.append(
      _check(
        "model_config",
        "pass" if _has_model_config(settings) else "blocked",
        "写作模型配置完整。" if _has_model_config(settings) else "写作模型配置缺少 API Key、接口地址或模型名。",
        severity="critical",
      )
    )
  if any(action.kind in {"chapter_generate", "chapter_workflow", "rewrite_chapter"} for action in plan.actions):
    checks.append(
      _check(
        "review_model",
        "pass" if _has_review_model_config(settings) else "warning",
        "第二审查模型已配置，章节核验会优先使用独立评审模型。"
        if _has_review_model_config(settings)
        else "第二审查模型未完整配置，章节核验会退回当前写作模型；独立性较弱。",
        severity="warning",
      )
    )
  project_failure_cases = _latest_failure_cases(project_dir, limit=20) if project_dir.exists() else []
  if project_failure_cases:
    checks.append(
      _check(
        "failure_case_library",
        "warning",
        f"已读取 {len(project_failure_cases)} 条历史失败案例，相关动作会加入执行前门禁。",
        severity="warning",
      )
    )
  blocked = any(item["status"] == "blocked" for item in checks)
  return {
    "status": "blocked" if blocked else "pass",
    "checks": checks,
    "summary": "预检未通过。" if blocked else "预检完成。",
  }


def evaluate_agent_action_contract(
  settings: Settings,
  runtime: object,
  plan: AgentPlan,
  action: AgentPlanAction,
  *,
  completed_action_kinds: list[str] | None = None,
) -> dict[str, object]:
  spec = action_contract_spec(action)
  checks: list[dict[str, object]] = []
  project_dir = _project_dir(runtime)
  checks.append(
    _check(
      "project_exists",
      "pass" if project_dir.exists() else "blocked",
      f"项目目录：{project_dir}",
      severity="critical",
    )
  )
  if action.kind in _MODEL_ACTIONS:
    configured = _has_model_config(settings)
    checks.append(
      _check(
        "model_config",
        "pass" if configured else "blocked",
        "写作模型配置完整。" if configured else "写作模型配置不完整，不能执行模型动作。",
        severity="critical",
      )
    )
  if action.kind in _CHAPTER_ACTIONS:
    chapter = _chapter_by_id(runtime, action.chapter_id)
    checks.append(
      _check(
        "chapter_target",
        "pass" if chapter is not None else "blocked",
        f"目标章节：{action.chapter_id or '未指定'}",
        severity="critical",
      )
    )
  if action.kind in _WRITING_ACTIONS:
    completed = set(completed_action_kinds or [])
    architecture_in_plan_before = "generate_architecture" in completed
    ready = _architecture_ready(runtime) or architecture_in_plan_before
    checks.append(
      _check(
        "architecture_ready",
        "pass" if ready else "warning",
        "整书架构可用。" if ready else "整书架构不完整，本次允许执行，但结果必须通过章节核验和后续修订检查。",
        severity="major",
      )
    )
  if action.kind == "review_knowledge":
    overview = getattr(getattr(runtime, "detail", None), "story_overview", None)
    material_count = len(getattr(overview, "materials", []) or [])
    obsidian = getattr(overview, "obsidian", None)
    chapter_index = _chapter_index_for_action(runtime, action)
    if chapter_index > 0:
      obsidian_count = sum(
        1
        for note in list(getattr(obsidian, "notes", []) or [])
        if obsidian_note_available_for_chapter(note, chapter_index)
      )
      source_message = f"第 {chapter_index} 章可用资料数量：{material_count + obsidian_count}"
    else:
      obsidian_count = int(getattr(obsidian, "included_count", 0) or 0)
      source_message = f"资料数量：{material_count + obsidian_count}"
    source_count = material_count + obsidian_count
    checks.append(
      _check(
        "knowledge_materials",
        "pass" if source_count else "warning",
        source_message,
        severity="warning",
      )
    )
  checks.extend(_failure_gate_checks(project_dir, action) if project_dir.exists() else [])
  blocked = any(item["status"] == "blocked" for item in checks)
  return {
    **spec,
    "status": "blocked" if blocked else "pass",
    "checks": checks,
    "summary": "动作条件未满足。" if blocked else "动作条件满足。",
  }


def validate_agent_action_outputs(
  runtime: object,
  artifacts: list[Any],
  action: AgentPlanAction,
  *,
  artifact_count_before: int,
) -> dict[str, object]:
  delta = artifacts[artifact_count_before:]
  delta_kinds = [str(getattr(item, "kind", "") or "") for item in delta]
  checks: list[dict[str, object]] = []
  spec = action_contract_spec(action)
  expected = list(spec.get("expected_outputs") or [])
  if expected:
    artifact_expectations = [item for item in expected if item not in {"project_documents"}]
    missing = [
      item for item in artifact_expectations
      if item not in delta_kinds
      and not (item == "chapter_review" and "chapter_content" in delta_kinds)
      and not (item == "chapter_review" and "rewrite_report" in delta_kinds)
      and not (item == "user_skill" and any(kind.endswith("skill") for kind in delta_kinds))
    ]
    checks.append(
      _check(
        "artifact_outputs",
        "pass" if not missing else "blocked",
        f"新增产物：{', '.join(delta_kinds) or '无'}；缺少：{', '.join(missing) or '无'}",
        severity="critical",
      )
    )
  if "project_documents" in expected:
    ready = _architecture_ready(runtime)
    checks.append(
      _check(
        "project_documents",
        "pass" if ready else "warning",
        "架构文档已写入。" if ready else "架构文档没有全部写入；已记录产物缺口，后续需要重新执行架构生成。",
        severity="major",
      )
    )
  if (
    action.kind in {"chapter_generate", "rewrite_chapter"}
    or action.kind == "chapter_workflow" and action.mode == "draft"
  ) and action.chapter_id:
    chapter = _chapter_by_id(runtime, action.chapter_id)
    content = str(getattr(chapter, "content", "") or "") if chapter is not None else ""
    checks.append(
      _check(
        "chapter_content",
        "pass" if content.strip() else "blocked",
        f"章节正文长度：{len(content.strip())}",
        severity="critical",
      )
    )
  blocked = any(item["status"] == "blocked" for item in checks)
  return {
    "status": "blocked" if blocked else "pass",
    "checks": checks,
    "expected_outputs": expected,
    "observed_artifacts": delta_kinds,
    "summary": "产物检查未通过。" if blocked else "产物检查通过。",
  }
