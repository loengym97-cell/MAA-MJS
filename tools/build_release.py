"""构建不含本机配置和排障数据的发布包。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIRS = ("python", "deps", "libs", "runtimes", "plugins")
RUNTIME_FILES = (
    "MFAAvalonia.exe",
    "MFAAvalonia.dll",
    "MFAAvalonia.deps.json",
    "MFAAvalonia.runtimeconfig.json",
    "libloader.dll",
    "DependencySetup_依赖库安装_win.bat",
    "收集排障信息.bat",
)
SOURCE_FILES = (
    "interface.json",
    "README.md",
    "AGENTS.md",
    "LICENSE",
    "collect_diag.py",
    "config/maa_option.json",
    "experimental/strategy_v0_1/README.md",
)
SKIP_PARTS = {"__pycache__", "debug", "logs", "temp", "backup", "tests"}


def allowed(path: Path) -> bool:
    return path.is_file() and not (SKIP_PARTS & set(path.parts)) and path.suffix not in {".pyc", ".log"}


def tracked_sources() -> set[Path]:
    result = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    paths = {Path(raw.decode("utf-8")) for raw in result.split(b"\0") if raw}
    return {
        path for path in paths
        if path.parts[0] in {"resource", "agent"}
        or path.parts[:3] == ("experimental", "strategy_v0_1", "resource")
        or path == Path("experimental/strategy_v0_1/千里策略试验版.py")
    }


def main() -> None:
    version = json.loads((ROOT / "interface.json").read_text(encoding="utf-8-sig"))["version"]
    output = ROOT / "MJS" / f"MAA-MJS-{version}.zip"
    files = {Path(name) for name in RUNTIME_FILES + SOURCE_FILES} | tracked_sources()
    for directory in RUNTIME_DIRS:
        files.update(path.relative_to(ROOT) for path in (ROOT / directory).rglob("*") if path.is_file())
    files = {path for path in files if allowed(path)}
    missing = [str(path) for path in files if not (ROOT / path).is_file()]
    if missing:
        raise FileNotFoundError(f"缺少打包文件：{missing}")
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for path in sorted(files):
            archive.write(ROOT / path, (Path("MAA_MJS") / path).as_posix())
        archive.writestr("MAA_MJS/appsettings.json", '{"AnnouncementInfo.DoNotShowAgain":"False"}\n')
        archive.writestr("MAA_MJS/config/config.json", '{"CurrentLanguage":"zh-CN"}\n')

    digest = hashlib.sha256()
    with output.open("rb") as package:
        for chunk in iter(lambda: package.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    print(f"发布包：{output}\n文件数：{len(files) + 2}\nSHA-256：{digest.hexdigest()}")


if __name__ == "__main__":
    main()
