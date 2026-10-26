"""Mouvement des piétons crédibles (atelier.monde.foule), sans ROS ni Gazebo.

On intègre nous-mêmes les vitesses rendues (le corps va exactement où on le pousse) : horaire suivi,
réaction au robot (aucune, arret, ecart), consigne d'un piéton piloté, murs, /pietons/etat conforme.
"""
import json
import math

import pytest

from atelier import RACINE
from atelier.lieu import Monde, Pieton, charger_monde, valider_message
from atelier.lieu.passants import RAYON_ROBOT_CONTACT
from atelier.monde.foule import (ATTENTE_ROBOT_MAX_S, ECART_MAX_M, MARGE_PASSAGE_M, CarteLibre, Foule, Passant,
                                 lire_consigne, vitesse_dans_la_carte, vitesse_dans_le_corps)

DT = 0.05


@pytest.fixture(scope="module")
def monde_demo():
    return charger_monde(RACINE / "lieux" / "demo", "rdc")


@pytest.fixture(scope="module")
def carte(monde_demo):
    return CarteLibre(monde_demo)


def couloir():
    """Couloir de 12 × 3 m (murs en y = ±1,5), sans piéton."""
    return Monde.depuis_dict({
        "version": 1, "emprise": {"min": [-0.5, -2.0], "max": [12.5, 2.0]},
        "murs": [{"id": "sud", "de": [0, -1.5], "a": [12, -1.5], "epaisseur": 0.15, "hauteur": 2.5},
                 {"id": "nord", "de": [0, 1.5], "a": [12, 1.5], "epaisseur": 0.15, "hauteur": 2.5}],
        "depart_robot": {"x": 1.0, "y": 0.0, "theta": 0.0}})


def rouler(passant, robot, duree, v_robot=(0.0, 0.0), t0=0.0):
    """Intègre le piéton (et le robot, à vitesse constante) ; renvoie (états vus, distance bord min, positions)."""
    position = passant.cible
    robot = list(robot)
    etats, dmin, trace = [], math.inf, []
    t = t0
    for _ in range(int(round(duree / DT))):
        t += DT
        c = passant.pas(t, DT, position, (robot[0], robot[1], v_robot[0], v_robot[1]))
        position = (position[0] + c.vx * DT, position[1] + c.vy * DT)
        robot[0] += v_robot[0] * DT
        robot[1] += v_robot[1] * DT
        dmin = min(dmin, math.dist(position, robot) - RAYON_ROBOT_CONTACT - passant.rayon)
        if not etats or etats[-1] != c.etat:
            etats.append(c.etat)
        trace.append(position)
    return etats, dmin, trace


def test_carte_libre(carte):
    assert carte.libre(2.5, 10.0, 0.3)                 # accueil
    assert not carte.libre(12.0, 14.5, 0.1)            # mur nord du couloir nord
    assert carte.libre(12.0, 11.9, 0.25)               # 1,18 m libre à côté du passant immobile
    assert not carte.libre(12.0, 11.7, 0.25)
    assert not carte.libre(-5.0, 10.0, 0.25)           # hors de l'emprise


def test_sans_robot_il_suit_son_horaire():
    p = Pieton("h", [(1.0, 0.0), (9.0, 0.0)], 1.0, True)
    passant = Passant(p, CarteLibre(couloir()))
    etats, _, trace = rouler(passant, (100.0, 100.0), 4.0)
    assert etats == ["marche"]
    assert trace[-1] == pytest.approx((5.0, 0.0), abs=0.05)


def test_il_rattrape_sa_position_apres_une_poussee():
    p = Pieton("h", [(1.0, 0.0), (9.0, 0.0)], 1.0, True)
    passant = Passant(p, CarteLibre(couloir()))
    c = passant.pas(0.05, DT, (1.05, 0.4), None)       # le robot l'a poussé de 0,4 m sur le côté
    assert c.vy < -0.5 and c.vx > 0.8


@pytest.mark.parametrize("reaction", ["aucune", "arret", "ecart"])
def test_reaction_au_robot_qui_arrive_en_face(reaction):
    p = Pieton("h", [(10.0, 0.0), (1.0, 0.0)], 1.0, False, reaction=reaction, repeter=False)
    passant = Passant(p, CarteLibre(couloir()))
    etats, dmin, trace = rouler(passant, (3.0, 0.0), 26.0)       # robot arrêté sur sa ligne
    if reaction == "aucune":
        assert "arret" not in etats and "ecart" not in etats and dmin < 0      # il fonce dedans
    elif reaction == "arret":
        assert "arret" in etats and "ecart" not in etats
        assert 0.0 < dmin < passant.reglages["distance_reaction_m"] + 0.06
    else:
        # robot arrêté droit devant : 0,6 m d'écart ne laisse que 0,09 m pour passer ; il s'écarte et
        # attend ATTENTE_ROBOT_MAX_S, loin du robot, puis passe quand même (le robot ne bouge pas)
        assert "ecart" in etats and dmin > 0.0
        assert max(abs(y) for _, y in trace) <= ECART_MAX_M + 0.02
        assert trace[-1] == pytest.approx((1.0, 0.0), abs=0.1)            # revenu sur son trajet, arrivé
        attente = [i for i in range(1, len(trace)) if abs(trace[i][0] - trace[i - 1][0]) < 0.01 * DT
                   and trace[i][0] > 3.5]
        assert len(attente) * DT == pytest.approx(ATTENTE_ROBOT_MAX_S, abs=1.0)


def test_ecart_attend_puis_passe_quand_le_robot_s_ecarte():
    p = Pieton("h", [(10.0, 0.0), (1.0, 0.0)], 1.0, False, reaction="ecart", repeter=False)
    passant = Passant(p, CarteLibre(couloir()))
    etats, dmin, trace = rouler(passant, (3.0, 0.0), 10.0)          # il attend devant le robot arrêté
    assert etats[-1] == "ecart" and dmin > 0.5
    attente = trace[-1]
    assert abs(trace[-1][0] - trace[-20][0]) < 0.02                  # il n'avance plus
    # le robot s'écarte vers le sud (0,8 m en 2 s), puis ne bouge plus : la place est libre
    etats2, dmin2, trace2 = rouler(passant, (3.0, 0.0), 2.0, v_robot=(0.0, -0.4), t0=10.0)
    etats3, dmin3, trace3 = rouler(passant, (3.0, -0.8), 14.0, t0=12.0)
    assert min(dmin2, dmin3) > MARGE_PASSAGE_M - 0.02
    assert trace3[-1] == pytest.approx((1.0, 0.0), abs=0.1)           # revenu sur son trajet, arrivé
    assert attente[0] > trace3[-1][0] + 3.0


def test_ecart_suffisant_il_passe_sans_attendre():
    # robot arrêté 0,2 m au sud de sa ligne : 0,6 + 0,2 − 0,51 = 0,29 m pour passer, il ne s'arrête pas
    p = Pieton("h", [(10.0, 0.0), (1.0, 0.0)], 1.0, False, reaction="ecart", repeter=False)
    passant = Passant(p, CarteLibre(couloir()))
    etats, dmin, trace = rouler(passant, (5.0, -0.2), 14.0)
    assert "ecart" in etats and dmin > MARGE_PASSAGE_M
    assert trace[-1] == pytest.approx((1.0, 0.0), abs=0.1)


def test_ecart_du_cote_oppose_au_robot():
    p = Pieton("h", [(10.0, 0.0), (1.0, 0.0)], 1.0, False, reaction="ecart", repeter=False)
    # le piéton marche vers l'ouest ; robot un peu au sud de sa ligne (à sa gauche) : il passe au nord
    passant = Passant(p, CarteLibre(couloir()))
    _, _, trace = rouler(passant, (6.0, -0.2), 4.0)
    assert max(y for _, y in trace) > 0.3 and min(y for _, y in trace) > -0.05


def test_pas_de_reaction_au_robot_derriere():
    p = Pieton("h", [(5.0, 0.0), (11.0, 0.0)], 1.0, False, reaction="arret", repeter=False)
    passant = Passant(p, CarteLibre(couloir()))
    etats, _, _ = rouler(passant, (4.3, 0.0), 2.0, v_robot=(1.0, 0.0))  # le robot le suit de près
    assert etats == ["marche"]


def test_ecart_impossible_contre_un_mur_il_s_arrete():
    # piéton qui longe le mur nord (y = 1,15) ; le robot vient du sud-ouest, à sa droite : il voudrait
    # s'écarter vers le nord, dans le mur
    p = Pieton("h", [(10.0, 1.15), (1.0, 1.15)], 1.0, False, reaction="ecart", repeter=False)
    passant = Passant(p, CarteLibre(couloir()))
    etats, _, trace = rouler(passant, (6.5, 0.85), 5.0)
    assert "arret" in etats
    assert max(y for _, y in trace) < 1.2


def test_pause_et_ecart_sur_place(carte):
    # passant debout en pause au milieu du couloir nord, qui s'écarte quand le robot arrive devant lui
    p = Pieton("passant", [(12.0, 13.0), (12.5, 13.0)], 1.0, True, reaction="ecart",
               pauses=[{"point": 0, "duree_s": 3600}])
    passant = Passant(p, carte)
    etats, dmin, trace = rouler(passant, (13.2, 13.0), 3.0)
    assert etats[0] == "ecart" and dmin > 0.0
    assert abs(trace[-1][1] - 13.0) == pytest.approx(ECART_MAX_M, abs=0.02)


def test_pilote_externe_consigne_valable_0_5_s_et_murs():
    p = Pieton("visiteur", [(1.0, 0.0), (1.5, 0.0)], 1.0, True, pilote="externe")
    passant = Passant(p, CarteLibre(couloir()))
    assert passant.pas(0.0, DT, (1.0, 0.0)).etat == "pilote"
    passant.consigner(3.0, 0.0, None, 0.0)                    # plafonnée à 1,5 m/s
    c = passant.pas(0.1, DT, (1.0, 0.0))
    assert (c.vx, c.vy) == pytest.approx((1.5, 0.0)) and c.theta == pytest.approx(0.0)
    assert passant.pas(0.6, DT, (1.6, 0.0)).vx == 0.0          # plus de consigne depuis 0,5 s
    passant.consigner(0.0, 1.0, 1.0, 1.0)
    assert passant.pas(1.1, DT, (2.0, 0.0)).vy == pytest.approx(1.0)
    assert passant.pas(1.2, DT, (2.0, 1.1)).vy == 0.0          # il s'arrête devant le mur nord
    assert passant.theta == 1.0


def test_foule_message_etat_conforme(monde_demo):
    m = Monde.depuis_dict(monde_demo.vers_dict())
    m.pietons.append(Pieton("acteur", [(26.5, 6.5), (26.5, 13.5)], 0.7, True, corps=False))
    m.pietons.append(Pieton("visiteur", [(3.0, 10.0), (3.5, 10.0)], 1.0, True, pilote="externe"))
    foule = Foule(m, carte=CarteLibre(monde_demo))
    assert set(foule.passants) == {"pieton_sud", "pieton_nord", "visiteur"}
    assert [a.id for a in foule.acteurs] == ["acteur"]
    commandes = foule.pas(0.05, DT, {}, None)
    assert set(commandes) == set(foule.passants)
    foule.consigner("visiteur", 0.2, 0.0, None, 0.05)
    with pytest.raises(ValueError, match="pilote: externe"):
        foule.consigner("pieton_sud", 0.2, 0.0, None, 0.05)
    with pytest.raises(ValueError, match="pas de piéton-corps"):
        foule.consigner("acteur", 0.2, 0.0, None, 0.05)
    message = foule.message_etat(12.0, 0.05, {"pieton_sud": (5.0, 7.8, 0.8, 0.0)})
    assert valider_message("pietons_etat", message) == []
    par_id = {p["id"]: p for p in message["pietons"]}
    assert par_id["pieton_sud"]["x"] == 5.0 and par_id["pieton_sud"]["corps"] is True
    assert par_id["acteur"]["corps"] is False and par_id["acteur"]["y"] == pytest.approx(13.5 - (0.7 * 12.0 - 7.0), abs=1e-3)
    assert par_id["visiteur"]["etat"] == "pilote"
    json.dumps(message)
    foule.reinitialiser()
    assert foule.passants["visiteur"].consigne is None


def test_lire_consigne():
    assert lire_consigne('{"id": "visiteur", "vx": 0.35, "vy": 0.0}') == ("visiteur", 0.35, 0.0, None)
    for faux, motif in (("pas du json", "JSON"), ('{"id": "v", "vx": 2.0, "vy": 0}', "1.5"),
                        ('{"id": "v", "vx": 0.1}', "vy")):
        with pytest.raises(ValueError, match=motif):
            lire_consigne(faux)


def test_vitesses_carte_et_corps():
    vx, vy = vitesse_dans_le_corps(1.0, 0.0, math.pi / 2)
    assert (vx, vy) == pytest.approx((0.0, -1.0))
    assert vitesse_dans_la_carte(vx, vy, math.pi / 2) == pytest.approx((1.0, 0.0))
