# Project: Autonomous Killer Marble AI for Algodoo (`wincentemanuel/marble-ai`)

## 1. First Action (Read Before Editing)
Inspect the existing codebase before making changes:
1. Read `NOTES.md` for design decisions, V0.2/V0.3 graph specs, and open TODOs.
2. Read `build.py` to see how `src/*.thyme` scripts are injected into `scene/Magenta Marathon botted.phz` to produce `dist/scene_built.phn` and `dist/setup.txt`.
3. Read `src/setup.thyme`, `src/killer_poststep.thyme`, `src/killer_oncollide.thyme`, and `src/victim_poststep.thyme` to see the exact current implementation.

## 2. Repository Structure
- `NOTES.md`: Architecture notes and iteration history.
- `build.py`: Python build pipeline packaging Thyme scripts into the Algodoo scene.
- `scene/Magenta Marathon botted.phz`: Base Algodoo scene archive.
- `src/setup.thyme`: One-time scene/AI initialization script (also mirrored to `dist/setup.txt`).
- `src/killer_poststep.thyme`: 60Hz killer AI loop (graph updates, incremental planner, movement).
- `src/killer_oncollide.thyme`: Killer collision handler (kills `materialName == "a"`, floor/wall normal sensing).
- `src/victim_poststep.thyme`: Victim marble loop (spatial telemetry, breadcrumbs/edges, target auction).
- `dist/scene_built.phn` & `dist/setup.txt`: Generated build artifacts.

## 3. Hard Technical Constraints (Algodoo & Thyme)
- **No external pathfinding/raycast APIs:** Spatial awareness must come strictly from `pos`, `vel`, `radius`, `onCollide` normals (`e.normal`), and shared `scene.my` state.
- **Thyme Variable Scoping:** Curly braces `{ ... }` create local scope. Using `=` inside `{ ... }` creates a temporary local variable that disappears at `}`. Persistent state MUST live on `scene.my.<var>` or `this.<var>`.
- **Thyme Immutable Lists:** `list + [item]` appends and `list(i)` reads, but in-place index assignment (`list(i) = val`) is a syntax error. Track counts manually as integers, iterate with `for(count, (i)=>{ ... })`, and mutate per-node/per-edge fields via `eval("scene.my.n" + id + "_...")` or functional list rebuilds.
- **Physics Realism ("Act Like a Marble"):** Never override `vel(1)` to jump, hover, or fly. Drive movement solely through rolling torque (`angvel = -desiredVx / radius`) and horizontal traction (`vel(0)`), letting gravity and ramps handle vertical motion.
- **Kill Contract:** Victims are identified by `e.other.materialName == "a"`. Killing a victim teleports it to `scene.my.tp3`, zeroes `vel`, sets `restitution = 0`, and clears `e.other.postStep = (e)=>{}`.
- **No 0-arg `()=>` Lambdas:** Algodoo `.phn` loading rejects `()=>{ ... }` (evaluates to `undefined`). Always write 1-arg `(u)=>{ ... }` for helpers (called with `0`), or `{ ... }` for `.phn` top-level `Scene.my.* :=`.
- **Never Overwrite `onCollide` Inside `postStep`:** Reassigning `onCollide` at 60Hz drops collision events.

## 4. Architecture & Goals (V0.2 -> V0.9)
We are building an empirical **Grounded-Cell Navigation Graph** (`walk` edges + directional `fall` edges with `departureX` and `departureVx`, `cs = 5.0 * _r`, `220/320/240` nested `20`-chunk caps), `1`-tick per-victim live `targetCell` tracking (`this._lastGx`/`this._lastGy` cache, deduplicated `vCells`), same-cell `findCell` fast paths (`kPrevGx`/`kPrevGy`, `kHeatIdx`), event-driven sleeping Bellman-Ford (`bfDirty` / `bfResweep`), 10Hz HUD throttle (`hudTick >= 6` + `hudVer`), sparse `cHeat` visit fatigue, `wUse`/`fUse` branch penalties, and a low-bounce (`0.18` passive / `0.12` hunter) **`PASSIVE_EXPLORE` (`UNSTICK_NUDGE` + `ACTIVE_PATROL` alternation) vs `ACTIVE_HUNTER` (`_directStrike` `7.5 m` / same-cell `4.4 m/s` chase, `_graphCost < 90000`, `WINDUP_RUN`, `300`t breakout)** state machine with `V0.9 |` HUD and snapshot preload.

### Your Tasks:
1. **Automate the Build & Validation Pipeline:** Upgrade `build.py` with a `--watch` mode and a pre-flight Thyme static linter so syntax/scoping bugs are caught before launching Algodoo.
2. **Complete & Harden the V0.3 Graph AI:** Finish any remaining planning/exploration/failure-recovery stages found in `NOTES.md` and `src/*.thyme`.
3. **Add New Features:** Implement multi-victim graph-cost target selection, optional pre-trained map graph serialization into `setup.thyme`, an on-screen Text Box debug HUD, and smart evasion AI for victims (`src/victim_poststep.thyme`).