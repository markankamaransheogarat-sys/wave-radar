"""Deterministic tailored application pitch generator from issue metadata."""

from __future__ import annotations

import re

_PATH_RE = re.compile(
    r"`((?:[a-zA-Z0-9_.-]+/)+[a-zA-Z0-9_.-]+(?:\.[a-zA-Z0-9]+)?|[a-zA-Z0-9_.-]+\.(?:ts|tsx|js|jsx|rs|go|py|sol|sql))`"
)
_BOILERPLATE_PREFIXES = (
    "difficulty:",
    "points:",
    "assignment required",
    "pr description must",
    "timeframe:",
    "fork and",
    "test and commit",
    "cover normal,",
    "add automated tests",
    "document edge cases",
    "preserve existing contracts",
)


def extract_file_paths(body: str, limit: int = 3) -> list[str]:
    """Extract distinct backticked file/directory paths mentioned in an issue body."""
    seen: set[str] = set()
    paths: list[str] = []
    for match in _PATH_RE.findall(body or ""):
        cleaned = match.strip().rstrip("/")
        if cleaned in seen or len(cleaned) < 4:
            continue
        seen.add(cleaned)
        paths.append(cleaned)
        if len(paths) >= limit:
            break
    return paths


def extract_focus_points(body: str, limit: int = 2) -> list[str]:
    """Extract concise non-boilerplate bullet points from issue markdown."""
    points: list[str] = []
    for line in (body or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith(("- ", "* ", "- [ ] ")):
            continue
        text = re.sub(r"^(?:-\s*\[\s*\]\s*|[-*]\s+)", "", stripped)
        text = " ".join(text.split())
        if len(text) < 16 or text.lower().startswith(_BOILERPLATE_PREFIXES):
            continue
        if len(text) > 130:
            text = text[:127].rstrip() + "..."
        points.append(text)
        if len(points) >= limit:
            break
    return points


def infer_test_suite(title: str, body: str, paths: list[str]) -> str:
    """Infer the appropriate verification suite from file extensions or issue text."""
    corpus = f"{title}\n{body}\n{' '.join(paths)}".lower()
    if (
        any(p.endswith(".rs") for p in paths)
        or "cargo " in corpus
        or "rust" in corpus
        or "soroban" in corpus
    ):
        return "`cargo test` and `cargo clippy`"
    if any(p.endswith(".go") for p in paths) or "golang" in corpus or "godoc" in corpus:
        return "`go vet ./...` and `go test ./...`"
    if (
        any(p.endswith((".ts", ".tsx", ".js", ".jsx")) for p in paths)
        or "vitest" in corpus
        or "frontend" in corpus
    ):
        return "unit/component tests and `typecheck`"
    if any(p.endswith(".py") for p in paths) or "pytest" in corpus:
        return "`pytest` and type checks"
    return "automated unit and edge-case tests"


def generate_pitch(issue_number: int, title: str, body: str = "") -> str:
    """Build a crisp, concrete English Wave application ready to paste into Drips."""
    clean_title = " ".join(title.split())
    paths = extract_file_paths(body)
    focus = extract_focus_points(body)
    checks = infer_test_suite(clean_title, body, paths)

    target_clause = f" in {', '.join(f'`{p}`' for p in paths)}" if paths else ""
    if focus:
        scope_sentence = (
            f"I'll implement this{target_clause} focusing on: {'; '.join(focus)}, "
            f"while keeping existing interfaces backward-compatible."
        )
    else:
        scope_sentence = (
            f"I'll implement a clean, focused slice{target_clause} covering happy paths, "
            f"validation/error handling, and edge cases."
        )

    return (
        f"Hi! I'd like to take `#{issue_number}` (*{clean_title}*).\n"
        f"{scope_sentence}\n"
        f"I'll verify everything locally with {checks} before opening the PR. "
        f"Ready to start immediately upon assignment!"
    )
