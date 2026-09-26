"""rom-mapper web UI.

Reads/writes the same Rom_Mapping.csv the rom-mapper.sh script uses, scans the
ROM source folder for new/removed folders, and runs the sync script on demand
or on a schedule.

RomM (romm.py): maps a lolroms download folder (nested, e.g. Nintendo/Super Famicom) to RomM
platforms with relative platform links next to it plus a generated config.yml. Settings and folder
choices live in romm-mapper.json next to the CSV - the same file Rom Sync used.
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_from_directory

import romm

# --- CONFIGURATION (environment variables) ---
INPUT_CSV = os.environ.get("INPUT_CSV", "/config/Rom_Mapping.csv")
SRC_BASE = os.environ.get("SRC_BASE", "/path/to/roms")
DEST_PATH = os.environ.get("DEST_PATH", "/path/to/mapping")
STATE_FILE = os.environ.get(
    "STATE_FILE", os.path.join(os.path.dirname(INPUT_CSV), "rom-mapper-state.json")
)
SYNC_SCRIPT = os.environ.get("SYNC_SCRIPT", "/usr/local/bin/rom-mapper.sh")
BASH_BIN = os.environ.get("BASH_BIN") or shutil.which("bash") or "bash"
PORT = int(os.environ.get("PORT", "8085"))
# RomM: the download folder(s) to map (e.g. Rom Sync's lolroms folder), mounted at the same path as
# on the host; several separated by ";" (first = preferred when two give the same platform).
# Can also be set in the UI; "" = RomM section not set up yet.
ROMM_SOURCE = os.environ.get("ROMM_SOURCE", "")
CONFIG_DIR = os.path.dirname(INPUT_CSV) or "."
# ----------------------------------------------

TOGGLE_ROW = "Media Toggle"
LOCATION_ROW = "Media Location"
RESERVED = {TOGGLE_ROW, LOCATION_ROW}

DEFAULT_SETTINGS = {
    # source folders for the mapping grid: [{"path", "label", "depth"}]; [] = SRC_BASE (one level)
    "sources": [],
    "scan_enabled": True,
    "scan_interval_minutes": 60,
    "auto_add_new": True,
    "sync_enabled": False,
    "sync_interval_hours": 24,
}

app = Flask(__name__, static_folder="static", static_url_path="/static")

csv_lock = threading.RLock()      # guards reads/writes of the CSV and state file
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
    data["settings"] = {**DEFAULT_SETTINGS, **data.get("settings", {})}
    data.setdefault("last_scan", None)
    data.setdefault("last_sync", None)
    return data


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


# ---------------------------------------------------------------- CSV model
#
# The CSV is deliberately parsed the same naive way rom-mapper.sh does
# (split on commas, no quoting), so anything the UI writes the script reads.

def read_raw():
    try:
        with open(INPUT_CSV, encoding="utf-8-sig") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def version_of(raw):
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def parse_mapping(raw):
    lines = [l.rstrip("\r") for l in raw.split("\n")]
    if not lines or not lines[0].strip():
        return {"key_header": "Folder", "frontends": [], "rows": []}

    header = lines[0].split(",")
    names = header[1:]
    toggles, locations, rows = {}, {}, []

    for line in lines[1:]:
        fields = line.split(",")
        folder = fields[0]
        if not folder.strip():
            continue
        vals = [(fields[i + 1] if i + 1 < len(fields) else "").strip() for i in range(len(names))]
        if folder == TOGGLE_ROW:
            toggles = dict(zip(names, vals))
        elif folder == LOCATION_ROW:
            locations = dict(zip(names, vals))
        else:
            rows.append({"folder": folder, "values": vals})

    frontends = [
        {
            "name": n,
            "media_toggle": "1" if toggles.get(n, "0") == "1" else "0",
            "media_location": locations.get(n, ""),
        }
        for n in names
    ]
    return {"key_header": header[0] or "Folder", "frontends": frontends, "rows": rows}


def serialize_mapping(m):
    fes = m["frontends"]
    out = [",".join([m.get("key_header") or "Folder"] + [f["name"] for f in fes])]
    out.append(",".join([TOGGLE_ROW] + [f["media_toggle"] for f in fes]))
    out.append(",".join([LOCATION_ROW] + [f["media_location"] for f in fes]))
    for r in m["rows"]:
        out.append(",".join([r["folder"]] + r["values"]))
    return "\n".join(out) + "\n"


def write_mapping(m):
    text = serialize_mapping(m)
    if os.path.exists(INPUT_CSV):
        shutil.copy2(INPUT_CSV, INPUT_CSV + ".bak")
    atomic_write(INPUT_CSV, text)
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
        if folder in RESERVED:
            errors.append(f"'{folder}' is a reserved row name.")
        elif err := bad_path_part(folder, allow_slash=True):
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


def sources_env(sources):
    """For rom-mapper.sh: "label=path;label=path" (first = where folders without a label are)."""
    return ";".join(f"{x['label']}={x['path']}" for x in sources)


def split_key(key, sources):
    """CSV folder column -> (source, path inside it). "lolroms/Nintendo/Super Famicom" -> the
    lolroms source; a key without a known label belongs to the first source (older CSVs)."""
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


def list_source_folders(sources=None):
    """Every folder in the source folders down to each one's depth, as "label/path" keys.
    Raises RuntimeError naming the first source folder that isn't there."""
    sources = sources if sources is not None else get_sources()
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
        disk = list_source_folders(sources)
    except RuntimeError as e:
        disk, disk_error = [], str(e)
    for r in m["rows"]:
        r["folder"] = full_key(r["folder"], sources)
    in_csv = {r["folder"] for r in m["rows"]}

    for r in m["rows"]:
        path = key_path(r["folder"], sources)
        if not disk_error and not (path and os.path.isdir(path)):
            r["status"] = "missing"
        elif any(r["values"]):
            r["status"] = "mapped"
        else:
            r["status"] = "unmapped"
    for name in disk:
        if name not in in_csv and not bad_path_part(name, allow_slash=True):
            m["rows"].append({"folder": name, "values": [""] * len(m["frontends"]), "status": "new"})

    return {
        **m,
        "version": version_of(raw),
        "disk_error": disk_error,
        "paths": {"csv": INPUT_CSV, "src": "; ".join(x["path"] for x in sources), "dest": DEST_PATH},
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
        in_csv = {r["folder"] for r in m["rows"]}
        unsupported = [d for d in disk if bad_path_part(d, allow_slash=True)]
        new = [d for d in disk if d not in in_csv and d not in unsupported]
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
    """Run rom-mapper.sh against a snapshot of the CSV. Caller holds sync_lock."""
    started = time.time()
    log(f"Resync started ({trigger})")
    with csv_lock:
        raw = read_raw()
    fd, snapshot = tempfile.mkstemp(prefix="rom-mapping-", suffix=".csv")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(raw)
    try:
        sources = get_sources()
        env = {**os.environ, "INPUT_CSV": snapshot, "SRC_BASE": sources[0]["path"] if sources else SRC_BASE,
               "SOURCES": sources_env(sources), "DEST_PATH": DEST_PATH}
        proc = subprocess.run(
            [BASH_BIN, SYNC_SCRIPT], env=env, capture_output=True, text=True, timeout=3600
        )
        ok = proc.returncode == 0
        output = (proc.stdout + proc.stderr).strip()
    except Exception as e:  # noqa: BLE001 - surface anything to the UI
        ok, output = False, f"{type(e).__name__}: {e}"
    finally:
        os.remove(snapshot)

    result = {
        "time": now_iso(), "ok": ok, "trigger": trigger,
        "seconds": round(time.time() - started, 1),
        "output": output[-4000:],
    }
    update_state(last_sync=result)
    log(f"Resync {'finished' if ok else 'FAILED'} in {result['seconds']}s ({trigger})")
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
        root = os.path.relpath(sources[0], romm_links_dir(cur, sources)).replace(os.sep, "/")
        cur["map"] = {(f"{root}/{k}" if k else root): v for k, v in cur["map"].items()}
    cur["sources"] = sources
    if cur.get("map") or old:
        romm_save(cur)
    return cur


def romm_save(cur):
    atomic_write(os.path.join(CONFIG_DIR, romm.BACKUP_FILE),
                 json.dumps(cur, ensure_ascii=False, indent=1, sort_keys=True))
    _romm_cache["key"] = None


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


def romm_mapping(fresh=False):
    """-> (Mapping or None, saved settings, error). Folder counts are cached for 30 s (walking a
    big library takes a moment)."""
    saved = romm_saved()
    sources = [p.rstrip("/") for p in saved.get("sources") or []]
    links_dir = romm_links_dir(saved, sources)
    error = romm_check(sources, links_dir)
    if error:
        return None, saved, error
    c = _romm_cache
    key = (tuple(sources), links_dir)
    if fresh or c["key"] != key or time.time() - c["at"] > 30:
        c.update(key=key, at=time.time(), folders=romm.folders_from_roots(links_dir, sources))
    folders, roots = c["folders"]
    return romm.Mapping(folders, romm.options_from({"romm": saved}), links_dir, roots), saved, None


def romm_view(fresh=False):
    m, saved, error = romm_mapping(fresh)
    opt = romm.options_from({"romm": saved})
    sources = saved.get("sources") or []
    slugs = [{"slug": k, "name": v[0], "family": v[1], "kind": v[2]} for k, v in sorted(romm.PLATFORMS.items())]
    base = {"sources": sources, "error": error, "slugs": slugs,
            "links_dir": romm_links_dir(saved, sources),
            "options": {**{k: opt[k] for k in ("variants", "layout", "links_dir", "keep_links")},
                        "romm_folder": romm.Mapping({"": (0, 0)}, opt).romm_folder()}}
    if m is None:
        return {**base, "rows": [], "platforms": [], "firmware": [], "warnings": [], "summary":
                {"platforms": 0, "firmware": 0, "files": 0}, "links": {}, "outputs": {"compose": "", "config": ""}}
    return {**base,
            "links": {"dir": m.links_dir, "roots": m.roots, "targets": m.link_targets()},
            "conflicts": m.conflicts,
            "rows": m.rows(), "platforms": m.platforms, "firmware": m.firmware,
            "warnings": m.warnings(), "summary": m.summary(),
            "outputs": {"compose": m.compose(), "config": m.config_yml()}}


def romm_apply_links(trigger):
    with romm_lock:
        m, _saved, error = romm_mapping(fresh=True)
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
            if s["scan_enabled"] and now - last_scan >= max(1, float(s["scan_interval_minutes"])) * 60:
                run_scan("scheduled")
                if romm_saved().get("keep_links") and romm_saved().get("sources"):
                    try:
                        romm_apply_links("scheduled")
                    except Exception as e:  # noqa: BLE001
                        log(f"RomM platform links not updated: {e}")
            if s["sync_enabled"] and now - last_sync >= max(0.1, float(s["sync_interval_hours"])) * 3600:
                start_sync_async("scheduled")
        except Exception as e:  # noqa: BLE001 - never let the scheduler die
            log(f"Scheduler error: {e}")
        time.sleep(30)


# ---------------------------------------------------------------- routes

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
                            "details": ["The CSV changed since you loaded it (e.g. a scheduled scan added folders)."]}), 409
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
    try:
        s["scan_enabled"] = bool(body.get("scan_enabled"))
        s["auto_add_new"] = bool(body.get("auto_add_new"))
        s["sync_enabled"] = bool(body.get("sync_enabled"))
        s["scan_interval_minutes"] = max(1, int(body.get("scan_interval_minutes")))
        s["sync_interval_hours"] = max(0.1, float(body.get("sync_interval_hours")))
    except (TypeError, ValueError):
        return jsonify({"error": "Intervals must be numbers."}), 400
    update_state(settings=s)
    log("Schedule settings updated")
    return jsonify({"ok": True, "settings": s})


@app.get("/api/romm")
def api_romm():
    return jsonify(romm_view(fresh=request.args.get("fresh") == "1"))


@app.put("/api/romm/options")
def api_romm_options():
    body = request.get_json(force=True) or {}
    with romm_lock:
        cur = romm_saved()
        for k in ("romm_folder", "links_dir"):
            if k in body:
                v = str(body[k] or "").strip().rstrip("/")
                if k == "links_dir" and v and not v.startswith("/"):
                    return jsonify({"error": "The links folder must be a full path starting with /"}), 400
                cur[k] = v
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
        for k in ("variants", "keep_links"):
            if k in body:
                cur[k] = bool(body[k])
        if body.get("layout") in ("category", "folders"):
            cur["layout"] = body["layout"]
        romm_save(cur)
    return jsonify(romm_view(fresh="sources" in body))


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
    return jsonify(romm_view())


@app.post("/api/romm/links")
def api_romm_links():
    try:
        res, text = romm_apply_links("manual")
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    with romm_lock:
        cur = romm_saved()
        if not cur.get("keep_links") and not res["errors"]:
            cur["keep_links"] = True          # from now on kept up to date with every scan
            romm_save(cur)
    return jsonify({**romm_view(), "applied": {**res, "text": text}})


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
        # a folder keeps its label (the CSV refers to it); new ones get their folder name
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
    from waitress import serve

    log(f"Starting rom-mapper UI on port {PORT} (csv={INPUT_CSV}, src={SRC_BASE}, dest={DEST_PATH})")
    threading.Thread(target=scheduler_loop, daemon=True).start()
    serve(app, host="0.0.0.0", port=PORT, threads=8)


if __name__ == "__main__":
    main()
