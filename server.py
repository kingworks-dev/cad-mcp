#!/usr/bin/env python3
"""cadkit MCP server (stdio). Tools: create_drawing, add_entities, draw_room_plan, draw_column_grid, draw_bracket,
render_drawing, audit_drawing, list_layers.

Run:  python3 server.py            (output directory: $CADKIT_OUT or ./cad-output)
Needs: pip install ezdxf matplotlib mcp
"""
import functools
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from cadkit import CadError, Drawing, audit_file, bracket_part, column_grid, render_dxf, room_plan  # noqa: E402
from cadkit.spec import add_entities as _add_entities  # noqa: E402

mcp = _Server("cadkit", instructions="Create real DXF drawings (R2010) with PNG/PDF renders: room plans, column grids, "
              "L-brackets or generic entities. Drafting aid only; not stamped engineering drawings.")
DRAWINGS: dict[str, Drawing] = {}


def _out_dir(out_dir=None):
    d = out_dir or os.environ.get("CADKIT_OUT") or os.path.join(os.getcwd(), "cad-output")
    os.makedirs(d, exist_ok=True)
    return d


def _slug(name):
    s = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(name)).strip("-")
    if not s:
        raise CadError("name must contain letters or digits")
    return s


def _ok(**kw):
    return json.dumps({"ok": True, **kw}, indent=2)


def _err(e):
    return json.dumps({"ok": False, "error": str(e)}, indent=2)


def _save(d: Drawing, name, out_dir, render):
    name = _slug(name)
    out = _out_dir(out_dir)
    DRAWINGS[name] = d
    dxf = d.save(os.path.join(out, f"{name}.dxf"))
    res = {"name": name, "dxf": dxf, "audit": audit_file(dxf)}
    if render:
        res["render"] = render_dxf(dxf, out)
    return res


def _guard(fn):
    @functools.wraps(fn)
    def w(*a, **k):
        try:
            return fn(*a, **k)
        except (CadError, ValueError, TypeError, KeyError) as e:
            return _err(e)
    return w


@mcp.tool()
@_guard
def create_drawing(name: str, units: str = "mm", title: str = "UNTITLED", scale: str = "NTS", layers: list[dict] | None = None) -> str:
    """Start an empty drawing held in memory. units: 'mm' (mechanical) or 'in' (architectural, feet-inches dimensions).
    layers: optional [{"name","color","linetype","lineweight"}]. Then call add_entities, then render_drawing."""
    d = Drawing(units, title=title, scale=scale)
    for l in layers or []:
        d.add_layer(l["name"], l.get("color", 7), l.get("linetype", "Continuous"), l.get("lineweight", 25))
    DRAWINGS[_slug(name)] = d
    return _ok(name=_slug(name), units=units, layers=[l["name"] for l in d.list_layers()])


@mcp.tool()
@_guard
def add_entities(name: str, entities: list[dict]) -> str:
    """Add primitives to a drawing. Each entity is {"type": line|rectangle|polyline|circle|arc|text|dimension|hatch, ...,
    "layer": "NAME"}. line: start,end. rectangle: corner1,corner2. polyline: points,closed. circle: center,radius.
    arc: center,radius,start_angle,end_angle. text: text,insert,height,align. dimension: p1,p2,offset,kind
    (aligned|horizontal|vertical),text. hatch: points,pattern,scale,solid. Coordinates are in drawing units."""
    d = DRAWINGS.get(_slug(name))
    if d is None:
        raise CadError(f"no drawing named {name!r}; call create_drawing first (open: {sorted(DRAWINGS)})")
    n = _add_entities(d, entities)
    return _ok(name=_slug(name), added=n, per_layer=d.entity_counts())


@mcp.tool()
@_guard
def draw_room_plan(name: str, width_ft: float, length_ft: float, wall_thickness_in: float = 6, doors: list[dict] | None = None,
                   windows: list[dict] | None = None, room_name: str = "ROOM", out_dir: str | None = None, render: bool = True) -> str:
    """Room plan with double-line walls, doors (swing arc), windows (sill lines), overall + opening dimensions, label,
    area and title block. width_ft/length_ft are clear interior sizes. doors: [{"wall": "south|east|north|west",
    "offset_ft", "width_ft", "swing": "in|out", "hinge": "start|end"}]; windows: [{"wall","offset_ft","width_ft"}].
    Saves DXF (+ PNG/PDF when render)."""
    d = room_plan(width_ft, length_ft, wall_thickness_in, doors, windows, room_name)
    return _ok(**_save(d, name, out_dir, render))


@mcp.tool()
@_guard
def draw_column_grid(name: str, bays_x: int, bays_y: int, spacing_x_ft: float, spacing_y_ft: float, column_size_in: float = 14,
                     out_dir: str | None = None, render: bool = True) -> str:
    """Structural column grid: dashed grid lines, bubbles A.. / 1.., hatched square columns, beams, dimension strings."""
    d = column_grid(bays_x, bays_y, spacing_x_ft, spacing_y_ft, column_size_in)
    return _ok(**_save(d, name, out_dir, render))


@mcp.tool()
@_guard
def draw_bracket(name: str, length_mm: float = 100, height_mm: float = 80, leg_width_mm: float = 30, thickness_mm: float = 6,
                 hole_dia_mm: float = 9, fillet_r_mm: float = 10, holes: list[list[float]] | None = None,
                 out_dir: str | None = None, render: bool = True) -> str:
    """L-shaped plate bracket: top and side view, holes (default 4), filleted corners, centre marks, mm dimensions."""
    d = bracket_part(length_mm, height_mm, leg_width_mm, thickness_mm, hole_dia_mm, fillet_r_mm, holes)
    return _ok(**_save(d, name, out_dir, render))


@mcp.tool()
@_guard
def render_drawing(name_or_path: str, out_dir: str | None = None, formats: list[str] | None = None) -> str:
    """Render a drawing (in-memory name, or a .dxf path) to PNG (~2000 px, white background) and PDF."""
    if name_or_path.lower().endswith(".dxf"):
        dxf = name_or_path
    else:
        nm = _slug(name_or_path)
        if nm not in DRAWINGS:
            raise CadError(f"no drawing named {name_or_path!r} (open: {sorted(DRAWINGS)})")
        dxf = DRAWINGS[nm].save(os.path.join(_out_dir(out_dir), f"{nm}.dxf"))
    return _ok(dxf=dxf, **render_dxf(dxf, out_dir, formats=tuple(formats or ("png", "pdf"))))


@mcp.tool()
@_guard
def audit_drawing(name_or_path: str) -> str:
    """ezdxf audit (errors/fixes), DXF version, entity counts per layer and type, and sanity warnings for a DXF."""
    if name_or_path.lower().endswith(".dxf"):
        dxf = name_or_path
    else:
        nm = _slug(name_or_path)
        if nm not in DRAWINGS:
            raise CadError(f"no drawing named {name_or_path!r} (open: {sorted(DRAWINGS)})")
        dxf = DRAWINGS[nm].save(os.path.join(_out_dir(), f"{nm}.dxf"))
    return _ok(**audit_file(dxf))


@mcp.tool()
@_guard
def list_layers(name_or_path: str) -> str:
    """List layers (name, color, linetype, entity count) of an in-memory drawing or a DXF path."""
    if name_or_path.lower().endswith(".dxf"):
        import ezdxf
        from collections import Counter
        doc = ezdxf.readfile(name_or_path)
        used = Counter(e.dxf.layer for e in doc.modelspace())
        layers = [{"name": l.dxf.name, "color": l.color, "linetype": l.dxf.linetype, "entities": used.get(l.dxf.name, 0)} for l in doc.layers]
    else:
        nm = _slug(name_or_path)
        if nm not in DRAWINGS:
            raise CadError(f"no drawing named {name_or_path!r} (open: {sorted(DRAWINGS)})")
        layers = DRAWINGS[nm].list_layers()
    return _ok(layers=layers)


if __name__ == "__main__":
    mcp.run("stdio")
