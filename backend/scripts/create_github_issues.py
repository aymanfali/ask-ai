from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = "aymanfali/ask-ai"
ISSUES_DIR = Path(__file__).resolve().parents[1] / "docs" / "development" / "github-issues"


def main() -> int:
    if subprocess.run(["gh", "auth", "status"], check=False).returncode != 0:
        print("Authenticate first with: gh auth login", file=sys.stderr)
        return 2
    for issue_file in sorted(ISSUES_DIR.glob("*.md")):
        first_line = issue_file.read_text(encoding="utf-8").splitlines()[0]
        if not first_line.startswith("# "):
            print(f"Skipping invalid issue file: {issue_file}", file=sys.stderr)
            continue
        title = first_line[2:].strip()
        print(f"Creating: {title}")
        result = subprocess.run(
            [
                "gh",
                "issue",
                "create",
                "--repo",
                REPO,
                "--title",
                title,
                "--body-file",
                str(issue_file),
            ],
            check=False,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            print(result.stderr.strip(), file=sys.stderr)
            print("Stopped on first failure to avoid silently skipping an issue.", file=sys.stderr)
            return result.returncode
        print(result.stdout.strip())
    print("All backlog issues were submitted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
