from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import tempfile
import threading
import time
import unittest
from pathlib import Path

from novel_backend.config import Settings
from novel_backend.models import AppConfigUpdateRequest, ModelRuntimeConfig
from novel_backend.services.config_service import initialize_app_storage, save_config
from novel_backend.services.model_runtime_service import (
  get_model_runtime_state,
  model_runtime_foreground_session,
  model_runtime_should_defer_background,
  model_runtime_slot,
  reset_model_runtime_for_tests,
)


class ModelRuntimeServiceTestCase(unittest.TestCase):
  def setUp(self) -> None:
    reset_model_runtime_for_tests()
    self._temp_dir = tempfile.TemporaryDirectory()
    self.settings = Settings(data_dir=Path(self._temp_dir.name))
    initialize_app_storage(self.settings)
    save_config(
      self.settings,
      AppConfigUpdateRequest(
        model_runtime=ModelRuntimeConfig(
          max_chat_concurrency=1,
          max_retrieval_concurrency=1,
          background_requires_idle_seconds=0,
          provider_cooldown_seconds=0,
        ),
      ),
    )

  def tearDown(self) -> None:
    self._temp_dir.cleanup()
    reset_model_runtime_for_tests()

  def test_chat_lane_serializes_parallel_callers(self) -> None:
    lock = threading.Lock()
    active_count = 0
    max_active_count = 0

    def run_task(index: int) -> None:
      nonlocal active_count, max_active_count
      with model_runtime_slot(self.settings, lane="chat", task_name=f"chapter_generate:{index}"):
        with lock:
          active_count += 1
          max_active_count = max(max_active_count, active_count)
        time.sleep(0.03)
        with lock:
          active_count -= 1

    with ThreadPoolExecutor(max_workers=3) as executor:
      list(executor.map(run_task, range(3)))

    state = get_model_runtime_state(self.settings)
    self.assertEqual(max_active_count, 1)
    self.assertEqual(state["active_count"], 0)
    self.assertEqual(state["waiting_count"], 0)

  def test_retrieval_waits_for_foreground_chat(self) -> None:
    foreground_entered = threading.Event()
    release_foreground = threading.Event()
    retrieval_entered = threading.Event()

    def run_foreground() -> None:
      with model_runtime_slot(self.settings, lane="chat", task_name="chapter_generate"):
        foreground_entered.set()
        release_foreground.wait(timeout=2)

    def run_retrieval() -> None:
      with model_runtime_slot(self.settings, lane="retrieval", task_name="project_query_embedding"):
        retrieval_entered.set()

    foreground_thread = threading.Thread(target=run_foreground)
    retrieval_thread = threading.Thread(target=run_retrieval)
    foreground_thread.start()
    self.assertTrue(foreground_entered.wait(timeout=1))
    retrieval_thread.start()
    time.sleep(0.05)
    self.assertFalse(retrieval_entered.is_set())

    release_foreground.set()
    foreground_thread.join(timeout=1)
    retrieval_thread.join(timeout=1)
    self.assertTrue(retrieval_entered.is_set())

  def test_background_defers_until_idle_window(self) -> None:
    save_config(
      self.settings,
      AppConfigUpdateRequest(
        model_runtime=ModelRuntimeConfig(
          max_chat_concurrency=1,
          max_retrieval_concurrency=1,
          background_requires_idle_seconds=60,
          provider_cooldown_seconds=0,
        ),
      ),
    )

    with model_runtime_slot(self.settings, lane="chat", task_name="chapter_generate"):
      self.assertTrue(model_runtime_should_defer_background(self.settings))

    self.assertTrue(model_runtime_should_defer_background(self.settings))

  def test_foreground_session_blocks_background_tasks_between_model_calls(self) -> None:
    background_entered = threading.Event()

    def run_background() -> None:
      with model_runtime_slot(self.settings, lane="chat", task_name="story_overview_model", background=True):
        background_entered.set()

    with model_runtime_foreground_session():
      self.assertTrue(model_runtime_should_defer_background(self.settings))
      with model_runtime_slot(self.settings, lane="chat", task_name="architecture_step:core_seed:initial"):
        pass

      background_thread = threading.Thread(target=run_background)
      background_thread.start()
      time.sleep(0.05)
      self.assertFalse(background_entered.is_set())

    background_thread.join(timeout=1)
    self.assertTrue(background_entered.is_set())
