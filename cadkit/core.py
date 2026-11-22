"""Drawing model: layers, primitives, dimensions, hatch, title block, save and audit."""
from __future__ import annotations

import math
import os
import subprocess
from collections import Counter
from datetime import datetime

import ezdxf
from ezdxf import bbox
from ezdxf.enums import TextEntityAlignment, MTextEntityAlignment
from ezdxf.math import Vec2


class CadError(Exception):
    """Any drawing error with a human-readable message."""


class SpecError(CadError):
    """A request/spec that failed validation."""


DXF_VERSION = "R2010"  # AC1024: opens in AutoCAD 2010+, LibreCAD, FreeCAD, QCAD

# name -> (ACI color, true rgb for a white sheet, linetype, lineweight 1/100 mm)
STD_LAYERS = {
    "A-WALL": (7, (0, 0, 0), "Continuous", 50),
    "A-DOOR": (7, (0, 0, 0), "Continuous", 25),
    "A-GLAZ": (5, (0, 60, 190), "Continuous", 35),
    "A-ANNO-TEXT": (7, (0, 0, 0), "Continuous", 18),
    "A-ANNO-DIMS": (3, (0, 135, 60), "Continuous", 13),
    "S-GRID": (1, (200, 30, 30), "CENTER", 18),
    "S-GRID-IDEN": (1, (200, 30, 30), "Continuous", 25),
    "S-COLS": (7, (0, 0, 0), "Continuous", 50),
    "S-BEAM": (5, (0, 90, 200), "DASHED", 25),
    "M-OUTLINE": (7, (0, 0, 0), "Continuous", 50),
    "M-CENTER": (1, (200, 30, 30), "CENTER", 13),
    "M-HIDDEN": (8, (110, 110, 110), "DASHED", 25),
    "M-DIMS": (3, (0, 135, 60), "Continuous", 13),
    "M-TEXT": (7, (0, 0, 0), "Continuous", 18),
    "TITLE-BLOCK": (7, (0, 0, 0), "Continuous", 35),
}

ACI_BY_NAME = {"black": 7, "white": 7, "red": 1, "yellow": 2, "green": 3, "cyan": 4, "blue": 5, "magenta": 6, "grey": 8, "gray": 8}


def today_central() -> str:
    """Date read from `TZ=America/Chicago date` (falls back to zoneinfo)."""
    try:
        env = dict(os.environ, TZ="America/Chicago")
        return subprocess.run(["date", "+%b %d, %Y"], env=env, capture_output=True, text=True, timeout=5, check=True).stdout.strip().upper()
    except Exception:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Chicago")).strftime("%b %d, %Y").upper()


def fmt_ftin(inches: float, denom: int = 16) -> str:
    """Architectural length: 150 -> 12'-6", 6.5 -> 0'-6 1/2", 144 -> 12'-0"."""
    total = round(abs(inches) * denom)
    whole, frac = divmod(total, denom)
    ft, inch = divmod(whole, 12)
    f = ""
    if frac:
        from math import gcd
        g = gcd(frac, denom)
        f = f" {frac // g}/{denom // g}"
    return f"{'-' if inches < 0 else ''}{ft}'-{inch}{f}\""


def _pt(p, name="point"):
    try:
        x, y = float(p[0]), float(p[1])
    except Exception:
        raise SpecError(f"{name} must be [x, y] numbers, got {p!r}")
    if not (math.isfinite(x) and math.isfinite(y)):
        raise SpecError(f"{name} must be finite, got {p!r}")
    return (x, y)


def _num(v, name, positive=False):
    try:
        f = float(v)
    except Exception:
        raise SpecError(f"{name} must be a number, got {v!r}")
    if not math.isfinite(f) or (positive and f <= 0):
        raise SpecError(f"{name} must be {'a positive ' if positive else 'a finite '}number, got {v!r}")
    return f


class Drawing:
    """A DXF drawing. units='in' (architectural, feet-inches dimensions) or 'mm' (mechanical).

    All coordinates are in drawing units (inches or mm). `text_h` is the standard annotation height in
    drawing units (what a 1/8 in character would be at plot scale); dimension sizes derive from it.
    """

    def __init__(self, units: str = "mm", title: str = "UNTITLED", scale: str = "NTS", text_h: float | None = None,
                 sheet: str = "1 OF 1", drawn_by: str = "Drawn by King AI"):
        if units not in ("mm", "in"):
            raise SpecError(f"units must be 'mm' or 'in', got {units!r}")
        self.units = units
        self.title, self.scale, self.sheet, self.drawn_by = str(title), str(scale), sheet, drawn_by
        self.doc = ezdxf.new(DXF_VERSION, setup=True, units=1 if units == "in" else 4)
        self.msp = self.doc.modelspace()
        self.text_h = float(text_h) if text_h else (4.0 if units == "in" else 3.5)
        self.date = today_central()
        self._ttlb: list = []
        self.doc.header["$LTSCALE"] = self.text_h * 1.5
        self.doc.header["$MEASUREMENT"] = 0 if units == "in" else 1
        self.doc.header["$LUNITS"] = 4 if units == "in" else 2
        self.doc.header["$AUNITS"] = 0
        self.extra_extents: list[tuple[float, float]] = []
        for name, (aci, rgb, lt, lw) in STD_LAYERS.items():
            self.add_layer(name, aci, lt, lw, rgb)
        self._make_dimstyle()

    # ---------------------------------------------------------------- layers
    def add_layer(self, name: str, color=7, linetype: str = "Continuous", lineweight: int = 25, rgb=None):
        if not isinstance(name, str) or not name.strip():
            raise SpecError("layer name must be a non-empty string")
        if isinstance(color, str):
            if color.lower() not in ACI_BY_NAME:
                raise SpecError(f"unknown color {color!r}; use 1-255 or one of {sorted(ACI_BY_NAME)}")
            color = ACI_BY_NAME[color.lower()]
        color = int(color)
        if not 1 <= color <= 255:
            raise SpecError(f"layer color must be 1-255, got {color}")
        lt_names = {l.dxf.name.lower(): l.dxf.name for l in self.doc.linetypes}
        if linetype.lower() not in lt_names:
            raise SpecError(f"unknown linetype {linetype!r}; available: {sorted(lt_names.values())}")
        if name in self.doc.layers:
            lay = self.doc.layers.get(name)
        else:
            lay = self.doc.layers.add(name)
        lay.color = color
        lay.dxf.linetype = lt_names[linetype.lower()]
        lay.dxf.lineweight = int(lineweight)
        if rgb:
            lay.rgb = tuple(rgb)
        return lay

    def list_layers(self):
        used = Counter(e.dxf.layer for e in self.msp)
        out = []
        for l in self.doc.layers:
            out.append({"name": l.dxf.name, "color": l.color, "linetype": l.dxf.linetype, "entities": used.get(l.dxf.name, 0)})
        return out

    def _layer(self, layer):
        if layer is None:
            return "0"
        if layer not in self.doc.layers:
            self.add_layer(layer)
        return layer

    # ---------------------------------------------------------------- dimstyle
    def _make_dimstyle(self):
        t = self.text_h
        arch = self.units == "in"
        name = "ARCH-FTIN" if arch else "MECH-MM"
        ds = self.doc.dimstyles.new(name)
        ds.dxf.dimtxt = t * (1.15 if arch else 1.0)
        ds.dxf.dimasz = t * (0.8 if arch else 1.0)
        ds.dxf.dimexe = t * 0.6
        ds.dxf.dimexo = t * 0.4
        ds.dxf.dimgap = t * 0.3
        ds.dxf.dimtad = 1
        ds.dxf.dimtih = 0
        ds.dxf.dimtoh = 0
        ds.dxf.dimclrd = 3
        ds.dxf.dimclre = 3
        ds.dxf.dimclrt = 3
        if arch:
            ds.dxf.dimlunit = 4   # architectural: feet and fractional inches
            ds.dxf.dimfrac = 1    # diagonal stacking off: simple 1/2
            ds.dxf.dimdec = 0
            ds.dxf.dimrnd = 1 / 16
            ds.dxf.dimzin = 0
            ds.dxf.dimdsep = 46
            ds.set_arrows(blk=ezdxf.ARROWS.architectural_tick)
            ds.dxf.dimdle = t * 0.4
            ds.dxf.dimtsz = t * 0.8
        else:
            ds.dxf.dimlunit = 2   # decimal
            ds.dxf.dimdec = 1
            ds.dxf.dimzin = 8
            ds.dxf.dimdsep = 46
            ds.set_arrows(blk=ezdxf.ARROWS.closed_filled)
        self.dimstyle = name

    @property
    def dim_layer(self):
        return "A-ANNO-DIMS" if self.units == "in" else "M-DIMS"

    # ---------------------------------------------------------------- primitives
    def _grow(self, *pts):
        for p in pts:
            self.extra_extents.append((p[0], p[1]))

    def line(self, start, end, layer="0", **kw):
        s, e = _pt(start, "start"), _pt(end, "end")
        self._grow(s, e)
        return self.msp.add_line(s, e, dxfattribs={"layer": self._layer(layer), **kw})

    def rectangle(self, corner1, corner2, layer="0", **kw):
        (x1, y1), (x2, y2) = _pt(corner1, "corner1"), _pt(corner2, "corner2")
        if x1 == x2 or y1 == y2:
            raise SpecError("rectangle must have non-zero width and height")
        return self.polyline([(x1, y1), (x2, y1), (x2, y2), (x1, y2)], closed=True, layer=layer, **kw)

    def polyline(self, points, closed=False, layer="0", **kw):
        if not isinstance(points, (list, tuple)) or len(points) < 2:
            raise SpecError("polyline needs at least 2 points")
        pts = [_pt(p, f"points[{i}]") for i, p in enumerate(points)]
        self._grow(*pts)
        return self.msp.add_lwpolyline(pts, close=bool(closed), dxfattribs={"layer": self._layer(layer), **kw})

    def circle(self, center, radius, layer="0", **kw):
        c, r = _pt(center, "center"), _num(radius, "radius", True)
        self._grow((c[0] - r, c[1] - r), (c[0] + r, c[1] + r))
        return self.msp.add_circle(c, r, dxfattribs={"layer": self._layer(layer), **kw})

    def arc(self, center, radius, start_angle, end_angle, layer="0", **kw):
        c, r = _pt(center, "center"), _num(radius, "radius", True)
        a1, a2 = _num(start_angle, "start_angle"), _num(end_angle, "end_angle")
        self._grow((c[0] - r, c[1] - r), (c[0] + r, c[1] + r))
        return self.msp.add_arc(c, r, a1, a2, dxfattribs={"layer": self._layer(layer), **kw})

    def text(self, text, insert, height=None, layer="0", align="left", rotation=0.0, width=None, **kw):
        """MTEXT. align: left|center|right|middle-center|bottom-left|... (ezdxf MTextEntityAlignment names)."""
        ins = _pt(insert, "insert")
        h = _num(height, "height", True) if height else self.text_h
        names = {"left": "TOP_LEFT", "center": "TOP_CENTER", "right": "TOP_RIGHT", "middle": "MIDDLE_CENTER",
                 "middle-center": "MIDDLE_CENTER", "middle-left": "MIDDLE_LEFT", "middle-right": "MIDDLE_RIGHT",
                 "bottom-left": "BOTTOM_LEFT", "bottom-center": "BOTTOM_CENTER", "bottom-right": "BOTTOM_RIGHT",
                 "top-left": "TOP_LEFT", "top-center": "TOP_CENTER", "top-right": "TOP_RIGHT"}
        if align not in names:
            raise SpecError(f"unknown align {align!r}; use one of {sorted(names)}")
        if not str(text).strip():
            raise SpecError("text must not be empty")
        attribs = {"layer": self._layer(layer), "char_height": h, "rotation": float(rotation), **kw}
        if width:
            attribs["width"] = float(width)
        m = self.msp.add_mtext(str(text), dxfattribs=attribs)
        m.set_location(ins, attachment_point=getattr(MTextEntityAlignment, names[align]).value)
        nlines = str(text).count("\\P") + str(text).count("\n") + 1
        longest = max(len(s) for s in str(text).replace("\\P", "\n").split("\n"))
        w = longest * h * 0.62
        self._grow((ins[0] - (w / 2 if "center" in align or align == "middle" else (w if "right" in align else 0)), ins[1] - nlines * h * 1.4),
                   (ins[0] + (w / 2 if "center" in align or align == "middle" else (0 if "right" in align else w)), ins[1] + h))
        return m

    def hatch(self, points, pattern="ANSI31", scale=1.0, angle=0.0, layer="0", color=None, solid=False, **kw):
        pts = [_pt(p, f"points[{i}]") for i, p in enumerate(points)]
        if len(pts) < 3:
            raise SpecError("hatch needs at least 3 boundary points")
        h = self.msp.add_hatch(color=color or 256, dxfattribs={"layer": self._layer(layer), **kw})
        if solid:
            h.set_solid_fill()
        else:
            h.set_pattern_fill(pattern, scale=float(scale), angle=float(angle))
        h.paths.add_polyline_path(pts, is_closed=True)
        self._grow(*pts)
        return h

    # ---------------------------------------------------------------- dimensions
    def dim_linear(self, p1, p2, offset=None, kind="aligned", text=None, layer=None, base=None):
        """Real DIMENSION entity. kind: aligned|horizontal|vertical. `offset` = distance of the dimension line from
        the p1-p2 segment (aligned: left of p1->p2; horizontal: +y; vertical: +x); `base` = explicit dim-line point."""
        a, b = _pt(p1, "p1"), _pt(p2, "p2")
        if a == b:
            raise SpecError("dimension points are identical")
        layer = self._layer(layer or self.dim_layer)
        off = _num(offset if offset is not None else self.text_h * 4, "offset")
        if kind not in ("aligned", "horizontal", "vertical"):
            raise SpecError(f"dimension kind must be aligned|horizontal|vertical, got {kind!r}")
        attribs = {"layer": layer}
        if text is None and self.units == "in":
            m = math.dist(a, b) if kind == "aligned" else abs(b[0] - a[0]) if kind == "horizontal" else abs(b[1] - a[1])
            text = fmt_ftin(m)
        if kind == "aligned":
            d = Vec2(b) - Vec2(a)
            n = Vec2(-d.y, d.x).normalize()
            dim = self.msp.add_aligned_dim(a, b, distance=off, text=text or "<>", dimstyle=self.dimstyle, dxfattribs=attribs)
            self._grow(*(Vec2(a) + n * off,), *(Vec2(b) + n * off,))
        else:
            if kind == "horizontal":
                bp = base if base is not None else ((a[0] + b[0]) / 2, max(a[1], b[1]) + off if off >= 0 else min(a[1], b[1]) + off)
                ang = 0
            else:
                bp = base if base is not None else (max(a[0], b[0]) + off if off >= 0 else min(a[0], b[0]) + off, (a[1] + b[1]) / 2)
                ang = 90
            dim = self.msp.add_linear_dim(base=_pt(bp, "base"), p1=a, p2=b, angle=ang, text=text or "<>",
                                          dimstyle=self.dimstyle, dxfattribs=attribs)
            self._grow(a, b, bp, (bp[0], bp[1]) if ang == 0 else (bp[0], bp[1]))
            if ang == 0:
                self._grow((a[0], bp[1]), (b[0], bp[1]), (a[0], bp[1] + self.text_h * 2))
            else:
                self._grow((bp[0], a[1]), (bp[0], b[1]), (bp[0] + self.text_h * 3, bp[1]))
        dim.render()
        return dim

    RADIAL_OVERRIDE = {"dimtih": 1, "dimtoh": 1, "dimtmove": 1, "dimtad": 0}

    def dim_diameter(self, center, radius, angle=45, text=None, location=None, layer=None):
        c, r = _pt(center, "center"), _num(radius, "radius", True)
        kw = {"location": _pt(location, "location")} if location else {}
        dim = self.msp.add_diameter_dim(center=c, radius=r, angle=float(angle), text=text or "<>",
                                        dimstyle=self.dimstyle, override=self.RADIAL_OVERRIDE, dxfattribs={"layer": self._layer(layer or self.dim_layer)}, **kw)
        dim.render()
        if location:
            self._grow(_pt(location), (location[0] + self.text_h * 6, location[1] + self.text_h))
        return dim

    def dim_radius(self, center, radius, angle=45, text=None, location=None, layer=None):
        c, r = _pt(center, "center"), _num(radius, "radius", True)
        kw = {"location": _pt(location, "location")} if location else {}
        dim = self.msp.add_radius_dim(center=c, radius=r, angle=float(angle), text=text or "<>",
                                      dimstyle=self.dimstyle, override=self.RADIAL_OVERRIDE, dxfattribs={"layer": self._layer(layer or self.dim_layer)}, **kw)
        dim.render()
        if location:
            self._grow(_pt(location), (location[0] + self.text_h * 4, location[1] + self.text_h))
        return dim

    # ---------------------------------------------------------------- title block
    def extents(self):
        pts = [p for p in self.extra_extents]
        if not pts:
            raise CadError("drawing is empty")
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))

    def finish(self, margin=None):
        """(Re)build the border + title block around the current content. Safe to call repeatedly."""
        for e in self._ttlb:
            try:
                self.msp.delete_entity(e)
            except Exception:
                pass
        self._ttlb = []
        saved = list(self.extra_extents)
        x0, y0, x1, y1 = self.extents()
        cw = x1 - x0
        W = max(cw + 2 * (margin or self.text_h * 4), self.text_h * 60)
        m = margin or W * 0.03
        W = max(cw + 2 * m, self.text_h * 60)
        cx = (x0 + x1) / 2
        fx0, fx1 = cx - W / 2, cx + W / 2
        tb_h = W * 0.095
        fy0 = y0 - m - tb_h
        fy1 = y1 + m
        L = "TITLE-BLOCK"
        new = []
        new.append(self.rectangle((fx0 - W * 0.01, fy0 - W * 0.01), (fx1 + W * 0.01, fy1 + W * 0.01), layer=L, lineweight=18))
        new.append(self.rectangle((fx0, fy0), (fx1, fy1), layer=L, lineweight=50))
        ty = fy0 + tb_h
        new.append(self.line((fx0, ty), (fx1, ty), layer=L))
        fr = [0.0, 0.46, 0.64, 0.82, 1.0]
        xs = [fx0 + W * f for f in fr]
        for xx in xs[1:-1]:
            new.append(self.line((xx, fy0), (xx, ty), layer=L))
        lab_h, val_h = W * 0.0105, W * 0.0225
        labels = ["TITLE", "SCALE", "DATE", "DRAWN BY / SHEET"]
        title = self.title.upper()
        vals = [title, self.scale, self.date, self.drawn_by]
        for i in range(4):
            cw_i = xs[i + 1] - xs[i]
            new.append(self.text(labels[i], (xs[i] + W * 0.008, ty - W * 0.006), height=lab_h, layer=L))
            vh = min(val_h, cw_i * 0.92 / (0.8 * max(len(vals[i]), 1)))
            new.append(self.text(vals[i], (xs[i] + W * 0.008, fy0 + tb_h * 0.38), height=vh, layer=L, align="middle-left"))
        new.append(self.text(self.sheet, (xs[4] - W * 0.008, fy0 + W * 0.008), height=lab_h, layer=L, align="bottom-right"))
        self._ttlb = new
        self.extra_extents = saved + [(fx0 - W * 0.01, fy0 - W * 0.01), (fx1 + W * 0.01, fy1 + W * 0.01)]
        self.frame = (fx0, fy0, fx1, fy1)
        return self.frame

    # ---------------------------------------------------------------- output
    def save(self, path):
        if not self._ttlb:
            self.finish()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        # extents for viewers
        try:
            ext = bbox.extents(self.msp)
            self.doc.header["$EXTMIN"] = tuple(ext.extmin)
            self.doc.header["$EXTMAX"] = tuple(ext.extmax)
            self.doc.set_modelspace_vport(height=max(ext.size.y, 1) * 1.05, center=tuple(ext.center)[:2])
        except Exception:
            pass
        self.doc.saveas(path)
        return path

    def audit(self):
        auditor = self.doc.audit()
        return {"errors": len(auditor.errors), "fixes": len(auditor.fixes),
                "error_messages": [str(e.message) for e in auditor.errors][:20]}

    def entity_counts(self):
        return dict(Counter(e.dxf.layer for e in self.msp))


def audit_file(path: str) -> dict:
    """Open a DXF with ezdxf, run doc.audit(), count entities per layer and types, and sanity-check content."""
    if not os.path.exists(path):
        raise CadError(f"no such file: {path}")
    try:
        doc = ezdxf.readfile(path)
    except Exception as e:
        raise CadError(f"cannot open DXF: {e}")
    msp = doc.modelspace()
    auditor = doc.audit()
    per_layer = Counter(e.dxf.layer for e in msp)
    types = Counter(e.dxftype() for e in msp)
    warnings = []
    for e in msp:
        if e.dxftype() == "LINE" and Vec2(e.dxf.start).isclose(Vec2(e.dxf.end)):
            warnings.append(f"zero-length LINE on layer {e.dxf.layer}")
        if e.dxftype() == "CIRCLE" and e.dxf.radius <= 0:
            warnings.append(f"zero radius CIRCLE on layer {e.dxf.layer}")
    undefined = sorted({e.dxf.layer for e in msp if e.dxf.layer not in doc.layers})
    for u in undefined:
        warnings.append(f"layer {u!r} used but not defined")
    return {
        "file": path,
        "dxf_version": doc.dxfversion,
        "acad_release": doc.acad_release,
        "units": doc.header.get("$INSUNITS"),
        "errors": len(auditor.errors),
        "fixes": len(auditor.fixes),
        "error_messages": [str(e.message) for e in auditor.errors][:20],
        "entities_total": sum(per_layer.values()),
        "entities_per_layer": dict(sorted(per_layer.items())),
        "entity_types": dict(sorted(types.items())),
        "dimensions": types.get("DIMENSION", 0),
        "warnings": warnings[:20],
        "ok": len(auditor.errors) == 0 and not warnings,
    }
