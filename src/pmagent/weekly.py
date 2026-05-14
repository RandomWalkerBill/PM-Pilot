from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from .paths import resolve_data_dir


QUALITY_TEMPLATE = """# Agent 输出质量评审

> 文件名：{date}-quality-review.md

## 基本信息

- 评审日期：{date}
- 评审周期：
- 抽查数量：5 条

## 抽查记录

### 样本 1

- 对话日期：
- 用户问题摘要：
- Agent 输出摘要：
- 评分：
| 维度 | 分数(1-5) | 备注 |
|------|-----------|------|
| 准确性 | | |
| 可执行性 | | |
| 相关性 | | |
| 挑战价值 | | |

- 问题/改进点：
"""


def _run_module_main(module, argv: list[str]) -> int:
    old_argv = sys.argv[:]
    sys.argv = [module.__name__, *argv]
    try:
        result = module.main()
        return int(result) if result is not None else 0
    finally:
        sys.argv = old_argv


def _count_markdown_files(directory: Path, excludes: set[str] | None = None) -> int:
    excludes = excludes or set()
    if not directory.exists():
        return 0
    return sum(1 for file_path in directory.rglob("*.md") if file_path.name not in excludes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run PM Agent weekly maintenance routine")
    parser.add_argument("--repo-root", default=None, help="PM Agent data directory")
    args = parser.parse_args(argv)

    data_dir = Path(args.repo_root).resolve() if args.repo_root else resolve_data_dir()
    today = dt.date.today().strftime("%Y-%m-%d")

    reports_dir = data_dir / "ops" / "weekly-reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    conflict_report = reports_dir / f"{today}-conflict-report.md"
    from . import conflicts

    _run_module_main(
        conflicts,
        ["--repo-root", str(data_dir), "--all", "--threshold", "0.4", "--out", str(conflict_report)],
    )

    quality_dir = data_dir / "ops" / "quality-log"
    quality_dir.mkdir(parents=True, exist_ok=True)
    quality_log = quality_dir / f"{today}-quality-review.md"
    if not quality_log.exists():
        quality_log.write_text(QUALITY_TEMPLATE.format(date=today), encoding="utf-8")

    linker_error = None
    try:
        from . import linker

        _run_module_main(linker, ["--repo-root", str(data_dir), "--all-projects", "--reindex"])
    except Exception as exc:  # pragma: no cover - best-effort maintenance step
        linker_error = str(exc)

    memory_total = _count_markdown_files(
        data_dir / "memory",
        excludes={"README.md", "TEMPLATE.md", "EVOLUTION_ROUTINE.md"},
    )
    persona_total = _count_markdown_files(data_dir / "memory" / "persona")
    global_total = _count_markdown_files(data_dir / "memory" / "global")

    print("=== PM Agent weekly routine ===")
    print(f"date: {today}")
    print(f"conflict report: {conflict_report}")
    print(f"quality log: {quality_log}")
    print(f"memory notes: {memory_total}")
    print(f"persona notes: {persona_total}")
    print(f"global notes: {global_total}")
    if linker_error:
        print(f"auto-link skipped: {linker_error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
