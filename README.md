# ROM Mapper

ROM Mapper builds folder layouts for emulation frontends (Batocera/RGS, RetroBat, Knulli, ...)
and for [RomM](https://github.com/rommapp/romm) out of **links** into your ROM folders. Nothing is
copied or moved: each frontend gets its own folder of links, named the way that frontend expects,
pointing at the one copy of your files.

It runs as a small web app in Docker (made for Unraid) and keeps the links up to date on a
schedule. The page has two tabs of equal standing: **Frontend links** (the mapping grid) and
**RomM**. The open tab is kept in the address (`#links`, `#romm`) and remembered by the browser.

- **New here?** Follow the [user guide](docs/user-guide.md).
- **What changed?** See the [changelog](CHANGELOG.md) and the [releases](../../releases). The running
  version is shown next to the title in the web page.
- **Working on the code (people or AI assistants)?** This README is the full reference; coding
  rules are in [CLAUDE.md](CLAUDE.md).

---

## Contents

1. [Features](#features)
2. [Install](#install)
3. [How it works](#how-it-works)
4. [RomM](#romm)
5. [Settings and files](#settings-and-files)
6. [Import and export](#import-and-export)
7. [Upgrading from older versions](#upgrading-from-older-versions)
8. [HTTP API](#http-api)
9. [Code map](#code-map)
10. [Development, tests and releases](#development-tests-and-releases)

---

## Features

| Area | What it does |
|---|---|
| Mapping grid | One row per folder found in your source folders, one column per frontend. Type the name a frontend should see; blank = no link. Double-click an empty cell to use the folder's own name. |
| Source folders | Any number of folders, each read to a chosen depth (1 = folders directly inside it, 2 = also the folders inside those, up to 6). Rows show the source folder's name in front: `<source>/<path>`. |
| Frontends | Add or remove columns. Each frontend can also link every system's `media/` folder into a sub-folder (default `MEDIA_FULL`). |
| Links | **Resync all** makes the mapping folder match the mapping: missing links are made, wrong ones corrected, unused ones removed - nothing else is touched, and frontends never see an empty folder. |
| Status | Rows are marked *New* (on disk, not mapped yet), *Unmapped*, *Missing* (mapped, gone from disk). Filter by status, search, remove missing rows. Duplicate names for one frontend are highlighted (the first row gets the link). |
| Schedule | Scan every N minutes (optionally adding new folders automatically) and resync every N hours. |
| Import / export | Download the mapping as a CSV that lists **every** folder found (ready to fill in, e.g. in a spreadsheet) and load one back - merged into the grid or replacing it. |
| RomM | Maps one or more download folders to RomM platforms: platform links in one folder, a generated `config.yml`, per-folder choices, overlap handling. |
| Storage | Everything is stored by the app in its config folder (JSON); no files to edit by hand. |

---

## Install

### Docker (Unraid or any Docker host)

ROM Mapper needs **one** folder mounted at the **same path** inside the container as on the host,
containing everything it uses: your source folders, the mapping folder and RomM's download
folders. Pick a folder high enough to cover them all (on Unraid, the user-shares folder covers every
share). Folders are then chosen in the web page - adding one never needs another mapping.

**Unraid (Compose Manager):** Docker > Compose > Add New Stack `rom-mapper` > Edit Stack, paste
[`unraid/docker-compose.yml`](unraid/docker-compose.yml), set the paths, then **Compose Up**. It
builds the image straight from GitHub; every Compose Up updates to the latest version.

**Any Docker host:**

```bash
git clone https://github.com/sireteanu/rom-mapper.git /path/to/appdata/rom-mapper
cd /path/to/appdata/rom-mapper
cp .env.example .env     # set the paths
docker compose up -d --build
```

`.env`:

| Variable | Meaning |
|---|---|
| `CONFIG_DIR` | Host folder for the app's settings and mapping (mounted as `/config`) |
| `EMULATION_ROOT` | The one folder mounted at the same path (contains everything below) |
| `ROMS_PATH` | First source folder, used until you set the list in the page |
| `MAPPING_PATH` | The mapping folder: one sub-folder of links per frontend |
| `ROMM_SOURCE` | Optional: RomM download folders (`;`-separated) until set in the page |
| `PUID` / `PGID` | User/group the container runs as (Unraid: 99/100) |
| `WEBUI_PORT` | Port of the web page (default 8085) |
| `TZ` | Time zone for the schedule |

Or with `docker run`:

```bash
docker build -t rom-mapper .
docker run -d --name rom-mapper --restart unless-stopped --user 99:100 -p 8085:8085 \
  -e TZ=America/New_York -e SRC_BASE=/path/to/roms -e DEST_PATH=/path/to/mapping \
  -v /path/to/appdata/rom-mapper-config:/config -v /path/to/shares:/path/to/shares rom-mapper
```

Open `http://SERVER:8085/`. There is no login - keep the port on your LAN.

**Update:** Compose Manager: **Compose Up**. Otherwise `git pull`, then `docker compose up -d --build`.
Settings and mapping are kept.

**Why the same path?** Links are absolute. A folder mounted at `/roms` inside the container would
produce links to `/roms/...`, which don't exist on the host.

**Permissions:** the container user needs write access to the config folder, the mapping folder
and (for RomM) the folder that holds the download folders.

### Without Docker

```bash
pip install -r requirements.txt
CONFIG_DIR=/path/to/config SRC_BASE=/path/to/roms DEST_PATH=/path/to/mapping python app/server.py
```

One-off resync without the web page: `python app/server.py --resync` (in Docker:
`docker exec rom-mapper python /app/server.py --resync`).

---

## How it works

### Rows and keys

Every row is a folder written as `<source name>/<path inside it>`, e.g. `roms/snes` or
`downloads/Nintendo/Super Famicom`. The source name is the source folder's own name (made unique
with `-2`, `-3` if two have the same name) and stays the same when you reorder the list, so saved
rows keep pointing at the right place. A row without a known source name in front (from older
versions) belongs to the **first** source folder.

### Scanning

**Scan now** (and the scheduled scan) reads every source folder down to its depth. Folders starting
with `.`, folders named `media`, and links are skipped. Folders that aren't in the mapping yet are
*New*; with *Auto-add new folders* they're added to the mapping (unmapped). Mapped folders that no
longer exist are *Missing* - their links wait until they come back. The page re-reads the folders
when it refreshes (every 30 s, reusing a listing up to 10 s old).

### Links (Resync)

For every row and frontend with a name:

```
<mapping folder>/<frontend>/<name>  ->  <source folder>/<path>
```

`<name>` may contain `/` (e.g. `SDCARD/snes`). With *link media/ folders* on for a frontend, and a
`media` folder inside the source folder:

```
<mapping folder>/<frontend>/<media location>/<name without its first part>/media  ->  <source folder>/<path>/media
```

A resync compares what should exist with what does: it creates missing links, corrects links that
point elsewhere, removes links no row wants any more (and folders left empty), and leaves
everything else alone. Only links are ever removed - a real file or folder in the mapping folder is
reported and kept. When two rows give one frontend the same name, the first row (grid order) gets
the link and the output says which was skipped. The mapping folder may not be `/`, a top-level
share folder, inside a source folder, or contain one.

---

## RomM

RomM wants one folder per platform, named by its *slug* (`snes`, `psx`, ...), all directly inside
its roms folder. The **RomM** tab maps your download folders to that without moving anything; its
**Refresh** and **Create / update links now** buttons sit at the top, where the grid's buttons are on
the other tab.

- **Download folders**: a list in priority order (add, remove, move up/down). Each is read from
  disk completely; rows start with the folder's name. Folders get a platform from built-in rules
  for lolroms' folder tree (e.g. `Nintendo/Super Famicom` -> `snes`), or automatically when a folder
  right inside a download folder is named exactly like a RomM platform (`snes`). Subfolders join
  their parent's platform (variants, translations), except raw dumps and similar (skipped) and
  `BIOS` folders (firmware).
- **Your choices**: every folder has a dropdown with every RomM platform and **exclude**. Excluding a
  folder leaves it **and everything inside it** out of RomM, unless you choose something else for a
  subfolder. Choices are saved immediately.
- **Overlaps**: when two download folders give the same platform, the one higher in the list is
  used; the other's rows say *not linked* and a warning names both. *Overlaps only* in the filter
  shows just those rows.
- **Platform links**: relative links named after the platforms, kept in the folder that holds the
  download folders (the *links folder*): `<links folder>/<slug> -> <download folder>/<path>`. Map the
  links folder as RomM's roms folder (the **RomM compose** tab shows the line).
  **Create / update links now** makes them and turns on *Update the links with every scan*. Only
  links pointing into a download folder are ever changed or removed; real folders and other links
  are left alone. All download folders must be inside the links folder.
- **config.yml**: merge the generated section into RomM's `config.yml`: the download folders aren't
  platforms (`exclude.platforms`), which subfolders belong to a platform (`{category}` levels by
  default, or exact names), which to ignore, and `system.versions` for arcade boards RomM has no
  platform for. Firmware isn't linked (RomM's bios folder is separate) - the dialog lists the
  folders to copy. Restart RomM and scan its library.
- **RomM platforms list**: every platform RomM knows (slug, name, maker), searchable.

RomM facts this relies on are listed in `app/romm.py`'s docstring - re-check them when RomM changes.

---

## Settings and files

All in the config folder (`/config` in Docker):

| File | What |
|---|---|
| `rom-mapper-mapping.json` | The mapping: frontends (name, media toggle, media location) and rows (folder, one name per frontend) |
| `rom-mapper-mapping.json.bak` | The previous version, written on every save |
| `rom-mapper-state.json` | Source folders, schedule settings, last scan and last resync |
| `romm-mapper.json` | RomM: download folders (`sources`), links folder, options, your choices (`map`, by `<download folder>/<path>`) |

Files are written to a temporary file first and then swapped in, so a crash never leaves half a
file. Environment variables: `CONFIG_DIR` (else the folder of `INPUT_CSV`), `INPUT_CSV` (an older
CSV to import once), `SRC_BASE` (first source folder(s), `;`-separated), `DEST_PATH` (mapping
folder), `ROMM_SOURCE`, `PORT` (8085), `MAPPING_FILE`, `STATE_FILE`.

---

## Import and export

- **Export** downloads `rom-mapping-<date>.csv` with what the grid shows, unsaved edits included:
  a header (`Folder`, then one column per frontend), the `Media Toggle` and `Media Location` rows,
  and one row per folder - **every folder found in the source folders**, mapped or not, so the file
  is ready to fill in. UTF-8 with a BOM and Windows line endings (opens cleanly in Excel).
- **Import** reads such a file (also the older `Rom_Mapping.csv`; quotes, BOM and either line ending
  are fine). Folders get their source name in front like in the grid. Choose **Merge** (folders in
  the file get its names; other folders and frontends stay; missing frontends are added) or
  **Replace** (the grid becomes the file). Problems (commas, `..`, ...) are listed. Nothing is saved
  until you click **Save**.

---

## Upgrading from older versions

Older files keep working; the tests in `tests/test_upgrades.py` check every case:

- **`Rom_Mapping.csv`** (before 1.0.0): imported once at the first start into
  `rom-mapper-mapping.json`; the CSV is left untouched and no longer read. Its rows (plain folder
  names) belong to the first source folder, so every link stays where it was.
- **Rows without a source name** keep pointing at the first source folder, even after the list is
  reordered (they get the name written in front when the order changes).
- **`romm-mapper.json` with one folder** (`source`) or from Rom Sync (no folder list, choices
  without a folder name): converted to the folder list; choices get the first folder's name in
  front; a relative links folder is dropped.
- **`rom-mapper.sh`** (the bash script before 1.0.0) is replaced by the built-in resync, which makes
  the same links.

---

## HTTP API

JSON throughout; the page uses nothing else.

| Method & path | Purpose |
|---|---|
| `GET /api/state` | Mapping (frontends, rows with status), `version` (for saving), `app_version`, source folders, paths, settings, last scan/resync, `sync_running` |
| `PUT /api/mapping` `{version, frontends, rows, resync?, force?}` | Save (409 if the mapping changed since `version`; `force` overrides); 400 with details on invalid names |
| `PUT /api/sources` `{sources: [{path, depth}]}` | Set the source folders (labels are kept per path) |
| `POST /api/scan` · `POST /api/sync` · `GET /api/sync` | Scan now · start a resync (409 when running) · resync status |
| `PUT /api/settings` | Schedule settings |
| `POST /api/import` (CSV text) | Parse a mapping CSV -> `{frontends, rows, problems}` (not saved) |
| `GET /api/activity` | Recent events |
| `GET /api/romm` · `PUT /api/romm/options` · `PUT /api/romm/map {path, action}` · `POST /api/romm/links` | RomM dialog data, options/download folders, a folder's choice, create/update the platform links |

---

## Code map

```
app/server.py     Flask app: settings, mapping storage + import, source folders, scan, resync,
                  scheduler, RomM endpoints; `python server.py --resync` for a one-off resync
app/links.py      the link engine: desired links from the mapping, apply only the differences
app/romm.py       RomM mapping (RULES for lolroms' tree, Mapping with several roots, templates,
                  config.yml, apply_links); romm_slugs.py = RomM's platform list (vendored)
app/version.py    __version__ (shown in the page, used for releases)
app/static/index.html   the whole page (HTML, CSS, JS; no build step)
tests/            pytest: test_mapping, test_romm, test_upgrades (temporary folders only)
.github/workflows tests.yml (every push), release.yml (a release per new version)
unraid/           docker-compose.yml for Unraid's Compose Manager (builds from GitHub)
```

---

## Development, tests and releases

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest              # all tests run on temporary folders
python -m pyflakes app tests
```

- Every change to the app is a new version: bump `app/version.py` (last number for fixes and small
  features, middle number for bigger changes) and add a `## [x.y.z] - date` section to
  `CHANGELOG.md` (plain words, grouped New / Improved / Fixed / Changed). On push to `main`, the
  **Release** workflow runs the tests and publishes release `vx.y.z` with that section as its text;
  correcting a section later updates the release text. The **Tests** workflow runs on every push.
- Every behaviour change gets a test; anything that reads older files gets a case in
  `tests/test_upgrades.py`.
- Documentation (this README, the user guide, the changelog) is updated in the same commit.
