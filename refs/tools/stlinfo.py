import struct, sys, os

def load(path):
    with open(path, 'rb') as f:
        data = f.read()
    n = struct.unpack_from('<I', data, 80)[0]
    if 84 + n * 50 != len(data):
        raise ValueError('not binary STL: %s' % path)
    tris = []
    off = 84
    for i in range(n):
        v = struct.unpack_from('<12f', data, off)
        tris.append((v[3:6], v[6:9], v[9:12]))
        off += 50
    return tris

for p in sys.argv[1:]:
    t = load(p)
    xs = [v[0] for tr in t for v in tr]
    ys = [v[1] for tr in t for v in tr]
    zs = [v[2] for tr in t for v in tr]
    print('%-34s tris=%6d  X[%8.3f,%8.3f] Y[%8.3f,%8.3f] Z[%8.3f,%8.3f]  size=%.2f x %.2f x %.2f' % (
        os.path.basename(p), len(t), min(xs), max(xs), min(ys), max(ys), min(zs), max(zs),
        max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)))
