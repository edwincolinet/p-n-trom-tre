"""
Widget galerie photos pour un arbre (pane Identification).

Affiche les photos de `Arbre.photos` sous forme de vignettes cliquables
(80×80 px). Bouton « ＋ Photo » pour ajouter, ✕ pour supprimer.
Clic sur une vignette → vue plein écran (système ou Toplevel PIL).

Les photos sont copiées dans un dossier compagnon `<mission>_photos/`
à côté du fichier JSON, et stockées en chemin relatif dans le modèle.
Cela rend la mission portable : déplacer le JSON + le dossier _photos
suffit à tout conserver.

**Sécurité** : les références lues dans le JSON sont résolues par
`photo_paths.resolve_photo` (confinement au dossier de la mission +
extensions autorisées) et le contenu est vérifié comme image avant tout
passage à la visionneuse système — cf. `_view_photo`.

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
from photo_paths import (
    MOTIF_INTROUVABLE,
    MOTIF_SANS_MISSION,
    PHOTO_SUFFIXES,
    PhotoResolue,
    resolve_photo,
    suffixe_autorise,
)
from ui_fonts import font as ui_font
from ui_fonts import font_body_bold

log = logging.getLogger("penetrometre")

_THUMB_W = 80
_THUMB_H = 80
# Filtre du sélecteur de fichiers — dérivé de la whitelist partagée pour
# qu'on ne puisse pas ajouter via l'UI un type que la résolution refusera
# ensuite au rechargement. Pas d'entrée « Tous » : elle laissait choisir
# un fichier que `resolve_photo` rejette, donc une photo qui « disparaît »
# à la réouverture de la mission.
_ACCEPTED = (
    ("Images", " ".join(f"*{s}" for s in sorted(PHOTO_SUFFIXES))),
)


class PhotoGallery(ttk.Frame):
    """Galerie de vignettes photos attachée à un Arbre."""

    def __init__(self, master: tk.Misc,
                 photos: List[str],
                 on_change: Callable[[], None],
                 get_mission_file: Callable[[], Optional[Path]],
                 on_before_change: Callable[[], None],
                 title: Optional[str] = None,
                 **kw: Any) -> None:
        super().__init__(master, style="Panel.TFrame", **kw)
        self._title = title
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

    def _resolve_ref(self, stored: str) -> "PhotoResolue":
        """Résout une référence photo en appliquant le confinement.

        Délègue à `photo_paths.resolve_photo` (règles et justification
        dans l'en-tête de ce module-là). Renvoie le résultat complet —
        chemin **et** motif de refus — pour que la vignette puisse dire
        *pourquoi* une photo n'est pas affichée.
        """
        mf = self._get_mission_file()
        res = resolve_photo(stored, mf.parent if mf is not None else None)
        if res.path is None and res.motif not in ("", MOTIF_INTROUVABLE,
                                                  MOTIF_SANS_MISSION):
            log.warning("Référence photo refusée (%s) : %s", res.motif, stored)
        return res

    def _resolve(self, stored: str) -> Optional[Path]:
        """Chemin utilisable, ou None si refusé/introuvable."""
        return self._resolve_ref(stored).path

    # ------------------------------------------------------------------
    # Construction UI
    # ------------------------------------------------------------------

    def _build(self) -> None:
        hdr = ttk.Frame(self, style="Panel.TFrame")
        hdr.pack(fill="x", pady=(0, 4))
        ttk.Label(hdr, text=self._title or _("Photos"),
                  font=font_body_bold(),
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
        res = self._resolve_ref(stored)
        resolved = res.path
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
            # Photo indisponible : on affiche le MOTIF plutôt qu'un
            # « introuvable » générique — une référence refusée par le
            # confinement n'est pas un fichier déplacé, et confondre les
            # deux ferait passer un garde-fou pour un bug.
            lbl_txt = ttk.Label(cell,
                                text=f"📷\n{name[:12]}\n⚠ {_(res.motif)}",
                                style="Muted.TLabel",
                                justify="center")
            lbl_txt.pack()

        ttk.Label(cell, text=name[:14], style="Muted.TLabel",
                  font=ui_font("Helvetica", 7)).pack()
        if res.hors_mission and resolved is not None:
            # Chemin absolu hérité (première version de la galerie) :
            # utilisable mais hors du dossier portable de la mission.
            ttk.Label(cell, text=_("⚠ hors dossier mission"),
                      style="Muted.TLabel",
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
        refuses: list[str] = []
        for src in paths:
            src_path = Path(src)
            # Le filtre du filedialog est indicatif (l'utilisateur peut
            # taper un nom) : on revalide avec la même whitelist que la
            # résolution, sinon on stockerait une référence que la
            # relecture de la mission rejetterait.
            if not suffixe_autorise(src_path.name):
                refuses.append(src_path.name)
                continue
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

        if refuses:
            messagebox.showwarning(
                _("Format non pris en charge"),
                _("Ces fichiers ne sont pas des images reconnues :")
                + "\n\n" + "\n".join(refuses[:5]),
                parent=self)
        if added:
            self._refresh()
            self._on_change()

    def _remove_photo(self, idx: int) -> None:
        if 0 <= idx < len(self._photos):
            self._on_before_change()
            del self._photos[idx]
            self._refresh()
            self._on_change()

    @staticmethod
    def _est_image_lisible(path: str) -> bool:
        """Vrai si le fichier est réellement décodable comme image.

        Garde-fou de contenu, indispensable AVANT de passer le chemin à
        la visionneuse système : celle-ci choisit le programme à lancer
        d'après le type MIME, qui se déduit en partie du **contenu**. Un
        `.desktop` ou un script renommé `photo.png` passerait la
        whitelist d'extension mais serait exécuté par `xdg-open`. On
        exige donc que Pillow reconnaisse une image avant de déléguer.

        Pillow absent → on renvoie False : sans moyen de vérifier, on ne
        délègue pas (le repli Toplevel affiche un message propre).
        """
        try:
            from PIL import Image as PILImage
            with PILImage.open(path) as img:
                img.verify()   # lève si l'entête n'est pas une image
            return True
        except Exception:
            return False

    def _view_photo(self, path: str) -> None:
        """Ouvre la photo — viewer système ou Toplevel PIL."""
        if not Path(path).exists():
            messagebox.showwarning(
                _("Fichier introuvable"),
                f"{path}\n\n{_('Le fichier a été déplacé ou supprimé.')}",
                parent=self)
            return
        if not suffixe_autorise(path) or not self._est_image_lisible(path):
            log.warning("Ouverture refusée — pas une image lisible : %s", path)
            messagebox.showwarning(
                _("Fichier non affichable"),
                f"{Path(path).name}\n\n"
                + _("Ce fichier n'est pas une image lisible — ouverture "
                    "annulée par sécurité."),
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
