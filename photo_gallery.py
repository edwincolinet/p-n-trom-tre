"""
Widget galerie photos pour un arbre (pane Identification).

Affiche les photos de `Arbre.photos` sous forme de vignettes cliquables
(80×80 px). Bouton « ＋ Photo » pour ajouter, ✕ pour supprimer.
Clic sur une vignette → vue plein écran (système ou Toplevel PIL).

Aucune dépendance vers App/penetrometre : le widget reçoit un callback
`on_change` appelé après toute mutation de la liste.
"""

from __future__ import annotations

import logging
import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, List

from i18n import _
from ui_fonts import font as ui_font

log = logging.getLogger("penetrometre")

_THUMB_W = 80
_THUMB_H = 80
_ACCEPTED = (
    ("Images", "*.jpg *.jpeg *.png *.gif *.bmp *.tiff *.tif *.webp"),
    ("Tous", "*.*"),
)


class PhotoGallery(ttk.Frame):
    """Galerie de vignettes photos attachée à un Arbre."""

    def __init__(self, master: tk.Misc,
                 photos: List[str],
                 on_change: Callable[[], None],
                 **kw: Any) -> None:
        super().__init__(master, style="Panel.TFrame", **kw)
        self._photos = photos        # référence directe à Arbre.photos
        self._on_change = on_change
        self._thumbs: list[object] = []  # garde les PhotoImage (GC)
        self._build()

    def _build(self) -> None:
        hdr = ttk.Frame(self, style="Panel.TFrame")
        hdr.pack(fill="x", pady=(0, 4))
        ttk.Label(hdr, text=_("Photos"),
                  font=ui_font("Helvetica", 10, "bold"),
                  style="Panel.TLabel").pack(side="left")
        ttk.Button(hdr, text=_("＋ Photo"),
                   style="Ghost.TButton",
                   command=self._add_photo).pack(side="right")

        self._grid_frame = ttk.Frame(self, style="Panel.TFrame")
        self._grid_frame.pack(fill="x")
        self._refresh()

    def _refresh(self) -> None:
        for w in self._grid_frame.winfo_children():
            w.destroy()
        self._thumbs.clear()

        if not self._photos:
            ttk.Label(self._grid_frame,
                      text=_("Aucune photo"),
                      style="Muted.TLabel").pack(anchor="w")
            return

        cols = 4
        for i, path in enumerate(self._photos):
            row, col = divmod(i, cols)
            cell = ttk.Frame(self._grid_frame, style="Panel.TFrame")
            cell.grid(row=row, column=col, padx=4, pady=4, sticky="nw")
            self._make_thumb(cell, path, i)

    def _make_thumb(self, cell: ttk.Frame, path: str, idx: int) -> None:
        """Crée la vignette + bouton ✕ pour une photo."""
        p = Path(path)
        try:
            from PIL import Image as PILImage
            from PIL import ImageTk
            if not p.exists():
                raise FileNotFoundError(path)
            img = PILImage.open(path)
            img.thumbnail((_THUMB_W, _THUMB_H), PILImage.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._thumbs.append(photo)
            lbl = tk.Label(cell, image=photo, cursor="hand2",
                           relief="flat", bd=1)
            lbl.pack()
            lbl.bind("<Button-1>", lambda e, pp=path: self._view_photo(pp))
        except Exception:
            # Pillow absent ou fichier manquant → icône textuelle
            lbl_txt = ttk.Label(cell,
                                text=f"📷\n{p.name[:12]}",
                                style="Muted.TLabel",
                                justify="center",
                                cursor="hand2")
            lbl_txt.pack()
            lbl_txt.bind("<Button-1>", lambda e, pp=path: self._view_photo(pp))

        # Nom de fichier tronqué
        ttk.Label(cell, text=p.name[:14], style="Muted.TLabel",
                  font=ui_font("Helvetica", 7)).pack()

        # Bouton supprimer
        ttk.Button(cell, text="✕", style="Ghost.TButton", width=2,
                   command=lambda i=idx: self._remove_photo(i)).pack()

    def _add_photo(self) -> None:
        paths = filedialog.askopenfilenames(
            title=_("Ajouter des photos"),
            filetypes=list(_ACCEPTED))
        if not paths:
            return
        added = 0
        for p in paths:
            if p not in self._photos:
                self._photos.append(p)
                added += 1
        if added:
            self._refresh()
            self._on_change()

    def _remove_photo(self, idx: int) -> None:
        if 0 <= idx < len(self._photos):
            del self._photos[idx]
            self._refresh()
            self._on_change()

    def _view_photo(self, path: str) -> None:
        """Ouvre la photo — viewer système ou Toplevel PIL."""
        if not Path(path).exists():
            messagebox.showwarning(
                _("Fichier introuvable"),
                f"{path}\n\n{_('Le fichier a été déplacé ou supprimé.')}",
                parent=self)
            return
        try:
            import subprocess
            import sys
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            self._view_in_toplevel(path)

    def _view_in_toplevel(self, path: str) -> None:
        """Fallback : affiche la photo dans un Toplevel Tk."""
        try:
            from PIL import Image as PILImage
            from PIL import ImageTk
            img: PILImage.Image = PILImage.open(path)
            w, h = img.size
            max_dim = 900
            if max(w, h) > max_dim:
                scale = max_dim / max(w, h)
                img = img.resize((int(w*scale), int(h*scale)),
                                 PILImage.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            dlg = tk.Toplevel(self)
            dlg.title(Path(path).name)
            tk.Label(dlg, image=photo).pack()
            dlg._photo = photo  # type: ignore[attr-defined]  # avoid GC
        except Exception as e:
            log.exception("Impossible d'afficher la photo")
            messagebox.showerror(_("Erreur"), str(e), parent=self)

    def reload(self, photos: List[str]) -> None:
        """Recharge la galerie depuis une nouvelle liste (changement d'arbre)."""
        self._photos = photos
        self._refresh()
