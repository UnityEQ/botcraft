# Isolated wolf hunts forever until you hit Ctrl+C.
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
    pick, cands = pick_isolated("wolf", max_level=max_level, min_iso=ISOLATION_MIN, min_path=12.0)
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
                "hp": c["hp"],
                "xyz": c.get("xyz") or xyz_of(c),
                "route": c.get("route"),
            }
            for c in cands[:8]
        ],
    )
    if not pick:
        note("no_safe_wolf", [{"id": c["id"], "xyz": c.get("xyz") or xyz_of(c), "iso": c.get("isolation"), "path": c.get("path")} for c in cands[:5]])
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
    target(wid)
    time.sleep(0.08)
    stop()
    # 1 Attack on as soon as we have a target. Casts go through world.castAbility
    # and skip the bar's start-attack-on-cast, so the script has to hold this.
    attack(True)
    cast(CINDERBOLT)
    note("cinderbolt_1", {"dist": mob["dist"], "hp": mob["hp"], "autoAttack": True})
    # Plant through the 1.5s cast. Moving here cancels the bolt.
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
    bolts = 1
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
        if extras and s["hp"] < 22:
            note("abort_adds_or_low_hp", {"hp": s["hp"], "adds": extras, "wolf": mob})
            attack(False)
            back_off(mob["x"], mob["z"], yards=28, max_s=6)
            return log
        if keep_autoattack(s) and not reon:
            reon = True
            note("autoattack_reon", {"dist": mob["dist"], "hp": mob["hp"]})
        # Extra Cinderbolt only if the wolf will still be up after another hit.
        # In melee, Attack (1) finishes them. Third bolt only on fat targets.
        hp = mob.get("hp") or 0
        mana = s.get("mana") or 0
        want_bolt = False
        if (not casting_or_gcd(s)) and mana >= CINDERBOLT_COST and hp > 0 and mob["dist"] <= CAST_RANGE:
            if bolts < 2 and hp > BOLT_OVERKILL_HP:
                want_bolt = True
            elif bolts < 3 and hp > BOLT_THIRD_HP:
                want_bolt = True
        if want_bolt:
            face(face_to(mob["x"], mob["z"], s["x"], s["z"]))
            cast(CINDERBOLT)
            bolts += 1
            note(
                f"cinderbolt_{bolts}",
                {"dist": mob["dist"], "hp": hp, "mana": mana, "autoAttack": s.get("autoAttack")},
            )
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

    # Leave the pack immediately. Loot only if nothing else is on us.
    if mob:
        s = back_off(mob["x"], mob["z"], yards=14, max_s=4)
    aggro = attackers(s)
    if aggro:
        note("defend_after_backoff", [{"id": a.get("id"), "name": a.get("name"), "dist": a.get("dist")} for a in aggro])
        s, killed = defend()
        note("defended", {"killed": killed, "hp": s.get("hp")})
        if s.get("dead"):
            note("we_died", {"hp": s["hp"]})
            return log
    extras = adds_on_us(s, ignore_id=wid, radius=12)
    if mob and mob.get("dead") and not extras and not attackers(s):
        target(wid)
        interact()
        time.sleep(0.25)
        note("looted")
    else:
        note("skip_loot", {"adds": extras})

    recover()
    s = snapshot()
    note("done", {"hp": s["hp"], "mana": s["mana"], "xp": s["xp"], "pos": [s["x"], s["z"]]})
    return log


def log_has(log, *msgs):
    found = {r.get("msg") for r in log}
    return any(m in found for m in msgs)


def check_after(round_i, log):
    stop()
    s = snapshot()
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
    if log_has(log, "abort_adds_on_walk", "abort_adds_on_stage", "abort_crowded_on_approach", "abort_adds_or_low_hp", "ran_past_wolf", "approach_timeout"):
        return "aborted", report
    return "other", report


def loop():
    activate_game()
    stop()
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
            s = snapshot()
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
            if s["hp"] < s["maxHp"] * MIN_PULL_HP_FRAC:
                print("RECOVER", s["hp"], "/", s["maxHp"])
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
                print("WAIT no isolated wolf, 8s")
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
