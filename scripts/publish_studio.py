"""Build the password-protected web copy of the Pricing Studio in docs/ (served by GitHub Pages).

The studio code is copied as is; every data file is gzipped and AES-256-GCM encrypted with a key
derived from the password (PBKDF2-SHA256). The browser asks for the password and decrypts the data.
The password is read from STUDIO_PASSWORD in .env; if missing, a new one is made and saved there.

Run after scripts/build_studio_data.py:  python scripts/publish_studio.py
"""
import base64
import gzip
import json
import os
import secrets
import shutil
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).resolve().parents[1]
SRC, OUT = ROOT / "dashboard", ROOT / "docs"
ITER = 310_000
WORDS = ("mango baobab coast savanna harbour market basket cashew palm river "
         "sunrise kwanza lobito huila namibe cabinda benguela marula tamarind papaya").split()


def password():
    env = ROOT / ".env"
    for line in env.read_text(encoding="utf-8").splitlines() if env.exists() else []:
        if line.startswith("STUDIO_PASSWORD="):
            return line.split("=", 1)[1].strip(), False
    pw = "-".join(w.capitalize() for w in secrets.SystemRandom().sample(WORDS, 3)) + f"-{secrets.randbelow(90) + 10}"
    with env.open("a", encoding="utf-8") as f:
        f.write(f"\nSTUDIO_PASSWORD={pw}\n")
    return pw, True


def seal(aes, raw):
    iv = secrets.token_bytes(12)
    return iv + aes.encrypt(iv, gzip.compress(raw, 9), None)


def main():
    pw, new = password()
    salt = secrets.token_bytes(16)
    key = PBKDF2HMAC(hashes.SHA256(), 32, salt, ITER).derive(pw.encode())
    aes = AESGCM(key)

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "studio" / "data").mkdir(parents=True)
    (OUT / ".nojekyll").touch()
    shutil.copy(SRC / "d3.min.js", OUT / "d3.min.js")
    (OUT / "index.html").write_text('<!doctype html><meta charset="utf-8"><title>Fresmart Pricing Studio</title>'
                                    '<meta http-equiv="refresh" content="0; url=studio/">'
                                    '<meta name="robots" content="noindex"><a href="studio/">Open the Pricing Studio</a>\n', encoding="utf-8")
    for f in ("index.html", "studio.css", "studio.js", "fresmart_logo.png"):
        shutil.copy(SRC / "studio" / f, OUT / "studio" / f)
    html = OUT / "studio" / "index.html"
    html.write_text(html.read_text(encoding="utf-8").replace('<meta charset="utf-8">', '<meta charset="utf-8">\n<meta name="robots" content="noindex">', 1), encoding="utf-8")

    n = size = 0
    for f in sorted((SRC / "studio" / "data").rglob("*.json")):
        dst = OUT / "studio" / "data" / (str(f.relative_to(SRC / "studio" / "data")) + ".enc")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(seal(aes, f.read_bytes()))
        n, size = n + 1, size + dst.stat().st_size
    lock = {"salt": base64.b64encode(salt).decode(), "iter": ITER, "check": base64.b64encode(seal(aes, b"fresmart")).decode()}
    (OUT / "studio" / "data" / "lock.json").write_text(json.dumps(lock), encoding="utf-8")

    print(f"docs/: {n} data files encrypted, {size / 1e6:.1f} MB")
    print(f"Password {'(new, saved in .env)' if new else '(from .env)'}: {pw}")


if __name__ == "__main__":
    main()
