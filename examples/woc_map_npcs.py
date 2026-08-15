# Live map overlay for World of ClaudeCraft. Separate from the hunt loop.
# Edit this file, then run it to update the open game tab. Hunt never installs this.
#
#   .\scripts\map.ps1
#   .\scripts\run.ps1 examples\woc_map_npcs.py
#
# Square color is mob level vs the player:
#   green  5+ below   blue  1-4 below   white  same
#   yellow +1 or +2   red   +3 or more
# Mouseover matches herb patches: name, level, type, hostile/friendly, HP, yards.
from pathlib import Path
import json
import os

# Injected into the live page. Re-running the script replaces the hook with this text.
MAP_NPC_JS = r"""
(() => {
  const g = window.__game;
  const hud = g && g.hud;
  const painter = hud && hud.mapPainter;
  if (!hud || !painter || typeof painter.draw !== 'function') return false;
  const prev = window.__wocMapNpcs || {};
  const hudProto = Object.getPrototypeOf(hud);
  if (typeof hudProto.updateMapWindow === 'function') {
    hud.updateMapWindow = hudProto.updateMapWindow.bind(hud);
  }
  const nativeDraw = prev.nativeDraw || painter.draw.bind(painter);
  const MARK = 12;
  const HIT_R = 18;
  function worldToMap(x, z, v, n) {
    const dx = v.maxX - v.minX, dz = v.maxZ - v.minZ;
    if (!dx || !dz) return null;
    return { mx: (v.maxX - x) / dx * n, my: (v.maxZ - z) / dz * n };
  }
  function colorFor(e) {
    const w = g.world;
    const p = w && w.entities.get(w.playerId);
    const pl = (p && p.level) || 1;
    const lv = e.level;
    if (lv == null) return '#c8c8c8';
    const d = lv - pl;
    if (d <= -5) return '#3dcc5a';
    if (d < 0) return '#3d8cff';
    if (d === 0) return '#f4f4f4';
    if (d <= 2) return '#f0c040';
    return '#e33c3c';
  }
  function esc(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function tipHtml(e) {
    const w = g.world;
    const p = w && w.entities.get(w.playerId);
    const tmpl = (g.MOBS && e.templateId && g.MOBS[e.templateId]) || {};
    const fam = tmpl.family || e.kind || '';
    const lvl = e.level != null ? 'Level ' + e.level : '';
    const stance = e.hostile
      ? '<div class="tt-red">Hostile</div>'
      : '<div class="tt-green">Friendly</div>';
    const elite = (tmpl.rare || tmpl.elite) ? '<div class="tt-sub">Elite</div>' : '';
    const hp = (e.hp != null && e.maxHp)
      ? '<div class="tt-sub">' + Math.round(e.hp) + ' / ' + Math.round(e.maxHp) + ' HP</div>'
      : '';
    let yards = '';
    if (p && p.pos && e.pos) {
      const d = Math.hypot((e.pos.x || 0) - p.pos.x, (e.pos.z || 0) - p.pos.z);
      yards = '<div class="tt-sub">' + Math.round(d) + ' yards</div>';
    }
    return (
      '<div class="tt-title">' + esc(e.name || e.templateId || 'Unknown') + '</div>' +
      '<div class="tt-sub">' + esc([lvl, fam].filter(Boolean).join(' ')) + '</div>' +
      elite + stance + hp + yards
    );
  }
  function paint(ctx, region, n) {
    const w = g.world;
    const state = window.__wocMapNpcs;
    if (state) state.hits = [];
    if (!w || !ctx || !region || !n) return;
    const pid = w.playerId;
    w.entities.forEach((e) => {
      if (!e || e.id === pid || e.dead) return;
      if (e.kind !== 'mob' && e.kind !== 'npc') return;
      const pos = e.pos || {};
      const pt = worldToMap(pos.x || 0, pos.z || 0, region, n);
      if (!pt) return;
      if (pt.mx < -MARK || pt.my < -MARK || pt.mx > n + MARK || pt.my > n + MARK) return;
      ctx.fillStyle = colorFor(e);
      ctx.strokeStyle = 'rgba(0,0,0,0.95)';
      ctx.lineWidth = 1.5;
      ctx.fillRect(pt.mx - MARK / 2, pt.my - MARK / 2, MARK, MARK);
      ctx.strokeRect(pt.mx - MARK / 2 + 0.5, pt.my - MARK / 2 + 0.5, MARK - 1, MARK - 1);
      if (state) state.hits.push({ mx: pt.mx, my: pt.my, r: HIT_R, id: e.id });
    });
  }
  function hitAt(clientX, clientY) {
    const canvas = document.querySelector('#map-canvas');
    const state = window.__wocMapNpcs;
    if (!canvas || !state || !state.hits) return null;
    const box = canvas.getBoundingClientRect();
    const cx = (clientX - box.left) * canvas.width / box.width;
    const cy = (clientY - box.top) * canvas.height / box.height;
    let best = null, bestD = 1e9;
    for (const h of state.hits) {
      const d = Math.hypot(cx - h.mx, cy - h.my);
      if (d <= h.r && d < bestD) { best = h; bestD = d; }
    }
    if (!best) return null;
    const e = g.world && g.world.entities.get(best.id);
    if (!e || e.dead) return null;
    return { html: tipHtml(e) };
  }
  function bindHover() {
    const canvas = document.querySelector('#map-canvas');
    const state = window.__wocMapNpcs;
    if (!canvas || !state) return;
    state.handleMove = function(ev) {
      if (hud.mapLevel !== 'zone' || hud.mapDrag || ev.pointerType !== 'mouse') {
        state.hovering = false;
        return;
      }
      const hit = hitAt(ev.clientX, ev.clientY);
      if (hit) {
        state.hovering = true;
        hud.paintTooltipAt(hit.html, ev.clientX, ev.clientY);
      } else {
        const was = state.hovering;
        state.hovering = false;
        if (was) hud.hideTooltip();
      }
    };
    state.handleLeave = function() {
      const was = state.hovering;
      state.hovering = false;
      if (was) hud.hideTooltip();
    };
    if (!state.hideOrig) {
      state.hideOrig = hud.hideTooltip.bind(hud);
      hud.hideTooltip = function() {
        if (window.__wocMapNpcs && window.__wocMapNpcs.hovering) return;
        return state.hideOrig();
      };
    }
    if (!state.hoverBound) {
      canvas.addEventListener('pointermove', (ev) => {
        const fn = window.__wocMapNpcs && window.__wocMapNpcs.handleMove;
        if (fn) fn(ev);
      });
      canvas.addEventListener('pointerleave', () => {
        const fn = window.__wocMapNpcs && window.__wocMapNpcs.handleLeave;
        if (fn) fn();
      });
      state.hoverBound = true;
    }
  }
  const wrappedDraw = function(e, t, nbg, r, i) {
    const ret = nativeDraw(e, t, nbg, r, i);
    try {
      if (t && t.region && e && e.canvas && e.canvas.id === 'map-canvas') {
        paint(e, t.region, r || e.canvas.width);
      }
      bindHover();
    } catch (err) {}
    return ret;
  };
  painter.draw = wrappedDraw;
  window.__wocMapNpcs = Object.assign(prev || {}, {
    nativeDraw, hooked: wrappedDraw, paint, hits: [], hovering: false
  });
  try { hud.updateMapWindow(); } catch (err) {}
  return true;
})()
"""


def _load_woc_lib():
    candidates = []
    root = os.environ.get("BOTCRAFT_ROOT")
    if root:
        candidates.append(Path(root) / "examples" / "woc_lib.py")
    here = globals().get("__file__")
    if here:
        candidates.append(Path(here).with_name("woc_lib.py"))
    cwd = Path.cwd()
    candidates.extend([cwd / "examples" / "woc_lib.py", cwd / "woc_lib.py"])
    for path in candidates:
        if path.is_file():
            exec(path.read_text(encoding="utf-8"), globals())
            return
    raise FileNotFoundError(
        "Could not find examples/woc_lib.py. Run via .\\scripts\\map.ps1"
    )


def install_map_npc_markers():
    """Push MAP_NPC_JS into the live Chrome tab. Safe to call again after edits."""
    return j(MAP_NPC_JS)


def apply_overlay():
    activate_game()
    ok = install_map_npc_markers()
    info = j(
        r"""
(() => {
  const g = window.__game;
  const s = window.__wocMapNpcs || {};
  const w = g && g.world;
  const hud = g && g.hud;
  const win = document.querySelector('#map-window');
  const mapOpen = !!(win && win.style.display !== 'none' && !win.hidden);
  let living = 0, hostile = 0, npc = 0;
  if (w) {
    w.entities.forEach((e) => {
      if (!e || e.id === w.playerId || e.dead) return;
      if (e.kind !== 'mob' && e.kind !== 'npc') return;
      living += 1;
      if (e.hostile) hostile += 1;
      if (e.kind === 'npc') npc += 1;
    });
  }
  return {
    hooked: typeof s.paint === 'function',
    mapOpen,
    painted: (s.hits || []).length,
    living,
    hostile,
    npc,
    zone: hud && hud.mapZoneId
  };
})()
"""
    )
    rec = {"installed": bool(ok)}
    if isinstance(info, dict):
        rec.update(info)
    print("MAP overlay", json.dumps(rec))
    if not ok:
        raise SystemExit("Could not hook the map. Is World of ClaudeCraft open in Chrome?")
    if not rec.get("mapOpen"):
        print("MAP hint: open the world map (M) to see the squares")
    return rec


if not globals().get("_WOC_MAP_IMPORT"):
    os.environ["WOC_HALT_ON_EXIT"] = "0"
    _load_woc_lib()
    apply_overlay()
