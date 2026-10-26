# Sewer Profile Viewer (QGIS plugin)

English | [한국어](README.md)

Splits a sewer network into a **tree of runs between junctions** and draws the **longitudinal profile** of the selected run in a QGIS bottom panel.
Hover over a pipe on the map and a red dot follows the line while the profile shows the same chainage (it also works from profile to map).

> The plugin UI and the default field names are in Korean (Korean sewer design practice). See [Layer fields](#layer-fields) for mapping your own field names.

## Installation

### Easiest: ask an AI to do it
Tell an AI that can **run commands on your PC** (Claude Code, Cursor, etc.):

> Install the QGIS plugin from https://github.com/taylee9809/qgis-sewer-profile

The AI reads the [AI install steps](#ai-install-steps) below and handles download, unzip and activation.
Then restart QGIS and click the profile icon on the toolbar.
(A web-only chat AI can't put files on your PC, so use the manual install instead.)

### Manual install
1. Download `sewer_profile.zip` from the [latest release](https://github.com/taylee9809/qgis-sewer-profile/releases/latest).
2. QGIS → **Plugins → Manage and Install Plugins → Install from ZIP** → choose the zip → **Install Plugin**.
3. On the **Installed** tab, make sure `Sewer Profile Viewer` is checked, then open the panel from the toolbar icon.

Requires QGIS 3.22 or later. Nothing else to install (matplotlib ships with QGIS).

### AI install steps
Steps for an AI agent. Humans can skip this.
1. Download: `https://github.com/taylee9809/qgis-sewer-profile/releases/latest/download/sewer_profile.zip`
2. Unzip into the plugins folder (`<plugins>`) so that `<plugins>/sewer_profile/metadata.txt` exists. The folder must be named `sewer_profile`.
   - Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins`
   - macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins`
   - Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins`
   - If the profile isn't `default`, use the actual profile name under `profiles/`. If a `sewer_profile` folder already exists, delete it and unzip fresh (update).
3. Enable: **with QGIS closed**, add `sewer_profile=true` under `[PythonPlugins]` in `profiles/<profile>/QGIS/QGIS3.ini` (create the section if missing). QGIS rewrites the ini on exit, so if QGIS is running, ask the user to close it first, or tell them to tick the plugin in the Plugin Manager instead.
4. Tell the user to restart QGIS and click the Sewer Profile toolbar icon. If their field names differ from the table below, tell them to add candidates to `PIPE_FIELDS` / `MH_FIELDS` in `sewer_profile/network.py`.

## Features
- Line layer → pipe graph (endpoints within 0.05 m are one node) → runs split at junctions, shown as a tree
  - Root = outfall run, children = branches joining at its start. Children are sorted by upstream length (main line first)
  - Grouped by district; runs containing force mains are shown in pink
- Select a run → profile: ground line (manhole ground level or 2 m DEM sampling), invert and crown lines, manholes, drops, crossing utilities
  - Ctrl-select several runs and they are joined if they connect up/downstream
  - `방류까지` (to outfall) / `상류 본선` (upstream main) checkboxes extend the run automatically
  - Pipe colour: type (gravity / force main) · hydraulic check result (`금회_수리판정`)
- **Pick a layer and the tree builds itself** (press Enter after editing the filter to rebuild)
- **Select a pipe on the map → tree selects and expands → profile shows**, cursor jumps to the clicked spot
  - `지도에서 고르기` (pick on map) button (nearest pipe to the click) or any QGIS selection tool
- Map ↔ profile cursor sync with info readout (chainage, pipe ID, ground level, invert, cover, slope, cumulative flow, velocity)
- Double-click in the tree → zoom map; matplotlib toolbar for zoom/pan/PNG; **mouse-wheel zoom**
- **Display: drawing style (default)** — mimics a typical Korean sewer profile DXF sheet (H 1:1000 · V 1:200 by default, V scale selectable)
  - 7 bottom bands (station, distance, cumulative distance, ground level, invert, cover, slope), manhole circles + inverts in the slope band, `L=..M, H=..M` / `S=..‰`
  - Pipe ID bar and pipe type bar (`신설오수, D=200MM`), double-square manholes with 45° leaders (`SW-A-001 1호맨홀`, `H=..M (dh=..M)`)
  - Crossing utilities as ellipses (true width × V exaggeration) with 45° three-line labels (type, INV.EL., NO.)
  - When the line leaves the frame vertically the **DATUM changes at a manhole (break line)**, as on real drawings, so long runs keep their height
  - Text is in drawing units (TextPath), so it scales with zoom like CAD
  - The profile pans to follow the map cursor when it goes off-screen
- Display: simple — elevation-axis chart, pipe colour (type / hydraulic result)

## Layer fields
Default (Korean) field names:

| Purpose | Field |
|---|---|
| Pipe ID | `관번호` |
| Invert levels | `상류관저고` (upstream), `하류관저고` (downstream) |
| Diameter (mm) | `관경` |
| Ground level | `상류지반고` (the last node uses manhole layer field `지반고`) |
| Type | `구분` (force main → pink) |
| Crossing utilities | `종단지장물` — `횡배수관 D600@13.3(74.70) / BOX D2.00X1.00@3.3(25.50)` (chainage = m from pipe start, brackets = bottom EL) |
| Check / flow | `금회_수리판정`, `수리판정`, `금회_누가유량_m3d`, `금회_실유속_mps`, `경사퍼밀` |

To use other names, add them to the candidate lists `PIPE_FIELDS` / `MH_FIELDS` in `sewer_profile/network.py`.
Line geometry must run **upstream → downstream**.

## Development install
Clone the repo and junction it into the QGIS plugins folder:
```powershell
New-Item -ItemType Junction -Path "$env:APPDATA\QGIS\QGIS3\profiles\default\python\plugins\sewer_profile" -Target "<repo>\sewer_profile"
```
Enable `Sewer Profile Viewer` in the Plugin Manager and open the panel from the toolbar icon.
After editing code, use Plugin Reloader or `qgis.utils.reloadPlugin('sewer_profile')` in the Python console.

## Performance (1,227 pipes · longest run 8.7 km)
Tree build 0.05 s · map selection → profile 0.2–0.3 s · 8.7 km drawing style 2.3 s · pan after zoom 0.4 s.
Drawing-style text is only built when visible and at least 3 px tall (building it all took 44 s).

## Known limitations
- Circular crossing utilities take `bottom EL + 0.30` as their invert (hydraulic .flo convention). BOX culverts are drawn from bottom EL.
- If you select runs from different branches of a fork they can't be laid out on one line, so only the last selection is drawn.
