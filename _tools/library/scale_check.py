"""Проверка масштаба моделей: сравнить размер из FBX с настоящим размером предмета («стул - 70-110 см
высотой»). Low-poly наборы часто сделаны не в сантиметрах: стул Kenney Furniture Kit - 4.7 м, дверь Kenney
Modular Buildings - 50 см, кровать KayKit - 3 м. В Unreal такая модель приезжает великаном или игрушкой.

Ошибка у набора обычно общая (одна единица на весь кит) - поэтому сначала ищется общий множитель набора
(источник + страница кита), и исправление - одной кнопкой на весь набор. Исправление не трогает файлы:
множитель хранится в _tools/_unreal_scale.json и применяется к размерам в окне и при импорте в Unreal
(Import Uniform Scale). Без Qt."""

import math
import re
import statistics

# (слова в имени, что мерить, от, до в см): h - высота, len - длина по полу, max - самый большой размер.
# Порядок важен: сначала частное («table lamp»), потом общее («table»).
RULES = [
    (r"\bbunk\b", "h", 140, 210),
    (r"\b(table|desk)[ _-]?lamp|lamp[ _-]?(table|desk)|lamp round table", "h", 25, 75),
    (r"\b(floor|standing)[ _-]?lamp|lamp[ _-]?(floor|standing)|lamp round floor", "h", 110, 210),
    (r"\b(street|lamp)[ _-]?post|streetlight|street light", "h", 300, 1200),
    (r"\bcoffee[ _-]?table|table[ _-]?coffee|table low", "h", 25, 60),
    (r"\bbed\b(?!.*\b(floor|flower|grass|river|sea|garden)\b)", "len", 180, 240),
    (r"\b(arm)?chair\b|\bchair[ _-]", "h", 65, 120),
    (r"\bstool\b", "h", 40, 85),
    (r"\bsofa\b|\bcouch\b|\blounge\b", "h", 55, 110),
    (r"\bbench\b", "h", 35, 100),
    (r"\b(table|desk)\b", "h", 60, 115),
    (r"\bdoor(way)?\b(?!.*(knob|handle|frame cap))", "h", 180, 290),
    (r"\btoilet\b", "h", 55, 95),
    (r"\b(bathtub|bath)\b", "len", 140, 200),
    (r"\b(fridge|refrigerator)\b", "h", 140, 210),
    (r"\b(bookcase|bookshelf|wardrobe|closet)\b", "h", 90, 240),
    (r"\bcoat[ _-]?rack\b", "h", 150, 200),
    (r"\b(rug|carpet)\b", "len", 80, 450),
    (r"\b(car|sedan|suv|taxi|police)\b(?!.*(wheel|tire|door|seat))", "len", 300, 560),
    (r"\b(truck|bus|van)\b(?!.*(wheel|tire|door|seat))", "len", 450, 1300),
    (r"\b(barrel)\b", "h", 50, 130),
    (r"\b(crate)\b", "max", 30, 160),
    (r"\b(mug|cup)\b", "h", 6, 16),
    (r"\b(bottle)\b", "h", 12, 45),
    (r"\b(plate)\b(?!.*(armor|metal|floor))", "len", 15, 35),
    (r"\b(apple|lime|lemon|kiwi|onion|tomato)\b|\b(fruit|food)\b.*\borange\b", "max", 4, 14),
    (r"\b(sword)\b", "max", 60, 150),
    (r"\b(coin)\b", "max", 1, 5),
    (r"\b(tree)\b(?!.*(stump|log|branch|trunk|small|sapling))", "h", 300, 4500),
    (r"\b(bush|shrub)\b", "max", 30, 400),
    (r"\b(fence)\b", "h", 60, 300),
]
# части и мелочи с «говорящим» словом в имени: колесо грузовика - не грузовик, обломок двери - не дверь
SKIP = re.compile(
    r"\b(debris|wheel|wheels|tire|tyre|part|piece|sign|icon|detail|decal|warning|handle|knob|frame|cap|"
    r"slice|slices|chopped|rings|half|broken|rotate|wall|gate|flower|platform)\b|\bfence door\b"
)
NICE = [0.01, 0.02, 0.025, 0.05, 0.1, 0.2, 0.25, 0.5, 2, 2.5, 2.54, 4, 5, 10, 20, 25, 50, 100]
OFF = 1.6  # во сколько раз за пределами нормы - уже «не тот масштаб»


def _rule(name):
    low = name.lower().replace("_", " ")
    if SKIP.search(low):
        return None
    for pat, axis, lo, hi in RULES:
        if re.search(pat, low):
            return axis, lo, hi
    return None


def measure(dims, axis):
    w, d, h = dims
    return h if axis == "h" else max(w, d) if axis == "len" else max(dims)


def nice(factor, value, lo, hi):
    """Красивый множитель (5, 0.2, 100...), если с ним размер попадает в норму, иначе - точный (2 знака)."""
    best = min(NICE, key=lambda f: abs(math.log(f / factor)))
    if lo <= value * best <= hi:
        return best
    return float(f"{factor:.2g}")


def pack_of(a):
    """Набор: одна единица измерения на весь кит - источник и страница кита."""
    return f"{a.get('source', '')}|{a.get('url') or a.get('theme', '')}"


def check(items):
    """-> {"items": [...], "packs": [...]}: модели не в своём масштабе и общие множители наборов."""
    rows = []
    for a in items:
        if a.get("kind") != "model" or a.get("rigged") or a.get("dimensions_mm"):  # у Poly Haven размеры настоящие
            continue
        dims = a.get("dims_cm")
        r = _rule(a.get("name", ""))
        if not dims or not r or max(dims) <= 0:
            continue
        axis, lo, hi = r
        v = measure(dims, axis)
        if v <= 0:
            continue
        mid = math.sqrt(lo * hi)
        rows.append(dict(a=a, value=v, lo=lo, hi=hi, axis=axis, exact=mid / v, bad=v < lo / OFF or v > hi * OFF))
    packs = {}
    for r in rows:
        packs.setdefault(pack_of(r["a"]), []).append(r)
    pack_out, in_pack = [], set()
    for key, rs in packs.items():
        bad = [r for r in rs if r["bad"]]
        if len(rs) < 3 or len(bad) < max(2, 0.6 * len(rs)):
            continue
        logs = [math.log(r["exact"]) for r in bad]
        med = statistics.median(logs)
        close = [r for r in bad if abs(math.log(r["exact"]) - med) < math.log(1.8)]
        if len(close) < 0.6 * len(bad):
            continue  # в наборе разнобой - чинить поштучно
        f = math.exp(med)
        snapped = min(NICE, key=lambda x: abs(math.log(x / f)))
        f = snapped if abs(math.log(snapped / f)) < math.log(1.35) else float(f"{f:.2g}")
        fixed = sum(1 for r in rs if r["lo"] <= r["value"] * f <= r["hi"])
        if fixed < 0.6 * len(rs):
            continue  # общий множитель чинит меньшинство - набор смешанный, поштучно
        pack_out.append(
            dict(
                pack=key,
                source=rs[0]["a"].get("source", ""),
                url=rs[0]["a"].get("url", ""),
                theme=rs[0]["a"].get("theme", ""),
                factor=f,
                checked=len(rs),
                wrong=len(bad),
                fixed=fixed,
                examples=[_example(r) for r in bad[:4]],
            )
        )
        in_pack.update(id(r["a"]) for r in rs)
    singles = []
    for r in rows:
        if r["bad"] and id(r["a"]) not in in_pack:
            singles.append(dict(_example(r), factor=nice(r["exact"], r["value"], r["lo"], r["hi"]), asset=r["a"]))
    pack_out.sort(key=lambda p: -p["wrong"])
    return dict(packs=pack_out, items=singles)


def _example(r):
    what = {"h": "высота", "len": "длина", "max": "размер"}[r["axis"]]
    return dict(
        name=r["a"].get("name", ""),
        id=r["a"].get("id", ""),
        what=what,
        cm=round(r["value"]),
        expected=f"{r['lo']}-{r['hi']}",
    )


def pack_members(items, key):
    """Все модели набора - множитель ставится на весь кит, а не только на проверенные по имени."""
    return [a for a in items if a.get("kind") == "model" and not a.get("dimensions_mm") and pack_of(a) == key]
