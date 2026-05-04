from __future__ import annotations

import unittest

from novel_backend.services.humanize_service import (
  analyze_humanize_text,
  build_humanize_prompt_block,
  build_humanize_quality_report,
)


REGRESSION_CASES = [
  {
    "name": "意义宣告和连接词",
    "before": (
      "# 第一章 雨夜靠港\n"
      "此外，林追站在码头边，这不仅仅是一场普通的会面，更是他命运转折的重要一步。"
      "冷风与海潮交织，彰显了这座城市在不断演变的格局中的复杂性。"
    ),
    "after": (
      "# 第一章 雨夜靠港\n"
      "林追站在码头边。海风卷起外套下摆，他知道这次见面不能失手。"
    ),
    "min_delta": 25,
  },
  {
    "name": "解释腔和总结句",
    "before": (
      "值得注意的是，旧仓库不仅仅是藏钥匙的地方，更是整个秘密网络的象征。"
      "总的来说，这一发现为后续调查奠定了坚实基础。"
    ),
    "after": (
      "旧仓库里只剩半截铁锁和一地潮气。钥匙没了，说明有人比他先到。"
    ),
    "min_delta": 25,
  },
  {
    "name": "模糊归因",
    "before": (
      "一些人认为白石会馆的安静只是假象，也有人指出这代表着旧势力正在重新聚拢。"
    ),
    "after": (
      "白石会馆门口连守夜的人都换了。林追刚抬头，就看见二楼窗帘轻轻动了一下。"
    ),
    "min_delta": 18,
  },
  {
    "name": "助手口吻残留",
    "before": (
      "当然！希望这对你有帮助。可以说，林追这一步选择非常关键，这意味着剧情即将迎来新的变化。"
    ),
    "after": (
      "林追把钥匙收进掌心，没有再看那人一眼。他知道从这一刻开始，退路已经没了。"
    ),
    "min_delta": 25,
  },
  {
    "name": "三连排比",
    "before": (
      "海港呈现出潮湿、幽暗、压迫的气息，巷子里回荡着冰冷、急促、刺耳的脚步声。"
    ),
    "after": (
      "海港又湿又暗，巷子里脚步声越来越近，像是直接踩在后颈上。"
    ),
    "min_delta": 10,
  },
]


class HumanizeServiceTestCase(unittest.TestCase):
  def test_analyze_humanize_text_detects_high_risk_patterns(self) -> None:
    text = (
      "此外，这不仅仅是一场普通的会面，更是命运转折的重要一步。"
      "总的来说，这意味着故事迈出了关键一步。"
    )
    profile = analyze_humanize_text(text)

    self.assertLess(profile.score, 70)
    labels = [item.label for item in profile.issues]
    self.assertIn("AI连接词和套话", labels)
    self.assertIn("口号式对照句", labels)
    self.assertIn("总结式结尾", labels)

  def test_build_humanize_prompt_block_includes_detected_issues_and_checks(self) -> None:
    text = "此外，这不仅仅是一场普通的会面，更是命运转折的重要一步。"
    prompt_block = build_humanize_prompt_block(text)

    self.assertIn("参考内置中文去痕规则", prompt_block)
    self.assertIn("优先处理这些问题", prompt_block)
    self.assertIn("AI连接词和套话", prompt_block)
    self.assertIn("交付前自检", prompt_block)

  def test_regression_cases_show_score_improvement(self) -> None:
    for case in REGRESSION_CASES:
      with self.subTest(case=case["name"]):
        report = build_humanize_quality_report(case["before"], case["after"])
        self.assertGreaterEqual(report.delta, case["min_delta"])
        self.assertGreater(report.after_score, report.before_score)
        self.assertTrue(report.fixed_issues)
