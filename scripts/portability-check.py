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
    (
        "private-ip-address",
        re.compile(
            r"""(?<![0-9.])(?:
                192\.168\.\d{1,3}\.\d{1,3}
                | 10\.\d{1,3}\.\d{1,3}\.\d{1,3}
                | 172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}
            )(?![0-9.])""",
            re.VERBOSE,
        ),
    ),
    (
        "internal-hostname",
        re.compile(r"(?i)\b[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.(?:internal|lan|local)\b(?!\.[a-z])"),
    ),
]

# Rule names that are skipped for documentation: Doku und CHANGELOG zitieren
# Heimnetz-Adressen und interne Hostnamen absichtlich als historischen
# Kontext (z. B. CLIENT_SERVER_STATE.md, AUDIO_ARCHITECTURE.md, der
# archivierte Codex-Handoff). Andere Regeln (Pfade, Fremdrepo-Marker,
# Klartext-Credentials) scannen Doku weiterhin.
NETWORK_ADDRESS_RULES = {"private-ip-address", "internal-hostname"}

# Bekannte, unbedenkliche Adressen, die keine Heimnetz-Konfiguration sind:
# ESP-IDF-SoftAP-Standard, der Android-Emulator-Alias für den Hostrechner
# (ADR-0009) und Test-/Platzhalteradressen in Validator-Tests und UI-Hints.
NETWORK_ADDRESS_ALLOWLIST = {
    "192.168.4.1",
    "192.168.1.100",
    "192.168.1.10",
    "192.168.1.1",
    "192.168.001.1",
    "10.0.2.2",
}

HANDOFF_ARCHIVE_DIR = "smart-notebook-codex-handoff-v1.0"

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


def is_network_address_exempt(relative_path: Path) -> bool:
    parts = relative_path.parts
    if relative_path.suffix.lower() == ".md":
        return True
    if "changelog" in relative_path.name.lower():
        return True
    if parts and parts[0] == HANDOFF_ARCHIVE_DIR:
        return True
    return False


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
    if rule == "internal-hostname" and line.lstrip().startswith(("import ", "package ")):
        # Dotted Kotlin/Java/Python identifier chains (e.g. `org.gradle.api.tasks.Internal`)
        # are not hostnames; only the TLD-like suffix happens to match.
        return []
    if rule in NETWORK_ADDRESS_RULES:
        messages = []
        for match in pattern.finditer(line):
            value = match.group(0)
            if value.lower() in NETWORK_ADDRESS_ALLOWLIST:
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
        relative_path = path.relative_to(root)
        network_exempt = is_network_address_exempt(relative_path)
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, start=1):
            for rule, pattern in PATTERNS:
                if rule in NETWORK_ADDRESS_RULES and network_exempt:
                    continue
                for match in check_line(line, rule, pattern):
                    findings.append(Finding(path, line_number, rule, excerpt_for(f"{match} | {line}")))

    for finding in findings:
        relative = finding.path.relative_to(root)
        print(f"[FAIL] {relative}:{finding.line} {finding.rule}: {finding.excerpt}")

    print(f"Portability-Check: {scanned} Dateien geprüfst, {len(findings)} Befunde.")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
