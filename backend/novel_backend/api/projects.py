from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from novel_backend.api.license_guard import require_valid_license
from novel_backend.models import (
  AgentThreadStoreUpdateRequest,
  ArchitectureWorkspaceApplyRequest,
  ChapterReviewRefreshRequest,
  ChapterUpdateRequest,
  CreateProjectRequest,
  ExistingNovelImportRequest,
  ImportedFileBatchRequest,
  ObsidianVaultConfig,
  ProjectDreamPromoteRequest,
  ProjectDreamRunRequest,
  ProjectMigrationImportRequest,
  ProjectRenameRequest,
  KnowledgeImportRequest,
  ProjectMemoryUpdateRequest,
  ProjectExportRequest,
  SelfEvolutionCandidateUpdateRequest,
  SelfEvolutionDraftUpdateRequest,
  SelfEvolutionScheduleUpdateRequest,
  SnapshotCreateRequest,
  SnapshotRestoreRequest,
  StoryDocumentBatchUpdateRequest,
  StoryDocumentUpdateRequest,
)
from novel_backend.services.import_service import imported_files_to_knowledge_items
from novel_backend.services.project_takeover_service import (
  get_existing_novel_takeover_state,
  import_existing_novel,
  resume_existing_novel_takeover,
)
from novel_backend.services.project_service import (
  apply_architecture_workspace,
  auto_save_project_snapshot,
  confirm_project_obsidian_maintenance_merge,
  confirm_project_obsidian_maintenance_merges,
  create_project,
  create_project_snapshot,
  delete_project,
  export_project_book,
  export_project_migration_package,
  get_project_agent_threads,
  get_project_obsidian_state,
  get_project_snapshot_detail,
  get_project_detail,
  ignore_project_obsidian_maintenance_notes,
  ignore_project_obsidian_maintenance_note,
  import_project_knowledge,
  import_project_migration_package,
  list_projects,
  open_project_directory,
  promote_project_dream,
  rename_project,
  reopen_project_obsidian_maintenance_notes,
  reopen_project_obsidian_maintenance_note,
  restore_project_snapshot,
  run_project_dream,
  search_project_knowledge,
  save_project_agent_threads,
  publish_project_obsidian_maintenance_notes,
  publish_project_obsidian_maintenance_note,
  stage_project_obsidian_maintenance_draft,
  stage_project_obsidian_maintenance_drafts,
  sync_project_obsidian,
  refresh_chapter_review,
  update_chapter_content,
  update_chapter_content_with_review_status,
  update_project_obsidian_config,
  update_project_memory,
  update_story_documents,
  update_story_document,
)
from novel_backend.services.self_evolution_service import (
  apply_self_evolution_draft,
  get_self_evolution_state,
  run_self_evolution_model_review,
  run_self_evolution_scheduled_tasks,
  run_writing_regression_suite,
  update_self_evolution_candidate_status,
  update_self_evolution_draft_status,
  update_self_evolution_schedule,
)
from novel_backend.services.skill_usage_service import run_skill_curator
from novel_backend.services.log_service import append_app_log
from novel_backend.services.web_research_service import research_historical_reference
from novel_backend.utils.sse import encode_sse

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _self_evolution_meta(settings, detail, log_context: str) -> dict[str, object]:
  meta = {}
  try:
    meta["self_evolution"] = get_self_evolution_state(settings, Path(detail.path), detail)
  except Exception as error:
    meta["self_evolution_error"] = str(error)
    append_app_log(settings, f"{log_context}后的自学习状态刷新失败：{error}", level="WARNING")
  return meta


def _chapter_mutation_response(settings, detail, review_error: str = ""):
  meta = {}
  if review_error:
    meta["review_error"] = review_error
  meta.update(_self_evolution_meta(settings, detail, "章节保存"))
  payload = {
    "ok": True,
    "data": detail.model_dump(mode="json"),
  }
  if meta:
    payload["meta"] = meta
  return payload


def _project_action_response(settings, project_id: str, data: dict[str, object], log_context: str):
  payload = {
    "ok": True,
    "data": data,
  }
  try:
    detail = get_project_detail(settings, project_id)
  except Exception as error:
    payload["meta"] = {"self_evolution_error": str(error)}
    append_app_log(settings, f"{log_context}后的自学习状态刷新失败：{error}", level="WARNING")
    return payload

  meta = _self_evolution_meta(settings, detail, log_context)
  if meta:
    payload["meta"] = meta
  return payload


def _self_evolution_action_response(settings, detail, data: dict[str, object], log_context: str):
  payload = {
    "ok": True,
    "data": data,
  }
  meta = _self_evolution_meta(settings, detail, log_context)
  if meta:
    payload["meta"] = meta
  return payload


@router.get("")
def get_projects(request: Request):
  settings = request.app.state.settings
  payload = [item.model_dump(mode="json") for item in list_projects(settings)]
  return {"ok": True, "data": payload}


@router.post("")
async def post_project(request: Request, project_request: CreateProjectRequest):
  settings = request.app.state.settings
  summary = create_project(settings, project_request)
  watcher = getattr(request.app.state, "project_history_watcher", None)
  if watcher is not None:
    await watcher.register_project(summary.id, Path(summary.path))

  payload = summary.model_dump(mode="json")
  return JSONResponse(
    status_code=status.HTTP_201_CREATED,
    content={"ok": True, "data": payload},
  )


@router.post("/migration/import")
async def post_project_migration_import(
  request: Request,
  import_request: ProjectMigrationImportRequest,
):
  settings = request.app.state.settings
  payload = import_project_migration_package(settings, import_request)
  watcher = getattr(request.app.state, "project_history_watcher", None)
  if watcher is not None:
    await watcher.register_project(payload.project.id, Path(payload.project.path))
  return {"ok": True, "data": payload.model_dump(mode="json")}


@router.post("/takeover/import")
async def post_existing_novel_import(
  request: Request,
  import_request: ExistingNovelImportRequest,
):
  settings = request.app.state.settings
  payload = import_existing_novel(settings, import_request)
  watcher = getattr(request.app.state, "project_history_watcher", None)
  if watcher is not None:
    await watcher.register_project(payload.project.id, Path(payload.project.path))
  return {"ok": True, "data": payload.model_dump(mode="json")}


@router.get("/{project_id}")
def get_project(
  request: Request,
  project_id: str,
  review_characters: bool = Query(default=False),
):
  if review_characters:
    require_valid_license(request)
  settings = request.app.state.settings
  payload = get_project_detail(
    settings,
    project_id,
    review_characters=review_characters,
    refresh_narrative_state=review_characters,
    auto_publish_obsidian_maintenance=review_characters,
  ).model_dump(mode="json")
  return {"ok": True, "data": payload}


@router.get("/{project_id}/takeover")
def get_project_takeover_state(request: Request, project_id: str):
  settings = request.app.state.settings
  payload = get_existing_novel_takeover_state(settings, project_id).model_dump(mode="json")
  return {"ok": True, "data": payload}


@router.post("/{project_id}/takeover/resume")
def post_project_takeover_resume(request: Request, project_id: str):
  settings = request.app.state.settings
  payload = resume_existing_novel_takeover(settings, project_id)
  return {"ok": True, "data": payload.model_dump(mode="json")}


@router.get("/{project_id}/agent-threads")
def get_project_threads(request: Request, project_id: str):
  settings = request.app.state.settings
  payload = get_project_agent_threads(settings, project_id).model_dump(mode="json")
  return {"ok": True, "data": payload}


@router.put("/{project_id}/agent-threads")
def put_project_threads(
  request: Request,
  project_id: str,
  thread_request: AgentThreadStoreUpdateRequest,
):
  settings = request.app.state.settings
  payload = save_project_agent_threads(settings, project_id, thread_request).model_dump(mode="json")
  return {"ok": True, "data": payload}


@router.patch("/{project_id}")
async def patch_project(
  request: Request,
  project_id: str,
  rename_request: ProjectRenameRequest,
):
  settings = request.app.state.settings
  payload = rename_project(settings, project_id, rename_request)
  watcher = getattr(request.app.state, "project_history_watcher", None)
  if watcher is not None:
    await watcher.register_project(payload.id, Path(payload.path))
  return {"ok": True, "data": payload.model_dump(mode="json")}


@router.delete("/{project_id}")
async def delete_project_item(request: Request, project_id: str):
  settings = request.app.state.settings
  payload = delete_project(settings, project_id)
  watcher = getattr(request.app.state, "project_history_watcher", None)
  if watcher is not None:
    await watcher.unregister_project(project_id)
  return {"ok": True, "data": payload.model_dump(mode="json")}


@router.post("/{project_id}/open-directory")
def post_project_open_directory(request: Request, project_id: str):
  settings = request.app.state.settings
  payload = open_project_directory(settings, project_id).model_dump(mode="json")
  return {"ok": True, "data": payload}


@router.post("/{project_id}/export")
def post_project_export(
  request: Request,
  project_id: str,
  export_request: ProjectExportRequest,
):
  settings = request.app.state.settings
  payload = export_project_book(settings, project_id, export_request).model_dump(mode="json")
  return {"ok": True, "data": payload}


@router.post("/{project_id}/migration/export")
def post_project_migration_export(request: Request, project_id: str):
  settings = request.app.state.settings
  payload = export_project_migration_package(settings, project_id).model_dump(mode="json")
  return {"ok": True, "data": payload}


@router.put("/{project_id}/documents/{document_key}")
def put_story_document(
  request: Request,
  project_id: str,
  document_key: str,
  document_request: StoryDocumentUpdateRequest,
):
  settings = request.app.state.settings
  payload = update_story_document(settings, project_id, document_key, document_request).model_dump(mode="json")
  return {"ok": True, "data": payload}


@router.put("/{project_id}/documents")
def put_story_documents(
  request: Request,
  project_id: str,
  document_request: StoryDocumentBatchUpdateRequest,
):
  settings = request.app.state.settings
  payload = update_story_documents(settings, project_id, document_request).model_dump(mode="json")
  return {"ok": True, "data": payload}


@router.put("/{project_id}/memory")
def put_project_memory(
  request: Request,
  project_id: str,
  memory_request: ProjectMemoryUpdateRequest,
):
  settings = request.app.state.settings
  payload = update_project_memory(settings, project_id, memory_request).model_dump(mode="json")
  return {"ok": True, "data": payload}


@router.post("/{project_id}/dreams/run")
def post_project_dream_run(
  request: Request,
  project_id: str,
  dream_request: ProjectDreamRunRequest,
):
  require_valid_license(request)
  settings = request.app.state.settings
  payload = run_project_dream(settings, project_id, dream_request).model_dump(mode="json")
  return {"ok": True, "data": payload}


@router.post("/{project_id}/dreams/promote")
def post_project_dream_promote(
  request: Request,
  project_id: str,
  promote_request: ProjectDreamPromoteRequest,
):
  settings = request.app.state.settings
  payload = promote_project_dream(settings, project_id, promote_request).model_dump(mode="json")
  return {"ok": True, "data": payload}


@router.get("/{project_id}/self-evolution")
def get_project_self_evolution(request: Request, project_id: str):
  settings = request.app.state.settings
  detail = get_project_detail(settings, project_id)
  payload = get_self_evolution_state(settings, Path(detail.path), detail)
  return {"ok": True, "data": payload}


@router.patch("/{project_id}/self-evolution/candidates/{candidate_id}")
def patch_project_self_evolution_candidate(
  request: Request,
  project_id: str,
  candidate_id: str,
  candidate_request: SelfEvolutionCandidateUpdateRequest,
):
  settings = request.app.state.settings
  detail = get_project_detail(settings, project_id)
  try:
    payload = update_self_evolution_candidate_status(Path(detail.path), candidate_id, candidate_request.status)
  except FileNotFoundError:
    raise HTTPException(
      status_code=404,
      detail={"code": "self_evolution_candidate_not_found", "message": "自学习候选不存在"},
    ) from None
  except ValueError as error:
    raise HTTPException(
      status_code=400,
      detail={"code": "self_evolution_candidate_status_invalid", "message": str(error)},
    ) from None
  return _self_evolution_action_response(settings, detail, payload, "自学习候选状态更新")


@router.post("/{project_id}/self-evolution/curate")
def post_project_self_evolution_curate(request: Request, project_id: str):
  settings = request.app.state.settings
  detail = get_project_detail(settings, project_id)
  payload = run_skill_curator(settings)
  return _self_evolution_action_response(settings, detail, payload, "自学习技能维护")


@router.post("/{project_id}/self-evolution/regression")
def post_project_self_evolution_regression(request: Request, project_id: str):
  settings = request.app.state.settings
  detail = get_project_detail(settings, project_id)
  payload = run_writing_regression_suite(settings, Path(detail.path))
  return _self_evolution_action_response(settings, detail, payload, "自学习写作回归")


@router.post("/{project_id}/self-evolution/model-review")
def post_project_self_evolution_model_review(request: Request, project_id: str):
  settings = request.app.state.settings
  detail = get_project_detail(settings, project_id)
  payload = run_self_evolution_model_review(settings, Path(detail.path))
  return _self_evolution_action_response(settings, detail, payload, "自学习模型审查")


@router.put("/{project_id}/self-evolution/schedule")
def put_project_self_evolution_schedule(
  request: Request,
  project_id: str,
  schedule_request: SelfEvolutionScheduleUpdateRequest,
):
  settings = request.app.state.settings
  detail = get_project_detail(settings, project_id)
  try:
    payload = update_self_evolution_schedule(Path(detail.path), schedule_request.model_dump(mode="json"))
  except ValueError as error:
    raise HTTPException(
      status_code=400,
      detail={"code": "self_evolution_schedule_invalid", "message": str(error)},
    ) from None
  return _self_evolution_action_response(settings, detail, payload, "自学习排程设置")


@router.post("/{project_id}/self-evolution/schedule/run")
def post_project_self_evolution_schedule_run(request: Request, project_id: str):
  settings = request.app.state.settings
  detail = get_project_detail(settings, project_id)
  payload = run_self_evolution_scheduled_tasks(settings, Path(detail.path), force=True)
  return _self_evolution_action_response(settings, detail, payload, "自学习排程执行")


@router.patch("/{project_id}/self-evolution/drafts/{draft_id}")
def patch_project_self_evolution_draft(
  request: Request,
  project_id: str,
  draft_id: str,
  draft_request: SelfEvolutionDraftUpdateRequest,
):
  settings = request.app.state.settings
  detail = get_project_detail(settings, project_id)
  try:
    payload = update_self_evolution_draft_status(Path(detail.path), draft_id, draft_request.status)
  except FileNotFoundError:
    raise HTTPException(
      status_code=404,
      detail={"code": "self_evolution_draft_not_found", "message": "自学习草案不存在"},
    ) from None
  except ValueError as error:
    raise HTTPException(
      status_code=400,
      detail={"code": "self_evolution_draft_status_invalid", "message": str(error)},
    ) from None
  return _self_evolution_action_response(settings, detail, payload, "自学习草案状态更新")


@router.post("/{project_id}/self-evolution/drafts/{draft_id}/apply")
def post_project_self_evolution_draft_apply(request: Request, project_id: str, draft_id: str):
  settings = request.app.state.settings
  detail = get_project_detail(settings, project_id)
  try:
    payload = apply_self_evolution_draft(settings, Path(detail.path), draft_id)
  except FileNotFoundError:
    raise HTTPException(
      status_code=404,
      detail={"code": "self_evolution_draft_not_found", "message": "自学习草案不存在"},
    ) from None
  except ValueError as error:
    raise HTTPException(
      status_code=400,
      detail={"code": "self_evolution_draft_apply_invalid", "message": str(error)},
    ) from None
  return _self_evolution_action_response(settings, detail, payload, "自学习草案应用")


@router.put("/{project_id}/chapters/{chapter_id}")
def put_project_chapter(
  request: Request,
  project_id: str,
  chapter_id: str,
  chapter_request: ChapterUpdateRequest,
):
  settings = request.app.state.settings
  detail, review_error = update_chapter_content_with_review_status(settings, project_id, chapter_id, chapter_request)
  return _chapter_mutation_response(settings, detail, review_error)


@router.post("/{project_id}/chapters/{chapter_id}/review")
def post_project_chapter_review(
  request: Request,
  project_id: str,
  chapter_id: str,
  review_request: ChapterReviewRefreshRequest,
):
  settings = request.app.state.settings
  detail, review_error = refresh_chapter_review(settings, project_id, chapter_id, review_request)
  return _chapter_mutation_response(settings, detail, review_error)


@router.get("/{project_id}/knowledge/search")
def get_project_knowledge_search(
  request: Request,
  project_id: str,
  q: str = Query(min_length=1, max_length=120),
  limit: int = Query(default=8, ge=1, le=20),
  chapter_index: int = Query(default=0, ge=0),
):
  settings = request.app.state.settings
  payload = [
    item.model_dump(mode="json")
    for item in search_project_knowledge(settings, project_id, q, limit, chapter_index=chapter_index)
  ]
  return {"ok": True, "data": payload}


@router.get("/{project_id}/research/historical")
def get_project_historical_research(
  request: Request,
  project_id: str,
  q: str = Query(min_length=1, max_length=160),
  limit: int = Query(default=8, ge=1, le=12),
  chapter_index: int = Query(default=0, ge=0),
):
  require_valid_license(request)
  settings = request.app.state.settings
  payload = research_historical_reference(settings, project_id, q, limit, chapter_index=chapter_index).model_dump(mode="json")
  return {"ok": True, "data": payload}


@router.post("/{project_id}/knowledge/import")
def post_project_knowledge_import(
  request: Request,
  project_id: str,
  knowledge_request: KnowledgeImportRequest,
):
  settings = request.app.state.settings
  payload = import_project_knowledge(settings, project_id, knowledge_request).model_dump(mode="json")
  return {"ok": True, "data": payload}


@router.post("/{project_id}/knowledge/import-files")
def post_project_knowledge_import_files(
  request: Request,
  project_id: str,
  file_request: ImportedFileBatchRequest,
):
  settings = request.app.state.settings
  payload = import_project_knowledge(
    settings,
    project_id,
    KnowledgeImportRequest(items=imported_files_to_knowledge_items(file_request, settings=settings)),
  ).model_dump(mode="json")
  return {"ok": True, "data": payload}


@router.get("/{project_id}/obsidian")
def get_project_obsidian(request: Request, project_id: str):
  settings = request.app.state.settings
  payload = get_project_obsidian_state(settings, project_id).model_dump(mode="json")
  return {"ok": True, "data": payload}


@router.put("/{project_id}/obsidian")
def put_project_obsidian(
  request: Request,
  project_id: str,
  obsidian_request: ObsidianVaultConfig,
):
  settings = request.app.state.settings
  detail = update_project_obsidian_config(settings, project_id, obsidian_request)
  payload = {
    "ok": True,
    "data": detail.model_dump(mode="json"),
  }
  meta = _self_evolution_meta(settings, detail, "Obsidian 配置保存")
  if meta:
    payload["meta"] = meta
  return payload


@router.post("/{project_id}/obsidian/sync")
def post_project_obsidian_sync(request: Request, project_id: str):
  settings = request.app.state.settings
  detail = sync_project_obsidian(settings, project_id)
  payload = {
    "ok": True,
    "data": detail.model_dump(mode="json"),
  }
  meta = _self_evolution_meta(settings, detail, "Obsidian 同步")
  if meta:
    payload["meta"] = meta
  return payload


@router.post("/{project_id}/obsidian/maintenance/stage-batch")
def post_project_obsidian_maintenance_stage_batch(
  request: Request,
  project_id: str,
  payload: dict[str, object] | None = Body(default=None),
):
  settings = request.app.state.settings
  suggestion_ids_payload = (payload or {}).get("suggestion_ids")
  suggestion_ids = [
    str(item or "").strip()
    for item in suggestion_ids_payload
    if str(item or "").strip()
  ] if isinstance(suggestion_ids_payload, list) else None
  try:
    limit = int((payload or {}).get("limit") or 80)
  except (TypeError, ValueError):
    limit = 80
  result = stage_project_obsidian_maintenance_drafts(
    settings,
    project_id,
    suggestion_ids=suggestion_ids,
    limit=limit,
  )
  return _project_action_response(settings, project_id, result, "Obsidian 维护动作")


@router.post("/{project_id}/obsidian/maintenance/publish-batch")
def post_project_obsidian_maintenance_publish_batch(
  request: Request,
  project_id: str,
  payload: dict[str, object] | None = Body(default=None),
):
  settings = request.app.state.settings
  suggestion_ids_payload = (payload or {}).get("suggestion_ids")
  suggestion_ids = [
    str(item or "").strip()
    for item in suggestion_ids_payload
    if str(item or "").strip()
  ] if isinstance(suggestion_ids_payload, list) else None
  try:
    limit = int((payload or {}).get("limit") or 80)
  except (TypeError, ValueError):
    limit = 80
  result = publish_project_obsidian_maintenance_notes(
    settings,
    project_id,
    suggestion_ids=suggestion_ids,
    limit=limit,
  )
  return _project_action_response(settings, project_id, result, "Obsidian 维护动作")


@router.post("/{project_id}/obsidian/maintenance/confirm-merge-batch")
def post_project_obsidian_maintenance_confirm_merge_batch(
  request: Request,
  project_id: str,
  payload: dict[str, object] | None = Body(default=None),
):
  settings = request.app.state.settings
  suggestion_ids_payload = (payload or {}).get("suggestion_ids")
  suggestion_ids = [
    str(item or "").strip()
    for item in suggestion_ids_payload
    if str(item or "").strip()
  ] if isinstance(suggestion_ids_payload, list) else None
  try:
    limit = int((payload or {}).get("limit") or 80)
  except (TypeError, ValueError):
    limit = 80
  result = confirm_project_obsidian_maintenance_merges(
    settings,
    project_id,
    suggestion_ids=suggestion_ids,
    limit=limit,
  )
  return _project_action_response(settings, project_id, result, "Obsidian 维护动作")


@router.post("/{project_id}/obsidian/maintenance/ignore-batch")
def post_project_obsidian_maintenance_ignore_batch(
  request: Request,
  project_id: str,
  payload: dict[str, object] | None = Body(default=None),
):
  settings = request.app.state.settings
  suggestion_ids_payload = (payload or {}).get("suggestion_ids")
  suggestion_ids = [
    str(item or "").strip()
    for item in suggestion_ids_payload
    if str(item or "").strip()
  ] if isinstance(suggestion_ids_payload, list) else None
  try:
    limit = int((payload or {}).get("limit") or 80)
  except (TypeError, ValueError):
    limit = 80
  result = ignore_project_obsidian_maintenance_notes(
    settings,
    project_id,
    suggestion_ids=suggestion_ids,
    limit=limit,
  )
  return _project_action_response(settings, project_id, result, "Obsidian 维护动作")


@router.post("/{project_id}/obsidian/maintenance/reopen-batch")
def post_project_obsidian_maintenance_reopen_batch(
  request: Request,
  project_id: str,
  payload: dict[str, object] | None = Body(default=None),
):
  settings = request.app.state.settings
  suggestion_ids_payload = (payload or {}).get("suggestion_ids")
  suggestion_ids = [
    str(item or "").strip()
    for item in suggestion_ids_payload
    if str(item or "").strip()
  ] if isinstance(suggestion_ids_payload, list) else None
  try:
    limit = int((payload or {}).get("limit") or 80)
  except (TypeError, ValueError):
    limit = 80
  result = reopen_project_obsidian_maintenance_notes(
    settings,
    project_id,
    suggestion_ids=suggestion_ids,
    limit=limit,
  )
  return _project_action_response(settings, project_id, result, "Obsidian 维护动作")


@router.post("/{project_id}/obsidian/maintenance/{suggestion_id}/stage")
def post_project_obsidian_maintenance_stage(request: Request, project_id: str, suggestion_id: str):
  settings = request.app.state.settings
  try:
    payload = stage_project_obsidian_maintenance_draft(settings, project_id, suggestion_id)
  except FileNotFoundError:
    raise HTTPException(
      status_code=404,
      detail={"code": "obsidian_maintenance_suggestion_not_found", "message": "Obsidian 维护建议不存在"},
    ) from None
  except ValueError as error:
    raise HTTPException(
      status_code=400,
      detail={"code": "obsidian_maintenance_suggestion_invalid", "message": str(error)},
    ) from None
  return _project_action_response(settings, project_id, payload, "Obsidian 维护动作")


@router.post("/{project_id}/obsidian/maintenance/{suggestion_id}/publish")
def post_project_obsidian_maintenance_publish(request: Request, project_id: str, suggestion_id: str):
  settings = request.app.state.settings
  try:
    payload = publish_project_obsidian_maintenance_note(settings, project_id, suggestion_id)
  except FileNotFoundError:
    raise HTTPException(
      status_code=404,
      detail={"code": "obsidian_maintenance_suggestion_not_found", "message": "Obsidian 维护建议不存在"},
    ) from None
  except ValueError as error:
    raise HTTPException(
      status_code=400,
      detail={"code": "obsidian_maintenance_suggestion_invalid", "message": str(error)},
    ) from None
  return _project_action_response(settings, project_id, payload, "Obsidian 维护动作")


@router.post("/{project_id}/obsidian/maintenance/{suggestion_id}/confirm-merge")
def post_project_obsidian_maintenance_confirm_merge(request: Request, project_id: str, suggestion_id: str):
  settings = request.app.state.settings
  try:
    payload = confirm_project_obsidian_maintenance_merge(settings, project_id, suggestion_id)
  except FileNotFoundError:
    raise HTTPException(
      status_code=404,
      detail={"code": "obsidian_maintenance_suggestion_not_found", "message": "Obsidian 维护建议不存在"},
    ) from None
  except ValueError as error:
    raise HTTPException(
      status_code=400,
      detail={"code": "obsidian_maintenance_suggestion_invalid", "message": str(error)},
    ) from None
  return _project_action_response(settings, project_id, payload, "Obsidian 维护动作")


@router.post("/{project_id}/obsidian/maintenance/{suggestion_id}/ignore")
def post_project_obsidian_maintenance_ignore(request: Request, project_id: str, suggestion_id: str):
  settings = request.app.state.settings
  try:
    payload = ignore_project_obsidian_maintenance_note(settings, project_id, suggestion_id)
  except FileNotFoundError:
    raise HTTPException(
      status_code=404,
      detail={"code": "obsidian_maintenance_suggestion_not_found", "message": "Obsidian 维护建议不存在"},
    ) from None
  return _project_action_response(settings, project_id, payload, "Obsidian 维护动作")


@router.post("/{project_id}/obsidian/maintenance/{suggestion_id}/reopen")
def post_project_obsidian_maintenance_reopen(request: Request, project_id: str, suggestion_id: str):
  settings = request.app.state.settings
  try:
    payload = reopen_project_obsidian_maintenance_note(settings, project_id, suggestion_id)
  except FileNotFoundError:
    raise HTTPException(
      status_code=404,
      detail={"code": "obsidian_maintenance_suggestion_not_found", "message": "Obsidian 维护建议不存在"},
    ) from None
  except ValueError as error:
    raise HTTPException(
      status_code=400,
      detail={"code": "obsidian_maintenance_suggestion_invalid", "message": str(error)},
    ) from None
  return _project_action_response(settings, project_id, payload, "Obsidian 维护动作")


@router.put("/{project_id}/architecture/workspace")
def put_project_architecture_workspace(
  request: Request,
  project_id: str,
  workspace_request: ArchitectureWorkspaceApplyRequest,
):
  settings = request.app.state.settings
  payload = apply_architecture_workspace(settings, project_id, workspace_request).model_dump(mode="json")
  return {"ok": True, "data": payload}


@router.post("/{project_id}/snapshots")
async def post_project_snapshot(
  request: Request,
  project_id: str,
  snapshot_request: SnapshotCreateRequest,
):
  settings = request.app.state.settings
  payload = create_project_snapshot(settings, project_id, snapshot_request).model_dump(mode="json")
  return JSONResponse(
    status_code=status.HTTP_201_CREATED,
    content={"ok": True, "data": payload},
  )


@router.post("/{project_id}/autosave")
async def post_project_autosave(request: Request, project_id: str):
  settings = request.app.state.settings
  payload = auto_save_project_snapshot(settings, project_id).model_dump(mode="json")
  return {"ok": True, "data": payload}


@router.get("/{project_id}/snapshots/{snapshot_id}")
async def get_project_snapshot(request: Request, project_id: str, snapshot_id: str):
  settings = request.app.state.settings
  payload = get_project_snapshot_detail(settings, project_id, snapshot_id).model_dump(mode="json")
  return {"ok": True, "data": payload}


@router.post("/{project_id}/snapshots/{snapshot_id}/restore")
async def post_restore_project_snapshot(
  request: Request,
  project_id: str,
  snapshot_id: str,
  restore_request: SnapshotRestoreRequest | None = None,
):
  settings = request.app.state.settings
  payload = restore_project_snapshot(settings, project_id, snapshot_id, restore_request).model_dump(mode="json")
  return {"ok": True, "data": payload}


@router.get("/{project_id}/events")
async def get_project_events(request: Request, project_id: str):
  watcher = getattr(request.app.state, "project_history_watcher", None)
  if watcher is None:
    raise HTTPException(
      status_code=503,
      detail={"code": "history_watch_unavailable", "message": "本地版本监听服务尚未启动"},
    )

  queue = watcher.subscribe(project_id)

  async def stream():
    try:
      yield encode_sse("ready", {"project_id": project_id})
      while True:
        if await request.is_disconnected():
          break

        try:
          event = await asyncio.wait_for(queue.get(), timeout=15)
        except TimeoutError:
          yield encode_sse("ping", {"project_id": project_id})
          continue

        yield encode_sse(str(event["event"]), event["data"])
    finally:
      watcher.unsubscribe(project_id, queue)

  return StreamingResponse(
    stream(),
    media_type="text/event-stream",
    headers={
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  )
