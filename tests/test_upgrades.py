"""Upgrades: files written by older versions (and by Rom Sync) keep working."""
import json
import os

from conftest import make_dirs, state

OLD_CSV = ("﻿Folder,!named,rgs,retrobat\r\n"
           "Media Toggle,0,0,1\r\n"
           "Media Location,,,MEDIA_FULL\r\n"
           "snes,Nintendo - Super Nintendo,snes,snes\r\n"
           "psx,,psx,\r\n"
           "gone,,gone,\r\n")


def test_old_rom_mapping_csv_is_imported_once_and_links_stay_the_same(env):
    """Before 1.0 the mapping was Rom_Mapping.csv, rows were plain folder names under SRC_BASE."""
    make_dirs(env.roms, "snes", "psx", "snes/media")
    env.write_config("Rom_Mapping.csv", OLD_CSV)
    server, c = env.start()
    d = state(c)
    assert [f["name"] for f in d["frontends"]] == ["!named", "rgs", "retrobat"]
    assert d["frontends"][2]["media_toggle"] == "1"
    rows = {r["folder"]: (r["values"], r["status"]) for r in d["rows"]}
    assert rows["roms/snes"] == (["Nintendo - Super Nintendo", "snes", "snes"], "mapped")
    assert rows["roms/gone"][1] == "missing"
    assert "rom-mapper-mapping.json" in os.listdir(env.config)
    assert env.read_config("Rom_Mapping.csv") == OLD_CSV, "the old file is left as it was"
    server.run_sync("t")
    # the same links rom-mapper.sh made
    assert env.link("rgs", "snes") == os.path.join(env.roms, "snes")
    assert env.link("!named", "Nintendo - Super Nintendo") == os.path.join(env.roms, "snes")
    assert env.link("retrobat", "MEDIA_FULL", "snes", "media") == os.path.join(env.roms, "snes", "media")
    # a later change to the old CSV is ignored: the app's copy is used from now on
    env.write_config("Rom_Mapping.csv", "Folder,other\n")
    server, c = env.start()
    assert [f["name"] for f in state(c)["frontends"]] == ["!named", "rgs", "retrobat"]


def test_rows_without_a_source_name_keep_their_folder_when_the_first_source_changes(env):
    """Rows saved before source folders had names point at the first source folder."""
    make_dirs(env.roms, "snes")
    make_dirs(env.path("roms", "collection"), "n64")
    env.write_config("rom-mapper-mapping.json", json.dumps(
        {"frontends": [{"name": "rgs", "media_toggle": "0", "media_location": ""}],
         "rows": [{"folder": "snes", "values": ["snes"]}]}))
    server, c = env.start()
    c.put("/api/sources", json={"sources": [{"path": env.path("roms", "collection")}, {"path": env.roms}]})
    rows = {r["folder"]: r for r in state(c)["rows"]}
    assert rows["roms/snes"]["values"] == ["snes"] and rows["roms/snes"]["status"] == "mapped"
    server.run_sync("t")
    assert env.link("rgs", "snes") == os.path.join(env.roms, "snes")


def test_src_base_with_several_folders(env):
    make_dirs(env.roms, "snes")
    make_dirs(env.path("roms", "collection"), "n64")
    server, c = env.start(SRC_BASE=f"{env.roms};{env.path('roms', 'collection')}")
    assert [r["folder"] for r in state(c)["rows"]] == ["roms/snes", "collection/n64"]


def test_schedule_in_minutes_and_hours_is_converted_to_units(env):
    """Before 1.0.3 the schedule was scan_interval_minutes and sync_interval_hours."""
    cases = [  # (old minutes, old hours) -> (scan every, unit, sync every, unit)
        ((60, 24), (1, "hours", 1, "days")),
        ((15, 2.5), (15, "minutes", 150, "minutes")),
        ((1440, 48), (1, "days", 2, "days")),
        ((90, 0.1), (90, "minutes", 6, "minutes")),
    ]
    for (minutes, hours), want in cases:
        env.write_config("rom-mapper-state.json", json.dumps(
            {"settings": {"scan_enabled": True, "scan_interval_minutes": minutes, "auto_add_new": False,
                          "sync_enabled": True, "sync_interval_hours": hours},
             "last_scan": None, "last_sync": None}))
        server, c = env.start()
        s = state(c)["settings"]
        assert (s["scan_every"], s["scan_unit"], s["sync_every"], s["sync_unit"]) == want
        assert "scan_interval_minutes" not in s and "sync_interval_hours" not in s
        assert s["auto_add_new"] is False, "the other settings stay"
        assert server.interval_seconds(s, "scan") == minutes * 60
        assert server.interval_seconds(s, "sync") == round(hours * 3600)
    # a page from before 1.0.3 (still open in a browser) sends the old names
    r = c.put("/api/settings", json={"scan_enabled": True, "auto_add_new": True, "sync_enabled": False,
                                     "scan_interval_minutes": "30", "sync_interval_hours": "12"})
    s = r.get_json()["settings"]
    assert (s["scan_every"], s["scan_unit"], s["sync_every"], s["sync_unit"]) == (30, "minutes", 12, "hours")


def test_romm_settings_from_rom_sync_are_converted(env):
    """Rom Sync's romm-mapper.json: one download folder, choices without a folder name, maybe a
    links folder from inside Rom Sync's container."""
    lol = env.path("roms", "lolroms")
    make_dirs(lol, "Konami - Picno", "Nintendo/Super Famicom")
    env.write_config("romm-mapper.json", json.dumps(
        {"map": {"Konami - Picno": "exclude"}, "layout": "folders", "keep_links": True,
         "links_dir": "relative/inside/rom-sync", "method": "links"}))
    server, c = env.start(ROMM_SOURCE=lol)
    d = c.get("/api/romm").get_json()
    assert d["error"] is None and d["sources"] == [lol]
    saved = json.loads(env.read_config("romm-mapper.json"))
    assert saved["map"] == {"lolroms/Konami - Picno": "exclude"}
    assert "links_dir" not in saved and saved["sources"] == [lol]
    rows = {r["path"]: r for r in d["rows"]}
    assert rows["lolroms/Konami - Picno"]["value"] == "exclude"
    assert rows["lolroms/Nintendo/Super Famicom"]["value"] == "snes"
    assert d["options"]["layout"] == "folders" and d["options"]["keep_links"] is True


def test_first_romm_version_with_one_source_is_converted(env):
    """rom-mapper's first RomM section saved "source" (one folder) and choices without its name."""
    lol = env.path("roms", "lolroms")
    make_dirs(lol, "Atari/2600")
    env.write_config("romm-mapper.json", json.dumps({"source": lol, "map": {"Atari/2600": "exclude"}}))
    server, c = env.start()
    d = c.get("/api/romm").get_json()
    assert d["sources"] == [lol]
    assert {r["path"]: r["value"] for r in d["rows"]}["lolroms/Atari/2600"] == "exclude"
