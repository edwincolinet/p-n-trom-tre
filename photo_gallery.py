"""
Widget galerie photos pour un arbre (pane Identification).

Affiche les photos de `Arbre.photos` sous forme de vignettes cliquables
(80×80 px). Bouton « ＋ Photo » pour ajouter, ✕ pour supprimer.
Clic sur une vignette → vue plein écran (système ou Toplevel PIL).

Les photos sont copiées dans un dossier compagnon `<mission>_photos/`
à côté du fichier JSON, et stockées en chemin relatif dans le modèle.
Cela rend la mission portable : déplacer le JSON + le dossier _photos
suffit à tout conserver.

Aucune dépendance vers App/penetrometre : le widget reçoit des callbacks.
"""

from __future__ import annotations

import logging
import os
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, List, Optional

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
                 get_mission_file: Callable[[], Optional[Path]],
                 on_before_change: Callable[[], None],
                 **kw: Any) -> None:
        super().__init__(master, style="Panel.TFrame", **kw)
        self._photos = photos            # référence directe à Arbre.photos
        self._on_change = on_change
        self._get_mission_file = get_mission_file
        self._on_before_change = on_before_change
        self._thumbs: list[object] = []  # garde les PhotoImage (GC)
        self._build()

    # ------------------------------------------------------------------
    # Helpers chemin
    # ------------------------------------------------------------------

    def _companion_dir(self) -> Optional[Path]:
        """Dossier `<mission_stem>_photos/` à côté du JSON, ou None si non enregistré."""
        mf = self._get_mission_file()
        if mf is None:
            return None
        return mf.parent / f"{mf.stem}_photos"

    def _resolve(self, stored: str) -> Optional[Path]:
        """Résout un chemin stocké (relatif ou absolu) en chemin absolu.

        - Absolu → utilisé tel quel (compat anciens fichiers).
        - Relatif → résolu depuis le dossier du fichier JSON courant.
        Renvoie None si le fichier n'existe pas.
        """
        p = Path(stored)
        if p.is_absolute():
            return p if p.exists() else None
        mf = self._get_mission_file()
        if mf is None:
            return None
        resolved = mf.parent / p
        return resolved if resolved.exists() else None

    # ------------------------------------------------------------------
    # Construction UI
    # ------------------------------------------------------------------

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

    def _make_thumb(self, cell: ttk.Frame, stored: str, idx: int) -> None:
        """Crée la vignette + bouton ✕ pour une photo."""
        resolved = self._resolve(stored)
        name = Path(stored).name

        if resolved is not None:
            try:
                from PIL import Image as PILImage
                from PIL import ImageTk
                img = PILImage.open(resolved)
                img.thumbnail((_THUMB_W, _THUMB_H), PILImage.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self._thumbs.append(photo)
                lbl = tk.Label(cell, image=photo, cursor="hand2",
                               relief="flat", bd=1)
                lbl.pack()
                lbl.bind("<Button-1>",
                         lambda e, p=str(resolved): self._view_photo(p))
            except Exception:
                self._make_thumb_fallback(cell, stored)
                return
        else:
            # Fichier introuvable
            lbl_txt = ttk.Label(cell,
                                text=f"📷\n{name[:12]}\n⚠ introuvable",
                                style="Muted.TLabel",
                                justify="center")
            lbl_txt.pack()

        ttk.Label(cell, text=name[:14], style="Muted.TLabel",
                  font=ui_font("Helvetica", 7)).pack()
        ttk.Button(cell, text="✕", style="Ghost.TButton", width=2,
                   command=lambda i=idx: self._remove_photo(i)).pack()

    def _make_thumb_fallback(self, cell: ttk.Frame, stored: str) -> None:
        """Icône textuelle quand Pillow est absent ou fichier illisible."""
        name = Path(stored).name
        lbl = ttk.Label(cell, text=f"📷\n{name[:12]}",
                        style="Muted.TLabel", justify="center", cursor="hand2")
        lbl.pack()
        resolved = self._resolve(stored)
        if resolved:
            lbl.bind("<Button-1>",
                     lambda e, p=str(resolved): self._view_photo(p))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _add_photo(self) -> None:
        cdir = self._companion_dir()
        if cdir is None:
            messagebox.showwarning(
                _("Mission non enregistrée"),
                _("Enregistrez d'abord la mission (Ctrl+S) pour pouvoir "
                  "ajouter des photos."),
                parent=self)
            return

        paths = filedialog.askopenfilenames(
            title=_("Ajouter des photos"),
            filetypes=list(_ACCEPTED))
        if not paths:
            return

        mf = self._get_mission_file()
        if mf is None:
            return

        try:
            cdir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            log.exception("Impossible de créer le dossier photos")
            messagebox.showerror(_("Erreur"), str(exc), parent=self)
            return

        self._on_before_change()
        added = 0
        for src in paths:
            src_path = Path(src)
            dst = cdir / src_path.name
            # Déduplication de nom
            if dst.exists() and dst != src_path:
                stem, suffix = src_path.stem, src_path.suffix
                i = 1
                while dst.exists():
                    dst = cdir / f"{stem}_{i}{suffix}"
                    i += 1
            try:
                if str(src_path) != str(dst):
                    shutil.copy2(src, dst)
                rel = str(dst.relative_to(mf.parent))
                if rel not in self._photos:
                    self._photos.append(rel)
                    added += 1
            except Exception:
                log.exception("Échec copie photo %s", src)

        if added:
            self._refresh()
            self._on_change()

    def _remove_photo(self, idx: int) -> None:
        if 0 <= idx < len(self._photos):
            self._on_before_change()
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
