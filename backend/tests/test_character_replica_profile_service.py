from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from novel_backend.config import Settings
from novel_backend.models import CharacterReplicaProfileSaveRequest
from novel_backend.services.character_replica_profile_service import (
  delete_character_replica_profile,
  get_character_replica_profile,
  list_character_replica_profiles,
  save_character_replica_profile,
)
from novel_backend.services.config_service import initialize_app_storage


class CharacterReplicaProfileServiceTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self._temp_dir = tempfile.TemporaryDirectory()
    self.settings = Settings(data_dir=Path(self._temp_dir.name))
    initialize_app_storage(self.settings)

  def tearDown(self) -> None:
    self._temp_dir.cleanup()

  def test_save_list_get_and_delete_profile(self) -> None:
    saved = save_character_replica_profile(
      self.settings,
      "乔布斯",
      CharacterReplicaProfileSaveRequest(
        focus="只看开头的取舍和冲突。",
        source_notes="聚焦、删繁就简、端到端体验。",
        summary="先把真正重要的冲突放到读者眼前。",
        voice_profile="先切核心问题，不喜欢平铺直叙。",
        mental_models=["聚焦比堆料更重要。"],
        heuristics=["人物选择要比说明先出现。"],
        boundaries=["公开表达不等于全部真实想法。"],
        disclaimer="这是基于公开资料整理的近似视角。",
      ),
    )

    self.assertEqual(saved.name, "乔布斯")
    self.assertIn("核心问题", saved.voice_profile)

    items = list_character_replica_profiles(self.settings)
    self.assertEqual(len(items), 1)
    self.assertEqual(items[0].name, "乔布斯")

    detail = get_character_replica_profile(self.settings, "乔布斯")
    self.assertEqual(detail.focus, "只看开头的取舍和冲突。")
    self.assertEqual(detail.mental_models[0], "聚焦比堆料更重要。")

    delete_character_replica_profile(self.settings, "乔布斯")
    self.assertEqual(list_character_replica_profiles(self.settings), [])
