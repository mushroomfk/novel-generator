from __future__ import annotations

from dataclasses import dataclass, field

from novel_backend.config import Settings
from novel_backend.models import ChapterReviewReport, ChapterUpdateRequest, ProjectDetail
from novel_backend.services.config_service import load_config
from novel_backend.services.generation_service import _extract_json_object, _invoke_model, _string_from_keys
from novel_backend.services.log_service import append_app_log
from novel_backend.services.project_service import (
  summarize_chapter_review_status,
  update_chapter_content_with_review_status,
)

_CHAPTER_PROMPT_CHAR_LIMIT = 32000


@dataclass
class ChapterAutoRepairResult:
  attempted: bool = False
  applied: bool = False
  rounds_attempted: int = 0
  rounds_applied: int = 0
  score_threshold: int = 65
  max_rounds: int = 1
  reason: str = ""
  summary: str = ""
  changes: list[str] = field(default_factory=list)
  error: str = ""
  review_error: str = ""
  review_status: dict[str, object] = field(default_factory=dict)


def chapter_review_needs_auto_repair(review_status: dict[str, object], score_threshold: int = 65) -> bool:
  if not review_status.get("ok"):
    return False
  score = review_status.get("score")
  status = str(review_status.get("status") or "").strip()
  if status == "risk":
    return True
  return isinstance(score, int) and score < score_threshold


def auto_repair_chapter_after_review(
  settings: Settings,
  project_id: str,
  chapter_id: str,
  detail: ProjectDetail,
  *,
  review_error: str = "",
  style_name: str = "",
  xp_preset: str = "",
  instruction: str = "",
  max_rounds: int | None = None,
) -> tuple[ProjectDetail, str, ChapterAutoRepairResult]:
  config = load_config(settings).chapter_auto_repair
  configured_rounds = config.max_rounds if max_rounds is None else max_rounds
  current_detail = detail
  current_review_error = review_error
  result = ChapterAutoRepairResult(
    score_threshold=config.score_threshold,
    max_rounds=configured_rounds,
    review_error=review_error,
  )
  if not config.enabled:
    result.reason = "章节核验自动修订未启用。"
    result.review_status = dict(summarize_chapter_review_status(current_detail, chapter_id, current_review_error))
    return current_detail, current_review_error, result
  if configured_rounds <= 0:
    result.reason = "自动修订次数为 0。"
    result.review_status = dict(summarize_chapter_review_status(current_detail, chapter_id, current_review_error))
    return current_detail, current_review_error, result

  for _round_index in range(configured_rounds):
    review_status = summarize_chapter_review_status(current_detail, chapter_id, current_review_error)
    result.review_status = dict(review_status)
    result.review_error = current_review_error
    if current_review_error.strip():
      if not result.applied:
        result.reason = "章节核验失败，无法获得可执行的修订问题。"
      return current_detail, current_review_error, result
    if not chapter_review_needs_auto_repair(review_status, config.score_threshold):
      if not result.applied:
        result.reason = "章节核验分数未触发自动修订。"
      return current_detail, current_review_error, result

    chapter = next((item for item in current_detail.chapters if item.id == chapter_id), None)
    if chapter is None:
      result.reason = "目标章节不存在。"
      return current_detail, current_review_error, result
    original_content = chapter.content.strip()
    if not original_content:
      result.reason = "目标章节没有可修订正文。"
      return current_detail, current_review_error, result

    review = next(
      (item for item in current_detail.story_overview.chapter_reviews if item.chapter_id == chapter_id),
      None,
    )
    if review is None:
      result.reason = "章节核验报告不存在。"
      return current_detail, current_review_error, result

    result.attempted = True
    result.rounds_attempted += 1
    try:
      revised_payload = _generate_revised_chapter(
        settings,
        current_detail,
        review,
        original_content,
        style_name=style_name,
        xp_preset=xp_preset,
        instruction=instruction,
      )
    except Exception as error:
      result.error = str(error)
      append_app_log(settings, f"chapter auto repair failed for {project_id}/{chapter_id}: {error}", level="ERROR")
      return current_detail, current_review_error, result

    revised_content = _ensure_heading(
      original_content,
      _string_from_keys(revised_payload, "revised_content", "content", "chapter_content").strip(),
    )
    if not revised_content:
      result.reason = "模型没有返回可保存正文。"
      return current_detail, current_review_error, result
    if _content_equal(original_content, revised_content):
      result.reason = "模型没有给出有效改动。"
      return current_detail, current_review_error, result
    if _looks_truncated(original_content, revised_content):
      result.reason = "模型返回内容疑似不完整，已保留原正文。"
      return current_detail, current_review_error, result

    current_detail, current_review_error = update_chapter_content_with_review_status(
      settings,
      project_id,
      chapter_id,
      ChapterUpdateRequest(content=revised_content, style_name=style_name, xp_preset=xp_preset),
    )
    result.applied = True
    result.rounds_applied += 1
    summary = _string_from_keys(revised_payload, "summary", "repair_summary").strip()
    if summary:
      result.summary = summary
    _append_unique(result.changes, _string_list(revised_payload.get("changes")))

  review_status = summarize_chapter_review_status(current_detail, chapter_id, current_review_error)
  result.review_error = current_review_error
  result.review_status = dict(review_status)
  if chapter_review_needs_auto_repair(review_status, config.score_threshold):
    result.reason = "已达到自动修订次数上限。"
  return current_detail, current_review_error, result


def _generate_revised_chapter(
  settings: Settings,
  detail: ProjectDetail,
  review: ChapterReviewReport,
  content: str,
  *,
  style_name: str,
  xp_preset: str,
  instruction: str,
) -> dict[str, object]:
  response = _invoke_model(
    settings,
    _build_auto_repair_messages(
      detail,
      review,
      content,
      style_name=style_name,
      xp_preset=xp_preset,
      instruction=instruction,
    ),
    task_name="chapter_auto_repair",
    temperature=0.45,
    max_tokens=24000,
    enable_thinking=False,
  )
  payload = _extract_json_object(response)
  if not isinstance(payload, dict):
    raise RuntimeError("章节自动修订没有返回合法 JSON")
  return payload


def _build_auto_repair_messages(
  detail: ProjectDetail,
  review: ChapterReviewReport,
  content: str,
  *,
  style_name: str,
  xp_preset: str,
  instruction: str,
) -> list[dict[str, str]]:
  system_prompt = """
你是中文长篇小说的章节修订编辑。你只根据章节核验报告修订正文，不重写故事方向。

输出一个 JSON 对象，字段固定为：
{
  "summary": "本次修订摘要",
  "changes": ["实际改动 1", "实际改动 2"],
  "revised_content": "完整章节正文，第一行保留 Markdown 章节标题"
}

修订边界：
1. 保留人物姓名、关系、事件结果、时间顺序和既有设定。
2. 只处理核验报告指出的风险和警告。
3. 不新增大段设定说明，不把悬念提前揭穿。
4. 返回完整章节正文，不能只返回片段。
5. 不输出 JSON 以外的文字。
""".strip()
  user_prompt = "\n\n".join(
    [
      f"项目：{detail.name}｜类型：{detail.genre}",
      f"章节：第 {review.chapter_index} 章《{review.chapter_title}》",
      f"文风方案：{style_name or '未指定'}",
      f"体验预设：{xp_preset or '未指定'}",
      f"用户要求：{instruction or '按章节核验报告修订。'}",
      "章节核验报告：",
      _format_review_for_prompt(review),
      "需要修订的正文：",
      _limit_prompt_text(content),
    ]
  )
  return [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": user_prompt},
  ]


def _format_review_for_prompt(review: ChapterReviewReport) -> str:
  lines = [
    f"总分：{review.overall_score}/100",
    f"状态：{review.status}",
    f"总评：{review.summary}",
  ]
  if review.suggestions:
    lines.append("建议：" + "；".join(item for item in review.suggestions if item.strip()))
  for dimension in review.dimensions:
    if dimension.status == "good" and dimension.score >= 80 and not dimension.issues:
      continue
    lines.append(f"- {dimension.label}：{dimension.score}/100，{dimension.status}。{dimension.summary}")
    for issue in dimension.issues:
      lines.append(f"  - [{issue.level}] {issue.title}：{issue.detail}")
  return "\n".join(item for item in lines if item.strip())


def _limit_prompt_text(text: str, limit: int = _CHAPTER_PROMPT_CHAR_LIMIT) -> str:
  stripped = text.strip()
  if len(stripped) <= limit:
    return stripped
  head_limit = max(1000, limit // 2)
  tail_limit = max(1000, limit - head_limit)
  return f"{stripped[:head_limit]}\n\n[中间内容过长，已省略]\n\n{stripped[-tail_limit:]}"


def _ensure_heading(original_content: str, revised_content: str) -> str:
  revised = revised_content.strip()
  if not revised:
    return ""
  original_first_line = original_content.strip().splitlines()[0].strip() if original_content.strip() else ""
  if original_first_line.startswith("#") and not revised.lstrip().startswith("#"):
    return f"{original_first_line}\n{revised.lstrip()}".strip()
  return revised


def _content_equal(left: str, right: str) -> bool:
  return "\n".join(line.rstrip() for line in left.strip().splitlines()) == "\n".join(
    line.rstrip() for line in right.strip().splitlines()
  )


def _looks_truncated(original_content: str, revised_content: str) -> bool:
  original_length = len(original_content.strip())
  revised_length = len(revised_content.strip())
  return original_length >= 600 and revised_length < int(original_length * 0.55)


def _string_list(value: object) -> list[str]:
  if not isinstance(value, list):
    return []
  return [str(item).strip() for item in value if str(item).strip()]


def _append_unique(target: list[str], values: list[str]) -> None:
  seen = set(target)
  for value in values:
    if value in seen:
      continue
    target.append(value)
    seen.add(value)
