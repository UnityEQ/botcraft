# Isolated hunts forever until you hit Ctrl+C.
# Any aggressive mob at most player level + 1. Start position is the recover safespot.
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


_load_woc_lib()

# 0 = no cap (default). Set WOC_HUNT_ROUNDS=8 to restore a fixed count.
ROUNDS = int(os.environ.get("WOC_HUNT_ROUNDS", "0"))
FAIL_STREAK_PAUSE = 8


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
    if SAFESPOT is None:
        set_safespot(s)
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

    if s["hp"] < s["maxHp"] * 0.9 or s["mana"] < s["maxMana"] * 0.75:
        note("recover_first", {"hp": s["hp"], "mana": s["mana"]})
        s = recover(hp_frac=0.95, mana_frac=0.9)

    if s.get("dead"):
        note("dead_cannot_hunt", {"hp": s["hp"]})
        return log

    aggro = attackers(s)
    if aggro:
        note(
            "defend_before_hunt",
            [{"id": a.get("id"), "name": a.get("name"), "dist": a.get("dist"), "hp": a.get("hp")} for a in aggro],
        )
        s, killed = defend()
        note("defended", {"killed": killed, "hp": s.get("hp"), "mana": s.get("mana")})
        if s.get("dead"):
            note("we_died", {"hp": s["hp"]})
            return log
        if s["hp"] < s["maxHp"] * 0.9 or s["mana"] < s["maxMana"] * 0.75:
            s = recover(hp_frac=0.95, mana_frac=0.9)

    if s.get("dead"):
        note("dead_cannot_hunt", {"hp": s["hp"]})
        return log
    if s["hp"] < s["maxHp"] * MIN_PULL_HP_FRAC:
        note("skip_low_hp", {"hp": s["hp"], "maxHp": s["maxHp"]})
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
    note("hunt_band", {"player_level": player_level, "max_mob_level": max_level})
    pick, cands = pick_isolated(max_level=max_level, min_iso=ISOLATION_MIN, min_path=ISOLATION_MIN)
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
            "no_safe_wolf",
            [
                {
                    "id": c["id"],
                    "xyz": c.get("xyz") or xyz_of(c),
                    "iso": c.get("isolation"),
                    "path": c.get("path"),
                    "danger": c.get("danger"),
                    "crowd": c.get("crowd"),
                    "why": c.get("why"),
                }
                for c in cands[:5]
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

    if already_in_range:
        note("already_in_range", {"dist": mob["dist"], "xyz": xyz_of(mob)})
        stop()
    else:
        # One walk: live wolf xyz + every nearby NPC xyz, bent around packs.
        note(
            "walk_to_wolf",
            {
                "wolf_xyz": xyz_of(mob) if mob else None,
                "me": [s.get("x"), s.get("y"), s.get("z")],
                "route": pick.get("route"),
            },
        )
        s, mob, why = approach_entity(wid, stop_at=PULL_RANGE, max_s=28, add_radius=12.0)
        stop()
        if why == "danger":
            dangers = danger_nearby(s, ignore_id=wid)
            note(
                "abort_danger_on_walk",
                {
                    "wolf": mob,
                    "danger": [
                        {
                            "id": d.get("id"),
                            "name": d.get("name"),
                            "level": d.get("level"),
                            "dist": d.get("dist"),
                            "xyz": xyz_of(d),
                        }
                        for d in dangers[:4]
                    ],
                    "hp": s.get("hp"),
                },
            )
            if dangers:
                flee_from(dangers[0]["x"], dangers[0]["z"], yards=36, max_s=7)
            return log
        if why == "adds":
            extras = adds_on_us(s, ignore_id=wid, radius=12)
            aggro = attackers(s)
            if aggro:
                note("defend_on_walk", {"wolf": mob, "adds": aggro, "hp": s["hp"]})
                s, killed = defend()
                note("defended", {"killed": killed, "hp": s.get("hp")})
                return log
            note("abort_adds_on_walk", {"wolf": mob, "adds": extras, "hp": s["hp"]})
            if extras:
                back_off(extras[0]["x"], extras[0]["z"], yards=24, max_s=6)
            else:
                move_toward(-8, -8, stop_at=8, max_s=8, jump=True)
            return log
        if not mob or mob.get("dead") or why == "gone":
            note("wolf_died_before_pull")
            return log
        if why == "past":
            note("ran_past_wolf", {"dist": mob.get("dist"), "wolf_xyz": xyz_of(mob), "me": [s.get("x"), s.get("y"), s.get("z")]})
            s = back_off(mob["x"], mob["z"], yards=PULL_RANGE, max_s=5)
            mob = entity(wid)
            if not mob or mob.get("dead") or mob["dist"] > CAST_RANGE:
                return log
        if why == "timeout" and (not mob or mob.get("dist", 99) > CAST_RANGE):
            note("approach_timeout", {"dist": None if not mob else mob.get("dist"), "me": [s.get("x"), s.get("y"), s.get("z")]})
            return log
        note("arrived", {"dist": mob.get("dist"), "why": why, "wolf_xyz": xyz_of(mob), "me": [s.get("x"), s.get("y"), s.get("z")]})

    extras = adds_on_us(s, ignore_id=wid, radius=12)
    crowd = nearby_hostiles(s, ignore_id=wid, radius=CROWD_RADIUS)
    if mob:
        crowd_at_mob = nearby_hostiles(s, origin=(mob["x"], mob["z"]), ignore_id=wid, radius=CROWD_RADIUS)
    else:
        crowd_at_mob = []
    if len(crowd) > MAX_CROWD or len(crowd_at_mob) > MAX_CROWD:
        note(
            "abort_crowd",
            {
                "near_me": [{"id": e.get("id"), "name": e.get("name"), "dist": e.get("dist")} for e in crowd[:5]],
                "near_mob": [
                    {"id": e.get("id"), "name": e.get("name"), "dist": e.get("dist")} for e in crowd_at_mob[:5]
                ],
            },
        )
        if crowd:
            back_off(crowd[0]["x"], crowd[0]["z"], yards=28, max_s=6)
        elif mob:
            back_off(mob["x"], mob["z"], yards=24, max_s=5)
        return log
    dangers = danger_nearby(s, ignore_id=wid)
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
        flee_from(dangers[0]["x"], dangers[0]["z"], yards=36, max_s=7)
        return log
    aggro = attackers(s)
    if aggro:
        note("defend_on_approach", {"wolf": mob, "adds": aggro, "hp": s.get("hp")})
        s, killed = defend()
        note("defended", {"killed": killed, "hp": s.get("hp")})
        return log
    if extras or not mob or mob.get("dead"):
        note("abort_crowded_on_approach", {"wolf": mob, "adds": extras})
        if mob:
            back_off(mob["x"], mob["z"], yards=22, max_s=5)
        return log
    if mob["dist"] < MELEE_RANGE:
        note("too_close_backing_out", {"dist": mob["dist"]})
        s = back_off(mob["x"], mob["z"], yards=PULL_RANGE, max_s=5)
        mob = entity(wid)
        if not mob or mob.get("dead"):
            note("wolf_died_before_pull")
            return log

    s = snapshot()
    if s.get("dead") or s["hp"] < s["maxHp"] * MIN_PULL_HP_FRAC:
        note("skip_low_hp_before_pull", {"hp": s.get("hp"), "maxHp": s.get("maxHp")})
        if mob:
            back_off(mob["x"], mob["z"], yards=20, max_s=4)
        return log

    ang = face_to(mob["x"], mob["z"], s["x"], s["z"])
    face(ang)
    s = ensure_hostile_target(wid, s)
    time.sleep(0.08)
    stop()
    # 1 Attack on as soon as we have a target. Casts go through world.castAbility
    # and skip the bar's start-attack-on-cast, so the script has to hold this.
    attack(True)
    spell, ok, err = press_damage(wid, mob, s)
    note(
        "opener",
        {
            "spell": spell,
            "dist": mob["dist"],
            "hp": mob["hp"],
            "autoAttack": True,
            "started": ok,
            "err": err or None,
        },
    )
    # Plant through a 1.5s hard cast. Moving here cancels Cinderbolt / Rimelance.
    if ok and spell in (CINDERBOLT, RIMELANCE):
        t_cast = time.time()
        while time.time() - t_cast < CINDERBOLT_CAST + 0.2:
            keep_autoattack()
            incoming = [e for e in attackers() if e.get("id") != wid]
            if incoming:
                break
            time.sleep(0.1)
    keep_autoattack()
    incoming = [e for e in attackers(snapshot()) if e.get("id") != wid]
    if incoming:
        note("attacker_during_cast", [{"id": e.get("id"), "name": e.get("name"), "dist": e.get("dist")} for e in incoming])

    t0 = time.time()
    bolts = 1 if ok else 0
    reon = False
    while time.time() - t0 < 16:
        s = snapshot()
        mob = entity(wid)
        if s.get("dead"):
            note("we_died", {"hp": s["hp"]})
            stop()
            attack(False)
            return log
        if not mob or mob.get("dead"):
            note("wolf_dead")
            break
        s = ensure_hostile_target(wid, s)
        incoming = [e for e in attackers(s) if e.get("id") != wid]
        if incoming:
            note(
                "attacker_joined",
                {
                    "adds": [
                        {"id": e.get("id"), "name": e.get("name"), "dist": e.get("dist"), "hp": e.get("hp")}
                        for e in incoming
                    ],
                    "wolf": {"id": mob.get("id"), "hp": mob.get("hp"), "dist": mob.get("dist")},
                },
            )
            s, killed = defend()
            note("defended", {"killed": killed, "hp": s.get("hp")})
            if s.get("dead"):
                note("we_died", {"hp": s["hp"]})
                stop()
                attack(False)
                return log
            break
        extras = adds_on_us(s, ignore_id=wid, radius=ADD_ABORT_RANGE)
        wanderers = nearby_hostiles(s, ignore_id=wid, radius=CROWD_RADIUS)
        if extras or len(wanderers) > MAX_CROWD:
            note(
                "abort_adds_or_crowd",
                {
                    "hp": s["hp"],
                    "adds": [{"id": e.get("id"), "name": e.get("name"), "dist": e.get("dist")} for e in extras[:4]],
                    "crowd": [
                        {"id": e.get("id"), "name": e.get("name"), "dist": e.get("dist")} for e in wanderers[:5]
                    ],
                    "wolf": {"id": mob.get("id"), "hp": mob.get("hp"), "dist": mob.get("dist")},
                },
            )
            attack(False)
            leave = extras[0] if extras else wanderers[0]
            back_off(leave["x"], leave["z"], yards=28, max_s=6)
            return log
        if keep_autoattack(s) and not reon:
            reon = True
            note("autoattack_reon", {"dist": mob["dist"], "hp": mob["hp"]})
        hp = mob.get("hp") or 0
        if (not casting_or_gcd(s)) and pick_damage_spell(s, mob) and bolts < 4:
            spell, ok, err = press_damage(wid, mob, s)
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
            else:
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

    # Anyone who jumped us during the fight stays on the to-kill list.
    aggro = attackers(s)
    if aggro:
        note(
            "defend_after_fight",
            [{"id": a.get("id"), "name": a.get("name"), "dist": a.get("dist"), "hp": a.get("hp")} for a in aggro],
        )
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

    # Home before the next pull. Do not back off into the pack.
    s = go_safespot()
    note("safespot", {"pos": [s.get("x"), s.get("z")], "home": SAFESPOT})
    if attackers(s):
        note("defend_on_safespot", [{"id": a.get("id"), "name": a.get("name"), "dist": a.get("dist")} for a in attackers(s)])
        s, killed = defend()
        note("defended", {"killed": killed, "hp": s.get("hp")})
        if s.get("dead"):
            note("we_died", {"hp": s["hp"]})
            return log
        s = go_safespot()

    recover()
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
    if log_has(log, "skip_low_hp", "skip_low_hp_before_pull"):
        return "low_hp", report
    if log_has(log, "wolf_dead"):
        return "kill", report
    if log_has(log, "no_safe_wolf", "wolf_died_before_pull"):
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
    ):
        return "aborted", report
    return "other", report


def loop():
    activate_game()
    stop()
    s0 = snapshot()
    if s0.get("ok"):
        set_safespot(s0)
    fail = 0
    kills = 0
    i = 0
    last_rounds = []
    try:
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
                if s.get("dead"):
                    print("WAIT dead, 12s (rez to continue, Ctrl+C to stop)")
                    last_rounds.append({"round": i, "outcome": "dead"})
                    last_rounds = last_rounds[-12:]
                    wait_or_defend(12)
                    continue
                max_hp = s.get("maxHp") or 1
                if (s.get("hp") or 0) < max_hp * MIN_PULL_HP_FRAC:
                    print("RECOVER", s.get("hp"), "/", s.get("maxHp"))
                    s = recover(hp_frac=0.95, mana_frac=0.9)
                    if s.get("dead"):
                        print("WAIT died while recovering")
                        wait_or_defend(12)
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
                    print("WAIT dead after hunt, 12s")
                    wait_or_defend(12)
                    fail = 0
                elif outcome == "stuck_moving":
                    print("UNSTICK")
                    stop()
                    fail += 1
                elif outcome == "low_hp":
                    s = recover(hp_frac=0.95, mana_frac=0.9)
                    fail += 1
                elif outcome == "no_target":
                    print("WAIT no isolated target, 8s")
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
                    s, killed = wait_or_defend(12)
                    if killed:
                        kills += len(killed)
                    fail = 0
                s, killed = wait_or_defend(1.2)
                if killed:
                    kills += len(killed)
                    print("DEFENDED", json.dumps(killed))
            except KeyboardInterrupt:
                raise
            except Exception as err:
                print("ROUND_ERROR", type(err).__name__, str(err)[:800])
                fail += 1
                try:
                    stop()
                    attack(False)
                except Exception:
                    pass
                time.sleep(3)
    except KeyboardInterrupt:
        print("STOP interrupted")
    finally:
        try:
            stop()
            attack(False)
        except Exception:
            pass
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
