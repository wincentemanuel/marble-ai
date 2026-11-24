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
- Harvested inside `Scene.addBox` `postStep` (`dist/saved_probe_scene.phz`):
  - Truncation: `x - (x % 1)` works (`3.75 -> 3.0`, `-3.75 -> -3.0`; truncates toward zero, add offset for negatives).
  - Entity IDs: `entityID`, `geomID` work (`685`, `516`).
  - Physics properties: `adhesion`, `attraction`, `attractionType`, `heteroCollide` are readable (`0.0`, `0.0`, `2`, `false`).
  - Timing & logging: `Sim.time` (`0.016666668`), `Sim.tick` (`1`), `print`, `System.print`, `Console.print` (return `void`) all work.
  - Note on Thyme error handling: failed expressions leave LHS unchanged (`"NOT_RUN"`) or return `undefined`, and subsequent top-level statements still execute.

- 0-arg `()=>` lambdas in `.phn` files: **BANNED** (`Scene.my.fn := ()=>{ ... }` loads as `undefined` in `.phn`). Use 1-arg `(u)=>{ ... }` for helpers or `{ ... }` for `.phn` top-level `Scene.my.* :=`.

## Verified MISSING (do not use)
()=>, len, floor, abs, round, sqrt (global), foldl, fold, map, toString, str, Math.floor,
int, math.round, math.floor, math.ceil, math.abs,
Scene.entities, Sim.entities, Scene.addLaser, hitPos, length (on Box),
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

## Planned simplifications & V0.2 / V0.3 / Bellman-Ford budget
- **V0.2** (`9d1e12c`, retconned from V5.2): True floor `flr`, auto-init `runSetup`, shared `4 * radius` grounded-cell graph (`cells`, `wA`/`wB`, `fA`/`fB`/`fX`/`fVx`), incremental double-buffered Bellman-Ford (12 edges/tick rolling `bfCursor`, `1.25x` victim-edge weighting), and `departureVx` fall execution.
- **V0.3** (`c5ce197`, `c1e1639`): Slope-aware grounding + ramp climb, directed Frontier Bellman-Ford exploration, `failCount` penalties, native `Scene.my` header export + chunked auto-init, and snapshot export/preload.
- **V0.4** (`4ae2ad2`): Ban 0-arg `()=>`; eliminate 51°–69° wall/ramp overlap (`_ny > 0.55` ground, `|_nx| > 0.62` wall) + verified `adhesion = 2.0` uphill grip (0.0 elsewhere); edge cooldowns (`wCool`/`fCool` = `600` ticks on `90`-tick timeout or `ppCount >= 2`); `MICRO_BACKOFF` (`24`-tick stall -> `18`-tick runway + `1.35x` surge); `EXPLORE_BREAKOUT` (`240`-tick macro loiter -> `180`-tick frontier escape); diagonal & ledge-aware frontier scanning.
- **V0.5** (`ced6d5a`): Per-cell visit fatigue `cHeat` (`+0.25`/tick at `kCell` capped `120.0`, rolling `12`-cell/tick decay by `0.15`, `cHeat * 0.35` penalty in `bfRelax`/`frRelax`); `PASSIVE_MARBLE` pure Box2D coasting (`friction = 0.0`, `restitution = 0.500`, `adhesion = 0.0`, no `vel`/`angvel` writes for `180` ticks with early exit on fresh `< 12.0` cell after `30` ticks, valid goal path, or idle `< 0.25` for `45` ticks); `WINDUP_RUN` tactical ramp wind-up (`35`-tick retreat at `2.6 m/s`, `65`-tick `5.6 m/s` uphill charge with `adhesion = 2.0`, cooldown + `PASSIVE_MARBLE` fallback on failure).
- **V0.6** (`090fdab`): Long-memory `cHeat` (`+0.45`/tick capped `200.0`, `8`-cell/tick rolling decay by `0.04`, `cHeat * 0.85` cost multiplier); outgoing edge-usage counters `wUse`/`fUse` (incremented on commit/traversal, capped `10`, `+ useCount * 14.0` cost penalty in `bfRelax`/`frRelax` + active-hop commitment lock); longer `PASSIVE_MARBLE` (`480` ticks default, `540` ticks on familiarity trigger; `150`-tick minimum coasting window; requires `3` consecutive grounded `< 8.0` cells `passiveFreshStreak >= 3`, unless idle `< 0.20` for `60` ticks or within `2.0 m` same-floor `|dy| < 1.2` of a victim; auto-triggers on `curCellHeat >= 28.0` for `> 90` ticks without new cells); explicit `hudThought` familiarity HUD callout (`V0.6 | ...`) and `wUse`/`fUse` snapshot export/preload support.
- **V0.7** (`6fe316c`): Guard `getUse`, `hopCool`, `bfRelax`, `frRelax`, and `cCost`/`fCost` list lookups with braced `{ ... }` blocks and `< 0`/bounds checks so `hudUse` never evaluates `error`; calibrate familiarity heat (`+6.0` entry stamp on grounded cell change via `prevHeatCell` + `+1.0`/tick occupancy capped `200.0`, rolling `0.02` decay across `8` cells/tick, threshold `curCellHeat >= 15.0`); extend `PASSIVE_MARBLE` (`1080`t default, `1200`t on familiarity/breakout, `420`t min coasting window, `6` consecutive grounded `< 5.0` cells before exit, only fast-waking on `_nearVictim` `< 2.5 m` same floor or dead stop `< 0.15` for `90`t; triggers proactively at `45`t in familiar territory); update HUD header/callouts to **V0.7**.
- **V0.8** (`39b60ff`): Eliminate overtime slowdown via sparse `cHeat` updates (`setAt` only on entry `+6.0`, every `10` dwell ticks `+3.0`, and `1` cell decayed by `0.08` every `4` ticks), removing redundant `frStep`/`frScanStep`, throttling `bfStep` to every 2nd tick (`bfTickToggle`, two `for(<=6)` sub-batches), setting `cs = 5.0 * _r`, and expanding nested `20`-chunk helpers for `MAX_CELLS = 220`, `MAX_WALK = 320`, `MAX_FALL = 240`. Clean two-mode split: `PASSIVE_EXPLORE` (default when `cHop == NONE` / `cCost >= 90000` or `passiveBreakoutTimer > 0`, with `35`t `UNSTICK_NUDGE` after `75`t `< 0.18` dead-stop) vs `ACTIVE_HUNTER` (engages immediately when a target route exists or `_nearVictim`, dropping into `300`t `PASSIVE_EXPLORE` breakout on `90`t timeout, `ppCount >= 2` ping-pong, ramp/micro stall, or `60`t `cHeat >= 18.0` familiar loop). Updated HUD/auto-init/export to **V0.8**.
- **V0.9**: Fix live `targetCell` tracking (`1`-tick victim ground hysteresis `_minGnd = 1`, per-victim `this._lastGx`/`this._lastGy`/`this._lastCell` & isolated `this._v*` telemetry, deduplicated `vCells` via `addVCell`, continuous living-victim auction without spawn latching); eliminate overtime slowdown (`kPrevGx`/`kPrevGy` + `kHeatIdx` same-cell fast paths skipping redundant `findCell` & `recTick` scans, event-driven `bfDirty` / `bfResweep` sleeping Bellman-Ford on convergence, and 10Hz HUD formatting + Text Box update every `6` ticks via `hudTick`/`hudVer`); tame bounciness (`PASSIVE_EXPLORE` `restitution = 0.18`, `ACTIVE_HUNTER` `restitution = 0.12`); reliable `_directStrike` (`dist < 7.5 && |dy| < 3.5` or `kCell == targetCell` interrupting passive/breakout into `DIRECT_CHASE` at `4.4 m/s`), same-cell graph fix (`_graphCost < 90000`), and `ACTIVE_PATROL` cycle (`180`t active drive toward highest-elevation/lowest-heat cells after `> 300`t passive stagnation, alternating with `240`t `PASSIVE_EXPLORE`). Updated HUD and labels to **V0.9**.
- Target Bellman-Ford per-tick relaxation budget: 12 edge relaxations per tick (chunked `for(20, ...)` helpers), keeping recursion depth well below the ~66-level limit.
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