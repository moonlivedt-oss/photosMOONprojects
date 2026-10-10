"""Сведения о модели из FBX без Blender и без Unreal: треугольники, вершины, размеры в см, есть ли скелет и
какие анимации. Нужны фильтру «Полигоны» и карточке ассета: у Poly Haven это приходит из каталога, а у Kenney,
Quaternius, KayKit и своих архивов - только из самого файла. Без Qt.

FBX бывает двоичный (почти все) и текстовый (старые наборы Kenney) - оба разбираются в одно дерево узлов N:
имя, значения, вложенные узлы. Двоичный - через fbx_colors._parse, массивы бывают сжаты zlib."""

import math
import re
import struct
import zlib

import numpy as np

from library import fbx_colors as F

_SIZES = {b"Y": 2, b"C": 1, b"I": 4, b"F": 4, b"D": 8, b"L": 8, b"B": 1}
_FMT = {b"Y": "<h", b"I": "<i", b"F": "<f", b"D": "<d", b"L": "<q"}
_ARR = {b"d": "<f8", b"f": "<f4", b"i": "<i4", b"l": "<i8", b"b": "<u1"}


class N:
    __slots__ = ("name", "vals", "kids")

    def __init__(self, name, vals, kids):
        self.name, self.vals, self.kids = name, vals, kids


def props(raw):
    """Свойства двоичного узла: числа, строки (bytes), массивы numpy."""
    out, p = [], 0
    while p < len(raw):
        t = raw[p : p + 1]
        p += 1
        if t in _SIZES:
            n = _SIZES[t]
            out.append(raw[p] if t in (b"C", b"B") else struct.unpack(_FMT[t], raw[p : p + n])[0])
            p += n
        elif t in (b"S", b"R"):
            n = struct.unpack_from("<I", raw, p)[0]
            out.append(raw[p + 4 : p + 4 + n])
            p += 4 + n
        elif t in _ARR:
            ln, enc, cl = struct.unpack_from("<III", raw, p)
            data = raw[p + 12 : p + 12 + cl]
            if enc == 1:
                data = zlib.decompress(data)
            out.append(np.frombuffer(data, _ARR[t], ln))
            p += 12 + cl
        else:  # незнакомый тип - дальше не разобрать
            break
    return out


def _from_binary(node):
    return N(node.name, props(node.props[1]), [_from_binary(c) for c in node.children])


_VAL = re.compile(r'"([^"]*)"|([^,\s][^,]*)')


def _ascii_vals(text):
    out = []
    for m in _VAL.finditer(text):
        if m.group(1) is not None:
            out.append(m.group(1).encode("utf-8"))
            continue
        tok = m.group(2).strip()
        if not tok or tok.startswith("*"):
            continue
        try:
            out.append(int(tok))
        except ValueError:
            try:
                out.append(float(tok))
            except ValueError:
                out.append(tok.encode("utf-8"))
    return out


def _from_ascii(text):
    """Текстовый FBX -> верхние узлы N. Массивы «Vertices: *N { a: ... }» - узел с ребёнком «a»."""
    root = N(b"", [], [])
    stack, last = [root], None
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith(";"):
            continue
        if s == "}":
            if len(stack) > 1:
                stack.pop()
            last = None
            continue
        m = re.match(r"^([A-Za-z_][\w|]*):\s*(.*)$", s)
        if m is None:  # продолжение длинного массива «a: 1,2,3,\n4,5,6»
            if last is not None:
                last.vals.extend(_ascii_vals(s))
            continue
        name, rest = m.group(1).encode(), m.group(2)
        opens = rest.endswith("{")
        node = N(name, _ascii_vals(rest[:-1] if opens else rest), [])
        stack[-1].kids.append(node)
        if opens:
            stack.append(node)
            last = None
        else:
            last = node
    return root.kids


def _child(node, name):
    return next((c for c in node.kids if c.name == name), None)


def _array(node, dtype):
    """Массив узла: в двоичном - значение, в текстовом - ребёнок «a»."""
    if node.vals and isinstance(node.vals[0], np.ndarray):
        return node.vals[0].astype(dtype, copy=False)
    a = _child(node, b"a")
    return np.asarray(a.vals if a else [], dtype)


def _p70(node):
    """{имя свойства: [значения]} из Properties70."""
    out = {}
    p = _child(node, b"Properties70")
    for c in p.kids if p else ():
        if c.vals and isinstance(c.vals[0], bytes):
            out[c.vals[0].decode("utf-8", "replace")] = c.vals[4:]
    return out


def _rot(deg):
    """Матрица поворота FBX (порядок XYZ: сначала X, потом Y, потом Z)."""
    x, y, z = (math.radians(a) for a in deg)
    rx = np.array([[1, 0, 0], [0, math.cos(x), -math.sin(x)], [0, math.sin(x), math.cos(x)]])
    ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    rz = np.array([[math.cos(z), -math.sin(z), 0], [math.sin(z), math.cos(z), 0], [0, 0, 1]])
    return rz @ ry @ rx


def _vec(p, key, default):
    v = [x for x in p.get(key, default) if isinstance(x, (int, float))][:3]
    return v if len(v) == 3 else default


def _local(model):
    """Матрица 4x4 модели: перенос * пред-поворот * поворот * масштаб (сдвиги точек вращения пропущены -
    для габаритов их хватает)."""
    p = _p70(model)
    m = np.eye(4)
    m[:3, :3] = _rot(_vec(p, "PreRotation", [0, 0, 0])) @ _rot(_vec(p, "Lcl Rotation", [0, 0, 0]))
    m[:3, :3] = m[:3, :3] @ np.diag(_vec(p, "Lcl Scaling", [1, 1, 1]))
    m[:3, 3] = _vec(p, "Lcl Translation", [0, 0, 0])
    return m


def _name(node):
    raw = next((x for x in node.vals if isinstance(x, bytes)), b"")
    raw = raw.split(b"\x00\x01")[0]  # двоичный: «Имя\x00\x01Класс»
    return raw.split(b"::", 1)[-1].decode("utf-8", "replace")  # текстовый: «Класс::Имя»


def read(path):
    """-> {triangles, vertices, dims_cm [ширина, глубина, высота], rigged, animations [имена]} или None."""
    with open(path, "rb") as fh:
        data = fh.read()
    if data.startswith(b"Kaydara FBX Binary"):
        top = [_from_binary(n) for n in F._parse(data)[2]]
    elif data.lstrip().startswith(b";") or b"FBXHeaderExtension" in data[:4096]:
        top = _from_ascii(data.decode("utf-8", "replace"))
    else:
        return None
    nodes = {n.name: n for n in top}
    gs = _p70(nodes[b"GlobalSettings"]) if b"GlobalSettings" in nodes else {}
    unit = float((gs.get("UnitScaleFactor") or [1.0])[0])  # сколько см в единице файла
    up = int((gs.get("UpAxis") or [1])[0])  # 1 - ось Y вверх, 2 - Z
    objs = nodes.get(b"Objects")
    if objs is None:
        return None
    geoms, models = [], {}
    rigged, anims = False, []
    for c in objs.kids:
        oid = c.vals[0] if c.vals and isinstance(c.vals[0], int) else None
        if c.name == b"Geometry":
            geoms.append((oid, c))
        elif c.name == b"Model":
            models[oid] = c
        elif c.name == b"Deformer" and len(c.vals) > 2 and c.vals[2] == b"Skin":
            rigged = True
        elif c.name == b"AnimationStack":
            anims.append(_name(c))
    parent = {}  # объект -> родитель (связи «OO»)
    conn = nodes.get(b"Connections")
    for c in conn.kids if conn else ():
        if len(c.vals) >= 3 and c.vals[0] == b"OO":
            parent.setdefault(c.vals[1], c.vals[2])

    def world(oid):
        m, depth = np.eye(4), 0
        while oid in models and depth < 64:
            m = _local(models[oid]) @ m
            oid, depth = parent.get(oid), depth + 1
        return m

    tris = verts = 0
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for gid, g in geoms:
        vn, pn = _child(g, b"Vertices"), _child(g, b"PolygonVertexIndex")
        if vn is None or pn is None:
            continue
        pts = _array(vn, np.float64)
        pts = pts[: len(pts) // 3 * 3].reshape(-1, 3)
        idx = _array(pn, np.int64)
        ends = np.flatnonzero(idx < 0)  # конец полигона - отрицательный индекс
        sizes = np.diff(np.concatenate(([-1], ends)))
        tris += int(np.maximum(sizes - 2, 0).sum())
        verts += len(pts)
        if len(pts):
            m = world(parent.get(gid))
            w = pts @ m[:3, :3].T + m[:3, 3]
            lo, hi = np.minimum(lo, w.min(0)), np.maximum(hi, w.max(0))
    out = {"triangles": tris, "vertices": verts, "rigged": rigged, "animations": anims}
    if geoms and np.isfinite(lo).all():
        ext = (hi - lo) * unit
        # Z вверх: ширина X, глубина Y, высота Z; Y вверх (обычно): ширина X, глубина Z, высота Y
        dims = [ext[0], ext[1], ext[2]] if up == 2 else [ext[0], ext[2], ext[1]]
        out["dims_cm"] = [round(float(x), 1) for x in dims]
    return out
