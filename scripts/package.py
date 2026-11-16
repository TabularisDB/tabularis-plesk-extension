#!/usr/bin/env python3
"""Build the same installable ZIP from the same source, without local secrets."""
from pathlib import Path
import argparse
import hashlib
import stat
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
INCLUDED = ("_meta", "htdocs", "plib", "sbin")


def build(destination: Path) -> str:
    manifest = ET.parse(ROOT / "meta.xml").getroot()
    if manifest.findtext("id") != "tabularis" or manifest.findtext("os") != "unix":
        raise ValueError("Invalid extension manifest")
    files = [ROOT / "meta.xml", ROOT / "LICENSE"]
    for directory in INCLUDED:
        files.extend(p for p in (ROOT / directory).rglob("*") if p.is_file()
                     and "__pycache__" not in p.parts and p.suffix != ".pyc")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(files):
            if path.is_symlink() or path.suffix in (".key", ".pem"):
                raise ValueError("Unsafe package input")
            name = path.relative_to(ROOT).as_posix()
            entry = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if name.startswith("sbin/") else 0o644
            entry.external_attr = (stat.S_IFREG | mode) << 16
            archive.writestr(entry, path.read_bytes())
    return hashlib.sha256(destination.read_bytes()).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/tabularis-0.1.0.zip")
    args = parser.parse_args()
    print(f"{build(args.output)}  {args.output}")
