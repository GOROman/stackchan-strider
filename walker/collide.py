"""部品どうしの干渉(重なり体積)を調べる共通処理。"""
from __future__ import annotations

import itertools

import numpy as np

import design as d

# これ未満の重なり体積 [mm^3] は、面どうしが接しているだけの数値誤差として扱う
VOLUME_TOL = 0.02


def _boxes_overlap(a, b) -> bool:
    return all(a[i] < b[i + 3] and b[i] < a[i + 3] for i in range(3))


def _stackchan_internal(a: str, b: str) -> bool:
    """スタックチャン自身の部品どうし(製品側の話で、こちらの配置は推定)は判定しない。"""
    return a.startswith("sc_") and b.startswith("sc_")


DEFAULT_SKIP = frozenset()


def find_collisions(theta: float, head_yaw: float = 0.0, with_stackchan: bool = True, skip_pairs=DEFAULT_SKIP,
                    head_pitch: float = 0.0, nudge=None):
    """クランク角 theta での干渉ペアを (名前A, 名前B, 重なり体積) のリストで返す。

    nudge = {部品名: 4x4行列} を渡すと、その部品だけ追加で動かして調べる(ガタや自己診断用)。
    """
    placed = []
    for inst in d.instances(theta, head_yaw, with_stackchan, head_pitch):
        shape = d.placed(inst)
        if nudge and inst.name in nudge:
            shape = d.apply(shape, nudge[inst.name])
        placed.append((inst, shape, shape.bounding_box()))
    hits = []
    for (ia, sa, ba), (ib, sb, bb) in itertools.combinations(placed, 2):
        if frozenset((ia.name, ib.name)) in skip_pairs or _stackchan_internal(ia.name, ib.name):
            continue
        if not _boxes_overlap(ba, bb):
            continue
        volume = (sa ^ sb).volume()
        if volume > VOLUME_TOL:
            hits.append((ia.name, ib.name, volume))
    return hits


def min_gap(theta: float, name_a: str, name_b: str, search: float = 5.0) -> float:
    """2部品の最小すきま [mm](search より離れていれば search を返す)。"""
    shapes = {inst.name: d.placed(inst) for inst in d.instances(theta)}
    return shapes[name_a].min_gap(shapes[name_b], search)


if __name__ == "__main__":
    import math
    import sys

    theta = math.radians(float(sys.argv[1])) if len(sys.argv) > 1 else 0.0
    for a, b, v in sorted(find_collisions(theta), key=lambda h: -h[2]):
        print(f"{a:16s} {b:16s} {v:9.3f} mm^3")
