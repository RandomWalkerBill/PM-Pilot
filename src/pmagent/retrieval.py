#!/usr/bin/env python3
"""
仓库证据链检索（Hybrid Retrieval）— 借鉴 OpenClaw QMD 混合搜索架构

检索模式：
  hybrid（默认）：向量语义 55% + BM25 关键词 30% + 文件名匹配 15%
  bm25：纯 BM25（无需 API key / embeddings DB）
  vector：纯向量语义

特性：
  - 复用 auto_link.py 的 SQLite-vec 向量索引（cache/embeddings.db）
  - 查询向量 on-the-fly（1 次 embedding API 调用）
  - 优雅降级：缺 DB / API key 时自动回退到纯 BM25
  - jieba 中文分词（可选，回退到字符级分词）
  - 默认搜索 memory/ decisions/ research/ strategy/ prd/ context/

用法：
  pmagent retrieve --query "记忆系统设计"
  pmagent retrieve --query "DevOps 对接" --mode hybrid
  pmagent retrieve --query "PRD template" --mode bm25
  pmagent retrieve --query "蓝鲸" --top-k 5 --out /tmp/result.md
"""

import argparse
import datetime as dt
import math
import re
import struct
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .paths import resolve_data_dir

warnings.filterwarnings(
    "ignore",
    message=r"pkg_resources is deprecated as an API.*",
    category=UserWarning,
    module=r"jieba\._compat",
)

# ── 可选依赖（优雅降级）──────────────────────────────────
try:
    import jieba
    _HAS_JIEBA = True
except ImportError:
    _HAS_JIEBA = False

try:
    import sqlite3
    import sqlite_vec
    _HAS_SQLITE_VEC = True
except ImportError:
    _HAS_SQLITE_VEC = False

try:
    from openai import OpenAI
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False


# ── 配置 ──────────────────────────────────────────────────
# 全局目录（根级别）
GLOBAL_DIRS = ["memory", "decisions", "research", "context"]
# 项目级子目录（在 projects/<project>/ 下）
PROJECT_SUBDIRS = ["strategy", "decisions", "memory", "background"]
# 需求级子目录（在 workspaces/<workspace>/ 下）
WORKSPACE_SUBDIRS = ["prd", "research", "context"]
DB_PATH = "cache/embeddings.db"
PROJECTS_CONFIG = "config/projects.json"
EMBEDDING_MODEL = "openai/text-embedding-3-small"
EMBEDDING_DIM = 1536

# 混合检索权重
W_VECTOR = 0.55
W_BM25 = 0.30
W_FILENAME = 0.15
W_MEMORY_BOOST = 1.30  # 针对 memory 核心认知文件的提权因子

EXCLUDE_NAME_PATTERNS = [
    re.compile(r".*TEMPLATE.*\.md$", re.IGNORECASE),
    re.compile(r"^README\.md$", re.IGNORECASE),
]

WORD_RE = re.compile(r"[A-Za-z0-9]+")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


# ── 工具函数 ──────────────────────────────────────────────
def tokenize_simple(text: str) -> List[str]:
    """简单分词：英文单词 + CJK 单字"""
    if not text:
        return []
    text = text.lower()
    tokens: List[str] = []
    tokens.extend(WORD_RE.findall(text))
    tokens.extend(CJK_RE.findall(text))
    return tokens


def tokenize_jieba(text: str) -> List[str]:
    """jieba 分词：更好的中文分词效果"""
    if not text:
        return []
    text = re.sub(r"[#*`\[\]()]", " ", text)
    tokens = list(jieba.cut(text))
    return [t.lower() for t in tokens if len(t) >= 2 and not t.isspace()]


def tokenize(text: str) -> List[str]:
    """自动选择最佳分词器"""
    if _HAS_JIEBA:
        return tokenize_jieba(text)
    return tokenize_simple(text)


def extract_title(md_text: str) -> Optional[str]:
    for line in (md_text or "").splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip() or None
    return None


def find_snippet(md_text: str, query_terms: Sequence[str], width: int = 240) -> str:
    s = (md_text or "").replace("\r\n", "\n")
    s_compact = re.sub(r"\s+", " ", s).strip()
    if not s_compact:
        return ""
    if not query_terms:
        return s_compact[:width] + ("…" if len(s_compact) > width else "")

    lowered = s_compact.lower()
    positions: List[int] = []
    for t in query_terms:
        if not t:
            continue
        i = lowered.find(t.lower())
        if i >= 0:
            positions.append(i)
    if not positions:
        return s_compact[:width] + ("…" if len(s_compact) > width else "")

    pos = min(positions)
    start = max(0, pos - width // 3)
    end = min(len(s_compact), start + width)
    snippet = s_compact[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(s_compact):
        snippet = snippet + "…"
    return snippet


def extract_filename_keywords(path: str) -> Set[str]:
    """从文件路径提取关键词"""
    name = Path(path).stem
    name = re.sub(r"^\d{4}-\d{2}-\d{2}-?", "", name)
    keywords = set(re.split(r"[-_]", name.lower()))
    return {k for k in keywords if len(k) >= 2}


def serialize_f32(vec: List[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def deserialize_f32(data: bytes) -> List[float]:
    n = len(data) // 4
    return list(struct.unpack(f"{n}f", data))


# ── Env / OpenAI ──────────────────────────────────────────
def load_env(repo_root: Path) -> dict:
    env = {}
    env_file = repo_root / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


def get_openai_client(env: dict) -> Optional["OpenAI"]:
    if not _HAS_OPENAI:
        return None
    if env.get("OPENROUTER_API_KEY"):
        base_url = env.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        api_key = env.get("OPENROUTER_API_KEY")
    else:
        base_url = env.get("WEEKLY_AI_BASE_URL", "https://api.openai.com/v1")
        api_key = env.get("WEEKLY_AI_API_KEY") or env.get("OPENAI_API_KEY")
    if not api_key:
        return None
    return OpenAI(base_url=base_url, api_key=api_key)


def get_query_embedding(client: "OpenAI", text: str) -> Optional[List[float]]:
    try:
        text = text[:8000]
        resp = client.embeddings.create(input=text, model=EMBEDDING_MODEL)
        return resp.data[0].embedding
    except Exception as e:
        print(f"[warn] embedding 失败，回退 BM25: {e}", file=sys.stderr)
        return None


# ── Doc 模型 ──────────────────────────────────────────────
@dataclass
class Doc:
    path: Path
    text: str
    title: Optional[str]
    tokens: List[str]


def resolve_search_dirs(
    repo_root: Path,
    project: Optional[str],
    explicit_dirs: Optional[str],
) -> List[str]:
    """Resolve search directories based on project scope.
    
    If --project is given: search global dirs + projects/<project>/ subdirs + linked workspaces
    If --dirs is explicitly given: use those directly
    Otherwise: search global dirs only (backward compat)
    """
    if explicit_dirs:
        return [d.strip() for d in explicit_dirs.split(",") if d.strip()]
    
    dirs = list(GLOBAL_DIRS)
    if project:
        # Project-level directories
        proj_root = f"projects/{project}"
        for sub in PROJECT_SUBDIRS:
            dirs.append(f"{proj_root}/{sub}")
        # Workspace-level directories — scan all workspaces linked to this project
        ws_base = repo_root / "workspaces"
        if ws_base.exists():
            for ws_dir in ws_base.iterdir():
                if ws_dir.is_dir():
                    req_file = ws_dir / "Requirement.md"
                    # Include workspace if it links to this project or shares the name
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
    return dirs


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


def load_docs(
    repo_root: Path,
    dirs: Sequence[str],
    include_root_memory: bool,
    include_templates: bool,
) -> List[Doc]:
    files: List[Path] = []
    for d in dirs:
        p = (repo_root / d).resolve()
        if p.exists() and p.is_dir():
            files.extend(sorted(p.rglob("*.md")))
    if include_root_memory:
        p = repo_root / "MEMORY.md"
        if p.exists():
            files.append(p.resolve())

    docs: List[Doc] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        name = f.name
        if not include_templates:
            if any(pat.match(name) for pat in EXCLUDE_NAME_PATTERNS):
                continue
        rel = f.relative_to(repo_root)
        docs.append(Doc(path=rel, text=text, title=extract_title(text), tokens=tokenize(text)))
    return docs


# ── 评分引擎 ──────────────────────────────────────────────
def score_bm25(
    docs: List[Doc],
    query_tokens: List[str],
    k1: float = 1.5,
    b: float = 0.75,
) -> Dict[int, float]:
    """经典 BM25，返回 {doc_index: score}"""
    if not docs or not query_tokens:
        return {}

    df: Dict[str, int] = {}
    doc_tfs: List[Dict[str, int]] = []
    lengths: List[int] = []

    for doc in docs:
        tf: Dict[str, int] = {}
        for t in doc.tokens:
            tf[t] = tf.get(t, 0) + 1
        doc_tfs.append(tf)
        lengths.append(len(doc.tokens))
        for t in tf:
            df[t] = df.get(t, 0) + 1

    avgdl = sum(lengths) / max(1, len(lengths))
    N = len(docs)

    qtf: Dict[str, int] = {}
    for t in query_tokens:
        qtf[t] = qtf.get(t, 0) + 1

    scores: Dict[int, float] = {}
    for idx, doc in enumerate(docs):
        tf = doc_tfs[idx]
        dl = lengths[idx]
        score = 0.0
        for term, qt in qtf.items():
            if term not in tf:
                continue
            n_q = df.get(term, 0)
            idf = math.log(1.0 + (N - n_q + 0.5) / (n_q + 0.5))
            f = tf[term]
            denom = f + k1 * (1.0 - b + b * (dl / avgdl))
            score += (idf * (f * (k1 + 1.0)) / denom) * (1.0 + math.log(1 + qt))
        if score > 0:
            scores[idx] = score
    return scores


def score_vector(
    repo_root: Path,
    query_emb: List[float],
    doc_paths: List[str],
    top_n: int = 50,
) -> Dict[str, float]:
    """从 auto_link.py 的 SQLite-vec DB 查询向量相似度"""
    if not _HAS_SQLITE_VEC:
        return {}
    db_path = repo_root / DB_PATH
    if not db_path.exists():
        return {}

    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    try:
        results = conn.execute(
            """
            SELECT path, distance
            FROM doc_embeddings
            WHERE embedding MATCH ?
            AND k = ?
            ORDER BY distance
            """,
            (serialize_f32(query_emb), top_n),
        ).fetchall()
    except Exception:
        conn.close()
        return {}

    conn.close()
    path_set = set(doc_paths)
    sim_map: Dict[str, float] = {}
    for path, distance in results:
        if path in path_set:
            sim_map[path] = max(0.0, 1.0 - distance)  # cosine distance → similarity
    return sim_map


def score_filename(query_tokens: List[str], doc_paths: List[str]) -> Dict[str, float]:
    """文件名关键词匹配评分"""
    query_kw = set(query_tokens)
    if not query_kw:
        return {}
    result: Dict[str, float] = {}
    for p in doc_paths:
        kws = extract_filename_keywords(p)
        if kws:
            overlap = len(query_kw & kws) / max(1, len(query_kw))
            if overlap > 0:
                result[p] = overlap
    return result


def hybrid_rank(
    docs: List[Doc],
    query_tokens: List[str],
    query_emb: Optional[List[float]],
    repo_root: Path,
    mode: str = "hybrid",
) -> List[Tuple[float, Doc]]:
    """统一排序入口，按 mode 决定评分策略"""
    doc_paths = [doc.path.as_posix() for doc in docs]

    # ── BM25 ──
    bm25_raw = score_bm25(docs, query_tokens)
    max_bm25 = max(bm25_raw.values()) if bm25_raw else 1.0

    # ── Vector ──
    vec_scores: Dict[str, float] = {}
    if mode in ("hybrid", "vector") and query_emb is not None:
        vec_scores = score_vector(repo_root, query_emb, doc_paths)

    # ── Filename ──
    fn_scores: Dict[str, float] = {}
    if mode in ("hybrid",):
        fn_scores = score_filename(query_tokens, doc_paths)

    # ── 合成 ──
    final: Dict[int, float] = {}
    for idx, doc in enumerate(docs):
        p = doc.path.as_posix()
        s = 0.0

        if mode == "bm25":
            s = bm25_raw.get(idx, 0.0)
        elif mode == "vector":
            s = vec_scores.get(p, 0.0)
        else:  # hybrid
            bm25_norm = (bm25_raw.get(idx, 0.0) / max_bm25) if max_bm25 > 0 else 0.0
            s += bm25_norm * W_BM25
            s += vec_scores.get(p, 0.0) * W_VECTOR
            s += fn_scores.get(p, 0.0) * W_FILENAME

        # 核心认知防遗忘：针对 memory 类型的原子化文件提权
        if "memory/" in p or p.endswith("MEMORY.md"):
            s *= W_MEMORY_BOOST

        if s > 0:
            final[idx] = s

    ranked = sorted(((s, docs[i]) for i, s in final.items()), key=lambda x: x[0], reverse=True)
    return ranked


# ── 输出 ──────────────────────────────────────────────────
def render_markdown(
    *,
    query: str,
    searched_dirs: Sequence[str],
    mode: str,
    matches: List[Tuple[float, Doc]],
    query_terms_for_snippet: Sequence[str],
) -> str:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: List[str] = []
    lines.append(f"# Context Retrieval - {dt.date.today().strftime('%Y-%m-%d')}")
    lines.append("")
    lines.append(f"> 生成时间：{now}")
    lines.append("")
    lines.append(f"- 查询：`{query}`")
    lines.append(f"- 模式：`{mode}`")
    lines.append(f"- 范围：{', '.join(searched_dirs)}")
    lines.append("")
    lines.append("## Top Matches")
    lines.append("")
    if not matches:
        lines.append("- （无匹配）")
        return "\n".join(lines).rstrip() + "\n"

    for i, (score, doc) in enumerate(matches, start=1):
        title = doc.title or doc.path.as_posix()
        snippet = find_snippet(doc.text, query_terms_for_snippet, width=260)
        lines.append(f"{i}. `{doc.path.as_posix()}` (score: {score:.3f})")
        lines.append(f"   - 标题：{title}")
        if snippet:
            lines.append(f"   - 摘要片段：{snippet}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ── CLI ───────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Hybrid context retrieval: vector (55%) + BM25 (30%) + filename (15%). "
                    "Graceful fallback to BM25-only when embeddings unavailable."
    )
    p.add_argument("--query", required=True, help="Query text (Chinese/English)")
    p.add_argument("--mode", choices=["hybrid", "bm25", "vector"], default="hybrid",
                   help="Retrieval mode (default: hybrid)")
    p.add_argument("--repo-root", default=None,
                   help="PM Agent data directory (default: resolve from config)")
    p.add_argument("--project", default=None,
                   help="Project name to scope search (default: active project from config)")
    p.add_argument("--dirs", default=None,
                   help="Comma-separated dirs (overrides --project scoping)")
    p.add_argument("--global-only", action="store_true",
                   help="Search only global dirs, ignore project scope")
    p.add_argument("--top-k", type=int, default=8, help="Top K matches (default: 8)")
    p.add_argument("--include-memory-index", action="store_true", help="Also include root MEMORY.md")
    p.add_argument("--include-templates", action="store_true", help="Include template files")
    p.add_argument("--out", default=None, help="Write markdown to path (default: stdout)")
    return p


def main() -> int:
    args = build_parser().parse_args()
    if args.repo_root:
        repo_root = Path(args.repo_root).resolve()
    else:
        repo_root = resolve_data_dir()
    
    # Resolve project scope
    project = args.project
    if not project and not args.dirs and not args.global_only:
        project = load_active_project(repo_root)
    
    dirs = resolve_search_dirs(repo_root, project, args.dirs)
    if args.global_only:
        dirs = list(GLOBAL_DIRS)
    
    mode = args.mode

    query = args.query.strip()
    query_tokens = tokenize(query)
    # For snippet matching: use unique terms, keep longer ones first
    snippet_terms = sorted(set(query_tokens), key=lambda x: (-len(x), x))[:20]

    docs = load_docs(
        repo_root=repo_root,
        dirs=dirs,
        include_root_memory=bool(args.include_memory_index),
        include_templates=bool(args.include_templates),
    )

    # ── 获取查询向量（hybrid / vector 模式）──
    query_emb: Optional[List[float]] = None
    actual_mode = mode

    if mode in ("hybrid", "vector"):
        env = load_env(repo_root)
        client = get_openai_client(env)
        if client:
            query_emb = get_query_embedding(client, query)
        if query_emb is None and mode == "hybrid":
            print("[info] 向量不可用，回退到 BM25 模式", file=sys.stderr)
            actual_mode = "bm25"
        elif query_emb is None and mode == "vector":
            print("[error] vector 模式需要 embedding，但获取失败", file=sys.stderr)
            return 1

    # ── 排序 ──
    ranked = hybrid_rank(docs, query_tokens, query_emb, repo_root, actual_mode)
    ranked = ranked[: max(1, args.top_k)]

    md = render_markdown(
        query=query,
        searched_dirs=dirs + (["MEMORY.md"] if args.include_memory_index else []),
        mode=actual_mode,
        matches=ranked,
        query_terms_for_snippet=snippet_terms,
    )

    if args.out:
        out_path = Path(args.out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        print(str(out_path))
    else:
        print(md, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
