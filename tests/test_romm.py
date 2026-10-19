"""The RomM section: download folders, platform links, overlaps, exclude, config.yml."""
import json
import os

from conftest import make_dirs


def setup(env, collection_first=False):
    lol, rom = env.path("roms", "lolroms"), env.path("roms", "collection")
    make_dirs(lol, "Nintendo/Super Famicom", "Nintendo/Super Famicom/T-En", "Nintendo/Super Famicom/Satellaview",
              "Nintendo/GameCube", "Nintendo/GameCube/BIOS", "SONY/PlayStation", "Atari/800/Flux", "Konami - Picno")
    make_dirs(rom, "snes", "n64", "psx")
    with open(os.path.join(lol, "Nintendo", "Super Famicom", "half.7z.part"), "w") as f:
        f.write("x")
    server, c = env.start()
    order = [rom, lol] if collection_first else [lol, rom]
    d = c.put("/api/romm/options", json={"sources": order}).get_json()
    return server, c, d, lol, rom


def rows(d):
    return {r["path"]: r for r in d["rows"]}


def test_platforms_from_lolroms_rules_and_romm_style_names(env):
    server, c, d, lol, rom = setup(env)
    assert d["error"] is None and d["links_dir"] == env.path("roms")
    r = rows(d)
    assert r["lolroms/Nintendo/Super Famicom"]["value"] == "snes"
    assert r["lolroms/Nintendo/Super Famicom/T-En"]["kind"] == "merge"
    assert r["lolroms/Nintendo/Super Famicom/Satellaview"]["value"] == "satellaview"
    assert r["lolroms/Nintendo/GameCube/BIOS"]["value"] == "firmware"
    assert r["lolroms/Atari/800/Flux"]["value"] == "exclude"
    assert r["collection/n64"]["value"] == "n64", "a folder named like a RomM platform gets it"
    assert r["lolroms/Nintendo/Super Famicom"]["files"] == 1, ".part files aren't counted"


def test_overlaps_first_folder_wins_and_order_can_change(env):
    server, c, d, lol, rom = setup(env)
    assert sorted(x["slug"] for x in d["conflicts"]) == ["psx", "snes"]
    assert rows(d)["collection/snes"]["conflict"] == "lolroms"
    assert d["links"]["targets"]["snes"] == "lolroms/Nintendo/Super Famicom"
    assert any("more than one download folder" in w for w in d["warnings"])
    d = c.put("/api/romm/options", json={"sources": [rom, lol]}).get_json()
    assert d["links"]["targets"]["snes"] == "collection/snes"
    assert rows(d)["lolroms/Nintendo/Super Famicom"]["conflict"] == "collection"


def test_excluding_a_folder_leaves_everything_inside_it_out(env):
    server, c, d, lol, rom = setup(env)
    d = c.put("/api/romm/map", json={"path": "lolroms/Nintendo", "action": "exclude"}).get_json()
    r = rows(d)
    assert r["lolroms/Nintendo/Super Famicom"]["kind"] == "skip"
    assert r["lolroms/Nintendo/Super Famicom"]["excluded_by"] == "lolroms/Nintendo"
    assert d["links"]["targets"]["snes"] == "collection/snes"           # no overlap any more
    assert not any(x["slug"] == "snes" for x in d["conflicts"])
    d = c.put("/api/romm/map", json={"path": "lolroms/Nintendo/GameCube", "action": "ngc"}).get_json()
    assert d["links"]["targets"]["ngc"] == "lolroms/Nintendo/GameCube", "your own choice beats the excluded parent"
    assert c.put("/api/romm/map", json={"path": "x", "action": "Not A Slug"}).status_code == 400


def test_links_are_relative_kept_with_scans_and_never_touch_other_things(env):
    server, c, d, lol, rom = setup(env)
    roms = env.path("roms")
    os.makedirs(os.path.join(roms, "gb"))                              # a real folder with that name
    os.symlink("/somewhere/else", os.path.join(roms, "psx"))          # someone else's link
    make_dirs(lol, "Nintendo/Game Boy")
    d = c.post("/api/romm/links").get_json()
    assert d["options"]["keep_links"] is True
    assert os.readlink(os.path.join(roms, "snes")) == "lolroms/Nintendo/Super Famicom"
    assert os.readlink(os.path.join(roms, "n64")) == "collection/n64"
    assert os.readlink(os.path.join(roms, "psx")) == "/somewhere/else"
    assert os.path.isdir(os.path.join(roms, "gb")) and not os.path.islink(os.path.join(roms, "gb"))
    assert d["applied"]["skipped"]
    # a choice changes: the scheduled refresh updates the links
    c.put("/api/romm/map", json={"path": "collection/n64", "action": "exclude"})
    res, text = server.romm_apply_links("scheduled")
    assert res["removed"] == ["n64"] and not os.path.lexists(os.path.join(roms, "n64"))


def test_config_yml_and_compose_line(env):
    server, c, d, lol, rom = setup(env)
    y = d["outputs"]["config"]
    assert 'platforms:\n    - "collection"\n    - "lolroms"' in y
    assert '"Satellaview"' in y and '"snes":' in y
    assert '"/path/on/your/server:/romm/library/roms"' in d["outputs"]["compose"]
    d = c.put("/api/romm/options", json={"romm_folder": "/romm/data/roms/lolroms"}).get_json()
    assert ':/romm/data/roms"' in d["outputs"]["compose"]


def test_problems_are_explained(env):
    server, c = env.start()
    assert c.get("/api/romm").get_json()["error"] == "Add a download folder first."
    d = c.put("/api/romm/options", json={"sources": [env.path("nope")]}).get_json()
    assert "Folder not found" in d["error"]
    make_dirs(env.path("a"), "x")
    make_dirs(env.path("b"), "y")
    d = c.put("/api/romm/options", json={"sources": [env.path("a"), env.path("b")],
                                         "links_dir": env.path("a")}).get_json()
    assert "not inside the links folder" in d["error"]
    assert c.put("/api/romm/options", json={"sources": ["relative"]}).status_code == 400


def test_links_folder_outside_the_mounted_folders_is_refused_in_docker(env, monkeypatch):
    """A second mount for RomM pointed at the download folder itself: the links folder (its parent)
    is then on the container's own disk, where links would be lost."""
    server, c, d, lol, rom = setup(env)
    assert c.get("/api/romm").get_json()["error"] is None
    monkeypatch.setattr(server, "IN_DOCKER", True)
    mounted = {lol, rom}                        # only the download folders themselves
    monkeypatch.setattr(server.os.path, "ismount", lambda p: p in mounted or os.path.dirname(p) == p)
    d = c.get("/api/romm?fresh=1").get_json()
    assert d["links_dir"] == env.path("roms")
    assert "not inside a folder mounted into the container" in d["error"]
    assert c.post("/api/romm/links").status_code == 400, "no links are made"
    mounted.add(env.path("roms"))               # the folder that holds the download folders
    assert c.get("/api/romm?fresh=1").get_json()["error"] is None


def test_settings_file_is_written_safely(env):
    server, c, d, lol, rom = setup(env)
    c.put("/api/romm/map", json={"path": "collection/psx", "action": "exclude"})
    saved = json.loads(env.read_config("romm-mapper.json"))
    assert saved["map"] == {"collection/psx": "exclude"} and saved["sources"] == [lol, rom]
    assert not [n for n in os.listdir(env.config) if n.startswith(".tmp-")]


def test_folder_counts_reread_only_changed_folders(env, monkeypatch):
    server, c, d, lol, rom = setup(env)
    romm = server.romm
    full = romm.folders_from_disk(lol)
    os.symlink(env.path("roms", "collection"), os.path.join(lol, "linked"))     # folder links stay out
    with open(os.path.join(lol, "SONY", "PlayStation", "game.chd"), "w") as f:
        f.write("x")
    listed = []
    real = os.scandir
    monkeypatch.setattr(romm.os, "scandir", lambda p: (listed.append(p), real(p))[1])
    quick = romm.folders_from_disk(lol, full=False)
    before = full["SONY/PlayStation"][0]
    assert quick["SONY/PlayStation"] == (before + 1, before + 1), "a new file is seen"
    assert "linked" not in quick
    assert sorted(listed) == sorted([lol, os.path.join(lol, "SONY", "PlayStation")]), \
        "only the folders whose date changed are listed again"
    assert {k: v for k, v in quick.items() if k != "SONY/PlayStation"} == \
        {k: v for k, v in full.items() if k != "SONY/PlayStation"}
    listed.clear()
    assert romm.folders_from_disk(lol, full=True) == quick and len(listed) > 2      # Refresh reads everything


def test_platform_list_is_loaded_once_not_with_every_refresh(env):
    server, c, d, lol, rom = setup(env)
    assert "slugs" not in c.get("/api/romm").get_json()
    slugs = c.get("/api/romm/platforms").get_json()["slugs"]
    assert "snes" in {x["slug"] for x in slugs} and len(slugs) > 100
    assert set(slugs[0]) == {"slug", "name", "family", "kind"}


def test_levels_list_only_the_top_folders_and_count_what_is_below(env):
    """A RomM-style collection with one folder per platform: levels=1 gives one row per platform,
    and games kept in subfolders (one per multi-disc game) still count."""
    col = env.path("roms", "collection")
    make_dirs(col, "snes", "snes/media/box2d", "psx/Game A", "psx/Game B", "empty", files=2)
    for d in ("empty",):
        for f in os.listdir(os.path.join(col, d)):
            os.remove(os.path.join(col, d, f))
    romm = env.start()[0].romm
    every = romm.folders_from_disk(col)
    assert "snes/media/box2d" in every and every["psx"] == (0, 0)
    top = romm.folders_from_disk(col, depth=1)
    assert set(top) == {"", "snes", "psx", "empty"}
    assert top["snes"] == (3, 3), "2 files + the media folder"
    assert top["psx"] == (2, 2), "two game folders"
    assert top["empty"] == (0, 0)
    assert romm.folders_from_disk(col, full=False, depth=1) == top, "the quick re-read agrees"
    assert romm.folders_from_disk(col, full=False) == every, "and doesn't mix up the two"


def test_progress_is_reported_per_top_folder(env):
    col = env.path("roms", "collection")
    make_dirs(col, "a/x", "b", "c")
    romm = env.start()[0].romm
    seen = []
    romm.folders_from_disk(col, progress=lambda done, total, cur: seen.append((done, total, cur)))
    assert seen == [(0, 3, "a"), (1, 3, "b"), (2, 3, "c"), (3, 3, "")]
    seen.clear()
    romm.folders_from_roots(env.path("roms"), [col, col], progress=lambda *a: seen.append(a))
    assert seen[0] == (0, 2, 0, 3, "a") and seen[-1] == (1, 2, 3, 3, "")


def test_levels_setting_in_the_romm_tab(env):
    server, c, d, lol, rom = setup(env)
    make_dirs(rom, "psx/Game A")
    assert "collection/psx/Game A" in rows(c.get("/api/romm?fresh=1").get_json())
    d = c.put("/api/romm/options", json={"depths": {rom: 1}}).get_json()
    assert d["depths"] == {rom: 1}
    paths = {r["path"] for r in d["rows"]}
    assert "collection/psx" in paths and "collection/psx/Game A" not in paths
    assert "lolroms/Nintendo/Super Famicom/T-En" in paths, "other folders keep every level"
    assert json.loads(env.read_config("romm-mapper.json"))["depths"] == {rom: 1}
    assert c.put("/api/romm/options", json={"depths": {rom: 9}}).status_code == 400
    d = c.put("/api/romm/options", json={"sources": [lol]}).get_json()
    assert d["depths"] == {}, "a removed folder loses its setting"
    assert json.loads(env.read_config("romm-mapper.json")).get("depths", {}) == {}


def test_folders_are_read_in_the_background_with_progress(env, monkeypatch):
    server, c, d, lol, rom = setup(env)
    monkeypatch.setattr(server, "ROMM_BACKGROUND", True)
    gate = server.threading.Event()
    real = server.romm.folders_from_roots

    def slow(*a, **k):
        gate.wait(5)
        return real(*a, **k)
    monkeypatch.setattr(server.romm, "folders_from_roots", slow)
    d = c.put("/api/romm/options", json={"sources": [rom, lol]}).get_json()
    assert d["reading"]["running"] is True and "rows" not in d
    assert c.get("/api/romm").get_json()["reading"]["running"] is True, "the page waits, nothing else starts"
    assert c.get("/api/romm/progress").get_json()["sources"] == 2
    gate.set()
    for _ in range(100):
        if not c.get("/api/romm/progress").get_json()["running"]:
            break
        server.time.sleep(0.05)
    d = c.get("/api/romm").get_json()
    assert "reading" not in d and d["rows"] and d["sources"] == [rom, lol]


def test_folders_named_to_skip_are_not_read(env):
    col = env.path("roms", "collection")
    make_dirs(col, "snes", "snes/media/box2d", "snes/Media", "psx/Extras", "psx/Game.bak")
    romm = env.start()[0].romm
    every = romm.folders_from_disk(col)
    assert "snes/media/box2d" in every and "psx/Extras" in every
    listed = []
    real = romm.os.scandir
    romm.os.scandir = lambda p: (listed.append(p), real(p))[1]
    try:
        some = romm.folders_from_disk(col, skip=("media", "Extras", "*.BAK"))
    finally:
        romm.os.scandir = real
    assert set(some) == {"", "snes", "psx"}, "media/Media, Extras and *.bak are left out (any case)"
    assert not any("media" in p.lower() or "Extras" in p for p in listed), "and never read"
    assert romm.folders_from_disk(col, full=False) == every, "the cache keeps the two apart"


def test_never_read_setting_in_the_romm_tab(env):
    server, c, d, lol, rom = setup(env)
    make_dirs(rom, "snes/media/box2d", "psx/Extras")
    d = c.get("/api/romm?fresh=1").get_json()
    assert d["options"]["skip_names"] == ["media"], "media is skipped by default"
    paths = set(rows(d))
    assert "collection/snes/media/box2d" not in paths and "collection/psx/Extras" in paths
    assert '- "media"' in d["outputs"]["config"], "RomM is told to ignore it too"
    d = c.put("/api/romm/options", json={"skip_names": "media, Extras, extras"}).get_json()
    assert d["options"]["skip_names"] == ["media", "Extras"]
    assert "collection/psx/Extras" not in set(rows(d))
    assert json.loads(env.read_config("romm-mapper.json"))["skip_names"] == ["media", "Extras"]
    assert c.put("/api/romm/options", json={"skip_names": "roms/media"}).status_code == 400
    d = c.put("/api/romm/options", json={"skip_names": ""}).get_json()
    assert d["options"]["skip_names"] == [] and "collection/snes/media/box2d" in set(rows(d)), "nothing skipped"


def test_folders_without_files_are_sent_as_groups_and_can_be_excluded(env):
    """exodos/eXo/eXoDOS hold only folders: the page gets them as groups to build its tree, and
    excluding one leaves out everything inside it."""
    server, c, d, lol, rom = setup(env)
    make_dirs(rom, "exodos/eXo/eXoDOS/Game A", "exodos/eXo/eXoDOS/Game B")
    d = c.get("/api/romm?fresh=1").get_json()
    groups = {g["path"]: g for g in d["groups"]}
    assert {"collection/exodos", "collection/exodos/eXo", "collection/exodos/eXo/eXoDOS"} <= set(groups)
    assert not set(groups) & set(rows(d)), "a folder is a row or a group, not both"
    assert "collection" not in groups, "download folders are rows"
    d = c.put("/api/romm/map", json={"path": "collection/exodos", "action": "exclude"}).get_json()
    r = rows(d)
    assert r["collection/exodos/eXo/eXoDOS/Game A"]["excluded_by"] == "collection/exodos"
    assert r["collection/exodos"]["value"] == "exclude", "with a choice of its own it becomes a row"
