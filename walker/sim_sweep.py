"""MuJoCo で摩擦・速度・前後進の組み合わせを一通り走らせ、転倒の有無と歩行性能をまとめる。

使い方: python walker/sim_sweep.py [--json out/mujoco/sweep.json]
寸法を変えて試すときは環境変数 STRIDER_LEG_SCALE / STRIDER_CRANK_RATIO を指定する。
"""
from __future__ import annotations

import argparse
import json
import sys

import numpy as np

import design as d
import sim_mujoco as sm

FRICTIONS = (0.3, 0.5, 0.8, 1.0)
COMMANDS = (0.3, 0.6, 1.0, -0.3, -0.6, -1.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json")
    parser.add_argument("--seconds", type=float, default=14.0)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    rows = []
    for friction in FRICTIONS:
        for command in COMMANDS:
            result = sm.run(friction, command, args.seconds)
            result.pop("log")
            rows.append(result)
            if not args.quiet:
                print(
                    f"摩擦 {friction:.1f} 指令 {command:+.1f}: {'転倒' if result['fallen'] else '歩行'}  クランク {result['crank_rpm']:5.1f} rpm  "
                    f"速度 {result['speed_mm_s']:+6.1f} mm/s  {result['advance_per_rev_mm']:+6.1f} mm/回転  "
                    f"前後 {result['pitch_deg'][0]:+5.1f}〜{result['pitch_deg'][1]:+5.1f}°  左右 {result['roll_deg'][0]:+5.1f}〜{result['roll_deg'][1]:+5.1f}°  "
                    f"サーボ平均 {result['servo_torque_mNm_mean']:.1f} mN·m"
                )
    falls = sum(row["fallen"] for row in rows)
    walking = [row for row in rows if not row["fallen"]]
    summary = dict(
        leg_scale=d.LEG_SCALE,
        crank_ratio=d.CRANK_RATIO,
        cases=len(rows),
        falls=falls,
        worst_pitch_deg=float(max(max(abs(v) for v in row["pitch_deg"]) for row in walking)) if walking else None,
        mean_abs_speed_mm_s=float(np.mean([abs(row["speed_mm_s"]) for row in walking])) if walking else 0.0,
        servo_torque_mNm_max_mean=float(max(row["servo_torque_mNm_mean"] for row in walking)) if walking else None,
        rows=rows,
    )
    print(f"脚スケール {d.LEG_SCALE} クランク比 {d.CRANK_RATIO}: {len(rows)} 条件中 転倒 {falls}  最大の前後傾き {summary['worst_pitch_deg']:.1f}°  平均速度 {summary['mean_abs_speed_mm_s']:.1f} mm/s  サーボ平均トルク最大 {summary['servo_torque_mNm_max_mean']:.1f} mN·m")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=1)
    return 0 if falls == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
