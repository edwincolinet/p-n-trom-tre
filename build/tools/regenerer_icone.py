"""Régénère `assets/Icone.png` (1024×1024) depuis l'ancienne source 62×100.

La source d'origine (la feuille Silvavenir, 62×100 px) est trop petite : agrandie
à 256 px pour l'icône Windows, elle apparaît très pixélisée. Ce script :
  1. lisse la SILHOUETTE de la feuille (agrandissement ×16, flou, seuil) ;
  2. redessine le « a » blanc en vectoriel avec Jost Bold (police de la charte).
À n'exécuter que si la source `assets/Icone_source_62x100.png` change ; le
résultat versionné est `assets/Icone.png`.

Usage : python build/tools/regenerer_icone.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SRC = Path("assets/Icone_source_62x100.png")
OUT = Path("assets/Icone.png")
FONT = Path("assets/fonts/Jost-Bold.ttf")
VERT = (67, 160, 58, 255)      # vert de la feuille d'origine
TAILLE = 1024
K = 16                          # facteur d'agrandissement de la silhouette


def main() -> None:
    src = Image.open(SRC).convert("RGBA")
    w, h = src.size
    alpha = src.getchannel("A").resize((w * K, h * K), Image.BICUBIC)
    alpha = alpha.filter(ImageFilter.GaussianBlur(K * 0.9))
    masque = alpha.point(lambda v: 255 if v >= 110 else 0)
    # Lisser les bords (anti-crénelage) : réduction depuis une version ×2.
    masque = masque.filter(ImageFilter.GaussianBlur(2))

    # Feuille mise à l'échelle pour occuper ~94 % de la hauteur du canevas.
    cible_h = int(TAILLE * 0.94)
    cible_w = round(masque.width * cible_h / masque.height)
    masque = masque.resize((cible_w, cible_h), Image.LANCZOS)
    canevas = Image.new("RGBA", (TAILLE, TAILLE), (0, 0, 0, 0))
    ox, oy = (TAILLE - cible_w) // 2, (TAILLE - cible_h) // 2
    feuille = Image.new("RGBA", masque.size, VERT)
    canevas.paste(feuille, (ox, oy), masque)

    # « a » blanc, centré sur le corps de la feuille (position de l'original :
    # ~46 % de la largeur, ~52 % de la hauteur).
    sur = 4
    calque = Image.new("L", (TAILLE * sur // 2, TAILLE * sur // 2), 0)
    d = ImageDraw.Draw(calque)
    police = ImageFont.truetype(str(FONT), int(cible_h * 0.34) * sur // 2)
    cx = (ox + cible_w * 0.46) * sur / 2
    cy = (oy + cible_h * 0.52) * sur / 2
    d.text((cx, cy), "a", font=police, fill=255, anchor="mm")
    calque = calque.resize((TAILLE, TAILLE), Image.LANCZOS)
    blanc = Image.new("RGBA", (TAILLE, TAILLE), (255, 255, 255, 255))
    canevas.paste(blanc, (0, 0), calque)
    canevas.save(OUT)
    print(f"✓ {OUT} {canevas.size}")


if __name__ == "__main__":
    main()
