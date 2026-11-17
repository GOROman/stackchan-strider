"""傘歯車(ターンテーブル歯車 × ピニオン)の噛み合い判定。

判定内容:
  1. 諸元の整合(モジュール・歯数・ピッチ円錐角の和・歯幅・切り下げ・かみあい率)
  2. 実際の部品形状を使い、1回転を通して歯どうしの干渉体積が 0 であること
  3. 各位相でピニオンだけを左右に回し、歯が当たるまでの遊び(バックラッシュ)を測る。
     遊びが 0 より大きく(詰まらない)、半ピッチよりずっと小さい(歯が掛かっている)こと
  4. 組立ガタ(ピニオンの軸方向ずれ、ターンテーブルの浮き)を与えても 2・3 が成り立つこと
使い方: python walker/verify_gears.py [--json out/verify_gears.json]
"""
from __future__ import annotations

import argparse
import json
import math
import sys

import numpy as np

import design as d

CONTACT_TOL = 1e-3  # これを超える重なり体積 [mm^3] を「歯が当たった」とみなす
BACKLASH_MIN = 0.03  # ピッチ円上の遊びの下限 [mm](これ未満は詰まり気味)
BACKLASH_MAX = 0.90  # 上限 [mm](FDM の歯車として許せるガタ。半ピッチ 3.14 mm の 3 割未満)
# シャフト一式の軸方向ガタ(クランク内面と側板外面のすきま 0.2 mm)+ ピニオンとスリーブのすきま 0.2 mm
AXIAL_PLAY = 0.4


def _pair(theta: float, pinion_extra: float = 0.0, pinion_shift: float = 0.0, table_lift: float = 0.0):
    table = d.apply(d.part_shape("gear_table"), d.translation(0, 0, table_lift) @ d.rot_z(-theta))
    pinion = d.apply(d.part_shape("pinion"), d.translation(pinion_shift, 0, 0) @ d.rot_x(theta + pinion_extra))
    return table, pinion


def overlap(theta: float, **kwargs) -> float:
    table, pinion = _pair(theta, **kwargs)
    return (table ^ pinion).volume()


def free_play(theta: float, direction: int, limit: float, **kwargs) -> float:
    """ピニオンを direction 方向へ回して歯が当たるまでの角度 [rad]。limit まで当たらなければ limit。"""
    if overlap(theta, pinion_extra=direction * limit, **kwargs) <= CONTACT_TOL:
        return limit
    low, high = 0.0, limit
    for _ in range(14):
        mid = (low + high) / 2
        if overlap(theta, pinion_extra=direction * mid, **kwargs) > CONTACT_TOL:
            high = mid
        else:
            low = mid
    return (low + high) / 2


def spec_checks() -> list[dict]:
    spec = d.GEAR
    delta = spec.pitch_angle
    alpha = math.radians(spec.pressure_angle_deg)
    virtual_teeth = spec.teeth / math.cos(delta)
    # 背円錐の仮想平歯車どうしの正面かみあい率
    r = spec.module * virtual_teeth / 2
    ra = r + spec.addendum_coef * spec.module
    rb = r * math.cos(alpha)
    contact_ratio = (2 * math.sqrt(ra * ra - rb * rb) - 2 * r * math.sin(alpha)) / (math.pi * spec.module * math.cos(alpha))
    min_teeth_no_undercut = 2 * spec.addendum_coef / math.sin(alpha) ** 2
    rows = [
        ("歯数(ターンテーブル:ピニオン)", f"{spec.teeth}:{spec.mate_teeth}", spec.teeth == spec.mate_teeth),
        ("モジュール(外端)", f"{spec.module:.2f} mm(両歯車とも同じ諸元から生成)", True),
        ("ピッチ円錐半角の和 = 軸角", f"{math.degrees(delta):.2f}° + {math.degrees(delta):.2f}° = 90°", abs(2 * delta - math.pi / 2) < 1e-9),
        ("歯の向き", "ピッチ円錐半角 45°(下向き45°の歯で回転軸を90°変換)", abs(math.degrees(delta) - 45) < 1e-9),
        ("円錐距離 R / 歯幅 b", f"R={spec.cone_distance:.2f} mm, b={spec.face_width:.1f} mm (b ≤ R/3 = {spec.cone_distance / 3:.2f})", spec.face_width <= spec.cone_distance / 3 + 1e-9),
        ("切り下げ(仮想歯数)", f"zv={virtual_teeth:.1f} ≥ {min_teeth_no_undercut:.1f}", virtual_teeth >= min_teeth_no_undercut),
        ("かみあい率(仮想平歯車)", f"{contact_ratio:.2f} ≥ 1.2", contact_ratio >= 1.2),
    ]
    return [dict(item=a, value=b, ok=bool(c)) for a, b, c in rows]


def sweep(label: str, steps_fine: int, steps_rev: int, **kwargs) -> dict:
    spec = d.GEAR
    pitch_angle = 2 * math.pi / spec.teeth
    limit = pitch_angle / 2
    # 1ピッチ分を細かく、残りの1回転を粗く見る
    fine = [pitch_angle * n / steps_fine for n in range(steps_fine)]
    coarse = [2 * math.pi * n / steps_rev for n in range(steps_rev)]
    max_overlap = max(overlap(theta, **kwargs) for theta in fine + coarse)
    plays = []
    for theta in fine + coarse[:: max(1, steps_rev // 20)]:
        plus = free_play(theta, +1, limit, **kwargs)
        minus = free_play(theta, -1, limit, **kwargs)
        plays.append((plus + minus) * spec.pitch_radius)
    plays = np.array(plays)
    ok = max_overlap <= CONTACT_TOL and plays.min() >= BACKLASH_MIN and plays.max() <= BACKLASH_MAX
    return dict(
        case=label,
        max_overlap_mm3=float(max_overlap),
        backlash_min_mm=float(plays.min()),
        backlash_max_mm=float(plays.max()),
        half_pitch_mm=float(limit * spec.pitch_radius),
        ok=bool(ok),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json")
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    fine, rev = (12, 40) if args.quick else (36, 180)
    specs = spec_checks()
    cases = [
        sweep("設計位置", fine, rev),
        sweep(f"ピニオンが軸方向に {AXIAL_PLAY} mm 奥へずれた場合(組立ガタの上限)", fine // 2, rev // 4, pinion_shift=-AXIAL_PLAY),
        sweep(f"ピニオンが軸方向に {AXIAL_PLAY} mm 手前へずれた場合", fine // 2, rev // 4, pinion_shift=AXIAL_PLAY),
        sweep("ターンテーブルが 0.6 mm 浮いた場合(カラーの上限)", fine // 2, rev // 4, table_lift=0.6),
    ]
    print("== 傘歯車 諸元 ==")
    for row in specs:
        print(f"  [{'OK' if row['ok'] else 'NG'}] {row['item']}: {row['value']}")
    print("== 噛み合い(干渉体積とバックラッシュ) ==")
    for case in cases:
        print(
            f"  [{'OK' if case['ok'] else 'NG'}] {case['case']}: 最大干渉 {case['max_overlap_mm3']:.4f} mm^3, "
            f"バックラッシュ {case['backlash_min_mm']:.3f}〜{case['backlash_max_mm']:.3f} mm "
            f"(半ピッチ {case['half_pitch_mm']:.2f} mm)"
        )
    ok = all(row["ok"] for row in specs) and all(case["ok"] for case in cases)
    print("判定:", "合格" if ok else "不合格")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(dict(ok=ok, specs=specs, cases=cases), handle, ensure_ascii=False, indent=1)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
