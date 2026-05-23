export interface ApiError {
  code: string;
  message: string;
}

export interface ApiEnvelope<T> {
  ok: boolean;
  data?: T;
  error?: ApiError;
}

export interface HealthData {
  status: 'ok';
  backend_version: string;
  data_dir: string;
  started_at: string;
  project_count: number;
}

export interface ProjectSummary {
  id: string;
  name: string;
  path: string;
  genre: string;
  target_chapters: number;
  target_words: number;
  updated_at: string;
}

export interface LocalHistoryChangedFile {
  path: string;
  status: 'added' | 'modified' | 'deleted' | string;
}

export interface SnapshotChapterRef {
  id: string;
  index: number;
  title: string;
  path: string;
  status: 'added' | 'modified' | 'deleted' | string;
  preview: string;
}

export interface WorkingTreeStatus {
  clean: boolean;
  changed_count: number;
  changed_files: LocalHistoryChangedFile[];
  base_snapshot_version?: number | null;
  base_snapshot_id?: string | null;
  base_snapshot_message?: string | null;
  base_snapshot_created_at?: string | null;
}

export interface ProjectSnapshot {
  id: string;
  version: number;
  kind: 'system' | 'manual' | 'auto' | 'restore' | string;
  message: string;
  created_at: string;
  file_count: number;
  changed_count: number;
  affected_chapters: SnapshotChapterRef[];
}

export interface ProjectSnapshotDetail extends ProjectSnapshot {
  changed_files: LocalHistoryChangedFile[];
  preview_chapters: ChapterSummary[];
}

export interface LocalHistoryState {
  snapshots: ProjectSnapshot[];
  working_tree: WorkingTreeStatus;
}

export interface StoryDocument {
  key: string;
  label: string;
  filename: string;
  content: string;
  updated_at?: string | null;
}

export interface KnowledgeSearchResult {
  source: string;
  section: string;
  preview: string;
  score: number;
}

export interface KnowledgeMaterial {
  title: string;
  filename: string;
  preview: string;
  updated_at?: string | null;
}

export interface ProjectMemoryEntry {
  id: string;
  title: string;
  category: '硬规则' | '偏好' | '连续性' | '警告' | '目标' | string;
  content: string;
  source?: 'manual' | 'auto' | string;
  updated_at?: string | null;
}

export interface ProjectDreamCandidate {
  id: string;
  title: string;
  category: '硬规则' | '偏好' | '连续性' | '警告' | '目标' | string;
  content: string;
  rationale: string;
  confidence: number;
  promoted_at?: string | null;
}

export interface ProjectDreamReport {
  engine: string;
  generated_at?: string | null;
  source_signature: string;
  is_stale: boolean;
  focus: string;
  summary: string;
  themes: string[];
  insights: string[];
  open_questions: string[];
  memory_candidates: ProjectDreamCandidate[];
  source_chapter_ids: string[];
  source_document_keys: string[];
}

export interface StoryEntityReference {
  name: string;
  summary: string;
  related_characters: string[];
  chapter_indexes: number[];
}

export interface CharacterTimelineEntry {
  id: string;
  chapter_id?: string | null;
  chapter_index?: number | null;
  chapter_title: string;
  source_label: string;
  summary: string;
  relations: string[];
  events: string[];
  locations: string[];
  props: string[];
  skills: string[];
  scenes: string[];
  organizations: string[];
}

export interface StoryCharacter {
  name: string;
  profile: string;
  current_state: string;
  relationships: string[];
  events: string[];
  locations: string[];
  props: string[];
  skills: string[];
  scenes: string[];
  organizations: string[];
  timeline: CharacterTimelineEntry[];
}

export interface ChapterReviewIssue {
  level: 'info' | 'warning' | 'critical';
  title: string;
  detail: string;
}

export interface ChapterReviewDimension {
  id: string;
  label: string;
  score: number;
  status: 'good' | 'watch' | 'risk' | 'na';
  summary: string;
  highlights: string[];
  issues: ChapterReviewIssue[];
}

export interface ChapterReviewReport {
  chapter_id: string;
  chapter_index: number;
  chapter_title: string;
  version: string;
  engine: string;
  status: 'good' | 'watch' | 'risk' | 'na';
  overall_score: number;
  summary: string;
  highlights: string[];
  suggestions: string[];
  dimensions: ChapterReviewDimension[];
  style_name: string;
  updated_at?: string | null;
  source_signature: string;
  is_stale: boolean;
}

export interface StoryOverview {
  documents: StoryDocument[];
  knowledge_hits: KnowledgeSearchResult[];
  materials: KnowledgeMaterial[];
  memory_entries: ProjectMemoryEntry[];
  dream_report?: ProjectDreamReport | null;
  characters: StoryCharacter[];
  events: StoryEntityReference[];
  locations: StoryEntityReference[];
  props: StoryEntityReference[];
  skills: StoryEntityReference[];
  scenes: StoryEntityReference[];
  organizations: StoryEntityReference[];
  chapter_reviews: ChapterReviewReport[];
}

export interface ChapterSummary {
  id: string;
  index: number;
  title: string;
  path: string;
  exists: boolean;
  preview: string;
  content?: string;
  updated_at?: string | null;
}

export interface ProjectDetail extends ProjectSummary {
  chapters: ChapterSummary[];
  local_history: LocalHistoryState;
  story_overview: StoryOverview;
}

export interface ProjectExportResult {
  path: string;
  format: string;
  chapter_count: number;
  word_count: number;
  created_at: string;
}

export interface CreateProjectRequest {
  name: string;
  base_path?: string;
  genre?: string;
  target_chapters?: number;
  target_words?: number;
}

export interface ProjectRenameRequest {
  name: string;
}

export interface ProjectDeleteResult {
  id: string;
  name: string;
  path: string;
  removed_from_disk: boolean;
}

export interface ProjectDirectoryOpenResult {
  project_id: string;
  path: string;
  opened: boolean;
}

export interface ModelConfig {
  provider: string;
  base_url: string;
  api_key: string;
  model_name: string;
  max_tokens: number;
  temperature: number;
}

export interface EmbeddingConfig {
  provider: string;
  base_url: string;
  api_key: string;
  model_name: string;
  dimensions: number | null;
  retrieval_k: number;
  batch_size: number;
}

export interface ReviewModelConfig {
  enabled: boolean;
  provider: string;
  base_url: string;
  api_key: string;
  model_name: string;
  max_tokens: number;
  temperature: number;
}

export interface ChapterAutoRepairConfig {
  enabled: boolean;
  score_threshold: number;
  max_rounds: number;
}

export interface AppConfig {
  model: ModelConfig;
  embedding: EmbeddingConfig;
  review_model: ReviewModelConfig;
  chapter_auto_repair: ChapterAutoRepairConfig;
  updated_at: string;
}

export interface LicenseValidationResult {
  valid: boolean;
  reason: string;
  expires_at?: string | null;
}

export interface ArchitectureRequest {
  title: string;
  premise: string;
  genre: string;
  chapter_count: number;
  target_words: number;
}

export interface ArchitectureResult {
  task_id: string;
  core_seed: string;
  character_design: string;
  world_building: string;
  plot_structure: string;
}

export interface ArchitectureWorkspace {
  core_seed: string;
  character_design: string;
  world_building: string;
  plot_structure: string;
  character_state: string;
  blueprint: string;
  global_summary: string;
}

export interface ArchitectureWorkspaceApplyRequest {
  workspace: ArchitectureWorkspace;
  target_chapters?: number | null;
  target_words?: number | null;
  genre?: string | null;
}

export interface ChapterWorkflowScene {
  title: string;
  goal: string;
  conflict: string;
  turn: string;
}

export interface ChapterWorkflowRequest {
  project_id: string;
  chapter_id: string;
  mode: string;
  instruction: string;
  target_words: number;
}

export interface ChapterWorkflowResult {
  task_id: string;
  mode: string;
  headline: string;
  summary: string;
  checklist: string[];
  scenes: ChapterWorkflowScene[];
  draft: string;
  next_action: string;
}

export interface GenerationSseEvent<T = unknown> {
  event: string;
  data: T;
}

export interface RuntimeInfo {
  runtime: 'browser-preview' | 'tauri';
  version: string;
  backend_url?: string;
}
