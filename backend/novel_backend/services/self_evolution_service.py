from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from novel_backend.config import Settings
from novel_backend.models import SelfEvolutionCandidate, SelfEvolutionReport
from novel_backend.services.agent_trajectory_service import get_agent_trajectory_records
from novel_backend.services.log_service import get_prompt_history_records
from novel_backend.services.project_service import get_project_detail
from novel_backend.services.skill_service import get_skill_curation_report


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def _compact_text(text: object, limit: int = 220) -> str:
  normalized = " ".join(str(text or "").split())
  if len(normalized) <= limit:
    return normalized
  return f"{normalized[:limit].rstrip()}…"


def _candidate_id(kind: str, title: str, summary: str) -> str:
  raw = "::".join([kind.strip(), title.strip(), summary.strip()])
  return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]


def _learning_log_path(project_dir: Path) -> Path:
  return project_dir / ".gaoxia" / "learning" / "reviews.jsonl"


def _load_learning_reviews(project_dir: Path, limit: int = 200) -> list[dict[str, object]]:
  path = _learning_log_path(project_dir)
  if not path.exists():
    return []

  records: list[dict[str, object]] = []
  with path.open("r", encoding="utf-8") as handle:
    for raw_line in deque(handle, maxlen=max(1, limit)):
      line = raw_line.strip()
      if not line:
        continue
      try:
        payload = json.loads(line)
      except json.JSONDecodeError:
        continue
      if isinstance(payload, dict):
        records.append(payload)
  records.sort(key=lambda item: str(item.get("generated_at") or ""))
  return list(reversed(records))


def _as_dict_list(value: object) -> list[dict[str, object]]:
  if not isinstance(value, list):
    return []
  return [item for item in value if isinstance(item, dict)]


def _as_float(value: object, default: float = 0.0) -> float:
  if isinstance(value, int | float):
    return max(0.0, min(1.0, float(value)))
  try:
    return max(0.0, min(1.0, float(str(value))))
  except ValueError:
    return default


def _as_int(value: object) -> int | None:
  if isinstance(value, bool):
    return None
  if isinstance(value, int):
    return value
  if isinstance(value, float):
    return int(value)
  try:
    return int(str(value))
  except (TypeError, ValueError):
    return None


def _ordered_unique(items: list[object], limit: int = 5) -> list[str]:
  seen: set[str] = set()
  result: list[str] = []
  for raw in items:
    value = _compact_text(raw, 240)
    if not value or value in seen:
      continue
    seen.add(value)
    result.append(value)
    if len(result) >= limit:
      break
  return result


def _append_candidate(
  candidates: dict[str, SelfEvolutionCandidate],
  candidate: SelfEvolutionCandidate,
) -> None:
  existing = candidates.get(candidate.id)
  if existing is None:
    candidates[candidate.id] = candidate
    return

  existing.evidence = _ordered_unique([*existing.evidence, *candidate.evidence], 6)
  existing.source_task_ids = _ordered_unique([*existing.source_task_ids, *candidate.source_task_ids], 8)
  existing.confidence = max(existing.confidence, candidate.confidence)
  if len(candidate.summary) > len(existing.summary):
    existing.summary = candidate.summary


def _task_ids_from_review(review: dict[str, object]) -> list[str]:
  task_id = str(review.get("task_id") or "").strip()
  return [task_id] if task_id else []


def _candidate_from_learning_item(
  *,
  review: dict[str, object],
  item: dict[str, object],
  kind: str,
) -> SelfEvolutionCandidate:
  item_title = str(item.get("title") or ("技能候选" if kind == "skill" else "记忆候选")).strip()
  content = _compact_text(item.get("content") or item.get("summary") or item_title, 260)
  title_prefix = "写作技能候选" if kind == "skill" else "记忆候选待确认"
  title = f"{title_prefix}：{item_title}"
  latest_user = review.get("latest_user_message") or ""
  evidence = _ordered_unique([
    content,
    item.get("rationale") or "",
    f"来自任务：{review.get('plan', {}).get('title')}" if isinstance(review.get("plan"), dict) else "",
    f"用户要求：{latest_user}" if latest_user else "",
  ], 4)
  recommendation = (
    "通过用户技能沉淀入口创建或更新 SKILL.md，再用下一次章节任务验证。"
    if kind == "skill"
    else "由作者确认后写入项目记忆，避免把临时讨论误作长期规则。"
  )
  return SelfEvolutionCandidate(
    id=_candidate_id(kind, title, content),
    kind=kind,
    title=title,
    summary=content,
    evidence=evidence,
    recommendation=recommendation,
    confidence=_as_float(item.get("confidence"), 0.62),
    source_task_ids=_task_ids_from_review(review),
  )


def _review_candidate_from_artifact(record: dict[str, object], artifact: dict[str, object]) -> SelfEvolutionCandidate | None:
  kind = str(artifact.get("kind") or "")
  if kind not in {"chapter_content", "rewrite_report"}:
    return None

  metadata = artifact.get("metadata")
  if not isinstance(metadata, dict):
    return None

  review_score = _as_int(metadata.get("review_score"))
  review_status = str(metadata.get("review_status") or "")
  repair_applied = bool(metadata.get("review_auto_repair_applied"))
  if not repair_applied and review_status != "risk" and not (review_score is not None and review_score < 70):
    return None

  title = f"章节核验样本：{artifact.get('title') or record.get('task_id') or '未命名章节'}"
  summary = _compact_text(artifact.get("summary") or metadata.get("review_summary") or "章节核验发现了需要复查的问题。", 260)
  evidence = _ordered_unique([
    f"核验分数：{review_score}/100" if review_score is not None else "",
    f"核验状态：{review_status}" if review_status else "",
    f"自动修订：{metadata.get('review_auto_repair_summary')}" if metadata.get("review_auto_repair_summary") else "",
    f"修订原因：{metadata.get('review_auto_repair_reason')}" if metadata.get("review_auto_repair_reason") else "",
    f"任务：{record.get('plan', {}).get('title')}" if isinstance(record.get("plan"), dict) else "",
  ], 5)
  task_id = str(record.get("task_id") or "").strip()
  return SelfEvolutionCandidate(
    id=_candidate_id("review", title, summary),
    kind="review",
    title=title,
    summary=summary,
    evidence=evidence,
    recommendation="加入章节质量评测样本，后续比较提示词、技能和自动修订策略是否真的变好。",
    confidence=0.82 if repair_applied else 0.66,
    source_task_ids=[task_id] if task_id else [],
  )


def _failed_trajectory_candidate(record: dict[str, object]) -> SelfEvolutionCandidate:
  plan = record.get("plan") if isinstance(record.get("plan"), dict) else {}
  plan_title = str(plan.get("title") or record.get("task_id") or "未命名任务").strip()
  title = f"失败执行样本：{plan_title}"
  error = _compact_text(record.get("error") or "执行失败但没有记录错误详情。", 260)
  actions = plan.get("actions") if isinstance(plan.get("actions"), list) else []
  action_labels = [
    item.get("label") or item.get("kind")
    for item in actions
    if isinstance(item, dict) and (item.get("label") or item.get("kind"))
  ]
  evidence = _ordered_unique([
    error,
    f"用户要求：{record.get('latest_user_message')}" if record.get("latest_user_message") else "",
    f"动作：{' / '.join(str(item) for item in action_labels[:4])}" if action_labels else "",
  ], 4)
  task_id = str(record.get("task_id") or "").strip()
  return SelfEvolutionCandidate(
    id=_candidate_id("prompt", title, error),
    kind="prompt",
    title=title,
    summary=error,
    evidence=evidence,
    recommendation="保存为失败回归样本，复查对应 action 的提示词、工具权限和异常提示。",
    confidence=0.74,
    source_task_ids=[task_id] if task_id else [],
  )


def _prompt_failure_candidates(prompt_records: list[dict[str, object]]) -> list[SelfEvolutionCandidate]:
  grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
  for record in prompt_records:
    if str(record.get("status") or "") != "failed":
      continue
    key = str(record.get("error_title") or record.get("error_kind") or record.get("task") or "模型调用失败").strip()
    grouped[key].append(record)

  candidates: list[SelfEvolutionCandidate] = []
  for key, items in sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True)[:4]:
    latest = items[0]
    task_names = _ordered_unique([item.get("task") for item in items], 4)
    summary = _compact_text(f"{len(items)} 次失败，最近任务：{latest.get('task') or '未命名任务'}。{latest.get('error') or ''}", 260)
    evidence = _ordered_unique([
      f"模型：{latest.get('model')}" if latest.get("model") else "",
      f"任务：{' / '.join(task_names)}" if task_names else "",
      latest.get("error") or "",
      latest.get("error_user_action") or "",
    ], 5)
    candidates.append(
      SelfEvolutionCandidate(
        id=_candidate_id("prompt", f"Prompt 失败样本：{key}", summary),
        kind="prompt",
        title=f"Prompt 失败样本：{key}",
        summary=summary,
        evidence=evidence,
        recommendation="把失败请求纳入提示词方案回归，区分模型配置问题和提示词质量问题。",
        confidence=min(0.86, 0.58 + len(items) * 0.06),
        source_task_ids=task_names,
      )
    )
  return candidates


def build_self_evolution_report(settings: Settings, project_id: str) -> SelfEvolutionReport:
  detail = get_project_detail(settings, project_id)
  project_dir = Path(detail.path)
  learning_reviews = _load_learning_reviews(project_dir)
  trajectories_payload = get_agent_trajectory_records(settings, tail=200, search=project_id)
  prompt_payload = get_prompt_history_records(settings, tail=200, search="")

  trajectory_records = _as_dict_list(trajectories_payload.get("records"))
  prompt_records = _as_dict_list(prompt_payload.get("records"))
  candidates: dict[str, SelfEvolutionCandidate] = {}

  for review in learning_reviews:
    for item in _as_dict_list(review.get("skill_candidates")):
      _append_candidate(
        candidates,
        _candidate_from_learning_item(review=review, item=item, kind="skill"),
      )
    for item in _as_dict_list(review.get("memory_candidates")):
      _append_candidate(
        candidates,
        _candidate_from_learning_item(review=review, item=item, kind="memory"),
      )

  for record in trajectory_records:
    if str(record.get("status") or "") == "failed":
      _append_candidate(candidates, _failed_trajectory_candidate(record))
    for artifact in _as_dict_list(record.get("artifacts")):
      candidate = _review_candidate_from_artifact(record, artifact)
      if candidate is not None:
        _append_candidate(candidates, candidate)

  for candidate in _prompt_failure_candidates(prompt_records):
    _append_candidate(candidates, candidate)

  ordered_candidates = sorted(
    candidates.values(),
    key=lambda item: (-item.confidence, item.kind, item.title),
  )[:16]
  prompt_failure_count = sum(1 for item in prompt_records if str(item.get("status") or "") == "failed")

  return SelfEvolutionReport(
    project_id=project_id,
    generated_at=_now_iso(),
    candidates=ordered_candidates,
    skill_curation=get_skill_curation_report(settings),
    prompt_failure_count=prompt_failure_count,
    trajectory_count=int(trajectories_payload.get("total") or len(trajectory_records)),
    learning_review_count=len(learning_reviews),
  )
