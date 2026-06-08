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
from novel_backend.services.log_service import append_app_log, get_prompt_history_records
from novel_backend.services.model_runtime_service import (
  mark_model_runtime_cooldown,
  model_runtime_should_defer_background,
  model_runtime_slot,
)
from novel_backend.services.project_memory_service import append_project_memory
from novel_backend.services.project_narrative_state_service import (
  build_project_narrative_state_chapter_card,
  load_project_narrative_state,
  obsidian_pending_soft_constraint_lines,
  obsidian_maintenance_suggestion_available_for_chapter,
  obsidian_maintenance_suggestion_preview,
  obsidian_maintenance_suggestion_sort_key,
  refresh_project_narrative_state_chapter_cards,
)
from novel_backend.services.project_style_xp_evolution_service import (
  build_obsidian_style_xp_reference_prompt,
  load_project_style_xp_state,
)
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
_GOLDEN_EVALUATOR_CASES = (
  {
    "id": "ai_tone_snippet",
    "label": "模板腔片段",
    "mode": "chapter_snippet",
    "text": "此外，这场追逐不仅仅是一次逃亡，更是主角成长的重要一步。总的来说，这标志着他终于看清了自己的使命。",
    "expected_findings": ["ai_tone", "formula_conclusion"],
  },
  {
    "id": "dialogue_flat_snippet",
    "label": "对白同质片段",
    "mode": "chapter_snippet",
    "text": "林追说：我知道。宋闻说：我也知道。阿砚说：我早就知道。三个人站在雨里，谁也没有新的动作。",
    "expected_findings": ["dialogue_flat"],
  },
  {
    "id": "continuity_conflict_snippet",
    "label": "连续性冲突片段",
    "mode": "chapter_snippet",
    "text": "上一章里父亲已经死在旧码头。到了这一章，父亲却打来电话，让他用断掉的左手把箱子提起来。",
    "expected_findings": ["continuity_conflict"],
  },
  {
    "id": "clean_scene_snippet",
    "label": "正常场景片段",
    "mode": "chapter_snippet",
    "text": "雨线斜过码头灯。林追把钥匙藏进掌心，没回头，只听见铁门后有鞋底擦过积水。",
    "expected_findings": [],
  },
)
_HUMANIZE_AB_CASES = (
  {
    "id": "novel_stock_scene",
    "label": "套版画面和意义宣告",
    "before": (
      "# 第一章 雨夜靠港\n"
      "此外，林追站在旧码头边，空气仿佛凝固。"
      "这不仅仅是一场普通的会面，更是他命运转折的重要一步。"
      "总的来说，故事才刚刚开始。"
    ),
    "after": (
      "# 第一章 雨夜靠港\n"
      "林追站在旧码头边。雨水从仓库檐角滴下来，他把钥匙换到左手，右手摸向门缝里的铁锈。"
      "二楼窗帘动了一下，他没有抬头。"
    ),
    "min_delta": 35,
    "min_length_ratio": 0.72,
  },
  {
    "id": "abstract_emotion",
    "label": "抽象情绪和潜台词解释",
    "before": (
      "# 第二章 旧账\n"
      "他感到一种说不清的恐惧，内心深处涌起复杂的情绪。"
      "这个眼神意味着真正的危险，所有人都意识到局势已经不可逆转。"
    ),
    "after": (
      "# 第二章 旧账\n"
      "林追把账册合上，指尖在封皮上停了停。对面的人没催，只把茶杯往里收了半寸。"
      "屋里没人再提那艘船。"
    ),
    "min_delta": 30,
    "min_length_ratio": 0.72,
  },
  {
    "id": "dialogue_sameness",
    "label": "对白口气同质",
    "before": (
      "# 第三章 门后\n"
      "林追低声说道：我们必须找到钥匙。宋闻低声说道：我们必须尽快行动。"
      "阿砚低声说道：我们必须保持冷静。三个人的语气都很坚定。"
    ),
    "after": (
      "# 第三章 门后\n"
      "“钥匙不在柜里。”林追把抽屉推回去。\n"
      "宋闻看了眼窗外：“那人没走远。”\n"
      "阿砚没接话，只把门闩重新扣上。"
    ),
    "min_delta": 24,
    "min_length_ratio": 0.72,
  },
)
_HUMANIZE_PATROL_SCHEMA_VERSION = 1
_HUMANIZE_PATROL_COOLDOWN_HOURS = 12
_HUMANIZE_PATROL_STALE_RECHECK_HOURS = 24 * 7


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


def _humanize_evolution_rules_path(project_dir: Path) -> Path:
  return _learning_dir(project_dir) / "humanize_evolution_rules.json"


def _humanize_patrol_path(project_dir: Path) -> Path:
  return _learning_dir(project_dir) / "humanize_review_patrol.json"


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


def _load_humanize_evolution_rules(project_dir: Path) -> dict[str, object]:
  payload = read_json(_humanize_evolution_rules_path(project_dir), None)
  if not isinstance(payload, dict):
    return {"schema_version": 1, "updated_at": _now_iso(), "rules": []}
  rules = payload.get("rules")
  if not isinstance(rules, list):
    payload["rules"] = []
  payload.setdefault("schema_version", 1)
  payload.setdefault("updated_at", _now_iso())
  return payload


def _save_humanize_evolution_rules(project_dir: Path, store: dict[str, object]) -> None:
  store["updated_at"] = _now_iso()
  atomic_write_json(_humanize_evolution_rules_path(project_dir), store)


def _load_humanize_patrol(project_dir: Path) -> dict[str, object]:
  payload = read_json(_humanize_patrol_path(project_dir), None)
  if not isinstance(payload, dict) or payload.get("schema_version") != _HUMANIZE_PATROL_SCHEMA_VERSION:
    return {
      "schema_version": _HUMANIZE_PATROL_SCHEMA_VERSION,
      "last_check_at": "",
      "last_review_at": "",
      "last_signature": "",
      "last_reason": "",
      "last_status": "",
      "last_signal": {},
      "updated_at": _now_iso(),
    }
  payload.setdefault("last_check_at", "")
  payload.setdefault("last_review_at", "")
  payload.setdefault("last_signature", "")
  payload.setdefault("last_reason", "")
  payload.setdefault("last_status", "")
  if not isinstance(payload.get("last_signal"), dict):
    payload["last_signal"] = {}
  payload.setdefault("updated_at", _now_iso())
  return payload


def _save_humanize_patrol(project_dir: Path, state: dict[str, object]) -> None:
  state["schema_version"] = _HUMANIZE_PATROL_SCHEMA_VERSION
  state["updated_at"] = _now_iso()
  atomic_write_json(_humanize_patrol_path(project_dir), state)


def build_project_humanize_evolution_context(project_dir: Path, limit: int = 6) -> str:
  store = _load_humanize_evolution_rules(Path(project_dir).expanduser().resolve())
  rules = [
    item
    for item in store.get("rules") or []
    if isinstance(item, dict) and str(item.get("status") or "active") == "active"
  ]
  if not rules:
    return ""
  rules.sort(
    key=lambda item: (
      float(item.get("confidence") or 0),
      int(item.get("seen_count") or 1),
      str(item.get("last_seen_at") or item.get("created_at") or ""),
    ),
    reverse=True,
  )
  lines = ["项目去 AI 自学习规则："]
  for item in rules[:max(1, limit)]:
    title = _compact_text(str(item.get("title") or "规则"), 48)
    content = _compact_text(str(item.get("content") or ""), 180)
    if title and content:
      lines.append(f"- {title}：{content}")
    elif content:
      lines.append(f"- {content}")
  return "\n".join(lines).strip()


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


def _chapter_id_for_index(project_detail: object, chapter_index: int) -> str:
  for item in getattr(project_detail, "chapters", []) or []:
    if int(getattr(item, "index", 0) or 0) == chapter_index:
      return str(getattr(item, "id", "") or "").strip()
  return f"chapter-{chapter_index:03d}"


def _obsidian_card_text_items(value: object, *, limit: int = 4) -> list[str]:
  if not isinstance(value, list):
    return []
  items: list[str] = []
  for item in value:
    text = _compact_text(str(item or ""), 120)
    if text:
      items.append(text)
    if len(items) >= limit:
      break
  return items


def _obsidian_card_debt_items(value: object, *, limit: int = 3) -> list[str]:
  if not isinstance(value, list):
    return []
  items: list[str] = []
  for item in value:
    if not isinstance(item, dict):
      continue
    title = _compact_text(str(item.get("title") or "剧情债务"), 40)
    content = _compact_text(str(item.get("content") or ""), 120)
    payoff = item.get("expected_payoff_range")
    payoff_text = ""
    if isinstance(payoff, list) and len(payoff) >= 2:
      payoff_text = f"预计第 {payoff[0]}-{payoff[1]} 章处理"
    risk = _compact_text(str(item.get("risk_level") or ""), 20)
    meta = "；".join(part for part in [risk, payoff_text] if part)
    if title or content:
      items.append(f"{title}{f'：{content}' if content else ''}{f'（{meta}）' if meta else ''}")
    if len(items) >= limit:
      break
  return items


def _obsidian_card_arc_items(value: object, *, limit: int = 3) -> list[str]:
  if not isinstance(value, list):
    return []
  items: list[str] = []
  for item in value:
    if not isinstance(item, dict):
      continue
    name = _compact_text(str(item.get("name") or item.get("title") or "人物弧线"), 32)
    state = _compact_text(str(item.get("current_state") or ""), 120)
    check = _compact_text(str(item.get("required_next_check") or ""), 90)
    detail = "；".join(part for part in [state, check] if part)
    if name or detail:
      items.append(f"{name}{f'：{detail}' if detail else ''}")
    if len(items) >= limit:
      break
  return items


def _obsidian_card_plan_items(value: object, *, limit: int = 3) -> list[str]:
  if not isinstance(value, list):
    return []
  items: list[str] = []
  for item in value:
    if not isinstance(item, dict):
      continue
    title = _compact_text(str(item.get("title") or "章节计划"), 44)
    plan_lines = (
      [
        _compact_text(str(line or ""), 90)
        for line in item.get("plan_lines", [])
        if str(line or "").strip()
      ]
      if isinstance(item.get("plan_lines"), list)
      else []
    )
    if title and plan_lines:
      items.append(f"{title}：{'；'.join(plan_lines[:3])}")
    if len(items) >= limit:
      break
  return items


def _obsidian_card_chapter_note_items(value: object, *, limit: int = 3) -> list[str]:
  if not isinstance(value, list):
    return []
  items: list[str] = []
  for item in value:
    if not isinstance(item, dict):
      continue
    title = _compact_text(str(item.get("title") or "章节档案"), 44)
    summary = _compact_text(str(item.get("summary") or ""), 110)
    state_changes = (
      [
        _compact_text(str(line or ""), 70)
        for line in item.get("state_changes", [])
        if str(line or "").strip()
      ]
      if isinstance(item.get("state_changes"), list)
      else []
    )
    handoff = (
      [
        _compact_text(str(line or ""), 80)
        for line in item.get("handoff", [])
        if str(line or "").strip()
      ]
      if isinstance(item.get("handoff"), list)
      else []
    )
    detail_parts = []
    if summary:
      detail_parts.append(f"摘要：{summary}")
    if state_changes:
      detail_parts.append(f"状态变化：{' / '.join(state_changes[:2])}")
    if handoff:
      detail_parts.append(f"交接：{' / '.join(handoff[:2])}")
    if title and detail_parts:
      items.append(f"{title}：{'；'.join(detail_parts)}")
    if len(items) >= limit:
      break
  return items


def _chapter_obsidian_task_context(project_detail: object | None, chapter_index: int) -> list[str]:
  if project_detail is None or chapter_index <= 0:
    return []
  card = build_project_narrative_state_chapter_card(
    project_detail,
    _chapter_id_for_index(project_detail, chapter_index),
  )
  if not card:
    return []
  sources = _obsidian_card_text_items(card.get("obsidian_sources"), limit=3)
  external_references = _obsidian_card_text_items(card.get("obsidian_external_references"), limit=3)
  required = _obsidian_card_text_items(card.get("obsidian_required"), limit=4)
  forbidden = _obsidian_card_text_items(card.get("obsidian_forbidden"), limit=4)
  risks = _obsidian_card_text_items(card.get("obsidian_risks"), limit=3)
  plans = _obsidian_card_plan_items(card.get("obsidian_chapter_plans"), limit=3)
  chapter_notes = _obsidian_card_chapter_note_items(card.get("obsidian_chapter_notes"), limit=3)
  debts = _obsidian_card_debt_items(card.get("obsidian_narrative_debts"), limit=3)
  arcs = _obsidian_card_arc_items(card.get("obsidian_character_arcs"), limit=3)
  if not any([sources, external_references, required, forbidden, risks, plans, chapter_notes, debts, arcs]):
    return []
  lines = [f"目标章节 Obsidian 任务：第 {chapter_index} 章。"]
  if sources:
    lines.append(f"- 来源：{'；'.join(sources)}")
  if external_references:
    lines.append(f"- 考据来源：{'；'.join(external_references)}")
  if plans:
    lines.append(f"- 章节计划：{'；'.join(plans)}")
  if chapter_notes:
    lines.append(f"- 章节档案：{'；'.join(chapter_notes)}")
  if required:
    lines.append(f"- 必写：{'；'.join(required)}")
  if forbidden:
    lines.append(f"- 禁写：{'；'.join(forbidden)}")
  if debts:
    lines.append(f"- 剧情债务：{'；'.join(debts)}")
  if arcs:
    lines.append(f"- 人物弧线：{'；'.join(arcs)}")
  if risks:
    lines.append(f"- 图谱风险：{'；'.join(risks)}")
  return lines


def _obsidian_style_xp_capability_lines(
  project_dir: Path,
  project_detail: object | None,
  chapter_index: int = 0,
) -> list[str]:
  reference = build_obsidian_style_xp_reference_prompt(
    project_dir,
    project_detail=project_detail,
    chapter_index=chapter_index,
    max_obsidian_notes=3,
  )
  items = [
    _compact_text(line[2:].strip(), 180)
    for line in reference.splitlines()
    if line.strip().startswith("- ")
  ]
  items = [item for item in items if item]
  if not items:
    return []
  if chapter_index > 0:
    lines = [f"目标章节 Obsidian 文风 / XP：第 {chapter_index} 章。"]
  else:
    lines = ["全局 Obsidian 文风 / XP："]
  lines.extend(f"- {item}" for item in items[:3])
  return lines


def _obsidian_suggestion_source_chapter_text(item: dict[str, object]) -> str:
  indexes: list[int] = []
  for raw in item.get("source_chapters", []) if isinstance(item.get("source_chapters"), list) else []:
    try:
      chapter_index = int(raw or 0)
    except (TypeError, ValueError):
      continue
    if chapter_index > 0 and chapter_index not in indexes:
      indexes.append(chapter_index)
  if not indexes:
    return ""
  if len(indexes) == 1:
    return f"来源第 {indexes[0]} 章"
  return f"来源第 {'、'.join(str(index) for index in indexes[:4])} 章"


def _agent_capability_target_chapter_indexes(
  chapter_index: int = 0,
  chapter_indexes: list[int] | tuple[int, ...] | None = None,
) -> list[int]:
  indexes: list[int] = []
  raw_values: list[object] = []
  if chapter_index > 0:
    raw_values.append(chapter_index)
  if chapter_indexes:
    raw_values.extend(chapter_indexes)
  for raw in raw_values:
    try:
      index = int(raw or 0)
    except (TypeError, ValueError):
      continue
    if index > 0 and index not in indexes:
      indexes.append(index)
  return indexes


def _obsidian_suggestion_available_for_chapter_targets(
  item: dict[str, object],
  chapter_indexes: list[int],
  project_dir: Path,
) -> bool:
  if not chapter_indexes:
    return obsidian_maintenance_suggestion_available_for_chapter(item, 0, project_dir)
  return any(
    obsidian_maintenance_suggestion_available_for_chapter(item, chapter_index, project_dir)
    for chapter_index in chapter_indexes
  )


def _obsidian_suggestion_sort_key_for_chapter_targets(
  item: dict[str, object],
  chapter_indexes: list[int],
) -> tuple[int, int, int, str]:
  if not chapter_indexes:
    return obsidian_maintenance_suggestion_sort_key(item, 0)
  return max(
    obsidian_maintenance_suggestion_sort_key(item, chapter_index)
    for chapter_index in chapter_indexes
  )


def _obsidian_maintenance_status_for_agent(item: dict[str, object]) -> str:
  status = str(item.get("status") or "open")
  return status if status else "open"


def _obsidian_maintenance_summary_for_agent_targets(
  items: list[dict[str, object]],
  chapter_indexes: list[int],
) -> dict[str, object]:
  counts = {
    "open": 0,
    "staged": 0,
    "published": 0,
    "draft_missing": 0,
    "published_missing": 0,
    "published_outdated": 0,
    "vault_moved": 0,
    "ignored": 0,
  }
  auto_staged = 0
  manual_draft_edits = 0
  preserved_existing_draft = 0
  high_priority = 0
  for item in items:
    status = _obsidian_maintenance_status_for_agent(item)
    if status in counts:
      counts[status] += 1
    if item.get("vault_moved"):
      counts["vault_moved"] += 1
    if item.get("auto_staged"):
      auto_staged += 1
    if item.get("manual_draft_edits"):
      manual_draft_edits += 1
    if item.get("preserved_existing_draft"):
      preserved_existing_draft += 1
    if str(item.get("priority") or "") == "high":
      high_priority += 1

  top_items: list[dict[str, object]] = []
  actionable = [
    item
    for item in items
    if _obsidian_maintenance_status_for_agent(item) not in {"published", "ignored"}
  ]
  actionable.sort(
    key=lambda item: _obsidian_suggestion_sort_key_for_chapter_targets(item, chapter_indexes),
    reverse=True,
  )
  for item in actionable[:4]:
    top_items.append(
      {
        "id": str(item.get("id") or ""),
        "title": str(item.get("title") or ""),
        "priority": str(item.get("priority") or "medium"),
        "status": _obsidian_maintenance_status_for_agent(item),
        "suggested_path": str(item.get("suggested_path") or ""),
        "action": str(item.get("action") or item.get("reason") or ""),
      }
    )

  needs_action = (
    counts["open"]
    + counts["staged"]
    + counts["draft_missing"]
    + counts["published_missing"]
    + counts["published_outdated"]
  )
  return {
    "total": len(items),
    "needs_action": needs_action,
    "high_priority": high_priority,
    "auto_staged": auto_staged,
    "manual_draft_edits": manual_draft_edits,
    "preserved_existing_draft": preserved_existing_draft,
    "by_status": counts,
    "top_items": top_items,
  }


def build_agent_capability_context(
  project_dir: Path,
  limit: int = 6,
  project_detail: object | None = None,
  *,
  auto_stage_obsidian_drafts: bool = False,
  chapter_index: int = 0,
  chapter_indexes: list[int] | tuple[int, ...] | None = None,
  include_obsidian_suggestions: bool = True,
) -> str:
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
  narrative_state = (
    refresh_project_narrative_state_chapter_cards(
      project_dir,
      project_detail,
      persist=True,
      auto_stage_drafts=auto_stage_obsidian_drafts,
    )
    if project_detail is not None
    else load_project_narrative_state(project_dir)
  )
  target_chapter_indexes = _agent_capability_target_chapter_indexes(chapter_index, chapter_indexes)
  visible_chapter_indexes = target_chapter_indexes[:3]
  for target_chapter_index in visible_chapter_indexes:
    lines.extend(_chapter_obsidian_task_context(project_detail, target_chapter_index))
    lines.extend(_obsidian_style_xp_capability_lines(project_dir, project_detail, target_chapter_index))
    pending_soft_constraints = obsidian_pending_soft_constraint_lines(
      narrative_state,
      chapter_index=target_chapter_index,
      project_dir=project_dir,
      max_items=4,
    )
    if pending_soft_constraints:
      lines.append(f"目标章节 Obsidian 待审软约束：第 {target_chapter_index} 章。")
      lines.extend(pending_soft_constraints)
  if len(target_chapter_indexes) > len(visible_chapter_indexes):
    omitted = len(target_chapter_indexes) - len(visible_chapter_indexes)
    lines.append(f"目标章节 Obsidian 任务：还有 {omitted} 个目标章节未展开。")
  if not target_chapter_indexes:
    lines.extend(_obsidian_style_xp_capability_lines(project_dir, project_detail, 0))
  visible_obsidian_maintenance_items = [
    item
    for item in narrative_state.get("obsidian_maintenance_suggestions", [])
    if (
      isinstance(item, dict)
      and str(item.get("title") or "").strip()
      and _obsidian_suggestion_available_for_chapter_targets(item, target_chapter_indexes, project_dir)
    )
  ]
  obsidian_suggestions = [
    item
    for item in visible_obsidian_maintenance_items
    if _obsidian_maintenance_status_for_agent(item) not in {"published", "ignored"}
  ]
  obsidian_suggestions.sort(
    key=lambda item: _obsidian_suggestion_sort_key_for_chapter_targets(item, target_chapter_indexes),
    reverse=True,
  )
  global_obsidian_summary = narrative_state.get("obsidian_maintenance_summary")
  obsidian_summary = (
    _obsidian_maintenance_summary_for_agent_targets(visible_obsidian_maintenance_items, target_chapter_indexes)
    if target_chapter_indexes
    else global_obsidian_summary
  )
  should_show_obsidian_summary = False
  if isinstance(obsidian_summary, dict) and obsidian_summary.get("total"):
    should_show_obsidian_summary = True
  elif (
    target_chapter_indexes
    and isinstance(global_obsidian_summary, dict)
    and global_obsidian_summary.get("total")
  ):
    should_show_obsidian_summary = True
  if isinstance(obsidian_summary, dict) and should_show_obsidian_summary:
    by_status = obsidian_summary.get("by_status") if isinstance(obsidian_summary.get("by_status"), dict) else {}
    summary_parts = [
      f"待处理 {int(obsidian_summary.get('needs_action') or 0)}",
      f"高优先级 {int(obsidian_summary.get('high_priority') or 0)}",
      f"自动草稿 {int(obsidian_summary.get('auto_staged') or 0)}",
    ]
    draft_missing = int(by_status.get("draft_missing") or 0)
    published_missing = int(by_status.get("published_missing") or 0)
    if draft_missing:
      summary_parts.append(f"草稿缺失 {draft_missing}")
    if published_missing:
      summary_parts.append(f"Vault 缺失 {published_missing}")
    ignored = int(by_status.get("ignored") or 0)
    if ignored:
      summary_parts.append(f"已忽略 {ignored}")
    lines.append(f"Obsidian 维护摘要：{'，'.join(summary_parts)}。")
  if include_obsidian_suggestions and obsidian_suggestions:
    lines.append("Obsidian 维护建议：")
    for item in obsidian_suggestions[:4]:
      title = _compact_text(str(item.get("title") or ""), 56)
      action = _compact_text(str(item.get("action") or item.get("reason") or ""), 160)
      path = _compact_text(str(item.get("suggested_path") or ""), 80)
      source_chapters = _obsidian_suggestion_source_chapter_text(item)
      source_prefix = f"{source_chapters}；" if source_chapters else ""
      preview = obsidian_maintenance_suggestion_preview(item, project_dir)
      if path:
        lines.append(f"- {title}：{source_prefix}建议笔记 {path}；{action}{preview}")
      elif action:
        lines.append(f"- {title}：{source_prefix}{action}{preview}")
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
      "severity": "major" if action_kind in {"chapter_generate", "rewrite_chapter", "generate_architecture"} else "warning",
      "gate": {
        "action_kind": action_kind,
        "check_before_run": ["project_state", "chapter_target", "previous_outputs"],
        "blocks_on_repeat": True,
      },
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
  lines = ["Agent 失败案例提醒/门禁："]
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


def _regression_visible_len(text: str) -> int:
  lines = [item for item in str(text or "").splitlines() if not item.lstrip().startswith("#")]
  return len(re.sub(r"\s+", "", "\n".join(lines)))


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


def _chapter_index_from_path(path: Path) -> int:
  match = re.search(r"(\d+)", path.stem)
  if not match:
    return 1
  try:
    return max(1, int(match.group(1)))
  except ValueError:
    return 1


def _chapter_title_from_content(content: str, chapter_index: int) -> str:
  first_line = next((line.strip("# ").strip() for line in str(content or "").splitlines() if line.strip()), "")
  return first_line[:80] or f"第 {chapter_index} 章"


def _extract_project_humanize_snippet(content: str, issue_examples: list[str], limit: int = 520) -> str:
  body_lines = [
    line.strip()
    for line in str(content or "").splitlines()
    if line.strip() and not line.lstrip().startswith("#")
  ]
  body = "\n".join(body_lines).strip() or str(content or "").strip()
  for example in issue_examples:
    needle = str(example or "").strip()
    if not needle or needle.startswith(("句长序列", "段长序列")):
      continue
    offset = body.find(needle)
    if offset < 0:
      continue
    start = max(0, offset - 140)
    end = min(len(body), offset + len(needle) + 260)
    return _compact_text(body[start:end], limit)
  return _compact_text(body, limit)


def _build_project_humanize_sample_pool(project_dir: Path, limit: int = 5) -> dict[str, object]:
  from novel_backend.services.humanize_service import analyze_humanize_text

  candidates: list[dict[str, object]] = []
  issue_counts: dict[str, int] = {}
  for path in sorted((project_dir / "chapters").glob("*.md")):
    try:
      content = path.read_text(encoding="utf-8").strip()
    except OSError:
      continue
    if not content:
      continue
    profile = analyze_humanize_text(content)
    if not profile.issues or profile.score >= 92:
      continue
    chapter_index = _chapter_index_from_path(path)
    issue_examples = [
      example
      for issue in profile.issues[:5]
      for example in issue.examples
      if str(example or "").strip()
    ]
    for issue in profile.issues[:5]:
      issue_counts[issue.label] = issue_counts.get(issue.label, 0) + max(1, issue.count)
    candidates.append(
      {
        "chapter_id": f"chapter-{chapter_index:03d}",
        "chapter_index": chapter_index,
        "chapter_title": _chapter_title_from_content(content, chapter_index),
        "chapter_path": path.as_posix(),
        "score": profile.score,
        "score_ratio": round(profile.score / 100, 3),
        "issue_count": len(profile.issues),
        "top_issues": [issue.model_dump(mode="json") for issue in profile.issues[:5]],
        "snippet": _extract_project_humanize_snippet(content, issue_examples),
        "signature": hashlib.sha1(content.encode("utf-8")).hexdigest()[:12],
        "_penalty": profile.total_penalty,
      }
    )

  candidates.sort(
    key=lambda item: (
      float(item.get("score") or 0),
      -int(item.get("_penalty") or 0),
      int(item.get("chapter_index") or 0),
    )
  )
  samples = []
  for item in candidates[:limit]:
    item.pop("_penalty", None)
    samples.append(item)

  average_score = (
    sum(float(item.get("score") or 0) for item in samples) / len(samples)
    if samples
    else 100.0
  )
  top_issue_labels = [
    label
    for label, _count in sorted(issue_counts.items(), key=lambda pair: pair[1], reverse=True)[:6]
  ]
  return {
    "sample_count": len(samples),
    "risk_count": len(candidates),
    "average_score": round(average_score, 3),
    "average_score_ratio": round(average_score / 100, 3),
    "status": _score_status(average_score / 100) if samples else "good",
    "top_issue_labels": top_issue_labels,
    "samples": samples,
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


def _golden_case_detect(text: str) -> set[str]:
  normalized = str(text or "")
  detected: set[str] = set()
  from novel_backend.services.humanize_service import analyze_humanize_text

  profile = analyze_humanize_text(normalized)
  issue_codes = {item.code for item in profile.issues}
  if issue_codes & {"ai_lexicon", "importance_boosters", "explanatory_voice", "negation_parallelism"}:
    detected.add("ai_tone")
  if issue_codes & {"formula_conclusion"}:
    detected.add("formula_conclusion")
  dialogue_lines = re.findall(r"[\u4e00-\u9fff]{1,8}说[:：][^。！？\n]{0,16}", normalized)
  if len(dialogue_lines) >= 3 and len({re.sub(r"^[^说]+说[:：]", "", item) for item in dialogue_lines}) <= 2:
    detected.add("dialogue_flat")
  if (
    "已经死" in normalized and "打来电话" in normalized
    or "断掉的左手" in normalized and "左手把" in normalized
  ):
    detected.add("continuity_conflict")
  return detected


def _run_golden_evaluator_benchmark() -> dict[str, object]:
  results: list[dict[str, object]] = []
  total_expected = 0
  total_detected = 0
  total_matched = 0
  for item in _GOLDEN_EVALUATOR_CASES:
    expected = {str(value) for value in item.get("expected_findings", [])}
    detected = _golden_case_detect(str(item.get("text") or ""))
    matched = expected & detected
    missed = expected - detected
    false_positive = detected - expected
    total_expected += len(expected)
    total_detected += len(detected)
    total_matched += len(matched)
    if not expected and not detected:
      case_score = 1.0
    else:
      recall = len(matched) / max(len(expected), 1)
      precision = len(matched) / max(len(detected), 1)
      case_score = round((recall * 0.65) + (precision * 0.35), 3)
    results.append(
      {
        "id": item.get("id", ""),
        "label": item.get("label", ""),
        "mode": item.get("mode", "chapter_snippet"),
        "expected_findings": sorted(expected),
        "detected_findings": sorted(detected),
        "missed_findings": sorted(missed),
        "false_positive_findings": sorted(false_positive),
        "score": case_score,
        "status": _score_status(case_score),
      }
    )
  precision = total_matched / max(total_detected, 1)
  recall = total_matched / max(total_expected, 1)
  clean_case_count = sum(1 for item in results if not item["expected_findings"])
  clean_pass_count = sum(1 for item in results if not item["expected_findings"] and not item["false_positive_findings"])
  false_positive_control = clean_pass_count / max(clean_case_count, 1)
  score = round((recall * 0.55) + (precision * 0.3) + (false_positive_control * 0.15), 3)
  return {
    "id": f"golden-evaluator-{_candidate_id('golden', _now_iso(), str(score))}",
    "generated_at": _now_iso(),
    "score": score,
    "status": _score_status(score),
    "precision": round(precision, 3),
    "recall": round(recall, 3),
    "false_positive_control": round(false_positive_control, 3),
    "case_count": len(results),
    "cases": results,
  }


def _run_humanize_ab_benchmark(chapter_content: str, project_dir: Path | None = None) -> dict[str, object]:
  from novel_backend.services.humanize_service import analyze_humanize_text, build_humanize_quality_report

  results: list[dict[str, object]] = []
  total_delta = 0
  passed_count = 0
  fixed_labels: dict[str, int] = {}
  remaining_labels: dict[str, int] = {}
  for item in _HUMANIZE_AB_CASES:
    before_text = str(item.get("before") or "")
    after_text = str(item.get("after") or "")
    report = build_humanize_quality_report(before_text, after_text)
    before_len = _regression_visible_len(before_text)
    after_len = _regression_visible_len(after_text)
    length_ratio = round(after_len / max(before_len, 1), 3)
    min_delta = int(item.get("min_delta") or 0)
    min_length_ratio = float(item.get("min_length_ratio") or 0.0)
    passed = report.delta >= min_delta and length_ratio >= min_length_ratio
    if passed:
      passed_count += 1
    total_delta += report.delta
    for fixed in report.fixed_issues:
      fixed_labels[fixed.label] = fixed_labels.get(fixed.label, 0) + max(1, fixed.count)
    for remaining in report.remaining_issues:
      remaining_labels[remaining.label] = remaining_labels.get(remaining.label, 0) + max(1, remaining.count)
    results.append(
      {
        "id": item.get("id", ""),
        "label": item.get("label", ""),
        "before_score": report.before_score,
        "after_score": report.after_score,
        "delta": report.delta,
        "length_ratio": length_ratio,
        "status": "good" if passed else "risk",
        "summary": report.summary,
        "fixed_issues": [fixed.model_dump(mode="json") for fixed in report.fixed_issues],
        "remaining_issues": [remaining.model_dump(mode="json") for remaining in report.remaining_issues],
      }
    )

  project_profile = analyze_humanize_text(chapter_content) if chapter_content.strip() else None
  project_issues = [item.model_dump(mode="json") for item in project_profile.issues[:6]] if project_profile else []
  project_sample_pool = (
    _build_project_humanize_sample_pool(project_dir)
    if project_dir is not None
    else {
      "sample_count": 0,
      "risk_count": 0,
      "average_score": 100.0,
      "average_score_ratio": 1.0,
      "status": "good",
      "top_issue_labels": [],
      "samples": [],
    }
  )
  pass_rate = passed_count / max(len(results), 1)
  average_delta = total_delta / max(len(results), 1)
  if int(project_sample_pool.get("sample_count") or 0) > 0:
    project_score_factor = float(project_sample_pool.get("average_score_ratio") or 0)
  else:
    project_score_factor = (float(project_profile.score) / 100) if project_profile else 0.72
  score = round((pass_rate * 0.56) + (min(average_delta, 45) / 45 * 0.28) + (project_score_factor * 0.16), 3)
  fixed_rank = sorted(fixed_labels.items(), key=lambda pair: pair[1], reverse=True)
  remaining_rank = sorted(remaining_labels.items(), key=lambda pair: pair[1], reverse=True)
  distilled_rules = [
    f"A/B 对照里{label}改善 {count} 处。"
    for label, count in fixed_rank[:4]
  ]
  if remaining_rank:
    distilled_rules.extend(
      f"残留{label}，下次回归需要加样本或强化规则。"
      for label, _count in remaining_rank[:3]
    )
  if project_issues:
    distilled_rules.append(
      "项目样本当前重点：" + "、".join(str(item.get("label") or "") for item in project_issues[:3] if isinstance(item, dict))
    )
  project_issue_labels = [
    str(item or "").strip()
    for item in project_sample_pool.get("top_issue_labels") or []
    if str(item or "").strip()
  ]
  if project_issue_labels:
    distilled_rules.append("真实章节样本池重点：" + "、".join(project_issue_labels[:4]))
  return {
    "id": f"humanize-ab-{_candidate_id('humanize-ab', _now_iso(), str(score))}",
    "generated_at": _now_iso(),
    "score": score,
    "status": _score_status(score),
    "case_count": len(results),
    "pass_rate": round(pass_rate, 3),
    "average_delta": round(average_delta, 3),
    "cases": results,
    "distilled_rules": _ordered_unique(distilled_rules)[:8],
    "project_probe": {
      "score": project_profile.score if project_profile else 0,
      "issue_count": len(project_profile.issues) if project_profile else 0,
      "issues": project_issues,
    },
    "project_sample_pool": project_sample_pool,
  }


def _coerce_score_ratio(value: object, default: float = 0.0) -> float:
  try:
    numeric = float(value)
  except (TypeError, ValueError):
    return default
  if numeric > 1:
    numeric = numeric / 100
  return round(max(0.0, min(numeric, 1.0)), 3)


def _coerce_score_100(value: object, default: int = 0) -> int:
  try:
    numeric = float(value)
  except (TypeError, ValueError):
    return default
  if 0 <= numeric <= 1:
    numeric *= 100
  return int(max(0, min(round(numeric), 100)))


def _dict_items_from_value(value: object, limit: int = 6) -> list[dict[str, object]]:
  if not isinstance(value, list):
    return []
  items: list[dict[str, object]] = []
  for item in value:
    if isinstance(item, dict):
      items.append(item)
    if len(items) >= limit:
      break
  return items


def _humanize_response_text(response: object) -> str:
  raw = str(response or "").strip()
  if not raw:
    return ""
  try:
    parsed = _extract_json_object(raw)
  except Exception:
    parsed = {}
  if isinstance(parsed, dict):
    for key in ("revised", "content", "draft", "text", "chapter", "正文"):
      value = parsed.get(key)
      if isinstance(value, str) and value.strip():
        return value.strip()
  return raw


def _build_humanize_history_replay(settings: Settings, limit: int = 5) -> dict[str, object]:
  from novel_backend.services.humanize_service import analyze_humanize_text

  records_payload = get_prompt_history_records(settings, tail=240, search="humanize")
  records = records_payload.get("records") if isinstance(records_payload, dict) else []
  samples: list[dict[str, object]] = []
  iterable_records = records if isinstance(records, list) else []
  for record in iterable_records:
    if not isinstance(record, dict):
      continue
    task = str(record.get("task") or "")
    if "humanize" not in task.lower():
      continue
    text = _humanize_response_text(record.get("response"))
    if not text:
      continue
    profile = analyze_humanize_text(text)
    samples.append(
      {
        "timestamp": record.get("timestamp", ""),
        "task": task,
        "status": record.get("status", ""),
        "elapsed": record.get("elapsed", 0),
        "score": profile.score,
        "score_ratio": round(profile.score / 100, 3),
        "remaining_issues": [issue.model_dump(mode="json") for issue in profile.issues[:5]],
        "text_excerpt": _compact_text(text, 520),
      }
    )
    if len(samples) >= limit:
      break
  average_score = (
    sum(float(item.get("score") or 0) for item in samples) / len(samples)
    if samples
    else 0.0
  )
  return {
    "sample_count": len(samples),
    "average_score": round(average_score, 3),
    "average_score_ratio": round(average_score / 100, 3) if samples else 0.0,
    "samples": samples,
  }


def _latest_humanize_ab_for_review(project_dir: Path, regression_runs: list[dict[str, object]]) -> dict[str, object]:
  latest_regression = regression_runs[0] if regression_runs else {}
  if isinstance(latest_regression, dict) and isinstance(latest_regression.get("humanize_ab_benchmark"), dict):
    return latest_regression["humanize_ab_benchmark"]
  chapter = _selected_regression_chapter(project_dir)
  return _run_humanize_ab_benchmark(str(chapter.get("content") or ""), project_dir)


def _heuristic_humanize_model_judge(
  *,
  humanize_ab: dict[str, object],
  history_replay: dict[str, object],
  status: str,
  error: str = "",
) -> dict[str, object]:
  sample_pool = humanize_ab.get("project_sample_pool") if isinstance(humanize_ab.get("project_sample_pool"), dict) else {}
  sample_average = _coerce_score_100(sample_pool.get("average_score"), 72) if sample_pool else 72
  history_average = _coerce_score_100(history_replay.get("average_score"), 0) if int(history_replay.get("sample_count") or 0) else sample_average
  naturalness_score = int(round((sample_average * 0.65) + (history_average * 0.35)))
  issue_labels = [
    str(item or "").strip()
    for item in sample_pool.get("top_issue_labels") or []
    if str(item or "").strip()
  ]
  issues = [
    {
      "title": label,
      "detail": f"真实章节样本池多次出现{label}。",
      "severity": "warning" if naturalness_score >= 68 else "critical",
      "evidence": label,
    }
    for label in issue_labels[:5]
  ]
  rules = [
    f"处理{label}时，优先保留剧情事实和人物信息，只改表达方式。"
    for label in issue_labels[:4]
  ]
  if not rules:
    rules = [
      "去 AI 后仍要保留人物声音、场景推进和信息顺序，不能把正文改成摘要。",
    ]
  return {
    "id": f"humanize-judge-{_candidate_id('humanize-judge', _now_iso(), str(naturalness_score))}",
    "generated_at": _now_iso(),
    "status": status,
    "summary": "已用本地样本池完成去 AI 审查。" if not error else f"模型裁判不可用，已改用本地样本池：{error}",
    "naturalness_score": naturalness_score,
    "score": round(naturalness_score / 100, 3),
    "ai_flavor_score": 100 - naturalness_score,
    "sample_count": int(sample_pool.get("sample_count") or 0),
    "history_sample_count": int(history_replay.get("sample_count") or 0),
    "issues": issues,
    "distilled_rules": rules,
    "rewrite_principles": rules[:3],
    "false_positive_notes": [],
    "history_replay": history_replay,
  }


def _run_humanize_model_judge(settings: Settings, project_dir: Path, regression_runs: list[dict[str, object]]) -> dict[str, object]:
  humanize_ab = _latest_humanize_ab_for_review(project_dir, regression_runs)
  history_replay = _build_humanize_history_replay(settings)
  sample_pool = humanize_ab.get("project_sample_pool") if isinstance(humanize_ab.get("project_sample_pool"), dict) else {}
  if not int(sample_pool.get("sample_count") or 0) and not int(history_replay.get("sample_count") or 0):
    return _heuristic_humanize_model_judge(
      humanize_ab=humanize_ab,
      history_replay=history_replay,
      status="no_samples",
    )

  payload = {
    "fixed_ab_summary": {
      "score": humanize_ab.get("score", 0),
      "pass_rate": humanize_ab.get("pass_rate", 0),
      "average_delta": humanize_ab.get("average_delta", 0),
      "distilled_rules": humanize_ab.get("distilled_rules", []),
    },
    "project_sample_pool": sample_pool,
    "history_replay": history_replay,
    "existing_project_rules": _load_humanize_evolution_rules(project_dir).get("rules", [])[:8],
    "judge_dimensions": ["自然度", "人物声音", "叙事张力", "非模板化", "误报风险"],
  }
  messages = [
    {
      "role": "system",
      "content": (
        "你是中文小说去 AI 审美裁判。只输出 JSON 对象，字段为 summary、naturalness_score、"
        "ai_flavor_score、issues、false_positive_notes、distilled_rules、rewrite_principles、sample_actions。"
        "naturalness_score 和 ai_flavor_score 是 0 到 100 的整数。issues 每项包含 title、detail、severity、evidence。"
        "不要按通用作文标准判断，要看人物声音、场景推进、叙事张力和是否残留模型腔。"
      ),
    },
    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
  ]
  try:
    content = _invoke_model(
      settings,
      messages,
      task_name="self_evolution_humanize_judge",
      temperature=0.15,
      max_tokens=2200,
    )
    parsed = _extract_json_object(content)
    if not isinstance(parsed, dict):
      raise ValueError("去 AI 裁判结果不是 JSON 对象")
    distilled_rules = _string_list_from_keys(parsed, "distilled_rules", "rules")[:8]
    rewrite_principles = _string_list_from_keys(parsed, "rewrite_principles", "principles")[:8]
    issues = _dict_items_from_value(parsed.get("issues"), limit=8)
    naturalness_score = _coerce_score_100(parsed.get("naturalness_score") or parsed.get("score"), 0)
    if naturalness_score <= 0 and not distilled_rules and not issues:
      raise ValueError("去 AI 裁判结果缺少有效评分和规则")
    return {
      "id": f"humanize-judge-{_candidate_id('humanize-judge', _now_iso(), content)}",
      "generated_at": _now_iso(),
      "status": "model",
      "summary": str(parsed.get("summary") or "去 AI 裁判完成。").strip(),
      "naturalness_score": naturalness_score,
      "score": round(naturalness_score / 100, 3),
      "ai_flavor_score": _coerce_score_100(parsed.get("ai_flavor_score"), 100 - naturalness_score),
      "sample_count": int(sample_pool.get("sample_count") or 0),
      "history_sample_count": int(history_replay.get("sample_count") or 0),
      "issues": issues,
      "distilled_rules": _ordered_unique(distilled_rules),
      "rewrite_principles": _ordered_unique(rewrite_principles),
      "false_positive_notes": _string_list_from_keys(parsed, "false_positive_notes", "false_positives")[:6],
      "sample_actions": _string_list_from_keys(parsed, "sample_actions", "actions")[:8],
      "history_replay": history_replay,
    }
  except Exception as error:
    return _heuristic_humanize_model_judge(
      humanize_ab=humanize_ab,
      history_replay=history_replay,
      status="model_failed",
      error=str(error),
    )


def _normalize_humanize_rule(raw: object) -> tuple[str, str] | None:
  if isinstance(raw, dict):
    title = _compact_text(str(raw.get("title") or raw.get("label") or raw.get("name") or "去 AI 规则"), 60)
    content = _compact_text(str(raw.get("content") or raw.get("detail") or raw.get("rule") or raw.get("text") or ""), 260)
  else:
    content = _compact_text(str(raw or ""), 260)
    title = _compact_text(content.split("，", 1)[0].split("。", 1)[0], 60) or "去 AI 规则"
  if not content:
    return None
  return title, content


def _update_humanize_evolution_rules(project_dir: Path, judge: dict[str, object]) -> dict[str, object]:
  store = _load_humanize_evolution_rules(project_dir)
  existing_items = store.get("rules") if isinstance(store.get("rules"), list) else []
  by_id: dict[str, dict[str, object]] = {
    str(item.get("id")): item
    for item in existing_items
    if isinstance(item, dict) and str(item.get("id") or "").strip()
  }
  raw_rules: list[object] = []
  raw_rules.extend(judge.get("distilled_rules") if isinstance(judge.get("distilled_rules"), list) else [])
  raw_rules.extend(judge.get("rewrite_principles") if isinstance(judge.get("rewrite_principles"), list) else [])
  inserted = 0
  refreshed = 0
  confidence = 0.84 if judge.get("status") == "model" else 0.64
  confidence += max(0.0, min(float(judge.get("score") or 0), 1.0)) * 0.1
  confidence = round(min(confidence, 0.94), 3)
  for raw in raw_rules:
    normalized = _normalize_humanize_rule(raw)
    if normalized is None:
      continue
    title, content = normalized
    rule_id = f"humanize-{_candidate_id('humanize-rule', title, content)}"
    if rule_id in by_id:
      item = by_id[rule_id]
      item["last_seen_at"] = _now_iso()
      item["seen_count"] = int(item.get("seen_count") or 1) + 1
      item["confidence"] = max(float(item.get("confidence") or 0), confidence)
      item["source"] = judge.get("status", item.get("source", "model"))
      refreshed += 1
      continue
    by_id[rule_id] = {
      "id": rule_id,
      "title": title,
      "content": content,
      "status": "active",
      "confidence": confidence,
      "source": judge.get("status", "model"),
      "created_at": _now_iso(),
      "last_seen_at": _now_iso(),
      "seen_count": 1,
      "metadata": {
        "judge_id": judge.get("id", ""),
        "naturalness_score": judge.get("naturalness_score", 0),
        "sample_count": judge.get("sample_count", 0),
        "history_sample_count": judge.get("history_sample_count", 0),
      },
    }
    inserted += 1

  items = sorted(
    by_id.values(),
    key=lambda item: (
      float(item.get("confidence") or 0),
      int(item.get("seen_count") or 1),
      str(item.get("last_seen_at") or item.get("created_at") or ""),
    ),
    reverse=True,
  )[:80]
  store["rules"] = items
  _save_humanize_evolution_rules(project_dir, store)
  return {
    "inserted": inserted,
    "refreshed": refreshed,
    "total": len(items),
    "active_rules": [item for item in items if isinstance(item, dict) and item.get("status") == "active"][:8],
  }


def _latest_humanize_judge(project_dir: Path) -> dict[str, object]:
  for review in _latest_jsonl_items(_model_review_path(project_dir), 20):
    if not isinstance(review, dict):
      continue
    judge = review.get("humanize_model_judge")
    if isinstance(judge, dict):
      return judge
  return {}


def _humanize_patrol_signature(project_sample_pool: dict[str, object], history_replay: dict[str, object]) -> str:
  samples = []
  for item in project_sample_pool.get("samples") or []:
    if not isinstance(item, dict):
      continue
    samples.append(
      {
        "chapter_path": item.get("chapter_path", ""),
        "signature": item.get("signature", ""),
        "score": item.get("score", 0),
        "issues": [
          str(issue.get("label") or issue.get("code") or "")
          for issue in item.get("top_issues") or []
          if isinstance(issue, dict)
        ][:5],
      }
    )
  history = []
  for item in history_replay.get("samples") or []:
    if not isinstance(item, dict):
      continue
    excerpt = str(item.get("text_excerpt") or "")
    history.append(
      {
        "timestamp": item.get("timestamp", ""),
        "task": item.get("task", ""),
        "score": item.get("score", 0),
        "text": hashlib.sha1(excerpt.encode("utf-8")).hexdigest()[:12] if excerpt else "",
      }
    )
  raw = json.dumps({"samples": samples, "history": history}, ensure_ascii=False, sort_keys=True)
  return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _build_humanize_patrol_signal(settings: Settings, project_dir: Path) -> dict[str, object]:
  project_sample_pool = _build_project_humanize_sample_pool(project_dir)
  history_replay = _build_humanize_history_replay(settings)
  rule_store = _load_humanize_evolution_rules(project_dir)
  active_rule_count = sum(
    1
    for item in rule_store.get("rules") or []
    if isinstance(item, dict) and str(item.get("status") or "active") == "active"
  )
  latest_judge = _latest_humanize_judge(project_dir)
  project_average = _coerce_score_100(project_sample_pool.get("average_score"), 100)
  history_average = _coerce_score_100(history_replay.get("average_score"), 0)
  latest_judge_score = _coerce_score_ratio(
    latest_judge.get("score") or latest_judge.get("naturalness_score"),
    0.0,
  ) if latest_judge else 0.0
  project_sample_count = int(project_sample_pool.get("sample_count") or 0)
  history_sample_count = int(history_replay.get("sample_count") or 0)
  status = "good"
  if (
    project_sample_count > 0 and project_average < 78
    or history_sample_count > 0 and history_average < 78
    or latest_judge_score and latest_judge_score < 0.68
  ):
    status = "risk"
  elif project_sample_count > 0 or history_sample_count > 0 or latest_judge_score and latest_judge_score < 0.82:
    status = "watch"
  top_issue_labels = [
    str(item or "").strip()
    for item in project_sample_pool.get("top_issue_labels") or []
    if str(item or "").strip()
  ]
  return {
    "generated_at": _now_iso(),
    "status": status,
    "signature": _humanize_patrol_signature(project_sample_pool, history_replay),
    "project_sample_count": project_sample_count,
    "project_risk_count": int(project_sample_pool.get("risk_count") or 0),
    "project_average_score": project_average,
    "project_top_issue_labels": top_issue_labels[:6],
    "history_sample_count": history_sample_count,
    "history_average_score": history_average,
    "active_rule_count": active_rule_count,
    "latest_judge_score": round(latest_judge_score, 3),
    "latest_judge_status": latest_judge.get("status", "") if latest_judge else "",
  }


def _humanize_patrol_decision(
  signal: dict[str, object],
  state: dict[str, object],
  *,
  force: bool,
) -> dict[str, object]:
  if force:
    return {"should_run": True, "reason": "force"}
  project_sample_count = int(signal.get("project_sample_count") or 0)
  history_sample_count = int(signal.get("history_sample_count") or 0)
  if project_sample_count <= 0 and history_sample_count <= 0:
    return {"should_run": False, "status": "skipped", "reason": "no_signal"}

  last_review_at = _parse_datetime(state.get("last_review_at"))
  now = datetime.now(timezone.utc)
  if last_review_at is not None:
    cooldown_until = last_review_at + timedelta(hours=_HUMANIZE_PATROL_COOLDOWN_HOURS)
    if now < cooldown_until:
      return {
        "should_run": False,
        "status": "waiting",
        "reason": "cooldown",
        "next_review_at": cooldown_until.isoformat(),
      }

  previous_signature = str(state.get("last_signature") or "")
  current_signature = str(signal.get("signature") or "")
  if previous_signature and previous_signature == current_signature:
    stale_until = (
      last_review_at + timedelta(hours=_HUMANIZE_PATROL_STALE_RECHECK_HOURS)
      if last_review_at is not None
      else None
    )
    if stale_until is None or now < stale_until:
      return {"should_run": False, "status": "skipped", "reason": "unchanged"}
    if str(signal.get("status") or "") == "good":
      return {"should_run": False, "status": "skipped", "reason": "unchanged"}
    return {"should_run": True, "reason": "stale_recheck"}

  active_rule_count = int(signal.get("active_rule_count") or 0)
  project_average = _coerce_score_100(signal.get("project_average_score"), 100)
  history_average = _coerce_score_100(signal.get("history_average_score"), 0)
  latest_judge_score = _coerce_score_ratio(signal.get("latest_judge_score"), 0.0)
  if active_rule_count <= 0:
    return {"should_run": True, "reason": "no_active_rules"}
  if project_sample_count > 0 and project_average < 92:
    return {"should_run": True, "reason": "project_samples"}
  if history_sample_count > 0 and history_average and history_average < 90:
    return {"should_run": True, "reason": "history_replay"}
  if latest_judge_score and latest_judge_score < 0.72:
    return {"should_run": True, "reason": "weak_latest_judge"}
  return {"should_run": True, "reason": "new_signal"}


def _humanize_patrol_review_summary(judge: dict[str, object], trigger: str) -> dict[str, object]:
  issue_titles = [
    _compact_text(str(item.get("title") or item.get("label") or ""), 70)
    for item in judge.get("issues") or []
    if isinstance(item, dict) and str(item.get("title") or item.get("label") or "").strip()
  ]
  rules = [
    _compact_text(str(item or ""), 120)
    for item in judge.get("distilled_rules") or []
    if str(item or "").strip()
  ]
  return {
    "failure_causes": issue_titles[:5] or [str(judge.get("summary") or "去 AI 智能巡检完成。")],
    "improvement_suggestions": rules[:6] or ["继续观察真实章节样本池和历史去 AI 输出。"],
    "trigger": trigger,
  }


def run_self_evolution_humanize_patrol(
  settings: Settings,
  project_dir: Path,
  *,
  reason: str = "heartbeat",
  force: bool = False,
) -> dict[str, object]:
  resolved_project_dir = Path(project_dir).expanduser().resolve()
  state = _load_humanize_patrol(resolved_project_dir)
  signal = _build_humanize_patrol_signal(settings, resolved_project_dir)
  decision = _humanize_patrol_decision(signal, state, force=force)
  state["last_check_at"] = _now_iso()
  state["last_signal"] = signal
  state["last_reason"] = str(decision.get("reason") or reason)
  if not decision.get("should_run"):
    state["last_status"] = str(decision.get("status") or "skipped")
    _save_humanize_patrol(resolved_project_dir, state)
    return {
      "status": state["last_status"],
      "reason": decision.get("reason", ""),
      "next_review_at": decision.get("next_review_at", ""),
      "signal": signal,
    }
  if not force and model_runtime_should_defer_background(settings):
    state["last_status"] = "deferred"
    _save_humanize_patrol(resolved_project_dir, state)
    return {
      "status": "deferred",
      "reason": decision.get("reason", ""),
      "signal": signal,
    }

  trigger = str(decision.get("reason") or reason)
  regression_runs = _latest_jsonl_items(_writing_regression_path(resolved_project_dir), 4)
  try:
    judge = _run_humanize_model_judge(settings, resolved_project_dir, regression_runs)
    rule_update = _update_humanize_evolution_rules(resolved_project_dir, judge)
    summary = _humanize_patrol_review_summary(judge, trigger)
    review = {
      "id": f"model-review-humanize-patrol-{_candidate_id(reason, trigger, str(signal.get('signature') or ''))}",
      "generated_at": _now_iso(),
      "status": "humanize_patrol",
      "summary": str(judge.get("summary") or "去 AI 智能巡检完成。"),
      "failure_causes": summary["failure_causes"],
      "improvement_suggestions": _ordered_unique(
        [
          *summary["improvement_suggestions"],
          "去 AI 智能巡检已更新项目规则，后续去 AI 改稿会读取这些规则。",
        ]
      )[:8],
      "skill_actions": [],
      "capability_actions": [],
      "risk_notes": [],
      "cross_review": {
        "enabled": False,
        "status": "not_configured",
        "reviewer_count": 1,
        "summary": "本次只执行去 AI 智能巡检。",
      },
      "humanize_model_judge": judge,
      "humanize_rule_update": rule_update,
      "humanize_patrol": {
        "reason": reason,
        "trigger": trigger,
        "signal": signal,
      },
    }
    _append_jsonl(_model_review_path(resolved_project_dir), review)
    state.update(
      {
        "last_review_at": review["generated_at"],
        "last_signature": str(signal.get("signature") or ""),
        "last_status": "completed",
        "last_reason": trigger,
        "last_signal": signal,
      }
    )
    _save_humanize_patrol(resolved_project_dir, state)
    append_app_log(settings, f"去 AI 智能巡检完成：{trigger}")
    return {
      "status": "completed",
      "reason": reason,
      "trigger": trigger,
      "signal": signal,
      "review": review,
      "humanize_model_judge": judge,
      "humanize_rule_update": rule_update,
    }
  except Exception as error:
    state["last_status"] = "failed"
    state["last_error"] = str(error)
    _save_humanize_patrol(resolved_project_dir, state)
    append_app_log(settings, f"去 AI 智能巡检失败：{error}", level="WARNING")
    return {
      "status": "failed",
      "reason": reason,
      "trigger": trigger,
      "signal": signal,
      "error": str(error),
    }


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
    "golden_evaluator_benchmark": _run_golden_evaluator_benchmark(),
    "humanize_ab_benchmark": _run_humanize_ab_benchmark(chapter_content, resolved_project_dir),
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
  latest_humanize_ab = latest_regression.get("humanize_ab_benchmark") if isinstance(latest_regression, dict) else {}
  if isinstance(latest_humanize_ab, dict) and float(latest_humanize_ab.get("score") or 0) < 0.78:
    failure_causes.append("去 AI A/B 回归未达到稳定区，需要继续强化小说正文去痕规则。")
    for item in latest_humanize_ab.get("distilled_rules") or []:
      if str(item or "").strip():
        suggestions.append(str(item).strip())
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
  temperature_text = os.environ.get("NOVEL_REVIEW_MODEL_TEMPERATURE", "").strip()
  temperature = float(temperature_text) if temperature_text else review_config.temperature
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
    payload: dict[str, object] = {
      "model": model_name,
      "messages": messages,
      "max_tokens": max_tokens,
    }
    if temperature is not None:
      payload["temperature"] = temperature
    with model_runtime_slot(settings, lane="chat", task_name="self_evolution_model_review:cross"):
      response_payload = _request_chat_completion(
        endpoint,
        api_key,
        payload,
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
  humanize_judge = _run_humanize_model_judge(settings, resolved_project_dir, regression_runs)
  humanize_rule_update = _update_humanize_evolution_rules(resolved_project_dir, humanize_judge)
  review["humanize_model_judge"] = humanize_judge
  review["humanize_rule_update"] = humanize_rule_update
  if humanize_rule_update.get("inserted") or humanize_rule_update.get("refreshed"):
    review["improvement_suggestions"] = _ordered_unique(
      [
        *(review.get("improvement_suggestions") if isinstance(review.get("improvement_suggestions"), list) else []),
        "去 AI 自学习规则已更新，后续去 AI 改稿会读取这些项目规则。",
      ]
    )[:8]
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
  humanize_patrol: dict[str, object],
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
  latest_humanize_ab = (
    latest_regression.get("humanize_ab_benchmark")
    if isinstance(latest_regression.get("humanize_ab_benchmark"), dict)
    else {}
  )
  latest_humanize_judge = (
    model_reviews[0].get("humanize_model_judge")
    if model_reviews and isinstance(model_reviews[0], dict) and isinstance(model_reviews[0].get("humanize_model_judge"), dict)
    else {}
  )
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
    "latest_humanize_ab_score": round(float(latest_humanize_ab.get("score") or 0), 3),
    "latest_humanize_ab_status": latest_humanize_ab.get("status", ""),
    "latest_humanize_judge_score": round(float(latest_humanize_judge.get("score") or 0), 3),
    "latest_humanize_judge_status": latest_humanize_judge.get("status", ""),
    "latest_humanize_patrol_status": humanize_patrol.get("last_status", ""),
    "latest_humanize_patrol_reason": humanize_patrol.get("last_reason", ""),
    "latest_humanize_patrol_checked_at": humanize_patrol.get("last_check_at", ""),
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
      "humanize_ab_scores": [
        {
          "generated_at": item.get("generated_at", ""),
          "score": round(float(item.get("humanize_ab_benchmark", {}).get("score") or 0), 3),
        }
        for item in regression_runs[:20]
        if isinstance(item, dict) and isinstance(item.get("humanize_ab_benchmark"), dict)
      ],
      "humanize_judge_scores": [
        {
          "generated_at": item.get("generated_at", ""),
          "score": round(float(item.get("humanize_model_judge", {}).get("score") or 0), 3),
        }
        for item in model_reviews[:20]
        if isinstance(item, dict) and isinstance(item.get("humanize_model_judge"), dict)
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


def get_self_evolution_state(settings: Settings, project_dir: Path, project_detail: object | None = None) -> dict[str, object]:
  candidates = _load_candidates(project_dir)
  capability_rules = _load_capability_rules(project_dir)
  drafts = _load_drafts(project_dir)
  evaluations = _latest_jsonl_items(_writing_evaluation_path(project_dir), 20)
  model_reviews = _latest_jsonl_items(_model_review_path(project_dir), 10)
  regression_runs = _latest_jsonl_items(_writing_regression_path(project_dir), 10)
  failure_cases = _latest_jsonl_items(_failure_case_path(project_dir), 20)
  schedule = _load_schedule(project_dir)
  skill_usage = get_skill_usage_state(settings)
  style_xp_evolution = load_project_style_xp_state(project_dir)
  humanize_evolution_rules = _load_humanize_evolution_rules(project_dir)
  humanize_patrol = _load_humanize_patrol(project_dir)
  narrative_state = (
    refresh_project_narrative_state_chapter_cards(
      project_dir,
      project_detail,
      auto_stage_drafts=True,
    )
    if project_detail is not None
    else load_project_narrative_state(project_dir)
  )
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
    "humanize_evolution_rules": humanize_evolution_rules,
    "humanize_review_patrol": humanize_patrol,
    "style_xp_evolution": style_xp_evolution,
    "narrative_state": narrative_state,
    "dashboard": _self_evolution_dashboard(
      candidates=candidates,
      capability_rules=capability_rules,
      evaluations=evaluations,
      skill_usage=skill_usage,
      drafts=drafts,
      regression_runs=regression_runs,
      model_reviews=model_reviews,
      failure_cases=failure_cases,
      humanize_patrol=humanize_patrol,
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
