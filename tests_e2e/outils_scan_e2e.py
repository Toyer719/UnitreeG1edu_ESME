#!/usr/bin/env python3
"""Outils des critères de recette du scan intégré (critere_11 à critere_15, section 9 du plan).

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
Session, reconnaissance et évaluation
  verifier-session --session DOSSIER [--reference YAML --min 0.9]
  evaluer --session DOSSIER --reference LIEU [--etage rdc] [--strict]
  fabriquer-nuage --reference LIEU --sortie DOSSIER [--etage rdc] [--pas 0.25]
                                   nuage « vu » par le LiDAR du robot proxy le long des couloirs (lancer de
                                   rayons sur les formes du monde Gazebo), et sa carte 2D
  reconnaitre --session DOSSIER [--reference LIEU]
  faux-slam --lieu L --session S   le faux service a reçu 1801, puis 1802 avec carte_unitree
  bag --dossier DIR SUJET...       ces sujets sont dans l'enregistrement, avec des messages
  verifier-adoption --lieu L --session S [--monde]
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


def verifier_session(args):
    """Fichiers d'une session finie, validité de la reconnaissance et du monde, recouvrement."""
    from atelier import lieu as L
    from atelier.scan import carte2d
    d = Path(args.session)
    ok = True
    for quoi in ("nuage", "carte", "carte_image", "reconnaissance", "monde", "rapport"):
        if not (d / L.FICHIERS_SESSION[quoi]).is_file():
            dire(f"  manque {L.FICHIERS_SESSION[quoi]}")
            ok = False
    session = json.loads((d / "session.json").read_text())
    dire(f"session {session['id']} : {session['etat']} — {session.get('message')}")
    dire(f"  statistiques : {session['statistiques']}")
    if session["etat"] != "termine":
        ok = False
    if (d / L.FICHIERS_SESSION["monde"]).is_file():
        erreurs = L.valider_donnees("monde", _lire_yaml(d / L.FICHIERS_SESSION["monde"]), "monde_scan.monde.yaml")
        if erreurs:
            dire("  monde_scan.monde.yaml invalide :\n    " + "\n    ".join(erreurs[:10]))
            ok = False
        else:
            m = _lire_yaml(d / L.FICHIERS_SESSION["monde"])
            dire(f"  monde_scan.monde.yaml valide : {len(m.get('murs') or [])} murs, {len(m.get('objets') or [])} objets")
    if (d / L.FICHIERS_SESSION["reconnaissance"]).is_file():
        reco = _lire_yaml(d / L.FICHIERS_SESSION["reconnaissance"])
        erreurs = L.valider_reconnaissance(reco)
        if erreurs:
            dire("  reconnaissance.yaml invalide :\n    " + "\n    ".join(erreurs[:10]))
            ok = False
        else:
            dire(f"  reconnaissance : {json.dumps(L.resume_reconnaissance(reco), ensure_ascii=False)}")
    if (d / L.FICHIERS_SESSION["rapport"]).is_file():
        rapport = json.loads((d / L.FICHIERS_SESSION["rapport"]).read_text())
        dire(f"  rapport : traitement en {rapport.get('duree_traitement_s')} s ; comparaison "
             f"{rapport.get('comparaison')} ; avertissements {rapport.get('avertissements')}")
    if args.reference and (d / L.FICHIERS_SESSION["carte"]).is_file():
        c = carte2d.comparer_fichiers(d / L.FICHIERS_SESSION["carte"], args.reference)
        dire(f"Recouvrement avec la carte générée : {100 * c['recouvrement']:.1f} % (au moins "
             f"{100 * args.min:.0f} %) ; couverture {100 * c['couverture']:.1f} % ; "
             f"{c['occupes_scan']} pixels occupés dans le scan")
        if c["recouvrement"] < args.min:
            ok = False
    return 0 if ok else 1


# ---------------------------------------------------------------- évaluation de la reconnaissance

def _aplatir(d, prefixe=""):
    for cle, v in (d.items() if isinstance(d, dict) else []):
        nom = f"{prefixe}.{cle}" if prefixe else str(cle)
        if isinstance(v, dict):
            yield from _aplatir(v, nom)
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            yield nom, float(v)


def _sans_accents(texte):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn").lower()


def _mesure(plat, *variantes, exclure=("objectif", "seuil", "cible", "min", "max", "nombre", "vus", "total")):
    """Valeur de la première clé aplatie qui contient tous les mots d'une variante (la plus courte)."""
    for mots in variantes:
        cles = [c for c in plat
                if all(m in _sans_accents(c) for m in mots)
                and not any(e in _sans_accents(c).split(".")[-1] for e in exclure)]
        if cles:
            cle = min(cles, key=len)
            return cle, plat[cle]
    return None, None


def evaluer(args):
    """Évalue la reconnaissance d'une session avec atelier.scan.evaluation (objectifs de 9.8).

    Bloquants (critère 12) : murs ≥ 0,90, passages ≥ 0,80, objets de la bonne catégorie ≥ 0,70,
    aucune personne gardée. Avec --strict, aussi les autres objectifs de 9.8."""
    from atelier import lieu as L
    from atelier.scan import evaluation
    d = Path(args.session)
    reco = L.lire_reconnaissance(d)
    monde = L.charger_monde(args.reference, args.etage)
    info, image = L.charger_carte(d / L.FICHIERS_SESSION["carte"])
    debut = time.monotonic()
    resultat = evaluation.evaluer(reco, monde, info, image)
    dire(f"évaluation en {time.monotonic() - debut:.1f} s")
    if args.json:
        Path(args.json).write_text(json.dumps(resultat, ensure_ascii=False, indent=2, default=str))
    plat = dict(_aplatir(resultat))
    if not plat:
        dire(f"résultat de evaluer() illisible : {_court(resultat, 1500)}")
        return 1
    objectifs = resultat.get("objectifs") if isinstance(resultat.get("objectifs"), dict) else {}

    def valeur(cle_objectif, *variantes, **options):
        """D'abord les objectifs du bilan (contrat 9.8), sinon une clé du résultat qui contient ces mots."""
        o = objectifs.get(cle_objectif)
        if isinstance(o, dict) and isinstance(o.get("valeur"), (int, float)) and not isinstance(o["valeur"], bool):
            return f"objectifs.{cle_objectif}", float(o["valeur"])
        return _mesure(plat, *variantes, **options)

    # nom affiché : ((clé, valeur), sens, objectif, bloquant pour le critère 12)
    mesures = {
        "murs, rappel": (valeur("murs_rappel", ("mur", "rappel")), ">=", 0.90, True),
        "passages, rappel": (valeur("passages_rappel", ("passage", "rappel")), ">=", 0.80, True),
        "objets, catégorie": (valeur("objets_categorie", ("objet", "categorie")), ">=", 0.70, True),
        "murs, précision": (valeur("murs_precision", ("mur", "precision")), ">=", 0.90, False),
        "passages, précision": (valeur("passages_precision", ("passage", "precision")), ">=", 0.80, False),
        "objets, détection": (valeur("objets_detection", ("objet", "detection")), ">=", 0.80, False),
        "faux objets": (valeur("faux_objets_max", ("faux_objets",)), "<=", 3, False),
    }
    ok = ok_plan = True
    dire(f"{'mesure':22s} {'valeur':>8s}  objectif   (clé du résultat)")
    for nom, ((cle, valeur), sens, objectif, bloquant) in mesures.items():
        if cle is None:
            dire(f"{nom:22s} {'?':>8s}  {sens} {objectif:<6g}   introuvable dans le résultat")
            if bloquant or args.strict:
                ok = False
            ok_plan = False
            continue
        atteint = valeur >= objectif if sens == ">=" else valeur <= objectif
        marque = "oui" if atteint else ("NON" if bloquant or args.strict else "non (objectif du plan, non bloquant)")
        dire(f"{nom:22s} {valeur:8.3f}  {sens} {objectif:<6g}   {marque}  ({cle})")
        if not atteint:
            ok_plan = False
            if bloquant or args.strict:
                ok = False
    # Personnes : jamais cochées d'office, et la personne debout du demo reconnue
    personnes = [o for o in reco.get("objets") or [] if o.get("categorie") == "personne"]
    gardees = [o["id"] for o in personnes if o.get("a_garder")]
    dire(f"personnes reconnues : {len(personnes)} ; gardées : {', '.join(gardees) or 'aucune'}")
    if gardees:
        dire("  une personne est gardée : elle doit être décochée d'office (a_garder: false)")
        ok = False
    vraie = next((o for o in monde.objets if o.categorie_effective == "personne"), None)
    if vraie is not None:
        proche = [o for o in personnes if math.hypot(o["centre"][0] - vraie.centre[0],
                                                       o["centre"][1] - vraie.centre[1]) <= 0.5]
        dire(f"  {vraie.id} reconnue comme personne : {'oui' if proche else 'non'}"
             + ("" if proche else " (objectif du plan" + (")" if args.strict else ", non bloquant)")))
        if not proche:
            ok_plan = False
            if args.strict:
                ok = False
    if isinstance(resultat.get("personnes"), dict):
        dire(f"  évaluation des personnes : {_court(resultat['personnes'], 400)}")
    # Le détail : catégories trouvées, objets vrais et ce qu'ils sont devenus
    resume = L.resume_reconnaissance(reco)
    dire(f"reconnaissance : {json.dumps(resume, ensure_ascii=False)}")
    objets = resultat.get("objets") if isinstance(resultat.get("objets"), dict) else {}
    for d in objets.get("details") or []:
        if isinstance(d, dict):
            dire("  objet vrai : " + ", ".join(f"{k}={v}" for k, v in d.items()))
    for cle in ("faux",):
        if objets.get(cle):
            dire(f"  faux objets : {objets[cle]}")
    passages = resultat.get("passages") if isinstance(resultat.get("passages"), dict) else {}
    if passages.get("faux"):
        dire(f"  passages en trop : {passages['faux']}")
    retenues = {m[0][0] for m in mesures.values()}
    autres = {k: v for k, v in plat.items() if k not in retenues and not k.startswith(("tolerances", "objectifs"))
              and "details" not in k and "par_mur" not in k}
    if autres:
        dire("autres valeurs de l'évaluation : " + ", ".join(f"{k}={v:g}" for k, v in sorted(autres.items())[:40]))
    dire(f"objectifs bloquants : {'atteints' if ok else 'NON atteints'} ; tous les objectifs de 9.8 : "
         f"{'atteints' if ok_plan else 'pas tous'}")
    return 0 if ok else 1


# ---------------------------------------------------------------- nuage fabriqué (lancer de rayons)

HAUTEUR_LIDAR = 1.245             # m, LiDAR du robot proxy (ws/src/g1_sim/models/g1_proxy/model.sdf)
LIDAR_H = (360, -3.14159265, 3.12413936)
LIDAR_V = (16, -0.12217305, 0.90757121)
PORTEE = (0.1, 40.0)


def formes_du_monde(monde):
    """Boîtes (cx, cy, cz, demi_x, demi_y, demi_z, cap) et cylindres (cx, cy, rayon, z0, z1) du monde
    Gazebo que fabrique atelier.monde.sdf (mêmes meubles), sans le sol ni les piétons."""
    import xml.etree.ElementTree as ET
    from atelier.monde.sdf import texte_sdf
    m = copy.deepcopy(monde)
    m.pietons = []
    racine = ET.fromstring(texte_sdf(m, nom="essai"))
    boites, cylindres = [], []
    for modele in racine.find("world").findall("model"):
        if modele.get("name") == "sol":
            continue
        mx, my, mz, _, _, cap = (float(v) for v in modele.find("pose").text.split())
        c, s = math.cos(cap), math.sin(cap)
        for forme in modele.iter("collision"):
            p = forme.find("pose")
            lx, ly, lz = (float(v) for v in p.text.split()[:3]) if p is not None else (0.0, 0.0, 0.0)
            x, y, z = mx + c * lx - s * ly, my + s * lx + c * ly, mz + lz
            g = forme.find("geometry")
            if g.find("box") is not None:
                sx, sy, sz = (float(v) for v in g.find("box/size").text.split())
                boites.append((x, y, z, sx / 2, sy / 2, sz / 2, cap))
            elif g.find("cylinder") is not None:
                r, h = float(g.find("cylinder/radius").text), float(g.find("cylinder/length").text)
                cylindres.append((x, y, r, z - h / 2, z + h / 2))
    return boites, cylindres


def lancer_rayons(origine, directions, boites, cylindres):
    """Distance du premier obstacle (sol z = 0, boîtes, cylindres verticaux) le long de chaque rayon."""
    import numpy as np
    n = len(directions)
    ox, oy, oz = origine
    dx, dy, dz = directions[:, 0], directions[:, 1], directions[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(dz < -1e-9, -oz / dz, np.inf)
        for cx, cy, cz, hx, hy, hz, cap in boites:
            c, s = math.cos(-cap), math.sin(-cap)
            px, py = ox - cx, oy - cy
            lo = (c * px - s * py, s * px + c * py, oz - cz)
            ld = (c * dx - s * dy, s * dx + c * dy, dz)
            tmin, tmax = np.full(n, -np.inf), np.full(n, np.inf)
            for o, d, h in zip(lo, ld, (hx, hy, hz)):
                parallele = np.abs(d) < 1e-12
                if parallele.all():
                    if abs(o) > h:
                        tmin[:] = np.inf
                    continue
                t1, t2 = (-h - o) / d, (h - o) / d
                t1 = np.where(parallele, np.where(abs(o) > h, np.inf, -np.inf), t1)
                t2 = np.where(parallele, np.where(abs(o) > h, -np.inf, np.inf), t2)
                tmin = np.maximum(tmin, np.minimum(t1, t2))
                tmax = np.minimum(tmax, np.maximum(t1, t2))
            touche = (tmax >= tmin) & (tmin > 0)
            t = np.where(touche & (tmin < t), tmin, t)
        for cx, cy, r, z0, z1 in cylindres:
            px, py = ox - cx, oy - cy
            a = dx * dx + dy * dy
            b = 2 * (px * dx + py * dy)
            cc = px * px + py * py - r * r
            disc = b * b - 4 * a * cc
            tc = np.where((disc >= 0) & (a > 1e-12), (-b - np.sqrt(np.maximum(disc, 0))) / (2 * a), np.inf)
            zc = oz + tc * dz
            tc = np.where((tc > 0) & (zc >= z0) & (zc <= z1), tc, np.inf)
            for zp in (z0, z1):
                tp = (zp - oz) / dz
                xp, yp = px + tp * dx, py + tp * dy
                tp = np.where(np.isfinite(tp) & (tp > 0) & (xp * xp + yp * yp <= r * r), tp, np.inf)
                tc = np.minimum(tc, tp)
            t = np.minimum(t, tc)
    return t


def positions_couloirs(lieu, etage, pas):
    """Poses (x, y) tous les « pas » mètres le long de chaque couloir de l'étage."""
    from atelier import lieu as L
    itin = L.charger_itineraires(lieu)
    poses = []
    for c in itin.couloirs:
        a, b = itin.noeuds[c.a], itin.noeuds[c.b]
        if a.etage != etage or b.etage != etage:
            continue
        longueur = math.hypot(b.x - a.x, b.y - a.y)
        k = max(1, int(round(longueur / pas)))
        poses += [(a.x + (b.x - a.x) * i / k, a.y + (b.y - a.y) * i / k) for i in range(k + 1)]
    return poses


def fabriquer_nuage(args):
    """Nuage qu'aurait vu le LiDAR du robot proxy (360 × 16 rayons, de -7° à +52°, à 1,245 m) en
    parcourant les couloirs du monde de référence, réduit à 5 cm comme carte3d ; puis sa carte 2D
    (atelier.scan.carte2d), sur l'emprise du monde. Pas de piétons : ils seraient retirés du nuage."""
    import numpy as np
    from atelier import lieu as L
    from atelier.scan import carte2d, carte3d
    debut = time.monotonic()
    monde = L.charger_monde(args.reference, args.etage)
    boites, cylindres = formes_du_monde(monde)
    poses = positions_couloirs(args.reference, args.etage, args.pas)
    hasard = np.random.default_rng(args.graine)
    n_h, h_min, h_max = LIDAR_H
    n_v, v_min, v_max = LIDAR_V
    azimuts = np.linspace(h_min, h_max, n_h)
    elevations = np.linspace(v_min, v_max, n_v)
    morceaux = []
    for x, y in poses:
        az, el = np.meshgrid(azimuts + hasard.uniform(0, 2 * math.pi), elevations)
        az, el = az.ravel(), el.ravel()
        directions = np.column_stack([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)])
        origine = (x, y, HAUTEUR_LIDAR)
        t = lancer_rayons(origine, directions, boites, cylindres)
        garde = (t >= PORTEE[0]) & (t <= PORTEE[1])
        morceaux.append(np.asarray(origine) + directions[garde] * t[garde, None])
    points = np.vstack(morceaux)
    points = points + hasard.normal(0.0, 0.005, points.shape)     # bruit de mesure de 5 mm
    points[:, 2] = np.maximum(points[:, 2], 0.0)
    reduits = carte3d.reduire(points, 0.05)
    sortie = Path(args.sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    carte3d.ecrire_pcd(sortie / L.FICHIERS_SESSION["nuage"], reduits)
    e = monde.emprise
    info, image, sol = carte2d.fabriquer_carte(reduits, emprise=(e.xmin, e.ymin, e.xmax, e.ymax),
                                               image=L.FICHIERS_SESSION["carte_image"])
    L.enregistrer_carte(sortie / L.FICHIERS_SESSION["carte"], info, image)
    depart = monde.depart_robot
    (sortie / "fabrique.json").write_text(json.dumps({
        "reference": str(L.dossier_lieu(args.reference)), "etage": args.etage, "poses": len(poses),
        "depart_robot": [depart.x, depart.y, depart.theta], "sol": sol}, ensure_ascii=False))
    dire(f"nuage fabriqué en {time.monotonic() - debut:.0f} s : {len(poses)} poses le long des couloirs, "
         f"{len(points)} points, {len(reduits)} après réduction à 5 cm ; {len(boites)} boîtes et "
         f"{len(cylindres)} cylindres ; carte {info.largeur} × {info.hauteur}, {(image == 0).sum()} pixels occupés, "
         f"sol à {sol:.3f} m")
    return 0


def reconnaitre(args):
    """atelier.scan.reconnaissance.reconnaitre sur nuage.pcd et carte.yaml du dossier."""
    from atelier import lieu as L
    from atelier.scan.reconnaissance import reconnaitre as reco
    d = Path(args.session)
    parametres = {"etage": args.etage}
    infos = d / "fabrique.json"
    if infos.is_file():
        parametres["depart_robot"] = tuple(json.loads(infos.read_text())["depart_robot"])
    elif args.reference:
        p = L.charger_monde(args.reference, args.etage).depart_robot
        parametres["depart_robot"] = (p.x, p.y, p.theta)
    debut = time.monotonic()
    r = reco(d / L.FICHIERS_SESSION["nuage"], d / L.FICHIERS_SESSION["carte"], d, parametres)
    dire(f"reconnaissance en {time.monotonic() - debut:.1f} s (durée annoncée {r.get('duree_s')}) : "
         f"{json.dumps(r.get('resume'), ensure_ascii=False)}")
    for a in r.get("avertissements") or []:
        dire(f"  avertissement : {a}")
    ok = True
    for quoi in ("reconnaissance", "monde"):
        if not (d / L.FICHIERS_SESSION[quoi]).is_file():
            dire(f"  {L.FICHIERS_SESSION[quoi]} n'a pas été écrit")
            ok = False
    if time.monotonic() - debut > 60:
        dire("  plus de 60 s : le contrat (9.6) demande moins de 60 s sur un scan du demo")
        ok = False
    return 0 if ok else 1


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
    """Après « Adopter la carte (et le monde) » : la carte de l'étage est celle de la session (les
    personnes et les objets retirés effacés), masque à sa taille, source_carte: scan, ancien monde
    gardé dans la session et monde remplacé (avec --monde)."""
    import numpy as np
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
    if image.shape != image_s.shape or tuple(info.origin[:2]) != tuple(info_s.origin[:2]):
        dire(f"la carte de l'étage ({image.shape}, origine {info.origin}) n'a pas la taille et l'origine de la "
             f"carte de la session ({image_s.shape}, {info_s.origin})")
        ok = False
    else:
        attendue = L.carte_sans_elements_retires(info_s, image_s, L.lire_reconnaissance(d))
        ecarts = int((attendue != image).sum())
        dire(f"carte de l'étage = carte de la session sans les éléments retirés : {ecarts} pixels d'écart")
        if ecarts:
            ok = False
    masque = L.chemin_interdit(lieu, args.etage)
    if not masque.is_file():
        dire("pas de masque des zones interdites après l'adoption")
        ok = False
    else:
        info_m = L.charger_info_carte(masque)
        if (info_m.largeur, info_m.hauteur) != (info.largeur, info.hauteur):
            dire(f"masque {info_m.largeur} × {info_m.hauteur}, carte {info.largeur} × {info.hauteur} : tailles différentes")
            ok = False
    if (d / L.FICHIERS_SESSION["nuage"]).is_file() and not L.chemin_pcd(lieu, args.etage).is_file():
        dire(f"nuage de la session non copié en cartes/{args.etage}.pcd")
        ok = False
    session = L.lire_session(lieu, args.session)
    if not session.get("adoption"):
        dire("session.json : « adoption » n'est pas renseignée")
        ok = False
    if args.monde:
        if not (d / L.FICHIERS_SESSION["monde_remplace"]).is_file():
            dire("l'ancien monde n'est pas gardé dans la session (monde_remplace.monde.yaml)")
            ok = False
        # Comparés après lecture par atelier.lieu : la mise en forme du YAML peut changer à la copie
        actuel = L.Monde.depuis_dict(_lire_yaml(L.chemin_monde(lieu, args.etage))).vers_dict()
        scan = L.Monde.depuis_dict(_lire_yaml(d / L.FICHIERS_SESSION["monde"])).vers_dict()
        if actuel != scan:
            dire("mondes/<etage>.monde.yaml n'est pas le monde de la session")
            ok = False
        else:
            dire(f"monde de l'étage = monde du scan : {len(scan.get('murs') or [])} murs, "
                 f"{len(scan.get('objets') or [])} objets")
    # Personne debout du lieu de référence : aucun pixel occupé dans son empreinte (objectif 9.8)
    if args.reference:
        for o in L.charger_monde(args.reference, args.etage).objets:
            if o.categorie_effective != "personne":
                continue
            X, Y = L.centres_pixels(info)
            dedans = np.hypot(X - o.centre[0], Y - o.centre[1]) <= (o.rayon or 0.25) + 0.05
            n = int((image[dedans] == 0).sum())
            dire(f"{o.id} : {n} pixels occupés dans son empreinte sur la carte adoptée"
                 + ("" if n == 0 else " (objectif 9.8 non atteint, non bloquant ici)"))
    dire("adoption conforme" if ok else "adoption NON conforme")
    return 0 if ok else 1


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
             (("--min",), {"type": float, "default": 0.9}))
    commande("evaluer", evaluer, session, (("--reference",), {"required": True}), etage,
             (("--strict",), {"action": "store_true"}), (("--json",), {}))
    commande("fabriquer-nuage", fabriquer_nuage, (("--reference",), {"required": True}), (("--sortie",), {"required": True}),
             etage, (("--pas",), {"type": float, "default": 0.25}), (("--graine",), {"type": int, "default": 0}))
    commande("reconnaitre", reconnaitre, session, (("--reference",), {}), etage)
    commande("faux-slam", faux_slam, lieu, session)
    commande("bag", bag, (("--dossier",), {"required": True}), (("sujets",), {"nargs": "+"}))
    commande("verifier-adoption", verifier_adoption, lieu, session, etage, (("--monde",), {"action": "store_true"}),
             (("--reference",), {}))
    commande("partager", partager, session, (("--vers",), {"required": True}))
    commande("partagee", partagee, (("--depuis",), {"required": True}), (("--age-max",), {"type": float, "default": 12.0}))
    args = p.parse_args()
    sys.exit(args.fonction(args))


if __name__ == "__main__":
    main()
