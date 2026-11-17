"""公開用のファイルを out/ から写す。リポジトリには out/ を入れず、ここで写したものだけを入れる。

  print/stl/*.stl               印刷用 STL(造形時の向き。ファイル名末尾の _x4 などが必要個数)
  print/stackchan_strider.3mf   Bambu Studio のプロジェクト(全プレート)。作者のアカウント ID は消して写す
  docs/index.html               組立ガイド(GitHub Pages 用)
  docs/viewer.html              3D ビューアー
先に build.py、update_project.py、export_viewer.py、export_guide.py を実行しておく。
使い方: python walker/publish_files.py [--project out/3mf/stackchan_strider_updated.3mf]
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"
STL_NAME = re.compile(r".+_x\d+\.stl")  # build.py が出す名前(末尾が必要個数)


def copy_project(source: Path, target: Path) -> None:
    """3MF を写す。Bambu Studio が書き込む作者のアカウント ID(DesignerUserId)は空にする。"""
    with zipfile.ZipFile(source) as archive, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as out:
        for info in archive.infolist():
            data = archive.read(info.filename)
            if info.filename == "3D/3dmodel.model":
                text = data.decode("utf-8")
                text, count = re.subn(r'(<metadata name="DesignerUserId">)[^<]*(</metadata>)', r"\1\2", text)
                if count != 1:
                    raise RuntimeError(f"{source.name}: DesignerUserId が {count} か所(1 か所のはず)")
                data = text.encode("utf-8")
            out.writestr(info, data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=str(OUT / "3mf" / "stackchan_strider_updated.3mf"))
    args = parser.parse_args()
    stl_dir = ROOT / "print" / "stl"
    if stl_dir.exists():
        shutil.rmtree(stl_dir)
    stl_dir.mkdir(parents=True)
    names = sorted(path.name for path in (OUT / "stl").glob("*.stl") if STL_NAME.fullmatch(path.name))
    for name in names:
        shutil.copyfile(OUT / "stl" / name, stl_dir / name)
    copy_project(Path(args.project), ROOT / "print" / "stackchan_strider.3mf")
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    shutil.copyfile(OUT / "guide" / "index.html", docs / "index.html")
    shutil.copyfile(OUT / "viewer" / "index.html", docs / "viewer.html")
    print(f"print/stl: {len(names)} 個、print/stackchan_strider.3mf、docs/index.html(組立ガイド)、docs/viewer.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
