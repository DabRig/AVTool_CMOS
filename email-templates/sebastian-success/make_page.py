"""Build the "copy into Gmail" page for the Sebastian Success email.

The page previews the email with its images embedded (so the animation plays
right there) and has a Copy button that puts the email on the clipboard with
the images pointing at their public URLs. Pasted into a Gmail reply, Gmail
loads those URLs, so the stars keep moving for the recipient.

Usage:  python3 make_page.py <public-assets-base-url> <output.html>
"""
import base64
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
MIME = {".gif": "image/gif", ".png": "image/png"}


def data_uri(name):
    with open(os.path.join(OUT, name), "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{MIME[os.path.splitext(name)[1]]};base64,{b64}"


def email_text(email_html):
    """Plain-text alternative: one line per text block."""
    body = re.sub(r"<img[^>]*>", "", email_html)
    lines = [html.unescape(re.sub(r"<[^>]+>", "", m)).strip()
             for m in re.findall(r"<div[^>]*>(.*?)</div>", body, re.S)]
    lines = [l for l in lines if l and l != "\xa0" and "<" not in l]
    return "\n".join(lines) + "\n"


def main():
    assets, dest = sys.argv[1].rstrip("/"), sys.argv[2]
    template = open(os.path.join(HERE, "email.html"), encoding="utf-8").read()
    public_html = template.replace("{{ASSETS}}", assets)
    preview_html = template
    for name in ("hero.gif", "divider.gif", "sig.png"):
        preview_html = preview_html.replace("{{ASSETS}}/" + name, data_uri(name))

    page = open(os.path.join(HERE, "page_template.html"), encoding="utf-8").read()
    page = page.replace("<!--PREVIEW-->", preview_html)
    page = page.replace("/*EMAIL_HTML*/null", json.dumps(public_html))
    page = page.replace("/*EMAIL_TEXT*/null", json.dumps(email_text(template)))
    with open(dest, "w", encoding="utf-8") as f:
        f.write(page)
    print(dest, os.path.getsize(dest) // 1024, "KB")


if __name__ == "__main__":
    main()
