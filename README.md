# rom-mapper

Builds per-frontend ROM folder layouts (Batocera/RGS, RetroBat, Knulli, ...) as
**symlinks** into a single master ROM library, driven by a CSV mapping file.
It includes a web UI for editing the mappings and scheduling scans and resyncs, and a
**RomM** section that maps a lolroms download folder to RomM platforms (see [RomM](#romm)).

## Web UI

Open `http://<server>:8085`.

- **Mapping grid:** one row for each folder in the ROM folder and one column for each frontend.
  Type the folder name that frontend should see, or leave the cell blank to create no link.
  Double-click an empty cell to fill in the source folder name.
- **Row status:** *New* means the folder is on disk but not yet in the CSV. *Missing* means
  the folder is in the CSV but no longer on disk. *Unmapped* means it has no mappings yet.
  Filter by status, or click **Remove missing rows** to clean up.
- **+ Folder:** pre-map a folder that doesn't exist yet. It shows as *Missing* until it
  appears on disk. Its mappings are kept, and no link is created until then.
- **+ Frontend:** adds a new output column. Each column can also link each system's `media/`
  folder into a sub-folder (default `MEDIA_FULL`).
- **Scan now:** re-reads the ROM folder for added or removed folders. **Scan every N min**
  does the same on a schedule, and can add new folders to the CSV automatically (unmapped).
- **Resync all:** deletes every link under the mapping folder and rebuilds them from the
  saved CSV. **Resync every N h** does the same on a schedule. **Save & resync** saves
  your edits and rebuilds the links in one step.

Saving writes `Rom_Mapping.csv` in the same plain format the script reads, and keeps the
previous version as `Rom_Mapping.csv.bak`. Schedules and last-run info are stored in
`rom-mapper-state.json` next to the CSV.

> There is no login. Keep the port on your LAN.

## RomM

The **RomM** button maps one or more download folders to [RomM](https://github.com/rommapp/romm)
platforms - for example the lolroms folder [Rom Sync](https://github.com/sireteanu/rom-sync) keeps
(`/path/to/downloads/lolroms`) and a RomM-style collection (`/path/to/downloads/rommer`). lolroms nests
platforms (`Nintendo/Super Famicom/Satellaview`) and keeps variants in subfolders (`T-En`, `MSU-1`),
while RomM wants one folder per platform. Nothing is moved:

- **Download folders**: a list in priority order (add, remove, move up/down). Every folder is
  read from disk; rows in the table start with the folder's name (`lolroms/...`, `rommer/...`).
  Folders named exactly like a RomM platform right inside a download folder (`rommer/snes`) get
  that platform automatically; lolroms folders get it from built-in rules.
- **Overlaps**: RomM can only have one folder per platform. When two download folders give the
  same platform, the one **higher in the list** is linked; the other's rows say *not linked* and
  a warning names both. **Overlaps only** in the filter shows just those rows. Exclude the one
  you don't want, or change the order.
- **Exclude**: choosing *exclude* for a folder leaves it **and everything inside it** out of
  RomM (even subfolders the built-in rules would map), unless you pick something else for a
  subfolder.

- **Platform links**: relative links named after RomM's platforms are kept in the folder that holds
  the download folders, e.g. in `/path/to/downloads`: `snes -> lolroms/Nintendo/Super Famicom`, `n64 -> rommer/n64`,
  `satellaview -> lolroms/Nintendo/Super Famicom/Satellaview`. Map that one folder as RomM's roms
  folder (`- /path/to/downloads:/romm/library/roms`; the **RomM compose** tab shows the line).
  **Create / update links now** makes them and turns on *Update the links with every scan*; from
  then on every scheduled scan keeps them current. Only links pointing into the download folder
  are ever changed or removed; real folders and other links are left alone. All download
  folders must be inside the links folder.
- **config.yml**: merge the generated section into RomM's `config.yml` - the download folders
  themselves aren't platforms (`exclude.platforms`), which subfolders belong to a platform
  (`{category}` levels by default), which to ignore, and `system.versions` for arcade boards RomM
  has no platform for. Restart RomM and scan its library.
- **Folder table**: every folder in the download folder that holds files, with its RomM platform
  from built-in rules for lolroms' tree. Pick another platform or **exclude** from the dropdown;
  each choice is saved at once. BIOS folders become firmware automatically (copy them to RomM's
  bios folder). **RomM platforms list** shows every platform RomM knows.

Settings and choices are stored in `romm-mapper.json` next to the CSV (`sources` = the download
folders in order, `map` = your choices by `<download folder>/<path>`). Rom Sync's
`romm-mapper.json` (from its config folder) can be copied here: its choices are converted to the
first download folder (`Konami - Picno` -> `lolroms/Konami - Picno`) and a links folder from inside
Rom Sync's container is dropped. Rom Sync's own RomM Mapper keeps working for now; once this one is set up, turn off
*Update the links after every sync* there so only one app manages the links.

Setup: mount the folder that holds the download folders at the **same path** (`ROMM_ROOT` in
`docker-compose.yml`, writable - the links go there) and add the folders in the dialog (or set
`ROMM_SOURCE`, several separated by `;`, used until the dialog saves a list). Without Docker:
`ROMM_SOURCE="/path/to/lolroms;/path/to/rommer" python app/server.py`.

## CSV format

| Row | Meaning |
|---|---|
| Header | `Folder`, then one column per target frontend (e.g. `rgs,retrobat,knulli`) |
| `Media Toggle` | `1` = also link each system's `media/` folder for that frontend |
| `Media Location` | Sub-folder the media links go under (default `MEDIA_FULL`) |
| Every other row | Source folder under `SRC_BASE`, then the folder name to use per frontend (blank = skip) |

On each resync, the script **deletes everything inside `DEST_PATH`** and rebuilds it:

```
DEST_PATH/<frontend>/<mapped name>  ->  SRC_BASE/<folder>
```

Commas aren't supported in names (the script doesn't handle quoted CSV). The UI rejects them.

## Run on Unraid

```bash
git clone https://github.com/sireteanu/rom-mapper.git /path/to/appdata/rom-mapper
cd /path/to/appdata/rom-mapper && docker build -t rom-mapper .
```

```bash
docker run -d --name rom-mapper --restart unless-stopped --user 99:100 -p 8085:8085 -e TZ=America/New_York -e SRC_BASE=/path/to/roms -e DEST_PATH=/path/to/mapping -v /path/to/appdata/rom-mapper:/config -v /path/to/shares:/path/to/shares -e ROMM_SOURCE=/path/to/downloads/lolroms -v /path/to/downloads:/path/to/downloads rom-mapper
```

The container then appears on the Docker tab. To update it, run `git pull`, rebuild,
`docker rm -f rom-mapper`, and run the command above again.

Or use Docker Compose (on Unraid, install the *Docker Compose Manager* plugin):

```bash
cp .env.example .env   # edit the paths
docker compose up -d --build
```

### Why the share is mounted at the same path

The script creates **absolute** symlinks. If the ROMs were mounted at e.g. `/roms`
in the container, the links would point to `/roms/...`, which doesn't exist on the
host. Mount `EMULATION_ROOT` at the identical path inside the container, and keep
`ROMS_PATH` and `MAPPING_PATH` inside it.

### Permissions

The container runs as `99:100` (`nobody:users`). That user needs write access to the
config folder (to save the CSV) and to the mapping folder. If an older version
ran as root, fix the ownership once:

```bash
chown -R nobody:users /path/to/mapping /path/to/appdata/rom-mapper
```

## Run without Docker / without the UI

```bash
INPUT_CSV=/path/to/Rom_Mapping.csv SRC_BASE=/path/to/roms DEST_PATH=/path/to/mapping ./rom-mapper.sh
```

Inside the running container: `docker exec rom-mapper rom-mapper.sh`. Requires bash 4+.

The UI on its own: `pip install -r requirements.txt && python app/server.py`, with the same
environment variables.
