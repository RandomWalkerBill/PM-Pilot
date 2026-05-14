#!/usr/bin/env python3
"""
冲突检测脚本：检测新 note 与既有 notes 之间的潜在冲突

用法：
  pmagent conflicts --new memory/persona/2026-03-04-new-note.md
  pmagent conflicts --all  # 检测所有 notes 之间的冲突
  pmagent conflicts --new memory/persona/xxx.md --threshold 0.6
"""

import argparse
import os
import re
import sys
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import Counter
import math

from .paths import resolve_data_dir


# 中文分词简单实现（基于字符 n-gram + 关键词）
STOP_WORDS = {
    "的", "是", "在", "和", "了", "与", "或", "等", "及", "被", "把", "让", "给",
    "到", "从", "对", "为", "以", "可", "能", "会", "要", "将", "就", "都", "也",
    "而", "但", "如", "若", "则", "之", "其", "这", "那", "有", "无", "不", "没",
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "shall", "can", "need", "to", "of",
    "in", "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "and", "or", "but", "if", "then", "else", "when", "where", "which", "that",
}

# 矛盾指示词
CONTRADICTION_MARKERS = [
    ("不是", "是"), ("不要", "要"), ("不能", "能"), ("不应", "应"),
    ("避免", "使用"), ("禁止", "允许"), ("废弃", "推荐"),
    ("should not", "should"), ("don't", "do"), ("never", "always"),
    ("avoid", "use"), ("deprecated", "recommended"), ("禁", "允"),
    ("否", "是"), ("反对", "支持"), ("拒绝", "接受"),
]


def tokenize(text: str) -> List[str]:
    """简单分词：中文按字符 + 双字词，英文按单词"""
    text = text.lower()
    # 提取英文单词
    english_words = re.findall(r'[a-z]+', text)
    # 提取中文字符
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
    # 生成中文双字词
    chinese_bigrams = [chinese_chars[i] + chinese_chars[i+1] 
                       for i in range(len(chinese_chars) - 1)]
    
    tokens = english_words + chinese_chars + chinese_bigrams
    # 过滤停用词
    tokens = [t for t in tokens if t not in STOP_WORDS and len(t) > 0]
    return tokens


def extract_claim(content: str) -> str:
    """从 note 内容中提取核心主张（Claim 部分）"""
    lines = content.split('\n')
    claim_section = []
    in_claim = False
    
    for line in lines:
        # 检测 Claim 部分开始
        if re.match(r'^##?\s*(核心主张|Claim|主张)', line, re.IGNORECASE):
            in_claim = True
            continue
        # 检测下一个章节开始
        if in_claim and re.match(r'^##?\s+\S', line):
            break
        if in_claim:
            claim_section.append(line)
    
    # 如果没找到 Claim 部分，取标题和前 500 字符
    if not claim_section:
        # 尝试提取标题
        title_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        title = title_match.group(1) if title_match else ""
        return title + " " + content[:500]
    
    return '\n'.join(claim_section).strip()


def compute_tfidf(docs: List[List[str]]) -> Tuple[List[Dict[str, float]], Dict[str, float]]:
    """计算 TF-IDF"""
    # 计算 IDF
    doc_count = len(docs)
    df = Counter()
    for doc in docs:
        unique_tokens = set(doc)
        for token in unique_tokens:
            df[token] += 1
    
    idf = {token: math.log(doc_count / (count + 1)) + 1 
           for token, count in df.items()}
    
    # 计算 TF-IDF 向量
    tfidf_vectors = []
    for doc in docs:
        tf = Counter(doc)
        total = len(doc) if doc else 1
        vector = {token: (count / total) * idf.get(token, 1) 
                  for token, count in tf.items()}
        tfidf_vectors.append(vector)
    
    return tfidf_vectors, idf


def cosine_similarity(vec1: Dict[str, float], vec2: Dict[str, float]) -> float:
    """计算余弦相似度"""
    if not vec1 or not vec2:
        return 0.0
    
    # 交集
    common_keys = set(vec1.keys()) & set(vec2.keys())
    
    dot_product = sum(vec1[k] * vec2[k] for k in common_keys)
    norm1 = math.sqrt(sum(v ** 2 for v in vec1.values()))
    norm2 = math.sqrt(sum(v ** 2 for v in vec2.values()))
    
    if norm1 == 0 or norm2 == 0:
        return 0.0
    
    return dot_product / (norm1 * norm2)


def detect_contradiction_signals(text1: str, text2: str) -> List[str]:
    """检测矛盾信号"""
    signals = []
    text1_lower = text1.lower()
    text2_lower = text2.lower()
    
    for neg, pos in CONTRADICTION_MARKERS:
        # 一个文本有否定，另一个有肯定
        if neg in text1_lower and pos in text2_lower:
            signals.append(f"'{neg}' vs '{pos}'")
        if pos in text1_lower and neg in text2_lower:
            signals.append(f"'{pos}' vs '{neg}'")
    
    return signals


def llm_judge_conflict(claim1: str, claim2: str, path1: str, path2: str) -> Optional[Dict]:
    """用 LLM 判断两个决策/记忆是否存在策略冲突。
    
    Returns None if LLM unavailable, otherwise:
    {"conflict": bool, "type": str, "reason": str}
    """
    try:
        from openai import OpenAI
    except ImportError:
        return None
    
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    
    client = OpenAI(api_key=api_key)
    
    prompt = f"""你是一个产品决策审计员。请判断以下两段内容是否存在冲突。

文档 A ({Path(path1).name}):
{claim1[:500]}

文档 B ({Path(path2).name}):
{claim2[:500]}

冲突类型定义：
- 策略矛盾：两个决策的方向或结论互相矛盾
- 范围漂移：一个文档的scope超出了另一个文档定义的边界
- 信息过期：一个文档的结论已被另一个文档的更新内容替代

请严格按 JSON 格式返回（不要 markdown 代码块）：
{{"conflict": true/false, "type": "策略矛盾|范围漂移|信息过期|无冲突", "reason": "一句话说明"}}"""

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=200,
        )
        text = resp.choices[0].message.content.strip()
        # 尝试提取 JSON（兼容 markdown 代码块）
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        return json.loads(text)
    except Exception:
        return None


def load_notes(memory_dir: Path) -> Dict[str, str]:
    """加载所有 notes"""
    notes = {}
    for md_file in memory_dir.rglob("*.md"):
        # 跳过模板和 README
        if md_file.name in ("TEMPLATE.md", "README.md", "EVOLUTION_ROUTINE.md"):
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
            notes[str(md_file)] = content
        except Exception as e:
            print(f"Warning: 无法读取 {md_file}: {e}", file=sys.stderr)
    return notes


def find_conflicts(
    target_path: str,
    target_content: str,
    all_notes: Dict[str, str],
    similarity_threshold: float = 0.5
) -> List[Dict]:
    """查找与目标 note 可能冲突的 notes"""
    conflicts = []
    
    target_claim = extract_claim(target_content)
    target_tokens = tokenize(target_claim)
    
    # 准备所有文档
    docs = [target_tokens]
    other_paths = []
    other_claims = []
    
    for path, content in all_notes.items():
        if path == target_path or Path(path).resolve() == Path(target_path).resolve():
            continue
        claim = extract_claim(content)
        other_claims.append(claim)
        other_paths.append(path)
        docs.append(tokenize(claim))
    
    if not other_paths:
        return []
    
    # 计算 TF-IDF
    tfidf_vectors, _ = compute_tfidf(docs)
    target_vec = tfidf_vectors[0]
    
    # 比较相似度
    for i, (path, claim) in enumerate(zip(other_paths, other_claims)):
        other_vec = tfidf_vectors[i + 1]
        similarity = cosine_similarity(target_vec, other_vec)
        
        if similarity >= similarity_threshold:
            # 检测矛盾信号
            contradiction_signals = detect_contradiction_signals(target_claim, claim)
            
            # LLM 精判
            llm_result = llm_judge_conflict(target_claim, claim, target_path, path)
            
            conflicts.append({
                "path": path,
                "similarity": similarity,
                "target_claim": target_claim[:200],
                "other_claim": claim[:200],
                "contradiction_signals": contradiction_signals,
                "likely_conflict": (llm_result and llm_result.get("conflict")) or len(contradiction_signals) > 0,
                "llm_judgment": llm_result,
            })
    
    # 按相似度排序，优先显示可能冲突的
    conflicts.sort(key=lambda x: (-int(x["likely_conflict"]), -x["similarity"]))
    
    return conflicts


def find_all_conflicts(
    all_notes: Dict[str, str],
    similarity_threshold: float = 0.5
) -> List[Dict]:
    """检测所有 notes 之间的冲突"""
    all_conflicts = []
    checked_pairs = set()
    
    paths = list(all_notes.keys())
    for i, path1 in enumerate(paths):
        for j, path2 in enumerate(paths):
            if i >= j:
                continue
            pair_key = tuple(sorted([path1, path2]))
            if pair_key in checked_pairs:
                continue
            checked_pairs.add(pair_key)
            
            content1 = all_notes[path1]
            content2 = all_notes[path2]
            
            claim1 = extract_claim(content1)
            claim2 = extract_claim(content2)
            
            tokens1 = tokenize(claim1)
            tokens2 = tokenize(claim2)
            
            # 计算相似度
            docs = [tokens1, tokens2]
            tfidf_vectors, _ = compute_tfidf(docs)
            similarity = cosine_similarity(tfidf_vectors[0], tfidf_vectors[1])
            
            if similarity >= similarity_threshold:
                contradiction_signals = detect_contradiction_signals(claim1, claim2)
                
                # LLM 精判
                llm_result = llm_judge_conflict(claim1, claim2, path1, path2)
                
                all_conflicts.append({
                    "path1": path1,
                    "path2": path2,
                    "similarity": similarity,
                    "claim1": claim1[:200],
                    "claim2": claim2[:200],
                    "contradiction_signals": contradiction_signals,
                    "likely_conflict": (llm_result and llm_result.get("conflict")) or len(contradiction_signals) > 0,
                    "llm_judgment": llm_result,
                })
    
    # 按冲突可能性和相似度排序
    all_conflicts.sort(key=lambda x: (-int(x["likely_conflict"]), -x["similarity"]))
    
    return all_conflicts


def format_output(conflicts: List[Dict], mode: str = "single") -> str:
    """格式化输出"""
    if not conflicts:
        return "No potential conflicts detected.\n"
    
    lines = ["# 冲突检测报告\n"]
    
    likely_conflicts = [c for c in conflicts if c.get("likely_conflict")]
    similar_notes = [c for c in conflicts if not c.get("likely_conflict")]
    
    if likely_conflicts:
        lines.append(f"## ⚠️ 可能冲突（{len(likely_conflicts)} 条）\n")
        lines.append("> 以下 notes 语义相近但存在矛盾信号，需人工裁决\n")
        
        for i, c in enumerate(likely_conflicts, 1):
            llm = c.get("llm_judgment")
            if mode == "single":
                lines.append(f"### {i}. {Path(c['path']).name}")
                lines.append(f"- 路径：`{c['path']}`")
                lines.append(f"- 相似度：{c['similarity']:.2%}")
                if llm:
                    lines.append(f"- 冲突类型：{llm.get('type', '未知')}")
                    lines.append(f"- 判断理由：{llm.get('reason', '')}")
                if c['contradiction_signals']:
                    lines.append(f"- 矛盾信号：{', '.join(c['contradiction_signals'])}")
                lines.append(f"- 既有主张：{c['other_claim'][:100]}...")
            else:
                lines.append(f"### {i}. 冲突对")
                lines.append(f"- 文件 A：`{c['path1']}`")
                lines.append(f"- 文件 B：`{c['path2']}`")
                lines.append(f"- 相似度：{c['similarity']:.2%}")
                if llm:
                    lines.append(f"- 冲突类型：{llm.get('type', '未知')}")
                    lines.append(f"- 判断理由：{llm.get('reason', '')}")
                if c['contradiction_signals']:
                    lines.append(f"- 矛盾信号：{', '.join(c['contradiction_signals'])}")
            lines.append("")
    
    if similar_notes:
        lines.append(f"## 📋 相似但无明显冲突（{len(similar_notes)} 条）\n")
        lines.append("> 语义相近，建议检查是否需要合并或补充链接\n")
        
        for i, c in enumerate(similar_notes[:5], 1):  # 只显示前 5 条
            if mode == "single":
                lines.append(f"- `{Path(c['path']).name}` (相似度: {c['similarity']:.2%})")
            else:
                lines.append(f"- `{Path(c['path1']).name}` ↔ `{Path(c['path2']).name}` ({c['similarity']:.2%})")
        
        if len(similar_notes) > 5:
            lines.append(f"- ... 及其他 {len(similar_notes) - 5} 条")
        lines.append("")
    
    lines.append("---")
    lines.append("建议行动：")
    lines.append("1. 对「可能冲突」逐条检视，确认是否真的矛盾")
    lines.append("2. 若确认冲突：向用户确认后删除旧决策文件，并清理引用链接")
    lines.append("3. 若为补充关系：在两条文档中互相添加 `Related links`")
    
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description="检测 notes 之间的潜在冲突")
    parser.add_argument("--new", type=str, help="新增 note 的路径")
    parser.add_argument("--all", action="store_true", help="检测所有 notes 之间的冲突")
    parser.add_argument("--threshold", type=float, default=0.5, 
                        help="相似度阈值 (默认: 0.5)")
    parser.add_argument("--memory-dir", type=str, default=None,
                        help="memory 目录路径 (默认: 仓库根目录/memory)")
    parser.add_argument("--repo-root", type=str, default=None,
                        help="PM Agent data directory (default: resolve from config)")
    parser.add_argument("--out", type=str, help="输出到文件（可选）")
    
    args = parser.parse_args()
    
    # 确定扫描目录（memory + decisions，全局 + 所有项目级）
    if args.memory_dir:
        scan_dirs = [Path(args.memory_dir)]
    else:
        repo_root = Path(args.repo_root).resolve() if args.repo_root else resolve_data_dir()
        scan_dirs = [repo_root / "memory", repo_root / "decisions"]
        # Also scan project-level memory + decisions
        proj_dir = repo_root / "projects"
        if proj_dir.exists():
            for proj in sorted(proj_dir.iterdir()):
                if not proj.is_dir():
                    continue
                for sub in ("memory", "decisions"):
                    sub_dir = proj / sub
                    if sub_dir.exists():
                        scan_dirs.append(sub_dir)
        # Also scan workspace-level decisions
        ws_dir = repo_root / "workspaces"
        if ws_dir.exists():
            for ws in sorted(ws_dir.iterdir()):
                if not ws.is_dir():
                    continue
                ws_decisions = ws / "decisions"
                if ws_decisions.exists():
                    scan_dirs.append(ws_decisions)
    
    # 加载所有 notes
    all_notes = {}
    for scan_dir in scan_dirs:
        if scan_dir.exists():
            notes = load_notes(scan_dir)
            all_notes.update(notes)
    print(f"已加载 {len(all_notes)} 条文档 (from {len(scan_dirs)} dirs)", file=sys.stderr)
    
    if args.new:
        # 检测新 note 与既有 notes 的冲突
        new_path = Path(args.new)
        if not new_path.exists():
            print(f"Error: 文件不存在: {new_path}", file=sys.stderr)
            sys.exit(1)
        
        new_content = new_path.read_text(encoding="utf-8")
        conflicts = find_conflicts(str(new_path), new_content, all_notes, args.threshold)
        output = format_output(conflicts, mode="single")
        
    elif args.all:
        # 检测所有 notes 之间的冲突
        conflicts = find_all_conflicts(all_notes, args.threshold)
        output = format_output(conflicts, mode="all")
    else:
        parser.print_help()
        sys.exit(1)
    
    # 输出
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"报告已写入: {args.out}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
