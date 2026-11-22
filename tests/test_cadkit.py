import json
import os
import subprocess
import sys

import ezdxf
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from cadkit import (CadError, Drawing, SpecError, audit_file, bracket_part, build_from_spec, column_grid,  # noqa: E402
                    render_dxf, room_plan)
from cadkit.core import fmt_ftin  # noqa: E402

DOOR = [{"wall": "south", "offset_ft": 2, "width_ft": 3}]
WIN = [{"wall": "east", "offset_ft": 6, "width_ft": 4}]


def test_fmt_ftin():
    assert fmt_ftin(144) == "12'-0\""
    assert fmt_ftin(150.5) == "12'-6 1/2\""


def test_room_plan_dxf_roundtrip(tmp_path):
    d = room_plan(12, 16, 6, DOOR, WIN, "BEDROOM")
    p = d.save(str(tmp_path / "r.dxf"))
    a = audit_file(p)
    assert a["dxf_version"] == "AC1024" and a["errors"] == 0 and a["ok"]
    assert a["dimensions"] >= 6
    assert a["entities_per_layer"]["A-DOOR"] >= 2 and "A-GLAZ" in a["entities_per_layer"]
    doc = ezdxf.readfile(p)
    texts = " ".join(e.text for e in doc.modelspace().query("MTEXT"))
    assert "BEDROOM 12'-0\" x 16'-0\"" in texts and "192 SQ FT" in texts and "Drawn by King AI" in texts
    assert any(e.dxf.dimstyle == "ARCH-FTIN" for e in doc.modelspace().query("DIMENSION"))
    assert len(list(doc.modelspace().query("ARC"))) == 1


def test_room_plan_validation():
    with pytest.raises(SpecError, match="does not fit"):
        room_plan(10, 12, 6, [{"wall": "south", "offset_ft": 9, "width_ft": 3}])
    with pytest.raises(SpecError, match="overlap"):
        room_plan(10, 12, 6, [{"wall": "south", "offset_ft": 1, "width_ft": 3}], [{"wall": "south", "offset_ft": 2, "width_ft": 3}])
    with pytest.raises(SpecError, match="wall"):
        room_plan(10, 12, 6, [{"wall": "up"}])
    with pytest.raises(SpecError):
        room_plan(-1, 12)


def test_column_grid_counts(tmp_path):
    d = column_grid(4, 3, 25, 25, 14)
    p = d.save(str(tmp_path / "g.dxf"))
    a = audit_file(p)
    assert a["errors"] == 0
    assert a["entities_per_layer"]["S-GRID"] == 5 + 4
    assert a["entities_per_layer"]["S-COLS"] == 20 * 2  # polyline + hatch per column
    assert a["entities_per_layer"]["S-GRID-IDEN"] == (5 + 4) * 2
    assert a["dimensions"] == 4 + 1 + 3 + 1
    with pytest.raises(SpecError):
        column_grid(0, 3, 25, 25)


def test_bracket(tmp_path):
    d = bracket_part()
    p = d.save(str(tmp_path / "b.dxf"))
    doc = ezdxf.readfile(p)
    radii = sorted(round(c.dxf.radius, 3) for c in doc.modelspace().query("CIRCLE"))
    assert radii == [4.5] * 4
    assert len(list(doc.modelspace().query("ARC"))) == 6
    assert audit_file(p)["errors"] == 0
    with pytest.raises(SpecError):
        bracket_part(hole_dia_mm=40)
    with pytest.raises(SpecError):
        bracket_part(holes=[[200, 200]])


def test_generic_spec_and_errors(tmp_path):
    spec = {"units": "mm", "entities": [{"type": "line", "start": [0, 0], "end": [10, 0]}, {"type": "circle", "center": [5, 5], "radius": 2}]}
    d = build_from_spec(spec)
    assert d.save(str(tmp_path / "g.dxf"))
    with pytest.raises(SpecError, match="missing 'radius'"):
        build_from_spec({"entities": [{"type": "circle", "center": [0, 0]}]})
    with pytest.raises(SpecError, match="unknown spec type"):
        build_from_spec({"type": "castle"})
    with pytest.raises(SpecError, match="unknown field"):
        build_from_spec({"type": "bracket", "bogus": 1})
    with pytest.raises(SpecError, match="must be"):
        build_from_spec({"entities": [{"type": "line", "start": "a", "end": [1, 1]}]})


def test_render_png_width(tmp_path):
    from PIL import Image
    p = bracket_part().save(str(tmp_path / "b.dxf"))
    out = render_dxf(p)
    assert Image.open(out["png"]).size[0] == 2000 and os.path.getsize(out["pdf"]) > 1000


def test_cli_build_and_audit(tmp_path):
    spec = tmp_path / "s.json"
    spec.write_text(json.dumps({"type": "room_plan", "width_ft": 10, "length_ft": 10, "doors": DOOR}))
    r = subprocess.run([sys.executable, os.path.join(ROOT, "cli.py"), "build", str(spec), "--out", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["audit"]["errors"] == 0 and (tmp_path / "s.png").exists()
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "cli.py"), "build", str(bad), "--out", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 2 and "error" in r.stderr


def test_missing_file():
    with pytest.raises(CadError):
        audit_file("/nonexistent.dxf")
