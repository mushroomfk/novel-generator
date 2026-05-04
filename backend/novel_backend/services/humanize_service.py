from __future__ import annotations

import re
from dataclasses import dataclass

from novel_backend.models import HumanizeIssueReport, HumanizeQualityReport


@dataclass(frozen=True)
class _Rule:
  code: str
  label: str
  weight: int
  max_penalty: int
  patterns: tuple[re.Pattern[str], ...]


@dataclass(frozen=True)
class HumanizeTextProfile:
  score: int
  issues: list[HumanizeIssueReport]
  total_penalty: int


def _compile_patterns(*items: str) -> tuple[re.Pattern[str], ...]:
  return tuple(re.compile(item, re.IGNORECASE) for item in items)


_RULES: tuple[_Rule, ...] = (
  _Rule(
    code="ai_lexicon",
    label="AI连接词和套话",
    weight=5,
    max_penalty=25,
    patterns=_compile_patterns(
      r"(?:^|[。！？\n])\s*(?:此外|与此同时|值得注意的是|某种程度上|从某种意义上说|可以说|换句话说|不难看出)",
      r"(?:至关重要|深入探讨|持久影响|不断演变的格局|复杂性|高质量|无缝|赋能)",
    ),
  ),
  _Rule(
    code="importance_boosters",
    label="意义宣告句",
    weight=7,
    max_penalty=28,
    patterns=_compile_patterns(
      r"(?:标志着|象征着|彰显了|体现了|证明了|见证了).{0,18}(?:意义|价值|转折|变化)",
      r"(?:代表着).{0,12}(?:变化|转折|秩序|力量|秘密)",
      r"(?:关键作用|关键一步|重要一步|里程碑|奠定了(?:坚实)?基础|翻开了新的一页)",
    ),
  ),
  _Rule(
    code="explanatory_voice",
    label="解释腔",
    weight=6,
    max_penalty=24,
    patterns=_compile_patterns(
      r"(?:这意味着|这表明|这也说明|这无疑说明|由此可见|这代表着)",
      r"(?:让(?:人|读者).{0,10}(?:感受到|看到|意识到)|进一步凸显|进一步说明)",
    ),
  ),
  _Rule(
    code="vague_authority",
    label="模糊归因",
    weight=8,
    max_penalty=24,
    patterns=_compile_patterns(
      r"(?:一些人|有人|不少人|业内人士|观察者|评论界|专家).{0,8}(?:认为|觉得|指出|表示)",
    ),
  ),
  _Rule(
    code="formula_conclusion",
    label="总结式结尾",
    weight=7,
    max_penalty=28,
    patterns=_compile_patterns(
      r"(?:总的来说|总而言之|归根结底|说到底|可以预见)",
      r"(?:未来可期|迈出了?重要一步|继续书写|继续前行|追求卓越)",
    ),
  ),
  _Rule(
    code="negation_parallelism",
    label="口号式对照句",
    weight=6,
    max_penalty=24,
    patterns=_compile_patterns(
      r"(?:不仅仅?是|不只是|不是).{0,20}(?:而是|更是)",
    ),
  ),
  _Rule(
    code="triad_lists",
    label="过匀的三连排比",
    weight=5,
    max_penalty=15,
    patterns=_compile_patterns(
      r"[^。！？\n]{0,20}、[^。！？\n]{1,12}、[^。！？\n]{1,12}",
    ),
  ),
  _Rule(
    code="assistant_tone",
    label="助手口吻残留",
    weight=9,
    max_penalty=27,
    patterns=_compile_patterns(
      r"(?:当然[！!]?|希望这对(?:你|您)有帮助|请告诉我|如果你需要|很高兴)",
    ),
  ),
)

_HUMANIZE_CORE_RULES: tuple[str, ...] = (
  "只改语言和结构，不改剧情事实、信息顺序、人物关系、伏笔和结局。",
  "优先删掉 AI 连接词、意义宣告句、解释腔、总结句和口号式对照句。",
  "抽象判断尽量改成动作、对白、停顿、物件和可见细节，不替读者总结。",
  "避免均匀三连和过满的排比，让句子长短有变化，允许小说的呼吸感。",
  "结尾不要上价值，不要宣布主题，不要再补一个说明段。",
)

_HUMANIZE_SELF_CHECKS: tuple[str, ...] = (
  "是否还留着“此外、值得注意的是、某种程度上、可以说”这类词。",
  "是否还有“这意味着、这表明、让读者感受到”这类解释句。",
  "是否还有“不仅仅是……更是……”或整段三连排比。",
  "结尾有没有回到总结、升华、宣告意义。",
)


def _collect_matches(text: str, patterns: tuple[re.Pattern[str], ...]) -> list[str]:
  matches: list[str] = []
  seen: set[str] = set()
  for pattern in patterns:
    for match in pattern.finditer(text):
      raw = re.sub(r"\s+", " ", match.group(0)).strip(" ，。！？；：\n\t")
      if not raw or raw in seen:
        continue
      seen.add(raw)
      matches.append(raw)
  return matches


def analyze_humanize_text(text: str) -> HumanizeTextProfile:
  source = text.strip()
  if not source:
    return HumanizeTextProfile(score=100, issues=[], total_penalty=0)

  issues: list[HumanizeIssueReport] = []
  total_penalty = 0
  for rule in _RULES:
    matches = _collect_matches(source, rule.patterns)
    if not matches:
      continue
    penalty = min(rule.max_penalty, len(matches) * rule.weight)
    issues.append(
      HumanizeIssueReport(
        code=rule.code,
        label=rule.label,
        count=len(matches),
        penalty=penalty,
        examples=matches[:3],
      )
    )
    total_penalty += penalty

  issues.sort(key=lambda item: (-item.penalty, -item.count, item.label))
  return HumanizeTextProfile(
    score=max(0, 100 - total_penalty),
    issues=issues,
    total_penalty=total_penalty,
  )


def build_humanize_prompt_block(text: str) -> str:
  profile = analyze_humanize_text(text)
  issue_lines = (
    [f"- {item.label}：{item.count} 处，例如 {' / '.join(item.examples)}" for item in profile.issues[:5]]
    if profile.issues
    else ["- 当前正文没有扫出明显的模板腔高频词，但仍要检查节奏和结尾。"]
  )
  rule_lines = [f"{index}. {item}" for index, item in enumerate(_HUMANIZE_CORE_RULES, start=1)]
  check_lines = [f"- {item}" for item in _HUMANIZE_SELF_CHECKS]
  return "\n".join(
    [
      "参考内置中文去痕规则，按小说正文场景处理这章。",
      f"原文当前本地评分：{profile.score}/100。先处理分数最差的地方。",
      "优先处理这些问题：",
      *issue_lines,
      "执行规则：",
      *rule_lines,
      "交付前自检：",
      *check_lines,
    ]
  )


def build_humanize_quality_report(original: str, revised: str) -> HumanizeQualityReport:
  before = analyze_humanize_text(original)
  after = analyze_humanize_text(revised)
  before_map = {item.code: item for item in before.issues}
  after_map = {item.code: item for item in after.issues}

  fixed: list[HumanizeIssueReport] = []
  for code, issue in before_map.items():
    current = after_map.get(code)
    if current and current.count >= issue.count:
      continue
    reduced_count = issue.count if current is None else issue.count - current.count
    reduced_penalty = issue.penalty if current is None else max(0, issue.penalty - current.penalty)
    fixed.append(
      HumanizeIssueReport(
        code=issue.code,
        label=issue.label,
        count=reduced_count,
        penalty=reduced_penalty,
        examples=issue.examples,
      )
    )
  fixed.sort(key=lambda item: (-item.penalty, -item.count, item.label))

  remaining = sorted(
    after.issues,
    key=lambda item: (-item.penalty, -item.count, item.label),
  )[:4]
  delta = after.score - before.score
  improved_labels = "、".join(item.label for item in fixed[:3]) or "明显问题"
  remaining_labels = "、".join(item.label for item in remaining[:3])
  if delta > 0:
    summary = f"本地评分 {before.score} → {after.score}，主要压掉了 {improved_labels}。"
    if remaining_labels:
      summary += f" 还剩 {remaining_labels}。"
  elif delta == 0:
    summary = f"本地评分保持 {after.score}，还需要继续处理 {remaining_labels or '节奏和结尾'}。"
  else:
    summary = f"本地评分 {before.score} → {after.score}，这版没有变好，主要卡在 {remaining_labels or '整体语言质感'}。"

  return HumanizeQualityReport(
    before_score=before.score,
    after_score=after.score,
    delta=delta,
    summary=summary,
    fixed_issues=fixed[:4],
    remaining_issues=remaining,
  )


def build_humanize_fallback_changes(report: HumanizeQualityReport) -> list[str]:
  changes = [f"压掉了 {item.label}" for item in report.fixed_issues[:3] if item.count > 0]
  if not changes and report.remaining_issues:
    changes = [f"这版还残留 {item.label}" for item in report.remaining_issues[:3]]
  return changes[:4]
