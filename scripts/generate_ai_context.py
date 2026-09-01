from __future__ import annotations

from datetime import datetime
from pathlib import Path
import hashlib
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "CURRENT_PROJECT_CONTEXT.md"

def run_command(args: list[str]) -> str:
    try:
        result = subprocess.run(
            args,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        text = (result.stdout or result.stderr or "").strip()
        return text if text else "(no output)"
    except Exception as exc:
        return f"(command failed: {exc})"

def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def latest_release() -> str:
    releases = ROOT / "releases"
    if not releases.exists():
        return "(releases directory not found)"
    dirs = sorted(p.name for p in releases.iterdir() if p.is_dir())
    return dirs[-1] if dirs else "(no release directory)"

def main() -> None:
    names = [
        "AI_CONTEXT.md",
        "AI_RULES.md",
        "ARCHITECTURE.md",
        "DATA_CONTRACTS.md",
        "GOLDEN_CORPUS.md",
        "AGENTS.md",
        "CLAUDE.md",
        "GEMINI.md",
        "ANTIGRAVITY.md",
    ]
    hashes = []
    for name in names:
        path = ROOT / name
        hashes.append(
            f"- `{name}`: `{file_sha256(path)}`" if path.exists()
            else f"- `{name}`: MISSING"
        )

    content = f"""# Current Project Context

Generated: `{datetime.now().astimezone().isoformat(timespec="seconds")}`

## Repository

- Root: `{ROOT}`
- Current branch: `{run_command(["git", "branch", "--show-current"])}` 
- Latest release directory: `{latest_release()}`

## Git status

```text
{run_command(["git", "status", "--short"])}
```

## Recent commits

```text
{run_command(["git", "log", "-5", "--oneline"])}
```

## Instruction hashes

{chr(10).join(hashes)}

## Required reading order

1. `AI_CONTEXT.md`
2. `AI_RULES.md`
3. `ARCHITECTURE.md`
4. `DATA_CONTRACTS.md`
5. `GOLDEN_CORPUS.md`
6. relevant ADRs and incidents
7. `docs/agent_startup_protocol.md`

## Formal production path

```text
Main Statement Resolution
→ CertifiedChildTableLink
→ Whole-table Capture
→ Canonical
→ Merge
→ User Research XLSX
```

This generated file is an index and repository snapshot. It does not replace the manually maintained project facts in `AI_CONTEXT.md`.
"""
    OUTPUT.write_text(content, encoding="utf-8")
    print(f"Wrote {OUTPUT}")

if __name__ == "__main__":
    main()
