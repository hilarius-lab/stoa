from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = {
    ".git",
    ".gradle",
    ".idea",
    ".kotlin",
    ".venv",
    ".work",
    "__pycache__",
    "build",
    "data",
    "reports",
}

SKIP_FILES = {
    ".env",
    "gradle-wrapper.jar",
    "keystore.properties",
    "local.properties",
    "smart_notebook.db",
}

BINARY_SUFFIXES = {
    ".class",
    ".db",
    ".gif",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".key",
    ".mp3",
    ".mp4",
    ".m4a",
    ".pdf",
    ".png",
    ".sqlite",
    ".wav",
    ".webm",
    ".webp",
    ".zip",
}

PATTERNS = [
    (
        "windows-path",
        re.compile(r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/][A-Za-z._<]"),
    ),
    (
        "user-profile-path",
        re.compile(r"""(?i)(?:^|[\s"'\(`=:(])(?:/Users/[^/\s]+|/home/[^/\s]+|~/(?:\.android|\.gradle|\.keystore))"""),
    ),
    (
        "foreign-repo-marker",
        re.compile(r"(?i)\b(RacingManager|HannesApp|BackupD|Rennmanager)\b"),
    ),
    (
        "absolute-keystore-path",
        re.compile(
            r"""(?i)
            (?:
              (?<![A-Za-z0-9])[A-Z]:[\\/][^\\\n]*\.keystore
              |
              (?:^|[\s"'\(`=:(])(?:/[^/\s]+)+\.keystore
            )
            """,
            re.VERBOSE,
        ),
    ),
    (
        "literal-credential",
        re.compile(r"""(?i)\b(password|passwd|secret|api_?key|access_?token|auth_?token|private_?key)\b\s*[:=]\s*["']([^\s"']+)["']"""),
    ),
]

PLACEHOLDER_CREDENTIAL = re.compile(
    r"""^(?:
        CHANGE_?ME
        | XXX+
        | PLACEHOLDER
        | EXAMPLE
        | <[^>]+>
        | \$\{[^}]+\}
        | %[^%]+%
        | \$[A-Za-z_][A-Za-z0-9_]*
        | \.{3,}
        | [A-Z0-9_]+$
    )$""",
    re.VERBOSE,
)


@dataclass
class Finding:
    path: Path
    line: int
    rule: str
    excerpt: str


def is_scannable(path: Path) -> bool:
    if path.suffix.lower() in BINARY_SUFFIXES:
        return False
    try:
        head = path.open("rb").read(4096)
    except OSError:
        return False
    return b"\0" not in head


def iter_files(root: Path, self_path: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        if path.name in SKIP_FILES or path.name.endswith(".local.env"):
            continue
        if path.resolve() == self_path.resolve():
            continue
        if is_scannable(path):
            yield path


def excerpt_for(line: str) -> str:
    line = line.strip()
    if len(line) <= 160:
        return line
    return line[:157] + "..."


def check_line(line: str, rule: str, pattern: re.Pattern) -> list[str]:
    if rule == "literal-credential":
        messages = []
        for match in pattern.finditer(line):
            value = match.group(2)
            if len(value) < 6:
                continue
            if PLACEHOLDER_CREDENTIAL.match(value):
                continue
            if not re.search(r"[a-z]", value) or not re.search(r"[A-Z0-9]", value):
                continue
            messages.append(value)
        return messages
    return [match.group(0) for match in pattern.finditer(line)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Check committed project files for machine-specific or secret-bearing references.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()

    root = Path(args.root).resolve()
    self_path = Path(__file__).resolve()
    findings: list[Finding] = []
    scanned = 0

    for path in iter_files(root, self_path):
        scanned += 1
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, start=1):
            for rule, pattern in PATTERNS:
                for match in check_line(line, rule, pattern):
                    findings.append(Finding(path, line_number, rule, excerpt_for(f"{match} | {line}")))

    for finding in findings:
        relative = finding.path.relative_to(root)
        print(f"[FAIL] {relative}:{finding.line} {finding.rule}: {finding.excerpt}")

    print(f"Portability-Check: {scanned} Dateien geprüfst, {len(findings)} Befunde.")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
