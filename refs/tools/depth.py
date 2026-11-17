"""Depth-map renders of a binary STL along an axis. usage: depth.py in.stl outprefix axis(x|y|z) [res_mm]"""
import sys, struct
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def load(path):
    with open(path, 'rb') as f:
        data = f.read()
    n = struct.unpack_from('<I', data, 80)[0]
    assert 84 + n * 50 == len(data)
    dt = np.dtype([('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')])
    return np.frombuffer(data, dtype=dt, count=n, offset=84)['v'].astype(np.float64)


def depth(tris, ax, res, top):
    axes = [0, 1, 2]
    axes.remove(ax)
    u, v = axes
    mn = tris.reshape(-1, 3).min(0)
    mx = tris.reshape(-1, 3).max(0)
    W = int(np.ceil((mx[u] - mn[u]) / res)) + 1
    H = int(np.ceil((mx[v] - mn[v]) / res)) + 1
    img = np.full((H, W), -np.inf if top else np.inf)
    for t in tris:
        pu = (t[:, u] - mn[u]) / res
        pv = (t[:, v] - mn[v]) / res
        pz = t[:, ax]
        i0, i1 = int(np.floor(pu.min())), int(np.ceil(pu.max()))
        j0, j1 = int(np.floor(pv.min())), int(np.ceil(pv.max()))
        i1 = min(i1, W - 1); j1 = min(j1, H - 1)
        if i1 < i0 or j1 < j0:
            continue
        gi, gj = np.meshgrid(np.arange(i0, i1 + 1), np.arange(j0, j1 + 1))
        d = (pv[1] - pv[2]) * (pu[0] - pu[2]) + (pu[2] - pu[1]) * (pv[0] - pv[2])
        if abs(d) < 1e-12:
            continue
        a = ((pv[1] - pv[2]) * (gi - pu[2]) + (pu[2] - pu[1]) * (gj - pv[2])) / d
        b = ((pv[2] - pv[0]) * (gi - pu[2]) + (pu[0] - pu[2]) * (gj - pv[2])) / d
        c = 1 - a - b
        m = (a >= -1e-9) & (b >= -1e-9) & (c >= -1e-9)
        z = a * pz[0] + b * pz[1] + c * pz[2]
        sub = img[j0:j1 + 1, i0:i1 + 1]
        if top:
            sub[m] = np.maximum(sub[m], z[m])
        else:
            sub[m] = np.minimum(sub[m], z[m])
    img[~np.isfinite(img)] = np.nan
    return img, mn, mx, u, v


def main():
    path, prefix, axn = sys.argv[1], sys.argv[2], sys.argv[3]
    res = float(sys.argv[4]) if len(sys.argv) > 4 else 0.05
    ax = 'xyz'.index(axn)
    tris = load(path)
    for top in (True, False):
        img, mn, mx, u, v = depth(tris, ax, res, top)
        np.save('%s_%s_%s.npy' % (prefix, axn, 'max' if top else 'min'), img)
        fig, a = plt.subplots(figsize=(11, 11))
        ext = [0, mx[u] - mn[u], 0, mx[v] - mn[v]]
        im = a.imshow(img, origin='lower', extent=ext, cmap='viridis')
        a.set_xlabel('%s - %s_min (mm)' % ('xyz'[u], 'xyz'[u]))
        a.set_ylabel('%s - %s_min (mm)' % ('xyz'[v], 'xyz'[v]))
        a.set_xticks(np.arange(0, ext[1] + 0.01, 2)); a.set_yticks(np.arange(0, ext[3] + 0.01, 2))
        a.tick_params(labelsize=7)
        a.grid(True, lw=0.3, color='w', alpha=0.5)
        a.set_title('%s  seen from %s%s  (color = %s height, mm; origin = bbox min %s)' % (
            path.replace('\\', '/').split('/')[-1], '+' if top else '-', axn, axn, np.round(mn, 3)), fontsize=9)
        fig.colorbar(im, shrink=0.7)
        fig.savefig('%s_%s_%s.png' % (prefix, axn, 'max' if top else 'min'), dpi=110, bbox_inches='tight')
        plt.close(fig)


main()
