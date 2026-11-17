"""Bambu Studio で保存したプロジェクト 3MF の配置をそのまま保ち、部品の形状だけを最新の設計に置き換える。

プレートの分け方、部品の位置と向き、色、印刷設定には触れない。書き換えるのは各部品のメッシュ(3D/Objects/*.model)と面数の記録だけ。
新しい形状は、元の形状と同じ向きで、XY は外形の中心、Z は底面を合わせて置く(高さが変わっても底面がベッドに着いたままになる)。
元の形状と大きく違う部品(向きの取り違えなど)があれば、書き出さずにエラーにする。
部品の個数が増えたときは --add "部品名=個数" で、同じ部品の複製を、その部品があるプレートの空いた所へ並べて足す。
使い方: python walker/update_project.py out/3mf/stackchan_strider.3mf out/3mf/stackchan_strider_updated.3mf [--reshaped "A;B"] [--add "C-clip=20"]
"""
from __future__ import annotations

import argparse
import math
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np
from manifold3d import Manifold, Mesh

import build

CORE = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
MAX_CHANGE = 0.08  # 元の形状との違い(体積比)の上限。穴まわりを変えた薄い部品で 5% 程度になる。これを超えたら別の部品か向き違いとみなす
MAX_SIZE_CHANGE = 0.5  # 外形寸法(XYZ それぞれ)の変化の上限 [mm]
KEY_BY_NAME = {name: key for key, name in build.ENGLISH_NAMES.items()}


def read_mesh(xml: str) -> Manifold:
    root = ET.fromstring(xml)
    mesh = root.find(f"{CORE}resources/{CORE}object/{CORE}mesh")
    vertices = np.array([[float(v.get(a)) for a in "xyz"] for v in mesh.find(f"{CORE}vertices")], dtype=np.float32)
    triangles = np.array([[int(t.get(a)) for a in ("v1", "v2", "v3")] for t in mesh.find(f"{CORE}triangles")], dtype=np.uint32)
    return Manifold(Mesh(vert_properties=vertices, tri_verts=triangles))


def mesh_xml(shape: Manifold) -> tuple[str, int]:
    mesh = shape.to_mesh()
    vertices = np.asarray(mesh.vert_properties)[:, :3]
    triangles = np.asarray(mesh.tri_verts)
    lines = ["   <mesh>", "    <vertices>"]
    lines += [f'     <vertex x="{x:.7g}" y="{y:.7g}" z="{z:.7g}"/>' for x, y, z in vertices]
    lines += ["    </vertices>", "    <triangles>"]
    lines += [f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in triangles]
    lines += ["    </triangles>", "   </mesh>"]
    return "\n".join(lines), len(triangles)


BED = 180.0
PLATE_STRIDE = BED * 1.2
ADD_GAP = 2.3  # 足す部品どうし、ほかの部品との間隔 [mm]
BED_MARGIN = 4.0


def _vertices(xml: str) -> np.ndarray:
    return np.asarray(read_mesh(xml).to_mesh().vert_properties)[:, :3]


def _item_matrix(text: str) -> tuple[np.ndarray, np.ndarray]:
    values = [float(v) for v in text.split()]
    return np.array(values[:9]).reshape(3, 3), np.array(values[9:])


def add_copies(files: dict, name: str, count: int) -> str:
    """部品 name の複製を count 個、その部品があるプレートの空いた所へ格子状に並べて足す。files(3MF の中身)を書き換える。"""
    settings, model = files["Metadata/model_settings.config"], files["3D/3dmodel.model"]
    root = ET.fromstring(settings)
    objects = {obj.get("id"): obj for obj in root.findall("object")}
    donors = [oid for oid, obj in objects.items() if {m.get("key"): m.get("value") for m in obj.findall("metadata")}.get("name") == name]
    if not donors:
        raise RuntimeError(f"元のファイルに {name!r} が無い")
    plates = root.findall("plate")
    plate_index, plate_ids = None, []
    for index, plate in enumerate(plates):
        ids = [m.get("value") for inst in plate.findall("model_instance") for m in inst.findall("metadata") if m.get("key") == "object_id"]
        if donors[0] in ids:
            plate_index, plate_ids = index, ids
    columns = math.ceil(math.sqrt(len(plates)))
    ox, oy = (plate_index % columns) * PLATE_STRIDE, -(plate_index // columns) * PLATE_STRIDE
    # プレート上の部品の外接長方形で、ふさがっている所を 0.5 mm の升目に記録する
    components = dict(re.findall(r'<object id="(\d+)"[^>]*>\s*<components>\s*<component p:path="/([^"]+)"', model))
    items = dict(re.findall(r'<item objectid="(\d+)"[^>]*transform="([^"]+)"', model))
    cell = 0.5
    size = int(BED / cell)
    busy = np.zeros((size, size), dtype=bool)
    donor_box, centers = None, []
    for oid in plate_ids:
        rotation, shift = _item_matrix(items[oid])
        points = _vertices(files[components[oid]]) @ rotation + shift
        low, high = points.min(axis=0), points.max(axis=0)
        if oid in donors:
            donor_box = high - low
            centers.append((low[:2] + high[:2]) / 2)
        x0, y0 = int((low[0] - ox - ADD_GAP) / cell), int((low[1] - oy - ADD_GAP) / cell)
        x1, y1 = int(math.ceil((high[0] - ox + ADD_GAP) / cell)), int(math.ceil((high[1] - oy + ADD_GAP) / cell))
        busy[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = True
    pitch_x, pitch_y = donor_box[0] + ADD_GAP, donor_box[1] + ADD_GAP
    near = np.mean(centers, axis=0) - (ox, oy)
    filled = np.cumsum(np.cumsum(busy, axis=0), axis=1)  # 長方形の中のふさがりを一度に数えるための累積和

    def blocked(x0: float, y0: float, x1: float, y1: float) -> bool:
        a, b, c, e = int(x0 / cell), int(y0 / cell), int(math.ceil(x1 / cell)) - 1, int(math.ceil(y1 / cell)) - 1
        total = filled[e, c] - (filled[b - 1, c] if b else 0) - (filled[e, a - 1] if a else 0) + (filled[b - 1, a - 1] if a and b else 0)
        return total > 0

    best = None
    for cols in range(1, count + 1):
        rows = math.ceil(count / cols)
        if cols * rows != count:
            continue
        width, depth = cols * pitch_x - ADD_GAP, rows * pitch_y - ADD_GAP
        for y in np.arange(BED_MARGIN, BED - BED_MARGIN - depth, 1.0):
            for x in np.arange(BED_MARGIN, BED - BED_MARGIN - width, 1.0):
                if blocked(x, y, x + width, y + depth):
                    continue
                # 元からある同じ部品に近く、まとまった形(縦横の差が小さい)を選ぶ
                score = math.hypot(x + width / 2 - near[0], y + depth / 2 - near[1]) + 0.3 * abs(width - depth)
                if best is None or score < best[0]:
                    best = (score, cols, rows, x, y)
    if best is None:
        raise RuntimeError(f"{name} を {count} 個並べる空きが、プレート {plate_index + 1} に無い")
    _score, cols, rows, x_start, y_start = best

    donor = donors[0]
    donor_xml = files[components[donor]]
    donor_part = re.search(r'<object id="(\d+)"', donor_xml).group(1)
    donor_block = re.search(rf'  <object id="{donor}">.*?</object>\n', settings, flags=re.S).group(0)
    donor_height = float(items[donor].split()[11])
    next_id = max(int(v) for v in re.findall(r'<(?:object|part) id="(\d+)"', settings)) + 1
    next_file = max(int(v) for v in re.findall(r"object_(\d+)\.model", files["3D/_rels/3dmodel.model.rels"])) + 1
    next_identify = max(int(v) for v in re.findall(r'key="identify_id" value="(\d+)"', settings)) + 22
    new_objects, new_items, new_blocks, new_instances, new_assemble, new_rels, new_cuts = [], [], [], [], [], [], []
    for index in range(count):
        part_id, object_id, number = next_id + 2 * index, next_id + 2 * index + 1, next_file + index
        file_name = f"3D/Objects/object_{number}.model"
        files[file_name] = re.sub(r'<object id="\d+" p:UUID="[0-9a-f]{8}', f'<object id="{part_id}" p:UUID="{number:04x}0000', donor_xml, count=1)
        x = ox + x_start + (index % cols) * pitch_x + donor_box[0] / 2
        y = oy + y_start + (index // cols) * pitch_y + donor_box[1] / 2
        new_objects.append(f'  <object id="{object_id}" p:UUID="{number:08x}-61cb-4c03-9d28-80fed5dfa1dc" type="model">\n   <components>\n'
                           f'    <component p:path="/{file_name}" objectid="{part_id}" p:UUID="{number:04x}0000-b206-40ff-9872-83e8017abed1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>\n'
                           f"   </components>\n  </object>\n")
        new_items.append(f'  <item objectid="{object_id}" p:UUID="{object_id:08x}-b1ec-4553-aec9-835e5b724bb4" transform="1 0 0 0 1 0 0 0 1 {x:.4f} {y:.4f} {donor_height:.4f}" printable="1"/>\n')
        new_blocks.append(donor_block.replace(f'<object id="{donor}">', f'<object id="{object_id}">').replace(f'<part id="{donor_part}"', f'<part id="{part_id}"'))
        new_instances.append(f'    <model_instance>\n      <metadata key="object_id" value="{object_id}"/>\n      <metadata key="instance_id" value="0"/>\n'
                             f'      <metadata key="identify_id" value="{next_identify + 22 * index}"/>\n    </model_instance>\n')
        new_assemble.append(f'   <assemble_item object_id="{object_id}" instance_id="0" transform="1 0 0 0 1 0 0 0 1 {x:.3f} {y:.3f} 0" offset="0 0 0" />\n')
        new_rels.append(f' <Relationship Target="/{file_name}" Id="rel-{number}" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n')
        new_cuts.append(f' <object id="{number}">\n  <cut_id id="0" check_sum="1" connectors_cnt="0"/>\n </object>\n')

    def insert(text: str, marker: str, addition: str, last: bool = False) -> str:
        position = text.rindex(marker) if last else text.index(marker)
        return text[:position] + addition + text[position:]

    files["3D/3dmodel.model"] = insert(insert(model, " </resources>", "".join(new_objects)), " </build>", "".join(new_items))
    settings = insert(settings, "  <plate>", "".join(new_blocks))
    # 対象のプレートの終わり(その plate の </plate>)の直前にインスタンスを足す
    starts = [m.start() for m in re.finditer(r"  <plate>", settings)]
    end = settings.index("  </plate>", starts[plate_index])
    settings = settings[:end] + "".join(new_instances) + settings[end:]
    files["Metadata/model_settings.config"] = insert(settings, "  </assemble>", "".join(new_assemble), last=True)
    files["3D/_rels/3dmodel.model.rels"] = insert(files["3D/_rels/3dmodel.model.rels"], "</Relationships>", "".join(new_rels))
    files["Metadata/cut_information.xml"] = insert(files["Metadata/cut_information.xml"], "</objects>", "".join(new_cuts))
    return f"{name} を {count} 個足した(プレート {plate_index + 1}、{cols}×{rows} 個、プレート左下から x={x_start:.0f} y={y_start:.0f} mm)"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("output")
    parser.add_argument("--add", default="", help="足す部品。「部品名=個数」を ; 区切りで")
    parser.add_argument("--reshaped", default="", help="形を意図して大きく変えた部品名(名前にカンマがあるので ; 区切り)。この部品だけ、元の形状との照合を省く")
    args = parser.parse_args()
    source, output = Path(args.source), Path(args.output)
    reshaped = {name.strip() for name in args.reshaped.split(";") if name.strip()}
    unknown = reshaped - set(KEY_BY_NAME)
    if unknown:
        raise SystemExit(f"知らない部品名: {sorted(unknown)}")
    if source.resolve() == output.resolve():
        raise SystemExit("元のファイルには上書きしない。別の出力名を指定する")
    archive = zipfile.ZipFile(source)
    settings = archive.read("Metadata/model_settings.config").decode("utf-8")
    names = {}  # 部品ファイルの中の object id(= model_settings の part id) → 部品名
    for obj in ET.fromstring(settings).findall("object"):
        part = obj.find("part")
        names[part.get("id")] = {m.get("key"): m.get("value") for m in obj.findall("metadata")}.get("name", "")
    replaced, faces = {}, {}
    for info in archive.infolist():
        if not re.fullmatch(r"3D/Objects/object_\d+\.model", info.filename):
            continue
        xml = archive.read(info.filename).decode("utf-8")
        part_id = re.search(r'<object id="(\d+)"', xml).group(1)
        name = names[part_id]
        if name not in KEY_BY_NAME:
            raise RuntimeError(f"{info.filename}: 部品名 {name!r} がどの部品か分からない")
        key = KEY_BY_NAME[name]
        old = read_mesh(xml)
        new = build.print_shape(key)
        ob, nb = old.bounding_box(), new.bounding_box()
        new = new.translate(((ob[0] + ob[3] - nb[0] - nb[3]) / 2, (ob[1] + ob[4] - nb[1] - nb[4]) / 2, ob[2] - nb[2]))
        size_change = max(abs((nb[i + 3] - nb[i]) - (ob[i + 3] - ob[i])) for i in range(3))
        if size_change > MAX_SIZE_CHANGE and name not in reshaped:
            raise RuntimeError(f"{info.filename}({name}): 外形寸法が {size_change:.2f} mm 違う。向きか部品の対応が違う")
        change = ((old - new).volume() + (new - old).volume()) / old.volume()
        if change > MAX_CHANGE and name not in reshaped:
            raise RuntimeError(f"{info.filename}({name}): 元の形状との違いが {change:.1%}。向きか部品の対応が違う")
        body, count = mesh_xml(new)
        start, end = xml.index("   <mesh>"), xml.index("</mesh>") + len("</mesh>")
        replaced[info.filename] = xml[:start] + body + xml[end:]
        faces[part_id] = count
        print(f"{info.filename:32s} {name:24s} 形状の違い {change:7.3%}  外形の変化 {size_change:.2f} mm  高さ {ob[5] - ob[2]:.2f} → {new.bounding_box()[5] - new.bounding_box()[2]:.2f}")

    def refresh_counts(match: re.Match) -> str:
        block = match.group(0)
        part_id = re.search(r'<part id="(\d+)"', block).group(1)
        block = re.sub(r'<metadata face_count="\d+"/>', f'<metadata face_count="{faces[part_id]}"/>', block)
        return re.sub(r'<mesh_stat face_count="\d+"', f'<mesh_stat face_count="{faces[part_id]}"', block)

    settings = re.sub(r"<object id=.*?</object>", refresh_counts, settings, flags=re.S)
    text_files = ("Metadata/model_settings.config", "3D/3dmodel.model", "3D/_rels/3dmodel.model.rels", "Metadata/cut_information.xml")
    files = {name: archive.read(name).decode("utf-8") for name in text_files}
    files["Metadata/model_settings.config"] = settings
    files.update(replaced)
    for entry in [e for e in args.add.split(";") if e.strip()]:
        name, count = entry.rsplit("=", 1)
        print(add_copies(files, name.strip(), int(count)))
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as out:
        written = set()
        for info in archive.infolist():
            if info.filename in files:
                out.writestr(info.filename, files[info.filename])
            else:
                out.writestr(info, archive.read(info.filename))
            written.add(info.filename)
        for name in sorted(set(files) - written):
            out.writestr(name, files[name])
    print(f"{output}: {len(replaced)} 部品の形状を置き換えた(配置は {source.name} のまま)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
