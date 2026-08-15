# Clear autorun / held movement on the pinned ClaudeCraft tab.
# Run: .\scripts\stop.ps1
#      .\scripts\stop.ps1 -Name alt -Player CharacterName
from pathlib import Path
import os


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
    raise FileNotFoundError("Could not find examples/woc_lib.py")


_load_woc_lib()

try:
    activate_game(retries=4)
except Exception as err:
    print("STOP no tab", type(err).__name__, str(err)[:300])
    raise SystemExit(1)

halt_movement("stop_script")
try:
    s = snapshot()
    print("STOP sent", {"player": s.get("name"), "want": wanted_player() or None})
except Exception:
    print("STOP sent")
