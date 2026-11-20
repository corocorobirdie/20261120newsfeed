"""静的サイトの生成: web/ と data/ を _site/ にまとめる（GitHub Pages に置くもの）。"""
from __future__ import annotations

import shutil

import json

from .common import DATA, ROOT, load_yaml


def build_site():
    out = ROOT / "_site"
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "web", out)
    (out / "data").mkdir()
    shutil.copytree(DATA / "daily", out / "data" / "daily")
    shutil.copy(DATA / "index.json", out / "data" / "index.json")
    (out / ".nojekyll").touch()
    cfg = load_yaml("config.yaml")
    ac = cfg.get("ask_claude") or {}
    site = {"ask_claude_url": ac.get("url") or "", "ask_claude_tabs": ac.get("tabs") or {}}
    (out / "site-config.json").write_text(json.dumps(site, ensure_ascii=False), encoding="utf-8")
    print(f"■ サイト生成: {out}")


if __name__ == "__main__":
    build_site()
