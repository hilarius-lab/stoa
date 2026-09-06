from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def read_config_value(path: Path, key: str) -> str:
    if not path.is_file():
        return ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key:
            return value.strip().strip("\"'")
    return ""


def resolve_tool(name: str, repo_root: Path) -> Path | None:
    if "/" in name or "\\" in name:
        tool_path = Path(name).expanduser()
        if not tool_path.is_absolute():
            tool_path = repo_root / tool_path
        return tool_path if tool_path.exists() else None
    resolved = shutil.which(name)
    if resolved:
        return Path(resolved)
    return None


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    local_config = Path(__file__).resolve().with_name("graphify.local.env")
    tool_name = os.environ.get("GRAPHIFY_TOOL", "").strip()
    if not tool_name:
        tool_name = read_config_value(local_config, "GRAPHIFY_TOOL")
    if not tool_name:
        print("Graphify ist optional und ist lokal nicht konfiguriert.")
        print("Setze GRAPHIFY_TOOL oder lege scripts/graphify.local.env mit GRAPHIFY_TOOL an.")
        return 0

    tool_path = resolve_tool(tool_name, repo_root)
    if tool_path is None:
        print(f"Graphify-Tool nicht gefunden: {tool_name}")
        print("Pruefe GRAPHIFY_TOOL beziehungsweise scripts/graphify.local.env.")
        return 1

    output_dir = repo_root / ".work" / "graphify-out"
    output_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["GRAPHIFY_OUT"] = str(output_dir)
    command = [sys.executable, str(tool_path), *sys.argv[1:]] if tool_path.suffix == ".py" else [str(tool_path), *sys.argv[1:]]
    return subprocess.call(command, cwd=repo_root, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
