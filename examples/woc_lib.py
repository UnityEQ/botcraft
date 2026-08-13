# Shared World of ClaudeCraft helpers for Grok browser-use scripts.
# Drive window.__game — never leave a held W or controller.move without stop().
# Binds to the character already in the tab (world.playerId). No player name filter.

import json
import math
import time

CINDERBOLT = "fireball"
MANTLE = "frost_armor"
INSIGHT = "arcane_intellect"
FOOD = "baked_bread"
WATER = "spring_water"

# Action bar: 1 Attack, 2 Cinderbolt, 3 Hoarfrost Mantle, 4 Aether Insight.
CINDERBOLT_COST = 30
CINDERBOLT_CAST = 1.5
# Rank-1 bolt is 16-25 + 2 DoT. Forest Wolf is ~40/54 HP. Do not spend another 30 mana if they are already dying.
BOLT_OVERKILL_HP = 22
BOLT_THIRD_HP = 40
MANTLE_COST = 20
INSIGHT_COST = 25
BUFF_REFRESH_REMAINING = 60

CAST_RANGE = 30.0
# Open the first bolt near max range. Do not walk into 20y to start a fight.
PULL_RANGE = 27.0
MELEE_RANGE = 6.0
ISOLATION_MIN = 15.0
ADD_ABORT_RANGE = 10.0
# Never open a pull below this fraction of max HP.
MIN_PULL_HP_FRAC = 0.8
# Always allow pulls at least this many levels above the player.
HUNT_LEVEL_ABOVE = 2


def hunt_max_level(player_level):
    return (player_level or 1) + HUNT_LEVEL_ABOVE


def activate_game():
    tabs = list_tabs(include_chrome=False)
    for t in tabs:
        url = (t.get("url") or "").lower()
        if "claudecraft" in url:
            tid = t.get("targetId") or t.get("target_id")
            cdp("Target.activateTarget", targetId=tid)
            install_combat_hook()
            return tid
    raise RuntimeError("World of ClaudeCraft tab not found")


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
    return js(code)


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
    return [e for e in s.get("ents", []) if e.get("hostile") and not e.get("dead") and e.get("kind") == "mob"]


_MOBS = None


def mobs():
    global _MOBS
    if _MOBS is None:
        _MOBS = j("window.__game.MOBS || {}") or {}
    return _MOBS


def is_too_hard(mob, player_level):
    """Named rares / elites / over-level packs will kill a low-HP caster."""
    if not mob:
        return False
    if (mob.get("level") or 1) > hunt_max_level(player_level):
        return True
    tmpl = mobs().get(mob.get("templateId") or "") or {}
    return bool(tmpl.get("rare") or tmpl.get("elite"))


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
    """Target and kill one mob already on us. Does not abort when that mob is close."""
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
        keep_autoattack(s)
        ang = face_to(mob["x"], mob["z"], s["x"], s["z"])
        face(ang)
        d = mob.get("dist") or 0
        hp = mob.get("hp") or 0
        mana = s.get("mana") or 0
        want_bolt = (
            (not casting_or_gcd(s))
            and mana >= CINDERBOLT_COST
            and hp > BOLT_OVERKILL_HP
            and d <= CAST_RANGE
            and bolts < 3
        )
        if d > CAST_RANGE:
            move({"forward": True, "jump": d > 18}, ang)
        elif want_bolt:
            stop()
            cast(CINDERBOLT)
            bolts += 1
        elif d > MELEE_RANGE + 1.5:
            move({"forward": True}, ang)
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
        if is_too_hard(mob, s.get("level") or 1):
            print("FLEE too_hard", json.dumps(rec))
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


def route_to(ax, az, bx, bz, hostiles, ignore_id=None, min_clear=10.0, offset=14.0, max_hops=4):
    """Walkpoints from A to B that bend around other NPC xyz instead of through them."""
    pts = []
    cx, cz = ax, az
    used = set()
    for _ in range(max_hops):
        blocker = None
        blocker_d = min_clear
        for h in hostiles:
            hid = h.get("id")
            if ignore_id is not None and hid == ignore_id:
                continue
            if hid in used:
                continue
            d = _seg_dist(h["x"], h["z"], cx, cz, bx, bz)
            if d < blocker_d:
                blocker_d = d
                blocker = h
        if blocker is None:
            pts.append((bx, bz))
            return pts
        used.add(blocker["id"])
        dx, dz = bx - cx, bz - cz
        length = math.hypot(dx, dz) or 1.0
        px, pz = -dz / length, dx / length
        ox, oz = blocker["x"], blocker["z"]
        left = (ox + px * offset, oz + pz * offset)
        right = (ox - px * offset, oz - pz * offset)

        def _score(pt):
            return min(
                path_clearance(cx, cz, pt[0], pt[1], hostiles, ignore_id),
                path_clearance(pt[0], pt[1], bx, bz, hostiles, ignore_id),
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
    route = route_to(s["x"], s["z"], dest_x, dest_z, hostiles, ignore_id, min_clear=min_clear)
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


def staging_for(mob, hostiles, me=None):
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
        rec = {"x": sx, "z": sz, "tag": tag, "path": round(path, 2)}
        if best is None or score > best_score:
            best = rec
            best_score = score
    return best


def pick_isolated(name_sub, level=None, min_level=None, max_level=None, min_iso=ISOLATION_MIN, hostiles=None, min_path=8.0):
    s = snapshot()
    hostiles = hostiles if hostiles is not None else living_hostiles(s)
    needle = name_sub.lower()
    cands = []
    for h in hostiles:
        if needle not in (h.get("name") or "").lower() and needle not in (h.get("templateId") or "").lower():
            continue
        lv = h.get("level")
        if level is not None and lv != level:
            continue
        if min_level is not None and (lv is None or lv < min_level):
            continue
        if max_level is not None and (lv is None or lv > max_level):
            continue
        iso = isolation(h, hostiles)
        stage = staging_for(h, hostiles, s)
        stand_x, stand_z = _stand_off(h, s, PULL_RANGE)
        dest_x, dest_z = stand_x, stand_z
        if stage and not _beyond_mob(s["x"], s["z"], h, stage["x"], stage["z"]):
            dest_x, dest_z = stage["x"], stage["z"]
        route = route_to(s["x"], s["z"], dest_x, dest_z, hostiles, ignore_id=h["id"])
        if any(_beyond_mob(s["x"], s["z"], h, wx, wz) for wx, wz in route):
            route = [(dest_x, dest_z)]
        path = route_clearance(s["x"], s["z"], route, hostiles, ignore_id=h["id"])
        cands.append(
            {
                **h,
                "isolation": round(iso, 2),
                "path": round(path, 2),
                "stage": stage,
                "route": [{"x": round(wx, 2), "z": round(wz, 2)} for wx, wz in route],
                "xyz": xyz_of(h),
            }
        )
    cands.sort(
        key=lambda c: (
            -(c["isolation"] >= min_iso and c["path"] >= min_path),
            c["dist"],
            -c["isolation"],
            -c["path"],
        )
    )
    good = [c for c in cands if c["isolation"] >= min_iso and c["path"] >= min_path]
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


def cast(ability_id):
    j(f"window.__game.world.castAbility({ability_id!r})")


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
        # Insight is buffTarget/party. Drop a hostile so it lands on us, then restore.
        had = s.get("targetId")
        target(s.get("id") or None)
        cast(INSIGHT)
        time.sleep(0.3)
        if had:
            target(had)
        s = snapshot()
    return s


def ensure_mantle(min_remaining=BUFF_REFRESH_REMAINING):
    return ensure_buffs(min_remaining=min_remaining)


def _stand_off(mob, me, yards):
    """Point `yards` from the mob, on the side we already occupy."""
    dx, dz = me["x"] - mob["x"], me["z"] - mob["z"]
    length = math.hypot(dx, dz) or 1.0
    return mob["x"] + dx / length * yards, mob["z"] + dz / length * yards


def move_toward(tx, tz, stop_at=4.0, max_s=20.0, jump=True, ignore_id=None, add_radius=12.0, avoid=True):
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
        if adds_on_us(s, ignore_id=ignore_id, radius=add_radius):
            stop()
            s["aborted_adds"] = True
            return s
        d = dist(s["x"], s["z"], tx, tz)
        if d <= stop_at:
            stop()
            return s
        wx, wz = tx, tz
        if avoid:
            hostiles = living_hostiles(s)
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
        extras = adds_on_us(s, ignore_id=eid, radius=add_radius)
        if extras:
            stop()
            return s, mob, "adds"
        if mob["dist"] <= stop_at:
            stop()
            return s, mob, "ok"
        # We started on one side of the wolf. If we are now on the other side,
        # the walk went through it.
        if start and _beyond_mob(start["x"], start["z"], mob, s["x"], s["z"], slop=1.0):
            stop()
            return s, mob, "past"
        hostiles = living_hostiles(s)
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


def recover(hp_frac=0.85, mana_frac=0.7):
    """Eat / drink if needed. Stops first so sitting is not broken by movement."""
    stop()
    attack(False)
    for _attempt in range(4):
        s = snapshot()
        if not s.get("ok") or s.get("dead"):
            return s
        if attackers(s):
            s, _killed = defend()
            if s.get("dead"):
                return s
            continue
        if s.get("inCombat"):
            time.sleep(0.15)
            continue
        need_food = s["hp"] < s["maxHp"] * hp_frac
        need_water = s["mana"] < s["maxMana"] * mana_frac
        if not need_food and not need_water:
            return s
        ids = {i["id"] for i in s.get("inventory") or []}
        if need_food and FOOD in ids:
            use_item(FOOD)
        if need_water and WATER in ids:
            use_item(WATER)
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
            if s.get("inCombat"):
                stop()
                interrupted = True
                break
            hp_ok = s["hp"] >= s["maxHp"] * hp_frac
            mana_ok = s["mana"] >= s["maxMana"] * mana_frac
            if hp_ok and mana_ok:
                stop()
                return s
            time.sleep(0.4)
        if not interrupted:
            stop()
            return snapshot()
    stop()
    return snapshot()
