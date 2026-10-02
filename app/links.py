"""Building the frontend folders: one link per mapped folder (replaces rom-mapper.sh).

For every row and frontend with a name:
    <mapping folder>/<frontend>/<name>  ->  <source folder>/<path>              (absolute link)
and, when the frontend links media folders and <source>/media exists:
    <mapping folder>/<frontend>/<media location>/<name without its first part>/media
                                        ->  <source folder>/<path>/media
(the same layout rom-mapper.sh made; media location defaults to MEDIA_FULL). When two rows give
one frontend the same name, the first row gets the link.

Unlike the script, a resync changes only what differs: missing links are made, links pointing
somewhere else are corrected, links nobody wants any more are removed, and everything else is left
alone - so frontends never see an empty folder while it runs. Only symlinks are ever removed; a
real file or folder inside the mapping folder is reported and kept.
"""
from __future__ import annotations

import os

MEDIA_DEFAULT = "MEDIA_FULL"
FORBIDDEN_DEST = {"", "/", "/mnt", "/mnt/user", "/mnt/disks", "/mnt/cache", "/config"}


def check_dest(dest: str, source_paths) -> str | None:
    """Why the mapping folder can't be used, or None."""
    d = os.path.abspath(dest) if dest else ""
    if not dest or d in FORBIDDEN_DEST:
        return f"Refusing to use the mapping folder {dest!r} - pick a dedicated folder."
    for s in source_paths:
        s = os.path.abspath(s)
        if d == s or d.startswith(s + os.sep):
            return f"The mapping folder {dest} is inside the source folder {s} - pick another one."
        if s.startswith(d + os.sep):
            return f"The source folder {s} is inside the mapping folder {dest} - pick another one."
    return None


def desired_links(mapping: dict, dest: str, resolve) -> tuple:
    """-> ({link path: target}, [notes]). `resolve(folder key)` gives the folder on disk or None."""
    want: dict = {}
    notes: list = []
    fes = mapping["frontends"]
    for row in mapping["rows"]:
        src = resolve(row["folder"])
        if not src or not os.path.isdir(src):
            continue                                   # missing on disk: its links wait for it
        for fe, raw in zip(fes, row["values"]):
            name = (raw or "").strip()
            if not name:
                continue
            link = os.path.join(dest, fe["name"], *name.split("/"))
            if link in want:
                notes.append(f"{fe['name']}/{name}: already given to another folder - {row['folder']} skipped")
            else:
                want[link] = src
            if fe.get("media_toggle") == "1":
                media = os.path.join(src, "media")
                if os.path.isdir(media):
                    rel = name.split("/", 1)[1] if "/" in name else name
                    mlink = os.path.join(dest, fe["name"], fe.get("media_location") or MEDIA_DEFAULT,
                                         *rel.split("/"), "media")
                    want.setdefault(mlink, media)
    return want, notes


def apply(want: dict, dest: str) -> dict:
    """Make the mapping folder match `want`. -> {created, updated, removed, kept, problems}"""
    res = {"created": 0, "updated": 0, "removed": 0, "kept": 0, "problems": []}
    dest = os.path.abspath(dest)
    os.makedirs(dest, exist_ok=True)
    real_dest = os.path.realpath(dest)

    for link, target in sorted(want.items()):
        parent = os.path.dirname(link)
        # never create folders through a link (that would write into a source folder)
        probe = parent
        while probe != dest and not os.path.lexists(probe):
            probe = os.path.dirname(probe)
        if not os.path.realpath(probe).startswith(real_dest):
            res["problems"].append(f"{os.path.relpath(link, dest)}: its folder is a link to another place - skipped")
            continue
        try:
            os.makedirs(parent, exist_ok=True)
            if os.path.islink(link):
                if os.readlink(link) == target:
                    res["kept"] += 1
                    continue
                os.remove(link)
                os.symlink(target, link)
                res["updated"] += 1
            elif os.path.lexists(link):
                res["problems"].append(f"{os.path.relpath(link, dest)}: a real file or folder is in the way - left alone")
            else:
                os.symlink(target, link)
                res["created"] += 1
        except OSError as e:
            res["problems"].append(f"{os.path.relpath(link, dest)}: {e.strerror or e}")

    # remove links nobody wants any more, then folders left empty (never the mapping folder itself)
    stray = 0
    for root, dirs, files in os.walk(dest, topdown=False):
        for name in dirs + files:
            p = os.path.join(root, name)
            if os.path.islink(p):
                if p not in want:
                    try:
                        os.remove(p)
                        res["removed"] += 1
                    except OSError as e:
                        res["problems"].append(f"{os.path.relpath(p, dest)}: {e.strerror or e}")
            elif name in files:
                stray += 1
        if root != dest:
            try:
                os.rmdir(root)                     # only succeeds when it's empty
            except OSError:
                pass
    if stray:
        res["problems"].append(f"{stray} file(s) in the mapping folder aren't links - left alone")
    return res


def describe(res: dict) -> str:
    out = (f"{res['created']} links created, {res['updated']} corrected, {res['removed']} removed, "
           f"{res['kept']} unchanged")
    if res["problems"]:
        out += f"; {len(res['problems'])} problem(s)"
    return out
