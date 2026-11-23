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
from typing import Any, Optional

import angle_units
from bareme import classer_prbs, description_seuils_mission
from diagnostic import (
    degradation_externe_par_grade,
    mission_completeness_warnings,
    mission_synthesis_rows,
)
from dialogs import ProgressDialog
from export import (
    HAS_OPENPYXL,
    export_prbs_html,
    export_prbs_ods,
    export_prbs_xlsx,
)
from export_mission import (
    export_prbs_mission_html,
    export_prbs_mission_ods,
    export_prbs_mission_xlsx,
)
from export_synthesis import (
    export_synthesis_csv,
    export_synthesis_ods,
    export_synthesis_xlsx,
)
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


# Formats d'image du dessin de section : clé → (extension, filtre de
# dialogue, nom du format pour la sauvegarde Pillow, libellé de succès).
_FORMATS_IMAGE = {
    "png": (".png", "Image PNG", "PNG"),
    "jpeg": (".jpg", "Image JPEG", "JPEG"),
}
_DESSIN_PX = 2400        # côté de l'image exportée (carré)
_JPEG_QUALITE = 95       # qualité JPEG : texte du dessin net, fichier léger


def _enregistrer_image(img: Any, chemin: str, fmt: str) -> None:
    """Écrit l'image de section au format `fmt` ("png" | "jpeg"). Le rendu est
    déjà en RGB (fond opaque) : aucune transparence à aplatir pour le JPEG."""
    _ext, _filtre, nom_pil = _FORMATS_IMAGE[fmt]
    if fmt == "jpeg":
        img.save(chemin, nom_pil, quality=_JPEG_QUALITE, optimize=True)
    else:
        img.save(chemin, nom_pil)


def nom_fichier_sur(texte: str, repli: str = "sans_num") -> str:
    """Fragment de nom de fichier sûr (Windows/macOS/Linux) tiré de `texte`
    (n° d'arbre saisi librement) : caractères interdits `\\ / : * ? " < > |`
    et contrôles remplacés par « _ », espaces en « _ », points/espaces de
    fin retirés. `repli` si rien n'en reste."""
    sûr = "".join("_" if (c in '\\/:*?"<>|' or ord(c) < 32) else c
                  for c in texte.strip())
    sûr = sûr.replace(" ", "_").strip("._")
    return sûr or repli


def noms_dessins_mission(arbres: "list[Arbre]", ext: str) -> "list[str]":
    """Un nom de fichier par arbre (`arbre_<n°>.<ext>`), **uniques** : deux
    arbres de même n° (ou de n° identiques une fois assainis) reçoivent un
    suffixe `_2`, `_3`… plutôt que de s'écraser mutuellement."""
    vus: "dict[str, int]" = {}
    noms: "list[str]" = []
    for a in arbres:
        base = f"arbre_{nom_fichier_sur(a.numero_arbre)}"
        vus[base.lower()] = vus.get(base.lower(), 0) + 1
        n = vus[base.lower()]
        noms.append(f"{base}{'' if n == 1 else f'_{n}'}{ext}")
    return noms


def export_dessin_arbre(parent: tk.Misc, arbre: Optional[Arbre],
                        show_sondages: bool, fmt: str = "png") -> None:
    """Dessin de section de l'arbre courant en image (`fmt` : "png" ou
    "jpeg")."""
    ext, filtre, nom_pil = _FORMATS_IMAGE[fmt]
    if not _need_pil(nom_pil):
        return
    if not arbre:
        return
    suggest = f"dessin_arbre_{nom_fichier_sur(arbre.numero_arbre, 'X')}{ext}"
    p = filedialog.asksaveasfilename(
        defaultextension=ext,
        initialfile=suggest,
        filetypes=[(filtre, f"*{ext}")])
    if not p:
        return
    try:
        img = render_arbre_to_pil_image(
            arbre, width=_DESSIN_PX, height=_DESSIN_PX,
            show_sondages=show_sondages,
            show_legend=True)
        _enregistrer_image(img, p, fmt)
        _notify_export(parent, p, _("Image {fmt} enregistrée").format(
            fmt=nom_pil))
    except Exception as e:
        log.exception("Échec export dessin %s", nom_pil)
        messagebox.showerror("Erreur d'export", str(e))


def export_png(parent: tk.Misc, arbre: Optional[Arbre],
               show_sondages: bool) -> None:
    export_dessin_arbre(parent, arbre, show_sondages, "png")


def export_dessin_mission(parent: tk.Misc, chantier: Chantier,
                          show_sondages: bool, fmt: str = "png") -> None:
    """Dessins de section de TOUS les arbres de la mission : un fichier image
    par arbre (`arbre_<n°>.<ext>`) dans un dossier choisi. Comme le PDF de
    mission, la boucle rend la main à Tk entre deux arbres (barre de
    progression annulable, aucun thread — cf. `ProgressDialog`)."""
    ext, _filtre, nom_pil = _FORMATS_IMAGE[fmt]
    if not _need_pil(nom_pil):
        return
    arbres = [a for a in chantier.arbres if a.rayon_tronc_cm > 0]
    if not arbres:
        messagebox.showinfo(
            _("Rien à exporter"),
            "Aucun arbre avec un rayon renseigné dans cette mission.")
        return
    dossier = filedialog.askdirectory(
        parent=parent, title=_("Dossier des dessins de la mission"))
    if not dossier:
        return
    noms = noms_dessins_mission(arbres, ext)
    existants = [n for n in noms if (Path(dossier) / n).exists()]
    if existants and not messagebox.askyesno(
            _("Fichiers existants"),
            _("{n} fichier(s) du dossier seront remplacés. Continuer ?")
            .format(n=len(existants)), parent=parent):
        return
    prog = ProgressDialog(
        parent, _("Export des dessins de la mission"), len(arbres),
        message=_("Génération des dessins…"))
    ecrits: "list[Path]" = []
    annule = False
    try:
        for i, (a, nom) in enumerate(zip(arbres, noms), start=1):
            prog.avancer(i - 1, _("Arbre n°\u00a0{num}").format(
                num=a.numero_arbre or "?"))
            if prog.demande_annulation():
                annule = True
                break
            img = render_arbre_to_pil_image(
                a, width=_DESSIN_PX, height=_DESSIN_PX,
                show_sondages=show_sondages, show_legend=True)
            cible = Path(dossier) / nom
            _enregistrer_image(img, str(cible), fmt)
            ecrits.append(cible)
        if not annule:
            prog.avancer(len(arbres), _("Terminé"))
    except Exception as e:
        prog.fermer()
        log.exception("Échec export dessins mission")
        messagebox.showerror(
            "Erreur d'export",
            f"{e}\n\n" + _("{n} dessin(s) déjà écrit(s) dans le dossier.")
            .format(n=len(ecrits)))
        return
    prog.fermer()
    if annule:
        set_status = getattr(parent, "set_status", None)
        if set_status:
            set_status(_("Export annulé — {n} dessin(s) déjà écrit(s).")
                       .format(n=len(ecrits)))
        return
    _notify_export(parent, dossier,
                   _("{n} dessin(s) {fmt} enregistré(s)").format(
                       n=len(ecrits), fmt=nom_pil))


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
            prog.avancer(i - 1, _("Arbre n°\u00a0{num}").format(
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
                        "N° sondage", angle_units.titre_colonne(), "Direction",
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
                                    angle_units.valeur(s.grade), d,
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


def _curseur(parent: tk.Misc, valeur: str) -> None:
    """Curseur d'attente (« watch ») sur la fenêtre pendant un export long."""
    opts: "dict[str, str]" = {"cursor": valeur}
    try:
        parent.configure(**opts)
        parent.update_idletasks()
    except tk.TclError:
        pass


def export_ods_arbre(parent: tk.Misc, arbre: Optional[Arbre],
                     chantier: Chantier) -> None:
    """Tableau PRBS de l'arbre courant en .ods (sans dépendance)."""
    if not arbre:
        return
    if arbre.rayon_tronc_cm <= 0:
        messagebox.showerror(
            "Export impossible",
            "Renseignez un rayon de tronc avant l'export.")
        return
    default = (f"tableau_arbre_{nom_fichier_sur(arbre.numero_arbre, 'X')}.ods")
    p = filedialog.asksaveasfilename(
        defaultextension=".ods",
        initialfile=default,
        filetypes=[("Classeur OpenDocument", "*.ods")])
    if not p:
        return
    try:
        cabinet_name, _logo = _get_cabinet_info(parent)
        export_prbs_ods(arbre, chantier, p,
                        couleur_classe=COULEUR_CLASSE,
                        classer_prbs=classer_prbs,
                        cabinet_name=cabinet_name,
                        bareme_desc=description_seuils_mission(chantier))
        _notify_export(parent, p, _("Tableau ODS enregistré"))
    except Exception as e:
        log.exception("Échec export ODS")
        messagebox.showerror("Erreur", str(e))


# Tableaux PRBS de la mission : format → (extension, filtre de dialogue).
_FORMATS_TABLEAUX = {
    "xlsx": (".xlsx", "Classeur Excel"),
    "ods": (".ods", "Classeur OpenDocument"),
    "html": (".html", "Page HTML"),
}


def export_tableaux_mission(parent: tk.Misc, chantier: Chantier,
                            fmt: str) -> None:
    """Tableaux PRBS de TOUS les arbres de la mission dans UN fichier
    (`fmt` : "xlsx" | "ods" | "html"). XLSX/ODS : une feuille par arbre,
    précédée d'une feuille « Synthèse » ; HTML : une page, une section par
    arbre. Les arbres sans rayon renseigné sont ignorés (comme le PDF de
    mission)."""
    if fmt == "xlsx" and not HAS_OPENPYXL:
        messagebox.showerror(
            "Export XLSX indisponible",
            "Le module openpyxl n'est pas installé.\n\n"
            "Pour activer cet export, lancez dans un terminal :\n"
            "    pip install -r requirements.txt\n\n"
            "Les exports ODS et HTML restent disponibles sans dépendance.")
        return
    if not _check_completeness(parent, chantier):
        return
    arbres = [a for a in chantier.arbres if a.rayon_tronc_cm > 0]
    if not arbres:
        messagebox.showinfo(
            _("Rien à exporter"),
            "Aucun arbre avec un rayon renseigné dans cette mission.")
        return
    ext, filtre = _FORMATS_TABLEAUX[fmt]
    suggest = (f"tableaux_mission_{chantier.nom or 'sans_nom'}{ext}"
               .replace(" ", "_"))
    p = filedialog.asksaveasfilename(
        defaultextension=ext, initialfile=suggest,
        filetypes=[(filtre, f"*{ext}")])
    if not p:
        return
    cabinet_name, _logo = _get_cabinet_info(parent)
    bareme = description_seuils_mission(chantier)
    # Un classeur de plusieurs centaines de feuilles prend quelques
    # secondes : curseur d'attente plutôt qu'une fenêtre qui semble figée.
    _curseur(parent, "watch")
    try:
        if fmt == "html":
            export_prbs_mission_html(
                arbres, chantier, p, COULEUR_CLASSE, classer_prbs,
                cabinet_name=cabinet_name, bareme_desc=bareme)
        else:
            synth = mission_synthesis_rows(chantier, trier_par_urgence=True)
            ecrire = (export_prbs_mission_xlsx if fmt == "xlsx"
                      else export_prbs_mission_ods)
            ecrire(arbres, chantier, p, COULEUR_CLASSE, classer_prbs,
                   cabinet_name=cabinet_name, bareme_desc=bareme,
                   synthese=synth)
        _notify_export(parent, p,
                       _("Tableaux PRBS enregistrés ({n} arbre(s))")
                       .format(n=len(arbres)))
    except Exception as e:
        log.exception("Échec export tableaux mission %s", fmt)
        messagebox.showerror("Erreur", str(e))
    finally:
        _curseur(parent, "")


def export_synthesis_ods_mission(parent: tk.Misc,
                                 chantier: Chantier) -> None:
    """Synthèse mission en .ods."""
    if not _check_completeness(parent, chantier):
        return
    p = filedialog.asksaveasfilename(
        defaultextension=".ods",
        initialfile=_suggest_synthesis_name(chantier, "ods"),
        filetypes=[("Classeur OpenDocument", "*.ods")])
    if not p:
        return
    try:
        export_synthesis_ods(
            mission_synthesis_rows(chantier, trier_par_urgence=True),
            chantier, p, couleur_classe=COULEUR_CLASSE,
            bareme_desc=description_seuils_mission(chantier))
        _notify_export(parent, p, _("Synthèse mission ODS enregistrée"))
    except Exception as e:
        log.exception("Échec export synthèse ODS")
        messagebox.showerror("Erreur", str(e))
