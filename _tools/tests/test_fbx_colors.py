"""Цвета материалов в бинарном FBX (Quaternius): чтение .mtl, замена на месте и добавление поля."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from library import fbx_colors as F  # noqa: E402

MTL = "newmtl Red\nKd 0.5 0.1 0.05\nnewmtl Wood\nKd 0.640000 0.640000 0.640000\n"


def raw(*props):
    out = b""
    for p in props:
        if isinstance(p, int):
            out += b"L" + struct.pack("<q", p)
        else:
            b = p.encode() if isinstance(p, str) else p
            out += b"S" + struct.pack("<I", len(b)) + b
    return (len(props), out)


def fbx(material_names, with_color=False):
    """Маленький бинарный FBX 7.4: Objects с материалами (с DiffuseColor или без)."""
    mats = []
    for i, n in enumerate(material_names):
        kids = []
        if with_color:
            kids = [F.Node(b"Properties70", (0, b""), [F._p_color((0.8, 0.8, 0.8))], True)]
        mats.append(F.Node(b"Material", raw(100 + i, n.encode() + b"\x00\x01Material", ""), kids, bool(kids)))
    top = [F.Node(b"Objects", (0, b""), mats, True)]
    out = bytearray(b"Kaydara FBX Binary  \x00\x1a\x00" + struct.pack("<I", 7400))
    for n in top:
        F._write_node(out, n, False, 0)
    out += b"\x00" * 13
    out += b"\xfa\xbc" * 8 + b"\x00" * 4
    out += b"\x00" * ((16 - len(out) % 16) % 16 or 16) + struct.pack("<I", 7400) + b"\x00" * 120 + b"\xf8\x5a" * 8
    return bytes(out)


def diffuse(data):
    pos, top = 27, []
    while True:
        n, pos = F._read_node(data, pos, False)
        if n is None:
            break
        top.append(n)
    out = {}
    for m in top[0].children:
        name = F._strings(m.props[1])[0].split(b"\x00\x01")[0].decode()
        for p70 in m.children:
            for p in p70.children:
                r = p.props[1]
                k = r.find(b"AD")
                out[name] = tuple(round(struct.unpack_from("<d", r, k + 2 + 9 * i)[0], 3) for i in range(3))
    return out


class TestFbxColors(unittest.TestCase):
    def test_read_mtl(self):
        self.assertEqual(F.read_mtl(MTL)["Red"], (0.5, 0.1, 0.05))

    def test_patch_in_place(self):
        data = fbx(["Red", "Wood"], with_color=True)
        new, n = F.patch(data, F.read_mtl(MTL))
        self.assertEqual(n, 2)
        self.assertEqual(len(new), len(data))  # те же байты, только числа другие
        self.assertEqual(diffuse(new)["Red"], (0.5, 0.1, 0.05))

    def test_add_when_missing(self):
        data = fbx(["Red", "Other"])
        self.assertEqual(F.patch(data, {"Red": (1, 0, 0)})[1], 0)  # поля нет - заменить нечего
        new, n = F.add_colors(data, {"Red": (1.0, 0.0, 0.0)})
        self.assertEqual(n, 1)
        self.assertEqual(diffuse(new), {"Red": (1.0, 0.0, 0.0)})
        self.assertTrue(new.endswith(b"\xf8\x5a" * 8))

    def test_roundtrip_exact(self):
        data = fbx(["A", "B"], with_color=True)
        pos, top = 27, []
        while True:
            n, pos = F._read_node(data, pos, False)
            if n is None:
                break
            top.append(n)
        out = bytearray(data[:27])
        for n in top:
            F._write_node(out, n, False, 0)
        self.assertEqual(bytes(out), data[:len(out)])


if __name__ == "__main__":
    unittest.main()
