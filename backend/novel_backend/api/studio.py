from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from novel_backend.api.license_guard import require_valid_license
from novel_backend.models import (
  AgentChatRequest,
  BatchGenerateRequest,
  BlueprintGenerateRequest,
  BrainstormRequest,
  CharacterReplicaProfileSaveRequest,
  CharacterReplicaRequest,
  ChapterGenerateRequest,
  ChapterRewriteRequest,
  ConsistencyCheckRequest,
  ContinueProjectRequest,
  ImportedFileBatchRequest,
  PromptPresetCreateRequest,
  PromptPresetUpdateRequest,
  SkillMaterializeRequest,
  SkillPackageImportRequest,
  StyleAnalyzeRequest,
  StyleCalibrateRequest,
  StyleDNAAnalyzeRequest,
  StyleMergeRequest,
  StyleReferenceImportRequest,
  StyleSaveRequest,
  ToolFileContentRequest,
  XPPresetCreateRequest,
  XPPresetUpdateRequest,
)
from novel_backend.services.agent_service import agent_session_stream
from novel_backend.services.agent_workflow_service import request_agent_workflow_interrupt, workflow_summary
from novel_backend.services.character_replica_profile_service import (
  delete_character_replica_profile,
  get_character_replica_profile,
  list_character_replica_profiles,
  save_character_replica_profile,
)
from novel_backend.services.file_service import list_project_files, read_project_file, write_project_file
from novel_backend.services.import_service import imported_files_to_knowledge_items
from novel_backend.services.log_service import (
  clear_app_log,
  clear_prompt_history,
  get_app_log_tail,
  get_prompt_history_records,
)
from novel_backend.services.model_runtime_service import get_model_runtime_state
from novel_backend.services.agent_trajectory_service import get_agent_trajectory_records
from novel_backend.services.preset_service import (
  activate_prompt_preset,
  create_prompt_preset,
  create_xp_preset,
  delete_prompt_preset,
  delete_xp_preset,
  get_prompt_preset,
  list_prompt_presets,
  list_xp_presets,
  update_prompt_preset,
  update_xp_preset,
)
from novel_backend.services.project_service import get_project_detail
from novel_backend.services.self_evolution_service import get_self_evolution_state
from novel_backend.services.skill_service import (
  get_skill_curation_report,
  list_skill_catalog,
  list_skill_versions,
  export_skill_package,
  import_skill_package,
  materialize_skill,
  promote_skill_to_global,
  rollback_skill_version,
)
from novel_backend.services.style_service import (
  clear_style_references,
  delete_style,
  get_style,
  import_style_references,
  list_styles,
  rollback_style_calibration,
  search_style_references,
  save_style,
)
from novel_backend.services.studio_service import (
  batch_generate_stream,
  blueprint_stream,
  brainstorm_stream,
  character_replica_stream,
  chapter_generate_prompt_preview,
  chapter_generate_stream,
  chapter_rewrite_stream,
  consistency_stream,
  continue_project_stream,
  style_analyze_dna_stream,
  style_analyze_stream,
  style_calibrate_narrative_stream,
  style_calibrate_stream,
  style_merge_stream,
)

router = APIRouter(prefix="/api/studio", tags=["studio"])


def _stream_response(stream):
  return StreamingResponse(
    stream,
    media_type="text/event-stream",
    headers={
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  )


@router.get("/skills")
def get_skill_catalog(request: Request):
  settings = request.app.state.settings
  return {"ok": True, "data": list_skill_catalog(settings).model_dump(mode="json")}


@router.post("/skills/materialize")
def post_materialize_skill(request: Request, payload: SkillMaterializeRequest):
  settings = request.app.state.settings
  return {"ok": True, "data": materialize_skill(settings, payload).model_dump(mode="json")}


@router.post("/skills/import-package")
def post_skill_package_import(request: Request, payload: SkillPackageImportRequest):
  settings = request.app.state.settings
  return {"ok": True, "data": import_skill_package(settings, payload)}


@router.get("/skills/{skill_id}/versions")
def get_skill_versions(request: Request, skill_id: str):
  settings = request.app.state.settings
  return {"ok": True, "data": list_skill_versions(settings, skill_id)}


@router.get("/skills/{skill_id}/package")
def get_skill_package(request: Request, skill_id: str):
  settings = request.app.state.settings
  return {"ok": True, "data": export_skill_package(settings, skill_id)}


@router.post("/skills/{skill_id}/versions/{version_id}/rollback")
def post_skill_version_rollback(request: Request, skill_id: str, version_id: str):
  settings = request.app.state.settings
  return {"ok": True, "data": rollback_skill_version(settings, skill_id, version_id)}


@router.post("/skills/{skill_id}/promote-global")
def post_skill_promote_global(request: Request, skill_id: str):
  settings = request.app.state.settings
  return {"ok": True, "data": promote_skill_to_global(settings, skill_id)}


@router.get("/skills/curation")
def get_skills_curation(request: Request):
  settings = request.app.state.settings
  return {"ok": True, "data": get_skill_curation_report(settings).model_dump(mode="json")}


@router.get("/self-evolution")
def get_self_evolution(
  request: Request,
  project_id: str = Query(..., min_length=1, max_length=120),
):
  settings = request.app.state.settings
  detail = get_project_detail(settings, project_id)
  return {"ok": True, "data": get_self_evolution_state(settings, Path(detail.path), detail)}


@router.get("/model-runtime")
def get_model_runtime(request: Request):
  settings = request.app.state.settings
  return {"ok": True, "data": get_model_runtime_state(settings)}


@router.post("/brainstorm/stream")
async def stream_brainstorm(request: Request, payload: BrainstormRequest):
  require_valid_license(request)
  return _stream_response(brainstorm_stream(request.app.state.settings, payload))


@router.post("/agent/stream")
async def stream_agent_session(request: Request, payload: AgentChatRequest):
  require_valid_license(request)
  return _stream_response(agent_session_stream(request.app.state.settings, payload))


@router.get("/agent/{project_id}/runs/{task_id}")
def get_agent_workflow_run(request: Request, project_id: str, task_id: str):
  require_valid_license(request)
  settings = request.app.state.settings
  project = get_project_detail(settings, project_id)
  return {"ok": True, "data": workflow_summary(Path(project.path), task_id)}


@router.post("/agent/{project_id}/runs/{task_id}/interrupt")
def interrupt_agent_workflow_run(request: Request, project_id: str, task_id: str):
  require_valid_license(request)
  settings = request.app.state.settings
  project = get_project_detail(settings, project_id)
  request_agent_workflow_interrupt(Path(project.path), task_id)
  return {"ok": True, "data": workflow_summary(Path(project.path), task_id)}


@router.post("/character-replica/stream")
async def stream_character_replica(request: Request, payload: CharacterReplicaRequest):
  require_valid_license(request)
  return _stream_response(character_replica_stream(request.app.state.settings, payload))


@router.get("/character-replica-profiles")
def get_character_replica_profiles(request: Request):
  settings = request.app.state.settings
  payload = [item.model_dump(mode="json") for item in list_character_replica_profiles(settings)]
  return {"ok": True, "data": payload}


@router.get("/character-replica-profiles/{name}")
def get_character_replica_profile_detail(request: Request, name: str):
  settings = request.app.state.settings
  return {"ok": True, "data": get_character_replica_profile(settings, name).model_dump(mode="json")}


@router.put("/character-replica-profiles/{name}")
def put_character_replica_profile(request: Request, name: str, payload: CharacterReplicaProfileSaveRequest):
  settings = request.app.state.settings
  return {"ok": True, "data": save_character_replica_profile(settings, name, payload).model_dump(mode="json")}


@router.delete("/character-replica-profiles/{name}")
def remove_character_replica_profile(request: Request, name: str):
  settings = request.app.state.settings
  delete_character_replica_profile(settings, name)
  return {"ok": True, "data": {"message": "人物卡已删除"}}


@router.post("/consistency/stream")
async def stream_consistency(request: Request, payload: ConsistencyCheckRequest):
  require_valid_license(request)
  return _stream_response(consistency_stream(request.app.state.settings, payload))


@router.post("/blueprint/stream")
async def stream_blueprint(request: Request, payload: BlueprintGenerateRequest):
  require_valid_license(request)
  return _stream_response(blueprint_stream(request.app.state.settings, payload))


@router.post("/chapter-generate/stream")
async def stream_chapter_generate(request: Request, payload: ChapterGenerateRequest):
  require_valid_license(request)
  return _stream_response(chapter_generate_stream(request.app.state.settings, payload))


@router.post("/chapter-generate/prompt-preview")
async def preview_chapter_generate_prompt(request: Request, payload: ChapterGenerateRequest):
  require_valid_license(request)
  return {"ok": True, "data": chapter_generate_prompt_preview(request.app.state.settings, payload).model_dump(mode="json")}


@router.post("/chapter-finalize/stream")
async def stream_chapter_finalize(request: Request, payload: ChapterRewriteRequest):
  require_valid_license(request)
  return _stream_response(chapter_rewrite_stream(request.app.state.settings, payload, "finalize"))


@router.post("/chapter-polish/stream")
async def stream_chapter_polish(request: Request, payload: ChapterRewriteRequest):
  require_valid_license(request)
  return _stream_response(chapter_rewrite_stream(request.app.state.settings, payload, "polish"))


@router.post("/chapter-humanize/stream")
async def stream_chapter_humanize(request: Request, payload: ChapterRewriteRequest):
  require_valid_license(request)
  return _stream_response(chapter_rewrite_stream(request.app.state.settings, payload, "humanize"))


@router.post("/batch-generate/stream")
async def stream_batch_generate(request: Request, payload: BatchGenerateRequest):
  require_valid_license(request)
  return _stream_response(batch_generate_stream(request.app.state.settings, payload))


@router.post("/continue-project/stream")
async def stream_continue_project(request: Request, payload: ContinueProjectRequest):
  require_valid_license(request)
  return _stream_response(continue_project_stream(request.app.state.settings, payload))


@router.post("/styles/analyze/stream")
async def stream_style_analyze(request: Request, payload: StyleAnalyzeRequest):
  require_valid_license(request)
  return _stream_response(style_analyze_stream(request.app.state.settings, payload))


@router.post("/styles/analyze-dna/stream")
async def stream_style_analyze_dna(request: Request, payload: StyleDNAAnalyzeRequest):
  require_valid_license(request)
  return _stream_response(style_analyze_dna_stream(request.app.state.settings, payload))


@router.post("/styles/calibrate/stream")
async def stream_style_calibrate(request: Request, payload: StyleCalibrateRequest):
  require_valid_license(request)
  return _stream_response(style_calibrate_stream(request.app.state.settings, payload))


@router.post("/styles/calibrate-narrative/stream")
async def stream_style_calibrate_narrative(request: Request, payload: StyleCalibrateRequest):
  require_valid_license(request)
  return _stream_response(style_calibrate_narrative_stream(request.app.state.settings, payload))


@router.post("/styles/merge/stream")
async def stream_style_merge(request: Request, payload: StyleMergeRequest):
  require_valid_license(request)
  return _stream_response(style_merge_stream(request.app.state.settings, payload))


@router.get("/logs")
def get_logs(request: Request, tail: int = Query(default=200, ge=1, le=5000)):
  settings = request.app.state.settings
  return {"ok": True, "data": {"content": get_app_log_tail(settings, tail=tail)}}


@router.delete("/logs")
def delete_logs(request: Request):
  settings = request.app.state.settings
  return {"ok": True, "data": {"message": clear_app_log(settings)}}


@router.get("/prompt-history")
def get_prompt_history(
  request: Request,
  tail: int = Query(default=50, ge=1, le=500),
  search: str = Query(default="", max_length=120),
):
  settings = request.app.state.settings
  return {"ok": True, "data": get_prompt_history_records(settings, tail=tail, search=search)}


@router.get("/agent-trajectories")
def get_agent_trajectories(
  request: Request,
  tail: int = Query(default=50, ge=1, le=500),
  search: str = Query(default="", max_length=120),
):
  settings = request.app.state.settings
  return {"ok": True, "data": get_agent_trajectory_records(settings, tail=tail, search=search)}


@router.delete("/prompt-history")
def delete_prompt_history(request: Request):
  settings = request.app.state.settings
  return {"ok": True, "data": {"message": clear_prompt_history(settings)}}


@router.get("/prompt-presets")
def get_prompt_presets(request: Request):
  settings = request.app.state.settings
  return {"ok": True, "data": list_prompt_presets(settings)}


@router.post("/prompt-presets")
def post_prompt_preset(request: Request, payload: PromptPresetCreateRequest):
  settings = request.app.state.settings
  return {"ok": True, "data": create_prompt_preset(settings, payload).model_dump(mode="json")}


@router.get("/prompt-presets/{name}")
def get_prompt_preset_detail(request: Request, name: str):
  settings = request.app.state.settings
  return {"ok": True, "data": get_prompt_preset(settings, name).model_dump(mode="json")}


@router.put("/prompt-presets/{name}")
def put_prompt_preset(request: Request, name: str, payload: PromptPresetUpdateRequest):
  settings = request.app.state.settings
  return {"ok": True, "data": update_prompt_preset(settings, name, payload).model_dump(mode="json")}


@router.delete("/prompt-presets/{name}")
def remove_prompt_preset(request: Request, name: str):
  settings = request.app.state.settings
  delete_prompt_preset(settings, name)
  return {"ok": True, "data": {"message": "提示词方案已删除"}}


@router.post("/prompt-presets/{name}/activate")
def post_activate_prompt_preset(request: Request, name: str):
  settings = request.app.state.settings
  return {"ok": True, "data": activate_prompt_preset(settings, name)}


@router.get("/xp-presets")
def get_xp_presets(request: Request):
  settings = request.app.state.settings
  payload = [item.model_dump(mode="json") for item in list_xp_presets(settings)]
  return {"ok": True, "data": payload}


@router.post("/xp-presets")
def post_xp_preset(request: Request, payload: XPPresetCreateRequest):
  settings = request.app.state.settings
  return {"ok": True, "data": create_xp_preset(settings, payload).model_dump(mode="json")}


@router.put("/xp-presets/{name}")
def put_xp_preset(request: Request, name: str, payload: XPPresetUpdateRequest):
  settings = request.app.state.settings
  return {"ok": True, "data": update_xp_preset(settings, name, payload).model_dump(mode="json")}


@router.delete("/xp-presets/{name}")
def remove_xp_preset(request: Request, name: str):
  settings = request.app.state.settings
  delete_xp_preset(settings, name)
  return {"ok": True, "data": {"message": "XP 预设已删除"}}


@router.get("/styles")
def get_styles(request: Request):
  settings = request.app.state.settings
  payload = [item.model_dump(mode="json") for item in list_styles(settings)]
  return {"ok": True, "data": payload}


@router.get("/styles/{name}")
def get_style_detail(request: Request, name: str):
  settings = request.app.state.settings
  return {"ok": True, "data": get_style(settings, name).model_dump(mode="json")}


@router.put("/styles/{name}")
def put_style(request: Request, name: str, payload: StyleSaveRequest):
  settings = request.app.state.settings
  return {"ok": True, "data": save_style(settings, name, payload).model_dump(mode="json")}


@router.delete("/styles/{name}")
def remove_style(request: Request, name: str):
  settings = request.app.state.settings
  delete_style(settings, name)
  return {"ok": True, "data": {"message": "文风已删除"}}


@router.post("/styles/{name}/rollback-calibration")
def post_style_rollback_calibration(request: Request, name: str):
  settings = request.app.state.settings
  return {"ok": True, "data": rollback_style_calibration(settings, name).model_dump(mode="json")}


@router.post("/styles/{name}/references")
def post_style_references(request: Request, name: str, payload: StyleReferenceImportRequest):
  settings = request.app.state.settings
  return {"ok": True, "data": import_style_references(settings, name, payload).model_dump(mode="json")}


@router.post("/styles/{name}/references/import-files")
def post_style_reference_files(request: Request, name: str, payload: ImportedFileBatchRequest):
  settings = request.app.state.settings
  items = imported_files_to_knowledge_items(payload, settings=settings)
  return {
    "ok": True,
    "data": import_style_references(
      settings,
      name,
      StyleReferenceImportRequest(
        items=[
          {"title": item.title, "content": item.content}
          for item in items
        ]
      ),
    ).model_dump(mode="json"),
  }


@router.get("/styles/{name}/references/search")
def get_style_reference_hits(
  request: Request,
  name: str,
  q: str = Query(default="", max_length=300),
  limit: int = Query(default=6, ge=1, le=20),
):
  settings = request.app.state.settings
  payload = [item.model_dump(mode="json") for item in search_style_references(settings, name, q, limit)]
  return {"ok": True, "data": payload}


@router.delete("/styles/{name}/references")
def delete_style_references(request: Request, name: str):
  settings = request.app.state.settings
  return {"ok": True, "data": clear_style_references(settings, name).model_dump(mode="json")}


@router.get("/projects/{project_id}/files")
def get_project_tool_files(request: Request, project_id: str):
  settings = request.app.state.settings
  payload = [item.model_dump(mode="json") for item in list_project_files(settings, project_id)]
  return {"ok": True, "data": payload}


@router.get("/projects/{project_id}/files/content")
def get_project_tool_file_content(
  request: Request,
  project_id: str,
  path: str = Query(min_length=1, max_length=300),
):
  settings = request.app.state.settings
  return {"ok": True, "data": read_project_file(settings, project_id, path)}


@router.put("/projects/{project_id}/files/content")
def put_project_tool_file_content(
  request: Request,
  project_id: str,
  payload: ToolFileContentRequest,
  path: str = Query(min_length=1, max_length=300),
):
  settings = request.app.state.settings
  return {"ok": True, "data": write_project_file(settings, project_id, path, payload.content)}
