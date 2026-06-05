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
from typing import Any, Callable, Protocol, cast


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
    def action_new(self) -> None: ...
    def action_open(self) -> None: ...
    def action_save(self) -> None: ...
    def action_save_as(self) -> None: ...
    # Exports globaux (mission) — les exports individuels (PNG, fiche
    # PDF, tableau XLSX/HTML) restent accessibles depuis l'onglet
    # Diagnostic, qui les expose en haut du pane.
    def action_export_pdf_mission(self) -> None: ...
    def action_export_csv(self) -> None: ...
    def action_export_synthesis_xlsx(self) -> None: ...
    def action_export_synthesis_csv(self) -> None: ...

    # Actions Arbres
    def action_add_arbre(self) -> None: ...
    def action_dup_arbre(self) -> None: ...
    def action_rename_arbre(self) -> None: ...
    def action_del_arbre(self) -> None: ...

    # Aide
    def action_about(self) -> None: ...
    def action_shortcuts(self) -> None: ...
    def action_open_log(self) -> None: ...

    # Récents — l'App ouvre directement le chemin sans dialogue.
    def action_open_recent(self, path: str) -> None: ...
    def get_recent_files(self) -> list[str]: ...


def build_menu(app: AppLike) -> None:
    """Construit et attache la barre de menu de `app` (Tk root).

    Les raccourcis globaux (Ctrl+N/O/S/T) sont également câblés ici.
    """
    # `tk.Menu(parent)` exige un `tk.Misc` concret ; `AppLike` est un
    # Protocol structurel qui n'hérite pas de `Misc`. Le cast est sûr :
    # à l'usage `app` est toujours une instance de `tk.Tk` (l'App).
    m = tk.Menu(cast(tk.Misc, app))
    app.config(menu=m)

    # Fichier
    f = tk.Menu(m, tearoff=0)
    f.add_command(label="Nouvelle mission", accelerator="Ctrl+N",
                  command=app.action_new)
    f.add_command(label="Ouvrir mission…", accelerator="Ctrl+O",
                  command=app.action_open)
    # Sous-menu Récents — populé par `refresh_recent_menu` (appelé par
    # l'App au démarrage et après chaque ouverture/enregistrement).
    recent_menu = tk.Menu(f, tearoff=0)
    f.add_cascade(label="Ouvrir récent", menu=recent_menu)
    # Exposer le menu sur l'App pour qu'elle puisse le rafraîchir sans
    # reconstruire toute la barre de menu (réutilise les méthodes Tk
    # de Menu : delete / add_command).
    setattr(app, "_recent_menu", recent_menu)
    refresh_recent_menu(app)
    f.add_command(label="Enregistrer", accelerator="Ctrl+S",
                  command=app.action_save)
    f.add_command(label="Enregistrer sous…", command=app.action_save_as)
    f.add_separator()
    f.add_command(label="Exporter la synthèse mission (XLSX)…",
                  command=app.action_export_synthesis_xlsx)
    f.add_command(label="Exporter la synthèse mission (CSV)…",
                  command=app.action_export_synthesis_csv)
    f.add_command(label="Exporter toutes les fiches (PDF)…",
                  command=app.action_export_pdf_mission)
    f.add_command(label="Exporter sondages mission (CSV)…",
                  command=app.action_export_csv)
    f.add_separator()
    f.add_command(label="Quitter", command=app.destroy)
    m.add_cascade(label="Fichier", menu=f)

    # Arbres
    a = tk.Menu(m, tearoff=0)
    a.add_command(label="Ajouter un arbre", accelerator="Ctrl+T",
                  command=app.action_add_arbre)
    a.add_command(label="Dupliquer l'arbre courant",
                  command=app.action_dup_arbre)
    a.add_command(label="Renommer l'arbre courant",
                  command=app.action_rename_arbre)
    a.add_command(label="Supprimer l'arbre courant",
                  command=app.action_del_arbre)
    m.add_cascade(label="Arbres", menu=a)

    # Aide
    h = tk.Menu(m, tearoff=0)
    h.add_command(label="Raccourcis clavier…",
                  command=app.action_shortcuts)
    h.add_command(label="Ouvrir le fichier de log",
                  command=app.action_open_log)
    h.add_separator()
    h.add_command(label="À propos", command=app.action_about)
    m.add_cascade(label="Aide", menu=h)

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
