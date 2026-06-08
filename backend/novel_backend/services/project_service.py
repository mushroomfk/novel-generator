from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import os
import re
import sqlite3
import stat
import subprocess
import shutil
import sys
import tempfile
import time
import zipfile
from array import array
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
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
  ModelConfig,
  ObsidianVaultConfig,
  ObsidianVaultState,
  ReviewModelConfig,
  ProjectDeleteResult,
  ProjectDirectoryOpenResult,
  ProjectDreamPromoteRequest,
  ProjectDreamRunRequest,
  ProjectMemoryUpdateRequest,
  ProjectDetail,
  ProjectExportRequest,
  ProjectExportResult,
  ProjectMigrationExportResult,
  ProjectMigrationImportRequest,
  ProjectMigrationImportResult,
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
  StoryOverviewModelStatus,
  WorkingTreeStatus,
)
from novel_backend.services.embedding_service import embed_texts, embedding_config_signature
from novel_backend.services.log_service import append_app_log, append_prompt_history
from novel_backend.services.model_error_service import classify_model_error
from novel_backend.services.model_runtime_service import mark_model_runtime_cooldown, model_runtime_slot
from novel_backend.services.model_http_service import request_json_with_retries
from novel_backend.services.obsidian_service import (
  collect_obsidian_note_records,
  load_obsidian_state,
  obsidian_note_record_for_source_key,
  obsidian_source_signature_entries,
  select_obsidian_notes_for_query,
  save_obsidian_config,
  scoped_obsidian_note_records_for_chapter,
  sync_obsidian_state,
)
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
from novel_backend.services.project_narrative_state_service import (
  confirm_project_obsidian_maintenance_merge_suggestion,
  confirm_project_obsidian_maintenance_merge_suggestions,
  ignore_project_obsidian_maintenance_suggestion,
  ignore_project_obsidian_maintenance_suggestions,
  publish_project_obsidian_maintenance_suggestion,
  publish_project_obsidian_maintenance_suggestions,
  record_project_narrative_state_observation,
  refresh_project_narrative_state_chapter_cards,
  reopen_project_obsidian_maintenance_suggestion,
  reopen_project_obsidian_maintenance_suggestions,
  stage_project_obsidian_maintenance_suggestion,
  stage_project_obsidian_maintenance_suggestions,
)
from novel_backend.services.project_style_xp_evolution_service import record_project_style_xp_observation
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
from novel_backend.services.config_service import load_config, project_index_path
from novel_backend.utils.jsonfile import atomic_write_json, atomic_write_text, read_json

_LOCAL_HISTORY_DIRNAME = ".novel-history"
_APP_STATE_DIRNAME = ".gaoxia"
_AGENT_THREADS_DIRNAME = "threads"
_AGENT_RUNS_DIRNAME = "runs"
_MIGRATION_MANIFEST_FILENAME = ".gaoxia-project.json"
_MIGRATION_PROJECT_ROOT = "project"
_MIGRATION_PACKAGE_SUFFIX = ".gaoxia-project.zip"
_MIGRATION_SCHEMA_VERSION = "1"
_MIGRATION_MAX_FILE_COUNT = 20_000
_MIGRATION_MAX_UNCOMPRESSED_BYTES = 2_000_000_000
_MODEL_STORY_OVERVIEW_FILENAME = "story_overview_model.json"
_MODEL_STORY_OVERVIEW_FAILURE_FILENAME = "story_overview_model_failure.json"
_MODEL_STORY_OVERVIEW_SCHEMA_VERSION = "1"
_MIGRATION_OBSIDIAN_THREAD_NOTICE = "外部 Obsidian Vault 的资料分析记录已从迁移包移除，导入后需要重新同步 Vault 并重新分析资料。"
_MIGRATION_AGENT_TEXT_KEYS = {
  "changes",
  "content",
  "content_preview",
  "detail",
  "details",
  "body_markdown",
  "draft_path",
  "error",
  "instruction",
  "instruction_preview",
  "label",
  "latest_user",
  "latest_user_message",
  "message",
  "path",
  "preview",
  "prevention",
  "reason",
  "relative_path",
  "reply",
  "result",
  "rationale",
  "source",
  "source_key",
  "summary",
  "title",
  "vault_path",
}
_MIGRATION_AGENT_NOTICE_TITLE = "Obsidian 资料分析已移除"
_MODEL_STORY_OVERVIEW_SOURCE_CHUNK_LIMIT = 4500
_ARCHITECTURE_PROGRESS_FILENAME = "architecture_progress.json"
_ARCHITECTURE_PROGRESS_SCHEMA_VERSION = "1"
_AGENT_THREAD_CONTEXT_DIRNAME = "thread_context"
_AGENT_THREAD_CONTEXT_SCHEMA_VERSION = "1"
_AGENT_THREAD_CHUNK_SIZE = 1200
_AGENT_THREAD_CHUNK_OVERLAP = 160
_AGENT_THREAD_CONTEXT_MAX_CHARS = 4800
_REFERENCE_DIRNAME = "references"
_SNAPSHOT_FILES_DIRNAME = "files"
_KNOWLEDGE_SCHEMA_VERSION = "2"
_KNOWLEDGE_SEMANTIC_CANDIDATE_MIN = 48
_KNOWLEDGE_SEMANTIC_CANDIDATE_CAP = 240
_KNOWLEDGE_CHAPTER_FILTER_RESULT_CAP = 80
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
  "世界名",
  "蓝图",
  "骨架",
  "摘要",
  "设定",
  "结构",
  "时间线",
  "规则",
  "连续性规则",
  "初始状态",
  "感情线",
  "目标规模",
  "高潮分布",
  "神话主线",
  "全局叙事主线",
  "感情线节奏",
  "冲突",
  "项目",
  "当前小说",
  "方式",
  "封王",
  "国主",
  "相连",
  "金丹",
  "元婴",
  "赵王",
  "经学",
  "国运",
  "宗门",
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
  "章尾",
  "章展开",
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
  "方式",
  "每章",
  "主线",
  "感情线",
  "信任线",
  "目标",
  "规模",
  "高潮",
  "分布",
  "节奏",
  "生成",
  "叙事",
  "按上",
  "下三段",
  "王印",
  "华林苑",
  "经义",
  "胡天",
  "山海",
  "意象",
  "记名",
  "王朝",
  "天王",
  "北方",
  "东宫",
  "国主",
  "后赵",
  "葛陂",
  "权力",
  "封王",
  "州鼎",
  "副印",
  "境成",
  "失控",
  "相连",
  "机制",
  "结构",
  "规则",
  "国家",
  "国家修",
  "修仙",
  "修真",
  "东晋",
  "十六",
  "龙城",
  "香火",
  "金丹",
  "元婴",
  "通天",
  "古神",
  "怨炁",
  "国运",
  "邺城",
  "经学",
  "宗门",
  "天庭",
  "境界",
  "阵法",
  "法术",
  "文书",
  "史书",
  "宫廷",
  "边界",
  "材料",
  "路径",
  "制度",
  "主题",
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
_NON_CHARACTER_NAME_CHARS = frozenset("的了与及为被将把从因却虽而在是有和或并都就向以到给让使会要能须需应")
_DISCOVERED_CHARACTER_TRAILING_CONTEXT_CHARS = frozenset("称之任建成改反乱以连为被将把从因却虽而在死废受派写严等幼随第获不说问答喊叫笑看听想拿握见劝盯")
_DISCOVERED_CHARACTER_CONTEXT_PATTERN = re.compile(
  r"(?:"
  r"说|问|答|喊|叫|笑|冷笑|看|听|想|知道|觉得|认为|选择|决定|试图|负责|"
  r"参加|陷入|怀疑|追查|掌握|拿|握|回到|回来|离开|赶到|走进|进入|"
  r"来信|写信|见|盯|劝|提到|不答|不该|不会|不能|称帝|称王|称天王|称"
  r")"
)
_DISCOVERED_CHARACTER_LEFT_CONTEXT_PATTERN = re.compile(
  r"(?:"
  r"见|问|劝|对|向|替|给|找|逼|"
  r"主角|人物|角色|妻|父|母|兄|弟|姐|妹"
  r")$"
)
_CHARACTER_REVIEW_CACHE_VERSION = "1"
_ENTITY_REVIEW_CACHE_VERSION = "1"
_ENTITY_REVIEW_KINDS = ("events", "locations", "organizations", "props", "skills")
_ENTITY_REVIEW_LABELS = {
  "events": "事件",
  "locations": "地点",
  "organizations": "组织/势力",
  "props": "道具",
  "skills": "技能",
}
_CHAPTER_EVENT_ACTION_PATTERN = re.compile(
  r"(?:"
  r"进入|走进|回到|回来|离开|赶到|找到|拿到|握住|打开|闯进|避开|发现|听见|"
  r"问|答|说|冷笑|追查|追近|决定|选择|开始|建立|失踪|暴露|返回|捡到|堵住|"
  r"封闭|追求|试图|塞进|带着|点亮|横刀|来信|提到|翻出|低声议论"
  r")"
)
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
  "石头",
  "王印",
  "华林苑",
}
_DISCOVERED_CHARACTER_EXACT_BLACKLIST = {
  "季龙",
  "石头",
  "刘氏线",
  "王印",
  "华林苑",
  "解石季",
  "向石季",
  "相吞噬",
  "王朝怨",
  "都不能",
  "赵王",
  "天王",
  "金丹",
  "元婴",
  "国运",
  "宗门",
  "经学",
  "灵脉",
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
_DISCOVERED_NAME_TRAILING_CONTEXT_CHARS = frozenset(
  "的在对向和与把被将为从到给让使是有会要能可须需应因以跟同由曾仍已正也都只却但后"
)
_DISCOVERED_NAME_TRAILING_CONTEXT_PREFIXES = (
  "保持",
  "继续",
  "负责",
  "主动",
  "拒绝",
  "选择",
  "陷入",
  "试图",
  "争取",
  "证明",
  "推动",
  "需要",
  "必须",
  "已经",
  "正在",
  "仍有",
  "曾经",
)
_DISCOVERED_NAME_RIGHT_CONTEXT_CHARS = frozenset(
  "的在对向和与把被将为从到给让使说问想看听试选拒陷负曾仍已正会要能可须需应因以跟同靠去来回做冷见后"
)
_DISCOVERED_NAME_LEFT_CONTEXT_CHARS = frozenset("问劝叫让给对向和与跟同见找着")
_DISCOVERED_NAME_LEFT_CONTEXT_TOKENS = (
  "姓名",
  "名字",
  "名为",
  "叫",
  "人物",
  "角色",
  "主角",
  "男主",
  "女主",
  "反派",
  "配角",
  "导师",
  "上司",
  "下属",
  "同事",
  "同学",
  "学生",
  "实习生",
  "妻子",
  "丈夫",
  "父亲",
  "母亲",
  "哥哥",
  "姐姐",
  "妹妹",
  "弟弟",
  "朋友",
  "对手",
  "搭档",
)
_NON_CHARACTER_ENTITY_SUFFIX_BLACKLIST = (
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
  "王朝",
  "朝廷",
  "地脉",
  "州鼎",
  "副印",
  "秩序",
  "制度",
  "仪式",
  "方式",
  "势力",
  "阵营",
  "庭",
  "国",
  "朝",
)
_PROJECT_DIR_PREFIX_PATTERN = re.compile(r"^(\d{8}_\d{6})_(.+)$")
_LOCATION_PATTERN = re.compile(
  r"([\u4e00-\u9fff]{1,8}(?:港口|码头|仓库|车站|书房|病房|教室|办公室|走廊|庭院|屋顶|船舱|甲板|酒馆|会馆|广场|宫门|城门|巷|街|桥|山谷|河岸|湖畔|小镇|古城|村庄|城))"
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
  "宫门",
  "城门",
  "街口",
  "雨巷",
  "河岸",
  "湖畔",
  "小镇",
  "古城",
  "村庄",
  "城",
  "船",
)
_LOCATION_NAME_BLACKLIST = {
  "屠城",
  "攻城",
  "夺城",
  "造桥",
  "仓库",
  "城",
  "宫门",
  "城门",
  "宫城",
  "都城",
}
_LOCATION_NAME_BLACKLIST_FRAGMENTS = (
  "章尾",
  "章展开",
  "可以",
  "一城",
  "或城",
  "钵中",
  "钵水",
  "宴饮",
  "遮住",
  "压近",
  "参与",
  "怨炁",
  "籍阵",
  "最终",
  "身体",
  "每座",
  "同一座",
  "记载",
)
_ORGANIZATION_PATTERN = re.compile(
  r"([\u4e00-\u9fff]{2,12}(?:商会|警署|监察局|巡夜队|学宫|教会|公司|研究所|军团|联盟|帮会|门派|公会|教团|议会|财团|神殿|宗门|骑士团|帮派|王朝|朝廷|王庭|燕庭))"
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
  "王朝",
  "朝廷",
  "王庭",
  "燕庭",
)
_ORGANIZATION_GENERIC_NAMES = {
  "宗门",
  "王朝",
  "朝廷",
  "旧王朝",
  "普通宗门",
}
_ORGANIZATION_NAME_BLACKLIST_FRAGMENTS = (
  "不写成",
  "避免",
  "适合",
  "代表",
  "第一次",
  "看见",
  "国家像",
  "国家如",
  "章尾",
  "而是",
  "与旧王朝",
  "每逢",
  "通过",
  "史官",
  "主角",
  "国家为",
  "战利品",
  "隐语",
  "典籍",
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
_SINGLE_CHARACTER_PROP_KEYWORDS = frozenset({"灯", "信", "刀", "剑", "枪", "伞"})
_PROP_CONTEXT_PATTERNS = {
  "灯": re.compile(r"(?:一盏|这盏|那盏|油|铜|铁|旧|煤油|马|长明|手提|壁)灯(?!塔|光|火|影|芯|罩)"),
  "信": re.compile(r"(?:一封|这封|那封|密|旧|书|手写|匿名|遗|家|绝笔|求救|告密)信(?!任|号|息|念|仰|用|件)"),
  "刀": re.compile(r"(?:一把|这把|那把|短|长|弯|钢|铁|旧|断|佩|战|横|苗)刀(?!法|术|锋|口|柄|光|痕)"),
  "剑": re.compile(r"(?:一柄|一把|这把|那把|长|短|木|铁|铜|青铜|佩|断|古|宝)剑(?!术|法|气|意|阵|客|士)"),
  "枪": re.compile(r"(?:一杆|一把|这把|那把|长|短|火|手|步|猎|旧)枪(?!法|术|声|口|弹|械|兵|炮)"),
  "伞": re.compile(r"(?:一把|这把|那把|油纸|黑|红|旧|纸)伞(?!兵)"),
}
_PROP_SIMILE_PATTERN_TEMPLATE = r"(?:像|仿佛|如同|似)[^。！？!?；;\n]{{0,16}}{keyword}"
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
_SKILL_CONTEXT_TOKENS = (
  "擅长",
  "善于",
  "精通",
  "熟悉",
  "掌握",
  "精于",
  "最会",
  "很会",
  "会",
  "具备",
  "有",
  "靠",
  "用",
  "以",
)
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
_SKILL_BLACKLIST_FRAGMENTS = (
  "代表",
  "这些",
  "此道",
  "国家",
  "写成",
  "适合",
  "转化",
  "神通",
  "三类",
  "某种",
  "大型",
  "北方君主",
)
_ENTITY_CONTEXT_TOKENS = (
  "第一次看见",
  "详细记载",
  "最终让",
  "章展开",
  "章尾",
  "写成",
  "变成",
  "成为",
  "迁都",
  "营建",
  "镇守",
  "记载",
  "展示",
  "解释成",
  "章",
  "参与",
  "遮住",
  "压近",
  "回到",
  "来到",
  "前往",
  "抵达",
  "赶到",
  "潜入",
  "避开",
  "冲进",
  "走进",
  "进入",
  "入",
  "站在",
  "留在",
  "躲进",
  "返回",
  "奔向",
  "看向",
  "驶向",
  "抵抗被",
  "用",
  "以",
  "为",
  "把",
  "让",
  "使",
  "被",
  "救",
  "而是",
  "像",
  "如",
  "与",
  "和",
  "在",
  "到",
  "进",
  "向",
  "朝",
  "往",
  "从",
  "的",
)
_LOCATION_ORGANIZATION_FOLLOWING_SUFFIXES = tuple(
  sorted(_ORGANIZATION_KEYWORDS, key=len, reverse=True)
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


def _path_is_inside(path: Path, root: Path) -> bool:
  try:
    return path.expanduser().resolve().is_relative_to(root.expanduser().resolve())
  except (OSError, ValueError):
    return False


def _migration_cache_dir(settings: Settings) -> Path:
  cache_dir = settings.data_dir / "cache" / "project_migrations"
  cache_dir.mkdir(parents=True, exist_ok=True)
  return cache_dir


def _migration_output_dir(project_dir: Path) -> Path:
  output_dir = project_dir / "exports"
  output_dir.mkdir(parents=True, exist_ok=True)
  return output_dir


def _should_skip_migration_file(relative_path: str) -> bool:
  normalized = relative_path.replace("\\", "/")
  return normalized.startswith("exports/") and normalized.endswith(_MIGRATION_PACKAGE_SUFFIX)


def _migration_external_resource_warnings(project_dir: Path) -> list[str]:
  warnings: list[str] = []
  obsidian_payload = read_json(project_dir / _APP_STATE_DIRNAME / "obsidian.json", {})
  if isinstance(obsidian_payload, dict) and obsidian_payload.get("enabled"):
    raw_vault_path = str(obsidian_payload.get("vault_path") or "").strip()
    if raw_vault_path:
      vault_path = Path(raw_vault_path).expanduser()
      if not vault_path.is_absolute():
        vault_path = project_dir / vault_path
      if not _path_is_inside(vault_path, project_dir):
        warnings.append(
          f"Obsidian Vault 位于项目目录外，迁移包只保存配置和项目学习状态，不复制外部 Vault 原文、笔记摘要、维护草稿、蒸馏摘要或索引：{raw_vault_path}"
        )
  return warnings


def _project_has_external_obsidian_vault(project_dir: Path) -> bool:
  obsidian_payload = read_json(project_dir / _APP_STATE_DIRNAME / "obsidian.json", {})
  if not isinstance(obsidian_payload, dict) or not obsidian_payload.get("enabled"):
    return False
  raw_vault_path = str(obsidian_payload.get("vault_path") or "").strip()
  if not raw_vault_path:
    return False
  vault_path = Path(raw_vault_path).expanduser()
  if not vault_path.is_absolute():
    vault_path = project_dir / vault_path
  return not _path_is_inside(vault_path, project_dir)


def _sanitize_migration_knowledge_db(source_path: Path, output_path: Path) -> None:
  output_path.parent.mkdir(parents=True, exist_ok=True)
  shutil.copy2(source_path, output_path)
  _initialize_knowledge_db(output_path)
  connection = sqlite3.connect(output_path)
  try:
    chunk_ids = [
      str(row[0])
      for row in connection.execute(
        """
        SELECT chunk_id
        FROM knowledge_chunks
        WHERE kind = 'obsidian' OR source = 'Obsidian' OR source_key LIKE 'obsidian:%'
        """
      ).fetchall()
    ]
    if chunk_ids:
      rows = [(chunk_id,) for chunk_id in chunk_ids]
      connection.executemany("DELETE FROM knowledge_vectors WHERE chunk_id = ?", rows)
      connection.executemany("DELETE FROM knowledge_chunks_fts WHERE chunk_id = ?", rows)
      connection.executemany("DELETE FROM knowledge_chunks WHERE chunk_id = ?", rows)
    connection.execute(
      """
      DELETE FROM knowledge_sources
      WHERE kind = 'obsidian' OR source = 'Obsidian' OR source_key LIKE 'obsidian:%'
      """
    )
    _set_knowledge_state(connection, "source_signature", "")
    _set_knowledge_state(connection, "indexed_at", "")
    connection.commit()
  finally:
    connection.close()


def _sanitize_migration_obsidian_sync(project_dir: Path, output_path: Path) -> None:
  config_payload = read_json(project_dir / _APP_STATE_DIRNAME / "obsidian.json", {})
  if isinstance(config_payload, dict):
    config = ObsidianVaultConfig.model_validate(config_payload)
  else:
    config = ObsidianVaultConfig()

  sync_payload = read_json(project_dir / _APP_STATE_DIRNAME / "obsidian_sync.json", {})
  warnings: list[str] = []
  if isinstance(sync_payload, dict):
    warnings = [str(item) for item in sync_payload.get("warnings") or [] if str(item).strip()]
  warning = "外部 Obsidian Vault 的笔记摘要已从迁移包移除，导入后需要重新同步 Vault。"
  if warning not in warnings:
    warnings.append(warning)

  state = ObsidianVaultState(
    config=config,
    enabled=config.enabled,
    vault_path=config.vault_path.strip(),
    source_signature="",
    updated_at=_now_iso(),
    warnings=warnings,
  )
  output_path.parent.mkdir(parents=True, exist_ok=True)
  atomic_write_json(output_path, state.model_dump(mode="json"))


def _empty_migration_obsidian_maintenance_summary() -> dict[str, object]:
  return {
    "total": 0,
    "needs_action": 0,
    "high_priority": 0,
    "auto_staged": 0,
    "manual_draft_edits": 0,
    "preserved_existing_draft": 0,
    "by_status": {
      "open": 0,
      "staged": 0,
      "published": 0,
      "draft_missing": 0,
      "published_missing": 0,
      "published_outdated": 0,
      "vault_moved": 0,
      "ignored": 0,
    },
    "top_items": [],
    "migration_notice": "外部 Obsidian Vault 的维护队列已从迁移包移除，导入后需要重新同步 Vault。",
  }


def _sanitize_migration_narrative_state(source_path: Path, output_path: Path) -> None:
  payload = read_json(source_path, {})
  if not isinstance(payload, dict):
    payload = {}
  sanitized = dict(payload)
  sanitized["obsidian_maintenance_suggestions"] = []
  sanitized["obsidian_maintenance_actions"] = []
  sanitized["obsidian_maintenance_summary"] = _empty_migration_obsidian_maintenance_summary()
  output_path.parent.mkdir(parents=True, exist_ok=True)
  atomic_write_json(output_path, sanitized)


def _sanitize_migration_distillation_items(items: object) -> list[object]:
  if not isinstance(items, list):
    return []
  sanitized: list[object] = []
  for item in items:
    if isinstance(item, str) and item.strip().startswith("Obsidian:"):
      continue
    sanitized.append(item)
  return sanitized


def _sanitize_migration_project_distillation(source_path: Path, output_path: Path) -> None:
  payload = read_json(source_path, {})
  if not isinstance(payload, dict):
    payload = {}
  sanitized = dict(payload)
  profile = sanitized.get("source_profile")
  if isinstance(profile, dict):
    profile = dict(profile)
    for key in (
      "narrative_rules",
      "style_traits",
      "core_conflicts",
      "character_notes",
      "event_notes",
      "location_notes",
      "prop_notes",
      "skill_notes",
      "material_notes",
    ):
      profile[key] = _sanitize_migration_distillation_items(profile.get(key))
    if str(profile.get("summary") or "").strip().startswith("Obsidian:"):
      profile["summary"] = ""
    sanitized["source_profile"] = profile

  packs = sanitized.get("packs")
  if isinstance(packs, list):
    sanitized_packs: list[object] = []
    for pack in packs:
      if not isinstance(pack, dict):
        sanitized_packs.append(pack)
        continue
      sanitized_pack = dict(pack)
      for key in ("must_keep", "execution_focus", "voice_rules", "blocked_changes", "prepared_from"):
        sanitized_pack[key] = _sanitize_migration_distillation_items(sanitized_pack.get(key))
      sanitized_packs.append(sanitized_pack)
    sanitized["packs"] = sanitized_packs

  sanitized["source_signature"] = ""
  sanitized["is_stale"] = True
  sanitized["migration_notice"] = "外部 Obsidian Vault 的蒸馏摘要已从迁移包移除，导入后需要重新生成项目蒸馏。"
  output_path.parent.mkdir(parents=True, exist_ok=True)
  atomic_write_json(output_path, sanitized)


def _migration_text_mentions_obsidian(value: object) -> bool:
  if isinstance(value, str):
    normalized = value.lower()
    return "obsidian" in normalized or "vault" in normalized or "外部笔记" in value or "维护草稿" in value
  if isinstance(value, list):
    return any(_migration_text_mentions_obsidian(item) for item in value)
  if isinstance(value, dict):
    return any(_migration_text_mentions_obsidian(item) for item in value.values())
  return False


def _sanitize_migration_agent_artifacts(artifacts: object) -> tuple[list[object], bool]:
  if not isinstance(artifacts, list):
    return [], False
  sanitized: list[object] = []
  changed = False
  for item in artifacts:
    if not isinstance(item, dict):
      sanitized.append(item)
      continue
    kind = str(item.get("kind") or "").strip()
    sensitive_kind = kind in {"knowledge_summary", "obsidian_maintenance"} or "obsidian" in kind.lower()
    if sensitive_kind or _migration_text_mentions_obsidian(item):
      changed = True
      sanitized.append(
        {
          "kind": kind or "migration_sanitized",
          "title": "Obsidian 资料分析已移除",
          "summary": _MIGRATION_OBSIDIAN_THREAD_NOTICE,
          "content_preview": "",
          "metadata": {"migration_notice": _MIGRATION_OBSIDIAN_THREAD_NOTICE},
        }
      )
      continue
    sanitized.append(item)
  return sanitized, changed


def _sanitize_migration_agent_traces(traces: object) -> tuple[list[object], bool]:
  if not isinstance(traces, list):
    return [], False
  sanitized: list[object] = []
  changed = False
  for item in traces:
    if not isinstance(item, dict):
      sanitized.append(item)
      continue
    action_kind = str(item.get("action_kind") or "").strip()
    if action_kind == "review_knowledge" or _migration_text_mentions_obsidian(item):
      changed = True
      next_item = dict(item)
      next_item["summary"] = _MIGRATION_OBSIDIAN_THREAD_NOTICE
      next_item["changes"] = [_MIGRATION_OBSIDIAN_THREAD_NOTICE]
      sanitized.append(next_item)
      continue
    sanitized.append(item)
  return sanitized, changed


def _sanitize_migration_agent_event_blocks(event_blocks: object) -> tuple[list[object], bool]:
  if not isinstance(event_blocks, list):
    return [], False
  sanitized: list[object] = []
  changed = False
  for item in event_blocks:
    if not isinstance(item, dict):
      sanitized.append(item)
      continue
    action_kind = str(item.get("action_kind") or "").strip()
    if action_kind == "review_knowledge" or _migration_text_mentions_obsidian(item):
      changed = True
      next_item = dict(item)
      next_item["title"] = "Obsidian 资料分析已移除"
      next_item["summary"] = _MIGRATION_OBSIDIAN_THREAD_NOTICE
      sanitized.append(next_item)
      continue
    sanitized.append(item)
  return sanitized, changed


def _sanitize_migration_agent_thread_message(message: object) -> tuple[object, bool]:
  if not isinstance(message, dict):
    return message, False
  sanitized = dict(message)
  changed = False

  artifacts, artifacts_changed = _sanitize_migration_agent_artifacts(sanitized.get("artifacts"))
  if artifacts_changed:
    sanitized["artifacts"] = artifacts
    changed = True

  traces, traces_changed = _sanitize_migration_agent_traces(sanitized.get("execution_trace"))
  if traces_changed:
    sanitized["execution_trace"] = traces
    changed = True

  event_blocks, event_blocks_changed = _sanitize_migration_agent_event_blocks(sanitized.get("event_blocks"))
  if event_blocks_changed:
    sanitized["event_blocks"] = event_blocks
    changed = True

  if changed and str(sanitized.get("role") or "") == "assistant":
    sanitized["content"] = _MIGRATION_OBSIDIAN_THREAD_NOTICE
    sanitized["summary"] = _MIGRATION_OBSIDIAN_THREAD_NOTICE
    sanitized["original_length"] = len(_MIGRATION_OBSIDIAN_THREAD_NOTICE)
    sanitized["content_hash"] = _agent_thread_content_hash(_MIGRATION_OBSIDIAN_THREAD_NOTICE)
    sanitized["changes"] = [_MIGRATION_OBSIDIAN_THREAD_NOTICE]
  return sanitized, changed


def _sanitize_migration_agent_thread_file(source_path: Path, output_path: Path) -> None:
  payload = read_json(source_path, {})
  if not isinstance(payload, dict):
    payload = {}
  sanitized = dict(payload)
  messages = sanitized.get("messages")
  if isinstance(messages, list):
    sanitized_messages: list[object] = []
    for message in messages:
      sanitized_message, _changed = _sanitize_migration_agent_thread_message(message)
      sanitized_messages.append(sanitized_message)
    sanitized["messages"] = sanitized_messages
  output_path.parent.mkdir(parents=True, exist_ok=True)
  atomic_write_json(output_path, sanitized)


def _migration_agent_workflow_marker(payload: dict[str, object]) -> bool:
  kind = str(payload.get("kind") or payload.get("action_kind") or "").strip()
  subtask_id = str(payload.get("subtask_id") or "").strip()
  artifact_kind = str(payload.get("artifact_kind") or "").strip()
  return (
    kind == "review_knowledge"
    or subtask_id.startswith("review_knowledge")
    or artifact_kind == "knowledge_summary"
    or kind in {"knowledge_summary", "obsidian_maintenance"}
    or "obsidian" in kind.lower()
    or "obsidian" in artifact_kind.lower()
  )


def _migration_agent_notice_value(key: str) -> object:
  if key == "content_preview":
    return ""
  if key in {"title", "label"}:
    return _MIGRATION_AGENT_NOTICE_TITLE
  if key in {"changes", "suggestions"}:
    return [_MIGRATION_OBSIDIAN_THREAD_NOTICE]
  return _MIGRATION_OBSIDIAN_THREAD_NOTICE


def _sanitize_migration_agent_workflow_value(value: object, *, sensitive: bool = False) -> object:
  if isinstance(value, list):
    return [
      _sanitize_migration_agent_workflow_value(item, sensitive=sensitive)
      for item in value
    ]
  if not isinstance(value, dict):
    return value

  local_sensitive = sensitive or _migration_agent_workflow_marker(value)
  sanitized: dict[str, object] = {}
  for raw_key, raw_value in value.items():
    key = str(raw_key)
    if key in {"artifacts", "artifact_delta"}:
      artifacts, artifacts_changed = _sanitize_migration_agent_artifacts(raw_value)
      sanitized[key] = artifacts if artifacts_changed else _sanitize_migration_agent_workflow_value(
        raw_value,
        sensitive=local_sensitive,
      )
      continue
    if key == "execution_trace":
      traces, traces_changed = _sanitize_migration_agent_traces(raw_value)
      sanitized[key] = traces if traces_changed else _sanitize_migration_agent_workflow_value(
        raw_value,
        sensitive=local_sensitive,
      )
      continue
    if key == "event_blocks":
      event_blocks, event_blocks_changed = _sanitize_migration_agent_event_blocks(raw_value)
      sanitized[key] = event_blocks if event_blocks_changed else _sanitize_migration_agent_workflow_value(
        raw_value,
        sensitive=local_sensitive,
      )
      continue
    if key in {"contract", "output_validation", "metadata"} and local_sensitive:
      sanitized[key] = {"migration_notice": _MIGRATION_OBSIDIAN_THREAD_NOTICE}
      continue
    if key in _MIGRATION_AGENT_TEXT_KEYS and (local_sensitive or _migration_text_mentions_obsidian(raw_value)):
      sanitized[key] = _migration_agent_notice_value(key)
      continue
    sanitized[key] = _sanitize_migration_agent_workflow_value(raw_value, sensitive=local_sensitive)
  return sanitized


def _sanitize_migration_agent_workflow_file(source_path: Path, output_path: Path) -> None:
  payload = read_json(source_path, {})
  if not isinstance(payload, dict):
    payload = {}
  sanitized = _sanitize_migration_agent_workflow_value(payload)
  output_path.parent.mkdir(parents=True, exist_ok=True)
  atomic_write_json(output_path, sanitized if isinstance(sanitized, dict) else {})


def _sanitize_migration_json_file(source_path: Path, output_path: Path) -> None:
  try:
    payload = json.loads(source_path.read_text(encoding="utf-8"))
  except (OSError, json.JSONDecodeError):
    _sanitize_migration_jsonl_file(source_path, output_path)
    return
  sanitized = _sanitize_migration_agent_workflow_value(payload)
  output_path.parent.mkdir(parents=True, exist_ok=True)
  atomic_write_json(output_path, sanitized)


def _sanitize_migration_jsonl_file(source_path: Path, output_path: Path) -> None:
  sanitized_lines: list[str] = []
  try:
    raw_lines = source_path.read_text(encoding="utf-8").splitlines()
  except OSError:
    raw_lines = []

  for raw_line in raw_lines:
    if not raw_line.strip():
      continue
    try:
      payload = json.loads(raw_line)
    except json.JSONDecodeError:
      if _migration_text_mentions_obsidian(raw_line):
        payload = {"migration_notice": _MIGRATION_OBSIDIAN_THREAD_NOTICE}
      else:
        sanitized_lines.append(raw_line)
        continue
    sanitized = _sanitize_migration_agent_workflow_value(payload)
    sanitized_lines.append(json.dumps(sanitized, ensure_ascii=False))

  output_path.parent.mkdir(parents=True, exist_ok=True)
  atomic_write_text(output_path, "\n".join(sanitized_lines) + ("\n" if sanitized_lines else ""))


def _iter_migration_project_files(
  project_dir: Path,
  *,
  scrub_external_obsidian_index: bool = False,
) -> tuple[list[Path], list[str]]:
  files: list[Path] = []
  warnings: list[str] = []

  for path in sorted(project_dir.rglob("*"), key=lambda item: item.relative_to(project_dir).as_posix()):
    if not path.is_file():
      continue
    relative_path = path.relative_to(project_dir).as_posix()
    if _should_skip_migration_file(relative_path):
      continue
    if scrub_external_obsidian_index and relative_path.startswith(f"{_APP_STATE_DIRNAME}/obsidian_drafts/"):
      continue
    if scrub_external_obsidian_index and relative_path.startswith(f"{_APP_STATE_DIRNAME}/{_AGENT_THREAD_CONTEXT_DIRNAME}/"):
      continue
    if path.is_symlink():
      warnings.append(f"已跳过符号链接文件：{relative_path}")
      continue
    files.append(path)

  return files, warnings


def _safe_import_dirname(value: object, fallback_name: str) -> str:
  raw_value = str(value or "").strip().replace("\\", "/")
  candidate = PurePosixPath(raw_value).name if raw_value else ""
  if candidate in {"", ".", ".."}:
    candidate = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{_safe_folder_name(fallback_name)}"

  cleaned = "".join("_" if char in '<>:"/\\|?*' or ord(char) < 32 else char for char in candidate)
  cleaned = cleaned.strip(" .")
  return cleaned[:120] or f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_novel-project"


def _unique_import_project_dir(base_dir: Path, preferred_dirname: str) -> Path:
  candidate = base_dir / preferred_dirname
  if not candidate.exists():
    return candidate

  timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
  first_candidate = base_dir / f"{preferred_dirname}_导入_{timestamp}"
  if not first_candidate.exists():
    return first_candidate

  for index in range(2, 1000):
    next_candidate = base_dir / f"{preferred_dirname}_导入_{timestamp}_{index}"
    if not next_candidate.exists():
      return next_candidate

  raise HTTPException(
    status_code=409,
    detail={"code": "migration_import_dir_exists", "message": "导入目录已存在，请清理重名目录后再试"},
  )


def _coerce_project_meta_int(value: object, default: int, lower: int, upper: int) -> int:
  try:
    parsed = int(value)
  except (TypeError, ValueError):
    return default
  return max(lower, min(upper, parsed))


def _invalid_migration_package(message: str, *, status_code: int = 400) -> HTTPException:
  return HTTPException(
    status_code=status_code,
    detail={"code": "invalid_migration_package", "message": message},
  )


def _decode_migration_package(content_base64: str) -> bytes:
  try:
    return base64.b64decode(content_base64.encode("utf-8"), validate=True)
  except (binascii.Error, ValueError) as error:
    raise _invalid_migration_package("迁移包内容不是有效的 Base64") from error


def _safe_zip_member_path(filename: str) -> PurePosixPath:
  normalized = filename.replace("\\", "/")
  if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
    raise _invalid_migration_package("迁移包包含非法绝对路径")

  path = PurePosixPath(normalized)
  if any(part in {"", ".", ".."} for part in path.parts):
    raise _invalid_migration_package("迁移包包含非法相对路径")

  return path


def _zip_member_is_symlink(info: zipfile.ZipInfo) -> bool:
  mode = info.external_attr >> 16
  return stat.S_ISLNK(stat.S_IFMT(mode))


def _read_migration_manifest(archive: zipfile.ZipFile) -> dict:
  try:
    raw_manifest = archive.read(_MIGRATION_MANIFEST_FILENAME)
  except KeyError as error:
    raise _invalid_migration_package("这不是稿匣项目迁移包") from error

  try:
    manifest = json.loads(raw_manifest.decode("utf-8"))
  except (UnicodeDecodeError, json.JSONDecodeError) as error:
    raise _invalid_migration_package("迁移包清单无法读取") from error

  if not isinstance(manifest, dict):
    raise _invalid_migration_package("迁移包清单格式不正确")
  return manifest


def _migration_archive_project_files(archive: zipfile.ZipFile) -> tuple[list[tuple[zipfile.ZipInfo, PurePosixPath]], int]:
  project_files: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
  total_size = 0

  for info in archive.infolist():
    if info.is_dir():
      continue

    member_path = _safe_zip_member_path(info.filename)
    member_name = member_path.as_posix()
    if member_name == _MIGRATION_MANIFEST_FILENAME:
      continue
    if not member_name.startswith(f"{_MIGRATION_PROJECT_ROOT}/"):
      raise _invalid_migration_package("迁移包包含项目目录外的文件")
    if _zip_member_is_symlink(info):
      raise _invalid_migration_package("迁移包包含符号链接文件，无法安全导入")

    relative_path = PurePosixPath(member_name[len(f"{_MIGRATION_PROJECT_ROOT}/"):])
    if any(part in {"", ".", ".."} for part in relative_path.parts):
      raise _invalid_migration_package("迁移包包含非法项目文件路径")

    total_size += int(info.file_size)
    if total_size > _MIGRATION_MAX_UNCOMPRESSED_BYTES:
      raise _invalid_migration_package("迁移包解压后体积超过限制", status_code=413)

    project_files.append((info, relative_path))
    if len(project_files) > _MIGRATION_MAX_FILE_COUNT:
      raise _invalid_migration_package("迁移包文件数量超过限制", status_code=413)

  return project_files, total_size


def _extract_migration_project(
  archive: zipfile.ZipFile,
  project_files: list[tuple[zipfile.ZipInfo, PurePosixPath]],
  target_dir: Path,
) -> None:
  target_root = target_dir.resolve()

  for info, relative_path in project_files:
    output_path = target_dir.joinpath(*relative_path.parts)
    if not output_path.resolve().is_relative_to(target_root):
      raise _invalid_migration_package("迁移包包含非法项目文件路径")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(info) as source, output_path.open("wb") as output:
      shutil.copyfileobj(source, output)


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


def _agent_thread_context_dir(project_dir: Path) -> Path:
  return _app_state_dir(project_dir) / _AGENT_THREAD_CONTEXT_DIRNAME


def _agent_threads_index_path(project_dir: Path) -> Path:
  return _agent_threads_dir(project_dir) / "index.json"


def _model_story_overview_path(project_dir: Path) -> Path:
  return _app_state_dir(project_dir) / _MODEL_STORY_OVERVIEW_FILENAME


def _model_story_overview_failure_path(project_dir: Path) -> Path:
  return _app_state_dir(project_dir) / _MODEL_STORY_OVERVIEW_FAILURE_FILENAME


def _architecture_progress_path(project_dir: Path) -> Path:
  return _app_state_dir(project_dir) / _ARCHITECTURE_PROGRESS_FILENAME


def _agent_thread_path(project_dir: Path, thread_id: str) -> Path:
  return _agent_threads_dir(project_dir) / f"{thread_id}.json"


def _agent_thread_context_path(project_dir: Path, thread_id: str) -> Path:
  return _agent_thread_context_dir(project_dir) / f"{thread_id}.json"


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
  _agent_thread_context_dir(project_dir).mkdir(parents=True, exist_ok=True)

  index_path = _agent_threads_index_path(project_dir)
  if not index_path.exists():
    atomic_write_json(index_path, {"active_thread_id": "", "threads": []})


def _agent_thread_content_hash(content: str) -> str:
  return hashlib.sha1(str(content or "").encode("utf-8")).hexdigest()


def _agent_thread_message_id(message: object, index: int) -> str:
  explicit_id = str(getattr(message, "id", "") or "").strip()
  if explicit_id:
    return explicit_id[:80]
  content_hash = str(getattr(message, "content_hash", "") or "").strip()
  if content_hash:
    return content_hash[:80]
  content = str(getattr(message, "content", "") or "")
  return f"message-{index + 1}-{_agent_thread_content_hash(content)[:12]}"


def _agent_thread_summary(content: str, limit: int = 420) -> str:
  normalized = " ".join(str(content or "").split())
  if len(normalized) <= limit:
    return normalized
  head_limit = max(80, limit // 2)
  tail_limit = max(80, limit - head_limit - 12)
  return f"{normalized[:head_limit].rstrip()} …… {normalized[-tail_limit:].lstrip()}"


def _agent_thread_chunks(content: str) -> list[str]:
  normalized = str(content or "").strip()
  if not normalized:
    return []
  if len(normalized) <= _AGENT_THREAD_CHUNK_SIZE:
    return [normalized]

  chunks: list[str] = []
  start = 0
  while start < len(normalized):
    end = min(len(normalized), start + _AGENT_THREAD_CHUNK_SIZE)
    chunks.append(normalized[start:end].strip())
    if end >= len(normalized):
      break
    start = max(0, end - _AGENT_THREAD_CHUNK_OVERLAP)
  return [item for item in chunks if item]


def _agent_thread_keyword_terms(text: str) -> set[str]:
  normalized = str(text or "").lower()
  terms: set[str] = set()
  for match in re.finditer(r"[a-z0-9_]{2,}", normalized):
    terms.add(match.group(0))

  for segment in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
    if len(segment) <= 8:
      terms.add(segment)
    for size in (2, 3, 4):
      if len(segment) < size:
        continue
      for index in range(0, len(segment) - size + 1):
        terms.add(segment[index:index + size])
        if len(terms) >= 260:
          return terms
  return terms


def _agent_thread_index_signature(record: AgentThreadRecord) -> str:
  payload = {
    "version": _AGENT_THREAD_CONTEXT_SCHEMA_VERSION,
    "messages": [
      {
        "id": _agent_thread_message_id(message, index),
        "role": message.role,
        "content_hash": message.content_hash or _agent_thread_content_hash(message.content),
        "length": len(message.content or ""),
      }
      for index, message in enumerate(record.messages)
    ],
  }
  return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _agent_thread_context_index(record: AgentThreadRecord) -> dict[str, object]:
  chunks: list[dict[str, object]] = []
  messages: list[dict[str, object]] = []
  for message_index, message in enumerate(record.messages):
    content = str(message.content or "")
    content_hash = message.content_hash or _agent_thread_content_hash(content)
    message_id = _agent_thread_message_id(message, message_index)
    summary = message.summary.strip() or _agent_thread_summary(content)
    messages.append(
      {
        "id": message_id,
        "role": message.role,
        "order": message_index,
        "content_hash": content_hash,
        "original_length": len(content),
        "summary": summary,
      }
    )
    for chunk_index, chunk in enumerate(_agent_thread_chunks(content)):
      chunks.append(
        {
          "message_id": message_id,
          "role": message.role,
          "message_order": message_index,
          "chunk_index": chunk_index,
          "text": chunk,
          "summary": _agent_thread_summary(chunk, limit=180),
          "keywords": sorted(_agent_thread_keyword_terms(chunk))[:260],
        }
      )

  return {
    "schema_version": _AGENT_THREAD_CONTEXT_SCHEMA_VERSION,
    "thread_id": record.id,
    "signature": _agent_thread_index_signature(record),
    "message_count": len(record.messages),
    "messages": messages,
    "chunks": chunks,
  }


def _save_agent_thread_context_index(project_dir: Path, record: AgentThreadRecord) -> None:
  _agent_thread_context_dir(project_dir).mkdir(parents=True, exist_ok=True)
  atomic_write_json(_agent_thread_context_path(project_dir, record.id), _agent_thread_context_index(record))


def _normalized_agent_thread_record(record: AgentThreadRecord, thread_id: str) -> AgentThreadRecord:
  normalized_messages = []
  for index, message in enumerate(record.messages):
    content = str(message.content or "")
    content_hash = message.content_hash.strip() or _agent_thread_content_hash(content)
    normalized_messages.append(
      message.model_copy(
        update={
          "id": _agent_thread_message_id(message, index),
          "content_hash": content_hash,
          "original_length": len(content),
          "summary": message.summary.strip() or _agent_thread_summary(content),
        }
      )
    )
  return record.model_copy(update={"id": thread_id, "messages": normalized_messages})


def _load_agent_thread_record(project_dir: Path, thread_id: str) -> AgentThreadRecord | None:
  normalized_thread_id = _normalize_thread_id_or_400(thread_id)
  thread_payload = read_json(_agent_thread_path(project_dir, normalized_thread_id), None)
  if not isinstance(thread_payload, dict):
    return None
  thread_payload = {**thread_payload, "id": normalized_thread_id}
  try:
    return AgentThreadRecord.model_validate(thread_payload)
  except Exception:
    return None


def _agent_thread_chunk_score(chunk: dict[str, object], query_terms: set[str], current_message_ids: set[str], message_count: int) -> float:
  chunk_terms = set(str(item) for item in chunk.get("keywords", []) if str(item))
  score = 0.0
  for term in query_terms:
    if term in chunk_terms:
      score += max(1.0, min(6.0, len(term) / 2))

  message_id = str(chunk.get("message_id", "") or "")
  if message_id in current_message_ids:
    score += 5.0

  message_order = int(chunk.get("message_order") or 0)
  if message_count > 0:
    score += min(2.0, max(0.0, message_order / message_count * 2.0))
  return score


def _agent_thread_context_payload(project_dir: Path, record: AgentThreadRecord) -> dict[str, object]:
  expected_signature = _agent_thread_index_signature(record)
  index_path = _agent_thread_context_path(project_dir, record.id)
  payload = read_json(index_path, None)
  if (
    not isinstance(payload, dict)
    or payload.get("schema_version") != _AGENT_THREAD_CONTEXT_SCHEMA_VERSION
    or payload.get("signature") != expected_signature
  ):
    _save_agent_thread_context_index(project_dir, record)
    payload = read_json(index_path, None)
  return payload if isinstance(payload, dict) else _agent_thread_context_index(record)


def _agent_thread_message_label(role: str) -> str:
  if role == "user":
    return "用户"
  if role == "system":
    return "系统"
  return "Agent"


def build_project_agent_thread_context(
  settings: Settings,
  project_id: str,
  thread_id: str,
  *,
  query: str = "",
  current_message_ids: list[str] | None = None,
  max_chars: int = _AGENT_THREAD_CONTEXT_MAX_CHARS,
) -> str:
  if not thread_id.strip():
    return ""

  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  _ensure_agent_threads_layout(project_dir)
  record = _load_agent_thread_record(project_dir, thread_id)
  if record is None or not record.messages:
    return ""

  payload = _agent_thread_context_payload(project_dir, record)
  messages = [item for item in payload.get("messages", []) if isinstance(item, dict)]
  chunks = [item for item in payload.get("chunks", []) if isinstance(item, dict)]
  if not chunks:
    return ""

  query_terms = _agent_thread_keyword_terms(query)
  current_ids = {str(item).strip() for item in (current_message_ids or []) if str(item).strip()}
  message_count = max(1, int(payload.get("message_count") or len(messages) or 1))

  long_messages = [
    item
    for item in messages
    if int(item.get("original_length") or 0) > 6000
  ]
  long_messages = sorted(long_messages, key=lambda item: int(item.get("order") or 0), reverse=True)[:4]

  scored_chunks = []
  for chunk in chunks:
    score = _agent_thread_chunk_score(chunk, query_terms, current_ids, message_count)
    if query_terms and score <= 0:
      continue
    scored_chunks.append((score, chunk))

  if query_terms:
    scored_chunks.sort(key=lambda item: (item[0], int(item[1].get("message_order") or 0)), reverse=True)
  else:
    scored_chunks.sort(key=lambda item: int(item[1].get("message_order") or 0), reverse=True)

  selected_chunks: list[dict[str, object]] = []
  seen_chunk_keys: set[tuple[str, int]] = set()

  def append_chunk(chunk: dict[str, object]) -> None:
    key = (str(chunk.get("message_id") or ""), int(chunk.get("chunk_index") or 0))
    if key in seen_chunk_keys:
      return
    seen_chunk_keys.add(key)
    selected_chunks.append(chunk)

  if current_ids:
    current_chunks = [chunk for chunk in chunks if str(chunk.get("message_id") or "") in current_ids]
    current_chunks.sort(key=lambda item: int(item.get("chunk_index") or 0))
    for chunk in current_chunks[:2]:
      append_chunk(chunk)
    for chunk in current_chunks[-1:]:
      append_chunk(chunk)

  for _score, chunk in scored_chunks:
    append_chunk(chunk)
    if len(selected_chunks) >= 6:
      break

  lines = [
    "本地完整对话历史检索：",
    "以下内容来自项目线程全文和分块索引，用于补足前端请求里的省略历史。",
  ]
  if long_messages:
    lines.append("长消息摘要：")
    for item in long_messages:
      role = _agent_thread_message_label(str(item.get("role", "")))
      message_id = str(item.get("id", ""))[:18]
      length = int(item.get("original_length") or 0)
      summary_text = _compact_text(str(item.get("summary", "") or ""), 360)
      lines.append(f"- {role}消息 {message_id}（{length} 字）：{summary_text}")

  if selected_chunks:
    lines.append("相关原文片段：")
    for chunk in selected_chunks:
      role = _agent_thread_message_label(str(chunk.get("role", "")))
      message_id = str(chunk.get("message_id", ""))[:18]
      chunk_index = int(chunk.get("chunk_index") or 0) + 1
      text = _compact_text(str(chunk.get("text", "") or ""), 900)
      lines.append(f"[{role}消息 {message_id} 片段 {chunk_index}]\n{text}")

  context = "\n".join(lines).strip()
  if len(context) <= max_chars:
    return context
  return f"{context[:max_chars].rstrip()}…"


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


def _knowledge_search_terms(text: str, limit: int = 160) -> list[str]:
  tokens = _knowledge_tokens(text).split()
  long_tokens = [item for item in tokens if len(item) >= 2]
  if long_tokens:
    return long_tokens[: max(1, limit)]
  return tokens[: max(1, min(limit, 32))]


def _knowledge_overlap_score(terms: list[str], content: str) -> float:
  normalized = re.sub(r"\s+", "", str(content or "")).lower()
  if not normalized:
    return 0.0
  hits = 0
  for term in terms[:120]:
    if term.lower() in normalized:
      hits += 1
  return float(hits)


def _knowledge_compact_query_text(value: str) -> str:
  return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or "").lower())


def _knowledge_query_matches_safe_text(query: str, content: str, terms: list[str]) -> bool:
  if not terms:
    return True
  normalized_query = _knowledge_compact_query_text(query)
  normalized_content = _knowledge_compact_query_text(content)
  if not normalized_content:
    return False
  if normalized_query and normalized_query in normalized_content:
    return True
  ascii_terms = [item for item in re.findall(r"[A-Za-z0-9_]{3,}", str(query or "").lower()) if item]
  if ascii_terms and any(item in normalized_content for item in ascii_terms):
    return True
  overlap = _knowledge_overlap_score(terms, content)
  if len(normalized_query) >= 4:
    return overlap >= 2
  return overlap > 0


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
  for source_label, mtime_ns, size in sorted(obsidian_source_signature_entries(project_dir)):
    digest.update(source_label.encode("utf-8"))
    digest.update(str(mtime_ns).encode("utf-8"))
    digest.update(str(size).encode("utf-8"))
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

  if normalized.startswith("obsidian:"):
    return normalized

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
) -> str:
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
    return ""

  rows_to_embed = [
    row for row in chunk_rows
    if existing_rows.get(row["chunk_id"]) != (row["content_hash"], embedding_signature, True)
  ]
  if not rows_to_embed:
    return ""

  try:
    vectors = embed_texts(
      settings,
      [row["content"] for row in rows_to_embed],
      task_name="project_knowledge_embedding",
    )
  except Exception as error:
    append_app_log(settings, f"project_knowledge_embedding skipped: {error}", level="ERROR")
    return str(error)

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
  return ""


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

  if source_key.startswith("obsidian:"):
    record = obsidian_note_record_for_source_key(project_dir, source_key)
    if record is None:
      return "Obsidian", "obsidian", []
    rows = _build_knowledge_chunk_rows(
      source_key=source_key,
      kind="obsidian",
      source="Obsidian",
      section=f"{record.summary.title} · {record.summary.relative_path}",
      content=record.content,
      created_at=record.summary.updated_at or created_at,
    )
    return "Obsidian", "obsidian", rows

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


def _rebuild_project_knowledge(project_dir: Path, target_chapters: int, settings: Settings) -> dict[str, object]:
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

    obsidian_records, _obsidian_skipped, _obsidian_warnings = collect_obsidian_note_records(project_dir)
    for record in obsidian_records:
      connection.execute(
        "INSERT INTO knowledge_sources (source_key, source, kind, created_at) VALUES (?, ?, ?, ?)",
        (record.summary.source_key, "Obsidian", "obsidian", record.summary.updated_at or now),
      )
      chunk_rows.extend(
        _build_knowledge_chunk_rows(
          source_key=record.summary.source_key,
          kind="obsidian",
          source="Obsidian",
          section=f"{record.summary.title} · {record.summary.relative_path}",
          content=record.content,
          created_at=record.summary.updated_at or now,
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
    embedding_error = _sync_knowledge_vectors(settings, connection, chunk_rows, embedding_signature)
    _set_knowledge_state(connection, "source_signature", _knowledge_source_signature(project_dir, target_chapters))
    _set_knowledge_state(connection, "embedding_signature", embedding_signature)
    _set_knowledge_state(connection, "schema_version", _KNOWLEDGE_SCHEMA_VERSION)
    _set_knowledge_state(connection, "indexed_at", now)
    connection.commit()
    return {
      "status": "partial" if embedding_error else "completed",
      "chunk_count": len(chunk_rows),
      "embedding_signature": embedding_signature,
      "embedding_error": embedding_error,
    }
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


def _knowledge_result_limit(limit: int) -> int:
  try:
    raw_limit = int(limit or 1)
  except (TypeError, ValueError):
    raw_limit = 1
  return max(1, min(raw_limit, 20))


def _chapter_filtered_search_limit(limit: int) -> int:
  return max(
    _KNOWLEDGE_SEMANTIC_CANDIDATE_MIN,
    min(max(1, limit) * 8, _KNOWLEDGE_CHAPTER_FILTER_RESULT_CAP),
  )


def _keyword_search_project_knowledge(connection: sqlite3.Connection, query: str, limit: int) -> list[dict[str, object]]:
  normalized = query.strip()
  if not normalized:
    return []
  search_limit = max(1, min(limit, _KNOWLEDGE_SEMANTIC_CANDIDATE_CAP))

  if _knowledge_supports_fts(connection):
    tokens = _knowledge_search_terms(normalized)
    fts_query = " OR ".join(tokens) if tokens else normalized
    rows = connection.execute(
      """
      SELECT knowledge_chunks.chunk_id, knowledge_chunks.source_key, knowledge_chunks.source,
             knowledge_chunks.section, knowledge_chunks.content, bm25(knowledge_chunks_fts) AS score
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
        "source_key": str(source_key),
        "source": str(source),
        "section": str(section),
        "content": str(content),
        "score": (float(-score) if isinstance(score, (int, float)) else 0.0) + _knowledge_overlap_score(tokens, str(content)),
        "match_type": "keyword",
      }
      for chunk_id, source_key, source, section, content, score in rows
    ]

  like_query = f"%{normalized}%"
  rows = connection.execute(
    """
    SELECT chunk_id, source_key, source, section, content
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
      "source_key": str(source_key),
      "source": str(source),
      "section": str(section),
      "content": str(content),
      "score": 0.0,
      "match_type": "keyword",
    }
    for chunk_id, source_key, source, section, content in rows
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
    SELECT knowledge_chunks.chunk_id, knowledge_chunks.source_key, knowledge_chunks.source,
           knowledge_chunks.section, knowledge_chunks.content, knowledge_vectors.vector_blob,
           knowledge_vectors.vector_json, knowledge_vectors.vector_norm
    FROM knowledge_vectors
    JOIN knowledge_chunks ON knowledge_chunks.chunk_id = knowledge_vectors.chunk_id
    {where_sql}
    """,
    params,
  ).fetchall()

  scored: list[dict[str, object]] = []
  for chunk_id, source_key, source, section, content, vector_blob, vector_json, vector_norm in rows:
    vector = _vector_from_storage(vector_blob, vector_json)
    if not vector:
      continue
    similarity = _cosine_similarity_values(query_vector, vector, query_norm, float(vector_norm or 0))
    if similarity <= 0:
      continue
    scored.append(
      {
        "chunk_id": str(chunk_id),
        "source_key": str(source_key),
        "source": str(source),
        "section": str(section),
        "content": str(content),
        "score": similarity,
        "match_type": "semantic",
      }
    )

  scored.sort(key=lambda item: float(item["score"]), reverse=True)
  return scored[: max(1, min(limit, 20))]


def _search_project_knowledge(
  settings: Settings,
  project_dir: Path,
  query: str,
  limit: int = 8,
  *,
  include_semantic: bool = True,
) -> list[KnowledgeSearchResult]:
  normalized = query.strip()
  if not normalized:
    return []

  db_path = _knowledge_db_path(project_dir)
  if not db_path.exists():
    return []

  search_limit = max(1, min(limit, _KNOWLEDGE_SEMANTIC_CANDIDATE_CAP))
  connection = sqlite3.connect(db_path)
  try:
    keyword_hits = _keyword_search_project_knowledge(connection, normalized, _knowledge_candidate_limit(search_limit))
    semantic_hits = (
      _semantic_search_project_knowledge(
        settings,
        connection,
        normalized,
        search_limit,
        candidate_chunk_ids=[str(item["chunk_id"]) for item in keyword_hits] if keyword_hits else None,
      )
      if include_semantic
      else []
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
      source_key=str(item.get("source_key") or ""),
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

  search_limit = max(1, min(limit, _KNOWLEDGE_CHAPTER_FILTER_RESULT_CAP))
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


def _filter_obsidian_evidence_hits_for_chapter(
  project_dir: Path,
  hits: list[dict[str, object]],
  query: str,
  chapter_index: int = 0,
) -> list[dict[str, object]]:
  try:
    target_chapter = int(chapter_index or 0)
  except (TypeError, ValueError):
    target_chapter = 0
  if target_chapter <= 0:
    return hits

  records = scoped_obsidian_note_records_for_chapter(project_dir, target_chapter)
  record_by_source_key = {
    record.summary.source_key: record
    for record in records
    if record.summary.source_key
  }
  query_terms = _knowledge_search_terms(query)
  filtered: list[dict[str, object]] = []
  for hit in hits:
    if str(hit.get("source") or "").strip() != "Obsidian":
      filtered.append(hit)
      continue
    record = record_by_source_key.get(str(hit.get("source_key") or "").strip())
    if record is None:
      continue
    safe_text = record.content or record.summary.preview or record.summary.title
    if query_terms and not _knowledge_query_matches_safe_text(query, safe_text, query_terms):
      continue
    safe_hit = dict(hit)
    safe_hit["content"] = safe_text
    safe_hit["section"] = f"{record.summary.title} · {record.summary.relative_path}"
    filtered.append(safe_hit)
  return filtered


def _filter_obsidian_search_results_for_chapter(
  project_dir: Path,
  hits: list[KnowledgeSearchResult],
  query: str,
  chapter_index: int = 0,
) -> list[KnowledgeSearchResult]:
  try:
    target_chapter = int(chapter_index or 0)
  except (TypeError, ValueError):
    target_chapter = 0
  if target_chapter <= 0:
    return hits

  records = scoped_obsidian_note_records_for_chapter(project_dir, target_chapter)
  record_by_source_key = {
    record.summary.source_key: record
    for record in records
    if record.summary.source_key
  }
  query_terms = _knowledge_search_terms(query)
  filtered: list[KnowledgeSearchResult] = []
  for hit in hits:
    if str(hit.source or "").strip() != "Obsidian":
      filtered.append(hit)
      continue
    record = record_by_source_key.get(str(hit.source_key or "").strip())
    if record is None:
      continue
    safe_text = record.content or record.summary.preview or record.summary.title
    if query_terms and not _knowledge_query_matches_safe_text(query, safe_text, query_terms):
      continue
    safe_preview = _compact_text(record.summary.preview or record.content or "", limit=180)
    if not safe_preview:
      safe_preview = f"Obsidian 笔记：{record.summary.title or record.summary.relative_path}"
    filtered.append(
      hit.model_copy(
        update={
          "section": f"{record.summary.title} · {record.summary.relative_path}",
          "preview": safe_preview,
        }
      )
    )
  return filtered


def _is_character_candidate(name: str) -> bool:
  cleaned = name.strip().strip("：:，,。；;、·-—()（）[]【】")
  if cleaned in _ROLE_CHARACTER_TOKENS:
    return True
  if len(cleaned) < 2 or len(cleaned) > 8:
    return False
  if cleaned in _CHARACTER_NAME_BLACKLIST:
    return False
  if any(char in _NON_CHARACTER_NAME_CHARS for char in cleaned):
    return False
  if any(fragment in cleaned for fragment in _NON_CHARACTER_NAME_FRAGMENTS):
    return False
  if len(cleaned) >= 3 and any(cleaned.endswith(suffix) for suffix in _NON_CHARACTER_ENTITY_SUFFIX_BLACKLIST):
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
      if isinstance(item, dict):
        name = _json_character_name(item)
        if name:
          sections[name].extend(_json_character_lines(item))
          continue
      for name, lines in _collect_json_character_sections(item).items():
        sections[name].extend(lines)
    return sections

  if isinstance(container, dict):
    name = _json_character_name(container)
    if name:
      sections[name].extend(_json_character_lines(container))
      return sections
    for key, value in container.items():
      if isinstance(key, str) and _is_character_candidate(key) and isinstance(value, dict):
        sections[key.strip()].extend(_json_character_lines(value))
        continue
      if isinstance(value, (dict, list)):
        for nested_name, lines in _collect_json_character_sections(value).items():
          sections[nested_name].extend(lines)
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


def _character_heading_candidates(line: str) -> list[str]:
  normalized = re.sub(r"^[#*\-\d\.\s、）\)]+", "", line).strip()
  if not normalized:
    return []

  if ":" in normalized or "：" in normalized:
    left, right = re.split(r"[:：]", normalized, maxsplit=1)
    candidate = left.strip()
    if _is_character_candidate(candidate) and right.strip():
      return [candidate]
    split_candidates = [
      item.strip()
      for item in re.split(r"[、/／与及和]+", candidate)
      if _is_character_candidate(item.strip())
    ]
    if split_candidates and right.strip():
      return _ordered_unique(split_candidates)

  if line.lstrip().startswith("#") and _is_character_candidate(normalized):
    return [normalized]

  if normalized in _ROLE_CHARACTER_TOKENS:
    return [normalized]

  return []


def _extract_character_sections(text: str) -> dict[str, list[str]]:
  sections: dict[str, list[str]] = defaultdict(list)
  current_characters: list[str] = []

  for name, lines in _extract_json_character_sections(text).items():
    sections[name].extend(lines)

  for raw_line in text.splitlines():
    line = raw_line.strip()
    if not line:
      continue

    candidates = _character_heading_candidates(line)
    if candidates:
      current_characters = candidates

    for current_character in current_characters:
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
  if (
    len(cleaned) == 3
    and cleaned[-1] in _DISCOVERED_CHARACTER_TRAILING_CONTEXT_CHARS
    and cleaned[:2] not in _CHARACTER_NAME_BLACKLIST
    and not any(fragment in cleaned for fragment in _NON_CHARACTER_NAME_FRAGMENTS)
    and not any(fragment in cleaned[:2] for fragment in _NON_CHARACTER_NAME_FRAGMENTS)
  ):
    cleaned = cleaned[:2]
  if len(cleaned) < 2 or len(cleaned) > 4:
    return ""
  if not re.fullmatch(r"[\u4e00-\u9fff]+", cleaned):
    return ""
  if (
    cleaned in _CHARACTER_NAME_BLACKLIST
    or cleaned in _DISCOVERED_CHARACTER_BLACKLIST
    or cleaned in _DISCOVERED_CHARACTER_EXACT_BLACKLIST
  ):
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


def _is_cjk_char(value: str) -> bool:
  return bool(value and re.fullmatch(r"[\u4e00-\u9fff]", value))


def _is_name_boundary_char(value: str) -> bool:
  return not value or not re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9]", value)


def _is_sentence_boundary_char(value: str) -> bool:
  return not value or value in "。！？!?；;，,、\n\r\t （([{【“‘\"'"


def _has_person_left_context(source: str, start: int) -> bool:
  left = source[max(0, start - 8) : start]
  return any(left.endswith(token) for token in _DISCOVERED_NAME_LEFT_CONTEXT_TOKENS)


def _discovered_name_context_score(source: str, start: int, end: int, candidate: str) -> int:
  previous_char = source[start - 1] if start > 0 else ""
  next_char = source[end] if end < len(source) else ""
  has_left_boundary = start == 0 or _is_name_boundary_char(previous_char)
  has_left_person_context = previous_char in _DISCOVERED_NAME_LEFT_CONTEXT_CHARS or _has_person_left_context(source, start)
  if not has_left_boundary and not has_left_person_context:
    return 0

  score = 0
  if has_left_person_context:
    score += 3
  elif _is_sentence_boundary_char(previous_char):
    score += 2
  elif has_left_boundary:
    score += 1

  if not next_char or _is_name_boundary_char(next_char):
    score += 2
  elif next_char in _DISCOVERED_NAME_RIGHT_CONTEXT_CHARS:
    score += 2
  elif has_left_person_context and _is_cjk_char(next_char):
    score += 1
  else:
    return 0

  if len(candidate) >= 3:
    score += 1
  return score


def _should_shorten_discovered_name(source: str, short_end: int) -> bool:
  if short_end >= len(source):
    return False
  next_char = source[short_end]
  if next_char in _DISCOVERED_NAME_TRAILING_CONTEXT_CHARS:
    return True
  return any(source.startswith(prefix, short_end) for prefix in _DISCOVERED_NAME_TRAILING_CONTEXT_PREFIXES)


def _candidate_names_from_position(source: str, start: int, surname: str) -> list[tuple[str, int]]:
  candidates: list[tuple[str, int]] = []
  surname_len = len(surname)

  for given_len in range(2, 0, -1):
    end = start + surname_len + given_len
    if end > len(source):
      continue

    raw_candidate = source[start:end]
    candidate_end = end
    if given_len > 1:
      short_end = start + surname_len + 1
      if _should_shorten_discovered_name(source, short_end) or raw_candidate[-1] in _DISCOVERED_NAME_TRAILING_CONTEXT_CHARS:
        raw_candidate = source[start:short_end]
        candidate_end = short_end

    candidate = _normalize_discovered_character_name(raw_candidate)
    if not candidate:
      continue

    candidate_end = start + len(candidate)
    score = _discovered_name_context_score(source, start, candidate_end, candidate)
    if score > 0:
      candidates.append((candidate, score))
      break

  return candidates


def _candidate_character_names(text: str) -> list[str]:
  return [name for name, _score in _candidate_character_evidence(text)]


def _candidate_character_evidence(text: str) -> list[tuple[str, int]]:
  evidence: list[tuple[str, int]] = []
  source = text or ""
  for index, char in enumerate(source):
    compound_matched = False
    for surname in _COMPOUND_SURNAMES:
      if source.startswith(surname, index):
        evidence.extend(_candidate_names_from_position(source, index, surname))
        compound_matched = True
        break
    if compound_matched:
      continue
    if char in _COMMON_SINGLE_CHAR_SURNAMES:
      evidence.extend(_candidate_names_from_position(source, index, char))
  return evidence


def _candidate_character_context_has_person_evidence(source: str, start: int, candidate: str) -> bool:
  end = start + len(candidate)
  left_context = source[max(0, start - 8):start]
  right_context = source[end:end + 12]
  return bool(
    _DISCOVERED_CHARACTER_CONTEXT_PATTERN.search(right_context)
    or _DISCOVERED_CHARACTER_LEFT_CONTEXT_PATTERN.search(left_context)
  )


def _character_review_cache_path(project_dir: Path) -> Path:
  return project_dir / _APP_STATE_DIRNAME / "story_overview_character_review.json"


def _story_entity_review_cache_path(project_dir: Path) -> Path:
  return project_dir / _APP_STATE_DIRNAME / "story_overview_entity_review.json"


def _character_review_model_signature(settings: Settings) -> str:
  config, api_key = _auxiliary_model_enabled(settings)
  if config is None:
    return "auxiliary-model:not-configured"
  return hashlib.sha1(
    json.dumps(
      {
        "base_url": config.base_url.strip(),
        "model_name": config.model_name.strip(),
        "api_key": hashlib.sha1(api_key.encode("utf-8")).hexdigest() if api_key else "",
        "temperature": 0,
      },
      ensure_ascii=False,
      sort_keys=True,
    ).encode("utf-8")
  ).hexdigest()


def _character_review_source_signature(
  texts: list[str],
  candidates: list[str],
  model_signature: str,
) -> str:
  payload = {
    "version": _CHARACTER_REVIEW_CACHE_VERSION,
    "model_signature": model_signature,
    "candidates": candidates,
    "texts": [hashlib.sha1((text or "").encode("utf-8")).hexdigest() for text in texts],
  }
  return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _story_entity_review_source_signature(
  texts: list[str],
  candidates_by_kind: dict[str, list[str]],
  model_signature: str,
) -> str:
  payload = {
    "version": _ENTITY_REVIEW_CACHE_VERSION,
    "model_signature": model_signature,
    "candidates_by_kind": candidates_by_kind,
    "texts": [hashlib.sha1((text or "").encode("utf-8")).hexdigest() for text in texts],
  }
  return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _has_character_review_model_config(settings: Settings) -> bool:
  config, api_key = _auxiliary_model_enabled(settings)
  return config is not None and bool(api_key)


def _character_candidate_evidence_items(
  texts: list[str],
  candidates: list[str],
  *,
  limit_per_candidate: int = 3,
) -> list[dict[str, object]]:
  items: list[dict[str, object]] = []
  for candidate in candidates:
    snippets: list[str] = []
    for text in texts:
      source = text or ""
      if candidate not in source:
        continue
      for sentence in _split_sentences(source):
        if candidate not in sentence:
          continue
        snippets.append(_compact_text(sentence, limit=140))
        if len(snippets) >= limit_per_candidate:
          break
      if len(snippets) >= limit_per_candidate:
        break
    items.append(
      {
        "name": candidate,
        "evidence": _ordered_unique(snippets)[:limit_per_candidate],
      }
    )
  return items


def _story_entity_candidate_evidence_items(
  texts: list[str],
  entity_store: dict[str, dict[str, dict]],
  *,
  limit_per_candidate: int = 3,
) -> list[dict[str, object]]:
  items: list[dict[str, object]] = []
  for kind in _ENTITY_REVIEW_KINDS:
    for name, payload in entity_store.get(kind, {}).items():
      snippets: list[str] = []
      for text in texts:
        source = text or ""
        if name not in source:
          continue
        for sentence in _split_sentences(source):
          if name not in sentence:
            continue
          snippets.append(_compact_text(sentence, limit=160))
          if len(snippets) >= limit_per_candidate:
            break
        if len(snippets) >= limit_per_candidate:
          break

      items.append(
        {
          "kind": kind,
          "label": _ENTITY_REVIEW_LABELS[kind],
          "name": name,
          "summary": str(payload.get("summary", "")),
          "related_characters": sorted(str(item) for item in payload.get("related_characters", set())),
          "chapter_indexes": sorted(int(item) for item in payload.get("chapter_indexes", set())),
          "evidence": _ordered_unique(snippets)[:limit_per_candidate],
        }
      )
  return items


def _json_object_from_model_text(text: str) -> dict[str, object] | None:
  stripped = (text or "").strip()
  if stripped.startswith("```"):
    lines = stripped.splitlines()
    if len(lines) >= 3 and lines[-1].strip() == "```":
      stripped = "\n".join(lines[1:-1]).strip()

  try:
    payload = json.loads(stripped)
  except json.JSONDecodeError:
    payload = None
  if isinstance(payload, dict):
    return payload

  start = stripped.find("{")
  end = stripped.rfind("}")
  if start == -1 or end == -1 or end <= start:
    return None

  try:
    payload = json.loads(stripped[start : end + 1])
  except json.JSONDecodeError:
    return None
  return payload if isinstance(payload, dict) else None


def _string_list_from_model_payload(value: object, allowed: set[str]) -> list[str]:
  if not isinstance(value, list):
    return []
  return _ordered_unique([str(item).strip() for item in value if str(item).strip() in allowed])


def _rejected_entities_from_model_payload(
  value: object,
  candidates_by_kind: dict[str, list[str]],
) -> dict[str, set[str]]:
  rejected: dict[str, set[str]] = {kind: set() for kind in _ENTITY_REVIEW_KINDS}
  if not isinstance(value, list):
    return rejected

  for item in value:
    if not isinstance(item, dict):
      continue
    kind = str(item.get("kind", "")).strip()
    name = str(item.get("name", "")).strip()
    if kind in rejected and name in set(candidates_by_kind.get(kind, [])):
      rejected[kind].add(name)
  return rejected


def _valid_story_entities_from_model_payload(
  payload: dict[str, object],
  candidates_by_kind: dict[str, list[str]],
) -> dict[str, set[str]]:
  valid_payload = payload.get("valid_entities")
  rejected_by_kind = _rejected_entities_from_model_payload(payload.get("rejected"), candidates_by_kind)
  if not isinstance(valid_payload, dict) and not any(rejected_by_kind.values()):
    raise RuntimeError("模型世界要素复核没有返回可用候选")

  valid_entities: dict[str, set[str]] = {}
  has_reviewed_item = False
  for kind in _ENTITY_REVIEW_KINDS:
    candidates = candidates_by_kind.get(kind, [])
    allowed = set(candidates)
    if isinstance(valid_payload, dict) and kind in valid_payload:
      names = _string_list_from_model_payload(valid_payload.get(kind), allowed)
      valid_entities[kind] = set(names)
      has_reviewed_item = True
      continue

    rejected = rejected_by_kind.get(kind, set())
    if rejected:
      valid_entities[kind] = allowed - rejected
      has_reviewed_item = True
    else:
      valid_entities[kind] = allowed

  if not has_reviewed_item:
    raise RuntimeError("模型世界要素复核没有返回可用候选")
  return valid_entities


def _model_review_character_candidates(
  settings: Settings,
  project_dir: Path,
  texts: list[str],
  candidates: list[str],
  *,
  allow_model_call: bool = False,
) -> list[str]:
  ordered_candidates = _ordered_unique(candidates)
  if not ordered_candidates:
    return ordered_candidates

  model_signature = _character_review_model_signature(settings)
  source_signature = _character_review_source_signature(texts, ordered_candidates, model_signature)
  cache_path = _character_review_cache_path(project_dir)
  cached = read_json(cache_path, None)
  if (
    isinstance(cached, dict)
    and cached.get("version") == _CHARACTER_REVIEW_CACHE_VERSION
    and cached.get("source_signature") == source_signature
    and isinstance(cached.get("characters"), list)
  ):
    return _string_list_from_model_payload(cached.get("characters"), set(ordered_candidates))

  if not allow_model_call or not _has_character_review_model_config(settings):
    return ordered_candidates

  evidence_items = _character_candidate_evidence_items(texts, ordered_candidates)
  messages = [
    {
      "role": "system",
      "content": (
        "你是中文小说资料整理助手，只判断候选词是不是人物。"
        "必须只输出 JSON，不要解释。"
        "JSON 字段固定为 characters、non_characters、aliases。"
        "只能从候选词里选择，不要新增候选外的人名。"
        "人物包括真实历史人物、小说角色和明确人物化的化名；"
        "制度、地点、组织、技能、称号、事件、抽象概念和普通短语都归入 non_characters。"
      ),
    },
    {
      "role": "user",
      "content": json.dumps(
        {
          "candidates": ordered_candidates,
          "evidence": evidence_items,
          "output_example": {
            "characters": ["石虎"],
            "non_characters": ["方式", "封王"],
            "aliases": {"石虎": ["石季龙"]},
          },
        },
        ensure_ascii=False,
      ),
    },
  ]

  try:
    content = _invoke_auxiliary_model(
      settings,
      messages,
      task_name="story_overview_character_review",
      temperature=0,
      max_tokens=1200,
    )
    payload = _json_object_from_model_text(content)
    if payload is None:
      raise RuntimeError("模型人物复核返回的不是合法 JSON")

    allowed = set(ordered_candidates)
    reviewed_characters = _string_list_from_model_payload(payload.get("characters"), allowed)
    reviewed_non_characters = _string_list_from_model_payload(payload.get("non_characters"), allowed)
    if not reviewed_characters and not reviewed_non_characters:
      raise RuntimeError("模型人物复核没有返回可用候选")

    atomic_write_json(
      cache_path,
      {
        "version": _CHARACTER_REVIEW_CACHE_VERSION,
        "source_signature": source_signature,
        "model_signature": model_signature,
        "characters": reviewed_characters,
        "non_characters": reviewed_non_characters,
        "aliases": payload.get("aliases") if isinstance(payload.get("aliases"), dict) else {},
      },
    )
    return reviewed_characters
  except Exception as error:
    append_app_log(settings, f"story_overview_character_review failed: {error}")
    return ordered_candidates


def _model_review_story_entities(
  settings: Settings,
  project_dir: Path,
  texts: list[str],
  entity_store: dict[str, dict[str, dict]],
  *,
  allow_model_call: bool = False,
) -> dict[str, set[str]]:
  candidates_by_kind = {
    kind: _ordered_unique(list(entity_store.get(kind, {}).keys()))
    for kind in _ENTITY_REVIEW_KINDS
  }
  default_entities = {kind: set(candidates) for kind, candidates in candidates_by_kind.items()}
  if not any(candidates_by_kind.values()):
    return default_entities

  model_signature = _character_review_model_signature(settings)
  source_signature = _story_entity_review_source_signature(texts, candidates_by_kind, model_signature)
  cache_path = _story_entity_review_cache_path(project_dir)
  cached = read_json(cache_path, None)
  if (
    isinstance(cached, dict)
    and cached.get("version") == _ENTITY_REVIEW_CACHE_VERSION
    and cached.get("source_signature") == source_signature
    and isinstance(cached.get("valid_entities"), dict)
  ):
    try:
      return _valid_story_entities_from_model_payload(cached, candidates_by_kind)
    except RuntimeError:
      pass

  if not allow_model_call or not _has_character_review_model_config(settings):
    return default_entities

  evidence_items = _story_entity_candidate_evidence_items(texts, entity_store)
  messages = [
    {
      "role": "system",
      "content": (
        "你是中文小说架构总览审核助手，只判断候选词是不是对应类别的世界要素。"
        "必须只输出 JSON，不要解释。"
        "JSON 字段固定为 valid_entities、rejected。"
        "只能从候选词里选择，不要新增候选外的词。"
        "事件是已经发生或即将推动情节的动作、决定、冲突、发现或关系变化；章节标题、场景名、纯环境描写和资料格式噪声不是事件。"
        "地点是可发生剧情的具体空间、建筑、城市、区域；章节提示、句子片段、比喻和泛称不是地点。"
        "组织/势力是有名字的机构、派系、政权、家族、公司、门派；泛称、比较句和句子片段不是组织。"
        "道具是剧情中可被持有、寻找、使用或争夺的具体物件；抽象概念和比喻不是道具。"
        "技能是人物明确具备或使用的能力；世界规则、法术体系名、抽象设定和泛称不是技能。"
      ),
    },
    {
      "role": "user",
      "content": json.dumps(
        {
          "candidates_by_kind": candidates_by_kind,
          "evidence": evidence_items,
          "output_example": {
            "valid_entities": {
              "events": ["石季龙回到邺城"],
              "locations": ["邺城"],
              "organizations": ["龙城燕庭"],
              "props": ["海内图"],
              "skills": ["钵中见城"],
            },
            "rejected": [
              {"kind": "organizations", "name": "国家像宗门", "reason": "比较句"},
              {"kind": "locations", "name": "章尾邺城", "reason": "章节提示"},
              {"kind": "events", "name": "冻土如铁", "reason": "环境描写"},
            ],
          },
        },
        ensure_ascii=False,
      ),
    },
  ]

  try:
    content = _invoke_auxiliary_model(
      settings,
      messages,
      task_name="story_overview_entity_review",
      temperature=0,
      max_tokens=1800,
    )
    payload = _json_object_from_model_text(content)
    if payload is None:
      raise RuntimeError("模型世界要素复核返回的不是合法 JSON")

    valid_entities = _valid_story_entities_from_model_payload(payload, candidates_by_kind)
    rejected = payload.get("rejected") if isinstance(payload.get("rejected"), list) else []
    atomic_write_json(
      cache_path,
      {
        "version": _ENTITY_REVIEW_CACHE_VERSION,
        "source_signature": source_signature,
        "model_signature": model_signature,
        "valid_entities": {
          kind: [name for name in candidates_by_kind[kind] if name in valid_entities[kind]]
          for kind in _ENTITY_REVIEW_KINDS
        },
        "rejected": rejected,
      },
    )
    return valid_entities
  except Exception as error:
    append_app_log(settings, f"story_overview_entity_review failed: {error}")
    return default_entities


def _filter_story_entity_values(items: list[str], allowed: set[str]) -> list[str]:
  return _ordered_unique([item for item in items if item in allowed])


def _apply_story_entity_review(
  entity_store: dict[str, dict[str, dict]],
  character_store: dict[str, dict],
  valid_entities: dict[str, set[str]],
) -> None:
  for kind in _ENTITY_REVIEW_KINDS:
    allowed = valid_entities.get(kind, set(entity_store.get(kind, {}).keys()))
    entity_store[kind] = {
      name: payload
      for name, payload in entity_store.get(kind, {}).items()
      if name in allowed
    }

  for store in character_store.values():
    for kind in _ENTITY_REVIEW_KINDS:
      allowed = valid_entities.get(kind, set())
      store[kind] = _filter_story_entity_values(store.get(kind, []), allowed)

    reviewed_timeline: list[CharacterTimelineEntry] = []
    for entry in store.get("timeline", []):
      reviewed_timeline.append(
        entry.model_copy(
          update={
            kind: _filter_story_entity_values(getattr(entry, kind), valid_entities.get(kind, set()))
            for kind in _ENTITY_REVIEW_KINDS
          }
        )
      )
    store["timeline"] = reviewed_timeline


def _discover_character_names(texts: list[str], limit: int = 24) -> list[str]:
  counts: dict[str, int] = {}
  evidence_scores: dict[str, int] = {}
  source_indexes: dict[str, set[int]] = defaultdict(set)
  first_seen: dict[str, tuple[int, int]] = {}

  for text_index, text in enumerate(texts):
    for match_index, (candidate, score) in enumerate(_candidate_character_evidence(text)):
      counts[candidate] = counts.get(candidate, 0) + 1
      evidence_scores[candidate] = evidence_scores.get(candidate, 0) + score
      source_indexes[candidate].add(text_index)
      first_seen.setdefault(candidate, (text_index, match_index))

  filtered = [
    name
    for name, count in counts.items()
    if count >= 2 and evidence_scores.get(name, 0) >= (6 if len(name) >= 3 else 8)
  ]
  filtered.sort(
    key=lambda name: (
      -len(source_indexes[name]),
      -evidence_scores[name],
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


def _is_descriptive_chapter_sentence(sentence: str) -> bool:
  compact = sentence.strip()
  if not compact:
    return True
  if "像" in compact and not re.search(r"(?:说|问|答|听见|看见|发现|进入|回到|找到|拿到|握住|打开|闯进)", compact):
    return True
  return False


def _chapter_event_summary(sentences: list[str], character_names: list[str]) -> str:
  for sentence in sentences:
    if any(name and name in sentence for name in character_names):
      return _compact_text(sentence, limit=90)

  for sentence in sentences:
    if _is_descriptive_chapter_sentence(sentence):
      continue
    if _CHAPTER_EVENT_ACTION_PATTERN.search(sentence):
      return _compact_text(sentence, limit=90)

  return ""


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
    if len(keyword) == 1:
      continue
    if keyword not in source_text:
      continue
    if any(item.endswith(keyword) and len(item) > len(keyword) for item in expanded_matches):
      continue
    expanded_matches.append(keyword)

  return expanded_matches


def _location_match_is_inside_organization(source_text: str, match: re.Match[str]) -> bool:
  following_text = source_text[match.end(1):]
  return any(following_text.startswith(suffix) for suffix in _LOCATION_ORGANIZATION_FOLLOWING_SUFFIXES)


def _is_location_candidate(name: str) -> bool:
  if not name or name in _LOCATION_NAME_BLACKLIST:
    return False
  if name.startswith(("一", "某", "这", "那", "每")):
    return False
  return not any(fragment in name for fragment in _LOCATION_NAME_BLACKLIST_FRAGMENTS)


def _extract_locations(text: str) -> list[str]:
  matches = []
  for item in _LOCATION_PATTERN.finditer(text):
    if _location_match_is_inside_organization(text, item):
      continue
    normalized = _normalize_entity_name(item.group(1), _LOCATION_KEYWORDS)
    if _is_location_candidate(normalized):
      matches.append(normalized)
  matches = _expand_entity_keywords(text, matches, _LOCATION_KEYWORDS)
  return _ordered_unique([item for item in matches if _is_location_candidate(item)])


def _extract_organizations(text: str) -> list[str]:
  matches = [
    _normalize_entity_name(item, _ORGANIZATION_KEYWORDS)
    for item in _ORGANIZATION_PATTERN.findall(text)
  ]
  matches = _expand_entity_keywords(text, matches, _ORGANIZATION_KEYWORDS)
  return _ordered_unique([item for item in matches if _is_organization_candidate(item)])


def _is_organization_candidate(name: str) -> bool:
  if not name or name in _ORGANIZATION_GENERIC_NAMES:
    return False
  return not any(fragment in name for fragment in _ORGANIZATION_NAME_BLACKLIST_FRAGMENTS)


def _prop_appears_as_simile(source: str, keyword: str) -> bool:
  pattern = re.compile(_PROP_SIMILE_PATTERN_TEMPLATE.format(keyword=re.escape(keyword)))
  return bool(pattern.search(source))


def _extract_props(text: str) -> list[str]:
  source = text or ""
  matches = []
  for keyword in _PROP_KEYWORDS:
    if keyword in _SINGLE_CHARACTER_PROP_KEYWORDS:
      pattern = _PROP_CONTEXT_PATTERNS.get(keyword)
      if pattern is not None and pattern.search(source):
        matches.append(keyword)
      continue
    if keyword in source:
      if _prop_appears_as_simile(source, keyword):
        continue
      matches.append(keyword)
  return _ordered_unique(matches)


def _normalize_skill_name(name: str) -> str:
  current = name.strip().strip("，,。！？!?；;：:、·“”‘’\"'（）()[]【】《》")
  for token in _SKILL_CONTEXT_TOKENS:
    if token in current:
      candidate = current.rsplit(token, maxsplit=1)[-1].strip()
      if candidate:
        current = candidate
        break
  current = re.sub(r"^(?:技能|能力|特长|绝活|本领|擅长|善于|精通|熟悉|掌握|精于|最会|很会)", "", current)
  current = re.sub(r"(?:能力|本事|技巧|的人|方面)$", "", current)
  current = current.strip("，,。！？!?；;：:、·“”‘’\"'（）()[]【】《》")
  if not current or current in _SKILL_BLACKLIST:
    return ""
  if any(fragment in current for fragment in _SKILL_BLACKLIST_FRAGMENTS):
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


_STRUCTURED_OVERVIEW_FIELD_ALIASES = {
  "current_state": {
    "current_state",
    "initial_state",
    "state",
    "当前状态",
    "初始状态",
    "状态",
    "现状",
    "处境",
  },
  "relationships": {
    "relationships",
    "relationship",
    "relations",
    "关联人物",
    "人物关系",
    "关系",
  },
  "events": {
    "events",
    "event",
    "plot_events",
    "关键事件",
    "事件",
  },
  "locations": {
    "locations",
    "location",
    "places",
    "place",
    "地点",
    "场所",
    "场地",
  },
  "props": {
    "props",
    "items",
    "key_items",
    "objects",
    "道具",
    "物件",
    "关键物件",
    "线索物",
  },
  "skills": {
    "skills",
    "skill",
    "ability",
    "abilities",
    "能力",
    "技能",
    "本领",
  },
  "scenes": {
    "scenes",
    "scene",
    "beats",
    "场景",
    "场次",
  },
  "organizations": {
    "organizations",
    "organization",
    "factions",
    "faction",
    "forces",
    "force",
    "组织",
    "势力",
    "机构",
    "阵营",
  },
}
_STRUCTURED_OVERVIEW_KEY_TO_FIELD = {
  key: field
  for field, keys in _STRUCTURED_OVERVIEW_FIELD_ALIASES.items()
  for key in keys
}
_STRUCTURED_OVERVIEW_FIELD_PATTERN = re.compile(
  r"(" + "|".join(re.escape(key) for key in sorted(_STRUCTURED_OVERVIEW_KEY_TO_FIELD, key=len, reverse=True)) + r")\s*[：:]"
)
_STRUCTURED_SPLIT_PATTERN = re.compile(r"[；;\n]+")
_STRUCTURED_ENTITY_NAME_KEYS = {
  "events": ("name", "title", "event", "事件", "关键事件", "标题"),
  "locations": ("name", "title", "location", "place", "地点", "场所", "标题"),
  "props": ("name", "title", "prop", "item", "道具", "物件", "标题"),
  "skills": ("name", "title", "skill", "ability", "技能", "能力", "标题"),
  "scenes": ("name", "title", "scene", "beat", "场景", "场次", "标题"),
  "organizations": ("name", "title", "organization", "faction", "force", "组织", "势力", "机构", "标题"),
}
_STRUCTURED_RELATED_CHARACTER_KEYS = ("related_characters", "characters", "人物", "关联人物", "角色")
_STRUCTURED_SUMMARY_KEYS = ("summary", "description", "detail", "goal", "hook", "content", "说明", "摘要", "目标", "钩子", "状态")


def _structured_field_map(lines: list[str]) -> dict[str, list[str]]:
  text = "\n".join(str(item or "") for item in lines if str(item or "").strip())
  if not text:
    return {}
  matches = list(_STRUCTURED_OVERVIEW_FIELD_PATTERN.finditer(text))
  fields: dict[str, list[str]] = defaultdict(list)
  for index, match in enumerate(matches):
    key = match.group(1)
    field = _STRUCTURED_OVERVIEW_KEY_TO_FIELD.get(key)
    if not field:
      continue
    next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
    value = text[match.end() : next_start].strip(" \t\r\n，,；;。")
    if value:
      fields[field].append(value)
  return fields


def _structured_items(values: list[str]) -> list[str]:
  items: list[str] = []
  for value in values:
    for piece in _STRUCTURED_SPLIT_PATTERN.split(str(value or "")):
      cleaned = piece.strip(" -，,、。")
      if cleaned:
        items.append(cleaned)
  return _ordered_unique(items)


def _structured_entity_name(value: str) -> str:
  cleaned = value.strip(" -，,、。")
  if "：" in cleaned or ":" in cleaned:
    left = re.split(r"[:：]", cleaned, maxsplit=1)[0].strip()
    if 1 <= len(left) <= 24:
      return left
  return _compact_text(cleaned, limit=40)


def _first_structured_string(payload: dict, keys: tuple[str, ...]) -> str:
  for key in keys:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
      return value.strip()
  return ""


def _structured_related_characters(payload: dict) -> list[str]:
  values: list[str] = []
  for key in _STRUCTURED_RELATED_CHARACTER_KEYS:
    value = payload.get(key)
    if isinstance(value, str):
      values.append(value)
    elif isinstance(value, list):
      values.extend(str(item) for item in value if str(item).strip())
  return _structured_items(values)


def _structured_entity_records(kind: str, value: object) -> list[tuple[str, str, list[str]]]:
  records: list[tuple[str, str, list[str]]] = []
  if value is None:
    return records
  if isinstance(value, str):
    for item in _structured_items([value]):
      records.append((_structured_entity_name(item), item, []))
    return [(name, summary, related) for name, summary, related in records if name]
  if isinstance(value, list):
    for item in value:
      records.extend(_structured_entity_records(kind, item))
    return records
  if not isinstance(value, dict):
    text = _json_value_to_text(value)
    return _structured_entity_records(kind, text)

  name = _first_structured_string(value, _STRUCTURED_ENTITY_NAME_KEYS[kind])
  related = _structured_related_characters(value)
  summary = _first_structured_string(value, _STRUCTURED_SUMMARY_KEYS)
  if not summary:
    summary = _json_value_to_text(value)
  if name:
    return [(_structured_entity_name(name), _compact_text(summary, limit=140), related)]

  for key, item in value.items():
    if key in _STRUCTURED_RELATED_CHARACTER_KEYS or key in _STRUCTURED_SUMMARY_KEYS:
      continue
    if isinstance(key, str) and key.strip() and key not in _STRUCTURED_OVERVIEW_KEY_TO_FIELD:
      if isinstance(item, (str, int, float, bool)):
        records.append((_structured_entity_name(key), _compact_text(str(item), limit=140), related))
        continue
    records.extend(_structured_entity_records(kind, item))
  return [(record_name, record_summary, record_related) for record_name, record_summary, record_related in records if record_name]


def _structured_overview_entities_from_payload(payload: object) -> dict[str, list[tuple[str, str, list[str]]]]:
  entities: dict[str, list[tuple[str, str, list[str]]]] = defaultdict(list)
  if isinstance(payload, list):
    for item in payload:
      for kind, records in _structured_overview_entities_from_payload(item).items():
        entities[kind].extend(records)
    return entities
  if not isinstance(payload, dict):
    return entities

  for key, value in payload.items():
    field = _STRUCTURED_OVERVIEW_KEY_TO_FIELD.get(str(key))
    if field in {"events", "locations", "props", "skills", "scenes", "organizations"}:
      entities[field].extend(_structured_entity_records(field, value))
      continue
    if isinstance(value, (dict, list)):
      for kind, records in _structured_overview_entities_from_payload(value).items():
        entities[kind].extend(records)
  return entities


def _extract_json_structured_overview_entities(text: str) -> dict[str, list[tuple[str, str, list[str]]]]:
  try:
    payload = json.loads(text)
  except (TypeError, json.JSONDecodeError):
    return {}
  return _structured_overview_entities_from_payload(payload)


def _overview_source_signature(
  documents: list[StoryDocument],
  material_payloads: list[dict[str, str]],
  chapters: list[ChapterSummary],
  obsidian_entries: list[tuple[str, int, int]] | None = None,
) -> str:
  parts: list[str] = []
  for item in documents:
    parts.append(f"document::{item.key}::{(item.content or '').strip()}")
  for item in material_payloads:
    parts.append(f"material::{item.get('title', '').strip()}::{item.get('content', '').strip()}::{item.get('updated_at', '')}")
  for chapter in chapters:
    if not chapter.exists and not (chapter.content or "").strip():
      continue
    parts.append(f"chapter::{chapter.id}::{chapter.title}::{(chapter.content or chapter.preview or '').strip()}")
  for source_label, mtime_ns, size in obsidian_entries or []:
    parts.append(f"obsidian::{source_label}::{mtime_ns}::{size}")
  return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


def _overview_source_blocks(
  documents: list[StoryDocument],
  material_payloads: list[dict[str, str]],
  chapters: list[ChapterSummary],
  obsidian_records: list[object] | None = None,
) -> list[str]:
  blocks: list[str] = []
  for document in documents:
    content = (document.content or "").strip()
    if content:
      blocks.append(f"【设定文件:{document.label} / {document.key}】\n{content}")
  for material in material_payloads[:20]:
    title = material.get("title", "").strip() or "未命名资料"
    content = _material_analysis_text(material.get("content", ""), limit=3000)
    if content:
      blocks.append(f"【资料:{title}】\n{content}")
  for chapter in chapters:
    if not chapter.exists or not (chapter.content or "").strip():
      continue
    content = _material_analysis_text(_extract_chapter_body(chapter), limit=2600)
    blocks.append(f"【章节:{chapter.index}《{chapter.title}》】\n{content}")
  for record in (obsidian_records or [])[:80]:
    summary = getattr(record, "summary", None)
    title = str(getattr(summary, "title", "") or "").strip() or "未命名笔记"
    relative_path = str(getattr(summary, "relative_path", "") or "").strip()
    content = _material_analysis_text(str(getattr(record, "content", "") or ""), limit=2400)
    if content:
      blocks.append(f"【Obsidian:{title} / {relative_path}】\n{content}")
  return blocks


def _split_oversized_source_block(block: str, limit: int) -> list[str]:
  if len(block) <= limit:
    return [block]

  chunks: list[str] = []
  overlap = min(600, max(0, limit // 5))
  step = max(1, limit - overlap)
  for index, start in enumerate(range(0, len(block), step), start=1):
    piece = block[start : start + limit].strip()
    if piece:
      chunks.append(f"【长来源片段 {index}】\n{piece}")
  return chunks


def _overview_source_chunks_from_blocks(blocks: list[str], *, limit: int) -> list[str]:
  chunks: list[str] = []
  current: list[str] = []
  current_size = 0

  def flush_current() -> None:
    nonlocal current, current_size
    if current:
      chunks.append("\n\n".join(current).strip())
      current = []
      current_size = 0

  for block in blocks:
    cleaned = block.strip()
    if not cleaned:
      continue
    if len(cleaned) > limit:
      flush_current()
      chunks.extend(_split_oversized_source_block(cleaned, limit))
      continue
    separator_size = 2 if current else 0
    if current and current_size + separator_size + len(cleaned) > limit:
      flush_current()
    current.append(cleaned)
    current_size += separator_size + len(cleaned)

  flush_current()
  return chunks


def _chat_completions_endpoint(base_url: str) -> str:
  normalized = base_url.strip().rstrip("/")
  return f"{normalized}/chat/completions" if not normalized.endswith("/chat/completions") else normalized


def _resolve_review_model_api_key(config: ReviewModelConfig) -> str:
  candidates = [
    config.api_key,
    os.getenv("NOVEL_REVIEW_MODEL_API_KEY", ""),
    os.getenv("NOVEL_AUXILIARY_MODEL_API_KEY", ""),
    os.getenv("OPENAI_API_KEY", ""),
    os.getenv("DASHSCOPE_API_KEY", ""),
    os.getenv("ARK_API_KEY", ""),
    os.getenv("NOVEL_API_KEY", ""),
  ]
  for item in candidates:
    value = item.strip()
    if value:
      return value
  return ""


def _resolve_primary_model_api_key(config: ModelConfig) -> str:
  candidates = [
    config.api_key,
    os.getenv("NOVEL_MODEL_API_KEY", ""),
    os.getenv("DASHSCOPE_API_KEY", ""),
    os.getenv("ARK_API_KEY", ""),
    os.getenv("NOVEL_API_KEY", ""),
    os.getenv("OPENAI_API_KEY", ""),
  ]
  for item in candidates:
    value = item.strip()
    if value:
      return value
  return ""


def _is_placeholder_model_config(config: ModelConfig | ReviewModelConfig, api_key: str) -> bool:
  base_url = config.base_url.strip().lower()
  model_name = config.model_name.strip().lower()
  return "example.com" in base_url or api_key.strip() == "test-key" or model_name in {"demo-model", "test-model"}


def _auxiliary_model_enabled(settings: Settings) -> tuple[ReviewModelConfig | None, str]:
  config = load_config(settings).review_model
  if not config.enabled:
    return None, ""

  resolved = config.model_copy(
    update={
      "base_url": os.getenv("NOVEL_REVIEW_MODEL_BASE_URL", "").strip() or config.base_url,
      "model_name": os.getenv("NOVEL_REVIEW_MODEL_NAME", "").strip() or config.model_name,
    }
  )
  api_key = _resolve_review_model_api_key(resolved)
  if not api_key or not resolved.base_url.strip() or not resolved.model_name.strip():
    return None, ""
  if _is_placeholder_model_config(resolved, api_key):
    return None, ""
  return resolved, api_key


def _story_overview_model_enabled(settings: Settings) -> tuple[ModelConfig | ReviewModelConfig | None, str, str]:
  review_config, review_api_key = _auxiliary_model_enabled(settings)
  if review_config is not None and review_api_key:
    return review_config, review_api_key, "review_model"

  config = load_config(settings).model
  api_key = _resolve_primary_model_api_key(config)
  if not api_key or not config.base_url.strip() or not config.model_name.strip():
    return None, "", ""
  if _is_placeholder_model_config(config, api_key):
    return None, "", ""
  return config, api_key, "primary_model"


def _strip_json_code_fence(text: str) -> str:
  stripped = str(text or "").strip()
  if not stripped.startswith("```"):
    return stripped
  lines = stripped.splitlines()
  if len(lines) >= 3 and lines[-1].strip() == "```":
    return "\n".join(lines[1:-1]).strip()
  return stripped


def _extract_json_object_from_text(text: str) -> dict[str, object] | None:
  stripped = _strip_json_code_fence(text)
  try:
    payload = json.loads(stripped)
  except json.JSONDecodeError:
    payload = None
  if isinstance(payload, dict):
    return payload
  start = stripped.find("{")
  end = stripped.rfind("}")
  if start == -1 or end == -1 or end <= start:
    return None
  try:
    embedded = json.loads(stripped[start : end + 1])
  except json.JSONDecodeError:
    return None
  return embedded if isinstance(embedded, dict) else None


def _model_overview_messages(source_text: str) -> list[dict[str, str]]:
  return [
    {
      "role": "system",
      "content": (
        "你是中文长篇小说资料整理编辑，只能依据用户提供的项目来源整理架构总览。"
        "必须输出 JSON 对象，不要输出解释、标题或代码块。"
        "不能把字段名、普通名词、配置项、任务说明误当成故事节点。"
      ),
    },
    {
      "role": "user",
      "content": (
        "请把下面项目来源整理成架构总览。字段固定为：\n"
        "{\n"
        '  "characters": [{"name":"","profile":"","current_state":"","relationships":[],"events":[],"locations":[],"props":[],"skills":[],"scenes":[],"organizations":[],"evidence":[]}],\n'
        '  "events": [{"name":"","summary":"","related_characters":[],"evidence":[]}],\n'
        '  "locations": [{"name":"","summary":"","related_characters":[],"evidence":[]}],\n'
        '  "props": [{"name":"","summary":"","related_characters":[],"evidence":[]}],\n'
        '  "skills": [{"name":"","summary":"","related_characters":[],"evidence":[]}],\n'
        '  "scenes": [{"name":"","summary":"","related_characters":[],"evidence":[]}],\n'
        '  "organizations": [{"name":"","summary":"","related_characters":[],"evidence":[]}]\n'
        "}\n"
        "准确性要求：\n"
        "1. 每个节点必须有 evidence，evidence 必须是来源里的短句或原文片段。\n"
        "2. 找不到证据就不要输出该节点。\n"
        "3. relationships 写成“对方：关系说明”，对方必须是来源中出现的人物或明确称谓。\n"
        "4. events、locations、props、skills、scenes、organizations 都只写来源里明确存在的内容。\n"
        "5. 不要推测、不要补设定、不要为了填满字段编内容。\n\n"
        "数量限制：每个分片只输出最明确的核心节点，characters 最多 12 个，events 最多 12 个，"
        "locations、props、skills、scenes、organizations 各最多 10 个；合并同类项，"
        "不要把每个章节标题都拆成事件。profile、current_state、summary 都控制在 60 个中文字符以内；"
        "每个人物 relationships 最多 3 条，events 最多 4 条；每个节点 evidence 最多 2 条，"
        "evidence 必须是原文里可直接匹配的短片段。\n"
        "人物筛选：characters 只输出稳定人物。稳定人物必须在人物状态中有专属段落，"
        "或在两个以上来源文件中持续出现；只在单个旧设定文件出现的旧名字、职务泛称、"
        "临时配角和章节功能角色不要放进 characters。若人物设定与人物状态、情节骨架、章节蓝图互相冲突，"
        "优先采用后续文件中反复出现的姓名，不要同时保留被替换的旧名字。\n\n"
        f"项目来源：\n{source_text}"
      ),
    },
  ]


def _invoke_auxiliary_model(
  settings: Settings,
  messages: list[dict[str, str]],
  *,
  task_name: str,
  temperature: float,
  max_tokens: int,
  model_config: ModelConfig | ReviewModelConfig | None = None,
  api_key: str = "",
  model_source: str = "review_model",
  timeout: int = 45,
) -> str:
  config = model_config
  if config is None or not api_key:
    config, api_key = _auxiliary_model_enabled(settings)
    model_source = "review_model"
  if config is None or not api_key:
    raise RuntimeError("辅助模型未配置")

  endpoint = _chat_completions_endpoint(config.base_url)
  chat_payload = {
    "model": config.model_name,
    "messages": messages,
    "temperature": temperature,
    "max_tokens": max(256, min(max_tokens, 16000)),
  }
  prompt_text = "\n\n".join(f"[{item['role']}] {item['content']}" for item in messages)
  started = time.perf_counter()
  runtime_task = None
  try:
    with model_runtime_slot(settings, lane="chat", task_name=task_name) as task:
      runtime_task = task
      response_payload = request_json_with_retries(
        endpoint,
        headers={
          "Content-Type": "application/json",
          "Authorization": f"Bearer {api_key}",
        },
        payload=chat_payload,
        error_prefix="模型请求失败",
        invalid_json_message="模型返回的不是合法 JSON",
        invalid_payload_message="模型返回格式不正确",
        timeout=timeout,
        retry_delays=(1.0,),
      )
    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
      raise RuntimeError("模型返回为空")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
      raise RuntimeError("模型没有返回文本内容")
    content = message["content"].strip()
    elapsed = round(time.perf_counter() - started, 3)
    append_prompt_history(
      settings,
      {
        "task": task_name,
        "model": config.model_name,
        "model_source": model_source,
        "prompt": prompt_text,
        "response": content,
        "status": "completed",
        "elapsed": elapsed,
        "runtime_task_id": runtime_task.task_id if runtime_task is not None else "",
        "runtime_lane": runtime_task.lane if runtime_task is not None else "chat",
        "runtime_priority": runtime_task.priority if runtime_task is not None else 0,
        "queue_wait_seconds": runtime_task.queue_wait_seconds if runtime_task is not None else 0.0,
      },
    )
    append_app_log(settings, f"{task_name} completed in {elapsed:.3f}s")
    return content
  except Exception as error:
    elapsed = round(time.perf_counter() - started, 3)
    classified_error = classify_model_error(error)
    if classified_error.retryable:
      mark_model_runtime_cooldown(settings, "chat", classified_error.title)
    append_prompt_history(
      settings,
      {
        "task": task_name,
        "model": config.model_name,
        "model_source": model_source,
        "prompt": prompt_text,
        "response": "",
        "status": "failed",
        "elapsed": elapsed,
        "error": str(error),
        "error_kind": classified_error.kind,
        "error_title": classified_error.title,
        "error_user_action": classified_error.user_action,
        "error_retryable": classified_error.retryable,
        "runtime_task_id": runtime_task.task_id if runtime_task is not None else "",
        "runtime_lane": runtime_task.lane if runtime_task is not None else "chat",
        "runtime_priority": runtime_task.priority if runtime_task is not None else 0,
        "queue_wait_seconds": runtime_task.queue_wait_seconds if runtime_task is not None else 0.0,
      },
    )
    append_app_log(settings, f"{task_name} failed: {classified_error.title}: {error}", level="ERROR")
    raise


def _request_model_story_overview(settings: Settings, source_text: str) -> dict[str, object]:
  messages = _model_overview_messages(source_text)
  config, api_key, model_source = _story_overview_model_enabled(settings)
  if config is None:
    append_app_log(settings, "story_overview_model skipped: 写作模型和第二审查模型均未配置", level="INFO")
    raise RuntimeError("模型总览生成失败：写作模型和第二审查模型均未配置。")
  content = _invoke_auxiliary_model(
    settings,
    messages,
    task_name="story_overview_model",
    temperature=0.1,
    max_tokens=8192,
    model_config=config,
    api_key=api_key,
    model_source=model_source,
    timeout=240,
  )
  payload = _extract_json_object_from_text(content)
  if payload is None:
    raise RuntimeError("模型总览生成失败：模型返回的不是合法 JSON。")
  return payload


def _normalized_evidence_text(text: str) -> str:
  return " ".join(str(text or "").split())


def _source_contains(source_text: str, value: str) -> bool:
  normalized = _normalized_evidence_text(value)
  return bool(normalized and normalized in _normalized_evidence_text(source_text))


def _model_string_from_keys(payload: dict[str, object], *keys: str) -> str:
  for key in keys:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
      return value.strip()
  return ""


def _model_string_list(value: object) -> list[str]:
  if value is None:
    return []
  if isinstance(value, str):
    return _structured_items([value])
  if isinstance(value, list):
    items: list[str] = []
    for item in value:
      if isinstance(item, str):
        items.extend(_structured_items([item]))
      elif isinstance(item, dict):
        name = _model_string_from_keys(item, "name", "title", "姓名", "名称", "标题")
        summary = _model_string_from_keys(item, "summary", "description", "detail", "说明", "摘要")
        if name and summary:
          items.append(f"{name}：{summary}")
        elif name:
          items.append(name)
        else:
          text = _json_value_to_text(item)
          if text:
            items.append(text)
      else:
        text = str(item).strip()
        if text:
          items.append(text)
    return _ordered_unique(items)
  if isinstance(value, dict):
    items = []
    for key, item in value.items():
      text = _json_value_to_text(item)
      if text:
        items.append(f"{key}：{text}")
    return _ordered_unique(items)
  text = str(value).strip()
  return [text] if text else []


def _model_evidence_list(payload: dict[str, object]) -> list[str]:
  return _model_string_list(
    payload.get("evidence")
    or payload.get("source_evidence")
    or payload.get("evidence_snippet")
    or payload.get("依据")
    or payload.get("证据")
  )


def _has_supported_evidence(source_text: str, payload: dict[str, object], name: str) -> bool:
  evidence_items = _model_evidence_list(payload)
  if any(_source_contains(source_text, item) for item in evidence_items):
    return True
  return bool(name and _source_contains(source_text, name) and any(_source_contains(source_text, item) for item in _model_string_list(payload.get("summary") or payload.get("description") or payload.get("说明"))))


def _model_entity_name_from_text(value: str) -> str:
  return _structured_entity_name(value).strip()


def _model_entity_records(kind: str, value: object, source_text: str) -> list[tuple[str, str, list[str]]]:
  records: list[tuple[str, str, list[str]]] = []
  if isinstance(value, list):
    values = value
  elif value is None:
    values = []
  else:
    values = [value]

  for item in values:
    if isinstance(item, dict):
      name = _model_string_from_keys(item, "name", "title", "名称", "标题")
      summary = _model_string_from_keys(item, "summary", "description", "detail", "说明", "摘要")
      related = _model_string_list(item.get("related_characters") or item.get("characters") or item.get("关联人物"))
      if not name:
        continue
      name = _model_entity_name_from_text(name)
      if not name or not _has_supported_evidence(source_text, item, name):
        continue
      records.append((name, _compact_text(summary or name, limit=140), related))
      continue

    for raw_name in _model_string_list(item):
      name = _model_entity_name_from_text(raw_name)
      if name and _source_contains(source_text, name):
        records.append((name, _compact_text(raw_name, limit=140), []))

  return records


def _model_cache_to_overview(
  project_dir: Path,
  documents: list[StoryDocument],
  source_signature: str,
) -> StoryOverview | None:
  payload = read_json(_model_story_overview_path(project_dir), None)
  if not isinstance(payload, dict):
    return None
  if payload.get("schema_version") != _MODEL_STORY_OVERVIEW_SCHEMA_VERSION:
    return None
  if payload.get("source_signature") != source_signature:
    return None
  overview_payload = payload.get("overview")
  if not isinstance(overview_payload, dict):
    return None
  try:
    return StoryOverview(
      documents=documents,
      materials=_build_knowledge_materials(project_dir),
      memory_entries=load_project_memory(project_dir),
      characters=[StoryCharacter.model_validate(item) for item in overview_payload.get("characters", [])],
      events=[StoryEntityReference.model_validate(item) for item in overview_payload.get("events", [])],
      locations=[StoryEntityReference.model_validate(item) for item in overview_payload.get("locations", [])],
      props=[StoryEntityReference.model_validate(item) for item in overview_payload.get("props", [])],
      skills=[StoryEntityReference.model_validate(item) for item in overview_payload.get("skills", [])],
      scenes=[StoryEntityReference.model_validate(item) for item in overview_payload.get("scenes", [])],
      organizations=[StoryEntityReference.model_validate(item) for item in overview_payload.get("organizations", [])],
    )
  except Exception:
    return None


def _validated_model_story_overview(
  payload: dict[str, object],
  *,
  project_dir: Path,
  documents: list[StoryDocument],
  source_text: str,
  allow_unmatched_related: bool = False,
) -> StoryOverview | None:
  raw_characters = payload.get("characters")
  if raw_characters is None:
    raw_characters = []
  if not isinstance(raw_characters, list):
    return None

  character_store: dict[str, dict] = {}
  entity_store = {
    "events": {},
    "locations": {},
    "props": {},
    "skills": {},
    "scenes": {},
    "organizations": {},
  }

  for raw_item in raw_characters:
    if not isinstance(raw_item, dict):
      continue
    name = _model_string_from_keys(raw_item, "name", "姓名", "人物", "角色")
    if not _is_character_candidate(name) or not _has_supported_evidence(source_text, raw_item, name):
      continue
    profile = _compact_text(_model_string_from_keys(raw_item, "profile", "summary", "description", "身份", "说明"), limit=220)
    current_state = _compact_text(_model_string_from_keys(raw_item, "current_state", "initial_state", "state", "当前状态", "初始状态"), limit=180)
    store = _new_character_store_item()
    store["profile"] = profile
    store["current_state"] = current_state
    store["relationships"] = _model_string_list(raw_item.get("relationships") or raw_item.get("relations") or raw_item.get("关系"))

    for kind in ("events", "locations", "props", "skills", "scenes", "organizations"):
      records = _model_entity_records(kind, raw_item.get(kind), source_text)
      names = [record_name for record_name, _summary, _related in records]
      store[kind] = names
      for record_name, summary, related in records:
        _register_entity(
          entity_store[kind],
          record_name,
          summary=summary,
          related_characters=_ordered_unique([name] + related),
        )

    store["timeline"] = [
      CharacterTimelineEntry(
        id=f"{name}-model-overview",
        source_label="模型总览",
        summary=profile or current_state or name,
        relations=store["relationships"],
        events=store["events"],
        locations=store["locations"],
        props=store["props"],
        skills=store["skills"],
        scenes=store["scenes"],
        organizations=store["organizations"],
      )
    ]
    character_store[name] = store

  character_names = list(character_store.keys())
  for kind in ("events", "locations", "props", "skills", "scenes", "organizations"):
    for record_name, summary, related in _model_entity_records(kind, payload.get(kind), source_text):
      related_characters = _ordered_unique(related if allow_unmatched_related else [name for name in related if name in character_store])
      _register_entity(entity_store[kind], record_name, summary=summary, related_characters=related_characters)
      for character_name in related_characters:
        if character_name in character_store:
          character_store[character_name][kind] = _ordered_unique(character_store[character_name][kind] + [record_name])

  def build_entities(kind: str) -> list[StoryEntityReference]:
    return [
      StoryEntityReference(
        name=name,
        summary=str(item["summary"]),
        related_characters=_ordered_unique(
          list(item["related_characters"])
          if allow_unmatched_related
          else [value for value in item["related_characters"] if value in character_names]
        ),
        chapter_indexes=[],
      )
      for name, item in sorted(
        entity_store[kind].items(),
        key=lambda entity: (-(len(entity[1]["related_characters"])), entity[0]),
      )
    ]

  if not character_store and not any(entity_store[kind] for kind in entity_store):
    return None

  return StoryOverview(
    documents=documents,
    materials=_build_knowledge_materials(project_dir),
    memory_entries=load_project_memory(project_dir),
    characters=[
      StoryCharacter(
        name=name,
        profile=str(character_store[name]["profile"]),
        current_state=str(character_store[name]["current_state"]),
        relationships=character_store[name]["relationships"],
        events=character_store[name]["events"],
        locations=character_store[name]["locations"],
        props=character_store[name]["props"],
        skills=character_store[name]["skills"],
        scenes=character_store[name]["scenes"],
        organizations=character_store[name]["organizations"],
        timeline=character_store[name]["timeline"],
      )
      for name in character_names
    ],
    events=build_entities("events"),
    locations=build_entities("locations"),
    props=build_entities("props"),
    skills=build_entities("skills"),
    scenes=build_entities("scenes"),
    organizations=build_entities("organizations"),
  )


def _merge_model_entity_references(
  items: list[StoryEntityReference],
  *,
  character_names: list[str],
) -> list[StoryEntityReference]:
  merged: dict[str, dict[str, object]] = {}
  for item in items:
    name = item.name.strip()
    if not name:
      continue
    record = merged.setdefault(
      name,
      {
        "summary": "",
        "related_characters": set(),
        "chapter_indexes": set(),
      },
    )
    if item.summary and not record["summary"]:
      record["summary"] = item.summary
    record["related_characters"].update(value for value in item.related_characters if value in character_names)
    record["chapter_indexes"].update(item.chapter_indexes)

  return [
    StoryEntityReference(
      name=name,
      summary=str(item["summary"]),
      related_characters=_ordered_unique(list(item["related_characters"])),
      chapter_indexes=sorted(int(value) for value in item["chapter_indexes"]),
    )
    for name, item in sorted(
      merged.items(),
      key=lambda entity: (-(len(entity[1]["related_characters"]) + len(entity[1]["chapter_indexes"])), entity[0]),
    )
  ]


def _merge_model_story_overviews(
  project_dir: Path,
  documents: list[StoryDocument],
  overviews: list[StoryOverview],
) -> StoryOverview | None:
  if not overviews:
    return None

  character_store: dict[str, dict[str, object]] = {}
  for overview_index, overview in enumerate(overviews, start=1):
    for character in overview.characters:
      name = character.name.strip()
      if not name:
        continue
      store = character_store.setdefault(name, _new_character_store_item())
      if character.profile and not store["profile"]:
        store["profile"] = character.profile
      if character.current_state and not store["current_state"]:
        store["current_state"] = character.current_state
      for field in ("relationships", "events", "locations", "props", "skills", "scenes", "organizations"):
        store[field] = _ordered_unique(store[field] + getattr(character, field))
      timeline = store["timeline"]
      existing_timeline_ids = {item.id for item in timeline}
      for entry in character.timeline:
        next_entry = entry
        if next_entry.id in existing_timeline_ids:
          next_entry = entry.model_copy(update={"id": f"{entry.id}-{overview_index}"})
        timeline.append(next_entry)
        existing_timeline_ids.add(next_entry.id)

  character_names = list(character_store.keys())
  entity_sources = {
    "events": [item for overview in overviews for item in overview.events],
    "locations": [item for overview in overviews for item in overview.locations],
    "props": [item for overview in overviews for item in overview.props],
    "skills": [item for overview in overviews for item in overview.skills],
    "scenes": [item for overview in overviews for item in overview.scenes],
    "organizations": [item for overview in overviews for item in overview.organizations],
  }
  entities = {
    kind: _merge_model_entity_references(items, character_names=character_names)
    for kind, items in entity_sources.items()
  }

  if not character_store and not any(entities.values()):
    return None

  return StoryOverview(
    documents=documents,
    materials=_build_knowledge_materials(project_dir),
    memory_entries=load_project_memory(project_dir),
    characters=[
      StoryCharacter(
        name=name,
        profile=str(character_store[name]["profile"]),
        current_state=str(character_store[name]["current_state"]),
        relationships=character_store[name]["relationships"],
        events=character_store[name]["events"],
        locations=character_store[name]["locations"],
        props=character_store[name]["props"],
        skills=character_store[name]["skills"],
        scenes=character_store[name]["scenes"],
        organizations=character_store[name]["organizations"],
        timeline=character_store[name]["timeline"],
      )
      for name in character_names
    ],
    events=entities["events"],
    locations=entities["locations"],
    props=entities["props"],
    skills=entities["skills"],
    scenes=entities["scenes"],
    organizations=entities["organizations"],
  )


def _read_model_story_overview_failure(project_dir: Path) -> dict[str, object] | None:
  payload = read_json(_model_story_overview_failure_path(project_dir), None)
  return payload if isinstance(payload, dict) else None


def _model_story_overview_failure_message(payload: dict[str, object] | None) -> str:
  error = str((payload or {}).get("error") or "").strip()
  if error:
    if error.startswith("模型总览生成失败"):
      return error
    return f"模型总览生成失败：{error}"
  return "模型总览生成失败，请检查写作模型或第二审查模型配置和模型调用日志。"


def _write_model_story_overview_failure(project_dir: Path, error: str) -> None:
  atomic_write_json(
    _model_story_overview_failure_path(project_dir),
    {
      "schema_version": _MODEL_STORY_OVERVIEW_SCHEMA_VERSION,
      "failed_at": _now_iso(),
      "error": str(error or "模型总览生成失败"),
    },
  )


def _clear_model_story_overview_failure(project_dir: Path) -> None:
  try:
    _model_story_overview_failure_path(project_dir).unlink()
  except FileNotFoundError:
    pass


def _model_story_overview_status(
  settings: Settings,
  project_dir: Path,
  documents: list[StoryDocument],
  material_payloads: list[dict[str, str]],
  chapters: list[ChapterSummary],
) -> StoryOverviewModelStatus:
  source_signature = _overview_source_signature(
    documents,
    material_payloads,
    chapters,
    obsidian_source_signature_entries(project_dir),
  )
  cache_payload = read_json(_model_story_overview_path(project_dir), None)
  stale_generated_at = ""
  if isinstance(cache_payload, dict) and cache_payload.get("schema_version") == _MODEL_STORY_OVERVIEW_SCHEMA_VERSION:
    generated_at = str(cache_payload.get("generated_at") or "")
    if cache_payload.get("source_signature") == source_signature:
      return StoryOverviewModelStatus(
        status="ready",
        message="模型总览已生成。",
        generated_at=generated_at,
      )
    stale_generated_at = generated_at

  failure_payload = _read_model_story_overview_failure(project_dir)
  if failure_payload is not None:
    return StoryOverviewModelStatus(
      status="failed",
      message=_model_story_overview_failure_message(failure_payload),
      failed_at=str(failure_payload.get("failed_at") or ""),
      error=str(failure_payload.get("error") or ""),
    )

  if stale_generated_at:
    return StoryOverviewModelStatus(
      status="stale",
      message="模型总览已过期，需要重新生成。",
      generated_at=stale_generated_at,
    )

  if _story_overview_model_enabled(settings)[0] is None:
    return StoryOverviewModelStatus(
      status="disabled",
      message="写作模型和第二审查模型均未配置，不能生成模型总览。",
    )

  return StoryOverviewModelStatus(
    status="not_generated",
    message="模型总览还没有生成。",
  )


def _base_story_overview(project_dir: Path, documents: list[StoryDocument], status: StoryOverviewModelStatus) -> StoryOverview:
  return StoryOverview(
    documents=documents,
    materials=_build_knowledge_materials(project_dir),
    obsidian=load_obsidian_state(project_dir),
    memory_entries=load_project_memory(project_dir),
    model_overview=status,
  )


def _model_story_overview_or_none(
  settings: Settings,
  project_dir: Path,
  documents: list[StoryDocument],
  material_payloads: list[dict[str, str]],
  chapters: list[ChapterSummary],
  *,
  allow_request: bool = False,
  force: bool = False,
  use_cache: bool = True,
) -> StoryOverview | None:
  source_signature = _overview_source_signature(
    documents,
    material_payloads,
    chapters,
    obsidian_source_signature_entries(project_dir),
  )
  cached = _model_cache_to_overview(project_dir, documents, source_signature) if use_cache else None
  if cached is not None and not force:
    return cached
  if not allow_request:
    return None
  if _story_overview_model_enabled(settings)[0] is None:
    append_app_log(settings, "story_overview_model skipped: 写作模型和第二审查模型均未配置", level="INFO")
    raise RuntimeError("模型总览生成失败：写作模型和第二审查模型均未配置。")

  obsidian_records, _obsidian_skipped, _obsidian_warnings = collect_obsidian_note_records(project_dir)
  source_blocks = _overview_source_blocks(documents, material_payloads, chapters, obsidian_records)
  full_source_text = "\n\n".join(source_blocks).strip()
  if not full_source_text:
    return None
  source_chunks = _overview_source_chunks_from_blocks(
    source_blocks,
    limit=_MODEL_STORY_OVERVIEW_SOURCE_CHUNK_LIMIT,
  )
  if not source_chunks:
    return None

  chunk_overviews: list[StoryOverview] = []
  for index, source_chunk in enumerate(source_chunks, start=1):
    chunk_text = f"【来源分片 {index}/{len(source_chunks)}】\n{source_chunk}"
    try:
      model_payload = _request_model_story_overview(settings, chunk_text)
    except Exception as error:
      append_app_log(settings, f"story_overview_model chunk {index}/{len(source_chunks)} failed", level="WARNING")
      _write_model_story_overview_failure(project_dir, str(error))
      error_message = str(error)
      if not error_message.startswith("模型总览生成失败"):
        error_message = f"模型总览生成失败：{error_message}"
      raise RuntimeError(error_message) from error
    chunk_overview = _validated_model_story_overview(
      model_payload,
      project_dir=project_dir,
      documents=documents,
      source_text=full_source_text,
      allow_unmatched_related=True,
    )
    if chunk_overview is not None:
      chunk_overviews.append(chunk_overview)

  overview = _merge_model_story_overviews(project_dir, documents, chunk_overviews)
  if overview is None:
    append_app_log(settings, "story_overview_model returned no validated overview nodes", level="WARNING")
    _write_model_story_overview_failure(project_dir, "returned no validated overview nodes")
    raise RuntimeError("模型总览生成失败：模型没有返回可验证的人物、事件或世界要素。")
  atomic_write_json(
    _model_story_overview_path(project_dir),
    {
      "schema_version": _MODEL_STORY_OVERVIEW_SCHEMA_VERSION,
      "source_signature": source_signature,
      "generated_at": _now_iso(),
      "overview": {
        "characters": [item.model_dump(mode="json") for item in overview.characters],
        "events": [item.model_dump(mode="json") for item in overview.events],
        "locations": [item.model_dump(mode="json") for item in overview.locations],
        "props": [item.model_dump(mode="json") for item in overview.props],
        "skills": [item.model_dump(mode="json") for item in overview.skills],
        "scenes": [item.model_dump(mode="json") for item in overview.scenes],
        "organizations": [item.model_dump(mode="json") for item in overview.organizations],
      },
    },
  )
  _clear_model_story_overview_failure(project_dir)
  return overview


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


def _new_character_store_item() -> dict[str, object]:
  return {
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


def _apply_structured_character_fields(
  character_store: dict[str, dict],
  entity_store: dict[str, dict],
  name: str,
  lines: list[str],
  *,
  summary: str,
) -> dict[str, list[str]]:
  fields = _structured_field_map(lines)
  if not fields:
    return {}

  store = character_store.setdefault(name, _new_character_store_item())
  if fields.get("current_state") and not store["current_state"]:
    store["current_state"] = _compact_text("；".join(_structured_items(fields["current_state"])), limit=160)

  if fields.get("relationships"):
    store["relationships"] = _ordered_unique(
      store["relationships"] + _structured_items(fields["relationships"])
    )

  structured_entities: dict[str, list[str]] = {}
  for kind in ("events", "locations", "props", "skills", "scenes", "organizations"):
    values = _structured_items(fields.get(kind, []))
    if not values:
      continue
    entity_names = [_structured_entity_name(item) for item in values]
    entity_names = [item for item in entity_names if item]
    if not entity_names:
      continue
    structured_entities[kind] = entity_names
    store[kind] = _ordered_unique(store[kind] + entity_names)
    for entity_name, raw_value in zip(entity_names, values):
      _register_entity(
        entity_store[kind],
        entity_name,
        summary=_compact_text(raw_value if raw_value != entity_name else summary, limit=120),
        related_characters=[name],
      )

  return structured_entities


def _build_story_overview(
  settings: Settings,
  project_dir: Path,
  chapters: list[ChapterSummary],
  *,
  review_character_candidates: bool = False,
  allow_model_overview: bool = False,
  force_model_overview: bool = False,
  use_model_overview_cache: bool = True,
) -> StoryOverview:
  documents = _build_story_documents(project_dir)
  material_payloads = _load_knowledge_material_payloads(project_dir)
  model_status = _model_story_overview_status(settings, project_dir, documents, material_payloads, chapters)
  model_overview = _model_story_overview_or_none(
    settings,
    project_dir,
    documents,
    material_payloads,
    chapters,
    allow_request=allow_model_overview,
    force=force_model_overview,
    use_cache=use_model_overview_cache,
  )
  if model_overview is not None:
    model_status = _model_story_overview_status(settings, project_dir, documents, material_payloads, chapters)
    return model_overview.model_copy(
      update={
        "obsidian": load_obsidian_state(project_dir),
        "model_overview": model_status,
      }
    )

  return _base_story_overview(project_dir, documents, model_status)


def _overview_has_structured_entities(overview: StoryOverview) -> bool:
  return any(
    bool(getattr(overview, field, []) or [])
    for field in ("characters", "events", "locations", "props", "skills", "scenes", "organizations")
  )


def list_projects(settings: Settings) -> list[ProjectSummary]:
  payload = read_json(project_index_path(settings), [])
  projects = [ProjectSummary.model_validate(item) for item in payload]
  return sorted(projects, key=lambda item: item.updated_at, reverse=True)


def get_project_detail(
  settings: Settings,
  project_id: str,
  *,
  review_characters: bool = False,
  allow_model_overview: bool = False,
  use_model_overview_cache: bool = True,
) -> ProjectDetail:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  chapters = [
    _build_chapter_summary(project_dir, index)
    for index in range(1, summary.target_chapters + 1)
  ]
  local_history = _local_history_state(project_dir)
  overview = _build_story_overview(
    settings,
    project_dir,
    chapters,
    review_character_candidates=review_characters,
    allow_model_overview=allow_model_overview or review_characters,
    use_model_overview_cache=use_model_overview_cache,
  )
  memory_overview = overview
  if _overview_has_structured_entities(overview):
    memory_overview = _build_story_overview(
      settings,
      project_dir,
      chapters,
      review_character_candidates=False,
      allow_model_overview=False,
      use_model_overview_cache=False,
    )
  auto_entries, memory_signature = build_auto_project_memory(
    documents=memory_overview.documents,
    characters=memory_overview.characters,
    events=memory_overview.events,
    locations=memory_overview.locations,
    props=memory_overview.props,
    scenes=memory_overview.scenes,
    organizations=memory_overview.organizations,
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
  distillation_overview = overview
  if _overview_has_structured_entities(overview):
    distillation_overview = memory_overview.model_copy(
      update={
        "memory_entries": overview.memory_entries,
        "dream_report": overview.dream_report,
      }
    )
  detail = ProjectDetail(
    **summary.model_dump(),
    chapters=chapters,
    local_history=local_history,
    story_overview=overview,
  )
  distillation_detail = detail.model_copy(update={"story_overview": distillation_overview})
  distillation_signature = build_project_distillation_signature(distillation_detail)
  distillation_report = load_project_distillation(
    project_dir,
    source_signature=distillation_signature,
  )
  if distillation_report is None or distillation_report.is_stale:
    distillation_report = generate_project_distillation(distillation_detail, source_signature=distillation_signature)
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


def refresh_project_model_story_overview(
  settings: Settings,
  project_id: str,
  *,
  force: bool = False,
) -> ProjectDetail:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  chapters = [
    _build_chapter_summary(project_dir, index)
    for index in range(1, summary.target_chapters + 1)
  ]
  overview = _model_story_overview_or_none(
    settings,
    project_dir,
    _build_story_documents(project_dir),
    _load_knowledge_material_payloads(project_dir),
    chapters,
    allow_request=True,
    force=force,
  )
  if overview is None or not _model_story_overview_path(project_dir).exists():
    raise RuntimeError(
      "模型总览生成失败：没有生成 .gaoxia/story_overview_model.json，请检查写作模型或第二审查模型配置和模型调用日志。"
    )
  return get_project_detail(settings, project_id, allow_model_overview=False)


def refresh_project_knowledge_index(settings: Settings, project_id: str) -> dict[str, object]:
  summary = _project_summary_or_404(settings, project_id)
  result = _rebuild_project_knowledge(_project_dir(summary), summary.target_chapters, settings)
  embedding_error = str(result.get("embedding_error") or "").strip()
  if embedding_error:
    raise RuntimeError(f"知识库向量索引刷新失败：{embedding_error}")
  return result


def refresh_project_system_memory(settings: Settings, project_id: str, *, focus: str = "辅助任务刷新") -> ProjectDetail:
  return _auto_refresh_system_memory(settings, project_id, focus=focus)


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


def export_project_migration_package(
  settings: Settings,
  project_id: str,
) -> ProjectMigrationExportResult:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _assert_project_dir_is_valid(summary)
  scrub_external_obsidian_index = _project_has_external_obsidian_vault(project_dir)
  project_files, file_warnings = _iter_migration_project_files(
    project_dir,
    scrub_external_obsidian_index=scrub_external_obsidian_index,
  )
  warnings = [*file_warnings, *_migration_external_resource_warnings(project_dir)]
  created_at = _now_iso()
  timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
  filename = f"{timestamp}_{_safe_folder_name(summary.name)}{_MIGRATION_PACKAGE_SUFFIX}"
  output_path = _migration_output_dir(project_dir) / filename
  temp_path = _migration_cache_dir(settings) / f"{uuid4().hex}{_MIGRATION_PACKAGE_SUFFIX}"
  manifest = {
    "schema_version": _MIGRATION_SCHEMA_VERSION,
    "app_name": settings.app_name,
    "app_version": settings.app_version,
    "exported_at": created_at,
    "project_root": _MIGRATION_PROJECT_ROOT,
    "root_dirname": project_dir.name,
    "project": summary.model_dump(mode="json"),
    "project_meta": read_json(_project_meta_path(project_dir), {}),
    "file_count": len(project_files),
    "warnings": warnings,
  }

  try:
    with tempfile.TemporaryDirectory(prefix="project-migration-export-", dir=_migration_cache_dir(settings)) as scratch_dir:
      scratch_path = Path(scratch_dir)
      with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
          _MIGRATION_MANIFEST_FILENAME,
          json.dumps(manifest, ensure_ascii=False, indent=2),
        )
        for path in project_files:
          relative_path = path.relative_to(project_dir).as_posix()
          archive_path = f"{_MIGRATION_PROJECT_ROOT}/{relative_path}"
          if scrub_external_obsidian_index and relative_path == "knowledge.db":
            sanitized_db_path = scratch_path / "knowledge.db"
            _sanitize_migration_knowledge_db(path, sanitized_db_path)
            archive.write(sanitized_db_path, archive_path)
          elif scrub_external_obsidian_index and relative_path == f"{_APP_STATE_DIRNAME}/obsidian_sync.json":
            sanitized_sync_path = scratch_path / "obsidian_sync.json"
            _sanitize_migration_obsidian_sync(project_dir, sanitized_sync_path)
            archive.write(sanitized_sync_path, archive_path)
          elif scrub_external_obsidian_index and relative_path == f"{_APP_STATE_DIRNAME}/learning/narrative_state.json":
            sanitized_state_path = scratch_path / "narrative_state.json"
            _sanitize_migration_narrative_state(path, sanitized_state_path)
            archive.write(sanitized_state_path, archive_path)
          elif scrub_external_obsidian_index and relative_path == "project_distillation.json":
            sanitized_distillation_path = scratch_path / "project_distillation.json"
            _sanitize_migration_project_distillation(path, sanitized_distillation_path)
            archive.write(sanitized_distillation_path, archive_path)
          elif scrub_external_obsidian_index and relative_path.startswith(f"{_APP_STATE_DIRNAME}/learning/") and relative_path.endswith(".jsonl"):
            sanitized_learning_path = scratch_path / "learning" / Path(relative_path).name
            _sanitize_migration_jsonl_file(path, sanitized_learning_path)
            archive.write(sanitized_learning_path, archive_path)
          elif scrub_external_obsidian_index and relative_path.startswith(f"{_APP_STATE_DIRNAME}/learning/") and relative_path.endswith(".json"):
            sanitized_learning_path = scratch_path / "learning" / Path(relative_path).name
            _sanitize_migration_json_file(path, sanitized_learning_path)
            archive.write(sanitized_learning_path, archive_path)
          elif (
            scrub_external_obsidian_index
            and relative_path.startswith(f"{_APP_STATE_DIRNAME}/{_AGENT_THREADS_DIRNAME}/")
            and relative_path.endswith(".json")
          ):
            sanitized_thread_path = scratch_path / "agent_threads" / Path(relative_path).name
            _sanitize_migration_agent_thread_file(path, sanitized_thread_path)
            archive.write(sanitized_thread_path, archive_path)
          elif (
            scrub_external_obsidian_index
            and relative_path.startswith(f"{_APP_STATE_DIRNAME}/{_AGENT_RUNS_DIRNAME}/")
            and relative_path.endswith(".json")
          ):
            sanitized_run_path = scratch_path / "agent_runs" / Path(*PurePosixPath(relative_path).parts)
            _sanitize_migration_agent_workflow_file(path, sanitized_run_path)
            archive.write(sanitized_run_path, archive_path)
          elif (
            scrub_external_obsidian_index
            and relative_path.startswith(f"{_APP_STATE_DIRNAME}/")
            and relative_path != f"{_APP_STATE_DIRNAME}/obsidian.json"
            and relative_path.endswith(".json")
          ):
            sanitized_app_state_path = scratch_path / "app_state" / Path(*PurePosixPath(relative_path).parts)
            _sanitize_migration_json_file(path, sanitized_app_state_path)
            archive.write(sanitized_app_state_path, archive_path)
          else:
            archive.write(path, archive_path)

    shutil.move(str(temp_path), output_path)
  finally:
    temp_path.unlink(missing_ok=True)

  append_app_log(settings, f"project migration package exported: {summary.name} -> {output_path}")
  return ProjectMigrationExportResult(
    path=str(output_path),
    filename=filename,
    project_id=summary.id,
    project_name=summary.name,
    file_count=len(project_files),
    size_bytes=output_path.stat().st_size,
    created_at=created_at,
    warnings=warnings,
  )


def import_project_migration_package(
  settings: Settings,
  request: ProjectMigrationImportRequest,
) -> ProjectMigrationImportResult:
  package_bytes = _decode_migration_package(request.content_base64)
  imported_at = _now_iso()
  base_dir = (
    Path(request.base_path).expanduser().resolve()
    if request.base_path
    else (settings.data_dir / "workspace").resolve()
  )
  base_dir.mkdir(parents=True, exist_ok=True)

  try:
    archive = zipfile.ZipFile(io.BytesIO(package_bytes))
  except zipfile.BadZipFile as error:
    raise _invalid_migration_package("迁移包不是有效的 zip 文件") from error

  with archive:
    manifest = _read_migration_manifest(archive)
    project_files, total_size = _migration_archive_project_files(archive)
    if not project_files:
      raise _invalid_migration_package("迁移包没有包含项目文件")

    raw_project_meta = manifest.get("project_meta")
    if not isinstance(raw_project_meta, dict):
      raw_project_meta = {}

    manifest_project = manifest.get("project")
    if not isinstance(manifest_project, dict):
      manifest_project = {}

    original_project_id = str(raw_project_meta.get("id") or manifest_project.get("id") or "").strip()
    original_project_name = str(
      raw_project_meta.get("name") or manifest_project.get("name") or Path(request.filename).stem
    ).strip() or "导入作品"
    project_name = (request.name_override or "").strip() or original_project_name
    preferred_dirname = _safe_import_dirname(manifest.get("root_dirname"), project_name)
    target_dir = _unique_import_project_dir(base_dir, preferred_dirname)

    with tempfile.TemporaryDirectory(prefix="project-migration-", dir=_migration_cache_dir(settings)) as temp_dir:
      extracted_dir = Path(temp_dir) / _MIGRATION_PROJECT_ROOT
      _extract_migration_project(archive, project_files, extracted_dir)
      project_meta = read_json(_project_meta_path(extracted_dir), {})
      if not isinstance(project_meta, dict):
        raise _invalid_migration_package("迁移包缺少 project.json")

      original_project_id = str(project_meta.get("id") or original_project_id).strip()
      original_project_name = str(project_meta.get("name") or original_project_name).strip() or "导入作品"
      project_name = (request.name_override or "").strip() or original_project_name
      existing_project_ids = {item.id for item in list_projects(settings)}
      next_project_id = original_project_id if original_project_id and original_project_id not in existing_project_ids else str(uuid4())
      id_changed = next_project_id != original_project_id

      try:
        shutil.copytree(extracted_dir, target_dir)
        _initialize_knowledge_db(target_dir / "knowledge.db")
        _ensure_history_layout(target_dir)

        target_project_meta = read_json(_project_meta_path(target_dir), {})
        if not isinstance(target_project_meta, dict):
          target_project_meta = {}
        target_project_meta.update(
          {
            "id": next_project_id,
            "name": project_name,
            "path": str(target_dir),
            "genre": str(target_project_meta.get("genre") or project_meta.get("genre") or "未定题材"),
            "target_chapters": _coerce_project_meta_int(
              target_project_meta.get("target_chapters", project_meta.get("target_chapters")),
              20,
              1,
              1000,
            ),
            "target_words": _coerce_project_meta_int(
              target_project_meta.get("target_words", project_meta.get("target_words")),
              200000,
              1000,
              2000000,
            ),
            "updated_at": imported_at,
          }
        )
        target_project_meta.setdefault("created_at", imported_at)
        atomic_write_json(_project_meta_path(target_dir), target_project_meta)
      except Exception:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise

  warnings = _migration_external_resource_warnings(target_dir)
  if id_changed:
    warnings.insert(0, "当前项目列表已有同 ID 作品，本次导入已生成新的作品 ID")

  summary = ProjectSummary(
    id=next_project_id,
    name=project_name,
    path=str(target_dir),
    genre=str(target_project_meta["genre"]),
    target_chapters=int(target_project_meta["target_chapters"]),
    target_words=int(target_project_meta["target_words"]),
    updated_at=imported_at,
  )
  projects = [item for item in list_projects(settings) if item.id != summary.id]
  projects.insert(0, summary)
  _write_project_index(settings, projects)

  append_app_log(settings, f"project migration package imported: {request.filename} -> {target_dir}")
  return ProjectMigrationImportResult(
    project=summary,
    original_project_id=original_project_id,
    original_project_name=original_project_name,
    imported_at=imported_at,
    path=str(target_dir),
    file_count=len(project_files),
    size_bytes=total_size,
    id_changed=id_changed,
    warnings=warnings,
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


def get_project_obsidian_state(settings: Settings, project_id: str):
  summary = _project_summary_or_404(settings, project_id)
  return load_obsidian_state(_project_dir(summary))


def _refresh_narrative_state_after_obsidian_sync(
  settings: Settings,
  project_id: str,
  project_dir: Path,
  detail: ProjectDetail,
) -> ProjectDetail:
  try:
    refresh_project_narrative_state_chapter_cards(
      project_dir,
      detail,
      persist=True,
      auto_stage_drafts=True,
    )
  except Exception as error:
    append_app_log(settings, f"narrative state obsidian refresh failed for {project_id}: {error}")
  return detail


def update_project_obsidian_config(
  settings: Settings,
  project_id: str,
  request: ObsidianVaultConfig,
) -> ProjectDetail:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  save_obsidian_config(project_dir, request)
  sync_obsidian_state(project_dir)
  updated_at = _now_iso()
  _touch_project_timestamp(settings, project_id, updated_at)
  _rebuild_project_knowledge(project_dir, summary.target_chapters, settings)
  detail = _auto_refresh_system_memory(settings, project_id, focus="Obsidian 配置已更新")
  return _refresh_narrative_state_after_obsidian_sync(settings, project_id, project_dir, detail)


def sync_project_obsidian(settings: Settings, project_id: str) -> ProjectDetail:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  sync_obsidian_state(project_dir)
  updated_at = _now_iso()
  _touch_project_timestamp(settings, project_id, updated_at)
  _rebuild_project_knowledge(project_dir, summary.target_chapters, settings)
  detail = _auto_refresh_system_memory(settings, project_id, focus="Obsidian 知识库已同步")
  return _refresh_narrative_state_after_obsidian_sync(settings, project_id, project_dir, detail)


def stage_project_obsidian_maintenance_draft(
  settings: Settings,
  project_id: str,
  suggestion_id: str,
) -> dict[str, object]:
  detail = get_project_detail(settings, project_id)
  return stage_project_obsidian_maintenance_suggestion(Path(detail.path), detail, suggestion_id)


def stage_project_obsidian_maintenance_drafts(
  settings: Settings,
  project_id: str,
  suggestion_ids: list[str] | None = None,
  *,
  limit: int = 80,
) -> dict[str, object]:
  detail = get_project_detail(settings, project_id)
  return stage_project_obsidian_maintenance_suggestions(
    Path(detail.path),
    detail,
    suggestion_ids=suggestion_ids,
    limit=limit,
  )


def confirm_project_obsidian_maintenance_merge(
  settings: Settings,
  project_id: str,
  suggestion_id: str,
) -> dict[str, object]:
  summary = _project_summary_or_404(settings, project_id)
  detail = get_project_detail(settings, project_id)
  project_dir = Path(detail.path)
  result = confirm_project_obsidian_maintenance_merge_suggestion(project_dir, detail, suggestion_id)
  sync_obsidian_state(project_dir)
  updated_at = _now_iso()
  _touch_project_timestamp(settings, project_id, updated_at)
  _rebuild_project_knowledge(project_dir, summary.target_chapters, settings)
  refreshed_detail = _auto_refresh_system_memory(settings, project_id, focus="Obsidian 维护笔记已确认合并")
  refresh_project_narrative_state_chapter_cards(project_dir, refreshed_detail, persist=True)
  return result


def confirm_project_obsidian_maintenance_merges(
  settings: Settings,
  project_id: str,
  suggestion_ids: list[str] | None = None,
  *,
  limit: int = 80,
) -> dict[str, object]:
  summary = _project_summary_or_404(settings, project_id)
  detail = get_project_detail(settings, project_id)
  project_dir = Path(detail.path)
  result = confirm_project_obsidian_maintenance_merge_suggestions(
    project_dir,
    detail,
    suggestion_ids=suggestion_ids,
    limit=limit,
  )
  if int(result.get("confirmed_count") or 0) > 0:
    sync_obsidian_state(project_dir)
    updated_at = _now_iso()
    _touch_project_timestamp(settings, project_id, updated_at)
    _rebuild_project_knowledge(project_dir, summary.target_chapters, settings)
    refreshed_detail = _auto_refresh_system_memory(settings, project_id, focus="Obsidian 维护笔记已批量确认合并")
    refresh_project_narrative_state_chapter_cards(project_dir, refreshed_detail, persist=True)
  return result


def ignore_project_obsidian_maintenance_note(
  settings: Settings,
  project_id: str,
  suggestion_id: str,
) -> dict[str, object]:
  detail = get_project_detail(settings, project_id)
  return ignore_project_obsidian_maintenance_suggestion(Path(detail.path), detail, suggestion_id)


def ignore_project_obsidian_maintenance_notes(
  settings: Settings,
  project_id: str,
  suggestion_ids: list[str] | None = None,
  *,
  limit: int = 80,
) -> dict[str, object]:
  detail = get_project_detail(settings, project_id)
  return ignore_project_obsidian_maintenance_suggestions(
    Path(detail.path),
    detail,
    suggestion_ids=suggestion_ids,
    limit=limit,
  )


def reopen_project_obsidian_maintenance_note(
  settings: Settings,
  project_id: str,
  suggestion_id: str,
) -> dict[str, object]:
  detail = get_project_detail(settings, project_id)
  return reopen_project_obsidian_maintenance_suggestion(Path(detail.path), detail, suggestion_id)


def reopen_project_obsidian_maintenance_notes(
  settings: Settings,
  project_id: str,
  suggestion_ids: list[str] | None = None,
  *,
  limit: int = 80,
) -> dict[str, object]:
  detail = get_project_detail(settings, project_id)
  return reopen_project_obsidian_maintenance_suggestions(
    Path(detail.path),
    detail,
    suggestion_ids=suggestion_ids,
    limit=limit,
  )


def publish_project_obsidian_maintenance_note(
  settings: Settings,
  project_id: str,
  suggestion_id: str,
) -> dict[str, object]:
  summary = _project_summary_or_404(settings, project_id)
  detail = get_project_detail(settings, project_id)
  project_dir = Path(detail.path)
  result = publish_project_obsidian_maintenance_suggestion(project_dir, detail, suggestion_id)
  sync_obsidian_state(project_dir)
  updated_at = _now_iso()
  _touch_project_timestamp(settings, project_id, updated_at)
  _rebuild_project_knowledge(project_dir, summary.target_chapters, settings)
  refreshed_detail = _auto_refresh_system_memory(settings, project_id, focus="Obsidian 维护笔记已发布")
  refresh_project_narrative_state_chapter_cards(project_dir, refreshed_detail, persist=True)
  return result


def publish_project_obsidian_maintenance_notes(
  settings: Settings,
  project_id: str,
  suggestion_ids: list[str] | None = None,
  *,
  limit: int = 80,
) -> dict[str, object]:
  summary = _project_summary_or_404(settings, project_id)
  detail = get_project_detail(settings, project_id)
  project_dir = Path(detail.path)
  result = publish_project_obsidian_maintenance_suggestions(
    project_dir,
    detail,
    suggestion_ids=suggestion_ids,
    limit=limit,
  )
  if int(result.get("published_count") or 0) > 0:
    sync_obsidian_state(project_dir)
    updated_at = _now_iso()
    _touch_project_timestamp(settings, project_id, updated_at)
    _rebuild_project_knowledge(project_dir, summary.target_chapters, settings)
    refreshed_detail = _auto_refresh_system_memory(settings, project_id, focus="Obsidian 维护笔记已批量发布")
    refresh_project_narrative_state_chapter_cards(project_dir, refreshed_detail, persist=True)
  return result


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
  try:
    from novel_backend.services.project_auxiliary_service import enqueue_project_auxiliary_tasks

    enqueue_project_auxiliary_tasks(settings, project_id, tasks=["humanize_review"], reason="dream")
  except Exception as error:
    append_app_log(settings, f"做梦后的去 AI 巡检排队失败：{error}", level="WARNING")
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


def save_story_document_incremental(
  settings: Settings,
  project_id: str,
  document_key: str,
  content: str,
) -> None:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  filename, _key, _label = _story_document_spec_or_404(document_key)
  atomic_write_text(project_dir / filename, content)
  _touch_project_timestamp(settings, summary.id, _now_iso())


def load_architecture_progress(settings: Settings, project_id: str) -> dict[str, object] | None:
  summary = _project_summary_or_404(settings, project_id)
  payload = read_json(_architecture_progress_path(_project_dir(summary)), None)
  if not isinstance(payload, dict):
    return None
  if payload.get("schema_version") != _ARCHITECTURE_PROGRESS_SCHEMA_VERSION:
    return None
  return payload


def save_architecture_progress(settings: Settings, project_id: str, payload: dict[str, object]) -> None:
  summary = _project_summary_or_404(settings, project_id)
  next_payload = {
    **payload,
    "schema_version": _ARCHITECTURE_PROGRESS_SCHEMA_VERSION,
    "updated_at": _now_iso(),
  }
  atomic_write_json(_architecture_progress_path(_project_dir(summary)), next_payload)


def clear_architecture_progress(settings: Settings, project_id: str) -> None:
  summary = _project_summary_or_404(settings, project_id)
  try:
    _architecture_progress_path(_project_dir(summary)).unlink()
  except FileNotFoundError:
    pass


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
    normalized_record = _normalized_agent_thread_record(item, normalized_thread_id)
    normalized_records.append(normalized_record)
    kept_ids.add(normalized_thread_id)
    atomic_write_json(
      _agent_thread_path(project_dir, normalized_thread_id),
      normalized_record.model_dump(mode="json"),
    )
    _save_agent_thread_context_index(project_dir, normalized_record)

  for path in _agent_threads_dir(project_dir).glob("*.json"):
    if path.name == "index.json":
      continue
    if path.stem not in kept_ids:
      path.unlink(missing_ok=True)

  for path in _agent_thread_context_dir(project_dir).glob("*.json"):
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


def summarize_chapter_review_status(detail: ProjectDetail, chapter_id: str, review_error: str = "") -> dict[str, object]:
  if review_error.strip():
    return {
      "ok": False,
      "message": review_error.strip(),
      "error": review_error.strip(),
    }

  review = next(
    (item for item in detail.story_overview.chapter_reviews if item.chapter_id == chapter_id),
    None,
  )
  if review is None:
    return {
      "ok": False,
      "message": "章节核验未生成报告。",
      "error": "章节核验未生成报告。",
    }

  issue_count = 0
  critical_issue_count = 0
  obsidian_required_issue_count = 0
  obsidian_forbidden_issue_count = 0
  continuity_contract_issue_count = 0
  must_repair_issue_count = 0
  for dimension in review.dimensions:
    for issue in dimension.issues:
      issue_count += 1
      level = str(issue.level or "").strip()
      title = str(issue.title or "").strip()
      must_repair = False
      if level == "critical":
        critical_issue_count += 1
        must_repair = True
      if title.startswith("缺少 Obsidian 必需设定"):
        obsidian_required_issue_count += 1
        must_repair = True
      if title.startswith("触犯 Obsidian 禁用设定"):
        obsidian_forbidden_issue_count += 1
        must_repair = True
      if title.startswith("缺少连续性合同项") or title.startswith("违背连续性合同"):
        continuity_contract_issue_count += 1
        must_repair = True
      if must_repair:
        must_repair_issue_count += 1

  label = {
    "good": "良好",
    "watch": "需关注",
    "risk": "有风险",
    "na": "未评估",
  }.get(review.status, review.status or "未评估")
  stale_note = "，报告已过期" if review.is_stale else ""
  summary = review.summary.strip()
  message = f"章节核验：{review.overall_score}/100（{label}{stale_note}）。"
  if summary:
    message = f"{message}{summary}"
  return {
    "ok": True,
    "message": message,
    "score": review.overall_score,
    "status": review.status,
    "status_label": label,
    "summary": summary,
    "is_stale": review.is_stale,
    "updated_at": review.updated_at or "",
    "issue_count": issue_count,
    "critical_issue_count": critical_issue_count,
    "obsidian_required_issue_count": obsidian_required_issue_count,
    "obsidian_forbidden_issue_count": obsidian_forbidden_issue_count,
    "continuity_contract_issue_count": continuity_contract_issue_count,
    "must_repair_issue_count": must_repair_issue_count,
  }


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
  detail, review_error = _persist_chapter_review(
    settings,
    project_id,
    project_dir,
    detail,
    chapter_id,
    style_name=request.style_name,
    failure_prefix="章节已保存，但核验失败",
  )
  try:
    record_project_style_xp_observation(
      project_dir,
      detail,
      chapter_id,
      style_name=request.style_name,
      xp_preset=request.xp_preset,
      review_error=review_error,
    )
  except Exception as error:
    append_app_log(settings, f"style/xp evolution failed for {project_id}/{chapter_id}: {error}")
  try:
    record_project_narrative_state_observation(
      project_dir,
      detail,
      chapter_id,
      settings=settings,
      review_error=review_error,
    )
  except Exception as error:
    append_app_log(settings, f"narrative state update failed for {project_id}/{chapter_id}: {error}")
  try:
    from novel_backend.services.project_auxiliary_service import enqueue_project_auxiliary_tasks

    enqueue_project_auxiliary_tasks(settings, project_id, tasks=["humanize_review"], reason=f"chapter_update:{chapter_id}")
  except Exception as error:
    append_app_log(settings, f"章节更新后的去 AI 巡检排队失败：{error}", level="WARNING")
  return detail, review_error


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
  *,
  ensure_current: bool = True,
  include_semantic: bool = True,
  chapter_index: int = 0,
) -> list[KnowledgeSearchResult]:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  if ensure_current:
    _ensure_project_knowledge_current(settings, project_dir, summary.target_chapters)
  result_limit = _knowledge_result_limit(limit)
  try:
    target_chapter = int(chapter_index or 0)
  except (TypeError, ValueError):
    target_chapter = 0
  raw_limit = _chapter_filtered_search_limit(result_limit) if target_chapter > 0 else result_limit
  hits = _search_project_knowledge(settings, project_dir, query, raw_limit, include_semantic=include_semantic)
  filtered = _filter_obsidian_search_results_for_chapter(project_dir, hits, query, chapter_index=target_chapter)
  return filtered[:result_limit]


def search_project_knowledge_evidence(
  settings: Settings,
  project_id: str,
  query: str,
  *,
  limit: int = 8,
  candidate_limit: int = 24,
  chapter_index: int = 0,
) -> list[dict[str, object]]:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  _ensure_project_knowledge_current(settings, project_dir, summary.target_chapters)
  result_limit = _knowledge_result_limit(limit)
  try:
    target_chapter = int(chapter_index or 0)
  except (TypeError, ValueError):
    target_chapter = 0
  raw_limit = _chapter_filtered_search_limit(result_limit) if target_chapter > 0 else result_limit
  hits = _search_project_knowledge_evidence(
    settings,
    project_dir,
    query,
    limit=raw_limit,
    candidate_limit=max(candidate_limit, raw_limit),
  )
  filtered = _filter_obsidian_evidence_hits_for_chapter(project_dir, hits, query, chapter_index=target_chapter)
  return filtered[:result_limit]


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


def load_project_obsidian_note_contents(
  settings: Settings,
  project_id: str,
  limit: int = 12,
  *,
  chapter_index: int = 0,
  query: str = "",
) -> list[dict[str, str]]:
  summary = _project_summary_or_404(settings, project_id)
  project_dir = _project_dir(summary)
  try:
    target_chapter = int(chapter_index or 0)
  except (TypeError, ValueError):
    target_chapter = 0
  if target_chapter > 0:
    records = scoped_obsidian_note_records_for_chapter(project_dir, target_chapter)
  else:
    records, _skipped, _warnings = collect_obsidian_note_records(project_dir)
  max_items = max(1, min(limit, 20))
  if records and (target_chapter > 0 or query.strip()):
    records_by_source_key = {
      record.summary.source_key: record
      for record in records
      if record.summary.source_key
    }
    selected_summaries = select_obsidian_notes_for_query(
      [record.summary for record in records],
      query,
      limit=max_items,
      chapter_index=target_chapter,
    )
    selected_records = [
      records_by_source_key.get(summary.source_key)
      for summary in selected_summaries
      if summary.source_key
    ]
    records = [record for record in selected_records if record is not None]
  items = [
    {
      "title": record.summary.title,
      "filename": record.summary.relative_path,
      "content": record.content,
      "updated_at": record.summary.updated_at or "",
      "source": "Obsidian",
    }
    for record in records
    if record.summary.title and record.content.strip()
  ]
  return items[:max_items]
