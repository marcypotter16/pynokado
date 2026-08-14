---
name: run-game
description: Launch, drive and screenshot the pynokado pygame window on this machine. Use when asked to run the game, start the app, take a screenshot of it, check how a change looks on screen, or switch the terrain view (glyphmap / colmap / heightmap). Covers the Windows 200%-DPI trap that silently crops every capture.
---

# Running and screenshotting pynokado

```bash
uv run main.py
```

That is the whole launch. `main.py` pushes `BoardTestState`, which builds the
parchment background, the `Board` (grid + `Terrain` + `Weather`) and the map-mode
menu. No env vars, no flags, no display server setup — this is a real Windows
desktop.

The window is **fullscreen** (`Settings.FULLSCREEN` defaults to `True` and
`settings.json` does not override it), titled `pygame window`, process name
`python`.

## THE DPI RULE — read this before any screen coordinate

This machine runs a **2880x1800 physical screen at 200% scaling**, so the logical
desktop is 1440x900. **Every physical dimension is 2x the logical one.**

A process that is not DPI-aware — which includes PowerShell by default — gets
*logical* numbers back from `GetWindowRect`, then `CopyFromScreen` treats them as
*physical*. The capture silently succeeds and returns the **top-left quarter** of
the screen. It looks like a zoomed-in game, not like an error.

Two ways out; use the first:

1. Call `SetProcessDPIAware()` before measuring anything (see script below).
2. Or multiply every logical dimension by 2 by hand.

`GetSystemMetrics(0/1)` is a good check: if it prints 1440x900 you are NOT
DPI-aware yet and everything downstream is wrong.

## Screenshot recipe (works; use it verbatim)

Three things this handles that a naive capture does not: DPI awareness, the
window being **minimized** (`GetWindowRect` returns `-32000,-32000` — restore it
first with `ShowWindow(h, 9)`), and the repaint delay after raising it.

`CopyFromScreen` is required rather than `PrintWindow`: the game renders through
moderngl/OpenGL, which `PrintWindow` captures as black. That also means the
window must be **unoccluded** — raise it and wait before capturing.

```powershell
Add-Type @'
using System;
using System.Runtime.InteropServices;
public class Cap {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  public struct RECT { public int Left, Top, Right, Bottom; }
}
'@
[void][Cap]::SetProcessDPIAware()          # MUST come before any measurement
Add-Type -AssemblyName System.Drawing
$h = (Get-Process | Where-Object { $_.MainWindowTitle -eq 'pygame window' }).MainWindowHandle
[void][Cap]::ShowWindow($h, 9)             # SW_RESTORE: it is often minimized
Start-Sleep -Milliseconds 400
[void][Cap]::SetForegroundWindow($h)
Start-Sleep -Milliseconds 1500             # let it raise and repaint
$r = New-Object Cap+RECT
[void][Cap]::GetWindowRect($h, [ref]$r)
$w = $r.Right - $r.Left; $ht = $r.Bottom - $r.Top
if ($w -lt 100) { throw "still minimized ($w x $ht)" }
$bmp = New-Object System.Drawing.Bitmap($w, $ht)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.Left, $r.Top, 0, 0, $bmp.Size)
$bmp.Save("<scratchpad>\shot.png", [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output "$w x $ht"                    # expect 2880 x 1800
```

**Then Read the PNG.** A 1440x900 result means DPI awareness did not take. A
black frame means the window was occluded or GL had not drawn yet.

### Is the running window even testing your change?

There is usually already an instance running, and it may predate your edits.
Compare before trusting a screenshot:

```powershell
(Get-Process -Id <pid>).StartTime.ToString("yyyy-MM-dd HH:mm:ss")
(Get-Item Models\Terrain.py).LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
```

Always format explicitly — the default rendering mixes `MM/dd` and `dd/MM` in the
same output and is genuinely unreadable. If the process is older than the edit,
relaunch instead of screenshotting a stale build.

## Driving it

Keyboard (handled in `Board.update`):

| Key | Effect |
|---|---|
| `A` | toggle brush mode (grow the board graph) |
| `S` | toggle the extendable-node markers |

The **terrain view has no key binding** — `glyphmap` / `colmap` / `heightmap` are
`TextButton`s in a `VertContainer` built in `States/BoardTestState.py`, anchored
at `0.85 * GAME_W, 0.8 * GAME_H` with `GAME_W, GAME_H = 1920, 1080` (game space,
letterbox-corrected; NOT the physical resolution). Clicking them from a script
means mapping game space -> physical pixels, so prefer either asking the user to
click, or launching your own driver that calls
`state.board.change_terrain_mode(TerrainMode.COLOURMAP)` before `game_loop()`.

`colmap` is the flat biome wash and is the view to use when checking
classification work — it also shows the hovered-biome tooltip
(`Board._render_biome_tooltip`), which only draws in that mode.

## Headless verification (faster than screenshotting)

Most terrain work does not need the window at all. `Terrain` builds standalone,
and `SDL_VIDEODRIVER=dummy` lets it run with no display:

```bash
SDL_VIDEODRIVER=dummy uv run python your_check.py
```

The script still needs `p.init()` and `p.display.set_mode((1, 1))` before
loading any sprite — `image.load(...).convert_alpha()` and `surfarray` both
require a display mode. From there `Terrain(NoiseParams(...), ...)` gives you
`biome_mat`, `height_map`, `surface_for(mode)` and `_render_biomes()` to assert
against, across several seeds, in seconds. Prefer this for anything you can
express as a number; screenshot only to judge how it *looks*.

`scratch/terrain_preview.py` is an existing interactive preview of every terrain
view (`[R]` cycles, ESC quits) — `uv run scratch/terrain_preview.py`, from the
repo root.
