from __future__ import annotations

from novel_backend.models import SkillBehavior


DEFAULT_SKILL_BEHAVIORS: dict[str, SkillBehavior] = {
  "brainstorm": SkillBehavior(
    panel="brainstorm",
    agent_action_kind="brainstorm",
    agent_requires_confirmation=False,
  ),
  "blueprint": SkillBehavior(
    panel="blueprint",
    agent_action_kind="generate_architecture",
    agent_requires_confirmation=True,
  ),
  "continue-project": SkillBehavior(
    panel="continue-project",
    agent_action_kind="continue_project",
    agent_requires_confirmation=True,
  ),
  "consistency": SkillBehavior(
    panel="consistency",
    agent_action_kind="consistency_check",
    agent_requires_confirmation=False,
  ),
  "knowledge-search": SkillBehavior(
    panel="knowledge-search",
    agent_action_kind="review_knowledge",
    agent_requires_confirmation=False,
  ),
  "chapter-scenes": SkillBehavior(
    panel="chapter-workflow",
    mode="scenes",
    input_label="拆场要求",
    submit_label="开始拆场",
    agent_action_kind="chapter_workflow",
    agent_action_mode="scenes",
    agent_requires_confirmation=False,
  ),
  "chapter-diagnose": SkillBehavior(
    panel="chapter-workflow",
    mode="diagnose",
    input_label="诊断要求",
    submit_label="开始诊断",
    agent_action_kind="chapter_workflow",
    agent_action_mode="diagnose",
    agent_requires_confirmation=False,
  ),
  "chapter-generate": SkillBehavior(
    panel="chapter-generate",
    agent_action_kind="chapter_generate",
    agent_requires_confirmation=True,
  ),
  "chapter-draft": SkillBehavior(
    panel="chapter-workflow",
    mode="draft",
    input_label="续写要求",
    submit_label="开始续写",
    agent_action_kind="chapter_workflow",
    agent_action_mode="draft",
    agent_requires_confirmation=True,
  ),
  "chapter-finalize": SkillBehavior(
    panel="chapter-rewrite",
    mode="finalize",
    input_label="改稿要求",
    submit_label="开始定稿",
    agent_action_kind="rewrite_chapter",
    agent_action_mode="finalize",
    agent_requires_confirmation=True,
  ),
  "chapter-polish": SkillBehavior(
    panel="chapter-rewrite",
    mode="polish",
    input_label="改稿要求",
    submit_label="开始润色",
    agent_action_kind="rewrite_chapter",
    agent_action_mode="polish",
    agent_requires_confirmation=True,
  ),
  "chapter-humanize": SkillBehavior(
    panel="chapter-rewrite",
    mode="humanize",
    input_label="改稿要求",
    submit_label="开始去 AI",
    agent_action_kind="rewrite_chapter",
    agent_action_mode="humanize",
    agent_requires_confirmation=True,
  ),
}


def default_skill_behavior(skill_id: str) -> SkillBehavior:
  return DEFAULT_SKILL_BEHAVIORS.get(skill_id, SkillBehavior(panel=skill_id))


def default_skill_behavior_payloads() -> dict[str, dict[str, object]]:
  return {skill_id: behavior.model_dump() for skill_id, behavior in DEFAULT_SKILL_BEHAVIORS.items()}


def merge_skill_behavior(skill_id: str, payload: object | None) -> SkillBehavior:
  default_payload = default_skill_behavior(skill_id).model_dump()
  if isinstance(payload, SkillBehavior):
    raw_payload: dict[str, object] = payload.model_dump()
  elif isinstance(payload, dict):
    raw_payload = dict(payload)
  else:
    raw_payload = {}

  merged = dict(default_payload)
  for key, value in raw_payload.items():
    if isinstance(value, str):
      cleaned = value.strip()
      if cleaned:
        merged[key] = cleaned
      continue
    if value is not None:
      merged[key] = value
  return SkillBehavior.model_validate(merged)
