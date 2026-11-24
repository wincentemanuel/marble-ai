# Marble killer AI (Algodoo / Thyme)

Last updated: 2026-11-25

## Rules for the agent
- Edit only files in src/. Never edit dist/ or hand-edit script bodies in the .phn; run build.py.
- Use only features under "Verified to WORK". Anything else must be probed first (see below).
- Commit before and after each change. One behavior change per commit.
- Never reset the scene: learned edges live in scene.my and are lost on reset.
- Never paste partial snippets for the user to merge by hand. Give complete functions.

## Handling features outside "Verified"
1. Never put an unverified feature into src/. Write it as a probe first.
2. A probe is one console line the user can paste, with the expected output stated.
   Example: `Math.floor(2.7)` should print 2; "Function call applied to non-function" means missing.
3. Wait for the user's result. Do not assume it works because it exists in another language,
   in documentation, in a decompiled grammar, or in another Algodoo version.
4. Record the result here (Verified WORK with exact syntax, or Verified MISSING). Commit that note alone.
5. Test inside a marble script too if scope or stack could matter (console and postStep differ).
6. Online docs, community code and the posted grammar are hints for what to probe, not proof.

## Verified to WORK (console unless noted)
- Braced lambdas: (a)=>{ a + 1 }
- `%` on floats; list indexing l(i); list append `++`; "text" + number
- `:=` creates a local that vanishes at the closing }. Persistent state: scene.my.<name> or this.<name>.
- Ternary with BRACED branches: cond ? { ... } : { ... }
- Math.sqrt(x), math.sqrt(x)
- Console-pasted functions on scene.my can be called from marble scripts.
- `time`: running simulation clock in seconds (3.95 -> 8.03 between readings). Use for timeouts.
- `for(n, (k)=>{ ... })`: runs k = 0..n-1. Recursive internally (see limits).
- Nested for: for(20,(a)=>{ for(20,(b)=>{...}) }) ran 400 iterations, no overflow (console).
  List index for a 2D loop: a * width + b.
- `god` exists (object). Contents not yet explored.

## Verified MISSING (do not use)
len, floor, abs, round, sqrt (global), foldl, fold, map, toString, str, Math.floor,
list.length, list.size, scene.my["key"] indexing/assignment, gameTime,
while, repeat, loop, foreach, C-style for(;;), 3-arg and 4-arg for.
- floor substitute: v - v % 1 (positive v only; add an offset first).
- Bool in string concat: use (cond ? 1 : 0).

## Limits
- Call depth is about 66 levels, and every ternary and { } block counts as a level.
- for(n, ...) is recursive: n above ~60 silently skips the FIRST iterations (warning only).
  Safe single loop: n <= 50. Nest two loops for more (each level adds only its own depth).
- Floats are 32-bit. Never pack pair keys into one big number.
- Algodoo exports rewrite floats (0.6 becomes 0.60000002). They are identical.

## UNTESTED (probe next)
- Nested for inside a marble script postStep (put at top of killer postStep, read scene.my.lt, expect 400,
  watch frame rate).
- Frame-rate cost of a few hundred loop iterations per tick at 60 Hz.
- Whether `time` pauses with the sim and resets on scene reload.
- Whether Thyme can write files (Scene.fileExists, File, Scene.log are unprobed).
- Contents of `god` (probe members one at a time).

## Physics facts measured on this map
- e.normal in onCollide points from the marble TOWARD the touched object:
  floor under marble: normal(1) about -1; wall on the right: normal(0) about +0.7.
- onCollide does not fire every tick while rolling. Use postStep for ground/air detection.
- Free fall: vel(1) changes about -0.13 per tick; on a flat floor about 0.
  Airborne test: (vy - pvy) < -0.1.
- Cell size cs = 4.0; floor "row" = last three digits of key(px, py).
- Spinner elevator: recorded as a rising "fall" edge (landing row > source row) = plan type 4.

## Architecture
- Victim postStep: records drop points d0..d3, bids as target.
- recTick (shared): airborne counter, fall edges (fA,fB,fX, deduped by source + X within 0.8),
  directional walk edges (wA,wB). Cap 120 per list.
- planStep: breadth-first search over edges, one edge per call, 4 calls per tick.
  planType: 0 walk, 1 drop, 3 same row, 4 lift, -1 none.
- Killer states by color: teal idle, red chase, orange hole/plan, purple scan,
  cyan drop brake, pink back-off, white settle.
- Sensors: stuck (20 ticks), trapped (150 ticks), alignment timeout (300 ticks), atLift gate.
- Debug: scene.my.dump (state string every 5 ticks) and scene.my.ev0..ev2 (last 3 give-up events).

## Planned simplifications (once nested-for is verified inside postStep)
1. Replace hasW, hasF, findPv, sfStep with nested-loop full-list scans.
2. Run the whole planner search in one call, triggered when the killer's row changes or every ~0.5 s.
   Raise the 40-cell planner cap.
3. Replace tick-counter timeouts with `time`-based ones.
4. Per-edge failCount: a hop that triggers stuck/aligntimeout twice is skipped by the planner.

## Known open problems
- Killer overshoots or oscillates at the lift entry (recorded X is where the marble left the ground).
- Inverse gravity, teleporters, launchers, conveyors are unhandled or untested.
  Teleporter idea: detect a position jump of more than N units in one tick and record a transport edge.
  Inverse gravity would need gravity direction read from the scene and every vertical test flipped.

## Reference material (UNVERIFIED)
- A decompiled Thyme grammar was posted 2026-11-25. It lacks ?: and ++ (both verified to work)
  and allows scene.my["k"]= (verified to fail). Use only to choose what to probe.
- A third-party Thyme IDE reports its own parser errors (for example "Missing ';'"). Those describe the
  IDE, not Algodoo.