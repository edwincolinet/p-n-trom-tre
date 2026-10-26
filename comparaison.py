"""
Fenêtre de comparaison d'inspections (ré-inspection inter-missions).

Le suivi patrimonial d'un arbre se lit dans la **durée** : comparer la
campagne courante à une campagne antérieure montre si l'état se dégrade.

Design (choix métier, cf. mémoire) :
- **Référence par session** : on charge une mission antérieure en mémoire
  (aucun champ persisté dans le fichier → pas de lien cassé).
- **Lien explicite par arbre** : l'opérateur choisit, dans un combobox,
  l'arbre de la mission de référence à comparer (défaut : même n° s'il
  existe). Robuste même si la numérotation a changé entre campagnes.
- **Vue côte à côte** : référence | courant | **section d'évolution**
  (couronne orange = bois sain perdu depuis la référence), un tableau
  chiffré (Δ PRBS, taux cm/an, compartimentation, t/R…) et un verdict.
- **Cépée** : un bloc de comparaison **par brin**, empilés dans une zone
  défilante (mono-caule = un seul bloc). Appariement automatique par
  index/label ; un brin courant sans homologue de référence est comparé à
  None. Le tout **exportable** PNG/PDF (une page par brin pour une cépée).

**Fenêtre intégrée au reste de l'app (2026-09-05)** : avant, cette
fenêtre portait ses propres boutons Export PDF/PNG et un bouton
Fermer — coupant l'utilisateur du menu Export et de la barre d'état
pendant qu'elle était ouverte (repéré à l'usage : plus de bandeau,
donc plus d'« Enregistrer » ni de « Ouvrir le fichier/dossier » après
un export). Un premier passage lui a donné un menu local réduit à
« Export » ; **désormais elle porte le MÊME bandeau que la fenêtre
principale** (le même widget `tk.Menu`, cf. `open_comparison`) — accès
complet à Fichier/Comparaison/Arbres/Affichage/Export/Aide sans quitter
la comparaison :
- l'export PDF/PNG se déclenche depuis le menu **Export**, exactement
  comme ailleurs dans l'app (entrées grisées tant qu'aucune comparaison
  n'est ouverte) — `is_comparison_active`/`export_active_comparison`
  exposent l'état à `app_export_actions.ExportActionsMixin` ;
- **le pied de fenêtre reprend le MÊME bandeau que la barre d'état
  principale** (mêmes styles `Side.TFrame`/`Side.TLabel`/`Ghost.TButton`,
  même disposition) : bouton « Enregistrer » (`on_save` = `App.action_save`
  ; un widget Tk ne pouvant pas être partagé entre deux fenêtres comme un
  menu, c'est une **reconstruction visuellement identique**, pas le même
  widget) + indicateur d'enregistrement (texte/couleur venant de
  `dialogs_shared.save_state_label`, SOURCE UNIQUE partagée avec
  `App._update_save_indicator` pour que les deux bandeaux disent toujours
  la même chose) + message d'export + boutons « Ouvrir le fichier/dossier »
  (`show_export_feedback`, appelé par `App._export_comparison`) — l'ancien
  bouton « Enregistrer » du bandeau supérieur a été retiré (doublon,
  2026-09-06) ;
- plus de bouton « Fermer » : la fenêtre a ses décorations système
  complètes (pas de `transient`, cf. plus bas), la croix suffit.

Le calcul est délégué à `diagnostic_comparaison` (`comparaison_detaillee`,
`verdict_evolution`) et le rendu PIL à `comparaison_render` (sans Tk).
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any, Callable, Mapping, Optional

from chrome_icons import save_icon
from comparaison_render import (
    PTS_LEGENDE,
    metric_rows,
    render_brin_section,
    render_comparison_pages,
    render_evolution_pngs,
    render_evolution_section_brin,
    verdict_couleur,
)
from diagnostic_comparaison import (
    comparaison_par_brin,
    evolution_globale,
    verdict_evolution,
)
from dialogs_shared import annees_entre, save_state_label
from i18n import _
from model import Arbre, Chantier
from palette import COLOR_INK, COLOR_MUTED, COLOR_PANEL
from tooltip import Tooltip
from ui_fonts import font, font_small, font_small_bold

_SEC = 440  # côté des dessins (px)
_comparison_window: "Optional[tk.Toplevel]" = None  # singleton
# État de la sélection courante (arbres/brins choisis) de la fenêtre
# ci-dessus — même durée de vie qu'elle. Exposé en lecture par
# `export_active_comparison` pour que le menu Export de la fenêtre
# principale puisse déclencher un export sans passer par un bouton local.
_comparison_state: "Optional[dict[str, Any]]" = None


def _photo(img: Any) -> Any:
    from PIL import ImageTk
    return ImageTk.PhotoImage(img)


def is_comparison_active() -> bool:
    """Une comparaison est ouverte ET un couple d'arbres y est sélectionné
    (donc exportable). Pilote l'état des entrées du menu Export."""
    return (_comparison_window is not None
            and _comparison_window.winfo_exists()
            and _comparison_state is not None
            and "builder_args" in _comparison_state)


def get_comparison_window() -> "Optional[tk.Toplevel]":
    """Fenêtre de comparaison actuellement ouverte, pour y ancrer un
    filedialog (au premier plan) — `None` si aucune n'est ouverte."""
    if _comparison_window is not None and _comparison_window.winfo_exists():
        return _comparison_window
    return None


def export_active_comparison(fmt: str) -> "Optional[Callable[[], Any]]":
    """Builder de pages (cf. `_page_builder`) pour la comparaison
    actuellement ouverte, ou `None` si aucune n'est active — le menu
    Export appelle ceci plutôt que de garder son propre état."""
    if not is_comparison_active():
        return None
    assert _comparison_state is not None
    return _page_builder(_comparison_state, fmt)


def show_export_feedback(text: str, *, on_open_file: Callable[[], None],
                         on_open_folder: Callable[[], None]) -> None:
    """Affiche la confirmation d'export (+ boutons Ouvrir) dans le pied de
    la fenêtre de comparaison actuellement ouverte. No-op si aucune n'est
    ouverte (export déclenché après sa fermeture, cas limite). Reproduit
    localement `App.notify_export`, invisible tant que cette fenêtre
    couvre l'écran principal."""
    if _comparison_state is None:
        return
    lbl = _comparison_state.get("_lbl_msg")
    if lbl is None:
        return
    lbl.configure(text=text)
    btn_file = _comparison_state.get("_btn_open_file")
    if btn_file is not None:
        btn_file.configure(state="normal", command=on_open_file)
    btn_folder = _comparison_state.get("_btn_open_folder")
    if btn_folder is not None:
        btn_folder.configure(state="normal", command=on_open_folder)


def open_comparison(parent: tk.Misc, current: Chantier, reference: Chantier,
                    *, default_arbre: Arbre, cur_date: str,
                    couleur_classe: Mapping[str, str],
                    on_save: Callable[[], None]) -> None:
    """Fenêtre de comparaison d'un arbre de la mission `current` (courante)
    avec un arbre de la mission `reference` (antérieure). Les **deux** arbres
    se choisissent dans la fenêtre (combobox) ; sélection courante par défaut
    = `default_arbre`. `cur_date` = date de la mission courante (taux cm/an).
    `on_save` est appelé par le bouton « Enregistrer » (= `App.action_save`,
    la mission reste enregistrable sans fermer la fenêtre).

    `parent` est l'App principale : sa barre de menu (`parent._menubar`,
    posée par `app_menu.build_menu`) est réutilisée **telle quelle** comme
    bandeau de cette fenêtre (un `tk.Menu` Tk peut servir de menu à
    plusieurs fenêtres à la fois) — ce qui donne accès à Fichier/
    Comparaison/Arbres/Affichage/Export/Aide sans quitter la comparaison,
    au lieu d'un sous-ensemble reconstruit à la main. Les entrées Export de
    la comparaison (« Comparaison — fiche PDF… »/« … évolution (PNG)… »)
    s'activent d'elles-mêmes dès qu'une sélection est faite ici, via
    `is_comparison_active`.

    **Case « Afficher sondages » partagée** (2026-09-06, plus de paramètre
    `show_sondages`) : la fenêtre pose sa PROPRE case à cocher sur
    `parent.var_show_sondages` — la MÊME `tk.BooleanVar` que celle de la
    fenêtre principale (un seul interpréteur Tcl pour toute l'app, comme le
    menu partagé ci-dessus) — pour ne plus avoir à changer de fenêtre pour
    afficher/masquer les sondages. Une trace sur cette variable redessine
    les blocs à chaque bascule, d'où qu'elle vienne (cette fenêtre ou la
    principale) ; la variable et sa trace, `App`-level, redessinent aussi le
    canevas principal (`App._build_right`). Une seule fenêtre de comparaison
    à la fois (singleton) : ré-ouvrir ferme la précédente et ouvre une
    nouvelle avec la sélection courante."""
    global _comparison_window, _comparison_state
    if _comparison_window is not None and _comparison_window.winfo_exists():
        _comparison_window.destroy()
    curs = current.arbres
    refs = reference.arbres
    annees = annees_entre(reference.date_releve, cur_date)
    ref_label = reference.date_releve or reference.nom or "référence"
    cur_label = cur_date or "courant"

    dlg = tk.Toplevel(parent)
    _comparison_window = dlg
    dlg.title("Comparaison d'inspections")
    dlg.configure(bg=COLOR_PANEL)
    dlg.minsize(1000, 720)
    # Même bandeau que la fenêtre principale (littéralement le même widget
    # `tk.Menu`) : avant, cette fenêtre reconstruisait un menu local réduit
    # à « Export », ce qui coupait l'accès à Fichier/Comparaison/Arbres/
    # Affichage/Aide tant qu'elle restait ouverte (quasi plein écran, pas
    # `transient`, cf. plus bas). Réutiliser le menu de `parent` (posé sur
    # `_menubar` par `app_menu.build_menu`) évite ce sous-ensemble à
    # entretenir en double.
    menubar = getattr(parent, "_menubar", None)
    if menubar is not None:
        dlg.config(menu=menubar)
    # PAS de `transient` : sous Linux/X11 un transient est traité en dialogue
    # utilitaire par le gestionnaire de fenêtres → souvent **sans bouton
    # « maximiser »** (et `-zoomed` y est ignoré silencieusement). Une fenêtre
    # normale obtient les décorations complètes (maximiser d'un clic). On
    # l'ouvre déjà **grande et centrée** (95 % de l'écran) pour éviter tout
    # redimensionnement manuel, puis on tente un vrai maximize en best-effort.
    dlg.update_idletasks()
    sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
    w, h = int(sw * 0.95), int(sh * 0.90)
    dlg.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2 - 20)}")
    try:
        dlg.state("zoomed")
    except tk.TclError:
        try:
            dlg.attributes("-zoomed", True)
        except tk.TclError:
            pass

    state: dict[str, Any] = {}
    _comparison_state = state
    photos: list[Any] = []  # garde les PhotoImage du GC (multi-brin)

    # --- Sélecteurs : arbre courant (cette mission) ET arbre de référence,
    # tous deux modifiables (avant, le courant était figé au lancement). ---
    def _labels(arbres: list) -> list:
        return [f"n° {a.numero_arbre} — {a.essence or '?'}" for a in arbres]

    top = ttk.Frame(dlg, style="Panel.TFrame", padding=(12, 10, 12, 4))
    top.pack(fill="x")
    ttk.Label(top, text=_("Arbre courant :"), style="Panel.TLabel").pack(
        side="left", padx=(0, 4))
    var_cur = tk.StringVar()
    cmb_cur = ttk.Combobox(top, textvariable=var_cur, values=_labels(curs),
                           state="readonly", width=26)
    cmb_cur.pack(side="left", padx=(0, 16))
    ttk.Label(top, text=_("comparé à (référence) :"),
              style="Panel.TLabel").pack(side="left", padx=(0, 4))
    var_ref = tk.StringVar()
    cmb_ref = ttk.Combobox(top, textvariable=var_ref, values=_labels(refs),
                           state="readonly", width=26)
    cmb_ref.pack(side="left")
    # Garde une réf aux StringVar : locales, elles seraient GC à la sortie de
    # la fonction, et leur __del__ désaffecte la variable Tcl → combobox vide.
    # `state` survit (capturé par les closures des boutons/sélecteurs).
    state["_vars"] = (var_cur, var_ref)
    ttk.Label(top, text=_("(réf. {r}  →  courant {c})").format(r=ref_label, c=cur_label),
              style="Muted.TLabel").pack(side="left", padx=(12, 0))
    # Case « Afficher sondages » — MÊME `BooleanVar` que celle de la fenêtre
    # principale (`App.var_show_sondages`, un seul interpréteur Tcl pour
    # toute l'app) : cocher ici la coche aussi là-bas, et réciproquement,
    # sans avoir à changer de fenêtre. Repli local si `parent` n'en expose
    # pas (robustesse tests).
    var_show_sondages = getattr(parent, "var_show_sondages", None)
    if var_show_sondages is None:
        var_show_sondages = tk.BooleanVar(value=True)
    ttk.Checkbutton(
        top, text=_("Afficher l'emplacement des sondages sur le dessin"),
        variable=var_show_sondages, style="Panel.TCheckbutton",
    ).pack(side="right")

    # --- Zone centrale défilante : un bloc par brin (cépée). Mono-caule
    # = un seul bloc, sans en-tête de brin. Scrollbar seule (pas de binding
    # molette global, qui casserait le défilement de l'app). ---
    mid = ttk.Frame(dlg, style="Panel.TFrame")
    mid.pack(fill="both", expand=True)
    canvas = tk.Canvas(mid, bg=COLOR_PANEL, highlightthickness=0)
    vsb = ttk.Scrollbar(mid, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    inner = ttk.Frame(canvas, style="Panel.TFrame")
    inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>",
               lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>",
                lambda e: canvas.itemconfigure(inner_id, width=e.width))

    # Molette : bindings globaux activés UNIQUEMENT quand le pointeur est sur
    # ce canvas (même pattern que `pane_diagnostic`) — sinon la molette
    # détournerait le scroll ailleurs ; `unbind` au Leave, re-`bind` à
    # l'Enter de chaque zone scrollable. Couvre la fenêtre entière (les blocs
    # ne scrollent pas eux-mêmes).
    def _wheel(e: Any) -> None:
        canvas.yview_scroll(int(-e.delta / 120), "units")

    def _wheel_linux(e: Any) -> None:
        canvas.yview_scroll(-1 if e.num == 4 else 1, "units")

    def _bind_wheel(_e: Any) -> None:
        canvas.bind_all("<MouseWheel>", _wheel)
        canvas.bind_all("<Button-4>", _wheel_linux)
        canvas.bind_all("<Button-5>", _wheel_linux)

    def _unbind_wheel(_e: Any) -> None:
        canvas.unbind_all("<MouseWheel>")
        canvas.unbind_all("<Button-4>")
        canvas.unbind_all("<Button-5>")

    canvas.bind("<Enter>", _bind_wheel)
    canvas.bind("<Leave>", _unbind_wheel)

    # --- Pied de fenêtre = MÊME bandeau que la barre d'état principale
    # (même styles Side.TFrame/Side.TLabel/Ghost.TButton, même disposition :
    # bouton Enregistrer + indicateur d'enregistrement à gauche, message à
    # la suite, « Ouvrir le fichier/dossier » à droite). Avant, la fenêtre
    # avait son propre bouton « Enregistrer » en haut (retiré : il fait
    # doublon avec celui-ci) et un pied réduit au message d'export. Le menu
    # (Ctrl+S compris, via `bind_all` sur la fenêtre principale) reste
    # disponible en parallèle — pas de bouton Export/Fermer ici : l'export
    # se fait par le menu Export, la fermeture par la croix de la fenêtre
    # (décorations système complètes, cf. plus haut).
    foot = ttk.Frame(dlg, style="Side.TFrame")
    foot.pack(side="bottom", fill="x")
    # Icône bitmap plutôt que le préfixe « 💾 » sur Windows — cf.
    # `chrome_icons.py` (emoji couleur disgracieux confirmé sur Windows,
    # rendu correct ailleurs).
    if sys.platform == "win32":
        btn_save = ttk.Button(foot, image=save_icon(), text=_("Enregistrer"),
                              compound="left", style="Ghost.TButton")
    else:
        btn_save = ttk.Button(foot, text=_("💾 Enregistrer"),
                              style="Ghost.TButton")
    btn_save.pack(side="left", padx=(10, 6), pady=2)
    Tooltip(btn_save, _("Enregistrer la mission") + " (Ctrl+S)")
    lbl_save_state = ttk.Label(foot, text="", style="Side.TLabel",
                               font=font_small_bold())
    lbl_save_state.pack(side="left", padx=(0, 14), pady=3)

    def _refresh_save_state() -> None:
        dirty = bool(getattr(parent, "_dirty", False))
        has_file = getattr(parent, "current_file", None) is not None
        text, color, enabled = save_state_label(dirty=dirty, has_file=has_file)
        lbl_save_state.configure(text=text, foreground=color)
        btn_save.configure(state="normal" if enabled else "disabled")

    def _do_save() -> None:
        on_save()
        _refresh_save_state()

    btn_save.configure(command=_do_save)
    _refresh_save_state()
    lbl_msg = ttk.Label(foot, text="", style="Side.TLabel", font=font_small())
    lbl_msg.pack(side="left", padx=(0, 12), pady=3, fill="x", expand=True)
    btn_open_folder = ttk.Button(foot, text=_("Ouvrir le dossier"),
                                 style="Ghost.TButton", state="disabled")
    btn_open_folder.pack(side="right", padx=(0, 10), pady=2)
    btn_open_file = ttk.Button(foot, text=_("Ouvrir le fichier"),
                               style="Ghost.TButton", state="disabled")
    btn_open_file.pack(side="right", padx=(0, 4), pady=2)
    state["_lbl_msg"] = lbl_msg
    state["_btn_open_file"] = btn_open_file
    state["_btn_open_folder"] = btn_open_folder

    def _on_select(_e: Any = None) -> None:
        ci, ri = cmb_cur.current(), cmb_ref.current()
        if not (0 <= ci < len(curs)) or not (0 <= ri < len(refs)):
            return
        cur_arbre, ref_arbre = curs[ci], refs[ri]
        show_sondages = bool(var_show_sondages.get())
        # Mémo export (les pages sont recalculées à la demande dans le builder).
        state["builder_args"] = (reference.nom, ref_arbre, cur_arbre, annees,
                                  ref_label, cur_label, show_sondages,
                                  _en_tete_export(parent, current))
        for w in inner.winfo_children():
            w.destroy()
        photos.clear()
        pairs = comparaison_par_brin(ref_arbre, cur_arbre, annees)
        multi = len(pairs) > 1
        for label, cur_b, ref_b, detail in pairs:
            _build_brin_block(inner, label if multi else None,
                              ref_arbre, cur_arbre, cur_b, ref_b, detail,
                              ref_label, cur_label, photos, show_sondages)
        _build_photos_block(inner, parent, cur_arbre, ref_label, cur_label,
                            _refresh_save_state)
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.yview_moveto(0.0)

    cmb_cur.bind("<<ComboboxSelected>>", _on_select)
    cmb_ref.bind("<<ComboboxSelected>>", _on_select)
    # Redessine les blocs (avec les sondages affichés/masqués) dès que la
    # case bascule, d'où qu'elle vienne (cette fenêtre ou la principale).
    # Trace retirée à la fermeture : sinon elle survivrait sur cette
    # `BooleanVar` partagée et rappellerait `_on_select` sur des widgets
    # détruits à la prochaine bascule.
    _trace_id = var_show_sondages.trace_add(
        "write", lambda *_a: _on_select())

    def _on_destroy(e: Any) -> None:
        if e.widget is dlg:
            try:
                var_show_sondages.trace_remove("write", _trace_id)
            except tk.TclError:
                pass

    dlg.bind("<Destroy>", _on_destroy)

    if not curs or not refs:
        ttk.Label(inner,
                  text=_("La mission courante ou de référence ne contient aucun arbre."),
                  style="Panel.TLabel").pack(
                      anchor="w", padx=12, pady=12)
    else:
        ci = next((i for i, a in enumerate(curs) if a is default_arbre), 0)
        cmb_cur.current(ci)
        # Référence par défaut = même n° que l'arbre courant (lien implicite).
        cur_num = curs[ci].numero_arbre
        ri = next((i for i, a in enumerate(refs)
                   if a.numero_arbre == cur_num), 0)
        cmb_ref.current(ri)
        _on_select()

    dlg.update_idletasks()
    dlg.focus_set()


def _build_photos_block(parent: tk.Misc, app: Any, cur_arbre: Arbre,
                        ref_label: str, cur_label: str,
                        on_changed: Callable[[], None]) -> None:
    """Photos de la comparaison : une galerie pour l'état de **référence**,
    une pour l'état **actuel** — reprises sur une page « évolution
    photographique » du PDF. Stockées sur l'arbre courant
    (`photos_comparaison_ref/_cur`) et copiées dans le dossier photos de la
    mission courante (mission à enregistrer d'abord, comme la galerie de
    l'onglet Identification)."""
    from comparaison_render import PHOTOS_COMPARAISON_MAX
    from photo_gallery import PhotoGallery

    block = ttk.Frame(parent, style="Panel.TFrame", padding=(12, 6))
    block.pack(fill="x")
    ttk.Label(block, text=_("Photos de la comparaison"), style="H.TLabel",
              font=font("Georgia", 13, "bold")).pack(anchor="w")
    ttk.Label(block,
              text=_("Reprises dans le PDF (page « Évolution photographique », "
                     "{n} photos maximum par colonne).").format(
                         n=PHOTOS_COMPARAISON_MAX),
              style="Muted.TLabel", wraplength=900, justify="left"
              ).pack(anchor="w", pady=(0, 4))
    row = ttk.Frame(block, style="Panel.TFrame")
    row.pack(fill="x")

    def _changed() -> None:
        app.on_identification_changed(rayon_adjusted=False)
        on_changed()

    for titre, liste in (
            (_("Photos de la référence — {r}").format(r=ref_label),
             cur_arbre.photos_comparaison_ref),
            (_("Photos du diagnostic actuel — {c}").format(c=cur_label),
             cur_arbre.photos_comparaison_cur)):
        g = PhotoGallery(
            row, photos=liste, on_change=_changed,
            get_mission_file=lambda: getattr(app, "current_file", None),
            on_before_change=app.push_undo, title=titre)
        g.pack(side="left", fill="both", expand=True, padx=(0, 12), anchor="n")
    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=2)


def _build_brin_block(parent: tk.Misc, label: Optional[str], ref_arbre: Arbre,
                      cur_arbre: Arbre, cur_b: Any, ref_b: Any,
                      detail: Any, ref_label: str, cur_label: str,
                      photos: list, show_sondages: bool = True) -> None:
    """Construit un bloc de comparaison (3 dessins + tableau + verdict) pour
    un brin. `label=None` ⟹ mono-caule (pas d'en-tête de brin). `ref_b=None`
    ⟹ brin courant sans homologue de référence (colonne réf. vide).
    `show_sondages` reprend la case « Afficher sondages »."""
    block = ttk.Frame(parent, style="Panel.TFrame", padding=(0, 6))
    block.pack(fill="x", expand=True)
    if label is not None:
        ttk.Label(block, text=f"Brin {label}", style="H.TLabel",
                  font=font("Georgia", 13, "bold")).pack(anchor="w", padx=12)

    row = ttk.Frame(block, style="Panel.TFrame", padding=(12, 4))
    row.pack(fill="x")
    img_ref = _build_image_col(row, _("Référence — {r}").format(r=ref_label))
    img_cur = _build_image_col(row, f"Courant — {cur_label}")
    img_evo = _build_image_col(row, "Évolution de l'altération")
    if ref_b is not None:
        p = _photo(render_brin_section(ref_arbre, ref_b, _SEC,
                                       show_sondages=show_sondages))
        photos.append(p)
        img_ref.configure(image=p)
    else:
        img_ref.configure(text=_("(pas de brin de référence)"))
    pc = _photo(render_brin_section(cur_arbre, cur_b, _SEC,
                                    show_sondages=show_sondages))
    photos.append(pc)
    img_cur.configure(image=pc)
    pe = _photo(render_evolution_section_brin(ref_b, cur_b, _SEC))
    photos.append(pe)
    img_evo.configure(image=pe)

    rows = metric_rows(detail)
    tbl_frame = ttk.Frame(block, style="Panel.TFrame", padding=(12, 4))
    tbl_frame.pack(fill="x")
    cols = ("ind", "ref", "cur", "evo")
    tbl = ttk.Treeview(tbl_frame, columns=cols, show="headings",
                       height=len(rows))
    for c, txt, w in (("ind", "Indicateur", 280), ("ref", "Référence", 150),
                      ("cur", "Courant", 150), ("evo", "Évolution", 230)):
        tbl.heading(c, text=txt)
        tbl.column(c, width=w, anchor="w")
    for r in rows:
        tbl.insert("", "end", values=r)
    tbl.pack(fill="x")

    ttk.Label(block, text=PTS_LEGENDE, style="Muted.TLabel",
              wraplength=900, justify="left").pack(anchor="w", padx=12,
                                                   pady=(2, 0))

    ttk.Label(block, text=verdict_evolution(detail), style="Panel.TLabel",
              font=font("Helvetica", 11, "bold"), wraplength=900, justify="left",
              foreground=_verdict_color(detail)
              ).pack(anchor="w", padx=12, pady=(2, 6))
    ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=2)


def _build_image_col(parent: tk.Misc, titre: str) -> ttk.Label:
    host = ttk.Frame(parent, style="Panel.TFrame")
    host.pack(side="left", fill="both", expand=True, padx=4)
    ttk.Label(host, text=titre, style="H.TLabel").pack(anchor="w")
    img = ttk.Label(host, style="Panel.TLabel")
    img.pack(pady=4)
    return img


def _en_tete_export(parent: Any, current: Chantier) -> "dict[str, Any]":
    """Éléments de l'en-tête/pied de page de la page PDF (mission courante,
    logo et nom du cabinet des réglages de l'App) — mêmes sources que la
    fiche d'expertise (`app_exports._get_cabinet_info`)."""
    settings = getattr(parent, "_settings", None)
    cf = getattr(parent, "current_file", None)
    return {"chantier": current,
            "mission_dir": Path(cf).parent if cf else None,
            "cabinet_name": getattr(settings, "cabinet_name", "") or "",
            "logo_path": getattr(settings, "logo_path", None)}


def _page_builder(state: dict, fmt: str) -> Callable[[], Any]:
    """Renvoie une closure qui rend le contenu d'export depuis la sélection
    courante (capturée dans `state`), un par brin pour une cépée.

    Le format dicte la composition : `pdf` → feuilles A4 livrables (en-tête,
    3 dessins, tableau chiffré, verdict — `render_comparison_pages`,
    assemblées en un seul PDF multi-pages) ; `png` → la section d'évolution
    seule, au format de l'export PNG classique d'un arbre (titre + dessin +
    légende — `render_evolution_pngs`, `[(label, image)]`), pensée pour être
    insérée directement dans un rapport — `save_evolution_pngs` en écrit
    **un fichier par brin** plutôt qu'une image empilée."""
    def _build() -> Any:
        args = state.get("builder_args")
        if args is None:
            raise RuntimeError("Aucun arbre de référence sélectionné.")
        (nom, ref_arbre, cur, annees, ref_label, cur_label,
         show_sondages, en_tete) = args
        if fmt == "png":
            return render_evolution_pngs(
                nom, ref_arbre, cur, annees, ref_label=ref_label,
                cur_label=cur_label, show_sondages=show_sondages)
        return render_comparison_pages(
            nom, ref_arbre, cur, annees, ref_label=ref_label,
            cur_label=cur_label, show_sondages=show_sondages, **en_tete)
    return _build


def _verdict_color(detail: Any) -> str:
    if evolution_globale(detail) is None:
        return COLOR_MUTED
    return verdict_couleur(detail) or COLOR_INK
