"""Build the Windows distribution zip.

    python scripts/windows/build_zip.py            -> dist/archivist-windows-py314.zip

The zip is self-contained: the package, the launchers, requirements, an example
.env and a README. Unzip anywhere, double-click ``run_archivist.bat``, and the
setup script resolves (or downloads) Python 3.14 on its own.
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WINDOWS = ROOT / "scripts" / "windows"

# (source, name inside the zip)
INCLUDE_FILES = [
    (WINDOWS / "setup.bat", "setup.bat"),
    (WINDOWS / "run_archivist.bat", "run_archivist.bat"),
    (WINDOWS / "run_pipeline.bat", "run_pipeline.bat"),
    (WINDOWS / "README-WINDOWS.md", "README-WINDOWS.md"),
    (ROOT / "requirements.txt", "requirements.txt"),
    (ROOT / ".env.example", ".env.example"),
    (ROOT / "README.md", "docs/README.md"),
]

SKIP_DIR_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache"}


def package_files() -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    for path in sorted((ROOT / "archivist").rglob("*.py")):
        if SKIP_DIR_PARTS & set(path.parts):
            continue
        files.append((path, str(path.relative_to(ROOT)).replace("\\", "/")))
    return files


def build(output: Path, *, include_notebook: bool = True) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    entries = package_files()
    for source, name in INCLUDE_FILES:
        if source.is_file():
            entries.append((source, name))
    notebook = ROOT / "notebooks" / "archivist_pipeline.ipynb"
    if include_notebook and notebook.is_file():
        entries.append((notebook, "notebooks/archivist_pipeline.ipynb"))

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source, name in entries:
            archive.write(source, name)

    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"wrote {output} ({size_mb:.2f} MB, {len(entries)} files)")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(ROOT / "dist" / "archivist-windows-py314.zip"))
    parser.add_argument("--no-notebook", action="store_true")
    args = parser.parse_args()
    build(Path(args.output), include_notebook=not args.no_notebook)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
