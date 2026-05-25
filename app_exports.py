"""
Actions d'export de la fenêtre App.

Chaque fonction de ce module incarne UNE action utilisateur (Export
PNG, Export PDF, Export CSV mission, Export tableau XLSX/HTML d'un
arbre). Elle gère :

- la vérification des prérequis (Pillow, openpyxl) avec un
  `messagebox` clair si manquant ;
- le `filedialog` (nom de fichier suggéré, filtres d'extension) ;
- le `try/except` autour de l'écriture + `log.exception` pour que la
  stack trace finisse dans `~/.penetrometre/penetrometre.log` ;
- le `messagebox` de succès en fin de chemin heureux.

Le rendu PNG/PDF et la production XLSX/HTML eux-mêmes vivent dans
`pil_render.py` et `export.py`. Ce module est l'**adaptateur Tk** qui
glue ces fonctions pures aux dialogues système et au logger applicatif.

Aucune dépendance vers `penetrometre.py` (pas de cycle d'import).
"""

from __future__ import annotations

import csv
import logging
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Optional

from bareme import classer_prbs
from diagnostic import degradation_externe_par_grade
from export import HAS_OPENPYXL, export_prbs_html, export_prbs_xlsx
from fiche_pdf import render_fiche_arbre_to_pdf_page
from geometry import DIRECTION_LABELS, GRADES
from model import Arbre, Chantier
from palette import COULEUR_CLASSE
from pil_render import HAS_PIL, render_arbre_to_pil_image

log = logging.getLogger("penetrometre")


def _need_pil(format_label: str) -> bool:
    """Affiche un message clair si Pillow est absent. Renvoie True si
    OK pour continuer, False si on doit avorter."""
    if HAS_PIL:
        return True
    messagebox.showinfo(
        "Pillow requis",
        f"L'export {format_label} nécessite Pillow.\n"
        "Installez-le :  pip install Pillow")
    return False


def export_png(parent: tk.Misc, arbre: Optional[Arbre],
               show_sondages: bool) -> None:
    if not _need_pil("PNG"):
        return
    if not arbre:
        return
    p = filedialog.asksaveasfilename(
        defaultextension=".png",
        filetypes=[("Image PNG", "*.png")])
    if not p:
        return
    try:
        img = render_arbre_to_pil_image(
            arbre, width=1600, height=1600,
            show_sondages=show_sondages,
            show_legend=True)
        img.save(p, "PNG")
        messagebox.showinfo("Exporté", f"Image enregistrée : {p}")
    except Exception as e:
        log.exception("Échec export PNG")
        messagebox.showerror("Erreur d'export", str(e))


def export_pdf_arbre(parent: tk.Misc, arbre: Optional[Arbre],
                     chantier: Chantier) -> None:
    """Exporte une fiche PDF (dessin + tableau + diagnostic) pour
    l'arbre courant. Utilise uniquement Pillow (multi-pages via save)."""
    if not _need_pil("PDF"):
        return
    if not arbre:
        return
    suggest = (f"fiche_arbre_{arbre.numero_arbre or 'sans_num'}.pdf"
               .replace(" ", "_"))
    p = filedialog.asksaveasfilename(
        defaultextension=".pdf",
        initialfile=suggest,
        filetypes=[("Document PDF", "*.pdf")])
    if not p:
        return
    try:
        page = render_fiche_arbre_to_pdf_page(arbre, chantier)
        # Pillow : sauvegarder une image en PDF donne un PDF 1 page
        page.save(p, "PDF", resolution=150.0)
        messagebox.showinfo("Exporté", f"Fiche PDF enregistrée : {p}")
    except Exception as e:
        log.exception("Échec export PDF")
        messagebox.showerror("Erreur d'export PDF", str(e))


def export_pdf_mission(parent: tk.Misc, chantier: Chantier) -> None:
    """Exporte un PDF unique multi-pages regroupant les fiches de tous
    les arbres de la mission."""
    if not _need_pil("PDF"):
        return
    arbres = [a for a in chantier.arbres if a.rayon_tronc_cm > 0]
    if not arbres:
        messagebox.showinfo(
            "Rien à exporter",
            "Aucun arbre avec un rayon renseigné dans cette mission.")
        return
    suggest = f"fiches_mission_{chantier.nom or 'sans_nom'}.pdf".replace(" ", "_")
    p = filedialog.asksaveasfilename(
        defaultextension=".pdf",
        initialfile=suggest,
        filetypes=[("Document PDF", "*.pdf")])
    if not p:
        return
    try:
        pages = [render_fiche_arbre_to_pdf_page(a, chantier)
                 for a in arbres]
        pages[0].save(p, "PDF", resolution=150.0, save_all=True,
                      append_images=pages[1:])
        messagebox.showinfo(
            "Exporté",
            f"PDF mission enregistré ({len(pages)} fiche(s)) :\n{p}")
    except Exception as e:
        log.exception("Échec export PDF mission")
        messagebox.showerror("Erreur d'export PDF", str(e))


def export_csv_mission(parent: tk.Misc, chantier: Chantier) -> None:
    """CSV de tous les sondages de la mission. Séparateur `;`,
    encodage UTF-8 avec BOM (compatible Excel). Colonnes ajustées
    uniquement (PRBS et t/R tiennent compte des dégradations externes).
    """
    p = filedialog.asksaveasfilename(
        defaultextension=".csv",
        filetypes=[("CSV", "*.csv")])
    if not p:
        return
    try:
        with open(p, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["N° arbre", "Essence", "Rayon (cm)",
                        "Port",
                        "N° sondage", "Grade (gr)", "Direction",
                        "PRBS (cm)", "Bois altéré (cm)",
                        "t/R (%)",
                        "Classe",
                        "Compartimentation", "Commentaire"])
            for a in chantier.arbres:
                R = a.rayon_tronc_cm
                deg_ext_par_grade = degradation_externe_par_grade(a)
                for s in a.sondages:
                    d = DIRECTION_LABELS.get(s.grade, "")
                    idx_g = (GRADES.index(s.grade)
                             if s.grade in GRADES else 0)
                    deg_ext = deg_ext_par_grade[idx_g]
                    prbs_adj = max(0.0, s.prbs_cm - deg_ext)
                    ratio_adj = prbs_adj / R if R > 0 else 0.0
                    tR_pct = f"{100*ratio_adj:.1f}"
                    classe = classer_prbs(ratio_adj, a.port_arbre)
                    w.writerow([a.numero_arbre, a.essence,
                                a.rayon_tronc_cm, a.port_arbre,
                                s.numero,
                                s.grade, d,
                                prbs_adj, s.bois_altere_cm,
                                tR_pct,
                                classe,
                                s.compartimentation, s.commentaire])
        messagebox.showinfo("Exporté", f"CSV enregistré : {p}")
    except Exception as e:
        log.exception("Échec export CSV")
        messagebox.showerror("Erreur", str(e))


def export_xlsx_arbre(parent: tk.Misc, arbre: Optional[Arbre],
                      chantier: Chantier) -> None:
    if not arbre:
        return
    if not HAS_OPENPYXL:
        messagebox.showerror(
            "Export XLSX indisponible",
            "Le module openpyxl n'est pas installé.\n\n"
            "Pour activer cet export, lance dans un terminal :\n"
            "    pip install -r requirements.txt\n\n"
            "L'export HTML reste disponible sans dépendance.")
        return
    if arbre.rayon_tronc_cm <= 0:
        messagebox.showerror(
            "Export impossible",
            "Renseigne un rayon de tronc avant l'export.")
        return
    default = (f"tableau_arbre_{arbre.numero_arbre or 'X'}.xlsx"
               .replace(" ", "_"))
    p = filedialog.asksaveasfilename(
        defaultextension=".xlsx",
        initialfile=default,
        filetypes=[("Classeur Excel", "*.xlsx")])
    if not p:
        return
    try:
        export_prbs_xlsx(arbre, chantier, p,
                         couleur_classe=COULEUR_CLASSE,
                         classer_prbs=classer_prbs)
        messagebox.showinfo("Exporté", f"Tableau XLSX enregistré :\n{p}")
    except Exception as e:
        log.exception("Échec export XLSX")
        messagebox.showerror("Erreur", str(e))


def export_html_arbre(parent: tk.Misc, arbre: Optional[Arbre],
                      chantier: Chantier) -> None:
    if not arbre:
        return
    if arbre.rayon_tronc_cm <= 0:
        messagebox.showerror(
            "Export impossible",
            "Renseigne un rayon de tronc avant l'export.")
        return
    default = (f"tableau_arbre_{arbre.numero_arbre or 'X'}.html"
               .replace(" ", "_"))
    p = filedialog.asksaveasfilename(
        defaultextension=".html",
        initialfile=default,
        filetypes=[("Page HTML", "*.html")])
    if not p:
        return
    try:
        export_prbs_html(arbre, chantier, p,
                         couleur_classe=COULEUR_CLASSE,
                         classer_prbs=classer_prbs)
        messagebox.showinfo("Exporté", f"Tableau HTML enregistré :\n{p}")
    except Exception as e:
        log.exception("Échec export HTML")
        messagebox.showerror("Erreur", str(e))
