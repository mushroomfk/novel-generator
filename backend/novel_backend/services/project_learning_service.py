from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from novel_backend.models import (
  AgentArtifact,
  AgentChatRequest,
  AgentChatResult,
  AgentExecutionTrace,
  AgentPlan,
)


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def _compact_text(text: str, limit: int = 220) -> str:
  normalized = " ".join(str(text or "").split())
  if len(normalized) <= limit:
    return normalized
  return f"{normalized[:limit].rstrip()}…"


def _latest_user_text(payload: AgentChatRequest) -> str:
  for item in reversed(payload.messages):
    if item.role == "user" and item.content.strip():
      return item.content.strip()
  return ""


def _candidate_id(kind: str, title: str, content: str) -> str:
  raw = "::".join([kind.strip(), title.strip(), content.strip()])
  return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _review_dir(project_dir: Path) -> Path:
  return project_dir / ".gaoxia" / "learning"


def _review_log_path(project_dir: Path) -> Path:
  return _review_dir(project_dir) / "reviews.jsonl"


def _append_review(project_dir: Path, review: dict[str, object]) -> None:
  path = _review_log_path(project_dir)
  path.parent.mkdir(parents=True, exist_ok=True)
  with path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(review, ensure_ascii=False) + "\n")


def _build_memory_candidates(
  payload: AgentChatRequest,
  result: AgentChatResult,
) -> list[dict[str, object]]:
  candidates: list[dict[str, object]] = []
  latest_user = _latest_user_text(payload)

  if result.can_save_discussion_summary and result.reply.strip():
    content = _compact_text(result.reply, 260)
    candidates.append(
      {
        "id": _candidate_id("memory", "讨论结论", content),
        "kind": "memory",
        "title": "讨论结论",
        "category": "目标",
        "content": content,
        "rationale": "本次讨论形成了后续规划可复用的判断，但还没有写入作者记忆。",
        "confidence": 0.72,
        "status": "pending",
      }
    )

  for artifact in result.artifacts:
    if artifact.kind != "knowledge_summary":
      continue
    content = _compact_text(artifact.content_preview or artifact.summary, 260)
    if not content:
      continue
    candidates.append(
      {
        "id": _candidate_id("memory", artifact.title or "资料分析要点", content),
        "kind": "memory",
        "title": artifact.title or "资料分析要点",
        "category": "连续性",
        "content": content,
        "rationale": "资料分析结论可能会影响后续架构或续写，适合由作者确认后写入项目记忆。",
        "confidence": 0.68,
        "status": "pending",
      }
    )

  if any(token in latest_user for token in ("以后", "每次", "固定", "都按")):
    content = _compact_text(latest_user, 220)
    candidates.append(
      {
        "id": _candidate_id("memory", "作者流程偏好", content),
        "kind": "memory",
        "title": "作者流程偏好",
        "category": "偏好",
        "content": content,
        "rationale": "用户表达了可长期复用的处理偏好，写入前需要作者确认。",
        "confidence": 0.66,
        "status": "pending",
      }
    )

  unique: dict[str, dict[str, object]] = {}
  for item in candidates:
    unique[str(item["id"])] = item
  return list(unique.values())[:4]


def _build_skill_candidates(
  payload: AgentChatRequest,
  result: AgentChatResult,
) -> list[dict[str, object]]:
  latest_user = _latest_user_text(payload)
  if any(artifact.kind == "user_skill" for artifact in result.artifacts):
    return []

  candidate_signals = [
    suggestion for suggestion in result.suggestions
    if "保存成用户技能" in suggestion or "用户技能" in suggestion
  ]
  if not candidate_signals:
    return []

  content = _compact_text(latest_user or "本次形成了可复用流程。", 260)
  return [
    {
      "id": _candidate_id("skill", "用户技能候选", content),
      "kind": "skill",
      "title": "用户技能候选",
      "category": "用户技能",
      "content": content,
      "rationale": _compact_text(candidate_signals[0], 160),
      "confidence": 0.7,
      "status": "pending",
    }
  ]


def _build_risk_notes(traces: list[AgentExecutionTrace]) -> list[str]:
  notes: list[str] = []
  failed = [item for item in traces if item.status == "failed"]
  if failed:
    notes.append(f"有 {len(failed)} 个执行步骤失败，后续复用前需要先看错误。")
  if len(traces) >= 5:
    notes.append("本次动作较多，适合回看是否有可复用流程或资料约束。")
  return notes[:3]


def _build_review_payload(
  *,
  project_id: str,
  project_dir: Path,
  payload: AgentChatRequest,
  plan: AgentPlan,
  result: AgentChatResult,
) -> dict[str, object] | None:
  memory_candidates = _build_memory_candidates(payload, result)
  skill_candidates = _build_skill_candidates(payload, result)
  risk_notes = _build_risk_notes(result.execution_trace)
  if not memory_candidates and not skill_candidates and not risk_notes:
    return None

  review_id = f"learning-{_candidate_id(project_id, result.task_id, _now_iso())}"
  return {
    "id": review_id,
    "project_id": project_id,
    "thread_id": payload.thread_id,
    "task_id": result.task_id,
    "generated_at": _now_iso(),
    "latest_user_message": _compact_text(_latest_user_text(payload), 300),
    "plan": {
      "title": plan.title,
      "actions": [item.kind for item in plan.actions],
    },
    "memory_candidates": memory_candidates,
    "skill_candidates": skill_candidates,
    "risk_notes": risk_notes,
    "status": "pending",
    "review_path": str(_review_log_path(project_dir)),
  }


def build_learning_review_artifact(
  *,
  project_id: str,
  project_dir: Path,
  payload: AgentChatRequest,
  plan: AgentPlan,
  result: AgentChatResult,
) -> AgentArtifact | None:
  review = _build_review_payload(
    project_id=project_id,
    project_dir=project_dir,
    payload=payload,
    plan=plan,
    result=result,
  )
  if review is None:
    return None

  _append_review(project_dir, review)
  memory_count = len(review["memory_candidates"])
  skill_count = len(review["skill_candidates"])
  risk_count = len(review["risk_notes"])
  summary = f"生成 {memory_count} 条记忆候选、{skill_count} 条技能候选、{risk_count} 条风险提示。"
  preview_parts: list[str] = []
  for item in review["memory_candidates"][:2]:
    preview_parts.append(f"记忆候选：{item['title']}｜{item['content']}")
  for item in review["skill_candidates"][:1]:
    preview_parts.append(f"技能候选：{item['content']}")
  for note in review["risk_notes"][:1]:
    preview_parts.append(f"提示：{note}")

  return AgentArtifact(
    kind="learning_review",
    title="经验候选",
    summary=summary,
    content_preview="\n".join(preview_parts),
    metadata={
      "review_id": review["id"],
      "memory_candidate_count": memory_count,
      "skill_candidate_count": skill_count,
      "risk_note_count": risk_count,
      "review_path": review["review_path"],
    },
  )
