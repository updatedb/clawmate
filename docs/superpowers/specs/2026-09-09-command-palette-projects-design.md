# Command Palette — Projects-first + MRU + search chips — Design

Date: 2026-09-09 · Status: approved (approach A) · Area: index command palette (Ctrl/Cmd+K)

## Problem

The command palette currently mixes root hints, directory hints, file/content search
actions, and projects as flat list rows. The goal is to make it **project-first**:
the default view shows only projects as cards, sorted by most-recently-used, with the
two search shortcuts as a fixed chip row right under the input. Plus a small companion
tweak: horizontally center the breadcrumb/title content in the index and preview topbars.

## Requirements (from user)

- TODO1 — `cpList` shows **only projects**, sorted by **most-recently-used (newest first)**.
- TODO2 — projects shown as **flat cards**, **not grouped by root** (no root fold).
- TODO3 — typing **auto-filters projects by name** as you type.
- TODO4 — **file search + content search** placed **after the input box**; clicking one
  runs the search and shows results in the index (palette closes).
- Companion — center all content within index `.path-title-wrap` and preview
  `.preview-topbar-title-wrap`.

## Decisions (confirmed)

- **root fold** = flat cards, no per-root grouping.
- **MRU source** = both: a client-side `localStorage` record (preferred) + the project's
  `mtime` from `/api/clawmate/list` (fallback for projects never opened this session/browser).
- **search actions** = the existing two: `文件搜索` (`fileSearch`, recursive filename)
  and `内容搜索` (`contentSearch`, ripgrep). No new backend endpoint.

## Architecture

### Palette structure (index.html + command-palette.css)

```
[ input box ........................ ↑↓·Enter·Esc ]   ← existing
[ 文件搜索 | 内容搜索 ]                               ← NEW: fixed chip row below input, not list items
[ project card grid ................................ ] ← cpList: only project cards (flat)
```

- Remove `_pushSearchActions()` (no longer list items). The search chips live in a
  dedicated row under the input, styled like a button group.
- `.cp-list` renders only project cards (grid/flex-wrap), each card carrying:
  project name, its root id/label, and a last-used-time line (or `—` if never used).

### Project loading + MRU (command-palette.js)

- On open, fetch each root's projects via existing
  `GET /api/clawmate/list?root=<id>&dir=&marker_filter=true`. Each entry already includes
  `name`, `is_dir`, `mtime`, `marker`.
- Read MRU from `localStorage["clawmate.recentProjects"]` = a map `"<rootId>/<name>" -> epochMs`.
- **Sort**: projects with an MRU record first, descending by record time; projects without
  a record after them, descending by `entry.mtime`. (Stable, deterministic.)
- **Record on use**: write `{"<rootId>/<name>": Date.now()}` to the MRU map whenever a
  project is entered — from the palette's `switchProject()` and from the project panel
  open path (`app.js` `_setProjectPanelOpen(true)`).
- `render(query)` filters the project list by `label.toLowerCase().indexOf(q)` (existing
  local filter, unchanged) and renders cards. No async file search.

### Search chips (TODO4)

- Two fixed chips under the input: `文件搜索` and `内容搜索`.
- Clicking a chip runs `fileSearch(inputValue)` / `contentSearch(inputValue)`, then
  `close()`; the index renders the results (existing behavior, unchanged functions).
- The chips are always visible (default view), independent of the project list.

### Companion centering

- `.path-title-wrap` (index) and `.preview-topbar-title-wrap` (preview) already have
  `align-items: center` (vertical). Add `justify-content: center` so the breadcrumb /
  document title are horizontally centered within the flex-1 wrapper.

## Files touched

- `dev/static/js/command-palette.js` — remove search-action items; add card rendering,
  MRU read/sort, search-chip handler, `switchProject` MRU write.
- `dev/static/css/command-palette.css` — add `.cp-chips` row + `.cp-card` styles; adjust
  `.cp-list` into a card grid.
- `dev/static/index.html` — add the search-chip row markup; adjust `#cpList` container.
- `dev/static/js/app.js` — write MRU record when a project panel opens.
- `dev/static/css/style.css` — `justify-content: center` on `.path-title-wrap`.
- `dev/static/css/preview.css` — `justify-content: center` on `.preview-topbar-title-wrap`.

## Data flow

1. `Ctrl+K` → `open()` → `loadProjectsForLayout()` fetches all roots' projects + reads MRU.
2. Sort MRU+fallback → `render("")` draws card grid + chip row.
3. Type → `render(q)` filters cards by name (live).
4. Click card → write MRU → `switchProject(name, rootId)` (switch root + `loadDir`) → `close()`.
5. Click 文件搜索/内容搜索 → `fileSearch(q)`/`contentSearch(q)` → `close()` → index shows results.

## Testing

- Manual: open palette (default = only project cards, MRU-sorted, cards not rows); type to
  filter; CLI click a search chip → index results; click a project → jumps + closes.
- Verify `.path-title-wrap` / `.preview-topbar-title-wrap` content centers on desktop + mobile.
- Run full pytest suite; update any `command-palette`/search contract test that hardcodes
  the old list-row items or the search-action-in-list structure.

## Non-goals

- No backend MRU endpoint (client-side only).
- No per-root grouping/fold.
- No new search type (reuses existing fileSearch/contentSearch).
