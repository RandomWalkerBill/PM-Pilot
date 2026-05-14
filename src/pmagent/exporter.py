#!/usr/bin/env python3
"""
Dev Pack 导出器 — 从项目 + 需求工作区生成干净的开发消费包

功能：
  从 projects/<project>/ 的 strategy/ decisions/ memory/ 和
  workspaces/<workspace>/ 的 prd/ 中提取内容，
  组装成面向开发侧的交付文件包，版本化输出到 exports/vN/。

导出内容：
  - PRD.md：最新 PRD 主体（去除 PM 过程噪音）
  - DEV_CONTEXT.md：技术约束、依赖、边界、术语表
  - MANIFEST.md：导出版本元信息（来源、时间戳、未决问题）

用法：
  pmagent export                                                 # 导出当前激活项目
  pmagent export --project podcast-audio --workspace podcast-audio-editing
  pmagent export --project crc-copilot --workspace crc-copilot --output /tmp/devpack
"""

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .paths import resolve_data_dir


def load_active_project(repo_root: Path) -> Optional[str]:
    config_path = repo_root / "config" / "projects.json"
    if not config_path.exists():
        return None
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return data.get("active_project")
    except Exception:
        return None


def find_latest_file(directory: Path, pattern: str = "*.md") -> Optional[Path]:
    """Find the most recently modified .md file in a directory."""
    files = sorted(directory.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)
    return files[0] if files else None


def find_all_md(directory: Path) -> List[Path]:
    """Find all .md files recursively, sorted by date descending."""
    if not directory.exists():
        return []
    files = sorted(directory.rglob("*.md"), key=lambda f: f.name, reverse=True)
    return [f for f in files if "TEMPLATE" not in f.name and f.name != "README.md"]


def extract_sections(text: str) -> Dict[str, str]:
    """Extract H2 sections from markdown."""
    sections: Dict[str, str] = {}
    current_header = None
    current_lines: List[str] = []
    
    for line in text.splitlines():
        if line.startswith("## "):
            if current_header:
                sections[current_header] = "\n".join(current_lines).strip()
            current_header = line[3:].strip()
            current_lines = []
        elif current_header:
            current_lines.append(line)
    
    if current_header:
        sections[current_header] = "\n".join(current_lines).strip()
    
    return sections


def strip_related_links(text: str) -> str:
    """Remove 'Related links' section from markdown."""
    lines = text.splitlines()
    result = []
    skip = False
    for line in lines:
        if re.match(r"^##\s*Related\s*links", line, re.IGNORECASE):
            skip = True
            continue
        if skip and line.startswith("## "):
            skip = False
        if not skip:
            result.append(line)
    return "\n".join(result).rstrip() + "\n"


def generate_prd_delivery(workspace_root: Path) -> str:
    """Generate a clean PRD.md for development consumption."""
    prd_dir = workspace_root / "prd"
    files = find_all_md(prd_dir)
    if not files:
        return "# PRD\n\n> 暂无 PRD 文档。\n"
    
    # Use the latest PRD
    latest = files[0]
    text = latest.read_text(encoding="utf-8")
    text = strip_related_links(text)
    
    header = f"<!-- 此文件由 export_devpack.py 自动生成，请勿手动编辑 -->\n"
    header += f"<!-- 来源: {latest.name} -->\n"
    header += f"<!-- 导出时间: {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} -->\n\n"
    
    return header + text


def generate_dev_context(project_root: Path) -> str:
    """Generate DEV_CONTEXT.md from strategy + decisions + memory."""
    lines = [
        "<!-- 此文件由 export_devpack.py 自动生成，请勿手动编辑 -->",
        f"<!-- 导出时间: {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} -->",
        "",
        "# 开发上下文 (Dev Context)",
        "",
    ]
    
    # Strategy brief summary
    strategy_dir = project_root / "strategy"
    strategy_files = find_all_md(strategy_dir)
    if strategy_files:
        lines.append("## 价值层摘要 (Strategy)")
        lines.append("")
        for sf in strategy_files[:2]:  # At most 2 most recent
            text = strip_related_links(sf.read_text(encoding="utf-8"))
            # Extract key sections
            sections = extract_sections(text)
            for key in ["核心价值主张", "目标用户", "关键约束", "成功指标", "North Star"]:
                if key in sections:
                    lines.append(f"### {key}")
                    lines.append("")
                    lines.append(sections[key])
                    lines.append("")
        lines.append("---")
        lines.append("")
    
    # Key decisions
    decision_dir = project_root / "decisions"
    decision_files = find_all_md(decision_dir)
    if decision_files:
        lines.append("## 关键决策")
        lines.append("")
        for df in decision_files[:5]:  # At most 5 most recent
            text = df.read_text(encoding="utf-8")
            title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
            title = title_match.group(1) if title_match else df.stem
            sections = extract_sections(text)
            decision = sections.get("决策", sections.get("Decision", ""))
            lines.append(f"- **{title}**")
            if decision:
                lines.append(f"  {decision[:200]}")
            lines.append("")
        lines.append("---")
        lines.append("")
    
    # Project memory (world knowledge / constraints)
    memory_dir = project_root / "memory"
    memory_files = find_all_md(memory_dir)
    if memory_files:
        lines.append("## 项目约束与事实")
        lines.append("")
        for mf in memory_files[:5]:
            text = mf.read_text(encoding="utf-8")
            sections = extract_sections(text)
            claim = sections.get("Claim", sections.get("核心主张", ""))
            if claim:
                lines.append(f"- {claim[:200]}")
        lines.append("")
    
    return "\n".join(lines) + "\n"


def generate_manifest(
    project_name: str,
    project_root: Path,
    output_dir: Path,
    repo_root: Path = None,
    workspace_root: Path = None,
) -> str:
    """Generate MANIFEST.md with export metadata."""
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Use repo-relative paths instead of absolute paths for portability
    if repo_root:
        rel_project = project_root.relative_to(repo_root)
        rel_output = output_dir.relative_to(repo_root)
        rel_workspace = workspace_root.relative_to(repo_root) if workspace_root else rel_project
    else:
        rel_project = project_root
        rel_output = output_dir
        rel_workspace = workspace_root or project_root
    
    lines = [
        "# Dev Pack Manifest",
        "",
        f"- **项目**: {project_name}",
        f"- **导出时间**: {now}",
        f"- **项目目录**: `{rel_project}`",
        f"- **工作空间**: `{rel_workspace}`",
        f"- **输出目录**: `{rel_output}`",
        "",
        "## 包含文件",
        "",
        "| 文件 | 用途 |",
        "|------|------|",
        "| `PRD.md` | 最新 PRD（面向开发消费） |",
        "| `DEV_CONTEXT.md` | 技术约束、依赖、决策、术语 |",
        "| `MANIFEST.md` | 此文件：导出元信息 |",
        "",
        "## 来源文件",
        "",
    ]
    
    # Project-level source files
    lines.append("### 项目级来源 (projects/)")
    lines.append("")
    for subdir in ["strategy", "decisions", "memory"]:
        d = project_root / subdir
        files = find_all_md(d)
        if files:
            lines.append(f"#### {subdir}/")
            for f in files:
                lines.append(f"- `{f.relative_to(project_root)}`")
            lines.append("")
    
    # Workspace-level source files
    ws = workspace_root or project_root
    lines.append("### 需求级来源 (workspaces/)")
    lines.append("")
    for subdir in ["prd", "research", "context"]:
        d = ws / subdir
        files = find_all_md(d)
        if files:
            lines.append(f"#### {subdir}/")
            for f in files:
                lines.append(f"- `{f.relative_to(ws)}`")
            lines.append("")
    
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="导出 Dev Pack 给开发侧消费")
    parser.add_argument("--project", type=str, default=None,
                        help="项目名称 (default: 当前激活项目)")
    parser.add_argument("--workspace", type=str, default=None,
                        help="需求工作空间名称 (default: 与项目同名)")
    parser.add_argument("--output", type=str, default=None,
                        help="输出目录 (default: workspaces/<workspace>/exports/vN)")
    parser.add_argument("--repo-root", type=str, default=None,
                        help="PM Agent data directory (default: resolve from config)")
    args = parser.parse_args()
    
    if args.repo_root:
        repo_root = Path(args.repo_root).resolve()
    else:
        repo_root = resolve_data_dir()
    
    # Resolve project
    project = args.project or load_active_project(repo_root)
    if not project:
        print("[error] 未指定项目，也未找到激活项目。请用 --project 指定。", file=sys.stderr)
        return 1
    
    project_root = repo_root / "projects" / project
    if not project_root.exists():
        print(f"[error] 项目目录不存在: {project_root}", file=sys.stderr)
        return 1
    
    # Resolve workspace (default: same name as project)
    workspace = args.workspace or project
    workspace_root = repo_root / "workspaces" / workspace
    if not workspace_root.exists():
        print(f"[error] 工作空间目录不存在: {workspace_root}", file=sys.stderr)
        return 1
    
    # Resolve output — auto-increment version
    if args.output:
        output_dir = Path(args.output).resolve()
    else:
        exports_dir = workspace_root / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        existing = sorted(
            [d for d in exports_dir.iterdir() if d.is_dir() and d.name.startswith("v")],
            key=lambda d: int(d.name[1:]) if d.name[1:].isdigit() else 0,
        )
        next_ver = (int(existing[-1].name[1:]) + 1) if existing else 1
        output_dir = exports_dir / f"v{next_ver}"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"导出 Dev Pack: {project} (workspace: {workspace})")
    print(f"  项目目录: {project_root}")
    print(f"  工作空间: {workspace_root}")
    print(f"  输出目录: {output_dir}")
    print()
    
    # Generate files — PRD from workspace, context from project
    prd_text = generate_prd_delivery(workspace_root)
    (output_dir / "PRD.md").write_text(prd_text, encoding="utf-8")
    print("  - PRD.md")
    
    ctx_text = generate_dev_context(project_root)
    (output_dir / "DEV_CONTEXT.md").write_text(ctx_text, encoding="utf-8")
    print("  - DEV_CONTEXT.md")
    
    manifest = generate_manifest(project, project_root, output_dir, repo_root=repo_root, workspace_root=workspace_root)
    (output_dir / "MANIFEST.md").write_text(manifest, encoding="utf-8")
    print("  - MANIFEST.md")
    
    print(f"\n导出完成！开发侧可直接读取: {output_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
