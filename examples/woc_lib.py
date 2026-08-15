# Shared World of ClaudeCraft helpers for Grok browser-use scripts.
# Drive window.__game — never leave a held W or controller.move without stop().
# Binds to the character already in the tab (world.playerId). No player name filter.

import atexit
import json
import math
import os
import signal
import time
from pathlib import Path

CINDERBOLT = "fireball"
RIMELANCE = "frostbolt"
ICEBIND = "frost_nova"
BLINK = "blink"
BLAZING_BARRIER = "blazing_barrier"
MANTLE = "frost_armor"
INSIGHT = "arcane_intellect"
BREADBIND = "conjure_food"
WATERBIND = "conjure_water"
FOOD = "baked_bread"
WATER = "spring_water"
FOOD_PREFIXES = ("conjured_bread", "baked_bread")
WATER_PREFIXES = ("conjured_water", "spring_water")

# Fight buttons: 1 Attack, 3 Cinderbolt, 4 Icebind, 5 Blazing Barrier.
# Do not press bar 2. Frostbolt is off the bar.
CINDERBOLT_COST = 65
CINDERBOLT_CAST = 2.5
RIMELANCE_COST = 35
RIMELANCE_CAST = 2.0
ICEBIND_COST = 35
ICEBIND_RADIUS = 10.0
BLAZING_BARRIER_COST = 65
# Rank-1 Cinderbolt is 16-25 + 2 DoT. Rimelance is 18-20. Don't spend 30 mana on a dying mob.
BOLT_OVERKILL_HP = 22
BOLT_THIRD_HP = 40
MANTLE_COST = 20
INSIGHT_COST = 25
BREADBIND_COST = 45
WATERBIND_COST = 40
BREADBIND_CAST = 3.2
WATERBIND_CAST = 3.2
BUFF_REFRESH_REMAINING = 60

CAST_RANGE = 30.0
# Open the first bolt near max range. Do not walk into 20y to start a fight.
PULL_RANGE = 27.0
# How far from home we may step to tag. Then we kite back.
PULL_LEASH = 24.0
# Closest mob in this ring always wins. If that ring is empty, allow PULL_FAR.
PULL_NEAR_YARDS = 42.0
PULL_FAR_YARDS = 55.0
# A pull never walks farther than this toward home. Bigger = stale/wrong xyz.
PULL_HOME_MAX = 28.0
# Keep running at least this far so we are outside the 20y detect clamp.
FLEE_MIN_YARDS = 22.0
# Only keep sprinting this far if they have not dropped yet.
FLEE_AWAY_YARDS = 32.0
# Hard cap so a long chase does not cross the map.
FLEE_HOME_MAX = 56.0
# aiState values that mean the NPC is no longer chasing us.
_FLEE_RETURN_AI = frozenset(("idle", "wander", "return", "evade", "reset", "leash", "home"))
MELEE_RANGE = 6.0
# Pack spacing. Neighbors inside this range disqualify the pull.
ISOLATION_MIN = 5.0
ADD_ABORT_RANGE = 10.0
# Mobs wander up to ~9y. More than this many *other* hostiles inside this
# bubble means a pack that will walk into the pull.
CROWD_RADIUS = 16.0
MAX_CROWD = 1
# Game locomotion clamps detection at 20y (MAX_AGGRO_RADIUS). Stay outside it
# for anything above the hunt band (player + HUNT_LEVEL_ABOVE).
NORMAL_KEEP = 10.0
DANGER_KEEP = 22.0
# Never open a pull below this fraction of max HP.
MIN_PULL_HP_FRAC = 0.9
# Cloth cannot finish a hard cast below this. Run, do not tank.
FLEE_HP_FRAC = 0.55
# Do not sit inside the 20y aggro clamp.
SIT_CLEAR_YARDS = 24.0
# Hunt band: player-7 through player+1.
HUNT_LEVEL_ABOVE = 1
HUNT_LEVEL_BELOW = 7
# Only pull this mob when set. Empty string = any hunt-band hostile.
# To lock a camp later: HUNT_NAME = "Mire Prowler"
HUNT_NAME = ""
# Closest legal mob wins. Do not walk past a nearer NPC for a higher level.


def hunt_max_level(player_level):
    return (player_level or 1) + HUNT_LEVEL_ABOVE


def hunt_min_level(player_level):
    return max(1, (player_level or 1) - HUNT_LEVEL_BELOW)


# Other characters' last-known camps (updated when each hunt starts). Never used as our home.
SAFESPOTS = []
# This hunt's home — stamped from the character's xyz when the script starts.
# Per process. The other hunt cannot see or change these values.
SAFESPOT = None
SAFESPOT_OWNER = None
SAFESPOT_INDEX = None
SAFESPOT_ID = None
# True after this process has issued a walk. Used to detect a stale first xyz.
HOME_WALKED = False
# Mid-fight only corrects a small drift. A far home is the other character.
HOME_HOLD_YARDS = 12.0
# Pull / recover never crosses the map to another character's camp.
HOME_WALK_YARDS = 90.0
# Treat an xyz this close to a listed row as that character's camp.
HOME_MATCH_YARDS = 40.0
# Tab this process owns. j() always evaluates here so another hunt cannot steal reads.
BOUND_TID = None


def _safespot_path(name):
    raw = (name or "").strip()
    if not raw:
        return None
    safe = "".join(c for c in raw.lower() if c.isalnum() or c in "-_")
    if not safe:
        return None
    root = Path(os.environ.get("LOCALAPPDATA") or ".") / "botcraft" / "safespots"
    root.mkdir(parents=True, exist_ok=True)
    return root / (safe + ".json")


def wanted_player():
    return (os.environ.get("WOC_PLAYER") or "").strip()


def _name_key(name):
    return (name or "").strip().lower()


def snapshot_is_ours(s):
    """True if this snapshot is the character this hunt process is pinned to."""
    if not s or not s.get("ok"):
        return False
    who = (s.get("name") or "").strip()
    want = wanted_player()
    if want and who.lower() != want.lower():
        return False
    if SAFESPOT_OWNER and who and who.lower() != SAFESPOT_OWNER.lower():
        return False
    return True


def listed_safespot(name):
    """This character's row in SAFESPOTS. Never falls through to someone else's camp."""
    want = _name_key(name) or _name_key(wanted_player())
    if not want:
        return None
    idx_raw = (os.environ.get("WOC_SAFESPOT_INDEX") or "").strip()
    if idx_raw.isdigit():
        idx = int(idx_raw)
        if 0 <= idx < len(SAFESPOTS):
            row = dict(SAFESPOTS[idx])
            row["_index"] = idx
            owner = _name_key(row.get("player"))
            if owner and owner != want:
                print(
                    "SAFESPOT index skipped",
                    json.dumps({"index": idx, "row": row.get("player"), "want": want}),
                )
            else:
                return row
    for i, spot in enumerate(SAFESPOTS):
        if _name_key(spot.get("player")) == want:
            row = dict(spot)
            row["_index"] = i
            return row
    return None


def whose_listed_home(x, z, max_d=None):
    """Which SAFESPOTS row is this xyz standing on?"""
    limit = HOME_MATCH_YARDS if max_d is None else max_d
    best = None
    best_d = limit
    for i, spot in enumerate(SAFESPOTS):
        d = dist(x, z, spot["x"], spot["z"])
        if d <= best_d:
            best_d = d
            row = dict(spot)
            row["_index"] = i
            row["_dist"] = d
            best = row
    return best


def dest_is_foreign_home(x, z, who):
    other = whose_listed_home(x, z)
    if not other:
        return None
    if _name_key(other.get("player")) == _name_key(who):
        return None
    return other


def load_safespot(name):
    """This character's saved JSON only. Do not substitute another row or a stale listed camp."""
    path = _safespot_path(name)
    if not path or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        owner = (data.get("player") or name or "").strip()
        want = wanted_player()
        if want and owner and owner.lower() != want.lower():
            return None
        foreign = dest_is_foreign_home(float(data["x"]), float(data["z"]), owner or name)
        if foreign:
            print(
                "SAFESPOT file ignored, on other camp",
                json.dumps({"file": owner, "other": foreign.get("player")}),
            )
            return None
        return {
            "x": float(data["x"]),
            "y": float(data.get("y") or 0),
            "z": float(data["z"]),
            "player": owner or name,
        }
    except Exception:
        return None


def save_safespot(name, spot):
    path = _safespot_path(name)
    if not path or not spot:
        return
    rec = {"x": spot["x"], "y": spot.get("y") or 0, "z": spot["z"], "player": name}
    path.write_text(json.dumps(rec), encoding="utf-8")


def update_listed_home(who, spot):
    """Keep this character's SAFESPOTS row in sync so others will not walk here."""
    if not who or not spot:
        return None
    key = _name_key(who)
    rec = {"player": who, "x": float(spot["x"]), "y": float(spot.get("y") or 0), "z": float(spot["z"])}
    for i, row in enumerate(SAFESPOTS):
        if _name_key(row.get("player")) == key:
            SAFESPOTS[i] = rec
            return i
    SAFESPOTS.append(rec)
    return len(SAFESPOTS) - 1


def adopt_safespot(spot, owner, eid=None):
    global SAFESPOT, SAFESPOT_OWNER, SAFESPOT_INDEX, SAFESPOT_ID
    if not spot:
        return None
    who = (owner or spot.get("player") or wanted_player() or "").strip()
    SAFESPOT = {"x": float(spot["x"]), "y": float(spot.get("y") or 0), "z": float(spot["z"])}
    SAFESPOT_OWNER = who
    SAFESPOT_ID = eid
    SAFESPOT_INDEX = update_listed_home(who, SAFESPOT)
    return SAFESPOT


def home_dist(s):
    if not SAFESPOT or not s or not s.get("ok"):
        return None
    return dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"])


def refuse_home_walk(s, max_away, why):
    """Stop a walk that would send this character off their start stamp."""
    if not SAFESPOT:
        return s, "no_home"
    if not snapshot_is_ours(s):
        print(
            "SAFESPOT skip wrong player",
            json.dumps({"name": s.get("name"), "want": wanted_player() or None, "owner": SAFESPOT_OWNER, "why": why}),
        )
        stop()
        return s, "wrong_player"
    if SAFESPOT_ID is not None and s.get("id") is not None and s.get("id") != SAFESPOT_ID:
        print(
            "SAFESPOT skip wrong id",
            json.dumps({"id": s.get("id"), "home_id": SAFESPOT_ID, "name": s.get("name"), "why": why}),
        )
        stop()
        return s, "wrong_player"
    d = home_dist(s)
    if d is not None and d > max_away:
        print(
            "SAFESPOT skip too far",
            json.dumps(
                {
                    "from": [round(s["x"], 1), round(s["z"], 1)],
                    "to": SAFESPOT,
                    "dist": round(d, 1),
                    "owner": SAFESPOT_OWNER,
                    "index": SAFESPOT_INDEX,
                    "why": why,
                }
            ),
        )
        stop()
        return s, "too_far"
    return s, None


def set_safespot(s=None, force=False):
    """Home is this character's feet right now. Call once when the hunt process starts."""
    s = s or snapshot()
    if not s.get("ok"):
        return None
    who = (s.get("name") or "").strip()
    want = wanted_player()
    if want and who.lower() != want.lower():
        print("SAFESPOT refused, snapshot is", json.dumps({"name": who, "want": want}))
        return None
    if SAFESPOT is not None and not force:
        print(
            "SAFESPOT keep",
            json.dumps({"player": SAFESPOT_OWNER, "index": SAFESPOT_INDEX, "home": SAFESPOT}),
        )
        return SAFESPOT
    pack = [h for h in living_hostiles(s) if (h.get("dist") or 99) <= 16]
    near = [
        {"name": h.get("name"), "dist": h.get("dist"), "xyz": xyz_of(h)}
        for h in pack[:4]
    ]
    if not adopt_safespot(s, who, eid=s.get("id")):
        return None
    print(
        "SAFESPOT set",
        json.dumps(
            {
                "player": who or None,
                "id": s.get("id"),
                "index": SAFESPOT_INDEX,
                "home": SAFESPOT,
                "from": "script_start",
                "nearby": near,
            }
        ),
    )
    return SAFESPOT


def stamp_start_home():
    """Read xyz a few times after bind. The first CDP read after attach can be stale."""
    stop()
    time.sleep(0.35)
    agreed = None
    last = None
    for i in range(6):
        s = snapshot()
        if not s.get("ok") or not snapshot_is_ours(s):
            time.sleep(0.2)
            continue
        if last and dist(s["x"], s["z"], last["x"], last["z"]) <= 2.0:
            agreed = s
            break
        last = s
        print(
            "SAFESPOT sample",
            json.dumps({"n": i, "name": s.get("name"), "id": s.get("id"), "xyz": [s.get("x"), s.get("y"), s.get("z")]}),
        )
        time.sleep(0.25)
    s = agreed or last
    if not s or not snapshot_is_ours(s):
        print("SAFESPOT wait, no stable read for", wanted_player() or "?")
        return None
    return set_safespot(s, force=True)


def restamp_home_if_stale(s):
    """If we have not walked yet but are already far from recorded home, the first xyz was wrong."""
    global HOME_WALKED
    if HOME_WALKED or not s or not s.get("ok"):
        return s
    d = home_dist(s)
    if d is None or d <= 6.0:
        return s
    print(
        "SAFESPOT restamp stale",
        json.dumps(
            {
                "was": SAFESPOT,
                "now": [round(s["x"], 2), round(s.get("y") or 0, 2), round(s["z"], 2)],
                "dist": round(d, 1),
                "name": s.get("name"),
                "id": s.get("id"),
            }
        ),
    )
    set_safespot(s, force=True)
    return s


def go_safespot(stop_at=5.0, max_s=16.0, max_away=None, defend_on_aggro=True):
    """Walk back to the start stamp. Refuses a long march to a stale/wrong xyz."""
    if not SAFESPOT:
        return snapshot()
    s = snapshot()
    if not s.get("ok") or s.get("dead") or is_resting(s):
        return s
    cap = PULL_HOME_MAX if max_away is None else max_away
    s, why = refuse_home_walk(s, cap, "go")
    if why:
        return s
    if dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"]) <= stop_at:
        stop()
        return s
    print(
        "SAFESPOT walk",
        json.dumps(
            {
                "from": [round(s["x"], 1), round(s["z"], 1)],
                "to": SAFESPOT,
                "owner": SAFESPOT_OWNER,
                "index": SAFESPOT_INDEX,
            }
        ),
    )
    attack(False)
    for _try in range(3):
        if attackers(s):
            if not defend_on_aggro:
                stop()
                return s
            s, _killed = defend()
            if s.get("dead"):
                return s
        s, why = refuse_home_walk(s, cap, "go_retry")
        if why:
            return s
        s = move_toward(
            SAFESPOT["x"],
            SAFESPOT["z"],
            stop_at=stop_at,
            max_s=max_s,
            jump=True,
            abort_adds=False,
            abort_danger=False,
            avoid=False,
        )
        if s.get("dead"):
            return s
        if dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"]) <= stop_at + 1.0:
            stop()
            return s
        if attackers(s):
            if not defend_on_aggro:
                stop()
                return s
            continue
        break
    return s


def kite_to_safespot(ignore_id=None, stop_at=6.0, max_s=22.0):
    """After a tag, run home. The pull target may chase; a second aggro aborts."""
    if not SAFESPOT:
        return snapshot(), "no_home"
    s = snapshot()
    if not s.get("ok") or s.get("dead"):
        return s, "dead" if s.get("dead") else "no_game"
    s, why = refuse_home_walk(s, PULL_HOME_MAX, "kite")
    if why:
        return s, why
    if dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"]) <= stop_at:
        stop()
        return s, "already"
    print(
        "SAFESPOT kite",
        json.dumps(
            {
                "from": [round(s["x"], 1), round(s["z"], 1)],
                "to": SAFESPOT,
                "ignore": ignore_id,
                "owner": SAFESPOT_OWNER,
                "index": SAFESPOT_INDEX,
            }
        ),
    )
    # Leave Attack (1) on so the tag swing is not cancelled. Do not plant here.
    t0 = time.time()
    last = s
    last_pos_t = t0
    last_d = dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"])
    stuck_hits = 0
    wrong_way = 0
    while time.time() - t0 < max_s:
        s = snapshot()
        if not s.get("ok") or s.get("dead"):
            stop()
            return s, "dead"
        if not snapshot_is_ours(s):
            stop()
            return s, "wrong_player"
        d = dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"])
        if d <= stop_at:
            stop()
            return s, "ok"
        if d > PULL_HOME_MAX:
            stop()
            return s, "too_far"
        if last_d is not None and d > last_d + 0.4:
            wrong_way += 1
            if wrong_way >= 4:
                stop()
                return s, "wrong_way"
        else:
            wrong_way = 0
        last_d = d
        # Beeline home. Path-bending around packs is what ran us into the wild.
        ang = face_to(SAFESPOT["x"], SAFESPOT["z"], s["x"], s["z"])
        now = time.time()
        moved = dist(s["x"], s["z"], last["x"], last["z"]) if last else 1
        stuck = (now - last_pos_t) > 0.45 and moved < 0.35
        if stuck:
            stuck_hits += 1
            last = s
            last_pos_t = now
        elif moved >= 0.35:
            stuck_hits = 0
            last = s
            last_pos_t = now
        move({"forward": True, "jump": True if stuck else int((now - t0) * 8) % 10 == 0}, ang)
        if stuck_hits >= 6:
            stop()
            return s, "stuck"
        time.sleep(0.12)
    stop()
    s = snapshot()
    if dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"]) <= stop_at + 3.0:
        return s, "ok"
    return s, "timeout"


def _tab_player_info(tid=None):
    """Read the in-world character on this tab. tid avoids reading the wrong page."""
    code = r"""
(() => {
  const g = window.__game;
  if (!g || !g.world) return {ok: false, reason: 'no_game'};
  const p = g.world.entities && g.world.entities.get(g.world.playerId);
  if (!p) return {ok: false, reason: 'no_player'};
  return {ok: true, name: p.name || '', level: p.level || null};
})()
"""
    try:
        if tid:
            return js(code, target_id=tid) or {}
        return j(code) or {}
    except Exception as err:
        return {"ok": False, "reason": type(err).__name__}


def _bound_player_ok():
    if not BOUND_TID:
        return False
    info = _tab_player_info(BOUND_TID)
    if not info.get("ok"):
        return False
    want = wanted_player()
    name = (info.get("name") or "").strip()
    if want and name.lower() != want.lower():
        return False
    return True


def activate_game(retries=8):
    """Bind the ClaudeCraft tab. WOC_PLAYER pins a character when several tabs exist."""
    global BOUND_TID
    last = None
    want = wanted_player().lower()
    if _bound_player_ok():
        # Keep this hunt on its own tab. Scanning every round switch_tab's the other character.
        try:
            cdp("Target.activateTarget", targetId=BOUND_TID)
        except Exception:
            pass
        install_combat_hook()
        return BOUND_TID
    for attempt in range(max(1, retries)):
        try:
            tabs = list_tabs(include_chrome=False)
            found = []
            match = None
            for t in tabs:
                url = (t.get("url") or "").lower()
                if "claudecraft" not in url:
                    continue
                tid = t.get("targetId") or t.get("target_id")
                if not tid:
                    continue
                info = _tab_player_info(tid)
                name = (info.get("name") or "").strip()
                label = name or info.get("reason") or "?"
                found.append({"title": (t.get("title") or "")[:40], "player": label})
                if not info.get("ok"):
                    continue
                if want and name.lower() != want:
                    continue
                match = (tid, name, url)
                break
            if match:
                tid, name, url = match
                try:
                    switch_tab(tid)
                except Exception:
                    cdp("Target.activateTarget", targetId=tid)
                install_combat_hook()
                BOUND_TID = tid
                print("BOUND", json.dumps({"player": name or None, "want": want or None, "tab": url[:80]}))
                return tid
            if want:
                last = RuntimeError(
                    "WOC_PLAYER=%s not in any in-world ClaudeCraft tab (saw %s)" % (want, found or "none")
                )
            else:
                last = RuntimeError("World of ClaudeCraft tab not found (saw %s)" % (found or "none"))
        except Exception as err:
            last = err
        BOUND_TID = None
        time.sleep(1.5)
    raise RuntimeError(f"World of ClaudeCraft tab not found ({last})")


def install_combat_hook():
    """Catch damage-taken the same frame the combat log writes 'X hits you'."""
    return j(
        r"""
(() => {
  const g = window.__game;
  if (!g || !g.hud || !g.hud.handleEvents) return false;
  if (window.__wocCombat && window.__wocCombat.hooked === g.hud.handleEvents) return true;
  const orig = g.hud.handleEvents.bind(g.hud);
  const state = { hooked: null, incoming: [], lastEventAt: 0 };
  const wrapped = function(events) {
    try {
      const pid = g.world && g.world.playerId;
      const now = Date.now();
      if (pid != null && Array.isArray(events)) {
        for (const e of events) {
          if (!e || e.type !== 'damage' || e.targetId !== pid) continue;
          state.incoming.push({
            t: now,
            sourceId: e.sourceId,
            amount: e.amount || 0,
            kind: e.kind || 'hit',
            ability: e.ability || null
          });
          state.lastEventAt = now;
        }
        if (state.incoming.length > 60) state.incoming = state.incoming.slice(-60);
      }
    } catch (err) {}
    return orig(events);
  };
  g.hud.handleEvents = wrapped;
  state.hooked = wrapped;
  window.__wocCombat = state;
  return true;
})()
"""
    )


def j(code):
    """js() with retries — Chrome/CDP drops show up as WinError 64 / timeouts."""
    last = None
    for attempt in range(5):
        try:
            if BOUND_TID:
                return js(code, target_id=BOUND_TID)
            return js(code)
        except Exception as err:
            last = err
            msg = str(err).lower()
            transient = any(
                tok in msg
                for tok in (
                    "winerror 64",
                    "network name",
                    "timed out",
                    "timeout",
                    "connection",
                    "10054",
                    "10053",
                    "10061",
                    "broken pipe",
                    "eof",
                )
            )
            if not transient:
                raise
            time.sleep(0.6 + attempt * 0.4)
    raise last


def stop():
    """Drop scripted movement so this tick stands still. Keyboard works again after this."""
    return j(
        """
(() => {
  const g = window.__game;
  if (!g) return {ok: false};
  try { if (g.input && typeof g.input.setAutorun === 'function') g.input.setAutorun(false); } catch (e) {}
  try { if (g.input) g.input.autorun = false; } catch (e) {}
  try { if (g.controller && typeof g.controller.stop === 'function') g.controller.stop(); } catch (e) {}
  try { if (g.input && typeof g.input.clearControllerMoveInput === 'function') g.input.clearControllerMoveInput(); } catch (e) {}
  try { if (g.input && typeof g.input.clearClickMove === 'function') g.input.clearClickMove(); } catch (e) {}
  try {
    if (g.world && g.world.setMoveInput) {
      g.world.setMoveInput({
        forward: false, back: false, turnLeft: false, turnRight: false,
        strafeLeft: false, strafeRight: false, jump: false, dive: false, surface: false
      });
    }
  } catch (e) {}
  return {ok: true};
})()
"""
    )


_HALTED = False


def halt_movement(reason="exit"):
    """Stop autorun and give the keyboard back. Do not leave controllerMoveInput set."""
    global _HALTED
    if _HALTED:
        return True
    ok = False
    try:
        stop()
        ok = True
    except Exception as err:
        print("HALT stop failed", reason, type(err).__name__, str(err)[:200])
    try:
        attack(False)
    except Exception:
        pass
    if ok:
        _HALTED = True
        print("HALT", reason)
    return ok


def _on_stop_signal(signum, _frame):
    halt_movement("signal_%s" % signum)
    raise KeyboardInterrupt


def _install_halt_hooks():
    # Map overlay and other one-shot scripts must not halt on exit — that
    # left controllerMoveInput set and blocked WASD. Hunt sets WOC_HALT_ON_EXIT=1.
    flag = (os.environ.get("WOC_HALT_ON_EXIT") or "").strip().lower()
    if flag not in ("1", "true", "yes"):
        return
    atexit.register(halt_movement, "atexit")
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _on_stop_signal)
        except Exception:
            pass


_install_halt_hooks()


def is_resting(s=None):
    s = s or snapshot()
    return bool(s.get("sitting") or s.get("eating") or s.get("drinking"))


def stop_unless_resting(s=None):
    """Move-input stop stands you up. Do not send it while eating or drinking."""
    s = s or snapshot()
    if not is_resting(s):
        stop()
    return s


def face_to(x, z, from_x, from_z):
    return math.atan2(x - from_x, z - from_z)


def dist(ax, az, bx, bz):
    return math.hypot(ax - bx, az - bz)


def xyz_of(e):
    return [round(e.get("x") or 0, 2), round(e.get("y") or 0, 2), round(e.get("z") or 0, 2)]


def _snapshot_raw():
    return j(
        r"""
(() => {
  const g = window.__game;
  if (!g || !g.world) return { ok: false };
  const w = g.world;
  const p = w.entities.get(w.playerId);
  if (!p) return { ok: false };
  const ents = [];
  w.entities.forEach((e) => {
    if (!e || e.id === w.playerId) return;
    const ep = e.pos || {};
    const d = Math.hypot((ep.x ?? 0) - p.pos.x, (ep.z ?? 0) - p.pos.z);
    const x = ep.x ?? 0, y = ep.y ?? 0, z = ep.z ?? 0;
    ents.push({
      id: e.id, kind: e.kind, name: e.name, level: e.level,
      hp: e.hp, maxHp: e.maxHp, dead: !!e.dead, hostile: !!e.hostile,
      templateId: e.templateId,
      x: Math.round(x * 100) / 100,
      y: Math.round(y * 100) / 100,
      z: Math.round(z * 100) / 100,
      dist: Math.round(d * 100) / 100,
      dist3: Math.round(Math.hypot(x - p.pos.x, y - p.pos.y, z - p.pos.z) * 100) / 100,
      facing: e.facing ?? null,
      targetId: e.targetId || null,
      aggroTargetId: e.aggroTargetId || null,
      inCombat: !!e.inCombat,
      aiState: e.aiState || null,
      evadeEpoch: e.evadeEpoch || 0,
      chaseStall: e.chaseStall || 0,
      vx: Math.round((e.vx || 0) * 100) / 100,
      vz: Math.round((e.vz || 0) * 100) / 100
    });
  });
  ents.sort((a, b) => a.dist - b.dist);
  const now = Date.now();
  const hook = window.__wocCombat || { incoming: [] };
  const recentHits = (hook.incoming || []).filter((h) => now - (h.t || 0) < 8000);
  const hitByIds = [];
  for (const h of recentHits) {
    if (h.sourceId != null && !hitByIds.includes(h.sourceId)) hitByIds.push(h.sourceId);
  }
  const hitByNames = [];
  const hitRe = /^(.+?) (?:critically )?hits you for /;
  const logEl = g.hud && g.hud.combatLogEl;
  const kids = logEl ? logEl.children : [];
  for (let i = Math.max(0, kids.length - 16); i < kids.length; i++) {
    const t = (kids[i].innerText || '').trim();
    const m = t.match(hitRe);
    if (m && !hitByNames.includes(m[1])) hitByNames.push(m[1]);
  }
  return {
    ok: true,
    id: p.id,
    name: p.name,
    level: p.level,
    hp: p.hp,
    maxHp: p.maxHp,
    mana: p.resource,
    maxMana: p.maxResource,
    dead: !!p.dead,
    sitting: !!p.sitting,
    eating: !!p.eating,
    drinking: !!p.drinking,
    x: Math.round(p.pos.x * 100) / 100,
    y: Math.round(p.pos.y * 100) / 100,
    z: Math.round(p.pos.z * 100) / 100,
    facing: p.facing,
    targetId: p.targetId,
    xp: w.xp,
    copper: w.copper,
    auras: (p.auras || []).map((a) => ({
      id: a.id,
      remaining: Math.round((a.remaining || 0) * 10) / 10
    })),
    autoAttack: !!p.autoAttack,
    inCombat: !!p.inCombat,
    combatExitHoldUntil: p.combatExitHoldUntil || 0,
    gcdRemaining: Math.round((p.gcdRemaining || 0) * 100) / 100,
    castingAbility: p.castingAbility || null,
    castRemaining: Math.round((p.castRemaining || 0) * 100) / 100,
    swingTimer: Math.round((p.swingTimer || 0) * 100) / 100,
    cooldowns: (() => {
      const o = {};
      const cds = p.cooldowns;
      if (cds && typeof cds.forEach === 'function') {
        cds.forEach((v, k) => { o[k] = Math.round((v || 0) * 100) / 100; });
      }
      return o;
    })(),
    inventory: (w.inventory || []).map((it) => ({
      id: it.itemId || it.id,
      count: it.count || it.qty || 0
    })),
    hitByIds,
    hitByNames,
    lastHitAt: hook.lastEventAt || 0,
    ents
  };
})()
"""
    )


def snapshot():
    """Read this hunt's character only. A leaked snapshot from another tab walks us to their xyz."""
    data = _snapshot_raw()
    want = _name_key(wanted_player()) or _name_key(SAFESPOT_OWNER)
    if not want:
        return data or {"ok": False}
    if data and data.get("ok") and _name_key(data.get("name")) == want:
        return data
    print(
        "SNAPSHOT wrong player",
        json.dumps({"name": (data or {}).get("name"), "want": want, "bound": bool(BOUND_TID)}),
    )
    if BOUND_TID:
        try:
            cdp("Target.activateTarget", targetId=BOUND_TID)
        except Exception:
            pass
        data = _snapshot_raw()
        if data and data.get("ok") and _name_key(data.get("name")) == want:
            return data
    try:
        activate_game(retries=2)
    except Exception:
        pass
    data = _snapshot_raw()
    if data and data.get("ok") and _name_key(data.get("name")) == want:
        return data
    return {"ok": False, "reason": "wrong_player", "name": (data or {}).get("name")}


def own_listed_home(s=None):
    """Session start first. Listed coords are only a fallback, never another player."""
    who = (s.get("name") if s else None) or wanted_player() or SAFESPOT_OWNER
    if SAFESPOT and (not SAFESPOT_OWNER or not who or _name_key(SAFESPOT_OWNER) == _name_key(who)):
        rec = dict(SAFESPOT)
        rec["player"] = SAFESPOT_OWNER or who
        rec["_index"] = SAFESPOT_INDEX
        return rec
    return listed_safespot(who)


def standing_on_foreign_camp(s):
    if not s or not s.get("ok"):
        return None
    who = s.get("name") or wanted_player() or SAFESPOT_OWNER
    other = whose_listed_home(s["x"], s["z"])
    if other and _name_key(other.get("player")) != _name_key(who):
        return other
    return None


def away_from_own_home(s):
    home = own_listed_home(s)
    if not home or not s or not s.get("ok"):
        return None
    d = dist(s["x"], s["z"], home["x"], home["z"])
    if d > HOME_WALK_YARDS:
        return d
    return None


def entity(eid):
    return j(
        f"""
(() => {{
  const w = window.__game.world;
  const p = w.entities.get(w.playerId);
  const e = w.entities.get({int(eid)});
  if (!e) return null;
  const d = Math.hypot(e.pos.x - p.pos.x, e.pos.z - p.pos.z);
  return {{
    id: e.id, kind: e.kind, name: e.name, level: e.level,
    hp: e.hp, maxHp: e.maxHp, dead: !!e.dead, hostile: !!e.hostile,
    templateId: e.templateId || null,
    x: Math.round(e.pos.x * 100) / 100,
    y: Math.round(e.pos.y * 100) / 100,
    z: Math.round(e.pos.z * 100) / 100,
    dist: Math.round(d * 100) / 100,
    dist3: Math.round(Math.hypot(e.pos.x - p.pos.x, e.pos.y - p.pos.y, e.pos.z - p.pos.z) * 100) / 100,
    facing: e.facing ?? null,
    targetId: e.targetId || null,
    aggroTargetId: e.aggroTargetId || null,
    inCombat: !!e.inCombat,
    aiState: e.aiState || null,
    evadeEpoch: e.evadeEpoch || 0,
    chaseStall: e.chaseStall || 0,
    vx: Math.round((e.vx || 0) * 100) / 100,
    vz: Math.round((e.vz || 0) * 100) / 100
  }};
}})()
"""
    )


def living_hostiles(s=None):
    s = s or snapshot()
    return [
        e
        for e in s.get("ents", [])
        if e.get("hostile") and not e.get("dead") and e.get("kind") in ("mob", "npc")
    ]


_MOBS = None


def mobs():
    global _MOBS
    if _MOBS is None:
        _MOBS = j("window.__game.MOBS || {}") or {}
    return _MOBS


def template_flags(mob):
    tmpl = mobs().get((mob or {}).get("templateId") or "") or {}
    return bool(tmpl.get("rare")), bool(tmpl.get("elite"))


def is_overlevel(mob, player_level):
    """True only when we know both levels and the mob is above the hunt band."""
    if not player_level or player_level < 1:
        return False
    lv = (mob or {}).get("level")
    if lv is None:
        return False
    return lv > hunt_max_level(player_level)


def is_too_hard(mob, player_level):
    """Flee / do-not-open: over-level or rare. Same-band elite is keepaway, not a flee."""
    if not mob or not mob.get("hostile"):
        return False
    if mob.get("kind") not in ("mob", "npc"):
        return False
    rare, _elite = template_flags(mob)
    return is_overlevel(mob, player_level) or rare


def hunt_name_match(mob, needle=None):
    """True if mob is the configured hunt target. Underscore/space are the same."""
    if needle is None:
        needle = HUNT_NAME
    needle = (needle or "").lower().replace("_", " ").strip()
    if not needle:
        return True
    name = (mob.get("name") or "").lower().replace("_", " ")
    tmpl = (mob.get("templateId") or "").lower().replace("_", " ")
    return needle in name or needle in tmpl


def is_hunt_mob(mob, player_level=None):
    """Hostile, not rare/elite, in the hunt band, and the named target if set."""
    if not mob or mob.get("dead"):
        return False
    if mob.get("kind") not in ("mob", "npc"):
        return False
    if not mob.get("hostile"):
        return False
    if not hunt_name_match(mob):
        return False
    if player_level is None:
        return True
    rare, elite = template_flags(mob)
    if rare or elite:
        return False
    if is_overlevel(mob, player_level):
        return False
    lv = mob.get("level")
    if lv is None:
        return True
    return hunt_min_level(player_level) <= lv <= hunt_max_level(player_level)


def is_danger(mob, player_level):
    """Pathing keepaway: over-level, rare, or elite. Hunt-band trash is not danger."""
    if not mob or mob.get("dead") or not mob.get("hostile"):
        return False
    if mob.get("kind") not in ("mob", "npc"):
        return False
    if is_hunt_mob(mob, player_level):
        return False
    rare, elite = template_flags(mob)
    return is_overlevel(mob, player_level) or rare or elite


def keepaway_for(mob, player_level):
    """How far to stay from this mob.

    Over-level: stay outside ~20y detection. A same-band elite (Captain
    Verlan at player-2) only needs its own aggro bubble. Using DANGER_KEEP
    (22y) on those elites marked every chapel bone as route_danger and
    idled the loop while we were already in bolt range.
    """
    if is_danger(mob, player_level):
        tmpl = mobs().get(mob.get("templateId") or "") or {}
        aggro = tmpl.get("aggroRadius")
        aggro_keep = float(aggro) + 4.0 if isinstance(aggro, (int, float)) and aggro > 0 else 16.0
        if (mob.get("level") or 1) > hunt_max_level(player_level):
            return max(DANGER_KEEP, aggro_keep)
        return aggro_keep
    return NORMAL_KEEP


def living_blockers(s=None, player_level=None):
    """Mobs/NPCs we must not walk through, including over-level even if not hostile yet."""
    s = s or snapshot()
    player_level = player_level if player_level is not None else (s.get("level") or 1)
    out = []
    for e in s.get("ents") or []:
        if e.get("dead"):
            continue
        if e.get("kind") not in ("mob", "npc"):
            continue
        if e.get("hostile") or is_danger(e, player_level):
            out.append(e)
    return out


def danger_nearby(s=None, ignore_id=None, player_level=None, radius=None):
    s = s or snapshot()
    player_level = player_level if player_level is not None else (s.get("level") or 1)
    out = []
    for e in s.get("ents") or []:
        if e.get("dead"):
            continue
        if ignore_id is not None and e.get("id") == ignore_id:
            continue
        if e.get("kind") not in ("mob", "npc"):
            continue
        if not is_danger(e, player_level):
            continue
        keep = radius if radius is not None else keepaway_for(e, player_level)
        if (e.get("dist") or 99) <= keep:
            out.append(e)
    out.sort(key=lambda e: (e.get("dist") or 99))
    return out


def flee_reason(mob, player_level, attacker_count=1):
    """Why we would run. Hunt-band trash and same-band elites are not 'too hard'."""
    if attacker_count >= 2:
        return "pack"
    if not mob:
        return None
    if is_overlevel(mob, player_level):
        return "over_level"
    rare, _elite = template_flags(mob)
    if rare:
        return "rare"
    return None


def should_flee(mob, player_level, attacker_count=1):
    """Cloth cannot tank a pack or a rare. A single hunt-band NPC is a fight."""
    return flee_reason(mob, player_level, attacker_count) is not None


def hp_frac(s):
    mx = (s or {}).get("maxHp") or 0
    if mx <= 0:
        return 0.0
    return float((s.get("hp") or 0)) / float(mx)


def close_hostiles(s, radius=SIT_CLEAR_YARDS):
    """Living hostiles inside radius, nearest first."""
    s = s or snapshot()
    out = [h for h in living_hostiles(s) if (h.get("dist") or 99) <= radius]
    out.sort(key=lambda e: (e.get("dist") or 99))
    return out


def hostiles_near_point(s, x, z, radius=SIT_CLEAR_YARDS):
    """Living hostiles near a world point (used to test if the stamp is a camp)."""
    s = s or snapshot()
    out = []
    for h in living_hostiles(s):
        if h.get("x") is None or h.get("z") is None:
            continue
        if dist(h["x"], h["z"], x, z) <= radius:
            out.append(h)
    out.sort(key=lambda e: dist(e["x"], e["z"], x, z))
    return out


def should_reset(s, aggro=None):
    """True if standing to fight will get us killed."""
    if not s or not s.get("ok") or s.get("dead"):
        return True
    if hp_frac(s) <= FLEE_HP_FRAC:
        return True
    aggro = attackers(s) if aggro is None else aggro
    if not aggro:
        return False
    return should_flee(aggro[0], s.get("level") or 1, attacker_count=len(aggro))


def reset_combat(s=None):
    """Drop the pack: nova if it will not leech, then run away and come home."""
    s = s or snapshot()
    stop()
    attack(False)
    if s.get("ok") and not s.get("dead"):
        aggro = attackers(s)
        mob = aggro[0] if aggro else None
        if (
            mob
            and knows_ability(ICEBIND)
            and (s.get("mana") or 0) >= ICEBIND_COST
            and (mob.get("dist") or 99) <= ICEBIND_RADIUS
            and cooldown_remaining(ICEBIND, s) <= 0.08
            and nova_is_safe(s, ignore_id=mob.get("id"))
        ):
            try_cast(ICEBIND)
    return flee_to_safespot()


def attackers(s=None):
    """Anyone actually hitting us: target, aggroTarget, combat-log, or melee while inCombat."""
    s = s or snapshot()
    pid = s.get("id")
    out = []
    seen = set()

    def add(e):
        if not e or e.get("dead") or e.get("id") in seen:
            return
        if e.get("kind") not in ("mob", "npc"):
            return
        seen.add(e.get("id"))
        out.append(e)

    ents = s.get("ents") or []
    by_id = {e.get("id"): e for e in ents}
    for e in ents:
        if e.get("targetId") == pid or e.get("aggroTargetId") == pid:
            add(e)
    for hid in s.get("hitByIds") or []:
        add(by_id.get(hid))
    # Same-name camps (Bog Bloat, Restless Bones) must not count a neighbor
    # as an add. Only attach a name hit if that mob is already on us.
    if s.get("hitByIds") and s.get("inCombat"):
        hit_ids = set(s.get("hitByIds") or [])
        for name in s.get("hitByNames") or []:
            matches = [e for e in ents if (e.get("name") or "") == name and not e.get("dead")]
            on_us = [
                e
                for e in matches
                if e.get("id") in hit_ids
                or e.get("targetId") == pid
                or e.get("aggroTargetId") == pid
            ]
            if on_us:
                for e in on_us:
                    add(e)
    out.sort(key=lambda e: (e.get("dist") or 99, e.get("hp") or 0))
    return out


def under_attack(s=None):
    s = s or snapshot()
    return bool(attackers(s))


def fight_entity(eid, max_s=22.0):
    """Kill one mob already on us. Plant at the safespot — do not chase."""
    stop()
    target(eid)
    attack(True)
    t0 = time.time()
    bolts = 0
    while time.time() - t0 < max_s:
        s = snapshot()
        mob = entity(eid)
        if s.get("dead"):
            stop()
            attack(False)
            return s, mob, "we_died"
        if not mob or mob.get("dead"):
            stop()
            attack(False)
            return s, mob, "dead"
        if should_reset(s):
            print("FLEE low_hp fight", json.dumps({"hp": s.get("hp"), "maxHp": s.get("maxHp"), "id": eid}))
            reset_combat(s)
            return snapshot(), entity(eid), "fled"
        s = ensure_hostile_target(eid, s)
        keep_autoattack(s)
        hold_safespot()
        s = snapshot()
        ang = face_to(mob["x"], mob["z"], s["x"], s["z"])
        face(ang)
        d = mob.get("dist") or 0
        want = (not casting_or_gcd(s)) and pick_damage_spell(s, mob) and bolts < 4
        if want:
            spell, ok, err = press_damage(eid, mob, s, planted=True)
            if ok:
                bolts += 1
                print("CAST", json.dumps({"spell": spell, "dist": d, "hp": mob.get("hp")}))
                if spell == CINDERBOLT and bolts == 1:
                    after_first_cinderbolt()
            elif err:
                print("CAST fail", json.dumps({"spell": spell, "err": err, "dist": d}))
        else:
            stop()
        time.sleep(0.12)
    stop()
    attack(False)
    return snapshot(), entity(eid), "timeout"


def defend(max_s=30.0):
    """Kill whoever is hitting us, closest first. Returns (snapshot, killed)."""
    killed = []
    deadline = time.time() + max_s
    while time.time() < deadline:
        s = snapshot()
        if not s.get("ok") or s.get("dead"):
            return s, killed
        aggro = attackers(s)
        if not aggro:
            break
        mob = aggro[0]
        rec = {
            "id": mob.get("id"),
            "name": mob.get("name"),
            "level": mob.get("level"),
            "dist": mob.get("dist"),
            "hp": mob.get("hp"),
            "xyz": xyz_of(mob),
            "templateId": mob.get("templateId"),
        }
        why_flee = flee_reason(mob, s.get("level"), attacker_count=len(aggro))
        if why_flee or should_reset(s, aggro):
            print(
                "FLEE",
                why_flee or "low_hp",
                json.dumps({**rec, "attackers": len(aggro), "player_level": s.get("level"), "hp": s.get("hp")}),
            )
            reset_combat(s)
            return snapshot(), killed
        print("DEFEND", json.dumps(rec))
        remain = max(6.0, deadline - time.time())
        s, dead_mob, why = fight_entity(mob["id"], max_s=remain)
        if why == "dead":
            rec = {"id": mob.get("id"), "name": mob.get("name"), "level": mob.get("level")}
            killed.append(rec)
            leftover = attackers(s)
            if dead_mob and not leftover:
                target(dead_mob["id"])
                interact()
                time.sleep(0.2)
        elif why == "we_died":
            return s, killed
    stop()
    attack(False)
    return snapshot(), killed


def wait_or_defend(seconds):
    """Sleep, but break immediately to kill anything that aggroes."""
    t0 = time.time()
    while time.time() - t0 < seconds:
        s = snapshot()
        if not s.get("ok") or s.get("dead"):
            return s, []
        if attackers(s):
            if should_reset(s):
                print("FLEE wait_or_defend", json.dumps({"hp": s.get("hp"), "adds": len(attackers(s))}))
                reset_combat(s)
                return snapshot(), []
            return defend()
        time.sleep(0.12 if s.get("inCombat") else 0.3)
    return snapshot(), []


def radar(s=None, kinds=("mob", "npc"), radius=160.0, include_dead=True):
    """Every loaded NPC/mob with live xyz, nearest first."""
    s = s or snapshot()
    want = None if kinds is None else set(kinds)
    out = []
    for e in s.get("ents") or []:
        if want is not None and e.get("kind") not in want:
            continue
        if not include_dead and e.get("dead"):
            continue
        if radius is not None and (e.get("dist") or 0) > radius:
            continue
        out.append(e)
    return out


def radar_brief(s=None, kinds=("mob", "npc"), radius=160.0):
    rows = []
    for e in radar(s, kinds=kinds, radius=radius):
        rows.append(
            {
                "id": e.get("id"),
                "kind": e.get("kind"),
                "name": e.get("name"),
                "level": e.get("level"),
                "xyz": xyz_of(e),
                "dist": e.get("dist"),
                "hostile": bool(e.get("hostile")),
                "dead": bool(e.get("dead")),
                "hp": e.get("hp"),
                "targetId": e.get("targetId"),
            }
        )
    return rows


def nearby_hostiles(s=None, origin=None, ignore_id=None, radius=CROWD_RADIUS):
    """Living hostiles within `radius` of origin (default: the player)."""
    s = s or snapshot()
    if origin is None:
        ox, oz = s.get("x") or 0.0, s.get("z") or 0.0
    else:
        ox, oz = origin
    out = []
    for h in living_hostiles(s):
        if ignore_id is not None and h.get("id") == ignore_id:
            continue
        if dist(ox, oz, h["x"], h["z"]) <= radius:
            out.append(h)
    out.sort(key=lambda e: dist(ox, oz, e["x"], e["z"]))
    return out


def crowd_around(mob, hostiles, radius=CROWD_RADIUS):
    n = 0
    for h in hostiles:
        if h.get("id") == mob.get("id"):
            continue
        if dist(mob["x"], mob["z"], h["x"], h["z"]) <= radius:
            n += 1
    return n


def isolation(mob, hostiles):
    others = [h for h in hostiles if h["id"] != mob["id"]]
    if not others:
        return 999.0
    return min(dist(mob["x"], mob["z"], h["x"], h["z"]) for h in others)


def _seg_dist(px, pz, ax, az, bx, bz):
    dx, dz = bx - ax, bz - az
    len2 = dx * dx + dz * dz
    if len2 <= 1e-6:
        return dist(px, pz, ax, az)
    t = max(0.0, min(1.0, ((px - ax) * dx + (pz - az) * dz) / len2))
    return dist(px, pz, ax + t * dx, az + t * dz)


def _beyond_mob(ax, az, mob, px, pz, slop=0.92):
    """True if (px,pz) is on the far side of the mob from (ax,az)."""
    mx = (mob.get("x") or 0.0) - ax
    mz = (mob.get("z") or 0.0) - az
    dx, dz = px - ax, pz - az
    len2 = mx * mx + mz * mz
    if len2 <= 1e-6:
        return False
    return (dx * mx + dz * mz) / len2 > slop


def path_clearance(ax, az, bx, bz, hostiles, ignore_id=None):
    """How far the closest other hostile sits from the walk line."""
    best = 999.0
    for h in hostiles:
        if ignore_id is not None and h["id"] == ignore_id:
            continue
        best = min(best, _seg_dist(h["x"], h["z"], ax, az, bx, bz))
    return best


def path_margin(ax, az, bx, bz, hostiles, player_level, ignore_id=None):
    """Smallest (distance - keepaway). Negative means the line clips a bubble."""
    best = 999.0
    for h in hostiles:
        if ignore_id is not None and h["id"] == ignore_id:
            continue
        d = _seg_dist(h["x"], h["z"], ax, az, bx, bz)
        best = min(best, d - keepaway_for(h, player_level))
    return best


def nearest_danger_dist(x, z, hostiles, player_level, ignore_id=None):
    best = 999.0
    hit = None
    for h in hostiles:
        if ignore_id is not None and h.get("id") == ignore_id:
            continue
        if not is_danger(h, player_level):
            continue
        d = dist(x, z, h["x"], h["z"])
        if d < best:
            best = d
            hit = h
    return best, hit


def route_danger_clearance(ax, az, waypoints, hostiles, player_level, ignore_id=None):
    best = 999.0
    cx, cz = ax, az
    for wx, wz in waypoints:
        for h in hostiles:
            if ignore_id is not None and h.get("id") == ignore_id:
                continue
            if not is_danger(h, player_level):
                continue
            best = min(best, _seg_dist(h["x"], h["z"], cx, cz, wx, wz))
        cx, cz = wx, wz
    return best


def route_clips_danger(ax, az, waypoints, hostiles, player_level, ignore_id=None):
    """True if the walk line enters a danger mob's keepaway."""
    cx, cz = ax, az
    for wx, wz in waypoints:
        for h in hostiles:
            if ignore_id is not None and h.get("id") == ignore_id:
                continue
            if not is_danger(h, player_level):
                continue
            if _seg_dist(h["x"], h["z"], cx, cz, wx, wz) < keepaway_for(h, player_level):
                return True
        cx, cz = wx, wz
    return False


def danger_leash(mob, hostiles, player_level):
    """Yards of slack to the nearest danger keepaway. Negative = inside the bubble."""
    best = 999.0
    for h in hostiles:
        if h.get("id") == mob.get("id"):
            continue
        if not is_danger(h, player_level):
            continue
        slack = dist(mob["x"], mob["z"], h["x"], h["z"]) - keepaway_for(h, player_level)
        if slack < best:
            best = slack
    return best


def route_to(ax, az, bx, bz, hostiles, ignore_id=None, min_clear=10.0, offset=14.0, max_hops=4, player_level=1):
    """Walkpoints from A to B that bend around other NPC xyz instead of through them."""
    pts = []
    cx, cz = ax, az
    used = set()
    for _ in range(max_hops):
        blocker = None
        blocker_margin = 0.0
        for h in hostiles:
            hid = h.get("id")
            if ignore_id is not None and hid == ignore_id:
                continue
            if hid in used:
                continue
            d = _seg_dist(h["x"], h["z"], cx, cz, bx, bz)
            keep = max(min_clear, keepaway_for(h, player_level))
            margin = d - keep
            if margin < 0 and (blocker is None or margin < blocker_margin):
                blocker_margin = margin
                blocker = h
        if blocker is None:
            pts.append((bx, bz))
            return pts
        used.add(blocker["id"])
        hop = max(offset, keepaway_for(blocker, player_level) + 4.0)
        dx, dz = bx - cx, bz - cz
        length = math.hypot(dx, dz) or 1.0
        px, pz = -dz / length, dx / length
        ox, oz = blocker["x"], blocker["z"]
        left = (ox + px * hop, oz + pz * hop)
        right = (ox - px * hop, oz - pz * hop)

        def _score(pt):
            return min(
                path_margin(cx, cz, pt[0], pt[1], hostiles, player_level, ignore_id),
                path_margin(pt[0], pt[1], bx, bz, hostiles, player_level, ignore_id),
            )

        side = left if _score(left) >= _score(right) else right
        # Never detour past the mob we are walking up to.
        if ignore_id is not None:
            blocker_mob = next((h for h in hostiles if h.get("id") == ignore_id), None)
            if blocker_mob and _beyond_mob(ax, az, blocker_mob, side[0], side[1]):
                other = right if side is left else left
                if not _beyond_mob(ax, az, blocker_mob, other[0], other[1]):
                    side = other
                else:
                    pts.append((bx, bz))
                    return pts
        pts.append((round(side[0], 2), round(side[1], 2)))
        cx, cz = side
    pts.append((bx, bz))
    return pts


def route_clearance(ax, az, waypoints, hostiles, ignore_id=None):
    cx, cz = ax, az
    best = 999.0
    for wx, wz in waypoints:
        best = min(best, path_clearance(cx, cz, wx, wz, hostiles, ignore_id))
        cx, cz = wx, wz
    return best


def next_step_toward(s, dest_x, dest_z, hostiles, ignore_id=None, min_clear=10.0):
    """First live walkpoint toward dest, given every nearby hostile xyz."""
    route = route_to(
        s["x"],
        s["z"],
        dest_x,
        dest_z,
        hostiles,
        ignore_id,
        min_clear=min_clear,
        player_level=s.get("level") or 1,
    )
    if not route:
        return dest_x, dest_z, []
    wx, wz = route[0]
    if dist(s["x"], s["z"], wx, wz) <= 3.0 and len(route) > 1:
        wx, wz = route[1]
    if ignore_id is not None:
        mob = next((h for h in hostiles if h.get("id") == ignore_id), None)
        if mob and _beyond_mob(s["x"], s["z"], mob, wx, wz):
            return dest_x, dest_z, route
    return wx, wz, route


def staging_for(mob, hostiles, me=None, player_level=1):
    """Stand off the wolf, on the side away from its nearest neighbor."""
    others = [h for h in hostiles if h["id"] != mob["id"]]
    spots = []
    if others:
        n = min(others, key=lambda h: dist(mob["x"], mob["z"], h["x"], h["z"]))
        dx, dz = mob["x"] - n["x"], mob["z"] - n["z"]
        L = math.hypot(dx, dz) or 1.0
        spots.append((mob["x"] + dx / L * PULL_RANGE, mob["z"] + dz / L * PULL_RANGE, "away"))
    spots.extend(
        [
            (mob["x"], mob["z"] - PULL_RANGE, "south"),
            (mob["x"] + PULL_RANGE, mob["z"], "east"),
            (mob["x"] - PULL_RANGE, mob["z"], "west"),
            (mob["x"], mob["z"] + PULL_RANGE, "north"),
        ]
    )
    sx0, sz0 = (me["x"], me["z"]) if me else (0.0, 0.0)
    # Prefer standing south of the pack (toward town). North staging walks us
    # through the wolf and into the deep woods.
    tag_bias = {"south": 8.0, "away": 4.0, "east": 1.0, "west": 1.0, "north": -12.0}
    best = None
    best_score = None
    for sx, sz, tag in spots:
        path = path_clearance(sx0, sz0, sx, sz, hostiles, ignore_id=mob["id"])
        score = path + tag_bias.get(tag, 0.0)
        # Far-side spots require walking through the wolf. Never prefer those.
        if me and _beyond_mob(sx0, sz0, mob, sx, sz):
            score -= 40.0
        dng, _hit = nearest_danger_dist(sx, sz, hostiles, player_level, ignore_id=mob["id"])
        if dng < DANGER_KEEP:
            score -= 80.0
        rec = {"x": sx, "z": sz, "tag": tag, "path": round(path, 2), "danger": round(dng, 2)}
        if best is None or score > best_score:
            best = rec
            best_score = score
    return best


def pick_isolated(name_sub=None, level=None, min_level=None, max_level=None, min_iso=ISOLATION_MIN, hostiles=None, min_path=8.0):
    s = snapshot()
    player_level = s.get("level") or 1
    hostiles = hostiles if hostiles is not None else living_hostiles(s)
    blockers = living_blockers(s, player_level)
    needle = name_sub if name_sub is not None else HUNT_NAME
    cands = []
    who = s.get("name") or wanted_player() or SAFESPOT_OWNER
    for h in hostiles:
        if not hunt_name_match(h, needle):
            continue
        lv = h.get("level")
        if level is not None and lv != level:
            continue
        skip = None
        if not h.get("hostile"):
            skip = "friendly"
        elif not is_hunt_mob(h, player_level):
            rare, elite = template_flags(h)
            if rare:
                skip = "rare"
            elif elite:
                skip = "elite"
            elif is_overlevel(h, player_level):
                skip = "over_level"
            elif min_level is not None and (lv is None or lv < min_level):
                skip = "low_level"
            elif max_level is not None and (lv is None or lv > max_level):
                skip = "high_level"
            else:
                skip = "not_hunt"
        elif dest_is_foreign_home(h["x"], h["z"], who):
            skip = "other_camp"
        elif SAFESPOT and dist(h["x"], h["z"], SAFESPOT["x"], SAFESPOT["z"]) > PULL_FAR_YARDS:
            skip = "far_from_home"
        if skip:
            cands.append({**h, "why": skip, "xyz": xyz_of(h), "isolation": 0, "path": 0, "danger": 0, "mob_danger": 0, "crowd": 0, "leash": 0, "stage": None, "route": []})
            continue
        iso = isolation(h, hostiles)
        stage = staging_for(h, blockers, s, player_level=player_level)
        stand_x, stand_z = _stand_off(h, s, PULL_RANGE)
        dest_x, dest_z = stand_x, stand_z
        if stage and not _beyond_mob(s["x"], s["z"], h, stage["x"], stage["z"]):
            dest_x, dest_z = stage["x"], stage["z"]
        route = route_to(
            s["x"], s["z"], dest_x, dest_z, blockers, ignore_id=h["id"], player_level=player_level
        )
        if any(_beyond_mob(s["x"], s["z"], h, wx, wz) for wx, wz in route):
            route = [(dest_x, dest_z)]
        path = route_clearance(s["x"], s["z"], route, blockers, ignore_id=h["id"])
        danger = route_danger_clearance(s["x"], s["z"], route, blockers, player_level, ignore_id=h["id"])
        dest_danger, _ = nearest_danger_dist(dest_x, dest_z, blockers, player_level, ignore_id=h["id"])
        mob_danger, _ = nearest_danger_dist(h["x"], h["z"], blockers, player_level, ignore_id=h["id"])
        # Isolation / path / dest_crowd are sort hints only. A packed camp
        # is still a pull. Hard rejects are: walking *through* an elite or
        # over-level keepaway, or the mob itself sitting inside one (pull
        # will leech Captain Verlan). dest_danger used to compare against
        # a flat 22y and rejected every chapel bone from our stand-off.
        crowd = crowd_around(h, hostiles, CROWD_RADIUS)
        dest_crowd = len(
            [o for o in hostiles if o.get("id") != h["id"] and dist(dest_x, dest_z, o["x"], o["z"]) <= CROWD_RADIUS]
        )
        leash = danger_leash(h, blockers, player_level)
        why = None
        if route_clips_danger(s["x"], s["z"], route, blockers, player_level, ignore_id=h["id"]):
            why = "route_danger"
        elif leash < 0:
            why = "on_danger"
        d_home = dist(h["x"], h["z"], SAFESPOT["x"], SAFESPOT["z"]) if SAFESPOT else (h.get("dist") or 99)
        cands.append(
            {
                **h,
                "isolation": round(iso, 2),
                "path": round(path, 2),
                "danger": round(min(danger, dest_danger), 2),
                "mob_danger": round(mob_danger, 2),
                "crowd": crowd,
                "leash": round(leash, 2),
                "why": why,
                "stage": stage,
                "route": [{"x": round(wx, 2), "z": round(wz, 2)} for wx, wz in route],
                "xyz": xyz_of(h),
                "d_home": round(d_home, 1),
                "near": d_home <= PULL_NEAR_YARDS,
            }
        )
    legal = [c for c in cands if c.get("why") is None or c.get("why") in ("route_danger", "on_danger")]
    legal.sort(key=lambda c: (c.get("dist") or 99.0, -((c.get("level") or 1))))
    near = [c for c in legal if c.get("near")]
    pick = near[0] if near else (legal[0] if legal else None)
    return pick, cands


def move(flags, facing=None):
    global HOME_WALKED
    if flags and (flags.get("forward") or flags.get("back") or flags.get("strafeLeft") or flags.get("strafeRight")):
        HOME_WALKED = True
    payload = json.dumps(dict(flags))
    if facing is None:
        j(f"window.__game.controller.move({payload})")
    else:
        j(f"window.__game.controller.move({payload}, {float(facing)})")


def face(radians):
    j(f"window.__game.controller.face({float(radians)})")


def target(eid):
    if eid is None:
        j("window.__game.world.targetEntity(null)")
    else:
        j(f"window.__game.world.targetEntity({int(eid)})")


def ensure_hostile_target(eid, s=None):
    """Keep the fight on eid. A click on ourselves (or nothing) must not stick."""
    if eid is None:
        return s or snapshot()
    s = s or snapshot()
    pid = s.get("id")
    cur = s.get("targetId")
    if cur == eid:
        return s
    if cur == pid or cur is None:
        print("RETARGET", json.dumps({"from": cur, "to": eid, "reason": "self_or_empty"}))
    target(eid)
    return snapshot()


def cast(ability_id, eid=None):
    # castAbilityOn sends the mob id on the wire so a self-click cannot steal the bolt.
    if eid is None:
        j(f"window.__game.world.castAbility({ability_id!r})")
    else:
        ensure_hostile_target(eid)
        j(f"window.__game.world.castAbilityOn({ability_id!r}, {int(eid)})")


def hud_error():
    """Server reject text (e.g. 'Line of sight.') from the HUD error line."""
    return (
        j(
            r"""
(() => {
  const hud = window.__game && window.__game.hud;
  if (!hud) return '';
  const el = hud.errorEl;
  const t = (hud.lastMirroredErrorText || (el && (el.innerText || el.textContent)) || '').trim();
  return t;
})()
"""
        )
        or ""
    )


def clear_hud_error():
    j(
        r"""
(() => {
  const hud = window.__game && window.__game.hud;
  if (!hud) return;
  hud.lastMirroredErrorText = '';
  if (hud.errorEl) hud.errorEl.textContent = '';
})()
"""
    )


def is_los_error(err):
    t = (err or "").lower()
    return "line of sight" in t or "can't see" in t or "cannot see" in t


_KNOWN = None
_UNKNOWN = set()


def mark_unknown_ability(ability_id):
    if ability_id:
        _UNKNOWN.add(str(ability_id))


def known_abilities():
    """Ability ids the character actually knows. frost_armor is not on this fire spec."""
    global _KNOWN
    if _KNOWN is None:
        ids = (
            j(
                r"""
(() => {
  const w = window.__game && window.__game.world;
  const K = w && w.known;
  const out = [];
  const walk = (v) => {
    if (!v) return;
    const d = v.def || v;
    const id = d.id || v.id;
    if (id) out.push(String(id));
  };
  if (K && typeof K.forEach === 'function') K.forEach(walk);
  else if (Array.isArray(K)) K.forEach(walk);
  else if (K) Object.values(K).forEach(walk);
  return out;
})()
"""
            )
            or []
        )
        _KNOWN = {str(i) for i in ids}
    return _KNOWN


def knows_ability(ability_id):
    if not ability_id:
        return False
    aid = str(ability_id)
    if aid in _UNKNOWN:
        return False
    known = known_abilities()
    if not known:
        return True
    return aid in known


def is_unknown_ability_error(err):
    t = (err or "").lower()
    return "do not know" in t or "don't know" in t or "unknown ability" in t or "not learned" in t


def is_busy_error(err):
    t = (err or "").lower()
    return (
        "busy" in t
        or "already casting" in t
        or "not ready" in t
        or "can't do that yet" in t
        or "cannot do that yet" in t
    )


def is_casting(s=None):
    s = s or snapshot()
    return bool(s.get("castingAbility") or (s.get("castRemaining") or 0) > 0.05)


def wait_until_ready(timeout=3.5, also_stop=True):
    """Block until we are not mid-cast or on GCD. Moving/autoattack can also busy a press."""
    if also_stop:
        stop()
    t0 = time.time()
    s = snapshot()
    while time.time() - t0 < timeout:
        if not s.get("ok") or s.get("dead"):
            return s
        if not casting_or_gcd(s):
            return s
        time.sleep(0.05)
        s = snapshot()
    return s


def try_cast(ability_id, eid=None, wait=0.4, retries=3):
    """Press a cast. Returns (started, error, snapshot).

    Waits out an in-progress cast/GCD first. 'You are busy' retries instead of
    giving up. Instants never set castingAbility, so aura/cooldown is success.
    """
    err = ""
    s = snapshot()
    if not knows_ability(ability_id):
        mark_unknown_ability(ability_id)
        return False, "unknown_ability", s
    for attempt in range(max(1, retries)):
        s = wait_until_ready(timeout=3.5)
        if not s.get("ok") or s.get("dead"):
            return False, err or "dead", s
        if eid is not None:
            ensure_hostile_target(eid, s)
        clear_hud_error()
        had_aura = has_aura(s, ability_id)
        cd_before = cooldown_remaining(ability_id, s)
        cast(ability_id, eid)
        t0 = time.time()
        err = ""
        while time.time() - t0 < wait:
            s = snapshot()
            if s.get("castingAbility") == ability_id or (s.get("castRemaining") or 0) > 0.08:
                return True, "", s
            if not had_aura and has_aura(s, ability_id):
                return True, "", s
            if cooldown_remaining(ability_id, s) > cd_before + 0.2:
                return True, "", s
            err = hud_error()
            if err:
                break
            time.sleep(0.05)
        if not err:
            err = hud_error()
        if is_unknown_ability_error(err):
            mark_unknown_ability(ability_id)
            print("CAST skip unknown", ability_id)
            return False, "unknown_ability", snapshot()
        if is_busy_error(err) and attempt + 1 < retries:
            print("CAST busy, retry", json.dumps({"spell": ability_id, "attempt": attempt + 1, "err": err}))
            time.sleep(0.12)
            continue
        if err:
            return False, err, snapshot()
        # Instant with no HUD reject and no hard-cast flag still counts.
        s = snapshot()
        if not had_aura and has_aura(s, ability_id):
            return True, "", s
        if cooldown_remaining(ability_id, s) > cd_before + 0.2:
            return True, "", s
        if not is_casting(s) and not err and attempt + 1 < retries:
            time.sleep(0.1)
            continue
        return False, err, s
    return False, err, snapshot()


def nudge_clear_los(tx, tz, attempt=0, yards=4.5, max_s=0.65):
    """Step off the blocked line. Left, right, then down toward the target."""
    stop()
    s = snapshot()
    if not s.get("ok"):
        return s
    ang = face_to(tx, tz, s["x"], s["z"])
    # Never walk toward the mob. Forward chase is how we leave the safespot.
    step = attempt % 2
    if step == 0:
        flags, move_ang = {"strafeLeft": True}, ang
    else:
        flags, move_ang = {"strafeRight": True}, ang
    move(flags, move_ang)
    t0 = time.time()
    sx, sz = s["x"], s["z"]
    while time.time() - t0 < max_s:
        s = snapshot()
        if not s.get("ok") or s.get("dead"):
            break
        if dist(s["x"], s["z"], sx, sz) >= yards:
            break
        time.sleep(0.08)
    stop()
    s = snapshot()
    if s.get("ok"):
        face(face_to(tx, tz, s["x"], s["z"]))
    return s


def cast_or_clear_los(ability_id, tx, tz, eid=None, max_tries=4):
    """Cast, and if LoS/facing blocks it, sidestep and retry."""
    started, err, s = try_cast(ability_id, eid)
    if started:
        return True, err, s
    need = is_los_error(err) or "facing" in (err or "").lower()
    if "no target" in (err or "").lower() and eid is not None:
        ensure_hostile_target(eid)
        started, err, s = try_cast(ability_id, eid)
        if started:
            return True, err, s
        need = is_los_error(err) or "facing" in (err or "").lower()
    if not need:
        return False, err, s
    for i in range(max_tries):
        print("LOS nudge", json.dumps({"attempt": i, "err": err, "pos": [s.get("x"), s.get("z")]}))
        s = nudge_clear_los(tx, tz, attempt=i)
        if eid is not None:
            ensure_hostile_target(eid)
        started, err, s = try_cast(ability_id, eid)
        if started:
            return True, err, s
        if not (is_los_error(err) or "facing" in (err or "").lower()):
            return False, err, s
    return False, err, s


def attack(on=True):
    # Slot 1 is a toggle. Always call start/stop, never press the slot, or we flip it off.
    if on:
        j("window.__game.world.startAutoAttack()")
    else:
        j("window.__game.world.stopAutoAttack()")


def keep_autoattack(s=None):
    """Turn Attack (1) on if it dropped. world.castAbility bypasses the bar's start-attack-on-cast."""
    s = s or snapshot()
    if not s.get("autoAttack"):
        attack(True)
        return True
    return False


def cooldown_remaining(ability_id, s=None):
    s = s or snapshot()
    cds = s.get("cooldowns") or {}
    return float(cds.get(ability_id) or 0)


def is_rooted(eid):
    return bool(
        j(
            f"""
(() => {{
  const e = window.__game.world.entities.get({int(eid)});
  if (!e || !Array.isArray(e.auras)) return false;
  return e.auras.some((a) => {{
    const id = String(a.id || '').toLowerCase();
    const n = String(a.name || '').toLowerCase();
    const k = String(a.kind || '').toLowerCase();
    return id.includes('root') || id.includes('nova') || id.includes('icebind') || id.includes('freeze')
      || n.includes('root') || n.includes('icebind') || k.includes('root');
  }});
}})()
"""
        )
    )


def nova_is_safe(s=None, ignore_id=None, radius=ICEBIND_RADIUS):
    """Icebind is a self-centered nova. Any other hostile in the ring gets aggro."""
    s = s or snapshot()
    for h in living_hostiles(s):
        if ignore_id is not None and h.get("id") == ignore_id:
            continue
        if (h.get("dist") or 99) <= radius:
            return False
    return True


def pick_damage_spell(s, mob):
    """Cinderbolt at range. Icebind only in melee when the nova will not leech a pack."""
    if not mob or mob.get("dead"):
        return None
    mana = s.get("mana") or 0
    hp = mob.get("hp") or 0
    d = mob.get("dist") or 99
    # Icebind is a 10y self-centered AoE. Only fire it when they are already
    # in melee so the root actually lands — and never when a packmate is
    # inside the nova (that is what pulled the second bone and killed us).
    if (
        knows_ability(ICEBIND)
        and mana >= ICEBIND_COST
        and d <= MELEE_RANGE
        and cooldown_remaining(ICEBIND, s) <= 0.08
        and not is_rooted(mob["id"])
        and nova_is_safe(s, ignore_id=mob.get("id"))
    ):
        return ICEBIND
    if knows_ability(CINDERBOLT) and mana >= CINDERBOLT_COST and hp > BOLT_OVERKILL_HP and d <= CAST_RANGE:
        return CINDERBOLT
    return None


def hold_safespot(stop_at=4.0):
    """Stay planted at home. If a LoS strafe drifted us, step back — never chase."""
    s = snapshot()
    if not s.get("ok") or s.get("dead"):
        return s
    if not SAFESPOT:
        stop()
        return s
    if not snapshot_is_ours(s):
        stop()
        return s
    who = (s.get("name") or SAFESPOT_OWNER or wanted_player() or "").strip()
    if dest_is_foreign_home(SAFESPOT["x"], SAFESPOT["z"], who):
        stop()
        return s
    d = dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"])
    if d <= stop_at:
        stop()
        return s
    if d > HOME_HOLD_YARDS:
        # Farther than a fight drift — walking here is how we crossed the map.
        stop()
        return s
    ang = face_to(SAFESPOT["x"], SAFESPOT["z"], s["x"], s["z"])
    move({"forward": True}, ang)
    return s


def press_damage(eid, mob, s=None, max_los_tries=3, planted=True):
    """Cast the next 2-4 damage spell at eid. Returns (ability_id or None, started, error)."""
    s = s or snapshot()
    spell = pick_damage_spell(s, mob)
    if not spell:
        return None, False, ""
    s = wait_until_ready(timeout=3.0)
    ensure_hostile_target(eid, s)
    face(face_to(mob["x"], mob["z"], s["x"], s["z"]))
    if spell == ICEBIND:
        started, err, _s = try_cast(spell, eid)
        return spell, started, err
    started, err, _s = cast_or_clear_los(spell, mob["x"], mob["z"], eid=eid, max_tries=max_los_tries)
    return spell, started, err


def press_blazing_barrier(s=None):
    """Bar 5. Instant self shield. Press after the first Cinderbolt of a pull."""
    s = s or snapshot()
    if not knows_ability(BLAZING_BARRIER):
        return False, "unknown_ability", s
    s = wait_until_ready(timeout=3.5)
    if has_aura(s, BLAZING_BARRIER):
        return False, "already", s
    if cooldown_remaining(BLAZING_BARRIER, s) > 0.08:
        return False, "cd", s
    if (s.get("mana") or 0) < BLAZING_BARRIER_COST:
        return False, "mana", s
    started, err, s = try_cast(BLAZING_BARRIER)
    return started, err, s


def after_first_cinderbolt(s=None):
    """Wait out the hard cast and GCD, then hit Blazing Barrier."""
    s = wait_while_casting(timeout=CINDERBOLT_CAST + 1.6, abort_on_attack=False)
    if not s.get("ok") or s.get("dead"):
        return False, "dead" if s.get("dead") else "no_game", s
    s = wait_until_ready(timeout=2.5)
    started, err, s = press_blazing_barrier(s)
    print("BAR5 blazing_barrier", json.dumps({"started": started, "err": err or None, "mana": s.get("mana")}))
    return started, err, s


def tag_with_attack(eid, timeout=0.55):
    """Pull tag: bar 1 only. Plant just long enough for the wand/swing to fire, then the caller runs."""
    s = snapshot()
    mob = entity(eid)
    if not mob or mob.get("dead"):
        return s, False
    stop()
    s = ensure_hostile_target(eid, s)
    face(face_to(mob["x"], mob["z"], s["x"], s["z"]))
    attack(True)
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = snapshot()
        if any(e.get("id") == eid for e in attackers(s)):
            return s, True
        mob = entity(eid)
        if mob and (mob.get("targetId") == s.get("id") or mob.get("aggroTargetId") == s.get("id")):
            return s, True
        time.sleep(0.04)
    s = snapshot()
    tagged = s.get("autoAttack") or any(e.get("id") == eid for e in attackers(s))
    return s, bool(tagged)


def home_cinder_then_barrier(eid):
    """At the safespot: Cinderbolt, then Blazing Barrier. Never do this in the camp."""
    stop()
    s = wait_until_ready(timeout=2.5)
    mob = entity(eid)
    if not mob or mob.get("dead") or s.get("dead"):
        return False, "gone", False, "", s
    s = ensure_hostile_target(eid, s)
    face(face_to(mob["x"], mob["z"], s["x"], s["z"]))
    attack(True)
    started, err, s = try_cast(CINDERBOLT, eid)
    print("HOME cinderbolt", json.dumps({"started": started, "err": err or None}))
    if not started:
        return False, err, False, "", s
    started5, err5, s = after_first_cinderbolt(s)
    return True, err, started5, err5, s


def casting_or_gcd(s=None):
    s = s or snapshot()
    if s.get("castingAbility"):
        return True
    if (s.get("castRemaining") or 0) > 0.08:
        return True
    if (s.get("gcdRemaining") or 0) > 0.08:
        return True
    return False


def interact():
    j("window.__game.world.interact()")


def use_item(item_id):
    j(f"window.__game.world.useItem({item_id!r})")


def has_aura(s, aura_id):
    return any(a.get("id") == aura_id for a in s.get("auras") or [])


def aura_remaining(s, aura_id):
    aura = next((a for a in s.get("auras") or [] if a.get("id") == aura_id), None)
    return (aura or {}).get("remaining", 0) or 0


def ensure_buffs(min_remaining=BUFF_REFRESH_REMAINING):
    """Keep known self-buffs up. Skip anything not learned (no frost_armor on fire)."""
    s = snapshot()
    if (
        knows_ability(MANTLE)
        and aura_remaining(s, MANTLE) < min_remaining
        and (s.get("mana") or 0) >= MANTLE_COST
    ):
        cast(MANTLE)
        time.sleep(0.3)
        s = snapshot()
    if (
        knows_ability(INSIGHT)
        and aura_remaining(s, INSIGHT) < min_remaining
        and (s.get("mana") or 0) >= INSIGHT_COST
    ):
        # Insight is buffTarget/party. Land it on us, then put the fight target back.
        had = s.get("targetId")
        pid = s.get("id")
        target(pid or None)
        cast(INSIGHT)
        time.sleep(0.3)
        s = snapshot()
        restore = had if had and had != pid else None
        if restore is None:
            aggro = attackers(s)
            if aggro:
                restore = aggro[0]["id"]
        if restore:
            ensure_hostile_target(restore, s)
        s = snapshot()
    return s


def ensure_mantle(min_remaining=BUFF_REFRESH_REMAINING):
    return ensure_buffs(min_remaining=min_remaining)


def _stand_off(mob, me, yards):
    """Point `yards` from the mob, on the side we already occupy."""
    dx, dz = me["x"] - mob["x"], me["z"] - mob["z"]
    length = math.hypot(dx, dz) or 1.0
    return mob["x"] + dx / length * yards, mob["z"] + dz / length * yards


def move_toward(
    tx,
    tz,
    stop_at=4.0,
    max_s=20.0,
    jump=True,
    ignore_id=None,
    add_radius=12.0,
    avoid=True,
    abort_adds=True,
    abort_danger=True,
):
    """Walk toward a point. Pulses jump so fences and slope lips do not pin us."""
    t0 = time.time()
    last = snapshot()
    last_pos_t = t0
    stuck_hits = 0
    while time.time() - t0 < max_s:
        s = snapshot()
        if not s.get("ok") or s.get("dead"):
            stop()
            return s
        if not snapshot_is_ours(s):
            stop()
            return s
        who = s.get("name") or wanted_player() or SAFESPOT_OWNER
        if dest_is_foreign_home(tx, tz, who):
            stop()
            return s
        if SAFESPOT:
            dest_is_home = dist(tx, tz, SAFESPOT["x"], SAFESPOT["z"]) <= 6.0
            if not dest_is_home:
                if dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"]) > 35.0:
                    stop()
                    return s
                if dist(tx, tz, SAFESPOT["x"], SAFESPOT["z"]) > 40.0:
                    stop()
                    return s
        if attackers(s):
            stop()
            s["aborted_adds"] = True
            return s
        if abort_adds and adds_on_us(s, ignore_id=ignore_id, radius=add_radius):
            stop()
            s["aborted_adds"] = True
            return s
        if abort_danger and danger_nearby(s, ignore_id=ignore_id):
            stop()
            s["aborted_danger"] = True
            return s
        d = dist(s["x"], s["z"], tx, tz)
        if d <= stop_at:
            stop()
            return s
        wx, wz = tx, tz
        if avoid:
            hostiles = living_blockers(s, s.get("level") or 1)
            wx, wz, _route = next_step_toward(s, tx, tz, hostiles, ignore_id=ignore_id)
        ang = face_to(wx, wz, s["x"], s["z"])
        now = time.time()
        moved = dist(s["x"], s["z"], last["x"], last["z"]) if last else 1
        stuck = (now - last_pos_t) > 0.45 and moved < 0.35
        if stuck:
            stuck_hits += 1
            last = s
            last_pos_t = now
        elif moved >= 0.35:
            stuck_hits = 0
            last = s
            last_pos_t = now
        pulse_jump = jump and (stuck or int((now - t0) * 10) % 12 == 0)
        move({"forward": True, "jump": pulse_jump}, ang)
        if stuck_hits >= 6:
            j("window.__game.world.unstuck()")
            stuck_hits = 0
        time.sleep(0.12)
    stop()
    return snapshot()


def approach_entity(eid, stop_at=PULL_RANGE, max_s=16.0, add_radius=12.0):
    """Short leash walk toward eid. Prefer step_out_to_tag for pulls."""
    return step_out_to_tag(eid, max_away=PULL_LEASH, max_s=min(max_s, 7.0))


def step_out_to_tag(eid, max_away=None, max_s=7.0):
    """Take a short step toward the mob so Attack can land, then stop. Never leave the leash."""
    max_away = PULL_LEASH if max_away is None else max_away
    t0 = time.time()
    while time.time() - t0 < max_s:
        s = snapshot()
        mob = entity(eid)
        if not s.get("ok") or s.get("dead") or not mob or mob.get("dead"):
            stop()
            return s, mob, "gone"
        if (mob.get("dist") or 99) <= CAST_RANGE:
            stop()
            return s, mob, "ok"
        if SAFESPOT and dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"]) >= max_away:
            stop()
            return s, mob, "leash"
        ang = face_to(mob["x"], mob["z"], s["x"], s["z"])
        move({"forward": True}, ang)
        time.sleep(0.12)
    stop()
    return snapshot(), entity(eid), "timeout"


def back_off(from_x, from_z, yards=16.0, max_s=6.0):
    """Run away from a point (usually the mob), jumping so we do not snag."""
    t0 = time.time()
    while time.time() - t0 < max_s:
        s = snapshot()
        if not s.get("ok") or s.get("dead"):
            stop()
            return s
        if attackers(s):
            stop()
            s["attacked"] = True
            return s
        d = dist(s["x"], s["z"], from_x, from_z)
        if d >= yards:
            stop()
            return s
        ang = face_to(s["x"] * 2 - from_x, s["z"] * 2 - from_z, s["x"], s["z"])
        move({"forward": True, "jump": True}, ang)
        time.sleep(0.12)
    stop()
    return snapshot()


def _npc_returning(e):
    """True when the NPC's AI has given up the chase (evade / walk home / idle)."""
    return (e.get("aiState") or "").lower() in _FLEE_RETURN_AI


def chasing_us(s=None):
    """NPCs still pursuing this character. Empty means they dropped or are walking home."""
    s = s or snapshot()
    pid = s.get("id")
    out = []
    for e in s.get("ents") or []:
        if e.get("dead") or e.get("kind") not in ("mob", "npc"):
            continue
        on_us = e.get("targetId") == pid or e.get("aggroTargetId") == pid
        if not on_us:
            continue
        if _npc_returning(e):
            continue
        out.append(e)
    out.sort(key=lambda e: (e.get("dist") or 99))
    return out


def aggro_dropped(s=None):
    """True when nobody is chasing or targeting us. inCombat may still be sticky."""
    s = s or snapshot()
    if chasing_us(s):
        return False
    if attackers(s):
        # attackers() includes a targetId we already classified as returning.
        live = [e for e in attackers(s) if not _npc_returning(e)]
        if live:
            return False
    return True


def _threat_point(s):
    """Centroid of whoever is hitting us. None if combat is already clear."""
    aggro = [e for e in attackers(s) if e.get("x") is not None and e.get("z") is not None]
    if not aggro:
        chasers = [e for e in chasing_us(s) if e.get("x") is not None and e.get("z") is not None]
        if not chasers:
            return None
        aggro = chasers
    return (
        sum(e["x"] for e in aggro) / len(aggro),
        sum(e["z"] for e in aggro) / len(aggro),
        len(aggro),
    )


def _flee_blockers(s):
    """Hostiles we must not run into. Includes hunt-band trash, not just rares."""
    out = []
    seen = set()
    for e in living_blockers(s, s.get("level") or 1):
        if not e or e.get("id") in seen:
            continue
        if e.get("x") is None or e.get("z") is None:
            continue
        if (e.get("dist") or 99) > 48.0:
            continue
        seen.add(e.get("id"))
        out.append(e)
    return out


def _flee_away_ang(s, from_x, from_z):
    """Fallback: opposite the pack, or opposite home if we are standing on it."""
    dx = s["x"] - from_x
    dz = s["z"] - from_z
    if math.hypot(dx, dz) < 1.5:
        if SAFESPOT:
            hx = s["x"] - SAFESPOT["x"]
            hz = s["z"] - SAFESPOT["z"]
            if math.hypot(hx, hz) > 1.0:
                return face_to(s["x"] + hx, s["z"] + hz, s["x"], s["z"])
        return s.get("facing") or 0.0
    return face_to(s["x"] + dx, s["z"] + dz, s["x"], s["z"])


def _flee_heading(s, from_x, from_z):
    """Pick the gap: away from the pack AND not through any other camp."""
    player_level = s.get("level") or 1
    away = _flee_away_ang(s, from_x, from_z)
    chaser_ids = {e.get("id") for e in chasing_us(s)} | {e.get("id") for e in attackers(s)}
    others = [h for h in _flee_blockers(s) if h.get("id") not in chaser_ids]
    lookahead = 28.0
    best_ang = away
    best_score = None
    for i in range(16):
        ang = i * (math.pi / 8.0)
        tx = s["x"] + math.sin(ang) * lookahead
        tz = s["z"] + math.cos(ang) * lookahead
        if others:
            clear = path_clearance(s["x"], s["z"], tx, tz, others)
            margin = path_margin(s["x"], s["z"], tx, tz, others, player_level)
            end_near = min(dist(tx, tz, h["x"], h["z"]) for h in others)
        else:
            clear, margin, end_near = 99.0, 99.0, 99.0
        align = math.cos(ang - away)
        score = end_near * 2.6 + margin * 2.2 + clear * 0.4 + align * 6.0
        if end_near < DANGER_KEEP:
            score -= 35.0
        if margin < 0:
            score -= 28.0
        if SAFESPOT:
            d_home = dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"])
            if d_home < 16.0:
                home_ang = face_to(SAFESPOT["x"], SAFESPOT["z"], s["x"], s["z"])
                if math.cos(ang - home_ang) > 0.5:
                    score -= 18.0
        if best_score is None or score > best_score:
            best_score = score
            best_ang = ang
    return best_ang


def _flee_line_clear(s, ang, yards=28.0):
    """True if blinking/running this heading will not clip another camp."""
    others = [h for h in _flee_blockers(s) if h.get("id") not in ({e.get("id") for e in chasing_us(s)} | {e.get("id") for e in attackers(s)})]
    if not others:
        return True
    tx = s["x"] + math.sin(ang) * yards
    tz = s["z"] + math.cos(ang) * yards
    return path_margin(s["x"], s["z"], tx, tz, others, s.get("level") or 1) >= 8.0


def flee_away(from_x=None, from_z=None, yards=None, max_s=16.0):
    """Sprint away from the pack. Never walks toward the safespot."""
    yards = FLEE_AWAY_YARDS if yards is None else yards
    stop()
    attack(False)
    s0 = snapshot()
    if s0.get("ok") and not s0.get("dead") and snapshot_is_ours(s0):
        threat0 = _threat_point(s0)
        if threat0:
            fx0, fz0 = threat0[0], threat0[1]
        elif from_x is not None and from_z is not None:
            fx0, fz0 = from_x, from_z
        elif SAFESPOT:
            fx0, fz0 = SAFESPOT["x"], SAFESPOT["z"]
        else:
            fx0, fz0 = s0["x"], s0["z"]
        ang0 = _flee_heading(s0, fx0, fz0)
        clear0 = _flee_line_clear(s0, ang0)
        print(
            "FLEE heading",
            json.dumps(
                {
                    "ang": round(ang0, 2),
                    "clear": clear0,
                    "others": [
                        {"id": h.get("id"), "name": h.get("name"), "dist": h.get("dist")}
                        for h in _flee_blockers(s0)[:6]
                    ],
                }
            ),
        )
        face(ang0)
        if knows_ability(BLINK) and cooldown_remaining(BLINK, s0) <= 0.08 and clear0:
            try_cast(BLINK)
    t0 = time.time()
    last = None
    last_pos_t = t0
    stuck_hits = 0
    evade_seen = {}
    while time.time() - t0 < max_s:
        s = snapshot()
        if not s.get("ok") or s.get("dead"):
            stop()
            return s
        if not snapshot_is_ours(s):
            stop()
            return s
        threat = _threat_point(s)
        if threat:
            from_x, from_z, n_at = threat
        elif from_x is None or from_z is None:
            if SAFESPOT:
                from_x, from_z = SAFESPOT["x"], SAFESPOT["z"]
            else:
                stop()
                return s
            n_at = 0
        else:
            n_at = 0
        d_threat = dist(s["x"], s["z"], from_x, from_z)
        d_home = home_dist(s)
        chasers = chasing_us(s)
        evaded = set()
        for e in list(chasers) + (attackers(s) or []):
            eid = e.get("id")
            if eid is None:
                continue
            ev = e.get("evadeEpoch") or 0
            if eid not in evade_seen:
                evade_seen[eid] = ev
            elif ev > evade_seen[eid]:
                evaded.add(eid)
        if evaded:
            chasers = [c for c in chasers if c.get("id") not in evaded]
        dropped = (not chasers) and (aggro_dropped(s) or bool(evaded))
        nearest = None
        if chasers:
            nearest = min((c.get("dist") or 99) for c in chasers)
        elif n_at:
            nearest = d_threat
        # They dropped: stop only if we are also clear of every other camp.
        nest = close_hostiles(s, FLEE_MIN_YARDS)
        if dropped and d_threat >= FLEE_MIN_YARDS and not nest:
            print(
                "FLEE dropped",
                json.dumps(
                    {
                        "dist": round(d_threat, 1),
                        "nearest": None if nearest is None else round(nearest, 1),
                        "inCombat": bool(s.get("inCombat")),
                        "chasers": [
                            {
                                "id": c.get("id"),
                                "name": c.get("name"),
                                "ai": c.get("aiState"),
                                "dist": c.get("dist"),
                            }
                            for c in chasers[:4]
                        ],
                    }
                ),
            )
            stop()
            return s
        if d_home is not None and d_home >= FLEE_HOME_MAX - 2.0:
            stop()
            return s
        # Still on us, or still inside another camp: keep running through the gap.
        ang = _flee_heading(s, from_x, from_z)
        now = time.time()
        if last is not None:
            moved = dist(s["x"], s["z"], last["x"], last["z"])
            if (now - last_pos_t) > 0.45 and moved < 0.35:
                stuck_hits += 1
                last = s
                last_pos_t = now
                ang = ang + (math.pi / 2 if stuck_hits % 2 else math.pi)
            elif moved >= 0.35:
                stuck_hits = 0
                last = s
                last_pos_t = now
        else:
            last = s
            last_pos_t = now
        move({"forward": True, "jump": True}, ang)
        time.sleep(0.12)
    stop()
    return snapshot()


def flee_from(from_x, from_z, yards=40.0, max_s=8.0):
    """Run away even if they are still hitting us. Does not walk home."""
    return flee_away(from_x, from_z, yards=yards, max_s=max_s)


def flee_to_safespot(stop_at=5.0, max_s=24.0):
    """Run away until the pack drops, then walk back to the start stamp."""
    stop()
    attack(False)
    s = snapshot()
    if not s.get("ok") or s.get("dead"):
        return s
    away_s = max(14.0, max_s)
    home_s = max(16.0, max_s)
    for attempt in range(3):
        if not s.get("ok") or s.get("dead"):
            return s
        threat = _threat_point(s)
        if threat:
            fx, fz = threat[0], threat[1]
            n_at = threat[2]
        elif SAFESPOT:
            fx, fz = SAFESPOT["x"], SAFESPOT["z"]
            n_at = 0
        else:
            fx, fz = s["x"], s["z"]
            n_at = 0
        print(
            "FLEE away",
            json.dumps(
                {
                    "from": [round(fx, 1), round(fz, 1)],
                    "me": [round(s.get("x") or 0, 1), round(s.get("z") or 0, 1)],
                    "home": SAFESPOT,
                    "adds": n_at,
                    "hp": s.get("hp"),
                    "attempt": attempt,
                }
            ),
        )
        s = flee_away(fx, fz, yards=FLEE_AWAY_YARDS, max_s=away_s)
        if not s.get("ok") or s.get("dead"):
            return s
        # They dropped, or the sprint timed out. Wait for the sticky combat lock.
        # Do not defend — that tanks the pack.
        t0 = time.time()
        picked_up = False
        while time.time() - t0 < 8.0:
            s = snapshot()
            if not s.get("ok") or s.get("dead"):
                stop()
                return s
            if chasing_us(s) or (attackers(s) and not aggro_dropped(s)):
                picked_up = True
                break
            if aggro_dropped(s) and not s.get("inCombat"):
                break
            if aggro_dropped(s) and (s.get("combatExitHoldUntil") or 0) <= 0:
                break
            time.sleep(0.2)
        if picked_up:
            continue
        if SAFESPOT:
            print(
                "FLEE home",
                json.dumps(
                    {
                        "from": [round(s.get("x") or 0, 1), round(s.get("z") or 0, 1)],
                        "to": SAFESPOT,
                        "owner": SAFESPOT_OWNER,
                    }
                ),
            )
            s = go_safespot(
                stop_at=stop_at,
                max_s=home_s,
                max_away=FLEE_HOME_MAX,
                defend_on_aggro=False,
            )
            if not s.get("ok") or s.get("dead"):
                return s
            if attackers(s):
                continue
        return s
    stop()
    return snapshot()


def adds_on_us(s, ignore_id=None, radius=ADD_ABORT_RANGE):
    extra = []
    pid = s.get("id")
    for h in s.get("ents") or []:
        if h.get("dead"):
            continue
        if ignore_id is not None and h.get("id") == ignore_id:
            continue
        if h.get("kind") not in ("mob", "npc"):
            continue
        on_us = h.get("targetId") == pid
        close = (h.get("dist") or 99) <= radius and (h.get("hostile") or on_us)
        if on_us or close:
            extra.append(h)
    extra.sort(key=lambda e: (e.get("dist") or 99))
    return extra


def item_count(s, prefixes):
    n = 0
    for it in s.get("inventory") or []:
        iid = it.get("id") or ""
        if any(iid == p or iid.startswith(p) for p in prefixes):
            n += it.get("count") or 0
    return n


def first_item(s, prefixes):
    for it in s.get("inventory") or []:
        iid = it.get("id") or ""
        if (it.get("count") or 0) <= 0:
            continue
        if any(iid == p or iid.startswith(p) for p in prefixes):
            return iid
    return None


def wait_while_casting(timeout=4.0, abort_on_attack=True):
    """Wait until a hard cast finishes. Combat pulls must pass abort_on_attack=False
    or the tagged mob makes this return mid-cast ('You are busy' on the next press)."""
    t0 = time.time()
    saw = False
    while time.time() - t0 < timeout:
        s = snapshot()
        if not s.get("ok") or s.get("dead"):
            stop()
            return s
        if abort_on_attack and attackers(s):
            stop()
            return s
        if is_casting(s):
            saw = True
        elif saw:
            return s
        time.sleep(0.08)
    return snapshot()


def is_combat_error(err):
    t = (err or "").lower()
    return "while in combat" in t


# Server keeps a combat lock after the last hit. Client inCombat often drops first.
COMBAT_DROP_SEC = 6.0


def wait_out_of_combat(timeout=14.0, settle=None):
    """Wait until we are not attacked and combat has been clear for the server drop."""
    if settle is None:
        settle = COMBAT_DROP_SEC
    t0 = time.time()
    clear_since = None
    while time.time() - t0 < timeout:
        s = snapshot()
        if not s.get("ok") or s.get("dead"):
            return s
        if attackers(s):
            if should_reset(s):
                print("FLEE wait_combat", json.dumps({"hp": s.get("hp"), "adds": len(attackers(s))}))
                s = reset_combat(s)
            else:
                s, _killed = defend()
            clear_since = None
            if s.get("dead"):
                return s
            continue
        if s.get("inCombat"):
            clear_since = None
            time.sleep(0.25)
            continue
        if clear_since is None:
            clear_since = time.time()
        elif time.time() - clear_since >= settle:
            return s
        time.sleep(0.2)
    return snapshot()


def _try_conjure(spell):
    started, err, s = try_cast(spell)
    if is_combat_error(err):
        print("CONJURE blocked combat", err)
        s = wait_out_of_combat(settle=2.0)
        if attackers(s) or s.get("inCombat") or s.get("dead"):
            return s, False
        started, err, s = try_cast(spell)
    if started:
        s = wait_while_casting((WATERBIND_CAST if spell == WATERBIND else BREADBIND_CAST) + 0.4)
        return s, True
    if err:
        print("CONJURE fail", json.dumps({"spell": spell, "err": err}))
    return snapshot(), False


def conjure_rations(s, need_food, need_water):
    """Waterbind / Breadbind as soon as combat has dropped. Do this before walking home."""
    if attackers(s) or s.get("inCombat") or s.get("dead"):
        return s
    if need_water and item_count(s, WATER_PREFIXES) < 1 and (s.get("mana") or 0) >= WATERBIND_COST:
        print("CONJURE waterbind")
        s, _ok = _try_conjure(WATERBIND)
    if attackers(s) or s.get("inCombat") or s.get("dead"):
        return s
    if need_food and item_count(s, FOOD_PREFIXES) < 1 and (s.get("mana") or 0) >= BREADBIND_COST:
        print("CONJURE breadbind")
        s, _ok = _try_conjure(BREADBIND)
    return snapshot()


def needs_recover(s, hp_frac=None, mana_frac=0.9):
    """True if this character is too hurt or dry to open a pull."""
    if not s or not s.get("ok") or s.get("dead"):
        return False
    hp_frac = MIN_PULL_HP_FRAC if hp_frac is None else hp_frac
    max_hp = s.get("maxHp") or 0
    max_mana = s.get("maxMana") or 0
    if max_hp <= 0:
        return True
    if (s.get("hp") or 0) < max_hp * hp_frac:
        return True
    if max_mana > 0 and (s.get("mana") or 0) < max_mana * mana_frac:
        return True
    return False


def _recover_clear_space(s, radius=SIT_CLEAR_YARDS, max_s=8.0):
    """Step off the stamp so we do not sit inside aggro range."""
    t0 = time.time()
    while time.time() - t0 < max_s:
        s = snapshot()
        if not s.get("ok") or s.get("dead"):
            stop()
            return s
        if attackers(s):
            stop()
            return reset_combat(s)
        near = close_hostiles(s, radius)
        if not near:
            stop()
            return s
        if home_dist(s) is not None and home_dist(s) >= min(40.0, FLEE_HOME_MAX / 2):
            stop()
            return s
        h = near[0]
        ang = face_to(s["x"] * 2 - h["x"], s["z"] * 2 - h["z"], s["x"], s["z"])
        move({"forward": True, "jump": True}, ang)
        time.sleep(0.12)
    stop()
    return snapshot()


def recover(hp_frac=0.95, mana_frac=0.9):
    """Eat and drink in the clear. Never sit inside a camp, and never tank a wanderer."""
    s = snapshot()
    if attackers(s) or (s.get("inCombat") and should_reset(s)):
        s = reset_combat(s)
        if s.get("dead"):
            return s
    if not is_resting(s):
        stop()
        attack(False)
        home_hot = bool(SAFESPOT and hostiles_near_point(s, SAFESPOT["x"], SAFESPOT["z"], SIT_CLEAR_YARDS))
        if not close_hostiles(s, SIT_CLEAR_YARDS) and not home_hot:
            s = go_safespot(max_s=24.0, max_away=FLEE_HOME_MAX)
            if s.get("dead"):
                return s
    for _attempt in range(12):
        s = snapshot()
        if not s.get("ok") or s.get("dead"):
            return s
        if attackers(s):
            print("RECOVER flee aggro", json.dumps({"hp": s.get("hp"), "adds": len(attackers(s))}))
            s = reset_combat(s)
            if s.get("dead"):
                return s
            continue
        if not is_resting(s):
            hot = close_hostiles(s, SIT_CLEAR_YARDS)
            if hot:
                print(
                    "RECOVER camp hot",
                    json.dumps(
                        [{"id": h.get("id"), "name": h.get("name"), "dist": h.get("dist")} for h in hot[:4]]
                    ),
                )
                s = _recover_clear_space(s)
                if s.get("dead"):
                    return s
                continue
            if SAFESPOT and dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"]) > 6.0:
                home_hot = hostiles_near_point(s, SAFESPOT["x"], SAFESPOT["z"], SIT_CLEAR_YARDS)
                if home_hot:
                    print(
                        "RECOVER skip hot home",
                        json.dumps(
                            [{"id": h.get("id"), "name": h.get("name")} for h in home_hot[:4]]
                        ),
                    )
                else:
                    s = go_safespot(max_s=24.0, max_away=FLEE_HOME_MAX, defend_on_aggro=False)
                    if s.get("dead"):
                        return s
                    if attackers(s) or close_hostiles(s, SIT_CLEAR_YARDS):
                        continue
            s = wait_out_of_combat(settle=0.6)
        if not s.get("ok") or s.get("dead"):
            return s
        if attackers(s):
            continue
        if s.get("inCombat") and not is_resting(s):
            continue
        if not is_resting(s) and close_hostiles(s, SIT_CLEAR_YARDS):
            continue
        need_food = s["hp"] < s["maxHp"] * hp_frac
        need_water = s["mana"] < s["maxMana"] * mana_frac
        if not need_food and not need_water:
            return s
        if not is_resting(s):
            s = conjure_rations(s, need_food, need_water)
            if attackers(s) or s.get("dead") or s.get("inCombat"):
                continue
        food = first_item(s, FOOD_PREFIXES) if need_food else None
        water = first_item(s, WATER_PREFIXES) if need_water else None
        if food and not s.get("eating"):
            use_item(food)
        if water and not s.get("drinking"):
            use_item(water)
        time.sleep(0.15)
        err = hud_error()
        if is_combat_error(err):
            print("RECOVER blocked combat", err)
            time.sleep(COMBAT_DROP_SEC)
            continue
        if "already" in (err or "").lower():
            pass
        elif not food and not water and not is_resting(s):
            print(
                "RECOVER no_rations",
                json.dumps({"need_food": need_food, "need_water": need_water, "mana": s.get("mana")}),
            )
            return s
        t0 = time.time()
        interrupted = False
        while time.time() - t0 < 18:
            s = snapshot()
            if s.get("dead"):
                return s
            if attackers(s):
                stop()
                print("RECOVER flee eat", json.dumps({"hp": s.get("hp"), "adds": len(attackers(s))}))
                s = reset_combat(s)
                if s.get("dead"):
                    return s
                interrupted = True
                break
            hp_ok = s["hp"] >= s["maxHp"] * hp_frac
            mana_ok = s["mana"] >= s["maxMana"] * mana_frac
            if hp_ok and mana_ok:
                return s
            time.sleep(0.15)
        if not interrupted:
            s = snapshot()
            if not needs_recover(s, hp_frac=hp_frac, mana_frac=mana_frac):
                return s
            print("RECOVER still short", json.dumps({"hp": s.get("hp"), "maxHp": s.get("maxHp"), "mana": s.get("mana")}))
    stop()
    return snapshot()
