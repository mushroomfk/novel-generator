from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from novel_backend.config import Settings
from novel_backend.models import (
  AgentArtifact,
  AgentChatRequest,
  AgentEventBlock,
  AgentExecutionTrace,
  AgentPlanAction,
)


@dataclass(slots=True)
class AgentExecutionState:
  runtime: Any
  changes: list[str] = field(default_factory=list)
  suggestions: list[str] = field(default_factory=list)
  last_reply: str = ""
  can_save_discussion_summary: bool = False
  knowledge_summary: str = ""
  knowledge_summary_chapter_id: str = ""
  chapter_knowledge_summaries: dict[str, str] = field(default_factory=dict)
  knowledge_review_note: str = ""
  execution_trace: list[AgentExecutionTrace] = field(default_factory=list)
  event_blocks: list[AgentEventBlock] = field(default_factory=list)
  artifacts: list[AgentArtifact] = field(default_factory=list)
  active_task_pack_kind: str = ""
  announced_task_pack_kind: str = ""
  active_skill_ids: list[str] = field(default_factory=list)
  skill_prompt_block: str = ""


@dataclass(slots=True)
class AgentActionExecutionContext:
  settings: Settings
  payload: AgentChatRequest
  task_id: str
  step: int
  total: int
  action: AgentPlanAction
  task_pack_kind: str


ActionHandler = Callable[[AgentActionExecutionContext, AgentExecutionState], Awaitable[None]]

_ACTION_HANDLERS: dict[str, ActionHandler] = {}


def register_action_handler(kind: str) -> Callable[[ActionHandler], ActionHandler]:
  normalized = str(kind or "").strip()

  def decorator(func: ActionHandler) -> ActionHandler:
    if not normalized:
      raise ValueError("action kind 不能为空")
    _ACTION_HANDLERS[normalized] = func
    return func

  return decorator


def get_action_handler(kind: str) -> ActionHandler:
  normalized = str(kind or "").strip()
  if normalized not in _ACTION_HANDLERS:
    raise RuntimeError(f"暂不支持的动作：{normalized}")
  return _ACTION_HANDLERS[normalized]
