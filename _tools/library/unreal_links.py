"""Страница со ссылками на наборы моделей, которые скачиваются только руками (itch.io): _Unreal/_Архивы/Ссылки.html.
Скачанные zip кладутся в ту же папку - «Добавить архивы» во вкладке Unreal разберёт их по темам."""

import html
import os

import imaging as K
from library import unreal_local as L

NOTES = {
    "https://kaylousberg.itch.io/kaykit-forest": "деревья, кусты, камни, трава",
    "https://kaylousberg.itch.io/kaykit-platformer": "платформы, препятствия, монеты - уровень для персонажа",
    "https://kaylousberg.itch.io/block-bits": "блоки в стиле Minecraft",
    "https://kaylousberg.itch.io/resource-bits": "дерево, камень, руда, слитки",
    "https://kaylousberg.itch.io/board-game-bits": "фишки, кубики, карты",
    "https://kaylousberg.itch.io/fantasy-weapons-bits": "мечи, топоры, луки, щиты",
    "https://kaylousberg.itch.io/rpg-tools-bits": "сундуки, зелья, свитки",
    "https://kaylousberg.itch.io/holiday-bits": "новогоднее",
    "https://kaylousberg.itch.io/mixed-bag-1": "всякое понемногу",
    "https://kaylousberg.itch.io/kaykit-medieval-builder-pack": "старый набор: средневековый город",
    "https://kaylousberg.itch.io/kay-kit-mini-game-variety-pack": "старый набор: мини-игры",
    "https://kaylousberg.itch.io/kaykit-spooktober": "старый набор: Хэллоуин",
    "https://kaylousberg.itch.io/kaykit-character-animations": "анимации для персонажей KayKit",
    "https://quaternius.itch.io/stylized-nature-megakit": "большой набор природы, с текстурами",
    "https://quaternius.itch.io/medieval-village-megakit": "модульные дома, стены, крыши",
    "https://quaternius.itch.io/modular-sci-fi-megakit": "коридоры, стены, двери космической базы",
    "https://quaternius.itch.io/downtown-city-megakit": "современный город: дома, улицы, машины",
    "https://quaternius.itch.io/fantasy-props-megakit": "бочки, столы, свечи, оружие",
    "https://quaternius.itch.io/sci-fi-essentials-kit": "sci-fi предметы и оружие",
    "https://quaternius.itch.io/universal-base-characters": "базовые персонажи под анимации",
    "https://quaternius.itch.io/universal-animation-library": "сотни анимаций (FBX, GLB)",
    "https://quaternius.itch.io/modular-character-outfits-fantasy": "одежда для персонажей (glTF)",
    "https://quaternius.itch.io/bestiary-dungeon-monsters-kit": "монстры подземелий",
    "https://quaternius.itch.io/3d-card-kit-fantasy": "3D-карты для настольной игры",
}


def page():
    rows = []
    for src, url, theme in L.known_list():
        title = url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").replace("kaykit ", "").title()
        rows.append(
            f'<tr><td><input type="checkbox"></td><td>{html.escape(src)}</td>'
            f'<td><a href="{html.escape(url)}" target="_blank">{html.escape(title)}</a></td>'
            f"<td>{html.escape(NOTES.get(url, ''))}</td><td>{html.escape(theme)}</td></tr>"
        )
    return f"""<!doctype html><meta charset="utf-8"><title>Модели для скачивания</title>
<style>
:root {{ --bg:#15151c; --panel:#1f1f29; --text:#e8e6f0; --dim:#9a98a8; --accent:#b8a4f0; }}
@media (prefers-color-scheme: light) {{ :root {{ --bg:#f6f5fa; --panel:#fff; --text:#1d1b26; --dim:#6b6878; --accent:#6a4fc4; }} }}
body {{ font:15px/1.5 system-ui, sans-serif; background:var(--bg); color:var(--text); margin:0; padding:24px 16px; }}
main {{ max-width:1000px; margin:auto; }}
h1 {{ font-size:22px; margin:0 0 8px; }}
p, li {{ color:var(--dim); }}
table {{ width:100%; border-collapse:collapse; background:var(--panel); border-radius:10px; overflow:hidden; }}
td, th {{ padding:8px 10px; text-align:left; border-bottom:1px solid rgba(128,128,128,.15); vertical-align:top; }}
th {{ font-size:13px; color:var(--dim); font-weight:600; }}
a {{ color:var(--accent); }}
.wrap {{ overflow-x:auto; }}
</style>
<main>
<h1>Модели, которые скачиваются руками</h1>
<p>Все наборы - CC0: можно в любые проекты, указывать автора не нужно. Отмеченное галкой нигде не сохраняется -
это просто памятка на время скачивания.</p>
<ol>
<li>Открыть ссылку, нажать <b>Download Now</b>; в окне с ценой - <b>No thanks, just take me to the downloads</b>
(или указать 0).</li>
<li>Скачать zip (если вариантов несколько - <b>Standard</b> или <b>FREE</b>) и положить в эту папку:
<code>{html.escape(L.DROP)}</code>.</li>
<li>В окне библиотеки: вкладка <b>Unreal</b> -> <b>Добавить архивы...</b> (или
<code>py -3.14 _tools/cli.py unreal archives</code>). Модели разложатся по темам, превью нарисуются сами,
разобранные архивы уйдут в <code>_разобрано</code>.</li>
</ol>
<p>Kenney, Poly Haven, KayKit с GitHub и наборы Quaternius с Google Drive качаются сами - «Скачать ещё...».</p>
<div class="wrap"><table>
<tr><th></th><th>Автор</th><th>Набор</th><th>Что внутри</th><th>Тема в библиотеке</th></tr>
{"".join(rows)}
</table></div>
</main>"""


def write():
    os.makedirs(L.DROP, exist_ok=True)
    path = os.path.join(L.DROP, "Ссылки.html")
    K.write_atomic(path, page(), "utf-8")
    return path


if __name__ == "__main__":
    print(write())
