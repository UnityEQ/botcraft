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

## Run the wolf loop

1. In Chrome, open [https://worldofclaudecraft.com/](https://worldofclaudecraft.com/).
2. Log in and enter the world on **your** character. Stay on that tab. The script will not pick a character for you.
3. From the repo root:

   ```powershell
   .\scripts\run.ps1 examples\woc_hunt_loop.py
   ```

4. Stop with **Ctrl+C**. The script releases movement and auto-attack on the way out.

Optional cap (default is no cap — it hunts until you interrupt):

```powershell
$env:WOC_HUNT_ROUNDS = "8"
.\scripts\run.ps1 examples\woc_hunt_loop.py
```

`.\scripts\run.ps1` starts the daemon if it is down, sets `BOTCRAFT_ROOT` so the script can find `examples\woc_lib.py` on any machine, and pipes the file into `browser-use`.

### What one hunt does

- Attaches to the open ClaudeCraft tab (`claudecraft` in the URL)
- Reads the current player from `window.__game.world.playerId`
- Recovers if HP/mana are low
- Fights anything already hitting you
- Keeps Hoarfrost Mantle and Aether Insight up
- Picks an isolated **wolf** within 2 levels of you
- Walks a path that bends around other hostiles
- Pulls with Cinderbolt, holds Attack (1), extra bolts only if the wolf is still fat
- Backs off, loots if nothing else is on you, then eats/drinks

If you die, the hunt **exits** (code 2) and the watchdog does not relaunch. Rez, then start the hunt again. If it cannot find a target, it waits and retries.

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
| `scripts\hunt.ps1` | Hunt loop with auto-restart (stops if you die) |
| `scripts\map.ps1` | Install or refresh the world-map NPC overlay |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `browser-use` not found | `$env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"` then open a new terminal |
| Allow popup on every click | Daemon died. `.\scripts\start-daemon.ps1`, click Allow once, leave it running |
| Doctor says Chrome / daemon failed | Start the daemon, enable remote debugging, click Allow once |
| `World of ClaudeCraft tab not found` | Open the game in Chrome and enter the world first |
| `Could not find examples/woc_lib.py` | Run from the repo via `.\scripts\run.ps1`, or set `BOTCRAFT_ROOT` to the clone path |
| Character looks wrong | The script uses whoever is already in that tab. Switch characters in the game, then rerun |

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
