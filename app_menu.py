"""
Barre de menu de l'application Pénétromètre.

Module séparé de `penetrometre.py` pour la même raison qu'`app_style.py` :
ce sont ~50 lignes de plomberie déclarative (entrées de menu, raccourcis
clavier) qui n'ont pas leur place dans le corps de la classe `App`.

`build_menu(app)` attache la barre de menu à `app` et bind les
accélérateurs globaux. Les commandes pointent vers les méthodes
`action_*` de `app` — on les appelle dynamiquement via `getattr`-style
accès (`app.action_new`, etc.), donc l'agencement est resté simple :
ce module reste un pur agencement de widgets Tk.
"""

from __future__ import annotations

import tkinter as tk
from typing import Any


def build_menu(app: Any) -> None:
    """Construit et attache la barre de menu de `app` (Tk root).

    `app` doit exposer les méthodes :
    - `action_new`, `action_open`, `action_save`, `action_save_as`,
      `action_export_png`, `action_export_pdf_arbre`,
      `action_export_prbs_xlsx`, `action_export_prbs_html`,
      `action_export_csv`,
    - `action_add_arbre`, `action_dup_arbre`,
      `action_rename_arbre`, `action_del_arbre`,
    - `action_about`,
    - `destroy` (héritée de Tk).

    Les raccourcis globaux (Ctrl+N/O/S/T) sont également câblés ici.
    """
    m = tk.Menu(app)
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
