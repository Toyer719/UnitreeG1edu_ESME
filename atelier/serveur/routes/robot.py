"""Routes du vrai robot et de la répétition (section 10.8 du plan) : repérage et verrou du pont.

  GET  /api/robot/etat [?lieu=L&etage=E]
        {mode, lieu, etage, localisation, repere, etat, position, precision_m, age_s, message,
         marque, pont, reperage}. mode vaut null si aucune navigation ne tourne ; lieu et etage
         (facultatifs) donnent alors la marque au sol du lieu affiché.
  POST /api/robot/reperer {lieu, etage, x?, y?, cap?}
        « Repérer le robot » : publie /reperage/demander (nouvel id ; cap devient theta, repère
        map ; sans x, y et cap : la marque au sol), puis attend 25 s au plus l'état final de cette
        demande sur /reperage/etat. Repéré : 200 et l'état de GET /api/robot/etat ; echec : 502 avec
        le message du relais ; rien : 504 ; 409 en simulation, sans navigation, ou pour un autre lieu
        ou étage ; 400 si x, y et cap ne vont pas ensemble ; 503 sans pont ROS 2.
  POST /api/robot/arret {verrou}
        publie /pont/arret (verrou du pont : le robot reste immobile jusqu'au déverrouillage) ;
        renvoie {verrou, pont, ecoute}.

Le relais odom_vers_tf (paquet g1_nav) envoie lui-même la commande 1804 au service slam_operate
du robot (ou au faux service de la répétition) : l'Atelier ne parle jamais directement au robot.
"""
import itertools
import math
import time
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from atelier.lieu import ErreurLieu, marque_au_sol

from ..communs import ErreurAtelier, dossier_du_lieu, etage_du_lieu

routeur = APIRouter(tags=["vrai robot"])

DELAI_REPERAGE_S = 25.0      # attente de l'état final d'une demande de repérage
DELAI_DECOUVERTE_S = 3.0     # attente du relais (abonné à /reperage/demander)
_NUMEROS = itertools.count(1)

MESSAGES = {
    None: "Aucune navigation ne tourne : lancez la répétition ou le robot dans l'onglet Simulation.",
    "simu": "Simulation : la position vient de Gazebo, il n'y a pas besoin de repérer le robot.",
    "relais": "Le relais de position (odom_vers_tf) ne répond pas encore : la navigation démarre…",
}


class DemandeReperer(BaseModel):
    lieu: str
    etage: str
    x: Optional[float] = None       # m, repère map de l'étage
    y: Optional[float] = None
    cap: Optional[float] = None     # rad, sens inverse des aiguilles d'une montre


class DemandeArret(BaseModel):
    verrou: bool


def _etat(request):
    return request.app.state.atelier


def _marque(lieu, etage):
    """Marque au sol {x, y, theta} (repère map) d'un étage, ou None si le lieu est illisible."""
    if not lieu or not etage:
        return None
    try:
        dossier = dossier_du_lieu(lieu)
        etage_du_lieu(dossier, etage)
        m = marque_au_sol(dossier, etage)
    except (ErreurAtelier, ErreurLieu):
        return None
    return {"x": round(m.x, 4), "y": round(m.y, 4), "theta": round(m.theta, 4)}


def etat_robot(etat, lieu=None, etage=None):
    """Réponse de GET /api/robot/etat (et de POST /api/robot/reperer réussi)."""
    mode = etat.mode_navigation()
    if mode is not None:
        lieu, etage = etat.simulation["lieu"], etat.simulation["etage"]
    reperage = etat.pont.reperage()
    pont = etat.pont.etat_pont()
    reponse = {"mode": mode, "lieu": lieu, "etage": etage, "localisation": None, "repere": False,
               "etat": "non_repere", "position": None, "precision_m": None, "age_s": None,
               "message": MESSAGES[None], "marque": _marque(lieu, etage), "pont": pont,
               "reperage": reperage}
    if mode == "simu":
        robot = etat.pont.etat()["robot"]
        reponse.update(localisation="simu", repere=robot is not None, etat="repere" if robot else "non_repere",
                       message=MESSAGES["simu"],
                       position=None if robot is None else {k: robot[k] for k in ("x", "y", "theta")},
                       age_s=None if robot is None else robot["age_s"])
    elif mode is not None:
        if reperage is None or reperage.get("perime"):
            reponse.update(localisation="unitree", message=MESSAGES["relais"])
        else:
            reponse.update(localisation=reperage.get("localisation"), repere=bool(reperage.get("repere")),
                           etat=reperage.get("etat"), position=reperage.get("pose"),
                           precision_m=reperage.get("precision_m"), age_s=reperage.get("age_s"),
                           message=reperage.get("message", ""))
    return reponse


@routeur.get("/api/robot/etat")
def lire_etat(request: Request, lieu: Optional[str] = None, etage: Optional[str] = None):
    return etat_robot(_etat(request), lieu, etage)


def _pose_demandee(demande):
    """(x, y, theta) de la demande, ou None pour la marque au sol. 400 si incomplète ou absurde."""
    valeurs = {"x": demande.x, "y": demande.y, "cap": demande.cap}
    donnees = [nom for nom, v in valeurs.items() if v is not None]
    if not donnees:
        return None
    if len(donnees) != 3:
        manque = ", ".join(nom for nom, v in valeurs.items() if v is None)
        raise ErreurAtelier(400, f"x, y et cap vont ensemble (il manque : {manque}). Sans aucun des trois, "
                                 "le robot est supposé posé sur la marque au sol.")
    for nom, v in valeurs.items():
        if not math.isfinite(v):
            raise ErreurAtelier(400, f"« {nom} » doit être un nombre fini, pas {v}.")
    if abs(demande.cap) > 2 * math.pi:
        raise ErreurAtelier(400, "Le cap est en radians, entre -2π et 2π (par exemple 1.57 pour un quart de tour).")
    cap = (demande.cap + math.pi) % (2 * math.pi) - math.pi
    return float(demande.x), float(demande.y), cap


@routeur.post("/api/robot/reperer")
def reperer(demande: DemandeReperer, request: Request):
    etat = _etat(request)
    dossier = dossier_du_lieu(demande.lieu)
    etage_du_lieu(dossier, demande.etage)
    pose = _pose_demandee(demande)
    mode = etat.mode_navigation()
    if mode is None:
        raise ErreurAtelier(409, MESSAGES[None])
    if mode == "simu":
        raise ErreurAtelier(409, "Le repérage sert à la répétition et au vrai robot : en simulation, la position "
                                 "vient de Gazebo. Choisissez « Répétition sans robot » ou « Robot ».")
    s = etat.simulation
    if (s["lieu"], s["etage"]) != (demande.lieu, demande.etage):
        raise ErreurAtelier(409, f"La navigation tourne sur le lieu « {s['lieu']} », étage « {s['etage']} » : "
                                 "choisissez ce lieu et cet étage pour repérer le robot.")
    if not etat.pont.actif:
        raise ErreurAtelier(503, "Pas de liaison avec ROS 2 : "
                            + (etat.pont.erreur or "le pont ROS 2 du serveur n'est pas démarré") + ".")
    fin = time.monotonic() + DELAI_DECOUVERTE_S
    while etat.pont.abonnes_reperage() == 0 and time.monotonic() < fin:
        time.sleep(0.1)
    if etat.pont.abonnes_reperage() == 0:
        raise ErreurAtelier(504, "Le relais de position (odom_vers_tf) ne répond pas : la navigation est-elle "
                                 "lancée ? Ouvrez « Ce qui tourne » dans l'onglet Simulation.")
    ident = f"atelier-{int(time.time())}-{next(_NUMEROS)}"
    message = {"id": ident}
    if pose is not None:
        message.update(x=pose[0], y=pose[1], theta=pose[2])
    etat.pont.reperer(message)
    resultat = etat.pont.attendre_reperage(ident, DELAI_REPERAGE_S)
    if resultat is None:
        raise ErreurAtelier(504, f"Pas de réponse du repérage en {DELAI_REPERAGE_S:.0f} s : le relais de "
                                 "position tourne-t-il ? Réessayez, ou ouvrez « Ce qui tourne ».")
    if resultat.get("etat") != "repere":
        raise ErreurAtelier(502, resultat.get("message") or "Le repérage a échoué.")
    reponse = etat_robot(etat)
    reponse["demande"] = ident
    return reponse


@routeur.post("/api/robot/arret")
def arret(demande: DemandeArret, request: Request):
    etat = _etat(request)
    if not etat.pont.actif:
        raise ErreurAtelier(503, "Pas de liaison avec ROS 2 : "
                            + (etat.pont.erreur or "le pont ROS 2 du serveur n'est pas démarré") + ".")
    ecoute = etat.pont.bloquer(demande.verrou)
    reponse = {"verrou": demande.verrou, "pont": etat.pont.etat_pont(), "ecoute": ecoute}
    if ecoute == 0:
        reponse["avertissement"] = ("Aucun pont n'écoute /pont/arret pour l'instant : le verrou sera appliqué "
                                    "dès qu'il démarrera.")
    return reponse
