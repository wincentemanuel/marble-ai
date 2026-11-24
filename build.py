import re, sys, pathlib, zipfile

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

def main():
    text = read_scene_phn()
    text = replace_hook(text, KILLER_ID, "postStep", read("killer_poststep.thyme"))
    text = replace_hook(text, KILLER_ID, "onCollide", read("killer_oncollide.thyme"))
    text = replace_hook(text, VICTIM_ID, "postStep", read("victim_poststep.thyme"))
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    (out / "scene_built.phn").write_text(text, encoding="utf-8")
    (out / "setup.txt").write_text(read("setup.thyme"), encoding="utf-8")
    print("wrote dist/scene_built.phn and dist/setup.txt")

if __name__ == "__main__":
    sys.exit(main())