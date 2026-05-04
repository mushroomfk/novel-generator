from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from novel_backend.models import (
  AgentThreadStoreUpdateRequest,
  ArchitectureWorkspaceApplyRequest,
  ChapterReviewRefreshRequest,
  ChapterUpdateRequest,
  CreateProjectRequest,
  ImportedFileBatchRequest,
  ProjectDreamPromoteRequest,
  ProjectDreamRunRequest,
  ProjectRenameRequest,
  KnowledgeImportRequest,
  ProjectMemoryUpdateRequest,
  ProjectExportRequest,
  SnapshotCreateRequest,
  SnapshotRestoreRequest,
  StoryDocumentBatchUpdateRequest,
  StoryDocumentUpdateRequest,
)
from novel_backend.services.import_service import imported_files_to_knowledge_items
from novel_backend.services.project_service import (
  apply_architecture_workspace,
  auto_save_project_snapshot,
  create_project,
  create_project_snapshot,
  delete_project,
  export_project_book,
  get_project_agent_threads,
  get_project_snapshot_detail,
  get_project_detail,
  import_project_knowledge,
  list_projects,
  open_project_directory,
  promote_project_dream,
  rename_project,
  restore_project_snapshot,
  run_project_dream,
  search_project_knowledge,
  save_project_agent_threads,
  refresh_chapter_review,
  update_chapter_content,
  update_chapter_content_with_review_status,
  update_project_memory,
  update_story_documents,
  update_story_document,
)
from novel_backend.services.web_research_service import research_historical_reference
from novel_backend.utils.sse import encode_sse

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _chapter_mutation_response(detail, review_error: str = ""):
  payload = {
    "ok": True,
    "data": detail.model_dump(mode="json"),
  }
  if review_error:
    payload["meta"] = {
      "review_error": review_error,
    }
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


@router.get("/{project_id}")
def get_project(request: Request, project_id: str):
  settings = request.app.state.settings
  payload = get_project_detail(settings, project_id).model_dump(mode="json")
  return {"ok": True, "data": payload}


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


@router.put("/{project_id}/chapters/{chapter_id}")
def put_project_chapter(
  request: Request,
  project_id: str,
  chapter_id: str,
  chapter_request: ChapterUpdateRequest,
):
  settings = request.app.state.settings
  detail, review_error = update_chapter_content_with_review_status(settings, project_id, chapter_id, chapter_request)
  return _chapter_mutation_response(detail, review_error)


@router.post("/{project_id}/chapters/{chapter_id}/review")
def post_project_chapter_review(
  request: Request,
  project_id: str,
  chapter_id: str,
  review_request: ChapterReviewRefreshRequest,
):
  settings = request.app.state.settings
  detail, review_error = refresh_chapter_review(settings, project_id, chapter_id, review_request)
  return _chapter_mutation_response(detail, review_error)


@router.get("/{project_id}/knowledge/search")
def get_project_knowledge_search(
  request: Request,
  project_id: str,
  q: str = Query(min_length=1, max_length=120),
  limit: int = Query(default=8, ge=1, le=20),
):
  settings = request.app.state.settings
  payload = [item.model_dump(mode="json") for item in search_project_knowledge(settings, project_id, q, limit)]
  return {"ok": True, "data": payload}


@router.get("/{project_id}/research/historical")
def get_project_historical_research(
  request: Request,
  project_id: str,
  q: str = Query(min_length=1, max_length=160),
  limit: int = Query(default=8, ge=1, le=12),
):
  settings = request.app.state.settings
  payload = research_historical_reference(settings, project_id, q, limit).model_dump(mode="json")
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
