# ROM Mapper

ROM Mapper builds folder layouts for emulation frontends (Batocera/RGS, RetroBat, Knulli, ...)
out of **links** into your ROM folders, and gives [RomM](https://github.com/rommapp/romm) its
platform folders as volume mounts of your folders. Nothing is copied or moved: each frontend gets its own folder of
links, named the way that frontend expects, pointing at the one copy of your files.

It runs as a small web app in Docker on Linux (made for Unraid) and keeps the links up to date on
a schedule. **Linux and Docker only** - it relies on Linux paths and symlinks; Windows and macOS
hosts aren't supported. The page has two tabs of equal standing: **Frontend links** (the mapping grid) and
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
6. [Upgrading from older versions](#upgrading-from-older-versions)
7. [HTTP API](#http-api)
8. [Code map](#code-map)
9. [Development, tests and releases](#development-tests-and-releases)

---

## Features

| Area | What it does |
|---|---|
| Mapping grid | One row per folder found in your source folders, one column per frontend. Type the name a frontend should see; blank = no link. Double-click an empty cell to use the folder's own name. |
| Source folders | Any number of folders, each read to a chosen depth (1 = folders directly inside it, 2 = also the folders inside those, up to 6). Rows show the source folder's name in front: `<source>/<path>`. |
| Frontends | Add or remove columns. Each frontend can also link every system's `media/` folder into a sub-folder (default `MEDIA_FULL`). |
| Links | **Resync all** makes the mapping folder match the mapping: missing links are made, wrong ones corrected, unused ones removed - nothing else is touched, and frontends never see an empty folder. |
| Status | Rows are marked *New* (on disk, not mapped yet), *Unmapped*, *Missing* (mapped, gone from disk). Filter by status, search, remove missing rows. Duplicate names for one frontend are highlighted (the first row gets the link). |
| Schedule | Scan and resync each on their own interval, in minutes, hours or days (scans can add new folders automatically). |
| RomM | Pick the RomM platform for any of your folders; ROM Mapper generates the volume lines for RomM's compose file (each folder mounted as `roms/<platform>`) and a `config.yml` with category levels for platforms with subfolders. |
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

### Without Docker (Linux)

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
when it refreshes (every 30 s, reusing a listing up to 10 s old). A page in a hidden browser tab
doesn't refresh, so a forgotten tab doesn't keep disks awake; it refreshes as soon as you come back.

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

RomM wants one folder per platform, named by its *slug* (`snes`, `psx`, ...), directly inside its
roms folder. ROM Mapper decides which of your folders is which platform and gives you the
**volume lines for RomM's compose file**: each of those folders is mounted into RomM's container
under the platform's name, by Docker, every time RomM starts:

```yaml
    volumes:                      # the RomM service
      - "/path/to/roms/amigacdtv:/romm/library/roms/commodore-cdtv"
      - "/path/to/roms/gbc:/romm/library/roms/gbc"
      - "/path/to/lolroms/Nintendo/Super Famicom:/romm/library/roms/snes"
```

RomM sees plain folders with the right names - no renames, no platform excludes, nothing moved, no
script and no extra rights for ROM Mapper. These lines replace RomM's own `.../romm/library/roms`
line. After a change, paste them again and **Compose Up** RomM (a folder with a `:` in its name
gets compose's long syntax; add `:ro` / `read_only: true` for read-only).

- **Download folders**: any number; any folder in them can be a platform, nested ones too. Read
  in the background with a progress bar; counts are reused for 30 s, after that only folders whose
  date changed are listed again, with a full read every hour and on **Refresh**.
- **Levels**: how deep the list goes. Use at least **2 levels** where systems have subfolders
  (`gbc/+translations`): at 1 level subfolders aren't read and can't become categories (a warning
  says so). **Never read folders named** (default `media`) skips folders everywhere and tells RomM to
  ignore them too. Excluded folders aren't read inside.
- **Platforms**: folders named like a RomM platform get it automatically, lolroms' tree has built-in
  rules; pick the rest in the searchable picker, or **exclude**. A platform counts when it or anything
  below it has files. Two folders for one platform: the one named like it wins, else the shallower,
  else the first by name (a warning names both).
- **Categories**: a platform whose subfolders belong to it (*category of gbc* in the list) gets
  `roms/{platform}/{game}` and `roms/{platform}/{category}/{game}`, keyed by the platform. Every such
  subfolder is then a category - exclude (or never-read) the ones that aren't, like `images` or
  `manuals`. A subfolder that is a platform of its own (lolroms' `Satellaview`) gets its own mount.
- **RomM volumes** tab: the volume lines above, for the RomM service in its compose file.
- **config.yml**: merge into RomM's `config.yml` and restart RomM - `filesystem.structure` (default,
  firmware, the platforms with categories), `exclude.roms.multi_file.names` (subfolders that aren't
  games: never-read names, firmware, raw dumps, your excludes, platforms of their own) and
  `system.versions` for arcade boards RomM has no platform for.

Older versions made platform links next to the download folders: **Remove old platform links** (top
right) appears while any are left and removes only those.

RomM facts this relies on are listed in `app/romm.py`'s docstring - re-check them when RomM changes.

---

## Settings and files

All in the config folder (`/config` in Docker):

| File | What |
|---|---|
| `rom-mapper-mapping.json` | The mapping: frontends (name, media toggle, media location) and rows (folder, one name per frontend) |
| `rom-mapper-mapping.json.bak` | The previous version, written on every save |
| `rom-mapper-state.json` | Source folders, schedule settings (`scan_every` / `scan_unit`, `sync_every` / `sync_unit`; units `minutes`, `hours`, `days`), last scan and last resync |
| `romm-mapper.json` | RomM: download folders (`sources`), levels per folder (`depths`, only those not set to all), folder names never read (`skip_names`; missing = `["media"]`), your choices (`map`, by `<download folder>/<path>`: a slug, `exclude`, ...; 1.0.9's `cat:<slug>` reads as the slug). Settings of the platform-links versions (`links_dir`, `keep_links`, `romm_folder`, `layout`, `variants`, `mode`) are ignored |

Files are written to a temporary file first and then swapped in, so a crash never leaves half a
file. Environment variables: `CONFIG_DIR` (default `/config`), `SRC_BASE` (first source folder(s),
`;`-separated), `DEST_PATH` (mapping folder), `ROMM_SOURCE`, `PORT` (8085), `MAPPING_FILE`,
`STATE_FILE`.

---

## Upgrading from older versions

Older files keep working; the tests in `tests/test_upgrades.py` check every case:

- **`Rom_Mapping.csv`** (before 1.0.0) is no longer read since 1.0.3. Versions 1.0.0 to 1.0.2
  imported it into `rom-mapper-mapping.json` at their first start; that mapping keeps working (its
  rows, plain folder names, belong to the first source folder). The CSV file is left where it is.
- **Rows without a source name** keep pointing at the first source folder, even after the list is
  reordered (they get the name written in front when the order changes).
- **Schedule in minutes and hours** (before 1.0.3: `scan_interval_minutes`, `sync_interval_hours`):
  converted to a number and a unit, in the largest unit that fits (60 minutes -> 1 hour, 24 hours ->
  1 day, 2.5 hours -> 150 minutes). Same intervals as before.
- **`romm-mapper.json` with one folder** (`source`) or from Rom Sync (no folder list, choices
  without a folder name): converted to the folder list; choices get the first folder's name in
  front; a relative links folder is dropped.
- **Platform-links settings** (before 1.0.9): ignored; your choices stay. Links an older version
  made can be removed with **Remove old platform links**.
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
| `GET /api/activity` | Recent events |
| `GET /api/romm/platforms` | RomM's platform list (`slugs`), loaded once by the page |
| `GET /api/romm` · `PUT /api/romm/options` · `PUT /api/romm/map {path, action}` · `POST /api/romm/links` | RomM dialog data, options/download folders/`depths` (`{folder: 1-6}`, 0 = all)/`skip_names` (list or comma-separated text), a folder's choice, remove old platform links (`POST /api/romm/links`; `old_links` in the data says how many). When the folders need a full read, `GET /api/romm` and `PUT /api/romm/options` start it in the background and answer `{reading: {...}}` instead of the rows |
| `GET /api/romm/progress` | The background read: `running`, `source` / `sources` (folder N of M), `path`, `done` / `total` (folders directly inside it), `current`, `error` |

---

## Code map

```
app/server.py     Flask app: settings, mapping storage, source folders, scan, resync,
                  scheduler, RomM endpoints; `python server.py --resync` for a one-off resync
app/links.py      the link engine: desired links from the mapping, apply only the differences
app/romm.py       RomM mapping (folder roles, platforms as mounts, categories, mount list,
                  config.yml, removing old links); romm_slugs.py = RomM's platform list (vendored)
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
