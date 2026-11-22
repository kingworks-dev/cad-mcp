"""JSON spec -> Drawing, with clear validation errors.

Spec forms
  {"type": "room_plan", "width_ft": 12, "length_ft": 16, "wall_thickness_in": 6, "name": "BEDROOM",
   "doors": [{"wall": "south", "offset_ft": 2, "width_ft": 3}], "windows": [{"wall": "east", "offset_ft": 6, "width_ft": 4}]}
  {"type": "column_grid", "bays_x": 4, "bays_y": 3, "spacing_x_ft": 25, "spacing_y_ft": 25, "column_size_in": 14}
  {"type": "bracket", "length_mm": 100, "height_mm": 80, "leg_width_mm": 30, "thickness_mm": 6, "hole_dia_mm": 9, "fillet_r_mm": 10}
  {"type": "generic", "units": "mm"|"in", "title": "...", "layers": [{"name": "WALLS", "color": "red", "linetype": "DASHED"}],
   "entities": [{"type": "line", "start": [0,0], "end": [10,0], "layer": "WALLS"}, ...]}
  (a spec with "entities" and no "type" is generic).
Entity types: line, rectangle, polyline, circle, arc, text, dimension, hatch.
"""
from __future__ import annotations

from .builders import bracket_part, column_grid, room_plan
from .core import Drawing, SpecError

TYPES = ("room_plan", "column_grid", "bracket", "generic")
_COMMON = {"title", "scale", "name", "text_h", "out_name"}
ALLOWED = {
    "room_plan": {"width_ft", "length_ft", "wall_thickness_in", "doors", "windows"} | _COMMON,
    "column_grid": {"bays_x", "bays_y", "spacing_x_ft", "spacing_y_ft", "column_size_in", "beam_width_in"} | _COMMON,
    "bracket": {"length_mm", "height_mm", "leg_width_mm", "thickness_mm", "hole_dia_mm", "fillet_r_mm", "holes"} | _COMMON,
    "generic": {"units", "layers", "entities"} | _COMMON,
}
REQUIRED = {"room_plan": ("width_ft", "length_ft"), "column_grid": ("bays_x", "bays_y", "spacing_x_ft", "spacing_y_ft"),
            "bracket": (), "generic": ("entities",)}
ENTITY_FIELDS = {
    "line": ("start", "end"), "rectangle": ("corner1", "corner2"), "polyline": ("points",),
    "circle": ("center", "radius"), "arc": ("center", "radius", "start_angle", "end_angle"),
    "text": ("text", "insert"), "dimension": ("p1", "p2"), "hatch": ("points",),
}


def validate_spec(spec) -> str:
    """Raise SpecError with a precise message, else return the resolved spec type."""
    if not isinstance(spec, dict):
        raise SpecError("spec must be a JSON object")
    t = spec.get("type") or ("generic" if "entities" in spec else None)
    if t is None:
        raise SpecError(f"spec needs a 'type' ({', '.join(TYPES)}) or an 'entities' list")
    if t not in TYPES:
        raise SpecError(f"unknown spec type {t!r}; use one of {', '.join(TYPES)}")
    unknown = set(spec) - ALLOWED[t] - {"type"}
    if unknown:
        raise SpecError(f"unknown field(s) for {t}: {sorted(unknown)}; allowed: {sorted(ALLOWED[t])}")
    for r in REQUIRED[t]:
        if r not in spec:
            raise SpecError(f"{t} requires field '{r}'")
    if t == "generic":
        ents = spec["entities"]
        if not isinstance(ents, list) or not ents:
            raise SpecError("'entities' must be a non-empty list")
        for i, e in enumerate(ents):
            validate_entity(e, f"entities[{i}]")
        for i, l in enumerate(spec.get("layers", [])):
            if not isinstance(l, dict) or "name" not in l:
                raise SpecError(f"layers[{i}] must be an object with a 'name'")
    return t


def validate_entity(e, where="entity"):
    if not isinstance(e, dict):
        raise SpecError(f"{where} must be an object")
    t = e.get("type")
    if t not in ENTITY_FIELDS:
        raise SpecError(f"{where}.type {t!r} is not one of {sorted(ENTITY_FIELDS)}")
    for f in ENTITY_FIELDS[t]:
        if f not in e:
            raise SpecError(f"{where} ({t}) is missing '{f}'")


def add_entities(d: Drawing, entities, prefix="entities"):
    """Add generic entity dicts to a drawing (used by spec build and the MCP add_entities tool)."""
    n = 0
    for i, e in enumerate(entities):
        w = f"{prefix}[{i}]"
        validate_entity(e, w)
        t, layer = e["type"], e.get("layer", "0")
        try:
            if t == "line":
                d.line(e["start"], e["end"], layer)
            elif t == "rectangle":
                d.rectangle(e["corner1"], e["corner2"], layer)
            elif t == "polyline":
                d.polyline(e["points"], e.get("closed", False), layer)
            elif t == "circle":
                d.circle(e["center"], e["radius"], layer)
            elif t == "arc":
                d.arc(e["center"], e["radius"], e["start_angle"], e["end_angle"], layer)
            elif t == "text":
                d.text(e["text"], e["insert"], e.get("height"), layer, e.get("align", "left"), e.get("rotation", 0))
            elif t == "dimension":
                d.dim_linear(e["p1"], e["p2"], e.get("offset"), e.get("kind", "aligned"), e.get("text"), e.get("layer"))
            elif t == "hatch":
                d.hatch(e["points"], e.get("pattern", "ANSI31"), e.get("scale", 1.0), e.get("angle", 0.0), layer,
                        solid=bool(e.get("solid", False)))
        except SpecError as ex:
            raise SpecError(f"{w} ({t}): {ex}")
        n += 1
    return n


def build_from_spec(spec) -> Drawing:
    t = validate_spec(spec)
    kw = {k: spec[k] for k in ("title", "scale", "text_h") if k in spec}
    if t == "room_plan":
        return room_plan(spec["width_ft"], spec["length_ft"], spec.get("wall_thickness_in", 6), spec.get("doors"),
                         spec.get("windows"), spec.get("name", "ROOM"), **kw)
    if t == "column_grid":
        return column_grid(spec["bays_x"], spec["bays_y"], spec["spacing_x_ft"], spec["spacing_y_ft"],
                           spec.get("column_size_in", 14), spec.get("beam_width_in", 8), **kw)
    if t == "bracket":
        keys = ("length_mm", "height_mm", "leg_width_mm", "thickness_mm", "hole_dia_mm", "fillet_r_mm", "holes")
        return bracket_part(**{k: spec[k] for k in keys if k in spec}, **kw)
    d = Drawing(spec.get("units", "mm"), title=spec.get("title", "UNTITLED"), scale=spec.get("scale", "NTS"),
                text_h=spec.get("text_h"))
    for l in spec.get("layers", []):
        d.add_layer(l["name"], l.get("color", 7), l.get("linetype", "Continuous"), l.get("lineweight", 25))
    add_entities(d, spec["entities"])
    d.finish()
    return d
