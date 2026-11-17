"""ヤンセン機構(Theo Jansen linkage)の平面運動学。

座標は脚の動作平面内: u = 前方(+), w = 上方(+)。クランク軸 O を原点とする。
リンク長は Jansen の "holy numbers" を基準に SCALE を掛けたもの。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# Theo Jansen の比率(単位なし)
HOLY = dict(a=38.0, b=41.5, c=39.3, d=40.1, e=55.8, f=39.4, g=36.7, h=65.7, i=49.0, j=50.0, k=61.9, l=7.8, m=15.0)


@dataclass(frozen=True)
class LegGeometry:
    a: float
    b: float
    c: float
    d: float
    e: float
    f: float
    g: float
    h: float
    i: float
    j: float
    k: float
    l: float
    m: float

    @staticmethod
    def scaled(scale: float) -> "LegGeometry":
        return LegGeometry(**{k: v * scale for k, v in HOLY.items()})


def _circle_intersection(p0: np.ndarray, r0: float, p1: np.ndarray, r1: float, side: int) -> np.ndarray:
    """p0→p1 の向きに対して左側(side=+1)/右側(side=-1)の交点を返す。交点が無ければ例外。"""
    delta = p1 - p0
    dist = float(np.hypot(*delta))
    if dist > r0 + r1 or dist < abs(r0 - r1) or dist == 0.0:
        raise ValueError(f"リンクが閉じない: dist={dist:.3f}, r0={r0:.3f}, r1={r1:.3f}")
    along = (r0 * r0 - r1 * r1 + dist * dist) / (2 * dist)
    height = math.sqrt(max(r0 * r0 - along * along, 0.0))
    unit = delta / dist
    normal = np.array([-unit[1], unit[0]])
    return p0 + along * unit + side * height * normal


def solve_leg(geom: LegGeometry, theta: float) -> dict[str, np.ndarray]:
    """クランク角 theta[rad] での全ジョイント位置を返す。

    固定ピボット B はクランク軸 O の後方(-u)。足先 H は下。
    戻り値のキー: O, B, C(クランクピン), D(上), E(後), F(下), G(膝), H(足先)
    """
    origin = np.zeros(2)
    pivot = np.array([-geom.a, -geom.l])
    crank = geom.m * np.array([math.cos(theta), math.sin(theta)])
    upper = _circle_intersection(crank, geom.j, pivot, geom.b, side=-1)
    rear = _circle_intersection(upper, geom.e, pivot, geom.d, side=-1)
    lower = _circle_intersection(crank, geom.k, pivot, geom.c, side=+1)
    knee = _circle_intersection(rear, geom.f, lower, geom.g, side=-1)
    foot = _circle_intersection(knee, geom.h, lower, geom.i, side=-1)
    return dict(O=origin, B=pivot, C=crank, D=upper, E=rear, F=lower, G=knee, H=foot)


def foot_path(geom: LegGeometry, steps: int = 360) -> np.ndarray:
    """クランク1回転分の足先軌跡 (steps, 2)。"""
    return np.array([solve_leg(geom, 2 * math.pi * n / steps)["H"] for n in range(steps)])


if __name__ == "__main__":
    geometry = LegGeometry.scaled(1.0)
    path = foot_path(geometry)
    lowest = path[:, 1].min()
    on_ground = path[:, 1] < lowest + 1.0
    print("足先 u 範囲", path[:, 0].min(), path[:, 0].max())
    print("足先 w 範囲", lowest, path[:, 1].max())
    print("接地率(最下点+1以内)", on_ground.mean())
    print("接地中の u ストローク", path[on_ground, 0].min(), path[on_ground, 0].max())
