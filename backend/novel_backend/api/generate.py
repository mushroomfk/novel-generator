from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from novel_backend.api.license_guard import require_valid_license
from novel_backend.models import ArchitectureRequest, ArchitectureStepRequest, ChapterWorkflowRequest
from novel_backend.services.generation_service import architecture_step_stream, architecture_stream, chapter_workflow_stream

router = APIRouter(prefix="/api/generate", tags=["generate"])


@router.post("/architecture/stream")
async def stream_architecture(request: Request, payload: ArchitectureRequest):
  require_valid_license(request)
  settings = request.app.state.settings
  return StreamingResponse(
    architecture_stream(settings, payload),
    media_type="text/event-stream",
    headers={
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  )


@router.post("/architecture/step/stream")
async def stream_architecture_step(request: Request, payload: ArchitectureStepRequest):
  require_valid_license(request)
  settings = request.app.state.settings
  return StreamingResponse(
    architecture_step_stream(settings, payload),
    media_type="text/event-stream",
    headers={
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  )


@router.post("/chapter-workflow/stream")
async def stream_chapter_workflow(request: Request, payload: ChapterWorkflowRequest):
  require_valid_license(request)
  settings = request.app.state.settings
  return StreamingResponse(
    chapter_workflow_stream(settings, payload),
    media_type="text/event-stream",
    headers={
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  )
