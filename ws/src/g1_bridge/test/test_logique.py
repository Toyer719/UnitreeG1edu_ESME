"""
Règles du pont, sans ROS, avec une horloge à la main (section 10.3 du plan).

Plafonds, consigne fraîche à 10 Hz, chien de garde de 0,3 s, /guide/stop et sa garde de 1 s,
verrou (3 arrêts en 0,2 s, reprise seulement avec un /cmd_vel neuf), repérage exigé et périmé,
robot muet, refus, lancement et sortie. Chaque état produit est aussi validé par le schéma
etat_pont quand atelier.lieu est disponible.
"""
import json
import math

import pytest

from g1_bridge.logique import (ErreurReglages, est_nulle, message_refus, plafonner, Pont,
                               Reglages)


class Horloge:
    """Temps mural simulé, en secondes."""

    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t

    def avancer(self, dt):
        self.t += dt


try:
    from atelier.lieu import valider_message
except ImportError:       # atelier absent : les états ne sont pas validés par le schéma
    valider_message = None


def conforme(pont):
    """État du pont, vérifié par le schéma etat_pont et ses règles."""
    etat = pont.etat()
    json.dumps(etat)
    if valider_message is not None:
        assert valider_message('etat_pont', etat) == [], etat
    return etat


def nouveau(**reglages):
    horloge = Horloge()
    pont = Pont(Reglages(**reglages), horloge=horloge)
    return pont, horloge


def pret(**reglages):
    """Pont lancé, lien vérifié (réponse à l'arrêt de lancement), robot repéré."""
    pont, h = nouveau(**reglages)
    (arret,) = pont.demarrer()
    assert pont.sur_reponse(arret.identifiant, 0)
    pont.sur_reperage(True)
    return pont, h


def faire_tourner(pont, h, duree, cmd_vel=None, reperage=True, repondre=True, pas=0.02):
    """
    Avance de duree, pas() toutes les 20 ms ; /cmd_vel toutes les 50 ms (20 Hz) s'il est donné.

    /reperage/etat toutes les 0,2 s ; chaque requête reçoit sa réponse si repondre.
    Renvoie [(instant, Envoi)].
    """
    envois = []
    fin = h.t + duree - 1e-9
    prochain_cmd, prochain_rep = h.t, h.t
    while h.t < fin:
        lot = []
        if cmd_vel is not None and h.t >= prochain_cmd - 1e-9:
            lot += pont.sur_cmd_vel(*cmd_vel)
            prochain_cmd += 0.05
        if reperage is not None and h.t >= prochain_rep - 1e-9:
            lot += pont.sur_reperage(reperage)
            prochain_rep += 0.2
        lot += pont.pas()
        for e in lot:
            envois.append((h.t, e))
            if repondre:
                pont.sur_reponse(e.identifiant, 0)
        conforme(pont)
        h.avancer(pas)
    return envois


def vitesses(envoi):
    return (envoi.vx, envoi.vy, envoi.wz)


# ---------------------------------------------------------------- réglages et plafonds

def test_reglages_du_contrat():
    r = Reglages()
    assert (r.vx_max, r.vy_max, r.wz_max) == (0.4, 0.25, 0.6)
    assert (r.duree_consigne, r.duree_arret) == (0.5, 1.0)
    assert (r.delai_cmd_vel, r.frequence) == (0.3, 10.0)
    assert (r.garde_stop, r.exiger_reperage) == (1.0, True)
    assert (r.delai_reperage, r.delai_muet) == (1.0, 1.0)


@pytest.mark.parametrize('reglage', [
    {'vx_max': 0.41}, {'vy_max': 0.3}, {'wz_max': 1.0}, {'vx_max': -0.1}, {'vx_max': math.nan},
    {'duree_consigne': 0.6}, {'duree_consigne': 0.0}, {'delai_cmd_vel': 2.0}, {'frequence': 1.0},
    {'frequence': 100.0}, {'garde_stop': -1.0}, {'delai_muet': 0.0}, {'exiger_reperage': 'oui'},
    {'vx_max': True}])
def test_reglages_refuses(reglage):
    """Plafonds durs : un réglage plus haut (ou absurde) est refusé, avec un message clair."""
    with pytest.raises(ErreurReglages) as erreur:
        Pont(Reglages(**reglage))
    assert next(iter(reglage)) in str(erreur.value)


def test_reglages_plus_prudents_acceptes():
    Pont(Reglages(vx_max=0.2, vy_max=0.1, wz_max=0.3, duree_consigne=0.4, frequence=20.0))


def test_plafonner():
    r = Reglages()
    assert plafonner(1.0, 0.6, 2.0, r) == (0.4, 0.25, 0.6)
    assert plafonner(-1.0, -0.6, -2.0, r) == (-0.4, -0.25, -0.6)
    assert plafonner(0.1, -0.05, 0.2, r) == (0.1, -0.05, 0.2)
    for absurde in (math.nan, math.inf, -math.inf, None, 'a'):
        assert plafonner(0.3, absurde, 0.1, r) == (0.0, 0.0, 0.0)
    assert plafonner(1e9, -1e9, 1e9, r) == (0.4, -0.25, 0.6)
    assert est_nulle((0.0009, -0.0009, 0.0)) and not est_nulle((0.0011, 0.0, 0.0))


# ---------------------------------------------------------------- lancement et sortie

def test_lancement_envoie_un_arret_et_attend_la_reponse():
    pont, h = nouveau()
    (arret,) = pont.demarrer()
    assert vitesses(arret) == (0.0, 0.0, 0.0) and arret.duree == 1.0
    assert arret.parametre == '{"velocity": [0.0, 0.0, 0.0], "duration": 1.0}'
    assert conforme(pont)['etat'] == 'attente_reperage'      # non repéré passe avant demarrage
    pont.sur_reperage(True)
    assert conforme(pont)['etat'] == 'demarrage'
    h.avancer(0.5)
    pont.sur_reperage(True)
    assert conforme(pont)['etat'] == 'demarrage'
    assert pont.sur_reponse(arret.identifiant, 0)
    etat = conforme(pont)
    assert etat['etat'] == 'pret' and etat['code'] == 0 and etat['reponses'] == 1


def test_lancement_sans_reponse_donne_robot_muet():
    pont, h = nouveau()
    pont.demarrer()
    pont.sur_reperage(True)
    h.avancer(0.99)
    pont.sur_reperage(True)
    assert conforme(pont)['etat'] == 'demarrage'
    h.avancer(0.02)
    pont.sur_reperage(True)
    etat = conforme(pont)
    assert etat['etat'] == 'robot_muet' and 'ne répond plus' in etat['message']


def test_lancement_sans_abonne_attend_le_service():
    """Service sport pas encore vu (découverte DDS) : l'arrêt part dès qu'il apparaît."""
    pont, h = nouveau()
    assert pont.demarrer(abonnes=0) == []
    pont.sur_reperage(True)
    assert conforme(pont)['etat'] == 'demarrage'
    h.avancer(1.0)
    pont.sur_reperage(True)
    assert conforme(pont)['etat'] == 'robot_muet'
    assert pont.sur_abonnes(0) == [] and pont.pas() == []
    (arret,) = pont.sur_abonnes(1)
    assert arret.raison == 'lien' and vitesses(arret) == (0.0, 0.0, 0.0) and arret.duree == 1.0
    assert pont.sur_reponse(arret.identifiant, 0)
    assert conforme(pont)['etat'] == 'pret'
    # Ensuite, plus rien : ni répétition, ni nouvel arrêt pour un abonné de plus
    assert faire_tourner(pont, h, 1.0) == []
    assert pont.sur_abonnes(2) == []


def test_verification_repetee_trois_fois_au_plus():
    pont, h = nouveau()
    envois = [(h.t, e) for e in pont.demarrer(abonnes=1)]
    envois += faire_tourner(pont, h, 3.0, repondre=False)
    assert [e.raison for _, e in envois] == ['lancement', 'verification', 'verification']
    assert envois[-1][0] - envois[0][0] == pytest.approx(0.6, abs=0.021)
    assert conforme(pont)['etat'] == 'robot_muet'


def test_verification_arretee_par_la_reponse():
    pont, h = nouveau()
    (arret,) = pont.demarrer(abonnes=1)
    h.avancer(0.1)
    pont.sur_reponse(arret.identifiant, 0)
    assert faire_tourner(pont, h, 2.0) == []


def test_service_relance_pendant_robot_muet():
    """Robot muet au repos, puis le service sport réapparaît (relancé) : vérification du lien."""
    pont, h = pret()
    pont.sur_abonnes(1)
    faire_tourner(pont, h, 0.5, cmd_vel=(0.3, 0, 0), repondre=False)
    faire_tourner(pont, h, 2.0, repondre=False)
    assert conforme(pont)['etat'] == 'robot_muet'
    assert pont.sur_abonnes(0) == []
    (arret,) = pont.sur_abonnes(1)
    assert arret.raison == 'lien' and est_nulle(vitesses(arret))
    pont.sur_reponse(arret.identifiant, 0)
    assert conforme(pont)['etat'] == 'pret'


def test_pas_de_verification_en_marche():
    pont, h = pret()
    pont.sur_abonnes(1)
    faire_tourner(pont, h, 0.5, cmd_vel=(0.3, 0, 0), repondre=False)
    faire_tourner(pont, h, 0.6, cmd_vel=(0.3, 0, 0), repondre=False)
    assert pont.nom_etat() == 'robot_muet' and pont.actif
    assert pont.sur_abonnes(2) == []


def test_sortie_envoie_un_arret():
    pont, h = pret()
    faire_tourner(pont, h, 0.5, cmd_vel=(0.3, 0, 0))
    (arret,) = pont.quitter()
    assert vitesses(arret) == (0.0, 0.0, 0.0) and arret.duree == 1.0


# ---------------------------------------------------------------- consigne fraîche à 10 Hz

def test_consigne_a_10_hz_avec_duree_de_0_5_s():
    pont, h = pret()
    envois = faire_tourner(pont, h, 3.0, cmd_vel=(0.3, 0.1, -0.2))
    mouvement = [(t, e) for t, e in envois if not est_nulle(vitesses(e))]
    assert len(mouvement) == pytest.approx(30, abs=1)
    for _, e in mouvement:
        assert vitesses(e) == (0.3, 0.1, -0.2) and e.duree == 0.5
        assert json.loads(e.parametre) == {'velocity': [0.3, 0.1, -0.2], 'duration': 0.5}
    ecarts = [b[0] - a[0] for a, b in zip(mouvement, mouvement[1:])]
    assert min(ecarts) >= 0.099 - 1e-9 and max(ecarts) <= 0.101 + 1e-9
    ids = [e.identifiant for _, e in envois]
    assert all(b > a for a, b in zip(ids, ids[1:]))
    assert conforme(pont)['etat'] == 'en_mouvement'


def test_depart_immediat():
    """Repos → mouvement : la consigne part tout de suite, sans attendre le prochain pas."""
    pont, h = pret()
    (e,) = pont.sur_cmd_vel(0.2, 0, 0)
    assert vitesses(e) == (0.2, 0.0, 0.0)
    # Un second /cmd_vel 50 ms plus tard n'envoie rien de plus (cadence de 10 Hz)
    h.avancer(0.05)
    assert pont.sur_cmd_vel(0.25, 0, 0) == [] and pont.pas() == []
    h.avancer(0.05)
    (e,) = pont.pas()
    assert vitesses(e) == (0.25, 0.0, 0.0)


def test_consigne_plafonnee():
    pont, h = pret()
    envois = faire_tourner(pont, h, 1.0, cmd_vel=(1.0, 0.6, 2.0))
    assert {vitesses(e) for _, e in envois} == {(0.4, 0.25, 0.6)}
    assert conforme(pont)['consigne'] == {'vx': 0.4, 'vy': 0.25, 'wz': 0.6}
    envois = faire_tourner(pont, h, 0.3, cmd_vel=(-5.0, -5.0, -5.0))
    assert vitesses(envois[-1][1]) == (-0.4, -0.25, -0.6)


def test_nan_donne_un_arret_immediat():
    pont, h = pret()
    faire_tourner(pont, h, 0.5, cmd_vel=(0.3, 0, 0))
    (e,) = pont.sur_cmd_vel(math.nan, 0.0, 0.0)
    assert vitesses(e) == (0.0, 0.0, 0.0) and e.duree == 1.0
    # Tant que les NaN arrivent : des arrêts à 10 Hz, jamais de mouvement
    envois = faire_tourner(pont, h, 1.0, cmd_vel=(0.3, math.inf, 0.0))
    assert envois and all(vitesses(x) == (0.0, 0.0, 0.0) for _, x in envois)
    assert conforme(pont)['etat'] == 'pret'


def test_consigne_nulle_au_format_de_l_arret():
    pont, h = pret()
    faire_tourner(pont, h, 0.5, cmd_vel=(0.3, 0, 0))
    (e,) = pont.sur_cmd_vel(0.0005, 0.0, -0.0005)      # sous 1e-3 : arrêt, tout de suite
    assert vitesses(e) == (0.0, 0.0, 0.0) and e.duree == 1.0
    assert e.parametre == '{"velocity": [0.0, 0.0, 0.0], "duration": 1.0}'


# ---------------------------------------------------------------- chien de garde

def test_arret_0_3_s_apres_le_dernier_cmd_vel_puis_plus_rien():
    pont, h = pret()
    faire_tourner(pont, h, 1.0, cmd_vel=(0.3, 0, 0))
    dernier = pont.t_cmd_vel
    envois = faire_tourner(pont, h, 2.0)       # plus de /cmd_vel
    # La consigne reste fraîche 0,3 s (encore envoyée à 10 Hz), puis un seul arrêt
    mouvement = [t for t, e in envois if not est_nulle(vitesses(e))]
    assert all(t < dernier + 0.3 for t in mouvement) and len(mouvement) <= 3
    arrets = [(t, e) for t, e in envois if est_nulle(vitesses(e))]
    assert len(arrets) == 1
    t, arret = arrets[0]
    assert arret.raison == 'delai_cmd_vel' and arret.duree == 1.0
    assert 0.3 <= t - dernier <= 0.3 + 0.021
    assert conforme(pont)['etat'] == 'pret'
    # Au repos, rien en continu
    assert faire_tourner(pont, h, 3.0) == []


def test_consigne_jamais_au_dela_de_0_5_s():
    """Chaque consigne non nulle a duration 0,5 s : si le pont se tait, le robot s'arrête seul."""
    pont, h = pret()
    envois = faire_tourner(pont, h, 2.0, cmd_vel=(0.4, 0.25, 0.6))
    assert all(e.duree <= 0.5 for _, e in envois if not est_nulle(vitesses(e)))


# ---------------------------------------------------------------- /guide/stop

def test_guide_stop_arret_immediat_puis_garde_de_1_s():
    pont, h = pret()
    faire_tourner(pont, h, 1.0, cmd_vel=(0.3, 0, 0))
    (arret,) = pont.sur_guide_stop()
    assert vitesses(arret) == (0.0, 0.0, 0.0) and arret.raison == 'stop_guide'
    t_stop = h.t
    assert conforme(pont)['etat'] == 'arret'
    assert not pont.mouvement_permis()
    # /cmd_vel continue : ignoré pendant 1 s, puis le mouvement reprend
    envois = faire_tourner(pont, h, 1.5, cmd_vel=(0.3, 0, 0))
    mouvement = [t for t, e in envois if not est_nulle(vitesses(e))]
    assert mouvement and min(mouvement) >= t_stop + 1.0 - 1e-9
    assert min(mouvement) <= t_stop + 1.0 + 0.06
    assert conforme(pont)['etat'] == 'en_mouvement'


def test_guide_stop_au_repos_envoie_aussi_un_arret():
    pont, h = pret()
    assert len(pont.sur_guide_stop()) == 1


# ---------------------------------------------------------------- verrou /pont/arret

def test_verrou_trois_arrets_en_0_2_s_puis_immobile():
    pont, h = pret()
    faire_tourner(pont, h, 1.0, cmd_vel=(0.3, 0, 0))
    t0 = h.t
    premiers = [(h.t, e) for e in pont.sur_verrou(True)]
    envois = premiers + faire_tourner(pont, h, 3.0, cmd_vel=(0.3, 0, 0))
    assert all(vitesses(e) == (0.0, 0.0, 0.0) for _, e in envois)
    assert len(envois) == 3
    assert envois[-1][0] - t0 <= 0.2 + 0.021
    etat = conforme(pont)
    assert etat['etat'] == 'arret_verrouille' and etat['verrou'] and not etat['mouvement_permis']


def test_deverrouillage_reprise_seulement_avec_un_cmd_vel_neuf():
    pont, h = pret()
    faire_tourner(pont, h, 0.5, cmd_vel=(0.3, 0, 0))
    pont.sur_verrou(True)
    faire_tourner(pont, h, 1.0, cmd_vel=(0.3, 0, 0))
    assert pont.sur_verrou(False) == []
    # Pas de reprise sans /cmd_vel reçu après le déverrouillage
    assert faire_tourner(pont, h, 1.0) == []
    assert conforme(pont)['etat'] == 'pret'
    envois = faire_tourner(pont, h, 0.3, cmd_vel=(0.2, 0, 0))
    assert envois and vitesses(envois[0][1]) == (0.2, 0.0, 0.0)


def test_verrou_prioritaire_sur_tout():
    pont, h = nouveau()
    pont.demarrer()
    pont.sur_verrou(True)
    h.avancer(2.0)          # muet, non repéré : le verrou passe quand même avant
    assert conforme(pont)['etat'] == 'arret_verrouille'


# ---------------------------------------------------------------- maître des mouvements (vague 4)

def test_pilotage_arrete_le_robot_et_ignore_cmd_vel():
    pont, h = pret()
    faire_tourner(pont, h, 0.5, cmd_vel=(0.3, 0, 0))
    (arret,) = pont.sur_maitre('pilotage')
    assert vitesses(arret) == (0.0, 0.0, 0.0) and arret.duree == 1.0
    pont.sur_reponse(arret.identifiant, 0)
    assert faire_tourner(pont, h, 2.0, cmd_vel=(0.3, 0, 0)) == []        # /cmd_vel ignoré
    etat = conforme(pont)
    assert etat['etat'] == 'pilotage' and not etat['mouvement_permis']
    assert pont.maitre == 'pilotage'
    assert 'onglet Pilotage' in etat['message']


def test_pilotage_au_repos_n_envoie_rien():
    pont, h = pret()
    assert pont.sur_maitre('pilotage') == [] and conforme(pont)['etat'] == 'pilotage'
    assert pont.sur_maitre('pilotage') == []


def test_main_rendue_reprise_seulement_avec_un_cmd_vel_neuf():
    pont, h = pret()
    faire_tourner(pont, h, 0.5, cmd_vel=(0.3, 0, 0))
    (arret,) = pont.sur_maitre('pilotage')
    pont.sur_reponse(arret.identifiant, 0)
    faire_tourner(pont, h, 0.5, cmd_vel=(0.3, 0, 0))
    assert pont.sur_maitre('guide') == []
    assert faire_tourner(pont, h, 1.0) == [] and conforme(pont)['etat'] == 'pret'
    envois = faire_tourner(pont, h, 0.3, cmd_vel=(0.2, 0, 0))
    assert envois and vitesses(envois[0][1]) == (0.2, 0.0, 0.0)


def test_verrou_et_robot_muet_passent_avant_le_pilotage():
    pont, h = pret()
    pont.sur_maitre('pilotage')
    pont.sur_verrou(True)
    assert conforme(pont)['etat'] == 'arret_verrouille'
    pont.sur_verrou(False)
    assert conforme(pont)['etat'] == 'pilotage'
    pont.sur_guide_stop()                              # l'arrêt reste toujours permis
    h.avancer(1.5)
    assert conforme(pont)['etat'] == 'robot_muet'       # l'arrêt n'a pas eu de réponse


def test_maitre_inconnu_refuse():
    pont, h = pret()
    with pytest.raises(ValueError, match='guide ou pilotage'):
        pont.sur_maitre('robot')
    assert pont.maitre == 'guide'


# ---------------------------------------------------------------- repérage exigé

def test_sans_reperage_cmd_vel_ignore():
    pont, h = nouveau()
    (arret,) = pont.demarrer()
    pont.sur_reponse(arret.identifiant, 0)
    envois = faire_tourner(pont, h, 2.0, cmd_vel=(0.3, 0, 0), reperage=None)
    assert envois == []
    etat = conforme(pont)
    assert etat['etat'] == 'attente_reperage' and not etat['mouvement_permis']
    assert 'Repérer le robot' in etat['message']


def test_reperage_faux_cmd_vel_ignore():
    pont, h = nouveau()
    (arret,) = pont.demarrer()
    pont.sur_reponse(arret.identifiant, 0)
    assert faire_tourner(pont, h, 2.0, cmd_vel=(0.3, 0, 0), reperage=False) == []
    assert conforme(pont)['etat'] == 'attente_reperage'


def test_reperage_perdu_en_marche_arret_tout_de_suite():
    pont, h = pret()
    faire_tourner(pont, h, 1.0, cmd_vel=(0.3, 0, 0))
    (arret,) = pont.sur_reperage(False)
    assert vitesses(arret) == (0.0, 0.0, 0.0) and arret.raison == 'reperage'
    assert faire_tourner(pont, h, 1.0, cmd_vel=(0.3, 0, 0), reperage=False) == []
    assert conforme(pont)['etat'] == 'attente_reperage'


def test_reperage_muet_depuis_1_s_arret():
    """Plus de /reperage/etat : au bout de 1 s, le mouvement cesse (état attente_reperage)."""
    pont, h = pret()
    faire_tourner(pont, h, 0.5, cmd_vel=(0.3, 0, 0))
    t_dernier = pont.t_reperage
    envois = faire_tourner(pont, h, 1.5, cmd_vel=(0.3, 0, 0), reperage=None)
    arrets = [(t, e) for t, e in envois if est_nulle(vitesses(e))]
    assert arrets and arrets[0][1].raison == 'reperage'
    assert 1.0 <= arrets[0][0] - t_dernier <= 1.0 + 0.021
    assert all(t <= arrets[0][0] for t, e in envois if not est_nulle(vitesses(e)))
    etat = conforme(pont)
    assert etat['etat'] == 'attente_reperage' and not etat['reperage']
    assert 'plus de nouvelles' in etat['message']


def test_exiger_reperage_faux_pour_le_portique():
    pont, h = nouveau(exiger_reperage=False)
    (arret,) = pont.demarrer()
    pont.sur_reponse(arret.identifiant, 0)
    envois = faire_tourner(pont, h, 1.0, cmd_vel=(0.2, 0, 0), reperage=None)
    assert any(not est_nulle(vitesses(e)) for _, e in envois)
    etat = conforme(pont)
    assert etat['etat'] == 'en_mouvement' and not etat['exiger_reperage']


# ---------------------------------------------------------------- robot muet et refus

def test_robot_muet_apres_1_s_sans_reponse_puis_retour():
    pont, h = pret()
    faire_tourner(pont, h, 0.5, cmd_vel=(0.3, 0, 0))
    envois = faire_tourner(pont, h, 0.95, cmd_vel=(0.3, 0, 0), repondre=False)
    assert conforme(pont)['etat'] == 'en_mouvement'
    envois += faire_tourner(pont, h, 0.1, cmd_vel=(0.3, 0, 0), repondre=False)
    etat = conforme(pont)
    assert etat['etat'] == 'robot_muet' and etat['mouvement_permis']
    # Le pont continue d'envoyer la consigne fraîche
    envois += faire_tourner(pont, h, 1.0, cmd_vel=(0.3, 0, 0), repondre=False)
    assert sum(1 for _, e in envois if not est_nulle(vitesses(e))) >= 19
    # Une réponse : retour à la normale
    faire_tourner(pont, h, 0.2, cmd_vel=(0.3, 0, 0))
    assert conforme(pont)['etat'] == 'en_mouvement'


def test_robot_muet_au_repos_ne_relance_rien():
    pont, h = pret()
    faire_tourner(pont, h, 0.5, cmd_vel=(0.3, 0, 0), repondre=False)
    envois = faire_tourner(pont, h, 3.0, repondre=False)
    arrets = [e for _, e in envois if est_nulle(vitesses(e))]
    assert [e.raison for e in arrets] == ['delai_cmd_vel']      # puis plus rien
    assert envois[-1][1] is arrets[0]
    assert conforme(pont)['etat'] == 'robot_muet'
    # Retour du robot : rien ne repart sans /cmd_vel frais
    assert faire_tourner(pont, h, 1.0) == []


def test_reponses_des_autres_clients_ignorees():
    pont, h = pret()
    assert not pont.sur_reponse(42, 0)
    assert not pont.sur_reponse(42, 7301)
    etat = conforme(pont)
    assert etat['code'] == 0 and etat['reponses'] == 1


def test_une_seule_reponse_comptee_par_requete():
    pont, h = nouveau()
    (arret,) = pont.demarrer()
    assert pont.sur_reponse(arret.identifiant, 0)
    assert not pont.sur_reponse(arret.identifiant, 0)
    assert conforme(pont)['reponses'] == 1


def test_refus_avec_code_et_message():
    pont, h = pret()
    (e,) = pont.sur_cmd_vel(0.3, 0, 0)
    pont.sur_reponse(e.identifiant, 7301)
    etat = conforme(pont)
    assert etat['etat'] == 'refus' and etat['code'] == 7301
    assert etat['message'] == ('Le robot refuse de marcher (code 7301) : mettez-le en mode '
                               'marche avec la télécommande.')
    # Une réponse acceptée efface le refus
    faire_tourner(pont, h, 0.3, cmd_vel=(0.3, 0, 0))
    assert conforme(pont)['etat'] == 'en_mouvement'


def test_message_refus_inconnu():
    assert '(code 1234)' in message_refus(1234) and 'télécommande' in message_refus(1234)


# ---------------------------------------------------------------- tout ensemble

def test_etats_toujours_conformes_au_hasard():
    """Suite d'entrées tirées au hasard : jamais au-delà des plafonds, état toujours conforme."""
    import random
    aleatoire = random.Random(7)
    pont, h = nouveau()
    envois = [(h.t, e) for e in pont.demarrer()]
    for _ in range(3000):
        choix = aleatoire.random()
        if choix < 0.5:
            v = [aleatoire.choice([aleatoire.uniform(-3, 3), math.nan, 1e9, 0.0])
                 for _ in range(3)]
            envois += [(h.t, e) for e in pont.sur_cmd_vel(*v)]
        elif choix < 0.6:
            envois += [(h.t, e) for e in pont.sur_reperage(aleatoire.random() < 0.8)]
        elif choix < 0.63:
            envois += [(h.t, e) for e in pont.sur_guide_stop()]
        elif choix < 0.66:
            envois += [(h.t, e) for e in pont.sur_verrou(aleatoire.random() < 0.5)]
        elif choix < 0.68:
            envois += [(h.t, e) for e in pont.sur_maitre(aleatoire.choice(['guide', 'pilotage']))]
        envois += [(h.t, e) for e in pont.pas()]
        for _, e in envois[-3:]:
            if aleatoire.random() < 0.9:
                pont.sur_reponse(e.identifiant, aleatoire.choice([0, 0, 0, 7301]))
        conforme(pont)
        h.avancer(aleatoire.uniform(0.0, 0.05))
    for _, e in envois:
        assert abs(e.vx) <= 0.4 and abs(e.vy) <= 0.25 and abs(e.wz) <= 0.6
        assert all(math.isfinite(v) for v in vitesses(e))
        assert e.duree == (1.0 if est_nulle(vitesses(e)) else 0.5)
