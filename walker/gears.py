"""すぐば傘歯車(straight bevel gear)のメッシュ生成。

歯形は Tredgold 近似(背円錐を展開した仮想平歯車のインボリュート)を背円錐面に巻き付け、
円錐頂点に向けて相似縮小して歯すじを作る。すぐば傘歯車の歯面は頂点を通る直線の集まりなので、
外端と内端の歯形を直線で結べば歯面になる。

座標: 歯車軸 = Z。ピッチ円錐の頂点 = 原点。歯車本体は z < 0 側(頂点を見上げる向き)。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import trimesh


@dataclass(frozen=True)
class BevelSpec:
    module: float  # 外端でのモジュール [mm]
    teeth: int
    mate_teeth: int
    face_width: float  # 歯幅(ピッチ円錐母線方向) [mm]
    pressure_angle_deg: float = 20.0
    backlash: float = 0.0  # 外端ピッチ円上での歯厚減少量(片側歯車ぶん) [mm]
    addendum_coef: float = 1.0
    dedendum_coef: float = 1.25
    shaft_angle_deg: float = 90.0

    @property
    def pitch_angle(self) -> float:
        """ピッチ円錐半角 [rad]。"""
        sigma = math.radians(self.shaft_angle_deg)
        return math.atan2(math.sin(sigma), self.mate_teeth / self.teeth + math.cos(sigma))

    @property
    def pitch_radius(self) -> float:
        return self.module * self.teeth / 2

    @property
    def cone_distance(self) -> float:
        return self.pitch_radius / math.sin(self.pitch_angle)

    @property
    def inner_ratio(self) -> float:
        return (self.cone_distance - self.face_width) / self.cone_distance

    @property
    def tip_radius(self) -> float:
        """外端の歯先円半径(軸からの距離)。"""
        return self.pitch_radius + self.addendum_coef * self.module * math.cos(self.pitch_angle)

    @property
    def tip_z(self) -> float:
        """外端の歯先の z。"""
        return -self.cone_distance * math.cos(self.pitch_angle) + self.addendum_coef * self.module * math.sin(
            self.pitch_angle
        )

    @property
    def root_z_outer(self) -> float:
        """外端の歯底の z。"""
        return -self.cone_distance * math.cos(self.pitch_angle) - self.dedendum_coef * self.module * math.sin(
            self.pitch_angle
        )

    @property
    def root_radius_outer(self) -> float:
        return self.pitch_radius - self.dedendum_coef * self.module * math.cos(self.pitch_angle)

    @property
    def back_apex_z(self) -> float:
        """背円錐の頂点(軸上)の z。"""
        return -self.cone_distance * math.cos(self.pitch_angle) - self.pitch_radius * math.tan(self.pitch_angle)


def _involute(angle: float) -> float:
    return math.tan(angle) - angle


def _virtual_tooth_profile(spec: BevelSpec, flank_points: int) -> list[tuple[float, float]]:
    """仮想平歯車の歯1枚の輪郭を (半径, 角度) で返す。左歯底→左歯先→右歯先→右歯底の順。"""
    delta = spec.pitch_angle
    alpha = math.radians(spec.pressure_angle_deg)
    r_virtual = spec.pitch_radius / math.cos(delta)
    r_base = r_virtual * math.cos(alpha)
    r_tip = r_virtual + spec.addendum_coef * spec.module
    r_root = r_virtual - spec.dedendum_coef * spec.module
    thickness = math.pi * spec.module / 2 - spec.backlash
    half_at_pitch = thickness / (2 * r_virtual)

    def half_angle(radius: float) -> float:
        if radius <= r_base:
            return half_at_pitch + _involute(alpha)
        return half_at_pitch + _involute(alpha) - _involute(math.acos(r_base / radius))

    if half_angle(r_tip) <= 0:
        raise ValueError("歯先が尖る: モジュール・歯数・バックラッシュを見直すこと")
    radii = [r_root] + list(np.linspace(max(r_base, r_root), r_tip, flank_points))
    if r_root >= r_base:
        radii = list(np.linspace(r_root, r_tip, flank_points))
    left = [(radius, -half_angle(radius)) for radius in radii]
    right = [(radius, half_angle(radius)) for radius in reversed(radii)]
    return left + right


def bevel_ring_outline(spec: BevelSpec, flank_points: int = 8) -> np.ndarray:
    """外端(背円錐上)の歯形リング全周の3D点列 (N,3)。"""
    delta = spec.pitch_angle
    r_virtual = spec.pitch_radius / math.cos(delta)
    z_pitch = -spec.cone_distance * math.cos(delta)
    profile = _virtual_tooth_profile(spec, flank_points)
    points = []
    for tooth in range(spec.teeth):
        center = 2 * math.pi * tooth / spec.teeth
        for radius_v, angle_v in profile:
            height = radius_v - r_virtual
            phi = center + angle_v / math.cos(delta)
            radius = spec.pitch_radius + height * math.cos(delta)
            points.append((radius * math.cos(phi), radius * math.sin(phi), z_pitch + height * math.sin(delta)))
    return np.array(points)


def bevel_teeth_mesh(spec: BevelSpec, flank_points: int = 8) -> trimesh.Trimesh:
    """歯付き円錐台(軸まで中実)の水密メッシュ。外端・内端は背円錐で閉じる。"""
    outer = bevel_ring_outline(spec, flank_points)
    inner = outer * spec.inner_ratio
    count = len(outer)
    outer_center = np.array([[0.0, 0.0, spec.back_apex_z]])
    inner_center = outer_center * spec.inner_ratio
    vertices = np.vstack([outer, inner, outer_center, inner_center])
    idx_outer_center = 2 * count
    idx_inner_center = 2 * count + 1
    faces = []
    for n in range(count):
        nxt = (n + 1) % count
        faces.append((n, nxt, count + nxt))
        faces.append((n, count + nxt, count + n))
        faces.append((nxt, n, idx_outer_center))
        faces.append((count + n, count + nxt, idx_inner_center))
    mesh = trimesh.Trimesh(vertices=vertices, faces=np.array(faces), process=True)
    if mesh.volume < 0:
        mesh.invert()
    if not mesh.is_watertight:
        raise RuntimeError("傘歯車メッシュが閉じていない")
    return mesh


def mesh_phase_offset(spec: BevelSpec) -> float:
    """相手歯車(同じ頂点・直交軸)と噛み合わせるとき、自分を軸回りに回しておく角度 [rad]。

    bevel_ring_outline は歯の中心を角度0に置く。相手の歯の中心も角度0にあるので、
    片方を半ピッチ回すと歯と歯溝が向き合う。
    """
    return math.pi / spec.teeth
