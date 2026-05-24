from __future__ import annotations

import hashlib
import json
import os
import re
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from novel_backend.config import Settings
from novel_backend.models import (
  AgentArtifact,
  AgentChatRequest,
  AgentChatResult,
  AgentPlan,
  BrainstormMessage,
  ProjectMemoryEntryInput,
  SkillMaterializeRequest,
)
from novel_backend.services.generation_service import (
  _chat_completions_endpoint,
  _extract_json_object,
  _extract_message_content,
  _invoke_model,
  _request_chat_completion,
  _string_list_from_keys,
)
from novel_backend.services.config_service import load_config
from novel_backend.services.model_runtime_service import mark_model_runtime_cooldown, model_runtime_slot
from novel_backend.services.project_memory_service import append_project_memory
from novel_backend.services.skill_service import materialize_skill
from novel_backend.services.skill_usage_service import (
  get_skill_usage_state,
  record_skill_usage,
  run_skill_curator,
)
from novel_backend.utils.jsonfile import atomic_write_json, read_json

_LEARNING_DIRNAME = "learning"
_CANDIDATE_STATUS_VALUES = {"pending", "accepted", "rejected", "archived"}
_DRAFT_STATUS_VALUES = {"pending", "applied", "discarded"}
_SCHEDULE_TASK_VALUES = {"curate", "regression", "model_review"}
_SELF_EVOLUTION_LIMIT = 200
_REGRESSION_CASES = (
  ("continuation", "续写样本"),
  ("rewrite", "改稿样本"),
  ("humanize", "去 AI 样本"),
  ("knowledge", "资料调用样本"),
)


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def _parse_datetime(value: object) -> datetime | None:
  if not isinstance(value, str) or not value.strip():
    return None
  normalized = value.strip()
  if normalized.endswith("Z"):
    normalized = f"{normalized[:-1]}+00:00"
  try:
    parsed = datetime.fromisoformat(normalized)
  except ValueError:
    return None
  if parsed.tzinfo is None:
    return parsed.replace(tzinfo=timezone.utc)
  return parsed.astimezone(timezone.utc)


def _compact_text(text: str, limit: int = 260) -> str:
  normalized = " ".join(str(text or "").split())
  if len(normalized) <= limit:
    return normalized
  return f"{normalized[:limit].rstrip()}…"


def _learning_dir(project_dir: Path) -> Path:
  return project_dir / ".gaoxia" / _LEARNING_DIRNAME


def _candidate_path(project_dir: Path) -> Path:
  return _learning_dir(project_dir) / "self_evolution_candidates.json"


def _review_log_path(project_dir: Path) -> Path:
  return _learning_dir(project_dir) / "self_evolution_reviews.jsonl"


def _capability_rules_path(project_dir: Path) -> Path:
  return _learning_dir(project_dir) / "agent_capability_rules.json"


def _writing_evaluation_path(project_dir: Path) -> Path:
  return _learning_dir(project_dir) / "writing_evaluations.jsonl"


def _drafts_path(project_dir: Path) -> Path:
  return _learning_dir(project_dir) / "self_evolution_drafts.json"


def _model_review_path(project_dir: Path) -> Path:
  return _learning_dir(project_dir) / "self_evolution_model_reviews.jsonl"


def _writing_regression_path(project_dir: Path) -> Path:
  return _learning_dir(project_dir) / "writing_regression_runs.jsonl"


def _schedule_path(project_dir: Path) -> Path:
  return _learning_dir(project_dir) / "self_evolution_schedule.json"


def _failure_case_path(project_dir: Path) -> Path:
  return _learning_dir(project_dir) / "failure_cases.jsonl"


def _candidate_id(kind: str, title: str, content: str) -> str:
  raw = "::".join([kind.strip(), title.strip(), content.strip()])
  return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _latest_user_text(payload: AgentChatRequest) -> str:
  for item in reversed(payload.messages):
    if item.role == "user" and item.content.strip():
      return item.content.strip()
  return ""


def _ordered_unique(items: list[str]) -> list[str]:
  seen: set[str] = set()
  ordered: list[str] = []
  for raw in items:
    value = str(raw or "").strip()
    if not value or value in seen:
      continue
    seen.add(value)
    ordered.append(value)
  return ordered


def _action_kinds(plan: AgentPlan) -> list[str]:
  return [action.kind for action in plan.actions]


def _skill_ids(payload: AgentChatRequest, plan: AgentPlan) -> list[str]:
  ids = list(payload.active_skill_ids)
  for action in plan.actions:
    ids.extend(action.skill_ids)
  return _ordered_unique(ids)


def _task_pack_kind(plan: AgentPlan, result: AgentChatResult) -> str:
  if result.task_pack_kind:
    return result.task_pack_kind
  for action in reversed(plan.actions):
    if action.task_pack_kind:
      return action.task_pack_kind
  return ""


def _failed_traces(result: AgentChatResult) -> list[object]:
  return [trace for trace in result.execution_trace if trace.status == "failed"]


def _append_jsonl(path: Path, payload: dict[str, object]) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  with path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _load_candidates(project_dir: Path) -> dict[str, object]:
  payload = read_json(_candidate_path(project_dir), None)
  if not isinstance(payload, dict):
    return {"schema_version": 1, "updated_at": _now_iso(), "items": []}
  items = payload.get("items")
  if not isinstance(items, list):
    payload["items"] = []
  payload.setdefault("schema_version", 1)
  payload.setdefault("updated_at", _now_iso())
  return payload


def _load_drafts(project_dir: Path) -> dict[str, object]:
  payload = read_json(_drafts_path(project_dir), None)
  if not isinstance(payload, dict):
    return {"schema_version": 1, "updated_at": _now_iso(), "items": []}
  items = payload.get("items")
  if not isinstance(items, list):
    payload["items"] = []
  payload.setdefault("schema_version", 1)
  payload.setdefault("updated_at", _now_iso())
  return payload


def _save_drafts(project_dir: Path, store: dict[str, object]) -> None:
  store["updated_at"] = _now_iso()
  atomic_write_json(_drafts_path(project_dir), store)


def _latest_jsonl_items(path: Path, limit: int) -> list[dict[str, object]]:
  items: list[dict[str, object]] = []
  if not path.exists():
    return items
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
        items.append(payload)
  return list(reversed(items))


def _load_schedule(project_dir: Path) -> dict[str, object]:
  payload = read_json(_schedule_path(project_dir), None)
  if not isinstance(payload, dict):
    return {
      "schema_version": 1,
      "enabled": False,
      "tasks": ["curate", "regression", "model_review"],
      "interval_hours": 168,
      "last_run_at": "",
      "updated_at": _now_iso(),
    }
  tasks = [
    str(item)
    for item in payload.get("tasks") or []
    if str(item) in _SCHEDULE_TASK_VALUES
  ]
  payload["tasks"] = tasks or ["curate", "regression", "model_review"]
  payload["enabled"] = bool(payload.get("enabled", False))
  try:
    payload["interval_hours"] = max(1, min(int(payload.get("interval_hours") or 168), 24 * 90))
  except (TypeError, ValueError):
    payload["interval_hours"] = 168
  payload.setdefault("schema_version", 1)
  payload.setdefault("last_run_at", "")
  payload.setdefault("updated_at", _now_iso())
  return payload


def update_self_evolution_schedule(project_dir: Path, payload: dict[str, object]) -> dict[str, object]:
  current = _load_schedule(project_dir)
  if "enabled" in payload:
    current["enabled"] = bool(payload.get("enabled"))
  if "interval_hours" in payload:
    try:
      current["interval_hours"] = max(1, min(int(payload.get("interval_hours") or 168), 24 * 90))
    except (TypeError, ValueError):
      raise ValueError("排程间隔无效") from None
  if "tasks" in payload:
    tasks = [str(item) for item in payload.get("tasks") or [] if str(item) in _SCHEDULE_TASK_VALUES]
    current["tasks"] = tasks or ["curate", "regression", "model_review"]
  current["updated_at"] = _now_iso()
  atomic_write_json(_schedule_path(project_dir), current)
  return current


def _draft_diff_preview(draft: dict[str, object]) -> dict[str, object]:
  payload = draft.get("payload") if isinstance(draft.get("payload"), dict) else {}
  kind = str(draft.get("kind") or "")
  if kind == "memory":
    entries = payload.get("entries") if isinstance(payload.get("entries"), list) else []
    return {
      "summary": f"将新增 {len(entries)} 条作者侧项目记忆。",
      "additions": [
        f"{item.get('category', '连续性')}｜{item.get('title', '')}：{item.get('content', '')}"
        for item in entries
        if isinstance(item, dict)
      ],
      "warnings": [],
    }
  if kind == "skill":
    body = str(payload.get("body_markdown") or "")
    action = str(payload.get("action") or "create")
    target_skill_id = str(payload.get("target_skill_id") or "")
    return {
      "summary": "将更新用户技能。" if action == "iterate" and target_skill_id else "将创建用户技能。",
      "additions": [body[:1600]] if body else [],
      "warnings": ["应用后仍会走技能生成自检，并保留版本记录。"],
    }
  if kind == "capability":
    rule = payload.get("rule") if isinstance(payload.get("rule"), dict) else {}
    return {
      "summary": "将把调用规则标为作者采纳。",
      "additions": [f"{rule.get('title', '')}：{rule.get('content', '')}"],
      "warnings": [],
    }
  return {"summary": "", "additions": [], "warnings": []}


def _candidate(
  *,
  kind: str,
  title: str,
  content: str,
  rationale: str,
  confidence: float,
  project_id: str,
  task_id: str,
  thread_id: str,
  metadata: dict[str, object] | None = None,
) -> dict[str, object]:
  normalized_content = _compact_text(content, 480)
  normalized_title = _compact_text(title, 80)
  return {
    "id": _candidate_id(kind, normalized_title, normalized_content),
    "kind": kind,
    "title": normalized_title,
    "content": normalized_content,
    "rationale": _compact_text(rationale, 300),
    "confidence": max(0.0, min(float(confidence), 1.0)),
    "status": "pending",
    "project_id": project_id,
    "thread_id": thread_id,
    "source_task_id": task_id,
    "created_at": _now_iso(),
    "last_seen_at": _now_iso(),
    "seen_count": 1,
    "metadata": dict(metadata or {}),
  }


def _merge_candidates(project_dir: Path, candidates: list[dict[str, object]]) -> dict[str, object]:
  store = _load_candidates(project_dir)
  existing_items = store.get("items")
  if not isinstance(existing_items, list):
    existing_items = []

  by_id: dict[str, dict[str, object]] = {}
  for item in existing_items:
    if isinstance(item, dict) and str(item.get("id") or "").strip():
      by_id[str(item["id"])] = item

  inserted = 0
  refreshed = 0
  for candidate in candidates:
    candidate_id = str(candidate.get("id") or "").strip()
    if not candidate_id:
      continue
    if candidate_id in by_id:
      existing = by_id[candidate_id]
      existing["last_seen_at"] = _now_iso()
      existing["seen_count"] = int(existing.get("seen_count") or 1) + 1
      existing["confidence"] = max(float(existing.get("confidence") or 0), float(candidate.get("confidence") or 0))
      existing["source_task_id"] = candidate.get("source_task_id", existing.get("source_task_id", ""))
      refreshed += 1
      continue
    by_id[candidate_id] = candidate
    inserted += 1

  items = sorted(
    by_id.values(),
    key=lambda item: str(item.get("last_seen_at") or item.get("created_at") or ""),
    reverse=True,
  )[:_SELF_EVOLUTION_LIMIT]
  store["items"] = items
  store["updated_at"] = _now_iso()
  atomic_write_json(_candidate_path(project_dir), store)
  return {"inserted": inserted, "refreshed": refreshed, "total": len(items)}


def _load_capability_rules(project_dir: Path) -> dict[str, object]:
  payload = read_json(_capability_rules_path(project_dir), None)
  if not isinstance(payload, dict):
    return {"schema_version": 1, "updated_at": _now_iso(), "rules": []}
  rules = payload.get("rules")
  if not isinstance(rules, list):
    payload["rules"] = []
  payload.setdefault("schema_version", 1)
  payload.setdefault("updated_at", _now_iso())
  return payload


def _apply_capability_rules(project_dir: Path, candidates: list[dict[str, object]]) -> dict[str, object]:
  store = _load_capability_rules(project_dir)
  rules = store.get("rules")
  if not isinstance(rules, list):
    rules = []

  by_id: dict[str, dict[str, object]] = {
    str(item.get("id")): item
    for item in rules
    if isinstance(item, dict) and str(item.get("id") or "").strip()
  }
  applied = 0
  refreshed = 0
  for candidate in candidates:
    if candidate.get("kind") != "capability":
      continue
    if float(candidate.get("confidence") or 0) < 0.72:
      continue
    rule_id = f"cap-{candidate['id']}"
    if rule_id in by_id:
      rule = by_id[rule_id]
      rule["last_seen_at"] = _now_iso()
      rule["seen_count"] = int(rule.get("seen_count") or 1) + 1
      rule["confidence"] = max(float(rule.get("confidence") or 0), float(candidate.get("confidence") or 0))
      refreshed += 1
      continue
    by_id[rule_id] = {
      "id": rule_id,
      "title": candidate.get("title", ""),
      "content": candidate.get("content", ""),
      "rationale": candidate.get("rationale", ""),
      "confidence": candidate.get("confidence", 0),
      "source_candidate_id": candidate.get("id", ""),
      "created_at": _now_iso(),
      "last_seen_at": _now_iso(),
      "seen_count": 1,
      "metadata": candidate.get("metadata", {}),
    }
    applied += 1

  next_rules = sorted(
    by_id.values(),
    key=lambda item: str(item.get("last_seen_at") or item.get("created_at") or ""),
    reverse=True,
  )[:120]
  store["rules"] = next_rules
  store["updated_at"] = _now_iso()
  atomic_write_json(_capability_rules_path(project_dir), store)
  return {"applied": applied, "refreshed": refreshed, "total": len(next_rules)}


def build_agent_capability_context(project_dir: Path, limit: int = 6) -> str:
  store = _load_capability_rules(project_dir)
  rules = store.get("rules")
  if not isinstance(rules, list):
    rules = []

  usable_rules = [
    item for item in rules
    if isinstance(item, dict)
    and str(item.get("content") or "").strip()
    and float(item.get("confidence") or 0) >= 0.7
  ]

  usable_rules.sort(
    key=lambda item: (
      float(item.get("confidence") or 0),
      int(item.get("seen_count") or 0),
      str(item.get("last_seen_at") or item.get("created_at") or ""),
    ),
    reverse=True,
  )
  lines: list[str] = []
  if usable_rules:
    lines.append("Agent 自学习调用规则：")
    for item in usable_rules[:max(1, min(limit, 12))]:
      title = _compact_text(str(item.get("title") or "调用规则"), 48)
      content = _compact_text(str(item.get("content") or ""), 180)
      if title and content:
        lines.append(f"- {title}：{content}")
  failure_context = _failure_case_context(project_dir, limit=3)
  if failure_context:
    lines.append(failure_context)
  return "\n".join(lines).strip()


def _memory_category_for_candidate(candidate: dict[str, object]) -> str:
  text = f"{candidate.get('title', '')}\n{candidate.get('content', '')}"
  if any(token in text for token in ("偏好", "喜欢", "以后", "每次", "固定")):
    return "偏好"
  if any(token in text for token in ("警告", "不要", "避免", "禁止")):
    return "警告"
  if any(token in text for token in ("目标", "方向", "推进")):
    return "目标"
  return "连续性"


def _skill_draft_markdown(candidate: dict[str, object]) -> str:
  title = _compact_text(str(candidate.get("title") or "用户沉淀技能"), 48)
  content = str(candidate.get("content") or "").strip()
  rationale = str(candidate.get("rationale") or "").strip()
  return (
    f"# {title}\n\n"
    "## 适用场景\n"
    "- 主对话再次出现同类写作要求时。\n"
    "- 需要把已经验证过的处理方式复用到章节、设定或资料分析时。\n\n"
    "## 输入要求\n"
    "- 用户需要说明当前处理对象、目标和不能改动的部分。\n"
    "- 如果只处理某一章或某一类资料，需要点明范围。\n\n"
    "## 执行步骤\n"
    f"1. 读取本次候选经验：{_compact_text(content, 140)}\n"
    "2. 对照当前作品上下文，只保留和本轮任务有关的约束。\n"
    "3. 按固定顺序处理资料、架构、章节或改稿任务。\n"
    "4. 输出结果时说明已使用的规则和还需要作者确认的部分。\n\n"
    "## 输出要求\n"
    "- 给出可以直接执行的结果或修改建议。\n"
    "- 标出本次沿用的固定规则。\n"
    "- 如果信息不足，说明缺口，不直接替作者做长期设定决定。\n\n"
    "## 边界\n"
    f"- 草案来源：{_compact_text(rationale or content, 160)}\n"
    "- 应用前需要作者在自学习面板确认。"
  )


def _draft_for_candidate(candidate: dict[str, object]) -> dict[str, object]:
  candidate_id = str(candidate.get("id") or "").strip()
  kind = str(candidate.get("kind") or "").strip() or "memory"
  metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
  now_iso = _now_iso()
  draft_id = f"draft-{kind}-{candidate_id}"
  title = _compact_text(str(candidate.get("title") or "自学习候选"), 80)
  content = str(candidate.get("content") or "").strip()
  rationale = str(candidate.get("rationale") or "").strip()

  if kind == "skill":
    action = str(metadata.get("action") or "").strip() or ("iterate" if metadata.get("target_skill_id") else "create")
    target_skill_id = str(metadata.get("target_skill_id") or "").strip()
    draft = {
      "id": draft_id,
      "kind": "skill",
      "status": "pending",
      "title": f"用户技能草案：{title}",
      "summary": "确认后会创建或更新用户技能。",
      "source_candidate_id": candidate_id,
      "project_id": candidate.get("project_id", ""),
      "created_at": now_iso,
      "updated_at": now_iso,
      "payload": {
        "project_id": candidate.get("project_id", ""),
        "action": "iterate" if action == "iterate" and target_skill_id else "create",
        "target_skill_id": target_skill_id,
        "skill_name": title,
        "messages": [
          {"role": "user", "content": content},
          {"role": "assistant", "content": rationale or "这条经验适合整理为可复用用户技能。"},
        ],
        "body_markdown": _skill_draft_markdown(candidate),
      },
    }
    draft["diff_preview"] = _draft_diff_preview(draft)
    return draft

  if kind == "capability":
    draft = {
      "id": draft_id,
      "kind": "capability",
      "status": "pending",
      "title": f"调用规则草案：{title}",
      "summary": "确认后会把这条规则标为作者采纳。",
      "source_candidate_id": candidate_id,
      "project_id": candidate.get("project_id", ""),
      "created_at": now_iso,
      "updated_at": now_iso,
      "payload": {
        "rule": {
          "title": title,
          "content": content,
          "rationale": rationale,
          "confidence": candidate.get("confidence", 0),
          "source_candidate_id": candidate_id,
          "metadata": metadata,
        },
      },
    }
    draft["diff_preview"] = _draft_diff_preview(draft)
    return draft

  category = _memory_category_for_candidate(candidate)
  draft = {
    "id": draft_id,
    "kind": "memory",
    "status": "pending",
    "title": f"项目记忆草案：{title}",
    "summary": "确认后会写入作者侧项目记忆。",
    "source_candidate_id": candidate_id,
    "project_id": candidate.get("project_id", ""),
    "created_at": now_iso,
    "updated_at": now_iso,
    "payload": {
      "entries": [
        {
          "title": title,
          "category": category,
          "content": content,
        }
      ],
    },
  }
  draft["diff_preview"] = _draft_diff_preview(draft)
  return draft


def _ensure_candidate_draft(project_dir: Path, candidate: dict[str, object]) -> dict[str, object]:
  store = _load_drafts(project_dir)
  items = store.get("items")
  if not isinstance(items, list):
    items = []
  source_candidate_id = str(candidate.get("id") or "").strip()
  for item in items:
    if isinstance(item, dict) and str(item.get("source_candidate_id") or "") == source_candidate_id:
      item["updated_at"] = _now_iso()
      _save_drafts(project_dir, store)
      return item
  draft = _draft_for_candidate(candidate)
  items.insert(0, draft)
  store["items"] = items[:_SELF_EVOLUTION_LIMIT]
  _save_drafts(project_dir, store)
  return draft


def _upsert_accepted_capability_rule(project_dir: Path, rule_payload: dict[str, object]) -> dict[str, object]:
  store = _load_capability_rules(project_dir)
  rules = store.get("rules")
  if not isinstance(rules, list):
    rules = []
  source_candidate_id = str(rule_payload.get("source_candidate_id") or "").strip()
  rule_id = f"accepted-{source_candidate_id or _candidate_id('capability', str(rule_payload.get('title') or ''), str(rule_payload.get('content') or ''))}"
  matched = None
  for item in rules:
    if isinstance(item, dict) and str(item.get("id") or "") == rule_id:
      matched = item
      break
  if matched is None:
    matched = {
      "id": rule_id,
      "created_at": _now_iso(),
      "seen_count": 1,
    }
    rules.insert(0, matched)
  matched.update(
    {
      "title": rule_payload.get("title", ""),
      "content": rule_payload.get("content", ""),
      "rationale": rule_payload.get("rationale", ""),
      "confidence": max(0.82, float(rule_payload.get("confidence") or 0)),
      "source_candidate_id": source_candidate_id,
      "last_seen_at": _now_iso(),
      "accepted_at": _now_iso(),
      "metadata": rule_payload.get("metadata", {}),
    }
  )
  store["rules"] = rules[:120]
  store["updated_at"] = _now_iso()
  atomic_write_json(_capability_rules_path(project_dir), store)
  return matched


def _build_memory_candidates(
  payload: AgentChatRequest,
  result: AgentChatResult,
) -> list[dict[str, object]]:
  latest_user = _latest_user_text(payload)
  candidates: list[dict[str, object]] = []
  if result.can_save_discussion_summary and result.reply.strip():
    candidates.append(
      _candidate(
        kind="memory",
        title="讨论结论候选",
        content=result.reply,
        rationale="本次讨论形成了后续写作可复用的信息，需要作者确认后再进入项目记忆。",
        confidence=0.7,
        project_id=payload.project_id,
        task_id=result.task_id,
        thread_id=payload.thread_id,
        metadata={"source": "discussion"},
      )
    )
  if any(token in latest_user for token in ("以后", "每次", "固定", "都按", "一直按")):
    candidates.append(
      _candidate(
        kind="memory",
        title="作者偏好候选",
        content=latest_user,
        rationale="用户表达了长期偏好，写入项目记忆前需要确认范围。",
        confidence=0.68,
        project_id=payload.project_id,
        task_id=result.task_id,
        thread_id=payload.thread_id,
        metadata={"source": "user_preference"},
      )
    )
  return candidates


def _build_skill_candidates(
  payload: AgentChatRequest,
  plan: AgentPlan,
  result: AgentChatResult,
  skill_ids: list[str],
) -> list[dict[str, object]]:
  if any(action.kind == "skill_optimize" for action in plan.actions):
    return []
  latest_user = _latest_user_text(payload)
  skill_signal = next(
    (
      suggestion for suggestion in result.suggestions
      if "用户技能" in suggestion or "保存成" in suggestion or "技能" in suggestion
    ),
    "",
  )
  if not skill_signal and not any(token in latest_user for token in ("流程", "规则", "以后", "每次", "固定", "都按")):
    return []

  target_skill_id = skill_ids[0] if skill_ids else ""
  return [
    _candidate(
      kind="skill",
      title="技能更新候选" if target_skill_id else "技能创建候选",
      content=latest_user or result.reply,
      rationale=skill_signal or "本次任务出现了可复用处理方式，适合整理为技能候选。",
      confidence=0.78 if skill_signal else 0.64,
      project_id=payload.project_id,
      task_id=result.task_id,
      thread_id=payload.thread_id,
      metadata={
        "target_skill_id": target_skill_id,
        "action": "iterate" if target_skill_id else "create",
      },
    )
  ]


def _build_capability_candidates(
  payload: AgentChatRequest,
  plan: AgentPlan,
  result: AgentChatResult,
  skill_ids: list[str],
) -> list[dict[str, object]]:
  latest_user = _latest_user_text(payload)
  actions = _action_kinds(plan)
  candidates: list[dict[str, object]] = []
  failures = _failed_traces(result)
  if failures:
    first = failures[0]
    candidates.append(
      _candidate(
        kind="capability",
        title="失败动作复盘规则",
        content=f"动作 {getattr(first, 'action_kind', '')} 失败时，下次同类任务需要先检查输入条件和项目状态，再继续执行。",
        rationale=_compact_text(getattr(first, "summary", "") or "执行步骤失败。", 220),
        confidence=0.82,
        project_id=payload.project_id,
        task_id=result.task_id,
        thread_id=payload.thread_id,
        metadata={"actions": actions, "failure_count": len(failures)},
      )
    )
  if "review_knowledge" in actions:
    candidates.append(
      _candidate(
        kind="capability",
        title="资料优先调用规则",
        content="用户要求先看资料、分析资料库或参考资料时，计划里应把 review_knowledge 放在生成、续写或改稿动作之前。",
        rationale="本次任务已经验证资料分析适合作为前置步骤。",
        confidence=0.76,
        project_id=payload.project_id,
        task_id=result.task_id,
        thread_id=payload.thread_id,
        metadata={"actions": actions},
      )
    )
  if "generate_architecture" in actions and any(action in actions for action in ("chapter_generate", "rewrite_chapter", "continue_project")):
    candidates.append(
      _candidate(
        kind="capability",
        title="架构依赖调用规则",
        content="续写、改稿或后续规划前，如果整书架构不完整，应先生成或补齐架构，再处理章节内容。",
        rationale="本次计划已经把架构补齐作为内容写作前置步骤。",
        confidence=0.74,
        project_id=payload.project_id,
        task_id=result.task_id,
        thread_id=payload.thread_id,
        metadata={"actions": actions},
      )
    )
  if skill_ids and actions:
    candidates.append(
      _candidate(
        kind="capability",
        title="技能匹配调用规则",
        content=f"同类任务再次出现时，可优先检查并启用用户技能：{', '.join(skill_ids[:3])}。",
        rationale="本次执行已经启用了用户沉淀技能，后续可以复用匹配信号。",
        confidence=0.73,
        project_id=payload.project_id,
        task_id=result.task_id,
        thread_id=payload.thread_id,
        metadata={"skill_ids": skill_ids, "actions": actions, "latest_user": _compact_text(latest_user, 160)},
      )
    )
  return candidates


def _writing_evaluation(
  payload: AgentChatRequest,
  plan: AgentPlan,
  result: AgentChatResult,
  skill_ids: list[str],
) -> dict[str, object]:
  actions = _action_kinds(plan)
  artifact_kinds = [artifact.kind for artifact in result.artifacts]
  failure_count = len(_failed_traces(result))
  chapter_write_count = sum(1 for action in plan.actions if action.kind == "chapter_generate" or action.kind == "chapter_workflow" and action.mode == "draft")
  rewrite_count = actions.count("rewrite_chapter")
  consistency_count = actions.count("consistency_check")
  issue_count = 0
  for artifact in result.artifacts:
    if artifact.kind == "consistency_report":
      try:
        issue_count += int(artifact.metadata.get("issue_count") or 0)
      except (TypeError, ValueError):
        pass

  score = 0.5
  if result.changes:
    score += 0.12
  if failure_count == 0:
    score += 0.12
  if "knowledge_summary" in artifact_kinds:
    score += 0.08
  if skill_ids:
    score += 0.08
  if chapter_write_count or rewrite_count:
    score += 0.08
  if consistency_count:
    score += 0.04
  if failure_count:
    score -= 0.18
  score = max(0.0, min(score, 0.96))
  reply_text = result.reply or ""
  latest_user = _latest_user_text(payload)
  quality_dimensions = {
    "character_consistency": round(min(0.96, 0.48 + (0.16 if consistency_count else 0) + (0.16 if "character_state" in " ".join(str(change) for change in result.changes) else 0) + (0.12 if failure_count == 0 else -0.08)), 3),
    "conflict_progress": round(min(0.96, 0.45 + (0.16 if chapter_write_count or rewrite_count else 0) + (0.12 if any(token in reply_text + latest_user for token in ("冲突", "追", "逼近", "推进")) else 0)), 3),
    "information_release": round(min(0.96, 0.46 + (0.14 if "knowledge_summary" in artifact_kinds else 0) + (0.12 if any(token in reply_text + latest_user for token in ("线索", "信息", "揭露", "伏笔")) else 0)), 3),
    "dialogue_naturalness": round(min(0.96, 0.52 + (0.14 if rewrite_count else 0) + (0.08 if any(token in reply_text for token in ("对白", "语气", "人物")) else 0)), 3),
    "style_stability": round(min(0.96, 0.5 + (0.12 if skill_ids else 0) + (0.1 if "style" in " ".join(str(change) for change in result.changes).lower() else 0) + (0.08 if failure_count == 0 else -0.06)), 3),
  }

  return {
    "id": f"writing-eval-{_candidate_id(payload.project_id, result.task_id, _now_iso())}",
    "project_id": payload.project_id,
    "thread_id": payload.thread_id,
    "task_id": result.task_id,
    "generated_at": _now_iso(),
    "latest_user_message": _compact_text(_latest_user_text(payload), 320),
    "actions": actions,
    "task_pack_kind": _task_pack_kind(plan, result),
    "skill_ids": skill_ids,
    "chapter_write_count": chapter_write_count,
    "rewrite_count": rewrite_count,
    "consistency_check_count": consistency_count,
    "consistency_issue_count": issue_count,
    "knowledge_used": "knowledge_summary" in artifact_kinds,
    "project_change_count": len(result.changes),
    "failure_count": failure_count,
    "score": round(score, 3),
    "quality_dimensions": quality_dimensions,
  }


def _append_review(project_dir: Path, review: dict[str, object]) -> None:
  _append_jsonl(_review_log_path(project_dir), review)


def _append_writing_evaluation(project_dir: Path, evaluation: dict[str, object]) -> None:
  _append_jsonl(_writing_evaluation_path(project_dir), evaluation)


def _append_failure_cases(
  project_dir: Path,
  *,
  payload: AgentChatRequest,
  plan: AgentPlan,
  result: AgentChatResult,
) -> list[dict[str, object]]:
  failures = _failed_traces(result)
  cases: list[dict[str, object]] = []
  if not failures:
    return cases
  actions = _action_kinds(plan)
  latest_user = _latest_user_text(payload)
  for trace in failures:
    action_kind = str(getattr(trace, "action_kind", "") or "")
    summary = str(getattr(trace, "summary", "") or "")
    case = {
      "id": f"failure-{_candidate_id(action_kind, result.task_id, summary or latest_user)}",
      "project_id": payload.project_id,
      "thread_id": payload.thread_id,
      "task_id": result.task_id,
      "created_at": _now_iso(),
      "action_kind": action_kind,
      "label": str(getattr(trace, "label", "") or ""),
      "summary": _compact_text(summary or result.reply, 500),
      "latest_user_message": _compact_text(latest_user, 320),
      "plan_actions": actions,
      "prevention": _compact_text(
        f"下次执行 {action_kind or '同类动作'} 前，先检查项目状态、章节选择、输入材料和上一步输出是否齐备。",
        260,
      ),
    }
    cases.append(case)
    _append_jsonl(_failure_case_path(project_dir), case)
  return cases


def _failure_case_context(project_dir: Path, limit: int = 4) -> str:
  cases = _latest_jsonl_items(_failure_case_path(project_dir), limit)
  if not cases:
    return ""
  lines = ["Agent 失败案例提醒："]
  for item in cases[:limit]:
    action = _compact_text(str(item.get("action_kind") or "同类任务"), 40)
    prevention = _compact_text(str(item.get("prevention") or item.get("summary") or ""), 180)
    if prevention:
      lines.append(f"- {action}：{prevention}")
  return "\n".join(lines).strip()


def _score_status(score: float) -> str:
  if score >= 0.78:
    return "good"
  if score >= 0.58:
    return "watch"
  return "risk"


def _project_documents(project_dir: Path) -> dict[str, str]:
  docs: dict[str, str] = {}
  for filename in (
    "core_seed.txt",
    "character_design.txt",
    "character_state.txt",
    "world_building.txt",
    "plot_structure.txt",
    "blueprint.txt",
    "global_summary.txt",
  ):
    path = project_dir / filename
    if path.exists():
      docs[filename] = path.read_text(encoding="utf-8").strip()
  return docs


def _selected_regression_chapter(project_dir: Path) -> dict[str, object]:
  for path in sorted((project_dir / "chapters").glob("*.md")):
    content = path.read_text(encoding="utf-8").strip()
    if content:
      match = re.search(r"(\d+)", path.stem)
      index = int(match.group(1)) if match else 1
      first_line = next((line.strip("# ").strip() for line in content.splitlines() if line.strip()), "")
      return {
        "id": f"chapter-{index:03d}",
        "index": index,
        "title": first_line[:80] or f"第 {index} 章",
        "content": content,
        "path": path.as_posix(),
      }
  return {
    "id": "chapter-001",
    "index": 1,
    "title": "第 1 章",
    "content": "",
    "path": "",
  }


def _case_score(case_id: str, chapter_content: str, docs: dict[str, str], state: dict[str, object]) -> tuple[float, list[str], list[str]]:
  rules = state.get("capability_rules", {}).get("rules", []) if isinstance(state.get("capability_rules"), dict) else []
  candidates = state.get("candidates", {}).get("items", []) if isinstance(state.get("candidates"), dict) else []
  has_chapter = bool(chapter_content.strip())
  has_blueprint = bool(docs.get("blueprint.txt", "").strip())
  has_summary = bool(docs.get("global_summary.txt", "").strip())
  has_character_state = bool(docs.get("character_state.txt", "").strip())
  has_materials = (project_dir := Path(str(state.get("_project_dir", "")))) and (
    (project_dir / "knowledge.db").exists() or any((project_dir / "references").rglob("*")) if project_dir.exists() else False
  )
  has_rules = bool(rules)
  has_skill_candidates = any(isinstance(item, dict) and item.get("kind") == "skill" for item in candidates)
  checks: list[str] = []
  suggestions: list[str] = []

  if case_id == "continuation":
    score = 0.35
    if has_chapter:
      score += 0.22
      checks.append("样本章有正文，可重复评估续写输入。")
    else:
      suggestions.append("补一段样本章正文后，续写回归才有稳定输入。")
    if has_blueprint:
      score += 0.18
      checks.append("章节蓝图存在。")
    else:
      suggestions.append("补齐章节蓝图，提高续写目标稳定性。")
    if has_summary:
      score += 0.12
      checks.append("滚动摘要存在。")
    if has_rules:
      score += 0.1
      checks.append("已有自学习调用规则。")
    return min(score, 0.96), checks, suggestions

  if case_id == "rewrite":
    score = 0.38
    if len(chapter_content) >= 240:
      score += 0.22
      checks.append("样本章长度足够做改稿对照。")
    else:
      suggestions.append("样本章太短，改稿回归容易失真。")
    if has_character_state:
      score += 0.16
      checks.append("人物状态存在。")
    if has_skill_candidates:
      score += 0.1
      checks.append("已有技能候选可参与改稿规则沉淀。")
    if "rewrite_chapter" in " ".join(str(rule.get("metadata", "")) for rule in rules if isinstance(rule, dict)):
      score += 0.08
    return min(score, 0.96), checks, suggestions

  if case_id == "humanize":
    score = 0.42
    punctuation_count = len(re.findall(r"[，。！？；：]", chapter_content))
    sentence_count = max(1, punctuation_count)
    average_sentence = len(chapter_content) / sentence_count if chapter_content else 0
    if has_chapter:
      score += 0.16
      checks.append("样本章可用于去 AI 质量检查。")
    if 18 <= average_sentence <= 70:
      score += 0.16
      checks.append("句长分布处在可读范围。")
    else:
      suggestions.append("样本章句长分布偏离常规范围，后续需要人工检查节奏。")
    if any(token in chapter_content for token in ("忽然", "只见", "仿佛", "不由得")):
      suggestions.append("样本章包含高频模板词，适合继续强化去 AI 技能。")
    else:
      score += 0.08
    return min(score, 0.96), checks, suggestions

  score = 0.34
  if has_materials:
    score += 0.24
    checks.append("项目已有资料或知识库文件。")
  else:
    suggestions.append("导入资料后，资料调用回归才能评估检索链路。")
  if has_blueprint:
    score += 0.14
  if any(isinstance(rule, dict) and "资料" in str(rule.get("content") or "") for rule in rules):
    score += 0.18
    checks.append("已有资料优先调用规则。")
  if has_chapter:
    score += 0.08
  return min(score, 0.96), checks, suggestions


def run_writing_regression_suite(settings: Settings, project_dir: Path) -> dict[str, object]:
  resolved_project_dir = Path(project_dir).expanduser().resolve()
  state = get_self_evolution_state(settings, resolved_project_dir)
  state["_project_dir"] = str(resolved_project_dir)
  chapter = _selected_regression_chapter(resolved_project_dir)
  chapter_content = str(chapter.get("content") or "")
  docs = _project_documents(resolved_project_dir)
  cases = []
  for case_id, label in _REGRESSION_CASES:
    score, checks, suggestions = _case_score(case_id, chapter_content, docs, state)
    cases.append(
      {
        "id": case_id,
        "label": label,
        "score": round(score, 3),
        "status": _score_status(score),
        "checks": checks,
        "suggestions": suggestions,
      }
    )
  average_score = round(sum(float(item["score"]) for item in cases) / len(cases), 3)
  run = {
    "id": f"writing-regression-{_candidate_id(str(chapter.get('id') or ''), _now_iso(), chapter_content[:120])}",
    "generated_at": _now_iso(),
    "chapter_id": chapter.get("id", ""),
    "chapter_title": chapter.get("title", ""),
    "chapter_path": chapter.get("path", ""),
    "chapter_signature": hashlib.sha1(chapter_content.encode("utf-8")).hexdigest()[:12],
    "average_score": average_score,
    "status": _score_status(average_score),
    "cases": cases,
  }
  _append_jsonl(_writing_regression_path(resolved_project_dir), run)
  return run


def _heuristic_model_review(
  *,
  evaluations: list[dict[str, object]],
  regression_runs: list[dict[str, object]],
  candidates: list[dict[str, object]],
  status: str,
  error: str = "",
) -> dict[str, object]:
  latest_evaluation = evaluations[0] if evaluations else {}
  latest_regression = regression_runs[0] if regression_runs else {}
  failure_causes: list[str] = []
  suggestions: list[str] = []
  if int(latest_evaluation.get("failure_count") or 0) > 0:
    failure_causes.append("最近任务包含失败步骤，需要检查输入条件、章节选择和工具调用顺序。")
  if latest_regression and float(latest_regression.get("average_score") or 0) < 0.7:
    failure_causes.append("写作回归评分偏低，样本章、蓝图、资料链路至少有一项不足。")
  if not failure_causes:
    failure_causes.append("最近没有明显失败信号，主要继续观察调用规则是否稳定复用。")
  if any(item.get("kind") == "skill" and item.get("status") == "pending" for item in candidates):
    suggestions.append("处理待确认技能候选，把重复出现的流程转成用户技能。")
  if any(item.get("kind") == "memory" and item.get("status") == "pending" for item in candidates):
    suggestions.append("处理项目记忆候选，避免长期偏好只停留在任务记录里。")
  suggestions.append("定期运行写作回归，观察同一样本章在续写、改稿、去 AI、资料调用四类任务中的变化。")
  return {
    "id": f"model-review-{_now_iso()}",
    "generated_at": _now_iso(),
    "status": status,
    "summary": "已完成自学习审查。",
    "failure_causes": failure_causes[:5],
    "improvement_suggestions": _ordered_unique(suggestions)[:6],
    "skill_actions": ["优先处理高频待确认技能候选。"] if candidates else [],
    "capability_actions": ["保留高可信调用规则，并观察后续规划是否复用。"],
    "risk_notes": [error] if error else [],
  }


def _invoke_optional_reviewer_model(settings: Settings, messages: list[dict[str, object]]) -> str:
  review_config = load_config(settings).review_model
  api_key = os.environ.get("NOVEL_REVIEW_MODEL_API_KEY", "").strip()
  base_url = os.environ.get("NOVEL_REVIEW_MODEL_BASE_URL", "").strip()
  model_name = os.environ.get("NOVEL_REVIEW_MODEL_NAME", "").strip()
  max_tokens = int(os.environ.get("NOVEL_REVIEW_MODEL_MAX_TOKENS", "") or review_config.max_tokens)
  temperature = float(os.environ.get("NOVEL_REVIEW_MODEL_TEMPERATURE", "") or review_config.temperature)
  if not api_key and bool(review_config.enabled):
    api_key = review_config.api_key.strip()
  if not base_url and bool(review_config.enabled):
    base_url = review_config.base_url.strip()
  if not model_name and bool(review_config.enabled):
    model_name = review_config.model_name.strip()
  if not api_key or not base_url or not model_name:
    return ""
  endpoint = _chat_completions_endpoint(base_url)
  try:
    with model_runtime_slot(settings, lane="chat", task_name="self_evolution_model_review:cross"):
      response_payload = _request_chat_completion(
        endpoint,
        api_key,
        {
          "model": model_name,
          "messages": messages,
          "temperature": temperature,
          "max_tokens": max_tokens,
        },
      )
  except Exception as error:
    mark_model_runtime_cooldown(settings, "chat", str(error))
    raise
  return _extract_message_content(response_payload)


def _merge_cross_review(base_review: dict[str, object], cross_content: str) -> dict[str, object]:
  if not cross_content.strip():
    base_review["cross_review"] = {
      "enabled": False,
      "status": "not_configured",
      "reviewer_count": 1,
      "summary": "未配置第二审查模型，已使用当前模型或本地规则审查。",
    }
    return base_review
  try:
    parsed = _extract_json_object(cross_content)
  except Exception:
    parsed = {}
  if not isinstance(parsed, dict):
    parsed = {}
  base_review["cross_review"] = {
    "enabled": True,
    "status": "completed",
    "reviewer_count": 2,
    "summary": str(parsed.get("summary") or "第二审查模型已完成复核。").strip(),
    "failure_causes": _string_list_from_keys(parsed, "failure_causes", "causes")[:6],
    "improvement_suggestions": _string_list_from_keys(parsed, "improvement_suggestions", "suggestions")[:8],
    "risk_notes": _string_list_from_keys(parsed, "risk_notes", "risks")[:6],
  }
  return base_review


def run_self_evolution_model_review(settings: Settings, project_dir: Path) -> dict[str, object]:
  resolved_project_dir = Path(project_dir).expanduser().resolve()
  state = get_self_evolution_state(settings, resolved_project_dir)
  candidates = state.get("candidates", {}).get("items", []) if isinstance(state.get("candidates"), dict) else []
  evaluations = state.get("writing_evaluations", []) if isinstance(state.get("writing_evaluations"), list) else []
  regression_runs = state.get("writing_regression_runs", []) if isinstance(state.get("writing_regression_runs"), list) else []
  prompt_payload = {
    "candidates": candidates[:12],
    "capability_rules": state.get("capability_rules", {}).get("rules", [])[:8] if isinstance(state.get("capability_rules"), dict) else [],
    "writing_evaluations": evaluations[:8],
    "writing_regression_runs": regression_runs[:4],
    "skill_usage": state.get("skill_usage", {}),
  }
  review_messages = [
    {
      "role": "system",
      "content": (
        "你是小说写作 Agent 的自学习审查员。只输出 JSON 对象，字段为 summary、"
        "failure_causes、improvement_suggestions、skill_actions、capability_actions、risk_notes。"
      ),
    },
    {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False)},
  ]
  try:
    content = _invoke_model(
      settings,
      review_messages,
      task_name="self_evolution_model_review",
      temperature=0.2,
      max_tokens=1800,
    )
    parsed = _extract_json_object(content)
    if not isinstance(parsed, dict):
      raise ValueError("模型审查结果不是 JSON 对象")
    review = {
      "id": f"model-review-{_candidate_id('model-review', _now_iso(), content)}",
      "generated_at": _now_iso(),
      "status": "model",
      "summary": str(parsed.get("summary") or parsed.get("reply") or "模型审查完成。").strip(),
      "failure_causes": _string_list_from_keys(parsed, "failure_causes", "causes")[:6],
      "improvement_suggestions": _string_list_from_keys(parsed, "improvement_suggestions", "suggestions")[:8],
      "skill_actions": _string_list_from_keys(parsed, "skill_actions", "skills")[:6],
      "capability_actions": _string_list_from_keys(parsed, "capability_actions", "capabilities")[:6],
      "risk_notes": _string_list_from_keys(parsed, "risk_notes", "risks")[:6],
    }
    if not review["failure_causes"] and not review["improvement_suggestions"]:
      review = _heuristic_model_review(
        evaluations=evaluations,
        regression_runs=regression_runs,
        candidates=candidates,
        status="model_incomplete",
      )
  except Exception as error:
    review = _heuristic_model_review(
      evaluations=evaluations,
      regression_runs=regression_runs,
      candidates=candidates,
      status="model_failed",
      error=str(error),
    )
  try:
    cross_content = _invoke_optional_reviewer_model(settings, review_messages)
    review = _merge_cross_review(review, cross_content)
  except Exception as error:
    review["cross_review"] = {
      "enabled": True,
      "status": "failed",
      "reviewer_count": 1,
      "summary": str(error),
    }
  _append_jsonl(_model_review_path(resolved_project_dir), review)
  return review


def run_self_evolution_scheduled_tasks(settings: Settings, project_dir: Path, *, force: bool = False) -> dict[str, object]:
  resolved_project_dir = Path(project_dir).expanduser().resolve()
  schedule = _load_schedule(resolved_project_dir)
  if not bool(schedule.get("enabled")) and not force:
    return {
      "status": "disabled",
      "ran": [],
      "schedule": schedule,
    }
  if not force:
    last_run_at = _parse_datetime(schedule.get("last_run_at"))
    try:
      interval_hours = max(1, min(int(schedule.get("interval_hours") or 168), 24 * 90))
    except (TypeError, ValueError):
      interval_hours = 168
    if last_run_at is not None and datetime.now(timezone.utc) - last_run_at < timedelta(hours=interval_hours):
      return {
        "status": "waiting",
        "ran": [],
        "schedule": schedule,
      }

  ran: list[dict[str, object]] = []
  for task in schedule.get("tasks") or []:
    if task == "curate":
      ran.append({"task": task, "result": run_skill_curator(settings)})
    elif task == "regression":
      ran.append({"task": task, "result": run_writing_regression_suite(settings, resolved_project_dir)})
    elif task == "model_review":
      ran.append({"task": task, "result": run_self_evolution_model_review(settings, resolved_project_dir)})
  schedule["last_run_at"] = _now_iso()
  schedule["updated_at"] = _now_iso()
  atomic_write_json(_schedule_path(resolved_project_dir), schedule)
  return {
    "status": "completed",
    "ran": ran,
    "schedule": schedule,
  }


def _self_evolution_dashboard(
  *,
  candidates: dict[str, object],
  capability_rules: dict[str, object],
  evaluations: list[dict[str, object]],
  skill_usage: dict[str, object],
  drafts: dict[str, object],
  regression_runs: list[dict[str, object]],
  model_reviews: list[dict[str, object]],
  failure_cases: list[dict[str, object]],
) -> dict[str, object]:
  candidate_items = candidates.get("items") if isinstance(candidates.get("items"), list) else []
  rule_items = capability_rules.get("rules") if isinstance(capability_rules.get("rules"), list) else []
  draft_items = drafts.get("items") if isinstance(drafts.get("items"), list) else []
  usage_records = skill_usage.get("records") if isinstance(skill_usage.get("records"), list) else []
  candidate_status_counts: dict[str, int] = {}
  candidate_kind_counts: dict[str, int] = {}
  for item in candidate_items:
    if not isinstance(item, dict):
      continue
    status = str(item.get("status") or "pending")
    kind = str(item.get("kind") or "memory")
    candidate_status_counts[status] = candidate_status_counts.get(status, 0) + 1
    candidate_kind_counts[kind] = candidate_kind_counts.get(kind, 0) + 1
  skill_state_counts: dict[str, int] = {}
  for item in usage_records:
    if isinstance(item, dict):
      state = str(item.get("state") or "active")
      skill_state_counts[state] = skill_state_counts.get(state, 0) + 1
  scores = [float(item.get("score") or 0) for item in evaluations if isinstance(item, dict)]
  quality_trends: dict[str, list[dict[str, object]]] = {}
  for item in evaluations[:20]:
    if not isinstance(item, dict) or not isinstance(item.get("quality_dimensions"), dict):
      continue
    for key, value in item["quality_dimensions"].items():
      quality_trends.setdefault(key, []).append(
        {
          "generated_at": item.get("generated_at", ""),
          "score": round(float(value or 0), 3),
        }
      )
  latest_score = scores[0] if scores else 0.0
  previous_score = scores[1] if len(scores) > 1 else latest_score
  latest_regression = regression_runs[0] if regression_runs else {}
  previous_regression = regression_runs[1] if len(regression_runs) > 1 else latest_regression
  regression_delta = float(latest_regression.get("average_score") or 0) - float(previous_regression.get("average_score") or 0)
  failing_actions: dict[str, int] = {}
  for item in evaluations:
    if not isinstance(item, dict) or int(item.get("failure_count") or 0) <= 0:
      continue
    for action in item.get("actions") or []:
      action_key = str(action)
      failing_actions[action_key] = failing_actions.get(action_key, 0) + 1
  failure_groups_by_action: dict[str, dict[str, object]] = {}
  for item in failure_cases:
    if not isinstance(item, dict):
      continue
    action = str(item.get("action_kind") or item.get("label") or "unknown")
    group = failure_groups_by_action.setdefault(
      action,
      {
        "action_kind": action,
        "count": 0,
        "latest_at": "",
        "latest_summary": "",
        "prevention": "",
        "status": "single",
      },
    )
    group["count"] = int(group.get("count") or 0) + 1
    created_at = str(item.get("created_at") or "")
    if not str(group.get("latest_at") or "") or created_at > str(group.get("latest_at") or ""):
      group["latest_at"] = created_at
      group["latest_summary"] = item.get("summary", "")
      group["prevention"] = item.get("prevention", "")
    if int(group.get("count") or 0) >= 2:
      group["status"] = "repeated"
  return {
    "generated_at": _now_iso(),
    "candidate_status_counts": candidate_status_counts,
    "candidate_kind_counts": candidate_kind_counts,
    "skill_state_counts": skill_state_counts,
    "pending_draft_count": sum(1 for item in draft_items if isinstance(item, dict) and item.get("status") == "pending"),
    "accepted_candidate_count": candidate_status_counts.get("accepted", 0),
    "capability_rule_count": len(rule_items),
    "latest_writing_score": round(latest_score, 3),
    "writing_score_delta": round(latest_score - previous_score, 3),
    "latest_regression_score": round(float(latest_regression.get("average_score") or 0), 3),
    "regression_score_delta": round(regression_delta, 3),
    "recent_failure_count": sum(int(item.get("failure_count") or 0) for item in evaluations[:10] if isinstance(item, dict)),
    "failing_actions": sorted(
      [{"action": action, "count": count} for action, count in failing_actions.items()],
      key=lambda item: item["count"],
      reverse=True,
    )[:6],
    "latest_model_review": model_reviews[0] if model_reviews else None,
    "quality_dimensions": evaluations[0].get("quality_dimensions", {}) if evaluations and isinstance(evaluations[0], dict) else {},
    "trends": {
      "writing_scores": [
        {
          "generated_at": item.get("generated_at", ""),
          "score": round(float(item.get("score") or 0), 3),
        }
        for item in evaluations[:20]
        if isinstance(item, dict)
      ],
      "regression_scores": [
        {
          "generated_at": item.get("generated_at", ""),
          "score": round(float(item.get("average_score") or 0), 3),
        }
        for item in regression_runs[:20]
        if isinstance(item, dict)
      ],
      "quality_dimensions": quality_trends,
    },
    "failure_case_count": len(failure_cases),
    "latest_failure_cases": failure_cases[:8],
    "failure_case_groups": sorted(
      failure_groups_by_action.values(),
      key=lambda item: (int(item.get("count") or 0), str(item.get("latest_at") or "")),
      reverse=True,
    )[:8],
  }


def get_self_evolution_state(settings: Settings, project_dir: Path) -> dict[str, object]:
  candidates = _load_candidates(project_dir)
  capability_rules = _load_capability_rules(project_dir)
  drafts = _load_drafts(project_dir)
  evaluations = _latest_jsonl_items(_writing_evaluation_path(project_dir), 20)
  model_reviews = _latest_jsonl_items(_model_review_path(project_dir), 10)
  regression_runs = _latest_jsonl_items(_writing_regression_path(project_dir), 10)
  failure_cases = _latest_jsonl_items(_failure_case_path(project_dir), 20)
  schedule = _load_schedule(project_dir)
  skill_usage = get_skill_usage_state(settings)
  return {
    "candidates": candidates,
    "capability_rules": capability_rules,
    "drafts": drafts,
    "writing_evaluations": evaluations,
    "writing_regression_runs": regression_runs,
    "model_reviews": model_reviews,
    "failure_cases": failure_cases,
    "schedule": schedule,
    "skill_usage": skill_usage,
    "dashboard": _self_evolution_dashboard(
      candidates=candidates,
      capability_rules=capability_rules,
      evaluations=evaluations,
      skill_usage=skill_usage,
      drafts=drafts,
      regression_runs=regression_runs,
      model_reviews=model_reviews,
      failure_cases=failure_cases,
    ),
  }


def update_self_evolution_candidate_status(project_dir: Path, candidate_id: str, status: str) -> dict[str, object]:
  normalized_status = str(status or "").strip()
  if normalized_status not in _CANDIDATE_STATUS_VALUES:
    raise ValueError("候选状态无效")
  store = _load_candidates(project_dir)
  items = store.get("items")
  if not isinstance(items, list):
    items = []
  matched = None
  for item in items:
    if not isinstance(item, dict):
      continue
    if str(item.get("id") or "") == candidate_id:
      item["status"] = normalized_status
      item["updated_at"] = _now_iso()
      if normalized_status == "accepted":
        draft = _ensure_candidate_draft(project_dir, item)
        item["draft_id"] = draft.get("id", "")
      matched = item
      break
  if matched is None:
    raise FileNotFoundError("候选不存在")
  store["items"] = items
  store["updated_at"] = _now_iso()
  atomic_write_json(_candidate_path(project_dir), store)
  return matched


def update_self_evolution_draft_status(project_dir: Path, draft_id: str, status: str) -> dict[str, object]:
  normalized_status = str(status or "").strip()
  if normalized_status not in _DRAFT_STATUS_VALUES:
    raise ValueError("草案状态无效")
  store = _load_drafts(project_dir)
  items = store.get("items")
  if not isinstance(items, list):
    items = []
  matched = None
  for item in items:
    if not isinstance(item, dict):
      continue
    if str(item.get("id") or "") == draft_id:
      item["status"] = normalized_status
      item["updated_at"] = _now_iso()
      matched = item
      break
  if matched is None:
    raise FileNotFoundError("草案不存在")
  store["items"] = items
  _save_drafts(project_dir, store)
  return matched


def apply_self_evolution_draft(settings: Settings, project_dir: Path, draft_id: str) -> dict[str, object]:
  store = _load_drafts(project_dir)
  items = store.get("items")
  if not isinstance(items, list):
    items = []
  matched = None
  for item in items:
    if isinstance(item, dict) and str(item.get("id") or "") == draft_id:
      matched = item
      break
  if matched is None:
    raise FileNotFoundError("草案不存在")
  if str(matched.get("status") or "") == "applied":
    return matched
  if str(matched.get("status") or "") == "discarded":
    raise ValueError("草案已废弃，不能应用")

  payload = matched.get("payload") if isinstance(matched.get("payload"), dict) else {}
  kind = str(matched.get("kind") or "")
  result: dict[str, object]
  if kind == "memory":
    entries = []
    for raw_entry in payload.get("entries") or []:
      if not isinstance(raw_entry, dict):
        continue
      entries.append(
        ProjectMemoryEntryInput(
          title=str(raw_entry.get("title") or "").strip()[:80],
          category=str(raw_entry.get("category") or "连续性"),
          content=str(raw_entry.get("content") or "").strip(),
        )
      )
    if not entries:
      raise ValueError("项目记忆草案缺少内容")
    updated_entries = append_project_memory(project_dir, entries)
    result = {
      "type": "memory",
      "entry_count": len(entries),
      "total_memory_count": len(updated_entries),
    }
  elif kind == "skill":
    raw_messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
    messages = [
      BrainstormMessage(role=str(item.get("role") or "user"), content=str(item.get("content") or ""))
      for item in raw_messages
      if isinstance(item, dict) and str(item.get("content") or "").strip()
    ]
    if not messages:
      raise ValueError("技能草案缺少对话内容")
    skill_result = materialize_skill(
      settings,
      SkillMaterializeRequest(
        project_id=str(payload.get("project_id") or matched.get("project_id") or ""),
        messages=messages,
        action=str(payload.get("action") or "create"),
        skill_id=str(payload.get("target_skill_id") or ""),
        skill_name=str(payload.get("skill_name") or matched.get("title") or ""),
      ),
    )
    result = {
      "type": "skill",
      "action": skill_result.action,
      "skill_id": skill_result.skill.id,
      "skill_name": skill_result.skill.name,
      "saved_path": skill_result.saved_path,
    }
  elif kind == "capability":
    rule_payload = payload.get("rule") if isinstance(payload.get("rule"), dict) else {}
    if not str(rule_payload.get("content") or "").strip():
      raise ValueError("调用规则草案缺少内容")
    rule = _upsert_accepted_capability_rule(project_dir, rule_payload)
    result = {
      "type": "capability",
      "rule_id": rule.get("id", ""),
      "title": rule.get("title", ""),
    }
  else:
    raise ValueError("草案类型无效")

  matched["status"] = "applied"
  matched["applied_at"] = _now_iso()
  matched["updated_at"] = _now_iso()
  matched["result"] = result
  store["items"] = items
  _save_drafts(project_dir, store)
  return matched


def _review_artifact(
  *,
  review: dict[str, object],
  candidate_merge: dict[str, object],
  capability_apply: dict[str, object],
  skill_usage: dict[str, object],
  curator_report: dict[str, object],
  evaluation: dict[str, object],
) -> AgentArtifact:
  candidate_count = int(candidate_merge.get("inserted") or 0) + int(candidate_merge.get("refreshed") or 0)
  rule_count = int(capability_apply.get("applied") or 0) + int(capability_apply.get("refreshed") or 0)
  usage_count = int(skill_usage.get("updated") or 0)
  summary = (
    f"复盘完成：候选 {candidate_count} 条，调用规则 {rule_count} 条，"
    f"技能统计 {usage_count} 项，写作评分 {evaluation.get('score')}。"
  )
  preview_lines = []
  for item in review.get("candidates", [])[:4]:
    if isinstance(item, dict):
      preview_lines.append(f"{item.get('kind')}｜{item.get('title')}：{item.get('content')}")
  if not preview_lines:
    preview_lines.append("本次没有新的候选，但已刷新技能统计和写作评价。")
  return AgentArtifact(
    kind="self_evolution_review",
    title="自学习复盘",
    summary=summary,
    content_preview="\n".join(preview_lines),
    metadata={
      "review_id": review.get("id", ""),
      "candidate_count": candidate_count,
      "new_candidate_count": candidate_merge.get("inserted", 0),
      "capability_rule_count": rule_count,
      "skill_usage_count": usage_count,
      "curator_change_count": curator_report.get("change_count", 0),
      "writing_score": evaluation.get("score", 0),
      "candidate_path": str(_candidate_path(Path(str(review.get("project_dir", ""))))),
      "rules_path": str(_capability_rules_path(Path(str(review.get("project_dir", ""))))),
    },
  )


def run_self_evolution_cycle(
  settings: Settings,
  project_dir: Path,
  *,
  payload: AgentChatRequest,
  plan: AgentPlan,
  result: AgentChatResult,
) -> AgentArtifact:
  try:
    resolved_project_dir = Path(project_dir).expanduser().resolve()
    resolved_skill_ids = _skill_ids(payload, plan)
    status = "failed" if _failed_traces(result) else "completed"
    skill_usage = record_skill_usage(
      settings,
      resolved_skill_ids,
      project_id=payload.project_id,
      task_id=result.task_id,
      action_kinds=_action_kinds(plan),
      task_pack_kind=_task_pack_kind(plan, result),
      status=status,
    )
    candidates = [
      *_build_memory_candidates(payload, result),
      *_build_skill_candidates(payload, plan, result, resolved_skill_ids),
      *_build_capability_candidates(payload, plan, result, resolved_skill_ids),
    ]
    candidate_merge = _merge_candidates(resolved_project_dir, candidates)
    capability_apply = _apply_capability_rules(resolved_project_dir, candidates)
    evaluation = _writing_evaluation(payload, plan, result, resolved_skill_ids)
    _append_writing_evaluation(resolved_project_dir, evaluation)
    failure_cases = _append_failure_cases(
      resolved_project_dir,
      payload=payload,
      plan=plan,
      result=result,
    )
    curator_report = run_skill_curator(settings)
    review = {
      "id": f"self-evolution-{_candidate_id(payload.project_id, result.task_id, _now_iso())}",
      "project_id": payload.project_id,
      "project_dir": str(resolved_project_dir),
      "thread_id": payload.thread_id,
      "task_id": result.task_id,
      "generated_at": _now_iso(),
      "latest_user_message": _compact_text(_latest_user_text(payload), 360),
      "status": status,
      "actions": _action_kinds(plan),
      "skill_ids": resolved_skill_ids,
      "candidates": candidates,
      "candidate_merge": candidate_merge,
      "capability_apply": capability_apply,
      "skill_usage": skill_usage,
      "curator": curator_report,
      "writing_evaluation": evaluation,
      "failure_cases": failure_cases,
    }
    _append_review(resolved_project_dir, review)
    return _review_artifact(
      review=review,
      candidate_merge=candidate_merge,
      capability_apply=capability_apply,
      skill_usage=skill_usage,
      curator_report=curator_report,
      evaluation=evaluation,
    )
  except Exception as error:
    return AgentArtifact(
      kind="self_evolution_review",
      title="自学习复盘",
      summary=f"自学习复盘失败：{error}",
      content_preview=str(error),
      metadata={"status": "failed"},
    )
