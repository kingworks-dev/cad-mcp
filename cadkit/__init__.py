"""cadkit: plain-language / JSON -> real DXF (R2010) plus PNG and PDF renders. No AutoCAD needed."""
from .core import Drawing, SpecError, CadError, audit_file, today_central
from .builders import room_plan, column_grid, bracket_part
from .spec import build_from_spec, validate_spec
from .render import render_dxf

__version__ = "0.1.0"
__all__ = ["Drawing", "SpecError", "CadError", "audit_file", "today_central", "room_plan", "column_grid",
           "bracket_part", "build_from_spec", "validate_spec", "render_dxf"]
