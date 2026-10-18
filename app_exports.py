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
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

from bareme import classer_prbs, description_seuils_mission
from diagnostic import (
    degradation_externe_par_grade,
    mission_completeness_warnings,
    mission_synthesis_rows,
)
from dialogs import ProgressDialog
from export import HAS_OPENPYXL, export_prbs_html, export_prbs_xlsx
from export_synthesis import export_synthesis_csv, export_synthesis_xlsx
from fiche_pdf import HAS_FPDF, _new_pdf, render_fiche_arbre
from geometry import DIRECTION_LABELS, GRADES
from i18n import _
from model import Arbre, Chantier, label_brin
from palette import COULEUR_CLASSE
from pil_render import HAS_PIL, render_arbre_to_pil_image

log = logging.getLogger("penetrometre")


def _get_cabinet_info(parent: tk.Misc) -> "tuple[str, str | None]":
    """Extrait (cabinet_name, logo_path) depuis les settings de l'hôte App."""
    settings = getattr(parent, "_settings", None)
    if settings is None:
        return "", None
    return getattr(settings, "cabinet_name", ""), getattr(settings, "logo_path", None)


def _check_completeness(parent: tk.Misc, chantier: "Chantier") -> bool:
    """Vérifie la complétude de la mission avant export.

    Si des avertissements existent, affiche un dialog non bloquant avec
    les problèmes détectés. L'utilisateur peut exporter quand même ou
    annuler pour corriger. Renvoie True si l'export peut continuer."""
    warnings = mission_completeness_warnings(chantier)
    if not warnings:
        return True
    detail = "\n".join(f"  • {w}" for w in warnings)
    msg = (f"{_('La mission présente des points incomplets :')}\n\n"
           f"{detail}\n\n"
           f"{_('Exporter quand même ?')}")
    return messagebox.askyesno(
        _("Vérification avant export"), msg, parent=parent)


def _notify_export(parent: tk.Misc, path: str, label: str) -> None:
    """Feedback de succès d'export. Non-modal via la barre d'état de
    l'App (`notify_export`) si l'hôte la fournit ; sinon `messagebox`
    classique (parent générique, contexte de test). Évite le « OK » à
    cliquer après chaque export."""
    notify = getattr(parent, "notify_export", None)
    if callable(notify):
        notify(path, label)
    else:
        messagebox.showinfo(_("Exporté"), f"{label} :\n{path}")


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


def _need_fpdf() -> bool:
    """Affiche un message clair si fpdf2 est absent (fiche PDF vectorielle).
    Renvoie True si OK pour continuer, False si on doit avorter."""
    if HAS_FPDF:
        return True
    messagebox.showinfo(
        "fpdf2 requis",
        "L'export de la fiche PDF nécessite fpdf2.\n"
        "Installez-le :  pip install fpdf2")
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
            arbre, width=2400, height=2400,
            show_sondages=show_sondages,
            show_legend=True)
        img.save(p, "PNG")
        _notify_export(parent, p, _("Image PNG enregistrée"))
    except Exception as e:
        log.exception("Échec export PNG")
        messagebox.showerror("Erreur d'export", str(e))


def export_pdf_arbre(parent: tk.Misc, arbre: Optional[Arbre],
                     chantier: Chantier,
                     show_sondages: bool = True,
                     mission_file: Optional[Path] = None) -> None:
    """Exporte une fiche PDF (dessin + tableau + diagnostic) pour
    l'arbre courant. Utilise uniquement Pillow (multi-pages via save).

    `show_sondages` : reflète la case « Afficher les sondages » (pastilles
    sur le dessin uniquement ; le tableau PRBS reste présent)."""
    if not _need_pil("PDF"):
        return
    if not _need_fpdf():
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
        cabinet_name, logo_path = _get_cabinet_info(parent)
        pdf = _new_pdf()
        render_fiche_arbre(pdf, arbre, chantier,
                           show_sondages=show_sondages,
                           logo_path=logo_path,
                           cabinet_name=cabinet_name,
                           mission_file=mission_file)
        pdf.output(p)
        _notify_export(parent, p, _("Fiche PDF enregistrée"))
    except Exception as e:
        log.exception("Échec export PDF")
        messagebox.showerror("Erreur d'export PDF", str(e))


def export_pdf_mission(parent: tk.Misc, chantier: Chantier,
                       show_sondages: bool = True,
                       mission_file: Optional[Path] = None) -> None:
    """Exporte un PDF unique multi-pages regroupant les fiches de tous
    les arbres de la mission. `show_sondages` : cf. `export_pdf_arbre`."""
    if not _need_pil("PDF"):
        return
    if not _need_fpdf():
        return
    if not _check_completeness(parent, chantier):
        return
    arbres = [a for a in chantier.arbres if a.rayon_tronc_cm > 0]
    if not arbres:
        messagebox.showinfo(
            _("Rien à exporter"),
            "Aucun arbre avec un rayon renseigné dans cette mission.")
        return
    suggest = f"fiches_mission_{chantier.nom or 'sans_nom'}.pdf".replace(" ", "_")
    p = filedialog.asksaveasfilename(
        defaultextension=".pdf",
        initialfile=suggest,
        filetypes=[("Document PDF", "*.pdf")])
    if not p:
        return
    # ~60 ms par fiche : produire le PDF d'une traite gèle la fenêtre (300
    # arbres ⟹ ~20 s, l'OS la marque « ne répond pas »). On boucle donc en
    # rendant la main à Tk entre chaque fiche — voir `ProgressDialog` pour
    # les raisons de NE PAS passer par un thread.
    cabinet_name, logo_path = _get_cabinet_info(parent)
    prog = ProgressDialog(
        parent, _("Export PDF de la mission"), len(arbres),
        message=_("Génération des fiches…"))
    annule = False
    try:
        pdf = _new_pdf()
        for i, a in enumerate(arbres, start=1):
            # `avancer` repeint ET traite les événements en attente :
            # c'est ce qui garde le bouton Annuler réactif.
            prog.avancer(i - 1, _("Arbre n°{num}").format(
                num=a.numero_arbre or "?"))
            if prog.demande_annulation():
                annule = True
                break
            render_fiche_arbre(
                pdf, a, chantier,
                show_sondages=show_sondages,
                logo_path=logo_path,
                cabinet_name=cabinet_name,
                mission_file=mission_file)
        if not annule:
            prog.avancer(len(arbres), _("Écriture du fichier…"))
            # L'écriture n'a lieu qu'une fois TOUTES les fiches produites :
            # un PDF de mission tronqué serait pris pour un export complet.
            pdf.output(p)
    except Exception as e:
        prog.fermer()
        log.exception("Échec export PDF mission")
        messagebox.showerror("Erreur d'export PDF", str(e))
        return
    prog.fermer()

    if annule:
        set_status = getattr(parent, "set_status", None)
        if set_status:
            set_status(_("Export PDF annulé — aucun fichier écrit."))
        return
    _notify_export(parent, p,
                   f"PDF mission enregistré ({len(arbres)} fiche(s))")


def export_csv_mission(parent: tk.Misc, chantier: Chantier) -> None:
    """CSV de tous les sondages de la mission. Séparateur `;`,
    encodage UTF-8 avec BOM (compatible Excel). Colonnes ajustées
    uniquement (PRBS et t/R tiennent compte des dégradations externes).

    **Itère les brins**, pas les propriétés-relais du genet. `Arbre.sondages`
    et `Arbre.rayon_tronc_cm` renvoient vers `brins[0]` (compat mono-caule) :
    boucler dessus faisait disparaître du CSV, en silence, tous les sondages
    des brins b, c… d'une cépée. La colonne « Brin » n'est renseignée que
    pour les cépées, pour ne pas alourdir le cas courant.
    """
    p = filedialog.asksaveasfilename(
        defaultextension=".csv",
        filetypes=[("CSV", "*.csv")])
    if not p:
        return
    try:
        with open(p, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow([f"# Barème appliqué : "
                        f"{description_seuils_mission(chantier)}"])
            w.writerow(["N° arbre", "Brin", "Essence", "Rayon (cm)",
                        "Port",
                        "N° sondage", "Grade (gr)", "Direction",
                        "PRBS (cm)", "Bois altéré (cm)",
                        "t/R (%)",
                        "Classe",
                        "Compartimentation", "Commentaire"])
            for a in chantier.arbres:
                brins = list(a.brins) or []
                multi = len(brins) > 1
                for i, b in enumerate(brins):
                    R = b.rayon_tronc_cm
                    # Rayon ET dégradations externes sont propres au brin.
                    deg_ext_par_grade = degradation_externe_par_grade(b)
                    # Repli sur l'indice si `label` est vide (cf.
                    # `model.label_brin`).
                    label = (b.label or label_brin(i)) if multi else ""
                    for s in b.sondages:
                        d = DIRECTION_LABELS.get(s.grade, "")
                        idx_g = (GRADES.index(s.grade)
                                 if s.grade in GRADES else 0)
                        deg_ext = deg_ext_par_grade[idx_g]
                        prbs_adj = max(0.0, s.prbs_cm - deg_ext)
                        ratio_adj = prbs_adj / R if R > 0 else 0.0
                        tR_pct = f"{100*ratio_adj:.1f}"
                        # Le port reste une donnée du genet.
                        classe = classer_prbs(ratio_adj, a.port_arbre)
                        w.writerow([a.numero_arbre, label, a.essence,
                                    R, a.port_arbre,
                                    s.numero,
                                    s.grade, d,
                                    prbs_adj, s.bois_altere_cm + deg_ext,
                                    tR_pct,
                                    classe,
                                    s.compartimentation, s.commentaire])
        _notify_export(parent, p, "CSV mission enregistré")
    except Exception as e:
        log.exception("Échec export CSV")
        messagebox.showerror("Erreur", str(e))


def _suggest_synthesis_name(chantier: Chantier, ext: str) -> str:
    return (f"synthese_mission_{chantier.nom or 'sans_nom'}.{ext}"
            .replace(" ", "_"))


def export_synthesis_csv_mission(parent: tk.Misc,
                                 chantier: Chantier) -> None:
    """Synthèse mission (1 ligne/arbre : classe, t/R minimal,
    direction critique) en CSV."""
    if not _check_completeness(parent, chantier):
        return
    p = filedialog.asksaveasfilename(
        defaultextension=".csv",
        initialfile=_suggest_synthesis_name(chantier, "csv"),
        filetypes=[("CSV", "*.csv")])
    if not p:
        return
    try:
        export_synthesis_csv(
            mission_synthesis_rows(chantier, trier_par_urgence=True), p,
            bareme_desc=description_seuils_mission(chantier))
        _notify_export(parent, p, _("Synthèse mission CSV enregistrée"))
    except Exception as e:
        log.exception("Échec export synthèse CSV")
        messagebox.showerror("Erreur", str(e))


def export_synthesis_xlsx_mission(parent: tk.Misc,
                                  chantier: Chantier) -> None:
    """Synthèse mission en .xlsx thémé (cellule classe colorée,
    autofiltre pour trier par risque)."""
    if not _check_completeness(parent, chantier):
        return
    if not HAS_OPENPYXL:
        messagebox.showerror(
            "Export XLSX indisponible",
            "Le module openpyxl n'est pas installé.\n\n"
            "Pour activer cet export, lancez dans un terminal :\n"
            "    pip install -r requirements.txt\n\n"
            "L'export CSV de la synthèse reste disponible sans dépendance.")
        return
    p = filedialog.asksaveasfilename(
        defaultextension=".xlsx",
        initialfile=_suggest_synthesis_name(chantier, "xlsx"),
        filetypes=[("Classeur Excel", "*.xlsx")])
    if not p:
        return
    try:
        export_synthesis_xlsx(
            mission_synthesis_rows(chantier, trier_par_urgence=True),
            chantier, p,
            couleur_classe=COULEUR_CLASSE,
            bareme_desc=description_seuils_mission(chantier))
        _notify_export(parent, p, _("Synthèse mission XLSX enregistrée"))
    except Exception as e:
        log.exception("Échec export synthèse XLSX")
        messagebox.showerror("Erreur", str(e))


def export_xlsx_arbre(parent: tk.Misc, arbre: Optional[Arbre],
                      chantier: Chantier) -> None:
    if not arbre:
        return
    if not HAS_OPENPYXL:
        messagebox.showerror(
            "Export XLSX indisponible",
            "Le module openpyxl n'est pas installé.\n\n"
            "Pour activer cet export, lancez dans un terminal :\n"
            "    pip install -r requirements.txt\n\n"
            "L'export HTML reste disponible sans dépendance.")
        return
    if arbre.rayon_tronc_cm <= 0:
        messagebox.showerror(
            "Export impossible",
            "Renseignez un rayon de tronc avant l'export.")
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
        cabinet_name, _logo = _get_cabinet_info(parent)
        export_prbs_xlsx(arbre, chantier, p,
                         couleur_classe=COULEUR_CLASSE,
                         classer_prbs=classer_prbs,
                         cabinet_name=cabinet_name,
                         bareme_desc=description_seuils_mission(chantier))
        _notify_export(parent, p, "Tableau XLSX enregistré")
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
            "Renseignez un rayon de tronc avant l'export.")
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
        cabinet_name, _logo = _get_cabinet_info(parent)
        export_prbs_html(arbre, chantier, p,
                         couleur_classe=COULEUR_CLASSE,
                         classer_prbs=classer_prbs,
                         cabinet_name=cabinet_name,
                         bareme_desc=description_seuils_mission(chantier))
        _notify_export(parent, p, "Tableau HTML enregistré")
    except Exception as e:
        log.exception("Échec export HTML")
        messagebox.showerror("Erreur", str(e))
