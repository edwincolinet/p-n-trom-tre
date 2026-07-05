#!/usr/bin/env python3
"""
Pilote de l'app Pénétromètre (Pénétromètre) — lance la VRAIE App Tk et déclenche
un export réel, sans interaction manuelle.

Le seul « faux » élément est la boîte « Enregistrer sous »
(`filedialog.asksaveasfilename`), neutralisée pour renvoyer un chemin fixe ;
tout le reste est le code de production : `App.__init__`, `_open_path`
(chargement + migration + montage UI), puis l'action du bouton / raccourci
(`action_export_pdf_arbre` ou `action_export_pdf_mission`) →
`app_exports.export_pdf_*` → `_need_pil`/`_need_fpdf` → `_new_pdf` →
`render_fiche_arbre` → `pdf.output` → `_notify_export`.

Requiert un DISPLAY (l'app est Tkinter). Sur cette machine : `DISPLAY=:0`
(bureau réel — une fenêtre apparaît brièvement). Sur une machine sans écran,
préfixer par `xvfb-run -a`.

Usage :
    DISPLAY=:0 PYTHONPATH=<repo> python3 driver.py \
        [--mission exemples/mission_demo.json] [--arbre 3] \
        [--out /tmp/fiche.pdf] [--no-sondages] [--mission-pdf] [--no-render]

Sortie : lignes `KEY=VALUE` + un récap ; code de sortie ≠ 0 si l'export échoue.
Le PDF est écrit dans --out et (si poppler dispo) rendu en `<out>.png`.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description="Pilote d'export PDF Pénétromètre")
    ap.add_argument("--mission", default="exemples/mission_demo.json",
                    help="Fichier mission .json à charger")
    ap.add_argument("--arbre", default=None,
                    help="N° d'arbre à exporter (fiche arbre). "
                         "Défaut : le 1er de la mission.")
    ap.add_argument("--out", default="/tmp/penetrometre_fiche.pdf",
                    help="Chemin du PDF produit")
    ap.add_argument("--no-sondages", action="store_true",
                    help="Décoche « Afficher les sondages » (pastilles du dessin)")
    ap.add_argument("--mission-pdf", action="store_true",
                    help="Exporte la fiche mission complète (tous les arbres) "
                         "au lieu d'une seule fiche arbre")
    ap.add_argument("--no-render", action="store_true",
                    help="Ne pas rendre le PDF en PNG (pdftoppm)")
    args = ap.parse_args()

    if not os.environ.get("DISPLAY"):
        print("ERREUR : aucun DISPLAY. Lance avec `DISPLAY=:0 …` ou "
              "`xvfb-run -a python3 driver.py …`.", file=sys.stderr)
        return 2

    out_pdf = os.path.abspath(args.out)
    if os.path.exists(out_pdf):
        os.remove(out_pdf)

    # Imports du projet (PYTHONPATH doit pointer sur le repo).
    import app_exports
    import penetrometre

    # Neutralise UNIQUEMENT la boîte « Enregistrer sous ».
    app_exports.filedialog.asksaveasfilename = lambda **k: out_pdf
    # Capture les messages d'erreur/info au lieu d'ouvrir un modal bloquant.
    captured: dict = {}
    app_exports.messagebox.showerror = \
        lambda *a, **k: captured.setdefault("error", a)
    app_exports.messagebox.showinfo = \
        lambda *a, **k: captured.setdefault("info", a)
    # L'export mission demande une confirmation modale si la mission a des
    # points incomplets (`_check_completeness` → askyesno) : on répond « oui »
    # pour ne pas bloquer sur un dialogue.
    app_exports.messagebox.askyesno = lambda *a, **k: True

    app = penetrometre.App()
    try:
        app.update_idletasks()
        # Chargement réel de la mission (comme Fichier → Ouvrir).
        app._open_path(args.mission)
        app.update_idletasks()
        print(f"MISSION={app.chantier.nom}")
        print(f"ARBRES={len(app.chantier.arbres)}")

        if args.mission_pdf:
            print("MODE=mission")
            app.action_export_pdf_mission()
        else:
            if args.arbre is not None:
                idx = next((i for i, a in enumerate(app.chantier.arbres)
                            if a.numero_arbre == args.arbre), None)
                if idx is None:
                    print(f"ERREUR : arbre n°{args.arbre} introuvable.",
                          file=sys.stderr)
                    return 3
                app.current_idx = idx
            arbre = app._current_arbre()
            print(f"MODE=arbre")
            print(f"ARBRE={arbre.display_name if arbre else '(aucun)'}")
            app.action_export_pdf_arbre()
        app.update()
    finally:
        app.destroy()

    if "error" in captured:
        print(f"SHOWERROR={captured['error']}", file=sys.stderr)
        return 4

    ok = os.path.exists(out_pdf) and os.path.getsize(out_pdf) > 0
    data = open(out_pdf, "rb").read() if ok else b""
    is_pdf = data[:4] == b"%PDF"
    print(f"PDF_OK={ok}")
    print(f"PDF_BYTES={len(data)}")
    print(f"PDF_MAGIC_OK={is_pdf}")
    if not (ok and is_pdf):
        print("ERREUR : PDF absent ou invalide.", file=sys.stderr)
        return 5

    # Texte sélectionnable (le cœur du chantier vectoriel).
    if shutil.which("pdftotext"):
        txt = subprocess.run(["pdftotext", out_pdf, "-"],
                             capture_output=True, text=True)
        n_lines = sum(1 for ln in txt.stdout.splitlines() if ln.strip())
        print(f"PDF_TEXT_LINES={n_lines}")
        if n_lines == 0:
            print("ATTENTION : aucun texte extrait (rendu non vectoriel ?).",
                  file=sys.stderr)

    # Rendu PNG de la 1re page (artefact à inspecter visuellement).
    if not args.no_render and shutil.which("pdftoppm"):
        png_base = out_pdf.rsplit(".", 1)[0] + "_p"
        subprocess.run(["pdftoppm", "-png", "-r", "110", "-f", "1", "-l", "1",
                        out_pdf, png_base], check=False)
        png = png_base + "-1.png"
        if os.path.exists(png):
            print(f"PDF_PNG={png}")

    print(f"OUT_PDF={out_pdf}")
    print("RESULT=OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
