"""Planches de contrôle : les pages du PDF (controle/pages/page-NN.png) réunies 8 par image.
    /usr/bin/python3 controle/planches.py"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw

ICI = Path(__file__).resolve().parent
pages = sorted((ICI / "pages").glob("page-*.png"))
sortie = ICI / "planches"
sortie.mkdir(exist_ok=True)
for ancien in sortie.glob("*.png"):
    ancien.unlink()
par_planche, colonnes = 8, 4
for k in range(0, len(pages), par_planche):
    lot = [Image.open(p) for p in pages[k:k + par_planche]]
    w, h = lot[0].size
    lignes = (len(lot) + colonnes - 1) // colonnes
    planche = Image.new("RGB", (colonnes * (w + 10) + 10, lignes * (h + 30) + 10), "#808080")
    d = ImageDraw.Draw(planche)
    for i, im in enumerate(lot):
        x, y = 10 + (i % colonnes) * (w + 10), 10 + (i // colonnes) * (h + 30)
        planche.paste(im, (x, y + 20))
        d.text((x, y + 4), pages[k + i].stem, fill="white")
    planche.save(sortie / f"planche_{k // par_planche + 1:02d}.png")
print(f"{len(pages)} pages, {len(list(sortie.glob('*.png')))} planches dans {sortie}")
