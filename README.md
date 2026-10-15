# Markers to Render Queue

> Part of [PostFlows](https://github.com/postflows) toolkit for DaVinci Resolve

Batch add clips with timeline markers to the render queue. Filter by marker color and type (Single, Duration, or range-between-markers). Edit markers directly in the table, pick specific markers with checkboxes, custom naming with components, naming presets, optional folder-per-render. **Python** script.

## What it does

GUI for adding clips at marker positions to the render queue.

- **Filter** by marker color (dropdown shows live counts per color, e.g. `Blue (5)`) and by marker type:
  - **Single** — render the entire clip under each single marker.
  - **Duration** — render only the marker's own frame range (with validation).
  - **Single → Next Marker** — range from each single marker to the frame before the next marker of any color/type (last marker renders to the end of the timeline).
  - **Single → Next Same Color** — same as above, but the range extends to the next marker of the *same* color as the current color filter (handy for in/out pairs marked with one color).
- **Edit markers directly in the table** — double-click a Color, Marker Name, or Note cell to open a small dialog and change it (the marker is updated on the timeline immediately; Resolve has no in-place marker edit, so it's deleted and re-added under the hood). Double-clicking the Timecode column still jumps the playhead there, as before.
- **Checkboxes per row** — tick specific markers to either:
  - render only those (leave nothing checked to process every marker matching the current filter, as before), or
  - delete them from the timeline with the **Delete Checked** button (asks for confirmation). **Clear Checks** unchecks everything without deleting.
  - Checks are remembered by marker, so they survive filter changes and table refreshes.
- **Custom naming**: components (ProjectName, TimelineName, MarkerName, RenderFormat/Codec, etc.), shotID (auto/reel/source), task, version; save/load naming presets. Duplicate filenames are automatically given a numbered suffix so one render never silently overwrites another. Auto Number stays consistent whether you render everything or just a checked subset.
- Video track selection; export path history; optional subfolder per render (for EXR sequences). Use the render preset's own filename or custom naming.
- Render preset is validated before anything is queued — if it can't be loaded, the export is aborted up front instead of failing partway through.
- Works fine in an empty project (no timeline yet) — the UI opens without errors, just inert until a timeline with markers exists.
- The tool is locked to the timeline that was active in Resolve when it was launched (shown read-only next to "Timeline:"); it doesn't switch between timelines while its window is open — relaunch it if you need to work on a different one.

## Requirements

- DaVinci Resolve Studio
- An open project (a timeline with markers is needed to actually export, but the tool no longer errors if one isn't open yet)
- A render preset defined in the project

## Installation

Copy the **`markers-to-render-queue.py`** file to:

- **macOS:** `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/`
- **Windows:** `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\`

Run from **Workspace → Scripts** in Resolve (or from the Fusion page Scripts menu).

## Usage

1. Run the script.
2. Pick marker color, marker type/mode (Single, Duration, Single → Next Marker, Single → Next Same Color), and render preset.
3. Configure naming (or enable "Use filename from current render preset").
4. Optionally edit markers right in the table (double-click Color/Name/Note), delete unwanted ones, or tick checkboxes to render only a subset.
5. Choose export path; optionally "Create separate folder for each render".
6. Click **Add to Render Queue**.

Double-click a row's Timecode to jump the playhead there. The status line at the bottom reports what happened, including any markers that were skipped and why.

## Changelog

### 4.1
- **Fix: custom filenames ignored for Duration markers.** Filenames were only generated when a media clip sat exactly on the marker's first frame. If a Duration marker started on a title, Fusion composition, Solid Color or transition, the job got no `CustomName` and Resolve fell back to whatever name was left in the Deliver page (timeline name or a stale name from a previous job). Now:
  - Duration markers look for a media clip anywhere inside the marker range (largest overlap, topmost track / selected Video Track) — only needed for Source/Clip/Reel name components.
  - A marker is never skipped for naming just because no clip was found; Marker/Project/Timeline/Auto Number components don't need one.
  - With custom naming enabled, `CustomName` is always set (falls back to the marker name), so stale Deliver names are never inherited.

### 4.0
- Marker modes Single → Next Marker / Single → Next Same Color, in-table marker editing, per-row checkboxes (render subset / delete), duplicate filename protection, up-front render preset validation, empty-project support.

## License

MIT © PostFlows
