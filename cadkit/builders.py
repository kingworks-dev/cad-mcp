"""High-level builders: room_plan, column_grid, bracket_part. Each returns a finished Drawing (title block included)."""
from __future__ import annotations

import math

from .core import Drawing, SpecError, _num, fmt_ftin

WALLS = ("south", "east", "north", "west")


def _fmt_area(a: float) -> str:
    return f"{a:.0f}" if abs(a - round(a)) < 1e-9 else f"{a:.1f}"


# ============================================================ room plan
def _gaps_to_segments(lo, hi, gaps):
    """Segments of [lo, hi] left after removing gaps [(a, b), ...]."""
    segs, cur = [], lo
    for a, b in sorted(gaps):
        a, b = max(a, lo), min(b, hi)
        if b <= a:
            continue
        if a > cur:
            segs.append((cur, a))
        cur = max(cur, b)
    if cur < hi:
        segs.append((cur, hi))
    return segs


def room_plan(width_ft, length_ft, wall_thickness_in=6, doors=None, windows=None, name="ROOM", title=None,
              scale="NTS", text_h=None) -> Drawing:
    """Double-line room plan. width_ft is the clear interior size along x, length_ft along y.

    doors:   [{"wall": "south|east|north|west", "offset_ft": 2, "width_ft": 3, "swing": "in|out", "hinge": "start|end"}]
    windows: [{"wall": ..., "offset_ft": 4, "width_ft": 4}]
    offset_ft is measured along the wall from its interior start corner (south/north: from the left; east/west:
    from the bottom). hinge 'start' puts the hinge at the low-offset jamb.
    """
    W = _num(width_ft, "width_ft", True) * 12
    L = _num(length_ft, "length_ft", True) * 12
    t = _num(wall_thickness_in, "wall_thickness_in", True)
    if t > min(W, L) / 4:
        raise SpecError("wall_thickness_in is too large for this room")
    doors, windows = list(doors or []), list(windows or [])
    ops = []
    for kind, lst in (("door", doors), ("window", windows)):
        for i, o in enumerate(lst):
            if not isinstance(o, dict):
                raise SpecError(f"{kind}s[{i}] must be an object")
            wall = str(o.get("wall", "south")).lower()
            if wall not in WALLS:
                raise SpecError(f"{kind}s[{i}].wall must be one of {WALLS}, got {o.get('wall')!r}")
            w = _num(o.get("width_ft", 3 if kind == "door" else 4), f"{kind}s[{i}].width_ft", True) * 12
            off = _num(o.get("offset_ft", 1), f"{kind}s[{i}].offset_ft") * 12
            wlen = W if wall in ("south", "north") else L
            if off < 0 or off + w > wlen + 1e-9:
                raise SpecError(f"{kind}s[{i}] ({off/12:g} ft + {w/12:g} ft wide) does not fit the {wall} wall ({wlen/12:g} ft clear)")
            swing = str(o.get("swing", "in")).lower()
            hinge = str(o.get("hinge", "start")).lower()
            if kind == "door" and (swing not in ("in", "out") or hinge not in ("start", "end")):
                raise SpecError(f"doors[{i}]: swing must be in|out and hinge start|end")
            ops.append({"kind": kind, "wall": wall, "u0": t + off, "u1": t + off + w, "w": w, "swing": swing, "hinge": hinge})
    for wall in WALLS:  # overlap check
        on = sorted((o for o in ops if o["wall"] == wall), key=lambda o: o["u0"])
        for a, b in zip(on, on[1:]):
            if b["u0"] < a["u1"] - 1e-9:
                raise SpecError(f"openings overlap on the {wall} wall")

    Wo, Lo = W + 2 * t, L + 2 * t
    th = text_h or max(3.0, round(max(Wo, Lo) / 40, 1))
    d = Drawing("in", title=title or f"{name} PLAN", scale=scale, text_h=th)

    def T(wall, u, v):
        return {"south": (u, v), "north": (u, Lo - v), "west": (v, u), "east": (Wo - v, u)}[wall]

    for wall in WALLS:
        olen = Wo if wall in ("south", "north") else Lo
        ilen = W if wall in ("south", "north") else L
        gaps = [(o["u0"], o["u1"]) for o in ops if o["wall"] == wall]
        for lo, hi in _gaps_to_segments(0, olen, gaps):
            d.line(T(wall, lo, 0), T(wall, hi, 0), "A-WALL")
        for lo, hi in _gaps_to_segments(t, t + ilen, gaps):
            d.line(T(wall, lo, t), T(wall, hi, t), "A-WALL")
        # corner closures at both ends of each wall are implied by faces meeting at the corners
    for o in ops:
        w, u0, u1 = o["wall"], o["u0"], o["u1"]
        for u in (u0, u1):
            d.line(T(w, u, 0), T(w, u, t), "A-WALL")
        if o["kind"] == "window":
            for v in (t / 3, t / 2, 2 * t / 3):
                d.line(T(w, u0, v), T(w, u1, v), "A-GLAZ")
            sill = 1.5
            pts = [T(w, u0 - 1, t), T(w, u0 - 1, t + sill), T(w, u1 + 1, t + sill), T(w, u1 + 1, t)]
            d.polyline(pts, closed=False, layer="A-GLAZ")
        else:
            wd = o["w"]
            hu = u0 if o["hinge"] == "start" else u1
            s = 1 if o["hinge"] == "start" else -1
            dirn = 1 if o["swing"] == "in" else -1
            vb = t if o["swing"] == "in" else 0
            leaf = 1.75
            leaf_pts = [T(w, hu, vb), T(w, hu + s * leaf, vb), T(w, hu + s * leaf, vb + dirn * wd), T(w, hu, vb + dirn * wd)]
            d.polyline(leaf_pts, closed=True, layer="A-DOOR")
            c = T(w, hu, vb)
            p_closed, p_open = T(w, hu + s * wd, vb), T(w, hu, vb + dirn * wd)
            a_c = math.degrees(math.atan2(p_closed[1] - c[1], p_closed[0] - c[0]))
            a_o = math.degrees(math.atan2(p_open[1] - c[1], p_open[0] - c[0]))
            vc = (p_closed[0] - c[0], p_closed[1] - c[1])
            vo = (p_open[0] - c[0], p_open[1] - c[1])
            ccw = vc[0] * vo[1] - vc[1] * vo[0] > 0  # closed -> open is counter-clockwise
            d.arc(c, wd, a_c if ccw else a_o, a_o if ccw else a_c, "A-DOOR")

    # label + area
    area = width_ft * length_ft
    label = f"{name} {fmt_ftin(W)} x {fmt_ftin(L)}\\P{_fmt_area(area)} SQ FT"
    d.text(label, (Wo / 2, Lo / 2 + th * 1.2), height=th * 1.3, layer="A-ANNO-TEXT", align="middle")

    # dimensions: chains on walls with openings, overall on south and west
    ch, ov = th * 6, th * 13
    for wall in WALLS:
        on = sorted((o for o in ops if o["wall"] == wall), key=lambda o: o["u0"])
        if not on:
            continue
        olen = Wo if wall in ("south", "north") else Lo
        us = [0.0]
        for o in on:
            us += [o["u0"], o["u1"]]
        us.append(olen)
        for a, b in zip(us, us[1:]):
            if b - a < 1e-6:
                continue
            p1, p2 = T(wall, a, 0), T(wall, b, 0)
            if wall in ("south", "north"):
                d.dim_linear(p1, p2, offset=-ch if wall == "south" else ch, kind="horizontal")
            else:
                d.dim_linear(p1, p2, offset=-ch if wall == "west" else ch, kind="vertical")
    d.dim_linear((0, 0), (Wo, 0), offset=-ov, kind="horizontal")
    d.dim_linear((0, 0), (0, Lo), offset=-ov, kind="vertical")
    d.finish()
    return d


# ============================================================ column grid
def _letters(n):
    out = []
    for i in range(n):
        s, k = "", i
        while True:
            s = chr(65 + k % 26) + s
            k = k // 26 - 1
            if k < 0:
                break
        out.append(s)
    return out


def column_grid(bays_x, bays_y, spacing_x_ft, spacing_y_ft, column_size_in=14, beam_width_in=8, title=None,
                scale="NTS", text_h=None) -> Drawing:
    """Structural column grid: bays_x x bays_y bays; grid lines A.. (x) and 1.. (y), bubbles, columns, beams, dim strings.
    spacing_*_ft may be a number or a list with one spacing per bay."""
    for nm, v in (("bays_x", bays_x), ("bays_y", bays_y)):
        if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 25:
            raise SpecError(f"{nm} must be an integer 1-25, got {v!r}")

    def spacings(v, n, nm):
        if isinstance(v, (list, tuple)):
            if len(v) != n:
                raise SpecError(f"{nm} list must have {n} entries (one per bay), got {len(v)}")
            return [_num(s, nm, True) * 12 for s in v]
        return [_num(v, nm, True) * 12] * n

    sx, sy = spacings(spacing_x_ft, bays_x, "spacing_x_ft"), spacings(spacing_y_ft, bays_y, "spacing_y_ft")
    col = _num(column_size_in, "column_size_in", True)
    bw = _num(beam_width_in, "beam_width_in", True)
    if col >= min(sx + sy):
        raise SpecError("column_size_in must be smaller than the bay spacing")
    xs, ys = [0.0], [0.0]
    for s in sx:
        xs.append(xs[-1] + s)
    for s in sy:
        ys.append(ys[-1] + s)
    X, Y = xs[-1], ys[-1]
    th = text_h or round(max(X, Y) / 75, 1)
    d = Drawing("in", title=title or f"COLUMN GRID {bays_x} x {bays_y} BAYS", scale=scale, text_h=th)
    ext = th * 5
    br = th * 2.1
    names_x, names_y = _letters(bays_x + 1), [str(i + 1) for i in range(bays_y + 1)]
    for x, nm in zip(xs, names_x):
        d.line((x, -ext), (x, Y + ext), "S-GRID")
        c = (x, Y + ext + br)
        d.circle(c, br, "S-GRID-IDEN")
        d.text(nm, c, height=th * 1.5, layer="S-GRID-IDEN", align="middle")
    for y, nm in zip(ys, names_y):
        d.line((-ext, y), (X + ext, y), "S-GRID")
        c = (-ext - br, y)
        d.circle(c, br, "S-GRID-IDEN")
        d.text(nm, c, height=th * 1.5, layer="S-GRID-IDEN", align="middle")
    h = col / 2
    # beams first (dashed), column face to column face
    for y in ys:
        for x0, x1 in zip(xs, xs[1:]):
            for off in (-bw / 2, bw / 2):
                d.line((x0 + h, y + off), (x1 - h, y + off), "S-BEAM")
    for x in xs:
        for y0, y1 in zip(ys, ys[1:]):
            for off in (-bw / 2, bw / 2):
                d.line((x + off, y0 + h), (x + off, y1 - h), "S-BEAM")
    for x in xs:
        for y in ys:
            pts = [(x - h, y - h), (x + h, y - h), (x + h, y + h), (x - h, y + h)]
            d.polyline(pts, closed=True, layer="S-COLS")
            d.hatch(pts, "ANSI31", scale=max(col / 14 * 12.0, 1.0), angle=0, layer="S-COLS")
    # dimension strings: bottom (x) and right (y); bubbles are on the top and left
    e1 = ext
    chain, overall = th * 5, th * 11
    for a, b in zip(xs, xs[1:]):
        d.dim_linear((a, -e1), (b, -e1), offset=-chain, kind="horizontal")
    d.dim_linear((0, -e1), (X, -e1), offset=-overall, kind="horizontal")
    for a, b in zip(ys, ys[1:]):
        d.dim_linear((X + e1, a), (X + e1, b), offset=chain, kind="vertical")
    d.dim_linear((X + e1, 0), (X + e1, Y), offset=overall, kind="vertical")
    d.text(f"COLUMNS {col:g}\" x {col:g}\" (W-SHAPE, SQUARE SYMBOL)  -  BEAMS SHOWN DASHED ({bw:g}\" WIDE)",
           (X / 2, -e1 - overall - th * 6), height=th * 1.1, layer="A-ANNO-TEXT", align="top-center")
    d.finish()
    return d


# ============================================================ bracket
def _fillet_outline(d: Drawing, pts, r, layer):
    """Draw a CCW polygon with every corner rounded by radius r (LINE + ARC entities). Returns arc centres."""
    n = len(pts)
    corners = []
    for i in range(n):
        P, A, B = pts[i], pts[i - 1], pts[(i + 1) % n]
        u1 = ((A[0] - P[0]), (A[1] - P[1]))
        u2 = ((B[0] - P[0]), (B[1] - P[1]))
        l1, l2 = math.hypot(*u1), math.hypot(*u2)
        u1, u2 = (u1[0] / l1, u1[1] / l1), (u2[0] / l2, u2[1] / l2)
        cosang = max(-1, min(1, u1[0] * u2[0] + u1[1] * u2[1]))
        theta = math.acos(cosang)
        tl = r / math.tan(theta / 2)
        if tl > min(l1, l2) / 2 + 1e-9:
            raise SpecError("fillet radius is too large for the part size")
        T1 = (P[0] + u1[0] * tl, P[1] + u1[1] * tl)
        T2 = (P[0] + u2[0] * tl, P[1] + u2[1] * tl)
        bis = (u1[0] + u2[0], u1[1] + u2[1])
        bl = math.hypot(*bis)
        cd = r / math.sin(theta / 2)
        C = (P[0] + bis[0] / bl * cd, P[1] + bis[1] / bl * cd)
        convex = (P[0] - A[0]) * (B[1] - P[1]) - (P[1] - A[1]) * (B[0] - P[0]) > 0  # CCW polygon: left turn
        corners.append((T1, T2, C, convex))
    for i in range(n):
        T1, T2, C, convex = corners[i]
        nT1 = corners[(i + 1) % n][0]
        d.line(T2, nT1, layer)
        a1 = math.degrees(math.atan2(T1[1] - C[1], T1[0] - C[0]))
        a2 = math.degrees(math.atan2(T2[1] - C[1], T2[0] - C[0]))
        if convex:
            d.arc(C, r, a1, a2, layer)
        else:
            d.arc(C, r, a2, a1, layer)
    return corners


def bracket_part(length_mm=100, height_mm=80, leg_width_mm=30, thickness_mm=6, hole_dia_mm=9, fillet_r_mm=10,
                 holes=None, title=None, scale="NTS", text_h=3.5) -> Drawing:
    """L-shaped plate bracket (top view + side view), holes, fillets, centre marks, mm dimensions.
    Corner of the L is at the origin: leg 1 runs along +x (length_mm), leg 2 along +y (height_mm).
    holes: optional [[x, y], ...]; default is two holes per leg (4 total)."""
    Lg, Hg = _num(length_mm, "length_mm", True), _num(height_mm, "height_mm", True)
    lw, tk = _num(leg_width_mm, "leg_width_mm", True), _num(thickness_mm, "thickness_mm", True)
    hd, fr = _num(hole_dia_mm, "hole_dia_mm", True), _num(fillet_r_mm, "fillet_r_mm", True)
    if lw >= min(Lg, Hg):
        raise SpecError("leg_width_mm must be smaller than length_mm and height_mm")
    if hd >= lw - 2 * 2:
        raise SpecError("hole_dia_mm is too large for the leg width")
    if fr * 2 > lw:
        raise SpecError("fillet_r_mm must be at most half the leg width")
    if holes is None:
        holes = []
        for k in range(2):
            holes.append((lw + (Lg - lw) * (k + 0.5) / 2, lw / 2))
        for k in range(2):
            holes.append((lw / 2, lw + (Hg - lw) * (k + 0.5) / 2))
    else:
        holes = [(_num(h[0], "holes[x]"), _num(h[1], "holes[y]")) for h in holes]
    poly = [(0, 0), (Lg, 0), (Lg, lw), (lw, lw), (lw, Hg), (0, Hg)]

    def inside(x, y):
        return (0 <= x <= Lg and 0 <= y <= lw) or (0 <= x <= lw and 0 <= y <= Hg)

    for i, (x, y) in enumerate(holes):
        if not all(inside(x + dx, y + dy) for dx, dy in ((hd / 2, 0), (-hd / 2, 0), (0, hd / 2), (0, -hd / 2))):
            raise SpecError(f"hole {i + 1} at ({x:g}, {y:g}) is not fully inside the plate")
    d = Drawing("mm", title=title or "L-BRACKET PLATE", scale=scale, text_h=text_h)
    corners = _fillet_outline(d, poly, fr, "M-OUTLINE")
    cm = hd * 0.9
    for (x, y) in holes:
        d.circle((x, y), hd / 2, "M-OUTLINE")
        d.line((x - cm, y), (x + cm, y), "M-CENTER")
        d.line((x, y - cm), (x, y + cm), "M-CENTER")
    # side view (looking from +x), to the right of the top view
    sx0 = Lg + 62
    d.rectangle((sx0, 0), (sx0 + tk, Hg), "M-OUTLINE")
    for (x, y) in holes:
        if x >= lw:  # leg-1 holes are not visible from the side except through the end face: hidden lines across thickness
            pass
        if x <= lw and y >= lw:  # leg-2 holes run along x: horizontal hidden lines across the plate thickness
            for yy in (y - hd / 2, y + hd / 2):
                d.line((sx0, yy), (sx0 + tk, yy), "M-HIDDEN")
    d.text("TOP VIEW", (Lg / 2, -(18 + 3 * 3.5) - 14), height=3.5 * 1.2, layer="M-TEXT", align="top-center")
    d.text("SIDE VIEW", (sx0 + tk / 2, -(18 + 3 * 3.5) - 14), height=3.5 * 1.2, layer="M-TEXT", align="top-center")
    # dimensions
    xs = sorted({0.0} | {h[0] for h in holes if h[1] < lw} | {float(Lg)})
    for a, b in zip(xs, xs[1:]):
        d.dim_linear((a, 0), (b, 0), offset=-14, kind="horizontal")
    d.dim_linear((0, 0), (Lg, 0), offset=-30, kind="horizontal")
    ysl = sorted({0.0} | {h[1] for h in holes if h[0] < lw} | {float(Hg)})
    for a, b in zip(ysl, ysl[1:]):
        d.dim_linear((0, a), (0, b), offset=-14, kind="vertical")
    d.dim_linear((0, 0), (0, Hg), offset=-30, kind="vertical")
    d.dim_linear((Lg, 0), (Lg, lw), offset=14, kind="vertical")
    d.dim_linear((0, Hg), (lw, Hg), offset=12, kind="horizontal")
    d.dim_linear((sx0, Hg), (sx0 + tk, Hg), offset=12, kind="horizontal", text=f"{tk:g}")
    # radius + diameter callouts
    C = corners[3][2]  # concave inner corner at (lw, lw); the leader runs from the free side through the arc into the plate
    d.dim_radius(C, fr, location=(C[0] - 2.2 * fr, C[1] - 2.2 * fr))
    hx, hy = holes[-1] if holes[-1][0] >= lw else holes[0]
    hx, hy = holes[1]
    d.dim_diameter((hx, hy), hd / 2, text=f"{len(holes)}X <>", location=(hx + 8, hy + 26))
    n_notes = f"PLATE THK {tk:g} mm\\PALL CORNERS R{fr:g}\\PBREAK SHARP EDGES"
    d.text(n_notes, (lw + 14, Hg - 10), height=3.0, layer="M-TEXT", align="top-left")
    d.finish()
    return d
