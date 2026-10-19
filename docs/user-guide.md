# ROM Mapper user guide

Step by step: set up your folders, map them for each frontend, keep the links up to date, and
show your games in RomM. For the full reference see the [README](../README.md).

- [1. Install and open it](#1-install-and-open-it)
- [2. Choose your source folders](#2-choose-your-source-folders)
- [3. Add frontends](#3-add-frontends)
- [4. Map folders](#4-map-folders)
- [5. Save and resync](#5-save-and-resync)
- [6. Keep it up to date automatically](#6-keep-it-up-to-date-automatically)
- [7. Export and import](#7-export-and-import)
- [8. RomM](#8-romm)
- [9. Troubleshooting](#9-troubleshooting)

---

## 1. Install and open it

Follow [Install](../README.md#install) in the README. The one thing to get right: mount **one**
folder that contains all your ROM folders and the mapping folder, at the **same path** inside the
container (for example `/path/to/shares:/path/to/shares`). After that you never need to change the
container to use another folder.

If RomM's download folders are somewhere else, add a second mapping for RomM, also at the same
path: the folder that **holds** the download folders (see
[RomM in another place](../README.md#docker-unraid-or-any-docker-host) in the README).

Open `http://YOUR-SERVER:8085/`. The version you're running is next to the title; click it to see
what changed. The page has two tabs at the top: **Frontend links** (steps 2-7) and **RomM** (step 8).
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

## 7. Export and import

- **Export** downloads a CSV with every folder in your source folders - mapped or not - and every
  frontend. Open it in a spreadsheet, fill in names, and import it back. It's also a handy backup.
- **Import** reads a CSV (an export, or a `Rom_Mapping.csv` from an older version). Choose
  **Merge** to apply the file's names to matching folders and keep everything else, or **Replace**
  to make the grid exactly what's in the file. The grid shows the result; click **Save** to keep it
  (or reload the page to undo).

## 8. RomM

Open the **RomM** tab (or go to `http://YOUR-SERVER:8085/#romm`).

1. **Download folders** - add the folders RomM should see, in order of preference. The table lists
   every folder with files and the RomM platform it becomes. Most are filled in already.
2. **Check the platforms** - pick another platform from a folder's dropdown, or **exclude** to leave
   it (and everything inside it) out of RomM. Each choice is saved right away.
3. **Overlaps** - if two download folders give the same platform, the higher one in the list is
   used and the other is marked *not linked*. Choose **Overlaps only** in the filter to see them;
   exclude the one you don't want, or move a folder up or down.
4. **Create / update links now** (top right) - makes one link per platform in the links folder (by default the
   folder that holds your download folders) and keeps them updated with every scan from then on.
   In RomM's compose file, map the links folder as RomM's roms folder - the **RomM compose** tab shows
   the line.
5. **config.yml** - copy it into RomM's `config.yml` (keep your other settings), restart RomM and
   scan its library. BIOS folders aren't linked: copy the folders the dialog lists into RomM's bios
   folder.

**RomM platforms list** shows every platform RomM knows, with a search box.

## 9. Troubleshooting

**"Source folder not found" / "Folder not found".** The folder isn't inside the folder mounted into
the container, or the path has a typo. Paths must be the same as on the host.

**RomM: "not inside a folder mounted into the container".** RomM's platform links go next to the
download folders. Mount the folder that holds them (not the download folder itself), at the same
path, or pick a links folder inside a mounted folder.

**A link isn't created.** Check the resync output: the folder may be *Missing*, the name may be
used twice for that frontend, or a real file or folder may already be in the way.

**Permission denied.** The container's user (Unraid: `nobody`) needs write access to the mapping
folder, the config folder and, for RomM, the links folder.

**Something else?** The **Activity** card and the container log show what happened.
