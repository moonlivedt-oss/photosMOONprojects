"""Цвета материалов в бинарном FBX: Quaternius экспортирует FBX из Blender с серым DiffuseColor (0.8),
а настоящие цвета лежат в .mtl версии OBJ (Kd). Вписываем Kd в FBX на место серого - те же 3 числа
double, длина файла не меняется. Имена материалов в FBX и MTL совпадают. Без Qt."""

import re
import struct


def read_mtl(text):
    """{имя материала: (r, g, b)} из .mtl."""
    out, name = {}, None
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "newmtl" and len(parts) > 1:
            name = " ".join(parts[1:])
        elif parts[0] == "Kd" and name and len(parts) >= 4:
            out[name] = tuple(float(x) for x in parts[1:4])
    return out


def patch(data: bytes, colors: dict):
    """-> (новые байты, сколько материалов перекрашено).
    В бинарном FBX имя объекта - строка «Имя\\x00\\x01Material»; дальше в его Properties70 идёт
    P "DiffuseColor" "Color" "" "A" D D D."""
    buf = bytearray(data)
    done = 0
    marks = [m for m in re.finditer(rb"S(....)([^\x00]{1,128})\x00\x01Material", data, re.S)]
    for i, m in enumerate(marks):
        name = m.group(2).decode("utf-8", "replace")
        if name not in colors:
            continue
        end = marks[i + 1].start() if i + 1 < len(marks) else len(data)
        j = data.find(b"DiffuseColorS", m.end(), end)
        if j < 0:
            continue
        k = data.find(b"AD", j, j + 64)
        if k < 0:
            continue
        pos = k + 1  # первый 'D'
        for c in colors[name]:
            if buf[pos : pos + 1] != b"D":
                break
            buf[pos + 1 : pos + 9] = struct.pack("<d", c)
            pos += 9
        else:
            done += 1
    return bytes(buf), done


def colorize(fbx_path, mtl_text):
    with open(fbx_path, "rb") as fh:
        data = fh.read()
    if not data.startswith(b"Kaydara FBX Binary"):
        return 0
    new, n = patch(data, read_mtl(mtl_text))
    if n:
        with open(fbx_path + ".tmp", "wb") as fh:
            fh.write(new)
        import os

        os.replace(fbx_path + ".tmp", fbx_path)
    return n


# Когда в .mtl цвета нет (старый набор Quaternius Furniture: всё 0.64), цвет берётся по имени материала.
BY_NAME = {
    "wood": "#9a6b43",
    "darkwood": "#5a3a24",
    "darkbrown": "#4a2f1e",
    "white": "#e8e6e0",
    "sheets": "#c9d3e6",
    "metal": "#8c9096",
    "top": "#b08a62",
    "sofa": "#6f8fb5",
    "cover2": "#b5473a",
    "cover3": "#3f6fa8",
    "cover4": "#4f8a4a",
    "pages": "#efe9da",
    "red": "#b23a32",
    "green": "#4f8f4a",
    "vase": "#c9895c",
}


def srgb_to_linear(h):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    h = h.lstrip("#")
    return tuple(ch(int(h[i : i + 2], 16)) for i in (0, 2, 4))


def names_in(data: bytes):
    return [
        m.group(2).decode("utf-8", "replace")
        for m in re.finditer(rb"S(....)([^\x00]{1,128})\x00\x01Material", data, re.S)
    ]


def colorize_by_name(fbx_path):
    """Цвета по именам материалов (Wood.003 -> wood). -> сколько перекрашено."""
    with open(fbx_path, "rb") as fh:
        data = fh.read()
    colors = {}
    for n in names_in(data):
        base = n.split(".")[0].lower()
        if base in BY_NAME:
            colors[n] = srgb_to_linear(BY_NAME[base])
    new, k = patch(data, colors)
    if not k:  # своих DiffuseColor у материалов нет - добавить
        new, k = add_colors(data, colors)
    if k:
        import os

        with open(fbx_path + ".tmp", "wb") as fh:
            fh.write(new)
        os.replace(fbx_path + ".tmp", fbx_path)
    return k


# ---------------------------------------------------------------- разбор и сборка бинарного FBX 7.x
# Нужен, когда у материала нет своего DiffuseColor (только шаблон): поле надо добавить, а с ним
# меняются длины - смещения узлов пересчитываются при сборке.
class Node:
    __slots__ = ("name", "props", "children", "null")

    def __init__(self, name, props=b"", children=None, null=False):
        self.name, self.props, self.children, self.null = name, props, children or [], null


def _read_node(d, pos, wide):
    head = 25 if wide else 13
    if wide:
        end, nprops, plen = struct.unpack_from("<QQQ", d, pos)
    else:
        end, nprops, plen = struct.unpack_from("<III", d, pos)
    if end == 0:
        return None, pos + head
    nlen = d[pos + head - 1]
    name = d[pos + head : pos + head + nlen]
    p = pos + head + nlen
    node = Node(name, (nprops, d[p : p + plen]))
    p += plen
    if p < end:  # вложенные узлы, в конце - пустая запись
        node.null = True
        while True:
            child, p = _read_node(d, p, wide)
            if child is None:
                break
            node.children.append(child)
    return node, end


def _write_node(out, node, wide, base):
    head = 25 if wide else 13
    start = base + len(out)
    nprops, raw = node.props
    body = bytearray()
    for c in node.children:  # base - где начинается тело узла; внутри к нему прибавится уже записанное
        _write_node(body, c, wide, start + head + len(node.name) + len(raw))
    if node.null or node.children:
        body += b"\x00" * head
    end = start + head + len(node.name) + len(raw) + len(body)
    fmt = "<QQQ" if wide else "<III"
    out += struct.pack(fmt, end, nprops, len(raw)) + bytes([len(node.name)]) + node.name + raw + body


def _strings(raw):
    """Строковые свойства узла по порядку (остальные типы пропускаются) - для имени материала."""
    out, p = [], 0
    sizes = {b"Y": 2, b"C": 1, b"I": 4, b"F": 4, b"D": 8, b"L": 8}
    while p < len(raw):
        t = raw[p : p + 1]
        p += 1
        if t in sizes:
            p += sizes[t]
        elif t in (b"S", b"R"):
            n = struct.unpack_from("<I", raw, p)[0]
            out.append(raw[p + 4 : p + 4 + n])
            p += 4 + n
        else:  # массивы: длина, кодировка, размер
            n = struct.unpack_from("<III", raw, p)[2]
            p += 12 + n
    return out


def _s(text):
    b = text.encode()
    return b"S" + struct.pack("<I", len(b)) + b


def _p_color(rgb):
    raw = _s("DiffuseColor") + _s("Color") + _s("") + _s("A") + b"".join(b"D" + struct.pack("<d", c) for c in rgb)
    return Node(b"P", (7, raw))


def add_colors(data: bytes, colors: dict):
    """Добавить DiffuseColor материалам, у которых его нет. -> (байты, сколько) или (data, 0)."""
    version = struct.unpack_from("<I", data, 23)[0]
    wide = version >= 7500
    pos, top = 27, []
    while True:
        node, pos = _read_node(data, pos, wide)
        if node is None:
            break
        top.append(node)
    footer = data[pos:]
    done = 0
    for obj in (n for n in top if n.name == b"Objects"):
        for m in (c for c in obj.children if c.name == b"Material"):
            names = _strings(m.props[1])
            name = names[0].split(b"\x00\x01")[0].decode("utf-8", "replace") if names else ""
            if name not in colors:
                continue
            p70 = next((c for c in m.children if c.name == b"Properties70"), None)
            if p70 is None:
                p70 = Node(b"Properties70", (0, b""), null=True)
                m.children.append(p70)
                m.null = True
            if any(_strings(c.props[1])[:1] == [b"DiffuseColor"] for c in p70.children):
                continue
            p70.children.append(_p_color(colors[name]))
            p70.null = True
            done += 1
    if not done:
        return data, 0
    out = bytearray(data[:27])
    for n in top:
        _write_node(out, n, wide, 0)
    out += b"\x00" * (25 if wide else 13)
    # подвал: id (16 байт), 4 нуля, выравнивание до 16, версия, 120 нулей, сигнатура (16 байт)
    fid, magic = footer[:16], footer[-16:]
    out += fid + b"\x00" * 4
    pad = (16 - len(out) % 16) % 16 or 16
    out += b"\x00" * pad + struct.pack("<I", version) + b"\x00" * 120 + magic
    return bytes(out), done
