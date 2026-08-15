# Isolated hunts forever until you hit Ctrl+C.
# Hunt-band hostiles (player-7..+1), or only HUNT_NAME if that is set.
# Tag with Attack (1), kite home, then Cinderbolt + Blazing Barrier at the safespot.
# Run: .\scripts\run.ps1 examples\woc_hunt_loop.py
#
# Uses whichever character is already in the World of ClaudeCraft tab.
# Nothing is hardcoded to a player name.
from pathlib import Path
import json
import os
import time


def _load_woc_lib():
    candidates = []
    root = os.environ.get("BOTCRAFT_ROOT")
    if root:
        candidates.append(Path(root) / "examples" / "woc_lib.py")
    here = globals().get("__file__")
    if here:
        candidates.append(Path(here).with_name("woc_lib.py"))
    cwd = Path.cwd()
    candidates.extend(
        [
            cwd / "examples" / "woc_lib.py",
            cwd / "woc_lib.py",
        ]
    )
    for path in candidates:
        if path.is_file():
            exec(path.read_text(encoding="utf-8"), globals())
            return
    raise FileNotFoundError(
        "Could not find examples/woc_lib.py. Run via .\\scripts\\run.ps1 "
        "or set BOTCRAFT_ROOT to the cloned repo root."
    )


os.environ["WOC_HALT_ON_EXIT"] = "1"
_load_woc_lib()

# 0 = no cap (default). Set WOC_HUNT_ROUNDS=8 to restore a fixed count.
ROUNDS = int(os.environ.get("WOC_HUNT_ROUNDS", "0"))
FAIL_STREAK_PAUSE = 8
# Process exit code when the character dies. Watchdogs must not relaunch.
DIED_EXIT = 2


def stop_if_dead(s, where=""):
    if s and s.get("dead"):
        print("STOP died", where, json.dumps({"hp": s.get("hp"), "pos": [s.get("x"), s.get("z")]}))
        raise SystemExit(DIED_EXIT)


def hunt():
    activate_game()
    stop()
    log = []

    def note(msg, extra=None):
        rec = {"msg": msg}
        if extra is not None:
            rec["extra"] = extra
        log.append(rec)
        print(msg, json.dumps(extra) if extra is not None else "")

    s = snapshot()
    if not s.get("ok"):
        note("no_game")
        return log
    if not snapshot_is_ours(s):
        note("wrong_player", {"name": s.get("name"), "want": wanted_player() or None, "owner": SAFESPOT_OWNER})
        activate_game()
        return log
    if SAFESPOT is None:
        note("no_home")
        return log
    note(
        "character",
        {
            "name": s.get("name"),
            "id": s.get("id"),
            "level": s.get("level"),
            "hp": s.get("hp"),
            "mana": s.get("mana"),
        },
    )
    if s.get("dead"):
        note("dead_cannot_hunt", {"hp": s["hp"]})
        return log

    if needs_recover(s, hp_frac=MIN_PULL_HP_FRAC, mana_frac=0.75):
        note("recover_first", {"hp": s["hp"], "mana": s["mana"]})
        s = recover(hp_frac=0.95, mana_frac=0.9)

    if s.get("dead"):
        note("dead_cannot_hunt", {"hp": s["hp"]})
        return log

    aggro = attackers(s)
    if aggro:
        if needs_recover(s, hp_frac=MIN_PULL_HP_FRAC, mana_frac=0.0):
            note("flee_low_hp_before_hunt", {"hp": s.get("hp"), "maxHp": s.get("maxHp"), "adds": len(aggro)})
            attack(False)
            reset_combat(s)
            recover(hp_frac=0.95, mana_frac=0.9)
            return log
        note(
            "defend_before_hunt",
            [{"id": a.get("id"), "name": a.get("name"), "dist": a.get("dist"), "hp": a.get("hp")} for a in aggro],
        )
        s, killed = defend()
        note("defended", {"killed": killed, "hp": s.get("hp"), "mana": s.get("mana")})
        if s.get("dead"):
            note("we_died", {"hp": s["hp"]})
            return log
        s = recover(hp_frac=0.95, mana_frac=0.9)

    if s.get("dead"):
        note("dead_cannot_hunt", {"hp": s["hp"]})
        return log
    if needs_recover(s, hp_frac=MIN_PULL_HP_FRAC, mana_frac=0.75):
        note("skip_low_hp", {"hp": s["hp"], "maxHp": s["maxHp"], "mana": s.get("mana")})
        recover(hp_frac=0.95, mana_frac=0.9)
        return log

    s = ensure_buffs()
    note(
        "buffs",
        {
            "auras": s.get("auras"),
            "mana": s.get("mana"),
            "hp": s.get("hp"),
            "mantle": aura_remaining(s, MANTLE),
            "insight": aura_remaining(s, INSIGHT),
        },
    )

    player_level = s.get("level") or 1
    min_level = hunt_min_level(player_level)
    max_level = hunt_max_level(player_level)
    note(
        "here",
        {
            "player_level": player_level,
            "xyz": [s.get("x"), s.get("y"), s.get("z")],
            "facing": s.get("facing"),
        },
    )
    nearby = radar_brief(s, kinds=("mob", "npc"), radius=160.0)
    note("radar", {"count": len(nearby), "npcs": nearby})
    note(
        "hunt_band",
        {
            "player_level": player_level,
            "min_mob_level": min_level,
            "max_mob_level": max_level,
            "name": HUNT_NAME,
        },
    )
    pick, cands = pick_isolated(
        name_sub=HUNT_NAME, min_level=min_level, max_level=max_level, min_iso=ISOLATION_MIN, min_path=ISOLATION_MIN
    )
    note(
        "candidates",
        [
            {
                "id": c["id"],
                "name": c.get("name"),
                "level": c.get("level"),
                "dist": c["dist"],
                "iso": c.get("isolation"),
                "path": c.get("path"),
                "danger": c.get("danger"),
                "mob_danger": c.get("mob_danger"),
                "crowd": c.get("crowd"),
                "leash": c.get("leash"),
                "why": c.get("why"),
                "hp": c["hp"],
                "xyz": c.get("xyz") or xyz_of(c),
                "route": c.get("route"),
            }
            for c in cands[:8]
        ],
    )
    if not pick:
        note(
            "no_safe_target",
            [
                {
                    "id": c["id"],
                    "name": c.get("name"),
                    "level": c.get("level"),
                    "dist": c.get("dist"),
                    "xyz": c.get("xyz") or xyz_of(c),
                    "why": c.get("why"),
                }
                for c in cands[:8]
            ],
        )
        return log

    wid = pick["id"]
    note(
        "pull_target",
        {
            "id": pick["id"],
            "name": pick.get("name"),
            "level": pick.get("level"),
            "hp": pick.get("hp"),
            "dist": pick.get("dist"),
            "iso": pick.get("isolation"),
            "path": pick.get("path"),
            "danger": pick.get("danger"),
            "xyz": pick.get("xyz") or xyz_of(pick),
            "stage": pick.get("stage"),
            "route": pick.get("route"),
        },
    )

    s = snapshot()
    mob = entity(wid)
    already_in_range = mob and not mob.get("dead") and 16.0 <= mob["dist"] <= CAST_RANGE
    mob_from_home = None
    if SAFESPOT and mob and not mob.get("dead"):
        mob_from_home = dist(mob["x"], mob["z"], SAFESPOT["x"], SAFESPOT["z"])

    if SAFESPOT:
        if mob_from_home is None or mob_from_home > PULL_FAR_YARDS:
            note(
                "skip_mob_far_from_home",
                {
                    "mob_from_home": None if mob_from_home is None else round(mob_from_home, 1),
                    "home": SAFESPOT,
                    "mob": xyz_of(mob) if mob else None,
                },
            )
            go_safespot(stop_at=5.0, max_s=16.0, max_away=RETURN_HOME_MAX)
            return log
        home_now = dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"])
        if home_now > RETURN_HOME_MAX:
            note("skip_bad_home_xyz", {"dist": round(home_now, 1), "home": SAFESPOT, "me": [s.get("x"), s.get("z")]})
            stop()
            return log
        if home_now > PULL_HOME_MAX:
            note("return_home_after_flee", {"dist": round(home_now, 1), "home": SAFESPOT, "me": [s.get("x"), s.get("z")]})
            go_safespot(stop_at=5.0, max_s=20.0, max_away=RETURN_HOME_MAX)
            s = snapshot()
            home_now = dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"]) if s.get("ok") else home_now
            if home_now > PULL_HOME_MAX:
                note("still_far_from_home", {"dist": round(home_now, 1)})
                return log
        if home_now > 5.0:
            note("return_home_before_tag", {"dist": round(home_now, 1), "mob_from_home": round(mob_from_home, 1)})
            go_safespot(stop_at=5.0, max_s=12.0, max_away=RETURN_HOME_MAX)
            s = snapshot()
            mob = entity(wid)
        if mob and (mob.get("dist") or 99) > CAST_RANGE:
            note("step_out_tag", {"dist": mob.get("dist"), "mob_from_home": round(mob_from_home, 1)})
            s, mob, why_step = step_out_to_tag(wid, max_away=PULL_LEASH, max_s=7.0)
            note("stepped_out", {"why": why_step, "dist": None if not mob else mob.get("dist")})
        stop()
        note("pull_from_home", {"mob_from_home": round(mob_from_home, 1), "dist": None if not mob else mob.get("dist")})
        mob = entity(wid)
    elif already_in_range:
        note("already_in_range", {"dist": mob["dist"], "xyz": xyz_of(mob)})
        stop()
    else:
        note("no_home_skip_walk", {"dist": None if not mob else mob.get("dist")})
        stop()
        return log

    extras = adds_on_us(s, ignore_id=wid, radius=12)
    home_now = dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"]) if SAFESPOT and s.get("ok") else 0
    dangers = danger_nearby(s, ignore_id=wid) if home_now > PULL_LEASH else []
    if dangers:
        note(
            "abort_danger_on_approach",
            {
                "wolf": mob,
                "danger": [
                    {"id": d.get("id"), "name": d.get("name"), "level": d.get("level"), "dist": d.get("dist")}
                    for d in dangers[:4]
                ],
            },
        )
        go_safespot(stop_at=5.0, max_s=16.0, max_away=RETURN_HOME_MAX)
        return log
    aggro = attackers(s)
    if aggro:
        note("defend_on_approach", {"wolf": mob, "adds": aggro, "hp": s.get("hp")})
        s, killed = defend()
        note("defended", {"killed": killed, "hp": s.get("hp")})
        return log
    if not mob or mob.get("dead"):
        note("wolf_died_before_pull")
        return log
    if mob["dist"] < MELEE_RANGE:
        note("too_close_backing_out", {"dist": mob["dist"]})
        if SAFESPOT:
            go_safespot(stop_at=5.0, max_s=12.0, max_away=RETURN_HOME_MAX)
        else:
            s = back_off(mob["x"], mob["z"], yards=PULL_RANGE, max_s=5)
        mob = entity(wid)
        if not mob or mob.get("dead"):
            note("wolf_died_before_pull")
            return log

    s = snapshot()
    if s.get("dead") or s["hp"] < s["maxHp"] * MIN_PULL_HP_FRAC:
        note("skip_low_hp_before_pull", {"hp": s.get("hp"), "maxHp": s.get("maxHp")})
        if SAFESPOT:
            go_safespot(stop_at=5.0, max_s=16.0, max_away=RETURN_HOME_MAX)
        return log

    # Tag with Attack (1) and run. Do not plant a Cinderbolt or Barrier in the camp.
    s, tagged = tag_with_attack(wid)
    note(
        "tag_attack",
        {
            "tagged": tagged,
            "dist": None if not mob else mob.get("dist"),
            "autoAttack": s.get("autoAttack"),
        },
    )
    incoming = [e for e in attackers(s) if e.get("id") != wid]
    if incoming:
        note(
            "flee_adds_during_cast",
            [{"id": e.get("id"), "name": e.get("name"), "dist": e.get("dist")} for e in incoming],
        )
        attack(False)
        reset_combat(s)
        recover(hp_frac=0.95, mana_frac=0.9)
        return log

    used_barrier = False
    bolts = 0
    if SAFESPOT:
        s = snapshot()
        if not snapshot_is_ours(s):
            note("wrong_player_on_pull", {"name": s.get("name"), "want": wanted_player() or None})
            activate_game()
            stop()
            return log
        home_d = dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"])
        if home_d > PULL_HOME_MAX:
            note(
                "home_too_far",
                {
                    "from": [round(s["x"], 1), round(s["z"], 1)],
                    "home": SAFESPOT,
                    "dist": round(home_d, 1),
                    "owner": SAFESPOT_OWNER,
                },
            )
            stop()
            return log
        if home_d > 4.0:
            note(
                "pull_home",
                {
                    "from": [round(s["x"], 1), round(s["z"], 1)],
                    "home": SAFESPOT,
                    "dist": round(home_d, 1),
                    "name": s.get("name"),
                    "id": s.get("id"),
                },
            )
            s, why_home = kite_to_safespot(ignore_id=wid, stop_at=5.0, max_s=8.0)
            note("pulled_home", {"why": why_home, "pos": [round(s.get("x") or 0, 1), round(s.get("z") or 0, 1)]})
            if s.get("dead"):
                note("we_died", {"hp": s.get("hp")})
                stop()
                attack(False)
                return log
            if why_home in ("timeout", "too_far", "wrong_player", "wrong_way", "stuck"):
                stop()
            home_d = dist(s["x"], s["z"], SAFESPOT["x"], SAFESPOT["z"]) if s.get("ok") else home_d
            extras = [e for e in attackers(s) if e.get("id") != wid]
            if extras or why_home == "adds":
                note(
                    "flee_adds_on_kite",
                    [{"id": e.get("id"), "name": e.get("name"), "dist": e.get("dist")} for e in extras[:4]],
                )
                attack(False)
                reset_combat(s)
                recover(hp_frac=0.95, mana_frac=0.9)
                return log
            mob = entity(wid)
            if not mob or mob.get("dead"):
                note("wolf_died_before_pull")
                return log
            pack = [h for h in living_hostiles(s) if h.get("id") != wid and (h.get("dist") or 99) <= 12]
            if len(pack) >= 2:
                note(
                    "flee_pack_at_home",
                    [{"id": h.get("id"), "name": h.get("name"), "dist": h.get("dist")} for h in pack[:4]],
                )
                attack(False)
                reset_combat(s)
                recover(hp_frac=0.95, mana_frac=0.9)
                return log
            s = ensure_hostile_target(wid, s)
            face(face_to(mob["x"], mob["z"], s["x"], s["z"]))
            stop()

    # Fight at home: Cinderbolt, then Blazing Barrier.
    ok_cinder, err_cinder, used_barrier, err5, s = home_cinder_then_barrier(wid)
    note(
        "home_opener",
        {
            "cinder": ok_cinder,
            "cinder_err": err_cinder or None,
            "barrier": used_barrier,
            "barrier_err": err5 or None,
        },
    )
    if ok_cinder:
        bolts = 1
    keep_autoattack()

    t0 = time.time()
    reon = False
    while time.time() - t0 < 16:
        s = snapshot()
        mob = entity(wid)
        if s.get("ok") and not snapshot_is_ours(s):
            note("wrong_player_in_fight", {"name": s.get("name"), "want": wanted_player() or None})
            stop()
            activate_game()
            return log
        if s.get("dead"):
            note("we_died", {"hp": s["hp"]})
            stop()
            attack(False)
            return log
        if not mob or mob.get("dead"):
            note("wolf_dead")
            break
        if should_reset(s):
            note("flee_low_hp", {"hp": s.get("hp"), "maxHp": s.get("maxHp"), "wolf": mob.get("hp")})
            attack(False)
            reset_combat(s)
            recover(hp_frac=0.95, mana_frac=0.9)
            return log
        s = ensure_hostile_target(wid, s)
        incoming = [e for e in attackers(s) if e.get("id") != wid]
        if incoming:
            note(
                "flee_adds",
                {
                    "adds": [
                        {"id": e.get("id"), "name": e.get("name"), "dist": e.get("dist"), "hp": e.get("hp")}
                        for e in incoming
                    ],
                    "wolf": {"id": mob.get("id"), "hp": mob.get("hp"), "dist": mob.get("dist")},
                    "hp": s.get("hp"),
                },
            )
            attack(False)
            reset_combat(s)
            recover(hp_frac=0.95, mana_frac=0.9)
            return log
        extras = [e for e in adds_on_us(s, ignore_id=wid, radius=ADD_ABORT_RANGE) if e.get("targetId") == s.get("id")]
        if extras:
            note(
                "flee_adds_or_low_hp",
                {
                    "hp": s["hp"],
                    "adds": [{"id": e.get("id"), "name": e.get("name"), "dist": e.get("dist")} for e in extras[:4]],
                    "wolf": {"id": mob.get("id"), "hp": mob.get("hp"), "dist": mob.get("dist")},
                },
            )
            attack(False)
            reset_combat(s)
            recover(hp_frac=0.95, mana_frac=0.9)
            return log
        hold_safespot()
        if keep_autoattack(s) and not reon:
            reon = True
            note("autoattack_reon", {"dist": mob["dist"], "hp": mob["hp"]})
        hp = mob.get("hp") or 0
        if (not casting_or_gcd(s)) and pick_damage_spell(s, mob) and bolts < 4:
            spell, ok, err = press_damage(wid, mob, s, planted=True)
            if ok:
                bolts += 1
                note(
                    f"cast_{spell}_{bolts}",
                    {
                        "dist": mob["dist"],
                        "hp": hp,
                        "mana": s.get("mana"),
                        "autoAttack": s.get("autoAttack"),
                    },
                )
                if spell == CINDERBOLT and not used_barrier:
                    started5, err5, _s = after_first_cinderbolt()
                    used_barrier = True
                    note("bar5_blazing_barrier", {"started": started5, "err": err5 or None})
            else:
                if err == "unknown_ability" or is_unknown_ability_error(err):
                    mark_unknown_ability(spell)
                    continue
                note("cast_blocked", {"spell": spell, "err": err, "dist": mob["dist"], "hp": hp})
        time.sleep(0.12)

    stop()
    mob = entity(wid)
    s = snapshot()
    if not attackers(s):
        attack(False)
    note(
        "fight_over",
        {
            "hp": s["hp"],
            "mana": s["mana"],
            "wolf": mob,
            "xp": s["xp"],
            "autoAttack": s.get("autoAttack"),
            "bolts": bolts,
        },
    )

    # A leftover attacker after the kill is a pack leech. Run, do not tank it.
    aggro = attackers(s)
    if aggro:
        note(
            "flee_after_fight",
            [{"id": a.get("id"), "name": a.get("name"), "dist": a.get("dist"), "hp": a.get("hp")} for a in aggro],
        )
        attack(False)
        if should_reset(s, aggro) or len(aggro) >= 2:
            reset_combat(s)
            recover(hp_frac=0.95, mana_frac=0.9)
            return log
        s, killed = defend()
        note("defended", {"killed": killed, "hp": s.get("hp")})
        if s.get("dead"):
            note("we_died", {"hp": s["hp"]})
            return log
        mob = entity(wid)

    extras = adds_on_us(s, ignore_id=wid, radius=12)
    if mob and mob.get("dead") and not extras and not attackers(s):
        target(wid)
        interact()
        time.sleep(0.25)
        note("looted")
    else:
        note("skip_loot", {"adds": extras})

    recover(hp_frac=0.95, mana_frac=0.9)
    s = snapshot()
    note("done", {"hp": s["hp"], "mana": s["mana"], "xp": s["xp"], "pos": [s["x"], s["z"]]})
    return log


def log_has(log, *msgs):
    found = {r.get("msg") for r in log}
    return any(m in found for m in msgs)


def check_after(round_i, log):
    s = stop_unless_resting()
    killed_adds = []
    aggro = attackers(s)
    if aggro:
        print(
            "DEFEND leftover",
            json.dumps([{"id": a.get("id"), "name": a.get("name"), "dist": a.get("dist")} for a in aggro]),
        )
        s, killed_adds = defend()
    if not attackers(s):
        attack(False)
    moving = False
    try:
        mi = js("({...window.__game.world.moveInput})")
        moving = any(mi.get(k) for k in ("forward", "back", "strafeLeft", "strafeRight"))
    except Exception:
        pass
    if moving:
        stop()
    extras = [e for e in living_hostiles(s) if e["dist"] < 10]
    report = {
        "round": round_i,
        "dead": s.get("dead"),
        "hp": s.get("hp"),
        "maxHp": s.get("maxHp"),
        "mana": s.get("mana"),
        "xp": s.get("xp"),
        "level": s.get("level"),
        "pos": [round(s.get("x") or 0, 1), round(s.get("z") or 0, 1)],
        "moving": moving,
        "inCombat": s.get("inCombat"),
        "autoAttack": s.get("autoAttack"),
        "auras": [a.get("id") for a in (s.get("auras") or [])],
        "close_mobs": extras,
        "defended": killed_adds,
        "last": [r.get("msg") for r in log[-6:]],
    }
    print("CHECK", json.dumps(report))
    if s.get("dead") or log_has(log, "we_died", "died_on_stage", "dead_cannot_hunt"):
        return "dead", report
    if killed_adds or log_has(log, "defended", "attacker_joined", "defend_before_hunt", "defend_on_walk", "defend_after_fight"):
        if log_has(log, "wolf_dead") or killed_adds:
            return "kill", report
    if moving:
        return "stuck_moving", report
    if log_has(log, "skip_low_hp", "skip_low_hp_before_pull", "flee_low_hp_before_hunt"):
        return "low_hp", report
    if log_has(log, "wolf_dead"):
        if (s.get("maxHp") or 0) and (s.get("hp") or 0) < (s.get("maxHp") or 1) * MIN_PULL_HP_FRAC:
            return "low_hp", report
        return "kill", report
    if log_has(log, "no_safe_target", "no_safe_wolf", "wolf_died_before_pull"):
        return "no_target", report
    if log_has(
        log,
        "abort_adds_on_walk",
        "abort_adds_on_stage",
        "abort_crowded_on_approach",
        "abort_adds_or_low_hp",
        "abort_adds_or_crowd",
        "abort_crowd",
        "abort_danger_on_walk",
        "abort_danger_on_approach",
        "ran_past_wolf",
        "approach_timeout",
        "flee_adds",
        "flee_adds_during_cast",
        "flee_adds_or_low_hp",
        "flee_low_hp",
        "flee_adds_on_kite",
        "flee_pack_at_home",
        "flee_after_fight",
        "leave_pack",
    ):
        return "aborted", report
    return "other", report


def loop():
    fail = 0
    kills = 0
    i = 0
    last_rounds = []
    try:
        while True:
            try:
                activate_game()
                stop()
                s0 = snapshot()
                who = (s0.get("name") or "").strip()
                want = wanted_player()
                if want and who.lower() != want.lower():
                    print("WAIT snapshot is", who or "?", "wanted", want)
                    time.sleep(2)
                    continue
                if not s0.get("ok"):
                    time.sleep(2)
                    continue
                home = stamp_start_home()
                if not home or SAFESPOT is None:
                    print("WAIT safespot not set, will not pull yet")
                    time.sleep(2)
                    continue
                print(
                    "SAFESPOT locked before pulls",
                    json.dumps(
                        {
                            "player": SAFESPOT_OWNER,
                            "id": SAFESPOT_ID,
                            "home": SAFESPOT,
                        }
                    ),
                )
                break
            except KeyboardInterrupt:
                raise
            except Exception as err:
                print("WAIT activate_game", type(err).__name__, str(err)[:400])
                time.sleep(3)
        while True:
            i += 1
            if ROUNDS and i > ROUNDS:
                print("STOP reached WOC_HUNT_ROUNDS", ROUNDS)
                break
            print(f"ROUND {i}")
            try:
                s = snapshot()
                if not s.get("ok"):
                    print("WAIT no_game snapshot, 4s")
                    time.sleep(4)
                    continue
                aggro = attackers(s)
                if aggro:
                    if needs_recover(s, hp_frac=MIN_PULL_HP_FRAC, mana_frac=0.0):
                        print("FLEE low hp before defend", s.get("hp"), "/", s.get("maxHp"))
                        attack(False)
                        reset_combat(s)
                        s = recover(hp_frac=0.95, mana_frac=0.9)
                    else:
                        print(
                            "DEFEND before round",
                            json.dumps(
                                [{"id": a.get("id"), "name": a.get("name"), "dist": a.get("dist"), "hp": a.get("hp")} for a in aggro]
                            ),
                        )
                        s, killed = defend()
                        if killed:
                            kills += len(killed)
                            print("DEFENDED", json.dumps(killed))
                stop_if_dead(s, "before_round")
                if needs_recover(s, hp_frac=MIN_PULL_HP_FRAC, mana_frac=0.75):
                    print("RECOVER", s.get("hp"), "/", s.get("maxHp"))
                    s = recover(hp_frac=0.95, mana_frac=0.9)
                    stop_if_dead(s, "while_recovering")
                    if needs_recover(s, hp_frac=MIN_PULL_HP_FRAC, mana_frac=0.75):
                        print("WAIT still recovering", s.get("hp"), "/", s.get("maxHp"))
                        time.sleep(3)
                        continue
                log = hunt()
                outcome, report = check_after(i, log)
                report["outcome"] = outcome
                last_rounds.append(report)
                last_rounds = last_rounds[-12:]
                if outcome == "kill":
                    kills += 1
                    fail = 0
                elif outcome == "dead":
                    stop_if_dead({"dead": True, "hp": report.get("hp"), "x": (report.get("pos") or [None, None])[0], "z": (report.get("pos") or [None, None])[1]}, "after_hunt")
                elif outcome == "stuck_moving":
                    print("UNSTICK")
                    stop()
                    fail += 1
                elif outcome == "low_hp":
                    s = recover(hp_frac=0.95, mana_frac=0.9)
                    fail += 1
                elif outcome == "aborted":
                    print("RECOVER after flee")
                    s = recover(hp_frac=0.95, mana_frac=0.9)
                    fail += 1
                elif outcome == "no_target":
                    print("WAIT no hunt target, 8s")
                    s = snapshot()
                    if needs_recover(s, hp_frac=MIN_PULL_HP_FRAC, mana_frac=0.75):
                        s = recover(hp_frac=0.95, mana_frac=0.9)
                    else:
                        s, killed = wait_or_defend(8)
                        if killed:
                            kills += len(killed)
                            print("DEFENDED", json.dumps(killed))
                    fail = 0
                else:
                    fail += 1
                if fail >= FAIL_STREAK_PAUSE:
                    print("WAIT fail streak, backing off 12s", fail)
                    stop()
                    attack(False)
                    s = recover(hp_frac=0.95, mana_frac=0.9)
                    fail = 0
                s = snapshot()
                if needs_recover(s, hp_frac=MIN_PULL_HP_FRAC, mana_frac=0.75):
                    s = recover(hp_frac=0.95, mana_frac=0.9)
                else:
                    s, killed = wait_or_defend(1.2)
                    stop_if_dead(s, "between_rounds")
                    if killed:
                        kills += len(killed)
                        print("DEFENDED", json.dumps(killed))
            except KeyboardInterrupt:
                raise
            except SystemExit:
                raise
            except BaseException as err:
                print("ROUND_ERROR", type(err).__name__, str(err)[:800])
                fail += 1
                try:
                    stop()
                    attack(False)
                except Exception:
                    pass
                # Evaluate timeouts mean the tab is busy, not gone. Rebinding
                # storms another timeout and looks like the character vanished.
                msg = str(err).lower()
                if "timed out" not in msg and "timeout" not in msg:
                    try:
                        activate_game()
                    except Exception:
                        pass
                time.sleep(2)
    except KeyboardInterrupt:
        print("STOP interrupted")
        raise SystemExit(130)
    finally:
        halt_movement("loop_done")
        try:
            s = snapshot()
        except Exception:
            s = {}
        print(
            "LOOP_DONE",
            json.dumps(
                {
                    "kills": kills,
                    "rounds_ran": i,
                    "last_rounds": last_rounds,
                    "final": {
                        "dead": s.get("dead"),
                        "hp": s.get("hp"),
                        "mana": s.get("mana"),
                        "xp": s.get("xp"),
                        "level": s.get("level"),
                    },
                },
                indent=2,
            )[:12000],
        )


loop()
