#!/usr/bin/env python3
"""Extract learned V0.9 grounded-cell graph arrays from a saved Algodoo .phz/.phn scene."""

import argparse
import json
import pathlib
import re
import sys
import zipfile


def read_phn_from_path(scene_path: pathlib.Path) -> str:
    if scene_path.suffix.lower() == ".phz":
        with zipfile.ZipFile(scene_path) as zf:
            return zf.read("scene.phn").decode("utf-8")
    return scene_path.read_text(encoding="utf-8")


def parse_scene_my_assignments(phn_text: str) -> dict[str, str]:
    header = phn_text.split("FileInfo ->")[0]
    items: dict[str, str] = {}
    for m in re.finditer(r"Scene\.my\.(\w+)\s*:=\s*", header):
        name = m.group(1)
        i = m.end()
        depth = 0
        in_str = False
        while i < len(header):
            c = header[i]
            if c == "\\" and in_str and i + 1 < len(header):
                i += 2
                continue
            if c == '"':
                in_str = not in_str
            elif not in_str:
                if c in "{[(":
                    depth += 1
                elif c in "}])":
                    depth -= 1
                elif c == ";" and depth == 0:
                    break
            i += 1
        items[name] = header[m.end() : i].strip()
    return items


def parse_num(raw: str | None, default: float = 0.0, as_int: bool = False):
    if raw is None:
        return int(default) if as_int else float(default)
    try:
        v = float(raw)
        return int(round(v)) if as_int else v
    except ValueError:
        return int(default) if as_int else float(default)


def parse_num_list(raw: str | None, as_int: bool = False) -> list:
    if not raw or not raw.startswith("[") or not raw.endswith("]"):
        return []
    inner = raw[1:-1].strip()
    if not inner:
        return []
    out = []
    for part in inner.split(","):
        s = part.strip()
        if not s:
            continue
        v = float(s)
        out.append(int(round(v)) if as_int else v)
    return out


def pad_or_trim(lst: list, n: int, fill) -> list:
    if len(lst) >= n:
        return lst[:n]
    return lst + [fill] * (n - len(lst))


def extract_graph(scene_path: pathlib.Path, cap_cells: int = 220, cap_walk: int = 320, cap_fall: int = 240) -> dict:
    phn_text = read_phn_from_path(scene_path)
    items = parse_scene_my_assignments(phn_text)

    cs = parse_num(items.get("cs"), default=1.25, as_int=False)
    cells = parse_num_list(items.get("cells"), as_int=True)[:cap_cells]
    n_cells = min(parse_num(items.get("nCells"), default=len(cells), as_int=True), len(cells), cap_cells)
    cells = cells[:n_cells]
    c_block_l = pad_or_trim(parse_num_list(items.get("cBlockL"), as_int=True), n_cells, 0)
    c_block_r = pad_or_trim(parse_num_list(items.get("cBlockR"), as_int=True), n_cells, 0)
    c_ramp = pad_or_trim(parse_num_list(items.get("cRamp"), as_int=True), n_cells, 0)
    c_heat = pad_or_trim(parse_num_list(items.get("cHeat"), as_int=False), n_cells, 0.0)

    w_a = parse_num_list(items.get("wA"), as_int=True)[:cap_walk]
    w_b = parse_num_list(items.get("wB"), as_int=True)[:cap_walk]
    n_walk = min(parse_num(items.get("nWalk"), default=min(len(w_a), len(w_b)), as_int=True), len(w_a), len(w_b), cap_walk)
    w_a, w_b = w_a[:n_walk], w_b[:n_walk]
    w_by_k = pad_or_trim(parse_num_list(items.get("wByK"), as_int=True), n_walk, 1)
    w_fail = pad_or_trim(parse_num_list(items.get("wFail"), as_int=True), n_walk, 0)
    w_use = pad_or_trim(parse_num_list(items.get("wUse"), as_int=True), n_walk, 0)

    f_a = parse_num_list(items.get("fA"), as_int=True)[:cap_fall]
    f_b = parse_num_list(items.get("fB"), as_int=True)[:cap_fall]
    f_x = parse_num_list(items.get("fX"), as_int=False)[:cap_fall]
    n_fall = min(
        parse_num(items.get("nFall"), default=min(len(f_a), len(f_b), len(f_x)), as_int=True),
        len(f_a),
        len(f_b),
        len(f_x),
        cap_fall,
    )
    f_a, f_b, f_x = f_a[:n_fall], f_b[:n_fall], f_x[:n_fall]
    f_vx = pad_or_trim(parse_num_list(items.get("fVx"), as_int=False), n_fall, 0.0)
    f_by_k = pad_or_trim(parse_num_list(items.get("fByK"), as_int=True), n_fall, 1)
    f_fail = pad_or_trim(parse_num_list(items.get("fFail"), as_int=True), n_fall, 0)
    f_use = pad_or_trim(parse_num_list(items.get("fUse"), as_int=True), n_fall, 0)

    return {
        "cs": cs,
        "nCells": n_cells,
        "cells": cells,
        "cBlockL": c_block_l,
        "cBlockR": c_block_r,
        "cRamp": c_ramp,
        "cHeat": c_heat,
        "walk": {
            "nWalk": n_walk,
            "wA": w_a,
            "wB": w_b,
            "wByK": w_by_k,
            "wFail": w_fail,
            "wUse": w_use,
        },
        "fall": {
            "nFall": n_fall,
            "fA": f_a,
            "fB": f_b,
            "fX": f_x,
            "fVx": f_vx,
            "fByK": f_by_k,
            "fFail": f_fail,
            "fUse": f_use,
        },
    }


def format_thyme_snapshot(snap: dict) -> str:
    n_cells = snap["nCells"]
    c_ramp = pad_or_trim(snap.get("cRamp", []), n_cells, 0)
    c_heat = pad_or_trim(snap.get("cHeat", []), n_cells, 0.0)
    w = snap["walk"]
    n_w = w["nWalk"]
    w_use = pad_or_trim(w.get("wUse", []), n_w, 0)
    f = snap["fall"]
    n_f = f["nFall"]
    f_use = pad_or_trim(f.get("fUse", []), n_f, 0)
    lines = [
        f"scene.my.cs = {snap['cs']};",
        f"scene.my.nCells = {n_cells}; scene.my.cells = {snap['cells']}; scene.my.cBlockL = {snap['cBlockL']}; scene.my.cBlockR = {snap['cBlockR']}; scene.my.cRamp = {c_ramp}; scene.my.cHeat = {c_heat};",
        f"scene.my.nWalk = {n_w}; scene.my.wA = {w['wA']}; scene.my.wB = {w['wB']}; scene.my.wByK = {w['wByK']}; scene.my.wFail = {w['wFail']}; scene.my.wCool = {[0]*n_w}; scene.my.wUse = {w_use};",
        f"scene.my.nFall = {n_f}; scene.my.fA = {f['fA']}; scene.my.fB = {f['fB']}; scene.my.fX = {f['fX']}; scene.my.fVx = {f['fVx']}; scene.my.fByK = {f['fByK']}; scene.my.fFail = {f['fFail']}; scene.my.fCool = {[0]*n_f}; scene.my.fUse = {f_use};",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export learned graph arrays from a saved Algodoo .phz/.phn scene.")
    parser.add_argument("scene", help="Path to saved .phz or .phn file")
    parser.add_argument("-o", "--output", help="Output JSON snapshot path (default: <scene_stem>_graph.json)")
    parser.add_argument("--thyme", help="Optional output Thyme snippet path")
    args = parser.parse_args(argv)

    scene_path = pathlib.Path(args.scene)
    if not scene_path.exists():
        print(f"Scene not found: {scene_path}", file=sys.stderr)
        return 1

    snap = extract_graph(scene_path)
    out_json = pathlib.Path(args.output) if args.output else scene_path.with_name(f"{scene_path.stem}_graph.json")
    out_json.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
    print(
        f"Exported graph to {out_json}: cs={snap['cs']}, cells={snap['nCells']}, "
        f"walk={snap['walk']['nWalk']}, fall={snap['fall']['nFall']}"
    )

    if args.thyme:
        out_thyme = pathlib.Path(args.thyme)
        out_thyme.write_text(format_thyme_snapshot(snap), encoding="utf-8")
        print(f"Wrote Thyme snapshot to {out_thyme}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
