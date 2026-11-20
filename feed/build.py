"""静的サイトの生成: web/ と data/ を _site/ にまとめる（GitHub Pages に置くもの）。"""
from __future__ import annotations

import shutil

from .common import DATA, ROOT


def build_site():
    out = ROOT / "_site"
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "web", out)
    (out / "data").mkdir()
    shutil.copytree(DATA / "daily", out / "data" / "daily")
    shutil.copy(DATA / "index.json", out / "data" / "index.json")
    (out / ".nojekyll").touch()
    print(f"■ サイト生成: {out}")


if __name__ == "__main__":
    build_site()
