# Shared World of ClaudeCraft helpers for Grok browser-use scripts.
# Drive window.__game — never leave a held W or controller.move without stop().
# Binds to the character already in the tab (world.playerId). No player name filter.

import json
import math
import time

CINDERBOLT = "fireball"
RIMELANCE = "frostbolt"
ICEBIND = "frost_nova"
BLAZING_BARRIER = "blazing_barrier"
MANTLE = "frost_armor"
INSIGHT = "arcane_intellect"
BREADBIND = "conjure_food"
WATERBIND = "conjure_water"
FOOD = "baked_bread"
WATER = "spring_water"
FOOD_PREFIXES = ("conjured_bread", "baked_bread")
WATER_PREFIXES = ("conjured_water", "spring_water")

# Action bar: 1 Attack, 2 Cinderbolt, 3 Rimelance, 4 Icebind, 5 Blazing Barrier.
# Buffs live on 11/12. Combat DPS is 2-5. Bar 5 is after the first Cinderbolt.
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
# Hunt band: player-7 through player+1.
HUNT_LEVEL_ABOVE = 1
HUNT_LEVEL_BELOW = 7
# Only pull this mob when set. Empty string = any hunt-band hostile.
# To lock a camp later: HUNT_NAME = "Mire Prowler"
HUNT_NAME = ""
# A +1 mob is worth this many extra yards vs a same-level. Keeps pulls local
# but prefers the best legal level among nearby targets.
HUNT_LEVEL_YARDS = 18.0


def hunt_max_level(player_level):
    return (player_level or 1) + HUNT_LEVEL_ABOVE


def hunt_min_level(player_level):
    return max(1, (player_level or 1) - HUNT_LEVEL_BELOW)


# xyz recorded when the hunt loop starts. Recover walks here to eat/drink.
SAFESPOT = None


def set_safespot(s=None):
    global SAFESPOT
    s = s or snapshot()
    if not s.get("ok"):
        return None
    pack = [h for h in living_hostiles(s) if (h.get("dist") or 99) <= 16]
    if len(pack) >= 2:
        print(
            "SAFESPOT refused, standing in a pack",
            json.dumps([{"name": h.get("name"), "dist": h.get("dist")} for h in pack[:6]]),
        )
        return None
    SAFESPOT = {"x": float(s["x"]), "y": float(s.get("y") or 0), "z": float(s["z"])}
    print("SAFESPOT set", json.dumps(SAFESPOT))
    return SAFESPOT


def go_safespot(stop_at=5.0, max_s=28.0):
    """Walk back to the start point. Used between pulls to eat and drink."""
    if not SAFESPOT:
        return snapshot()
    s = snapshot()
    if not s.get("ok") or s.get("dead") or is_resting(s):
        return s
    if dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"]) <= stop_at:
        stop()
        return s
    print("SAFESPOT walk", json.dumps({"from": [round(s["x"], 1), round(s["z"], 1)], "to": SAFESPOT}))
    attack(False)
    for _try in range(3):
        if attackers(s):
            s, _killed = defend()
            if s.get("dead"):
                return s
        s = move_toward(
            SAFESPOT["x"],
            SAFESPOT["z"],
            stop_at=stop_at,
            max_s=max_s,
            jump=True,
            abort_adds=False,
            abort_danger=False,
        )
        if s.get("dead"):
            return s
        if dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"]) <= stop_at + 1.0:
            stop()
            return s
        if attackers(s):
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
    if dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"]) <= stop_at:
        stop()
        return s, "already"
    print(
        "SAFESPOT kite",
        json.dumps({"from": [round(s["x"], 1), round(s["z"], 1)], "to": SAFESPOT, "ignore": ignore_id}),
    )
    # Leave Attack (1) on so the tag swing is not cancelled. Do not plant here.
    t0 = time.time()
    last = s
    last_pos_t = t0
    stuck_hits = 0
    while time.time() - t0 < max_s:
        s = snapshot()
        if not s.get("ok") or s.get("dead"):
            stop()
            return s, "dead"
        extras = [e for e in attackers(s) if e.get("id") != ignore_id]
        if extras:
            stop()
            return s, "adds"
        if dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"]) <= stop_at:
            stop()
            return s, "ok"
        hostiles = living_blockers(s, s.get("level") or 1)
        wx, wz, _route = next_step_toward(
            s, SAFESPOT["x"], SAFESPOT["z"], hostiles, ignore_id=ignore_id
        )
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
        move({"forward": True, "jump": True if stuck else int((now - t0) * 8) % 10 == 0}, ang)
        if stuck_hits >= 6:
            j("window.__game.world.unstuck()")
            stuck_hits = 0
        time.sleep(0.12)
    stop()
    s = snapshot()
    if dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"]) <= stop_at + 3.0:
        return s, "ok"
    return s, "timeout"


def activate_game(retries=8):
    last = None
    for attempt in range(max(1, retries)):
        try:
            tabs = list_tabs(include_chrome=False)
            for t in tabs:
                url = (t.get("url") or "").lower()
                if "claudecraft" in url:
                    tid = t.get("targetId") or t.get("target_id")
                    cdp("Target.activateTarget", targetId=tid)
                    install_combat_hook()
                    return tid
            last = RuntimeError("World of ClaudeCraft tab not found")
        except Exception as err:
            last = err
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
    j(
        """
(() => {
  const g = window.__game;
  if (!g) return;
  g.controller.stop();
  g.input.autorun = false;
  if (g.world && g.world.setMoveInput) {
    g.world.setMoveInput({
      forward: false, back: false, turnLeft: false, turnRight: false,
      strafeLeft: false, strafeRight: false, jump: false, dive: false, surface: false
    });
  }
})()
"""
    )


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


def snapshot():
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
      inCombat: !!e.inCombat
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
    inCombat: !!e.inCombat
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


def is_too_hard(mob, player_level):
    """Named rares / elites / over-level packs will kill a low-HP caster."""
    if not mob or not mob.get("hostile"):
        return False
    if mob.get("kind") not in ("mob", "npc"):
        return False
    if (mob.get("level") or 1) > hunt_max_level(player_level):
        return True
    tmpl = mobs().get(mob.get("templateId") or "") or {}
    return bool(tmpl.get("rare") or tmpl.get("elite"))


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
    if is_too_hard(mob, player_level):
        return False
    lv = mob.get("level")
    if lv is None:
        return True
    return hunt_min_level(player_level) <= lv <= hunt_max_level(player_level)


def is_danger(mob, player_level):
    """Hostile over the hunt band, rare, or elite. Town vendors are not danger."""
    if not mob or mob.get("dead") or not mob.get("hostile"):
        return False
    if mob.get("kind") not in ("mob", "npc"):
        return False
    if is_hunt_mob(mob, player_level):
        return False
    return is_too_hard(mob, player_level)


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


def should_flee(mob, player_level, attacker_count=1):
    """Cloth cannot tank a pack. Two hostiles on us is always a run."""
    if is_danger(mob, player_level):
        return True
    if attacker_count >= 2:
        return True
    return False


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
    # Names only while a live hit is on the hook. Stale "Forest Wolf hits you"
    # lines stay in the 200-line combat log after the fight is over.
    if s.get("hitByIds") and s.get("inCombat"):
        for name in s.get("hitByNames") or []:
            matches = [e for e in ents if (e.get("name") or "") == name and not e.get("dead")]
            if matches:
                add(min(matches, key=lambda e: e.get("dist") or 99))
    if s.get("inCombat") and not out:
        for h in living_hostiles(s):
            if (h.get("dist") or 99) <= MELEE_RANGE + 2:
                add(h)
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
        if should_flee(mob, s.get("level") or 1, attacker_count=len(aggro)):
            print("FLEE too_hard", json.dumps({**rec, "attackers": len(aggro)}))
            flee_from(mob["x"], mob["z"], yards=40, max_s=8)
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
    for h in hostiles:
        if not hunt_name_match(h, needle):
            continue
        if not is_hunt_mob(h, player_level):
            continue
        lv = h.get("level")
        if level is not None and lv != level:
            continue
        if min_level is not None and (lv is None or lv < min_level):
            continue
        if max_level is not None and (lv is None or lv > max_level):
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
            }
        )
    def _hunt_score(c):
        d = c.get("dist") or 99.0
        lv = c.get("level") or 1
        return d - HUNT_LEVEL_YARDS * (lv - player_level)

    cands.sort(
        key=lambda c: (
            -(c.get("why") is None),
            _hunt_score(c),
            c.get("crowd") or 0,
            c["dist"],
            -((c.get("level") or 1)),
            -c["isolation"],
            -c["path"],
            -c["danger"],
        )
    )
    good = [c for c in cands if c.get("why") is None]
    if not good:
        # Walk would clip an elite — still pull if the mob itself is not
        # stacked on that elite. Never pick on_danger (social-aggro wipe).
        good = [c for c in cands if c.get("why") != "on_danger"]
    return good[0] if good else None, cands


def move(flags, facing=None):
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
    """Highest DPS from bars 2-4: Icebind only in melee, else Cinderbolt, else Rimelance."""
    if not mob or mob.get("dead"):
        return None
    mana = s.get("mana") or 0
    hp = mob.get("hp") or 0
    d = mob.get("dist") or 99
    # Icebind is a 10y self-centered AoE. Only fire it when they are already
    # in melee so the root actually lands — and never when a packmate is
    # inside the nova (that is what pulled the second bone and killed us).
    if (
        mana >= ICEBIND_COST
        and d <= MELEE_RANGE
        and cooldown_remaining(ICEBIND, s) <= 0.08
        and not is_rooted(mob["id"])
        and nova_is_safe(s, ignore_id=mob.get("id"))
    ):
        return ICEBIND
    if mana >= CINDERBOLT_COST and hp > BOLT_OVERKILL_HP and d <= CAST_RANGE:
        return CINDERBOLT
    if mana >= RIMELANCE_COST and hp > 0 and d <= CAST_RANGE:
        return RIMELANCE
    return None


def hold_safespot(stop_at=4.0):
    """Stay planted at home. If a LoS strafe drifted us, step back — never chase."""
    s = snapshot()
    if not s.get("ok") or s.get("dead"):
        return s
    if not SAFESPOT:
        stop()
        return s
    if dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"]) <= stop_at:
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
    """Keep Hoarfrost Mantle (3) and Aether Insight (4) up. Instant, 30 min, not used in the fight."""
    s = snapshot()
    if aura_remaining(s, MANTLE) < min_remaining and (s.get("mana") or 0) >= MANTLE_COST:
        cast(MANTLE)
        time.sleep(0.3)
        s = snapshot()
    if aura_remaining(s, INSIGHT) < min_remaining and (s.get("mana") or 0) >= INSIGHT_COST:
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
    """Home on a same-side stand-off. Never walk through or past the mob."""
    t0 = time.time()
    last = snapshot()
    last_pos_t = t0
    start = last
    while time.time() - t0 < max_s:
        s = snapshot()
        mob = entity(eid)
        if not s.get("ok") or s.get("dead") or not mob or mob.get("dead"):
            stop()
            return s, mob, "gone"
        # Packmates standing nearby are not adds. Only abort if something
        # actually aggroed us, or we walked into an elite/over-level bubble.
        incoming = [e for e in attackers(s) if e.get("id") != eid]
        if incoming:
            stop()
            return s, mob, "adds"
        dangers = danger_nearby(s, ignore_id=eid)
        if dangers:
            stop()
            s["danger"] = [
                {"id": d.get("id"), "name": d.get("name"), "level": d.get("level"), "dist": d.get("dist")}
                for d in dangers[:4]
            ]
            return s, mob, "danger"
        if mob["dist"] <= stop_at:
            stop()
            return s, mob, "ok"
        # We started on one side of the wolf. If we are now on the other side,
        # the walk went through it.
        if start and _beyond_mob(start["x"], start["z"], mob, s["x"], s["z"], slop=1.0):
            stop()
            return s, mob, "past"
        hostiles = living_blockers(s, s.get("level") or 1)
        dest_x, dest_z = _stand_off(mob, s, stop_at)
        wx, wz, _route = next_step_toward(s, dest_x, dest_z, hostiles, ignore_id=eid)
        if _beyond_mob(s["x"], s["z"], mob, wx, wz):
            wx, wz = dest_x, dest_z
        ang = face_to(wx, wz, s["x"], s["z"])
        now = time.time()
        moved = dist(s["x"], s["z"], last["x"], last["z"]) if last else 1
        stuck = (now - last_pos_t) > 0.45 and moved < 0.35
        if not stuck and moved >= 0.35:
            last = s
            last_pos_t = now
        elif stuck:
            last = s
            last_pos_t = now
        move({"forward": True, "jump": True if stuck else int((now - t0) * 8) % 10 == 0}, ang)
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


def flee_from(from_x, from_z, yards=40.0, max_s=8.0):
    """Run away even if they are still hitting us. Used for rares / over-level."""
    stop()
    attack(False)
    t0 = time.time()
    while time.time() - t0 < max_s:
        s = snapshot()
        if not s.get("ok") or s.get("dead"):
            stop()
            return s
        d = dist(s["x"], s["z"], from_x, from_z)
        if d >= yards and not s.get("inCombat"):
            stop()
            return s
        if d >= yards + 8:
            stop()
            return s
        ang = face_to(s["x"] * 2 - from_x, s["z"] * 2 - from_z, s["x"], s["z"])
        move({"forward": True, "jump": True}, ang)
        time.sleep(0.12)
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


def recover(hp_frac=0.85, mana_frac=0.7):
    """Walk to the safespot, then Breadbind / Waterbind, then eat / drink."""
    s = snapshot()
    if not is_resting(s):
        stop()
        attack(False)
        s = go_safespot()
        if s.get("dead"):
            return s
    for _attempt in range(6):
        s = snapshot()
        if not s.get("ok") or s.get("dead"):
            return s
        if not is_resting(s):
            if SAFESPOT and dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"]) > 6.0:
                s = go_safespot()
                if s.get("dead"):
                    return s
            s = wait_out_of_combat(settle=0.6)
        if not s.get("ok") or s.get("dead"):
            return s
        if attackers(s):
            continue
        if s.get("inCombat") and not is_resting(s):
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
        time.sleep(0.25)
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
                s, _killed = defend()
                if s.get("dead"):
                    return s
                interrupted = True
                break
            hp_ok = s["hp"] >= s["maxHp"] * hp_frac
            mana_ok = s["mana"] >= s["maxMana"] * mana_frac
            if hp_ok and mana_ok:
                return s
            time.sleep(0.4)
        if not interrupted:
            return snapshot()
    stop()
    return snapshot()
