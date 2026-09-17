# rom-mapper

Builds per-frontend ROM folder layouts (Batocera/RGS, RetroBat, Knulli, ...) as
**symlinks** into a single master ROM library, driven by a CSV mapping file.
It includes a web UI for editing the mappings and scheduling scans and resyncs.

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
docker run -d --name rom-mapper --restart unless-stopped --user 99:100 -p 8085:8085 -e TZ=America/New_York -e SRC_BASE=/path/to/roms -e DEST_PATH=/path/to/mapping -v /path/to/appdata/rom-mapper:/config -v /path/to/shares:/path/to/shares rom-mapper
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
