from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from novel_backend.app import create_app
from novel_backend.config import reset_settings_cache


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


def api_json(response, label: str) -> dict[str, object]:
  try:
    payload = response.json()
  except Exception as error:
    raise RuntimeError(f"{label} 返回的不是 JSON：{response.text[:300]}") from error

  require(response.status_code < 400, f"{label} HTTP {response.status_code}: {payload}")
  require(payload.get("ok") is True, f"{label} 返回 ok=false：{payload}")
  data = payload.get("data")
  require(isinstance(data, dict) or isinstance(data, list), f"{label} 缺少 data")
  return payload


def chapter_review_status(detail: dict[str, object], chapter_id: str) -> dict[str, object]:
  overview = detail.get("story_overview")
  require(isinstance(overview, dict), "项目详情缺少 story_overview")
  reviews = overview.get("chapter_reviews")
  require(isinstance(reviews, list), "项目详情缺少 chapter_reviews")
  for item in reviews:
    if isinstance(item, dict) and item.get("chapter_id") == chapter_id:
      return item
  raise RuntimeError(f"找不到章节核验：{chapter_id}")


def dimension_issues(review: dict[str, object], dimension_id: str) -> str:
  dimensions = review.get("dimensions")
  require(isinstance(dimensions, list), "章节核验缺少 dimensions")
  for dimension in dimensions:
    if not isinstance(dimension, dict) or dimension.get("id") != dimension_id:
      continue
    issues = dimension.get("issues") or []
    return "\n".join(json.dumps(item, ensure_ascii=False) for item in issues)
  raise RuntimeError(f"找不到核验维度：{dimension_id}")


def _review_dimensions(review: dict[str, object]) -> list[dict[str, object]]:
  dimensions = review.get("dimensions")
  require(isinstance(dimensions, list), "章节核验缺少 dimensions")
  return [item for item in dimensions if isinstance(item, dict)]


def count_review_issues(review: dict[str, object], level: str = "") -> int:
  dimensions = _review_dimensions(review)
  count = 0
  for dimension in dimensions:
    issues = dimension.get("issues") or []
    for issue in issues:
      if not isinstance(issue, dict):
        continue
      if level and issue.get("level") != level:
        continue
      count += 1
  return count


def count_dimension_issues(review: dict[str, object], dimension_id: str, level: str = "") -> int:
  for dimension in _review_dimensions(review):
    if dimension.get("id") != dimension_id:
      continue
    return sum(
      1
      for issue in (dimension.get("issues") or [])
      if isinstance(issue, dict) and (not level or issue.get("level") == level)
    )
  raise RuntimeError(f"找不到核验维度：{dimension_id}")


def run_smoke() -> dict[str, object]:
  with tempfile.TemporaryDirectory(prefix="novel-api-release-smoke-") as temp_dir:
    env = {key: os.environ.get(key) for key in NETWORK_ENV_KEYS + ("NOVEL_DATA_DIR",)}
    try:
      os.environ["NOVEL_DATA_DIR"] = temp_dir
      for key in NETWORK_ENV_KEYS:
        os.environ[key] = ""
      reset_settings_cache()
      app = create_app()

      with patch(
        "novel_backend.services.chapter_review_service._call_model_review",
        side_effect=RuntimeError("api smoke skips remote chapter review model"),
      ), patch(
        "novel_backend.services.project_narrative_state_service._invoke_narrative_editor_model",
        side_effect=RuntimeError("api smoke skips remote narrative editor model"),
      ), TestClient(app) as client:
        config_payload = {
          "model": {
            "provider": "openai-compatible",
            "base_url": "",
            "api_key": "",
            "model_name": "",
            "max_tokens": 8192,
          },
          "embedding": {
            "provider": "local-fastembed",
            "base_url": "builtin://bge-small-zh-v1.5",
            "api_key": "",
            "model_name": "BAAI/bge-small-zh-v1.5",
            "dimensions": 512,
            "retrieval_k": 6,
            "batch_size": 8,
          },
          "review_model": {
            "enabled": False,
            "provider": "openai-compatible",
            "base_url": "",
            "api_key": "",
            "model_name": "",
            "max_tokens": 1800,
          },
          "chapter_auto_repair": {
            "enabled": True,
            "score_threshold": 65,
            "max_rounds": 2,
          },
          "model_runtime": {
            "max_chat_concurrency": 1,
            "max_retrieval_concurrency": 1,
            "background_model_enabled": False,
            "background_requires_idle_seconds": 90,
            "chapter_candidate_mode": "standard",
            "queue_policy": "wait",
            "max_queue_size": 24,
            "provider_cooldown_seconds": 1800,
          },
        }
        api_json(client.put("/api/config", json=config_payload), "保存配置")
        embedding_test = api_json(
          client.post("/api/config/test", json={"target": "embedding", "embedding": config_payload["embedding"]}),
          "测试本地 Embedding",
        )["data"]
        embedding_items = embedding_test.get("items") if isinstance(embedding_test, dict) else []
        embedding_item = next((item for item in embedding_items if item.get("target") == "embedding"), None)
        require(embedding_item and embedding_item.get("status") == "passed", "本地 Embedding API 测试未通过")

        source = (
          "第一章 雨夜靠港\n"
          "林追在旧码头找到账册残页，顾临确认铜钥匙还在林追手里。\n\n"
          "第二章 盐仓旧账\n"
          "陈小雨查出白石商会正在找铜钥匙，但没有拿到钥匙。\n\n"
          "第三章 潮声暗号\n"
          "顾临守在盐仓门口，提醒林追不要把铜钥匙交给白石商会。\n"
        )
        takeover_payload = api_json(
          client.post(
            "/api/projects/takeover/import",
            json={
              "name": "API 发布冒烟",
              "genre": "悬疑",
              "target_chapters": 6,
              "target_words": 120000,
              "source_filename": "api-smoke.txt",
              "content": source,
            },
          ),
          "旧稿接管导入",
        )["data"]
        project = takeover_payload["project"]
        project_id = project["id"]
        require(takeover_payload["report"]["applied_chapter_count"] == 3, "旧稿导入章节数不正确")
        require(takeover_payload["report"]["next_chapter_index"] == 4, "旧稿接续章号不正确")

        projects = api_json(client.get("/api/projects"), "作品列表")["data"]
        require(any(item.get("id") == project_id for item in projects), "作品列表没有新导入项目")

        api_json(client.patch(f"/api/projects/{project_id}", json={"name": "API 发布冒烟复核"}), "重命名作品")
        api_json(
          client.put(
            f"/api/projects/{project_id}/documents",
            json={
              "documents": [
                {"key": "core_seed", "content": "林追、顾临和铜钥匙是主线。"},
                {"key": "plot_structure", "content": "第四章必须承接盐仓旧账。"},
                {"key": "blueprint", "content": "铜钥匙不能落入白石商会。"},
              ]
            },
          ),
          "批量保存架构文档",
        )
        api_json(
          client.put(
            f"/api/projects/{project_id}/memory",
            json={
              "entries": [
                {"category": "硬规则", "title": "关键物品归属", "content": "铜钥匙不能被交给白石商会。"},
                {"category": "硬规则", "title": "人物状态", "content": "顾临不能死亡。"},
              ]
            },
          ),
          "保存项目记忆",
        )
        api_json(
          client.put(
            f"/api/projects/{project_id}/agent-threads",
            json={
              "active_thread_id": "thread-api-smoke",
              "threads": [
                {
                  "id": "thread-api-smoke",
                  "title": "API 冒烟线程",
                  "preview": "检查第四章承接。",
                  "updated_at": "2026-06-09T00:00:00+00:00",
                  "messages": [{"role": "user", "content": "续写第 4 章，不能混淆铜钥匙归属。"}],
                }
              ],
            },
          ),
          "保存 Agent 线程",
        )
        api_json(
          client.post(
            f"/api/projects/{project_id}/knowledge/import",
            json={
              "items": [
                {
                  "title": "盐仓资料",
                  "content": "盐仓密押账本只能由林追和顾临核对，白石商会只能追查线索。",
                }
              ]
            },
          ),
          "导入资料",
        )
        knowledge_hits = api_json(
          client.get(f"/api/projects/{project_id}/knowledge/search", params={"q": "盐仓密押 顾临", "limit": 8}),
          "知识检索",
        )["data"]
        require(any(item.get("section") == "盐仓资料" for item in knowledge_hits), "资料检索没有命中导入资料")

        chapter_payload = api_json(
          client.put(
            f"/api/projects/{project_id}/chapters/chapter-004",
            json={
              "content": "# 第四章 盐仓密押\n顾临在盐仓被杀。林追为了换通行证，把铜钥匙交给白石商会。\n"
            },
          ),
          "保存违规章节",
        )["data"]
        review = chapter_review_status(chapter_payload, "chapter-004")
        issue_text = dimension_issues(review, "project_memory")
        require("铜钥匙" in issue_text and "白石商会" in issue_text, "API 章节核验没有识别铜钥匙归属违规")
        require("顾临" in issue_text and "被杀" in issue_text, "API 章节核验没有识别人物死亡违规")

        chapter_hits = api_json(
          client.get(f"/api/projects/{project_id}/knowledge/search", params={"q": "盐仓密押", "limit": 8}),
          "章节检索",
        )["data"]
        require(any(item.get("source") == "章节正文" for item in chapter_hits), "章节保存后知识索引没有刷新")

        api_json(
          client.put(
            f"/api/projects/{project_id}/documents",
            json={
              "documents": [
                {"key": "global_summary", "content": "API 冒烟快照前版本标记：盐仓密押违规已完成核验。"},
              ]
            },
          ),
          "写入快照前版本标记",
        )

        snapshot_detail = api_json(
          client.post(f"/api/projects/{project_id}/snapshots", json={"message": "API 冒烟快照"}),
          "创建快照",
        )["data"]
        snapshots = snapshot_detail.get("local_history", {}).get("snapshots", [])
        require(snapshots, "创建快照后项目详情缺少 snapshots")
        snapshot_id = snapshots[0]["id"]
        api_json(client.get(f"/api/projects/{project_id}/snapshots/{snapshot_id}"), "读取快照")
        api_json(client.post(f"/api/projects/{project_id}/autosave"), "自动保存快照")

        export_result = api_json(
          client.post(f"/api/projects/{project_id}/export", json={"format": "markdown"}),
          "导出整书",
        )["data"]
        require(Path(export_result["path"]).is_file(), "整书导出文件不存在")

        migration = api_json(client.post(f"/api/projects/{project_id}/migration/export"), "导出迁移包")["data"]
        package_path = Path(migration["path"])
        require(package_path.is_file() and package_path.suffix == ".zip", "迁移包不存在")
        import_payload = api_json(
          client.post(
            "/api/projects/migration/import",
            json={
              "filename": package_path.name,
              "content_base64": base64.b64encode(package_path.read_bytes()).decode("ascii"),
              "name_override": "API 发布冒烟导入副本",
            },
          ),
          "导入迁移包",
        )["data"]
        require(import_payload["project"]["id"] != project_id, "迁移导入不应覆盖原项目")

        return {
          "status": "passed",
          "data_dir": temp_dir,
          "embedding": embedding_item,
          "project_id": project_id,
          "takeover": {
            "applied_chapter_count": takeover_payload["report"]["applied_chapter_count"],
            "next_chapter_index": takeover_payload["report"]["next_chapter_index"],
          },
          "knowledge_hit_count": len(knowledge_hits),
          "chapter_hit_count": len(chapter_hits),
          "chapter_review": {
            "score": review.get("overall_score"),
            "status": review.get("status"),
            "issue_count": count_review_issues(review),
            "critical_issue_count": count_review_issues(review, "critical"),
            "project_memory_issue_count": count_dimension_issues(review, "project_memory"),
            "project_memory_critical_issue_count": count_dimension_issues(review, "project_memory", "critical"),
          },
          "snapshot_id": snapshot_id,
          "export_path": export_result["path"],
          "migration_package": migration["filename"],
          "imported_project_id": import_payload["project"]["id"],
        }
    finally:
      for key, value in env.items():
        if value is None:
          os.environ.pop(key, None)
        else:
          os.environ[key] = value
      reset_settings_cache()


def main() -> int:
  try:
    result = run_smoke()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
  except Exception as error:
    print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False, indent=2), file=sys.stderr)
    return 1


if __name__ == "__main__":
  raise SystemExit(main())
