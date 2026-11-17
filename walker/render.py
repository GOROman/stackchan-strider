"""確認用の簡易レンダラー(点サンプリング + Zバッファ、正射影)。設計の目視確認用。"""
from __future__ import annotations

import math
import sys

import numpy as np
import trimesh
from PIL import Image

import design as d


def _hex_to_rgb(text: str) -> np.ndarray:
    return np.array([int(text[i : i + 2], 16) for i in (1, 3, 5)], dtype=np.float64) / 255


def render(theta: float, azimuth: float, elevation: float, path: str, size: int = 1100, scale: float = 6.0,
           with_stackchan: bool = True, only=None, center=(0.0, 0.0, 10.0), clip=None):
    """azimuth: Z まわりの視点方位[deg](0 = +X 側から見る)、elevation: 仰角[deg]。clip=(軸, 値) でその先を切り取る。"""
    az, el = math.radians(azimuth), math.radians(elevation)
    view = np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])  # 視点方向(物体→カメラ)
    right = np.cross([0, 0, 1], view)
    right /= np.linalg.norm(right)
    up = np.cross(view, right)
    light = (view + 0.6 * up + 0.4 * right)
    light /= np.linalg.norm(light)
    depth = np.full((size, size), -1e9)
    image = np.ones((size, size, 3))
    defs = d.part_defs()
    rng = np.random.default_rng(0)
    for inst in d.instances(theta, 0.0, with_stackchan):
        if only is not None and not any(inst.name.startswith(prefix) for prefix in only):
            continue
        mesh = d.to_trimesh(d.placed(inst))
        count = int(max(2000, mesh.area * scale * scale * 2.5))
        points, face_index = trimesh.sample.sample_surface(mesh, count, seed=rng)
        normals = mesh.face_normals[face_index]
        if clip is not None:
            keep = points[:, clip[0]] * clip[2] <= clip[1] * clip[2]
            points, normals = points[keep], normals[keep]
        rel = points - np.asarray(center)
        px = np.round(size / 2 + rel @ right * scale).astype(int)
        py = np.round(size / 2 - rel @ up * scale).astype(int)
        pz = rel @ view
        ok = (px >= 0) & (px < size) & (py >= 0) & (py < size)
        px, py, pz, normals = px[ok], py[ok], pz[ok], normals[ok]
        shade = 0.35 + 0.65 * np.clip(np.abs(normals @ light), 0, 1)
        color = _hex_to_rgb(defs[inst.part].color)[None, :] * shade[:, None]
        order = np.argsort(pz)
        px, py, pz, color = px[order], py[order], pz[order], color[order]
        nearer = pz > depth[py, px]
        depth[py[nearer], px[nearer]] = pz[nearer]
        image[py[nearer], px[nearer]] = color[nearer]
    Image.fromarray((image * 255).astype(np.uint8)).save(path)


if __name__ == "__main__":
    out = sys.argv[1]
    theta = math.radians(float(sys.argv[2])) if len(sys.argv) > 2 else 0.0
    render(theta, -60, 20, f"{out}/iso.png")
    render(theta, 0, 0, f"{out}/side.png")
    render(theta, 90, 0, f"{out}/front.png")
    render(theta, 0, 0, f"{out}/side_nolegs.png", only=("side_plate", "deck", "yoke", "gear", "socket", "pinion", "shaft", "sleeve", "sc_"), clip=(0, 0.0, -1))
    render(theta, 90, 0, f"{out}/front_section.png", clip=(1, 0.0, 1))
