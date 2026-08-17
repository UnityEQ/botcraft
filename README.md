# botcraft

A [World of ClaudeCraft](https://worldofclaudecraft.com/) toolkit that drives **your already-open Chrome tab**. The hunt loop pulls hostiles and recovers at a safespot. A **separate** map overlay paints NPC squares on the world map.

It uses **whoever is already in the world**. There is no hardcoded player name. Log in, pick your own character, walk into the world, then start a script.

## Requirements

- Windows 10/11 (the helper scripts are PowerShell)
- [Google Chrome](https://www.google.com/chrome/)
- [uv](https://docs.astral.sh/uv/) (installs the `browser-use` CLI)
- A World of ClaudeCraft account, already in-world at [worldofclaudecraft.com](https://worldofclaudecraft.com/)

The bot attaches to the live game tab. It does not log you in, pick a character, or create one.

## Install

```powershell
git clone https://github.com/UnityEQ/botcraft.git
cd botcraft
```

Install `uv` if you do not have it: https://docs.astral.sh/uv/getting-started/installation/

Then install the Browser Use CLI:

```powershell
uv tool install --python 3.12 --upgrade --force browser-use
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
```

Confirm it is on PATH:

```powershell
browser-use --version
```

## Allow Chrome remote debugging

Chrome 144+ blocks DevTools until you allow it. The detached daemon holds **one** connection so you only click Allow once.

1. Leave your normal Google Chrome window open. Do not restart Chrome unless you have to.
2. Start the daemon:

   ```powershell
   .\scripts\start-daemon.ps1
   ```

3. First time on this Chrome profile, also open the inspect page:

   ```powershell
   .\scripts\enable-remote-debugging.ps1
   ```

   That opens `chrome://inspect/#remote-debugging`. Tick **Allow remote debugging for this browser instance**.

4. If Chrome shows **Allow remote debugging?**, click **Allow** once.
5. Confirm the daemon is holding the connection:

   ```powershell
   .\scripts\check-setup.ps1
   ```

   You want the daemon reported as alive. `browser-use --doctor` is the same check.

Chrome asks Allow on every *new* debug websocket. Leave the daemon running. Do not run `browser-use --reload` unless you want another popup.

If the daemon died (Allow popup on every command), run `.\scripts\start-daemon.ps1` again and click Allow once.

## Run the hunt

1. In Chrome, open [https://worldofclaudecraft.com/](https://worldofclaudecraft.com/).
2. Log in and enter the world on **your** character. Walk to the camp you want. **Home is wherever you are standing when the script starts.**
3. Leave that tab selected (the Chrome window can sit in the background). From the repo root:

   ```powershell
   .\scripts\hunt.ps1
   .\scripts\hunt.ps1 -Player CharacterName
   ```

4. Stop with **Ctrl+C**. Movement and auto-attack are released on the way out. If they keep running: `.\scripts\stop.ps1`.

`hunt.ps1` is the watchdog. It restarts if Chrome CDP drops. If you **die**, it exits (code 2) and does **not** relaunch — rez, walk back to camp, start it again.

A one-shot without the watchdog:

```powershell
.\scripts\run.ps1 examples\woc_hunt_loop.py
```

Optional cap (default is no cap):

```powershell
$env:WOC_HUNT_ROUNDS = "8"
.\scripts\hunt.ps1 -Player CharacterName
```

`.\scripts\run.ps1` starts the daemon if it is down, sets `BOTCRAFT_ROOT` so the script can find `examples\woc_lib.py`, and pipes the file into `browser-use`.

Hunt talks to the tab by target id and does **not** steal OS focus. Leave the ClaudeCraft tab selected; switching to another tab in that window can throttle the game. To restore the old “always grab Chrome” behavior: `$env:WOC_STEAL_FOCUS = "1"`.

### What one hunt does

- Binds the open ClaudeCraft tab (`claudecraft` in the URL) and the character already in-world
- Stamps **home** from your current xyz (per process; another hunt cannot overwrite it)
- Recovers if HP/mana are low — eats in the **clear**, never sitting inside 24y of a hostile
- Fights a single hunt-band add; a pack, rare, boss, or low HP is a reset
- Keeps known self-buffs up (Insight / Mantle if learned)
- Picks the closest legal hostile in the hunt band (**your level −7 through +1**), preferring mobs within 42y of home (then up to 55y)
- Skips quest props and scenery that look hostile but are not a fight (Broodmother Eggs, egg-sacs: `xpMult 0`, no damage). Skips bosses
- Steps out only far enough to tag with **Attack (1)**, kites home, then **Cinderbolt + absorb** (bar 5, bar 6 if 5 is down) at the safespot. Does not plant the opener in the camp
- Extra bolts only while the target is still worth it; plants at home and does not chase
- Loots if nothing else is on you, then eats/drinks

### Flee and recover

Cloth cannot tank a camp. On adds, a pack, or HP at or below **10%**:

1. Drop auto-attack, Icebind if it will not leech, Blink only if the line is clear
2. Sprint **away** through a gap — not toward home, and not through the next pack
3. Stop when NPCs drop chase (`targetId` / `aiState` / evade), just outside the 20y detect clamp
4. Walk back to the start stamp (allowed out to 90y so a long flee is not “too far”)

If a wanderer hits you while eating, it flees. It does not stand up and tank.

### Chrome getting slow

The game leaks WebGL fire meshes on a long session (JS heap can pass 1 GB). The hunt caches snapshots in-page so it is not walking the world 30×/sec over CDP, but it cannot free meshes already leaked.

When the heap is huge the log prints `CHROME heap … reload the game tab`. Reload the ClaudeCraft tab, log back in, walk to camp, start the hunt again.

Pin a character when more than one ClaudeCraft tab is open:

```powershell
.\scripts\hunt.ps1 -Player CharacterName
```

## Two characters at once

Two windows of the **same** Chrome share one debug connection. Two hunts there will steal each other's tab. For two characters at the same time you need **two Chrome instances**.

`start-chrome.ps1` opens a **separate** Chrome (its own folder). That is why your usual profile list is empty. It is not your everyday Chrome — it exists so the second hunt has its own debug port.

**First time only** — copy one of your real Chrome profiles so Google login comes along:

```powershell
.\scripts\start-chrome.ps1 -Name alt -ListProfiles
.\scripts\start-chrome.ps1 -Name alt -CloneProfile "Default"
```

Use the `Directory` column from `-ListProfiles` (`Default`, `Profile 1`, …). Close that profile in normal Chrome if the copy complains about locked files.

**Window 1** — your normal Chrome:

```powershell
.\scripts\hunt.ps1 -Player FirstName
```

**Window 2** — after the alt Chrome is open and that character is in-world, **second** PowerShell:

```powershell
.\scripts\start-daemon.ps1 -Name alt
.\scripts\hunt.ps1 -Name alt -Player SecondName
```

You do **not** run `start-chrome` every hunt. Only when that second window is closed. The alt folder keeps the login. `hunt.ps1 -Name alt` remembers the port.

Click **Allow remote debugging** on the new Chrome if it asks. Each hunt has its own safespot. Ctrl+C in that terminal stops only that hunt.

## Map overlay

Independent of the hunt. Edit `examples\woc_map_npcs.py`, then run it to push the overlay into the live game tab.

```powershell
.\scripts\map.ps1
```

Or:

```powershell
.\scripts\run.ps1 examples\woc_map_npcs.py
```

Open the world map (`M`) if you do not see the squares. Re-run after a page reload. The hunt never installs this.

Squares sit on living mobs and NPCs (your player arrow is unchanged) and follow zoom/pan. Hover a square for a herb-patch style tooltip: name, level, type, hostile/friendly, HP, distance.

| Color | Relative to your level |
|---|---|
| Green | 5 or more levels below |
| Blue | 1–4 levels below |
| White | same level |
| Yellow | 1 or 2 above |
| Red | 3 or more above |

## Other scripts

```powershell
.\scripts\run.ps1 examples\hello.py
$env:URL = "https://worldofclaudecraft.com/"; .\scripts\run.ps1 examples\open_url.py
```

PowerShell one-off (same helpers as the saved scripts):

```powershell
$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
@'
ensure_real_tab()
print(page_info())
'@ | browser-use
```

| Script | Purpose |
|---|---|
| `scripts\start-daemon.ps1` | Start the detached Chrome debug daemon |
| `scripts\enable-remote-debugging.ps1` | Open `chrome://inspect/#remote-debugging` |
| `scripts\check-setup.ps1` | PATH, Chrome, `browser-use --doctor` |
| `scripts\stop-daemon.ps1` | Kill the daemon (next run will prompt Allow again) |
| `scripts\run.ps1 <file>` | Run a Python file against the live tab |
| `scripts\hunt.ps1` | Hunt loop with auto-restart (stops if you die). `-Player`, `-Name` |
| `scripts\stop.ps1` | Clear autorun / held movement if a hunt was killed mid-step |
| `scripts\map.ps1` | Install or refresh the world-map NPC overlay |
| `scripts\start-chrome.ps1 -Name alt` | Second Chrome instance for a second hunt |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `browser-use` not found | `$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"` then open a new terminal |
| Allow popup on every click | Daemon died. `.\scripts\start-daemon.ps1`, click Allow once, leave it running |
| Doctor says Chrome / daemon failed | Start the daemon, enable remote debugging, click Allow once |
| `World of ClaudeCraft tab not found` | Open the game in Chrome and enter the world first. A timeout on a busy frame is not “character gone” — leave the bind |
| `Could not find examples/woc_lib.py` | Run from the repo via `.\scripts\run.ps1` or `.\scripts\hunt.ps1`, or set `BOTCRAFT_ROOT` to the clone path |
| Character looks wrong | The script uses whoever is already in that tab. Switch characters in the game, then rerun |
| Chrome keeps jumping in front | Hunt no longer activates the tab. Restart the loop. `$env:WOC_STEAL_FOCUS = "1"` restores the old grab |
| `SAFESPOT skip too far` after a flee | Should walk home up to 90y now. Restart the loop. If you are still stranded, walk back to camp and start there |
| `CHROME heap … reload` / hitchy tab | Game WebGL leak. Reload the ClaudeCraft tab, log in, walk to camp, start hunt again |
| Pulls Broodmother Eggs | Those are quest props (`spider_egg`, no XP/damage). Current hunt skips them as `dummy` |

```powershell
.\scripts\check-setup.ps1
browser-use --doctor
```

## How it talks to Chrome

```
you  →  .\scripts\run.ps1  →  browser-use  →  daemon  →  Chrome CDP
```

Local Chrome is the default, including your existing logins and cookies. Isolated [Browser Use Cloud](https://cloud.browser-use.com) browsers are optional (`browser-use auth login`) if you want a clean session.

Using this from [Grok](https://grok.com/) in this folder: the `.grok/config.toml` registers the same Browser Use plugin. Start a new Grok session after cloning so the MCP tools attach.

## Safety

This automates gameplay in a live MMO-style world. Use it on your own account, at your own risk. The script never types passwords, MFA codes, or payment details — log in yourself.
