# ASCII wireframe of one mesh object: front and side, true proportions.
#   bash mcp.sh code python/wireframe.py
import bpy

OBJECT = "Chair"
COLS, ROWS = 78, 34

o = bpy.data.objects.get(OBJECT)
if o is None or o.type != "MESH":
    print("no mesh object named", OBJECT)
else:
    me, mw = o.data, o.matrix_world
    verts = [mw @ v.co for v in me.vertices]
    edges = [(e.vertices[0], e.vertices[1]) for e in me.edges]
    print("object", o.name, "dims", [round(v, 3) for v in o.dimensions],
          "faces", len(me.polygons), "verts", len(me.vertices),
          "world z", round(min(v.z for v in verts), 3), round(max(v.z for v in verts), 3))

    def draw(ax, bz, label):
        a0 = min(ax(v) for v in verts); a1 = max(ax(v) for v in verts)
        b0 = min(bz(v) for v in verts); b1 = max(bz(v) for v in verts)
        s = min((COLS - 1) / ((a1 - a0) or 1.0), (ROWS - 1) / ((b1 - b0) or 1.0))
        ca = (COLS - 1 - (a1 - a0) * s) / 2
        cb = (ROWS - 1 - (b1 - b0) * s) / 2
        g = [[" "] * COLS for _ in range(ROWS)]
        for i, j in edges:
            p, q = verts[i], verts[j]
            n = max(2, int(max(abs(ax(p) - ax(q)), abs(bz(p) - bz(q))) * s * 2))
            for k in range(n + 1):
                t = k / n
                c = int(ca + (ax(p) * (1 - t) + ax(q) * t - a0) * s)
                r = int(cb + (bz(p) * (1 - t) + bz(q) * t - b0) * s)
                if 0 <= c < COLS and 0 <= r < ROWS:
                    g[ROWS - 1 - r][c] = "#"
        print(label)
        for row in g:
            print("".join(row))

    draw(lambda v: v.x, lambda v: v.z, "FRONT  x->right, z->up")
    draw(lambda v: v.y, lambda v: v.z, "SIDE   y->right, z->up")
