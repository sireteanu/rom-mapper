# Changelog

What changed in each ROM Mapper release. The section for a version becomes the text of its GitHub
release. Newest first.

## [Unreleased]

## [1.0.8] - 2026-10-19

### New
- **RomM folder names - RomM without links.** A new choice on the RomM tab, *How RomM sees your
  folders*. With **RomM folder names**, RomM reads your download folder directly and the generated
  `config.yml` renames folders to platforms (`system.platforms`, e.g. `amigacdtv: commodore-cdtv`)
  and leaves out the folders without a platform (`exclude.platforms`). No links are made; the
  compose line mounts the download folder itself. Made for one folder with one folder per system.
  **Platform links** (as before) stays the default and is still needed for nested downloads
  (lolroms) or several download folders. Switching to folder names turns the links button into
  **Remove old platform links**.

## [1.0.7] - 2026-10-19

### Fixed
- **The RomM compose tab showed a placeholder** (`/path/on/your/server`) instead of your links
  folder. It now shows the real line, e.g. `"/path/to/shares:/romm/library/roms"`, and the same
  thing as an ENV-file variable (`ROMM_ROMS=...` and `- ${ROMM_ROMS}:/romm/library/roms`) for a
  shorter compose file.
- **Other folders next to the download folders became RomM platforms.** The links folder is RomM's
  roms folder, so a folder like `sets` beside `roms` showed up as a platform. The generated
  `config.yml` now excludes every real folder there that isn't one of the platform links.

### Improved
- The result of a mapped folder reads "in RomM as roms/<platform>" instead of just the path.
- **The page never waits on the disk any more.** The quick re-check of the RomM folders (after 30
  seconds) runs in the background with the progress bar, like a full read.
- **Scheduled link updates no longer read everything.** With "Update the links with every scan",
  each scan used to read every RomM download folder in full; it now does the usual quick re-check
  (and a full read once an hour) in the background, then updates the links.
  **Create / update links now** also does a quick re-check instead of a full read (**Refresh**
  still reads everything).
- **Smaller answers**: big lists (like the RomM folders of a large share) are sent compressed.

### Changed
- **Linux and Docker only.** Windows and macOS hosts aren't supported any more.

## [1.0.6] - 2026-10-19

### Fixed
- **A platform choice snapped back to "pick a platform"** (and the result stayed "no platform").
  Every choice made the RomM tab read all download folders again; on a big share that took
  minutes, and meanwhile the page showed the old list. Choices and options now reuse the folder
  list - nothing is read from disk.
- **The progress box stayed up long after "N of N folders"**: right after a long read, the page's
  next request checked every folder again. It now says "preparing the list" and finishes quickly.

### Improved
- **Searchable platform picker.** Click a folder's platform and type: `snes`, `nintendo`, `sega`,
  `exclude`… Arrow keys and Enter work; the maker is shown next to each platform.
- **Excluded folders aren't read any more.** A folder you exclude (with no choice of yours inside
  it) is no longer read inside, so a big collection like eXoDOS stops slowing down every read.

## [1.0.5] - 2026-10-19

### Improved
- **A page left open during an update says so.** If ROM Mapper is updated while its page is open
  in your browser, a banner asks you to reload it, so you don't keep using the old page without
  the new controls. The version next to the title is the page's own version.

## [1.0.4] - 2026-10-19

### New
- **Never read folders named …** (RomM tab). List folder names to skip in every download folder -
  `media` is there by default, and `*` / `?` work (`*.bak`). They aren't read or listed, and the
  generated `config.yml` tells RomM to ignore them too.

### Improved
- **The RomM folder list is a tree.** Each folder's subfolders are tucked under it (click ▸ to open
  it, with a count of what's inside) instead of tens of thousands of rows in one list. Download
  folders start open, everything else closed, and the page remembers what you opened.
- **Find a folder** on the RomM tab: type part of a path to list every matching folder.
- Very long lists draw the first 600 rows and say how many there are, so the page stays quick.

### Changed
- Folders named `media` are no longer read for RomM unless you remove `media` from the list.

## [1.0.3] - 2026-10-19

### New
- **Schedules in minutes, hours or days.** Pick the unit next to **Scan every** and **Resync
  every**. Your current schedule is converted automatically (60 minutes becomes 1 hour, 24 hours
  becomes 1 day) and runs exactly as before.
- **RomM can use a folder outside the main one.** If RomM's download folders aren't inside the
  folder mounted for your ROMs, mount a second folder for RomM (the folder that holds the download
  folders), at the same path. Both compose files have it ready to switch on.

- **Levels for RomM download folders.** Choose **1 level** for a folder with one folder per
  system: the RomM tab then shows one row per system instead of every folder inside them, and reads
  much faster. **All levels** (needed for lolroms) stays the default.

### Improved
- **A progress bar while the RomM tab reads your folders.** Adding, removing or reordering a
  download folder, **Refresh** and opening the tab now read in the background and show how far
  they are, instead of the page seeming to hang.
- **RomM won't lose its links to a wrong mount.** In Docker, the RomM tab refuses to make platform
  links in a folder that isn't mounted from the host, and says what to mount instead.
- The schedule card says when the next scan and resync run in days for long intervals.

### Removed
- **Import and export.** The CSV buttons are gone: the mapping is edited in the grid and stored by
  the app (with a backup of the previous version on every save).
- **Reading `Rom_Mapping.csv`.** It was imported once at the first start; installs that already
  did that keep their mapping, and the old file is left untouched. A new install starts with an
  empty mapping.

### Fixed
- Changing several schedule settings quickly could put an earlier value back, and the page's
  automatic refresh could reset a schedule setting while you were changing it.

## [1.0.2] - 2026-10-18

### Improved
- **Less disk reading.** The RomM tab and scheduled scans now re-read only the download folders
  that changed (a full read still happens every hour and when you click **Refresh**).
- **A hidden page stops refreshing**, so a forgotten browser tab no longer keeps your disks awake.
  It refreshes as soon as you come back to it.
- RomM's platform list is loaded once instead of with every refresh of the RomM tab.

## [1.0.1] - 2026-10-08

### Changed
- **Two tabs: Frontend links and RomM.** RomM is no longer a pop-up window but a page of its own next to
  the mapping grid, with its **Refresh** and **Create / update links now** buttons at the top. The
  open tab is remembered, and `#romm` in the address opens it directly.

### Fixed
- The RomM page fits a phone screen.

## [1.0.0] - 2026-10-03

The first numbered release. ROM Mapper started as a bash script driven by a CSV file; it is now a
web app that stores everything itself.

### New
- **The mapping is stored in the app.** No CSV file to edit: the grid saves into the config folder
  (with a backup of the previous version). An existing `Rom_Mapping.csv` is imported automatically
  at the first start and every link stays where it was.
- **Export and import.** Export downloads a CSV with every folder in your source folders, mapped or
  not, ready to fill in; import loads one back, merged into the grid or replacing it, for you to
  review before saving.
- **Several source folders**, each read to its own depth (1 = the folders directly inside it, 2 =
  also the folders inside those, and so on). Rows show the source folder's name in front.
- **Duplicate names** for one frontend are highlighted; the first row gets the link.
- **RomM section**: maps download folders to RomM platforms with platform links in one folder and a
  generated `config.yml`; a dropdown per folder (any RomM platform, or exclude - which leaves the
  folder and everything inside it out); several download folders with overlaps resolved by their
  order; links kept up to date with every scan.
- The version is shown next to the title.

### Improved
- **Resync changes only what differs.** Missing links are made, wrong ones corrected and unused ones
  removed; links that are already right aren't touched, so frontends never see an empty folder
  during a resync. Your own files in the mapping folder are kept.
- **One folder mounted into the container covers everything**; folders are picked in the page.
- The page reuses a fresh folder listing instead of reading the disk on every refresh.

### Changed
- `rom-mapper.sh` is replaced by the built-in resync (same links). For a one-off resync without the
  page: `docker exec rom-mapper python /app/server.py --resync`.
- The image no longer needs bash and the extra command-line tools.
