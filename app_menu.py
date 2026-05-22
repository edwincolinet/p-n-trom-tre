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
    def action_export_png(self) -> None: ...
    def action_export_pdf_arbre(self) -> None: ...
    def action_export_prbs_xlsx(self) -> None: ...
    def action_export_prbs_html(self) -> None: ...
    def action_export_csv(self) -> None: ...

    # Actions Arbres
    def action_add_arbre(self) -> None: ...
    def action_dup_arbre(self) -> None: ...
    def action_rename_arbre(self) -> None: ...
    def action_del_arbre(self) -> None: ...

    # Aide
    def action_about(self) -> None: ...


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
    f.add_command(label="Enregistrer", accelerator="Ctrl+S",
                  command=app.action_save)
    f.add_command(label="Enregistrer sous…", command=app.action_save_as)
    f.add_separator()
    f.add_command(label="Exporter dessin (PNG)…",
                  command=app.action_export_png)
    f.add_command(label="Exporter fiche arbre (PDF)…",
                  command=app.action_export_pdf_arbre)
    f.add_command(label="Exporter tableau arbre (XLSX)…",
                  command=app.action_export_prbs_xlsx)
    f.add_command(label="Exporter tableau arbre (HTML)…",
                  command=app.action_export_prbs_html)
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
    h.add_command(label="À propos", command=app.action_about)
    m.add_cascade(label="?", menu=h)

    # Raccourcis globaux
    app.bind_all("<Control-n>", lambda e: app.action_new())
    app.bind_all("<Control-o>", lambda e: app.action_open())
    app.bind_all("<Control-s>", lambda e: app.action_save())
    app.bind_all("<Control-t>", lambda e: app.action_add_arbre())
