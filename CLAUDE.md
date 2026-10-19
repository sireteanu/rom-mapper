# ROM Mapper (rom-mapper)

Web app that builds per-frontend folders of links into ROM folders, and maps download folders to
RomM platforms. Flask + waitress, one page (`app/static/index.html`, no build step), Python 3.10+,
Docker (Unraid). See README.md for the full reference.

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
- RomM (`romm.py`): rows are paths relative to the links folder (`<root>/<path>`); RULES are keyed by
  the path inside a root (`inner()`); first root wins overlaps; a user "exclude" covers the subtree
  unless a subfolder has its own choice; `apply_links` only changes links pointing into a root.
  RomM facts it relies on are in the module docstring.
- Older files must keep working: any change to stored formats gets a conversion and a case in
  `tests/test_upgrades.py` (rows without labels, the minutes/hours schedule, one-folder and Rom
  Sync `romm-mapper.json`). There is no CSV import or export (removed in 1.0.3) - don't add one
  back without asking.
- RomM full reads run in the background (`start_romm_read`, `/api/romm/progress`); `romm_view` answers
  `{reading}` meanwhile. Tests set `server.ROMM_BACKGROUND = False` (conftest) to get rows directly.
  Per-download-folder levels are `depths` in `romm-mapper.json` (missing = all levels).
  `skip_names` (default `["media"]`, fnmatch, case-insensitive) is applied while reading
  (`romm.skipped`), is part of the folder cache key, and goes into config.yml's exclude names.
- Disk reads: RomM folder counts (`romm.folders_from_disk`) re-list only folders whose mtime changed,
  with a full read every hour and on Refresh (Unraid shares don't always update a folder's date);
  the page doesn't refresh while its tab is hidden; RomM's platform list comes from
  `/api/romm/platforms` once.
- The container runs as 99:100 and sees one host folder at the same path (plus, optionally, a
  second one holding RomM's download folders: `docker-compose.romm.yml`); links are absolute
  (frontends) or relative (RomM). In Docker, `romm_check` refuses a links folder that isn't on a
  host mount (`on_host_folder`).
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
