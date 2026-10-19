"""rom-mapper web UI.

Keeps the mapping (frontends x folders) in rom-mapper-mapping.json in the config folder, scans
the source folders for new/removed folders, and keeps the frontend links in line with it
(links.py) on demand or on a schedule.

RomM (romm.py): maps a lolroms download folder (nested, e.g. Nintendo/Super Famicom) to RomM
platforms with relative platform links next to it plus a generated config.yml. Settings and folder
choices live in romm-mapper.json in the config folder - the same file Rom Sync used.
"""

import gzip
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from collections import deque
from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_from_directory

import links
import romm
from version import __version__

# --- CONFIGURATION (environment variables) ---
CONFIG_DIR = os.environ.get("CONFIG_DIR", "/config")
MAPPING_FILE = os.environ.get("MAPPING_FILE", os.path.join(CONFIG_DIR, "rom-mapper-mapping.json"))
SRC_BASE = os.environ.get("SRC_BASE", "/data/roms")
DEST_PATH = os.environ.get("DEST_PATH", "/data/mapping")
STATE_FILE = os.environ.get(
    "STATE_FILE", os.path.join(CONFIG_DIR, "rom-mapper-state.json")
)
PORT = int(os.environ.get("PORT", "8085"))
# RomM: the download folder(s) to map (e.g. Rom Sync's lolroms folder), mounted at the same path as
# on the host; several separated by ";" (first = preferred when two give the same platform).
# Can also be set in the UI; "" = RomM section not set up yet.
ROMM_SOURCE = os.environ.get("ROMM_SOURCE", "")
# ----------------------------------------------

DEFAULT_SETTINGS = {
    # source folders for the mapping grid: [{"path", "label", "depth"}]; [] = SRC_BASE (one level)
    "sources": [],
    "scan_enabled": True,
    "scan_every": 1,
    "scan_unit": "hours",
    "auto_add_new": True,
    "sync_enabled": False,
    "sync_every": 1,
    "sync_unit": "days",
}

# Schedule units (seconds each) and the shortest / longest interval allowed.
UNITS = {"minutes": 60, "hours": 3600, "days": 86400}
MIN_INTERVAL = {"scan": 60, "sync": 300}
MAX_INTERVAL = 365 * 86400

app = Flask(__name__, static_folder="static", static_url_path="/static")

csv_lock = threading.RLock()      # guards reads/writes of the mapping and state file
romm_lock = threading.RLock()     # guards romm-mapper.json and the platform links
sync_lock = threading.Lock()      # only one sync at a time
activity = deque(maxlen=200)      # in-memory event log for the UI


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(msg):
    activity.appendleft({"time": now_iso(), "msg": msg})
    print(f"[{now_iso()}] {msg}", flush=True)


# ---------------------------------------------------------------- state file

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    data["settings"] = {**DEFAULT_SETTINGS, **convert_schedule(dict(data.get("settings", {})))}
    data.setdefault("last_scan", None)
    data.setdefault("last_sync", None)
    return data


def best_unit(minutes):
    """A number of minutes -> (every, unit) in the largest unit that divides it evenly."""
    for unit in ("days", "hours"):
        size = UNITS[unit] // 60
        if minutes >= size and minutes % size == 0:
            return minutes // size, unit
    return minutes, "minutes"


def convert_schedule(saved):
    """Before 1.0.3 the schedule was scan_interval_minutes / sync_interval_hours; now each is a
    number and a unit (minutes, hours or days)."""
    for kind, old, minutes_per in (("scan", "scan_interval_minutes", 1), ("sync", "sync_interval_hours", 60)):
        if old not in saved:
            continue
        value = saved.pop(old)
        if f"{kind}_every" in saved:
            continue
        try:
            minutes = max(1, round(float(value) * minutes_per))
        except (TypeError, ValueError):
            continue
        saved[f"{kind}_every"], saved[f"{kind}_unit"] = best_unit(minutes)
    return saved


def interval_seconds(settings, kind):
    """How often the scan ("scan") or resync ("sync") runs, in seconds."""
    try:
        seconds = float(settings[f"{kind}_every"]) * UNITS.get(settings[f"{kind}_unit"], 3600)
    except (KeyError, TypeError, ValueError):
        seconds = 0
    return min(MAX_INTERVAL, max(MIN_INTERVAL[kind], seconds))


def save_state(data):
    atomic_write(STATE_FILE, json.dumps(data, indent=2))


def update_state(**changes):
    with csv_lock:
        data = load_state()
        data.update(changes)
        save_state(data)
        return data


def atomic_write(path, text):
    folder = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


# ---------------------------------------------------------------- mapping model

def read_raw():
    """The saved mapping as text (JSON), "" if there is none."""
    try:
        with open(MAPPING_FILE, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def version_of(raw):
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def empty_mapping():
    return {"key_header": "Folder", "frontends": [], "rows": []}


def parse_mapping(raw):
    """Saved JSON -> {key_header, frontends: [{name, media_toggle, media_location}], rows: [{folder, values}]}"""
    if not raw.strip():
        return empty_mapping()
    data = json.loads(raw)
    fes = [{"name": str(f.get("name") or ""), "media_toggle": "1" if str(f.get("media_toggle")) == "1" else "0",
            "media_location": str(f.get("media_location") or "")} for f in data.get("frontends") or []]
    rows = []
    for r in data.get("rows") or []:
        vals = [str(v or "") for v in r.get("values") or []]
        rows.append({"folder": str(r.get("folder") or ""), "values": (vals + [""] * len(fes))[:len(fes)]})
    return {"key_header": data.get("key_header") or "Folder", "frontends": fes, "rows": rows}


def write_mapping(m):
    text = json.dumps({"key_header": m.get("key_header") or "Folder", "frontends": m["frontends"],
                       "rows": [{"folder": r["folder"], "values": r["values"]} for r in m["rows"]]},
                      ensure_ascii=False, indent=1)
    if os.path.exists(MAPPING_FILE):
        shutil.copy2(MAPPING_FILE, MAPPING_FILE + ".bak")
    atomic_write(MAPPING_FILE, text)
    return version_of(text)


def bad_path_part(value, allow_slash):
    """Return an error string if value would be unsafe/unparseable, else None."""
    if "," in value:
        return "cannot contain a comma"
    if "\\" in value or "\n" in value or "\r" in value:
        return "contains an invalid character"
    if not allow_slash and "/" in value:
        return "cannot contain '/'"
    if value.startswith("/"):
        return "cannot start with '/'"
    if any(p in ("..", ".") for p in value.split("/")):
        return "cannot contain '.' or '..' path segments"
    return None


def validate_mapping(m):
    errors = []
    fes = m.get("frontends") or []
    seen = set()
    for f in fes:
        name = (f.get("name") or "").strip()
        f["name"] = name
        f["media_toggle"] = "1" if str(f.get("media_toggle")) in ("1", "true", "True") else "0"
        f["media_location"] = (f.get("media_location") or "").strip()
        if not name:
            errors.append("A frontend column has no name.")
        elif err := bad_path_part(name, allow_slash=False):
            errors.append(f"Frontend '{name}' {err}.")
        if name in seen:
            errors.append(f"Frontend '{name}' appears twice.")
        seen.add(name)
        if f["media_location"] and (err := bad_path_part(f["media_location"], allow_slash=True)):
            errors.append(f"Media location for '{name}' {err}.")

    seen = set()
    for r in m.get("rows") or []:
        folder = r.get("folder") or ""
        if not folder.strip():
            errors.append("A row has no folder name.")
            continue
        if err := bad_path_part(folder, allow_slash=True):
            errors.append(f"Folder '{folder}' {err}.")
        if folder in seen:
            errors.append(f"Folder '{folder}' appears twice.")
        seen.add(folder)
        vals = [(v or "").strip() for v in (r.get("values") or [])]
        vals = (vals + [""] * len(fes))[: len(fes)]
        r["values"] = vals
        for fe, v in zip(fes, vals):
            if v and (err := bad_path_part(v, allow_slash=True)):
                errors.append(f"{folder} → {fe['name']}: '{v}' {err}.")
    return errors


# ---------------------------------------------------------------- scanning

SKIP_DIRS = {"media"}               # linked through the frontend's "link media/ folders" option


def clean_label(text):
    out = "".join(c for c in text if c not in "/\\=;,:\n\r").strip() or "roms"
    return out


def get_sources(settings=None):
    """The grid's source folders in order: [{"path", "label", "depth"}]. Without a saved list:
    SRC_BASE (several separated by ";"), looked at one level deep - the original behaviour."""
    settings = settings or load_state()["settings"]
    src = [dict(x) for x in settings.get("sources") or [] if x.get("path")]
    if not src:
        labels = set()
        for path in [p.strip().rstrip("/") for p in SRC_BASE.split(";") if p.strip()]:
            label = unique_label(clean_label(os.path.basename(path)), labels)
            labels.add(label)
            src.append({"path": path, "label": label, "depth": 1})
    for x in src:
        x["depth"] = max(1, min(6, int(x.get("depth") or 1)))
    return src


def unique_label(label, taken):
    if label not in taken:
        return label
    n = 2
    while f"{label}-{n}" in taken:
        n += 1
    return f"{label}-{n}"


def split_key(key, sources):
    """Row key -> (source, path inside it). "lolroms/Nintendo/Super Famicom" -> the
    lolroms source; a key without a known label belongs to the first source (older data)."""
    head, _, rest = key.partition("/")
    for x in sources:
        if x["label"] == head:
            return x, rest
    return (sources[0] if sources else None), key


def key_path(key, sources):
    src, rest = split_key(key, sources)
    if src is None:
        return None
    return os.path.join(src["path"], rest) if rest else src["path"]


def full_key(key, sources):
    """Show and save every row with its source's label in front."""
    src, rest = split_key(key, sources)
    if src is None:
        return key
    return f"{src['label']}/{rest}" if rest else src["label"]


_folders_cache = {"key": None, "at": 0.0, "value": None}


def list_source_folders(sources=None, fresh=True):
    """Every folder in the source folders down to each one's depth, as "label/path" keys.
    Raises RuntimeError naming the first source folder that isn't there. The page refreshes every
    30 s; with fresh=False a result up to 10 s old is reused instead of reading the disk again."""
    sources = sources if sources is not None else get_sources()
    key = tuple((x["path"], x["label"], x["depth"]) for x in sources)
    c = _folders_cache
    if not fresh and c["key"] == key and time.time() - c["at"] < 10:
        return list(c["value"])
    value = _list_source_folders(sources)
    c.update(key=key, at=time.time(), value=value)
    return list(value)


def _list_source_folders(sources):
    if not sources:
        raise RuntimeError("No source folder is set - add one under Source folders.")
    out = []
    for src in sources:
        base = src["path"]
        if not os.path.isdir(base):
            raise RuntimeError(f"Source folder not found: {base} (is it inside the folder mounted into the container?)")

        def walk(path, rel, depth):
            try:
                entries = sorted(os.scandir(path), key=lambda e: e.name.lower())
            except OSError:
                return
            for e in entries:
                if e.name.startswith(".") or e.name.lower() in SKIP_DIRS:
                    continue
                try:
                    if e.is_symlink() or not e.is_dir():
                        continue
                except OSError:
                    continue
                r = f"{rel}/{e.name}" if rel else e.name
                out.append(f"{src['label']}/{r}")
                if depth > 1:
                    walk(e.path, r, depth - 1)
        walk(base, "", src["depth"])
    return out


def build_view():
    """Mapping merged with what's on disk, with a status per row."""
    with csv_lock:
        raw = read_raw()
        m = parse_mapping(raw)
        state = load_state()
    sources = get_sources(state["settings"])
    disk_error = None
    try:
        disk = list_source_folders(sources, fresh=False)
    except RuntimeError as e:
        disk, disk_error = [], str(e)
    for r in m["rows"]:
        r["folder"] = full_key(r["folder"], sources)
    in_mapping = {r["folder"] for r in m["rows"]}

    for r in m["rows"]:
        path = key_path(r["folder"], sources)
        if not disk_error and not (path and os.path.isdir(path)):
            r["status"] = "missing"
        elif any(r["values"]):
            r["status"] = "mapped"
        else:
            r["status"] = "unmapped"
    for name in disk:
        if name not in in_mapping and not bad_path_part(name, allow_slash=True):
            m["rows"].append({"folder": name, "values": [""] * len(m["frontends"]), "status": "new"})

    return {
        **m,
        "app_version": __version__,
        "version": version_of(raw),
        "disk_error": disk_error,
        "paths": {"store": MAPPING_FILE, "src": "; ".join(x["path"] for x in sources), "dest": DEST_PATH},
        "sources": sources,
        "settings": state["settings"],
        "last_scan": state["last_scan"],
        "last_sync": state["last_sync"],
        "sync_running": sync_lock.locked(),
    }


def run_scan(trigger):
    with csv_lock:
        raw = read_raw()
        m = parse_mapping(raw)
        settings = load_state()["settings"]
        sources = get_sources(settings)
        try:
            disk = list_source_folders(sources)
        except RuntimeError as e:
            log(f"Scan ({trigger}) failed: {e}")
            result = {"time": now_iso(), "ok": False, "error": str(e), "new": [], "missing": [], "added": 0}
            update_state(last_scan=result)
            return result

        for r in m["rows"]:
            r["folder"] = full_key(r["folder"], sources)
        in_mapping = {r["folder"] for r in m["rows"]}
        unsupported = [d for d in disk if bad_path_part(d, allow_slash=True)]
        new = [d for d in disk if d not in in_mapping and d not in unsupported]
        missing = [r["folder"] for r in m["rows"]
                   if not os.path.isdir(key_path(r["folder"], sources) or "/nonexistent")]

        added = 0
        if new and settings["auto_add_new"]:
            for name in new:
                m["rows"].append({"folder": name, "values": [""] * len(m["frontends"])})
            write_mapping(m)
            added = len(new)

        result = {
            "time": now_iso(), "ok": True, "new": new, "missing": missing,
            "added": added, "unsupported": unsupported, "total": len(disk),
        }
        update_state(last_scan=result)

    parts = [f"{len(disk)} folders"]
    if new:
        parts.append(f"{len(new)} new" + (f" (added {added})" if added else ""))
    if missing:
        parts.append(f"{len(missing)} missing on disk")
    if unsupported:
        parts.append(f"{len(unsupported)} skipped (comma in name)")
    log(f"Scan ({trigger}): " + ", ".join(parts))
    return result


# ---------------------------------------------------------------- syncing

def run_sync(trigger):
    """Bring the mapping folder in line with the saved mapping (links.py). Caller holds sync_lock."""
    started = time.time()
    log(f"Resync started ({trigger})")
    with csv_lock:
        m = parse_mapping(read_raw())
    sources = get_sources()
    lines = []
    try:
        problem = links.check_dest(DEST_PATH, [x["path"] for x in sources])
        if problem:
            raise RuntimeError(problem)
        want, notes = links.desired_links(m, DEST_PATH, lambda key: key_path(key, sources))
        res = links.apply(want, DEST_PATH)
        ok = True
        lines.append(links.describe(res))
        lines += notes + res["problems"]
    except Exception as e:  # noqa: BLE001 - surface anything to the UI
        ok = False
        lines.append(f"{type(e).__name__}: {e}" if not isinstance(e, RuntimeError) else str(e))
    output = "\n".join(lines)
    result = {
        "time": now_iso(), "ok": ok, "trigger": trigger,
        "seconds": round(time.time() - started, 1),
        "output": output[-4000:],
    }
    update_state(last_sync=result)
    log(f"Resync {'finished' if ok else 'FAILED'} in {result['seconds']}s ({trigger}): {lines[0] if lines else ''}")
    return result


def start_sync_async(trigger):
    if not sync_lock.acquire(blocking=False):
        return False

    def worker():
        try:
            run_sync(trigger)
        finally:
            sync_lock.release()

    threading.Thread(target=worker, daemon=True).start()
    return True


# ---------------------------------------------------------------- RomM

_romm_cache = {"key": None, "at": 0.0, "folders": None}


def romm_saved():
    """romm-mapper.json, converted from the one-folder format (Rom Sync's, and the first version
    here): "source" -> "sources", and folder choices get the folder's name in front
    ("Konami - Picno" -> "lolroms/Konami - Picno")."""
    cur = romm.read_backup(CONFIG_DIR)
    if "sources" in cur:
        return cur
    old = (cur.pop("source", "") or "").rstrip("/")
    env = [p.strip().rstrip("/") for p in ROMM_SOURCE.split(";") if p.strip()]
    sources = [old] if old else env
    if cur.get("links_dir") and not os.path.isabs(cur["links_dir"]):
        cur.pop("links_dir")
    if cur.get("map") and sources:
        root = os.path.relpath(sources[0], romm_links_dir(cur, sources))
        cur["map"] = {(f"{root}/{k}" if k else root): v for k, v in cur["map"].items()}
    cur["sources"] = sources
    if cur.get("map") or old:
        romm_save(cur)
    return cur


def romm_save(cur):
    # The folder cache is NOT reset here: its key (romm_setup) holds everything that changes which
    # folders are read, so a platform choice or an option reuses it instead of re-reading the disk.
    atomic_write(os.path.join(CONFIG_DIR, romm.BACKUP_FILE),
                 json.dumps(cur, ensure_ascii=False, indent=1, sort_keys=True))


def romm_links_dir(saved, sources):
    """Where the platform links go: the setting, else the folder that holds all download folders."""
    if saved.get("links_dir"):
        return saved["links_dir"]
    if not sources:
        return ""
    return os.path.commonpath([os.path.dirname(os.path.abspath(p)) for p in sources])


def romm_check(sources, links_dir):
    """Problems that stop the RomM section from working, or None."""
    if not sources:
        return "Add a download folder first."
    for p in sources:
        if not os.path.isdir(p):
            return f"Folder not found: {p} (is it mounted into the container at the same path?)"
        r = os.path.relpath(p, links_dir)
        if r == "." or r.startswith(".."):
            return f"{p} is not inside the links folder {links_dir} - change the links folder."
    for a in sources:
        for b in sources:
            if a != b and (b + "/").startswith(a + "/"):
                return f"{b} is inside {a} - list only one of them."
    names = [os.path.relpath(p, links_dir) for p in sources]
    if len(set(names)) != len(names):
        return "The same folder is listed twice."
    return None


FULL_READ_EVERY = 3600     # s; between full reads only folders whose date changed are listed


ROMM_BACKGROUND = True     # read the download folders in the background (tests turn it off)
romm_read_lock = threading.Lock()   # one read of the download folders at a time
romm_job_lock = threading.Lock()    # held while a background read runs
_romm_read = {"error": None, "source": 0, "sources": 0, "path": "", "done": 0, "total": 0, "current": ""}


def romm_setup(saved):
    """-> (download folders, links folder, {folder: levels}, cache key)."""
    sources = [p.rstrip("/") for p in saved.get("sources") or []]
    links_dir = romm_links_dir(saved, sources)
    stored = saved.get("depths") or {}
    depths = {p: int(stored[p]) for p in sources if int(stored.get(p) or 0)}
    skip = tuple(romm.options_from({"romm": saved})["skip_names"])
    return sources, links_dir, depths, skip, (tuple(sources), links_dir, tuple(sorted(depths.items())), skip)


def romm_mapping(fresh=False, progress=None, reuse=False, quick=False):
    """-> (Mapping or None, saved settings, error). Folder counts are reused for 30 s; after that
    only folders whose date changed are listed again. fresh=True (Refresh button, new download
    folders) or an hour since the last full read lists every folder again - on some shares (e.g.
    Unraid's, spread over several disks) a folder's date doesn't always change. reuse=True (a
    platform choice or an option: nothing on disk changed) takes the folder list as it is; quick=True
    re-checks the folders' dates now, however recent the last read (Create / update links now)."""
    saved = romm_saved()
    sources, links_dir, depths, skip, key = romm_setup(saved)
    error = romm_check(sources, links_dir)
    if error:
        return None, saved, error
    with romm_read_lock:
        c = _romm_cache
        now = time.time()
        have = c["key"] == key and c.get("folders") is not None
        full = fresh or not have or (now - c.get("full_at", 0) > FULL_READ_EVERY and not reuse)
        if full or quick or (now - c["at"] > 30 and not reuse):
            folders = romm.folders_from_roots(links_dir, sources, full=full, depths=depths, progress=progress,
                                              skip=skip, stop=romm_stops(saved))
            # stamped when the read ends: on a big share it takes minutes, and a stamp from its start
            # made the very next request re-check every folder while the page still waited
            c.update(key=key, at=time.time(), folders=folders)
            if full:
                c["full_at"] = c["at"]
        folders, roots = c["folders"]
    return romm.Mapping(folders, romm.options_from({"romm": saved}), links_dir, roots), saved, None


def romm_stops(saved):
    """Folders you excluded, with no choice of yours below them: the read doesn't go inside them
    (an exclude covers everything inside, so there's nothing to list - eXoDOS's thousands of game
    folders are not read at all). Paths are relative to the links folder, like the choices."""
    choices = saved.get("map") or {}
    excluded = [p for p, a in choices.items() if a == "exclude"]
    return {p for p in excluded if not any(k.startswith(p + "/") for k in choices)}


def romm_read_due(saved, fresh=False, reuse=False):
    """Would romm_mapping touch the disk - a full read, or the quick re-check after 30 s? Either can
    take a while on a big share (a stat per folder), so the page gets it in the background."""
    sources, links_dir, _depths, _skip, key = romm_setup(saved)
    if romm_check(sources, links_dir):
        return False
    c = _romm_cache
    if fresh or c["key"] != key or c.get("folders") is None:
        return True
    if reuse:
        return False
    now = time.time()
    return now - c.get("full_at", 0) > FULL_READ_EVERY or now - c["at"] > 30


def romm_progress():
    return {**_romm_read, "running": romm_job_lock.locked()}


def start_romm_read(fresh=True):
    """Read every download folder in a background thread; the page follows /api/romm/progress.
    False if a read is already running."""
    if not romm_job_lock.acquire(blocking=False):
        return False
    sources = [p.rstrip("/") for p in romm_saved().get("sources") or []]
    _romm_read.update(error=None, source=0, sources=len(sources), path=sources[0] if sources else "",
                      done=0, total=0, current="")

    def progress(i, n, done, total, current):
        _romm_read.update(source=i, sources=n, path=sources[i] if i < len(sources) else "",
                          done=done, total=total, current=current)

    def worker():
        try:
            romm_mapping(fresh=fresh, progress=progress)
        except Exception as e:  # noqa: BLE001 - shown on the page
            _romm_read["error"] = str(e)
            log(f"RomM: reading the download folders failed: {e}")
        finally:
            romm_job_lock.release()

    threading.Thread(target=worker, daemon=True).start()
    return True


def romm_groups(m, rows):
    """Folders inside a download folder that hold no files themselves but have rows below them
    (exodos/eXo/eXoDOS): the page shows them as the tree's branches, and a choice on one (exclude)
    covers everything inside it."""
    have = {r["path"] for r in rows}
    out = {}
    for r in rows:
        p = r["path"]
        while "/" in p:
            p = p.rsplit("/", 1)[0]
            if p in have or p in out:
                break
            res = m.res.get(p)
            root = m.root_of(p)
            if res is None or root is None or root == p:
                break
            out[p] = {"path": p, "group": True, "files": 0, "kind": res["kind"], "slug": res["slug"],
                      "value": m.choice(res), "auto": m.choice(m.auto.get(p, res)), "root": root,
                      "action": m.user.get(p, ""), "excluded_by": res.get("excluded_by")}
    return sorted(out.values(), key=lambda g: g["path"].casefold())


def romm_view(fresh=False, reuse=False):
    saved = romm_saved()
    opt = romm.options_from({"romm": saved})
    sources = saved.get("sources") or []
    base = {"sources": sources, "depths": romm_setup(saved)[2], "error": None,
            "links_dir": romm_links_dir(saved, sources),
            "options": {"skip_names": opt["skip_names"]}}
    if ROMM_BACKGROUND and (romm_job_lock.locked() or romm_read_due(saved, fresh, reuse)):
        start_romm_read(fresh=fresh)
        return {**base, "reading": romm_progress()}
    m, saved, error = romm_mapping(fresh, reuse=reuse)
    base["error"] = error
    if m is None:
        return {**base, "rows": [], "platforms": [], "firmware": [], "warnings": [], "summary":
                {"platforms": 0, "firmware": 0, "files": 0}, "links": {}, "old_links": 0, "outputs": {"config": ""}}
    rows = m.rows()
    return {**base,
            "links": {"roots": m.roots}, "old_links": romm.old_links(m),
            "rows": rows, "groups": romm_groups(m, rows), "platforms": m.platforms, "firmware": m.firmware,
            "warnings": m.warnings(), "summary": m.summary(), "outputs": {"config": m.config_yml()}}


def romm_remove_old_links(trigger):
    """Remove the platform links older versions made (RomM reads the folders by name now). Only
    links pointing into a download folder are touched."""
    with romm_lock:
        m, _saved, error = romm_mapping(reuse=True)
        if m is None:
            raise RuntimeError(error)
        res = romm.apply_links(m)
    text = romm.describe_links(res)
    if trigger != "scheduled" or res["created"] or res["updated"] or res["removed"] or res["errors"]:
        log(f"{text} ({trigger})")
    return res, text


# ---------------------------------------------------------------- scheduler

def parse_iso(ts):
    try:
        return datetime.fromisoformat(ts).timestamp()
    except (TypeError, ValueError):
        return 0.0


def scheduler_loop():
    while True:
        try:
            state = load_state()
            s = state["settings"]
            now = time.time()
            last_scan = parse_iso((state["last_scan"] or {}).get("time"))
            last_sync = parse_iso((state["last_sync"] or {}).get("time"))
            if s["scan_enabled"] and now - last_scan >= interval_seconds(s, "scan"):
                run_scan("scheduled")
            if s["sync_enabled"] and now - last_sync >= interval_seconds(s, "sync"):
                start_sync_async("scheduled")
        except Exception as e:  # noqa: BLE001 - never let the scheduler die
            log(f"Scheduler error: {e}")
        time.sleep(30)


# ---------------------------------------------------------------- routes

@app.after_request
def compress(resp):
    """gzip large JSON answers when the browser accepts it: the RomM list of a big share is
    several MB of JSON and shrinks to a fraction of that."""
    if (resp.status_code == 200 and resp.mimetype == "application/json" and not resp.direct_passthrough
            and "gzip" in request.headers.get("Accept-Encoding", "")
            and "Content-Encoding" not in resp.headers and (resp.content_length or 0) > 4096):
        resp.set_data(gzip.compress(resp.get_data(), compresslevel=5))
        resp.headers["Content-Encoding"] = "gzip"
        resp.headers.add("Vary", "Accept-Encoding")
    return resp


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/state")
def api_state():
    return jsonify(build_view())


@app.put("/api/mapping")
def api_save():
    body = request.get_json(force=True)
    m = {
        "key_header": "Folder",
        "frontends": body.get("frontends") or [],
        "rows": [{"folder": r.get("folder", ""), "values": r.get("values", [])} for r in body.get("rows") or []],
    }
    errors = validate_mapping(m)
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 400

    with csv_lock:
        raw = read_raw()
        current = parse_mapping(raw)
        if body.get("version") != version_of(raw) and not body.get("force"):
            return jsonify({"error": "conflict",
                            "details": ["The mapping changed since you loaded it (e.g. a scheduled scan added folders)."]}), 409
        m["key_header"] = current["key_header"]
        version = write_mapping(m)
    log(f"Mapping saved: {len(m['rows'])} folders × {len(m['frontends'])} frontends")

    synced = start_sync_async("after save") if body.get("resync") else False
    return jsonify({"ok": True, "version": version, "sync_started": synced})


@app.post("/api/scan")
def api_scan():
    return jsonify(run_scan("manual"))


@app.post("/api/sync")
def api_sync():
    if not start_sync_async("manual"):
        return jsonify({"error": "A resync is already running."}), 409
    return jsonify({"ok": True})


@app.get("/api/sync")
def api_sync_status():
    return jsonify({"running": sync_lock.locked(), "last_sync": load_state()["last_sync"]})


@app.put("/api/settings")
def api_settings():
    body = request.get_json(force=True)
    s = dict(DEFAULT_SETTINGS)
    s["sources"] = load_state()["settings"].get("sources") or []
    body = convert_schedule(dict(body))          # older pages send the old field names
    s["scan_enabled"] = bool(body.get("scan_enabled"))
    s["auto_add_new"] = bool(body.get("auto_add_new"))
    s["sync_enabled"] = bool(body.get("sync_enabled"))
    for kind, what in (("scan", "Scan"), ("sync", "Resync")):
        unit = body.get(f"{kind}_unit")
        if unit not in UNITS:
            return jsonify({"error": f"{what}: the unit must be minutes, hours or days."}), 400
        try:
            every = int(body.get(f"{kind}_every"))
        except (TypeError, ValueError):
            return jsonify({"error": f"{what}: the interval must be a whole number."}), 400
        seconds = every * UNITS[unit]
        if seconds < MIN_INTERVAL[kind]:
            return jsonify({"error": f"{what}: the shortest interval is {MIN_INTERVAL[kind] // 60} minute(s)."}), 400
        if seconds > MAX_INTERVAL:
            return jsonify({"error": f"{what}: the longest interval is 365 days."}), 400
        s[f"{kind}_every"], s[f"{kind}_unit"] = every, unit
    update_state(settings=s)
    log("Schedule settings updated")
    return jsonify({"ok": True, "settings": s})


@app.get("/api/romm")
def api_romm():
    return jsonify(romm_view(fresh=request.args.get("fresh") == "1"))


@app.get("/api/romm/progress")
def api_romm_progress():
    """How far the background read of the download folders is (the page polls it)."""
    return jsonify(romm_progress())


@app.get("/api/romm/platforms")
def api_romm_platforms():
    """RomM's platform list. It only changes with a new version, so the page loads it once."""
    slugs = [{"slug": k, "name": v[0], "family": v[1], "kind": v[2]} for k, v in sorted(romm.PLATFORMS.items())]
    return jsonify({"slugs": slugs})


@app.put("/api/romm/options")
def api_romm_options():
    body = request.get_json(force=True) or {}
    with romm_lock:
        cur = romm_saved()
        if "sources" in body:
            sources = []
            for v in body["sources"] or []:
                v = str(v or "").strip().rstrip("/")
                if not v:
                    continue
                if not v.startswith("/"):
                    return jsonify({"error": f"{v}: a download folder must be a full path starting with /"}), 400
                if v not in sources:
                    sources.append(v)
            cur["sources"] = sources
        if "depths" in body:
            depths = {}
            for k, v in (body["depths"] or {}).items():
                try:
                    n = int(v or 0)
                except (TypeError, ValueError):
                    n = -1
                if not 0 <= n <= 6:
                    return jsonify({"error": "Levels must be All or a number from 1 to 6."}), 400
                if n:
                    depths[str(k).strip().rstrip("/")] = n
            cur["depths"] = depths
        if "skip_names" in body:
            raw = body["skip_names"]
            items = raw.split(",") if isinstance(raw, str) else list(raw or [])
            names = []
            for n in items:
                n = str(n or "").strip()
                if not n:
                    continue
                if "/" in n or "\\" in n:
                    return jsonify({"error": f"{n}: give folder names (like media), not paths."}), 400
                if n.casefold() not in {x.casefold() for x in names}:
                    names.append(n)
            cur["skip_names"] = names
        if cur.get("depths"):                 # only folders still in the list
            cur["depths"] = {k: v for k, v in cur["depths"].items() if k in (cur.get("sources") or [])}
        romm_save(cur)
    folders = any(k in body for k in ("sources", "depths", "skip_names"))
    return jsonify(romm_view(fresh=folders, reuse=not folders))


@app.put("/api/romm/map")
def api_romm_map():
    body = request.get_json(force=True) or {}
    path = str(body.get("path") or "")
    try:
        action = romm.check_action(str(body.get("action") or ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    with romm_lock:
        cur = romm_saved()
        mapping = dict(cur.get("map") or {})
        if action:
            mapping[path] = action
        else:
            mapping.pop(path, None)
        cur["map"] = mapping
        romm_save(cur)
    return jsonify(romm_view(reuse=True))


@app.post("/api/romm/links")
def api_romm_links():
    """Remove the platform links older versions made."""
    try:
        res, text = romm_remove_old_links("manual")
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({**romm_view(reuse=True), "applied": {**res, "text": text}})


@app.put("/api/sources")
def api_sources():
    """Save the grid's source folders: [{"path", "depth", "label"?}] in order."""
    body = request.get_json(force=True) or {}
    current = {x["path"]: x for x in get_sources()}
    out, labels = [], set()
    for x in body.get("sources") or []:
        path = str(x.get("path") or "").strip().rstrip("/")
        if not path:
            continue
        if not path.startswith("/"):
            return jsonify({"error": f"{path}: a source folder must be a full path starting with /"}), 400
        if any(o["path"] == path for o in out):
            continue
        try:
            depth = max(1, min(6, int(x.get("depth") or 1)))
        except (TypeError, ValueError):
            return jsonify({"error": "Depth must be a number from 1 to 6."}), 400
        # a folder keeps its label (the mapping refers to it); new ones get their folder name
        label = (current.get(path) or {}).get("label") or clean_label(os.path.basename(path))
        label = unique_label(label, labels)
        labels.add(label)
        out.append({"path": path, "label": label, "depth": depth})
    for a in out:
        for b in out:
            if a is not b and (b["path"] + "/").startswith(a["path"] + "/"):
                return jsonify({"error": f"{b['path']} is inside {a['path']} - raise the depth of "
                                         f"{a['path']} instead of listing both."}), 400
    with csv_lock:
        state = load_state()
        old = get_sources(state["settings"])
        # rows written without a label belonged to the first folder: keep them pointing there
        raw = read_raw()
        m = parse_mapping(raw)
        if m["rows"] and old and (not out or old[0]["path"] != out[0]["path"]):
            for r in m["rows"]:
                r["folder"] = full_key(r["folder"], old)
            write_mapping(m)
        state["settings"]["sources"] = out
        save_state(state)
    log("Source folders: " + (", ".join(f"{x['path']} ({x['depth']} deep)" for x in out) or "none"))
    return jsonify({"ok": True, "sources": get_sources()})


@app.get("/api/activity")
def api_activity():
    return jsonify(list(activity))


def main():
    import sys
    if "--resync" in sys.argv[1:]:          # one-off rebuild without the UI (docker exec ...)
        result = run_sync("command line")
        print(result["output"])
        raise SystemExit(0 if result["ok"] else 1)
    from waitress import serve

    log(f"Starting rom-mapper {__version__} on port {PORT} (mapping={MAPPING_FILE}, src={SRC_BASE}, dest={DEST_PATH})")
    threading.Thread(target=scheduler_loop, daemon=True).start()
    serve(app, host="0.0.0.0", port=PORT, threads=8)


if __name__ == "__main__":
    main()
