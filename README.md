# rom-mapper

Builds per-frontend ROM folder layouts (Batocera/RGS, RetroBat, Knulli, ...) as
**symlinks** into a single master ROM library, driven by a CSV mapping file.

## How it works

`Rom_Mapping.csv`:

| Row | Meaning |
|---|---|
| Header | `Folder`, then one column per target frontend (e.g. `rgs,retrobat,knulli`) |
| `Media Toggle` | `1` = also link each system's `media/` folder for that frontend |
| `Media Location` | Sub-folder the media links go under (default `MEDIA_FULL`) |
| Every other row | Source folder under `SRC_BASE`, then the folder name to use per frontend (blank = skip) |

On each run the script **deletes everything inside `DEST_PATH`** and rebuilds it:

```
DEST_PATH/<frontend>/<mapped name>  ->  SRC_BASE/<folder>
```

See [`config/Rom_Mapping.example.csv`](config/Rom_Mapping.example.csv).

## Run with Docker

```bash
cp .env.example .env              # edit the paths
cp config/Rom_Mapping.example.csv /path/to/appdata/rom-mapper/Rom_Mapping.csv   # first time only
docker compose run --rm rom-mapper
```

The container runs once and exits. Schedule it with cron / Unraid User Scripts if needed.

### Why the share is mounted at the same path

The script creates **absolute** symlinks. If the ROMs were mounted at e.g. `/roms`
in the container, the links would point to `/roms/...`, which doesn't exist on the
host. `docker-compose.yml` therefore mounts `EMULATION_ROOT` at the identical path
inside the container. Keep `ROMS_PATH` and `MAPPING_PATH` inside `EMULATION_ROOT`.

## Run without Docker

```bash
INPUT_CSV=/path/to/Rom_Mapping.csv \
SRC_BASE=/path/to/roms \
DEST_PATH=/path/to/mapping \
./rom-mapper.sh
```

Requires bash 4+.
