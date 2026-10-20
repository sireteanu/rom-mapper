# ROM Mapper (rom-mapper)

Web app that builds per-frontend folders of links into ROM folders, and decides which folders are
which RomM platform (volume lines for RomM's compose file - Docker mounts them). Flask + waitress, one page (`app/static/index.html`, no build step), Python 3.10+,
Docker (Unraid). See README.md for the full reference.

**Linux + Docker only.** Paths are POSIX (`/`, no drive letters, no `os.sep` juggling) and the code
and tests create real symlinks - run the tests on Linux (CI: `.github/workflows/tests.yml`).

## Commands
- Install (dev): `pip install -r requirements.txt -r requirements-dev.txt`
- Tests: `python -m pytest` (temporary folders only); lint: `python -m pyflakes app tests`
- Run: `CONFIG_DIR=... SRC_BASE=... DEST_PATH=... python app/server.py`; one-off: `--resync`
- Docker: `docker compose up -d --build` (reads `.env`)

## Rules
- The mapping lives in `<config>/rom-mapper-mapping.json` (+ `.bak`); state in
  `rom-mapper-state.json`; RomM in `romm-mapper.json`. Always write through `atomic_write`, under
  `csv_lock` (mapping/state) or `romm_lock` (RomM).
- Row keys are `<source label>/<path>`; labels are stored per source path and never change when the
  list is reordered. A key without a known label belongs to the first source (older data) - keep
  that working (`split_key`, `full_key`).
- `links.py` only ever removes **symlinks** inside the mapping folder and folders left empty; never
  delete real files. `check_dest` must refuse dangerous mapping folders.
- RomM (`romm.py`): every folder with a platform is a volume of RomM's container at
  /romm/library/roms/<slug> - the app only generates the lines (`Mapping.volumes`; long syntax when a
  path has ":"); Docker mounts them. The container must not mount or control Docker. No
  platform links (apply_links with no targets only removes old ones), no system.platforms /
  exclude.platforms. Categories are automatic: a platform with a MERGE child that has files gets
  both templates in filesystem.structure, keyed by slug. Rows are `<root>/<path>`; RULES are keyed
  by the path inside a root (`inner()`); a user "exclude" covers the subtree unless a subfolder has
  its own choice. RomM facts it relies on are in the module docstring.
- Older files must keep working: any change to stored formats gets a conversion and a case in
  `tests/test_upgrades.py` (rows without labels, the minutes/hours schedule, one-folder and Rom
  Sync `romm-mapper.json`). There is no CSV import or export for the frontend grid (removed in
  1.0.3) - don't add one back without asking. The only CSV import is the owner-requested one-time
  RomM import (`POST /api/romm/import`, Rom_Mapping_RomM.csv).
- RomM reads never block the page: any read `romm_view` needs (full, or the quick re-check after
  30 s - `romm_read_due`) runs in the background (`start_romm_read`, `/api/romm/progress`) and the
  answer is `{reading}` meanwhile.
  JSON answers over 4 KB are gzipped when the browser accepts it (`compress`). Tests set `server.ROMM_BACKGROUND = False` (conftest) to get rows directly.
  Per-download-folder levels are `depths` in `romm-mapper.json` (missing = all levels).
  The folder cache is never reset by saving: its key (`romm_setup`) covers what changes the folders;
  choices/options pass `reuse=True` (no disk access at all). Excluded folders without a choice below
  them are not read inside (`romm_stops` -> `stop`). The cache is stamped when a read ends.
  `skip_names` (default `["media"]`, fnmatch, case-insensitive) is applied while reading
  (`romm.skipped`), is part of the folder cache key, and goes into config.yml's exclude names.
- Disk reads: RomM folder counts (`romm.folders_from_disk`) re-list only folders whose mtime changed,
  with a full read every hour and on Refresh (Unraid shares don't always update a folder's date);
  the page doesn't refresh while its tab is hidden; RomM's platform list comes from
  `/api/romm/platforms` once.
- The container runs as 99:100 and sees one host folder at the same path; frontend links are
  absolute; RomM's platform folders are volumes of RomM's container (host paths).
- Schedule settings are `scan_every`/`scan_unit` and `sync_every`/`sync_unit` (minutes, hours,
  days); `convert_schedule` upgrades the older `scan_interval_minutes`/`sync_interval_hours`.

## Releases
- Every app change = new version: bump `app/version.py`, add `## [x.y.z] - date` to CHANGELOG.md
  (New / Improved / Fixed / Changed, plain words), push to `main`; `release.yml` runs the tests and
  publishes `vx.y.z` with that section. Last number by default; ask the owner before a minor/major
  bump. Docs (README, docs/user-guide.md, CHANGELOG) change in the same commit.

## Privacy
- Docs, examples, tests and commit messages use placeholder paths (`/path/to/roms`,
  `/path/to/mapping`, `/path/to/appdata`), never the owner's real folders, shares, IPs or names.
