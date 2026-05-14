from __future__ import annotations

import argparse
import shutil
from importlib import resources
from pathlib import Path

from .paths import resolve_data_dir


def _copy_package_tree(source_root: Path, dest_root: Path) -> int:
    copied = 0
    for file_path in sorted(source_root.rglob("*")):
        if not file_path.is_file():
            continue
        rel = file_path.relative_to(source_root)
        target = dest_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, target)
        copied += 1
    return copied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync packaged skills into the PM Agent data directory")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=None, help="PM Agent data directory")
    args = parser.parse_args(argv)

    data_dir = args.repo_root.resolve() if args.repo_root else resolve_data_dir()
    output_dir = (args.output_dir or (data_dir / "skills")).resolve()

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with resources.as_file(resources.files("pmagent").joinpath("skills")) as skills_root:
        copied = _copy_package_tree(skills_root, output_dir)

    print(f"Skills synced to: {output_dir}")
    print(f"Files copied: {copied}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
