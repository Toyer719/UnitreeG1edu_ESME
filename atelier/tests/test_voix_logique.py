"""La logique du nœud voix, sans ROS et à fausse horloge (vague 6, section 13.6 du plan ; agent Voix).

File et priorités (normale attend, haute coupe, securite coupe et vide la file, taire), jamais deux flux en même
temps (1004 avant la phrase suivante), morceaux de PCM comme les exemples du SDK d'Unitree (96 000 octets au
plus, pairs, même stream_id, un par seconde au plus), sorties robot, borne et robot_tts, volume (1006, 1005), robot
muet, réponses d'autres programmes, réglages d'une phrase (message, personnalité, nœud), synthèse d'avance,
messages faux refusés sans exception, /voix/etat et /voix/son conformes à leurs schémas.
"""
import json
from datetime import datetime

import pytest

from atelier.lieu import voix as V
from atelier.lieu.validation import valider_donnees
from atelier.voix import logique as LV
from atelier.voix.logique import Annonce, LogiqueVoix, Requete, id_de_phrase
from atelier.voix.synthese import SyntheseFactice

SYNTHESE = SyntheseFactice()


class Horloge:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def mur():
    return datetime(2026, 11, 12, 14, 20, 31).astimezone()


class Banc:
    """La logique, sa fausse horloge, la synthèse faite tout de suite, et tout ce qui a été publié."""

    def __init__(self, sortie="robot", abonne=True, repondre=True, **reglages):
        self.h = Horloge()
        self.v = LogiqueVoix(sortie=sortie, horloge=self.h, mur=mur, **reglages)
        self.v.changer_abonnes(1 if abonne else 0)
        self.repondre = repondre
        self.requetes, self.annonces, self.etats = [], [], []
        self.recevoir(self.v.pas())

    def recevoir(self, sorties):
        for s in sorties:
            assert isinstance(s, (Requete, Annonce))
            if isinstance(s, Requete):
                assert s.api_id in V.APIS_NOEUD_VOIX, s
                assert V.erreurs_requete_voix(s.api_id, s.parametre, s.binaire) == [], s[:2]
                self.requetes.append((self.h.t, s))
                if self.repondre:
                    data = json.dumps({"volume": self.v.volume or 70}) if s.api_id == 1005 else ""
                    self.v.reponse(s.identifiant, 0, data)
            else:
                assert valider_donnees("son_voix", s.message) == [], s.message
                self.annonces.append((self.h.t, s.message))
        etat = self.v.etat()
        assert valider_donnees("etat_voix", etat) == [], etat
        self.etats.append(etat)
        return sorties

    def synthetiser(self):
        while True:
            travail = self.v.prochaine_synthese()
            if travail is None:
                return
            ident, texte, voix, vitesse, gain = travail
            self.v.son_pret(ident, (voix, vitesse, gain), SYNTHESE.synthetiser(texte, voix, vitesse, gain))

    def dire(self, texte, **champs):
        sorties = self.recevoir(self.v.dire(dict({"version": 1, "texte": texte, "source": "guide"}, **champs)))
        self.synthetiser()
        return sorties

    def avancer(self, secondes, pas=0.05):
        fin = self.h.t + secondes
        while self.h.t < fin - 1e-9:
            self.h.t = round(self.h.t + pas, 6)
            self.recevoir(self.v.pas())
            self.synthetiser()

    def apis(self, depuis=0):
        """api_id des requêtes publiées, à partir du rang « depuis »."""
        return [r.api_id for _, r in self.requetes[depuis:]]

    def lectures(self):
        return [(t, r) for t, r in self.requetes if r.api_id == 1003]

    def flux(self):
        """stream_id des 1003 dans l'ordre, sans répétition consécutive."""
        ordre = []
        for _, r in self.lectures():
            sid = json.loads(r.parametre)["stream_id"]
            if not ordre or ordre[-1] != sid:
                ordre.append(sid)
        return ordre


LONGUE = "Bonjour ! Je suis le robot d'accueil du lycée. Suivez-moi jusqu'à la salle demandée, s'il vous plaît."


def test_une_phrase_en_morceaux_comme_le_sdk():
    b = Banc(volume=60)
    assert b.apis() == [1006, 1005]                     # volume réglé, puis relu, dès que le robot écoute
    b.dire(LONGUE * 2)
    b.avancer(1.0)
    lectures = b.lectures()
    assert lectures, "aucun 1003"
    stream = {json.loads(r.parametre)["stream_id"] for _, r in lectures}
    assert len(stream) == 1
    b.avancer(30.0)
    lectures = b.lectures()
    tailles = [len(r.binaire) for _, r in lectures]
    assert all(0 < n <= V.TAILLE_MORCEAU_OCTETS and n % 2 == 0 for n in tailles)
    assert tailles[:-1] == [V.TAILLE_MORCEAU_OCTETS] * (len(tailles) - 1) and len(tailles) >= 2
    instants = [t for t, _ in lectures]
    assert all(b2 - a >= V.ECART_MORCEAUX_S - 1e-6 for a, b2 in zip(instants, instants[1:]))
    son = SYNTHESE.synthetiser(LONGUE * 2)
    assert sum(tailles) == len(son.pcm16)
    assert json.loads(lectures[0][1].parametre) == {"app_name": "atelier", "stream_id": lectures[0][1].phrase}
    assert b.v.dites == 1 and b.v.en_cours is None and b.v.erreurs == 0
    assert b.etats[-1]["robot"] == {"abonne": True, "repond": True, "age_reponse_s": b.etats[-1]["robot"][
        "age_reponse_s"], "attendues": 0}


def test_fin_de_phrase_estimee_par_la_duree_du_pcm():
    b = Banc()
    b.dire("Suivez-moi !")
    b.avancer(0.05)
    debut = b.lectures()[0][0]
    duree = SYNTHESE.synthetiser("Suivez-moi !").duree_pcm_s
    while b.v.en_cours is not None:
        b.avancer(0.05)
    assert b.h.t == pytest.approx(debut + duree + LV.MARGE_FIN_S, abs=0.06)


def test_trois_phrases_dans_l_ordre_jamais_deux_flux():
    b = Banc()
    for texte in ("Première phrase.", "Deuxième phrase un peu plus longue.", "Troisième."):
        b.dire(texte)
    assert b.v.etat()["file"] == 2 or b.v.en_cours is None
    b.avancer(25.0)
    assert b.v.dites == 3 and b.v.interrompues == 0
    textes = [h["texte"] for h in b.v.historique]
    assert textes == ["Première phrase.", "Deuxième phrase un peu plus longue.", "Troisième."]
    assert 1004 not in b.apis()
    # chaque phrase commence après la fin estimée de la précédente
    debuts = {}
    for t, r in b.lectures():
        debuts.setdefault(r.phrase, t)
    ordre = sorted(debuts.values())
    durees = [SYNTHESE.synthetiser(x).duree_pcm_s for x in ("Première phrase.", "Deuxième phrase un peu plus longue.")]
    assert ordre[1] - ordre[0] >= durees[0] and ordre[2] - ordre[1] >= durees[1]


def test_haute_coupe_la_phrase_en_cours_puis_la_file_reprend():
    b = Banc()
    b.dire(LONGUE)
    b.dire("Phrase qui attend.")
    b.avancer(1.0)
    coupee = b.v.en_cours.id
    rang = len(b.requetes)
    b.dire("Attention, je passe !", priorite="haute")
    b.avancer(0.5)
    apres = b.requetes[rang:]
    assert apres[0][1].api_id == 1004 and json.loads(apres[0][1].parametre) == {"app_name": "atelier"}
    premier_1003 = next(t for t, r in apres if r.api_id == 1003)
    assert premier_1003 - apres[0][0] >= LV.PAUSE_APRES_ARRET_S - 1e-6
    assert b.v.en_cours.texte == "Attention, je passe !"
    b.avancer(20.0)
    assert [h["texte"] for h in b.v.historique] == [LONGUE, "Attention, je passe !", "Phrase qui attend."]
    assert b.v.historique[0]["fin"] == "interrompue" and b.v.interrompues == 1
    assert b.flux()[0] == coupee


def test_securite_coupe_et_vide_la_file():
    b = Banc()
    b.dire(LONGUE)
    b.avancer(0.2)
    b.dire("En attente un.")
    b.dire("En attente deux.")
    b.avancer(1.0)
    rang = len(b.requetes)
    b.dire("Je fais une petite pause.", priorite="securite", source="accueil", id="pause-v3")
    b.avancer(10.0)
    apres = [r for _, r in b.requetes[rang:]]
    assert apres[0].api_id == 1004
    assert {r.phrase for r in apres if r.api_id == 1003} == {"pause-v3"}
    assert b.v.file == type(b.v.file)() and b.v.abandonnees == 2
    assert b.v.historique[-1]["id"] == "pause-v3" and b.v.historique[-1]["fin"] == "dite"


def test_haute_ne_coupe_pas_une_phrase_de_securite():
    b = Banc()
    b.dire("Message de sécurité important à écouter.", priorite="securite")
    b.avancer(0.5)
    b.dire("Phrase haute.", priorite="haute")
    b.avancer(0.5)
    assert 1004 not in b.apis() and b.v.en_cours.priorite == "securite"
    b.avancer(15.0)
    assert [h["texte"] for h in b.v.historique] == ["Message de sécurité important à écouter.", "Phrase haute."]


def test_securite_coupe_une_securite():
    b = Banc()
    b.dire(LONGUE, priorite="securite")
    b.avancer(0.5)
    b.dire("Nouvelle alerte.", priorite="securite")
    b.avancer(5.0)
    assert 1004 in b.apis() and b.v.historique[0]["fin"] == "interrompue"


def test_taire_coupe_et_vide_la_file():
    b = Banc()
    b.dire(LONGUE)
    b.dire("Après.")
    b.avancer(1.0)
    rang = len(b.requetes)
    b.recevoir(b.v.commande({"version": 1, "action": "taire"}))
    b.avancer(5.0)
    assert b.apis(rang) == [1004] and b.v.en_cours is None and len(b.v.file) == 0
    assert b.v.derniere_commande == {"action": "taire", "ok": True, "message": "Le robot se tait."}
    rang = len(b.requetes)
    b.recevoir(b.v.commande({"version": 1, "action": "taire", "id": "c-2"}))  # rien ne joue : 1004 quand même
    assert b.apis(rang) == [1004] and b.v.derniere_commande["id"] == "c-2"


def test_volume_1006_puis_1005():
    b = Banc()
    assert b.apis() == [1005]                          # pas de volume réglé : seulement relu
    assert b.v.volume == 70 and b.v.volume_lu == 70
    rang = len(b.requetes)
    b.recevoir(b.v.commande({"version": 1, "action": "volume", "volume": 60}))
    assert [(r.api_id, json.loads(r.parametre)) for _, r in b.requetes[rang:]] == [
        (1006, {"volume": 60}), (1005, {})]
    assert b.v.volume == 60 and b.etats[-1]["volume"] == 60


def test_volume_envoye_quand_le_robot_arrive():
    b = Banc(abonne=False, volume=55)
    assert b.apis() == []
    b.avancer(0.5)
    assert b.apis() == []
    b.recevoir(b.v.commande({"version": 1, "action": "volume", "volume": 65}))
    assert b.apis() == []
    b.v.changer_abonnes(1)
    b.avancer(0.1)
    assert [(r.api_id, json.loads(r.parametre)) for _, r in b.requetes] == [(1006, {"volume": 65}), (1005, {})]


def test_sortie_borne_wav_annonce_sans_requete():
    b = Banc(sortie="borne", volume=80)
    assert b.apis() == []
    b.dire("Bonjour, suivez-moi !", id="Essai.1")
    b.avancer(0.1)
    assert len(b.annonces) == 1
    message = b.annonces[0][1]
    assert message["id"] == "essai-1" and message["url"] == "/api/voix/son/essai-1"
    assert message["texte"] == "Bonjour, suivez-moi !" and message["frequence_hz"] == 22050
    assert message["source"] == "guide" and message["priorite"] == "normale"
    b.avancer(5.0)
    assert b.apis() == [] and b.v.dites == 1
    b.recevoir(b.v.commande({"version": 1, "action": "taire"}))
    b.recevoir(b.v.commande({"version": 1, "action": "volume", "volume": 30}))
    assert b.apis() == []                              # la borne ne parle jamais au robot
    assert b.v.reglages_phrase(LV.Phrase("x", {"texte": "a"}, 0.0, 1))[2] == pytest.approx(0.3)


def test_sortie_robot_tts_1001():
    b = Banc(sortie="robot_tts")
    b.dire("Bonjour à tous")
    b.dire("Hello everyone", langue="en")
    b.avancer(15.0)
    tts = [json.loads(r.parametre) for _, r in b.requetes if r.api_id == 1001]
    assert tts == [{"index": 0, "speaker_id": LV.LOCUTEUR_TTS_DEFAUT, "text": "Bonjour à tous"},
                   {"index": 1, "speaker_id": V.LOCUTEURS_TTS["en"], "text": "Hello everyone"}]
    assert 1003 not in b.apis() and b.v.dites == 2
    debut = [t for t, r in b.requetes if r.api_id == 1001]
    assert debut[1] - debut[0] >= LV.duree_tts_s("Bonjour à tous")


def test_robot_tts_locuteur_regle_et_chinois():
    b = Banc(sortie="robot_tts", locuteur_tts=0)
    b.dire("Phrase.")
    b.dire("你好", langue="zh")
    b.avancer(10.0)
    assert [json.loads(r.parametre)["speaker_id"] for _, r in b.requetes if r.api_id == 1001] == [0, 0]


def test_changer_de_sortie_coupe_la_phrase_et_garde_la_file():
    b = Banc()
    b.dire(LONGUE)
    b.dire("Suivante.")
    b.avancer(1.0)
    rang = len(b.requetes)
    b.recevoir(b.v.commande({"version": 1, "action": "sortie", "sortie": "borne"}))
    b.avancer(5.0)
    assert b.apis(rang) == [1004] and b.v.sortie == "borne"
    assert [m["texte"] for _, m in b.annonces] == ["Suivante."]
    b.recevoir(b.v.commande({"version": 1, "action": "sortie", "sortie": "robot_tts"}))
    b.avancer(0.1)
    assert b.apis()[-1] == 1005                        # le robot reprend la parole : volume relu


def test_changer_de_voix():
    b = Banc(disponibles=["fr_FR-siwis-medium", "fr_FR-tom-medium"])
    b.recevoir(b.v.commande({"version": 1, "action": "voix", "voix": "fr_FR-tom-medium"}))
    assert b.v.voix == "fr_FR-tom-medium" and b.v.derniere_commande["ok"]
    b.recevoir(b.v.commande({"version": 1, "action": "voix", "voix": "fr_FR-absente"}))
    assert b.v.voix == "fr_FR-tom-medium" and not b.v.derniere_commande["ok"]
    assert "absente" in b.v.derniere_commande["message"]


def test_robot_muet_ne_repond_plus():
    b = Banc(repondre=False)
    b.dire(LONGUE)
    b.avancer(5.0)
    e = b.etats[-1]
    assert e["robot"]["repond"] is False and e["robot"]["abonne"] is True
    assert b.v.erreurs == 2                            # 1005 du départ, puis une fois pour la phrase
    assert "ne répond plus" in e["derniere_erreur"]
    b.avancer(10.0)
    assert b.v.erreurs == 2 and b.v.dites == 1


def test_reponse_tardive_et_reponses_des_autres():
    b = Banc(repondre=False)
    b.avancer(2.0)
    assert b.v.repond is False
    perdue = b.requetes[0][1].identifiant
    b.recevoir(b.v.reponse(perdue, 0, '{"volume": 50}'))
    assert b.v.repond is True
    avant = (b.v.erreurs, b.v.volume_lu)
    b.recevoir(b.v.reponse(123456789, 3204, ""))     # une réponse au pilotage : ignorée
    assert (b.v.erreurs, b.v.volume_lu) == avant


def test_personne_n_ecoute_la_phrase_est_abandonnee():
    b = Banc(abonne=False)
    b.dire("Personne ne m'entend.")
    b.avancer(LV.DELAI_ABONNE_S - 0.2)
    assert len(b.v.file) == 1 and b.apis() == []
    b.avancer(0.5)
    assert len(b.v.file) == 0 and b.apis() == [] and b.v.erreurs == 1
    assert "n'écoute pas" in b.v.derniere_erreur and b.etats[-1]["robot"]["abonne"] is False


def test_code_d_erreur_du_robot_arrete_les_morceaux():
    b = Banc(repondre=False)
    b.dire(LONGUE * 3)
    b.avancer(0.1)
    premier = b.lectures()[0][1]
    b.recevoir(b.v.reponse(premier.identifiant, 3204, ""))
    b.avancer(15.0)
    assert len(b.lectures()) == 1 and b.v.erreurs >= 1
    assert "code 3204" in b.etats[-1]["derniere_erreur"] or b.v.erreurs > 1


def test_code_de_1004_ignore_comme_le_sdk():
    b = Banc(repondre=False)
    b.recevoir(b.v.commande({"version": 1, "action": "taire"}))
    arret = [r for _, r in b.requetes if r.api_id == 1004][0]
    erreurs = b.v.erreurs
    b.recevoir(b.v.reponse(arret.identifiant, 3104, ""))
    b.avancer(3.0)
    assert b.v.erreurs == erreurs + 1                  # le 1005 du départ seulement


@pytest.mark.parametrize("message", [
    None, "texte", {"texte": ""}, {"texte": "   "}, {"source": "guide"}, {"texte": "x" * 501},
    {"texte": "Bonjour", "priorite": "urgente"}, {"texte": "Bonjour", "source": "inconnue"},
    {"texte": "Bonjour", "id": "a b"}, {"texte": 12},
])
def test_messages_faux_refuses_sans_exception(message):
    b = Banc()
    assert b.recevoir(b.v.dire(message)) == []
    assert b.v.refusees == 1 and b.v.derniere_erreur.startswith("Message ignoré")


@pytest.mark.parametrize("message", [
    None, {}, {"version": 1, "action": "fort"}, {"version": 1, "action": "volume"},
    {"version": 1, "action": "volume", "volume": 120}, {"version": 1, "action": "sortie", "sortie": "pc"},
])
def test_commandes_fausses_refusees(message):
    b = Banc()
    n = len(b.requetes)
    assert b.recevoir(b.v.commande(message)) == []
    assert b.v.refusees == 1 and len(b.requetes) == n and b.v.derniere_commande["ok"] is False


def test_ids_des_phrases():
    instant = mur()
    assert id_de_phrase("pause-v3", 1, instant) == "pause-v3"
    assert id_de_phrase("Borne:17.A", 1, instant) == "borne-17-a"
    assert id_de_phrase("___", 7, instant) == "s-20261112-142031-0007"
    assert id_de_phrase(None, 12345, instant) == "s-20261112-142031-2345"
    for ident in ("pause-v3", "borne-17-a", "s-20261112-142031-0007"):
        assert V.MOTIF_ID_SON.match(ident)
    b = Banc()
    b.dire("Un.")
    b.dire("Deux.", id="dialogue-3")
    assert [p.id for p in b.v._phrases()][-1] == "dialogue-3"


def test_peremption_et_file_pleine():
    b = Banc(abonne=False)
    for i in range(LV.FILE_MAX + 3):
        b.dire(f"Phrase {i}.")
    assert len(b.v.file) == LV.FILE_MAX and b.v.oubliees == 3
    assert b.v.file[0].texte == "Phrase 3."
    b2 = Banc()
    b2.dire("x" * 490)                             # coupée à 30 s de son (DUREE_PHRASE_MAX_S)
    b2.dire("Trop tard.")
    b2.avancer(LV.PEREMPTION_S + 5.0)
    assert b2.v.oubliees == 1 and "Trop tard." not in [h["texte"] for h in b2.v.historique if h["fin"] == "dite"]


def test_reglages_d_une_phrase():
    b = Banc(disponibles=["fr_FR-siwis-medium", "fr_FR-tom-medium"], vitesse=1.1)
    phrase = LV.Phrase("p", {"texte": "a"}, 0.0, 1)
    assert b.v.reglages_phrase(phrase) == ("fr_FR-siwis-medium", 1.1, 1.0)
    b.v.changer_personnalite({"id": "discret", "nom": "Discret", "voix": {"vitesse": 0.9, "volume": 50}})
    assert b.v.reglages_phrase(phrase) == ("fr_FR-siwis-medium", 0.9, 0.5)
    avec = LV.Phrase("q", {"texte": "a", "voix": {"nom": "fr_FR-tom-medium", "vitesse": 1.25}}, 0.0, 2)
    assert b.v.reglages_phrase(avec) == ("fr_FR-tom-medium", 1.25, 1.0)
    absente = LV.Phrase("r", {"texte": "a", "voix": {"nom": "fr_FR-absente", "vitesse": 9}}, 0.0, 3)
    assert b.v.reglages_phrase(absente) == ("fr_FR-siwis-medium", 2.0, 1.0)
    b.v.volume = 50
    assert b.v.reglages_phrase(phrase, "borne")[2] == pytest.approx(0.25)
    assert b.v.reglages_phrase(phrase, "robot")[2] == pytest.approx(0.5)
    assert b.v.etat()["personnalite"] == "discret"


def test_synthese_d_avance_et_refaite_si_les_reglages_changent():
    h = Horloge()
    v = LogiqueVoix(sortie="robot", horloge=h, mur=mur, disponibles=["fr_FR-siwis-medium", "fr_FR-tom-medium"])
    v.changer_abonnes(1)
    for i in range(6):
        v.dire({"texte": f"Phrase {i}."})
    travaux = []
    while True:
        t = v.prochaine_synthese()
        if t is None:
            break
        travaux.append(t)
    assert [t[1] for t in travaux] == ["Phrase 0.", "Phrase 1.", "Phrase 2."]
    assert v.prochaine_synthese() is None              # déjà demandées
    for ident, texte, voix, vitesse, gain in travaux:
        v.son_pret(ident, (voix, vitesse, gain), SYNTHESE.synthetiser(texte, voix, vitesse, gain))
    v.commande({"version": 1, "action": "voix", "voix": "fr_FR-tom-medium"})
    refaire = v.prochaine_synthese()
    assert refaire is not None and refaire[2] == "fr_FR-tom-medium"
    tts = LogiqueVoix(sortie="robot_tts", horloge=h, mur=mur)
    tts.dire({"texte": "Pas de Piper."})
    assert tts.prochaine_synthese() is None


def test_synthese_echouee():
    b = Banc()
    b.recevoir(b.v.dire({"texte": "Impossible à dire."}))
    ident = b.v.prochaine_synthese()[0]
    b.v.synthese_echouee(ident, "la voix « x » est absente")
    b.dire("Possible.")
    b.avancer(5.0)
    assert b.v.erreurs == 1 and "n'a pas pu dire" in b.v.derniere_erreur
    assert [h["fin"] for h in b.v.historique] == ["echec", "dite"]


def test_arret_du_noeud():
    b = Banc()
    assert b.v.arreter() == []                         # rien n'a jamais été dit : pas de 1004
    b.dire(LONGUE)
    b.dire("Encore une.")
    b.avancer(1.0)
    sorties = b.recevoir(b.v.arreter())
    assert [s.api_id for s in sorties] == [1004] and len(b.v.file) == 0
    b2 = Banc(sortie="borne")
    b2.dire("Bonjour.")
    b2.avancer(0.2)
    assert b2.v.arreter() == []                        # la borne ne parle jamais au robot


def test_etat_conforme_et_exemple_du_contrat():
    b = Banc()
    e = b.v.etat()
    for cle in ("version", "sortie", "en_cours", "file", "volume", "dites", "erreurs", "robot", "temps"):
        assert cle in e
    assert set(V.EXEMPLE_ETAT_VOIX) - {"interrompues", "derniere_erreur", "voix"} <= set(e)
    b.dire(LONGUE)
    b.avancer(0.2)
    en_cours = b.v.etat()["en_cours"]
    assert en_cours["texte"] == LONGUE and en_cours["priorite"] == "normale" and en_cours["source"] == "guide"
    assert en_cours["debut"] == "2026-11-12T14:20:31" + mur().strftime("%z")[:3] + ":" + mur().strftime("%z")[3:]
    assert en_cours["morceaux"]["envoyes"] == 1


def test_reglages_refuses_a_la_creation():
    with pytest.raises(ValueError):
        LogiqueVoix(sortie="pc")
    with pytest.raises(ValueError):
        LogiqueVoix(volume=101)
    with pytest.raises(ValueError):
        LogiqueVoix(volume=True)


def test_wav_pas_ecrit_le_robot_parle_la_borne_non():
    for sortie, annonces, dites in (("robot", 0, 1), ("borne", 0, 0)):
        b = Banc(sortie=sortie)
        b.recevoir(b.v.dire({"texte": "Disque plein."}))
        ident, texte, voix, vitesse, gain = b.v.prochaine_synthese()
        son = SYNTHESE.synthetiser(texte, voix, vitesse, gain)
        son.infos["wav"] = False                     # le fil de synthèse n'a pas pu écrire le WAV
        b.v.son_pret(ident, (voix, vitesse, gain), son)
        b.avancer(3.0)
        assert len(b.annonces) == annonces and b.v.dites == dites, sortie
        if sortie == "robot":
            assert b.lectures() and b.v.erreurs == 0
        else:
            assert b.v.erreurs == 1 and "écrit" in b.v.derniere_erreur and b.v.historique[-1]["fin"] == "echec"
