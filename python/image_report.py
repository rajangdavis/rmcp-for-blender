# Coarse text view of an image: dimensions, palette, a luminance grid and a
# silhouette. PATH is an image already in the file (by name) or a file to load.
import bpy, numpy as np

PATH = "Gigan T-Shirt 2018.jpg"
COLS = 116                          # characters across; rows follow the aspect
CROP = (0.0, 0.04, 1.0, 0.34)       # fractions of w,h; None for the whole image
CELL = 2.0                          # a terminal cell is about twice as tall as wide

src = bpy.data.images.get(PATH)
loaded = src is None
if loaded:
    src = bpy.data.images.load(PATH)
img = src
ow, oh = img.size
buf = np.empty(ow * oh * 4, dtype=np.float32)
img.pixels.foreach_get(buf)
a = buf.reshape(oh, ow, 4)[::-1, :, :3]

lum = 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
mean = [int(round(a[..., i].mean() * 255)) for i in range(3)]
q = (np.clip(a, 0, 1) * 15).astype(np.uint8).reshape(-1, 3)
keys = q[:, 0].astype(np.int32) * 256 + q[:, 1].astype(np.int32) * 16 + q[:, 2]
uniq, counts = np.unique(keys, return_counts=True)
total = float(keys.size)
palette = ["#%02x%02x%02x %2.0f%%"
           % ((int(uniq[i]) // 256) * 17, ((int(uniq[i]) // 16) % 16) * 17,
              (int(uniq[i]) % 16) * 17, 100.0 * counts[i] / total)
           for i in np.argsort(-counts)[:4]]

if CROP:
    cx0, cy0, cx1, cy1 = int(CROP[0] * ow), int(CROP[1] * oh), int(CROP[2] * ow), int(CROP[3] * oh)
    a = a[cy0:cy1, cx0:cx1]
    lum = lum[cy0:cy1, cx0:cx1]
h, w = a.shape[0], a.shape[1]
ROWS = max(6, int(round(COLS * (h / float(w)) / CELL)))

ys = np.linspace(0, h, ROWS + 1).astype(int)
xs = np.linspace(0, w, COLS + 1).astype(int)
grid = np.zeros((ROWS, COLS), dtype=np.float32)
for r in range(ROWS):
    for c in range(COLS):
        cell = lum[ys[r]:ys[r + 1], xs[c]:xs[c + 1]]
        grid[r, c] = float(cell.mean()) if cell.size else 0.0
lo, hi = np.percentile(grid, 5), np.percentile(grid, 95)
span = float(hi - lo) or 1.0
ramp = " .:-=+*#%@"

lines = ["image %s  %dx%d  aspect %.3f  mean #%02x%02x%02x"
         % (PATH, ow, oh, (ow / float(oh) if oh else 0), mean[0], mean[1], mean[2]),
         "palette " + ", ".join(palette),
         "crop %s   grid %dx%d (true proportions)   luminance, dense = bright:" % (str(CROP), COLS, ROWS)]
for r in range(ROWS):
    line = ""
    for c in range(COLS):
        v = (grid[r, c] - lo) / span
        line += ramp[max(0, min(len(ramp) - 1, int(v * (len(ramp) - 1))))]
    lines.append(line)

border = np.concatenate([a[0, :, :], a[-1, :, :], a[:, 0, :], a[:, -1, :]])
bg = border.mean(axis=0)
dist = np.sqrt(((a - bg) ** 2).sum(axis=2))
mask = dist > float(dist.mean() + dist.std())
sub = np.zeros((ROWS, COLS), dtype=np.float32)
for r in range(ROWS):
    for c in range(COLS):
        cell = mask[ys[r]:ys[r + 1], xs[c]:xs[c + 1]]
        sub[r, c] = float(cell.mean()) if cell.size else 0.0
yy, xx = np.where(mask)
if yy.size:
    lines.append("subject x %d%%..%d%%  y %d%%..%d%%  covers %d%%"
                 % (100 * xx.min() // w, 100 * xx.max() // w,
                    100 * yy.min() // h, 100 * yy.max() // h, int(100 * mask.mean())))
lines.append("silhouette (subject = #):")
for r in range(ROWS):
    lines.append("".join("#" if sub[r, c] > 0.5 else " " for c in range(COLS)))

if loaded:
    bpy.data.images.remove(img)
print("\n".join(lines))
