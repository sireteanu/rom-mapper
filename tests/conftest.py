"""Test helpers: a fake /mnt/user with source folders, a mapping folder and a config folder, and a
fresh copy of the app configured for it (the app reads its settings from the environment when it
is imported)."""
import importlib
import os
import sys

import pytest

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
sys.path.insert(0, APP)


def make_dirs(base, *paths, files=1):
    for p in paths:
        d = os.path.join(base, *p.split("/"))
        os.makedirs(d, exist_ok=True)
        for i in range(files):
            with open(os.path.join(d, f"Game {i}.zip"), "w") as f:
                f.write("x")


class Env:
    """One test installation. `root` stands in for /mnt/user."""

    def __init__(self, tmp_path, monkeypatch):
        self.root = str(tmp_path / "mnt" / "user")
        self.roms = os.path.join(self.root, "Emulation", "roms")
        self.dest = os.path.join(self.root, "Emulation", "sets", "mapping")
        self.config = str(tmp_path / "config")
        os.makedirs(self.roms)
        os.makedirs(self.config)
        self.monkeypatch = monkeypatch
        self.env = {"INPUT_CSV": os.path.join(self.config, "Rom_Mapping.csv"), "SRC_BASE": self.roms,
                    "DEST_PATH": self.dest, "ROMM_SOURCE": ""}

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def write_config(self, name, text):
        with open(os.path.join(self.config, name), "w", encoding="utf-8", newline="") as f:
            f.write(text)

    def read_config(self, name):
        with open(os.path.join(self.config, name), encoding="utf-8", newline="") as f:
            return f.read()

    def start(self, **env):
        """Import the app with this installation's settings -> (server module, test client)."""
        for k, v in {**self.env, **env}.items():
            self.monkeypatch.setenv(k, v)
        for mod in ("server", "romm", "links", "version"):
            sys.modules.pop(mod, None)
        server = importlib.import_module("server")
        return server, server.app.test_client()

    def link(self, *parts):
        p = os.path.join(self.dest, *parts)
        return os.readlink(p) if os.path.islink(p) else None


@pytest.fixture
def env(tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch)


def state(client):
    return client.get("/api/state").get_json()


def save(client, rows, frontends=None, resync=False):
    """Save rows {folder: [values]} (all other rows blank) with the current frontends."""
    d = state(client)
    fes = frontends if frontends is not None else d["frontends"]
    known = {r["folder"] for r in d["rows"]}
    body_rows = [{"folder": r["folder"], "values": rows.get(r["folder"], [""] * len(fes))} for r in d["rows"]]
    body_rows += [{"folder": k, "values": v} for k, v in rows.items() if k not in known]
    r = client.put("/api/mapping", json={"version": d["version"], "frontends": fes, "rows": body_rows,
                                          "resync": resync})
    return r


def fe(name, media=False, location=""):
    return {"name": name, "media_toggle": "1" if media else "0", "media_location": location}
