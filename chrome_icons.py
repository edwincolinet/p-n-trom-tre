"""
Icônes bitmap de secours pour Windows (calendrier, enregistrer).

Sur Windows, les emoji couleur (📅, 💾) rendent mal en ttk (Segoe UI ne
les contient pas, Tk bascule sur Segoe UI Emoji, glyphes pleine couleur
surdimensionnés) et le glyphe Unicode de repli testé (`▦`) n'est pas
garanti dans les polices Windows de base (absent de l'encodage `cp1252`,
cf. `icons.py`). Seule une **image** reste garantie identique quelle que
soit la plateforme, indépendamment des polices installées.

Ce module dessine par PIL (déjà une dépendance du projet — `pil_render.py`,
`fiche_pdf.py`) deux petites icônes plates monochromes, à la couleur
`COLOR_ACCENT` (même teinte que le texte `Ghost.TButton`) : un calendrier
et une disquette. Résultat mis en cache en `PhotoImage` (Tk) au premier
usage — comme `app_reglages._reload_logo`, une `PhotoImage` nécessite un
`tk.Tk` déjà créé, donc ces fonctions ne doivent être appelées QUE depuis
la construction des widgets, jamais au niveau module.

**Utilisé uniquement sur Windows** (`sys.platform == "win32"` aux points
d'appel — `app_layout.py`, `pane_diagnostic.py`, `comparaison.py`) :
Linux/macOS gardent l'emoji d'origine, dont le rendu convient (confirmé
à l'usage) — pas de raison de le remplacer là où il fonctionne déjà.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

from palette import COLOR_ACCENT

if TYPE_CHECKING:
    from PIL.ImageTk import PhotoImage

_cache: "Dict[str, PhotoImage]" = {}


def _calendar_image(size: int) -> Any:
    from PIL import Image, ImageDraw
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    w = max(1, s // 16)
    top = s * 22 // 100
    d.rounded_rectangle(
        [s * 8 // 100, top, s * 92 // 100, s * 94 // 100],
        radius=max(1, s // 12), outline=COLOR_ACCENT, width=w)
    d.line([s * 8 // 100, top + s * 16 // 100,
            s * 92 // 100, top + s * 16 // 100], fill=COLOR_ACCENT, width=w)
    ring_top, ring_bot = top - s * 12 // 100, top + s * 6 // 100
    for x in (s * 26 // 100, s * 74 // 100):
        d.line([x, ring_top, x, ring_bot], fill=COLOR_ACCENT, width=w)
    return img


def _save_image(size: int) -> Any:
    from PIL import Image, ImageDraw
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    w = max(1, s // 16)
    m = s * 10 // 100
    d.rounded_rectangle([m, m, s - m, s - m], radius=max(1, s // 14),
                        outline=COLOR_ACCENT, width=w)
    notch = s * 22 // 100
    d.line([s - m - notch, m, s - m, m + notch], fill=COLOR_ACCENT, width=w)
    lm = s * 24 // 100
    d.rectangle([lm, s * 58 // 100, s - lm, s - m - s * 6 // 100],
               outline=COLOR_ACCENT, width=w)
    return img


def calendar_icon(size: int = 18) -> "PhotoImage":
    """Icône calendrier plate (dessinée par PIL), mise en cache par taille."""
    key = f"cal{size}"
    if key not in _cache:
        from PIL import ImageTk
        _cache[key] = ImageTk.PhotoImage(_calendar_image(size))
    return _cache[key]


def save_icon(size: int = 18) -> "PhotoImage":
    """Icône disquette plate (dessinée par PIL), mise en cache par taille."""
    key = f"save{size}"
    if key not in _cache:
        from PIL import ImageTk
        _cache[key] = ImageTk.PhotoImage(_save_image(size))
    return _cache[key]
