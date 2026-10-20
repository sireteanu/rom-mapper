"""The RomM section: download folders, platforms as bind mounts, categories, exclude, config.yml."""
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


def test_excluding_a_folder_leaves_everything_inside_it_out(env):
    server, c, d, lol, rom = setup(env)
    d = c.put("/api/romm/map", json={"path": "lolroms/Nintendo", "action": "exclude"}).get_json()
    r = rows(d)
    assert r["lolroms/Nintendo/Super Famicom"]["kind"] == "skip"
    assert r["lolroms/Nintendo/Super Famicom"]["excluded_by"] == "lolroms/Nintendo"
    d = c.put("/api/romm/map", json={"path": "lolroms/Nintendo/GameCube", "action": "ngc"}).get_json()
    r = rows(d)
    assert r["lolroms/Nintendo/GameCube"]["value"] == "ngc", "your own choice beats the excluded parent"
    assert "excluded_by" not in r["lolroms/Nintendo/GameCube"]
    assert c.put("/api/romm/map", json={"path": "x", "action": "Not A Slug"}).status_code == 400


def test_problems_are_explained(env):
    server, c = env.start()
    assert c.get("/api/romm").get_json()["error"] == "Add a download folder first."
    d = c.put("/api/romm/options", json={"sources": [env.path("nope")]}).get_json()
    assert "Folder not found" in d["error"]
    make_dirs(env.path("a"), "x")
    d = c.put("/api/romm/options", json={"sources": [env.path("a"), env.path("a", "x")]}).get_json()
    assert "is inside" in d["error"]
    assert c.put("/api/romm/options", json={"sources": ["relative"]}).status_code == 400


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
    c.put("/api/romm/options", json={"sources": [rom]})         # RomM reads this one
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


def test_a_choice_does_not_read_the_folders_again(env, monkeypatch):
    """On a big share a full read takes minutes: picking a platform or an option must reuse the
    folder list (it used to start a full read, and the page showed the old choice meanwhile)."""
    server, c, d, lol, rom = setup(env)
    c.get("/api/romm")
    reads = []
    real = server.romm.folders_from_roots
    monkeypatch.setattr(server.romm, "folders_from_roots", lambda *a, **k: (reads.append(k.get("full")), real(*a, **k))[1])
    d = c.put("/api/romm/map", json={"path": "collection/psx", "action": "exclude"}).get_json()
    assert rows(d)["collection/psx"]["value"] == "exclude"
    c.put("/api/romm/options", json={"variants": False, "layout": "folders"})
    assert reads == [], "no folder was read again"
    c.put("/api/romm/options", json={"sources": [rom, lol]})
    assert reads == [True], "a change to the download folders still reads them"


def test_excluded_folders_are_not_read_inside(env, monkeypatch):
    """eXoDOS-style: once a folder is excluded, its thousands of subfolders aren't read any more -
    unless a folder inside it has a choice of its own."""
    server, c, d, lol, rom = setup(env)
    make_dirs(rom, "exodos/eXo/!dos/Game A/Extras", "exodos/eXo/!dos/Game B", "exodos/keep/psx2")
    assert "collection/exodos/eXo/!dos/Game B" in rows(c.get("/api/romm?fresh=1").get_json())
    c.put("/api/romm/map", json={"path": "collection/exodos", "action": "exclude"})
    listed = []
    real = server.romm.os.scandir
    monkeypatch.setattr(server.romm.os, "scandir", lambda p: (listed.append(p), real(p))[1])
    d = c.get("/api/romm?fresh=1").get_json()
    r = rows(d)
    assert r["collection/exodos"]["value"] == "exclude"
    assert not any(k.startswith("collection/exodos/") for k in r), "nothing inside is listed"
    assert not any("/exodos/" in p for p in listed), "or read"
    # a choice inside the excluded folder: it has to be read again
    c.put("/api/romm/map", json={"path": "collection/exodos/keep", "action": "psx"})
    r = rows(c.get("/api/romm?fresh=1").get_json())
    assert r["collection/exodos/keep"]["value"] == "psx"
    assert r["collection/exodos/eXo/!dos/Game B"]["value"] == "exclude", "read again, and still left out"


def test_the_page_never_waits_on_the_disk(env, monkeypatch):
    """With background reads on, even the quick re-check after 30 s runs in the background."""
    server, c, d, lol, rom = setup(env)
    monkeypatch.setattr(server, "ROMM_BACKGROUND", True)
    c.get("/api/romm")
    server._romm_cache["at"] -= 60                                    # the list is a minute old
    assert c.get("/api/romm").get_json()["reading"], "the quick re-check runs in the background"
    for _ in range(100):
        if not c.get("/api/romm/progress").get_json()["running"]:
            break
        server.time.sleep(0.05)
    assert "rows" in c.get("/api/romm").get_json(), "then the list comes straight from memory"


def test_big_answers_are_compressed(env):
    import gzip
    server, c = env.start()
    plain = c.get("/api/romm/platforms")
    zipped = c.get("/api/romm/platforms", headers={"Accept-Encoding": "gzip, deflate"})
    assert "Content-Encoding" not in plain.headers
    assert zipped.headers["Content-Encoding"] == "gzip" and "Accept-Encoding" in zipped.headers["Vary"]
    assert json.loads(gzip.decompress(zipped.data)) == plain.get_json()
    assert len(zipped.data) < len(plain.data) / 3


def collection(env):
    """A RomM-style collection: one folder per system, some named like a RomM platform."""
    rom = env.path("roms", "collection")
    make_dirs(rom, "snes", "snes/media/box2d", "amigacdtv", "gbc", "gbc/+translations", "junk",
              "exodos/eXo/G1", "dc", "dc/BIOS", "sfc")
    server, c = env.start()
    c.put("/api/romm/options", json={"sources": [rom]})
    c.put("/api/romm/map", json={"path": "collection/amigacdtv", "action": "commodore-cdtv"})
    c.put("/api/romm/map", json={"path": "collection/exodos", "action": "exclude"})
    return server, c, rom


def mounts(d):
    """{platform: source folder} from the RomM volume lines (short and long syntax)."""
    out, src = {}, None
    for line in d["outputs"]["volumes"].splitlines():
        line = line.strip()
        if line.startswith('- "'):
            src_dst = json.loads(line[2:])
            source, target = src_dst.rsplit(":/romm/library/roms/", 1)
            out[target] = source
        elif line.startswith("source: "):
            src = json.loads(line[len("source: "):])
        elif line.startswith("target: "):
            out[json.loads(line[len("target: "):]).rsplit("/", 1)[1]] = src
    return out


def test_every_platform_folder_is_a_volume_of_romm(env):
    server, c, rom = collection(env)
    d = c.get("/api/romm").get_json()
    assert d["outputs"]["volumes"].startswith("    volumes:")
    assert mounts(d) == {"snes": os.path.join(rom, "snes"), "commodore-cdtv": os.path.join(rom, "amigacdtv"),
                         "gbc": os.path.join(rom, "gbc"), "dc": os.path.join(rom, "dc")}, "junk and exodos aren't"
    r = rows(d)
    assert r["collection/amigacdtv"]["used"] and r["collection/gbc/+translations"]["category"]
    assert not [n for n in os.listdir(env.config) if "mounts" in n], "nothing for a host script any more"
    d = c.put("/api/romm/map", json={"path": "collection/junk", "action": "psx"}).get_json()
    assert mounts(d)["psx"] == os.path.join(rom, "junk")


def test_a_folder_with_a_colon_gets_the_long_volume_syntax(env):
    """Compose's short syntax splits on ":" - a folder like "Sega: Classics" needs the long one."""
    server, c, rom = collection(env)
    make_dirs(rom, "Sega: Classics")
    c.get("/api/romm?fresh=1")
    d = c.put("/api/romm/map", json={"path": "collection/Sega: Classics", "action": "genesis"}).get_json()
    v = d["outputs"]["volumes"]
    assert "      - type: bind\n" in v and '"/romm/library/roms/genesis"' in v
    assert mounts(d)["genesis"] == os.path.join(rom, "Sega: Classics")
    assert f'- "{os.path.join(rom, "snes")}:/romm/library/roms/snes"' in v, "the others stay short"


def test_config_yml_has_categories_for_platforms_with_subfolders(env):
    """gbc/+translations belongs to gbc: gbc gets the category template, keyed by the slug."""
    server, c, rom = collection(env)
    y = c.get("/api/romm").get_json()["outputs"]["config"]
    fs = y.split("exclude:")[0]
    assert 'default: "roms/{platform}/{game}"' in fs and 'firmware: "bios/{platform}"' in fs
    assert '"gbc":\n      - "roms/{platform}/{game}"\n      - "roms/{platform}/{category}/{game}"' in fs
    assert '"snes":' not in fs and '"commodore-cdtv":' not in fs, "no subfolders of their own (media isn't read)"
    assert "\nsystem:" not in y and "  platforms:" not in y, "no renames or platform excludes"
    names = y.split("names:")[1]
    assert '- "media"' in names and '- "BIOS"' in names, "not games"
    # excluding the subfolder: no category any more
    d = c.put("/api/romm/map", json={"path": "collection/gbc/+translations", "action": "exclude"}).get_json()
    assert '"gbc":' not in d["outputs"]["config"].split("exclude:")[0]
    assert '- "+translations"' in d["outputs"]["config"]


def test_two_folders_with_one_platform_keep_the_one_named_like_it(env):
    server, c, rom = collection(env)
    d = c.put("/api/romm/map", json={"path": "collection/sfc", "action": "snes"}).get_json()
    assert mounts(d)["snes"] == os.path.join(rom, "snes")
    assert rows(d)["collection/sfc"]["conflict"] == "collection/snes"
    assert any("both set to snes" in w for w in d["warnings"])


def test_nested_folders_and_several_download_folders_are_mounted(env):
    """lolroms' Nintendo/Super Famicom can be a platform too; a subfolder that is its own platform
    (Satellaview) is a mount of its own and left out of its parent's games."""
    server, c, d, lol, rom = setup(env)
    m = mounts(d)
    assert m["satellaview"] == os.path.join(lol, "Nintendo", "Super Famicom", "Satellaview")
    assert m["snes"] == os.path.join(rom, "snes"), "collection/snes is named like the platform: it wins"
    assert m["n64"] == os.path.join(rom, "n64")
    assert rows(d)["lolroms/Nintendo/Super Famicom"]["conflict"] == "collection/snes"
    assert '- "Satellaview"' in d["outputs"]["config"]


def test_one_level_warns_about_categories(env):
    server, c, rom = collection(env)
    d = c.put("/api/romm/options", json={"depths": {rom: 1}}).get_json()
    assert any("1 level" in w and "+translations" in w for w in d["warnings"])
    assert '"gbc":' not in d["outputs"]["config"].split("exclude:")[0], "subfolders weren't read"



def test_old_platform_links_are_removed_and_nothing_else(env):
    """Older versions made platform links next to the download folder; the button removes only those."""
    server, c, rom = collection(env)
    links = env.path("roms")
    os.symlink("collection/snes", os.path.join(links, "snes"))            # one of ours
    os.symlink("collection/amigacdtv", os.path.join(links, "commodore-cdtv"))
    os.symlink("/somewhere/else", os.path.join(links, "psx"))              # someone else's
    os.makedirs(os.path.join(links, "gb"))                                 # a real folder
    d = c.get("/api/romm").get_json()
    assert d["old_links"] == 2
    d = c.post("/api/romm/links").get_json()
    assert sorted(d["applied"]["removed"]) == ["commodore-cdtv", "snes"] and d["old_links"] == 0
    assert os.readlink(os.path.join(links, "psx")) == "/somewhere/else"
    assert os.path.isdir(os.path.join(links, "gb")) and os.path.isdir(os.path.join(rom, "amigacdtv"))



def test_importing_the_old_romm_csv(env):
    """The one-time import of Rom_Mapping_RomM.csv (Folder,romm; BOM and Windows line endings)."""
    server, c, rom = collection(env)
    text = ("﻿Folder,romm\r\namigacdtv,commodore-cdtv\r\nsnes,snes\r\ngbc,\r\njunk,psx\r\n"
            "gone,n64\r\nweird,Not A Slug\r\nexodos,\r\n")
    d = c.post("/api/romm/import", data=text.encode("utf-8"), content_type="text/csv").get_json()
    r = d["imported"]
    assert r["imported"] == 3 and r["already"] == 1 and r["empty"] == 2
    assert r["missing"] == ["gone"] and r["invalid"] == ["weird: Not A Slug"]
    assert r["excluded"] == 1, "gbc is empty in the file: excluded, not picked up by its name"
    m = mounts(d)
    assert m["commodore-cdtv"] == os.path.join(rom, "amigacdtv") and m["psx"] == os.path.join(rom, "junk")
    assert "gbc" not in m
    saved = json.loads(env.read_config("romm-mapper.json"))["map"]
    assert saved["collection/amigacdtv"] == "commodore-cdtv" and "collection/snes" not in saved
    assert c.post("/api/romm/import", data="nonsense", content_type="text/csv").status_code == 400
