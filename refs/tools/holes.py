"""Through-hole / region report from a depth npy. usage: holes.py file.npy res"""
import sys
import numpy as np
from scipy import ndimage as ndi

img = np.load(sys.argv[1])
res = float(sys.argv[2])
H, W = img.shape
print('shape mm: %.2f x %.2f' % (W * res, H * res))
lab, n = ndi.label(np.isnan(img))
for k in range(1, n + 1):
    m = lab == k
    ys, xs = np.nonzero(m)
    touches = xs.min() == 0 or ys.min() == 0 or xs.max() == W - 1 or ys.max() == H - 1
    area = m.sum() * res * res
    if area < 0.3:
        continue
    print('void%2d %s area=%7.2f mm2  cx=%6.2f cy=%6.2f  bbox x[%.2f,%.2f] y[%.2f,%.2f]  eqD=%.2f' % (
        k, 'EDGE' if touches else 'hole', area, xs.mean() * res, ys.mean() * res,
        xs.min() * res, (xs.max() + 1) * res, ys.min() * res, (ys.max() + 1) * res, 2 * np.sqrt(area / np.pi)))
# height histogram
v = img[np.isfinite(img)]
vals, cnt = np.unique(np.round(v, 1), return_counts=True)
o = np.argsort(-cnt)[:12]
print('main height levels (z, area mm2):', sorted([(float(vals[i]), round(cnt[i] * res * res, 1)) for i in o]))
# outline widths at several rows
for frac in (0.02, 0.1, 0.25, 0.5, 0.75, 0.9, 0.98):
    r = int(H * frac)
    xs = np.nonzero(np.isfinite(img[r]))[0]
    print('row y=%.2f: x from %.2f to %.2f' % (r * res, xs.min() * res, (xs.max() + 1) * res))
for frac in (0.02, 0.1, 0.25, 0.5, 0.75, 0.9, 0.98):
    c = int(W * frac)
    ys = np.nonzero(np.isfinite(img[:, c]))[0]
    print('col x=%.2f: y from %.2f to %.2f' % (c * res, ys.min() * res, (ys.max() + 1) * res))
