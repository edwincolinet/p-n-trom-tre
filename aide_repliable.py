"""Aide contextuelle repliable (widget Tk réutilisable).

Les libellés d'aide ⓘ affichés en permanence (« Saisir le diamètre
calcule le rayon… ») guident la première utilisation mais encombrent
l'écran pour l'opérateur expérimenté qui les a intégrés. `AideRepliable`
les place derrière un en-tête cliquable « ⓘ Aide ▸ » : **repliés par
défaut** (donc discrets), **dépliables d'un clic**. L'état déplié/replié
est conservé tant que le widget vit — les panes sont construits une
seule fois (pas reconstruits par arbre), donc le choix persiste dans la
session ; au prochain lancement on repart replié.

Réutilisable en `grid` comme en `pack` : le widget gère sa disposition
interne, le parent ne place que le widget lui-même (`.grid(...)` /
`.pack(...)`). Accepte un ou plusieurs paragraphes d'aide.

Usage :
    from aide_repliable import AideRepliable
    AideRepliable(parent, "Premier conseil…", "Second conseil…"
                  ).grid(row=n, column=0, sticky="we")

Styles attendus (définis par `app_style.apply_ttk_styles`) :
`Panel.TFrame` pour le fond et `Muted.TLabel` pour le texte secondaire —
le widget vit donc sur un panneau blanc (cas de tous les appelants).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class AideRepliable(ttk.Frame):
    """Bloc d'aide repliable : en-tête cliquable + corps masquable."""

    def __init__(self, master: tk.Misc, *paragraphes: str,
                 titre: str = "Aide", wraplength: int = 380,
                 expanded: bool = False) -> None:
        super().__init__(master, style="Panel.TFrame")
        self._titre = titre
        self._expanded = expanded

        # En-tête cliquable. Le curseur main + la flèche ▸/▾ signalent
        # l'interactivité (Muted.TLabel n'a pas de chrome de bouton).
        self._header = ttk.Label(self, style="Muted.TLabel", cursor="hand2")
        self._header.pack(anchor="w")
        self._header.bind("<Button-1>", lambda _e: self.toggle())

        # Corps : un paragraphe Muted par conseil, masqué/affiché en bloc.
        self._body = ttk.Frame(self, style="Panel.TFrame")
        for p in paragraphes:
            ttk.Label(self._body, text=p, style="Muted.TLabel",
                      wraplength=wraplength, justify="left"
                      ).pack(anchor="w", pady=(2, 0))

        self._sync()

    def toggle(self) -> None:
        """Inverse l'état déplié/replié."""
        self._expanded = not self._expanded
        self._sync()

    def _sync(self) -> None:
        """Reflète l'état courant : flèche de l'en-tête + visibilité du corps."""
        fleche = "▾" if self._expanded else "▸"
        self._header.configure(text=f"ⓘ {self._titre}  {fleche}")
        if self._expanded:
            self._body.pack(anchor="w", fill="x", pady=(2, 0))
        else:
            self._body.pack_forget()
