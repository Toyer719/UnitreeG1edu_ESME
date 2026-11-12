#!/usr/bin/env python3
"""Outils des critères de recette du scan intégré (critères 7, 11 à 15 et 33, sections 9 et 12 du plan).

Lancés par les scripts avec le Python du projet. Sans ROS : l'API du serveur, les fichiers des
sessions (par atelier.lieu) et les processus (/proc) suffisent.

Ménage et journaux
  nettoyer --lieux DIR             arrête les sessions de scan des lieux du test, puis tout processus
                                   lancé avec ces lieux (variable ATELIER_LIEUX)
  journaux --lieux DIR --vers DIR  recopie la fin des journaux des sessions (affichés par « echoue »)
  restants --lieux DIR [--sauf PGID] [--attendre S]
                                   processus du test encore vivants (hors groupes --sauf) ; code 1 s'il en reste
API du serveur
  route --api URL METHODE CHEMIN   code 0 si le serveur connaît la route (openapi.json), 77 sinon
  appel --api URL METHODE CHEMIN [JSON] [--codes 200,409] [--message] [--contient TEXTE]
                                   un appel, avec ses vérifications : jamais d'erreur 500, un message en
                                   français si demandé ; affiche « session: ID » quand la réponse en a une
  demarrer-api --api URL --lieu L [--mode simu] [--explorer] [--repetition] [--delai-max 10]
  suivre --api URL --lieu L --session S [--duree-min 30] [--part-tour 0.8] [--duree-max 600]
                                   pendant l'enregistrement : aperçu et statistiques ; rend la main quand
                                   on peut appuyer sur « Fin » (code 3 si le scan s'est arrêté seul)
  teleop --api URL --lieu L --session S [--vx 0.4] [--duree 3] [--min 0.5]
                                   les flèches : le robot simulé avance, puis s'arrête seul quand on lâche
  arreter-api --api URL --lieu L --session S
  attendre-fin (--api URL | --fichiers) --lieu L --session S [--delai 1200] [--accepter-echec]
  attendre-etape --lieu L --session S [--etape enregistrement] [--nuages-min 1] [--delai 120]
Session (vague 5 : sans reconnaissance) et adoption
  verifier-session --session DOSSIER [--reference YAML] [--precision 0.98] [--min 0.9] [--ignores-max 0.01]
                   [--points-min 50000] [--inclinaison MIN MAX]
                                   fichiers de la session, rapport (nuages ignorés, sol), nuage d'affichage
                                   (sol à z = 0), carte : précision (pixels du scan à 0,10 m d'un obstacle du
                                   monde) et recouvrement (à 0,05 m)
  servir-session --api URL --lieu L --session S
                                   le serveur sert carte.png, le rapport et le nuage 3D de la session
  damier --session DOSSIER [--vers ID] [--inclinaison-deg 0.6] [--abaissement 1.27] [--decalage-odom -138]
                                   copie de la session « comme le vrai G1 » (même dossier scans/, id suivant
                                   par défaut ; affiche « session: ID ») : nuages dans map à horodatage nul,
                                   odométrie décalée, sol penché et sous l'origine (scan du 27/10)
  faux-slam --lieu L --session S   le faux service a reçu 1801, puis 1802 avec carte_unitree
  bag --dossier DIR SUJET...       ces sujets sont dans l'enregistrement, avec des messages
  verifier-adoption --lieu L --session S [--reference LIEU] [--api URL]
                                   carte telle quelle, nuage de l'étage, carte extrudée (1,5 m), monde dessiné
                                   gardé dans la session et remplacé (piétons gardés) ; avec --api : GET …/nuage,
                                   …/nuage/info et …/monde/maillage les servent
Gazebo et carte d'Unitree (critère 33)
  temps-reel [--duree 20] [--min 0.9]   temps de /clock sur ce temps mural
  contre-un-mur --lieu L [--vx 0.5] [--duree 3]    le robot proxy (/cmd_vel, /odom), poussé vers +x, s'arrête
                                                   contre le premier mur de la carte extrudée, jamais au-delà
  voit-le-maillage --lieu L [--part 0.8]           les points de /points (0,3 à 1,45 m) tombent sur la carte extrudée
  depart --lieu L --x X --y Y [--theta T]          départ du robot simulé (depart_robot du monde de rdc)
  carte-unitree-repetition --api URL --lieu L      répétition par l'Atelier, g1-scan carte-unitree, « Repérer »
Partage d'une session entre critères (le 11 la garde, le 12 et le 13 la reprennent)
  partager --session DOSSIER --vers DIR
  partagee --depuis DIR [--age-max 12]   affiche le dossier de la session gardée, code 1 sans session
"""
import argparse
import copy
import hashlib
import json
import math
import os
import re
import shutil
import signal
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

ETATS_FINIS = ("termine", "echec")
MESSAGES_ANGLAIS = ("not found", "method not allowed", "internal server error", "unprocessable entity",
                    "bad request", "field required")


def dire(texte):
    print(texte, flush=True)


# ---------------------------------------------------------------- processus du test

def _environ(pid):
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            return f.read().split(b"\0")
    except OSError:
        return []


def _stat(pid):
    """(état, ppid, pgid) de /proc/<pid>/stat, ou None."""
    try:
        texte = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    champs = texte[texte.rfind(")") + 2:].split()
    return champs[0], int(champs[1]), int(champs[2])


def _ligne_commande(pid):
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        return "?"


def _ancetres():
    pids, pid = set(), os.getpid()
    while pid > 1:
        pids.add(pid)
        s = _stat(pid)
        if s is None:
            break
        pid = s[1]
    return pids


def processus_du_test(lieux, sauf_groupes=()):
    """Processus vivants lancés avec ATELIER_LIEUX=lieux : tous ceux du test (le script lui-même
    l'exporte après son démarrage, donc il n'y est pas). Ni ce processus ni ses parents."""
    cle = f"ATELIER_LIEUX={lieux}".encode()
    exclus = _ancetres()
    trouves = []
    for nom in os.listdir("/proc"):
        if not nom.isdigit() or int(nom) in exclus:
            continue
        pid = int(nom)
        s = _stat(pid)
        if s is None or s[0] == "Z" or s[2] in sauf_groupes:
            continue
        if cle in _environ(pid):
            trouves.append(pid)
    return trouves


def _vivant(pid):
    s = _stat(pid)
    return s is not None and s[0] != "Z"


def _groupe_vivant(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _signal_groupe(pgid, sig):
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _sessions_des_lieux(lieux):
    from atelier import lieu as L
    racine = Path(lieux)
    if not racine.is_dir():
        return []
    sessions = []
    for dossier in sorted(racine.iterdir()):
        if (dossier / "lieu.yaml").is_file():
            try:
                sessions += [(dossier, s) for s in L.lister_sessions(dossier)]
            except Exception as e:      # un lieu abîmé ne doit pas empêcher le ménage
                dire(f"  sessions de {dossier.name} illisibles : {e}")
    return sessions


def nettoyer(args):
    """Arrête proprement les sessions encore vivantes (SIGINT au groupe, comme g1-scan arreter),
    puis tout processus restant du test. Ne touche à rien d'autre."""
    from atelier import lieu as L
    for dossier, s in _sessions_des_lieux(args.lieux):
        p = s.get("processus") or {}
        if not p.get("pid") or not L.processus_vivant(s):
            continue
        try:
            pgid = os.getpgid(p["pid"])
        except ProcessLookupError:
            continue
        dire(f"[ménage] session {s['id']} ({s['etat']}) encore vivante : SIGINT au groupe {pgid}")
        for sig, attente in ((signal.SIGINT, args.attente), (signal.SIGTERM, 5.0), (signal.SIGKILL, 2.0)):
            _signal_groupe(pgid, sig)
            fin = time.monotonic() + attente
            while time.monotonic() < fin and _groupe_vivant(pgid):
                time.sleep(0.2)
            if not _groupe_vivant(pgid):
                break
    restes = processus_du_test(args.lieux)
    if restes:
        dire(f"[ménage] arrêt de {len(restes)} processus encore lancés par le test (serveur compris) :")
        for pid in restes:
            dire(f"    {pid} {_ligne_commande(pid)[:150]}")
        for sig, attente in ((signal.SIGINT, 5.0), (signal.SIGTERM, 3.0), (signal.SIGKILL, 1.0)):
            for pid in restes:
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    pass
            fin = time.monotonic() + attente
            while time.monotonic() < fin and any(_vivant(p) for p in restes):
                time.sleep(0.2)
            restes = [p for p in restes if _vivant(p)]
            if not restes:
                break
    return 0


def restants(args):
    """Code 0 si aucun processus du test (hors groupes --sauf) ne tourne, après au plus --attendre s."""
    sauf = {int(g) for g in args.sauf}
    fin = time.monotonic() + args.attendre
    while True:
        restes = processus_du_test(args.lieux, sauf)
        if not restes or time.monotonic() >= fin:
            break
        time.sleep(0.5)
    if not restes:
        dire("aucun processus restant")
        return 0
    dire(f"{len(restes)} processus restent :")
    for pid in restes:
        dire(f"    {pid} (groupe {_stat(pid)[2] if _stat(pid) else '?'}) {_ligne_commande(pid)[:160]}")
    return 1


def journaux(args):
    """Fin du journal de chaque session des lieux, recopiée dans --vers (session_<id>.log)."""
    from atelier import dossier_journaux
    vers = Path(args.vers)
    vers.mkdir(parents=True, exist_ok=True)
    for _, s in _sessions_des_lieux(args.lieux):
        candidats = []
        if s.get("journal"):
            candidats.append(Path(s["journal"]))
        candidats += sorted(p for p in dossier_journaux().glob(f"*{s['id']}*") if p.is_file())
        for i, chemin in enumerate(dict.fromkeys(candidats)):
            if chemin.is_file():
                lignes = chemin.read_text(errors="replace").splitlines()[-args.lignes:]
                suffixe = "" if i == 0 else f"_{chemin.stem}"
                (vers / f"session_{s['id']}{suffixe}.log").write_text("\n".join(lignes) + "\n")
    return 0


# ---------------------------------------------------------------- API du serveur

def appel_api(methode, url, corps=None, delai=120.0):
    """(code HTTP, contenu (JSON décodé si possible), durée en s). OSError si le serveur ne répond pas."""
    donnees = None if corps is None else json.dumps(corps).encode()
    requete = urllib.request.Request(url, data=donnees, method=methode, headers={"Content-Type": "application/json"})
    debut = time.monotonic()
    try:
        with urllib.request.urlopen(requete, timeout=delai) as r:
            code, brut, genre = r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        code, brut, genre = e.code, e.read(), e.headers.get("Content-Type", "")
    duree = time.monotonic() - debut
    if "json" in genre:
        try:
            return code, json.loads(brut), duree
        except ValueError:
            pass
    if genre.startswith("text/") or "json" in genre:
        return code, brut.decode(errors="replace"), duree
    return code, brut, duree


def _court(contenu, n=600):
    texte = json.dumps(contenu, ensure_ascii=False) if isinstance(contenu, (dict, list)) else str(contenu)
    return texte if len(texte) <= n else texte[:n] + "…"


def _texte_message(contenu):
    """Le message destiné à l'utilisateur dans une réponse : detail, sinon message (et sortie)."""
    if not isinstance(contenu, dict):
        return str(contenu or "")
    morceaux = []
    for cle in ("detail", "message"):
        v = contenu.get(cle)
        if isinstance(v, str) and v.strip():
            morceaux.append(v.strip())
        elif isinstance(v, list) and v:      # erreurs de validation de FastAPI (422)
            morceaux.append(json.dumps(v, ensure_ascii=False))
    s = contenu.get("session")
    if not morceaux and isinstance(s, dict) and isinstance(s.get("message"), str):
        morceaux.append(s["message"])
    return " | ".join(morceaux)


def _est_francais(texte):
    t = texte.strip().lower()
    return bool(t) and not any(t.startswith(m) or t == m for m in MESSAGES_ANGLAIS)


def route(args):
    try:
        code, schema, _ = appel_api("GET", args.api + "/openapi.json", delai=20)
    except OSError as e:
        dire(f"le serveur ne répond pas : {e}")
        return 1
    if code != 200 or not isinstance(schema, dict):
        dire(f"openapi.json illisible (code {code})")
        return 1
    chemins = schema.get("paths", {})
    motif = re.compile("^" + re.sub(r"\\\{[^}]*\\\}", "[^/]+", re.escape(args.chemin)) + "$")
    for chemin, methodes in chemins.items():
        if (chemin == args.chemin or motif.match(chemin)) and args.methode.lower() in methodes:
            return 0
    dire(f"route absente du serveur : {args.methode} {args.chemin}")
    return 77


def appel(args):
    corps = None if args.json is None else json.loads(args.json)
    try:
        code, contenu, duree = appel_api(args.methode, args.api + args.chemin, corps, args.delai)
    except OSError as e:
        dire(f"{args.methode} {args.chemin} : le serveur ne répond pas ({e})")
        return 1
    dire(f"{args.methode} {args.chemin} → {code} en {duree:.1f} s : {_court(contenu)}")
    if args.sortie:
        Path(args.sortie).write_text(json.dumps(contenu, ensure_ascii=False) if isinstance(contenu, (dict, list))
                                     else str(contenu))
    ok = True
    if code >= 500 and code not in (502, 503):
        dire(f"  erreur {code} du serveur : c'est un plantage, pas un refus expliqué")
        ok = False
    if args.codes and code not in [int(c) for c in args.codes.split(",")]:
        dire(f"  code {code} inattendu (attendus : {args.codes})")
        ok = False
    texte = _texte_message(contenu)
    sortie = contenu.get("sortie") if isinstance(contenu, dict) else None
    if args.message:
        if not _est_francais(texte):
            dire(f"  pas de message clair en français dans la réponse (detail ou message) : « {texte} »")
            ok = False
        else:
            dire(f"  message : {texte}")
    if args.contient:
        tout = f"{texte}\n{sortie or ''}"
        if args.contient.lower() not in tout.lower():
            dire(f"  « {args.contient} » absent du message et de la sortie")
            if sortie:
                dire("  sortie : " + _court(sortie, 800))
            ok = False
    if isinstance(contenu, dict):
        s = contenu.get("session")
        if isinstance(s, dict) and s.get("id"):
            dire(f"session: {s['id']}")
    if "traceback" in f"{texte}\n{sortie or ''}".lower():
        dire("  la réponse contient une trace Python (Traceback) : plantage mal rattrapé")
        ok = False
    return 0 if ok else 1


def _etat(args, session=None):
    """État du scan (format etat_scan), par l'API ou directement dans les fichiers."""
    if getattr(args, "api", None):
        chemin = f"/api/scan/etat?lieu={args.lieu}" + (f"&session={session}" if session else "")
        code, contenu, _ = appel_api("GET", args.api + chemin, delai=30)
        if code != 200 or not isinstance(contenu, dict):
            raise RuntimeError(f"GET {chemin} → {code} : {_court(contenu, 300)}")
        return contenu
    from atelier import lieu as L
    return L.etat_scan(args.lieu, session)


def demarrer_api(args):
    corps = {"lieu": args.lieu, "etage": args.etage, "mode": args.mode, "repetition": args.repetition,
             "explorer": args.explorer}
    try:
        code, contenu, duree = appel_api("POST", args.api + "/api/scan/demarrer", corps, delai=60)
    except OSError as e:
        dire(f"POST /api/scan/demarrer : le serveur ne répond pas ({e})")
        return 1
    dire(f"POST /api/scan/demarrer {json.dumps(corps)} → {code} en {duree:.1f} s")
    if code != 200 or not isinstance(contenu, dict) or not isinstance(contenu.get("session"), dict):
        dire(f"  réponse : {_court(contenu, 1500)}")
        return 1
    s = contenu["session"]
    dire(f"  session {s['id']} : état {s['etat']}, étape {s['etape']}, mode {s['mode']}, "
         f"explorer {s['explorer']}, sujets {s['sujets']['nuage']} et {s['sujets']['odom']}")
    dire(f"  message : {s.get('message')}")
    ok = True
    if s["etat"] != "en_cours" or not contenu.get("actif"):
        dire("  la session devrait être en_cours et active juste après le démarrage")
        ok = False
    if s["mode"] != args.mode or bool(s["explorer"]) != args.explorer or bool(s["repetition"]) != args.repetition:
        dire("  mode, explorer ou repetition de la session ne sont pas ceux demandés")
        ok = False
    if duree > args.delai_max:
        dire(f"  trop lent : {duree:.1f} s (au plus {args.delai_max:g} s ; g1-scan demarrer doit rendre la main "
             "en moins de 3 s)")
        ok = False
    dire(f"session: {s['id']}")
    return 0 if ok else 1


def longueur_couloirs(lieu, etage):
    from atelier import lieu as L
    itin = L.charger_itineraires(lieu)
    total = 0.0
    for c in itin.couloirs:
        a, b = itin.noeuds[c.a], itin.noeuds[c.b]
        if a.etage == etage and b.etage == etage:
            total += math.hypot(b.x - a.x, b.y - a.y)
    return total


def suivre(args):
    """Suit l'enregistrement par l'API, comme l'interface (état chaque seconde, aperçu toutes les 2 s).
    Rend la main quand on peut appuyer sur « Fin » : au moins duree_min s, et le robot a parcouru
    part_tour × la longueur des couloirs (ou duree_max s). Vérifie que l'aperçu se met à jour."""
    tour = longueur_couloirs(args.lieu, args.etage)
    cible = args.part_tour * tour
    dire(f"couloirs de l'étage : {tour:.1f} m ; « Fin » après {args.duree_min:g} s au moins et {cible:.1f} m "
         f"parcourus (ou {args.duree_max:g} s)")
    debut = time.monotonic()
    vus_maj, longueurs, png_ok, etapes = [], [], False, []
    dernier_aff = dernier_apercu = -100.0
    stats = {}
    fin_seule = False
    while True:
        ecoule = time.monotonic() - debut
        try:
            etat = _etat(args, args.session)
        except (RuntimeError, OSError) as e:
            dire(f"  {ecoule:5.0f} s : état illisible : {e}")
            time.sleep(1.0)
            continue
        s = etat["session"]
        stats = s["statistiques"]
        if not etapes or etapes[-1] != s["etape"]:
            etapes.append(s["etape"])
            dire(f"  {ecoule:5.0f} s : état {s['etat']}, étape {s['etape']} — {s.get('message')}")
        if s["etat"] != "en_cours":
            dire(f"  le scan a quitté l'enregistrement de lui-même après {ecoule:.0f} s (état {s['etat']}, "
                 f"{stats.get('distance_m', 0):.1f} m) — {s.get('message')}")
            fin_seule = True
            break
        if ecoule - dernier_apercu >= 2.0:
            dernier_apercu = ecoule
            try:
                code, apercu, _ = appel_api("GET", f"{args.api}/api/scan/apercu.json?lieu={args.lieu}"
                                            f"&session={args.session}", delai=10)
                if code == 200 and isinstance(apercu, dict):
                    if not vus_maj or vus_maj[-1] != apercu.get("maj"):
                        vus_maj.append(apercu.get("maj"))
                        longueurs.append((len(apercu.get("points") or []), len(apercu.get("trajectoire") or [])))
                if not png_ok:
                    code, image, _ = appel_api("GET", f"{args.api}/api/scan/apercu.png?lieu={args.lieu}"
                                               f"&session={args.session}", delai=10)
                    png_ok = code == 200 and isinstance(image, bytes) and image[:8] == b"\x89PNG\r\n\x1a\n"
            except OSError as e:
                dire(f"  aperçu illisible : {e}")
        if ecoule - dernier_aff >= 10:
            dernier_aff = ecoule
            dire(f"  {ecoule:5.0f} s : {stats.get('distance_m', 0):5.1f} m, {stats.get('nuages', 0)} nuages, "
                 f"{stats.get('points', 0)} points ; aperçu mis à jour {len(vus_maj)} fois"
                 + (f", {longueurs[-1][0]} points et {longueurs[-1][1]} poses" if longueurs else ""))
        if ecoule >= args.duree_min and (stats.get("distance_m", 0) >= cible or ecoule >= args.duree_max):
            break
        time.sleep(1.0)
    if not fin_seule:
        dire(f"prêt pour « Fin » après {ecoule:.0f} s : {stats.get('distance_m', 0):.1f} m parcourus, "
             f"{stats.get('nuages', 0)} nuages reçus")
    ok = True
    if stats.get("distance_m", 0) < cible and not fin_seule:
        dire(f"  le robot n'a parcouru que {stats.get('distance_m', 0):.1f} m sur {cible:.1f} m : l'exploration "
             "avance-t-elle ? (voir le journal de la session)")
    if len(vus_maj) < 3:
        dire(f"  l'aperçu n'a été mis à jour que {len(vus_maj)} fois (au moins 3 attendues, toutes les 2 s au plus)")
        ok = False
    elif longueurs[-1][1] <= longueurs[0][1]:
        dire(f"  la trajectoire de l'aperçu ne grandit pas ({longueurs[0][1]} → {longueurs[-1][1]} poses)")
        ok = False
    if not png_ok:
        dire("  GET /api/scan/apercu.png n'a jamais rendu d'image PNG")
        ok = False
    if not stats.get("nuages"):
        dire("  aucun nuage reçu d'après les statistiques de la session")
        ok = False
    if ok:
        dire(f"  aperçu mis à jour {len(vus_maj)} fois ; trajectoire de {longueurs[0][1]} à {longueurs[-1][1]} "
             f"poses ; apercu.png lisible")
    if not ok:
        return 2
    return 3 if fin_seule else 0


def _pose_apercu(args, apres=None, delai=30.0):
    """(x, y, maj) du robot dans apercu.json de la session, écrit après le maj apres s'il est donné."""
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        chemin = f"/api/scan/apercu.json?lieu={args.lieu}&session={args.session}"
        try:
            code, contenu, _ = appel_api("GET", args.api + chemin, delai=10.0)
        except OSError:
            code, contenu = 0, None
        if code == 200 and isinstance(contenu, dict) and contenu.get("robot") and contenu.get("maj") != apres:
            return contenu["robot"]["x"], contenu["robot"]["y"], contenu["maj"]
        time.sleep(0.3)
    return None


def teleop(args):
    """Les flèches de l'onglet Scan, par l'API : une consigne vx toutes les 0,2 s pendant --duree, puis
    plus rien. Le robot simulé (pose « robot » de apercu.json) doit avancer d'au moins --min m, puis
    s'arrêter seul (homme mort du serveur : vitesse nulle 0,5 s après la dernière consigne)."""
    p0 = _pose_apercu(args)
    if p0 is None:
        dire("apercu.json sans pose du robot : impossible de suivre la téléopération")
        return 1
    dire(f"avant : robot en ({p0[0]:.2f} ; {p0[1]:.2f})")
    ecoute, fin = 0, time.monotonic() + args.duree
    while time.monotonic() < fin:
        try:
            code, contenu, _ = appel_api("POST", args.api + "/api/simulation/teleop",
                                         {"vx": args.vx, "vy": 0.0, "wz": 0.0}, delai=5.0)
        except OSError as e:
            dire(f"POST /api/simulation/teleop : le serveur ne répond pas ({e})")
            return 1
        if code != 200:
            dire(f"POST /api/simulation/teleop → {code} : {_court(contenu)}")
            return 1
        ecoute = max(ecoute, int(contenu.get("ecoute") or 0))
        time.sleep(0.2)
    dire(f"consigne vx = {args.vx} m/s pendant {args.duree:g} s, puis plus rien ; abonnés à /cmd_vel : {ecoute}")
    time.sleep(1.0)                             # homme mort (0,5 s), puis le robot s'arrête
    p1 = _pose_apercu(args, apres=p0[2])
    p1 = p1 and _pose_apercu(args, apres=p1[2])  # un aperçu écrit entièrement après l'arrêt
    p2 = p1 and _pose_apercu(args, apres=p1[2])
    if p1 is None or p2 is None:
        dire("apercu.json n'est plus mis à jour")
        return 1
    avance, apres = math.hypot(p1[0] - p0[0], p1[1] - p0[1]), math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    dire(f"après : ({p1[0]:.2f} ; {p1[1]:.2f}), soit {avance:.2f} m parcourus ; puis {apres:.3f} m de plus "
         "sans consigne")
    ok = True
    if avance < args.min:
        dire(f"  le robot n'a avancé que de {avance:.2f} m (au moins {args.min:g} m attendus)")
        ok = False
    if apres > 0.05:
        dire(f"  le robot continue sans consigne ({apres:.2f} m) : l'homme mort n'a pas arrêté le robot")
        ok = False
    return 0 if ok else 1


def arreter_api(args):
    corps = {"lieu": args.lieu, "session": args.session}
    try:
        code, contenu, duree = appel_api("POST", args.api + "/api/scan/arreter", corps, delai=args.delai)
    except OSError as e:
        dire(f"POST /api/scan/arreter : le serveur ne répond pas ({e})")
        return 1
    dire(f"POST /api/scan/arreter → {code} en {duree:.1f} s")
    if code != 200 or not isinstance(contenu, dict) or not isinstance(contenu.get("session"), dict):
        dire(f"  réponse : {_court(contenu, 1500)}")
        return 1
    s = contenu["session"]
    dire(f"  état {s['etat']}, étape {s['etape']}, progression {s['progression']} — {s.get('message')}")
    ok = True
    if s["etat"] == "en_cours":
        dire("  la session est encore en_cours : la route doit rendre la main quand l'enregistrement est fermé")
        ok = False
    if s["etat"] in ("traitement", "termine") and not s.get("fin"):
        dire("  « fin » n'est pas renseignée alors que l'enregistrement est fermé")
        ok = False
    if not (s.get("fichiers") or {}).get("enregistrement"):
        dire("  l'enregistrement n'est pas complet (pas de enregistrement/metadata.yaml)")
        ok = False
    return 0 if ok else 1


def attendre_fin(args):
    """Suit le traitement jusqu'à termine (code 0) ou echec (code 1) ; affiche chaque étape."""
    debut = time.monotonic()
    vus, derniere_progression, recule = [], -1, False
    while time.monotonic() - debut < args.delai:
        try:
            etat = _etat(args, args.session)
        except (RuntimeError, OSError) as e:
            dire(f"  état illisible : {e}")
            time.sleep(2.0)
            continue
        s = etat["session"]
        cle = (s["etat"], s["etape"])
        if not vus or vus[-1] != cle:
            vus.append(cle)
            dire(f"  {time.monotonic() - debut:5.0f} s : {s['etat']} / {s['etape']} ({s['progression']} %) — "
                 f"{s.get('message')}")
        if s["etat"] == "traitement":
            if s["progression"] < derniere_progression:
                recule = True
            derniere_progression = s["progression"]
        if s["etat"] in ETATS_FINIS:
            break
        if s.get("interrompue"):
            dire("  la session est interrompue : son processus est mort sans la finir")
            break
        time.sleep(2.0)
    else:
        dire(f"pas fini en {args.delai:g} s")
        return 1
    duree = time.monotonic() - debut
    dire(f"étapes vues : {' → '.join(f'{e}/{t}' for e, t in vus)} ; fin en {duree:.0f} s")
    if recule:
        dire("  la progression a reculé pendant le traitement")
        return 1
    if s["etat"] == "termine":
        if s["progression"] != 100:
            dire(f"  termine, mais progression {s['progression']} (100 attendu)")
            return 1
        return 0
    if args.accepter_echec and s["etat"] == "echec":
        return 0
    return 1


def attendre_etape(args):
    """Attend (dans les fichiers) que la session soit à l'étape voulue, avec au moins nuages_min nuages."""
    from atelier import lieu as L
    debut = time.monotonic()
    s = None
    while time.monotonic() - debut < args.delai:
        s = L.etat_scan(args.lieu, args.session)["session"]
        if s["etat"] != "en_cours":
            dire(f"la session a quitté en_cours avant l'étape {args.etape} : {s['etat']} — {s.get('message')}")
            return 1
        if s["etape"] == args.etape and s["statistiques"]["nuages"] >= args.nuages_min:
            dire(f"étape {s['etape']} après {time.monotonic() - debut:.0f} s : {s['statistiques']}")
            return 0
        time.sleep(1.0)
    dire(f"étape {args.etape} non atteinte en {args.delai:g} s (dernier état : "
         f"{None if s is None else (s['etat'], s['etape'], s['statistiques'])})")
    return 1


# ---------------------------------------------------------------- session finie

def _lire_yaml(chemin):
    import yaml
    with open(chemin) as f:
        return yaml.safe_load(f)


def comparer_cartes(scan, reference):
    """{precision, recouvrement, couverture, occupes} d'une carte face à la référence : précision = part des
    pixels occupés du scan à 0,10 m au plus (2 pixels) d'un obstacle de la référence ; recouvrement : à 0,05 m."""
    from atelier.scan import carte2d
    c1 = carte2d.comparer_fichiers(scan, reference, tolerance_px=1)
    c2 = carte2d.comparer_fichiers(scan, reference, tolerance_px=2)
    return {"precision": c2["recouvrement"], "recouvrement": c1["recouvrement"], "couverture": c1["couverture"],
            "occupes": c1["occupes_scan"]}


def verifier_session(args):
    """Session finie, vague 5 : carte 3D, carte 2D, nuage d'affichage, rapport ; pas de reconnaissance ; nuages
    ignorés, sol, nuage d'affichage et carte comparée à la référence."""
    import numpy as np
    from atelier import lieu as L
    d = Path(args.session)
    ok = True
    for nom in ("nuage.pcd", "carte.yaml", "carte.pgm", "nuage_affichage.bin", "nuage_affichage.json", "rapport.json"):
        if not (d / nom).is_file():
            dire(f"  manque {nom}")
            ok = False
    for nom in ("reconnaissance.yaml", "monde_scan.monde.yaml"):
        if (d / nom).is_file():
            dire(f"  {nom} : la reconnaissance est retirée (vague 5), ce fichier ne devrait plus être écrit")
            ok = False
    session = json.loads((d / "session.json").read_text())
    dire(f"session {session['id']} : {session['etat']} — {session.get('message')}")
    dire(f"  statistiques : {session['statistiques']}")
    if session["etat"] != "termine":
        ok = False
    if (d / "rapport.json").is_file():
        rapport = json.loads((d / "rapport.json").read_text())
        etapes = [e["etape"] for e in rapport.get("etapes", [])]
        nuages, sol = rapport.get("nuages") or {}, rapport.get("sol") or {}
        dire(f"  rapport : étapes {etapes} ; nuages {nuages} ; base de temps {rapport.get('base_de_temps')} ; "
             f"passants retirés {rapport.get('mobiles_retires')} ; sol {sol} ; avertissements "
             f"{rapport.get('avertissements')}")
        if etapes != ["carte_3d", "carte_2d", "nuage"] or "reconnaissance" in rapport:
            dire("  rapport : les étapes devraient être carte_3d, carte_2d et nuage, sans reconnaissance")
            ok = False
        if not nuages or nuages.get("ignores", 1) > args.ignores_max * max(1, nuages.get("recus", 0)):
            dire(f"  trop de nuages ignorés : {nuages} (au plus {100 * args.ignores_max:g} %)")
            ok = False
        if args.inclinaison and not args.inclinaison[0] <= sol.get("inclinaison_deg", -1) <= args.inclinaison[1]:
            dire(f"  pente du sol {sol.get('inclinaison_deg')}° hors de {args.inclinaison[0]}–{args.inclinaison[1]}°")
            ok = False
    try:
        points, entete = L.lire_nuage(L.chemin_nuage_session(d))
        h = points[:, 2].astype(float)
        sol_vu = h[np.abs(h) < 0.1]
        niveau = float(np.median(sol_vu)) if len(sol_vu) else float("nan")
        dire(f"  nuage d'affichage : {entete['points']} points, grille {entete['grille']}, sol vu à {niveau:+.3f} m")
        if entete["points"] < args.points_min or entete["grille"] != 0.05 or not abs(niveau) <= 0.02:
            dire(f"  nuage d'affichage : au moins {args.points_min} points, grille 0,05 et sol à 0,02 m de z = 0 attendus")
            ok = False
    except L.ErreurLieu as e:
        dire(f"  nuage d'affichage illisible : {e.erreurs}")
        ok = False
    if args.reference and (d / "carte.yaml").is_file():
        c = comparer_cartes(d / "carte.yaml", args.reference)
        dire(f"Précision de la carte (à 0,10 m) : {100 * c['precision']:.1f} % (au moins {100 * args.precision:.0f} %)")
        dire(f"Recouvrement avec la carte générée : {100 * c['recouvrement']:.1f} % (au moins "
             f"{100 * args.min:.0f} %) ; couverture {100 * c['couverture']:.1f} % ; {c['occupes']} pixels occupés")
        if c["precision"] < args.precision or c["recouvrement"] < args.min:
            ok = False
    return 0 if ok else 1


def servir_session(args):
    """Le serveur sert la carte (carte.png), le rapport et le nuage 3D (GET /api/scan/nuage, Float32) d'une
    session finie, conformes aux fichiers de la session."""
    from atelier import lieu as L
    d = L.dossier_session(L.dossier_lieu(args.lieu), args.session)
    _, entete = L.lire_nuage(L.chemin_nuage_session(d))
    q = f"lieu={args.lieu}&session={args.session}"
    code_c, png, _ = appel_api("GET", f"{args.api}/api/scan/sessions/{args.session}/carte.png?lieu={args.lieu}")
    code_r, rapport, _ = appel_api("GET", f"{args.api}/api/scan/sessions/{args.session}/rapport?lieu={args.lieu}")
    code_i, info, _ = appel_api("GET", f"{args.api}/api/scan/nuage/info?{q}")
    code_n, nuage, _ = appel_api("GET", f"{args.api}/api/scan/nuage?{q}")
    dire(f"carte.png {code_c}, rapport {code_r}, nuage/info {code_i}, nuage {code_n}")
    ok = (code_c, code_r, code_i, code_n) == (200, 200, 200, 200)
    ok = ok and isinstance(png, bytes) and png[:8] == b"\x89PNG\r\n\x1a\n"
    ok = ok and isinstance(rapport, dict) and [e["etape"] for e in rapport.get("etapes", [])] == ["carte_3d", "carte_2d", "nuage"]
    ok = ok and isinstance(info, dict) and info.get("points") == entete["points"] and info.get("apercu") is False
    ok = ok and isinstance(nuage, bytes) and len(nuage) == 12 * entete["points"]
    if ok:
        dire(f"servis : carte.png ({len(png)} octets), rapport (étapes carte_3d, carte_2d, nuage), nuage de "
             f"{entete['points']} points ({len(nuage)} octets, source {info.get('source')})")
    else:
        dire(f"réponses non conformes : rapport {_court(rapport, 200)} ; info {_court(info, 200)}")
    return 0 if ok else 1


# ---------------------------------------------------------------- le « damier » : une session comme le vrai G1

def damier(args):
    """Copie une session finie (simulation) « comme le scan du 27/10 » : nuages placés dans le repère map, à
    horodatage nul ; odométrie (position du LiDAR) dans map, horodatages décalés ; sol penché et sous l'origine
    (on ajoute le plan au z : x et y ne bougent pas) ; pas de /tf_static. La copie est une session terminée,
    à retraiter (g1-scan traiter --refaire)."""
    import numpy as np
    import rosbag2_py
    from rclpy.serialization import deserialize_message, serialize_message
    from rosidl_runtime_py.utilities import get_message
    from atelier import lieu as L
    from atelier.scan import carte3d
    from atelier.scan.faux_slam import _nuage_xyz
    import datetime
    source = Path(args.session)
    if args.vers:
        cible = source.parent / L.verifier_id_session(args.vers)
        if cible.exists():
            shutil.rmtree(cible)
    else:                                                   # la première minute libre après la session
        quand = datetime.datetime.strptime(source.name, "%Y-%m-%d_%Hh%M")
        cible = source
        while cible.exists():
            quand += datetime.timedelta(minutes=1)
            cible = source.parent / quand.strftime("%Y-%m-%d_%Hh%M")
    shutil.copytree(source, cible, ignore=shutil.ignore_patterns("enregistrement", ".session.lock", ".processus.json",
                                                                   "ancien_*"))
    s = json.loads((cible / "session.json").read_text())
    s.update(id=cible.name, nom=f"{s['nom'][:60]} (comme le G1)", adoption=None, processus=None)
    L.ecrire_session(cible.parent.parent, s)
    pente = math.tan(math.radians(args.inclinaison_deg))
    plan = (0.0, -pente, -args.abaissement)                 # comme le 27/10 : le sol monte vers y négatif

    def incliner(p):
        p = np.asarray(p, dtype=float).reshape(-1, 3).copy()
        p[:, 2] += plan[0] * p[:, 0] + plan[1] * p[:, 1] + plan[2]
        return p
    enr = source / "enregistrement"
    sujets = s["sujets"]
    trajectoire = carte3d.lire_trajectoire(enr, sujets["odom"], "message")
    liens = carte3d.lire_tf_statique(enr)
    lecteur, types = carte3d._ouvrir(enr, [])
    ecrivain = rosbag2_py.SequentialWriter()
    ecrivain.open(rosbag2_py.StorageOptions(uri=str(cible / "enregistrement"), storage_id="sqlite3"),
                  rosbag2_py.ConverterOptions("cdr", "cdr"))
    for nom, genre in types.items():
        if nom != "/tf_static":
            ecrivain.create_topic(rosbag2_py.TopicMetadata(name=nom, type=genre, serialization_format="cdr"))
    classes = {nom: get_message(genre) for nom, genre in types.items()}
    capteur = None
    n_nuages = n_odom = 0
    while lecteur.has_next():
        nom, donnees, instant = lecteur.read_next()
        if nom == "/tf_static":
            continue
        if nom == sujets["odom"]:
            msg = deserialize_message(donnees, classes[nom])
            p, q = msg.pose.pose.position, msg.pose.pose.orientation
            pose = carte3d.transformation((p.x, p.y, p.z), (q.x, q.y, q.z, q.w))
            if capteur is None:
                capteur, _ = carte3d.position_capteur(liens, "lidar", msg.child_frame_id, None)
            lidar = incliner((pose @ capteur)[:3, 3])[0]
            msg.pose.pose.position.x, msg.pose.pose.position.y, msg.pose.pose.position.z = (float(v) for v in lidar)
            msg.header.frame_id = "map"
            t = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9 + args.decalage_odom
            msg.header.stamp.sec, msg.header.stamp.nanosec = int(math.floor(t)), int((t % 1) * 1e9) % 1000000000
            donnees = serialize_message(msg)
            n_odom += 1
        elif nom == sujets["nuage"]:
            msg = deserialize_message(donnees, classes[nom])
            t = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            pose = trajectoire.pose(t)
            if pose is None:
                continue
            repere = msg.header.frame_id.lstrip("/")
            c, _ = carte3d.position_capteur(liens, repere, trajectoire.repere_robot, None)
            m = pose @ c
            points = carte3d.points_du_nuage(msg)
            monde = incliner(points @ m[:3, :3].T + m[:3, 3])
            sortie = _nuage_xyz(monde, "map", msg.header.stamp)
            sortie.header.stamp.sec = sortie.header.stamp.nanosec = 0          # horodatage nul, comme le G1
            donnees = serialize_message(sortie)
            n_nuages += 1
        ecrivain.write(nom, donnees, instant)
    del ecrivain
    dire(f"session {cible.name} « comme le G1 » : {n_nuages} nuages dans map à horodatage nul, {n_odom} odométries "
         f"(position du LiDAR) décalées de {args.decalage_odom:+g} s, sol penché de {args.inclinaison_deg:g}° et "
         f"{args.abaissement:g} m sous l'origine, sans /tf_static")
    dire(f"session: {cible.name}")
    return 0 if n_nuages and n_odom else 1


# ---------------------------------------------------------------- répétition du mode robot

MOTIF_FAUX = re.compile(r"\[faux slam_operate\]\s*(\d{4})\b(.*)")


def faux_slam(args):
    """Le faux service slam_operate a reçu 1801, puis 1802 (avec carte_unitree), tous deux acceptés.
    Il l'écrit dans son journal (« [faux slam_operate] 1801 (…) : {"succeed": true…} ») : on cherche ces
    lignes dans le journal de la session et dans les journaux qui portent l'id de la session."""
    from atelier import dossier_journaux
    from atelier import lieu as L
    s = L.lire_session(args.lieu, args.session)
    candidats = [Path(s["journal"])] if s.get("journal") else []
    candidats += sorted(p for p in dossier_journaux().glob(f"*{args.session}*") if p.is_file())
    candidats += sorted(L.dossier_session(args.lieu, args.session).glob("*.log"))
    recus = []
    for chemin in dict.fromkeys(candidats):
        if not chemin.is_file():
            continue
        for ligne in chemin.read_text(errors="replace").splitlines():
            m = MOTIF_FAUX.search(ligne)
            if m:
                recus.append((int(m.group(1)), m.group(2).strip(), chemin.name))
    dire(f"journaux lus : {', '.join(p.name for p in dict.fromkeys(candidats) if p.is_file()) or 'aucun'}")
    for api, reste, fichier in recus:
        dire(f"  faux service ({fichier}) : {api} {reste[:200]}")
    if not recus:
        dire("aucune commande reçue par le faux service dans les journaux : lancez-le en mode bavard "
             "(g1-slam faux-service l'est), avec sa sortie dans le journal de la session")
        return 1
    acceptes = [(api, reste) for api, reste, _ in recus if '"succeed": true' in reste.replace("'", '"')]
    ordre = [api for api, _ in acceptes]
    ok = True
    if 1801 not in ordre:
        dire("1801 (début du scan) n'a pas été accepté par le faux service")
        ok = False
    if 1802 not in ordre:
        dire("1802 (fin du scan) n'a pas été accepté par le faux service")
        ok = False
    if ok and ordre.index(1801) > max(i for i, a in enumerate(ordre) if a == 1802):
        dire("1802 a été reçu avant 1801")
        ok = False
    carte = s.get("carte_unitree")
    if ok:
        fin_scan = [reste for api, reste in acceptes if api == 1802]
        if not carte or not any(carte in r for r in fin_scan):
            dire(f"la réponse à 1802 ne cite pas la carte de la session ({carte})")
            ok = False
    if ok:
        dire(f"1801 puis 1802 reçus et acceptés par le faux service ; carte {carte}")
    return 0 if ok else 1


def bag(args):
    """Sujets d'un ros2 bag (metadata.yaml) : chacun présent, avec au moins un message."""
    meta = Path(args.dossier) / "metadata.yaml"
    if not meta.is_file():
        dire(f"{args.dossier} : pas de metadata.yaml (enregistrement mal fermé)")
        return 1
    infos = _lire_yaml(meta).get("rosbag2_bagfile_information", {})
    comptes = {t["topic_metadata"]["name"]: int(t.get("message_count", 0))
               for t in infos.get("topics_with_message_count", [])}
    dire(f"enregistrement de {infos.get('duration', {}).get('nanoseconds', 0) / 1e9:.0f} s : "
         + ", ".join(f"{k} ({v})" for k, v in sorted(comptes.items())))
    manquants = [s for s in args.sujets if comptes.get(s, 0) == 0]
    if manquants:
        dire(f"sujets absents ou vides : {', '.join(manquants)}")
        return 1
    return 0


# ---------------------------------------------------------------- adoption

def verifier_adoption(args):
    """Après « Utiliser cette carte » (vague 5) : la carte de l'étage est celle de la session, telle quelle ; le
    masque est à sa taille ; le nuage de l'étage (source scan) ; la carte extrudée (hauteur 1,5) dans le monde,
    murs et objets dessinés retirés (gardés dans monde_remplace.monde.yaml), piétons gardés."""
    from atelier import lieu as L
    lieu = L.dossier_lieu(args.lieu)
    d = L.dossier_session(lieu, args.session)
    ok = True
    fiche = L.charger_fiche(lieu)
    if fiche.etage(args.etage).source_carte != "scan":
        dire(f"lieu.yaml : l'étage {args.etage} n'est pas passé en source_carte: scan")
        ok = False
    info, image = L.charger_carte(L.chemin_carte(lieu, args.etage))
    info_s, image_s = L.charger_carte(d / L.FICHIERS_SESSION["carte"])
    if image.shape != image_s.shape or tuple(info.origin[:2]) != tuple(info_s.origin[:2]) or (image != image_s).any():
        dire("la carte de l'étage n'est pas celle de la session, telle quelle")
        ok = False
    else:
        dire(f"carte de l'étage = carte de la session, telle quelle ({int((image == 0).sum())} pixels occupés)")
    info_m = L.charger_info_carte(L.chemin_interdit(lieu, args.etage))
    if (info_m.largeur, info_m.hauteur) != (info.largeur, info.hauteur):
        dire(f"masque {info_m.largeur} × {info_m.hauteur}, carte {info.largeur} × {info.hauteur} : tailles différentes")
        ok = False
    try:
        points, entete = L.lire_nuage(L.chemin_nuage(lieu, args.etage))
        dire(f"nuage de l'étage : {entete['points']} points, source {entete['source']}, session {entete.get('session')}")
        if entete["source"] != "scan" or entete.get("session") != args.session:
            ok = False
    except L.ErreurLieu as e:
        dire(f"nuage de l'étage illisible : {e.erreurs}")
        ok = False
    monde = L.charger_monde(lieu, args.etage)
    stl = L.chemin_maillage(lieu, args.etage)
    if monde.carte_extrudee is None or monde.carte_extrudee.hauteur != 1.5 or not stl.is_file():
        dire(f"carte extrudée absente ou fausse : {monde.carte_extrudee}, {stl.name} présent : {stl.is_file()}")
        ok = False
    else:
        dire(f"carte extrudée : {stl.name} ({stl.stat().st_size} octets), hauteur {monde.carte_extrudee.hauteur} m")
    garde = d / L.FICHIERS_SESSION["monde_remplace"]
    if args.reference:
        dessine = L.charger_monde(args.reference, args.etage)
        if monde.murs or monde.objets:
            dire(f"le monde garde {len(monde.murs)} murs et {len(monde.objets)} objets dessinés")
            ok = False
        if not garde.is_file():
            dire("l'ancien monde n'est pas gardé dans la session (monde_remplace.monde.yaml)")
            ok = False
        if sorted(p.id for p in monde.pietons) != sorted(p.id for p in dessine.pietons):
            dire(f"piétons : {[p.id for p in monde.pietons]} au lieu de {[p.id for p in dessine.pietons]}")
            ok = False
        else:
            dire(f"monde : carte extrudée, {len(monde.pietons)} piétons gardés ; monde dessiné dans {garde.name}")
    if "carte_du_scan" not in L.chemin_sdf(lieu, args.etage).read_text():
        dire("le monde Gazebo n'a pas le modèle carte_du_scan")
        ok = False
    session = L.lire_session(lieu, args.session)
    if not session.get("adoption"):
        dire("session.json : « adoption » n'est pas renseignée")
        ok = False
    if args.api:
        ok = _servis_par_l_api(args.api, args.lieu, args.etage, stl) and ok
    dire("adoption conforme" if ok else "adoption NON conforme")
    return 0 if ok else 1


def _servis_par_l_api(api, lieu, etage, stl):
    """GET …/nuage, …/nuage/info et …/monde/maillage servent le nuage et le STL de l'étage."""
    base = f"{api}/api/lieux/{lieu}/etages/{etage}"
    code_i, info, _ = appel_api("GET", base + "/nuage/info")
    code_n, nuage, _ = appel_api("GET", base + "/nuage")
    code_m, maillage, _ = appel_api("GET", base + "/monde/maillage")
    if (code_i, code_n, code_m) != (200, 200, 200) or not isinstance(info, dict):
        dire(f"API : …/nuage/info {code_i}, …/nuage {code_n}, …/monde/maillage {code_m} ({_court(info, 200)})")
        return False
    triangles = int.from_bytes(maillage[80:84], "little") if isinstance(maillage, bytes) else -1
    ok = (isinstance(nuage, bytes) and len(nuage) == 12 * info["points"] and info["source"] == "scan"
          and len(maillage) == 84 + 50 * triangles and len(maillage) == stl.stat().st_size)
    dire(f"API : nuage de {info['points']} points ({len(nuage)} octets, source {info['source']}) ; maillage de "
         f"{triangles} triangles ({len(maillage)} octets)" + ("" if ok else " : NON conformes"))
    return ok


# ---------------------------------------------------------------- Gazebo : le monde maillé (critère 33)

def _noeud_ros(nom):
    import rclpy
    rclpy.init()
    return rclpy, rclpy.create_node(nom)


def temps_reel(args):
    """Facteur temps réel : temps de /clock écoulé pendant args.duree secondes de temps mural."""
    from rosgraph_msgs.msg import Clock
    rclpy, n = _noeud_ros("e2e_temps_reel")
    horloge = []
    n.create_subscription(Clock, "/clock", lambda m: horloge.append(m.clock.sec + m.clock.nanosec * 1e-9), 10)
    try:
        fin = time.monotonic() + 60
        while not horloge and time.monotonic() < fin:
            rclpy.spin_once(n, timeout_sec=0.1)
        if not horloge:
            dire("pas de /clock en 60 s : la simulation tourne-t-elle ?")
            return 1
        debut_mur, debut_sim = time.monotonic(), horloge[-1]
        while time.monotonic() - debut_mur < args.duree:
            rclpy.spin_once(n, timeout_sec=0.05)
        facteur = (horloge[-1] - debut_sim) / (time.monotonic() - debut_mur)
    finally:
        n.destroy_node()
        rclpy.try_shutdown()
    dire(f"Facteur temps réel : {facteur:.3f} (au moins {args.min:g}) sur {args.duree:g} s de temps mural")
    return 0 if facteur >= args.min else 1


DEMI_LONGUEUR_ROBOT, DEMI_LARGEUR_ROBOT = 0.104, 0.2385      # robot proxy de g1_sim : 0,208 × 0,477 m


def boites_de_la_carte(lieu, etage):
    """(boîtes (n, 4) xmin, ymin, xmax, ymax en m, info, pixels extrudés) de la carte de l'étage, comme le STL
    (atelier.monde.extrusion : taches retirées, petits trous bouchés, rectangles)."""
    import numpy as np
    from atelier import lieu as L
    from atelier.monde import extrusion as X
    info, image = L.charger_carte(L.chemin_carte(lieu, etage))
    propre = X.nettoyer(np.asarray(image) == 0, X.AIRE_MIN, X.FERMETURE)
    return X.boites_metres(X.rectangles(propre), info), info, propre


def mur_devant(boites, x, y, demi_largeur=DEMI_LARGEUR_ROBOT):
    """x de la première face de boîte devant (x, y) vers +x, dans la bande de la largeur du robot, ou None."""
    devant = (boites[:, 1] < y + demi_largeur) & (boites[:, 3] > y - demi_largeur) & (boites[:, 0] > x)
    return float(boites[devant, 0].min()) if devant.any() else None


def _attendre(rclpy, n, condition, delai):
    fin = time.monotonic() + delai
    while not condition() and time.monotonic() < fin:
        rclpy.spin_once(n, timeout_sec=0.1)
    return condition()


def contre_un_mur(args):
    """Le robot proxy, poussé à vx pendant args.duree s vers +x, s'arrête contre le premier mur de la carte
    extrudée devant lui (face cherchée dans les boîtes du STL) : son avant (x + 0,104 m) ne la dépasse jamais
    (à args.marge près), et il est allé jusqu'à elle."""
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry
    boites, _, _ = boites_de_la_carte(args.lieu, args.etage)
    rclpy, n = _noeud_ros("e2e_contre_un_mur")
    odom = []
    n.create_subscription(Odometry, "/odom", lambda m: odom.append((m.pose.pose.position.x, m.pose.pose.position.y)), 10)
    pub = n.create_publisher(Twist, "/cmd_vel", 10)
    try:
        if not _attendre(rclpy, n, lambda: odom, 60):
            dire("pas de /odom en 60 s")
            return 1
        depart = odom[-1]
        face = mur_devant(boites, depart[0], depart[1])
        if face is None:
            dire(f"aucun mur de la carte extrudée devant ({depart[0]:.2f} ; {depart[1]:.2f}) vers +x")
            return 1
        dire(f"départ ({depart[0]:.3f} ; {depart[1]:.3f}) ; face du mur de la carte extrudée à x = {face:.3f}, "
             f"à {face - depart[0]:.2f} m du centre du robot")
        avant_max = depart[0] + DEMI_LONGUEUR_ROBOT
        debut = time.monotonic()
        while time.monotonic() - debut < args.duree:
            m = Twist()
            m.linear.x = args.vx
            pub.publish(m)
            rclpy.spin_once(n, timeout_sec=0.05)
            avant_max = max(avant_max, odom[-1][0] + DEMI_LONGUEUR_ROBOT)
        for _ in range(10):
            pub.publish(Twist())
            rclpy.spin_once(n, timeout_sec=0.05)
        attente = time.monotonic() + 1.0
        while time.monotonic() < attente:
            rclpy.spin_once(n, timeout_sec=0.05)
            avant_max = max(avant_max, odom[-1][0] + DEMI_LONGUEUR_ROBOT)
        fin = odom[-1]
    finally:
        n.destroy_node()
        rclpy.try_shutdown()
    libre = depart[0] + args.vx * args.duree + DEMI_LONGUEUR_ROBOT
    dire(f"sans mur, l'avant irait à x = {libre:.2f} ; avant du robot au plus à x = {avant_max:.3f} (face à "
         f"{face:.3f}) ; arrêté en ({fin[0]:.3f} ; {fin[1]:.3f})")
    ok = (avant_max <= face + args.marge and fin[0] + DEMI_LONGUEUR_ROBOT >= face - 0.10
          and libre > face + 0.2 and 0.5 <= face - depart[0] <= 1.5)
    dire("le robot s'arrête contre le mur, jamais au-delà" if ok
         else "le robot traverse le mur, s'arrête loin de lui, ou le mur n'est pas à 1 m environ")
    return 0 if ok else 1


def voit_le_maillage(args):
    """/points voit la carte extrudée : les points du LiDAR, replacés par /odom (LiDAR à 1,245 m sur le robot),
    entre 0,3 et 1,45 m de haut, presque tous à 0,10 m au plus d'un pixel extrudé de la carte."""
    import numpy as np
    from nav_msgs.msg import Odometry
    from sensor_msgs.msg import PointCloud2
    from atelier.lieu import dans_image, monde_vers_pixel
    from atelier.scan import carte3d
    _, info, propre = boites_de_la_carte(args.lieu, args.etage)
    proche = propre.copy()                                  # pixels extrudés, dilatés de 2 pixels (0,10 m)
    for di in range(-2, 3):
        for dj in range(-2, 3):
            proche |= np.roll(np.roll(propre, di, axis=0), dj, axis=1)
    rclpy, n = _noeud_ros("e2e_voit_le_maillage")
    odom, nuages = [], []
    n.create_subscription(Odometry, "/odom", lambda m: odom.append(m), 10)
    n.create_subscription(PointCloud2, "/points", lambda m: nuages.append(m) if odom else None, 10)
    try:
        if not _attendre(rclpy, n, lambda: len(nuages) >= 5, 60):
            dire(f"/points ou /odom absents en 60 s ({len(nuages)} nuages)")
            return 1
        pose = odom[-1].pose.pose
        nuage = nuages[-1]
    finally:
        n.destroy_node()
        rclpy.try_shutdown()
    p, q = pose.position, pose.orientation
    m = carte3d.transformation((p.x, p.y, p.z), (q.x, q.y, q.z, q.w))
    m[:3, 3] += m[:3, :3] @ np.asarray(carte3d.CAPTEUR_DEFAUT)
    points = carte3d.points_du_nuage(nuage)
    monde = points @ m[:3, :3].T + m[:3, 3]
    hauts = monde[(monde[:, 2] > 0.3) & (monde[:, 2] < 1.45)]
    c, ligne = monde_vers_pixel(hauts[:, 0], hauts[:, 1], info)
    dedans = dans_image(c, ligne, info)
    sur = np.zeros(len(hauts), dtype=bool)
    sur[dedans] = proche[ligne[dedans], c[dedans]]
    part = float(sur.mean()) if len(hauts) else 0.0
    dire(f"/points ({nuage.header.frame_id}) : {len(points)} points, dont {len(hauts)} entre 0,3 et 1,45 m ; "
         f"{int(sur.sum())} sur la carte extrudée ({100 * part:.0f} %, au moins {100 * args.part:.0f} %)")
    return 0 if sur.sum() >= args.points_min and part >= args.part else 1


def depart(args):
    """Place le départ du robot simulé (depart_robot du monde de rdc) pour l'essai du mur."""
    from atelier import lieu as L
    monde = L.charger_monde(args.lieu, "rdc")
    monde.depart_robot = L.Pose(args.x, args.y, args.theta)
    L.enregistrer_monde(args.lieu, "rdc", monde)
    dire(f"départ du robot simulé en ({args.x:g} ; {args.y:g} ; {args.theta:g})")
    return 0


# ---------------------------------------------------------------- carte d'Unitree (critère 33)

def carte_unitree_repetition(args):
    """Répétition lancée par l'Atelier ; g1-scan carte-unitree attend ; « Repérer le robot » (1804 au faux service,
    qui publie la carte globale) ; la commande l'enregistre : cartes/rdc_unitree.pcd et le nuage source unitree."""
    import subprocess
    from atelier import lieu as L
    code, r, _ = appel_api("POST", args.api + "/api/simulation/demarrer",
                           {"lieu": args.lieu, "etage": "rdc", "mode": "repetition"}, delai=120)
    if code != 200:
        dire(f"POST /api/simulation/demarrer (repetition) : {code} {_court(r)}")
        return 1
    try:
        fin = time.monotonic() + 180
        pret = False
        while time.monotonic() < fin and not pret:
            _, e, _ = appel_api("GET", args.api + "/api/robot/etat")
            pret = (isinstance(e, dict) and e.get("mode") == "repetition" and isinstance(e.get("reperage"), dict)
                    and not e["reperage"].get("perime"))
            if not pret:
                time.sleep(1.0)
        if not pret:
            dire("l'Atelier ne voit pas le repérage de la répétition en 180 s (GET /api/robot/etat)")
            return 1
        dire("répétition lancée par l'Atelier ; l'Atelier voit /reperage/etat")
        commande = [str(RACINE / "bin" / "g1-scan"), "carte-unitree", "--lieu", args.lieu, "--etage", "rdc",
                    "--delai", "90"]
        attente = subprocess.Popen(commande, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        time.sleep(3.0)
        code, r, duree = appel_api("POST", args.api + "/api/robot/reperer", {"lieu": args.lieu, "etage": "rdc"}, delai=60)
        dire(f"« Repérer le robot » : {code} en {duree:.1f} s ({_court(r, 200)})")
        try:
            sortie, _ = attente.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            attente.kill()
            sortie, _ = attente.communicate()
        print(sortie.strip())
        if attente.returncode != 0:
            dire(f"g1-scan carte-unitree : code {attente.returncode}")
            return 1
    finally:
        appel_api("POST", args.api + "/api/simulation/arreter", {}, delai=120)
    lieu = L.dossier_lieu(args.lieu)
    pcd = lieu / "cartes" / "rdc_unitree.pcd"
    points, entete = L.lire_nuage(L.chemin_nuage(lieu, "rdc", "unitree"))
    dire(f"{pcd.name} : {pcd.stat().st_size} octets ; nuage {entete['points']} points, source {entete['source']}")
    return 0 if pcd.is_file() and entete["source"] == "unitree" and entete["points"] > 1000 else 1


# ---------------------------------------------------------------- partage entre critères

def _empreinte_demo():
    h = hashlib.sha256()
    for nom in ("mondes/rdc.monde.yaml", "itineraires.yaml", "salles.yaml", "lieu.yaml"):
        chemin = RACINE / "lieux" / "demo" / nom
        h.update(chemin.read_bytes() if chemin.is_file() else b"")
    return h.hexdigest()[:16]


def partager(args):
    """Garde une copie de la session finie (sans son enregistrement) pour les critères 12 et 13."""
    source = Path(args.session)
    vers = Path(args.vers)
    if vers.exists():
        shutil.rmtree(vers)
    cible = vers / "session" / source.name
    shutil.copytree(source, cible, ignore=shutil.ignore_patterns("enregistrement", ".session.lock"))
    (vers / "origine.json").write_text(json.dumps({
        "quand": time.time(), "date": time.strftime("%Y-%m-%d %H:%M:%S"), "session": source.name,
        "empreinte_demo": _empreinte_demo(), "domaine": os.environ.get("ROS_DOMAIN_ID")}, ensure_ascii=False))
    dire(f"session {source.name} gardée dans {cible} pour les critères 12 et 13")
    return 0


def partagee(args):
    origine = Path(args.depuis) / "origine.json"
    if not origine.is_file():
        print("aucune session gardée par le critère 11", file=sys.stderr)
        return 1
    o = json.loads(origine.read_text())
    age = (time.time() - o["quand"]) / 3600
    cible = Path(args.depuis) / "session" / o["session"]
    if age > args.age_max:
        print(f"la session gardée a {age:.1f} h (au plus {args.age_max:g} h) : relancez le critère 11", file=sys.stderr)
        return 1
    if o.get("empreinte_demo") != _empreinte_demo():
        print("lieux/demo a changé depuis la session gardée : relancez le critère 11", file=sys.stderr)
        return 1
    if not (cible / "session.json").is_file():
        print(f"session gardée incomplète : {cible}", file=sys.stderr)
        return 1
    print(cible)
    return 0


# ---------------------------------------------------------------- ligne de commande

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sous = p.add_subparsers(dest="commande", required=True)

    def commande(nom, fonction, *options):
        s = sous.add_parser(nom)
        for noms, reglages in options:
            s.add_argument(*noms, **reglages)
        s.set_defaults(fonction=fonction)
        return s

    api = (("--api",), {"required": True})
    lieu = (("--lieu",), {"required": True})
    etage = (("--etage",), {"default": "rdc"})
    session = (("--session",), {"required": True})
    commande("nettoyer", nettoyer, (("--lieux",), {"required": True}), (("--attente",), {"type": float, "default": 10.0}))
    commande("journaux", journaux, (("--lieux",), {"required": True}), (("--vers",), {"required": True}),
             (("--lignes",), {"type": int, "default": 60}))
    commande("restants", restants, (("--lieux",), {"required": True}),
             (("--sauf",), {"action": "append", "default": []}), (("--attendre",), {"type": float, "default": 0.0}))
    commande("route", route, api, (("methode",), {}), (("chemin",), {}))
    commande("appel", appel, api, (("methode",), {"choices": ["GET", "POST", "PUT", "DELETE"]}), (("chemin",), {}),
             (("json",), {"nargs": "?"}), (("--codes",), {}), (("--message",), {"action": "store_true"}),
             (("--contient",), {}), (("--delai",), {"type": float, "default": 120.0}), (("--sortie",), {}))
    commande("demarrer-api", demarrer_api, api, lieu, etage, (("--mode",), {"default": "simu"}),
             (("--explorer",), {"action": "store_true"}), (("--repetition",), {"action": "store_true"}),
             (("--delai-max",), {"type": float, "default": 10.0}))
    commande("suivre", suivre, api, lieu, etage, session, (("--duree-min",), {"type": float, "default": 30.0}),
             (("--part-tour",), {"type": float, "default": 0.8}), (("--duree-max",), {"type": float, "default": 600.0}))
    commande("teleop", teleop, api, lieu, session, (("--vx",), {"type": float, "default": 0.4}),
             (("--duree",), {"type": float, "default": 3.0}), (("--min",), {"type": float, "default": 0.5}))
    commande("arreter-api", arreter_api, api, lieu, session, (("--delai",), {"type": float, "default": 120.0}))
    s = commande("attendre-fin", attendre_fin, lieu, session, (("--delai",), {"type": float, "default": 1200.0}),
                 (("--accepter-echec",), {"action": "store_true"}))
    groupe = s.add_mutually_exclusive_group(required=True)
    groupe.add_argument("--api")
    groupe.add_argument("--fichiers", action="store_true")
    commande("attendre-etape", attendre_etape, lieu, session, (("--etape",), {"default": "enregistrement"}),
             (("--nuages-min",), {"type": int, "default": 1}), (("--delai",), {"type": float, "default": 120.0}))
    commande("verifier-session", verifier_session, session, (("--reference",), {}),
             (("--min",), {"type": float, "default": 0.9}), (("--precision",), {"type": float, "default": 0.0}),
             (("--ignores-max",), {"type": float, "default": 0.01}), (("--points-min",), {"type": int, "default": 50000}),
             (("--inclinaison",), {"type": float, "nargs": 2}))
    commande("servir-session", servir_session, api, lieu, session)
    commande("damier", damier, session, (("--vers",), {}),
             (("--inclinaison-deg",), {"type": float, "default": 0.6}), (("--abaissement",), {"type": float, "default": 1.27}),
             (("--decalage-odom",), {"type": float, "default": -138.0}))
    commande("faux-slam", faux_slam, lieu, session)
    commande("bag", bag, (("--dossier",), {"required": True}), (("sujets",), {"nargs": "+"}))
    commande("verifier-adoption", verifier_adoption, lieu, session, etage, (("--reference",), {}), (("--api",), {}))
    commande("temps-reel", temps_reel, (("--duree",), {"type": float, "default": 20.0}),
             (("--min",), {"type": float, "default": 0.9}))
    commande("contre-un-mur", contre_un_mur, lieu, etage, (("--vx",), {"type": float, "default": 0.5}),
             (("--duree",), {"type": float, "default": 3.0}), (("--marge",), {"type": float, "default": 0.02}))
    commande("voit-le-maillage", voit_le_maillage, lieu, etage, (("--part",), {"type": float, "default": 0.8}),
             (("--points-min",), {"type": int, "default": 300}))
    commande("depart", depart, lieu, (("--x",), {"type": float, "required": True}),
             (("--y",), {"type": float, "required": True}), (("--theta",), {"type": float, "default": 0.0}))
    commande("carte-unitree-repetition", carte_unitree_repetition, api, lieu)
    commande("partager", partager, session, (("--vers",), {"required": True}))
    commande("partagee", partagee, (("--depuis",), {"required": True}), (("--age-max",), {"type": float, "default": 12.0}))
    args = p.parse_args()
    sys.exit(args.fonction(args))


if __name__ == "__main__":
    main()
