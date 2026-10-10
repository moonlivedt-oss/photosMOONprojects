"""Сведения о модели из FBX (library/fbx_meta.py): треугольники, размеры с учётом масштаба и единиц, скелет и
анимации - на маленьком текстовом FBX (двоичный сверен с каталогом Poly Haven вручную)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from library import fbx_meta as M  # noqa: E402

CUBE = """; FBX 7.3.0 project file
FBXHeaderExtension:  {
}
GlobalSettings:  {
	Properties70:  {
		P: "UpAxis", "int", "Integer", "",1
		P: "UnitScaleFactor", "double", "Number", "",100
	}
}
Objects:  {
	Geometry: 10, "Geometry::Box", "Mesh" {
		Vertices: *24 {
			a: 0,0,0,1,0,0,1,1,0,0,1,0,
			0,0,2,1,0,2,1,1,2,0,1,2
		}
		PolygonVertexIndex: *24 {
			a: 0,1,2,-4,4,5,6,-8,0,1,5,-5,2,3,7,-7,1,2,6,-6,0,3,7,-5
		}
	}
	Model: 20, "Model::Box", "Mesh" {
		Properties70:  {
			P: "Lcl Scaling", "Lcl Scaling", "", "A",3,1,1
		}
	}
	Deformer: 30, "Deformer::Skin", "Skin" {
	}
	AnimationStack: 40, "AnimStack::Walk", "" {
	}
}
Connections:  {
	C: "OO",10,20
	C: "OO",20,0
}
"""


class FbxMeta(unittest.TestCase):
    def test_ascii_box(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "box.fbx")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(CUBE)
        r = M.read(p)
        self.assertEqual(r["triangles"], 12)  # 6 четырёхугольников
        self.assertEqual(r["vertices"], 8)
        # x: 1 * масштаб 3 * 100 см; Y вверх: высота - y (1 * 100), глубина - z (2 * 100)
        self.assertEqual(r["dims_cm"], [300.0, 200.0, 100.0])
        self.assertTrue(r["rigged"])
        self.assertEqual(r["animations"], ["Walk"])

    def test_not_fbx(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "x.fbx")
        with open(p, "wb") as fh:
            fh.write(b"PNG nonsense")
        self.assertIsNone(M.read(p))


if __name__ == "__main__":
    unittest.main()
