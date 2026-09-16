"""rom-mapper web UI.

Reads/writes the same Rom_Mapping.csv the rom-mapper.sh script uses, scans the
ROM source folder for new/removed folders, and runs the sync script on demand
or on a schedule.
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
# ----------------------------------------------

TOGGLE_ROW = "Media Toggle"
LOCATION_ROW = "Media Location"
RESERVED = {TOGGLE_ROW, LOCATION_ROW}

DEFAULT_SETTINGS = {
    "scan_enabled": True,
    "scan_interval_minutes": 60,
    "auto_add_new": True,
    "sync_enabled": False,
    "sync_interval_hours": 24,
}

app = Flask(__name__, static_folder="static", static_url_path="/static")

csv_lock = threading.RLock()      # guards reads/writes of the CSV and state file
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
        elif err := bad_path_part(folder, allow_slash=False):
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

def list_source_folders():
    if not os.path.isdir(SRC_BASE):
        raise RuntimeError(f"ROM source folder not found: {SRC_BASE} (is the volume mounted?)")
    names = []
    for entry in os.scandir(SRC_BASE):
        if entry.name.startswith(".") or not entry.is_dir():
            continue
        names.append(entry.name)
    return sorted(names, key=str.lower)


def build_view():
    """Mapping merged with what's on disk, with a status per row."""
    with csv_lock:
        raw = read_raw()
        m = parse_mapping(raw)
        state = load_state()
    disk_error = None
    try:
        disk = list_source_folders()
    except RuntimeError as e:
        disk, disk_error = [], str(e)
    disk_set = set(disk)
    in_csv = {r["folder"] for r in m["rows"]}

    for r in m["rows"]:
        if not disk_error and r["folder"] not in disk_set:
            r["status"] = "missing"
        elif any(r["values"]):
            r["status"] = "mapped"
        else:
            r["status"] = "unmapped"
    for name in disk:
        if name not in in_csv and not bad_path_part(name, allow_slash=False):
            m["rows"].append({"folder": name, "values": [""] * len(m["frontends"]), "status": "new"})

    return {
        **m,
        "version": version_of(raw),
        "disk_error": disk_error,
        "paths": {"csv": INPUT_CSV, "src": SRC_BASE, "dest": DEST_PATH},
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
        try:
            disk = list_source_folders()
        except RuntimeError as e:
            log(f"Scan ({trigger}) failed: {e}")
            result = {"time": now_iso(), "ok": False, "error": str(e), "new": [], "missing": [], "added": 0}
            update_state(last_scan=result)
            return result

        in_csv = {r["folder"] for r in m["rows"]}
        disk_set = set(disk)
        unsupported = [d for d in disk if bad_path_part(d, allow_slash=False)]
        new = [d for d in disk if d not in in_csv and d not in unsupported]
        missing = [r["folder"] for r in m["rows"] if r["folder"] not in disk_set]

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
        env = {**os.environ, "INPUT_CSV": snapshot, "SRC_BASE": SRC_BASE, "DEST_PATH": DEST_PATH}
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
