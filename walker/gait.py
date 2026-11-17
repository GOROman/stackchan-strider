"""接地姿勢の解析: 各クランク角で、機体が床の上でどう静止するか(傾き・高さ・前進量)を求める。

足は4本とも「足幅の両端2点」で床に触れうる。重心の真下を含む、足裏点群の下側凸包の面が支持面になる。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from scipy.spatial import ConvexHull

import design as d

PLA_DENSITY = 1.24e-3  # g/mm^3
FILL_FACTOR = 0.55  # 外周壁 + インフィル 15% 程度での実質充填率(概算)
# スタックチャン本体の重心(ヨー軸基準)。公開値が無いので仮定: 頭部の中心付近、やや前寄り
SC_CG_ASSUMED = (0.0, 3.0, 38.0)
GRAVITY = 9.81


@dataclass(frozen=True)
class MassModel:
    total_g: float
    walker_g: float
    cg: np.ndarray  # 機体座標での重心


@lru_cache(maxsize=None)
def mass_model() -> MassModel:
    defs = d.part_defs()
    total, moment, walker = 0.0, np.zeros(3), 0.0
    for inst in d.instances(0.0, with_stackchan=False):
        mesh = d.to_trimesh(d.placed(inst))
        mass = abs(mesh.volume) * PLA_DENSITY * FILL_FACTOR
        total += mass
        walker += mass
        moment += mass * mesh.center_mass
        assert defs[inst.part].printable
    sc_cg = np.array([SC_CG_ASSUMED[0], SC_CG_ASSUMED[1], d.TABLE_Z1 + SC_CG_ASSUMED[2]])
    total += d.SC_MASS_G
    moment += d.SC_MASS_G * sc_cg
    return MassModel(total_g=total, walker_g=walker, cg=moment / total)


@dataclass(frozen=True)
class RestPose:
    up: np.ndarray  # 機体座標での鉛直上向き
    height: float  # 床から重心までの高さ
    support: tuple[int, ...]  # 支持面を作る足(LEGS の添字)
    margin: float  # 重心の真下から支持多角形の縁までの距離 [mm]
    feet_clear: np.ndarray  # 各足の床からの高さ [mm]

    @property
    def pitch_deg(self) -> float:
        """正 = 前のめり。"""
        return math.degrees(math.asin(self.up[1]))

    @property
    def roll_deg(self) -> float:
        """正 = 右へ傾く。"""
        return math.degrees(math.asin(self.up[0]))

    @property
    def tilt_deg(self) -> float:
        return math.degrees(math.acos(min(1.0, self.up[2])))


def rest_pose(theta: float, cg: np.ndarray | None = None, prev_up: np.ndarray | None = None) -> RestPose | None:
    """静止できる姿勢を返す。候補が複数あるときは直前の姿勢(prev_up)に最も近いもの、無ければ傾きが最小のもの。

    2本足だけで釣り合う候補(支持面の余裕がほぼ 0)は実際には保てないので、3本以上で支える候補を優先する。
    """
    cg = mass_model().cg if cg is None else cg
    contacts = d.foot_contacts(theta)  # (4, 2, 3)
    points = contacts.reshape(-1, 3)
    hull = ConvexHull(points, qhull_options="QJ")
    candidates = []
    for simplex, equation in zip(hull.simplices, hull.equations):
        normal = equation[:3]
        if normal[2] > -1e-6:
            continue
        up = -normal
        a, b, c = points[simplex]
        foot = cg - np.dot(cg - a, up) * up
        basis = np.array([b - a, c - a]).T
        uv = np.linalg.lstsq(basis, foot - a, rcond=None)[0]
        if min(uv[0], uv[1], 1 - uv.sum()) < -1e-6:
            continue
        heights = (points - a) @ up
        on_ground = points[heights < 0.05]
        margin = _margin(on_ground, foot, up)
        clear = heights.reshape(4, 2).min(axis=1)
        support = tuple(int(i) for i in np.nonzero(clear < 0.05)[0])
        candidates.append(RestPose(up=up, height=float(np.dot(cg - a, up)), support=support, margin=margin, feet_clear=clear))
    if not candidates:
        return None
    stable = [pose for pose in candidates if len(pose.support) >= 3] or candidates
    reference = np.array([0.0, 0.0, 1.0]) if prev_up is None else prev_up
    return max(stable, key=lambda pose: float(pose.up @ reference))


def _margin(on_ground: np.ndarray, foot: np.ndarray, up: np.ndarray) -> float:
    """接地点の凸多角形の内側で、重心の真下から縁までの最短距離。"""
    axis_u = np.cross(up, [1.0, 0.0, 0.0])
    axis_u /= np.linalg.norm(axis_u)
    axis_v = np.cross(up, axis_u)
    flat = np.array([[p @ axis_u, p @ axis_v] for p in on_ground - foot])
    if len(flat) < 3:
        return 0.0
    hull = ConvexHull(flat, qhull_options="QJ")
    # equations: n·x + offset <= 0 が内側。原点(= 重心の真下)から各辺までの距離は -offset
    return float(max(0.0, (-hull.equations[:, 2]).min()))


def body_transform(pose: RestPose, forward: float) -> np.ndarray:
    """機体座標 → 床座標(床 z=0、前進量 forward を Y に加える)の 4x4 行列。ヨーは変えない。"""
    up = pose.up
    z_axis = np.array([0.0, 0.0, 1.0])
    axis = np.cross(up, z_axis)
    sin, cos = np.linalg.norm(axis), float(up @ z_axis)
    rotation = np.eye(3)
    if sin > 1e-12:
        k = axis / sin
        skew = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
        rotation = np.eye(3) + sin * skew + (1 - cos) * skew @ skew
    cg = mass_model().cg
    out = np.eye(4)
    out[:3, :3] = rotation
    out[:3, 3] = np.array([0.0, forward, pose.height]) - rotation @ cg + np.array([cg[0], cg[1], 0.0])
    return out


def walk_cycle(frames: int = 180):
    """前進方向(クランク角が減る向き)に1回転ぶんの (theta, RestPose, 前進量) を返す。"""
    thetas = [-2 * math.pi * n / frames for n in range(frames + 1)]
    poses = []
    # 1周目で姿勢の履歴を作り、2周目の結果を使う(開始時の姿勢選択に依存させない)
    prev_up = None
    for _lap in range(2):
        poses = []
        for theta in thetas:
            pose = rest_pose(theta, prev_up=prev_up)
            prev_up = pose.up if pose is not None else prev_up
            poses.append(pose)
    forward = [0.0]
    for index in range(1, len(thetas)):
        prev, cur = poses[index - 1], poses[index]
        step = 0.0
        if prev is not None and cur is not None:
            shared = set(prev.support) & set(cur.support)
            if shared:
                before = d.foot_contacts(thetas[index - 1])[list(shared), 0, 1]
                after = d.foot_contacts(thetas[index])[list(shared), 0, 1]
                step = float(np.mean(before - after))  # 接地足が機体に対して後ろへ動いたぶん機体が前へ進む
        forward.append(forward[-1] + step)
    return thetas, poses, forward
