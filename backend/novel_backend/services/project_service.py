from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import shutil
import sys
from array import array
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from novel_backend.config import Settings
from novel_backend.models import (
  AgentThreadRecord,
  AgentThreadStore,
  AgentThreadStoreUpdateRequest,
  ArchitectureWorkspaceApplyRequest,
  ChapterReviewRefreshRequest,
  ChapterUpdateRequest,
  ChapterSummary,
  CharacterTimelineEntry,
  CreateProjectRequest,
  KnowledgeImportRequest,
  KnowledgeMaterial,
  KnowledgeSearchResult,
  LocalHistoryChangedFile,
  LocalHistoryState,
  ProjectDeleteResult,
  ProjectDirectoryOpenResult,
  ProjectDreamPromoteRequest,
  ProjectDreamRunRequest,
  ProjectMemoryUpdateRequest,
  ProjectDetail,
  ProjectExportRequest,
  ProjectExportResult,
  ProjectRenameRequest,
  ProjectSnapshotDetail,
  ProjectSnapshot,
  ProjectSummary,
  SnapshotChapterRef,
  SnapshotCreateRequest,
  SnapshotRestoreRequest,
  StoryCharacter,
  StoryDocumentBatchUpdateRequest,
  StoryDocumentPatch,
  StoryDocument,
  StoryDocumentUpdateRequest,
  StoryEntityReference,
  StoryOverview,
  WorkingTreeStatus,
)
from novel_backend.services.embedding_service import embed_texts, embedding_config_signature
from novel_backend.services.log_service import append_app_log
from novel_backend.services.rerank_service import rerank_documents
from novel_backend.services.project_dream_service import (
  build_project_dream_signature,
  generate_project_dream_report,
  load_project_dream_report,
  promote_project_dream_candidates as promote_dream_candidates,
  save_project_dream_report,
)
from novel_backend.services.project_distillation_service import (
  build_project_distillation_signature,
  generate_project_distillation,
  load_project_distillation,
  save_project_distillation,
)
from novel_backend.services.chapter_review_service import (
  build_chapter_review,
  delete_chapter_review,
  load_chapter_reviews,
  save_chapter_review,
)
from novel_backend.services.project_memory_auto_service import build_auto_project_memory
from novel_backend.services.project_memory_service import (
  ensure_project_memory_file,
  load_project_memory,
  project_memory_dir,
  save_project_memory,
  sync_project_memory,
)
from novel_backend.services.config_service import project_index_path
from novel_backend.utils.jsonfile import atomic_write_json, atomic_write_text, read_json

_LOCAL_HISTORY_DIRNAME = ".novel-history"
_APP_STATE_DIRNAME = ".gaoxia"
_AGENT_THREADS_DIRNAME = "threads"
_REFERENCE_DIRNAME = "references"
_SNAPSHOT_FILES_DIRNAME = "files"
_KNOWLEDGE_SCHEMA_VERSION = "2"
_KNOWLEDGE_SEMANTIC_CANDIDATE_MIN = 48
_KNOWLEDGE_SEMANTIC_CANDIDATE_CAP = 240
_SNAPSHOT_ROOT_FILES = (
  "core_seed.txt",
  "character_design.txt",
  "character_state.txt",
  "world_building.txt",
  "plot_structure.txt",
  "blueprint.txt",
  "global_summary.txt",
  "project_memory.json",
)
_STORY_DOCUMENT_SPECS = (
  ("core_seed.txt", "core_seed", "核心种子"),
  ("character_design.txt", "character_design", "人物设定"),
  ("character_state.txt", "character_state", "人物状态"),
  ("world_building.txt", "world_building", "世界设定"),
  ("plot_structure.txt", "plot_structure", "情节骨架"),
  ("blueprint.txt", "blueprint", "章节蓝图"),
  ("global_summary.txt", "global_summary", "滚动摘要"),
)
_ROLE_CHARACTER_TOKENS = (
  "主角",
  "男主",
  "女主",
  "反派",
  "配角",
  "搭档",
  "同伴",
  "对立角色",
  "辅助角色",
  "船长",
  "队长",
  "老师",
  "师父",
  "老板",
  "医生",
  "记者",
  "警探",
  "警官",
  "母亲",
  "父亲",
  "哥哥",
  "姐姐",
  "妹妹",
  "弟弟",
)
_CHARACTER_NAME_BLACKLIST = {
  "故事",
  "章节",
  "正文",
  "状态",
  "关系",
  "人物",
  "场景",
  "事件",
  "地点",
  "组织",
  "道具",
  "世界",
  "蓝图",
  "骨架",
  "摘要",
  "设定",
  "结构",
  "时间线",
  "冲突",
  "项目",
  "当前小说",
}
_JSON_CHARACTER_CONTAINER_KEYS = {
  "content",
  "characters",
  "character_design",
  "character_state",
  "人物",
  "人物设定",
  "人物状态",
  "角色",
  "角色设定",
  "角色状态",
}
_JSON_CHARACTER_NAME_KEYS = ("name", "姓名", "人物", "角色", "角色名")
_NON_CHARACTER_NAME_FRAGMENTS = (
  "危机",
  "问题",
  "终章",
  "章节",
  "时代",
  "动机",
  "严格",
  "原著",
  "改革",
  "思想",
  "方案",
  "文件",
  "通知",
  "权威",
  "张力",
  "全篇",
  "公文",
  "封建",
  "家属",
  "阁楼",
  "政治",
  "时局",
  "无爱",
  "钱氏",
  "蓝布",
  "东方红",
  "钩子",
  "检讨",
  "呕吐",
  "忠诚",
  "历史",
  "机制",
  "结构",
  "课程",
  "教师",
  "高校",
  "组织",
  "语言",
  "关系",
  "状态",
  "场景",
  "事件",
  "地点",
  "道具",
  "设定",
)
_NON_CHARACTER_NAME_CHARS = frozenset("的了与及为被将把从因却虽而")
_COMMON_SINGLE_CHAR_SURNAMES = (
  "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
  "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐费"
  "廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元顾孟平黄和穆"
  "萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁杜阮"
  "蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐丘骆高夏蔡田樊胡凌霍虞万"
  "支柯昝管卢莫经房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔吉龚程邢裴陆"
  "荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车侯"
  "宓蓬全郗班仰秋仲伊宫宁仇栾暴甘厉戎祖武符刘景詹束龙叶幸司黎乔苍双"
  "闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍璩桑桂濮牛寿通边扈燕冀郏浦尚农温"
  "别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡"
  "国文寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾"
  "沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公"
)
_COMPOUND_SURNAMES = (
  "欧阳",
  "司马",
  "上官",
  "诸葛",
  "东方",
  "皇甫",
  "尉迟",
  "公孙",
  "司徒",
  "司空",
  "夏侯",
  "令狐",
  "闻人",
  "长孙",
  "慕容",
  "宇文",
  "司寇",
  "南宫",
)
_COMPOUND_SURNAME_PATTERN = re.compile(
  rf"((?:{'|'.join(_COMPOUND_SURNAMES)})[\u4e00-\u9fff]{{1,2}})"
)
_SINGLE_SURNAME_PATTERN = re.compile(rf"([{_COMMON_SINGLE_CHAR_SURNAMES}][\u4e00-\u9fff]{{1,2}})")
_DISCOVERED_CHARACTER_BLACKLIST = {
  "中国人",
  "外国人",
  "年轻人",
  "老实人",
  "大学生",
  "中学生",
  "小孩子",
  "老太太",
  "老先生",
  "男孩子",
  "女孩子",
  "一个人",
  "那个人",
  "这个人",
  "什么人",
  "自己人",
  "委员会",
  "总经理",
  "副经理",
  "办公室",
  "图书馆",
  "火车站",
  "研究所",
}
_DISCOVERED_CHARACTER_SUFFIX_BLACKLIST = (
  "先生",
  "太太",
  "小姐",
  "夫人",
  "同学",
  "老师",
  "教授",
  "主任",
  "校长",
  "老板",
  "男人",
  "女人",
  "记者",
  "医生",
  "学生",
  "朋友",
)
_PROJECT_DIR_PREFIX_PATTERN = re.compile(r"^(\d{8}_\d{6})_(.+)$")
_LOCATION_PATTERN = re.compile(
  r"([\u4e00-\u9fff]{1,8}(?:港口|码头|仓库|车站|书房|病房|教室|办公室|走廊|庭院|屋顶|船舱|甲板|酒馆|会馆|广场|巷|街|桥|山谷|河岸|湖畔|小镇|古城|村庄))"
)
_LOCATION_KEYWORDS = (
  "码头",
  "港口",
  "仓库",
  "车站",
  "书房",
  "病房",
  "教室",
  "办公室",
  "走廊",
  "庭院",
  "屋顶",
  "船舱",
  "甲板",
  "酒馆",
  "会馆",
  "广场",
  "街口",
  "雨巷",
  "河岸",
  "湖畔",
  "小镇",
  "古城",
  "村庄",
  "船",
)
_ORGANIZATION_PATTERN = re.compile(
  r"([\u4e00-\u9fff]{2,12}(?:商会|警署|监察局|巡夜队|学宫|教会|公司|研究所|军团|联盟|帮会|门派|公会|教团|议会|财团|神殿|宗门|骑士团|帮派))"
)
_ORGANIZATION_KEYWORDS = (
  "商会",
  "警署",
  "监察局",
  "巡夜队",
  "学宫",
  "教会",
  "公司",
  "研究所",
  "军团",
  "联盟",
  "帮会",
  "门派",
  "公会",
  "教团",
  "议会",
  "财团",
  "神殿",
  "宗门",
  "骑士团",
  "帮派",
)
_PROP_KEYWORDS = (
  "灯",
  "钥匙",
  "信",
  "手稿",
  "地图",
  "怀表",
  "刀",
  "剑",
  "枪",
  "匕首",
  "伞",
  "戒指",
  "项链",
  "印章",
  "令牌",
  "账本",
  "箱子",
  "船票",
  "药剂",
  "手电",
)
_SKILL_HINT_KEYWORDS = (
  "开锁",
  "潜行",
  "追踪",
  "侦查",
  "审讯",
  "格斗",
  "射击",
  "谈判",
  "医术",
  "毒术",
  "易容",
  "占卜",
  "炼药",
  "炼丹",
  "黑客",
  "驾驶",
  "航海",
  "驭兽",
)
_SKILL_NOUN_PATTERN = re.compile(
  r"([\u4e00-\u9fff]{2,12}(?:剑术|刀法|枪法|拳法|掌法|步法|身法|术法|法术|阵法|符术|医术|毒术|机关术|傀儡术|驭兽|炼药|炼丹|开锁|潜行|追踪|侦查|审讯|格斗|射击|谈判|易容|占卜|航海|驾驶|黑客))"
)
_SKILL_LABEL_PATTERN = re.compile(r"(?:技能|能力|特长|绝活|本领|擅长)[：:]\s*([^\n。；;]+)")
_SKILL_VERB_PATTERNS = (
  re.compile(r"(?:擅长|善于|精通|熟悉|掌握|精于|最会|很会)([\u4e00-\u9fffA-Za-z0-9]{2,12})"),
  re.compile(r"(?:有|具备)([\u4e00-\u9fffA-Za-z0-9]{2,12}能力)"),
)
_SKILL_SPLIT_PATTERN = re.compile(r"[、,，/|｜]+")
_SKILL_BLACKLIST = {
  "人物设定",
  "人物状态",
  "当前状态",
  "章节正文",
  "关系",
  "地点",
  "事件",
  "道具",
  "场景",
  "组织",
  "世界设定",
  "情节骨架",
  "章节蓝图",
  "滚动摘要",
  "当前小说",
}
_ENTITY_CONTEXT_TOKENS = (
  "回到",
  "来到",
  "前往",
  "抵达",
  "赶到",
  "潜入",
  "避开",
  "冲进",
  "走进",
  "站在",
  "留在",
  "躲进",
  "返回",
  "奔向",
  "看向",
  "驶向",
  "在",
  "到",
  "进",
  "向",
  "朝",
  "往",
  "从",
  "的",
)
def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def _safe_folder_name(name: str) -> str:
  cleaned = "".join("_" if char in '<>:"/\\|?*' else char for char in name).strip()
  cleaned = cleaned.replace("  ", " ")
  return cleaned[:40] or "novel-project"


def _project_dir(summary: ProjectSummary) -> Path:
  return Path(summary.path).expanduser().resolve()


def _project_meta_path(project_dir: Path) -> Path:
  return project_dir / "project.json"


def _assert_project_dir_is_valid(summary: ProjectSummary) -> Path:
  project_dir = _project_dir(summary)
  if not project_dir.exists():
    raise HTTPException(
      status_code=404,
      detail={"code": "project_dir_not_found", "message": "项目目录不存在"},
    )

  project_meta = read_json(_project_meta_path(project_dir), {})
  if not isinstance(project_meta, dict) or project_meta.get("id") != summary.id:
    raise HTTPException(
      status_code=409,
      detail={"code": "project_meta_mismatch", "message": "项目目录与索引不一致"},
    )

  return project_dir


def _write_project_index(settings: Settings, projects: list[ProjectSummary]) -> None:
  sorted_projects = sorted(projects, key=lambda item: item.updated_at, reverse=True)
  atomic_write_json(
    project_index_path(settings),
    [item.model_dump(mode="json") for item in sorted_projects],
  )


def _replace_project_summary(settings: Settings, summary: ProjectSummary) -> None:
  project_items = [ProjectSummary.model_validate(item) for item in read_json(project_index_path(settings), [])]
  next_projects: list[ProjectSummary] = []
  found = False

  for item in project_items:
    if item.id == summary.id:
      next_projects.append(summary)
      found = True
    else:
      next_projects.append(item)

  if not found:
    raise HTTPException(
      status_code=404,
      detail={"code": "project_not_found", "message": "项目不存在"},
    )

  _write_project_index(settings, next_projects)


def _renamed_project_dirname(current_dirname: str, project_name: str) -> str:
  safe_name = _safe_folder_name(project_name)
  matched = _PROJECT_DIR_PREFIX_PATTERN.match(current_dirname)
  if matched:
    return f"{matched.group(1)}_{safe_name}"

  return safe_name


def _project_summary_or_404(settings: Settings, project_id: str) -> ProjectSummary:
  summary = next((item for item in list_projects(settings) if item.id == project_id), None)
  if summary is None:
    raise HTTPException(
      status_code=404,
      detail={"code": "project_not_found", "message": "项目不存在"},
    )

  return summary


def _chapter_display_title(content: str, fallback_index: int) -> str:
  for raw_line in content.splitlines():
    line = raw_line.strip().lstrip("#").strip()
    if line:
      return line[:80]

  return f"第 {fallback_index} 章"


def _chapter_preview(content: str) -> str:
  collapsed = " ".join(line.strip() for line in content.splitlines() if line.strip())
  return collapsed[:140]


def _chapter_filename(index: int) -> str:
  return f"{index:03d}.md"


def _chapter_file_path(project_dir: Path, index: int) -> Path:
  return project_dir / "chapters" / _chapter_filename(index)


def _chapter_id(index: int) -> str:
  return f"chapter-{index:03d}"


def _chapter_index_from_path(relative_path: str) -> int | None:
  normalized = relative_path.replace("\\", "/")
  if not normalized.startswith("chapters/"):
    return None

  stem = Path(normalized).stem
  if not stem.isdigit():
    return None

  return int(stem)


def _chapter_index_from_id(chapter_id: str) -> int:
  prefix = "chapter-"
  if not chapter_id.startswith(prefix):
    raise HTTPException(
      status_code=400,
      detail={"code": "invalid_chapter_id", "message": "章节标识无效"},
    )

  raw_index = chapter_id[len(prefix):]
  if not raw_index.isdigit():
    raise HTTPException(
      status_code=400,
      detail={"code": "invalid_chapter_id", "message": "章节标识无效"},
    )

  return int(raw_index)


def _history_dir(project_dir: Path) -> Path:
  return project_dir / _LOCAL_HISTORY_DIRNAME


def _app_state_dir(project_dir: Path) -> Path:
  return project_dir / _APP_STATE_DIRNAME


def _agent_threads_dir(project_dir: Path) -> Path:
  return _app_state_dir(project_dir) / _AGENT_THREADS_DIRNAME


def _agent_threads_index_path(project_dir: Path) -> Path:
  return _agent_threads_dir(project_dir) / "index.json"


def _agent_thread_path(project_dir: Path, thread_id: str) -> Path:
  return _agent_threads_dir(project_dir) / f"{thread_id}.json"


def _normalize_thread_id_or_400(thread_id: str) -> str:
  cleaned = str(thread_id or "").strip()
  if not cleaned or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", cleaned):
    raise HTTPException(
      status_code=400,
      detail={"code": "invalid_thread_id", "message": "线程标识无效"},
    )
  return cleaned


def _ensure_agent_threads_layout(project_dir: Path) -> None:
  threads_dir = _agent_threads_dir(project_dir)
  threads_dir.mkdir(parents=True, exist_ok=True)

  index_path = _agent_threads_index_path(project_dir)
  if not index_path.exists():
    atomic_write_json(index_path, {"active_thread_id": "", "threads": []})


def _history_index_path(project_dir: Path) -> Path:
  return _history_dir(project_dir) / "index.json"


def _snapshot_dir(project_dir: Path, snapshot_id: str) -> Path:
  return _history_dir(project_dir) / "snapshots" / snapshot_id


def _snapshot_manifest_path(project_dir: Path, snapshot_id: str) -> Path:
  return _snapshot_dir(project_dir, snapshot_id) / "manifest.json"


def _snapshot_files_dir(project_dir: Path, snapshot_id: str) -> Path:
  return _snapshot_dir(project_dir, snapshot_id) / _SNAPSHOT_FILES_DIRNAME


def _ensure_history_layout(project_dir: Path) -> None:
  snapshots_dir = _history_dir(project_dir) / "snapshots"
  snapshots_dir.mkdir(parents=True, exist_ok=True)

  history_index = _history_index_path(project_dir)
  if not history_index.exists():
    atomic_write_json(history_index, [])


def _iter_versioned_files(project_dir: Path) -> list[Path]:
  versioned_files: dict[str, Path] = {}

  for filename in _SNAPSHOT_ROOT_FILES:
    path = project_dir / filename
    if path.exists() and path.is_file():
      versioned_files[path.relative_to(project_dir).as_posix()] = path

  chapters_dir = project_dir / "chapters"
  if chapters_dir.exists():
    for pattern in ("*.md", "*.txt"):
      for path in chapters_dir.rglob(pattern):
        if path.is_file():
          versioned_files[path.relative_to(project_dir).as_posix()] = path

  memory_dir = project_memory_dir(project_dir)
  if memory_dir.exists():
    for pattern in ("*.md", "*.jsonl"):
      for path in memory_dir.rglob(pattern):
        if path.is_file():
          versioned_files[path.relative_to(project_dir).as_posix()] = path

  return [versioned_files[key] for key in sorted(versioned_files)]


def _hash_file(path: Path) -> str:
  digest = hashlib.sha256()
  with path.open("rb") as handle:
    for chunk in iter(lambda: handle.read(65536), b""):
      digest.update(chunk)

  return digest.hexdigest()


def _collect_manifest(project_dir: Path) -> list[dict[str, str | int]]:
  manifest: list[dict[str, str | int]] = []

  for path in _iter_versioned_files(project_dir):
    manifest.append(
      {
        "path": path.relative_to(project_dir).as_posix(),
        "sha256": _hash_file(path),
        "size": path.stat().st_size,
      }
    )

  return manifest


def _history_entries(project_dir: Path) -> list[dict]:
  _ensure_history_layout(project_dir)
  payload = read_json(_history_index_path(project_dir), [])
  if isinstance(payload, list):
    changed = False
    next_version = 1
    normalized: list[dict] = []

    for item in reversed(payload):
      entry = dict(item) if isinstance(item, dict) else {}
      if "version" not in entry:
        entry["version"] = next_version
        changed = True
      if "kind" not in entry:
        entry["kind"] = "system" if entry.get("message") == "初始化项目" else "manual"
        changed = True
      if "affected_chapters" not in entry:
        manifest = _read_snapshot_manifest(project_dir, str(entry["id"]))
        snapshot_files_dir = _snapshot_files_dir(project_dir, str(entry["id"]))
        snapshot_sources = {
          str(item["path"]): snapshot_files_dir / Path(str(item["path"]))
          for item in manifest.get("changes", [])
          if str(item.get("status")) != "deleted"
        }
        entry["affected_chapters"] = [
          item.model_dump(mode="json")
          for item in _affected_chapters_from_manifest(
            project_dir,
            str(entry["id"]),
            manifest,
            snapshot_sources,
          )
        ]
        changed = True
      next_version = max(next_version, int(entry["version"])) + 1
      normalized.append(entry)

    normalized.reverse()
    if changed:
      atomic_write_json(_history_index_path(project_dir), normalized)

    return normalized

  return [] 


def _snapshot_message(value: str | None, fallback: str) -> str:
  if value is None:
    return fallback

  cleaned = " ".join(value.split()).strip()
  return cleaned[:120] or fallback


def _read_snapshot_manifest(project_dir: Path, snapshot_id: str) -> dict:
  manifest_path = _snapshot_manifest_path(project_dir, snapshot_id)
  if not manifest_path.exists():
    raise HTTPException(
      status_code=404,
      detail={"code": "snapshot_not_found", "message": "本地快照不存在"},
    )

  payload = read_json(manifest_path, {"files": [], "changes": []})
  if isinstance(payload, dict):
    return payload

  return {"files": [], "changes": []}


def _manifest_by_path(manifest: list[dict[str, str | int]]) -> dict[str, dict[str, str | int]]:
  return {str(item["path"]): item for item in manifest}


def _build_changed_items(
  current_manifest: list[dict[str, str | int]],
  base_manifest: list[dict[str, str | int]],
) -> list[dict[str, str | int]]:
  current_by_path = _manifest_by_path(current_manifest)
  base_by_path = _manifest_by_path(base_manifest)
  changes: list[dict[str, str | int]] = []

  for path in sorted(set(current_by_path) | set(base_by_path)):
    if path not in base_by_path:
      current_item = current_by_path[path]
      changes.append(
        {
          "path": path,
          "status": "added",
          "sha256": str(current_item["sha256"]),
          "size": int(current_item["size"]),
        }
      )
    elif path not in current_by_path:
      changes.append({"path": path, "status": "deleted"})
    elif current_by_path[path]["sha256"] != base_by_path[path]["sha256"]:
      current_item = current_by_path[path]
      changes.append(
        {
          "path": path,
          "status": "modified",
          "sha256": str(current_item["sha256"]),
          "size": int(current_item["size"]),
        }
      )

  return changes


def _diff_manifest(
  current_manifest: list[dict[str, str | int]],
  base_manifest: list[dict[str, str | int]],
) -> list[LocalHistoryChangedFile]:
  return [
    LocalHistoryChangedFile(path=str(item["path"]), status=str(item["status"]))
    for item in _build_changed_items(current_manifest, base_manifest)
  ]


def _chapter_ref_from_source(
  project_dir: Path,
  relative_path: str,
  *,
  status: str,
  source_path: Path | None = None,
) -> SnapshotChapterRef | None:
  chapter_index = _chapter_index_from_path(relative_path)
  if chapter_index is None:
    return None

  chapter_title = f"第 {chapter_index} 章"
  chapter_preview = ""

  if source_path is not None and source_path.exists():
    try:
      content = source_path.read_text(encoding="utf-8")
    except OSError:
      content = ""

    if content:
      chapter_title = _chapter_display_title(content, chapter_index)
      chapter_preview = _chapter_preview(content)

  return SnapshotChapterRef(
    id=_chapter_id(chapter_index),
    index=chapter_index,
    title=chapter_title,
    path=relative_path,
    status=status,
    preview=chapter_preview,
  )


def _affected_chapters_from_changes(
  project_dir: Path,
  changed_items: list[dict[str, str | int]],
) -> list[SnapshotChapterRef]:
  chapter_items: dict[str, SnapshotChapterRef] = {}

  for item in changed_items:
    relative_path = str(item["path"])
    status = str(item["status"])
    source_path = None if status == "deleted" else (project_dir / Path(relative_path))
    chapter_ref = _chapter_ref_from_source(
      project_dir,
      relative_path,
      status=status,
      source_path=source_path,
    )
    if chapter_ref is not None:
      chapter_items[chapter_ref.id] = chapter_ref

  return [chapter_items[key] for key in sorted(chapter_items, key=lambda value: chapter_items[value].index)]


def _snapshot_sources_until(project_dir: Path, snapshot_id: str) -> tuple[dict[str, Path], dict]:
  ordered_entries = sorted(_history_entries(project_dir), key=lambda item: int(item.get("version", 0)))
  file_sources: dict[str, Path] = {}
  target_manifest: dict | None = None

  for entry in ordered_entries:
    manifest = _read_snapshot_manifest(project_dir, str(entry["id"]))
    snapshot_files_dir = _snapshot_files_dir(project_dir, str(entry["id"]))
    mode = str(manifest.get("mode") or ("full" if "changes" not in manifest else "delta"))

    if mode == "full":
      file_sources = {}
      for item in manifest.get("files", []):
        path = str(item["path"])
        file_sources[path] = snapshot_files_dir / Path(path)
    else:
      for item in manifest.get("changes", []):
        path = str(item["path"])
        status = str(item["status"])
        if status == "deleted":
          file_sources.pop(path, None)
        else:
          file_sources[path] = snapshot_files_dir / Path(path)

    if str(entry["id"]) == snapshot_id:
      target_manifest = manifest
      break

  if target_manifest is None:
    raise HTTPException(
      status_code=404,
      detail={"code": "snapshot_not_found", "message": "本地快照不存在"},
    )

  return file_sources, target_manifest


def _affected_chapters_from_manifest(
  project_dir: Path,
  snapshot_id: str,
  manifest: dict | None = None,
  file_sources: dict[str, Path] | None = None,
) -> list[SnapshotChapterRef]:
  resolved_manifest = manifest if manifest is not None else _read_snapshot_manifest(project_dir, snapshot_id)
  resolved_file_sources = file_sources
  if resolved_file_sources is None:
    resolved_file_sources, _ = _snapshot_sources_until(project_dir, snapshot_id)

  chapter_items: dict[str, SnapshotChapterRef] = {}
  for item in resolved_manifest.get("changes", []):
    relative_path = str(item["path"])
    status = str(item["status"])
    source_path = None if status == "deleted" else resolved_file_sources.get(relative_path)
    chapter_ref = _chapter_ref_from_source(
      project_dir,
      relative_path,
      status=status,
      source_path=source_path,
    )
    if chapter_ref is not None:
      chapter_items[chapter_ref.id] = chapter_ref

  return [chapter_items[key] for key in sorted(chapter_items, key=lambda value: chapter_items[value].index)]


def _snapshot_preview_chapters(
  project_dir: Path,
  snapshot_id: str,
  manifest: dict | None = None,
  file_sources: dict[str, Path] | None = None,
) -> list[ChapterSummary]:
  resolved_manifest = manifest if manifest is not None else _read_snapshot_manifest(project_dir, snapshot_id)
  resolved_file_sources = file_sources
  if resolved_file_sources is None:
    resolved_file_sources, _ = _snapshot_sources_until(project_dir, snapshot_id)

  chapters: list[ChapterSummary] = []
  seen_ids: set[str] = set()
  for item in resolved_manifest.get("changes", []):
    relative_path = str(item["path"])
    status = str(item["status"])
    chapter_index = _chapter_index_from_path(relative_path)
    if chapter_index is None:
      continue

    chapter_identifier = _chapter_id(chapter_index)
    if chapter_identifier in seen_ids:
      continue
    seen_ids.add(chapter_identifier)

    source_path = None if status == "deleted" else resolved_file_sources.get(relative_path)
    if source_path is not None and source_path.exists():
      content = source_path.read_text(encoding="utf-8")
      stat = source_path.stat()
      chapters.append(
        ChapterSummary(
          id=chapter_identifier,
          index=chapter_index,
          title=_chapter_display_title(content, chapter_index),
          path=relative_path,
          exists=True,
          preview=_chapter_preview(content),
          content=content,
          updated_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        )
      )
      continue

    chapters.append(
      ChapterSummary(
        id=chapter_identifier,
        index=chapter_index,
        title=f"第 {chapter_index} 章",
        path=relative_path,
        exists=False,
        preview="",
        content="",
        updated_at=None,
      )
    )

  return sorted(chapters, key=lambda item: item.index)


def _restore_snapshot_files(project_dir: Path, snapshot_id: str) -> dict:
  file_sources, target_manifest = _snapshot_sources_until(project_dir, snapshot_id)
  snapshot_files = target_manifest.get("files", [])
  snapshot_paths = {str(item["path"]) for item in snapshot_files}
  current_paths = {
    path.relative_to(project_dir).as_posix(): path
    for path in _iter_versioned_files(project_dir)
  }

  for relative_path in sorted(set(current_paths) - snapshot_paths):
    current_paths[relative_path].unlink(missing_ok=True)

  for item in snapshot_files:
    relative_path = str(item["path"])
    source_path = file_sources.get(relative_path)
    if source_path is None or not source_path.exists():
      raise HTTPException(
        status_code=500,
        detail={"code": "snapshot_corrupted", "message": "本地版本文件缺失，无法恢复"},
      )

    target_path = project_dir / Path(relative_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)

  return target_manifest


def _restore_snapshot_chapter(project_dir: Path, snapshot_id: str, chapter_id: str) -> None:
  chapter_index = _chapter_index_from_id(chapter_id)
  relative_path = f"chapters/{_chapter_filename(chapter_index)}"
  file_sources, _ = _snapshot_sources_until(project_dir, snapshot_id)
  source_path = file_sources.get(relative_path)
  target_path = project_dir / relative_path

  if source_path is None:
    target_path.unlink(missing_ok=True)
    return

  target_path.parent.mkdir(parents=True, exist_ok=True)
  shutil.copy2(source_path, target_path)


def _working_tree_status(project_dir: Path, snapshots: list[ProjectSnapshot]) -> WorkingTreeStatus:
  current_manifest = _collect_manifest(project_dir)
  base_snapshot = snapshots[0] if snapshots else None
  base_manifest = (
    _read_snapshot_manifest(project_dir, base_snapshot.id).get("files", [])
    if base_snapshot
    else []
  )
  changed_files = _diff_manifest(current_manifest, base_manifest)

  return WorkingTreeStatus(
    clean=len(changed_files) == 0,
    changed_count=len(changed_files),
    changed_files=changed_files,
    base_snapshot_version=base_snapshot.version if base_snapshot else None,
    base_snapshot_id=base_snapshot.id if base_snapshot else None,
    base_snapshot_message=base_snapshot.message if base_snapshot else None,
    base_snapshot_created_at=base_snapshot.created_at if base_snapshot else None,
  )


def _local_history_state(project_dir: Path) -> LocalHistoryState:
  snapshots = [ProjectSnapshot.model_validate(item) for item in _history_entries(project_dir)]
  return LocalHistoryState(
    snapshots=snapshots,
    working_tree=_working_tree_status(project_dir, snapshots),
  )


def _auto_snapshot_message(changed_files: list[LocalHistoryChangedFile]) -> str:
  if len(changed_files) == 0:
    return "自动保存"

  if len(changed_files) == 1:
    return f"自动保存 · {changed_files[0].path}"

  return f"自动保存 · {changed_files[0].path} 等 {len(changed_files)} 项"


def _write_snapshot(
  project_dir: Path,
  *,
  kind: str = "manual",
  message: str,
  created_at: str | None = None,
  allow_empty: bool = False,
) -> ProjectSnapshot:
  _ensure_history_layout(project_dir)
  history_entries = _history_entries(project_dir)
  current_manifest = _collect_manifest(project_dir)
  previous_snapshot_id = history_entries[0]["id"] if history_entries else None
  next_version = max((int(item.get("version", 0)) for item in history_entries), default=0) + 1
  previous_manifest = (
    _read_snapshot_manifest(project_dir, previous_snapshot_id).get("files", [])
    if previous_snapshot_id
    else []
  )
  changed_items = _build_changed_items(current_manifest, previous_manifest)
  changed_files = [
    LocalHistoryChangedFile(path=str(item["path"]), status=str(item["status"]))
    for item in changed_items
  ]
  affected_chapters = _affected_chapters_from_changes(project_dir, changed_items)

  if not allow_empty and len(changed_files) == 0:
    raise HTTPException(
      status_code=409,
      detail={"code": "no_local_changes", "message": "当前没有新的本地改动可保存为版本"},
    )

  snapshot_id = uuid4().hex[:12]
  snapshot_created_at = created_at or _now_iso()
  snapshot_files_dir = _snapshot_files_dir(project_dir, snapshot_id)
  snapshot_files_dir.mkdir(parents=True, exist_ok=True)
  storage_mode = "full" if len(history_entries) == 0 else "delta"

  copy_items = current_manifest if storage_mode == "full" else [
    item for item in changed_items if str(item["status"]) != "deleted"
  ]

  for item in copy_items:
    relative_path = Path(str(item["path"]))
    source_path = project_dir / relative_path
    target_path = snapshot_files_dir / relative_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)

  atomic_write_json(
    _snapshot_manifest_path(project_dir, snapshot_id),
    {
      "id": snapshot_id,
      "version": next_version,
      "kind": kind,
      "message": message,
      "created_at": snapshot_created_at,
      "mode": storage_mode,
      "base_snapshot_id": previous_snapshot_id,
      "affected_chapters": [item.model_dump(mode="json") for item in affected_chapters],
      "files": current_manifest,
      "changes": changed_items,
    },
  )

  snapshot_payload = {
    "id": snapshot_id,
    "version": next_version,
    "kind": kind,
    "message": message,
    "created_at": snapshot_created_at,
    "file_count": len(current_manifest),
    "changed_count": len(changed_files),
    "affected_chapters": [item.model_dump(mode="json") for item in affected_chapters],
  }
  history_entries.insert(0, snapshot_payload)
  atomic_write_json(_history_index_path(project_dir), history_entries)
  return ProjectSnapshot.model_validate(snapshot_payload)


def _touch_project_timestamp(settings: Settings, project_id: str, updated_at: str) -> None:
  project_items = [ProjectSummary.model_validate(item) for item in read_json(project_index_path(settings), [])]
  updated_projects: list[ProjectSummary] = []
  project_summary: ProjectSummary | None = None

  for item in project_items:
    if item.id == project_id:
      item = item.model_copy(update={"updated_at": updated_at})
      project_summary = item
    updated_projects.append(item)

  if project_summary is None:
    raise HTTPException(
      status_code=404,
      detail={"code": "project_not_found", "message": "项目不存在"},
    )

  _write_project_index(settings, updated_projects)

  project_meta_path = _project_meta_path(_project_dir(project_summary))
  project_meta = read_json(project_meta_path, {})
  if isinstance(project_meta, dict):
    project_meta["updated_at"] = updated_at
    atomic_write_json(project_meta_path, project_meta)


def update_project_targets(
  settings: Settings,
  project_id: str,
  *,
  target_chapters: int | None = None,
  target_words: int | None = None,
  genre: str | None = None,
  updated_at: str | None = None,
) -> ProjectSummary:
  project_items = [ProjectSummary.model_validate(item) for item in read_json(project_index_path(settings), [])]
  next_projects: list[ProjectSummary] = []
  project_summary: ProjectSummary | None = None
  target_chapters_changed = False
  next_updated_at = updated_at or _now_iso()

  for item in project_items:
    if item.id != project_id:
      next_projects.append(item)
      continue

    next_item = item.model_copy(
      update={
        "target_chapters": target_chapters if target_chapters is not None else item.target_chapters,
        "target_words": target_words if target_words is not None else item.target_words,
        "genre": genre if genre is not None else item.genre,
        "updated_at": next_updated_at,
      }
    )
    target_chapters_changed = target_chapters is not None and target_chapters != item.target_chapters
    project_summary = next_item
    next_projects.append(next_item)

  if project_summary is None:
    raise HTTPException(
      status_code=404,
      detail={"code": "project_not_found", "message": "项目不存在"},
    )

  _write_project_index(settings, next_projects)

  project_meta_path = _project_meta_path(_project_dir(project_summary))
  project_meta = read_json(project_meta_path, {})
  if isinstance(project_meta, dict):
    project_meta["target_chapters"] = project_summary.target_chapters
    project_meta["target_words"] = project_summary.target_words
    project_meta["genre"] = project_summary.genre
    project_meta["updated_at"] = project_summary.updated_at
    atomic_write_json(project_meta_path, project_meta)

  if target_chapters_changed:
    _rebuild_project_knowledge(_project_dir(project_summary), project_summary.target_chapters, settings)
  return project_summary


def _build_chapter_summary(project_dir: Path, index: int) -> ChapterSummary:
  chapter_path = _chapter_file_path(project_dir, index)
  relative_path = chapter_path.relative_to(project_dir)

  if chapter_path.exists():
    content = chapter_path.read_text(encoding="utf-8")
    stat = chapter_path.stat()
    updated_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
    return ChapterSummary(
      id=f"chapter-{index:03d}",
      index=index,
      title=_chapter_display_title(content, index),
      path=str(relative_path),
      exists=True,
      preview=_chapter_preview(content),
      content=content,
      updated_at=updated_at,
    )

  return ChapterSummary(
    id=f"chapter-{index:03d}",
    index=index,
    title=f"第 {index} 章",
    path=str(relative_path),
    exists=False,
    preview="",
    content="",
    updated_at=None,
  )


def _initialize_knowledge_db(path: Path) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  connection = sqlite3.connect(path)
  try:
    connection.execute(
      """
      CREATE TABLE IF NOT EXISTS knowledge_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_key TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'knowledge',
        created_at TEXT NOT NULL
      )
      """
    )
    connection.execute(
      """
      CREATE TABLE IF NOT EXISTS knowledge_index_state (
        state_key TEXT PRIMARY KEY,
        state_value TEXT NOT NULL
      )
      """
    )
    legacy_table = connection.execute(
      """
      SELECT sql FROM sqlite_master
      WHERE name = 'knowledge_chunks'
      """
    ).fetchone()
    if legacy_table is not None:
      legacy_sql = str(legacy_table[0] or "")
      if "VIRTUAL TABLE" in legacy_sql.upper():
        connection.execute("DROP TABLE knowledge_chunks")
    connection.execute(
      """
      CREATE TABLE IF NOT EXISTS knowledge_chunks (
        chunk_id TEXT PRIMARY KEY,
        source_key TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT 'knowledge',
        source TEXT NOT NULL DEFAULT '',
        section TEXT NOT NULL DEFAULT '',
        content TEXT NOT NULL,
        tokens TEXT NOT NULL DEFAULT '',
        content_hash TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
      )
      """
    )
    try:
      connection.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts
        USING fts5(chunk_id UNINDEXED, content, tokens, source UNINDEXED, section UNINDEXED, tokenize = 'unicode61')
        """
      )
    except sqlite3.OperationalError:
      connection.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_chunks_fts (
          chunk_id TEXT PRIMARY KEY,
          content TEXT NOT NULL,
          tokens TEXT NOT NULL DEFAULT '',
          source TEXT NOT NULL DEFAULT '',
          section TEXT NOT NULL DEFAULT ''
        )
        """
      )
    connection.execute(
      """
      CREATE TABLE IF NOT EXISTS knowledge_vectors (
        chunk_id TEXT PRIMARY KEY,
        content_hash TEXT NOT NULL,
        embedding_signature TEXT NOT NULL,
        vector_json TEXT NOT NULL,
        vector_blob BLOB,
        vector_dimension INTEGER NOT NULL DEFAULT 0,
        vector_norm REAL NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
      )
      """
    )
    _ensure_sqlite_column(connection, "knowledge_sources", "source_key", "source_key TEXT NOT NULL DEFAULT ''")
    _ensure_sqlite_column(connection, "knowledge_chunks", "source_key", "source_key TEXT NOT NULL DEFAULT ''")
    _ensure_sqlite_column(connection, "knowledge_vectors", "vector_blob", "vector_blob BLOB")
    _ensure_sqlite_column(connection, "knowledge_vectors", "vector_dimension", "vector_dimension INTEGER NOT NULL DEFAULT 0")
    connection.execute(
      "CREATE INDEX IF NOT EXISTS idx_knowledge_sources_source_key ON knowledge_sources(source_key)"
    )
    connection.execute(
      "CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_source_key ON knowledge_chunks(source_key)"
    )
    connection.execute(
      "CREATE INDEX IF NOT EXISTS idx_knowledge_vectors_signature ON knowledge_vectors(embedding_signature)"
    )
    _backfill_vector_blobs(connection)
    connection.commit()
  finally:
    connection.close()


def _ordered_unique(items: list[str]) -> list[str]:
  seen: set[str] = set()
  ordered: list[str] = []
  for item in items:
    cleaned = item.strip()
    if not cleaned or cleaned in seen:
      continue
    seen.add(cleaned)
    ordered.append(cleaned)
  return ordered


def _compact_text(text: str, limit: int = 180) -> str:
  normalized = " ".join(text.split())
  if len(normalized) <= limit:
    return normalized
  return f"{normalized[:limit].rstrip()}…"


def _read_story_document(project_dir: Path, filename: str, key: str, label: str) -> StoryDocument:
  path = project_dir / filename
  content = ""
  updated_at = None
  if path.exists() and path.is_file():
    try:
      content = path.read_text(encoding="utf-8")
    except OSError:
      content = ""

    try:
      updated_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
      updated_at = None

  return StoryDocument(
    key=key,
    label=label,
    filename=filename,
    content=content,
    updated_at=updated_at,
  )


def _build_story_documents(project_dir: Path) -> list[StoryDocument]:
  return [
    _read_story_document(project_dir, filename, key, label)
    for filename, key, label in _STORY_DOCUMENT_SPECS
  ]


def _references_dir(project_dir: Path) -> Path:
  return project_dir / _REFERENCE_DIRNAME


def _knowledge_material_path(project_dir: Path, title: str) -> Path:
  filename = f"{_safe_folder_name(title).replace(' ', '_')}.json"
  return _references_dir(project_dir) / filename


def _read_knowledge_material(path: Path) -> KnowledgeMaterial | None:
  payload = read_json(path, None)
  if not isinstance(payload, dict):
    return None

  title = str(payload.get("title") or "").strip()
  content = str(payload.get("content") or "").strip()
  if not title or not content:
    return None

  updated_at = str(payload.get("updated_at") or "").strip() or None
  if updated_at is None:
    try:
      updated_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
      updated_at = None

  return KnowledgeMaterial(
    title=title,
    filename=path.name,
    preview=_compact_text(content, limit=160),
    updated_at=updated_at,
  )


def _build_knowledge_materials(project_dir: Path) -> list[KnowledgeMaterial]:
  directory = _references_dir(project_dir)
  if not directory.exists():
    return []

  materials: list[KnowledgeMaterial] = []
  for path in sorted(directory.glob("*.json")):
    item = _read_knowledge_material(path)
    if item is not None:
      materials.append(item)

  materials.sort(
    key=lambda item: (
      item.updated_at or "",
      item.title,
    ),
    reverse=True,
  )
  return materials


def _load_knowledge_material_payloads(project_dir: Path) -> list[dict[str, str]]:
  directory = _references_dir(project_dir)
  if not directory.exists():
    return []

  materials: list[dict[str, str]] = []
  for path in sorted(directory.glob("*.json")):
    payload = read_json(path, None)
    if not isinstance(payload, dict):
      continue

    title = str(payload.get("title") or "").strip()
    content = str(payload.get("content") or "").strip()
    if not title or not content:
      continue

    updated_at = str(payload.get("updated_at") or "").strip()
    if not updated_at:
      try:
        updated_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
      except OSError:
        updated_at = ""

    materials.append(
      {
        "title": title,
        "content": content,
        "filename": path.name,
        "updated_at": updated_at,
      }
    )

  materials.sort(
    key=lambda item: (
      item.get("updated_at", ""),
      item.get("title", ""),
    ),
    reverse=True,
  )
  return materials


def _story_document_spec_or_404(document_key: str) -> tuple[str, str, str]:
  for filename, key, label in _STORY_DOCUMENT_SPECS:
    if key == document_key:
      return filename, key, label

  raise HTTPException(
    status_code=404,
    detail={"code": "story_document_not_found", "message": "故事文档不存在"},
  )


def _knowledge_db_path(project_dir: Path) -> Path:
  return project_dir / "knowledge.db"


def _sqlite_columns(connection: sqlite3.Connection, table: str) -> set[str]:
  return {
    str(row[1])
    for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
  }


def _ensure_sqlite_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
  if column in _sqlite_columns(connection, table):
    return
  connection.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def _vector_to_float_array(values: list[float]) -> array:
  output = array("f")
  output.extend(float(value) for value in values)
  return output


def _vector_blob(values: list[float]) -> bytes:
  return _vector_to_float_array(values).tobytes()


def _vector_from_blob(blob: bytes | memoryview | None) -> array:
  output = array("f")
  if blob is None:
    return output
  try:
    output.frombytes(bytes(blob))
  except ValueError:
    return array("f")
  return output


def _vector_from_json(raw_json: object) -> array:
  try:
    values = json.loads(str(raw_json))
  except (TypeError, json.JSONDecodeError):
    return array("f")
  if not isinstance(values, list):
    return array("f")
  output = array("f")
  try:
    output.extend(float(item) for item in values)
  except (TypeError, ValueError):
    return array("f")
  return output


def _vector_from_storage(blob: bytes | memoryview | None, raw_json: object) -> array:
  vector = _vector_from_blob(blob)
  if vector:
    return vector
  return _vector_from_json(raw_json)


def _vector_norm(values: array | list[float]) -> float:
  return float(sum(float(value) * float(value) for value in values) ** 0.5)


def _cosine_similarity_values(
  query_vector: array,
  stored_vector: array,
  query_norm: float,
  stored_norm: float,
) -> float:
  if query_norm <= 0 or stored_norm <= 0 or len(query_vector) != len(stored_vector):
    return 0.0
  dot = sum(float(left) * float(right) for left, right in zip(query_vector, stored_vector))
  return dot / (query_norm * stored_norm)


def _backfill_vector_blobs(connection: sqlite3.Connection) -> None:
  rows = connection.execute(
    """
    SELECT chunk_id, vector_json
    FROM knowledge_vectors
    WHERE (vector_blob IS NULL OR vector_dimension <= 0)
      AND vector_json IS NOT NULL
      AND vector_json != ''
    """
  ).fetchall()
  if not rows:
    return

  updates = []
  for chunk_id, vector_json in rows:
    vector = _vector_from_json(vector_json)
    if not vector:
      continue
    updates.append((sqlite3.Binary(vector.tobytes()), len(vector), str(chunk_id)))

  if updates:
    connection.executemany(
      """
      UPDATE knowledge_vectors
      SET vector_blob = ?, vector_dimension = ?
      WHERE chunk_id = ?
      """,
      updates,
    )


def _knowledge_supports_fts(connection: sqlite3.Connection) -> bool:
  row = connection.execute(
    """
    SELECT sql FROM sqlite_master
    WHERE name = 'knowledge_chunks_fts'
    """
  ).fetchone()
  if row is None:
    return False

  sql = str(row[0] or "")
  return "VIRTUAL TABLE" in sql.upper() and "FTS5" in sql.upper()


def _get_knowledge_state(connection: sqlite3.Connection, key: str) -> str:
  row = connection.execute(
    """
    SELECT state_value FROM knowledge_index_state
    WHERE state_key = ?
    """,
    (key,),
  ).fetchone()
  return str(row[0]) if row is not None else ""


def _set_knowledge_state(connection: sqlite3.Connection, key: str, value: str) -> None:
  connection.execute(
    """
    INSERT INTO knowledge_index_state (state_key, state_value)
    VALUES (?, ?)
    ON CONFLICT(state_key) DO UPDATE SET state_value = excluded.state_value
    """,
    (key, value),
  )


def _knowledge_tokens(text: str) -> str:
  normalized = re.sub(r"\s+", "", text)
  compact = re.sub(r"[^\w\u4e00-\u9fff]", "", normalized)
  tokens: list[str] = []

  if compact:
    max_ngram = 3
    for size in range(1, max_ngram + 1):
      if len(compact) < size:
        continue
      for index in range(len(compact) - size + 1):
        token = compact[index : index + size]
        if token not in tokens:
          tokens.append(token)

  for item in re.findall(r"[A-Za-z0-9_]+", text.lower()):
    if item not in tokens:
      tokens.append(item)

  return " ".join(tokens)


def _split_knowledge_chunks(text: str, limit: int = 220) -> list[str]:
  normalized = text.replace("\r\n", "\n").strip()
  if not normalized:
    return []

  chunks: list[str] = []
  buffer = ""

  paragraphs = [item.strip() for item in normalized.split("\n\n") if item.strip()]
  for paragraph in paragraphs:
    sentences = _split_sentences(paragraph)
    if not sentences:
      sentences = [paragraph]

    for sentence in sentences:
      candidate = sentence.strip()
      if not candidate:
        continue

      if len(candidate) > limit:
        if buffer:
          chunks.append(buffer)
          buffer = ""
        for start in range(0, len(candidate), limit):
          piece = candidate[start : start + limit].strip()
          if piece:
            chunks.append(piece)
        continue

      merged = f"{buffer}\n{candidate}".strip() if buffer else candidate
      if len(merged) > limit and buffer:
        chunks.append(buffer)
        buffer = candidate
      else:
        buffer = merged

    if buffer:
      chunks.append(buffer)
      buffer = ""

  if buffer:
    chunks.append(buffer)

  return chunks


def _knowledge_source_signature(project_dir: Path, target_chapters: int) -> str:
  candidates: list[Path] = []
  for filename, _key, _label in _STORY_DOCUMENT_SPECS:
    path = project_dir / filename
    if path.exists():
      candidates.append(path)

  for index in range(1, target_chapters + 1):
    chapter_path = _chapter_file_path(project_dir, index)
    if chapter_path.exists():
      candidates.append(chapter_path)

  references_dir = _references_dir(project_dir)
  if references_dir.exists():
    candidates.extend(sorted(references_dir.glob("*.json")))

  digest = hashlib.sha1()
  for path in sorted(candidates):
    stat = path.stat()
    digest.update(str(path.relative_to(project_dir)).encode("utf-8"))
    digest.update(str(stat.st_mtime_ns).encode("utf-8"))
    digest.update(str(stat.st_size).encode("utf-8"))
  return digest.hexdigest()


def _knowledge_chunk_id(kind: str, source: str, section: str, index: int, content: str) -> str:
  payload = f"{kind}|{source}|{section}|{index}|{content}"
  return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _story_document_source_key(document_key: str) -> str:
  return f"story:{document_key}"


def _chapter_source_key(index: int) -> str:
  return f"chapter:{_chapter_id(index)}"


def _reference_source_key(filename: str) -> str:
  return f"reference:{filename}"


def _knowledge_source_key_for_relative_path(relative_path: str) -> str:
  normalized = relative_path.strip().replace("\\", "/")
  for filename, key, _label in _STORY_DOCUMENT_SPECS:
    if normalized == filename:
      return _story_document_source_key(key)

  chapter_index = _chapter_index_from_path(normalized)
  if chapter_index is not None:
    return _chapter_source_key(chapter_index)

  if normalized.startswith(f"{_REFERENCE_DIRNAME}/") and normalized.endswith(".json"):
    return _reference_source_key(Path(normalized).name)

  return ""


def _content_hash(content: str) -> str:
  return hashlib.sha1(content.encode("utf-8")).hexdigest()


def _build_knowledge_chunk_rows(
  *,
  source_key: str,
  kind: str,
  source: str,
  section: str,
  content: str,
  created_at: str,
) -> list[dict[str, str]]:
  rows: list[dict[str, str]] = []
  for index, chunk in enumerate(_split_knowledge_chunks(content)):
    rows.append(
      {
        "chunk_id": _knowledge_chunk_id(kind, source, section, index, chunk),
        "source_key": source_key,
        "kind": kind,
        "source": source,
        "section": section,
        "content": chunk,
        "tokens": _knowledge_tokens(chunk),
        "content_hash": _content_hash(chunk),
        "created_at": created_at,
      }
    )
  return rows


def _sync_knowledge_vectors(
  settings: Settings,
  connection: sqlite3.Connection,
  chunk_rows: list[dict[str, str]],
  embedding_signature: str,
  *,
  prune_missing: bool = True,
) -> None:
  active_chunk_ids = {row["chunk_id"] for row in chunk_rows}
  existing_rows: dict[str, tuple[str, str, bool]] = {}

  if active_chunk_ids:
    placeholders = ",".join("?" for _item in active_chunk_ids)
    existing_rows = {
      str(chunk_id): (
        str(content_hash),
        str(saved_signature),
        bool(has_blob),
      )
      for chunk_id, content_hash, saved_signature, has_blob in connection.execute(
        f"""
        SELECT chunk_id, content_hash, embedding_signature,
               CASE
                 WHEN vector_blob IS NOT NULL AND length(vector_blob) > 0 AND vector_dimension > 0 THEN 1
                 ELSE 0
               END AS has_blob
        FROM knowledge_vectors
        WHERE chunk_id IN ({placeholders})
        """,
        tuple(active_chunk_ids),
      ).fetchall()
    }

  if prune_missing:
    saved_ids = [
      str(row[0])
      for row in connection.execute("SELECT chunk_id FROM knowledge_vectors").fetchall()
    ]
    stale_ids = [chunk_id for chunk_id in saved_ids if chunk_id not in active_chunk_ids]
    if stale_ids:
      connection.executemany(
        "DELETE FROM knowledge_vectors WHERE chunk_id = ?",
        [(chunk_id,) for chunk_id in stale_ids],
      )

  if not embedding_signature.endswith("ready"):
    if prune_missing:
      connection.execute("DELETE FROM knowledge_vectors")
    elif active_chunk_ids:
      connection.executemany(
        "DELETE FROM knowledge_vectors WHERE chunk_id = ?",
        [(chunk_id,) for chunk_id in active_chunk_ids],
      )
    return

  rows_to_embed = [
    row for row in chunk_rows
    if existing_rows.get(row["chunk_id"]) != (row["content_hash"], embedding_signature, True)
  ]
  if not rows_to_embed:
    return

  try:
    vectors = embed_texts(
      settings,
      [row["content"] for row in rows_to_embed],
      task_name="project_knowledge_embedding",
    )
  except Exception as error:
    append_app_log(settings, f"project_knowledge_embedding skipped: {error}", level="ERROR")
    return

  updated_at = _now_iso()
  connection.executemany(
    """
    INSERT INTO knowledge_vectors (
      chunk_id, content_hash, embedding_signature, vector_json, vector_blob, vector_dimension, vector_norm, updated_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(chunk_id) DO UPDATE SET
      content_hash = excluded.content_hash,
      embedding_signature = excluded.embedding_signature,
      vector_json = excluded.vector_json,
      vector_blob = excluded.vector_blob,
      vector_dimension = excluded.vector_dimension,
      vector_norm = excluded.vector_norm,
      updated_at = excluded.updated_at
    """,
    [
      (
        row["chunk_id"],
        row["content_hash"],
        embedding_signature,
        "",
        sqlite3.Binary(_vector_blob(vector)),
        len(vector),
        _vector_norm(vector),
        updated_at,
      )
      for row, vector in zip(rows_to_embed, vectors)
    ],
  )


def _insert_knowledge_chunk_rows(connection: sqlite3.Connection, chunk_rows: list[dict[str, str]]) -> None:
  if not chunk_rows:
    return
  connection.executemany(
    """
    INSERT INTO knowledge_chunks (
      chunk_id, source_key, kind, source, section, content, tokens, content_hash, created_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    [
      (
        row["chunk_id"],
        row["source_key"],
        row["kind"],
        row["source"],
        row["section"],
        row["content"],
        row["tokens"],
        row["content_hash"],
        row["created_at"],
      )
      for row in chunk_rows
    ],
  )
  connection.executemany(
    """
    INSERT INTO knowledge_chunks_fts (chunk_id, content, tokens, source, section)
    VALUES (?, ?, ?, ?, ?)
    """,
    [
      (
        row["chunk_id"],
        row["content"],
        row["tokens"],
        row["source"],
        row["section"],
      )
      for row in chunk_rows
    ],
  )


def _delete_knowledge_chunk_ids(
  connection: sqlite3.Connection,
  chunk_ids: list[str],
  *,
  delete_vectors: bool = True,
) -> None:
  if not chunk_ids:
    return
  rows = [(chunk_id,) for chunk_id in chunk_ids]
  connection.executemany("DELETE FROM knowledge_chunks_fts WHERE chunk_id = ?", rows)
  connection.executemany("DELETE FROM knowledge_chunks WHERE chunk_id = ?", rows)
  if delete_vectors:
    connection.executemany("DELETE FROM knowledge_vectors WHERE chunk_id = ?", rows)


def _replace_knowledge_source_rows(
  connection: sqlite3.Connection,
  *,
  source_key: str,
  source: str,
  kind: str,
  created_at: str,
  chunk_rows: list[dict[str, str]],
) -> None:
  old_chunk_ids = [
    str(row[0])
    for row in connection.execute(
      "SELECT chunk_id FROM knowledge_chunks WHERE source_key = ?",
      (source_key,),
    ).fetchall()
  ]
  next_chunk_ids = {row["chunk_id"] for row in chunk_rows}
  _delete_knowledge_chunk_ids(connection, old_chunk_ids, delete_vectors=False)
  stale_vector_ids = [chunk_id for chunk_id in old_chunk_ids if chunk_id not in next_chunk_ids]
  if stale_vector_ids:
    connection.executemany(
      "DELETE FROM knowledge_vectors WHERE chunk_id = ?",
      [(chunk_id,) for chunk_id in stale_vector_ids],
    )
  connection.execute("DELETE FROM knowledge_sources WHERE source_key = ?", (source_key,))
  if not chunk_rows:
    return
  connection.execute(
    "INSERT INTO knowledge_sources (source_key, source, kind, created_at) VALUES (?, ?, ?, ?)",
    (source_key, source, kind, created_at),
  )
  _insert_knowledge_chunk_rows(connection, chunk_rows)


def _knowledge_rows_for_source_key(project_dir: Path, source_key: str, created_at: str) -> tuple[str, str, list[dict[str, str]]]:
  if source_key.startswith("story:"):
    target_key = source_key.split(":", 1)[1]
    for filename, key, label in _STORY_DOCUMENT_SPECS:
      if key != target_key:
        continue
      path = project_dir / filename
      content = path.read_text(encoding="utf-8") if path.exists() else ""
      rows = _build_knowledge_chunk_rows(
        source_key=source_key,
        kind="story_document",
        source="架构文件",
        section=label,
        content=content,
        created_at=created_at,
      ) if content.strip() else []
      return "架构文件", "story_document", rows
    return "架构文件", "story_document", []

  if source_key.startswith("chapter:"):
    chapter_id = source_key.split(":", 1)[1]
    try:
      chapter_index = _chapter_index_from_id(chapter_id)
    except HTTPException:
      return "章节正文", "chapter", []
    chapter = _build_chapter_summary(project_dir, chapter_index)
    rows = _build_knowledge_chunk_rows(
      source_key=source_key,
      kind="chapter",
      source="章节正文",
      section=f"第 {chapter.index} 章 · {chapter.title}",
      content=chapter.content,
      created_at=created_at,
    ) if chapter.exists and chapter.content.strip() else []
    return "章节正文", "chapter", rows

  if source_key.startswith("reference:"):
    filename = source_key.split(":", 1)[1]
    path = _references_dir(project_dir) / filename
    payload = read_json(path, None)
    if not isinstance(payload, dict):
      return "资料库", "reference", []
    title = str(payload.get("title") or "").strip()
    content = str(payload.get("content") or "").strip()
    if not title or not content:
      return "资料库", "reference", []
    material_updated_at = str(payload.get("updated_at") or "").strip() or created_at
    rows = _build_knowledge_chunk_rows(
      source_key=source_key,
      kind="reference",
      source="资料库",
      section=title,
      content=content,
      created_at=material_updated_at,
    )
    return "资料库", "reference", rows

  return "", "", []


def _refresh_project_knowledge_sources(
  settings: Settings,
  project_dir: Path,
  target_chapters: int,
  source_keys: list[str],
) -> None:
  clean_source_keys = _ordered_unique([item for item in source_keys if item.strip()])
  if not clean_source_keys:
    return

  db_path = _knowledge_db_path(project_dir)
  _initialize_knowledge_db(db_path)
  embedding_signature = embedding_config_signature(settings)
  connection = sqlite3.connect(db_path)
  try:
    indexed_source_signature = _get_knowledge_state(connection, "source_signature")
    indexed_embedding_signature = _get_knowledge_state(connection, "embedding_signature")
    indexed_schema_version = _get_knowledge_state(connection, "schema_version")
  finally:
    connection.close()

  if (
    not indexed_source_signature
    or indexed_embedding_signature != embedding_signature
    or indexed_schema_version != _KNOWLEDGE_SCHEMA_VERSION
  ):
    _rebuild_project_knowledge(project_dir, target_chapters, settings)
    return

  connection = sqlite3.connect(db_path)
  try:
    created_at = _now_iso()
    vector_rows: list[dict[str, str]] = []
    for source_key in clean_source_keys:
      source, kind, chunk_rows = _knowledge_rows_for_source_key(project_dir, source_key, created_at)
      if not source or not kind:
        continue
      _replace_knowledge_source_rows(
        connection,
        source_key=source_key,
        source=source,
        kind=kind,
        created_at=created_at,
        chunk_rows=chunk_rows,
      )
      vector_rows.extend(chunk_rows)

    _sync_knowledge_vectors(
      settings,
      connection,
      vector_rows,
      embedding_signature,
      prune_missing=False,
    )
    _set_knowledge_state(connection, "source_signature", _knowledge_source_signature(project_dir, target_chapters))
    _set_knowledge_state(connection, "embedding_signature", embedding_signature)
    _set_knowledge_state(connection, "schema_version", _KNOWLEDGE_SCHEMA_VERSION)
    _set_knowledge_state(connection, "indexed_at", _now_iso())
    connection.commit()
  finally:
    connection.close()


def _refresh_project_knowledge_for_paths(
  settings: Settings,
  project_dir: Path,
  target_chapters: int,
  relative_paths: list[str],
) -> None:
  source_keys = [
    _knowledge_source_key_for_relative_path(relative_path)
    for relative_path in relative_paths
  ]
  _refresh_project_knowledge_sources(settings, project_dir, target_chapters, source_keys)


def _rebuild_project_knowledge(project_dir: Path, target_chapters: int, settings: Settings) -> None:
  db_path = _knowledge_db_path(project_dir)
  _initialize_knowledge_db(db_path)
  connection = sqlite3.connect(db_path)
  try:
    connection.execute("DELETE FROM knowledge_sources")
    connection.execute("DELETE FROM knowledge_chunks")
    connection.execute("DELETE FROM knowledge_chunks_fts")
    now = _now_iso()
    chunk_rows: list[dict[str, str]] = []

    for filename, _key, label in _STORY_DOCUMENT_SPECS:
      path = project_dir / filename
      if not path.exists():
        continue
      content = path.read_text(encoding="utf-8")
      if not content.strip():
        continue
      connection.execute(
        "INSERT INTO knowledge_sources (source_key, source, kind, created_at) VALUES (?, ?, ?, ?)",
        (_story_document_source_key(_key), "架构文件", "story_document", now),
      )
      chunk_rows.extend(
        _build_knowledge_chunk_rows(
          source_key=_story_document_source_key(_key),
          kind="story_document",
          source="架构文件",
          section=label,
          content=content,
          created_at=now,
        )
      )

    for index in range(1, target_chapters + 1):
      chapter = _build_chapter_summary(project_dir, index)
      if not chapter.exists or not chapter.content.strip():
        continue
      connection.execute(
        "INSERT INTO knowledge_sources (source_key, source, kind, created_at) VALUES (?, ?, ?, ?)",
        (_chapter_source_key(chapter.index), "章节正文", "chapter", now),
      )
      chunk_rows.extend(
        _build_knowledge_chunk_rows(
          source_key=_chapter_source_key(chapter.index),
          kind="chapter",
          source="章节正文",
          section=f"第 {chapter.index} 章 · {chapter.title}",
          content=chapter.content,
          created_at=now,
        )
      )

    for material in _build_knowledge_materials(project_dir):
      material_path = _references_dir(project_dir) / material.filename
      payload = read_json(material_path, {})
      content = str(payload.get("content") or "").strip() if isinstance(payload, dict) else ""
      if not content:
        continue
      connection.execute(
        "INSERT INTO knowledge_sources (source_key, source, kind, created_at) VALUES (?, ?, ?, ?)",
        (_reference_source_key(material.filename), "资料库", "reference", material.updated_at or now),
      )
      chunk_rows.extend(
        _build_knowledge_chunk_rows(
          source_key=_reference_source_key(material.filename),
          kind="reference",
          source="资料库",
          section=material.title,
          content=content,
          created_at=material.updated_at or now,
        )
      )

    connection.executemany(
      """
      INSERT INTO knowledge_chunks (
        chunk_id, source_key, kind, source, section, content, tokens, content_hash, created_at
      )
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
      """,
      [
        (
          row["chunk_id"],
          row["source_key"],
          row["kind"],
          row["source"],
          row["section"],
          row["content"],
          row["tokens"],
          row["content_hash"],
          row["created_at"],
        )
        for row in chunk_rows
      ],
    )
    connection.executemany(
      """
      INSERT INTO knowledge_chunks_fts (chunk_id, content, tokens, source, section)
      VALUES (?, ?, ?, ?, ?)
      """,
      [
        (
          row["chunk_id"],
          row["content"],
          row["tokens"],
          row["source"],
          row["section"],
        )
        for row in chunk_rows
      ],
    )

    embedding_signature = embedding_config_signature(settings)
    _sync_knowledge_vectors(settings, connection, chunk_rows, embedding_signature)
    _set_knowledge_state(connection, "source_signature", _knowledge_source_signature(project_dir, target_chapters))
    _set_knowledge_state(connection, "embedding_signature", embedding_signature)
    _set_knowledge_state(connection, "schema_version", _KNOWLEDGE_SCHEMA_VERSION)
    _set_knowledge_state(connection, "indexed_at", now)
    connection.commit()
  finally:
    connection.close()


def _ensure_project_knowledge_current(settings: Settings, project_dir: Path, target_chapters: int) -> None:
  db_path = _knowledge_db_path(project_dir)
  _initialize_knowledge_db(db_path)
  connection = sqlite3.connect(db_path)
  try:
    current_source_signature = _knowledge_source_signature(project_dir, target_chapters)
    current_embedding_signature = embedding_config_signature(settings)
    indexed_source_signature = _get_knowledge_state(connection, "source_signature")
    indexed_embedding_signature = _get_knowledge_state(connection, "embedding_signature")
    indexed_schema_version = _get_knowledge_state(connection, "schema_version")
  finally:
    connection.close()

  if (
    indexed_source_signature != current_source_signature
    or indexed_embedding_signature != current_embedding_signature
    or indexed_schema_version != _KNOWLEDGE_SCHEMA_VERSION
  ):
    _rebuild_project_knowledge(project_dir, target_chapters, settings)


def _knowledge_candidate_limit(limit: int) -> int:
  return max(
    _KNOWLEDGE_SEMANTIC_CANDIDATE_MIN,
    min(max(1, limit) * 8, _KNOWLEDGE_SEMANTIC_CANDIDATE_CAP),
  )


def _keyword_search_project_knowledge(connection: sqlite3.Connection, query: str, limit: int) -> list[dict[str, object]]:
  normalized = query.strip()
  if not normalized:
    return []
  search_limit = max(1, min(limit, _KNOWLEDGE_SEMANTIC_CANDIDATE_CAP))

  if _knowledge_supports_fts(connection):
    tokens = _knowledge_tokens(normalized).split()
    fts_query = " OR ".join(tokens[:10]) if tokens else normalized
    rows = connection.execute(
      """
      SELECT knowledge_chunks.chunk_id, knowledge_chunks.source, knowledge_chunks.section, knowledge_chunks.content,
             bm25(knowledge_chunks_fts) AS score
      FROM knowledge_chunks_fts
      JOIN knowledge_chunks ON knowledge_chunks.chunk_id = knowledge_chunks_fts.chunk_id
      WHERE knowledge_chunks_fts MATCH ?
      ORDER BY score
      LIMIT ?
      """,
      (fts_query, search_limit),
    ).fetchall()
    return [
      {
        "chunk_id": str(chunk_id),
        "source": str(source),
        "section": str(section),
        "content": str(content),
        "score": float(-score) if isinstance(score, (int, float)) else 0.0,
        "match_type": "keyword",
      }
      for chunk_id, source, section, content, score in rows
    ]

  like_query = f"%{normalized}%"
  rows = connection.execute(
    """
    SELECT chunk_id, source, section, content
    FROM knowledge_chunks
    WHERE content LIKE ? OR tokens LIKE ?
    ORDER BY LENGTH(content) ASC
    LIMIT ?
    """,
    (like_query, like_query, search_limit),
  ).fetchall()
  return [
    {
      "chunk_id": str(chunk_id),
      "source": str(source),
      "section": str(section),
      "content": str(content),
      "score": 0.0,
      "match_type": "keyword",
    }
    for chunk_id, source, section, content in rows
  ]


def _semantic_search_project_knowledge(
  settings: Settings,
  connection: sqlite3.Connection,
  query: str,
  limit: int,
  *,
  candidate_chunk_ids: list[str] | None = None,
) -> list[dict[str, object]]:
  try:
    query_vectors = embed_texts(settings, [query], task_name="project_query_embedding")
  except Exception:
    return []
  if not query_vectors:
    return []

  query_vector = _vector_to_float_array(query_vectors[0])
  query_norm = _vector_norm(query_vector)
  if query_norm <= 0:
    return []

  params: tuple[str, ...] = ()
  where_sql = ""
  if candidate_chunk_ids is not None:
    candidate_ids = _ordered_unique(candidate_chunk_ids)
    if not candidate_ids:
      return []
    placeholders = ",".join("?" for _item in candidate_ids)
    where_sql = f"WHERE knowledge_vectors.chunk_id IN ({placeholders})"
    params = tuple(candidate_ids)

  rows = connection.execute(
    f"""
    SELECT knowledge_chunks.chunk_id, knowledge_chunks.source, knowledge_chunks.section, knowledge_chunks.content,
           knowledge_vectors.vector_blob, knowledge_vectors.vector_json, knowledge_vectors.vector_norm
    FROM knowledge_vectors
    JOIN knowledge_chunks ON knowledge_chunks.chunk_id = knowledge_vectors.chunk_id
    {where_sql}
    """,
    params,
  ).fetchall()

  scored: list[dict[str, object]] = []
  for chunk_id, source, section, content, vector_blob, vector_json, vector_norm in rows:
    vector = _vector_from_storage(vector_blob, vector_json)
    if not vector:
      continue
    similarity = _cosine_similarity_values(query_vector, vector, query_norm, float(vector_norm or 0))
    if similarity <= 0:
      continue
    scored.append(
      {
        "chunk_id": str(chunk_id),
        "source": str(source),
        "section": str(section),
        "content": str(content),
        "score": similarity,
        "match_type": "semantic",
      }
    )

  scored.sort(key=lambda item: float(item["score"]), reverse=True)
  return scored[: max(1, min(limit, 20))]


def _search_project_knowledge(settings: Settings, project_dir: Path, query: str, limit: int = 8) -> list[KnowledgeSearchResult]:
  normalized = query.strip()
  if not normalized:
    return []

  db_path = _knowledge_db_path(project_dir)
  if not db_path.exists():
    return []

  search_limit = max(1, min(limit, 20))
  connection = sqlite3.connect(db_path)
  try:
    keyword_hits = _keyword_search_project_knowledge(connection, normalized, _knowledge_candidate_limit(search_limit))
    semantic_hits = _semantic_search_project_knowledge(
      settings,
      connection,
      normalized,
      search_limit,
      candidate_chunk_ids=[str(item["chunk_id"]) for item in keyword_hits] if keyword_hits else None,
    )
  finally:
    connection.close()

  merged: dict[str, dict[str, object]] = {}
  for item in semantic_hits:
    merged[str(item["chunk_id"])] = dict(item)
  for item in keyword_hits:
    chunk_id = str(item["chunk_id"])
    if chunk_id in merged:
      merged_item = merged[chunk_id]
      merged_item["score"] = max(float(merged_item["score"]), float(item["score"]))
      merged_item["match_type"] = "hybrid"
      continue
    merged[chunk_id] = dict(item)

  ranked = sorted(
    merged.values(),
    key=lambda item: (
      1 if item["match_type"] in {"hybrid", "semantic"} else 0,
      float(item["score"]),
    ),
    reverse=True,
  )
  return [
    KnowledgeSearchResult(
      source=str(item["source"]),
      section=str(item["section"]),
      preview=_compact_text(str(item["content"]), limit=180),
      score=float(item["score"]),
      match_type=str(item["match_type"]),
    )
    for item in ranked[:search_limit]
  ]


def _search_project_knowledge_evidence(
  settings: Settings,
  project_dir: Path,
  query: str,
  *,
  limit: int = 8,
  candidate_limit: int = 24,
) -> list[dict[str, object]]:
  normalized = query.strip()
  if not normalized:
    return []

  db_path = _knowledge_db_path(project_dir)
  if not db_path.exists():
    return []

  search_limit = max(1, min(limit, 20))
  rerank_candidate_limit = max(search_limit, candidate_limit)
  connection = sqlite3.connect(db_path)
  try:
    keyword_hits = _keyword_search_project_knowledge(
      connection,
      normalized,
      _knowledge_candidate_limit(rerank_candidate_limit),
    )
    semantic_hits = _semantic_search_project_knowledge(
      settings,
      connection,
      normalized,
      rerank_candidate_limit,
      candidate_chunk_ids=[str(item["chunk_id"]) for item in keyword_hits] if keyword_hits else None,
    )
  finally:
    connection.close()

  merged: dict[str, dict[str, object]] = {}
  for item in semantic_hits:
    merged[str(item["chunk_id"])] = dict(item)
  for item in keyword_hits:
    chunk_id = str(item["chunk_id"])
    if chunk_id in merged:
      merged_item = merged[chunk_id]
      merged_item["score"] = max(float(merged_item["score"]), float(item["score"]))
      merged_item["match_type"] = "hybrid"
      continue
    merged[chunk_id] = dict(item)

  ranked = sorted(
    merged.values(),
    key=lambda item: (
      1 if item["match_type"] in {"hybrid", "semantic"} else 0,
      float(item["score"]),
    ),
    reverse=True,
  )[:rerank_candidate_limit]

  reranked = rerank_documents(
    settings,
    query=normalized,
    documents=[str(item["content"]) for item in ranked],
    top_n=search_limit,
    task_name="project_knowledge_rerank",
  )
  if reranked:
    return [
      {
        **ranked[item["index"]],
        "score": float(item["score"]),
        "match_type": "rerank",
      }
      for item in reranked
      if isinstance(item.get("index"), int) and 0 <= int(item["index"]) < len(ranked)
    ]

  return ranked[:search_limit]


def _is_character_candidate(name: str) -> bool:
  cleaned = name.strip().strip("：:，,。；;、·-—()（）[]【】")
  if cleaned in _ROLE_CHARACTER_TOKENS:
    return True
  if len(cleaned) < 2 or len(cleaned) > 8:
    return False
  if cleaned in _CHARACTER_NAME_BLACKLIST:
    return False
  if cleaned.startswith("第") and "章" in cleaned:
    return False
  if any(keyword in cleaned for keyword in ("关系", "状态", "场景", "事件", "地点", "组织", "道具")):
    return False
  return bool(re.fullmatch(r"[\u4e00-\u9fff·]+", cleaned))


def _json_character_name(payload: dict) -> str:
  for key in _JSON_CHARACTER_NAME_KEYS:
    value = payload.get(key)
    if isinstance(value, str) and _is_character_candidate(value):
      return value.strip()
  return ""


def _json_value_to_text(value: object) -> str:
  if value is None:
    return ""
  if isinstance(value, str):
    return value.strip()
  if isinstance(value, (int, float, bool)):
    return str(value)
  if isinstance(value, list):
    return "；".join(item for item in (_json_value_to_text(item) for item in value) if item)
  if isinstance(value, dict):
    parts = []
    for key, item in value.items():
      text = _json_value_to_text(item)
      if text:
        parts.append(f"{key}：{text}")
    return "；".join(parts)
  return str(value).strip()


def _json_character_lines(payload: object) -> list[str]:
  if isinstance(payload, dict):
    lines = []
    for key, value in payload.items():
      if key in _JSON_CHARACTER_NAME_KEYS:
        continue
      text = _json_value_to_text(value)
      if text:
        lines.append(f"{key}：{text}")
    return lines
  text = _json_value_to_text(payload)
  return [text] if text else []


def _collect_json_character_sections(container: object) -> dict[str, list[str]]:
  sections: dict[str, list[str]] = defaultdict(list)

  if isinstance(container, list):
    for item in container:
      if not isinstance(item, dict):
        continue
      name = _json_character_name(item)
      if name:
        sections[name].extend(_json_character_lines(item))
    return sections

  if isinstance(container, dict):
    for key, value in container.items():
      if isinstance(key, str) and _is_character_candidate(key) and isinstance(value, dict):
        sections[key.strip()].extend(_json_character_lines(value))
        continue
      if isinstance(value, dict):
        name = _json_character_name(value)
        if name:
          sections[name].extend(_json_character_lines(value))
    return sections

  return sections


def _extract_json_character_sections(text: str) -> dict[str, list[str]]:
  try:
    payload = json.loads(text)
  except (TypeError, json.JSONDecodeError):
    return {}

  sections: dict[str, list[str]] = defaultdict(list)
  if isinstance(payload, list):
    for name, lines in _collect_json_character_sections(payload).items():
      sections[name].extend(lines)
  elif isinstance(payload, dict):
    for key, value in payload.items():
      if key in _JSON_CHARACTER_CONTAINER_KEYS:
        for name, lines in _collect_json_character_sections(value).items():
          sections[name].extend(lines)
    name = _json_character_name(payload)
    if name:
      sections[name].extend(_json_character_lines(payload))

  return {name: lines for name, lines in sections.items() if lines}


def _character_heading_candidate(line: str) -> str | None:
  normalized = re.sub(r"^[#*\-\d\.\s、）\)]+", "", line).strip()
  if not normalized:
    return None

  if ":" in normalized or "：" in normalized:
    left, right = re.split(r"[:：]", normalized, maxsplit=1)
    candidate = left.strip()
    if _is_character_candidate(candidate) and right.strip():
      return candidate

  if line.lstrip().startswith("#") and _is_character_candidate(normalized):
    return normalized

  if normalized in _ROLE_CHARACTER_TOKENS:
    return normalized

  return None


def _extract_character_sections(text: str) -> dict[str, list[str]]:
  sections: dict[str, list[str]] = defaultdict(list)
  current_character = ""

  for name, lines in _extract_json_character_sections(text).items():
    sections[name].extend(lines)

  for raw_line in text.splitlines():
    line = raw_line.strip()
    if not line:
      continue

    candidate = _character_heading_candidate(line)
    if candidate is not None:
      current_character = candidate

    if current_character:
      sections[current_character].append(line)

  return {name: lines for name, lines in sections.items() if len(lines) > 0}


def _has_named_character(known_characters: list[str]) -> bool:
  return any(name and name not in _ROLE_CHARACTER_TOKENS for name in known_characters)


def _extract_character_mentions(
  text: str,
  known_characters: list[str],
  *,
  include_role_names: bool | None = None,
) -> list[str]:
  mentions: list[str] = []
  source = text or ""

  for name in known_characters:
    if name and name in source:
      mentions.append(name)

  should_include_role_names = include_role_names
  if should_include_role_names is None:
    should_include_role_names = not _has_named_character(known_characters)

  if should_include_role_names:
    for role_name in _ROLE_CHARACTER_TOKENS:
      if role_name in source:
        mentions.append(role_name)

  return _ordered_unique(mentions)


def _normalize_discovered_character_name(name: str) -> str:
  cleaned = name.strip().strip("，,。！？!?；;：:、·“”‘’\"'（）()[]【】《》")
  if len(cleaned) < 2 or len(cleaned) > 4:
    return ""
  if not re.fullmatch(r"[\u4e00-\u9fff]+", cleaned):
    return ""
  if cleaned in _CHARACTER_NAME_BLACKLIST or cleaned in _DISCOVERED_CHARACTER_BLACKLIST:
    return ""
  if any(char in _NON_CHARACTER_NAME_CHARS for char in cleaned):
    return ""
  if any(fragment in cleaned for fragment in _NON_CHARACTER_NAME_FRAGMENTS):
    return ""
  if any(keyword in cleaned for keyword in ("关系", "状态", "场景", "事件", "地点", "组织", "设定")):
    return ""
  if any(cleaned.endswith(suffix) for suffix in _DISCOVERED_CHARACTER_SUFFIX_BLACKLIST):
    return ""
  return cleaned


def _candidate_character_names(text: str) -> list[str]:
  candidates: list[str] = []
  source = text or ""
  for pattern in (_COMPOUND_SURNAME_PATTERN, _SINGLE_SURNAME_PATTERN):
    for match in pattern.finditer(source):
      candidate = _normalize_discovered_character_name(match.group(1))
      if candidate:
        candidates.append(candidate)
  return candidates


def _discover_character_names(texts: list[str], limit: int = 24) -> list[str]:
  counts: dict[str, int] = {}
  first_seen: dict[str, tuple[int, int]] = {}

  for text_index, text in enumerate(texts):
    for match_index, candidate in enumerate(_candidate_character_names(text)):
      counts[candidate] = counts.get(candidate, 0) + 1
      first_seen.setdefault(candidate, (text_index, match_index))

  filtered = [
    name
    for name, count in counts.items()
    if count >= (2 if len(name) >= 3 else 3)
  ]
  filtered.sort(
    key=lambda name: (
      -counts[name],
      -len(name),
      first_seen[name][0],
      first_seen[name][1],
      name,
    )
  )
  return filtered[:limit]


def _split_sentences(text: str) -> list[str]:
  pieces = re.split(r"(?<=[。！？!?；;])|\n+", text)
  return [piece.strip() for piece in pieces if piece.strip()]


def _material_analysis_text(text: str, limit: int = 12000) -> str:
  normalized = str(text or "").strip()
  if len(normalized) <= limit:
    return normalized

  head_limit = max(2000, limit // 3)
  tail_limit = max(4000, limit - head_limit - 20)
  head = normalized[:head_limit].strip()
  tail = normalized[-tail_limit:].strip()
  return f"{head}\n\n[中间内容已省略]\n\n{tail}".strip()


def _material_tail_anchor(text: str, limit: int = 120) -> str:
  sentences = [item for item in _split_sentences(text) if not _is_meta_sentence(item)]
  if not sentences:
    return _compact_text(text, limit=limit)
  return _compact_text(sentences[-1], limit=limit)


def _character_anchor_from_text(text: str, character_name: str, limit: int = 140) -> str:
  for sentence in _split_sentences(text):
    if character_name in sentence and not _is_meta_sentence(sentence):
      return _compact_text(sentence, limit=limit)
  return ""


def _extract_chapter_body(chapter: ChapterSummary) -> str:
  lines = chapter.content.splitlines()
  if lines and lines[0].strip().startswith("#"):
    return "\n".join(lines[1:]).strip()
  return chapter.content.strip()


def _is_meta_sentence(sentence: str) -> bool:
  compact = sentence.strip()
  if not compact:
    return True
  return any(keyword in compact for keyword in ("初稿", "正文", "版本", "草稿"))


def _normalize_entity_name(name: str, keywords: tuple[str, ...]) -> str:
  current = name.strip().strip("，,。！？!?；;：:、·“”‘’\"'（）()[]【】《》")
  if not current:
    return ""

  changed = True
  while changed:
    changed = False
    for token in _ENTITY_CONTEXT_TOKENS:
      if token not in current:
        continue

      candidate = current.rsplit(token, maxsplit=1)[-1].strip()
      if candidate and candidate != current and any(keyword in candidate for keyword in keywords):
        current = candidate
        changed = True
        break

  return current


def _expand_entity_keywords(
  source_text: str,
  matches: list[str],
  keywords: tuple[str, ...],
) -> list[str]:
  expanded_matches = list(matches)
  for keyword in keywords:
    if keyword not in source_text:
      continue
    if any(item.endswith(keyword) and len(item) > len(keyword) for item in expanded_matches):
      continue
    expanded_matches.append(keyword)

  return expanded_matches


def _extract_locations(text: str) -> list[str]:
  matches = [
    _normalize_entity_name(item, _LOCATION_KEYWORDS)
    for item in _LOCATION_PATTERN.findall(text)
  ]
  matches = _expand_entity_keywords(text, matches, _LOCATION_KEYWORDS)
  return _ordered_unique(matches)


def _extract_organizations(text: str) -> list[str]:
  matches = [
    _normalize_entity_name(item, _ORGANIZATION_KEYWORDS)
    for item in _ORGANIZATION_PATTERN.findall(text)
  ]
  matches = _expand_entity_keywords(text, matches, _ORGANIZATION_KEYWORDS)
  return _ordered_unique(matches)


def _extract_props(text: str) -> list[str]:
  return _ordered_unique([keyword for keyword in _PROP_KEYWORDS if keyword in text])


def _normalize_skill_name(name: str) -> str:
  current = name.strip().strip("，,。！？!?；;：:、·“”‘’\"'（）()[]【】《》")
  current = re.sub(r"^(?:技能|能力|特长|绝活|本领|擅长|善于|精通|熟悉|掌握|精于|最会|很会)", "", current)
  current = re.sub(r"(?:能力|本事|技巧|的人|方面)$", "", current)
  current = current.strip("，,。！？!?；;：:、·“”‘’\"'（）()[]【】《》")
  if not current or current in _SKILL_BLACKLIST:
    return ""
  if len(current) < 2 or len(current) > 12:
    return ""
  return current


def _extract_skills(text: str) -> list[str]:
  source = text or ""
  matches: list[str] = []

  for value in _SKILL_NOUN_PATTERN.findall(source):
    normalized = _normalize_skill_name(value)
    if normalized:
      matches.append(normalized)

  for pattern in _SKILL_VERB_PATTERNS:
    for value in pattern.findall(source):
      normalized = _normalize_skill_name(value)
      if normalized:
        matches.append(normalized)

  for block in _SKILL_LABEL_PATTERN.findall(source):
    for item in _SKILL_SPLIT_PATTERN.split(block):
      normalized = _normalize_skill_name(item)
      if normalized:
        matches.append(normalized)

  matches.extend(keyword for keyword in _SKILL_HINT_KEYWORDS if keyword in source)
  return _ordered_unique(matches)


def _extract_relationship_summaries(text: str, character_names: list[str]) -> dict[str, list[str]]:
  relation_map: dict[str, list[str]] = defaultdict(list)
  if len(character_names) < 2:
    return relation_map

  for sentence in _split_sentences(text):
    present_characters = [name for name in character_names if name in sentence]
    if len(present_characters) < 2:
      continue

    summary = _compact_text(sentence, limit=84)
    for name in present_characters:
      others = [other for other in present_characters if other != name]
      relation_map[name].append(f"{' / '.join(others)}：{summary}")

  return {name: _ordered_unique(items) for name, items in relation_map.items()}


def _register_entity(
  entity_map: dict[str, dict[str, set[str] | str | set[int]]],
  name: str,
  *,
  summary: str = "",
  related_characters: list[str] | None = None,
  chapter_index: int | None = None,
) -> None:
  cleaned_name = name.strip()
  if not cleaned_name:
    return

  payload = entity_map.setdefault(
    cleaned_name,
    {
      "summary": "",
      "related_characters": set(),
      "chapter_indexes": set(),
    },
  )
  if summary and not payload["summary"]:
    payload["summary"] = summary
  if related_characters:
    payload["related_characters"].update(item for item in related_characters if item)
  if chapter_index is not None:
    payload["chapter_indexes"].add(chapter_index)


def _build_story_overview(project_dir: Path, chapters: list[ChapterSummary]) -> StoryOverview:
  documents = _build_story_documents(project_dir)
  material_payloads = _load_knowledge_material_payloads(project_dir)
  document_map = {item.key: item for item in documents}
  character_design_sections = _extract_character_sections(document_map["character_design"].content)
  character_state_sections = _extract_character_sections(document_map["character_state"].content)
  discovered_characters = _discover_character_names(
    [
      *(item.content for item in documents if item.content.strip()),
      *(item["content"] for item in material_payloads if item.get("content")),
      *(item.content for item in chapters if item.exists and item.content.strip()),
    ]
  )

  known_characters = _ordered_unique(
    list(character_design_sections.keys()) + list(character_state_sections.keys()) + discovered_characters
  )

  for document in documents:
    known_characters = _ordered_unique(
      known_characters + _extract_character_mentions(document.content, known_characters)
    )

  for material in material_payloads:
    known_characters = _ordered_unique(
      known_characters + _extract_character_mentions(material.get("content", ""), known_characters)
    )

  for chapter in chapters:
    if not chapter.exists or not chapter.content.strip():
      continue
    known_characters = _ordered_unique(
      known_characters + _extract_character_mentions(chapter.content, known_characters)
    )

  if len(known_characters) == 0 and any(chapter.exists and chapter.content.strip() for chapter in chapters):
    known_characters = ["主角"]

  character_store: dict[str, dict] = {
    name: {
      "profile": "",
      "current_state": "",
      "relationships": [],
      "events": [],
      "locations": [],
      "props": [],
      "skills": [],
      "scenes": [],
      "organizations": [],
      "timeline": [],
    }
    for name in known_characters
  }
  entity_store = {
    "events": {},
    "locations": {},
    "props": {},
    "skills": {},
    "scenes": {},
    "organizations": {},
  }

  for name, lines in character_design_sections.items():
    summary = _compact_text("\n".join(lines), limit=220)
    skills = _extract_skills("\n".join(lines))
    character_store.setdefault(
      name,
      {
        "profile": "",
        "current_state": "",
        "relationships": [],
        "events": [],
        "locations": [],
        "props": [],
        "skills": [],
        "scenes": [],
        "organizations": [],
        "timeline": [],
      },
    )
    character_store[name]["profile"] = summary
    character_store[name]["skills"] = _ordered_unique(character_store[name]["skills"] + skills)
    for item in skills:
      _register_entity(entity_store["skills"], item, summary=summary, related_characters=[name])
    character_store[name]["timeline"].append(
      CharacterTimelineEntry(
        id=f"{name}-design",
        source_label="人物设定",
        summary=summary,
        skills=skills,
      )
    )

  for name, lines in character_state_sections.items():
    summary = _compact_text("\n".join(lines), limit=220)
    skills = _extract_skills("\n".join(lines))
    character_store.setdefault(
      name,
      {
        "profile": "",
        "current_state": "",
        "relationships": [],
        "events": [],
        "locations": [],
        "props": [],
        "skills": [],
        "scenes": [],
        "organizations": [],
        "timeline": [],
      },
    )
    character_store[name]["current_state"] = summary
    character_store[name]["skills"] = _ordered_unique(character_store[name]["skills"] + skills)
    for item in skills:
      _register_entity(entity_store["skills"], item, summary=summary, related_characters=[name])
    character_store[name]["timeline"].append(
      CharacterTimelineEntry(
        id=f"{name}-state",
        source_label="人物状态",
        summary=summary,
        skills=skills,
      )
    )

  for document in documents:
    if not document.content:
      continue

    mentioned_characters = _extract_character_mentions(document.content, known_characters)
    locations = _extract_locations(document.content)
    organizations = _extract_organizations(document.content)
    props = _extract_props(document.content)
    skills = _extract_skills(document.content)
    summary = _compact_text(document.content, limit=120)

    for item in locations:
      _register_entity(entity_store["locations"], item, summary=summary, related_characters=mentioned_characters)
    for item in organizations:
      _register_entity(entity_store["organizations"], item, summary=summary, related_characters=mentioned_characters)
    for item in props:
      _register_entity(entity_store["props"], item, summary=summary, related_characters=mentioned_characters)
    for item in skills:
      _register_entity(entity_store["skills"], item, summary=summary, related_characters=mentioned_characters)

  for material in material_payloads:
    title = material.get("title", "").strip()
    raw_content = material.get("content", "").strip()
    if not title or not raw_content:
      continue

    analysis_text = _material_analysis_text(raw_content)
    mentioned_characters = _extract_character_mentions(raw_content, known_characters)
    material_locations = _extract_locations(f"{title}\n{analysis_text}")
    material_organizations = _extract_organizations(f"{title}\n{analysis_text}")
    material_props = _extract_props(f"{title}\n{analysis_text}")
    material_skills = _extract_skills(f"{title}\n{analysis_text}")
    material_summary = _material_tail_anchor(raw_content)
    if not material_summary:
      material_summary = _compact_text(analysis_text, limit=120)
    material_events = _ordered_unique(
      [
        title,
        material_summary if material_summary != title else "",
      ]
    )
    material_relations = _extract_relationship_summaries(analysis_text, mentioned_characters)

    _register_entity(
      entity_store["scenes"],
      title,
      summary=_compact_text(material_summary or analysis_text, limit=120),
      related_characters=mentioned_characters,
    )

    for event_name in material_events:
      _register_entity(
        entity_store["events"],
        event_name,
        summary=material_summary,
        related_characters=mentioned_characters,
      )

    for item in material_locations:
      _register_entity(
        entity_store["locations"],
        item,
        summary=material_summary,
        related_characters=mentioned_characters,
      )
    for item in material_organizations:
      _register_entity(
        entity_store["organizations"],
        item,
        summary=material_summary,
        related_characters=mentioned_characters,
      )
    for item in material_props:
      _register_entity(
        entity_store["props"],
        item,
        summary=material_summary,
        related_characters=mentioned_characters,
      )
    for item in material_skills:
      _register_entity(
        entity_store["skills"],
        item,
        summary=material_summary,
        related_characters=mentioned_characters,
      )

    for character_name in mentioned_characters:
      if character_name not in character_store:
        character_store[character_name] = {
          "profile": "",
          "current_state": "",
          "relationships": [],
          "events": [],
          "locations": [],
          "props": [],
          "skills": [],
          "scenes": [],
          "organizations": [],
          "timeline": [],
        }

      store = character_store[character_name]
      character_anchor = _character_anchor_from_text(analysis_text, character_name, limit=160)
      if character_anchor and not store["profile"]:
        store["profile"] = character_anchor
      store["events"] = _ordered_unique(store["events"] + material_events)
      store["locations"] = _ordered_unique(store["locations"] + material_locations)
      store["props"] = _ordered_unique(store["props"] + material_props)
      store["skills"] = _ordered_unique(store["skills"] + material_skills)
      store["scenes"] = _ordered_unique(store["scenes"] + [title])
      store["organizations"] = _ordered_unique(store["organizations"] + material_organizations)
      store["relationships"] = _ordered_unique(
        store["relationships"] + material_relations.get(character_name, [])
      )
      if character_anchor and character_name not in character_state_sections and not store["current_state"]:
        store["current_state"] = _compact_text(character_anchor, limit=120)

      store["timeline"].append(
        CharacterTimelineEntry(
          id=f"{character_name}-material-{hashlib.sha1(title.encode('utf-8')).hexdigest()[:8]}",
          source_label=f"参考资料：{title}",
          summary=character_anchor or material_summary,
          relations=material_relations.get(character_name, []),
          events=material_events,
          locations=material_locations,
          props=material_props,
          skills=material_skills,
          scenes=[title],
          organizations=material_organizations,
        )
      )

  for chapter in chapters:
    if not chapter.exists or not chapter.content.strip():
      continue

    chapter_body = _extract_chapter_body(chapter)
    chapter_text = chapter_body or chapter.preview or chapter.title
    chapter_characters = _extract_character_mentions(chapter_text, known_characters)
    if len(chapter_characters) == 0 and len(known_characters) == 1:
      chapter_characters = [known_characters[0]]
    elif len(chapter_characters) == 0 and len(known_characters) == 0:
      chapter_characters = ["主角"]
    chapter_sentences = [
      sentence
      for sentence in _split_sentences(chapter_text)
      if not _is_meta_sentence(sentence)
    ]
    chapter_summary = _compact_text(
      chapter_sentences[0] if chapter_sentences else chapter.title,
      limit=90,
    )
    chapter_locations = _extract_locations(f"{chapter.title}\n{chapter_text}")
    chapter_organizations = _extract_organizations(f"{chapter.title}\n{chapter_text}")
    chapter_props = _extract_props(f"{chapter.title}\n{chapter_text}")
    chapter_skills = _extract_skills(f"{chapter.title}\n{chapter_text}")
    chapter_events = _ordered_unique(
      [
        chapter.title,
        chapter_summary if chapter_summary != chapter.title else "",
      ]
    )
    chapter_relations = _extract_relationship_summaries(chapter_text, chapter_characters)

    _register_entity(
      entity_store["scenes"],
      chapter.title,
      summary=_compact_text(chapter_summary or chapter.preview or chapter_text, limit=120),
      related_characters=chapter_characters,
      chapter_index=chapter.index,
    )

    for event_name in chapter_events:
      _register_entity(
        entity_store["events"],
        event_name,
        summary=chapter_summary,
        related_characters=chapter_characters,
        chapter_index=chapter.index,
      )

    for item in chapter_locations:
      _register_entity(
        entity_store["locations"],
        item,
        summary=chapter_summary,
        related_characters=chapter_characters,
        chapter_index=chapter.index,
      )

    for item in chapter_organizations:
      _register_entity(
        entity_store["organizations"],
        item,
        summary=chapter_summary,
        related_characters=chapter_characters,
        chapter_index=chapter.index,
      )

    for item in chapter_props:
      _register_entity(
        entity_store["props"],
        item,
        summary=chapter_summary,
        related_characters=chapter_characters,
        chapter_index=chapter.index,
      )
    for item in chapter_skills:
      _register_entity(
        entity_store["skills"],
        item,
        summary=chapter_summary,
        related_characters=chapter_characters,
        chapter_index=chapter.index,
      )

    for character_name in chapter_characters:
      if character_name not in character_store:
        character_store[character_name] = {
          "profile": "",
          "current_state": "",
          "relationships": [],
          "events": [],
          "locations": [],
          "props": [],
          "skills": [],
          "scenes": [],
          "organizations": [],
          "timeline": [],
        }

      store = character_store[character_name]
      store["events"] = _ordered_unique(store["events"] + chapter_events)
      store["locations"] = _ordered_unique(store["locations"] + chapter_locations)
      store["props"] = _ordered_unique(store["props"] + chapter_props)
      store["skills"] = _ordered_unique(store["skills"] + chapter_skills)
      store["scenes"] = _ordered_unique(store["scenes"] + [chapter.title])
      store["organizations"] = _ordered_unique(store["organizations"] + chapter_organizations)
      store["relationships"] = _ordered_unique(
        store["relationships"] + chapter_relations.get(character_name, [])
      )
      if character_name not in character_state_sections:
        store["current_state"] = _compact_text(chapter_summary, limit=120)

      store["timeline"].append(
        CharacterTimelineEntry(
          id=f"{character_name}-chapter-{chapter.index:03d}",
          chapter_id=chapter.id,
          chapter_index=chapter.index,
          chapter_title=chapter.title,
          source_label="章节正文",
          summary=chapter_summary,
          relations=chapter_relations.get(character_name, []),
          events=chapter_events,
          locations=chapter_locations,
          props=chapter_props,
          skills=chapter_skills,
          scenes=[chapter.title],
          organizations=chapter_organizations,
        )
      )

  ordered_characters = _ordered_unique(list(character_store.keys()))
  character_items = [
    StoryCharacter(
      name=name,
      profile=character_store[name]["profile"],
      current_state=character_store[name]["current_state"],
      relationships=character_store[name]["relationships"],
      events=character_store[name]["events"],
      locations=character_store[name]["locations"],
      props=character_store[name]["props"],
      skills=character_store[name]["skills"],
      scenes=character_store[name]["scenes"],
      organizations=character_store[name]["organizations"],
      timeline=sorted(
        character_store[name]["timeline"],
        key=lambda item: (item.chapter_index or 0, item.source_label),
      ),
    )
    for name in ordered_characters
  ]

  def build_entities(kind: str) -> list[StoryEntityReference]:
    payload = entity_store[kind]
    return [
      StoryEntityReference(
        name=name,
        summary=str(item["summary"]),
        related_characters=_ordered_unique(list(item["related_characters"])),
        chapter_indexes=sorted(int(value) for value in item["chapter_indexes"]),
      )
      for name, item in sorted(
        payload.items(),
        key=lambda entity: (
          -(len(entity[1]["chapter_indexes"]) + len(entity[1]["related_characters"])),
          entity[0],
        ),
      )
    ]

  return StoryOverview(
    documents=documents,
    materials=_build_knowledge_materials(project_dir),
    memory_entries=load_project_memory(project_dir),
    characters=character_items,
    events=build_entities("events"),
    locations=build_entities("locations"),
    props=build_entities("props"),
    skills=build_entities("skills"),
    scenes=build_entities("scenes"),
    organizations=build_entities("organizations"),
  )


def list_projects(settings: Settings) -> list[ProjectSummary]:
  payload = read_json(project_index_path(settings), [])
  projects = [ProjectSummary.model_validate(item) for item in payload]
  return sorted(projects, key=lambda item: item.updated_at, reverse=True)


def get_project_detail(settings: Settings, project_id: str) -> ProjectDetail:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  chapters = [
    _build_chapter_summary(project_dir, index)
    for index in range(1, summary.target_chapters + 1)
  ]
  local_history = _local_history_state(project_dir)
  overview = _build_story_overview(project_dir, chapters)
  auto_entries, memory_signature = build_auto_project_memory(
    documents=overview.documents,
    characters=overview.characters,
    events=overview.events,
    locations=overview.locations,
    props=overview.props,
    scenes=overview.scenes,
    organizations=overview.organizations,
    chapters=chapters,
  )
  overview = overview.model_copy(
    update={
      "memory_entries": sync_project_memory(
        project_dir,
        auto_entries,
        derived_signature=memory_signature,
      ),
      "dream_report": load_project_dream_report(
        project_dir,
        source_signature=build_project_dream_signature(
          documents=overview.documents,
          chapters=chapters,
        ),
      ),
    }
  )
  detail = ProjectDetail(
    **summary.model_dump(),
    chapters=chapters,
    local_history=local_history,
    story_overview=overview,
  )
  distillation_signature = build_project_distillation_signature(detail)
  distillation_report = load_project_distillation(
    project_dir,
    source_signature=distillation_signature,
  )
  if distillation_report is None or distillation_report.is_stale:
    distillation_report = generate_project_distillation(detail, source_signature=distillation_signature)
  overview = overview.model_copy(
    update={
      "chapter_reviews": load_chapter_reviews(project_dir, detail),
      "distillation_report": distillation_report,
    }
  )

  return ProjectDetail(
    **summary.model_dump(),
    chapters=chapters,
    local_history=local_history,
    story_overview=overview,
  )


def project_count(settings: Settings) -> int:
  return len(list_projects(settings))


def create_project(settings: Settings, request: CreateProjectRequest) -> ProjectSummary:
  now = _now_iso()
  base_dir = (
    Path(request.base_path).expanduser().resolve()
    if request.base_path
    else (settings.data_dir / "workspace").resolve()
  )
  base_dir.mkdir(parents=True, exist_ok=True)

  folder_name = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{_safe_folder_name(request.name)}"
  project_dir = base_dir / folder_name
  if project_dir.exists():
    raise HTTPException(
      status_code=409,
      detail={"code": "project_exists", "message": f"项目目录已存在：{project_dir}"},
    )

  chapters_dir = project_dir / "chapters"
  backups_dir = project_dir / "backups"
  chapters_dir.mkdir(parents=True, exist_ok=True)
  backups_dir.mkdir(parents=True, exist_ok=True)

  project_id = str(uuid4())
  project_meta = {
    "id": project_id,
    "name": request.name,
    "genre": request.genre,
    "target_chapters": request.target_chapters,
    "target_words": request.target_words,
    "created_at": now,
    "updated_at": now,
    "path": str(project_dir),
  }

  initial_files = {
    "project.json": project_meta,
    "core_seed.txt": "",
    "character_design.txt": "",
    "character_state.txt": "",
    "world_building.txt": "",
    "plot_structure.txt": "",
    "blueprint.txt": "",
    "global_summary.txt": "",
    "checkpoint.json": {
      "step": "idle",
      "chapter_index": 0,
      "status": "ready",
      "updated_at": now,
    },
  }

  for filename, payload in initial_files.items():
    file_path = project_dir / filename
    if isinstance(payload, dict):
      atomic_write_json(file_path, payload)
    else:
      atomic_write_text(file_path, payload)

  ensure_project_memory_file(project_dir)
  _initialize_knowledge_db(project_dir / "knowledge.db")
  _rebuild_project_knowledge(project_dir, request.target_chapters, settings)
  _write_snapshot(
    project_dir,
    kind="system",
    message="初始化项目",
    created_at=now,
    allow_empty=True,
  )

  summary = ProjectSummary(
    id=project_id,
    name=request.name,
    path=str(project_dir),
    genre=request.genre,
    target_chapters=request.target_chapters,
    target_words=request.target_words,
    updated_at=now,
  )

  projects = [item.model_dump(mode="json") for item in list_projects(settings)]
  projects.insert(0, summary.model_dump(mode="json"))
  atomic_write_json(project_index_path(settings), projects)
  return summary


def rename_project(
  settings: Settings,
  project_id: str,
  request: ProjectRenameRequest,
) -> ProjectSummary:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _assert_project_dir_is_valid(summary)
  next_name = request.name.strip()
  if not next_name:
    raise HTTPException(
      status_code=400,
      detail={"code": "project_name_empty", "message": "项目名称不能为空"},
    )

  next_dir = project_dir.parent / _renamed_project_dirname(project_dir.name, next_name)
  if next_dir != project_dir and next_dir.exists():
    raise HTTPException(
      status_code=409,
      detail={"code": "project_dir_exists", "message": f"目标目录已存在：{next_dir}"},
    )

  if next_dir != project_dir:
    project_dir.rename(next_dir)

  updated_at = _now_iso()
  renamed_summary = summary.model_copy(
    update={
      "name": next_name,
      "path": str(next_dir),
      "updated_at": updated_at,
    }
  )

  project_meta = read_json(_project_meta_path(next_dir), {})
  if isinstance(project_meta, dict):
    project_meta["name"] = renamed_summary.name
    project_meta["path"] = renamed_summary.path
    project_meta["updated_at"] = renamed_summary.updated_at
    atomic_write_json(_project_meta_path(next_dir), project_meta)

  _replace_project_summary(settings, renamed_summary)
  append_app_log(settings, f"project renamed: {summary.name} -> {renamed_summary.name}")
  return renamed_summary


def delete_project(settings: Settings, project_id: str) -> ProjectDeleteResult:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  removed_from_disk = False

  if project_dir.exists():
    _assert_project_dir_is_valid(summary)
    shutil.rmtree(project_dir)
    removed_from_disk = True

  project_items = [ProjectSummary.model_validate(item) for item in read_json(project_index_path(settings), [])]
  next_projects = [item for item in project_items if item.id != project_id]
  _write_project_index(settings, next_projects)

  append_app_log(settings, f"project deleted: {summary.name}")
  return ProjectDeleteResult(
    id=summary.id,
    name=summary.name,
    path=summary.path,
    removed_from_disk=removed_from_disk,
  )


def open_project_directory(settings: Settings, project_id: str) -> ProjectDirectoryOpenResult:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _assert_project_dir_is_valid(summary)

  try:
    if sys.platform == "darwin":
      subprocess.run(["open", str(project_dir)], check=True)
    elif sys.platform.startswith("win"):
      startfile = getattr(os, "startfile", None)
      if startfile is None:
        raise FileNotFoundError("os.startfile unavailable")
      startfile(str(project_dir))
    else:
      subprocess.run(["xdg-open", str(project_dir)], check=True)
  except FileNotFoundError as error:
    raise HTTPException(
      status_code=503,
      detail={"code": "open_directory_unavailable", "message": "当前系统没有可用的文件管理器命令"},
    ) from error
  except (OSError, subprocess.CalledProcessError) as error:
    raise HTTPException(
      status_code=500,
      detail={"code": "open_directory_failed", "message": "打开项目目录失败"},
    ) from error

  append_app_log(settings, f"project directory opened: {project_dir}")
  return ProjectDirectoryOpenResult(
    project_id=summary.id,
    path=str(project_dir),
    opened=True,
  )


def create_project_snapshot(
  settings: Settings,
  project_id: str,
  request: SnapshotCreateRequest,
) -> ProjectDetail:
  summary = _project_summary_or_404(settings, project_id)
  updated_at = _now_iso()
  _write_snapshot(
    _project_dir(summary),
    kind="manual",
    message=_snapshot_message(request.message, "手动保存版本"),
  )
  _touch_project_timestamp(settings, project_id, updated_at)
  return get_project_detail(settings, project_id)


def auto_save_project_snapshot(settings: Settings, project_id: str) -> ProjectDetail:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  history_state = _local_history_state(project_dir)

  if history_state.working_tree.clean:
    return get_project_detail(settings, project_id)

  updated_at = _now_iso()
  _write_snapshot(
    project_dir,
    kind="auto",
    message=_auto_snapshot_message(history_state.working_tree.changed_files),
  )
  _touch_project_timestamp(settings, project_id, updated_at)
  return get_project_detail(settings, project_id)


def get_project_snapshot_detail(
  settings: Settings,
  project_id: str,
  snapshot_id: str,
) -> ProjectSnapshotDetail:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  history_state = _local_history_state(project_dir)
  snapshot = next((item for item in history_state.snapshots if item.id == snapshot_id), None)
  if snapshot is None:
    raise HTTPException(
      status_code=404,
      detail={"code": "snapshot_not_found", "message": "本地快照不存在"},
    )

  file_sources, snapshot_manifest = _snapshot_sources_until(project_dir, snapshot_id)
  changed_files = [
    LocalHistoryChangedFile(path=str(item["path"]), status=str(item["status"]))
    for item in snapshot_manifest.get("changes", [])
  ]

  return ProjectSnapshotDetail(
    **snapshot.model_dump(),
    changed_files=changed_files,
    preview_chapters=_snapshot_preview_chapters(
      project_dir,
      snapshot_id,
      snapshot_manifest,
      file_sources,
    ),
  )


def restore_project_snapshot(
  settings: Settings,
  project_id: str,
  snapshot_id: str,
  request: SnapshotRestoreRequest | None = None,
) -> ProjectDetail:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  history_state = _local_history_state(project_dir)
  restore_chapter_id = request.chapter_id if request is not None else None

  if (
    restore_chapter_id is None
    and history_state.working_tree.clean
    and history_state.working_tree.base_snapshot_id == snapshot_id
  ):
    return get_project_detail(settings, project_id)

  snapshot_detail = get_project_snapshot_detail(settings, project_id, snapshot_id)

  if not history_state.working_tree.clean:
    _write_snapshot(
      project_dir,
      kind="auto",
      message=f"恢复前自动快照 · {_snapshot_message(history_state.working_tree.base_snapshot_message, '未命名工作区')}",
    )

  if restore_chapter_id:
    _restore_snapshot_chapter(project_dir, snapshot_id, restore_chapter_id)
  else:
    _restore_snapshot_files(project_dir, snapshot_id)

  updated_at = _now_iso()
  _touch_project_timestamp(settings, project_id, updated_at)
  restored_chapter_title = next(
    (
      chapter.title
      for chapter in snapshot_detail.preview_chapters
      if chapter.id == restore_chapter_id
    ),
    restore_chapter_id or "",
  )
  restore_message = (
    f"恢复章节 · {_snapshot_message(snapshot_detail.message, '指定快照')} · {restored_chapter_title}"
    if restore_chapter_id
    else f"恢复到 · {_snapshot_message(snapshot_detail.message, '指定快照')}"
  )
  _write_snapshot(
    project_dir,
    kind="restore",
    message=restore_message,
  )
  _rebuild_project_knowledge(project_dir, summary.target_chapters, settings)
  return get_project_detail(settings, project_id)


def export_project_book(
  settings: Settings,
  project_id: str,
  request: ProjectExportRequest,
) -> ProjectExportResult:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  export_format = request.format.strip().lower()
  if export_format not in {"markdown", "text"}:
    raise HTTPException(
      status_code=400,
      detail={"code": "invalid_export_format", "message": "暂时只支持 markdown 或 text 导出"},
    )

  chapters = [
    _build_chapter_summary(project_dir, index)
    for index in range(1, summary.target_chapters + 1)
  ]
  written_chapters = [item for item in chapters if item.exists and item.content.strip()]
  if len(written_chapters) == 0:
    raise HTTPException(
      status_code=409,
      detail={"code": "no_written_chapters", "message": "当前作品还没有可导出的正文"},
    )

  exports_dir = project_dir / "exports"
  exports_dir.mkdir(parents=True, exist_ok=True)
  created_at = _now_iso()
  timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
  extension = "md" if export_format == "markdown" else "txt"
  output_path = exports_dir / f"{timestamp}_{_safe_folder_name(summary.name)}.{extension}"

  sections: list[str] = [f"# {summary.name}", ""]
  for chapter in written_chapters:
    content = chapter.content.strip()
    if export_format == "text":
      lines = content.splitlines()
      if lines and lines[0].strip().startswith("#"):
        content = "\n".join(lines[1:]).strip()
      section = f"第 {chapter.index} 章 {chapter.title}\n\n{content}".strip()
    else:
      section = content
    sections.append(section)
    sections.append("")

  export_text = "\n".join(sections).strip() + "\n"
  atomic_write_text(output_path, export_text)

  word_count = sum(len(chapter.content.strip()) for chapter in written_chapters)
  return ProjectExportResult(
    path=str(output_path),
    format=export_format,
    chapter_count=len(written_chapters),
    word_count=word_count,
    created_at=created_at,
  )


def import_project_knowledge(
  settings: Settings,
  project_id: str,
  request: KnowledgeImportRequest,
) -> ProjectDetail:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  references_dir = _references_dir(project_dir)
  references_dir.mkdir(parents=True, exist_ok=True)

  updated_at = _now_iso()
  changed_source_keys: list[str] = []
  for item in request.items:
    path = _knowledge_material_path(project_dir, item.title)
    atomic_write_json(
      path,
      {
        "title": item.title.strip(),
        "content": item.content.strip(),
        "updated_at": updated_at,
      },
    )
    changed_source_keys.append(_reference_source_key(path.name))

  _touch_project_timestamp(settings, project_id, updated_at)
  _refresh_project_knowledge_sources(settings, project_dir, summary.target_chapters, changed_source_keys)
  return _auto_refresh_system_memory(settings, project_id, focus="参考资料已导入")


def apply_architecture_workspace(
  settings: Settings,
  project_id: str,
  request: ArchitectureWorkspaceApplyRequest,
) -> ProjectDetail:
  summary = _project_summary_or_404(settings, project_id)
  workspace_payload = request.workspace.model_dump(mode="json")
  patches = [
    StoryDocumentPatch(key=key, content=str(value or ""))
    for key, value in workspace_payload.items()
    if any(spec_key == key for _filename, spec_key, _label in _STORY_DOCUMENT_SPECS)
  ]
  if patches:
    _update_story_documents(settings, summary, patches)
  next_genre = request.genre.strip() if isinstance(request.genre, str) and request.genre.strip() else None
  target_changed = (
    (request.target_chapters is not None and request.target_chapters != summary.target_chapters)
    or (request.target_words is not None and request.target_words != summary.target_words)
    or (next_genre is not None and next_genre != summary.genre)
  )
  if target_changed:
    update_project_targets(
      settings,
      project_id,
      target_chapters=request.target_chapters,
      target_words=request.target_words,
      genre=next_genre,
    )
    return _auto_refresh_system_memory(settings, project_id, focus="项目目标已更新")
  return get_project_detail(settings, project_id)


def update_story_document(
  settings: Settings,
  project_id: str,
  document_key: str,
  request: StoryDocumentUpdateRequest,
) -> ProjectDetail:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  return _update_story_documents(
    settings,
    summary,
    [StoryDocumentPatch(key=document_key, content=request.content)],
  )


def _auto_refresh_system_memory(
  settings: Settings,
  project_id: str,
  *,
  focus: str = "",
) -> ProjectDetail:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  detail = get_project_detail(settings, project_id)
  if detail.story_overview.distillation_report is not None:
    save_project_distillation(project_dir, detail.story_overview.distillation_report)
  report = generate_project_dream_report(settings, detail, focus=focus, use_model=False)
  save_project_dream_report(project_dir, report)
  candidate_ids = [item.id for item in report.memory_candidates]
  if candidate_ids:
    promote_dream_candidates(project_dir, candidate_ids, target_source="system")
    _touch_project_timestamp(settings, project_id, _now_iso())
  return get_project_detail(settings, project_id)


def _update_story_documents(
  settings: Settings,
  summary: ProjectSummary,
  documents: list[StoryDocumentPatch],
) -> ProjectDetail:
  project_dir = _project_dir(summary)

  for item in documents:
    filename, _key, _label = _story_document_spec_or_404(item.key)
    atomic_write_text(project_dir / filename, item.content)

  updated_at = _now_iso()
  _touch_project_timestamp(settings, summary.id, updated_at)
  _refresh_project_knowledge_sources(
    settings,
    project_dir,
    summary.target_chapters,
    [_story_document_source_key(item.key) for item in documents],
  )
  return _auto_refresh_system_memory(settings, summary.id, focus="设定文件已更新")


def update_story_documents(
  settings: Settings,
  project_id: str,
  request: StoryDocumentBatchUpdateRequest,
) -> ProjectDetail:
  summary = _project_summary_or_404(settings, project_id)
  return _update_story_documents(settings, summary, request.documents)


def update_project_memory(
  settings: Settings,
  project_id: str,
  request: ProjectMemoryUpdateRequest,
) -> ProjectDetail:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  save_project_memory(project_dir, request.entries)
  _touch_project_timestamp(settings, project_id, _now_iso())
  return _auto_refresh_system_memory(settings, project_id, focus="作者记忆已更新")


def get_project_agent_threads(
  settings: Settings,
  project_id: str,
) -> AgentThreadStore:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  _ensure_agent_threads_layout(project_dir)

  index_payload = read_json(_agent_threads_index_path(project_dir), {"active_thread_id": "", "threads": []})
  if not isinstance(index_payload, dict):
    index_payload = {"active_thread_id": "", "threads": []}

  records: list[AgentThreadRecord] = []
  raw_threads = index_payload.get("threads")
  if isinstance(raw_threads, list):
    for item in raw_threads:
      if not isinstance(item, dict):
        continue

      thread_id = item.get("id")
      if not isinstance(thread_id, str) or not thread_id.strip():
        continue

      try:
        normalized_thread_id = _normalize_thread_id_or_400(thread_id)
      except HTTPException:
        continue

      thread_payload = read_json(_agent_thread_path(project_dir, normalized_thread_id), None)
      if not isinstance(thread_payload, dict):
        continue

      merged_payload = {
        **thread_payload,
        "id": normalized_thread_id,
        "title": item.get("title", thread_payload.get("title", "")),
        "preview": item.get("preview", thread_payload.get("preview", "")),
        "updated_at": item.get("updated_at", thread_payload.get("updated_at", "")),
      }
      try:
        records.append(AgentThreadRecord.model_validate(merged_payload))
      except Exception:
        continue

  active_thread_id = str(index_payload.get("active_thread_id") or "")
  valid_thread_ids = {item.id for item in records}
  if active_thread_id not in valid_thread_ids:
    active_thread_id = records[0].id if records else ""

  return AgentThreadStore(
    active_thread_id=active_thread_id,
    threads=sorted(records, key=lambda item: item.updated_at, reverse=True),
  )


def save_project_agent_threads(
  settings: Settings,
  project_id: str,
  request: AgentThreadStoreUpdateRequest,
) -> AgentThreadStore:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  _ensure_agent_threads_layout(project_dir)

  normalized_records: list[AgentThreadRecord] = []
  kept_ids: set[str] = set()
  for item in request.threads:
    normalized_thread_id = _normalize_thread_id_or_400(item.id)
    normalized_record = item.model_copy(update={"id": normalized_thread_id})
    normalized_records.append(normalized_record)
    kept_ids.add(normalized_thread_id)
    atomic_write_json(
      _agent_thread_path(project_dir, normalized_thread_id),
      normalized_record.model_dump(mode="json"),
    )

  for path in _agent_threads_dir(project_dir).glob("*.json"):
    if path.name == "index.json":
      continue
    if path.stem not in kept_ids:
      path.unlink(missing_ok=True)

  active_thread_id = request.active_thread_id.strip()
  if active_thread_id and active_thread_id not in kept_ids:
    active_thread_id = ""
  if not active_thread_id and normalized_records:
    active_thread_id = normalized_records[0].id

  sorted_records = sorted(normalized_records, key=lambda item: item.updated_at, reverse=True)
  atomic_write_json(
    _agent_threads_index_path(project_dir),
    {
      "active_thread_id": active_thread_id,
      "threads": [
        {
          "id": item.id,
          "title": item.title,
          "preview": item.preview,
          "updated_at": item.updated_at,
        }
        for item in sorted_records
      ],
    },
  )

  return AgentThreadStore(active_thread_id=active_thread_id, threads=sorted_records)


def run_project_dream(
  settings: Settings,
  project_id: str,
  request: ProjectDreamRunRequest,
) -> ProjectDetail:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  detail = get_project_detail(settings, project_id)
  report = generate_project_dream_report(settings, detail, focus=request.focus)
  save_project_dream_report(project_dir, report)
  candidate_ids = [item.id for item in report.memory_candidates]
  if candidate_ids:
    promote_dream_candidates(project_dir, candidate_ids, target_source="system")
    _touch_project_timestamp(settings, project_id, _now_iso())
  return get_project_detail(settings, project_id)


def promote_project_dream(
  settings: Settings,
  project_id: str,
  request: ProjectDreamPromoteRequest,
) -> ProjectDetail:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  detail = get_project_detail(settings, project_id)
  report = detail.story_overview.dream_report
  if report is None:
    raise HTTPException(
      status_code=404,
      detail={"code": "dream_report_not_found", "message": "还没有做梦结果"},
    )
  if report.is_stale:
    raise HTTPException(
      status_code=409,
      detail={"code": "dream_report_stale", "message": "梦境结果已经过期，请重新做梦"},
    )

  promoted = promote_dream_candidates(project_dir, request.candidate_ids)
  if promoted <= 0:
    raise HTTPException(
      status_code=409,
      detail={"code": "dream_candidate_unavailable", "message": "候选不存在，或者已经写入项目记忆"},
    )

  _touch_project_timestamp(settings, project_id, _now_iso())
  return get_project_detail(settings, project_id)


def update_chapter_content(
  settings: Settings,
  project_id: str,
  chapter_id: str,
  request: ChapterUpdateRequest,
) -> ProjectDetail:
  detail, _review_error = update_chapter_content_with_review_status(settings, project_id, chapter_id, request)
  return detail


def _persist_chapter_review(
  settings: Settings,
  project_id: str,
  project_dir: Path,
  detail: ProjectDetail,
  chapter_id: str,
  *,
  style_name: str,
  failure_prefix: str,
) -> tuple[ProjectDetail, str]:
  try:
    review = build_chapter_review(
      settings,
      detail,
      chapter_id,
      style_name=style_name,
    )
    save_chapter_review(project_dir, review)
  except Exception as error:
    append_app_log(settings, f"chapter review failed for {project_id}/{chapter_id}: {error}")
    return get_project_detail(settings, project_id), f"{failure_prefix}：{error}"
  return get_project_detail(settings, project_id), ""


def update_chapter_content_with_review_status(
  settings: Settings,
  project_id: str,
  chapter_id: str,
  request: ChapterUpdateRequest,
) -> tuple[ProjectDetail, str]:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  chapter_index = _chapter_index_from_id(chapter_id)
  chapter_path = _chapter_file_path(project_dir, chapter_index)
  content = request.content

  if content.strip():
    atomic_write_text(chapter_path, content)
  else:
    delete_chapter_review(project_dir, chapter_id)
    if chapter_path.exists():
      chapter_path.unlink()

  updated_at = _now_iso()
  _touch_project_timestamp(settings, project_id, updated_at)
  _refresh_project_knowledge_sources(
    settings,
    project_dir,
    summary.target_chapters,
    [_chapter_source_key(chapter_index)],
  )
  detail = _auto_refresh_system_memory(settings, project_id, focus=f"第 {chapter_index} 章已更新")
  if not content.strip():
    return detail, ""
  return _persist_chapter_review(
    settings,
    project_id,
    project_dir,
    detail,
    chapter_id,
    style_name=request.style_name,
    failure_prefix="章节已保存，但核验失败",
  )


def refresh_chapter_review(
  settings: Settings,
  project_id: str,
  chapter_id: str,
  request: ChapterReviewRefreshRequest,
) -> tuple[ProjectDetail, str]:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  detail = get_project_detail(settings, project_id)
  return _persist_chapter_review(
    settings,
    project_id,
    project_dir,
    detail,
    chapter_id,
    style_name=request.style_name,
    failure_prefix="章节核验失败",
  )


def search_project_knowledge(
  settings: Settings,
  project_id: str,
  query: str,
  limit: int = 8,
) -> list[KnowledgeSearchResult]:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  _ensure_project_knowledge_current(settings, project_dir, summary.target_chapters)
  return _search_project_knowledge(settings, project_dir, query, limit)


def search_project_knowledge_evidence(
  settings: Settings,
  project_id: str,
  query: str,
  *,
  limit: int = 8,
  candidate_limit: int = 24,
) -> list[dict[str, object]]:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  _ensure_project_knowledge_current(settings, project_dir, summary.target_chapters)
  return _search_project_knowledge_evidence(
    settings,
    project_dir,
    query,
    limit=limit,
    candidate_limit=candidate_limit,
  )


def load_project_knowledge_material_contents(
  settings: Settings,
  project_id: str,
  limit: int = 12,
) -> list[dict[str, str]]:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  directory = _references_dir(project_dir)
  if not directory.exists():
    return []

  items: list[dict[str, str]] = []
  for path in sorted(directory.glob("*.json")):
    payload = read_json(path, None)
    if not isinstance(payload, dict):
      continue

    title = str(payload.get("title") or "").strip()
    content = str(payload.get("content") or "").strip()
    if not title or not content:
      continue

    updated_at = str(payload.get("updated_at") or "").strip()
    items.append(
      {
        "title": title,
        "filename": path.name,
        "content": content,
        "updated_at": updated_at,
      }
    )

  items.sort(
    key=lambda item: (
      item.get("updated_at") or "",
      item.get("title") or "",
    ),
    reverse=True,
  )
  return items[:max(1, min(limit, 20))]
