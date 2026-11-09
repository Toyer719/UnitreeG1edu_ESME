"""Le rapport de séance (vague 6, section 13.3 du plan) : g1-seance rapport DOSSIER.

  faire_rapport(dossier) → le dict de rapport.json, après avoir écrit dans le dossier de la séance :
      rapport.json   le résumé, lisible par une machine (atelier.seance.analyse.analyser)
      trajets.png    la carte de l'étage (copie du lieu dans lieu/) et le trajet du robot, chaque trajet coloré
                     selon son résultat et numéroté comme dans le tableau, les anomalies cerclées
      rapport.md     le rapport en Markdown (l'image à côté)
      rapport.html   le même, avec l'image dedans (un seul fichier : il s'ouvre aussi depuis le .zip)
  Le manifeste reçoit rapport {etat: en_cours, puis pret ou echec, fichiers, message, date}.
  Le bag est réindexé d'abord s'il n'a pas de metadata.yaml (séance d'un Atelier qui a planté).

Textes en français simple ; aucun nom de sujet ROS dans les titres (le détail technique est en petit, pour
l'analyse). Toutes les données insérées dans le HTML passent par html.escape.
"""
import base64
import html
import io
import json
import math
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from atelier.lieu.seance import FICHIERS_SEANCE
from . import analyse as A
from .lecture import charger, infos_bag, reindexer
from .manifeste import chemin, heure_iso, lire_heure, lire_manifeste, modifier_manifeste

FICHIERS_RAPPORT = ("rapport.json", "rapport.md", "rapport.html", "trajets.png")
JOURNAL_LU_MAX = 2 * 1000 * 1000        # octets lus à la fin de chaque journal pour y chercher les erreurs
CHRONOLOGIE_AFFICHEE = 600              # lignes de la chronologie dans le HTML et le Markdown
MODES = {"reel": "Robot réel", "repetition": "Répétition sans robot (faux G1)"}
JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre")
# Couleurs du graphique : la palette d'état (résultat d'un trajet) ; les salles et le fond restent neutres
COULEURS_RESULTAT = {"arrive": "#0ca30c", "interrompu": "#ec835a", "echec": "#d03b3b", "abandonne": "#fab219",
                     "remplace": "#52514e", "en_cours": "#52514e"}
LIBELLES_RESULTAT = {"arrive": "Arrivé", "interrompu": "Interrompu", "echec": "Échec",
                     "abandonne": "Abandonné (visiteur perdu)", "remplace": "Remplacé par une autre demande",
                     "en_cours": "Pas fini à la fin de la séance"}
# corrections de la vague 6 (revue de l'interface, défaut 12) : « 6 trajets : 5 arrivé » ; les pluriels
LIBELLES_RESULTAT_PLURIEL = {"arrive": "arrivés", "interrompu": "interrompus", "echec": "échecs",
                             "abandonne": "abandonnés (visiteur perdu)", "remplace": "remplacés par une autre demande",
                             "en_cours": "pas finis à la fin de la séance"}
ICONES_GRAVITE = {"probleme": "✖", "attention": "⚠", "info": "ℹ"}
NOMS_GRAVITE = {"probleme": "Problème", "attention": "Attention", "info": "Pour info"}
# Les états du diagnostic (13.2) écrits comme dans « Vérifier le robot » (assemblage de la vague 6)
ETATS_DIAGNOSTIC = {"ok": "OK", "attention": "Attention", "probleme": "Problème", "inconnu": "Inconnu"}


def etat_diagnostic(etat):
    """« Problème » pour probleme… ; un état inconnu reste tel quel."""
    return ETATS_DIAGNOSTIC.get(etat, etat if etat is not None else "?")


# ---------------------------------------------------------------- mise en forme en français

def nombre(x, decimales=1):
    """12.5 → « 12,5 » ; 1234 → « 1 234 » (espace fine insécable)."""
    if x is None:
        return "—"
    if isinstance(x, int) or decimales == 0:
        return f"{int(round(x)):,}".replace(",", " ")
    return f"{x:,.{decimales}f}".replace(",", " ").replace(".", ",")


def duree(s):
    """3725 → « 1 h 02 min » ; 192 → « 3 min 12 s » ; 45.2 → « 45 s »."""
    if s is None:
        return "—"
    s = int(round(float(s)))
    if s >= 3600:
        return f"{s // 3600} h {s % 3600 // 60:02d} min"
    if s >= 60:
        return f"{s // 60} min {s % 60:02d} s"
    return f"{s} s"


def heure_courte(iso):
    """« 2026-11-12T14:05:12+01:00 » → « 14:05:12 »."""
    t = lire_heure(iso)
    return datetime.fromtimestamp(t).strftime("%H:%M:%S") if t is not None else "—"


def date_longue(iso):
    """« jeudi 12 novembre 2026, 14 h 03 »."""
    t = lire_heure(iso)
    if t is None:
        return "date inconnue"
    d = datetime.fromtimestamp(t)
    return f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]} {d.year}, {d.hour} h {d.minute:02d}"


def taille(octets):
    if not octets:
        return "0 Mo"
    if octets < 1000 * 1000:
        return f"{nombre(octets / 1000, 0)} ko"
    return f"{nombre(octets / 1e6, 1)} Mo"


def pluriel(n, mot, mots=None):
    return f"{nombre(n, 0)} {mot if n in (0, 1) else (mots or mot + 's')}"


# ---------------------------------------------------------------- lecture du dossier

def charger_lieu(dossier_lieu, etage=None):
    """(analyse.Lieu, carte) d'après la copie du lieu de la séance ; carte : (InfoCarte, image) ou None."""
    from atelier import lieu as L
    dossier_lieu = Path(dossier_lieu)
    lieu = A.Lieu(etage=etage)
    carte = None
    if not dossier_lieu.is_dir():
        return lieu, carte
    try:
        fiche = L.charger_fiche(dossier_lieu)
        lieu.nom = fiche.nom
        if etage is not None and fiche.etage(etage) is not None:
            lieu.nom_etage = fiche.etage(etage).nom
    except Exception:       # noqa: BLE001 : la copie peut être incomplète
        fiche = None
    try:
        for s in L.charger_salles(dossier_lieu):
            lieu.salles[s.id] = {"nom": s.nom, "x": s.pose.x, "y": s.pose.y, "etage": s.etage,
                                 "theta": s.pose.theta}
    except Exception:       # noqa: BLE001
        pass
    try:
        for ident, n in L.charger_itineraires(dossier_lieu).noeuds.items():
            lieu.noeuds[ident] = {"x": n.x, "y": n.y, "etage": n.etage}
    except Exception:       # noqa: BLE001
        pass
    try:
        from atelier.lieu.principal import point_principal
        p = point_principal(dossier_lieu)
        lieu.principal = p.id if p else None
        if lieu.etage is None and p is not None:
            lieu.etage = p.etage
    except Exception:       # noqa: BLE001
        pass
    if lieu.nom_etage is None and lieu.etage and fiche is not None and fiche.etage(lieu.etage) is not None:
        lieu.nom_etage = fiche.etage(lieu.etage).nom
    if lieu.etage:
        try:
            carte = L.charger_carte(L.chemin_carte(dossier_lieu, lieu.etage))
        except Exception:       # noqa: BLE001 : pas de carte (lieu sans scan) : le trajet seul
            carte = None
    return lieu, carte


def lire_actions(dossier):
    """Les lignes de actions.jsonl (les lignes illisibles sont sautées)."""
    actions = []
    try:
        with open(chemin(dossier, "actions"), encoding="utf-8") as f:
            for ligne in f:
                try:
                    a = json.loads(ligne)
                except ValueError:
                    continue
                if isinstance(a, dict):
                    actions.append(a)
    except OSError:
        pass
    return actions


def lire_journaux(dossier):
    """[(source, ligne)] des lignes d'erreur des journaux de la séance (journaux/*.log, journaux/jetson/*.log)."""
    lignes = []
    for fichier in sorted(chemin(dossier, "journaux").rglob("*.log")):
        try:
            with open(fichier, "rb") as f:
                f.seek(max(0, os.path.getsize(fichier) - JOURNAL_LU_MAX))
                texte = f.read().decode("utf-8", "replace")
        except OSError:
            continue
        lignes += A.lignes_erreur(texte, str(fichier.relative_to(dossier)))
    return lignes


def lire_diagnostic(dossier):
    try:
        d = json.loads(chemin(dossier, "diagnostic_debut").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    a_regler = [{"titre": v.get("titre") or v.get("id"), "etat": v.get("etat"), "detail": v.get("detail"),
                 "conseil": v.get("conseil")} for v in d.get("verifications") or []
                if isinstance(v, dict) and v.get("etat") not in ("ok", None)]
    return {"etat": d.get("etat"), "message": d.get("message"), "resume": d.get("resume"), "a_regler": a_regler,
            "date": d.get("date")}


def fichiers_seance(dossier):
    """La liste des fichiers de la séance (chemins relatifs), sans le verrou."""
    dossier = Path(dossier)
    return sorted(str(p.relative_to(dossier)) for p in dossier.rglob("*")
                  if p.is_file() and not p.name.startswith("."))


# ---------------------------------------------------------------- graphique des trajets (PNG)

def dessiner_trajets(rapport, donnees, carte, lieu, sortie):
    """trajets.png : la carte de l'étage en fond (gris clair, murs en gris), le chemin complet du robot en gris,
    chaque trajet par-dessus dans la couleur de son résultat, numéroté à son départ ; ✕ à la fin d'un trajet
    interrompu ou en échec ; les anomalies cerclées. Renvoie True si l'image est écrite."""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    from matplotlib.lines import Line2D
    import numpy as np

    source, pts = A.positions(donnees)
    fig = Figure(figsize=(10.0, 6.6), dpi=110)
    fig.patch.set_facecolor("#fcfcfb")
    ax = fig.add_subplot(1, 1, 1)
    ax.set_facecolor("#fcfcfb")
    bornes = None
    if carte is not None:
        from atelier.lieu import bornes_carte
        info, image = carte
        xmin, ymin, xmax, ymax = bornes_carte(info)
        fond = np.full(image.shape + (3,), 0xEC, dtype=np.uint8)                 # inconnu : gris très clair
        fond[image >= 250] = (0xFC, 0xFC, 0xFB)                                  # libre : la surface
        fond[image <= 50] = (0x9A, 0x98, 0x90)                                   # occupé : gris (murs)
        ax.imshow(fond, extent=(xmin, xmax, ymin, ymax), origin="upper", interpolation="nearest", zorder=0)
        bornes = [xmin, xmax, ymin, ymax]
    # salles et point principal (encre neutre : ce ne sont pas des séries)
    for ident, s in lieu.salles.items():
        if lieu.etage and s.get("etage") not in (None, lieu.etage):
            continue
        principal = ident == lieu.principal
        ax.plot([s["x"]], [s["y"]], marker="*" if principal else "o", markersize=13 if principal else 6,
                color="#52514e", markeredgecolor="#fcfcfb", markeredgewidth=1.0, zorder=4, linestyle="none")
        ax.annotate(s.get("nom") or ident, (s["x"], s["y"]), xytext=(6, 5), textcoords="offset points",
                    fontsize=8, color="#0b0b0b", zorder=6)
    if pts:
        xs, ys = [p[1] for p in pts], [p[2] for p in pts]
        ax.plot(xs, ys, color="#c3c2b7", linewidth=1.5, zorder=2, solid_capstyle="round")
    trajets = rapport.get("trajets") or []
    # les trajets qui posent question par-dessus ceux qui sont arrivés (un chemin refait cacherait l'interruption)
    rang = {"arrive": 0, "remplace": 1, "en_cours": 1, "abandonne": 2, "interrompu": 3, "echec": 3}
    places = []

    def place_libre(x, y):
        """Une place pour un numéro, décalée vers le bas si un autre numéro est déjà là (même départ)."""
        while any(math.hypot(x - a, y - b) < 0.8 for a, b in places):
            y -= 0.9
        places.append((x, y))
        return x, y
    for tr in sorted(trajets, key=lambda t: rang.get(t.get("resultat"), 1)):
        debut, fin = lire_heure(tr.get("debut")), lire_heure(tr.get("fin"))
        morceau = [p for p in pts if debut is not None and fin is not None and debut - 0.5 <= p[0] <= fin + 0.5]
        couleur = COULEURS_RESULTAT.get(tr.get("resultat"), "#52514e")
        z = 3 + rang.get(tr.get("resultat"), 1) * 0.1
        if len(morceau) >= 2:
            ax.plot([p[1] for p in morceau], [p[2] for p in morceau], color=couleur, linewidth=2.4, zorder=z,
                    solid_capstyle="round", solid_joinstyle="round")
        arrivee = tr.get("position_fin") or (morceau[-1][1:3] if morceau else None)
        if arrivee and tr.get("resultat") in ("interrompu", "echec"):
            ax.plot([arrivee[0]], [arrivee[1]], marker="X", markersize=11, color=couleur,
                    markeredgecolor="#fcfcfb", markeredgewidth=1.2, zorder=7, linestyle="none")
            places.append(tuple(arrivee))          # le numéro du trajet suivant ne cache pas la croix
    for tr in trajets:
        debut = lire_heure(tr.get("debut"))
        couleur = COULEURS_RESULTAT.get(tr.get("resultat"), "#52514e")
        depart = tr.get("position_depart") or next(((p[1], p[2]) for p in pts if debut and p[0] >= debut), None)
        if depart:
            ax.annotate(str(tr["numero"]), place_libre(*depart), fontsize=7.5, color="#ffffff", ha="center",
                        va="center", zorder=8, fontweight="bold",
                        bbox={"boxstyle": "circle,pad=0.25", "facecolor": couleur, "edgecolor": "#fcfcfb",
                              "linewidth": 1.2})
    anomalies = [a for a in rapport.get("anomalies") or [] if a.get("position")]
    for a in anomalies:
        debut = lire_heure(a.get("t"))
        morceau = [p for p in pts if debut is not None and debut - 0.3 <= p[0] <= debut + (a.get("duree_s") or 0)
                   + 0.3]
        if len(morceau) >= 2:
            ax.plot([p[1] for p in morceau], [p[2] for p in morceau], color="#d03b3b", linewidth=2.4, zorder=9,
                    solid_capstyle="round")
            x, y = morceau[-1][1:3]             # là où le robot s'est retrouvé
        else:
            x, y = a["position"]
        ax.plot([x], [y], marker="o", markersize=18, markerfacecolor="#fcfcfb", markeredgecolor="#d03b3b",
                markeredgewidth=2.0, zorder=9.5, linestyle="none")
        ax.annotate("!", (x, y), fontsize=10, color="#d03b3b", ha="center", va="center", fontweight="bold",
                    zorder=10)
    # cadrage : la carte, ou le chemin avec une marge
    if bornes is None:
        if pts or lieu.salles:
            xs = [p[1] for p in pts] + [s["x"] for s in lieu.salles.values()]
            ys = [p[2] for p in pts] + [s["y"] for s in lieu.salles.values()]
            marge = 1.0
            bornes = [min(xs) - marge, max(xs) + marge, min(ys) - marge, max(ys) + marge]
        else:
            bornes = [-1, 1, -1, 1]
    ax.set_xlim(bornes[0], bornes[1])
    ax.set_ylim(bornes[2], bornes[3])
    ax.set_aspect("equal")
    ax.tick_params(colors="#898781", labelsize=8)
    from matplotlib.ticker import FuncFormatter
    ax.xaxis.set_major_formatter(FuncFormatter(nombre_axe))
    ax.yaxis.set_major_formatter(FuncFormatter(nombre_axe))
    for cote in ax.spines.values():
        cote.set_color("#c3c2b7")
    ax.set_xlabel("x (m)", fontsize=8, color="#52514e")
    ax.set_ylabel("y (m)", fontsize=8, color="#52514e")
    titre = "Trajets du robot"
    if lieu.nom:
        etage = f", {lieu.nom_etage}" if lieu.nom_etage else (f", étage {lieu.etage}" if lieu.etage else "")
        titre += f" — {lieu.nom}{etage}"
    ax.set_title(titre, fontsize=11, color="#0b0b0b", loc="left")
    if not pts:
        ax.text(0.5, 0.5, "Aucune position du robot enregistrée", transform=ax.transAxes, ha="center",
                va="center", fontsize=11, color="#52514e")
    # légende : seulement ce qui est dessiné
    vus = []
    for resultat in ("arrive", "interrompu", "echec", "abandonne", "remplace", "en_cours"):
        if any(t.get("resultat") == resultat for t in trajets):
            vus.append(Line2D([0], [0], color=COULEURS_RESULTAT[resultat], linewidth=2.4,
                              label=LIBELLES_RESULTAT[resultat]))
    if pts:
        vus.append(Line2D([0], [0], color="#c3c2b7", linewidth=1.5, label="Chemin hors des trajets"))
    if anomalies:
        vus.append(Line2D([0], [0], color="#d03b3b", linewidth=2.4, marker="o", markersize=9,
                          markerfacecolor="#fcfcfb", markeredgecolor="#d03b3b", markeredgewidth=2.0,
                          label="Mouvement sans demande"))
    if lieu.principal:
        vus.append(Line2D([0], [0], marker="*", markersize=11, color="#52514e", linestyle="none",
                          label="Point principal (accueil)"))
    if vus:
        legende = ax.legend(handles=vus, loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=8, frameon=False,
                            borderaxespad=0.0)
        for texte in legende.get_texts():
            texte.set_color("#0b0b0b")
    fig.tight_layout()
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    FigureCanvasAgg(fig)
    tampon = io.BytesIO()
    fig.savefig(tampon, format="png", facecolor=fig.get_facecolor())
    from atelier.lieu.fichiers import ecrire_atomique
    ecrire_atomique(sortie, tampon.getvalue())
    return True


# ---------------------------------------------------------------- les textes du rapport

def arrets_affiches(t):
    """Les arrêts d'un trajet à montrer : sans le dernier s'il n'est que la cause de l'interruption (déjà dite dans la
    colonne « Résultat »)."""
    arrets = list(t.get("arrets") or [])
    if arrets and t.get("cause") and arrets[-1].get("cause") == t["cause"]:
        arrets = arrets[:-1]
    return arrets


DOSSIERS_DECRITS = {"bag": "l'enregistrement ROS 2", "lieu": "la copie du lieu ouvert", "journaux": "les journaux"}


def fichiers_affiches(r):
    """La liste des fichiers, regroupée par dossier : « bag/ (2 fichiers : l'enregistrement ROS 2) »."""
    dossiers, seuls = {}, []
    for f in r.get("fichiers") or []:
        tete, _, reste = str(f).partition("/")
        if reste:
            dossiers.setdefault(tete, []).append(reste)
        else:
            seuls.append(f)
    lignes = list(seuls)
    for nom, contenu in sorted(dossiers.items()):
        quoi = DOSSIERS_DECRITS.get(nom)
        lignes.append(f"{nom}/ ({pluriel(len(contenu), 'fichier')}" + (f" : {quoi})" if quoi else ")"))
    return lignes


def etage_affiche(r):
    """« Rez-de-chaussée » (le nom de l'étage dans la fiche du lieu), sinon « étage rdc »."""
    return r.get("nom_etage") or f"étage {r.get('etage')}"


def nombre_axe(v, _position=None):
    """Graduation d'un axe en français : « 17,5 », « −2 » (virgule décimale)."""
    return f"{v:g}".replace("-", "−").replace(".", ",")


def phrase_trajets(r):
    s = r.get("resume") or {}
    n = s.get("trajets", 0)
    if not n:
        return "Aucun trajet du guide."
    morceaux = [f"{nombre(v, 0)} " + (LIBELLES_RESULTAT_PLURIEL.get(k, k) if v > 1 else
                                      LIBELLES_RESULTAT.get(k, k).lower())
                for k, v in sorted((s.get("par_resultat") or {}).items(), key=lambda x: -x[1])]
    return f"{pluriel(n, 'trajet')} : " + ", ".join(morceaux) + "."


def en_bref(r):
    """[(titre, valeur, détail)] des cases « En bref »."""
    s = r.get("resume") or {}
    b = r.get("batterie") or {}
    anomalies = s.get("anomalies") or {}
    a_regarder = anomalies.get("probleme", 0) + anomalies.get("attention", 0)
    batt = "—" if b.get("debut") is None else f"{b['debut']} → {b['fin']} %"
    return [("Durée", duree(r.get("duree_s")), MODES.get(r.get("mode"), r.get("mode") or "")),
            ("Trajets", nombre(s.get("trajets", 0), 0), phrase_trajets(r)),
            ("Distance", f"{nombre(s.get('distance_m', 0.0))} m",
             f"pendant les trajets ; {nombre(s.get('distance_totale_m', 0.0))} m en tout"),
            ("Arrêts d'urgence", nombre(s.get("arrets_urgence", 0), 0), "ARRÊT et verrous du pont"),
            ("Anomalies", nombre(a_regarder, 0), "à regarder" if a_regarder else "rien d'anormal"),
            ("Erreurs", nombre(s.get("erreurs", 0), 0), "refus de l'Atelier, erreurs des programmes"),
            ("Batterie", batt, "début → fin de la séance")]


def texte_markdown(r):
    """rapport.md : le rapport en Markdown (l'image trajets.png à côté)."""
    lignes = [f"# Rapport de séance du {date_longue(r.get('debut'))}", ""]
    lieu = r.get("nom_lieu") or r.get("lieu") or "sans lieu"
    lignes.append(f"Lieu « {lieu} »" + (f" ({etage_affiche(r)})" if r.get("etage") else "")
                  + f" · {MODES.get(r.get('mode'), r.get('mode'))} · durée {duree(r.get('duree_s'))}"
                  + f" · séance {r.get('seance')}" + ("" if r.get("etat") != "interrompue" else " · **interrompue**"))
    lignes += ["", "## En bref", "", "| | | |", "|---|---|---|"]
    lignes += [f"| {t} | **{v}** | {d} |" for t, v, d in en_bref(r)]
    lignes += ["", "## À regarder en premier", ""]
    anomalies = r.get("anomalies") or []
    if not anomalies:
        lignes.append("Rien d'anormal détecté.")
    for a in anomalies:
        lignes.append(f"- {ICONES_GRAVITE.get(a.get('gravite'), '•')} **{NOMS_GRAVITE.get(a.get('gravite'), '')}**"
                      f" {heure_courte(a.get('t')) if a.get('t') else ''} : {a.get('texte')}"
                      + (f" _({a['technique']})_" if a.get("technique") else ""))
    lignes += ["", "## Les trajets", "", "![Trajets du robot sur la carte](trajets.png)", ""]
    trajets = r.get("trajets") or []
    if trajets:
        lignes += ["| N° | Départ → but | Résultat | Début | Durée | Distance | Arrêts |",
                   "|---|---|---|---|---|---|---|"]
        for t in trajets:
            arrets = " ; ".join(f"{heure_courte(x['t'])} {x['cause']}" for x in arrets_affiches(t)) or "—"
            resultat = LIBELLES_RESULTAT.get(t["resultat"], t["resultat"]) + (f" : {t['cause']}" if t.get("cause")
                                                                              else "")
            lignes.append(f"| {t['numero']} | {t['depart']} → {t['nom']} | {resultat} | {heure_courte(t['debut'])} "
                          f"| {duree(t['duree_s'])} | {nombre(t['distance_m'])} m | {arrets} |")
    else:
        lignes.append("Aucun trajet du guide pendant la séance.")
    lignes += ["", "## Le robot", ""]
    etats = r.get("etats_pont") or {}
    if etats:
        lignes += ["Temps passé dans chaque état du pont vers la marche :", "", "| État | Temps |", "|---|---|"]
        lignes += [f"| {A.ETATS_PONT.get(k, k)} | {duree(v)} |" for k, v in etats.items()]
    else:
        lignes.append("Le pont vers la marche n'a rien publié (navigation pas lancée ?).")
    modes = r.get("modes") or []
    vus = ", ".join(f"{m['nom']} ({m['fsm']}, {duree(m['secondes'])})" for m in modes) or "aucun"
    lignes += ["", f"Modes du robot vus : {vus}."]
    rp = r.get("reperage") or {}
    lignes += ["", "Repérage : " + (f"précision moyenne {nombre((rp.get('precision_moyenne_m') or 0) * 100, 1)} cm, "
                                    f"pire {nombre((rp.get('precision_max_m') or 0) * 100, 1)} cm"
                                    if rp.get("precision_moyenne_m") is not None else "pas de précision connue")
               + f" ; {pluriel(rp.get('reperages', 0), 'repérage réussi', 'repérages réussis')}, "
               + f"{pluriel(rp.get('pertes', 0), 'perte', 'pertes')}, {pluriel(rp.get('sauts', 0), 'saut')}."]
    lignes += ["", "## Erreurs", ""]
    erreurs = r.get("erreurs") or []
    if not erreurs:
        lignes.append("Aucune erreur.")
    else:
        lignes += ["| Heure | Où | Ce qui s'est passé | Fois |", "|---|---|---|---|"]
        lignes += [f"| {heure_courte(e.get('t')) if e.get('t') else '—'} | {e.get('source')} | "
                   f"{str(e.get('texte')).replace('|', '/')} | {e.get('nombre', 1)} |" for e in erreurs]
        techniques = [e for e in erreurs if e.get("technique")]
        if techniques:          # le message d'origine, replié (anglais, noms des programmes)
            lignes += ["", "<details><summary>Détail technique</summary>", ""]
            lignes += [f"- {heure_courte(e.get('t')) if e.get('t') else '—'} : "
                       f"{str(e['technique']).replace('<', '‹').replace('>', '›')}" for e in techniques]
            lignes += ["", "</details>"]
    diag = r.get("diagnostic")
    lignes += ["", "## Diagnostic du début", ""]
    if not diag:
        lignes.append("Pas de diagnostic au début de la séance.")
    else:
        lignes.append(f"État : **{etat_diagnostic(diag.get('etat'))}**. {diag.get('message') or ''}".strip())
        lignes += [f"- {v['titre']} ({etat_diagnostic(v['etat'])}) : {v.get('detail') or ''} "
                   f"{v.get('conseil') or ''}".rstrip() for v in diag.get("a_regler") or []]
    lignes += ["", "## Chronologie", "", "| Heure | Depuis le début | Ce qui s'est passé |", "|---|---|---|"]
    chrono = r.get("chronologie") or []
    for c in chrono[:CHRONOLOGIE_AFFICHEE]:
        lignes.append(f"| {heure_courte(c['t'])} | {duree(c['depuis_s'])} | {str(c['texte']).replace('|', '/')} |")
    if len(chrono) > CHRONOLOGIE_AFFICHEE:
        lignes.append(f"| … | | {nombre(len(chrono) - CHRONOLOGIE_AFFICHEE, 0)} lignes de plus dans rapport.json |")
    lignes += ["", "## Les fichiers de la séance", ""] + [f"- {f}" for f in fichiers_affiches(r)]
    lignes += ["", f"Pour l'analyse : `g1-seance exporter {r.get('seance')}` fait un .zip de tout le dossier.", ""]
    return "\n".join(lignes)


STYLE = """
:root { color-scheme: light; --fond: #f9f9f7; --surface: #fcfcfb; --encre: #0b0b0b; --encre-2: #52514e;
  --encre-3: #898781; --trait: #e1e0d9; --bord: #c3c2b7; --bon: #0ca30c; --attention: #fab219;
  --serieux: #ec835a; --critique: #d03b3b; --serie: #2a78d6; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--fond); color: var(--encre);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", sans-serif; }
main { max-width: 1100px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 1.6rem; margin: 0 0 4px; }
h2 { font-size: 1.2rem; margin: 32px 0 10px; padding-bottom: 4px; border-bottom: 1px solid var(--trait); }
.sous-titre { color: var(--encre-2); margin: 0 0 18px; }
.cases { display: grid; grid-template-columns: repeat(auto-fit, minmax(138px, 1fr)); gap: 10px; }
.case { background: var(--surface); border: 1px solid var(--trait); border-radius: 12px; padding: 10px 12px; }
.case-titre { color: var(--encre-2); font-size: 0.85rem; }
.case-valeur { font-size: 1.25rem; font-weight: 600; margin: 2px 0; white-space: nowrap; }
.case-detail { color: var(--encre-2); font-size: 0.8rem; }
.anomalies { list-style: none; padding: 0; margin: 0; display: grid; gap: 8px; }
.anomalie { background: var(--surface); border: 1px solid var(--trait); border-left: 6px solid var(--encre-3);
  border-radius: 10px; padding: 8px 12px; }
.anomalie[data-gravite=probleme] { border-left-color: var(--critique); }
.anomalie[data-gravite=attention] { border-left-color: var(--attention); }
.anomalie-tete { font-weight: 600; }
.technique { color: var(--encre-3); font-size: 0.8rem; }
details.technique { margin-top: 2px; overflow-wrap: anywhere; }
details.technique summary { cursor: pointer; }
.rien { color: var(--encre-2); }
figure { margin: 0 0 12px; }
figure img { width: 100%; height: auto; border: 1px solid var(--trait); border-radius: 12px;
  background: var(--surface); }
table { width: 100%; border-collapse: collapse; background: var(--surface); border: 1px solid var(--trait);
  border-radius: 10px; overflow: hidden; font-size: 0.9rem; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--trait); vertical-align: top; }
th { color: var(--encre-2); font-weight: 600; background: #f3f2ee; }
td.nombre, th.nombre { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
td.heure { font-variant-numeric: tabular-nums; white-space: nowrap; color: var(--encre-2); }
.pastille { display: inline-block; min-width: 1.6em; padding: 0 6px; border-radius: 999px; color: #fff;
  font-weight: 700; text-align: center; font-size: 0.8rem; }
.resultat::before { content: ""; display: inline-block; width: 10px; height: 10px; border-radius: 50%;
  margin-right: 6px; background: var(--encre-3); vertical-align: baseline; }
.resultat[data-resultat=arrive]::before { background: var(--bon); }
.resultat[data-resultat=interrompu]::before { background: var(--serieux); }
.resultat[data-resultat=echec]::before { background: var(--critique); }
.resultat[data-resultat=abandonne]::before { background: var(--attention); }
.barre { height: 8px; border-radius: 0 4px 4px 0; background: var(--serie); min-width: 2px; }
tr[data-gravite=probleme] td { background: #fbeceb; }
tr[data-gravite=attention] td { background: #fdf6e7; }
.deux { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
.note { color: var(--encre-2); font-size: 0.9rem; }
code { background: #f0efec; padding: 1px 5px; border-radius: 4px; }
@media print { body { background: #fff; } .case, table, .anomalie { break-inside: avoid; } }
"""


def _e(x):
    return html.escape("" if x is None else str(x))


def texte_html(r, png=None):
    """rapport.html : le rapport complet, un seul fichier (l'image trajets.png dedans, en base64)."""
    h = []
    ajouter = h.append
    ajouter("<!doctype html><html lang=\"fr\"><head><meta charset=\"utf-8\">")
    ajouter("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">")
    ajouter(f"<title>Rapport de séance {_e(r.get('seance'))}</title><style>{STYLE}</style></head><body><main>")
    ajouter(f"<h1>Rapport de séance du {_e(date_longue(r.get('debut')))}</h1>")
    lieu = r.get("nom_lieu") or r.get("lieu") or "sans lieu"
    sous = (f"Lieu « {lieu} »" + (f" ({etage_affiche(r)})" if r.get("etage") else "")
            + f" · {MODES.get(r.get('mode'), r.get('mode'))} · durée {duree(r.get('duree_s'))}"
            + f" · séance {r.get('seance')}")
    atel = r.get("atelier") or {}
    if atel.get("version"):
        sous += f" · Atelier {atel['version']}" + (f" ({atel['commit']})" if atel.get("commit") else "")
    if r.get("etat") == "interrompue":
        sous += " · séance interrompue"
    ajouter(f"<p class=\"sous-titre\" data-role=\"sous-titre\">{_e(sous)}</p>")
    ajouter("<h2>En bref</h2><div class=\"cases\" data-role=\"en-bref\">")
    for titre, valeur, detail in en_bref(r):
        ajouter(f"<div class=\"case\"><div class=\"case-titre\">{_e(titre)}</div>"
                f"<div class=\"case-valeur\">{_e(valeur)}</div><div class=\"case-detail\">{_e(detail)}</div></div>")
    ajouter("</div>")
    ajouter("<h2>À regarder en premier</h2>")
    anomalies = r.get("anomalies") or []
    if not anomalies:
        ajouter("<p class=\"rien\">Rien d'anormal détecté.</p>")
    else:
        ajouter("<ul class=\"anomalies\" data-role=\"anomalies\">")
        for a in anomalies:
            quand = heure_courte(a.get("t")) if a.get("t") else ""
            ajouter(f"<li class=\"anomalie\" data-gravite=\"{_e(a.get('gravite'))}\" "
                    f"data-genre=\"{_e(a.get('genre'))}\">"
                    f"<div class=\"anomalie-tete\">{_e(ICONES_GRAVITE.get(a.get('gravite'), '•'))} "
                    f"{_e(NOMS_GRAVITE.get(a.get('gravite'), ''))} {_e(quand)}</div><div>{_e(a.get('texte'))}</div>"
                    + (f"<div class=\"technique\">{_e(a['technique'])}</div>" if a.get("technique") else "")
                    + "</li>")
        ajouter("</ul>")
    ajouter("<h2>Les trajets</h2>")
    if png:
        ajouter("<figure><img data-role=\"trajets\" alt=\"Carte de l'étage avec le trajet du robot ; chaque trajet "
                "est numéroté comme dans le tableau et coloré selon son résultat\" src=\"data:image/png;base64,"
                + base64.b64encode(png).decode("ascii") + "\"></figure>")
    trajets = r.get("trajets") or []
    if not trajets:
        ajouter("<p class=\"rien\">Aucun trajet du guide pendant la séance.</p>")
    else:
        ajouter("<table data-role=\"tableau-trajets\"><thead><tr><th>N°</th><th>Départ → but</th><th>Résultat</th>"
                "<th>Début</th><th class=\"nombre\">Durée</th><th class=\"nombre\">Distance</th><th>Arrêts</th>"
                "</tr></thead><tbody>")
        for t in trajets:
            couleur = COULEURS_RESULTAT.get(t["resultat"], "#52514e")
            arrets = "<br>".join(f"{_e(heure_courte(x['t']))} · {_e(x['cause'])}" for x in arrets_affiches(t))
            cause = f"<br><span class=\"note\">{_e(t['cause'])}</span>" if t.get("cause") else ""
            ajouter(f"<tr data-resultat=\"{_e(t['resultat'])}\"><td><span class=\"pastille\" "
                    f"style=\"background:{couleur}\">{_e(t['numero'])}</span></td>"
                    f"<td>{_e(t['depart'])} → <strong>{_e(t['nom'])}</strong>"
                    + (" <span class=\"note\">(avec un visiteur)</span>" if t.get("accompagner") else "")
                    + ("" if t.get("mission") != "retour" else " <span class=\"note\">(retour)</span>")
                    + f"</td><td><span class=\"resultat\" data-resultat=\"{_e(t['resultat'])}\">"
                    f"{_e(LIBELLES_RESULTAT.get(t['resultat'], t['resultat']))}</span>{cause}</td>"
                    f"<td class=\"heure\">{_e(heure_courte(t['debut']))}</td>"
                    f"<td class=\"nombre\">{_e(duree(t['duree_s']))}</td>"
                    f"<td class=\"nombre\">{_e(nombre(t['distance_m']))} m</td><td>{arrets or '—'}</td></tr>")
        ajouter("</tbody></table>")
    ajouter("<h2>Le robot</h2><div class=\"deux\"><div>")
    etats = r.get("etats_pont") or {}
    if etats:
        total = max(1e-6, sum(etats.values()))
        ajouter("<table data-role=\"etats-pont\"><thead><tr><th>Pont vers la marche</th><th class=\"nombre\">Temps"
                "</th><th style=\"width:35%\">Part</th></tr></thead><tbody>")
        for k, v in etats.items():
            ajouter(f"<tr><td>{_e(A.ETATS_PONT.get(k, k))}</td><td class=\"nombre\">{_e(duree(v))}</td>"
                    f"<td><div class=\"barre\" style=\"width:{max(1.0, 100.0 * v / total):.1f}%\" "
                    f"title=\"{_e(nombre(100.0 * v / total, 0))} %\"></div></td></tr>")
        ajouter("</tbody></table>")
    else:
        ajouter("<p class=\"rien\">Le pont vers la marche n'a rien publié (navigation pas lancée ?).</p>")
    ajouter("</div><div>")
    b = r.get("batterie") or {}
    rp = r.get("reperage") or {}
    modes = r.get("modes") or []
    ajouter("<table><tbody>")
    batterie = "—" if b.get("debut") is None else f"{b['debut']} % au début, {b['fin']} % à la fin"
    ajouter(f"<tr><th>Batterie</th><td>{_e(batterie)}</td></tr>")
    vus = ", ".join(f"{m['nom']} ({m['fsm']}, {duree(m['secondes'])})" for m in modes) or "aucun vu"
    ajouter(f"<tr><th>Modes du robot</th><td>{_e(vus)}</td></tr>")
    prec = ("pas de précision connue" if rp.get("precision_moyenne_m") is None else
            f"moyenne {nombre(rp['precision_moyenne_m'] * 100, 1)} cm, "
            f"pire {nombre(rp['precision_max_m'] * 100, 1)} cm")
    reussis = pluriel(rp.get("reperages", 0), "repérage réussi", "repérages réussis")
    ajouter(f"<tr><th>Repérage</th><td>{_e(prec)} ; {_e(reussis)}, "
            f"{_e(pluriel(rp.get('pertes', 0), 'perte'))}, {_e(pluriel(rp.get('sauts', 0), 'saut'))}</td></tr>")
    enr = r.get("enregistrement") or {}
    enr_texte = (f"{taille(enr.get('octets'))}, {pluriel(len(enr.get('sujets') or {}), 'sujet')}"
                 + ("" if enr.get("metadata") in (True, None) else ", sans index (réindexé à la lecture)"))
    if enr.get("etat") in ("coupe", "erreur", "absent"):
        enr_texte += " · " + (enr.get("message") or enr.get("etat"))
    ajouter(f"<tr><th>Enregistrement</th><td>{_e(enr_texte)}</td></tr>")
    ajouter("</tbody></table></div></div>")
    ajouter("<h2>Erreurs</h2>")
    erreurs = r.get("erreurs") or []
    if not erreurs:
        ajouter("<p class=\"rien\">Aucune erreur.</p>")
    else:
        ajouter("<table data-role=\"erreurs\"><thead><tr><th>Heure</th><th>Où</th><th>Ce qui s'est passé</th>"
                "<th class=\"nombre\">Fois</th></tr></thead><tbody>")
        for e in erreurs:
            technique = (f"<details class=\"technique\"><summary>Détail technique</summary>{_e(e['technique'])}"
                         "</details>" if e.get("technique") else "")
            ajouter(f"<tr><td class=\"heure\">{_e(heure_courte(e.get('t')) if e.get('t') else '—')}</td>"
                    f"<td>{_e(e.get('source'))}</td><td>{_e(e.get('texte'))}{technique}</td>"
                    f"<td class=\"nombre\">{_e(e.get('nombre', 1))}</td></tr>")
        ajouter("</tbody></table>")
    ajouter("<h2>Diagnostic du début</h2>")
    diag = r.get("diagnostic")
    if not diag:
        ajouter("<p class=\"rien\">Pas de diagnostic au début de la séance.</p>")
    else:
        ajouter(f"<p>État : <strong>{_e(etat_diagnostic(diag.get('etat')))}</strong>. "
                f"{_e(diag.get('message') or '')}</p>")
        if diag.get("a_regler"):
            ajouter("<ul>" + "".join(f"<li><strong>{_e(v['titre'])}</strong> ({_e(etat_diagnostic(v['etat']))}) : "
                                     f"{_e(v.get('detail') or '')} {_e(v.get('conseil') or '')}</li>"
                                     for v in diag["a_regler"]) + "</ul>")
    ajouter("<h2>Chronologie</h2>")
    chrono = r.get("chronologie") or []
    ajouter("<table data-role=\"chronologie\"><thead><tr><th>Heure</th><th class=\"nombre\">Depuis le début</th>"
            "<th>Ce qui s'est passé</th></tr></thead><tbody>")
    for c in chrono[:CHRONOLOGIE_AFFICHEE]:
        ajouter(f"<tr data-gravite=\"{_e(c.get('gravite'))}\" data-genre=\"{_e(c.get('genre'))}\">"
                f"<td class=\"heure\">{_e(heure_courte(c['t']))}</td><td class=\"nombre\">{_e(duree(c['depuis_s']))}"
                f"</td><td>{_e(c['texte'])}</td></tr>")
    ajouter("</tbody></table>")
    if len(chrono) > CHRONOLOGIE_AFFICHEE:
        ajouter(f"<p class=\"note\">{_e(nombre(len(chrono) - CHRONOLOGIE_AFFICHEE, 0))} lignes de plus dans "
                "rapport.json.</p>")
    ajouter("<h2>Les fichiers de la séance</h2><p class=\"note\">Pour l'analyse, <code>g1-seance exporter "
            f"{_e(r.get('seance'))}</code> fait un .zip de tout le dossier (enregistrement compris).</p><ul>")
    ajouter("".join(f"<li><code>{_e(f)}</code></li>" for f in fichiers_affiches(r)))
    ajouter(f"</ul><p class=\"note\">Rapport écrit le {_e(date_longue(heure_iso()))}.</p></main></body></html>")
    return "".join(h)


# ---------------------------------------------------------------- le tout

def faire_rapport(dossier, sortie=sys.stdout):
    """Écrit rapport.json, trajets.png, rapport.md et rapport.html dans le dossier de la séance ; le manifeste
    reçoit l'état du rapport. Renvoie le dict de rapport.json. Lève l'exception si le rapport échoue (le manifeste
    dit alors « echec » avec la raison)."""
    from atelier.lieu.fichiers import ecrire_atomique
    dossier = Path(dossier)
    debut = time.monotonic()

    def marquer(etat, message=None, fichiers=None):
        def changer(m):
            m["rapport"] = {"etat": etat, "fichiers": list(fichiers or []), "message": message,
                            "date": heure_iso() if etat in ("pret", "echec") else None}
        modifier_manifeste(dossier, changer)

    marquer("en_cours")
    try:
        manifeste = lire_manifeste(dossier) or {"id": dossier.name, "etat": "fermee"}
        bag = chemin(dossier, "bag")
        reindexe = (not (bag / "metadata.yaml").is_file()) and reindexer(bag)
        donnees = charger(bag)
        infos = infos_bag(bag)
        lieu, carte = charger_lieu(chemin(dossier, "lieu"), manifeste.get("etage"))
        actions = lire_actions(dossier)
        rapport = A.analyser(manifeste, actions, donnees, lieu, lire_journaux(dossier), infos,
                             lire_diagnostic(dossier))
        if reindexe:
            rapport["enregistrement"]["reindexe"] = True
        png = None
        try:
            dessiner_trajets(rapport, donnees, carte, lieu, chemin(dossier, "trajets"))
            png = chemin(dossier, "trajets").read_bytes()
        except Exception:       # noqa: BLE001 : le rapport s'écrit sans le graphique
            print("graphique des trajets impossible :\n" + traceback.format_exc(), file=sys.stderr, flush=True)
        rapport["fichiers"] = sorted(set(fichiers_seance(dossier)) | {"rapport.json", "rapport.md", "rapport.html"})
        rapport["duree_rapport_s"] = round(time.monotonic() - debut, 2)
        ecrire_atomique(chemin(dossier, "rapport_json"), json.dumps(rapport, ensure_ascii=False, indent=1) + "\n")
        ecrire_atomique(chemin(dossier, "rapport_md"), texte_markdown(rapport))
        ecrire_atomique(chemin(dossier, "rapport_html"), texte_html(rapport, png))
    except Exception as e:      # noqa: BLE001
        marquer("echec", f"Le rapport n'a pas pu être écrit : {e}"[:300])
        raise
    faits = [f for f in FICHIERS_RAPPORT if (dossier / f).is_file()]
    marquer("pret", None, faits)
    print(f"rapport écrit en {time.monotonic() - debut:.1f} s : {', '.join(faits)} "
          f"({len(rapport['trajets'])} trajets, {len(rapport['anomalies'])} anomalies)", file=sortie, flush=True)
    return rapport


def fichier_rapport(dossier, format_="html"):
    """Chemin du rapport dans ce format (html, md, json)."""
    return chemin(dossier, {"html": "rapport_html", "md": "rapport_md", "json": "rapport_json"}[format_])


__all__ = ["faire_rapport", "texte_html", "texte_markdown", "dessiner_trajets", "charger_lieu", "FICHIERS_SEANCE"]
