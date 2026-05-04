from __future__ import annotations

from pydantic import BaseModel, Field


KNOWLEDGE_IMPORT_CONTENT_MAX_LENGTH = 200_000
KNOWLEDGE_IMPORT_ITEM_MAX_COUNT = 400


class ApiError(BaseModel):
  code: str
  message: str


class ModelConfig(BaseModel):
  provider: str = "aliyun-bailian"
  base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
  api_key: str = ""
  model_name: str = "qwen3.6-plus"
  max_tokens: int = Field(default=8192, ge=256, le=64000)
  temperature: float = Field(default=0.8, ge=0.0, le=2.0)


class EmbeddingConfig(BaseModel):
  provider: str = "aliyun-bailian"
  base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
  api_key: str = ""
  model_name: str = "text-embedding-v4"
  dimensions: int | None = Field(default=2048, ge=64, le=4096)
  retrieval_k: int = Field(default=6, ge=1, le=20)
  batch_size: int = Field(default=8, ge=1, le=32)


class AppConfig(BaseModel):
  model: ModelConfig = Field(default_factory=ModelConfig)
  embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
  updated_at: str


class AppConfigUpdateRequest(BaseModel):
  model: ModelConfig = Field(default_factory=ModelConfig)
  embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)


class HealthPayload(BaseModel):
  status: str
  backend_version: str
  data_dir: str
  started_at: str
  project_count: int


class ProjectSummary(BaseModel):
  id: str
  name: str
  path: str
  genre: str
  target_chapters: int
  target_words: int
  updated_at: str


class ChapterSummary(BaseModel):
  id: str
  index: int
  title: str
  path: str
  exists: bool
  preview: str
  content: str = ""
  updated_at: str | None = None


class SnapshotChapterRef(BaseModel):
  id: str
  index: int
  title: str
  path: str
  status: str = "modified"
  preview: str = ""


class LocalHistoryChangedFile(BaseModel):
  path: str
  status: str


class WorkingTreeStatus(BaseModel):
  clean: bool = True
  changed_count: int = 0
  changed_files: list[LocalHistoryChangedFile] = Field(default_factory=list)
  base_snapshot_version: int | None = None
  base_snapshot_id: str | None = None
  base_snapshot_message: str | None = None
  base_snapshot_created_at: str | None = None


class ProjectSnapshot(BaseModel):
  id: str
  version: int
  kind: str = "manual"
  message: str
  created_at: str
  file_count: int
  changed_count: int
  affected_chapters: list[SnapshotChapterRef] = Field(default_factory=list)


class ProjectSnapshotDetail(ProjectSnapshot):
  changed_files: list[LocalHistoryChangedFile] = Field(default_factory=list)
  preview_chapters: list[ChapterSummary] = Field(default_factory=list)


class LocalHistoryState(BaseModel):
  snapshots: list[ProjectSnapshot] = Field(default_factory=list)
  working_tree: WorkingTreeStatus = Field(default_factory=WorkingTreeStatus)


class StoryDocument(BaseModel):
  key: str
  label: str
  filename: str = ""
  content: str = ""
  updated_at: str | None = None


class KnowledgeSearchResult(BaseModel):
  source: str
  section: str
  preview: str
  score: float = 0.0
  match_type: str = "keyword"


class HistoricalResearchSource(BaseModel):
  title: str = ""
  url: str = ""
  snippet: str = ""
  summary: str = ""
  site: str = ""
  published_at: str = ""
  score: float = 0.0
  provider: str = ""


class HistoricalResearchResult(BaseModel):
  query: str
  provider: str = ""
  answer: str = ""
  sources: list[HistoricalResearchSource] = Field(default_factory=list)
  local_hits: list[KnowledgeSearchResult] = Field(default_factory=list)
  suggestions: list[str] = Field(default_factory=list)
  warning: str = ""


class KnowledgeMaterial(BaseModel):
  title: str
  filename: str
  preview: str = ""
  updated_at: str | None = None


class ProjectMemoryEntry(BaseModel):
  id: str
  title: str = ""
  category: str = Field(default="硬规则", pattern="^(硬规则|偏好|连续性|警告|目标)$")
  content: str
  source: str = Field(default="manual", pattern="^(manual|auto)$")
  updated_at: str | None = None


class ProjectMemoryEntryInput(BaseModel):
  id: str | None = Field(default=None, max_length=40)
  title: str = Field(default="", max_length=80)
  category: str = Field(default="硬规则", pattern="^(硬规则|偏好|连续性|警告|目标)$")
  content: str = Field(min_length=1, max_length=2000)


class ProjectMemoryUpdateRequest(BaseModel):
  entries: list[ProjectMemoryEntryInput] = Field(default_factory=list, max_length=30)


class ProjectDreamCandidate(BaseModel):
  id: str
  title: str = ""
  category: str = Field(default="连续性", pattern="^(硬规则|偏好|连续性|警告|目标)$")
  content: str
  rationale: str = ""
  confidence: float = Field(default=0.0, ge=0.0, le=1.0)
  promoted_at: str | None = None


class ProjectDreamReport(BaseModel):
  engine: str = ""
  generated_at: str | None = None
  source_signature: str = ""
  is_stale: bool = False
  focus: str = ""
  summary: str = ""
  themes: list[str] = Field(default_factory=list)
  insights: list[str] = Field(default_factory=list)
  open_questions: list[str] = Field(default_factory=list)
  memory_candidates: list[ProjectDreamCandidate] = Field(default_factory=list)
  source_chapter_ids: list[str] = Field(default_factory=list)
  source_document_keys: list[str] = Field(default_factory=list)


class ProjectDreamRunRequest(BaseModel):
  focus: str = Field(default="", max_length=1000)


class ProjectDreamPromoteRequest(BaseModel):
  candidate_ids: list[str] = Field(default_factory=list, min_length=1, max_length=10)


class DistilledSourceProfile(BaseModel):
  summary: str = ""
  narrative_rules: list[str] = Field(default_factory=list)
  style_traits: list[str] = Field(default_factory=list)
  core_conflicts: list[str] = Field(default_factory=list)
  character_notes: list[str] = Field(default_factory=list)
  event_notes: list[str] = Field(default_factory=list)
  location_notes: list[str] = Field(default_factory=list)
  prop_notes: list[str] = Field(default_factory=list)
  skill_notes: list[str] = Field(default_factory=list)
  material_notes: list[str] = Field(default_factory=list)


class TaskDistillationPack(BaseModel):
  kind: str = Field(pattern="^(continuation|architecture|imitation|persona)$")
  summary: str = ""
  must_keep: list[str] = Field(default_factory=list)
  execution_focus: list[str] = Field(default_factory=list)
  voice_rules: list[str] = Field(default_factory=list)
  blocked_changes: list[str] = Field(default_factory=list)
  prepared_from: list[str] = Field(default_factory=list)


class ProjectDistillationReport(BaseModel):
  generated_at: str | None = None
  source_signature: str = ""
  is_stale: bool = False
  source_profile: DistilledSourceProfile = Field(default_factory=DistilledSourceProfile)
  packs: list[TaskDistillationPack] = Field(default_factory=list)


class StoryEntityReference(BaseModel):
  name: str
  summary: str = ""
  related_characters: list[str] = Field(default_factory=list)
  chapter_indexes: list[int] = Field(default_factory=list)


class CharacterTimelineEntry(BaseModel):
  id: str
  chapter_id: str | None = None
  chapter_index: int | None = None
  chapter_title: str = ""
  source_label: str = ""
  summary: str = ""
  relations: list[str] = Field(default_factory=list)
  events: list[str] = Field(default_factory=list)
  locations: list[str] = Field(default_factory=list)
  props: list[str] = Field(default_factory=list)
  skills: list[str] = Field(default_factory=list)
  scenes: list[str] = Field(default_factory=list)
  organizations: list[str] = Field(default_factory=list)


class StoryCharacter(BaseModel):
  name: str
  profile: str = ""
  current_state: str = ""
  relationships: list[str] = Field(default_factory=list)
  events: list[str] = Field(default_factory=list)
  locations: list[str] = Field(default_factory=list)
  props: list[str] = Field(default_factory=list)
  skills: list[str] = Field(default_factory=list)
  scenes: list[str] = Field(default_factory=list)
  organizations: list[str] = Field(default_factory=list)
  timeline: list[CharacterTimelineEntry] = Field(default_factory=list)


class ChapterReviewIssue(BaseModel):
  level: str = Field(default="warning", pattern="^(info|warning|critical)$")
  title: str
  detail: str = ""


class ChapterReviewDimension(BaseModel):
  id: str
  label: str
  score: int = Field(default=0, ge=0, le=100)
  status: str = Field(default="watch", pattern="^(good|watch|risk|na)$")
  summary: str = ""
  highlights: list[str] = Field(default_factory=list)
  issues: list[ChapterReviewIssue] = Field(default_factory=list)


class ChapterReviewReport(BaseModel):
  chapter_id: str = Field(min_length=1, max_length=120)
  chapter_index: int = Field(default=1, ge=1, le=1000)
  chapter_title: str = Field(default="", max_length=120)
  version: str = Field(default="complete", max_length=40)
  engine: str = Field(default="", max_length=40)
  status: str = Field(default="watch", pattern="^(good|watch|risk|na)$")
  overall_score: int = Field(default=0, ge=0, le=100)
  summary: str = ""
  highlights: list[str] = Field(default_factory=list)
  suggestions: list[str] = Field(default_factory=list)
  dimensions: list[ChapterReviewDimension] = Field(default_factory=list)
  style_name: str = Field(default="", max_length=80)
  updated_at: str | None = None
  source_signature: str = ""
  is_stale: bool = False


class StoryOverview(BaseModel):
  documents: list[StoryDocument] = Field(default_factory=list)
  knowledge_hits: list[KnowledgeSearchResult] = Field(default_factory=list)
  materials: list[KnowledgeMaterial] = Field(default_factory=list)
  memory_entries: list[ProjectMemoryEntry] = Field(default_factory=list)
  dream_report: ProjectDreamReport | None = None
  distillation_report: ProjectDistillationReport | None = None
  characters: list[StoryCharacter] = Field(default_factory=list)
  events: list[StoryEntityReference] = Field(default_factory=list)
  locations: list[StoryEntityReference] = Field(default_factory=list)
  props: list[StoryEntityReference] = Field(default_factory=list)
  skills: list[StoryEntityReference] = Field(default_factory=list)
  scenes: list[StoryEntityReference] = Field(default_factory=list)
  organizations: list[StoryEntityReference] = Field(default_factory=list)
  chapter_reviews: list[ChapterReviewReport] = Field(default_factory=list)


class ProjectDetail(ProjectSummary):
  chapters: list[ChapterSummary] = Field(default_factory=list)
  local_history: LocalHistoryState = Field(default_factory=LocalHistoryState)
  story_overview: StoryOverview = Field(default_factory=StoryOverview)


class CreateProjectRequest(BaseModel):
  name: str = Field(min_length=1, max_length=80)
  base_path: str | None = None
  genre: str = "未定题材"
  target_chapters: int = Field(default=20, ge=1, le=1000)
  target_words: int = Field(default=200000, ge=1000, le=2000000)


class ProjectRenameRequest(BaseModel):
  name: str = Field(min_length=1, max_length=80)


class ProjectDeleteResult(BaseModel):
  id: str
  name: str
  path: str
  removed_from_disk: bool = True


class ProjectDirectoryOpenResult(BaseModel):
  project_id: str
  path: str
  opened: bool = True


class SnapshotCreateRequest(BaseModel):
  message: str | None = Field(default=None, max_length=120)


class SnapshotRestoreRequest(BaseModel):
  chapter_id: str | None = Field(default=None, max_length=32)


class ProjectExportRequest(BaseModel):
  format: str = Field(default="markdown", min_length=1, max_length=20)


class ProjectExportResult(BaseModel):
  path: str
  format: str
  chapter_count: int
  word_count: int
  created_at: str


class ChapterUpdateRequest(BaseModel):
  content: str = Field(default="")
  style_name: str = Field(default="", max_length=80)
  xp_preset: str = Field(default="", max_length=80)


class ChapterReviewRefreshRequest(BaseModel):
  style_name: str = Field(default="", max_length=80)


class StoryDocumentUpdateRequest(BaseModel):
  content: str = Field(default="")


class StoryDocumentPatch(BaseModel):
  key: str = Field(min_length=1, max_length=40)
  content: str = Field(default="")


class StoryDocumentBatchUpdateRequest(BaseModel):
  documents: list[StoryDocumentPatch] = Field(default_factory=list, min_length=1)


class KnowledgeImportItem(BaseModel):
  title: str = Field(min_length=1, max_length=120)
  content: str = Field(min_length=1, max_length=KNOWLEDGE_IMPORT_CONTENT_MAX_LENGTH)


class KnowledgeImportRequest(BaseModel):
  items: list[KnowledgeImportItem] = Field(default_factory=list, min_length=1, max_length=KNOWLEDGE_IMPORT_ITEM_MAX_COUNT)


class ImportedFilePayload(BaseModel):
  filename: str = Field(min_length=1, max_length=240)
  content_base64: str = Field(min_length=1, max_length=12_000_000)


class ImportedFileBatchRequest(BaseModel):
  files: list[ImportedFilePayload] = Field(default_factory=list, min_length=1, max_length=20)


class LicenseImportRequest(BaseModel):
  content: str = Field(min_length=1)


class LicenseValidationResult(BaseModel):
  valid: bool
  reason: str
  expires_at: str | None = None


class ArchitectureRequest(BaseModel):
  title: str = Field(min_length=1, max_length=80)
  premise: str = Field(min_length=10, max_length=1200)
  genre: str = "幻想"
  chapter_count: int = Field(default=20, ge=1, le=300)
  target_words: int = Field(default=200000, ge=1000, le=2000000)


class ArchitectureResult(BaseModel):
  task_id: str
  core_seed: str
  character_design: str
  world_building: str
  plot_structure: str


class ArchitectureWorkspace(BaseModel):
  core_seed: str = ""
  character_design: str = ""
  world_building: str = ""
  plot_structure: str = ""
  character_state: str = ""
  blueprint: str = ""
  global_summary: str = ""


class ArchitectureStepRequest(BaseModel):
  project_id: str = Field(min_length=1)
  step: str = Field(pattern="^(core_seed|character_design|world_building|plot_structure|character_state|blueprint|global_summary)$")
  mode: str = Field(default="initial", pattern="^(initial|continue)$")
  guidance: str = Field(default="", max_length=4000)
  new_chapters: int = Field(default=0, ge=0, le=200)
  workspace: ArchitectureWorkspace = Field(default_factory=ArchitectureWorkspace)


class ArchitectureStepResult(BaseModel):
  task_id: str
  step: str
  mode: str
  headline: str
  summary: str
  content: str
  checklist: list[str] = Field(default_factory=list)
  target_chapters: int | None = None


class ArchitectureWorkspaceApplyRequest(BaseModel):
  workspace: ArchitectureWorkspace = Field(default_factory=ArchitectureWorkspace)
  target_chapters: int | None = Field(default=None, ge=1, le=1000)
  target_words: int | None = Field(default=None, ge=1000, le=2000000)
  genre: str | None = Field(default=None, min_length=1, max_length=40)


class ChapterWorkflowScene(BaseModel):
  title: str
  goal: str
  conflict: str
  turn: str


class ChapterWorkflowRequest(BaseModel):
  project_id: str = Field(min_length=1)
  chapter_id: str = Field(min_length=1)
  mode: str = Field(default="diagnose", min_length=1, max_length=32)
  instruction: str = Field(default="", max_length=2000)
  target_words: int = Field(default=1500, ge=300, le=8000)


class ChapterWorkflowResult(BaseModel):
  task_id: str
  mode: str
  headline: str
  summary: str
  checklist: list[str] = Field(default_factory=list)
  scenes: list[ChapterWorkflowScene] = Field(default_factory=list)
  draft: str = ""
  next_action: str = ""


class BrainstormMessage(BaseModel):
  role: str = Field(pattern="^(user|assistant|system)$")
  content: str = Field(min_length=1, max_length=4000)


class BrainstormRequest(BaseModel):
  project_id: str = Field(min_length=1)
  messages: list[BrainstormMessage] = Field(default_factory=list, min_length=1, max_length=40)
  include_core_seed: bool = True
  include_characters: bool = True
  include_world_building: bool = True
  include_plot: bool = True
  include_blueprint: bool = False
  include_character_state: bool = False
  skill_id: str = Field(default="", max_length=120)
  extra_context: str = Field(default="", max_length=4000)


class SkillSuggestion(BaseModel):
  action: str = Field(default="create", pattern="^(create|iterate)$")
  summary: str
  reason: str = ""
  highlights: list[str] = Field(default_factory=list, max_length=4)
  confidence: float = Field(default=0.0, ge=0.0, le=1.0)
  target_skill_id: str = Field(default="", max_length=120)
  target_skill_name: str = Field(default="", max_length=120)


class BrainstormResult(BaseModel):
  task_id: str
  reply: str
  suggestions: list[str] = Field(default_factory=list)
  skill_candidate: SkillSuggestion | None = None


class AgentMessage(BaseModel):
  role: str = Field(pattern="^(user|assistant|system)$")
  content: str = Field(min_length=1, max_length=6000)


class AgentStateSummary(BaseModel):
  project_name: str
  genre: str = ""
  discussion_ready: bool = False
  architecture_ready: bool = False
  architecture_progress: int = Field(default=0, ge=0, le=5)
  selected_chapter_id: str = ""
  selected_chapter_title: str = ""
  selected_chapter_index: int | None = None
  selected_chapter_exists: bool = False
  last_written_chapter_id: str = ""
  last_written_chapter_title: str = ""
  last_written_chapter_index: int | None = None
  next_chapter_id: str = ""
  next_chapter_title: str = ""
  next_chapter_index: int | None = None
  document_status: dict[str, bool] = Field(default_factory=dict)


class AgentExecutionTrace(BaseModel):
  step: int = Field(default=1, ge=1, le=20)
  action_kind: str = Field(min_length=1, max_length=80)
  label: str = Field(min_length=1, max_length=120)
  status: str = Field(default="completed", pattern="^(pending|running|completed|failed)$")
  task_pack_kind: str = Field(default="", pattern="^(|continuation|architecture|imitation|persona)$")
  summary: str = Field(default="", max_length=2000)
  changes: list[str] = Field(default_factory=list, max_length=10)
  material_count: int | None = Field(default=None, ge=0, le=1000)


class AgentEventBlock(BaseModel):
  event_type: str = Field(min_length=1, max_length=80)
  title: str = Field(default="", max_length=160)
  status: str = Field(default="", pattern="^(|pending|running|completed|failed)$")
  summary: str = Field(default="", max_length=4000)
  step: int | None = Field(default=None, ge=1, le=20)
  action_kind: str = Field(default="", max_length=80)


class AgentArtifact(BaseModel):
  kind: str = Field(min_length=1, max_length=80)
  title: str = Field(default="", max_length=160)
  summary: str = Field(default="", max_length=4000)
  content_preview: str = Field(default="", max_length=4000)
  metadata: dict[str, object] = Field(default_factory=dict)


class AgentPlanAction(BaseModel):
  kind: str = Field(
    pattern="^(brainstorm|review_knowledge|generate_architecture|continue_project|chapter_generate|chapter_workflow|consistency_check|rewrite_chapter|skill_optimize)$"
  )
  label: str = Field(min_length=1, max_length=120)
  task_pack_kind: str = Field(default="", pattern="^(|continuation|architecture|imitation|persona)$")
  instruction: str = Field(default="", max_length=4000)
  chapter_id: str = Field(default="", max_length=120)
  mode: str = Field(default="", max_length=40)
  new_chapters: int = Field(default=0, ge=0, le=200)
  target_words: int = Field(default=0, ge=0, le=12000)
  style_name: str = Field(default="", max_length=80)
  xp_preset: str = Field(default="", max_length=80)
  characters_involved: str = Field(default="", max_length=500)
  key_items: str = Field(default="", max_length=500)
  scene_location: str = Field(default="", max_length=300)
  time_constraint: str = Field(default="", max_length=300)
  skill_ids: list[str] = Field(default_factory=list, max_length=5)


class AgentPlan(BaseModel):
  id: str = Field(min_length=1, max_length=80)
  title: str = Field(min_length=1, max_length=120)
  summary: str = Field(default="", max_length=2000)
  requires_confirmation: bool = True
  steps: list[str] = Field(default_factory=list, max_length=10)
  actions: list[AgentPlanAction] = Field(default_factory=list, min_length=1, max_length=10)


class AgentChatRequest(BaseModel):
  project_id: str = Field(min_length=1)
  messages: list[AgentMessage] = Field(default_factory=list, min_length=1, max_length=50)
  thread_id: str = Field(default="", max_length=80)
  selected_chapter_id: str = Field(default="", max_length=120)
  reference_filenames: list[str] = Field(default_factory=list, max_length=20)
  active_skill_ids: list[str] = Field(default_factory=list, max_length=5)
  skill_hints: list[str] = Field(default_factory=list, max_length=10)
  style_name: str = Field(default="", max_length=80)
  xp_preset: str = Field(default="", max_length=80)
  characters_involved: str = Field(default="", max_length=500)
  key_items: str = Field(default="", max_length=500)
  scene_location: str = Field(default="", max_length=300)
  time_constraint: str = Field(default="", max_length=300)
  approved_plan: AgentPlan | None = None


class AgentChatResult(BaseModel):
  task_id: str
  mode: str = Field(pattern="^(reply|plan|execution)$")
  reply: str
  state: AgentStateSummary
  thread_id: str = Field(default="", max_length=80)
  task_pack_kind: str = Field(default="", pattern="^(|continuation|architecture|imitation|persona)$")
  plan: AgentPlan | None = None
  execution_trace: list[AgentExecutionTrace] = Field(default_factory=list, max_length=20)
  event_blocks: list[AgentEventBlock] = Field(default_factory=list, max_length=40)
  artifacts: list[AgentArtifact] = Field(default_factory=list, max_length=20)
  suggestions: list[str] = Field(default_factory=list)
  changes: list[str] = Field(default_factory=list)
  can_save_discussion_summary: bool = False
  project_detail: ProjectDetail | None = None


class AgentThreadMessage(BaseModel):
  role: str = Field(pattern="^(user|assistant|system)$")
  content: str = Field(min_length=1, max_length=6000)
  mode: str = Field(default="", max_length=40)
  task_pack_kind: str = Field(default="", pattern="^(|continuation|architecture|imitation|persona)$")
  plan: AgentPlan | None = None
  execution_trace: list[AgentExecutionTrace] = Field(default_factory=list, max_length=20)
  event_blocks: list[AgentEventBlock] = Field(default_factory=list, max_length=40)
  artifacts: list[AgentArtifact] = Field(default_factory=list, max_length=20)
  state: AgentStateSummary | None = None
  suggestions: list[str] = Field(default_factory=list, max_length=10)
  changes: list[str] = Field(default_factory=list, max_length=20)
  can_save_discussion_summary: bool = False


class AgentThreadRecord(BaseModel):
  id: str = Field(min_length=1, max_length=80)
  title: str = Field(default="", max_length=120)
  preview: str = Field(default="", max_length=240)
  updated_at: str = Field(min_length=1, max_length=80)
  messages: list[AgentThreadMessage] = Field(default_factory=list, max_length=100)
  suggestions: list[str] = Field(default_factory=list, max_length=10)
  pending_plan: AgentPlan | None = None


class AgentThreadStore(BaseModel):
  active_thread_id: str = Field(default="", max_length=80)
  threads: list[AgentThreadRecord] = Field(default_factory=list, max_length=20)


class AgentThreadStoreUpdateRequest(BaseModel):
  active_thread_id: str = Field(default="", max_length=80)
  threads: list[AgentThreadRecord] = Field(default_factory=list, max_length=20)


class CharacterReplicaRequest(BaseModel):
  persona_name: str = Field(min_length=1, max_length=120)
  question: str = Field(min_length=1, max_length=4000)
  focus: str = Field(default="", max_length=2000)
  source_notes: str = Field(default="", max_length=12000)
  project_id: str = Field(default="", max_length=120)
  chapter_id: str = Field(default="", max_length=120)
  include_project_context: bool = True
  include_chapter_context: bool = True


class CharacterReplicaResult(BaseModel):
  task_id: str
  headline: str
  summary: str
  voice_profile: str = ""
  mental_models: list[str] = Field(default_factory=list)
  heuristics: list[str] = Field(default_factory=list)
  boundaries: list[str] = Field(default_factory=list)
  answer: str
  disclaimer: str = ""


class ConsistencyIssue(BaseModel):
  level: str = "warning"
  title: str
  detail: str


class ConsistencyCheckRequest(BaseModel):
  project_id: str = Field(min_length=1)
  chapter_id: str = Field(min_length=1)
  focus: str = Field(default="", max_length=2000)


class ConsistencyCheckResult(BaseModel):
  task_id: str
  summary: str
  issues: list[ConsistencyIssue] = Field(default_factory=list)
  suggestions: list[str] = Field(default_factory=list)


class BlueprintChapterOutline(BaseModel):
  chapter_id: str
  title: str
  goal: str
  hook: str


class BlueprintGenerateRequest(BaseModel):
  project_id: str = Field(min_length=1)
  instruction: str = Field(default="", max_length=2000)
  chapter_count: int | None = Field(default=None, ge=1, le=1000)
  style_name: str = Field(default="", max_length=80)
  xp_preset: str = Field(default="", max_length=80)


class BlueprintGenerateResult(BaseModel):
  task_id: str
  headline: str
  summary: str
  blueprint: str
  chapters: list[BlueprintChapterOutline] = Field(default_factory=list)


class ChapterGenerateRequest(BaseModel):
  project_id: str = Field(min_length=1)
  chapter_id: str = Field(min_length=1)
  instruction: str = Field(default="", max_length=2000)
  style_name: str = Field(default="", max_length=80)
  xp_preset: str = Field(default="", max_length=80)
  characters_involved: str = Field(default="", max_length=500)
  key_items: str = Field(default="", max_length=500)
  scene_location: str = Field(default="", max_length=300)
  time_constraint: str = Field(default="", max_length=300)


class ChapterGenerateResult(BaseModel):
  task_id: str
  headline: str
  summary: str
  content: str
  next_action: str = ""


class ChapterRewriteRequest(BaseModel):
  project_id: str = Field(min_length=1)
  chapter_id: str = Field(min_length=1)
  instruction: str = Field(default="", max_length=2000)
  style_name: str = Field(default="", max_length=80)
  xp_preset: str = Field(default="", max_length=80)


class HumanizeIssueReport(BaseModel):
  code: str
  label: str
  count: int = Field(default=0, ge=0)
  penalty: int = Field(default=0, ge=0)
  examples: list[str] = Field(default_factory=list)


class HumanizeQualityReport(BaseModel):
  before_score: int = Field(default=100, ge=0, le=100)
  after_score: int = Field(default=100, ge=0, le=100)
  delta: int = 0
  summary: str = ""
  fixed_issues: list[HumanizeIssueReport] = Field(default_factory=list)
  remaining_issues: list[HumanizeIssueReport] = Field(default_factory=list)


class ChapterRewriteResult(BaseModel):
  task_id: str
  headline: str
  summary: str
  original: str
  revised: str
  changes: list[str] = Field(default_factory=list)
  updated_summary: str = ""
  updated_character_state: str = ""
  quality_report: HumanizeQualityReport | None = None


class BatchGenerateRequest(BaseModel):
  project_id: str = Field(min_length=1)
  start_chapter: int = Field(ge=1, le=1000)
  end_chapter: int = Field(ge=1, le=1000)
  instruction: str = Field(default="", max_length=2000)
  style_name: str = Field(default="", max_length=80)
  xp_preset: str = Field(default="", max_length=80)


class BatchGenerateChapterResult(BaseModel):
  chapter_id: str
  title: str
  status: str
  preview: str = ""


class BatchGenerateResult(BaseModel):
  task_id: str
  generated: list[BatchGenerateChapterResult] = Field(default_factory=list)


class ContinueProjectRequest(BaseModel):
  project_id: str = Field(min_length=1)
  new_chapters: int = Field(default=5, ge=1, le=200)
  instruction: str = Field(default="", max_length=3000)
  style_name: str = Field(default="", max_length=80)
  xp_preset: str = Field(default="", max_length=80)


class ContinueProjectResult(BaseModel):
  task_id: str
  headline: str
  summary: str
  target_chapters: int
  plot_structure: str
  world_building: str
  character_design: str
  character_state: str
  blueprint: str


class ToolFileEntry(BaseModel):
  path: str
  name: str
  size: int
  directory: str


class ToolFileContentRequest(BaseModel):
  content: str = Field(default="")


class PromptRecord(BaseModel):
  timestamp: str
  task: str = ""
  model: str = ""
  prompt: str = ""
  response: str = ""
  status: str = ""
  elapsed: float | None = None
  error: str = ""


class CharacterReplicaProfileSummary(BaseModel):
  name: str
  summary: str = ""
  updated_at: str | None = None


class CharacterReplicaProfileDetail(CharacterReplicaProfileSummary):
  focus: str = ""
  source_notes: str = ""
  voice_profile: str = ""
  mental_models: list[str] = Field(default_factory=list)
  heuristics: list[str] = Field(default_factory=list)
  boundaries: list[str] = Field(default_factory=list)
  disclaimer: str = ""


class CharacterReplicaProfileSaveRequest(BaseModel):
  focus: str = Field(default="", max_length=2000)
  source_notes: str = Field(default="", max_length=12000)
  summary: str = Field(default="", max_length=4000)
  voice_profile: str = Field(default="", max_length=4000)
  mental_models: list[str] = Field(default_factory=list, max_length=8)
  heuristics: list[str] = Field(default_factory=list, max_length=10)
  boundaries: list[str] = Field(default_factory=list, max_length=10)
  disclaimer: str = Field(default="", max_length=4000)


class PromptPresetSummary(BaseModel):
  name: str
  description: str = ""
  updated_at: str | None = None


class PromptPresetDetail(PromptPresetSummary):
  prompts: dict[str, str] = Field(default_factory=dict)


class PromptPresetCreateRequest(BaseModel):
  name: str = Field(min_length=1, max_length=80)
  description: str = Field(default="", max_length=300)


class PromptPresetUpdateRequest(BaseModel):
  description: str | None = Field(default=None, max_length=300)
  prompts: dict[str, str] | None = None


class XPPreset(BaseModel):
  name: str
  content: str


class XPPresetCreateRequest(BaseModel):
  name: str = Field(min_length=1, max_length=80)
  content: str = Field(min_length=1, max_length=2000)


class XPPresetUpdateRequest(BaseModel):
  name: str | None = Field(default=None, min_length=1, max_length=80)
  content: str | None = Field(default=None, min_length=1, max_length=2000)


class SkillBehavior(BaseModel):
  panel: str = ""
  mode: str = ""
  input_label: str = ""
  submit_label: str = ""


class SkillItem(BaseModel):
  id: str
  badge: str
  name: str
  description: str = ""
  category: str = "工具"
  scenes: list[str] = Field(default_factory=list)
  accent: str = "slate"
  requires_project: bool = True
  requires_chapter: bool = False
  order: int = 0
  behavior: SkillBehavior = Field(default_factory=SkillBehavior)
  source: str = "builtin"
  updated_at: str | None = None
  usage: list[str] = Field(default_factory=list)
  limitations: list[str] = Field(default_factory=list)
  instruction_preview: str = ""


class SkillSection(BaseModel):
  id: str
  title: str
  description: str = ""
  order: int = 0
  items: list[SkillItem] = Field(default_factory=list)


class SkillCatalog(BaseModel):
  filters: list[str] = Field(default_factory=list)
  sections: list[SkillSection] = Field(default_factory=list)


class SkillMaterializeRequest(BaseModel):
  project_id: str = Field(min_length=1)
  messages: list[BrainstormMessage] = Field(default_factory=list, min_length=1, max_length=60)
  action: str = Field(default="create", pattern="^(create|iterate)$")
  skill_id: str = Field(default="", max_length=120)
  skill_name: str = Field(default="", max_length=120)
  selected_chapter_id: str = Field(default="", max_length=120)


class SkillVerificationReport(BaseModel):
  summary: str
  checks: list[str] = Field(default_factory=list)
  strengths: list[str] = Field(default_factory=list)
  improvement_points: list[str] = Field(default_factory=list)


class SkillMaterializeResult(BaseModel):
  action: str = Field(pattern="^(create|iterate)$")
  message: str
  skill: SkillItem
  saved_path: str
  skill_markdown: str
  verification: SkillVerificationReport


class StyleSummary(BaseModel):
  name: str
  updated_at: str | None = None
  has_reference_library: bool = False


class StyleDetail(StyleSummary):
  instruction: str = ""
  analysis: str = ""
  dna_analysis: str = ""
  narrative_for_architecture: str = ""
  narrative_for_blueprint: str = ""
  narrative_for_chapter: str = ""
  reference_distillate: str = ""
  source_sample: str = ""
  calibration_reference: str = ""
  calibration_notes: str = ""
  last_calibrated_at: str | None = None
  has_calibration_snapshot: bool = False
  snapshot_timestamp: str | None = None
  reference_materials: list[KnowledgeMaterial] = Field(default_factory=list)


class StyleAnalyzeRequest(BaseModel):
  style_name: str = Field(min_length=1, max_length=80)
  sample_text: str = Field(min_length=20, max_length=30000)
  user_preference: str = Field(default="", max_length=2000)


class StyleDNAAnalyzeRequest(BaseModel):
  style_name: str = Field(min_length=1, max_length=80)
  sample_text: str = Field(min_length=20, max_length=30000)
  user_preference: str = Field(default="", max_length=2000)


class StyleMergeRequest(BaseModel):
  style_name: str = Field(min_length=1, max_length=80)
  selected_styles: list[str] = Field(default_factory=list, min_length=1, max_length=5)
  user_preference: str = Field(default="", max_length=2000)


class StyleCalibrateRequest(BaseModel):
  style_name: str = Field(min_length=1, max_length=80)
  max_iterations: int = Field(default=3, ge=1, le=8)
  user_preference: str = Field(default="", max_length=3000)


class StyleSaveRequest(BaseModel):
  instruction: str = Field(default="", max_length=12000)
  analysis: str = Field(default="", max_length=20000)
  dna_analysis: str = Field(default="", max_length=20000)
  narrative_for_architecture: str = Field(default="", max_length=8000)
  narrative_for_blueprint: str = Field(default="", max_length=8000)
  narrative_for_chapter: str = Field(default="", max_length=8000)
  source_sample: str = Field(default="", max_length=30000)
  calibration_reference: str = Field(default="", max_length=30000)
  calibration_notes: str = Field(default="", max_length=12000)


class StyleAnalysisResult(BaseModel):
  task_id: str
  instruction: str
  analysis: str
  dna_analysis: str = ""
  narrative_for_architecture: str = ""
  narrative_for_blueprint: str = ""
  narrative_for_chapter: str = ""
  calibration_notes: str = ""


class StyleReferenceItem(BaseModel):
  title: str = Field(min_length=1, max_length=120)
  content: str = Field(min_length=1, max_length=80000)


class StyleReferenceImportRequest(BaseModel):
  items: list[StyleReferenceItem] = Field(default_factory=list, min_length=1, max_length=20)
