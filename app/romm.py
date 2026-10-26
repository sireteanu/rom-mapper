"""RomM mapping: which of your folders is which RomM platform, without moving any files.

Moved here from Rom Sync (sireteanu/rom-sync, src/lolroms_sync/romm.py, v1.3.4); the rules and the
romm-mapper.json format are the same, so choices made in Rom Sync carry over.

Every folder with a platform becomes a volume of RomM's container, mounted at
/romm/library/roms/<slug>: ROM Mapper generates the volume lines for RomM's compose file and Docker
mounts them whenever RomM starts. So RomM's roms folder only holds valid platform folders, under
their slugs - no renames or platform excludes needed - and a platform can be any folder (lolroms'
Nintendo/Super Famicom too). A platform with subfolders that
belong to it (+translations under gbc) gets filesystem.structure templates
roms/{platform}/{game} + roms/{platform}/{category}/{game}, keyed by the slug (= the mount's folder
name). Subfolders that aren't games (never-read names, BIOS, raw dumps, your excludes, folders that
are a platform of their own) go into exclude.roms.multi_file.names. Older versions made platform
links; apply_links (with no targets) removes the ones they made.

Per folder an action decides what happens: a RomM slug, "merge" (into the platform above),
"bios:<slug>" (firmware), "skip", "exclude", or nothing (the built-in rule, else inherited).
"cat:<slug>" (1.0.9) is read as <slug>: categories now follow from the subfolders.
RomM facts this relies on (backend/, Oct 2026): filesystem.structure is keyed by the platform's
fs_slug (its folder name), str or list; roms_handler unions the templates and drops a folder-game
that another template descends through, so with both templates every subfolder is a category;
exclude multi_file names apply at wildcard levels ({category}); RomM sees a bind mount as a plain
folder; compose's short volume syntax splits on ":", so a source with one gets the long syntax.
"""
from __future__ import annotations

import difflib
import fnmatch
import json
import os
import re
from typing import Optional

from romm_slugs import PLATFORMS, SLUGS  # app/ is the script folder (python /app/server.py)


def yaml_path(s: str) -> str:
    """A path as a YAML value: plain (unquoted, like a hand-written compose file) when YAML reads it
    back unchanged, else a double-quoted string (JSON strings are valid YAML). A plain value can't
    start with a YAML indicator, hold ": " or " #", end with ":" or whitespace, or have control
    characters; paths start with "/", so the rest is what matters."""
    plain = (s and s[0] == "/" and s == s.strip() and ": " not in s and " #" not in s
             and not s.endswith(":") and not any(ord(ch) < 32 or ord(ch) == 127 for ch in s))
    return s if plain else json.dumps(s, ensure_ascii=False)

__all__ = ["PLATFORMS", "SLUGS", "Mapping"]   # PLATFORMS is used by web.py

DEFAULT_OPTIONS = {
    "only_synced": True,          # only folders that have files on disk
    "links_dir": "",              # where older versions made platform links ("" = the download
                                  # folder's parent); only used to remove them now
    "map": {},                    # your own actions: {download folder/path: action}
    "skip_names": ["media"],      # folders with these names (wildcards allowed) are never read or
                                  # listed, and RomM is told to ignore them too
}
# Settings of older versions (platform links, RomM folder, layout, variants, mode) are ignored.


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


def check_action(action: str) -> str:
    """Normalise a user-entered action; raises ValueError on nonsense."""
    a = (action or "").strip()
    low = a.lower()
    if low in ("", "auto", "default"):
        return ""
    if low in ("skip", "merge", "exclude"):
        return low
    if low.startswith("cat:"):
        slug = low.split(":", 1)[1].strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", slug):
            raise ValueError("categories need a platform: cat:<slug>, e.g. cat:atari2600")
        return "cat:" + slug
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
    """Resolve every folder to a RomM role, then render config.yml.

    `folders` is {path: (files directly in it, of which on disk)} with paths relative to the
    folder above the download folders, so they start with a root ("roms/snes"); every path's
    ancestors must be present (folders_from_roots guarantees that). RomM reads one roms folder:
    the first root. `links_dir` is that folder above (where older versions made links)."""

    def __init__(self, folders: dict, options: Optional[dict] = None, links_dir: str = "",
                 roots: Optional[list] = None):
        self.folders = folders
        self.opt = dict(DEFAULT_OPTIONS, **(options or {}))
        self.roots = list(roots or [])
        self.base = os.path.abspath(links_dir) if links_dir else ""
        self.user = {k: v for k, v in (self.opt.get("map") or {}).items() if v}
        self.res: dict = {}          # path -> dict(kind, slug, source[, cats])
        self.lost: dict = {}         # folder -> the folder that has its platform already
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
        elif action.startswith("cat:"):           # 1.0.9: categories now follow from the subfolders
            r.update(kind=PLATFORM, slug=action[4:])
        elif action:
            r.update(kind=PLATFORM, slug=action)
        elif up and up["kind"] in (PLATFORM, MERGE):
            name = name_of(path)
            if BIOS_NAMES.search(name):
                r.update(kind=BIOS, slug=up["slug"])
            elif SKIP_NAMES.match(name):
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
        """How a folder's role is shown in its picker: a platform slug, "exclude", "firmware" (BIOS
        folders, automatic) or "" (none)."""
        if r["kind"] in (PLATFORM, MERGE):
            return r["slug"]
        if r["kind"] == SKIP:
            return "exclude"
        if r["kind"] == BIOS:
            return "firmware"
        return ""

    def excluded_names(self) -> list:
        """Names of subfolders inside a platform that aren't its games - excluded by you, skipped by
        name (raw dumps), firmware, or a platform of their own: exclude.roms.multi_file.names."""
        out = set()
        for p, r in self.res.items():
            if r["kind"] in (SKIP, BIOS, PLATFORM) and not r.get("inherited"):
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
        """Every folder with a platform (and files in it or below) becomes a mount named after the
        platform. Two folders for one platform: the one already named like it wins, else the
        shallower, else the first by name. A platform whose subfolders belong to it (merged, with
        files) gets categories."""
        self.platforms, self.firmware = [], []
        col = 1 if self.opt["only_synced"] else 0
        self.tree: dict = {}                     # path -> files in it and everything below
        for p in self.folders:
            n = self._counts(p)[col]
            q = p
            while True:
                self.tree[q] = self.tree.get(q, 0) + n
                if not q:
                    break
                q = parent_of(q)
        cands = [p for p, r in self.res.items() if r["kind"] == PLATFORM and self.root_of(p) not in (None, p)
                 and self.tree.get(p)]
        cands.sort(key=lambda p: (name_of(p) != self.res[p]["slug"], p.count("/"), p.casefold()))
        taken: dict = {}
        for p in cands:
            slug = self.res[p]["slug"]
            if slug in taken:
                self.lost[p] = taken[slug]
                continue
            taken[slug] = p
            cats = any(self.res[k]["kind"] == MERGE and self.tree.get(k) for k in self.children(p))
            self.platforms.append({"slug": slug, "mount": p, "folders": [p], "categories": cats,
                                   "files": self.tree[p]})
        self.platforms.sort(key=lambda x: x["slug"])
        self.mounted = {x["mount"]: x for x in self.platforms}
        self.firmware = sorted(p for p, r in self.res.items()
                               if r["kind"] == BIOS and self._uses(p) and self.platform_of(p) in self.mounted)

    def platform_of(self, path: str) -> Optional[str]:
        """The folder whose platform path is part of: itself, or the nearest platform above it."""
        q = path
        while q:
            r = self.res.get(q)
            if r and r["kind"] == PLATFORM:
                return q
            if not r or r["kind"] not in (MERGE, BIOS, SKIP):
                return None
            q = parent_of(q)
        return None

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
            owner = self.platform_of(path) if r["kind"] in (PLATFORM, MERGE) else None
            row = {"path": path, "files": files, "synced": have, "kind": r["kind"], "slug": r["slug"],
                   "excluded": bool(r.get("excluded")), "root": self.root_of(path),
                   "value": self.choice(r), "auto": self.choice(self.auto[path]),
                   "source": r["source"], "action": self.user.get(path, ""),
                   "rule": RULES.get(self.inner(path), ""),
                   "used": owner in self.mounted}
            if r["kind"] == MERGE and owner in self.mounted and parent_of(path) == owner:
                row["category"] = True
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
        unmapped = [p for p, r in self.res.items() if r["kind"] == UNMAPPED and self._uses(p)
                    and self.platform_of(p) is None]
        if unmapped:
            w.append(f"{len(unmapped)} folders with files have no RomM platform and are left out: "
                     + ", ".join(unmapped[:6]) + (" ..." if len(unmapped) > 6 else ""))
        for p, winner in self.lost.items():
            w.append(f"{p} and {winner} are both set to {self.res[p]['slug']}: RomM gets {winner}, "
                     f"{p} is left out.")
        custom = sorted({p["slug"] for p in self.platforms if p["slug"] not in SLUGS})
        unknown = [s for s in custom if s not in VERSIONS]
        if unknown:
            w.append("RomM has no platform called " + ", ".join(unknown) +
                     " - it will add them as custom platforms without metadata.")
        if self.firmware:
            w.append("Firmware folders are left out of the games (RomM's bios folder is separate) - copy them "
                     "to RomM's bios folder: " + ", ".join(self.firmware[:6]) + (" ..." if len(self.firmware) > 6 else ""))
        return w

    # ------------------------------------------------------------------ old platform links
    @property
    def links_dir(self) -> str:
        return self.base

    def link_targets(self) -> dict:
        """Platform links to keep: none (RomM reads the folders by name). apply_links then removes
        the links older versions made."""
        return {}

    # ------------------------------------------------------------------ outputs
    def volumes(self) -> str:
        """The volume lines for RomM's compose file: one per platform, the source folder (a host path -
        the same inside ROM Mapper's container) mounted at /romm/library/roms/<slug>. Docker mounts
        them when RomM starts, so they survive reboots."""
        q = yaml_path
        lines = ["    volumes:",
                 "      # RomM platforms - generated by ROM Mapper. Put these in the RomM service's volumes,",
                 "      # replacing its own .../romm/library/roms line. After a change, paste them again and",
                 "      # Compose Up RomM. (Read-only: add :ro to a line, or read_only: true to a long one.)"]
        for p in self.platforms:
            src = os.path.join(self.base, p["mount"]) if self.base else p["mount"]
            dst = f"/romm/library/roms/{p['slug']}"
            if ":" in src:                       # the short syntax splits on ":" - use the long one
                lines += ["      - type: bind", f"        source: {q(src)}", f"        target: {q(dst)}"]
            else:
                lines.append(f"      - {q(src + ':' + dst)}")
        return "\n".join(lines) + "\n"

    def config_yml(self) -> str:
        """filesystem.structure (with categories for the platforms whose subfolders belong to them,
        keyed by slug = the mount's folder name), the subfolders that aren't games, system.versions."""
        q = lambda s: json.dumps(s, ensure_ascii=False)  # noqa: E731 - JSON strings are valid YAML
        lines = ["# RomM config.yml - generated by ROM Mapper. Merge these sections into your config.yml",
                 "# (keep your other settings). The platform folders are the RomM volumes.", "",
                 "filesystem:", "  structure:", '    default: "roms/{platform}/{game}"',
                 '    firmware: "bios/{platform}"']
        cats = [p for p in self.platforms if p["categories"]]
        if cats:
            lines.append("    # subfolders of these platforms are categories (+translations, Homebrew ...)")
            for p in cats:
                lines += [f"    {q(p['slug'])}:", '      - "roms/{platform}/{game}"',
                          '      - "roms/{platform}/{category}/{game}"']
        lines.append("")
        names = sorted(set(self.excluded_names()) | (set(self.opt.get("skip_names") or []) if self.platforms else set()),
                       key=str.casefold)
        if names:
            lines += ["exclude:", "  roms:", "    multi_file:", "      # subfolders that are not games",
                      "      names:"] + [f"        - {q(n)}" for n in names] + [""]
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
        return not os.path.isabs(target) and any(target == r or target.startswith(r + "/") for r in m.roots)

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


def old_links(m: "Mapping") -> int:
    """How many platform links an older version made are still in the links folder."""
    if not m.links_dir or not m.roots:
        return 0
    n = 0
    try:
        with os.scandir(m.links_dir) as it:
            for e in it:
                if e.is_symlink():
                    t = os.readlink(e.path)
                    if not os.path.isabs(t) and any(t == r or t.startswith(r + "/") for r in m.roots):
                        n += 1
    except OSError:
        return 0
    return n


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
        root = os.path.relpath(os.path.abspath(src), os.path.abspath(links_dir))
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
    saved.pop("method", None)                          # Rom Sync before 1.3.0
    saved.pop("host_path", None)                       # before 1.2.9 (Docker mounts only)
    saved.pop("library", None)                         # now derived from the RomM folder
    for old in ("romm_folder", "variants", "keep_links", "layout", "mode"):   # before 1.0.9
        saved.pop(old, None)
    return dict(DEFAULT_OPTIONS, **saved)
