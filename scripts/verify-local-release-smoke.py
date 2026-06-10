from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from novel_backend.config import Settings
from novel_backend.models import (
  AppConfigUpdateRequest,
  ChapterUpdateRequest,
  EmbeddingConfig,
  ExistingNovelImportRequest,
  KnowledgeImportItem,
  KnowledgeImportRequest,
  ModelConfig,
  ModelConfigTestRequest,
  ProjectMemoryEntryInput,
  ProjectMemoryUpdateRequest,
  ReviewModelConfig,
)
from novel_backend.services.config_service import initialize_app_storage, run_model_config_test, save_config
from novel_backend.services.context_builder import build_project_context_bundle
from novel_backend.services.project_service import (
  get_project_detail,
  import_project_knowledge,
  search_project_knowledge,
  summarize_chapter_review_status,
  update_chapter_content,
  update_project_memory,
)
from novel_backend.services.project_takeover_service import (
  get_existing_novel_takeover_state,
  import_existing_novel,
  resume_existing_novel_takeover,
)


NETWORK_ENV_KEYS = (
  "NOVEL_MODEL_API_KEY",
  "DASHSCOPE_API_KEY",
  "ARK_API_KEY",
  "OPENAI_API_KEY",
  "NOVEL_API_KEY",
  "NOVEL_REVIEW_MODEL_API_KEY",
  "NOVEL_AUXILIARY_MODEL_API_KEY",
)


def require(condition: bool, message: str) -> None:
  if not condition:
    raise RuntimeError(message)


def chapter_text(detail, chapter_id: str) -> str:
  for chapter in detail.chapters:
    if chapter.id == chapter_id:
      return chapter.content
  raise RuntimeError(f"章节不存在：{chapter_id}")


def review_dimension(detail, chapter_id: str, dimension_id: str):
  for review in detail.story_overview.chapter_reviews:
    if review.chapter_id == chapter_id:
      for dimension in review.dimensions:
        if dimension.id == dimension_id:
          return dimension
  raise RuntimeError(f"核验维度不存在：{chapter_id}/{dimension_id}")


def run_smoke() -> dict[str, object]:
  with tempfile.TemporaryDirectory(prefix="novel-local-release-smoke-") as temp_dir:
    settings = Settings(data_dir=Path(temp_dir))
    initialize_app_storage(settings)
    save_config(
      settings,
      AppConfigUpdateRequest(
        model=ModelConfig(api_key="", base_url="", model_name=""),
        embedding=EmbeddingConfig(),
        review_model=ReviewModelConfig(enabled=False, api_key="", base_url="", model_name=""),
      ),
    )

    embedding_result = run_model_config_test(
      settings,
      ModelConfigTestRequest(target="embedding", embedding=EmbeddingConfig()),
    )
    embedding_item = next((item for item in embedding_result.items if item.target == "embedding"), None)
    require(embedding_item is not None and embedding_item.status == "passed", "本地 Embedding 测试未通过")

    source = (
      "第一章 雨夜靠港\n"
      "林追回到旧码头，发现潮声里藏着旧船队的暗号。\n\n"
      "第二章 铜钥匙\n"
      "陈小雨把铜钥匙交给林追，两人决定去白石商会查旧账。\n\n"
      "第三章 空仓\n"
      "顾临守在盐仓门口，确认铜钥匙仍在林追手里。\n"
    )
    takeover = import_existing_novel(
      settings,
      ExistingNovelImportRequest(
        name="本地发布冒烟",
        genre="悬疑",
        target_chapters=6,
        target_words=120000,
        source_filename="local-smoke.txt",
        content=source,
      ),
    )
    require(takeover.report.applied_chapter_count == 3, "旧稿接管章节数量不正确")
    require(takeover.report.next_chapter_index == 4, "旧稿接续章号不正确")

    detail = get_project_detail(settings, takeover.project.id)
    require("林追回到旧码头" in chapter_text(detail, "chapter-001"), "第 1 章正文没有写入")
    require("顾临守在盐仓门口" in chapter_text(detail, "chapter-003"), "第 3 章正文没有写入")

    state = get_existing_novel_takeover_state(settings, takeover.project.id)
    require(state.state.get("status") == "completed", "旧稿接管状态不是 completed")
    resumed = resume_existing_novel_takeover(settings, takeover.project.id)
    require(resumed.report.applied_chapter_count == 3, "旧稿接管恢复结果不正确")

    context_bundle = build_project_context_bundle(
      settings,
      takeover.project.id,
      chapter_id="chapter-004",
      task_instruction="续写第 4 章",
    )
    require("旧稿接续简报" in context_bundle.context_text, "第 4 章上下文缺少旧稿接续简报")
    require("顾临守在盐仓门口" in context_bundle.context_text, "第 4 章上下文缺少上一章结尾")

    import_project_knowledge(
      settings,
      takeover.project.id,
      KnowledgeImportRequest(
        items=[
          KnowledgeImportItem(
            title="旧船队资料",
            content="隐秘航线只会在大潮夜开启，铜钥匙和盐仓密押账本必须一起出现。",
          )
        ]
      ),
    )
    hits = search_project_knowledge(settings, takeover.project.id, "隐秘航线 铜钥匙", limit=8)
    require(any(item.section == "旧船队资料" for item in hits), "知识检索没有命中导入资料")

    update_project_memory(
      settings,
      takeover.project.id,
      ProjectMemoryUpdateRequest(
        entries=[
          ProjectMemoryEntryInput(
            category="硬规则",
            title="关键物品归属",
            content="铜钥匙不能被交给白石商会。",
          ),
          ProjectMemoryEntryInput(
            category="硬规则",
            title="人物状态",
            content="顾临不能死亡。",
          ),
        ]
      ),
    )

    with patch(
      "novel_backend.services.chapter_review_service._call_model_review",
      side_effect=RuntimeError("local smoke skips remote chapter review model"),
    ), patch(
      "novel_backend.services.project_narrative_state_service._invoke_narrative_editor_model",
      side_effect=RuntimeError("local smoke skips remote narrative editor model"),
    ):
      reviewed = update_chapter_content(
        settings,
        takeover.project.id,
        "chapter-004",
        ChapterUpdateRequest(
          content=(
            "# 第四章 盐仓密押\n"
            "顾临在盐仓被杀。林追为了换通行证，把铜钥匙交给白石商会。\n"
          )
        ),
      )

    memory_dimension = review_dimension(reviewed, "chapter-004", "project_memory")
    require(memory_dimension.status == "risk", "项目记忆核验没有识别违规")
    issue_text = "\n".join(f"{item.title}\n{item.detail}" for item in memory_dimension.issues)
    require("铜钥匙" in issue_text and "白石商会" in issue_text, "项目记忆核验没有识别铜钥匙归属违规")
    require("顾临" in issue_text and "被杀" in issue_text, "项目记忆核验没有识别人物死亡违规")
    review_status = summarize_chapter_review_status(reviewed, "chapter-004")
    require(review_status.get("critical_issue_count", 0) >= 1, "章节核验没有产生 critical 问题")

    chapter_hits = search_project_knowledge(settings, takeover.project.id, "盐仓密押", limit=8)
    require(any(item.source == "章节正文" for item in chapter_hits), "章节写入后没有刷新知识索引")

    return {
      "status": "passed",
      "data_dir": str(settings.data_dir),
      "embedding": embedding_item.model_dump(mode="json"),
      "project_id": takeover.project.id,
      "takeover": {
        "applied_chapter_count": takeover.report.applied_chapter_count,
        "next_chapter_index": takeover.report.next_chapter_index,
      },
      "context_contains_takeover_brief": True,
      "knowledge_hit_count": len(hits),
      "chapter_hit_count": len(chapter_hits),
      "chapter_review": review_status,
    }


def main() -> int:
  original_env = {key: os.environ.get(key) for key in NETWORK_ENV_KEYS}
  try:
    for key in NETWORK_ENV_KEYS:
      os.environ[key] = ""
    result = run_smoke()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
  except Exception as error:
    print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False, indent=2), file=sys.stderr)
    return 1
  finally:
    for key, value in original_env.items():
      if value is None:
        os.environ.pop(key, None)
      else:
        os.environ[key] = value


if __name__ == "__main__":
  raise SystemExit(main())
