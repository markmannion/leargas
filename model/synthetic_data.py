"""Generate independent floor plans and gold questions; no dataset or model calls.

    python -m model.synthetic_data --out data/synthetic --plans 600

Requires Pillow and ezdxf (backend/requirements-dxf.txt). All variants of a layout
share a split. Gold answers come from the sampled scene, never from an engine.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import io
import json
import random
from pathlib import Path

VERSION = 1
STYLES = ("clean", "scan")
LABELS = ("Bedroom", "Kitchen", "Bathroom", "Living", "Office", "Storage")
GRIDS = ((2, 1), (3, 2), (4, 3), (5, 4))
DIFFICULTIES = ("easy", "medium", "hard", "dense")
FONT_PATHS = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
)


def font(size):
    from PIL import ImageFont
    for path in FONT_PATHS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def make_scene(index: int, seed: int) -> dict:
    rng = random.Random(f"{seed}:scene:{index}")
    difficulty = index % len(GRIDS)
    cols, rows = GRIDS[difficulty]
    widths = [rng.randint(30, 65) / 10 for _ in range(cols)]
    heights = [rng.randint(30, 60) / 10 for _ in range(rows)]
    ceiling = rng.randint(24, 34) / 10
    rooms, windows, doors = [], [], []
    y = 0.0
    # Some entire plans genuinely have no windows; zero is an answer, not a refusal.
    windowless = index % 13 == 0
    for row, h in enumerate(heights):
        x = 0.0
        for col, w in enumerate(widths):
            rid = f"1.{len(rooms) + 1:02d}"
            label = rng.choice(LABELS)
            rooms.append(dict(id=rid, label=label, x=x, y=y, w=w, h=h,
                              area=round(w * h, 2), ceiling=ceiling))
            # Doors connect each row through its first room, then adjacent columns.
            # The first door is the single external entrance.
            if col:
                doors.append(dict(x=x, y=y + h * .18, w=.16, h=.85,
                                  vertical=True, room_id=rid))
            else:
                doors.append(dict(x=x + w * .18, y=y, w=.85, h=.16,
                                  vertical=False, room_id=rid))
            if not windowless:
                sides = []
                if row == rows - 1:
                    sides.append("top")
                if col == cols - 1:
                    sides.append("right")
                for side in sides:
                    n = rng.randint(0, 2)
                    for j in range(n):
                        frac = (j + 1) / (n + 1)
                        if side == "top":
                            windows.append(dict(x=x + w * frac - .45, y=y + h - .08,
                                                w=.9, h=.16, room_id=rid))
                        else:
                            windows.append(dict(x=x + w - .08, y=y + h * frac - .45,
                                                w=.16, h=.9, room_id=rid))
            x += w
        y += h
    return dict(group_id=f"plan-{index:05d}", difficulty=DIFFICULTIES[difficulty],
                width=sum(widths), height=sum(heights), rooms=rooms,
                windows=windows, doors=doors, ceiling=ceiling)


def frame(scene: dict) -> dict:
    scale = min(1320 / scene["width"], 1010 / scene["height"])
    return dict(width=1600, height=1320, scale=scale,
                left=(1600 - scene["width"] * scale) / 2,
                bottom=1160)


def image_point(scene: dict, x: float, y: float) -> list[float]:
    f = frame(scene)
    return [round((f["left"] + x * f["scale"]) / f["width"], 6),
            round((f["bottom"] - y * f["scale"]) / f["height"], 6)]


def center(scene: dict, item: dict) -> list[float]:
    return image_point(scene, item["x"] + item["w"] / 2, item["y"] + item["h"] / 2)


def render(scene: dict, style: str, seed: int):
    from PIL import Image, ImageDraw, ImageFilter
    f = frame(scene)
    im = Image.new("RGB", (f["width"], f["height"]), "white")
    d = ImageDraw.Draw(im)
    ink = (20, 25, 30)

    def xy(x, y):
        p = image_point(scene, x, y)
        return p[0] * f["width"], p[1] * f["height"]

    def box(it):
        a = xy(it["x"], it["y"] + it["h"])
        b = xy(it["x"] + it["w"], it["y"])
        return (*a, *b)

    d.text((64, 30), "SYNTHETIC FLOOR PLAN / " + scene["group_id"], font=font(27), fill=ink)
    d.text((64, 71), f"Dimensions: metres | Ceiling height: {scene['ceiling']:.1f} m", font=font(22), fill=ink)
    for room in scene["rooms"]:
        d.rectangle(box(room), outline=ink, width=6)
    for it in scene["windows"]:
        b = box(it)
        d.rectangle(b, fill="white", outline=ink, width=2)
        if it["w"] > it["h"]:
            d.line((b[0], (b[1] + b[3]) / 2, b[2], (b[1] + b[3]) / 2), fill=ink, width=2)
        else:
            d.line(((b[0] + b[2]) / 2, b[1], (b[0] + b[2]) / 2, b[3]), fill=ink, width=2)
    for it in scene["doors"]:
        x, y, w, h = (it[k] for k in ("x", "y", "w", "h"))
        if it["vertical"]:
            hx, hy = xy(x, y)
            r = h * f["scale"]
            d.line((*xy(x, y), *xy(x, y + h)), fill="white", width=9)
            d.line((hx, hy, hx + r, hy), fill=ink, width=2)
            d.arc((hx - r, hy - r, hx + r, hy + r), 270, 360, fill=ink, width=2)
        else:
            hx, hy = xy(x, y)
            r = w * f["scale"]
            d.line((*xy(x, y), *xy(x + w, y)), fill="white", width=9)
            d.line((hx, hy, hx, hy - r), fill=ink, width=2)
            d.arc((hx - r, hy - r, hx + r, hy + r), 270, 360, fill=ink, width=2)
    for room in scene["rooms"]:
        cx, cy = xy(room["x"] + room["w"] / 2, room["y"] + room["h"] / 2)
        size = max(14, min(24, round(min(room["w"], room["h"]) * f["scale"] / 10)))
        lines = [f"{room['id']}  {room['label']}", f"{room['area']:.2f} m²",
                 f"{room['w']:.1f} x {room['h']:.1f} m"]
        for j, line in enumerate(lines):
            d.text((cx, cy + (j - 1) * (size + 5)), line, anchor="mm", font=font(size), fill=ink)
    d.text((64, 1220), "Symbols: windows = narrow double-line rectangles; doors = leaf + swing arc",
           font=font(20), fill=ink)
    d.text((64, 1255), "Room dimensions = horizontal x vertical. No wall thickness or structural specification supplied.",
           font=font(18), fill=ink)
    if style == "scan":
        # Mild resampling, paper tint and speckles; no cropping/occlusion/rotation.
        # Thus all gold point coordinates and numeric labels remain valid.
        rng = random.Random(f"{seed}:{scene['group_id']}:scan")
        im = im.resize((1280, 1056), Image.Resampling.BILINEAR).resize(im.size, Image.Resampling.BILINEAR)
        im = im.filter(ImageFilter.GaussianBlur(.35))
        tint = Image.new("RGB", im.size, (236, 232, 218))
        im = Image.blend(im, tint, .17)
        d = ImageDraw.Draw(im)
        for _ in range(2500):
            p = (rng.randrange(im.width), rng.randrange(im.height))
            d.point(p, fill=(rng.randrange(160, 225),) * 3)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=65)
        buf.seek(0)
        im = Image.open(buf).convert("RGB")
    return im


def write_dxf(scene: dict, path: Path) -> None:
    import ezdxf
    doc = ezdxf.new("R2010")
    doc.units = 6
    for layer in ("ROOM_OUTLINE", "UNIT_OUTLINE", "ROOM_TEXT", "WINDOW", "DOOR", "FIXTURE", "ANNOTATION"):
        doc.layers.new(layer)
    ms = doc.modelspace()
    # The current extractor gates on this literal convention name. This describes
    # compatibility, not provenance: no Swiss Dwellings source data is copied.
    ms.add_text("SYNTHETIC fixture; Swiss Dwellings layer convention; no source drawings used.",
                dxfattribs={"layer": "ANNOTATION", "insert": (0, -2), "height": .1})
    for room in scene["rooms"]:
        x, y, w, h = (room[k] for k in ("x", "y", "w", "h"))
        ms.add_lwpolyline([(x, y), (x+w, y), (x+w, y+h), (x, y+h)], close=True,
                          dxfattribs={"layer": "ROOM_OUTLINE"})
        for dy, text in ((.35, room["id"]), (0, room["label"]), (-.35, f"{room['area']:.2f} m²")):
            ms.add_text(text, dxfattribs={"layer": "ROOM_TEXT", "insert": (x+w/2, y+h/2+dy), "height": .15})
    for key, layer in (("windows", "WINDOW"), ("doors", "DOOR")):
        for it in scene[key]:
            x, y, w, h = (it[k] for k in ("x", "y", "w", "h"))
            ms.add_lwpolyline([(x, y), (x+w, y), (x+w, y+h), (x, y+h)], close=True,
                              dxfattribs={"layer": layer})
            if key == "windows":
                pts = [(x, y+h/2), (x+w, y+h/2)] if w > h else [(x+w/2, y), (x+w/2, y+h)]
                ms.add_lwpolyline(pts, dxfattribs={"layer": layer})
            else:
                radius = h if it["vertical"] else w
                ms.add_lwpolyline([(x, y), (x+radius, y) if it["vertical"] else (x, y+radius)],
                                  dxfattribs={"layer": layer})
                ms.add_arc((x, y), radius, 0, 90, dxfattribs={"layer": layer})
    doc.saveas(path)


def questions(scene: dict, style: str, split: str) -> list[dict]:
    rows = []
    path = f"data/synthetic/{scene['group_id']}_{style}.png"

    def add(question, answer, typ="count", unit="count", category="geometry", language="en", items=None):
        row = dict(id=f"{scene['group_id']}_{style}_q{len(rows):03d}", path=path,
                   question=question, answer=answer, type=typ, unit=unit,
                   expected="cannot_verify" if answer is None else "answer",
                   group_id=scene["group_id"], source="synthetic", split=split,
                   difficulty=scene["difficulty"], style=style, category=category, language=language)
        if items is not None:
            row["points"] = [center(scene, it) for it in items]
        rows.append(row)

    for key, noun in (("windows", "windows"), ("doors", "doors"), ("rooms", "rooms")):
        for q in (f"How many {noun} are shown on this floor plan?", f"Count all {noun} in the drawing."):
            add(q, len(scene[key]), items=scene[key])
    for language, q, key in (
        ("de", "Wie viele Fenster sind auf diesem Grundriss zu sehen?", "windows"),
        ("fr", "Combien de portes sont représentées sur ce plan ?", "doors"),
        ("fi", "Kuinka monta huonetta tässä pohjapiirroksessa on?", "rooms"),
        ("sv", "Hur många fönster finns på denna planritning?", "windows"),
    ):
        add(q, len(scene[key]), language=language, items=scene[key])
    # An absent category has count zero; an absent room's area is unverifiable.
    for label in ("Bedroom", "Kitchen", "Bathroom", "Garage"):
        matching = [r for r in scene["rooms"] if r["label"] == label]
        add(f'How many rooms labelled "{label}" are shown on this floor plan?', len(matching), items=matching)
    total = round(sum(r["area"] for r in scene["rooms"]), 2)
    add("What is the total area of all rooms in m²?", total, "area", "m2")
    add("What is the total area of all rooms in square feet?", total / .3048**2, "area", "ft2")
    # Up to eight individual areas per plan: labels and positions vary independently.
    for r in scene["rooms"][:8]:
        add(f"What is the area of room {r['id']} in m²?", r["area"], "area", "m2")
    for r in (scene["rooms"][0], scene["rooms"][-1]):
        add(f"What is the horizontal dimension of room {r['id']} in metres?",
            r["w"], "length", "m", "reasoning")
        add(f"What is the volume of room {r['id']} in m³ using its area and the printed ceiling height?",
            round(r["area"] * scene["ceiling"], 3), "volume", "m3", "reasoning")
    for q, typ, unit in (
        ("What is the area of room 9.99 in m²?", "area", "m2"),
        ("What is the volume of concrete in the foundations in m³?", "volume", "m3"),
        ("What is the thickness of the load-bearing walls in metres?", "length", "m"),
        ("How many electrical outlets are installed, including outlets not drawn on this plan?", "count", "count"),
    ):
        add(q, None, typ, unit, "abstention")
    return rows


def split_for(index: int, seed: int) -> str:
    # Difficulty-stratified stable assignment: each block has 10 plans per level.
    slots = list(range(10))
    random.Random(f"{seed}:split:{index % 4}:{index // 40}").shuffle(slots)
    slot = slots[(index // 4) % 10]
    return "train" if slot < 8 else "validation" if slot == 8 else "test"


def generate(out: Path, plans: int, seed: int, styles=STYLES) -> dict:
    if plans < 1 or not styles or len(set(styles)) != len(styles) or set(styles) - set(STYLES):
        raise ValueError("plans must be positive and styles must be unique clean/scan values")
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} is not empty; use a fresh output directory")
    images = out / "data" / "synthetic"
    images.mkdir(parents=True, exist_ok=True)
    (out / "splits").mkdir()
    counts = {key: collections.Counter() for key in ("split", "type", "category", "difficulty", "style", "language")}
    split_rows = collections.defaultdict(list)
    previews = []
    from PIL import Image, ImageDraw
    with (out / "questions.jsonl").open("w", encoding="utf-8") as gold, \
         (out / "scenes.jsonl").open("w", encoding="utf-8") as scenes:
        for index in range(plans):
            scene = make_scene(index, seed)
            split = split_for(index, seed)
            scene["split"] = split
            scenes.write(json.dumps(scene, ensure_ascii=False) + "\n")
            first_dxf = None
            for style in styles:
                path = images / f"{scene['group_id']}_{style}.png"
                im = render(scene, style, seed)
                im.save(path)
                dxf = path.with_suffix(".dxf")
                if first_dxf is None:
                    write_dxf(scene, dxf)
                    first_dxf = dxf
                else:
                    dxf.write_bytes(first_dxf.read_bytes())
                if index < 4:
                    thumb = im.copy()
                    thumb.thumbnail((480, 396))
                    previews.append((f"{scene['difficulty']} / {style}", thumb))
                for row in questions(scene, style, split):
                    line = json.dumps(row, ensure_ascii=False)
                    gold.write(line + "\n")
                    split_rows[split].append(line)
                    for key in counts:
                        counts[key][row[key]] += 1
            if (index + 1) % 50 == 0 or index + 1 == plans:
                print(f"Generated {index + 1}/{plans} layouts", flush=True)
    for split in ("train", "validation", "test"):
        (out / "splits" / f"{split}.jsonl").write_text("\n".join(split_rows[split]) + ("\n" if split_rows[split] else ""), encoding="utf-8")
    sheet = Image.new("RGB", (len(styles) * 480, min(plans, 4) * 430), "#eeeeee")
    draw = ImageDraw.Draw(sheet)
    for i, (title, thumb) in enumerate(previews):
        x, y = i % len(styles) * 480, i // len(styles) * 430
        sheet.paste(thumb, (x, y + 30))
        draw.text((x + 12, y + 5), title, fill="black", font=font(20))
    sheet.save(out / "preview.png")
    manifest = dict(version=VERSION, seed=seed, layouts=plans, drawings=plans * len(styles),
                    questions=sum(counts["split"].values()), styles=list(styles),
                    counts={k: dict(v) for k, v in counts.items()},
                    questions_sha256=hashlib.sha256((out / "questions.jsonl").read_bytes()).hexdigest(),
                    provenance="Procedurally generated; no real drawings or model-generated labels.",
                    split_unit="group_id (all PNG/DXF twins and scan variants stay together)",
                    scoring="Counts exact; numeric quantities within 2%; explicit refusals scored separately.")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (out / "README.md").write_text(
        f"# Synthetic drawing benchmark\n\n{plans} independent layouts, {manifest['drawings']} PNG drawings, "
        f"{manifest['questions']} labelled questions. Seed: {seed}.\n\n"
        "Gold answers are calculated from scenes.jsonl, independently of the model and geometry engine. "
        "DXF twins use the Swiss Dwellings layer convention for extractor compatibility; "
        "they are entirely synthetic and contain no source dataset material.\n\n"
        "questions.jsonl and splits/*.jsonl use dataset-relative paths rooted here. "
        "The split files are authoritative: do not re-split by PNG filename. "
        "All paraphrases and clean/scan variants of a layout share its group_id and split. "
        "Train/validation/test are 80/10/10 over complete 40-layout blocks, stratified by difficulty.\n\n"
        "Four room densities, variable dimensions, room labels, zero windows, English paraphrases, "
        "German/French/Finnish/Swedish questions, metric/imperial areas, dimension and volume reasoning, "
        "and four unanswerable questions per image. Count labels include normalized x,y points. "
        "The scan style adds mild blur, JPEG artifacts, tint and speckles without moving geometry.\n\n"
        "category=geometry identifies count/area questions; reasoning tests printed dimensions and height; "
        "abstention tests missing information. The current DXF engine supports only count/area. "
        "A vision model must read the PNG: never supply scenes, DXF, gold answers or metadata as model input.\n\n"
        "This is a controlled synthetic benchmark, not an estimate of real drawing accuracy. "
        "Repeated questions and scan variants are correlated; independent sample size is layouts. "
        "Keep test layouts out of training and continue using the real held-out raster benchmark.\n\n"
        "Run from the repository root (see model/README.md for more options):\n\n```bash\n"
        f".venv/bin/python -m model.synthetic_eval --data {out.as_posix()} --engine gemma-base --split test\n"
        f".venv/bin/python -m model.synthetic_eval --data {out.as_posix()} --engine geometry --split test --category geometry --language en\n"
        "```\n", encoding="utf-8")
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("data/synthetic"))
    ap.add_argument("--plans", type=int, default=600)
    ap.add_argument("--seed", type=int, default=20261114)
    ap.add_argument("--styles", nargs="+", choices=STYLES, default=list(STYLES))
    a = ap.parse_args()
    manifest = generate(a.out, a.plans, a.seed, a.styles)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
