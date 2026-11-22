#!/usr/bin/env python3
"""cadkit CLI.

    python3 cli.py build spec.json --out DIR [--name NAME] [--no-render]   # DXF + PNG + PDF
    python3 cli.py audit file.dxf                                          # ezdxf audit + entity counts per layer
    python3 cli.py render file.dxf [--out DIR]                             # PNG + PDF only
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cadkit import CadError, audit_file, build_from_spec, render_dxf  # noqa: E402


def build(spec_path, out, name=None, render=True):
    with open(spec_path) as f:
        try:
            spec = json.load(f)
        except json.JSONDecodeError as e:
            raise CadError(f"{spec_path} is not valid JSON: {e}")
    d = build_from_spec(spec)
    name = name or spec.get("out_name") or os.path.splitext(os.path.basename(spec_path))[0]
    dxf = d.save(os.path.join(out, f"{name}.dxf"))
    res = {"dxf": dxf, "audit": audit_file(dxf)}
    if render:
        res.update(render_dxf(dxf, out))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="cadkit: JSON -> DXF + PNG + PDF")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("spec"); b.add_argument("--out", required=True); b.add_argument("--name"); b.add_argument("--no-render", action="store_true")
    a = sub.add_parser("audit"); a.add_argument("dxf")
    r = sub.add_parser("render"); r.add_argument("dxf"); r.add_argument("--out")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "build":
            res = build(args.spec, args.out, args.name, not args.no_render)
        elif args.cmd == "audit":
            res = audit_file(args.dxf)
        else:
            res = render_dxf(args.dxf, args.out)
    except CadError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 2
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
