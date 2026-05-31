"""Infobulle Tk légère, attachable à n'importe quel widget.

Tkinter n'a pas de tooltip natif. Ce helper en fournit un minimal :
une petite fenêtre `Toplevel` sans bordure (`overrideredirect`) qui
apparaît après un court délai au survol et disparaît à la sortie ou au
clic. Sert à rappeler les accélérateurs clavier (« Ctrl+T ») et à
décrire les actions sans encombrer le libellé des boutons.

Usage :
    from tooltip import Tooltip
    Tooltip(mon_bouton, "Ajouter un arbre (Ctrl+T)")

Les bindings sont posés avec `add="+"` pour ne pas écraser ceux que le
widget porte déjà (ex. `<Enter>`/`<Leave>` du curseur `hand2`).
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional

from palette import COLOR_INK


class Tooltip:
    """Infobulle au survol d'un widget. Une instance par widget."""

    _BG = "#FFFFE0"  # jaune pâle classique d'infobulle

    def __init__(self, widget: tk.Widget, text: str,
                 delay_ms: int = 500) -> None:
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id: Optional[str] = None
        self._tip: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _e: "Optional[tk.Event[tk.Misc]]" = None) -> None:
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel(self) -> None:
        if self._after_id is not None:
            self.widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self) -> None:
        if self._tip is not None or not self.text:
            return
        x = self.widget.winfo_rootx() + 12
        y = (self.widget.winfo_rooty()
             + self.widget.winfo_height() + 4)
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        tk.Label(tip, text=self.text, justify="left", background=self._BG,
                 foreground=COLOR_INK, relief="solid", borderwidth=1,
                 font=("Helvetica", 9), padx=6, pady=3).pack()
        self._tip = tip

    def _hide(self, _e: "Optional[tk.Event[tk.Misc]]" = None) -> None:
        self._cancel()
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None
