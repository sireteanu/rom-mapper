"""RomM mapping: turn a lolroms folder tree into RomM platforms without moving any files.

Moved here from Rom Sync (sireteanu/rom-sync, src/lolroms_sync/romm.py, v1.3.4); the rules and the
romm-mapper.json format are the same, so choices made in Rom Sync carry over.

RomM wants one folder per platform, named by its slug, under <library>/roms/. lolroms nests
platforms (Nintendo/Super Famicom/Satellaview) and keeps variants in subfolders (T-En, MSU-1).
Instead of moving anything, we keep:

* platform links: relative symlinks named by slug in the links folder (RomM's roms folder, by
  default the download folder's parent), e.g. snes -> lolroms/Nintendo/Super Famicom, kept up to
  date after every scan, so RomM needs a single folder mapping; and
* a config.yml with `filesystem.structure` templates that pull variant subfolders into the
  platform (roms/{platform}/T-En/{game}), `exclude.roms.multi_file.names` so subfolders that are
  their own platform (Satellaview) or skipped (Flux dumps) aren't read as games, and
  `system.versions` for platforms RomM has no slug for (Naomi -> arcade).

When several folders map to one slug (APF/Imagination Machine + APF/MP-1000 -> apf), the link
points at their nearest common folder (the "mount") and each one gets its own template.

Per folder an action decides what happens: a RomM slug, "merge" (into the platform above),
"bios:<slug>" (firmware), "skip", or nothing (the built-in rule, else inherited).
RomM rules this relies on (backend/config/config_manager.py, Oct 2026): platforms are the
folders in the default template's platform dir; per-platform templates must keep that dir and
end in {game}; literal levels are followed even if excluded; a folder read as a multi-file game
by one template but descended by another is dropped; multi_file.names adds to the defaults.
"""
from __future__ import annotations

import difflib
import fnmatch
import json
import os
import re
from typing import Optional

from romm_slugs import PLATFORMS, SLUGS  # app/ is the script folder (python /app/server.py)

__all__ = ["PLATFORMS", "SLUGS", "Mapping"]   # PLATFORMS is used by web.py

DEFAULT_ROMM_FOLDER = "/romm/library/roms/lolroms"

DEFAULT_OPTIONS = {
    "romm_folder": "",            # where the lolroms downloads are inside RomM's container
                                  # ("" = /romm/library/roms/lolroms)
    "only_synced": True,          # only folders that have files on disk
    "variants": True,             # pull unmapped subfolders (T-En, hacks ...) into their platform
    "keep_links": False,          # update the platform links after every scan (turned on the first
                                  # time you create the links)
    "links_dir": "",              # where the links go; "" = the download
                                  # folder's parent, e.g. /romm when downloads are /romm/lolroms
    "layout": "category",         # config.yml subfolder levels: "category" = {category} wildcards
                                  # (new subfolders are picked up), "folders" = exact folder names
    "map": {},                    # your own actions: {lolroms path: action}
    "skip_names": ["media"],      # folders with these names (wildcards allowed) are never read or
                                  # listed, and RomM is told to ignore them too
}


def skipped(name: str, patterns) -> bool:
    """Does a folder name match one of the "never read" patterns (case-insensitive, * and ?)?"""
    n = name.casefold()
    return any(fnmatch.fnmatchcase(n, p.casefold()) for p in patterns)

# Built-in rules for lolroms' tree (folder names as of Oct 2026). Subfolders without a rule
# follow their parent: merged into its platform, or skipped / firmware by name (see below).
RULES = {
    # Arcade (only linked from the site's header bar)
    "Arcade/MAME": "arcade", "Arcade/FBNeo": "skip", "Arcade/HBMAME": "skip",
    "Arcade/Naomi": "naomi", "Arcade/Naomi 2": "naomi2", "Arcade/Atomiswave": "atomiswave",
    "Arcade/Chihiro": "chihiro", "Arcade/Triforce": "triforce", "Arcade/Lindbergh": "lindbergh",
    "Arcade/RingEdge": "ringedge", "Arcade/RingEdge 2": "ringedge2", "Arcade/RingWide": "ringwide",
    "Arcade/System 246": "system246", "Arcade/System 573": "system573", "Arcade/Aleck64": "aleck64",
    "Arcade/Prologue 21": "skip", "Arcade/PC Based (Nintendo)": "skip",
    "Audio [FLAC]": "skip", "fixdats": "skip",
    "Acorn/Archimedes": "acorn-archimedes", "Acorn/Risc PC": "acorn-archimedes", "Acorn/Atom": "atom",
    "Acorn/RISC OS - Flash Media": "skip",
    "Amstrad - CPC": "acpc", "Analogue Pocket": "skip",
    "APF/Imagination Machine": "apf", "APF/MP-1000": "apf",
    "Apple/II": "appleii", "Apple/II Plus": "appleii", "Apple/IIe": "appleii",
    "Apple/IIGS": "apple-iigs", "Apple/Macintosh": "mac", "Apple/PiPP!N": "apple-pippin",
    "Arduboy": "arduboy",
    "Atari/2600": "atari2600", "Atari/5200": "atari5200", "Atari/7800": "atari7800",
    "Atari/800": "atari8bit", "Atari/Jaguar": "jaguar", "Atari/Jaguar/CD": "atari-jaguar-cd",
    "Atari/Lynx": "lynx", "Atari/ST": "atari-st",
    "Bally - Astrocade": "astrocade",
    "Bandai/WonderSwan": "wonderswan", "Bandai/WonderSwan Color": "wonderswan-color",
    "Benesse/Pocket Challenge V2": "pocket-challenge-v2", "Benesse/Pocket Challenge W": "pocket-challenge-w",
    "Bit Corporation - Gamate": "gamate",
    "CASIO/Loopy": "casio-loopy", "CASIO/Loopy/Little Endian": "skip",   # same games, other byte order
    "CASIO/PV-1000": "casio-pv-1000",
    "ColecoVision": "colecovision",
    "Commodore/64": "c64", "Commodore/64/Headerless": "skip", "Commodore/Amiga": "amiga",
    "Commodore/Amiga CD": "amiga-cd", "Commodore/Amiga CD32": "amiga-cd32",
    "Commodore/Amiga CDTV": "commodore-cdtv", "Commodore/Plus-4": "c-plus-4",
    "Commodore/VIC-20": "vic-20", "Commodore/WinUAE [BIOS]": "bios:amiga",
    "Emerson - Arcadia 2001": "arcadia-2001", "Entex - Adventure Vision": "adventure-vision",
    "Epoch/Game Pocket Computer": "epoch-game-pocket-computer",
    "Epoch/Super Cassette Vision": "epoch-super-cassette-vision",
    "Evercade": "evercade", "Fairchild - Channel F": "fairchild-channel-f",
    "Fujitsu/FM Towns": "fm-towns", "Fujitsu/FM-7": "fm-7", "Fujitsu/FM-77AV (T-En)": "fm-7",
    "Funtech - Super Acan": "super-acan", "GCE - Vectrex": "vectrex",
    "GamePark/GP2X": "gp2x", "GamePark/GP32": "gp32",
    "Hartung - Game Master": "hartung", "Hitachi - S1": "hitachi-s1",
    "IBM - PC & Compatibles": "skip",                                  # disk-image preservation dumps
    "Interton - VC 4000": "interton-vc-4000",
    "LeapFrog/Explorer": "leapfrog-explorer",
    "LeapFrog/Leapster Learning Game System": "leapster",
    "Magnavox - Odyssey 2": "odyssey-2",
    "Mattel/HyperScan": "hyperscan", "Mattel/Intellivision": "intellivision",
    "Microsoft/MSX": "msx", "Microsoft/MSX2": "msx2", "Microsoft/MSX Turbo-R (T-En)": "msx-turbo",
    "Microsoft/Xbox": "xbox", "Microsoft/Xbox 360": "xbox360",
    "NEC/PC-Engine/TurboGrafx-16": "tg16", "NEC/PC-Engine/T-En": "tg16",
    "NEC/PC-Engine/SuperGrafx": "supergrafx", "NEC/PC-Engine CD": "turbografx-cd",
    "NEC/PC-FX": "pc-fx", "NEC/PC6001 (T-En)": "pc-6001", "NEC/PC8 Series": "pc-8800-series",
    "NEC/PC98": "pc-9800-series",
    "Nintendo/3DS": "3ds", "Nintendo/3DS/New 3DS": "new-nintendo-3ds",
    "Nintendo/DS": "nds", "Nintendo/DS/DSi": "nintendo-dsi",
    "Nintendo/Famicom": "nes", "Nintendo/Famicom/Disk System": "fds",
    "Nintendo/Famicom/BASIC (Tapes)": "skip", "Nintendo/Famicom/Network System": "skip",
    "Nintendo/Famicom/StudyBox": "skip",
    "Nintendo/Game & Watch": "g-and-w", "Nintendo/Game Boy": "gb", "Nintendo/Game Boy Color": "gbc",
    "Nintendo/Game Boy Advance": "gba",
    "Nintendo/Game Boy Advance/e-Reader": "e-reader-slash-card-e-reader",
    "Nintendo/GameCube": "ngc", "Nintendo/Nintendo 64": "n64", "Nintendo/Nintendo 64/64DD": "64dd",
    "Nintendo/Pokémon Mini": "pokemon-mini",
    "Nintendo/Super Famicom": "snes", "Nintendo/Super Famicom/Satellaview": "satellaview",
    "Nintendo/Super Famicom/SuFami Turbo": "sufami-turbo",
    "Nintendo/Virtual Boy": "virtualboy", "Nintendo/Wii": "wii", "Nintendo/Wii U": "wiiu",
    "Nintendo/amiibo": "skip",
    "Ouya": "ouya", "Panasonic - 3DO": "3do", "Panasonic - 3DO/M2": "panasonic-m2",
    "Philips/CD-i": "philips-cd-i", "Philips/Videopac+": "videopac-g7400",
    "Playdate": "playdate", "RCA - Studio II": "rca-studio-ii",
    "SEGA/Beena": "beena", "SEGA/DreamCast": "dc", "SEGA/Game Gear": "gamegear",
    "SEGA/Genesis": "genesis", "SEGA/Genesis/32X": "sega32", "SEGA/Genesis/Mega CD": "segacd",
    "SEGA/Master System": "sms", "SEGA/Pico": "sega-pico", "SEGA/SG-1000": "sg1000",
    "SEGA/Saturn": "saturn",
    "SNK/NeoGeo CD": "neo-geo-cd", "SNK/NeoGeo Pocket": "neo-geo-pocket",
    "SNK/NeoGeo Pocket Color": "neo-geo-pocket-color",
    "SONY/PlayStation": "psx", "SONY/PlayStation/Datel - Cheat Device Updates": "skip",
    "SONY/PlayStation 2": "ps2", "SONY/PlayStation 3 (T-En)": "ps3",
    "SONY/PlayStation Portable": "psp", "SONY/PlayStation Portable/Minis": "psp-minis",
    "Sharp/MZ-2200": "sharp-mz-2200", "Sharp/MZ-700": "sharp-mz-80k7008001500", "Sharp/X1": "x1",
    "Sharp/X68000": "sharp-x68000", "Sharp/Zaurus": "sharp-zaurus",
    "Sinclair - ZX Spectrum +3": "zxs", "Texas Instruments - 99-4A": "ti-994a",
    "VM Labs - NUON": "nuon", "VTech/CreatiVision": "creativision",
    "VTech/V.Flash & V.Smile Pro": "vflash", "VTech/V.Smile": "vsmile",
    "Watara - Supervision": "supervision", "Welback - Mega Duck": "mega-duck-slash-cougar-boy",
    "Zeebo": "zeebo",
}

# platforms RomM has no slug for: the RomM platform whose metadata they should use (system.versions)
VERSIONS = {"naomi": "arcade", "naomi2": "arcade", "atomiswave": "arcade", "chihiro": "arcade",
            "triforce": "arcade", "lindbergh": "arcade", "ringedge": "arcade", "ringedge2": "arcade",
            "ringwide": "arcade", "system246": "arcade", "system573": "arcade", "aleck64": "arcade"}

# subfolders skipped by name: raw disk/flux captures and things that are not games
SKIP_NAMES = re.compile(r"^(flux|fluxdumps|a2r|kryoflux|scp|ipf|bitstreams?|greaseweazle|waveform|wav|"
                        r"cdn|saves|encrypted|video|play-yan|loosefilesarchive|datel\b.*)$", re.I)
BIOS_NAMES = re.compile(r"\bbios\b", re.I)
DATED = re.compile(r"\(\d{4}-\d{2}-\d{2}\)")

PLATFORM, MERGE, BIOS, SKIP, UNMAPPED = "platform", "merge", "bios", "skip", "unmapped"


def parent_of(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def name_of(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def common_dir(paths) -> str:
    parts = [p.split("/") for p in paths]
    out = []
    for seg in zip(*parts):
        if len(set(seg)) != 1:
            break
        out.append(seg[0])
    return "/".join(out)


def rel(path: str, base: str) -> str:
    return path[len(base):].lstrip("/") if base else path


def check_action(action: str) -> str:
    """Normalise a user-entered action; raises ValueError on nonsense."""
    a = (action or "").strip()
    low = a.lower()
    if low in ("", "auto", "default"):
        return ""
    if low in ("skip", "merge", "exclude"):
        return low
    if low.startswith("bios:") or low.startswith("firmware:"):
        slug = low.split(":", 1)[1].strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", slug):
            raise ValueError("firmware needs a platform: bios:<slug>, e.g. bios:psx")
        return "bios:" + slug
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", low):
        raise ValueError("a RomM platform is a slug such as snes or psx (lowercase, no spaces)")
    return low


_SUGGEST = {s.replace("-", " "): s for s in SLUGS}


def suggest(name: str) -> Optional[str]:
    n = name.lower()
    n = n.split(" - ", 1)[-1]                       # "Watara - Supervision" -> "supervision"
    n = re.sub(r"\(.*?\)|\[.*?\]", "", n).strip()
    m = difflib.get_close_matches(n, list(_SUGGEST), n=1, cutoff=0.9)
    return _SUGGEST[m[0]] if m else None


class Mapping:
    """Resolve every folder to a RomM role, then render the links and config.yml.

    Several download folders ("roots", e.g. lolroms and collection) can feed RomM. `folders` is
    {path: (files directly in it, of which on disk)} with paths relative to the links folder, so
    they start with a root ("lolroms/Nintendo/Super Famicom", "collection/snes"); every path's
    ancestors must be present (folders_from_roots guarantees that). `roots` is the list of roots
    in priority order: when two roots give the same platform, the first one is linked and the
    other is reported as a conflict (exclude it, or change the order). `links_dir` is the folder
    that holds the roots and gets the platform links."""

    def __init__(self, folders: dict, options: Optional[dict] = None, links_dir: str = "",
                 roots: Optional[list] = None):
        self.folders = folders
        self.opt = dict(DEFAULT_OPTIONS, **(options or {}))
        self.roots = list(roots or [])
        self.base = os.path.abspath(links_dir) if links_dir else ""
        self.user = {k: v for k, v in (self.opt.get("map") or {}).items() if v}
        self.res: dict = {}          # path -> dict(kind, slug, source)
        self._resolve()
        self._group()

    # ------------------------------------------------------------------ roles
    def _resolve(self):
        self.auto: dict = {}         # path -> what it would be without your own choice for it
        for path in sorted(self.folders, key=lambda p: (p.count("/"), p)):
            if not path:
                continue
            up = self.res.get(parent_of(path))
            if self.root_of(path) == path or self.root_of(path) is None:
                # a download folder itself (or a folder above it): no platform of its own
                self.auto[path] = self.res[path] = self._decide(path, self.user.get(path, ""), "yours", None)
                continue
            rule = RULES.get(self.inner(path), "")
            mine = self.user.get(path)
            if up and (up.get("excluded") or up.get("excluded_tree")) and not mine:
                # inside a folder you excluded: left out too, whatever the built-in rules say
                self.auto[path] = self.res[path] = {"kind": SKIP, "slug": "", "source": "yours",
                                                    "excluded_by": up.get("excluded_by") or parent_of(path),
                                                    "excluded": False, "inherited": True}
                self.res[path]["excluded_tree"] = True
                continue
            self.auto[path] = self._decide(path, rule, "rule", up)
            self.res[path] = self._decide(path, mine, "yours", up) if mine else self.auto[path]

    def root_of(self, path: str) -> Optional[str]:
        """The download folder (root) a path belongs to, or None."""
        for r in self.roots:
            if path == r or path.startswith(r + "/"):
                return r
        return None

    def inner(self, path: str) -> str:
        """The path inside its root ("lolroms/Nintendo/Super Famicom" -> "Nintendo/Super Famicom"),
        which is what the built-in lolroms rules use."""
        r = self.root_of(path)
        return path[len(r) + 1:] if r and path != r else ""

    def _decide(self, path: str, action: str, source: str, up: Optional[dict]) -> dict:
        r = {"kind": UNMAPPED, "slug": "", "source": source if action else "auto"}
        if action == "skip":
            r["kind"] = SKIP
        elif action == "exclude":                 # skipped, and its name goes into RomM's
            r.update(kind=SKIP, excluded=True)     # exclude rules in config.yml
        elif action == "merge":
            if up and up["kind"] in (PLATFORM, MERGE):
                r.update(kind=MERGE, slug=up["slug"])
        elif action.startswith("bios:"):
            r.update(kind=BIOS, slug=action[5:])
        elif action:
            r.update(kind=PLATFORM, slug=action)
        elif up and up["kind"] in (PLATFORM, MERGE):
            name = name_of(path)
            if BIOS_NAMES.search(name):
                r.update(kind=BIOS, slug=up["slug"])
            elif SKIP_NAMES.match(name) or not self.opt["variants"]:
                r["kind"] = SKIP
            else:
                r.update(kind=MERGE, slug=up["slug"])
        elif up and up["kind"] in (SKIP, BIOS):
            r.update(kind=up["kind"], slug=up["slug"])
        elif name_of(path) in SLUGS and "/" not in self.inner(path):
            # a folder named exactly like a RomM platform right inside a download folder (a
            # RomM-style collection: collection/snes, collection/psx)
            r.update(kind=PLATFORM, slug=name_of(path))
        return r

    @staticmethod
    def choice(r: dict) -> str:
        """How a folder's role is shown in its dropdown: a platform slug, "exclude", "firmware"
        (BIOS folders, handled automatically) or "" (no platform yet)."""
        if r["kind"] in (PLATFORM, MERGE):
            return r["slug"]
        if r["kind"] == SKIP:
            return "exclude"
        if r["kind"] == BIOS:
            return "firmware"
        return ""

    def excluded_names(self) -> list:
        """Folder names you marked "exclude" inside a platform RomM reads: written to RomM's
        exclude rules. (A folder that isn't inside a linked platform is simply not linked.)"""
        out = set()
        for p, r in self.res.items():
            if r.get("excluded"):
                up = self.res.get(parent_of(p))
                if up and up["kind"] in (PLATFORM, MERGE):
                    out.add(name_of(p))
        return sorted(out, key=str.casefold)

    def _counts(self, path):
        files, have = self.folders.get(path, (0, 0))
        return files, have

    def _uses(self, path) -> bool:
        files, have = self._counts(path)
        return bool(have if self.opt["only_synced"] else files)

    # ------------------------------------------------------------------ platforms
    def _group(self):
        games, fw = {}, {}
        for path, r in self.res.items():
            if r["kind"] in (PLATFORM, MERGE) and self._uses(path):
                games.setdefault(r["slug"], {}).setdefault(self.root_of(path), []).append(path)
            elif r["kind"] == BIOS and self._uses(path):
                fw.setdefault(r["slug"], []).append(path)
        order = {r: i for i, r in enumerate(self.roots)}
        self.conflicts = []           # [{slug, root, folders, winner, winner_folders}]
        self.lost: dict = {}          # path -> root whose folder RomM gets instead
        chosen = {}
        for slug, by_root in games.items():
            ranked = sorted(by_root, key=lambda r: order.get(r, 99))
            win = ranked[0]
            chosen[slug] = by_root[win]
            for other in ranked[1:]:
                self.conflicts.append({"slug": slug, "root": other, "folders": sorted(by_root[other]),
                                       "winner": win, "winner_folders": sorted(by_root[win])})
                for p in by_root[other]:
                    self.lost[p] = win
        wild = self.opt.get("layout", "category") == "category"
        self.platforms = []
        for slug in sorted(chosen):
            paths = sorted(chosen[slug])
            mount = common_dir(paths)
            used = set(paths)
            # every folder on the way from the mount to a used folder is a grouping level
            grouping = set()
            for p in paths:
                while len(p) > len(mount):
                    grouping.add(p)
                    p = parent_of(p)
            # folders RomM looks inside: the used ones, and (with {category} wildcards, which match
            # any subfolder) the mount and every grouping level. Their other subfolders are excluded.
            looked_in = used | ((grouping | {mount}) if wild else set())
            exclude = set()
            for d in looked_in:
                for child in self.children(d):
                    if child not in used and child not in grouping:
                        exclude.add(name_of(child))
            self.platforms.append({"slug": slug, "mount": mount, "folders": paths, "grouping": grouping,
                                   "exclude": sorted(exclude),
                                   "files": sum(self._counts(p)[1 if self.opt["only_synced"] else 0]
                                                for p in paths)})
        # exclude.roms.multi_file.names is one list for all platforms (case-insensitive), and a
        # wildcard level skips those names - so a folder we need whose name is excluded somewhere
        # gets an exact-name template instead (RomM always follows literal levels).
        excluded = {n.lower() for p in self.platforms for n in p["exclude"]}
        for p in self.platforms:
            p["templates"] = self._templates(p, wild, excluded)
            del p["grouping"]
        self.firmware = []
        for slug in sorted(fw):
            paths = sorted(fw[slug])
            self.firmware.append({"slug": slug, "mount": paths[0], "folders": paths[:1],
                                  "ignored": paths[1:]})

    def _templates(self, plat: dict, wild: bool, excluded: set) -> list:
        mount, paths = plat["mount"], plat["folders"]
        literal = ["roms/{platform}/" + (rel(p, mount) + "/" if rel(p, mount) else "") + "{game}"
                   for p in paths]
        if not wild:
            return literal
        depth = {p: (rel(p, mount).count("/") + 1 if rel(p, mount) else 0) for p in paths}
        depths = set(depth.values())
        # a wildcard level reads every folder at that depth: if one of them holds files of its own
        # but isn't wanted (only a way down to wanted folders), exact names are the only safe choice
        for g in plat["grouping"] - set(paths):
            gd = rel(g, mount).count("/") + 1
            if gd in depths and self._counts(g)[1 if self.opt["only_synced"] else 0]:
                return literal
        names = ["{category}", "{subcategory}"]
        out = []
        for d in sorted(depths):
            levels = [names[i] if i < len(names) else "{level%d}" % (i + 1) for i in range(d)]
            out.append("/".join(["roms/{platform}", *levels, "{game}"]))
        for p, t in zip(paths, literal):
            if any(part.lower() in excluded for part in rel(p, mount).split("/") if part):
                out.append(t)
        return out

    def children(self, path):
        if not hasattr(self, "_kids"):
            self._kids = {}
            for p in self.folders:
                if p:
                    self._kids.setdefault(parent_of(p), []).append(p)
        return self._kids.get(path, [])

    # ------------------------------------------------------------------ report
    def rows(self) -> list:
        """One row per folder that holds files (or has a rule of its own), for the interface."""
        out = []
        for path in sorted(self.res, key=str.casefold):
            r = self.res[path]
            files, have = self._counts(path)
            if not files and path not in self.user and self.inner(path) not in RULES and path not in self.roots:
                continue
            row = {"path": path, "files": files, "synced": have, "kind": r["kind"], "slug": r["slug"],
                   "excluded": bool(r.get("excluded")), "root": self.root_of(path),
                   "value": self.choice(r), "auto": self.choice(self.auto[path]),
                   "source": r["source"], "action": self.user.get(path, ""),
                   "rule": RULES.get(self.inner(path), ""),
                   "used": r["kind"] in (PLATFORM, MERGE, BIOS) and self._uses(path) and path not in self.lost}
            if path in self.lost:
                row["conflict"] = self.lost[path]
            if r.get("excluded_tree"):
                row["excluded_by"] = r.get("excluded_by")
            if r["kind"] in (PLATFORM, MERGE) and r["slug"] not in SLUGS:
                row["custom"] = True
            out.append(row)
        return out

    def warnings(self) -> list:
        w = []
        unmapped = [p for p, r in self.res.items() if r["kind"] == UNMAPPED and self._uses(p)]
        if unmapped:
            w.append(f"{len(unmapped)} folders with files have no RomM platform yet and are left out: "
                     + ", ".join(unmapped[:6]) + (" ..." if len(unmapped) > 6 else ""))
        custom = sorted({p["slug"] for p in self.platforms if p["slug"] not in SLUGS})
        unknown = [s for s in custom if s not in VERSIONS]
        if unknown:
            w.append("RomM has no platform called " + ", ".join(unknown) +
                     " - it will add them as custom platforms without metadata.")
        dated = [f for p in self.platforms + self.firmware for f in p["folders"] if DATED.search(f)]
        if dated:
            w.append("These folder names include a date and change when the site updates them, so copy "
                     "config.yml again after a scan: " + ", ".join(dated))
        for f in self.firmware:
            if f["ignored"]:
                w.append(f"Firmware for {f['slug']} comes from {f['mount']}; also found in "
                         + ", ".join(f["ignored"]) + " (left out - RomM reads one firmware folder per platform).")
        for c in self.conflicts:
            w.append(f"{c['slug']} is in more than one download folder: RomM gets "
                     f"{', '.join(c['winner_folders'])} ({c['winner']} is first in the list), not "
                     f"{', '.join(c['folders'])}. Exclude the one you don't want, or change the order.")
        if self.firmware:
            w.append("Firmware isn't linked (RomM's bios folder is separate): copy these to RomM's bios "
                     "folder: " + ", ".join(f["mount"] for f in self.firmware))
        return w

    # ------------------------------------------------------------------ platform links
    @property
    def links_dir(self) -> str:
        return self.base

    def data_in_links(self) -> Optional[str]:
        """The first download folder, relative to the links folder (used in the help texts)."""
        return self.roots[0] if self.roots else None

    def link_targets(self) -> dict:
        """{platform slug: relative link target}, e.g. {"snes": "lolroms/Nintendo/Super Famicom"}"""
        return {p["slug"]: p["mount"] for p in self.platforms}

    def romm_folder(self) -> str:
        """The "RomM folder" setting: where the lolroms downloads appear inside RomM's container
        (default /romm/library/roms/lolroms). Values not under /romm are older server paths."""
        f = (self.opt.get("romm_folder") or "").strip().rstrip("/\\")
        return f if f.startswith("/romm/") else DEFAULT_ROMM_FOLDER

    def library(self) -> str:
        """RomM's library folder inside its container, from the RomM folder (/romm/library)."""
        f = self.romm_folder()
        return f.split("/roms/")[0] if "/roms/" in f else "/romm/library"

    def compose(self) -> str:
        """The one volume line RomM's compose file needs: the links folder as its roms folder."""
        return ("    volumes:\n"
                "      # for the RomM service: replace its .../romm/library/roms line with\n"
                f"      # the server folder that holds the download folders ({', '.join(self.roots) or 'downloads'}) and the platform links.\n"
                f"      - {json.dumps('/path/on/your/server:' + self.library() + '/roms', ensure_ascii=False)}\n")

    def config_yml(self) -> str:
        q = lambda s: json.dumps(s, ensure_ascii=False)  # noqa: E731 - JSON strings are valid YAML
        lines = ["# RomM config.yml - generated by ROM Mapper. Merge these sections into your config.yml",
                 "# (keep your other settings). Platforms: ROM Mapper's links in roms/<platform>.", ""]
        names = sorted({n for p in self.platforms for n in p["exclude"]} | set(self.excluded_names())
                       | (set(self.opt.get("skip_names") or []) if self.platforms else set()),
                       key=str.casefold)
        tops = sorted({r.split("/")[0] for r in self.roots}, key=str.casefold)
        if tops:
            lines += ["exclude:", "  # the download folders themselves are not platforms (their platforms are linked)",
                      "  platforms:"] + [f"    - {q(t)}" for t in tops]
            if names:
                lines += ["  roms:", "    multi_file:",
                          "      # subfolders that are another platform, firmware or not games",
                          "      names:"] + [f"        - {q(n)}" for n in names]
            lines.append("")
            names = []
        if names:
            lines += ["exclude:", "  roms:", "    multi_file:",
                      "      # subfolders that are another platform, firmware or not games",
                      "      names:"] + [f"        - {q(n)}" for n in names] + [""]
        custom = [p for p in self.platforms if p["templates"] != ["roms/{platform}/{game}"]]
        if custom:
            lines += ["filesystem:", "  structure:", "    default: 'roms/{platform}/{game}'",
                      "    firmware: 'bios/{platform}'"]
            for p in custom:
                lines.append(f"    {q(p['slug'])}:")
                lines += [f"      - {q(t)}" for t in p["templates"]]
            lines.append("")
        versions = {p["slug"]: VERSIONS[p["slug"]] for p in self.platforms if p["slug"] in VERSIONS}
        if versions:
            lines += ["system:", "  versions:"] + [f"    {q(k)}: {q(v)}" for k, v in versions.items()] + [""]
        return "\n".join(lines)

    def summary(self) -> dict:
        return {"platforms": len(self.platforms), "firmware": len(self.firmware),
                "files": sum(p["files"] for p in self.platforms)}


BACKUP_FILE = "romm-mapper.json"


def write_backup(config_dir: str, opts: dict) -> None:
    """Save the RomM settings and folder choices (written atomically)."""
    path = os.path.join(config_dir, BACKUP_FILE)
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(opts, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except OSError:
        pass


def read_backup(config_dir: str) -> dict:
    try:
        with open(os.path.join(config_dir, BACKUP_FILE), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def apply_links(m: "Mapping") -> dict:
    """Create / update / remove the platform folder links for links mode. Only links that point
    into the download folder are ever changed or removed; real folders are never touched."""
    res = {"created": [], "updated": [], "removed": [], "kept": 0, "skipped": [], "errors": []}
    if not m.roots:
        res["errors"].append("no download folder is set")
        return res
    links_dir = m.links_dir
    want = m.link_targets()

    def ours(target: str) -> bool:
        t = target.replace(os.sep, "/")
        return not os.path.isabs(t) and any(t == r or t.startswith(r + "/") for r in m.roots)

    for name, target in sorted(want.items()):
        path = os.path.join(links_dir, name)
        try:
            if os.path.islink(path):
                cur = os.readlink(path)
                if cur == target:
                    res["kept"] += 1
                    continue
                if not ours(cur):
                    res["skipped"].append(f"{name} (a link to {cur} that ROM Mapper didn't make)")
                    continue
                os.remove(path)
                os.symlink(target, path, target_is_directory=True)
                res["updated"].append(name)
            elif os.path.exists(path):
                res["skipped"].append(f"{name} (a folder with that name already exists)")
            else:
                os.symlink(target, path, target_is_directory=True)
                res["created"].append(name)
        except OSError as e:
            res["errors"].append(f"{name}: {e}")
    try:
        with os.scandir(links_dir) as it:
            for e in it:
                if e.is_symlink() and e.name not in want and ours(os.readlink(e.path)):
                    try:
                        os.remove(e.path)
                        res["removed"].append(e.name)
                    except OSError as err:
                        res["errors"].append(f"{e.name}: {err}")
    except OSError as e:
        res["errors"].append(str(e))
    return res


def describe_links(res: dict) -> str:
    parts = [f"{len(res['created'])} created", f"{len(res['updated'])} updated",
             f"{len(res['removed'])} removed", f"{res['kept']} unchanged"]
    out = "RomM platform links: " + ", ".join(parts)
    if res["skipped"]:
        out += "; skipped " + "; ".join(res["skipped"])
    if res["errors"]:
        out += "; problems: " + "; ".join(res["errors"][:5])
    return out


IGNORED_FILES = {"thumbs.db", "desktop.ini"}


def folders_from_roots(links_dir: str, sources: list, full: bool = True, depths: Optional[dict] = None,
                       progress=None, skip=(), stop=None) -> tuple:
    """Read every download folder -> ({path relative to links_dir: (files, files)}, [roots]).
    Folders above a root (e.g. "sets" for links_dir/sets/collection) are added with no files.
    depths: {download folder: levels to list} (missing or 0 = all). progress(i, n, done, total,
    current) is called while folder i of n is read: done of the total folders directly inside it
    are finished, and current is being read. Folders whose name matches skip aren't read. stop:
    folders (relative to links_dir, like "lolroms/Konami") that are listed but not read inside."""
    out = {"": (0, 0)}
    roots = []
    depths = depths or {}
    for i, src in enumerate(sources):
        root = os.path.relpath(os.path.abspath(src), os.path.abspath(links_dir)).replace(os.sep, "/")
        roots.append(root)
        parts = root.split("/")
        for j in range(1, len(parts)):
            out.setdefault("/".join(parts[:j]), (0, 0))
        step = (lambda done, total, cur, i=i: progress(i, len(sources), done, total, cur)) if progress else None
        inside = {s[len(root) + 1:] for s in (stop or ()) if s.startswith(root + "/")}
        for p, n in folders_from_disk(src, full, depth=int(depths.get(src) or 0), progress=step,
                                      skip=skip, stop=inside).items():
            out[root + ("/" + p if p else "")] = n
    return out, roots


# Folder counts from the last read, per absolute folder: (mtime_ns, files, subfolders). A folder's
# date changes whenever something is added, removed or renamed directly inside it, so an unchanged
# date means its count and subfolders can be reused without listing it again.
_dir_cache: dict = {}


def folders_from_disk(source: str, full: bool = True, depth: int = 0, progress=None, skip=(),
                      stop=()) -> dict:
    """{folder path relative to source: (files in it, files in it)} for every folder under source.
    Rom Sync's catalog knew what was listed on the site; here the disk is the truth, so both
    numbers are the files actually there. Dot-files (Rom Sync's manifest), unfinished downloads
    (.part) and folder links are left out. full=False lists only folders whose date changed since
    the last read (one stat per folder instead of reading every folder).

    depth > 0 lists only that many levels (1 = the folders directly inside source). A folder on the
    last level isn't read further; its subfolders count as items, so a platform folder that keeps
    its games in subfolders (one per multi-disc game) isn't taken for empty. progress(done, total,
    current) is called before each folder directly inside source is read, and once at the end.
    Folders whose name matches a skip pattern (e.g. "media") are left out and not read at all.
    Folders in stop (paths relative to source) are listed like a last level: not read inside."""
    out = {}
    source = os.path.abspath(source)
    skip = tuple(skip or ())

    def visit(path, rel, level):
        last = (bool(depth) and level >= depth) or (rel in stop)
        try:
            mtime = os.stat(path).st_mtime_ns
        except OSError:
            return
        key = (path, last, skip)
        hit = None if full else _dir_cache.get(key)
        if hit and hit[0] == mtime:
            _, n, subs = hit
        else:
            n, subs = 0, []
            try:
                with os.scandir(path) as it:
                    for e in it:
                        name = e.name
                        if name.startswith("."):
                            continue
                        try:
                            if e.is_dir():
                                # folder links and skipped names are left out
                                if not e.is_symlink() and not (skip and skipped(name, skip)):
                                    subs.append(name)
                                continue
                        except OSError:
                            continue
                        if not name.endswith(".part") and name.lower() not in IGNORED_FILES:
                            n += 1
            except OSError:
                return
            subs.sort()
            if last:                                # deeper folders aren't listed: count them
                n, subs = n + len(subs), []
            _dir_cache[key] = (mtime, n, subs)
        out[rel] = (n, n)
        for i, d in enumerate(subs):
            if level == 0 and progress:
                progress(i, len(subs), d)
            visit(os.path.join(path, d), f"{rel}/{d}" if rel else d, level + 1)
        if level == 0 and progress:
            progress(len(subs), len(subs), "")

    visit(source, "", 0)
    out.setdefault("", (0, 0))
    return out


def options_from(settings: dict) -> dict:
    saved = dict(settings.get("romm") or {})
    if saved.pop("method", None) == "links":          # before 1.3.0: links were one of two methods
        saved.setdefault("keep_links", True)
    saved.pop("host_path", None)                       # before 1.2.9 (Docker mounts only)
    saved.pop("library", None)                         # now derived from the RomM folder
    return dict(DEFAULT_OPTIONS, **saved)
