"""脚の組立手順(どの部品を、どの順に、どう入れるか)。組立ガイドと組立検証で同じものを使う。

脚は左右それぞれ 2 本(前と後ろ)が 1 本のクランクピンを共有し、ピンの上で 4 層に重なる。
内側から「低い脚のリンク1、高い脚のリンク1、低い脚のリンク2、高い脚のリンク2」の順なので、2 本を並行して組む。
すべての継ぎ目は丸い突起と丸穴で、重ねたあと C クリップを横からはめて留める。向き合わせは要らない。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import design as d

# 左右それぞれの (低い層を使う脚, 高い層を使う脚)
SIDES = {"R": ("RR", "RF"), "L": ("LF", "LR")}
LEG_SIGNS = {name: (sx, sy) for name, sx, sy in d.LEGS}
# 組み立てるときのクランク角(基準脚で)。ピンが、低い脚の固定ピボットの側へ水平に向く
ASSEMBLY_ANGLE = math.pi


def assembly_crank(side: str) -> float:
    """side の脚を組むときのクランク角。"""
    sx, sy = LEG_SIGNS[SIDES[side][0]]
    pin = ASSEMBLY_ANGLE if sy > 0 else math.pi - ASSEMBLY_ANGLE
    return pin - (math.pi if sx < 0 else 0.0)


@dataclass(frozen=True)
class Op:
    """組立の 1 操作。parts は一緒に動かす部品(機体の中での名前)。"""

    key: str  # 操作の種類: c / j / unit / k / clip
    leg: str
    parts: tuple[str, ...]
    crank: float  # このときのクランク角
    kind: str  # "axial" = まっすぐ重ねる / "radial" = クリップを横からはめる
    line: int  # 組立ガイドの箇条書きの何行目か
    owner: str = ""  # radial のとき、クリップをはめる突起の持ち主(はめる瞬間は弾性で広がるので、重なりを見ない)


def clip_owner(leg: str, joint: str) -> str:
    owner = d.STUD_JOINTS[joint][0]
    if owner == "plate":
        return "side_plate_R" if LEG_SIGNS[leg][0] > 0 else "side_plate_L"
    return f"{leg}_{owner}"


def side_ops(side: str) -> list[Op]:
    low, high = SIDES[side]
    crank = assembly_crank(side)

    def stack(key: str, leg: str, parts: tuple[str, ...], line: int) -> Op:
        return Op(key, leg, parts, crank, "axial", line)

    def clip(leg: str, joint: str, line: int) -> Op:
        return Op("clip", leg, (f"{leg}_clip_{joint}",), crank, "radial", line, clip_owner(leg, joint))

    def unit(leg: str) -> tuple[str, ...]:
        # 机の上で先に組んでおく: リンク4 に上下の三角板を通し、E と G をクリップで留めたもの
        return (f"{leg}_f", f"{leg}_tri_upper", f"{leg}_tri_lower", f"{leg}_clip_E", f"{leg}_clip_G")

    return [
        stack("c", low, (f"{low}_c",), 0),
        stack("j", low, (f"{low}_j",), 0),
        stack("unit", low, unit(low), 1),
        clip(low, "B", 2),
        clip(low, "D", 2),
        stack("c", high, (f"{high}_c",), 3),
        stack("j", high, (f"{high}_j",), 3),
        stack("k", low, (f"{low}_k",), 4),
        clip(low, "F", 4),
        stack("unit", high, unit(high), 5),
        clip(high, "B", 5),
        clip(high, "D", 5),
        stack("k", high, (f"{high}_k",), 6),
        clip(high, "F", 6),
        Op("clip", low, (f"clip_{side}",), crank, "radial", 7, f"crank_{side}"),
    ]
