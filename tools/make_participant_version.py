"""
Generate participant ("fill in the blanks") notebooks from the solution notebooks.

The problem this solves
-----------------------
Previously the participant notebooks were produced by hand-deleting code from the
solution notebooks. That made the two versions drift apart, and the diffs were
unreviewable (one commit deleted 8,898 lines from a single notebook, with code and
cell outputs tangled together).

Here the solution notebook is the single source of truth. You mark the bits you
want participants to write themselves, and this script generates the stripped
version on demand. Fix a bug in the solution and regenerate - the two can never
fall out of sync.

How to mark a solution block
----------------------------
Inside a code cell, wrap the lines you want removed:

    # --- SOLUTION: Transpose so that genes are rows and patients are columns ---
    patient_gene_matrix = expression_data.T
    # --- END SOLUTION ---

becomes, in the generated notebook:

    # TODO: Transpose so that genes are rows and patients are columns
    ### YOUR CODE HERE ###

The text after `SOLUTION:` is optional. Without it you just get a bare
`### YOUR CODE HERE ###`. Everything outside the markers - imports, scaffolding,
plotting calls, comments - is left untouched, so participants keep a runnable
skeleton and only fill in the interesting parts.

Indentation is preserved, so a block inside a function or loop still lands in the
right place.

Usage
-----
    # generate one notebook
    python tools/make_participant_version.py sessions/session-1-intro-networks/part-1.ipynb

    # generate a whole session into a participant/ subfolder
    python tools/make_participant_version.py "sessions/session-1-intro-networks/*.ipynb"

    # check markers are balanced without writing anything
    python tools/make_participant_version.py --check "sessions/**/*.ipynb"
"""

from __future__ import annotations

import argparse
import copy
import glob
import json
import re
import sys
from pathlib import Path

SOLUTION_START = re.compile(r"^(\s*)#\s*-*\s*SOLUTION\s*:?\s*(.*?)\s*-*\s*$", re.IGNORECASE)
SOLUTION_END = re.compile(r"^\s*#\s*-*\s*END\s+SOLUTION\s*-*\s*$", re.IGNORECASE)

PLACEHOLDER = "### YOUR CODE HERE ###"


def strip_cell_source(lines: list[str], cell_label: str) -> tuple[list[str], int]:
    """
    Replace each marked solution block in a cell with a TODO + placeholder.

    Returns the rewritten lines and the number of blocks that were replaced.
    """
    out: list[str] = []
    replaced = 0
    inside = False
    indent = ""
    hint = ""

    for line in lines:
        stripped = line.rstrip("\n")

        if not inside:
            match = SOLUTION_START.match(stripped)
            # Guard against matching the END marker, which also contains "SOLUTION"
            if match and not SOLUTION_END.match(stripped):
                inside = True
                indent, hint = match.group(1), match.group(2).strip()
                continue
            out.append(line)
            continue

        # inside a solution block: drop lines until the end marker
        if SOLUTION_END.match(stripped):
            if hint:
                out.append(f"{indent}# TODO: {hint}\n")
            out.append(f"{indent}{PLACEHOLDER}\n")
            replaced += 1
            inside = False
            continue
        # else: this is solution code, discard it

    if inside:
        raise ValueError(
            f"{cell_label}: '# --- SOLUTION ---' was never closed with "
            f"'# --- END SOLUTION ---'"
        )

    return out, replaced


def convert(notebook_path: Path, out_path: Path, keep_outputs: bool,
            check_only: bool) -> int:
    """Convert one notebook. Returns the number of solution blocks replaced."""
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    total = 0

    for index, cell in enumerate(notebook.get("cells", [])):
        if cell.get("cell_type") != "code":
            continue

        source = cell.get("source", [])
        if isinstance(source, str):
            source = source.splitlines(keepends=True)

        label = f"{notebook_path.name} cell {index}"
        new_source, replaced = strip_cell_source(source, label)

        if replaced:
            total += replaced
            cell["source"] = new_source
            # A stale output produced by code that no longer exists is misleading,
            # so clear it unless explicitly asked to keep it.
            if not keep_outputs:
                cell["outputs"] = []
                cell["execution_count"] = None

    if check_only:
        return total

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    return total


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("patterns", nargs="+",
                        help="notebook paths or globs (quote globs so the shell "
                             "does not expand them)")
    parser.add_argument("--out-dir", default=None,
                        help="output directory (default: a 'participant/' folder "
                             "next to each source notebook)")
    parser.add_argument("--keep-outputs", action="store_true",
                        help="keep cell outputs on stripped cells (default: clear them)")
    parser.add_argument("--check", action="store_true",
                        help="only verify markers are balanced; write nothing")
    args = parser.parse_args()

    paths: list[Path] = []
    for pattern in args.patterns:
        matches = sorted(glob.glob(pattern, recursive=True))
        if not matches:
            print(f"warning: no files matched {pattern!r}", file=sys.stderr)
        paths.extend(Path(p) for p in matches)

    # Never treat an already-generated participant notebook as a source.
    paths = [p for p in paths if p.suffix == ".ipynb" and "participant" not in p.parts]

    if not paths:
        sys.exit("No notebooks to process.")

    grand_total = 0
    failures = 0

    for path in paths:
        if args.out_dir:
            out_path = Path(args.out_dir) / path.name
        else:
            out_path = path.parent / "participant" / path.name

        try:
            count = convert(path, out_path, args.keep_outputs, args.check)
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"  FAIL  {path}: {exc}", file=sys.stderr)
            failures += 1
            continue

        grand_total += count
        if args.check:
            print(f"  ok    {path}  ({count} solution blocks)")
        elif count:
            print(f"  wrote {out_path}  ({count} blocks blanked)")
        else:
            print(f"  skip  {path}  (no solution markers found)")

    print(f"\n{grand_total} solution blocks across {len(paths)} notebooks.")
    if failures:
        sys.exit(f"{failures} notebook(s) failed.")


if __name__ == "__main__":
    main()
