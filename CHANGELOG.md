# Changelog

What changed in each ROM Mapper release. The section for a version becomes the text of its GitHub
release. Newest first.

## [Unreleased]

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
