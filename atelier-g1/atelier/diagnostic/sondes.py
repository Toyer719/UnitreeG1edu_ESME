"""Les sondes du diagnostic (vague 6, section 13.2 du plan) : agent Diagnostic.

Une sonde recueille des faits bruts (rien d'affiché) : le contenu d'un fichier de /sys, la sortie de nmcli, un
ping, la réponse de robot_state 1003, le dernier /pont/etat… Les sondes tournent en parallèle, chacune dans son
fil (démon : une sonde bloquée ne retient jamais le serveur ni g1-diagnostic) et avec son propre délai ; une sonde
peut attendre le résultat d'une autre (les pings attendent le câble, le ssh attend le ping du Jetson). Ce qui n'a
pas répondu à l'échéance du diagnostic vaut {"erreur": "pas de réponse à temps", "delai_depasse": True}.
verdicts.py transforme ensuite ces faits en vérifications, par des fonctions pures.

Le PontRos (atelier/serveur/pont_ros.py) fournit actif, erreur, infos_sujet(), appeler_unitree() (liste blanche :
robot_state 1003 et 1001, sport 7001), attendre_message(), etat_pont() et dernier() ; un faux pont des tests a les
mêmes méthodes.
"""
import json
import threading
import time

from atelier.lieu.diagnostic import (ADRESSES_ROBOT, DELAI_APPEL_S, PROFIL_RESEAU, SUJETS_ROBOT, SUJETS_SLAM,
                                     lire_liste_services, parametre_service_list)
from atelier.lieu.equipe import SUJET_ETAT_CAMERA
from atelier.lieu.robot import API_SPORT_GET_FSM_ID, DELAI_MODE_PERIME_S

from .contexte import EssaisInterdits, interface_cyclonedds

INTERFACE_DEFAUT = "eno2"
DELAI_CABLE_S = 1.0             # les pings attendent la lecture du câble au plus ce temps
DELAI_NMCLI_S = 2.5
DELAI_SSH_S = 6.0               # le ssh du Jetson (ConnectTimeout 3 s compris)
DELAI_DOCKER_PC_S = 3.0
DELAI_BATTERIE_S = 3.0          # /lf/bmsstate : 1 Hz sur le faux G1 (et la découverte DDS d'un nœud neuf)
DELAI_SUJETS_S = 1.5            # attente des sujets du robot dans le graphe ROS 2 (le pont du serveur tourne déjà)
PERIODE_SUJETS_S = 0.2
ECHEANCE_DEFAUT_S = 9.0         # tout le diagnostic : moins de 10 s (DELAI_DIAGNOSTIC_S du contrat : 15 s)

# Ce que publie ou écoute le robot (le côté qui prouve que le robot est là : un « request » est écouté par le
# service du robot, un état est publié par le robot). En répétition, le faux G1 n'a pas /lf/sportmodestate.
COTES_SUJETS = {"/api/sport/request": "abonnes", "/lf/sportmodestate": "publieurs",
                "/state_estimator/odom_pelvis": "publieurs", "/api/slam_operate/request": "abonnes"}
SUJETS_PAR_MODE = {"reel": tuple(SUJETS_ROBOT),
                   "repetition": ("/api/sport/request", "/state_estimator/odom_pelvis")}

# L'empreinte de l'image du conteneur sur le PC (étiquette posée par docker/jetson.py, CLE_EMPREINTE)
COMMANDE_EMPREINTE_PC = ("docker", "image", "inspect", "-f",
                         '{{index .Config.Labels "fr.robot-g1.empreinte"}}', "g1-jetson:arm64")
COMMANDE_PROFILS_ACTIFS = ("nmcli", "-t", "-f", "NAME,DEVICE,STATE", "connection", "show", "--active")
COMMANDE_AUTOCONNECT = ("nmcli", "-g", "connection.autoconnect", "connection", "show", PROFIL_RESEAU)

# Le petit script lancé par UN ssh sur le Jetson : clé = valeur, une par ligne (comme g1-jetson verifier)
SCRIPT_JETSON = r'''racine=$(docker info --format '{{.DockerRootDir}}' 2>/dev/null) && echo "docker_ok=oui" || echo "docker_ok=non"
racine=${racine:-/var/lib/docker}
echo "image=$(docker image inspect -f '{{index .Config.Labels "fr.robot-g1.empreinte"}}' g1-jetson:arm64 2>/dev/null)"
echo "place_ko=$(df -Pk "$HOME" 2>/dev/null | awk 'NR==2 {print $4}')"
echo "place_docker_ko=$(df -Pk "$racine" 2>/dev/null | awk 'NR==2 {print $4}')"
echo "conteneur=$(docker inspect -f '{{.State.Status}}' g1-jetson 2>/dev/null)"
for d in /dev/v4l/by-id/*See3CAM*-video-index0; do [ -e "$d" ] || continue; v=$(readlink -f "$d"); n=${v##*/}
  echo "camera=$d|$v|$(cat /sys/class/video4linux/$n/device/../speed 2>/dev/null)"; done
echo "heure=$(date +%s.%N)"
echo "fin=oui"
'''


def texte_commande(mots):
    """La clé d'une commande dans le faux contexte : ses mots joints par des espaces."""
    return " ".join(str(m) for m in mots)


def lire_terse(ligne):
    """Champs d'une ligne de « nmcli -t » (deux-points séparateurs ; « \\: » et « \\\\ » échappés)."""
    champs, courant, i = [], [], 0
    while i < len(ligne):
        c = ligne[i]
        if c == "\\" and i + 1 < len(ligne):
            courant.append(ligne[i + 1])
            i += 2
            continue
        if c == ":":
            champs.append("".join(courant))
            courant = []
        else:
            courant.append(c)
        i += 1
    champs.append("".join(courant))
    return champs


def lire_champs_jetson(sortie):
    """{cle: valeur} et la liste des caméras ({by_id, chemin, usb_mbps}) de la sortie de SCRIPT_JETSON."""
    champs, cameras = {}, []
    for ligne in (sortie or "").splitlines():
        cle, egal, valeur = ligne.partition("=")
        if not egal:
            continue
        cle = cle.strip()
        if cle == "camera":
            morceaux = (valeur.split("|") + ["", "", ""])[:3]
            try:
                debit = int(morceaux[2])
            except ValueError:
                debit = None
            cameras.append({"by_id": morceaux[0], "chemin": morceaux[1], "usb_mbps": debit})
        else:
            champs[cle] = valeur.strip()
    return champs, cameras


def adresses(ctx):
    """Adresses du PC1, du Jetson et du LiDAR : ATELIER_PC1, ATELIER_JETSON, ATELIER_LIDAR, sinon celles du G1."""
    return {"pc1": ctx.env("ATELIER_PC1") or ADRESSES_ROBOT["pc1"],
            "jetson": ctx.env("ATELIER_JETSON") or ADRESSES_ROBOT["jetson"],
            "lidar": ctx.env("ATELIER_LIDAR") or ADRESSES_ROBOT["lidar"]}


def interface_robot(ctx):
    """Interface du PC reliée au robot : ATELIER_INTERFACE_ROBOT, sinon eno2 (comme routes/liaison.py)."""
    return ctx.env("ATELIER_INTERFACE_ROBOT") or INTERFACE_DEFAUT


def pont_actif(pont):
    return pont is not None and bool(getattr(pont, "actif", False))


# ---------------------------------------------------------------- l'exécution en parallèle

class Collecte:
    """Les sondes en parallèle, un fil démon chacune, jusqu'à une échéance (time.monotonic)."""

    def __init__(self, echeance):
        self.echeance = echeance
        self._resultats = {}
        self._evenements = {}
        self._verrou = threading.Lock()

    def lancer(self, nom, fonction, *args):
        evenement = threading.Event()
        self._evenements[nom] = evenement

        def corps():
            debut = time.monotonic()
            try:
                resultat = fonction(*args)
                if not isinstance(resultat, dict):
                    resultat = {"valeur": resultat}
            except Exception as e:      # noqa: BLE001 : une sonde ne fait jamais tomber le diagnostic
                resultat = {"erreur": str(e) or type(e).__name__, "exception": type(e).__name__}
            resultat = dict(resultat, duree_s=round(time.monotonic() - debut, 3))
            with self._verrou:
                self._resultats[nom] = resultat
            evenement.set()

        threading.Thread(target=corps, name=f"diagnostic {nom}", daemon=True).start()

    def attendre(self, nom, delai=None):
        """Le résultat d'une sonde (attendu au plus delai, et jamais après l'échéance), ou None."""
        evenement = self._evenements.get(nom)
        if evenement is None:
            return None
        reste = self.echeance - time.monotonic()
        if delai is not None:
            reste = min(reste, delai)
        evenement.wait(max(0.0, reste))
        with self._verrou:
            return self._resultats.get(nom)

    def resultats(self):
        """Tous les résultats ; une sonde qui n'a pas fini à l'échéance : « pas de réponse à temps »."""
        for nom in list(self._evenements):
            self.attendre(nom)
        with self._verrou:
            resultats = dict(self._resultats)
        for nom in self._evenements:
            if nom not in resultats:
                resultats[nom] = {"erreur": "pas de réponse à temps", "delai_depasse": True}
        return resultats


# ---------------------------------------------------------------- les sondes

def sonde_cable(ctx, interface):
    """Porteuse et état de l'interface (lecture de /sys, rien n'est envoyé)."""
    porteuse = ctx.lire(f"/sys/class/net/{interface}/carrier")
    operstate = ctx.lire(f"/sys/class/net/{interface}/operstate")
    return {"interface": interface, "carrier": None if porteuse is None else porteuse.strip(),
            "operstate": None if operstate is None else operstate.strip()}


def sonde_adresse(ctx, interface):
    return {"interface": interface, "adresse": ctx.adresse_ipv4(interface)}


def sonde_profil(ctx, interface):
    """Connexions NetworkManager actives, et réglage « se rallume seule » de robot-g1 (lecture seule)."""
    actives = ctx.commande(list(COMMANDE_PROFILS_ACTIFS), delai=DELAI_NMCLI_S)
    auto = ctx.commande(list(COMMANDE_AUTOCONNECT), delai=DELAI_NMCLI_S)
    lignes = None
    if actives.code == 0:
        lignes = [lire_terse(x) for x in actives.sortie.splitlines() if x.strip()]
    return {"interface": interface, "code_actives": actives.code, "erreur_actives": actives.erreur[-300:],
            "actives": [{"nom": (x + ["", "", ""])[0], "interface": (x + ["", "", ""])[1],
                         "etat": (x + ["", "", ""])[2]} for x in lignes] if lignes is not None else None,
            "code_profil": auto.code, "autoconnect": (auto.sortie.strip() or None) if auto.code == 0 else None,
            "erreur_profil": auto.erreur[-300:]}


def sonde_ros(ctx, pont):
    """Réglages ROS du processus (domaine, CYCLONEDDS_URI) et pont ROS 2 du serveur."""
    uri = ctx.env("CYCLONEDDS_URI", "") or ""
    return {"domaine": ctx.env("ROS_DOMAIN_ID", "0") or "0", "interface_dds": interface_cyclonedds(uri),
            "uri": uri[:300], "pont_actif": pont_actif(pont),
            "erreur_pont": getattr(pont, "erreur", None) if pont is not None else "pas de pont ROS 2"}


def sonde_ping(collecte, ctx, adresse):
    """Un ping, seulement si le câble est là (jamais pendant les essais : EssaisInterdits)."""
    cable = collecte.attendre("cable", delai=DELAI_CABLE_S) or {}
    if cable.get("carrier") != "1":
        return {"adresse": adresse, "saute": "cable"}
    try:
        ms = ctx.ping(adresse)
    except EssaisInterdits as e:
        return {"adresse": adresse, "essais": True, "erreur": str(e)}
    except FileNotFoundError as e:
        return {"adresse": adresse, "commande_absente": True, "erreur": str(e)}
    return {"adresse": adresse, "repond": ms is not None, "ms": ms}


def sonde_sujets(pont, sujets, delai=DELAI_SUJETS_S):
    """Les sujets du robot dans le graphe ROS 2 (publiés ou écoutés par un autre nœud que le serveur), attendus au
    plus delai (la découverte DDS d'un nœud neuf prend une à deux secondes)."""
    if not pont_actif(pont):
        return {"sans_ros": True}
    fin = time.monotonic() + delai
    while True:
        vus = {}
        for sujet in sujets:
            infos = pont.infos_sujet(sujet) or {}
            vus[sujet] = {"publieurs": list(infos.get("publieurs") or []),
                          "abonnes": list(infos.get("abonnes") or [])}
        if all(vus[s][COTES_SUJETS.get(s, "publieurs")] for s in sujets) or time.monotonic() >= fin:
            return {"vus": vus, "cotes": {s: COTES_SUJETS.get(s, "publieurs") for s in sujets}}
        time.sleep(PERIODE_SUJETS_S)


def _appel(pont, service, api_id, parametre, delai):
    """(code, data) d'une requête du robot, ou un dict qui dit pourquoi il n'y a pas de réponse."""
    try:
        return pont.appeler_unitree(service, api_id, parametre, delai)
    except TimeoutError as e:
        texte = str(e)
        return {"sans_reponse": True, "personne": "personne n'écoute" in texte, "erreur": texte}
    except (RuntimeError, PermissionError) as e:
        return {"erreur": str(e)}


def sonde_services(pont, delai=DELAI_APPEL_S):
    """robot_state 1003 (ServiceList) : la liste des services du robot (lecture seule)."""
    if not pont_actif(pont):
        return {"sans_ros": True}
    r = _appel(pont, "robot_state", 1003, parametre_service_list(), delai)
    if isinstance(r, dict):
        return r
    code, data = r
    fait = {"code": int(code), "data": str(data)[:2000]}
    if code == 0:
        try:
            fait["services"] = lire_liste_services(data)
        except ValueError as e:
            fait["illisible"] = str(e)
    return fait


def sonde_mode(pont, delai=DELAI_APPEL_S):
    """Le mode du robot : celui de /pont/etat s'il est frais, sinon une lecture 7001 (lecture seule)."""
    if not pont_actif(pont):
        return {"sans_ros": True}
    etat = pont.etat_pont()
    if isinstance(etat, dict) and not etat.get("perime") and isinstance(etat.get("mode_robot"), dict):
        mode = etat["mode_robot"]
        age = mode.get("age_s")
        if isinstance(mode.get("fsm"), int) and (age is None or age < DELAI_MODE_PERIME_S):
            return {"fsm": mode["fsm"], "source": "pont", "age_s": age}
    r = _appel(pont, "sport", API_SPORT_GET_FSM_ID, "{}", delai)
    if isinstance(r, dict):
        return r
    code, data = r
    fait = {"code": int(code), "source": "7001", "data": str(data)[:200]}
    if code == 0:
        try:
            valeur = json.loads(data).get("data")
        except (ValueError, AttributeError):
            valeur = None
        if isinstance(valeur, int) and not isinstance(valeur, bool):
            fait["fsm"] = valeur
        else:
            fait["illisible"] = True
    return fait


def sonde_batterie(pont, delai=DELAI_BATTERIE_S):
    """Le prochain /lf/bmsstate (unitree_hg/BmsState) : la charge, champ soc."""
    if not pont_actif(pont):
        return {"sans_ros": True}
    try:
        msg = pont.attendre_message("/lf/bmsstate", "unitree_hg/msg/BmsState", delai)
    except ValueError as e:
        return {"type_absent": True, "erreur": str(e)}
    if msg is None:
        return {"rien": True}
    return {"soc": int(getattr(msg, "soc"))}


def sonde_camera(pont):
    """Le dernier /camera_poitrine/etat (nœud camera_usb du conteneur), s'il est publié."""
    if not pont_actif(pont):
        return {"sans_ros": True}
    return {"etat": pont.dernier(SUJET_ETAT_CAMERA)}


def sonde_image_pc(ctx):
    """L'empreinte de l'image g1-jetson:arm64 sur le PC (docker local, lecture seule)."""
    r = ctx.commande(list(COMMANDE_EMPREINTE_PC), delai=DELAI_DOCKER_PC_S)
    return {"code": r.code, "empreinte": (r.sortie.strip() or None) if r.code == 0 else None,
            "erreur": r.erreur[-300:]}


def sonde_jetson(collecte, ctx, rapide):
    """UN ssh vers le Jetson (seulement si son ping a répondu ; jamais avec rapide) qui lance SCRIPT_JETSON."""
    if rapide:
        return {"saute": "rapide"}
    ping = collecte.attendre("jetson", delai=DELAI_CABLE_S + 2.0) or {}
    if ping.get("essais"):
        return {"essais": True, "erreur": "pas pendant les essais : aucun ssh vers le Jetson"}
    if ping.get("saute") == "cable":
        return {"saute": "cable"}
    if not ping.get("repond"):
        return {"saute": "jetson"}
    debut = ctx.maintenant()
    try:
        r = ctx.ssh(SCRIPT_JETSON, delai=DELAI_SSH_S)
    except EssaisInterdits as e:
        return {"essais": True, "erreur": str(e)}
    fin = ctx.maintenant()
    champs, cameras = lire_champs_jetson(r.sortie)
    return {"code": r.code, "erreur": (r.erreur or "")[-500:], "champs": champs, "cameras": cameras,
            "complet": champs.get("fin") == "oui", "t0": debut, "t1": fin}


# ---------------------------------------------------------------- tout le recueil

def collecter(mode, pont, ctx, rapide=False, echeance=None, delai_sujets=DELAI_SUJETS_S, delai_appel=DELAI_APPEL_S):
    """Les faits de toutes les sondes du mode ({nom: dict}), en parallèle, avant l'échéance (time.monotonic).
    delai_sujets, delai_appel : plus longs pour un nœud neuf (g1-diagnostic : la découverte DDS du robot)."""
    echeance = echeance if echeance is not None else time.monotonic() + ECHEANCE_DEFAUT_S
    collecte = Collecte(echeance)
    interface = interface_robot(ctx)
    collecte.lancer("ros", sonde_ros, ctx, pont)
    collecte.lancer("sujets", sonde_sujets, pont, SUJETS_PAR_MODE[mode] + tuple(SUJETS_SLAM), delai_sujets)
    collecte.lancer("services", sonde_services, pont, delai_appel)
    collecte.lancer("mode", sonde_mode, pont, delai_appel)
    collecte.lancer("batterie", sonde_batterie, pont)
    if mode == "reel":
        lieux = adresses(ctx)
        collecte.lancer("cable", sonde_cable, ctx, interface)
        collecte.lancer("adresse", sonde_adresse, ctx, interface)
        collecte.lancer("profil", sonde_profil, ctx, interface)
        for nom in ("pc1", "jetson", "lidar"):
            collecte.lancer(nom, sonde_ping, collecte, ctx, lieux[nom])
        collecte.lancer("camera", sonde_camera, pont)
        collecte.lancer("ssh", sonde_jetson, collecte, ctx, rapide)
        if not rapide:
            collecte.lancer("image_pc", sonde_image_pc, ctx)
    faits = collecte.resultats()
    faits["_interface"] = interface
    return faits
