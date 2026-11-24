import argparse, json, re, subprocess, sys, pathlib, zipfile

ROOT = pathlib.Path(__file__).parent
PHN = ROOT / "scene" / "Magenta Marathon botted.phn"
PHZ = ROOT / "scene" / "Magenta Marathon botted.phz"
KILLER_ID, VICTIM_ID = "439", "438"

def read(p):
    return (ROOT / "src" / p).read_text(encoding="utf-8").strip()

def match_end(text, start):
    """index just after the } matching the { at/after start."""
    i = text.index("{", start)
    depth = 0
    in_str = False
    while i < len(text):
        c = text[i]
        if c == '"':
            in_str = not in_str
        elif not in_str:
            if c == "{": depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    raise ValueError("unbalanced braces")

def replace_hook(text, entity_id, hook, new_body):
    m = re.search(r"entityID := " + entity_id + r";", text)
    if not m:
        raise ValueError(f"entity {entity_id} not found")
    # object block runs from the previous Scene.add... to the next one
    obj_start = text.rfind("Scene.add", 0, m.start())
    nxt = text.find("Scene.add", m.end())
    obj_end = nxt if nxt != -1 else len(text)
    block = text[obj_start:obj_end]
    h = re.search(hook + r" := ", block)
    if not h:
        raise ValueError(f"{hook} not found on {entity_id}")
    end = match_end(block, h.end())
    block = block[:h.end()] + new_body + block[end:]
    return text[:obj_start] + block + text[obj_end:]

def read_scene_phn():
    """Load scene.phn from an unpacked .phn if present, otherwise from the .phz archive."""
    if PHN.exists():
        return PHN.read_text(encoding="utf-8")
    with zipfile.ZipFile(PHZ) as zf:
        return zf.read("scene.phn").decode("utf-8")

def apply_preload(setup_code, preload_path):
    """Bake pre-learned graph memory from a JSON or Thyme snapshot into setup_code."""
    p = pathlib.Path(preload_path)
    if not p.exists():
        raise FileNotFoundError(f"Preload snapshot not found: {p}")
    if p.suffix.lower() == ".json":
        snap = json.loads(p.read_text(encoding="utf-8"))
        n_cells = min(int(snap.get("nCells", len(snap.get("cells", [])))), 220)
        cells = list(snap.get("cells", []))[:n_cells]
        c_block_l = (list(snap.get("cBlockL", [])) + [0] * n_cells)[:n_cells]
        c_block_r = (list(snap.get("cBlockR", [])) + [0] * n_cells)[:n_cells]
        c_ramp = (list(snap.get("cRamp", [])) + [0] * n_cells)[:n_cells]
        c_heat = (list(snap.get("cHeat", [])) + [0.0] * n_cells)[:n_cells]
        w = snap.get("walk", {})
        n_walk = min(int(w.get("nWalk", len(w.get("wA", [])))), 320)
        w_a = list(w.get("wA", []))[:n_walk]
        w_b = list(w.get("wB", []))[:n_walk]
        w_by_k = (list(w.get("wByK", [])) + [1] * n_walk)[:n_walk]
        w_fail = (list(w.get("wFail", [])) + [0] * n_walk)[:n_walk]
        w_use = (list(w.get("wUse", [])) + [0] * n_walk)[:n_walk]
        f = snap.get("fall", {})
        n_fall = min(int(f.get("nFall", len(f.get("fA", [])))), 240)
        f_a = list(f.get("fA", []))[:n_fall]
        f_b = list(f.get("fB", []))[:n_fall]
        f_x = (list(f.get("fX", [])) + [0.0] * n_fall)[:n_fall]
        f_vx = (list(f.get("fVx", [])) + [0.0] * n_fall)[:n_fall]
        f_by_k = (list(f.get("fByK", [])) + [1] * n_fall)[:n_fall]
        f_fail = (list(f.get("fFail", [])) + [0] * n_fall)[:n_fall]
        f_use = (list(f.get("fUse", [])) + [0] * n_fall)[:n_fall]
        preload_block = "\n".join([
            f"scene.my.cs = {snap.get('cs', 1.25)};",
            f"scene.my.nCells = {n_cells}; scene.my.cells = {cells}; scene.my.cBlockL = {c_block_l}; scene.my.cBlockR = {c_block_r}; scene.my.cRamp = {c_ramp}; scene.my.cHeat = {c_heat};",
            f"scene.my.nWalk = {n_walk}; scene.my.wA = {w_a}; scene.my.wB = {w_b}; scene.my.wByK = {w_by_k}; scene.my.wFail = {w_fail}; scene.my.wCool = {[0]*n_walk}; scene.my.wUse = {w_use};",
            f"scene.my.nFall = {n_fall}; scene.my.fA = {f_a}; scene.my.fB = {f_b}; scene.my.fX = {f_x}; scene.my.fVx = {f_vx}; scene.my.fByK = {f_by_k}; scene.my.fFail = {f_fail}; scene.my.fCool = {[0]*n_fall}; scene.my.fUse = {f_use};",
        ])
    else:
        preload_block = p.read_text(encoding="utf-8").strip()

    # Insert right before `scene.my.v09Setup = true` so preloaded lists override empty init defaults
    marker = "scene.my.v09Setup = true"
    if marker in setup_code:
        return setup_code.replace(marker, preload_block + "\n" + marker, 1)
    return setup_code + "\n" + preload_block

def strip_thyme_comments(code):
    """Strip // line comments outside string literals so embedded blocks never collapse lines."""
    out = []
    i = 0
    n = len(code)
    in_str = False
    while i < n:
        c = code[i]
        if c == "\\" and in_str and i + 1 < n:
            out.append(c)
            out.append(code[i + 1])
            i += 2
            continue
        if c == '"':
            in_str = not in_str
            out.append(c)
            i += 1
            continue
        if not in_str and c == "/" and i + 1 < n and code[i + 1] == "/":
            while i < n and code[i] != "\n":
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)

def split_top_statements(code):
    """Split Thyme code at top-level semicolons outside strings and nested brackets."""
    stmts = []
    buf = []
    depth = 0
    in_str = False
    i = 0
    n = len(code)
    while i < n:
        c = code[i]
        if c == "\\" and in_str and i + 1 < n:
            buf.append(c)
            buf.append(code[i + 1])
            i += 2
            continue
        if c == '"':
            in_str = not in_str
            buf.append(c)
            i += 1
            continue
        if not in_str:
            if c in "{[(":
                depth += 1
            elif c in "}])":
                depth -= 1
            elif c == ";" and depth == 0:
                s = "".join(buf).strip()
                if s:
                    stmts.append(s)
                buf = []
                i += 1
                continue
        buf.append(c)
        i += 1
    s = "".join(buf).strip()
    if s:
        stmts.append(s)
    return stmts

def chunk_setup_body(setup_code, leaf_size=10, branch_size=5):
    """Group setup statements into <=10-stmt balanced ternary chunks so ; depth stays <= 20."""
    stmts = split_top_statements(strip_thyme_comments(setup_code))
    leaves = []
    for i in range(0, len(stmts), leaf_size):
        chunk = ";\n".join(stmts[i : i + leaf_size])
        leaves.append("1 == 1 ? {\n" + chunk + "\n} : {}")
    if len(leaves) <= branch_size:
        return ";\n".join(leaves)
    branches = []
    for i in range(0, len(leaves), branch_size):
        chunk = ";\n".join(leaves[i : i + branch_size])
        branches.append("1 == 1 ? {\n" + chunk + "\n} : {}")
    return ";\n".join(branches)

def strip_stale_scene_my(header, keys_to_replace):
    """Remove old Scene.my.<name> := ...; assignments from .phn header for keys redefined by setup."""
    out = []
    i = 0
    n = len(header)
    pattern = re.compile(r"Scene\.my\.(\w+)\s*:=\s*")
    while i < n:
        m = pattern.search(header, i)
        if not m:
            out.append(header[i:])
            break
        out.append(header[i : m.start()])
        name = m.group(1)
        j = m.end()
        depth = 0
        in_str = False
        while j < n:
            c = header[j]
            if c == "\\" and in_str and j + 1 < n:
                j += 2
                continue
            if c == '"':
                in_str = not in_str
            elif not in_str:
                if c in "{[(":
                    depth += 1
                elif c in "}])":
                    depth -= 1
                elif c == ";" and depth == 0:
                    j += 1
                    break
            j += 1
        if name in keys_to_replace:
            # Skip optional trailing newline after removed statement
            if j < n and header[j] == "\n":
                j += 1
        else:
            out.append(header[m.start() : j])
        i = j
    return "".join(out)

def inject_auto_setup(text, setup_code):
    """Pre-seed native .phn Scene.my.* entries and a chunked runSetup block before FileInfo ->."""
    stmts = split_top_statements(strip_thyme_comments(setup_code))
    native_lines = []
    redefined_keys = {"v09Setup", "hudText", "runSetup"}
    for s in stmts:
        m = re.match(r"^scene\.my\.(\w+)\s*=\s*(.+)$", s, flags=re.DOTALL)
        if m:
            k, rhs = m.group(1), m.group(2).strip()
            if k in ("v09Setup", "hudText"):
                continue
            redefined_keys.add(k)
            native_lines.append(f"Scene.my.{k} := {rhs};")

    chunked = chunk_setup_body(setup_code)
    indented = "\n".join("    " + line if line else "" for line in chunked.splitlines())
    setup_block = (
        "\n".join(native_lines) + "\n"
        "Scene.my.v09Setup := false;\n"
        'Scene.my.hudText := "V0.9 | Ready (press Play)";\n'
        "Scene.my.runSetup := {\n"
        f"{indented}\n"
        "};\n"
    )
    marker = "FileInfo ->"
    idx = text.find(marker)
    if idx == -1:
        raise ValueError("FileInfo -> marker not found in scene.phn")
    clean_header = strip_stale_scene_my(text[:idx], redefined_keys)
    return clean_header + setup_block + text[idx:]

def inject_hud_box(text, setup_code):
    """Inject a non-solid debug Text Box HUD that auto-runs chunked setup.thyme in postStep on tick 1."""
    if "entityID := 99901;" in text:
        return text
    chunked = chunk_setup_body(setup_code)
    indented_body = "\n".join("            " + line if line else "" for line in chunked.splitlines())
    hud_box = f"""Scene.addBox {{
    inertiaMultiplier := 1.0000000;
    resources := [];
    timeToLive := +inf;
    textureClamped := [false, false];
    adhesion := 0.0000000;
    attractionType := 2;
    attraction := 0.0000000;
    textScale := 0.42000000;
    texture := "";
    update := (e)=>{{}};
    vel := [0.0000000, 0.0000000];
    restitution := 0.50000000;
    onCollide := (e)=>{{}};
    killer := false;
    materialVelocity := 0.0000000;
    immortal := true;
    ruler := false;
    textColor := [0.95000000, 0.98000000, 1.0000000, 1.0000000];
    textConstrained := true;
    textFontSize := 24.000000;
    textFont := "Verdana";
    collideSet := 0;
    drawBorder := true;
    reflectiveness := 1.0000000;
    size := [12.500000, 4.0000000];
    friction := 0.50000000;
    entityID := 99901;
    onClick := (e)=>{{}};
    color := [0.050000001, 0.080000000, 0.12000000, 0.80000001];
    collideWater := false;
    onSpawn := (e)=>{{}};
    materialName := "";
    onHitByLaser := (e)=>{{}};
    pos := [172.63837, 23.500000];
    onDie := (e)=>{{}};
    density := 2.0000000;
    angvel := 0.0000000;
    heteroCollide := false;
    glued := true;
    onKey := (e)=>{{}};
    postStep := (e)=>{{
        scene.my.v09Setup != true ? {{
{indented_body};
            scene.my.v09Setup = true
        }} : {{}};
        this._hudInit != true ? {{
            this._hudInit = true;
            this._hudVer = -1
        }} : {{}};
        this._hudVer != scene.my.hudVer ? {{
            this._hudVer = scene.my.hudVer;
            text = scene.my.hudText
        }} : {{}};
        pos = [scene.my.seekerPos(0), scene.my.seekerPos(1) + 4.5000000]
    }};
    text := "V0.9 | Ready (press Play)";
    opaqueBorders := true;
    geomID := 99901;
    body := 0;
    edgeBlur := 0.0000000;
    angle := 0.0000000;
    zDepth := 999.00000;
    layer := 0
}};
"""
    marker = "Scene.add"
    idx = text.find(marker)
    if idx == -1:
        raise ValueError("No Scene.add block found for HUD injection")
    return text[:idx] + hud_box + text[idx:]

def run_lint():
    """Run tools/thyme_cli.py lint before packaging."""
    cli = ROOT / "tools" / "thyme_cli.py"
    res = subprocess.run([sys.executable, str(cli), "lint"], check=False)
    return res.returncode

def main(argv=None):
    parser = argparse.ArgumentParser(description="Build dist/scene_built.phn and dist/setup.txt from src/.")
    parser.add_argument("--force", action="store_true", help="Bypass thyme_cli.py lint (for experimental probing only).")
    parser.add_argument("--preload", help="Path to JSON or Thyme graph snapshot exported by tools/export_graph.py.")
    args = parser.parse_args(argv)

    if args.force:
        print("WARNING: --force specified; bypassing thyme_cli.py lint.")
    else:
        rc = run_lint()
        if rc != 0:
            print("Build aborted due to lint errors. Re-run with --force to bypass during experimental probing.", file=sys.stderr)
            return rc

    setup_code = read("setup.thyme")
    if args.preload:
        setup_code = apply_preload(setup_code, args.preload)
        print(f"Preloaded graph snapshot from {args.preload}")
    text = read_scene_phn()
    text = replace_hook(text, KILLER_ID, "postStep", read("killer_poststep.thyme"))
    text = replace_hook(text, KILLER_ID, "onCollide", read("killer_oncollide.thyme"))
    text = replace_hook(text, VICTIM_ID, "postStep", read("victim_poststep.thyme"))
    text = inject_auto_setup(text, setup_code)
    text = inject_hud_box(text, setup_code)
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    (out / "scene_built.phn").write_text(text, encoding="utf-8")
    (out / "setup.txt").write_text(setup_code, encoding="utf-8")
    print("wrote dist/scene_built.phn and dist/setup.txt")
    return 0

if __name__ == "__main__":
    sys.exit(main())