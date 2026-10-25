"""Routes de la simulation et du guide.

  POST /api/simulation/demarrer {lieu, etage, fenetre?, navigation?}
        g1-monde simuler --lieu L --etage E --sans-fenetre  (Gazebo, robot proxy, piétons)
        puis g1-guide navigation --lieu L --etage E --simu  (Nav2, routeur, guide)
  POST /api/simulation/arreter      arrête les deux, avec tout ce qu'ils ont lancé
  GET  /api/simulation/etat         processus, simulation en cours, pont ROS 2
  POST /api/guide/aller {cible}     publie l'id sur /guide/aller
  POST /api/guide/stop              publie sur /guide/stop (à défaut : g1-guide stop)
"""
import time

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from atelier.lieu import (ErreurLieu, charger_itineraires, charger_monde, charger_salles, chemin_carte,
                          chemin_monde, chemin_sdf)

from ..communs import ErreurAtelier, dossier_du_lieu, etage_du_lieu, verifier_id
from ..processus import CommandeAbsente, commande, lancer_et_attendre

routeur = APIRouter(tags=["simulation et guide"])


class DemandeSimulation(BaseModel):
    lieu: str
    etage: str
    fenetre: bool = False        # True : fenêtre de Gazebo en plus (jamais pendant les tests)
    navigation: bool = True      # False : Gazebo seul, sans Nav2 ni guide


class DemandeAller(BaseModel):
    cible: str


def _etat(request):
    return request.app.state.atelier


def etat_simulation(etat):
    pont = etat.pont.etat()
    return {"simulation": None if etat.simulation is None else
            {"lieu": etat.simulation["lieu"], "etage": etat.simulation["etage"],
             "en_cours": etat.simulation_en_cours(), "avertissements": etat.simulation["avertissements"]},
            "processus": etat.gestionnaire.etat(),
            "ros": {"actif": pont["actif"], "erreur": pont["erreur"],
                    "guide_ecoute": etat.pont.abonnes_aller()}}


@routeur.post("/api/simulation/demarrer")
async def demarrer(demande: DemandeSimulation, request: Request):
    etat = _etat(request)
    dossier = dossier_du_lieu(demande.lieu)
    etage_du_lieu(dossier, demande.etage)
    if etat.simulation_en_cours():
        s = etat.simulation
        raise ErreurAtelier(409, f"Une simulation tourne déjà (lieu « {s['lieu']} », étage « {s['etage']} ») : "
                                 "arrêtez-la d'abord avec « Arrêter la simulation ».")
    if commande("g1-monde") is None:
        raise ErreurAtelier(503, "Impossible de lancer la simulation : la commande g1-monde n'est pas "
                                 "encore installée (agent Monde).")
    if not chemin_sdf(dossier, demande.etage).is_file():
        raise ErreurAtelier(409, "Le monde Gazebo de cet étage n'existe pas encore : dans l'onglet Carte, "
                                 "cliquez sur « Fabriquer la carte », puis relancez la simulation.")
    avertissements = []
    navigation = demande.navigation
    if navigation and not chemin_carte(dossier, demande.etage).is_file():
        raise ErreurAtelier(409, "Cet étage n'a pas de carte 2D : le guide ne peut pas naviguer. Dans "
                                 "l'onglet Carte, cliquez sur « Fabriquer la carte ».")
    if navigation and commande("g1-guide") is None:
        navigation = False
        avertissements.append("La commande g1-guide n'est pas encore installée : la simulation tourne "
                              "sans guide (le bouton « Y aller » ne fera rien).")
    monde = None
    if chemin_monde(dossier, demande.etage).is_file():
        try:
            monde = charger_monde(dossier, demande.etage)
        except ErreurLieu:
            avertissements.append("Le monde de cet étage est invalide : les piétons ne s'afficheront pas.")

    etat.pont.oublier()
    arguments = ["simuler", "--lieu", dossier, "--etage", demande.etage]
    if not demande.fenetre:
        arguments.append("--sans-fenetre")
    infos = {"lieu": demande.lieu, "etage": demande.etage}
    try:
        await run_in_threadpool(etat.gestionnaire.lancer, "simulation", "g1-monde", arguments, infos)
        if navigation:
            await run_in_threadpool(etat.gestionnaire.lancer, "navigation", "g1-guide",
                                    ["navigation", "--lieu", dossier, "--etage", demande.etage, "--simu"],
                                    infos)
    except CommandeAbsente as e:
        for role in ("navigation", "simulation"):
            await run_in_threadpool(etat.gestionnaire.arreter, role)
        raise ErreurAtelier(503, f"Impossible de lancer la simulation : {e}.") from None
    etat.simulation = {"lieu": demande.lieu, "etage": demande.etage, "dossier": str(dossier),
                       "monde": monde, "debut": time.time(), "avertissements": avertissements}
    return etat_simulation(etat)


@routeur.post("/api/simulation/arreter")
async def arreter(request: Request):
    etat = _etat(request)
    # la navigation d'abord, puis Gazebo (le faux service du scan, lui, continue)
    for role in ("navigation", "simulation"):
        await run_in_threadpool(etat.gestionnaire.arreter, role)
    return etat_simulation(etat)


@routeur.get("/api/simulation/etat")
def lire_etat(request: Request):
    return etat_simulation(_etat(request))


@routeur.post("/api/guide/aller")
def aller(demande: DemandeAller, request: Request):
    etat = _etat(request)
    cible = verifier_id(demande.cible.strip(), "identifiant de salle ou de nœud")
    if etat.simulation is not None:
        # cible connue du lieu simulé ? (sinon le guide la refuserait sans rien dire)
        dossier = dossier_du_lieu(etat.simulation["lieu"])
        try:
            connus = {s.id for s in charger_salles(dossier)} | set(charger_itineraires(dossier).noeuds)
        except ErreurLieu:
            connus = None
        if connus is not None and cible not in connus:
            raise ErreurAtelier(404, f"« {cible} » n'est ni une salle ni un nœud du lieu "
                                     f"« {etat.simulation['lieu']} ». Placez-la dans l'onglet Salles.")
    if not etat.pont.actif:
        raise ErreurAtelier(503, "Pas de liaison avec ROS 2 : "
                            + (etat.pont.erreur or "le pont ROS 2 du serveur n'est pas démarré") + ".")
    ecoute = etat.pont.aller(cible)
    reponse = {"envoye": cible, "ecoute": ecoute}
    if ecoute == 0:
        reponse["avertissement"] = ("Aucun guide n'écoute /guide/aller : lancez la simulation (avec la "
                                    "navigation) ou g1-guide navigation.")
    return reponse


@routeur.post("/api/guide/stop")
async def stop(request: Request):
    etat = _etat(request)
    if etat.pont.actif:
        return {"envoye": "stop", "ecoute": etat.pont.stop()}
    # sans pont ROS 2, on passe par la commande du guide
    try:
        resultat = await run_in_threadpool(lancer_et_attendre, "g1-guide", ["stop"], 15.0)
    except CommandeAbsente:
        raise ErreurAtelier(503, "Impossible d'envoyer l'arrêt : pas de liaison ROS 2 et pas de commande "
                                 "g1-guide. Arrêtez la simulation.") from None
    if resultat["code"] != 0:
        raise ErreurAtelier(500, "g1-guide stop a échoué : arrêtez la simulation.", sortie=resultat["sortie"])
    return {"envoye": "stop", "par": "g1-guide stop"}
