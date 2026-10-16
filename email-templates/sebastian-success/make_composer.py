"""Build the Sebastian Success Mail composer page.

The page lets you type a message, previews the email with the animated
images embedded, and copies it for Gmail with the images pointing at their
public URLs (Gmail loads those, so the stars keep moving for the recipient).

Usage:  python3 make_composer.py <public-assets-base-url> <output.html>
"""
import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
FILES = {"hero": "hero-space.gif", "divider": "divider.gif", "sig": "sig.png"}
MIME = {".gif": "image/gif", ".png": "image/png"}


def data_uri(name):
    with open(os.path.join(OUT, name), "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{MIME[os.path.splitext(name)[1]]};base64,{b64}"


def main():
    base, dest = sys.argv[1].rstrip("/"), sys.argv[2]
    public = {k: f"{base}/{v}" for k, v in FILES.items()}
    embed = {k: data_uri(v) for k, v in FILES.items()}
    page = open(os.path.join(HERE, "composer_template.html"), encoding="utf-8").read()
    for marker, value in (("/*PUBLIC_URLS*/null", public), ("/*EMBED_URLS*/null", embed)):
        assert marker in page, marker
        page = page.replace(marker, json.dumps(value))
    with open(dest, "w", encoding="utf-8") as f:
        f.write(page)
    print(dest, os.path.getsize(dest) // 1024, "KB")


if __name__ == "__main__":
    main()
