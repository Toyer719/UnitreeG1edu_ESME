"""Logique du faux G1, sans ROS : service sport (7105, refus, pannes), odométrie qui dérive."""
import json
import math

import pytest

from g1_jumeau.logique import (angle_normal, CODE_API_INCONNUE, CODE_PARAMETRES, CODE_REFUS,
                               FauxSport, lire_set_velocity, OdometrieDerivee)


class Horloge:
    def __init__(self, t=50.0):
        self.t = t

    def __call__(self):
        return self.t


def parametre(vx, vy, wz, d):
    return json.dumps({'velocity': [vx, vy, wz], 'duration': d})


def test_7105_appliquee_pendant_duration_puis_zero():
    h = Horloge()
    sport = FauxSport(horloge=h)
    assert sport.traiter(7105, parametre(0.3, -0.1, 0.2, 0.5)) == 0
    assert sport.consigne() == (0.3, -0.1, 0.2)
    h.t += 0.49
    assert sport.consigne() == (0.3, -0.1, 0.2) and sport.reste() == pytest.approx(0.01)
    h.t += 0.02
    assert sport.consigne() == (0.0, 0.0, 0.0) and sport.reste() == 0.0
    assert (sport.requetes, sport.appliquees, sport.reponses) == (1, 1, 1)


def test_nouvelle_consigne_remplace_l_ancienne():
    h = Horloge()
    sport = FauxSport(horloge=h)
    sport.traiter(7105, parametre(0.3, 0, 0, 0.5))
    h.t += 0.1
    sport.traiter(7105, parametre(0.0, 0.0, 0.0, 1.0))      # arrêt (StopMove)
    assert sport.consigne() == (0.0, 0.0, 0.0)
    assert sport.reste() == pytest.approx(1.0)


def test_pas_de_plafond_au_faux_g1():
    """Le vrai robot a ses plafonds, plus hauts que ceux du pont : le faux G1 n'en a pas."""
    sport = FauxSport(horloge=Horloge())
    sport.traiter(7105, parametre(1.5, 0.8, 3.0, 864000.0))     # Move continu du SDK C++
    assert sport.consigne() == (1.5, 0.8, 3.0)


def test_format_du_client_cpp_accepte():
    """Le client C++ (nlohmann) trie les clés et écrit les float en double : lu aussi."""
    texte = '{"duration":0.5,"velocity":[0.30000001192092896,0.0,0.10000000149011612]}'
    assert lire_set_velocity(texte) == pytest.approx((0.3, 0.0, 0.1, 0.5), abs=1e-6)
    assert lire_set_velocity('{"velocity": [0, 0, 0], "duration": 1}') == (0.0, 0.0, 0.0, 1.0)


@pytest.mark.parametrize('texte', [
    '', 'pas du json', '[]', '{"velocity": [0.1, 0.2]}', '{"velocity": [0.1, 0, 0]}',
    '{"velocity": [0.1, "a", 0], "duration": 0.5}', '{"velocity": [NaN, 0, 0], "duration": 0.5}',
    '{"velocity": [0.1, 0, 0], "duration": -1}', '{"velocity": [true, 0, 0], "duration": 0.5}',
    '{"velocity": [0.1, 0, 0], "duration": Infinity}'])
def test_parametres_illisibles_3204(texte):
    sport = FauxSport(horloge=Horloge())
    assert sport.traiter(7105, texte) == CODE_PARAMETRES == 3204
    assert sport.consigne() == (0.0, 0.0, 0.0) and sport.appliquees == 0


def test_api_inconnue_3203():
    sport = FauxSport(horloge=Horloge())
    assert sport.traiter(7001, '{}') == CODE_API_INCONNUE == 3203
    assert sport.traiter(1804, parametre(0.3, 0, 0, 0.5)) == 3203
    assert sport.consigne() == (0.0, 0.0, 0.0)


def test_panne_muet_ne_repond_pas_et_laisse_expirer():
    h = Horloge()
    sport = FauxSport(horloge=h)
    sport.traiter(7105, parametre(0.3, 0, 0, 0.5))
    sport.changer_panne('muet')
    assert sport.traiter(7105, parametre(0.4, 0, 0, 0.5)) is None     # ni réponse, ni effet
    assert sport.consigne() == (0.3, 0.0, 0.0)                         # la consigne en cours
    h.t += 0.6
    assert sport.consigne() == (0.0, 0.0, 0.0)                         # expire normalement
    assert (sport.requetes, sport.reponses, sport.appliquees) == (2, 1, 1)
    sport.changer_panne('aucune')
    assert sport.traiter(7105, parametre(0.2, 0, 0, 0.5)) == 0


def test_panne_refus_7301_sans_bouger():
    h = Horloge()
    sport = FauxSport(horloge=h)
    sport.traiter(7105, parametre(0.3, 0, 0, 0.5))
    sport.changer_panne('refus')
    assert sport.consigne() == (0.0, 0.0, 0.0)                         # zéro tout de suite
    assert sport.traiter(7105, parametre(0.3, 0, 0, 0.5)) == CODE_REFUS == 7301
    assert sport.consigne() == (0.0, 0.0, 0.0)


def test_panne_inconnue_refusee():
    with pytest.raises(ValueError, match='aucune, muet, refus'):
        FauxSport().changer_panne('explosion')


# ---------------------------------------------------------------- odométrie qui dérive

def trajet(odometrie, points):
    pose = None
    for p in points:
        pose = odometrie.mettre_a_jour(*p)
    return pose


def test_origine_a_la_pose_du_lancement():
    o = OdometrieDerivee()
    assert o.mettre_a_jour(2.5, 10.0, 0.7) == (0.0, 0.0, 0.0)


def test_ligne_droite_2_pourcent_trop_longue_et_lacet():
    """2 m tout droit (en 200 pas) : 2,04 m comptés, 0,02 rad de lacet en plus."""
    o = OdometrieDerivee()
    pose = trajet(o, [(2.5 + 0.01 * i, 10.0, 0.0) for i in range(201)])
    assert o.parcouru == pytest.approx(2.0)
    x, y, theta = pose
    assert theta == pytest.approx(0.02, abs=1e-9)
    assert math.hypot(x, y) == pytest.approx(2.04, abs=1e-3)
    # Le lacet ajouté courbe la trajectoire vers la gauche
    assert 0 < y < 0.03


def test_dans_le_repere_du_depart():
    """Départ tourné de 90° : l'odométrie part quand même vers son x à elle."""
    o = OdometrieDerivee(echelle=0.0, lacet_par_m=0.0)
    x, y, theta = trajet(o, [(1.0, 1.0 + 0.01 * i, math.pi / 2) for i in range(101)])
    assert (x, y, theta) == pytest.approx((1.0, 0.0, 0.0), abs=1e-9)


def test_rotation_sur_place_sans_derive():
    o = OdometrieDerivee()
    pose = trajet(o, [(3.0, 4.0, angle_normal(0.05 * i)) for i in range(64)])
    assert pose[:2] == pytest.approx((0.0, 0.0), abs=1e-12)
    assert pose[2] == pytest.approx(angle_normal(0.05 * 63), abs=1e-9)


def test_pas_de_cote():
    o = OdometrieDerivee()
    x, y, theta = trajet(o, [(0.0, -0.01 * i, 0.0) for i in range(101)])      # 1 m à droite
    assert math.hypot(x, y) == pytest.approx(1.02, abs=1e-3) and y < 0
    assert theta == pytest.approx(0.01, abs=1e-9)


def test_derive_parametrable():
    o = OdometrieDerivee(echelle=0.0, lacet_par_m=0.0)
    pose = trajet(o, [(0.01 * i, 0.0, 0.0) for i in range(301)])
    assert pose == pytest.approx((3.0, 0.0, 0.0), abs=1e-9)


def test_valeurs_du_contrat():
    lieu = pytest.importorskip('atelier.lieu')
    o = OdometrieDerivee()
    assert (o.echelle, o.lacet_par_m) == (lieu.DERIVE_ECHELLE, lieu.DERIVE_LACET_PAR_M)


# ---------------------------------------------------------------- vague 5 : seuil de marche

@pytest.mark.parametrize('consigne,faite', [
    ((0.1, 0.0, 0.0), (0.0, 0.0, 0.0)),            # le 27/10 : 0,1 m/s, aucun pas
    ((0.2, 0.0, 0.0), (0.2, 0.0, 0.0)),            # 0,2 m/s : il marche
    ((0.1, 0.1, 0.0), (0.0, 0.0, 0.0)),            # norme 0,14 : sous 0,15
    ((0.12, 0.1, 0.05), (0.12, 0.1, 0.05)),        # norme 0,156 : tout est appliqué
    ((0.1, 0.0, 0.3), (0.0, 0.0, 0.3)),            # trop lent pour avancer : il tourne
    ((0.0, 0.0, 0.15), (0.0, 0.0, 0.0)),           # rotation sous 0,2 : rien
    ((0.0, 0.0, -0.3), (0.0, 0.0, -0.3)),
    ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))])
def test_seuil_de_marche(consigne, faite):
    h = Horloge()
    sport = FauxSport(horloge=h, seuil_lin=0.15, seuil_rot=0.2)
    assert sport.traiter(7105, parametre(*consigne, 0.5)) == 0          # toujours accepté
    assert sport.consigne() == pytest.approx(faite)
    assert sport.appliquees == 1
    assert sport.sous_seuil == (1 if faite != consigne else 0)


def test_sans_seuil_par_defaut():
    sport = FauxSport(horloge=Horloge())
    assert (sport.seuil_lin, sport.seuil_rot) == (0.0, 0.0)
    sport.traiter(7105, parametre(0.01, 0.0, 0.01, 0.5))
    assert sport.consigne() == (0.01, 0.0, 0.01)


@pytest.mark.parametrize('seuils', [(-0.1, 0.2), (0.15, math.nan), (2.0, 0.2), (True, 0.2),
                                    ('0.15', 0.2)])
def test_seuils_absurdes_refuses(seuils):
    with pytest.raises(ValueError):
        FauxSport(horloge=Horloge(), seuil_lin=seuils[0], seuil_rot=seuils[1])
