#!/usr/bin/env python3
"""Real-Algodoo Thyme Probe, Benchmark & Strict-Whitelist Linter CLI."""

import argparse
import dataclasses
import json
import pathlib
import re
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "src"
PROBES_FILE = ROOT / "probes" / "candidates.json"
VERIFIED_FILE = ROOT / "verified_thyme.json"
DIST_DIR = ROOT / "dist"

# Extra primitives verified in NOTES.md (console/postStep) that may not appear in src/*.thyme
NOTES_VERIFIED_EXTRAS = {
    "Math.sqrt",
    "for",
    "god",
    "list(i)",
    "time",
    "()",
    "{}",
    "[]",
    "?:",
}

# Lambda arrow / statement / expression operators
OP_PATTERNS = [
    "=>",
    ":=",
    "==",
    "!=",
    "<=",
    ">=",
    "&&",
    "||",
    "++",
    "+",
    "-",
    "*",
    "/",
    "%",
    "<",
    ">",
    "=",
    "!",
    "?",
    ":",
]


@dataclasses.dataclass
class Token:
    kind: str  # STRING, NUMBER, IDENT, OP, DELIM
    value: str
    line: int
    col: int


def tokenize_thyme(text: str) -> tuple[list[Token], list[str]]:
    """Tokenize Thyme source into tokens and lexical errors (e.g., unclosed strings)."""
    tokens: list[Token] = []
    errors: list[str] = []
    i = 0
    n = len(text)
    line = 1
    col = 1

    while i < n:
        c = text[i]

        if c == "\n":
            line += 1
            col = 1
            i += 1
            continue
        if c in " \t\r":
            col += 1
            i += 1
            continue

        # Line comment //
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue

        # String literal
        if c == '"':
            start_line, start_col = line, col
            i += 1
            col += 1
            buf = ['"']
            closed = False
            while i < n:
                sc = text[i]
                if sc == "\\" and i + 1 < n:
                    buf.append(sc)
                    buf.append(text[i + 1])
                    if text[i + 1] == "\n":
                        line += 1
                        col = 1
                    else:
                        col += 2
                    i += 2
                    continue
                if sc == "\n":
                    line += 1
                    col = 1
                    buf.append(sc)
                    i += 1
                    continue
                buf.append(sc)
                i += 1
                col += 1
                if sc == '"':
                    closed = True
                    break
            if not closed:
                errors.append(f"L{start_line}:{start_col}: unclosed string literal")
            tokens.append(Token("STRING", "".join(buf), start_line, start_col))
            continue

        # Number literal
        if c.isdigit():
            start_col = col
            j = i
            while j < n and text[j].isdigit():
                j += 1
            if j < n and text[j] == "." and j + 1 < n and text[j + 1].isdigit():
                j += 1
                while j < n and text[j].isdigit():
                    j += 1
            val = text[i:j]
            tokens.append(Token("NUMBER", val, line, start_col))
            col += j - i
            i = j
            continue

        # Identifier
        if c.isalpha() or c == "_":
            start_col = col
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            val = text[i:j]
            tokens.append(Token("IDENT", val, line, start_col))
            col += j - i
            i = j
            continue

        # Multi/single-char operators
        matched_op = None
        for op in OP_PATTERNS:
            if text.startswith(op, i):
                matched_op = op
                break
        if matched_op is not None:
            tokens.append(Token("OP", matched_op, line, col))
            col += len(matched_op)
            i += len(matched_op)
            continue

        # Delimiters
        if c in "(){}[];,.":
            tokens.append(Token("DELIM", c, line, col))
            col += 1
            i += 1
            continue

        errors.append(f"L{line}:{col}: unexpected character {c!r}")
        col += 1
        i += 1

    return tokens, errors


def match_closing(tokens: list[Token], open_idx: int) -> int | None:
    """Return index of the matching closing delimiter for (, {, or [ at open_idx."""
    pairs = {"(": ")", "{": "}", "[": "]"}
    open_ch = tokens[open_idx].value
    close_ch = pairs[open_ch]
    depth = 0
    for idx in range(open_idx, len(tokens)):
        t = tokens[idx]
        if t.kind == "DELIM":
            if t.value == open_ch:
                depth += 1
            elif t.value == close_ch:
                depth -= 1
                if depth == 0:
                    return idx
    return None


def compute_lambda_param_scopes(tokens: list[Token]) -> dict[int, set[str]]:
    """Map token index inside a lambda body `{ ... }` to active parameter names."""
    scopes: dict[int, set[str]] = {}
    i = 0
    n = len(tokens)
    while i < n:
        if tokens[i].kind == "DELIM" and tokens[i].value == "(":
            close_p = match_closing(tokens, i)
            if (
                close_p is not None
                and close_p + 2 < n
                and tokens[close_p + 1].kind == "OP"
                and tokens[close_p + 1].value == "=>"
                and tokens[close_p + 2].kind == "DELIM"
                and tokens[close_p + 2].value == "{"
            ):
                params = {
                    tokens[k].value
                    for k in range(i + 1, close_p)
                    if tokens[k].kind == "IDENT"
                }
                body_end = match_closing(tokens, close_p + 2)
                if body_end is not None:
                    for k in range(i, body_end + 1):
                        scopes.setdefault(k, set()).update(params)
        i += 1
    return scopes


def collect_dotted_chains(tokens: list[Token]) -> list[tuple[int, int, str]]:
    """Return list of (start_tok_idx, end_tok_idx_inclusive, 'a.b.c') for identifier chains."""
    chains: list[tuple[int, int, str]] = []
    i = 0
    n = len(tokens)
    while i < n:
        if tokens[i].kind == "IDENT":
            start = i
            parts = [tokens[i].value]
            j = i
            while (
                j + 2 < n
                and tokens[j + 1].kind == "DELIM"
                and tokens[j + 1].value == "."
                and tokens[j + 2].kind == "IDENT"
            ):
                parts.append(tokens[j + 2].value)
                j += 2
            chains.append((start, j, ".".join(parts)))
            i = j + 1
        else:
            i += 1
    return chains


def load_registry() -> dict:
    if VERIFIED_FILE.exists():
        return json.loads(VERIFIED_FILE.read_text(encoding="utf-8"))
    return {"verified": [], "rejected": []}


def save_registry(reg: dict) -> None:
    reg["verified"] = sorted(set(reg.get("verified", [])))
    reg["rejected"] = sorted(set(reg.get("rejected", [])))
    VERIFIED_FILE.write_text(json.dumps(reg, indent=2) + "\n", encoding="utf-8")


def scan_src_verified_tokens() -> set[str]:
    """Extract all operators, built-ins, and object/scene properties used across src/*.thyme."""
    found: set[str] = set(NOTES_VERIFIED_EXTRAS)
    src_files = sorted(SRC_DIR.glob("*.thyme"))
    for path in src_files:
        text = path.read_text(encoding="utf-8")
        tokens, _ = tokenize_thyme(text)
        param_scopes = compute_lambda_param_scopes(tokens)

        for tok in tokens:
            if tok.kind == "OP":
                found.add(tok.value)

        for start, end, chain in collect_dotted_chains(tokens):
            params = param_scopes.get(start, set())
            parts = chain.split(".")
            head = parts[0]
            if head.startswith("_") or (len(parts) == 1 and head in params):
                continue
            if chain.startswith("scene.my.") or chain == "scene.my":
                found.add("scene.my")
                continue
            if chain.startswith("this.") or chain == "this":
                found.add("this")
                continue
            found.add(chain)
    return found


def cmd_seed(_args: argparse.Namespace) -> int:
    reg = load_registry()
    extracted = scan_src_verified_tokens()
    rejected = set(reg.get("rejected", []))
    verified = (set(reg.get("verified", [])) | extracted) - rejected
    reg["verified"] = sorted(verified)
    reg["rejected"] = sorted(rejected)
    save_registry(reg)
    print(f"Synced {VERIFIED_FILE.name}: {len(reg['verified'])} verified, {len(reg['rejected'])} rejected.")
    return 0


def check_balanced_brackets(tokens: list[Token]) -> list[str]:
    errors: list[str] = []
    stack: list[Token] = []
    opening = {"(": ")", "{": "}", "[": "]"}
    closing = {")": "(", "}": "{", "]": "["}
    for tok in tokens:
        if tok.kind != "DELIM":
            continue
        if tok.value in opening:
            stack.append(tok)
        elif tok.value in closing:
            if not stack:
                errors.append(f"L{tok.line}:{tok.col}: unmatched closing '{tok.value}'")
            else:
                top = stack.pop()
                if opening[top.value] != tok.value:
                    errors.append(
                        f"L{tok.line}:{tok.col}: mismatched '{tok.value}' for '{top.value}' opened at L{top.line}:{top.col}"
                    )
    for top in stack:
        errors.append(f"L{top.line}:{top.col}: unclosed '{top.value}'")
    return errors


def lint_file(path: pathlib.Path, verified: set[str], rejected: set[str]) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for a single .thyme file."""
    text = path.read_text(encoding="utf-8")
    tokens, lex_errors = tokenize_thyme(text)
    errors: list[str] = list(lex_errors)
    warnings: list[str] = []

    errors.extend(check_balanced_brackets(tokens))
    param_scopes = compute_lambda_param_scopes(tokens)
    chains = collect_dotted_chains(tokens)
    chain_by_start = {s: (e, c) for s, e, c in chains}

    is_poststep = "poststep" in path.name.lower()
    is_killer_poststep = path.name.lower() == "killer_poststep.thyme"

    n = len(tokens)
    for idx, tok in enumerate(tokens):
        # Ban 0-arg ()=> lambdas (Algodoo .phn loader evaluates them as undefined; use (u)=>{} or {})
        if (
            tok.kind == "DELIM"
            and tok.value == "("
            and idx + 2 < n
            and tokens[idx + 1].kind == "DELIM"
            and tokens[idx + 1].value == ")"
            and tokens[idx + 2].kind == "OP"
            and tokens[idx + 2].value == "=>"
        ):
            errors.append(
                f"L{tok.line}:{tok.col}: banned 0-arg lambda '()=>' (use '(u)=>{{ ... }}' or '{{ ... }}')"
            )

        # Non-fatal warning for numeric literal immediately called like 240(...)
        if (
            tok.kind == "NUMBER"
            and idx + 1 < n
            and tokens[idx + 1].kind == "DELIM"
            and tokens[idx + 1].value == "("
        ):
            warnings.append(
                f"L{tok.line}:{tok.col}: numeric literal '{tok.value}' followed by '(' (possible missing ';')"
            )

        # Operator whitelist check
        if tok.kind == "OP":
            if tok.value in rejected:
                errors.append(f"L{tok.line}:{tok.col}: rejected operator '{tok.value}'")
            elif tok.value not in verified:
                errors.append(f"L{tok.line}:{tok.col}: unverified operator '{tok.value}'")

        # Forbid scene.my[...] bracket indexing
        if (
            idx in chain_by_start
            and chain_by_start[idx][1] == "scene.my"
            and chain_by_start[idx][0] + 1 < n
            and tokens[chain_by_start[idx][0] + 1].kind == "DELIM"
            and tokens[chain_by_start[idx][0] + 1].value == "["
        ):
            errors.append(f"L{tok.line}:{tok.col}: rejected scene.my[...] bracket indexing")

        # Forbid in-place list index assignment: target(...) = ...
        if idx in chain_by_start:
            end_i, chain = chain_by_start[idx]
            if (
                end_i + 1 < n
                and tokens[end_i + 1].kind == "DELIM"
                and tokens[end_i + 1].value == "("
            ):
                close_p = match_closing(tokens, end_i + 1)
                if (
                    close_p is not None
                    and close_p + 1 < n
                    and tokens[close_p + 1].kind == "OP"
                    and tokens[close_p + 1].value in ("=", ":=")
                ):
                    errors.append(
                        f"L{tok.line}:{tok.col}: in-place list index assignment '{chain}(...) {tokens[close_p + 1].value}' is rejected"
                    )

            # Forbid onCollide = inside postStep
            if (
                is_poststep
                and (chain == "onCollide" or chain.endswith(".onCollide"))
                and end_i + 1 < n
                and tokens[end_i + 1].kind == "OP"
                and tokens[end_i + 1].value in ("=", ":=")
            ):
                errors.append(
                    f"L{tok.line}:{tok.col}: assigning '{chain}' inside postStep is forbidden"
                )

            # Marble physics rule: vel(1) must stay untouched in killer_poststep.thyme
            if is_killer_poststep and chain == "vel":
                if (
                    end_i + 1 < n
                    and tokens[end_i + 1].kind == "OP"
                    and tokens[end_i + 1].value in ("=", ":=")
                ):
                    # Must be vel = [ <expr0> , vel(1) ]
                    rhs_start = end_i + 2
                    valid_vel_assign = False
                    if (
                        rhs_start < n
                        and tokens[rhs_start].kind == "DELIM"
                        and tokens[rhs_start].value == "["
                    ):
                        rhs_end = match_closing(tokens, rhs_start)
                        if rhs_end is not None:
                            # Split top-level comma inside [ ... ]
                            depth = 0
                            commas = []
                            for k in range(rhs_start + 1, rhs_end):
                                tk = tokens[k]
                                if tk.kind == "DELIM":
                                    if tk.value in "([{":
                                        depth += 1
                                    elif tk.value in ")]}":
                                        depth -= 1
                                    elif tk.value == "," and depth == 0:
                                        commas.append(k)
                            if len(commas) == 1:
                                y_toks = [t.value for t in tokens[commas[0] + 1 : rhs_end]]
                                if y_toks == ["vel", "(", "1", ")"]:
                                    valid_vel_assign = True
                    if not valid_vel_assign:
                        errors.append(
                            f"L{tok.line}:{tok.col}: killer_poststep vel assignment must preserve vel(1) as [vx, vel(1)]"
                        )

            # Strict whitelist check for identifiers & dotted paths
            params = param_scopes.get(idx, set())
            parts = chain.split(".")
            head = parts[0]
            if head.startswith("_") or (len(parts) == 1 and head in params):
                continue

            if chain in rejected:
                errors.append(f"L{tok.line}:{tok.col}: rejected symbol '{chain}'")
                continue

            if chain.startswith("scene.my.") or chain == "scene.my":
                if "scene.my" not in verified:
                    errors.append(f"L{tok.line}:{tok.col}: unverified namespace 'scene.my'")
                continue
            if chain.startswith("this.") or chain == "this":
                if "this" not in verified:
                    errors.append(f"L{tok.line}:{tok.col}: unverified namespace 'this'")
                continue

            if chain not in verified:
                if parts[-1] in rejected:
                    errors.append(f"L{tok.line}:{tok.col}: rejected symbol '{chain}'")
                else:
                    errors.append(f"L{tok.line}:{tok.col}: unverified symbol '{chain}'")

    return errors, warnings


def collect_setup_scene_my_inits(setup_path: pathlib.Path | None = None) -> set[str]:
    """Collect all scene.my.<name> variables/functions assigned in src/setup.thyme."""
    target = setup_path or (SRC_DIR / "setup.thyme")
    if not target.exists():
        return set()
    toks, _ = tokenize_thyme(target.read_text(encoding="utf-8"))
    inits: set[str] = set()
    n = len(toks)
    for start, end, chain in collect_dotted_chains(toks):
        if (
            chain.startswith("scene.my.")
            and end + 1 < n
            and toks[end + 1].kind == "OP"
            and toks[end + 1].value in ("=", ":=")
        ):
            inits.add(chain.split(".")[2])
    return inits


def check_scene_my_reads(path: pathlib.Path, setup_inits: set[str]) -> tuple[list[str], list[str]]:
    """Detect scene.my.<name> reads across src/*.thyme that are missing initialization in setup.thyme."""
    errors: list[str] = []
    warnings: list[str] = []
    toks, _ = tokenize_thyme(path.read_text(encoding="utf-8"))
    n = len(toks)
    seen_missing: set[str] = set()
    # Exempt build-injected auto-init helper and external scene teleport anchor (warn only for tp3)
    build_injected = {"runSetup"}
    external_anchors = {"tp3"}
    for start, end, chain in collect_dotted_chains(toks):
        if not chain.startswith("scene.my."):
            continue
        name = chain.split(".")[2]
        is_write = end + 1 < n and toks[end + 1].kind == "OP" and toks[end + 1].value in ("=", ":=")
        if is_write or name in setup_inits or name in build_injected or name in seen_missing:
            continue
        seen_missing.add(name)
        tok = toks[start]
        if name in external_anchors:
            warnings.append(
                f"L{tok.line}:{tok.col}: external scene anchor 'scene.my.{name}' not initialized in src/setup.thyme"
            )
        else:
            errors.append(
                f"L{tok.line}:{tok.col}: uninitialized read 'scene.my.{name}' not defined in src/setup.thyme"
            )
    return errors, warnings


def cmd_lint(_args: argparse.Namespace) -> int:
    reg = load_registry()
    verified = set(reg.get("verified", []))
    rejected = set(reg.get("rejected", []))
    src_files = sorted(SRC_DIR.glob("*.thyme"))
    if not src_files:
        print("No src/*.thyme files found.", file=sys.stderr)
        return 1

    setup_inits = collect_setup_scene_my_inits()
    total_errors = 0
    total_warnings = 0
    for path in src_files:
        errors, warnings = lint_file(path, verified, rejected)
        init_errs, init_warns = check_scene_my_reads(path, setup_inits)
        errors.extend(init_errs)
        warnings.extend(init_warns)
        rel = path.relative_to(ROOT)
        for w in warnings:
            print(f"[WARN] {rel}:{w}")
        for e in errors:
            print(f"[ERR]  {rel}:{e}", file=sys.stderr)
        total_warnings += len(warnings)
        total_errors += len(errors)
        if not errors:
            print(f"[OK]   {rel}")

    print(f"Lint complete: {len(src_files)} files, {total_errors} error(s), {total_warnings} warning(s).")
    return 1 if total_errors > 0 else 0


def build_minimal_phn_header(scene_my_lines: list[str], title: str, pan: tuple[float, float], zoom: float) -> str:
    """Return a clean Algodoo v2.2.4 .phn header block with custom Scene.my.* init lines."""
    my_block = "\n".join(scene_my_lines)
    return f"""// FileVersion 21
// Algodoo scene created by Algodoo v2.2.4

{my_block}
FileInfo -> {{
    title = "{title}";
    version = 21
}};
Sim -> {{
    gravitySwitch = true;
    gravityStrength = 9.8000002;
    gravityAngleOffset = 0;
    airSwitch = true;
    airFrictionMultiplier = 1;
    timeFactor = 1.0000000;
    frequency = 60.000000;
    collideCallbacksEveryStep = true;
    scriptUpdatesEveryStep = true
}};
Palette -> {{
    opaqueBorders = true;
    borders = true;
    skyColor = [0.15000001, 0.15000001, 0.18000001, 1.0000000]
}};
Scene -> {{
    textures = [];
    sounds = []
}};
Scene.Camera -> {{
    pan = [{pan[0]}, {pan[1]}];
    rotation = 0;
    trackRotation = false;
    zoom = {zoom}
}};
App.Background -> {{
    drawClouds = false;
    skyColor = [0.15000001, 0.15000001, 0.18000001, 1.0000000]
}};
"""


def format_add_box(
    entity_id: int,
    pos: tuple[float, float],
    size: tuple[float, float],
    color: tuple[float, float, float, float],
    text: str,
    text_scale: float,
    post_step: str,
    on_click: str = "(e)=>{}",
) -> str:
    esc_text = text.replace("\\", "\\\\").replace('"', '\\"')
    return f"""Scene.addBox {{
    inertiaMultiplier := 1.0000000;
    resources := [];
    timeToLive := +inf;
    textureClamped := [false, false];
    adhesion := 0.0000000;
    attractionType := 2;
    attraction := 0.0000000;
    textScale := {text_scale};
    texture := "";
    update := (e)=>{{}};
    vel := [0.0000000, 0.0000000];
    restitution := 0.50000000;
    onCollide := (e)=>{{}};
    killer := false;
    materialVelocity := 0.0000000;
    immortal := true;
    ruler := false;
    textColor := [1.0000000, 1.0000000, 1.0000000, 1.0000000];
    textConstrained := true;
    textFontSize := 24.000000;
    textFont := "Verdana";
    collideSet := 0;
    drawBorder := true;
    reflectiveness := 1.0000000;
    size := [{size[0]}, {size[1]}];
    friction := 0.50000000;
    entityID := {entity_id};
    onClick := {on_click};
    color := [{color[0]}, {color[1]}, {color[2]}, {color[3]}];
    collideWater := false;
    onSpawn := (e)=>{{}};
    materialName := "";
    onHitByLaser := (e)=>{{}};
    pos := [{pos[0]}, {pos[1]}];
    onDie := (e)=>{{}};
    density := 2.0000000;
    angvel := 0.0000000;
    heteroCollide := false;
    glued := true;
    onKey := (e)=>{{}};
    postStep := {post_step};
    text := "{esc_text}";
    opaqueBorders := true;
    geomID := {entity_id};
    body := 0;
    edgeBlur := 0.0000000;
    angle := 0.0000000;
    zDepth := {float(entity_id)};
    layer := 0
}};
"""


def write_phz(out_path: pathlib.Path, scene_phn: str) -> None:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("scene.phn", scene_phn.encode("utf-8"))


def cmd_probe(_args: argparse.Namespace) -> int:
    if not PROBES_FILE.exists():
        print(f"Missing {PROBES_FILE}", file=sys.stderr)
        return 1
    candidates = json.loads(PROBES_FILE.read_text(encoding="utf-8"))

    scene_my_lines: list[str] = []
    boxes: list[str] = []

    for idx, cand in enumerate(candidates):
        pid = cand["id"]
        expr = cand["expr"]
        scene_my_lines.append(f'Scene.my.probe_{pid} := "NOT_RUN";')
        scene_my_lines.append(f"Scene.my.probe_{pid}_ok := 0;")
        scene_my_lines.append(f'Scene.my.probe_{pid}_str := "(non-scalar)";')

        col_idx = idx % 2
        row_idx = idx // 2
        bx = -6.0 + col_idx * 7.0
        by = 6.0 - row_idx * 1.15

        # Isolated postStep: uses pre-initialized scene.my.probe_<id>_ok == 0 (no undefined this.* reads),
        # sets ok=-1 before evaluating expr, ok=1 after storing raw value, then stringifies & updates text.
        post_step = (
            "(e)=>{\n"
            f"        scene.my.probe_{pid}_ok == 0 ? {{\n"
            f"            scene.my.probe_{pid}_ok = -1;\n"
            f"            scene.my.probe_{pid} = ({expr});\n"
            f"            scene.my.probe_{pid}_ok = 1;\n"
            f'            scene.my.probe_{pid}_str = "" + scene.my.probe_{pid};\n'
            f'            text = "{pid}: " + scene.my.probe_{pid}_str\n'
            "        } : {}\n"
            "    }"
        )
        boxes.append(
            format_add_box(
                entity_id=100 + idx,
                pos=(bx, by),
                size=(6.5, 0.95),
                color=(0.18, 0.22, 0.28, 1.0),
                text=f"{pid}: WAIT",
                text_scale=0.35,
                post_step=post_step,
            )
        )

    # Summary Text Box on the right summarizing all probe statuses
    summary_parts = ['"PROBE SUMMARY\\n"']
    for cand in candidates:
        pid = cand["id"]
        summary_parts.append(
            f'"{pid}: " + (scene.my.probe_{pid}_ok == 1 ? ("OK (" + scene.my.probe_{pid}_str + ")") : (scene.my.probe_{pid}_ok == -1 ? "ERR" : "WAIT")) + "\\n"'
        )
    summary_expr = " + ".join(summary_parts)
    summary_post = (
        "(e)=>{\n"
        f"        text = {summary_expr}\n"
        "    }"
    )
    boxes.append(
        format_add_box(
            entity_id=900,
            pos=(8.0, 0.0),
            size=(11.0, 14.0),
            color=(0.1, 0.12, 0.16, 1.0),
            text="PROBE SUMMARY (press Play, then Save)",
            text_scale=0.32,
            post_step=summary_post,
        )
    )

    header = build_minimal_phn_header(scene_my_lines, "Thyme Probe Suite", pan=(2.0, 0.0), zoom=28.0)
    out_phz = DIST_DIR / "probe_scene.phz"
    write_phz(out_phz, header + "\n".join(boxes))
    print(f"Wrote {out_phz.relative_to(ROOT)} with {len(candidates)} isolated probes + summary box.")
    return 0


def parse_scene_my_assignments(phn_text: str) -> dict[str, str]:
    """Parse top-level `Scene.my.<name> := <value>;` entries from a saved .phn."""
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


def infer_thyme_type(raw_val: str) -> str:
    if raw_val in ("true", "false"):
        return "bool"
    if raw_val.startswith('"') and raw_val.endswith('"'):
        return "string"
    if raw_val.startswith("[") and raw_val.endswith("]"):
        return "list"
    if "=>" in raw_val or (raw_val.startswith("{") and raw_val.endswith("}")):
        return "lambda/block"
    if re.fullmatch(r"[+-]?\d+", raw_val):
        return "int"
    if re.fullmatch(r"[+-]?(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?", raw_val) or raw_val in ("+inf", "-inf", "NaN"):
        return "float"
    return "object/other"


def read_phn_from_path(scene_path: pathlib.Path) -> str:
    if scene_path.suffix.lower() == ".phz":
        with zipfile.ZipFile(scene_path) as zf:
            return zf.read("scene.phn").decode("utf-8")
    return scene_path.read_text(encoding="utf-8")


def cmd_harvest(args: argparse.Namespace) -> int:
    scene_path = pathlib.Path(args.scene)
    if not scene_path.is_absolute():
        scene_path = (pathlib.Path.cwd() / scene_path).resolve()
    if not scene_path.exists():
        print(f"Scene not found: {scene_path}", file=sys.stderr)
        return 1

    candidates = json.loads(PROBES_FILE.read_text(encoding="utf-8")) if PROBES_FILE.exists() else []
    cand_by_id = {c["id"]: c for c in candidates}

    phn_text = read_phn_from_path(scene_path)
    assignments = parse_scene_my_assignments(phn_text)

    probe_ids = sorted(
        {
            k[len("probe_") : -len("_ok")]
            for k in assignments
            if k.startswith("probe_") and k.endswith("_ok")
        }
        | {
            k[len("probe_") :]
            for k in assignments
            if k.startswith("probe_") and not k.endswith("_ok") and not k.endswith("_str")
        }
    )
    if not probe_ids:
        print("No Scene.my.probe_* results found in scene.", file=sys.stderr)
        return 1

    reg = load_registry()
    verified = set(reg.get("verified", []))
    rejected = set(reg.get("rejected", []))

    rows: list[tuple[str, str, str, str, str, str]] = []
    for pid in probe_ids:
        cand = cand_by_id.get(pid, {})
        token = cand.get("token", pid)
        category = cand.get("category", "-")
        ok_raw = assignments.get(f"probe_{pid}_ok", "0")
        val_raw = assignments.get(f"probe_{pid}", "<missing>")
        str_raw = assignments.get(f"probe_{pid}_str", "")

        if ok_raw == "1":
            if val_raw in ('"NOT_RUN"', "undefined") or (val_raw == "<missing>" and str_raw != '"void"'):
                status = "FAIL"
                val_type = "undefined" if val_raw == "undefined" else "error"
                rejected.add(token)
                verified.discard(token)
            elif val_raw == "<missing>" and str_raw == '"void"':
                status = "WORK"
                val_type = "void"
                val_raw = "void"
                verified.add(token)
                rejected.discard(token)
            else:
                status = "WORK"
                val_type = infer_thyme_type(val_raw)
                verified.add(token)
                rejected.discard(token)
        elif ok_raw == "-1":
            status = "FAIL"
            val_type = "error"
            rejected.add(token)
            verified.discard(token)
        else:
            status = "NOT_RUN"
            val_type = "-"

        rows.append((pid, token, category, status, val_type, val_raw[:48]))

    # Print formatted table
    headers = ("ID", "Token", "Category", "Status", "Type", "Value")
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print(fmt.format(*r))

    reg["verified"] = sorted(verified)
    reg["rejected"] = sorted(rejected)
    save_registry(reg)
    worked = sum(1 for r in rows if r[3] == "WORK")
    failed = sum(1 for r in rows if r[3] == "FAIL")
    not_run = sum(1 for r in rows if r[3] == "NOT_RUN")
    print(f"\nUpdated {VERIFIED_FILE.name}: +{worked} WORK, +{failed} FAIL, {not_run} NOT_RUN.")
    return 0


def cmd_bench(_args: argparse.Namespace) -> int:
    # Build a 50-element test array for list indexing inside 40x50 = 2000 nested iterations
    arr_literal = "[" + ", ".join(str(i) for i in range(50)) + "]"
    scene_my_lines = [
        "Scene.my.bench_active := 0;",
        f"Scene.my.bench_arr := {arr_literal};",
        "Scene.my.bench_list_ok := 0;",
        "Scene.my.bench_list_n := 0;",
        "Scene.my.bench_list_sum := 0;",
        "Scene.my.bench_list_dt := 0.0;",
        "Scene.my.bench_obj_ok := 0;",
        "Scene.my.bench_obj_n := 0;",
        "Scene.my.bench_obj_acc := 0;",
        "Scene.my.bench_obj_dt := 0.0;",
        "Scene.my.bench_eval_ok := 0;",
        "Scene.my.bench_eval_n := 0;",
        "Scene.my.bench_eval_dt := 0.0;",
        "Scene.my.bench_raw_ok := 0;",
        "Scene.my.bench_raw_n := 0;",
        "Scene.my.bench_raw_dt := 0.0;",
        "Scene.my.bench_dyn0 := 1;",
    ]

    # Mode 1: List indexing (40 x 50 = 2000 iterations)
    list_post = """(e)=>{
        (scene.my.bench_list_ok == 0 || scene.my.bench_active == 1) ? {
            scene.my.bench_list_ok = -1;
            _t0 := time;
            _n := 0;
            _acc := 0;
            for(40, (a)=>{
                for(50, (b)=>{
                    _acc = _acc + scene.my.bench_arr(b);
                    _n = _n + 1
                })
            });
            scene.my.bench_list_dt = time - _t0;
            scene.my.bench_list_n = _n;
            scene.my.bench_list_sum = _acc;
            scene.my.bench_list_ok = 1;
            text = "1. List Index (40x50)\\n" + (scene.my.bench_active == 1 ? "[ACTIVE] " : "[CLICK] ") + "n=" + scene.my.bench_list_n + " sum=" + scene.my.bench_list_sum
        } : {}
    }"""

    # Mode 2: Object properties (40 x 50 = 2000 iterations reading/writing entity & scene.my properties)
    obj_post = """(e)=>{
        (scene.my.bench_obj_ok == 0 || scene.my.bench_active == 2) ? {
            scene.my.bench_obj_acc = 0;
            scene.my.bench_obj_ok = -1;
            _t0 := time;
            _n := 0;
            for(40, (a)=>{
                for(50, (b)=>{
                    scene.my.bench_obj_acc = scene.my.bench_obj_acc + pos(0) + restitution;
                    _n = _n + 1
                })
            });
            scene.my.bench_obj_dt = time - _t0;
            scene.my.bench_obj_n = _n;
            scene.my.bench_obj_ok = 1;
            text = "2. Object Props (40x50)\\n" + (scene.my.bench_active == 2 ? "[ACTIVE] " : "[CLICK] ") + "n=" + scene.my.bench_obj_n + " acc=" + scene.my.bench_obj_acc
        } : {}
    }"""

    # Mode 3: eval() dynamic variables (isolated; 40 x 50 = 2000 iterations)
    eval_post = """(e)=>{
        (scene.my.bench_eval_ok == 0 || scene.my.bench_active == 3) ? {
            scene.my.bench_eval_ok = -1;
            _t0 := time;
            _n := 0;
            for(40, (a)=>{
                for(50, (b)=>{
                    eval("scene.my.bench_dyn0 = scene.my.bench_dyn0 + 1");
                    _n = _n + 1
                })
            });
            scene.my.bench_eval_dt = time - _t0;
            scene.my.bench_eval_n = _n;
            scene.my.bench_eval_ok = 1;
            text = "3. eval() DynVar (40x50)\\n" + (scene.my.bench_active == 3 ? "[ACTIVE] " : "[CLICK] ") + "n=" + scene.my.bench_eval_n
        } : {
            scene.my.bench_eval_ok == -1 ? {
                text = "3. eval() DynVar\\nERR (unsupported)"
            } : {}
        }
    }"""

    # Mode 4: Flat for(2000, ...) control to observe recursion depth / skipped iterations
    raw_post = """(e)=>{
        (scene.my.bench_raw_ok == 0 || scene.my.bench_active == 4) ? {
            scene.my.bench_raw_ok = -1;
            _t0 := time;
            _n := 0;
            for(2000, (k)=>{
                _n = _n + 1
            });
            scene.my.bench_raw_dt = time - _t0;
            scene.my.bench_raw_n = _n;
            scene.my.bench_raw_ok = 1;
            text = "4. Flat for(2000) Check\\n" + (scene.my.bench_active == 4 ? "[ACTIVE] " : "[CLICK] ") + "ran=" + scene.my.bench_raw_n + "/2000"
        } : {}
    }"""

    def click_toggle(mode: int) -> str:
        return f"(e)=>{{ scene.my.bench_active = (scene.my.bench_active == {mode}) ? 0 : {mode} }}"

    boxes = [
        format_add_box(201, (-5.5, 3.0), (8.0, 2.2), (0.15, 0.30, 0.22, 1.0), "1. List Index (click)", 0.38, list_post, click_toggle(1)),
        format_add_box(202, (-5.5, 0.3), (8.0, 2.2), (0.15, 0.24, 0.36, 1.0), "2. Object Props (click)", 0.38, obj_post, click_toggle(2)),
        format_add_box(203, (-5.5, -2.4), (8.0, 2.2), (0.34, 0.18, 0.20, 1.0), "3. eval() DynVar (click)", 0.38, eval_post, click_toggle(3)),
        format_add_box(204, (-5.5, -5.1), (8.0, 2.2), (0.28, 0.24, 0.14, 1.0), "4. Flat for(2000) (click)", 0.38, raw_post, click_toggle(4)),
    ]

    summary_post = """(e)=>{
        text = "BENCHMARK (mode=" + scene.my.bench_active + ", t=" + time + ")\\n" +
            "1. List(40x50): ok=" + scene.my.bench_list_ok + " n=" + scene.my.bench_list_n + "\\n" +
            "2. Obj(40x50):  ok=" + scene.my.bench_obj_ok + " n=" + scene.my.bench_obj_n + "\\n" +
            "3. eval(40x50): ok=" + scene.my.bench_eval_ok + " n=" + scene.my.bench_eval_n + "\\n" +
            "4. flat(2000):  ok=" + scene.my.bench_raw_ok + " n=" + scene.my.bench_raw_n + "\\n" +
            "Click a box to run per-tick & watch HUD FPS."
    }"""
    boxes.append(
        format_add_box(299, (4.5, -1.0), (10.0, 10.5), (0.10, 0.12, 0.16, 1.0), "BENCHMARK SUMMARY", 0.36, summary_post)
    )

    header = build_minimal_phn_header(scene_my_lines, "Thyme 2000-Iter Benchmark", pan=(-0.5, -1.0), zoom=32.0)
    out_phz = DIST_DIR / "bench_scene.phz"
    write_phz(out_phz, header + "\n".join(boxes))
    print(f"Wrote {out_phz.relative_to(ROOT)} (4 benchmark modes + live summary).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Real-Algodoo Thyme Probe, Benchmark & Linter CLI")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="Re-scan src/*.thyme and sync verified_thyme.json")
    sub.add_parser("probe", help="Generate dist/probe_scene.phz from probes/candidates.json")
    hp = sub.add_parser("harvest", help="Extract probe results from a saved .phz/.phn into verified_thyme.json")
    hp.add_argument("scene", help="Path to saved Algodoo .phz or .phn file")
    sub.add_parser("bench", help="Generate dist/bench_scene.phz for 2000-iter throughput benchmarks")
    sub.add_parser("lint", help="Strictly validate src/*.thyme against verified_thyme.json")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    dispatch = {
        "seed": cmd_seed,
        "probe": cmd_probe,
        "harvest": cmd_harvest,
        "bench": cmd_bench,
        "lint": cmd_lint,
    }
    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
