"""
Caméra de la tête (section 11.13 du plan).

Une demande à la fois au service videohub, au plus 5 par seconde, la dernière image partagée ;
réponses refusées, illisibles, perdues ou absentes.
"""
import threading

from g1_pilotage.camera import API_IMAGE, Camera
from g1_pilotage.coeur import Coeur
from g1_pilotage.logique import Envoi, Pilotage

JPEG = b'\xff\xd8\xff\xe0' + b'\x00' * 32 + b'\xff\xd9'


class Horloge:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_une_demande_a_la_fois_et_cinq_par_seconde_au_plus():
    h = Horloge()
    c = Camera(h, ecart_min_s=0.2, delai_s=1.0)
    assert c.derniere() is None
    assert c.demander(1) and c.en_attente()
    assert not c.demander(2)                       # la première attend encore sa réponse
    assert not c.sur_reponse(2, 0, JPEG)           # pas la nôtre
    h.t += 0.05
    assert c.sur_reponse(1, 0, JPEG)
    image, age, numero = c.derniere()
    assert image == JPEG and age == 0.0 and numero == 1
    h.t += 0.1
    assert not c.demander(3)                       # image de 0,1 s : on la garde
    h.t += 0.1
    assert c.demander(4)
    assert c.etat()['demandes'] == 2 and c.etat()['images'] == 1


def test_refus_image_illisible_et_silence():
    h = Horloge()
    c = Camera(h, ecart_min_s=0.2, delai_s=1.0)
    c.demander(1)
    c.sur_reponse(1, 3203, b'')
    assert 'code 3203' in c.erreur and c.derniere() is None
    h.t += 0.3
    c.demander(2)
    c.sur_reponse(2, 0, b'<html>')
    assert 'JPEG' in c.erreur
    h.t += 0.3
    assert c.demander(3)
    h.t += 1.5                                     # aucune réponse
    c.expirer()
    assert 'videohub' in c.erreur and not c.en_attente()
    assert c.demander(4)


def test_coeur_publie_une_demande_videohub_et_rend_l_image():
    publiees = []
    coeur = Coeur(Pilotage())

    def publier(sorties):
        for s in sorties:
            assert isinstance(s, Envoi)
            publiees.append(s)
            # le robot répond depuis un autre fil, comme le nœud ROS
            threading.Timer(0.05, coeur.sur_image, (s.identifiant, 0, JPEG)).start()

    coeur.publier = publier
    (image, age, numero), erreur = coeur.image_camera()
    assert image == JPEG and numero == 1 and erreur is None
    assert [(s.service, s.api_id, s.parametre, s.raison) for s in publiees] == [
        ('videohub', API_IMAGE, '', 'camera')]
    # tout de suite après : la même image, sans nouvelle demande au robot
    (image, _, numero), _ = coeur.image_camera()
    assert numero == 1 and len(publiees) == 1


def test_coeur_sans_reponse_rend_une_erreur():
    coeur = Coeur(Pilotage(), lambda sorties: None)
    coeur.camera.delai_s = 0.2
    derniere, erreur = coeur.image_camera()
    assert derniere is None and 'videohub' in erreur


def test_la_camera_ne_compte_pas_comme_une_reponse_du_robot():
    coeur = Coeur(Pilotage(), lambda sorties: None)
    assert not coeur.sur_image(12345, 0, JPEG)     # jamais demandée
    assert coeur.etat()['robot_repond'] is False
