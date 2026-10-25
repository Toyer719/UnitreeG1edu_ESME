"""Routes du scan d'un vrai bâtiment, reliées à la commande g1-slam (agent Scan).

  POST /api/scan/debut {faux?, lieu?, etage?}    g1-slam scan-debut [--faux]
  POST /api/scan/fin {nom, faux?, lieu?}         g1-slam scan-fin --nom N [--lieu L] [--faux]
  GET  /api/scan/etat                            (ajout) g1-slam présente ? faux service lancé ?
  POST /api/scan/faux-service/arreter            (ajout) arrête le faux service lancé par l'Atelier

faux vrai : faux service slam_operate sur l'interface lo, sans robot. Il doit tourner pendant
les commandes : l'Atelier le lance au besoin (g1-slam faux-service) et l'arrête avec le serveur.
faux faux (défaut, comme g1-slam) : le vrai robot, sur eno2. L'interface coche « faux service »
par défaut. Avec lieu, scan-fin note la carte dans lieu.yaml (carte_unitree).
"""
import re
import time
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from ..communs import ErreurAtelier, dossier_du_lieu, etage_du_lieu
from ..processus import CommandeAbsente, commande, lancer_et_attendre

routeur = APIRouter(prefix="/api/scan", tags=["scan"])

DELAI_SCAN = 60.0
ATTENTE_FAUX_SERVICE = 10.0     # s pour que le faux service dise qu'il est prêt
MOTIF_NOM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}(\.pcd)?$")


class DemandeDebut(BaseModel):
    faux: bool = False
    lieu: Optional[str] = None
    etage: Optional[str] = None


class DemandeFin(BaseModel):
    nom: str
    faux: bool = False
    lieu: Optional[str] = None


def _assurer_faux_service(etat, lieu=None, etage=None):
    """Lance g1-slam faux-service s'il ne tourne pas, et attend qu'il soit prêt.
    Renvoie True s'il vient d'être lancé."""
    if etat.gestionnaire.en_cours("faux_slam"):
        return False
    arguments = ["faux-service"]
    if lieu:
        dossier = dossier_du_lieu(lieu)
        arguments += ["--lieu", dossier]
        if etage:
            etage_du_lieu(dossier, etage)
            arguments += ["--etage", etage]
    p = etat.gestionnaire.lancer("faux_slam", "g1-slam", arguments)
    fin = time.monotonic() + ATTENTE_FAUX_SERVICE
    while time.monotonic() < fin:
        if any("prêt" in ligne for ligne in p.etat()["dernieres_lignes"]):
            return True
        if not p.en_cours:
            break
        time.sleep(0.1)
    sortie = "\n".join(p.etat()["dernieres_lignes"])
    etat.gestionnaire.arreter("faux_slam", attente_sigint=3.0)
    raise ErreurAtelier(502, "Le faux service du scan n'a pas démarré : lisez son message ci-dessous.", sortie=sortie)


async def _g1_slam(arguments, faux, quoi):
    if faux:
        arguments = [*arguments, "--faux"]
    try:
        resultat = await run_in_threadpool(lancer_et_attendre, "g1-slam", arguments, DELAI_SCAN)
    except CommandeAbsente as e:
        raise ErreurAtelier(503, f"Impossible de {quoi} : {e}. Elle est livrée par l'agent Scan "
                                 "(bin/g1-slam).") from None
    if resultat["code"] != 0:
        conseil = ("le faux service ne répond pas ; arrêtez-le puis réessayez" if faux else
                   "vérifiez que le robot est allumé et relié au PC (câble Ethernet, source robot.sh)")
        raise ErreurAtelier(502, f"g1-slam n'a pas pu {quoi} : {conseil}. Message de g1-slam ci-dessous.",
                            sortie=resultat["sortie"])
    return {"ok": True, "commande": "g1-slam " + " ".join(map(str, arguments)), "sortie": resultat["sortie"]}


def _verifier_g1_slam(quoi):
    if commande("g1-slam") is None:
        raise ErreurAtelier(503, f"Impossible de {quoi} : la commande g1-slam n'est pas encore installée "
                                 "(agent Scan).")


@routeur.post("/debut")
async def debut(demande: DemandeDebut, request: Request):
    _verifier_g1_slam("démarrer le scan")
    lance = False
    if demande.faux:
        lance = await run_in_threadpool(_assurer_faux_service, request.app.state.atelier,
                                        demande.lieu, demande.etage)
    reponse = await _g1_slam(["scan-debut"], demande.faux, "démarrer le scan")
    reponse["faux_service_lance"] = lance
    return reponse


@routeur.post("/fin")
async def fin(demande: DemandeFin, request: Request):
    nom = demande.nom.strip()
    if not MOTIF_NOM.match(nom):
        raise ErreurAtelier(400, f"« {nom} » n'est pas un nom de carte valable : lettres sans accent, "
                                 "chiffres, « _ » ou « - », 40 au plus (ex. rdc ou rdc.pcd).")
    _verifier_g1_slam("terminer le scan")
    arguments = ["scan-fin", "--nom", nom]
    if demande.lieu:
        arguments += ["--lieu", dossier_du_lieu(demande.lieu)]
    if demande.faux:
        await run_in_threadpool(_assurer_faux_service, request.app.state.atelier, demande.lieu)
    return await _g1_slam(arguments, demande.faux, "terminer le scan")


@routeur.get("/etat")
def etat_scan(request: Request):
    p = request.app.state.atelier.gestionnaire.processus.get("faux_slam")
    return {"g1_slam": commande("g1-slam") is not None, "faux_service": None if p is None else p.etat()}


@routeur.post("/faux-service/arreter")
async def arreter_faux_service(request: Request):
    etat = request.app.state.atelier
    await run_in_threadpool(etat.gestionnaire.arreter, "faux_slam", 5.0)
    return etat_scan(request)
