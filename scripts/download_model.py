"""Download official small Chinese model; no arbitrary model code is executed."""
import hashlib
import json
from pathlib import Path
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
URL = "https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip"

def main():
    target = ROOT / "models"
    target.mkdir(exist_ok=True)
    model = target / "vosk-model-small-cn-0.22"
    if (model / "am" / "final.mdl").exists():
        print("Model already installed:", model)
        return
    archive = target / "chinese-model.zip.part"
    print("Downloading official Chinese model (~42MB)...", flush=True)
    try:
        with urllib.request.urlopen(URL, timeout=60) as response, archive.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                resolved = (target / info.filename).resolve()
                if not resolved.is_relative_to(target.resolve()) or info.file_size > 200 * 1024 * 1024:
                    raise ValueError("Unsafe model archive")
            z.extractall(target)
        (target / "download_record.json").write_text(json.dumps({"url": URL, "sha256_downloaded": digest, "note": "HTTPS source; local digest is a download record, not an upstream signature"}, indent=2), encoding="utf-8")
        print("Installed:", model, flush=True)
    finally:
        archive.unlink(missing_ok=True)

if __name__ == "__main__":
    main()
