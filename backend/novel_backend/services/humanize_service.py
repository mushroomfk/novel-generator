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
    code="stock_scene_imagery",
    label="套版画面词",
    weight=5,
    max_penalty=25,
    patterns=_compile_patterns(
      r"(?:空气|时间|四周|周围).{0,8}(?:仿佛|像是)?(?:凝固|静止|冻结|停滞)",
      r"(?:命运的齿轮|故事才刚刚开始|一切(?:都)?将(?:会)?改变|真正的考验才刚刚开始)",
      r"(?:心跳漏了半拍|眼神(?:变得)?复杂|无形的压力|沉默(?:在.{0,8})?蔓延)",
      r"(?:昏暗的灯光|潮湿的空气|压抑的气氛|沉重的气息|冰冷的目光)",
    ),
  ),
  _Rule(
    code="abstract_emotion",
    label="抽象情绪直说",
    weight=5,
    max_penalty=25,
    patterns=_compile_patterns(
      r"(?:感到|感觉到|察觉到|意识到|明白了?|知道自己必须).{0,18}(?:不安|恐惧|愤怒|悲伤|震惊|困惑|犹豫|压力|责任|危险)",
      r"(?:心中|心底|内心深处).{0,12}(?:涌起|升起|泛起|掠过|产生).{0,16}(?:感觉|情绪|不安|恐惧|愤怒|悲伤|暖意|寒意)",
      r"(?:一种|一股|一阵).{0,16}(?:说不清|难以言喻|无法言喻|莫名|复杂).{0,10}(?:感觉|情绪|力量|冲动)",
    ),
  ),
  _Rule(
    code="subtext_explained",
    label="潜台词解释",
    weight=6,
    max_penalty=24,
    patterns=_compile_patterns(
      r"(?:他|她|众人|林追|[一-龥]{2,4}).{0,14}(?:明白|知道|意识到).{0,18}(?:真正|意味着|说明|代表)",
      r"(?:这句话|这个动作|这个眼神|这份沉默).{0,12}(?:意味着|说明|代表|透露出)",
      r"(?:他|她)没有说出口，但(?:他|她|所有人).{0,16}(?:知道|明白)",
    ),
  ),
  _Rule(
    code="dialogue_stage_direction",
    label="对白标签模板化",
    weight=4,
    max_penalty=20,
    patterns=_compile_patterns(
      r"(?:他|她|[一-龥]{2,4})(?:低声|轻声|沉声|平静|坚定|复杂|沙哑|认真|缓缓|淡淡)(?:地)?(?:说|说道|开口)",
      r"(?:语气|声音).{0,8}(?:低沉|平静|坚定|复杂|颤抖|沙哑|冰冷|温柔)",
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

_HUMANIZE_NOVEL_RULES: tuple[str, ...] = (
  "人物对白要分出各自的词汇、停顿和回避方式，不能让所有人都像同一个旁白在说话。",
  "情绪先写可见反应和选择后果，再考虑心理句；不要直接替人物宣告复杂感受。",
  "场景细节要服务当前冲突，删掉“空气凝固、命运齿轮、故事才刚刚开始”这类现成画面。",
  "段落结尾要多样：动作、未回答的问题、物件变化、对白中断都可以，不要统一收成金句。",
  "允许保留作者原来的粗粝、口语、残缺句和地域词，不要把正文磨成顺滑说明文。",
)

_HUMANIZE_SELF_CHECKS: tuple[str, ...] = (
  "是否还留着“此外、值得注意的是、某种程度上、可以说”这类词。",
  "是否还有“这意味着、这表明、让读者感受到”这类解释句。",
  "是否还有“不仅仅是……更是……”或整段三连排比。",
  "人物对白是否还互相替换也成立，缺少各自的语气和信息遮掩。",
  "情绪和气氛是否还靠抽象词硬说，没有动作、物件或环境变化。",
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


def _sentence_units(text: str) -> list[str]:
  parts = re.split(r"(?<=[。！？!?])|[\n\r]+", text)
  return [item.strip(" \t　“”\"'（）()[]【】") for item in parts if item.strip()]


def _visible_len(text: str) -> int:
  return len(re.sub(r"\s+", "", text))


def _metric_issue(code: str, label: str, count: int, penalty: int, examples: list[str]) -> HumanizeIssueReport:
  return HumanizeIssueReport(
    code=code,
    label=label,
    count=max(0, count),
    penalty=max(0, penalty),
    examples=examples[:3],
  )


def _rhythm_issues(text: str) -> list[HumanizeIssueReport]:
  issues: list[HumanizeIssueReport] = []
  sentences = [item for item in _sentence_units(text) if _visible_len(item) >= 4]
  lengths = [_visible_len(item) for item in sentences]
  if len(lengths) >= 7:
    mean_length = sum(lengths) / len(lengths)
    if mean_length >= 10:
      variance = sum((item - mean_length) ** 2 for item in lengths) / len(lengths)
      coefficient = (variance ** 0.5) / mean_length
      if coefficient < 0.28:
        sample = " / ".join(str(item) for item in lengths[:8])
        issues.append(
          _metric_issue(
            "low_sentence_burstiness",
            "句长过于整齐",
            1,
            18 if coefficient < 0.2 else 12,
            [f"句长序列：{sample}"],
          )
        )

  paragraph_lengths = [_visible_len(item) for item in re.split(r"\n{2,}", text) if _visible_len(item) >= 20]
  if len(paragraph_lengths) >= 5:
    mean_paragraph = sum(paragraph_lengths) / len(paragraph_lengths)
    if mean_paragraph >= 40:
      variance = sum((item - mean_paragraph) ** 2 for item in paragraph_lengths) / len(paragraph_lengths)
      coefficient = (variance ** 0.5) / mean_paragraph
      if coefficient < 0.24:
        sample = " / ".join(str(item) for item in paragraph_lengths[:6])
        issues.append(
          _metric_issue(
            "low_paragraph_burstiness",
            "段落长度过于整齐",
            1,
            12,
            [f"段长序列：{sample}"],
          )
        )
  return issues


def _leading_subject_issues(text: str) -> list[HumanizeIssueReport]:
  sentences = [item for item in _sentence_units(text) if _visible_len(item) >= 6]
  starts: dict[str, list[str]] = {}
  for sentence in sentences:
    normalized = sentence.strip(" ，。！？；：、“”\"'（）()[]【】")
    match = re.match(r"(他们|她们|他|她|我|你)", normalized)
    if not match:
      match = re.match(
        r"([一-龥]{2,4}?)(?=(?:说|问|答|看|听|想|走|推|握|把|将|在|从|向|朝|低|抬|转|拿|放|停|站|坐|进|出|回|笑|沉默|点头|摇头))",
        normalized,
      )
    if not match:
      continue
    start = match.group(1)
    starts.setdefault(start, []).append(normalized[:24])
  if len(sentences) < 8 or not starts:
    return []
  start, examples = max(starts.items(), key=lambda item: len(item[1]))
  count = len(examples)
  if count < 4 or count / max(1, len(sentences)) < 0.42:
    return []
  return [
    _metric_issue(
      "repeated_sentence_starts",
      "句首主语重复",
      count,
      min(20, count * 4),
      [f"{start}：{item}" for item in examples[:3]],
    )
  ]


def _dialogue_sameness_issues(text: str) -> list[HumanizeIssueReport]:
  labels = re.findall(
    r"(?:低声|轻声|沉声|平静|坚定|复杂|沙哑|认真|缓缓|淡淡)(?:地)?(?:说|说道|开口)|(?:语气|声音).{0,8}(?:低沉|平静|坚定|复杂|颤抖|沙哑|冰冷|温柔)",
    text,
    flags=re.IGNORECASE,
  )
  if len(labels) < 4:
    return []
  unique_count = len(set(labels))
  if unique_count > 2 and len(labels) < 7:
    return []
  examples = []
  seen: set[str] = set()
  for item in labels:
    if item in seen:
      continue
    seen.add(item)
    examples.append(str(item))
  return [
    _metric_issue(
      "dialogue_tag_repetition",
      "对白动作标签重复",
      len(labels),
      min(18, len(labels) * 3),
      examples,
    )
  ]


def _metric_issues(text: str) -> list[HumanizeIssueReport]:
  issues: list[HumanizeIssueReport] = []
  issues.extend(_rhythm_issues(text))
  issues.extend(_leading_subject_issues(text))
  issues.extend(_dialogue_sameness_issues(text))
  return issues


def _body_length_for_guard(text: str) -> int:
  lines = [item for item in text.splitlines() if not item.lstrip().startswith("#")]
  return _visible_len("\n".join(lines))


def validate_humanize_revision_length(original: str, revised: str) -> None:
  original_length = _body_length_for_guard(original)
  revised_length = _body_length_for_guard(revised)
  if original_length < 800:
    return
  minimum_length = int(original_length * 0.72)
  if revised_length >= minimum_length:
    return
  raise RuntimeError(
    f"去 AI 修订后的正文明显短于原文（原文约 {original_length} 字，修订后约 {revised_length} 字），已停止写回。"
  )


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

  for issue in _metric_issues(source):
    issues.append(issue)
    total_penalty += issue.penalty

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
  novel_rule_lines = [f"{index}. {item}" for index, item in enumerate(_HUMANIZE_NOVEL_RULES, start=1)]
  check_lines = [f"- {item}" for item in _HUMANIZE_SELF_CHECKS]
  return "\n".join(
    [
      "参考内置中文去痕规则，按小说正文场景处理这章，不按说明文或营销文案处理。",
      f"原文当前本地评分：{profile.score}/100。先处理分数最差的地方。",
      "优先处理这些问题：",
      *issue_lines,
      "执行规则：",
      *rule_lines,
      "小说叙事去 AI 规则：",
      *novel_rule_lines,
      "处理顺序：先保剧情事实，再保人物声音，然后处理句式、气味、节奏和结尾。",
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
