"""Create source/portable archives from explicit allowlists, never user data."""
from pathlib import Path
import hashlib
import importlib.metadata
import json
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def main():
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    portable = ROOT / "dist-v0.5" / "VoiceCompanion"
    for name in ("README.md", "requirements-lock.txt", "THIRD_PARTY.md"):
        shutil.copy2(ROOT / name, portable / name)
    (portable / "docs").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "docs" / "VALIDATION.md", portable / "docs" / "VALIDATION.md")
    shutil.copy2(ROOT / "docs" / "PERFORMANCE.md", portable / "docs" / "PERFORMANCE.md")
    shutil.copy2(ROOT / "docs" / "ARCHITECTURE.md", portable / "docs" / "ARCHITECTURE.md")
    shutil.copy2(ROOT / "docs" / "UI.md", portable / "docs" / "UI.md")
    # Preserve installed license texts in portable distributions.
    for package in ("PySide6", "shiboken6", "PyAudioWPatch", "vosk", "fastapi", "uvicorn", "httpx", "keyring", "qrcode", "pillow", "websockets", "pypdf", "pydantic", "starlette", "certifi"):
        dist = importlib.metadata.distribution(package)
        for item in dist.files or []:
            if any(term in item.name.lower() for term in ("license", "copying", "notice")) and str(item).endswith((".txt", ".md", "LICENSE", "COPYING", "NOTICE")):
                path = Path(dist.locate_file(item))
                if path.is_file() and path.stat().st_size < 2000000:
                    target = portable / "third_party_licenses" / package / item.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
    source_files = [ROOT / name for name in ("main.py", "Start.cmd", ".gitignore", "pytest.ini", "README.md", "requirements.txt", "requirements-dev.txt", "requirements-browser.txt", "requirements-lock.txt", "THIRD_PARTY.md")]
    for directory in ("assistant_app", "scripts", "tests", "examples", "docs"):
        for path in (ROOT / directory).rglob("*"):
            if path.is_file() and not any(part in ("__pycache__", ".temp", "test_data", "browser_test_data", "exe_test_data") for part in path.parts):
                if path.suffix in (".py", ".ps1", ".md", ".html", ".json", ".xml", ".png", ".svg"):
                    source_files.append(path)
    source_files.append(ROOT / "models" / "README.md")
    archives = [(release / "VoiceCompanion-source-v0.5.zip", source_files, ROOT),
                (release / "VoiceCompanion-Windows-x64-v0.5.zip", [p for p in portable.rglob("*") if p.is_file()], portable.parent)]
    results = []
    for archive, files, base in archives:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for path in sorted(set(files)):
                z.write(path, path.relative_to(base))
        results.append({"file": archive.name, "bytes": archive.stat().st_size, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()})
    (release / "SHA256.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    main()
