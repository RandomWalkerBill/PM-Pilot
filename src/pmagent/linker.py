#!/usr/bin/env python3
"""
自动双向链接工具 - 基于 A-Mem 思想 + 混合检索

功能：
1. 扫描 memory/, decisions/, research/, strategy/, prd/, context/ 目录的 Markdown 文件
2. 混合检索：向量相似度 (60%) + BM25 (25%) + 文件名匹配 (15%)
3. Evidence 引用提升：文档中 Evidence 部分引用的文件自动加入关联
4. 为新文档自动找 top-N 相关文件，更新 "Related links"
5. 双向链接：A 链接 B 时，B 也自动链接 A

用法：
    pmagent link --all-projects                    # 全量索引 + 更新链接
    pmagent link --file <path>                     # 只处理指定文件
    pmagent link --all-projects --reindex          # 重建索引（清空后重建）
    pmagent link --all-projects --dry-run          # 只显示，不写入文件
"""

import argparse
import hashlib
import re
import sqlite3
import struct
import sys
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

warnings.filterwarnings(
    "ignore",
    message=r"pkg_resources is deprecated as an API.*",
    category=UserWarning,
    module=r"jieba\._compat",
)

import jieba
import sqlite_vec
from openai import OpenAI
from rank_bm25 import BM25Okapi

from .paths import resolve_data_dir

# 配置
# 全局目录（根级别）
GLOBAL_DIRS = ["memory", "decisions", "research", "context"]
# 项目级子目录（在 projects/<project>/ 下）
PROJECT_SUBDIRS = ["strategy", "decisions", "memory", "background"]
# 需求级子目录（在 workspaces/<workspace>/ 下）
WORKSPACE_SUBDIRS = ["prd", "research", "context"]
PROJECTS_CONFIG = "config/projects.json"
EXCLUDE_PATTERNS = [
    re.compile(r".*TEMPLATE.*\.md$", re.IGNORECASE),
    re.compile(r"^README\.md$", re.IGNORECASE),
]
DB_PATH = "cache/embeddings.db"
EMBEDDING_MODEL = "openai/text-embedding-3-small"
EMBEDDING_DIM = 1536  # text-embedding-3-small 维度
TOP_N = 5  # 每个文档关联的最大相关文件数（从 3 提升到 5）
MIN_SIMILARITY = 0.5  # 最低相似度阈值（从 0.3 提升，减少噪声关联）

# 混合检索权重
WEIGHT_VECTOR = 0.60  # 向量相似度权重
WEIGHT_BM25 = 0.25    # BM25 权重
WEIGHT_FILENAME = 0.15  # 文件名匹配权重


def load_env(repo_root: Path) -> dict:
    """加载 .env 文件"""
    env = {}
    env_file = repo_root / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


def get_openai_client(env: dict) -> OpenAI:
    """创建 OpenAI 客户端（优先使用 OPENROUTER）"""
    # 优先使用 OpenRouter
    if env.get("OPENROUTER_API_KEY"):
        base_url = env.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        api_key = env.get("OPENROUTER_API_KEY")
    else:
        base_url = env.get("WEEKLY_AI_BASE_URL", "https://api.openai.com/v1")
        api_key = env.get("WEEKLY_AI_API_KEY") or env.get("OPENAI_API_KEY")
    
    if not api_key:
        raise ValueError("Missing OPENROUTER_API_KEY, WEEKLY_AI_API_KEY or OPENAI_API_KEY in .env")
    return OpenAI(base_url=base_url, api_key=api_key)


def init_db(db_path: Path) -> sqlite3.Connection:
    """初始化 SQLite-vec 数据库"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    
    # 创建表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            path TEXT PRIMARY KEY,
            content_hash TEXT,
            title TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 创建向量表（使用余弦距离）
    conn.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS doc_embeddings USING vec0(
            path TEXT PRIMARY KEY,
            embedding float[{EMBEDDING_DIM}] distance_metric=cosine
        )
    """)
    
    conn.commit()
    return conn


def content_hash(text: str) -> str:
    """计算内容哈希"""
    return hashlib.md5(text.encode()).hexdigest()


def extract_title(text: str) -> str:
    """提取 Markdown 标题"""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return ""


def serialize_f32(vec: List[float]) -> bytes:
    """将浮点数列表序列化为 bytes"""
    return struct.pack(f"{len(vec)}f", *vec)


def deserialize_f32(data: bytes) -> List[float]:
    """将 bytes 反序列化为浮点数列表"""
    n = len(data) // 4
    return list(struct.unpack(f"{n}f", data))


def get_embedding(client: OpenAI, text: str, model: str = EMBEDDING_MODEL) -> List[float]:
    """获取文本的 embedding"""
    # 截断过长文本
    text = text[:8000]
    response = client.embeddings.create(input=text, model=model)
    return response.data[0].embedding


def load_active_project(repo_root: Path) -> Optional[str]:
    """Read active project from config/projects.json"""
    config_path = repo_root / PROJECTS_CONFIG
    if not config_path.exists():
        return None
    try:
        import json
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return data.get("active_project")
    except Exception:
        return None


def resolve_scan_dirs(repo_root: Path, project: Optional[str]) -> List[str]:
    """Resolve directories to scan based on project scope."""
    dirs = list(GLOBAL_DIRS)
    if project:
        # Project-level directories
        proj_root = f"projects/{project}"
        for sub in PROJECT_SUBDIRS:
            dirs.append(f"{proj_root}/{sub}")
        # Workspace-level directories — scan linked workspaces
        ws_base = repo_root / "workspaces"
        if ws_base.exists():
            for ws_dir in sorted(ws_base.iterdir()):
                if ws_dir.is_dir():
                    req_file = ws_dir / "Requirement.md"
                    linked = False
                    if req_file.exists():
                        try:
                            content = req_file.read_text(encoding="utf-8")
                            if f"projects/{project}/" in content:
                                linked = True
                        except Exception:
                            pass
                    if linked or ws_dir.name == project:
                        for sub in WORKSPACE_SUBDIRS:
                            dirs.append(f"workspaces/{ws_dir.name}/{sub}")
    else:
        # Scan all projects + all workspaces
        proj_dir = repo_root / "projects"
        if proj_dir.exists():
            for p in sorted(proj_dir.iterdir()):
                if p.is_dir():
                    for sub in PROJECT_SUBDIRS:
                        dirs.append(f"projects/{p.name}/{sub}")
        ws_dir = repo_root / "workspaces"
        if ws_dir.exists():
            for p in sorted(ws_dir.iterdir()):
                if p.is_dir():
                    for sub in WORKSPACE_SUBDIRS:
                        dirs.append(f"workspaces/{p.name}/{sub}")
    return dirs


def scan_documents(repo_root: Path, dirs: List[str]) -> List[Path]:
    """扫描目录下的 Markdown 文件"""
    files = []
    for d in dirs:
        dir_path = repo_root / d
        if dir_path.exists():
            for f in dir_path.rglob("*.md"):
                name = f.name
                if not any(p.match(name) for p in EXCLUDE_PATTERNS):
                    files.append(f.relative_to(repo_root))
    return sorted(files)


def extract_filename_keywords(path: str) -> Set[str]:
    """从文件名提取关键词（去掉日期和扩展名）"""
    # 获取文件名
    name = Path(path).stem
    # 去掉日期前缀 (YYYY-MM-DD-)
    name = re.sub(r"^\d{4}-\d{2}-\d{2}-?", "", name)
    # 分割为关键词（按 - 和 _）
    keywords = set(re.split(r"[-_]", name.lower()))
    # 过滤空字符串和太短的词
    keywords = {k for k in keywords if len(k) >= 2}
    return keywords


def extract_evidence_refs(text: str) -> Set[str]:
    """提取 Evidence 部分引用的文件路径"""
    refs = set()
    in_evidence = False
    for line in text.splitlines():
        if re.match(r"^##\s*Evidence", line, re.IGNORECASE):
            in_evidence = True
            continue
        if in_evidence:
            if line.startswith("##"):
                break
            # 匹配 - `path` 格式
            m = re.match(r"^\s*-\s*`([^`]+\.md)`", line)
            if m:
                refs.add(m.group(1))
    return refs


def tokenize_chinese(text: str) -> List[str]:
    """中文分词（使用 jieba）"""
    # 去掉 Markdown 标记
    text = re.sub(r"[#*`\[\]()]", " ", text)
    # jieba 分词
    tokens = list(jieba.cut(text))
    # 过滤停用词和短词
    tokens = [t.lower() for t in tokens if len(t) >= 2 and not t.isspace()]
    return tokens


def build_bm25_index(doc_texts: Dict[str, str]) -> Tuple[BM25Okapi, List[str]]:
    """构建 BM25 索引"""
    paths = list(doc_texts.keys())
    tokenized_docs = [tokenize_chinese(doc_texts[p]) for p in paths]
    bm25 = BM25Okapi(tokenized_docs)
    return bm25, paths


def get_existing_links(text: str) -> Set[str]:
    """提取现有的 Related links"""
    links = set()
    in_related = False
    for line in text.splitlines():
        if re.match(r"^##\s*Related\s*links", line, re.IGNORECASE):
            in_related = True
            continue
        if in_related:
            if line.startswith("##"):
                break
            # 匹配 - `path` 或 - [text](path) 格式
            m = re.match(r"^\s*-\s*`([^`]+)`", line)
            if m:
                links.add(m.group(1))
            m = re.match(r"^\s*-\s*\[.*?\]\(([^)]+)\)", line)
            if m:
                links.add(m.group(1))
    return links


def add_related_link(text: str, link_path: str) -> str:
    """添加 Related link 到文档"""
    lines = text.splitlines()
    
    # 查找 Related links 部分
    related_idx = -1
    next_section_idx = -1
    for i, line in enumerate(lines):
        if re.match(r"^##\s*Related\s*links", line, re.IGNORECASE):
            related_idx = i
        elif related_idx >= 0 and line.startswith("##"):
            next_section_idx = i
            break
    
    new_link = f"- `{link_path}`"
    
    if related_idx == -1:
        # 没有 Related links 部分，在末尾添加
        lines.append("")
        lines.append("## Related links")
        lines.append("")
        lines.append(new_link)
    else:
        # 在 Related links 部分末尾或下一个 section 之前插入
        if next_section_idx == -1:
            # 没有下一个 section，在末尾添加
            lines.append(new_link)
        else:
            # 在下一个 section 之前插入
            lines.insert(next_section_idx, new_link)
    
    return "\n".join(lines)


def index_documents(
    conn: sqlite3.Connection,
    client: OpenAI,
    repo_root: Path,
    files: List[Path],
    force: bool = False
) -> Dict[str, List[float]]:
    """索引文档，返回所有 embeddings"""
    embeddings = {}
    
    for file_path in files:
        abs_path = repo_root / file_path
        text = abs_path.read_text(encoding="utf-8")
        hash_val = content_hash(text)
        path_str = str(file_path)
        
        # 检查是否需要更新
        row = conn.execute(
            "SELECT content_hash FROM documents WHERE path = ?",
            (path_str,)
        ).fetchone()
        
        if not force and row and row[0] == hash_val:
            # 内容未变，从数据库加载 embedding
            emb_row = conn.execute(
                "SELECT embedding FROM doc_embeddings WHERE path = ?",
                (path_str,)
            ).fetchone()
            if emb_row:
                embeddings[path_str] = deserialize_f32(emb_row[0])
                print(f"  [cached] {file_path}")
                continue
        
        # 需要重新计算 embedding
        print(f"  [embed]  {file_path}")
        try:
            emb = get_embedding(client, text)
            embeddings[path_str] = emb
            
            # 更新数据库
            title = extract_title(text)
            conn.execute("""
                INSERT OR REPLACE INTO documents (path, content_hash, title)
                VALUES (?, ?, ?)
            """, (path_str, hash_val, title))
            
            conn.execute("""
                INSERT OR REPLACE INTO doc_embeddings (path, embedding)
                VALUES (?, ?)
            """, (path_str, serialize_f32(emb)))
            
            conn.commit()
        except Exception as e:
            print(f"  [error]  {file_path}: {e}")
    
    return embeddings


def find_related(
    conn: sqlite3.Connection,
    target_path: str,
    embeddings: Dict[str, List[float]],
    top_n: int = TOP_N,
    min_sim: float = MIN_SIMILARITY
) -> List[Tuple[str, float]]:
    """找到与目标文档最相关的文档（纯向量检索，已废弃，保留兼容）"""
    if target_path not in embeddings:
        return []
    
    target_emb = embeddings[target_path]
    
    # 使用 sqlite-vec 进行相似度搜索（vec0 需要 k = ? 约束）
    results = conn.execute("""
        SELECT path, distance
        FROM doc_embeddings
        WHERE embedding MATCH ?
        AND k = ?
        ORDER BY distance
    """, (serialize_f32(target_emb), top_n + 10)).fetchall()
    
    # 转换距离为相似度 (cosine distance -> similarity)，排除自身
    related = []
    for path, distance in results:
        if path == target_path:
            continue
        similarity = 1 - distance  # vec0 返回的是距离，需要转换
        if similarity >= min_sim and len(related) < top_n:
            related.append((path, similarity))
    
    return related


def find_related_hybrid(
    conn: sqlite3.Connection,
    target_path: str,
    target_text: str,
    embeddings: Dict[str, List[float]],
    doc_texts: Dict[str, str],
    bm25: BM25Okapi,
    bm25_paths: List[str],
    top_n: int = TOP_N,
    min_sim: float = MIN_SIMILARITY
) -> List[Tuple[str, float]]:
    """混合检索：向量相似度 + BM25 + 文件名匹配"""
    if target_path not in embeddings:
        return []
    
    scores: Dict[str, float] = {}
    all_paths = list(embeddings.keys())
    
    # === 1. 向量相似度 (权重 60%) ===
    target_emb = embeddings[target_path]
    results = conn.execute("""
        SELECT path, distance
        FROM doc_embeddings
        WHERE embedding MATCH ?
        AND k = ?
        ORDER BY distance
    """, (serialize_f32(target_emb), len(all_paths))).fetchall()
    
    for path, distance in results:
        if path == target_path:
            continue
        similarity = 1 - distance
        scores[path] = similarity * WEIGHT_VECTOR
    
    # === 2. BM25 (权重 25%) ===
    query_tokens = tokenize_chinese(target_text)
    bm25_scores = bm25.get_scores(query_tokens)
    
    # 归一化 BM25 分数到 [0, 1]
    max_bm25 = max(bm25_scores) if max(bm25_scores) > 0 else 1
    for i, path in enumerate(bm25_paths):
        if path == target_path:
            continue
        normalized_score = bm25_scores[i] / max_bm25
        scores[path] = scores.get(path, 0) + normalized_score * WEIGHT_BM25
    
    # === 3. 文件名匹配 (权重 15%) ===
    target_keywords = extract_filename_keywords(target_path)
    if target_keywords:
        for path in all_paths:
            if path == target_path:
                continue
            doc_keywords = extract_filename_keywords(path)
            if doc_keywords:
                overlap = len(target_keywords & doc_keywords) / len(target_keywords)
                if overlap > 0:
                    scores[path] = scores.get(path, 0) + overlap * WEIGHT_FILENAME
    
    # === 4. Evidence 引用提升 ===
    evidence_refs = extract_evidence_refs(target_text)
    for ref in evidence_refs:
        if ref in all_paths and ref != target_path:
            # 直接引用的文件，保证进入 top-n
            scores[ref] = scores.get(ref, 0) + 0.5  # 额外加 0.5 分
    
    # 排序并过滤
    sorted_scores = sorted(scores.items(), key=lambda x: -x[1])
    
    related = []
    for path, score in sorted_scores:
        if score >= min_sim and len(related) < top_n:
            related.append((path, score))
    
    return related


def update_links(
    repo_root: Path,
    source_path: str,
    target_paths: List[str],
    dry_run: bool = False
) -> Tuple[int, int]:
    """更新双向链接，返回 (新增链接数, 修改文件数)"""
    added = 0
    modified_files = set()
    
    for target_path in target_paths:
        # 正向链接：source -> target
        source_file = repo_root / source_path
        source_text = source_file.read_text(encoding="utf-8")
        existing = get_existing_links(source_text)
        
        if target_path not in existing:
            new_text = add_related_link(source_text, target_path)
            if not dry_run:
                source_file.write_text(new_text, encoding="utf-8")
            added += 1
            modified_files.add(source_path)
            print(f"    {source_path} -> {target_path}")
        
        # 反向链接：target -> source
        target_file = repo_root / target_path
        if target_file.exists():
            target_text = target_file.read_text(encoding="utf-8")
            existing = get_existing_links(target_text)
            
            if source_path not in existing:
                new_text = add_related_link(target_text, source_path)
                if not dry_run:
                    target_file.write_text(new_text, encoding="utf-8")
                added += 1
                modified_files.add(target_path)
                print(f"    {target_path} -> {source_path} (反向)")
    
    return added, len(modified_files)


def main():
    parser = argparse.ArgumentParser(description="自动双向链接工具（混合检索）")
    parser.add_argument("--file", type=str, help="只处理指定文件")
    parser.add_argument("--project", type=str, default=None,
                        help="Project name to scope scanning (default: active project from config)")
    parser.add_argument("--all-projects", action="store_true",
                        help="Scan all projects (default if no --project)")
    parser.add_argument("--reindex", action="store_true", help="重建索引")
    parser.add_argument("--dry-run", action="store_true", help="只显示，不写入")
    parser.add_argument("--repo-root", type=str, default=None,
                        help="PM Agent data directory (default: resolve from config)")
    parser.add_argument("--top-n", type=int, default=TOP_N, help=f"每个文档关联数 (default: {TOP_N})")
    parser.add_argument("--min-sim", type=float, default=MIN_SIMILARITY, help=f"最低相似度 (default: {MIN_SIMILARITY})")
    parser.add_argument("--legacy", action="store_true", help="使用旧版纯向量检索")
    args = parser.parse_args()
    
    if args.repo_root:
        repo_root = Path(args.repo_root).resolve()
    else:
        repo_root = resolve_data_dir()
    
    db_path = repo_root / DB_PATH
    
    # Resolve project scope
    project = args.project
    if not project and not args.all_projects:
        project = load_active_project(repo_root)
    
    scan_dirs = resolve_scan_dirs(repo_root, project if not args.all_projects else None)
    
    # 加载环境变量
    env = load_env(repo_root)
    
    # 初始化
    print("初始化...")
    client = get_openai_client(env)
    
    if args.reindex and db_path.exists():
        print("  删除旧索引")
        db_path.unlink()
    
    conn = init_db(db_path)
    
    # 扫描文档
    print(f"\n扫描文档... (project: {project or 'all'})")
    files = scan_documents(repo_root, scan_dirs)
    print(f"  找到 {len(files)} 个文件")
    
    # 如果指定了文件，只处理该文件
    if args.file:
        target = Path(args.file)
        if not target.is_absolute():
            target = (repo_root / target).resolve().relative_to(repo_root)
        if target not in files:
            files.append(target)
    
    # 索引文档（向量 embedding）
    print("\n索引文档...")
    embeddings = index_documents(conn, client, repo_root, files, force=args.reindex)
    
    # 加载所有文档内容（用于 BM25）
    print("\n构建 BM25 索引...")
    doc_texts: Dict[str, str] = {}
    for file_path in files:
        path_str = str(file_path)
        abs_path = repo_root / file_path
        if abs_path.exists():
            doc_texts[path_str] = abs_path.read_text(encoding="utf-8")
    
    # 构建 BM25 索引
    bm25, bm25_paths = build_bm25_index(doc_texts)
    print(f"  BM25 索引完成，{len(bm25_paths)} 个文档")
    
    # 计算相关性并更新链接
    print("\n更新链接...")
    if not args.legacy:
        print(f"  使用混合检索：向量({WEIGHT_VECTOR:.0%}) + BM25({WEIGHT_BM25:.0%}) + 文件名({WEIGHT_FILENAME:.0%})")
    
    total_added = 0
    total_modified = 0
    
    files_to_process = [Path(args.file)] if args.file else files
    
    for file_path in files_to_process:
        path_str = str(file_path)
        
        if args.legacy:
            # 旧版：纯向量检索
            related = find_related(conn, path_str, embeddings, args.top_n, args.min_sim)
        else:
            # 新版：混合检索
            target_text = doc_texts.get(path_str, "")
            related = find_related_hybrid(
                conn, path_str, target_text, embeddings, doc_texts,
                bm25, bm25_paths, args.top_n, args.min_sim
            )
        
        if related:
            print(f"\n  {file_path}:")
            for rel_path, sim in related:
                print(f"    -> {rel_path} ({sim:.3f})")
            
            # 更新链接
            target_paths = [r[0] for r in related]
            added, modified = update_links(repo_root, path_str, target_paths, args.dry_run)
            total_added += added
            total_modified += modified
    
    # 总结
    print(f"\n完成！")
    print(f"  索引文档：{len(embeddings)}")
    print(f"  新增链接：{total_added}")
    print(f"  修改文件：{total_modified}")
    
    if args.dry_run:
        print("  (dry-run 模式，未实际写入)")
    
    conn.close()


if __name__ == "__main__":
    main()
