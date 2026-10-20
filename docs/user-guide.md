# ROM Mapper user guide

Step by step: set up your folders, map them for each frontend, keep the links up to date, and
show your games in RomM. For the full reference see the [README](../README.md).

- [1. Install and open it](#1-install-and-open-it)
- [2. Choose your source folders](#2-choose-your-source-folders)
- [3. Add frontends](#3-add-frontends)
- [4. Map folders](#4-map-folders)
- [5. Save and resync](#5-save-and-resync)
- [6. Keep it up to date automatically](#6-keep-it-up-to-date-automatically)
- [7. RomM](#7-romm)
- [8. Troubleshooting](#8-troubleshooting)

---

## 1. Install and open it

Follow [Install](../README.md#install) in the README. The one thing to get right: mount **one**
folder that contains all your ROM folders and the mapping folder, at the **same path** inside the
container (for example `/path/to/shares:/path/to/shares`). After that you never need to change the
container to use another folder.

Open `http://YOUR-SERVER:8085/`. The version you're running is next to the title; click it to see
what changed. After an update, reload the page - a banner reminds you if a tab was left open. The page has two tabs at the top: **Frontend links** (steps 2-6) and **RomM** (step 7).
Each has its own buttons on the right.

## 2. Choose your source folders

Click **Source folders**. Add each folder that holds ROMs, for example `/path/to/roms` and
`/path/to/downloads`. For each one, pick a **depth**:

- **1** - the folders directly inside it become rows (`roms/snes`, `roms/psx`).
- **2** - also the folders inside those (`downloads/Nintendo/Super Famicom`). Use this for
  collections sorted by maker or category.
- Higher numbers go deeper still.

Click **Save & scan**. Every folder found appears in the grid as *New*, with the source folder's
name in front so you can tell collections apart. Folders named `media` are skipped (see step 3).

## 3. Add frontends

Click **+ Frontend** and name it - the name becomes a folder inside the mapping folder (e.g. `rgs`,
`retrobat`, `knulli`). Tick **link media/ folders** if that frontend should also get each system's
`media` folder; the box below sets where they go (default `MEDIA_FULL`). Remove a frontend with ✕
next to its name.

## 4. Map folders

In each cell, type the folder name that frontend should see:

- `snes` -> the frontend gets `<mapping folder>/rgs/snes`, a link to that row's folder.
- `SDCARD/snes` -> a link inside a sub-folder (`<mapping folder>/knulli/SDCARD/snes`).
- Leave a cell blank for no link. **Double-click** an empty cell to fill in the folder's own name.

Rows are marked *New* (not saved yet), *Unmapped* (no names yet) and *Missing* (the folder is gone
from disk - its links come back when it does). Use the chips to filter, the search box to find a
folder, and **Remove missing rows** to tidy up. If two rows give the same name to one frontend,
the second turns orange: only the first row gets that link.

**+ Folder** adds a row for a folder that doesn't exist yet (type it as `<source name>/<path>`).

## 5. Save and resync

- **Save** stores the mapping in the app.
- **Resync all** makes the mapping folder match the saved mapping: missing links are created, wrong
  ones corrected, unused ones removed. Links that are already right aren't touched, so frontends
  keep working while it runs. Your own files in the mapping folder are left alone.
- **Save & resync** does both.

**Last resync** shows the result; click *view output* for details (links created, corrected,
removed, and any problems).

## 6. Keep it up to date automatically

In **Schedule**:

- **Scan every N** looks for new and removed folders. With **Auto-add new folders** they're
  added to the mapping (unmapped, so nothing changes until you give them names).
- **Resync every N** keeps the links in line with the mapping.

Pick **min**, **hours** or **days** next to each number. Scans can run every minute; resyncs at
most every 5 minutes. The card shows when each runs next. Turning a schedule on runs it right away
if it's already due.

## 7. RomM

Open the **RomM** tab (or go to `http://YOUR-SERVER:8085/#romm`). Each folder you give a platform is
mounted into RomM's roms folder under the platform's name - nothing is moved.

1. **Download folders** - add your ROM folders. Use **2 levels** if systems have subfolders like
   `+translations` (they become categories). Folders you never want in RomM (`media`, `Extras`) go in
   **Never read folders named**.
2. **Pick the platforms** - folders named like a RomM platform are done already. Click another
   folder's platform and type to search (`commodore`, `sega`…), or **exclude** it. Subfolders of a
   platform show *category of …*; exclude the ones that aren't categories (like `images`).
3. **The script, once** - in Unraid's User Scripts, add [`romm-mounts.sh`](../unraid/romm-mounts.sh),
   set its three paths, and schedule it **At Startup of Array**. In RomM's compose file, map its
   `DEST_PATH` as `/romm/library/roms`.
4. **After changes** - run the script (it restarts RomM), copy the **config.yml** into RomM's
   `config.yml` when it changed, and scan RomM's library.

Upgrading from a version that made platform links? **Remove old platform links** at the top removes
them (only the links ROM Mapper made).

**RomM platforms list** shows every platform RomM knows, with a search box.

## 8. Troubleshooting

**"Source folder not found" / "Folder not found".** The folder isn't inside the folder mounted into
the container, or the path has a typo. Paths must be the same as on the host.

**A link isn't created.** Check the resync output: the folder may be *Missing*, the name may be
used twice for that frontend, or a real file or folder may already be in the way.

**Permission denied.** The container's user (Unraid: `nobody`) needs write access to the mapping
folder and the config folder.

**Something else?** The **Activity** card and the container log show what happened.
