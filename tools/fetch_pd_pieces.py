"""Public-domain piano pieces for the Atlas, from the Mutopia Project (mutopiaproject.org)
and, where Mutopia has nothing Public Domain, the PDMX dataset of MuseScore scores.

    python tools/fetch_pd_pieces.py inventory     list Mutopia's piano pieces by graded-repertoire
                                                  composers -> ~/MidiCoach/atlas/source/mutopia.json
    python tools/fetch_pd_pieces.py tables        add Mutopia's composer tables to that inventory (its
                                                  name search misses pieces)
    python tools/fetch_pd_pieces.py pdmx <mid.tar.gz> <PDMX.csv>
                                                  extract the catalog's PDMX pieces (files from
                                                  https://zenodo.org/records/15571083) with their licence rows
    python tools/fetch_pd_pieces.py fetch         download the pieces in midi_coach/atlas/data/pieces.json,
                                                  keep only Public Domain ones, write each as checked
                                                  MusicXML to ~/MidiCoach/atlas/pieces/
    python tools/fetch_pd_pieces.py calibrate     re-measure the fetched pieces and fit the difficulty
                                                  model (midi_coach/atlas/data/difficulty_model.json)

Only pieces whose Mutopia licence is exactly "Public Domain" are used (not Creative Commons
ones); from PDMX, only CC0 or Public Domain Mark scores with no licence conflict, by a
composer who died before 1955. Each piece's MusicXML records its source URL, licence and fetch date in
<identification><source>, and the catalog keeps the sha1 of the downloaded MIDI so a
re-fetch can tell it is the same file. Uses fetch_alternates.get (polite, with retries).
"""

from __future__ import annotations

import html
import json
import pathlib
import re
import sys
import time
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from fetch_alternates import get  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
HOME = pathlib.Path.home() / "MidiCoach" / "atlas"
SITE = "https://www.mutopiaproject.org/cgibin/make-table.cgi"
COMPOSERS = ["Bach", "Handel", "Scarlatti", "Couperin", "Rameau", "Purcell", "Telemann", "Haydn", "Mozart", "Clementi",
             "Kuhlau", "Diabelli", "Türk", "Beethoven", "Czerny", "Burgmüller", "Gurlitt", "Köhler", "Streabbog", "Heller",
             "Schumann", "Mendelssohn", "Schubert", "Chopin", "Tchaikovsky", "Grieg", "Satie", "Debussy", "Joplin",
             "Duvernoy", "Lemoine", "Concone", "Bartók", "Reinagle", "Hook", "Attwood", "Dussek", "Kirnberger", "Krebs",
             "Field", "Liszt", "Brahms", "Fauré", "Granados", "Albéniz", "MacDowell", "Gade", "Lyadov", "Rebikov"]
# Mutopia's own composer codes (browse.html). Its name search misses many pieces (umlauts,
# 'J. F. F. Burgmüller'), so the composer tables are read as well.
TABLE_COMPOSERS = ["BurgmullerJFF", "DiabelliA", "SchumannR", "MozartWA", "CzernyC", "HaydnFJ", "BeethovenLv", "ChopinFF",
                   "GriegE", "TchaikovskyPI", "SchubertF", "HandelGF", "CouperinF", "TelemannGP", "PurcellH", "RameauJP",
                   "ScarlattiD", "KuhlauF", "ClementiM", "DussekJL", "MuellerAE", "FuchsR", "SatieE", "DebussyC", "GranadosE",
                   "AlbenizIMF", "DvorakA", "BrahmsJ", "MussorgskyM", "FieldJ", "ScriabinA", "FaureG", "RegerM", "VolkmannR",
                   "KuhnauJ", "PachelbelJ", "JoplinS", "BartokB", "ElgarE", "FranckC", "ChabrierEA", "LisztF", "AlkanCV",
                   "StanchinskyAV", "KopylovA", "GlazunovA", "SilcherF", "BendaJA", "PleyelIJ", "RiesF"]
MAX_PAGES = 40
BAROQUE ={"Bach", "Handel", "Scarlatti", "Couperin", "Rameau", "Purcell", "Telemann", "Kirnberger", "Krebs"}
KEYBOARDS = {"piano", "pianoforte", "fortepiano", "harpsichord", "clavichord", "keyboard", "piano solo", "virginal", "spinet"}


def solo_keyboard(for_text: str) -> bool:
    """'for Piano, Pianoforte, Harpsichord' yes; 'for Voice, Piano' or 'for Piano (4 hands)' no."""
    words = [w.strip().lower() for w in re.split(r",| and | or ", for_text.replace("for ", "", 1))]
    return bool(words) and all(w in KEYBOARDS for w in words if w)


def _cells(block: str) -> list[str]:
    return [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", block, re.S)]


def parse(page: str) -> list[dict]:
    """One make-table.cgi result page -> its pieces."""
    out = []
    for block in page.split('<table class="table-bordered result-table">')[1:]:
        block = block.split("</table>")[0]
        cells = _cells(block)
        links = re.findall(r'href="([^"]+)"', block)
        lic = re.search(r'legal\.html#[^"]*">([^<]+)</a>', block)
        info = re.search(r"piece-info\.cgi\?id=(\d+)", block)
        by = re.match(r"by (.*?)\s*\(([^)]*)\)", cells[1]) if len(cells) > 1 else None
        dates = re.findall(r"\d{4}", by.group(2)) if by else []
        out.append({
            "id": int(info.group(1)) if info else None,
            "title": cells[0] if cells else "",
            "composer": by.group(1) if by else (cells[1] if len(cells) > 1 else ""),
            "born": int(dates[0]) if dates else None,
            "died": int(dates[1]) if len(dates) > 1 else None,
            "opus": cells[2] if len(cells) > 2 else "",
            "for": cells[4] if len(cells) > 4 else "",
            "style": cells[6] if len(cells) > 6 else "",
            "licence": lic.group(1).strip() if lic else "",
            "mid": next((l for l in links if l.endswith(".mid")), None),
            "mids_zip": next((l for l in links if l.endswith(".zip") and "mid" in l.lower()), None),
            "ly": next((l for l in links if l.endswith(".ly")), None),
            "folder": next((l for l in links if l.endswith("/") and "/ftp/" in l), None),
        })
    return out


def inventory(composers: list[str] | None = None) -> list[dict]:
    """Every solo piano piece Mutopia lists for these composers (searched by name)."""
    seen: dict[int, dict] = {}
    for name, instrument in [(n, i) for n in composers or COMPOSERS for i in (("Piano", "Harpsichord", "Clavichord") if n in BAROQUE else ("Piano",))]:
        for page in range(MAX_PAGES):
            q = urllib.parse.urlencode({"searchingfor": name, "Instrument": instrument, "startat": page * 10})
            raw = get(f"{SITE}?{q}")
            if raw is None:
                break
            found = parse(raw.decode("utf-8", errors="replace"))
            if not found:
                break
            for p in found:
                if p["id"] and p["id"] not in seen and solo_keyboard(p["for"]):
                    seen[p["id"]] = p
            print(f"  {name} ({instrument}): page {page + 1}, {len(seen)} so far", flush=True)
            if len(found) < 10:
                break
    return sorted(seen.values(), key=lambda p: (p["composer"], p["title"]))


def inventory_tables(codes: list[str] | None = None) -> list[dict]:
    """Every solo keyboard piece in these Mutopia composer tables (make-table.cgi?Composer=...)."""
    seen: dict[int, dict] = {}
    for code in codes or TABLE_COMPOSERS:
        for page in range(MAX_PAGES):
            raw = get(f"{SITE}?{urllib.parse.urlencode({'startat': page * 10, 'Composer': code})}")
            found = parse(raw.decode("utf-8", errors="replace")) if raw else []
            for p in found:
                if p["id"] and p["id"] not in seen and solo_keyboard(p["for"]):
                    seen[p["id"]] = p
            if len(found) < 10:
                break
        print(f"  {code}: {len(seen)} so far", flush=True)
    return sorted(seen.values(), key=lambda p: (p["composer"], p["title"]))


def _compare_notes(source, written, tol: float) -> tuple[int, int]:
    """Notes of the source not found in the written score (same pitch, onset within tol
    beats), and the other way round. A unison struck by both hands at once is one key."""
    def keys(notes):
        seen = set()
        for n in sorted(notes, key=lambda n: (n.beat, n.pitch)):
            k = (round(n.beat, 3), n.pitch)
            if k not in seen:
                seen.add(k)
        return sorted(seen)

    a, b = keys(source), keys(written)

    def unmatched(xs, ys):
        by_pitch: dict[int, list[float]] = {}
        for beat, p in ys:
            by_pitch.setdefault(p, []).append(beat)
        return sum(1 for beat, p in xs if not any(abs(beat - y) <= tol for y in by_pitch.get(p, [])))

    return unmatched(a, b), unmatched(b, a)


def _from_mutopia(entry: dict, inv: dict) -> dict | str:
    """The piece's MIDI and source facts from Mutopia (licence checked in its .rdf), or a problem."""
    from midi_coach.atlas import pieces

    info = inv.get(entry["mutopia"])
    if not info or not (info.get("mid") or info.get("mids_zip")):
        return "not in the inventory, or no MIDI"
    base = (info.get("folder") or (info.get("mid") or info["mids_zip"]).rsplit("/", 1)[0] + "/").rstrip("/")
    rdf = ""
    listing = get(base + "/")  # the folder's file list names its .rdf
    names = re.findall(r'href="([^"?/]+\.rdf)"', listing.decode("utf-8", errors="replace")) if listing else []
    for name in names[:1] or ([info["ly"].rsplit("/", 1)[1].replace(".ly", ".rdf")] if info.get("ly") else []):
        raw = get(f"{base}/{name}")
        rdf = raw.decode("utf-8", errors="replace") if raw else ""
    lic = re.search(r"<mp:licence>([^<]*)</mp:licence>", rdf or "")
    if not lic or lic.group(1).strip() != "Public Domain":
        return f"licence {lic.group(1) if lic else 'unknown'} (only Public Domain is used)"
    data = get(info["mid"]) if info.get("mid") else None
    member = None
    if data is None and info.get("mids_zip"):  # a work in several movements: one of its MIDI files
        import io
        import zipfile

        raw = get(info["mids_zip"])
        if raw:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                names = sorted(n for n in z.namelist() if n.lower().endswith(".mid"))
                member = entry.get("member") or (names[0] if names else None)
                data = z.read(member) if member in names else None
    if not data:
        return "download failed" + (f" (no {entry.get('member')} in the zip)" if entry.get("member") else "")
    info_url = f"https://www.mutopiaproject.org/cgibin/piece-info.cgi?id={entry['mutopia']}"
    ly = get(info["ly"]) if info.get("ly") else None  # the LilyPond source says whether it starts with an upbeat
    return {"data": data, "title": info["title"], "composer": info["composer"], "died": info["died"], "opus": info["opus"],
            "member": member, "licence": lic.group(1).strip(), "source_url": info.get("mid") or info["mids_zip"], "info_url": info_url,
            "credit": f"{info['title']}{' (' + member + ')' if member else ''}, {info['composer']}: Mutopia Project piece "
                      f"{entry['mutopia']} ({info_url}), {lic.group(1).strip()}",
            "pickup": pieces.partial_beats(ly.decode("utf-8", errors="replace")) if ly else None}


# PDMX (Long et al. 2024, https://zenodo.org/records/15571083, the collection under CC BY 4.0):
# scores from MuseScore whose uploaders marked them CC0 or Public Domain. That label is
# self-declared, so only rows with no licence conflict and a composer who died before 1955
# are used, and the licence is re-checked against PDMX.csv when the MIDI is extracted.
PDMX_RECORD = "https://zenodo.org/records/15571083"
PDMX_LICENCES = {"cc-zero": "CC0 1.0", "publicdomain": "Public Domain Mark 1.0"}


def _from_pdmx(entry: dict) -> dict | str:
    """The piece's MIDI and source facts from the extracted PDMX files (tools/fetch_pd_pieces.py pdmx)."""
    path = HOME / "source" / "pdmx" / f"{entry['pdmx_id']}.mid"
    meta = HOME / "source" / "pdmx" / f"{entry['pdmx_id']}.json"
    if not path.is_file() or not meta.is_file():
        return "not extracted yet (run: tools/fetch_pd_pieces.py pdmx <mid.tar.gz> <PDMX.csv>)"
    from midi_coach.atlas import pieces
    from midi_coach.notes import load_score

    row = json.loads(meta.read_text(encoding="utf-8"))
    if row["licence"] not in PDMX_LICENCES.values() or row["license_conflict"] or not entry.get("died") or entry["died"] >= 1955:
        return f"licence {row['licence']} / conflict {row['license_conflict']} / died {entry.get('died')} (CC0 or PD, no conflict, died before 1955)"
    return {"data": path.read_bytes(), "title": entry["title"], "composer": entry["composer"], "died": entry["died"], "opus": entry.get("opus", ""),
            "member": None, "licence": row["licence"], "source_url": f"{PDMX_RECORD} (mid.tar.gz: {row['mid']})", "info_url": PDMX_RECORD,
            "credit": f"{row['title']}, {entry['composer']}: MuseScore score from the PDMX dataset ({PDMX_RECORD}, {row['mid']}), "
                      f"marked {row['licence']} by its uploader",
            "pickup": pieces.upbeat_bar(load_score(path))}  # MuseScore writes an upbeat as a short first bar


def extract_pdmx(archive: pathlib.Path, csv_path: pathlib.Path) -> dict:
    """Pull the catalog's PDMX pieces out of mid.tar.gz, each with its PDMX.csv row (licence,
    conflict flag) beside it in <home>/atlas/source/pdmx/."""
    import csv
    import tarfile

    sys.path.insert(0, str(REPO))
    from midi_coach.atlas import pieces

    wanted = {p["pdmx"]: p for p in pieces.load_catalog() if p.get("pdmx")}
    out_dir = HOME / "source" / "pdmx"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv.field_size_limit(10**8)
    rows = {}
    with open(csv_path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row["mid"] in wanted:
                rows[row["mid"]] = row
    found = 0
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            name = member.name if member.name.startswith("./") else "./" + member.name  # PDMX.csv writes ./mid/...
            if name not in wanted or not member.isfile() or name not in rows:
                continue
            entry, row = wanted[name], rows[name]
            (out_dir / f"{entry['pdmx_id']}.mid").write_bytes(tar.extractfile(member).read())  # our own file name, never the archive's path
            (out_dir / f"{entry['pdmx_id']}.json").write_text(json.dumps({
                "title": row["title"], "composer_name": row["composer_name"], "mid": row["mid"],
                "licence": PDMX_LICENCES.get(row["license"], row["license"]), "license_url": row["license_url"],
                "license_conflict": row["license_conflict"] == "True"}, indent=1, ensure_ascii=False), encoding="utf-8")
            found += 1
    return {"wanted": len(wanted), "extracted": found, "missing": sorted(set(wanted) - set(rows))}


def fetch_all(force: bool = False) -> dict:
    """Get every catalog piece (midi_coach/atlas/data/pieces.json) that isn't here yet, from
    Mutopia or the extracted PDMX files: licence checked, MIDI kept with its sha1, written out
    as MusicXML, checked (notes read back, 'published' engraving profile), and its features
    measured."""
    import hashlib

    sys.path.insert(0, str(REPO))
    from midi_coach import engraving
    from midi_coach.atlas import difficulty, pieces
    from midi_coach.notes import load_score

    inv = {p["id"]: p for p in json.loads((HOME / "source" / "mutopia.json").read_text(encoding="utf-8"))["pieces"]}
    catalog = pieces.load_catalog()
    report = {"fetched": 0, "kept": 0, "problems": []}
    for entry in catalog:
        mid_path = pieces.pieces_dir() / f"{entry['id']}.mid"
        xml_path = pieces.pieces_dir() / f"{entry['id']}.musicxml"
        if xml_path.is_file() and not force:
            report["kept"] += 1
            continue
        got = _from_pdmx(entry) if entry.get("pdmx") else _from_mutopia(entry, inv)
        if isinstance(got, str):
            report["problems"].append(f"{entry['id']}: {got}")
            continue
        data, info, member, pickup = got["data"], got, got["member"], got["pickup"]
        mid_path.write_bytes(data)
        sha1 = hashlib.sha1(data).hexdigest()
        source = (f"{got['credit']}. MIDI fetched {time.strftime('%Y-%m-%d')} (sha1 {sha1[:12]}) and written out "
                  "as notation with every note and rhythm kept; hands from the source's staves.")
        try:
            out = pieces.to_musicxml(mid_path, entry.get("title") or info["title"], info["composer"], source, pickup=pickup)
        except Exception as exc:
            report["problems"].append(f"{entry['id']}: could not write it out ({exc})")
            continue
        xml_path.write_text(out["xml"], encoding="utf-8")
        source_notes = load_score(mid_path).notes
        written = load_score(xml_path).notes
        lint = engraving.lint(out["xml"], profile="published")
        problems = []
        missing, extra = _compare_notes(source_notes, written, tol=0.13)
        if not out["snapped"]:  # exact: only the ornament notes may have moved
            strict = _compare_notes(source_notes, written, tol=0.02)
            if max(strict) > out["ornaments"]:
                missing, extra = strict
        if missing or extra:
            problems.append(f"notes differ ({missing} missing, {extra} extra)")
        if lint["findings"]:
            problems.append(f"engraving: {lint['findings'][:3]}")
        if problems:
            report["problems"].append(f"{entry['id']}: " + "; ".join(problems))
            xml_path.unlink()
            continue
        entry.update(title=entry.get("title") or info["title"], composer=info["composer"], member=member, died=info["died"], opus=info["opus"],
                     licence=got["licence"], source_url=got["source_url"], info_url=got["info_url"], sha1=sha1, bars=out["bars"],
                     lint_exempt=lint["exempt"], fetched=time.strftime("%Y-%m-%d"), snapped=out["snapped"], ornaments=out["ornaments"],
                     first_bar=out["first_bar"], pickup=float(pickup) if pickup else None,
                     features=difficulty.features(xml_path))
        report["fetched"] += 1
        print(f"  {entry['id']}: {info['title']} ({out['bars']} bars)", flush=True)
    pieces.save_catalog(catalog)
    return report


def calibrate(ridge: float = 8.0) -> dict:
    """Re-measure every fetched piece, fit the difficulty model and save it. Only grades an exam
    board set (grade_source "exam boards") are fitted on, once there are 20 of them: fitting on
    the coach's own estimates would only teach the model to agree with itself."""
    sys.path.insert(0, str(REPO))
    from midi_coach.atlas import difficulty, pieces

    catalog = pieces.load_catalog()
    rows, boards = [], []
    for entry in catalog:
        path = pieces.fetched(entry)
        if not path:
            continue
        entry["features"] = difficulty.features(path)
        row = (entry["features"], 0 if entry["grade"] == "initial" else int(entry["grade"][1:]))
        rows.append(row)
        if entry.get("grade_source") == "exam boards":
            boards.append(row)
    fitted_on = "exam boards" if len(boards) >= 20 else "all catalog grades"
    model = difficulty.calibrate(boards if fitted_on == "exam boards" else rows, ridge=ridge)
    model["ridge"] = ridge
    model["fitted_on"] = fitted_on
    difficulty.MODEL_PATH.write_text(json.dumps(model, indent=1) + "\n", encoding="utf-8")
    pieces.save_catalog(catalog)
    return model


def main(argv: list[str]) -> None:
    cmd = argv[0] if argv else "inventory"
    if cmd == "inventory":
        HOME.joinpath("source").mkdir(parents=True, exist_ok=True)
        pieces = inventory(argv[1:] or None)
        path = HOME / "source" / "mutopia.json"
        path.write_text(json.dumps({"fetched": time.strftime("%Y-%m-%d"), "pieces": pieces}, indent=1, ensure_ascii=False), encoding="utf-8")
        pd = sum(1 for p in pieces if p["licence"] == "Public Domain")
        print(f"{len(pieces)} piano pieces ({pd} Public Domain) -> {path}")
    elif cmd == "tables":  # add the composer tables to the inventory
        path = HOME / "source" / "mutopia.json"
        known = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"pieces": []}
        ids = {p["id"] for p in known["pieces"]}
        added = [p for p in inventory_tables(argv[1:] or None) if p["id"] not in ids]
        known.update(fetched=time.strftime("%Y-%m-%d"),
                     pieces=sorted(known["pieces"] + added, key=lambda p: (p["composer"], p["title"])))
        path.write_text(json.dumps(known, indent=1, ensure_ascii=False), encoding="utf-8")
        pd = sum(1 for p in added if p["licence"] == "Public Domain")
        print(f"{len(added)} more piano pieces ({pd} Public Domain) -> {path}")
    elif cmd == "pdmx":  # pdmx <mid.tar.gz> <PDMX.csv>
        report = extract_pdmx(pathlib.Path(argv[1]), pathlib.Path(argv[2]))
        print(f"{report['extracted']} of {report['wanted']} PDMX pieces extracted -> {HOME / 'source' / 'pdmx'}")
        for name in report["missing"]:
            print("   not in PDMX.csv:", name)
    elif cmd == "fetch":
        report = fetch_all(force="--force" in argv)
        print(f"{report['fetched']} fetched, {report['kept']} already here; {len(report['problems'])} problems")
        for prob in report["problems"]:
            print("  ", prob)
    elif cmd == "calibrate":
        model = calibrate()
        print(f"{model['pieces']} pieces ({model['fitted_on']}), leave-one-out: whole-piece grade within one grade "
              f"{model['within_one_grade']:.0%}, mean error {model['mean_error']}; playing grade "
              f"{model['playing_within_one_grade']:.0%}, {model['playing_mean_error']}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
