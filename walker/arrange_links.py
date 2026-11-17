"""Bambu Studio で保存したプロジェクト 3MF の「Links」プレートだけを、種類ごとに整列し直す。

ほかのプレートの配置・設定・サムネイルには触れない。書き換えるのは Links プレートの部品の位置(build の item の transform)だけ。
使い方: python walker/arrange_links.py out/3mf/stackchan_strider.3mf [--plate Links]
"""
from __future__ import annotations

import argparse
import math
import re
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np

CORE = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
BED = 180.0
PLATE_STRIDE = BED * 1.2
ROW_GAP = 5.0  # 同じ種類の部品どうしの間隔 [mm]
COLUMN_GAP = 9.0  # 種類の列どうしの間隔 [mm]
BLOCK_GAP = 14.0  # 上段と下段の間隔 [mm]
SMALL_GAP = 6.0  # 小物どうしの間隔 [mm]
# 上段に左から並べる種類と、下段の左に置く種類(名前の先頭で判定)
TOP_ROW = ("Link 1", "Link 2", "Link 3")
BOTTOM_LEFT = "Link 4"


def plate_origin(index: int, count: int) -> tuple[float, float]:
    columns = math.ceil(math.sqrt(count))
    return (index % columns) * PLATE_STRIDE, -(index // columns) * PLATE_STRIDE


def read_project(path: Path, plate_name: str):
    archive = zipfile.ZipFile(path)
    settings = ET.fromstring(archive.read("Metadata/model_settings.config"))
    names = {}
    for obj in settings.findall("object"):
        meta = {m.get("key"): m.get("value") for m in obj.findall("metadata")}
        names[obj.get("id")] = meta.get("name", "")
    plates = settings.findall("plate")
    target = None
    for index, plate in enumerate(plates):
        meta = {m.get("key"): m.get("value") for m in plate.findall("metadata")}
        if meta.get("plater_name", "").strip().lower() == plate_name.lower():
            ids = [m.get("value") for inst in plate.findall("model_instance") for m in inst.findall("metadata") if m.get("key") == "object_id"]
            target = (index, ids)
    if target is None:
        raise RuntimeError(f"プレート {plate_name!r} が見つからない")
    model = archive.read("3D/3dmodel.model").decode("utf-8")
    root = ET.fromstring(model)
    boxes = {}
    for obj in root.find(f"{CORE}resources"):
        if obj.get("id") not in target[1]:
            continue
        component = obj.find(f"{CORE}components/{CORE}component")
        if component.get("transform", "1 0 0 0 1 0 0 0 1 0 0 0").split() != "1 0 0 0 1 0 0 0 1 0 0 0".split():
            raise RuntimeError(f"部品 {names[obj.get('id')]} の内部変換が単位行列でない(想定外の形式)")
        part_path = next(value for key, value in component.attrib.items() if key.endswith("}path"))
        part_root = ET.fromstring(archive.read(part_path.lstrip("/")))
        mesh = next(o for o in part_root.find(f"{CORE}resources") if o.get("id") == component.get("objectid")).find(f"{CORE}mesh")
        vertices = np.array([[float(v.get(axis)) for axis in "xyz"] for v in mesh.find(f"{CORE}vertices")])
        boxes[obj.get("id")] = (vertices.min(axis=0), vertices.max(axis=0))
    return model, names, target[0], len(plates), target[1], boxes


def layout(ids, names, boxes) -> dict[str, tuple[float, float]]:
    """部品ごとの「外形の左下」の位置(プレート内 mm)を返す。種類ごとに縦へ積んだ列を作る。"""
    size = {i: boxes[i][1] - boxes[i][0] for i in ids}
    groups: dict[str, list[str]] = {}
    for i in ids:
        groups.setdefault(names[i], []).append(i)

    def group(prefix: str) -> list[str]:
        found = [members for name, members in groups.items() if name.startswith(prefix)]
        if len(found) != 1:
            raise RuntimeError(f"{prefix!r} で始まる部品の種類が {len(found)} 個ある(1 個のはず)")
        return found[0]

    def block_height(members) -> float:
        return sum(size[i][1] for i in members) + ROW_GAP * (len(members) - 1)

    top = [group(prefix) for prefix in TOP_ROW]
    bottom_left = group(BOTTOM_LEFT)
    small = [i for i in ids if i not in bottom_left and not any(i in members for members in top)]
    top_height = max(block_height(members) for members in top)
    bottom_height = block_height(bottom_left)
    widths = [max(size[i][0] for i in members) for members in top]
    total_width = sum(widths) + COLUMN_GAP * (len(widths) - 1)
    total_height = top_height + BLOCK_GAP + bottom_height
    x0, y0 = (BED - total_width) / 2, (BED - total_height) / 2
    place = {}

    def stack(members, x: float, top_y: float) -> None:
        y = top_y
        for i in members:
            y -= size[i][1]
            place[i] = (x, y)
            y -= ROW_GAP

    x = x0
    columns = []
    for members, width in zip(top, widths):
        columns.append(x)
        stack(members, x, y0 + total_height)
        x += width + COLUMN_GAP
    stack(bottom_left, columns[0], y0 + bottom_height)
    # 小物(シャフト、スリーブ、クリップ)は下段の 2 列目から。長いものを下、短いものをその上に横一列
    small.sort(key=lambda i: -size[i][0])
    longest, rest = small[0], small[1:]
    place[longest] = (columns[1], y0)
    x = columns[1]
    row_y = y0 + size[longest][1] + SMALL_GAP + 2.0
    for i in rest:
        place[i] = (x, row_y)
        x += size[i][0] + SMALL_GAP
    return place


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("--plate", default="Links")
    args = parser.parse_args()
    path = Path(args.project)
    model, names, plate_index, plate_count, ids, boxes = read_project(path, args.plate)
    origin = plate_origin(plate_index, plate_count)
    place = layout(ids, names, boxes)
    for i in ids:
        low, _ = boxes[i]
        x, y = place[i]
        transform = f"1 0 0 0 1 0 0 0 1 {origin[0] + x - low[0]:.4f} {origin[1] + y - low[1]:.4f} {-low[2]:.4f}"
        pattern = re.compile(r'(<item objectid="' + re.escape(i) + r'"[^>]*transform=")[^"]+(")')
        model, count = pattern.subn(lambda match: match.group(1) + transform + match.group(2), model)
        if count != 1:
            raise RuntimeError(f"部品 {i}({names[i]})の配置行が {count} 個見つかった(1 個のはず)")
    temporary = path.with_suffix(".tmp")
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as out:
        for info in source.infolist():
            data = model.encode("utf-8") if info.filename == "3D/3dmodel.model" else source.read(info.filename)
            out.writestr(info, data)
    shutil.move(temporary, path)
    for name in dict.fromkeys(names[i] for i in ids):
        members = [i for i in ids if names[i] == name]
        spots = ", ".join(f"({place[i][0]:.1f}, {place[i][1]:.1f})" for i in members)
        print(f"{name} ×{len(members)}: {spots}")
    print(f"書き換え: {path}(プレート {plate_index + 1}「{args.plate}」の {len(ids)} 個)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
