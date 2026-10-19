"""The mapping grid: source folders, scanning, saving, links, schedule."""
import json
import os

from conftest import fe, make_dirs, save, state


def test_first_start_has_an_empty_mapping_and_lists_the_rom_folders(env):
    make_dirs(env.roms, "snes", "psx", ".hidden")
    server, c = env.start()
    d = state(c)
    assert d["app_version"] == server.__version__
    assert [r["folder"] for r in d["rows"]] == ["roms/psx", "roms/snes"]       # new, from disk
    assert {r["status"] for r in d["rows"]} == {"new"}
    assert d["sources"] == [{"path": env.roms, "label": "roms", "depth": 1}]


def test_saving_and_resync_build_absolute_links_per_frontend(env):
    make_dirs(env.roms, "snes", "psx", "snes/media")
    server, c = env.start()
    r = save(c, {"roms/snes": ["snes", "SDCARD/snes"], "roms/psx": ["psx", ""]},
             frontends=[fe("rgs"), fe("knulli", media=True)])
    assert r.status_code == 200
    assert server.run_sync("test")["ok"]
    assert env.link("rgs", "snes") == os.path.join(env.roms, "snes")
    assert env.link("rgs", "psx") == os.path.join(env.roms, "psx")
    assert env.link("knulli", "SDCARD", "snes") == os.path.join(env.roms, "snes")
    assert env.link("knulli", "psx") is None                                   # blank = no link
    # media folders: <frontend>/<location or MEDIA_FULL>/<name without its first part>/media
    assert env.link("knulli", "MEDIA_FULL", "snes", "media") == os.path.join(env.roms, "snes", "media")


def test_resync_changes_only_what_differs_and_keeps_real_files(env):
    make_dirs(env.roms, "snes", "psx", "n64")
    server, c = env.start()
    save(c, {"roms/snes": ["snes"], "roms/psx": ["psx"]}, frontends=[fe("rgs")])
    server.run_sync("first")
    first_inode = os.lstat(os.path.join(env.dest, "rgs", "snes")).st_ino
    with open(os.path.join(env.dest, "rgs", "notes.txt"), "w") as f:
        f.write("mine")
    os.symlink("/elsewhere", os.path.join(env.dest, "rgs", "old"))           # stale link

    save(c, {"roms/snes": ["snes"], "roms/n64": ["n64"]}, frontends=[fe("rgs")])  # psx dropped, n64 added
    out = server.run_sync("second")["output"]
    assert "1 links created, 0 corrected, 2 removed, 1 unchanged" in out
    assert os.lstat(os.path.join(env.dest, "rgs", "snes")).st_ino == first_inode, "unchanged link untouched"
    assert env.link("rgs", "n64") and env.link("rgs", "psx") is None and env.link("rgs", "old") is None
    assert open(os.path.join(env.dest, "rgs", "notes.txt")).read() == "mine"
    assert "aren't links - left alone" in out


def test_renaming_a_target_corrects_the_link_and_empty_folders_go(env):
    make_dirs(env.roms, "snes")
    server, c = env.start()
    save(c, {"roms/snes": ["a/snes"]}, frontends=[fe("rgs")])
    server.run_sync("1")
    save(c, {"roms/snes": ["snes"]}, frontends=[fe("rgs")])
    server.run_sync("2")
    assert env.link("rgs", "snes") and not os.path.exists(os.path.join(env.dest, "rgs", "a"))


def test_duplicate_names_first_row_wins_and_is_reported(env):
    make_dirs(env.roms, "snes", "sfc")
    server, c = env.start()
    save(c, {"roms/sfc": ["snes"], "roms/snes": ["snes"]}, frontends=[fe("rgs")])
    rows = [r["folder"] for r in state(c)["rows"]]
    first = rows[0]
    out = server.run_sync("t")["output"]
    assert env.link("rgs", "snes") == os.path.join(env.roms, first.split("/", 1)[1])
    assert "already given to another folder" in out


def test_mapping_folder_inside_a_source_folder_is_refused(env):
    make_dirs(env.roms, "snes")
    server, c = env.start(DEST_PATH=os.path.join(env.roms, "links"))
    save(c, {"roms/snes": ["snes"]}, frontends=[fe("rgs")])
    res = server.run_sync("t")
    assert not res["ok"] and "inside the source folder" in res["output"]
    server, c = env.start(DEST_PATH="/mnt/user")
    assert "Refusing" in server.run_sync("t")["output"]


def test_several_source_folders_with_depth(env):
    make_dirs(env.roms, "snes")
    make_dirs(env.path("roms", "lolroms"), "Nintendo/Super Famicom", "Nintendo/Super Famicom/T-En", "SONY/PlayStation")
    make_dirs(env.path("roms", "collection"), "n64", "snes/media")
    server, c = env.start()
    r = c.put("/api/sources", json={"sources": [{"path": env.roms, "depth": 1},
                                                 {"path": env.path("roms", "lolroms"), "depth": 2},
                                                 {"path": env.path("roms", "collection"), "depth": 1}]})
    assert [x["label"] for x in r.get_json()["sources"]] == ["roms", "lolroms", "collection"]
    scan = c.post("/api/scan").get_json()
    assert "lolroms/Nintendo/Super Famicom" in scan["new"]
    assert "lolroms/Nintendo/Super Famicom/T-En" not in scan["new"], "depth 2 stops there"
    assert "collection/snes" in scan["new"] and not any(n.endswith("media") for n in scan["new"])
    save(c, {"lolroms/Nintendo/Super Famicom": ["sfc"], "collection/n64": ["n64"]}, frontends=[fe("rgs")])
    server.run_sync("t")
    assert env.link("rgs", "sfc") == env.path("roms", "lolroms", "Nintendo", "Super Famicom")
    assert env.link("rgs", "n64") == env.path("roms", "collection", "n64")


def test_source_folder_labels_stay_when_reordered_and_nesting_is_refused(env):
    make_dirs(env.path("a", "x"), "one")
    make_dirs(env.path("b", "x"), "two")
    server, c = env.start()
    c.put("/api/sources", json={"sources": [{"path": env.path("a", "x")}, {"path": env.path("b", "x")}]})
    labels = [x["label"] for x in state(c)["sources"]]
    assert labels == ["x", "x-2"]
    c.put("/api/sources", json={"sources": [{"path": env.path("b", "x")}, {"path": env.path("a", "x")}]})
    assert [x["label"] for x in state(c)["sources"]] == ["x-2", "x"]          # the mapping refers to them
    r = c.put("/api/sources", json={"sources": [{"path": env.path("a")}, {"path": env.path("a", "x")}]})
    assert r.status_code == 400 and "inside" in r.get_json()["error"]
    assert c.put("/api/sources", json={"sources": [{"path": "relative/path"}]}).status_code == 400


def test_missing_and_new_rows_and_auto_add(env):
    make_dirs(env.roms, "snes")
    server, c = env.start()
    save(c, {"roms/gone": ["gone"]}, frontends=[fe("rgs")])      # saving the grid saves snes too
    make_dirs(env.roms, "psx")                                      # appears later
    server._folders_cache["key"] = None                             # (the page reuses a listing for 10 s)
    status = {r["folder"]: r["status"] for r in state(c)["rows"]}
    assert status == {"roms/gone": "missing", "roms/snes": "unmapped", "roms/psx": "new"}
    scan = c.post("/api/scan").get_json()
    assert scan["added"] == 1 and scan["missing"] == ["roms/gone"]
    assert {r["folder"]: r["status"] for r in state(c)["rows"]}["roms/psx"] == "unmapped"


def test_saving_over_a_newer_mapping_needs_force(env):
    make_dirs(env.roms, "snes")
    server, c = env.start()
    d = state(c)
    save(c, {"roms/snes": ["snes"]}, frontends=[fe("rgs")])
    r = c.put("/api/mapping", json={"version": d["version"], "frontends": [fe("rgs")], "rows": []})
    assert r.status_code == 409
    r = c.put("/api/mapping", json={"version": d["version"], "frontends": [fe("rgs")], "rows": [], "force": True})
    assert r.status_code == 200


def test_invalid_names_are_rejected(env):
    server, c = env.start()
    for rows, frontends in (({"roms/a": ["x,y"]}, [fe("rgs")]), ({"roms/a": ["../x"]}, [fe("rgs")]),
                            ({"roms/a": ["x"]}, [fe("a/b")]), ({"roms/a": ["x"]}, [fe("rgs"), fe("rgs")])):
        r = save(c, rows, frontends=frontends)
        assert r.status_code == 400, rows


def test_mapping_is_stored_as_json_with_a_backup(env):
    make_dirs(env.roms, "snes")
    server, c = env.start()
    save(c, {"roms/snes": ["one"]}, frontends=[fe("rgs")])
    save(c, {"roms/snes": ["two"]}, frontends=[fe("rgs")])
    data = json.loads(env.read_config("rom-mapper-mapping.json"))
    assert data["rows"] == [{"folder": "roms/snes", "values": ["two"]}]
    assert json.loads(env.read_config("rom-mapper-mapping.json.bak"))["rows"][0]["values"] == ["one"]


def test_settings_and_schedule_validation(env):
    server, c = env.start()
    good = {"scan_enabled": True, "auto_add_new": False, "sync_enabled": True,
            "scan_every": "15", "scan_unit": "minutes", "sync_every": "3", "sync_unit": "days"}
    s = c.put("/api/settings", json=good).get_json()["settings"]
    assert (s["scan_every"], s["scan_unit"], s["sync_every"], s["sync_unit"]) == (15, "minutes", 3, "days")
    assert server.interval_seconds(s, "scan") == 15 * 60
    assert server.interval_seconds(s, "sync") == 3 * 86400
    assert server.load_state()["settings"]["sync_unit"] == "days", "saved"
    for bad in ({"scan_every": "soon"}, {"scan_unit": "weeks"}, {"scan_every": "1.5"},
                {"sync_every": "2", "sync_unit": "minutes"},      # shorter than 5 minutes
                {"sync_every": "400", "sync_unit": "days"}):     # longer than a year
        assert c.put("/api/settings", json={**good, **bad}).status_code == 400, bad


def test_scheduler_uses_the_unit(env, monkeypatch):
    server, c = env.start()
    c.put("/api/settings", json={"scan_enabled": True, "auto_add_new": True, "sync_enabled": True,
                                 "scan_every": 2, "scan_unit": "hours", "sync_every": 1, "sync_unit": "days"})
    ran = []
    monkeypatch.setattr(server, "run_scan", lambda trigger: ran.append("scan"))
    monkeypatch.setattr(server, "start_sync_async", lambda trigger: ran.append("sync"))
    monkeypatch.setattr(server, "romm_saved", lambda: {})

    def tick(scan_age, sync_age):
        now = server.time.time()
        iso = lambda age: server.datetime.fromtimestamp(now - age, server.timezone.utc).isoformat()
        server.update_state(last_scan={"time": iso(scan_age)}, last_sync={"time": iso(sync_age)})
        ran.clear()

        def stop(_):
            raise KeyboardInterrupt
        monkeypatch.setattr(server.time, "sleep", stop)
        try:
            server.scheduler_loop()
        except KeyboardInterrupt:
            pass
        return sorted(ran)

    assert tick(scan_age=90 * 60, sync_age=23 * 3600) == []
    assert tick(scan_age=2 * 3600 + 5, sync_age=23 * 3600) == ["scan"]
    assert tick(scan_age=60, sync_age=86400 + 5) == ["sync"]


def test_command_line_resync(env, capsys):
    make_dirs(env.roms, "snes")
    server, c = env.start()
    save(c, {"roms/snes": ["snes"]}, frontends=[fe("rgs")])
    import sys
    old = sys.argv
    sys.argv = ["server.py", "--resync"]
    try:
        try:
            server.main()
        except SystemExit as e:
            assert e.code == 0
    finally:
        sys.argv = old
    assert env.link("rgs", "snes") and "1 links created" in capsys.readouterr().out


def test_page_has_a_tab_for_frontend_links_and_one_for_romm(env):
    server, c = env.start()
    html = c.get("/").get_data(as_text=True)
    assert 'data-pane="links"' in html and 'data-pane="romm"' in html
    assert 'id="paneLinks"' in html and 'id="paneRomm"' in html


def test_a_hidden_page_stops_refreshing(env):
    server, c = env.start()
    html = c.get("/").get_data(as_text=True)
    assert "visibilitychange" in html and "document.hidden" in html
