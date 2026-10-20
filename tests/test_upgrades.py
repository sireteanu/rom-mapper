"""Upgrades: files written by older versions (and by Rom Sync) keep working."""
import json
import os

from conftest import make_dirs, state


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
    assert d["options"] == {"skip_names": ["media"]}, "settings of the platform links era are ignored"


def test_settings_from_the_platform_links_versions_still_load(env):
    """Before 1.0.9: links folder, RomM folder, layout, variants, keep_links and a mode. All are
    ignored now (RomM reads the folders by name); the choices and folders stay."""
    rom = env.path("roms", "collection")
    make_dirs(rom, "amigacdtv", "snes")
    env.write_config("romm-mapper.json", json.dumps(
        {"sources": [rom], "map": {"collection/amigacdtv": "commodore-cdtv"}, "mode": "links",
         "keep_links": True, "romm_folder": "/romm/library/roms/lolroms", "layout": "folders",
         "variants": False, "links_dir": env.path("roms")}))
    server, c = env.start()
    d = c.get("/api/romm").get_json()
    assert d["error"] is None and d["options"] == {"skip_names": ["media"]}
    assert f"{os.path.join(rom, 'amigacdtv')}\tcommodore-cdtv" in d["outputs"]["mounts"]


def test_categories_chosen_in_1_0_9_are_read_as_the_platform(env):
    """1.0.9 stored "cat:<slug>" for a system with categories; categories now follow from the
    subfolders, so it is simply that platform."""
    rom = env.path("roms", "collection")
    make_dirs(rom, "atari2600", "atari2600/Homebrew")
    env.write_config("romm-mapper.json", json.dumps({"sources": [rom], "map": {"collection/atari2600": "cat:atari2600"}}))
    server, c = env.start()
    d = c.get("/api/romm").get_json()
    assert {r["path"]: r for r in d["rows"]}["collection/atari2600"]["value"] == "atari2600"
    assert '"atari2600":' in d["outputs"]["config"], "it has a subfolder: categories"


def test_first_romm_version_with_one_source_is_converted(env):
    """rom-mapper's first RomM section saved "source" (one folder) and choices without its name."""
    lol = env.path("roms", "lolroms")
    make_dirs(lol, "Atari/2600")
    env.write_config("romm-mapper.json", json.dumps({"source": lol, "map": {"Atari/2600": "exclude"}}))
    server, c = env.start()
    d = c.get("/api/romm").get_json()
    assert d["sources"] == [lol]
    assert {r["path"]: r["value"] for r in d["rows"]}["lolroms/Atari/2600"] == "exclude"


def test_an_old_rom_mapping_csv_is_ignored(env):
    """Since 1.0.3 Rom_Mapping.csv is no longer read: a new install starts empty, the file stays."""
    old = "Folder,rgs\nMedia Toggle,0\nMedia Location,\nsnes,snes\n"
    make_dirs(env.roms, "snes")
    env.write_config("Rom_Mapping.csv", old)
    server, c = env.start()
    d = state(c)
    assert d["frontends"] == [] and [r["status"] for r in d["rows"]] == ["new"]
    assert "rom-mapper-mapping.json" not in os.listdir(env.config)
    assert env.read_config("Rom_Mapping.csv") == old
    assert c.post("/api/import", data=old, content_type="text/csv").status_code in (404, 405)
