"""
Barre de menu de l'application Pénétromètre.

Module séparé de `penetrometre.py` pour la même raison qu'`app_style.py` :
ce sont ~50 lignes de plomberie déclarative (entrées de menu, raccourcis
clavier) qui n'ont pas leur place dans le corps de la classe `App`.

`build_menu(app)` attache la barre de menu à `app` et bind les
accélérateurs globaux. Le `Protocol AppLike` ci-dessous formalise la
surface attendue de l'`App` Tk (méthodes d'action + plomberie Tk
nécessaire) — symétrique au pattern `_*Host` des panes et aux
Protocols `ArbreLike`/`ChantierLike` de `export.py`.
"""

from __future__ import annotations

import tkinter as tk
from functools import partial
from typing import Any, Callable, Optional, Protocol, Sequence, Tuple, cast

from i18n import LANGUAGES, _


class AppLike(Protocol):
    """Surface attendue de l'`App` par la barre de menu.

    Couvre :
    - les méthodes `action_*` câblées aux entrées de menu et aux
      raccourcis clavier ;
    - les méthodes Tk dont `build_menu` se sert directement (config
      du menu, bind_all, destroy).
    """

    # Plomberie Tk
    def config(self, **kwargs: Any) -> Any: ...
    def bind_all(self, sequence: str,
                 func: Callable[..., Any]) -> str: ...
    def destroy(self) -> None: ...

    # Actions Fichier
    def action_save_as_template(self) -> None: ...
    def action_new_from_template(self) -> None: ...
    def action_open_demo(self) -> None: ...
    def action_new(self) -> None: ...
    def action_open(self) -> None: ...
    def action_save(self) -> None: ...
    def action_save_as(self) -> None: ...
    def action_open_backups_folder(self) -> None: ...
    def action_load_reference(self) -> bool: ...
    def action_compare_arbre(self) -> None: ...
    def action_reinspection(self) -> None: ...

    # Exports — menu dédié, groupé par format (PDF/PNG/XLSX/CSV/HTML) ;
    # chaque action précise dans son libellé si elle porte sur l'arbre
    # courant ou sur la mission (cf. `app_export_actions.ExportActionsMixin`).
    def action_export_pdf_arbre(self) -> None: ...
    def action_export_pdf_mission(self) -> None: ...
    def action_export_png(self) -> None: ...
    def action_export_comparison_pdf(self) -> None: ...
    def action_export_comparison_png(self) -> None: ...
    def action_export_prbs_xlsx(self) -> None: ...
    def action_export_prbs_html(self) -> None: ...
    def action_export_csv(self) -> None: ...
    def action_export_synthesis_xlsx(self) -> None: ...
    def action_export_synthesis_csv(self) -> None: ...

    # Actions Arbres
    def action_add_arbre(self) -> None: ...
    def action_next_arbre(self) -> None: ...
    def action_prev_arbre(self) -> None: ...
    def action_next_a_finir(self) -> None: ...
    def action_dup_arbre(self) -> None: ...
    def action_rename_arbre(self) -> None: ...
    def action_del_arbre(self) -> None: ...

    # Affichage
    def action_set_ui_scale(self, scale: float) -> None: ...
    def get_ui_scale(self) -> float: ...
    def action_set_high_contrast(self, on: bool) -> None: ...
    def get_high_contrast(self) -> bool: ...
    def action_cabinet_settings(self) -> None: ...
    def action_bareme_settings(self) -> None: ...
    def action_set_language(self, lang: str) -> None: ...
    def get_language_code(self) -> str: ...

    # Aide
    def action_restart(self) -> None: ...
    def action_about(self) -> None: ...
    def action_shortcuts(self) -> None: ...
    def action_open_guide(self) -> None: ...
    def action_contact_support(self) -> None: ...
    def action_open_log(self) -> None: ...
    def action_check_updates(self) -> None: ...
    def action_toggle_check_updates(self) -> None: ...
    def get_check_updates(self) -> bool: ...

    # Récents — l'App ouvre directement le chemin sans dialogue.
    def action_open_recent(self, path: str) -> None: ...
    def get_recent_files(self) -> list[str]: ...


# Une entrée du menu Export = (libellé, commande, accélérateur|None).
_ExportItem = Tuple[str, Callable[[], None], Optional[str]]


def _add_export_section(menu: tk.Menu, titre: str,
                        items: Sequence[_ExportItem], *,
                        last: bool = False) -> None:
    """Ajoute un bloc d'un format (PDF/PNG/XLSX/CSV/HTML) au menu Export :
    un en-tête désactivé nommant le format, ses entrées, puis un
    séparateur (omis après le dernier bloc). Factorisé pour que les 5
    blocs restent visuellement identiques sans dupliquer la plomberie
    `add_command`/`add_separator`."""
    menu.add_command(label=f"— {titre} —", state="disabled")
    for label, command, accelerator in items:
        if accelerator:
            menu.add_command(label=label, accelerator=accelerator,
                             command=command)
        else:
            menu.add_command(label=label, command=command)
    if not last:
        menu.add_separator()


def _section(menu: tk.Menu, titre: str, *, first: bool = False) -> None:
    """En-tête de section désactivé, même style visuel que le menu Export
    (`_add_export_section`) — mais pour les menus dont les entrées ne
    sont pas de simples `add_command` (cascades, checkbuttons…), d'où un
    helper séparé plutôt qu'un format d'item partagé. Sépare du groupe
    précédent par un trait (omis avant le tout premier groupe du menu)."""
    if not first:
        menu.add_separator()
    menu.add_command(label=f"— {titre} —", state="disabled")


def build_menu(app: AppLike) -> None:
    """Construit et attache la barre de menu de `app` (Tk root).

    Les raccourcis globaux (Ctrl+N/O/S/T) sont également câblés ici.
    """
    # `tk.Menu(parent)` exige un `tk.Misc` concret ; `AppLike` est un
    # Protocol structurel qui n'hérite pas de `Misc`. Le cast est sûr :
    # à l'usage `app` est toujours une instance de `tk.Tk` (l'App).
    m = tk.Menu(cast(tk.Misc, app))
    app.config(menu=m)
    # Mémorisé pour que `comparaison.open_comparison` puisse donner à sa
    # fenêtre EXACTEMENT le même bandeau (un `tk.Menu` peut être attaché
    # comme barre de menu à plusieurs fenêtres à la fois) plutôt qu'un
    # sous-ensemble reconstruit à la main.
    setattr(app, "_menubar", m)

    # Fichier — organisé PAR ÉTAPE du cycle de vie (même principe que le
    # rangement par format du menu Export) plutôt que dans l'ordre où les
    # entrées ont été ajoutées au fil des fonctionnalités.
    f = tk.Menu(m, tearoff=0)
    _section(f, _("Mission"), first=True)
    f.add_command(label=_("Nouvelle mission"), accelerator="Ctrl+N",
                  command=app.action_new)
    f.add_command(label=_("Ouvrir mission…"), accelerator="Ctrl+O",
                  command=app.action_open)
    recent_menu = tk.Menu(f, tearoff=0)
    f.add_cascade(label=_("Ouvrir récent"), menu=recent_menu)
    setattr(app, "_recent_menu", recent_menu)
    refresh_recent_menu(app)
    f.add_command(label=_("Ouvrir la mission d'exemple…"),
                  command=app.action_open_demo)
    _section(f, _("Modèles"))
    f.add_command(label=_("Nouvelle mission depuis un modèle…"),
                  command=app.action_new_from_template)
    f.add_command(label=_("Enregistrer comme modèle…"),
                  command=app.action_save_as_template)
    _section(f, _("Enregistrement"))
    f.add_command(label=_("Enregistrer"), accelerator="Ctrl+S",
                  command=app.action_save)
    f.add_command(label=_("Enregistrer sous…"), command=app.action_save_as)
    f.add_command(label=_("Ouvrir le dossier des sauvegardes…"),
                  command=app.action_open_backups_folder)
    f.add_separator()
    f.add_command(label=_("Quitter"), command=app.destroy)
    m.add_cascade(label=_("Fichier"), menu=f)

    # Comparaison (ré-inspection)
    c = tk.Menu(m, tearoff=0)
    c.add_command(label=_("Faire une comparaison (ré-inspection)…"),
                  command=app.action_reinspection)
    c.add_command(label=_("Diagnostic de la comparaison…"),
                  command=app.action_compare_arbre, state="disabled")
    app._menu_comparaison = c  # type: ignore[attr-defined]
    m.add_cascade(label=_("Comparaison"), menu=c)

    # Arbres
    a = tk.Menu(m, tearoff=0)
    _section(a, _("Ajouter"), first=True)
    a.add_command(label=_("Ajouter un arbre"), accelerator="Ctrl+T",
                  command=app.action_add_arbre)
    _section(a, _("Navigation"))
    a.add_command(label="Arbre suivant", accelerator="Ctrl+PgDn",
                  command=app.action_next_arbre)
    a.add_command(label=_("Arbre précédent"), accelerator="Ctrl+PgUp",
                  command=app.action_prev_arbre)
    a.add_command(label=_("Prochain arbre à finir"),
                  command=app.action_next_a_finir)
    _section(a, _("Modifier"))
    a.add_command(label=_("Dupliquer l'arbre courant"),
                  command=app.action_dup_arbre)
    a.add_command(label=_("Renommer l'arbre courant…"),
                  command=app.action_rename_arbre)
    a.add_command(label=_("Supprimer l'arbre courant…"),
                  command=app.action_del_arbre)
    m.add_cascade(label=_("Arbres"), menu=a)

    # Affichage
    v = tk.Menu(m, tearoff=0)
    _section(v, _("Accessibilité"), first=True)
    scale_var = tk.DoubleVar(value=app.get_ui_scale())
    setattr(app, "_ui_scale_var", scale_var)
    taille = tk.Menu(v, tearoff=0)
    for label, factor in ((_("Petit"), 0.85), (_("Normal"), 1.0),
                          (_("Grand"), 1.2), (_("Très grand"), 1.4)):
        taille.add_radiobutton(
            label=label, value=factor, variable=scale_var,
            command=partial(app.action_set_ui_scale, factor))
    v.add_cascade(label=_("Taille du texte"), menu=taille)
    hc_var = tk.BooleanVar(value=app.get_high_contrast())
    setattr(app, "_high_contrast_var", hc_var)
    v.add_checkbutton(
        label=_("Contraste élevé"), variable=hc_var,
        command=lambda: app.action_set_high_contrast(hc_var.get()))
    _section(v, _("Préférences"))
    v.add_command(label=_("Logo et nom du cabinet…"),
                  command=app.action_cabinet_settings)
    v.add_command(label=_("Barème de classification…"),
                  command=app.action_bareme_settings)
    # Sous-menu Langue (fr / en / it)
    lang_menu = tk.Menu(v, tearoff=0)
    cur_lang = app.get_language_code()
    lang_var = tk.StringVar(value=cur_lang)
    setattr(app, "_lang_var", lang_var)
    for code, label in LANGUAGES.items():
        lang_menu.add_radiobutton(
            label=label, value=code, variable=lang_var,
            command=partial(app.action_set_language, code))
    v.add_cascade(label=_("Langue"), menu=lang_menu)
    m.add_cascade(label=_("Affichage"), menu=v)

    # Export — point d'entrée UNIQUE des exports (2026-09-05) : avant,
    # dispersés entre ce menu (exports mission) et l'onglet Diagnostic
    # (exports arbre). Regroupés ici PAR FORMAT (un bloc par
    # PDF/PNG/XLSX/CSV/HTML, en-tête désactivé) plutôt que par portée —
    # chaque libellé précise s'il porte sur l'arbre courant ou la mission.
    x = tk.Menu(m, tearoff=0)
    _add_export_section(x, "PDF", (
        (_("Fiche PDF (arbre courant)"), app.action_export_pdf_arbre,
         "Ctrl+E"),
        (_("Exporter toutes les fiches (PDF)…"),
         app.action_export_pdf_mission, None),
    ), last=True)
    # Export de la comparaison en cours (« Diagnostic de la comparaison… »).
    # Grisé tant qu'aucune comparaison n'est ouverte — avant, ces deux
    # exports vivaient dans des boutons de la fenêtre de comparaison
    # elle-même, la coupant du menu Export pendant qu'elle était ouverte.
    # État tenu à jour par `postcommand` juste avant que le menu s'affiche
    # (`_refresh_export_comparison_state`) plutôt que par un callback
    # explicite à l'ouverture/fermeture de la fenêtre.
    x.add_command(label=_("Comparaison — fiche PDF…"),
                  command=app.action_export_comparison_pdf,
                  state="disabled")
    idx_export_comparison_pdf = cast(int, x.index("end"))
    x.add_separator()
    _add_export_section(x, "PNG", (
        (_("PNG du dessin"), app.action_export_png, None),
    ), last=True)
    x.add_command(label=_("Comparaison — évolution (PNG)…"),
                  command=app.action_export_comparison_png,
                  state="disabled")
    idx_export_comparison_png = cast(int, x.index("end"))
    x.add_separator()
    _add_export_section(x, "XLSX", (
        (_("Tableau PRBS — Excel (XLSX)…"), app.action_export_prbs_xlsx,
         None),
        (_("Exporter la synthèse mission (XLSX)…"),
         app.action_export_synthesis_xlsx, None),
    ))
    _add_export_section(x, "CSV", (
        (_("Exporter sondages mission (CSV)…"), app.action_export_csv,
         None),
        (_("Exporter la synthèse mission (CSV)…"),
         app.action_export_synthesis_csv, None),
    ))
    _add_export_section(x, "HTML", (
        (_("Tableau PRBS — page HTML…"), app.action_export_prbs_html,
         None),
    ), last=True)

    def _refresh_export_comparison_state() -> None:
        from comparaison import is_comparison_active
        state = "normal" if is_comparison_active() else "disabled"
        x.entryconfigure(idx_export_comparison_pdf, state=state)
        x.entryconfigure(idx_export_comparison_png, state=state)

    x.configure(postcommand=_refresh_export_comparison_state)
    m.add_cascade(label=_("Export"), menu=x)

    # Aide
    h = tk.Menu(m, tearoff=0)
    _section(h, _("Aide"), first=True)
    h.add_command(label=_("Guide de démarrage…"),
                  command=app.action_open_guide)
    h.add_command(label=_("Raccourcis clavier…"),
                  command=app.action_shortcuts)
    _section(h, _("Support"))
    h.add_command(label=_("Contacter le support…"),
                  command=app.action_contact_support)
    h.add_command(label=_("Ouvrir le fichier de log"),
                  command=app.action_open_log)
    _section(h, _("Mises à jour"))
    h.add_command(label=_("Vérifier les mises à jour"),
                  command=app.action_check_updates)
    chk_var = tk.BooleanVar(value=app.get_check_updates())
    setattr(app, "_check_updates_var", chk_var)
    h.add_checkbutton(
        label=_("Vérification automatique au démarrage"),
        variable=chk_var,
        command=app.action_toggle_check_updates)
    h.add_separator()
    h.add_command(label=_("Redémarrer l'application"),
                  command=app.action_restart)
    h.add_command(label=_("À propos"), command=app.action_about)
    m.add_cascade(label=_("Aide"), menu=h)

    # Raccourcis globaux
    app.bind_all("<Control-n>", lambda e: app.action_new())
    app.bind_all("<Control-o>", lambda e: app.action_open())
    app.bind_all("<Control-s>", lambda e: app.action_save())
    app.bind_all("<Control-t>", lambda e: app.action_add_arbre())


def refresh_recent_menu(app: AppLike) -> None:
    """Vide et reconstruit le sous-menu « Ouvrir récent » à partir de
    `app.get_recent_files()`. À appeler par l'App après chaque ouverture
    ou enregistrement pour que la liste reflète l'historique courant."""
    menu = getattr(app, "_recent_menu", None)
    if menu is None:
        return
    menu.delete(0, "end")
    paths = app.get_recent_files()
    if not paths:
        menu.add_command(label="(aucun)", state="disabled")
        return
    for i, p in enumerate(paths, 1):
        # Affichage : "1. nom.json — /chemin/parent" (raccourci Alt+i
        # pour les 9 premiers via &i dans le label Tk : `underline`).
        from pathlib import Path
        pp = Path(p)
        label = f"{pp.name}  —  {pp.parent}"
        # Closure : capturer p par défaut, sinon Python lie p dynamiquement.
        menu.add_command(label=label,
                          command=lambda path=p: app.action_open_recent(path))
