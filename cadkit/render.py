"""DXF -> PNG (white background, ~2000 px wide) and PDF through ezdxf's matplotlib drawing add-on."""
from __future__ import annotations

import os

import ezdxf
from ezdxf import bbox
from ezdxf.addons.drawing import Frontend, RenderContext, layout
from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration, LineweightPolicy
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

from .core import CadError


def _phi(txt: str) -> str:
    for k in ("\u00d8", "%%c", "%%C", "\\U+00D8", "\\U+00d8"):
        txt = txt.replace(k, "\u03a6")
    return txt


def _patch_diameter_glyph(doc):
    """The matplotlib text-outline path fills the bowl of the diameter sign (U+00D8) solid. In this in-memory render
    copy only, draw it as the Greek capital phi, which renders as a clean ring. The DXF on disk keeps the real sign."""
    layouts = [doc.modelspace()] + [b for b in doc.blocks]
    for lay in layouts:
        for e in lay:
            t = e.dxftype()
            if t == "MTEXT":
                e.text = _phi(e.text)
            elif t == "TEXT":
                e.dxf.text = _phi(e.dxf.text)


def render_dxf(dxf_path: str, out_dir: str | None = None, width_px: int = 2000, formats=("png", "pdf"), basename: str | None = None) -> dict:
    """Render modelspace to PNG and/or PDF next to the DXF (or in out_dir). Returns {"png": path, "pdf": path, ...}."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if not os.path.exists(dxf_path):
        raise CadError(f"no such file: {dxf_path}")
    bad = [f for f in formats if f not in ("png", "pdf", "svg")]
    if bad:
        raise CadError(f"unsupported format(s) {bad}; use png, pdf, svg")
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    _patch_diameter_glyph(doc)
    frame = [e for e in msp if e.dxf.layer == "TITLE-BLOCK" and e.dxftype() == "LWPOLYLINE"]
    ext = bbox.extents(frame) if frame else bbox.extents(msp)
    if not ext.has_data:
        raise CadError("drawing has no geometry to render")
    pad_x, pad_y = ext.size.x * 0.01, ext.size.y * 0.01
    x0, y0 = ext.extmin.x - pad_x, ext.extmin.y - pad_y
    w, h = ext.size.x + 2 * pad_x, ext.size.y + 2 * pad_y
    dpi = 100
    fig_w = width_px / dpi
    fig_h = fig_w * h / w
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi, facecolor="white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(x0, x0 + w)
    ax.set_ylim(y0, y0 + h)
    ax.set_aspect("equal")
    ax.axis("off")
    cfg = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.COLOR,
                        lineweight_policy=LineweightPolicy.RELATIVE if hasattr(LineweightPolicy, "RELATIVE") else LineweightPolicy.ABSOLUTE,
                        min_lineweight=0.35, lineweight_scaling=1.6)
    ctx = RenderContext(doc)
    backend = MatplotlibBackend(ax)
    Frontend(ctx, backend, config=cfg).draw_layout(msp, finalize=True)
    fig.set_size_inches(fig_w, fig_h)
    ax.set_position([0, 0, 1, 1])
    ax.set_xlim(x0, x0 + w)
    ax.set_ylim(y0, y0 + h)
    base = basename or os.path.splitext(os.path.basename(dxf_path))[0]
    out_dir = out_dir or os.path.dirname(os.path.abspath(dxf_path))
    os.makedirs(out_dir, exist_ok=True)
    out = {}
    for f in formats:
        p = os.path.join(out_dir, f"{base}.{f}")
        fig.savefig(p, dpi=dpi, facecolor="white")
        out[f] = p
    plt.close(fig)
    out["size_px"] = [int(round(fig_w * dpi)), int(round(fig_h * dpi))]
    return out
