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


def test_settings_file_is_written_safely(env):
    server, c, d, lol, rom = setup(env)
    c.put("/api/romm/map", json={"path": "collection/psx", "action": "exclude"})
    saved = json.loads(env.read_config("romm-mapper.json"))
    assert saved["map"] == {"collection/psx": "exclude"} and saved["sources"] == [lol, rom]
    assert not [n for n in os.listdir(env.config) if n.startswith(".tmp-")]
