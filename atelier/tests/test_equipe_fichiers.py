"""Fichiers de l'équipe (atelier.lieu.equipe, vague 4, section 11.6 du plan) : textes normalisés,
messages des sujets, et vérification entre les fichiers (verifier_equipe), sur des copies de demo.
Agent Équipe ; les fonctions du contrat sont testées par test_contrats_vague4.py."""
import copy

import pytest

import atelier
from atelier.lieu import charger_salles, copier_lieu, valider_message
from atelier.lieu import equipe as E

DEMO = atelier.RACINE / "lieux" / "demo"


@pytest.fixture
def lieu(tmp_path):
    return copier_lieu(DEMO, tmp_path / "demo")


def exemples():
    return {q: E.exemple_equipe(q) for q in E.FICHIERS_EQUIPE}


# ---------------------------------------------------------------- textes

@pytest.mark.parametrize("brut, normal", [
    ("Emmène-moi à l'Accueil !", "emmene moi a l accueil"),
    ("  OÙ   est la B204 ? ", "ou est la b204"),
    ("Cœur, Ça, ÉLÈVE", "coeur ca eleve"),
    ("vie_scolaire", "vie scolaire"),
    ("«  »", ""),
    ("salle n°3", "salle n 3"),
])
def test_normaliser(brut, normal):
    assert E.normaliser(brut) == normal


def test_jetons_et_reperes():
    assert E.jetons_motif("Où est {salle} ?") == ["ou", "est", "{salle}"]
    assert E.jetons_motif("merci{*}") == ["merci", "{*}"]
    assert E.jetons_motif("aller à {piece}") == ["aller", "a", "piece"]
    assert E.reperes("Je vous emmène à {nom_salle} ({salle})") == ["{nom_salle}", "{salle}"]


def test_formes_des_salles():
    formes = E.formes_salles(charger_salles(DEMO))
    assert formes["b204"] == "b204" and formes["labo de physique"] == "b204"
    assert formes["vie scolaire"] == "vie_scolaire" and formes["entree"] == "accueil"
    assert formes["salle b204"] == "b204"


# ---------------------------------------------------------------- messages des sujets

def test_message_robot_dire():
    perso = E.exemple_equipe("personnalites")["personnalites"][0]
    m = E.message_robot_dire("  Bonjour !  ", "dialogue", personnalite=perso)
    assert m["texte"] == "Bonjour !" and m["personnalite"] == "accueillant" and m["voix"]["vitesse"] == 1.0
    assert valider_message("robot_dire", m) == []
    m = E.message_robot_dire("x" * 900, "guide", code="arret", priorite="haute")
    assert len(m["texte"]) == 500 and valider_message("robot_dire", m) == []
    with pytest.raises(ValueError):
        E.message_robot_dire("x", "voix")


def test_message_personnalite_active():
    d = E.exemple_equipe("personnalites")
    p = E.personnalite_active(d)
    assert p["id"] == "accueillant" and E.personnalite_active(d, "discret")["nom"] == "Discret"
    assert E.personnalite_active(d, "inconnue") is None and E.personnalite_active(None) is None
    m = E.message_personnalite_active(p, lieu="demo")
    assert m["id"] == "accueillant" and m["lieu"] == "demo" and m["phrases"] == p["phrases"] and m["temps"]
    assert valider_message("personnalite_active", m) == []
    assert "version" not in p          # la personnalité du fichier n'est pas touchée


def test_prereglage_see3cam_valide():
    c = E.exemple_equipe("camera")
    p = E.PREREGLAGES_CAMERA["See3CAM_11CUG"]
    c["camera"].update({k: p[k] for k in ("modele", "largeur", "hauteur", "ips")})
    assert E.valider_equipe("camera", c) == []
    assert (p["largeur"], p["hauteur"]) in E.MODES_IMAGE_11CUG


# ---------------------------------------------------------------- trois fautes de chaque fichier, refusées en français

FAUTES = {
    "personnalites": [
        (lambda d: d.update(active="joyeux"), "n'existe pas"),
        (lambda d: d["personnalites"][0]["led"].update(g=999), "personnalites.yaml"),
        (lambda d: d["personnalites"][1].update(vitesse_max=1.0), "personnalites.yaml"),
    ],
    "dialogues": [
        (lambda d: d["regles"][0]["motifs"].append("je cherche"), "{salle}"),
        (lambda d: d["regles"][1].update(action="danser"), "dialogues.yaml"),
        (lambda d: d.pop("repli"), "repli"),
    ],
    "camera": [
        (lambda d: d["camera"].update(peripherique="video0"), "camera.yaml"),
        (lambda d: d["detection"].update(confiance_min=1.5), "camera.yaml"),
        (lambda d: d["camera"]["position"].pop("lacet"), "lacet"),
    ],
}


@pytest.mark.parametrize("quoi, rang", [(q, i) for q in FAUTES for i in range(3)])
def test_fautes_refusees_en_francais(lieu, quoi, rang):
    faute, attendu = FAUTES[quoi][rang]
    d = E.exemple_equipe(quoi)
    faute(d)
    erreurs = E.valider_equipe(quoi, d)
    assert erreurs and any(attendu in m for m in erreurs), erreurs
    assert all(m.startswith(E.FICHIERS_EQUIPE[quoi]) for m in erreurs), erreurs
    with pytest.raises(E.ErreurLieu):
        E.enregistrer_equipe(lieu, quoi, d)
    assert not E.chemin_equipe(lieu, quoi).exists()


# ---------------------------------------------------------------- verifier_equipe

def test_lieu_sans_fichiers_et_exemples(lieu):
    assert E.verifier_equipe(lieu) == {"ok": True, "erreurs": [], "avertissements": []}
    r = E.verifier_equipe(lieu, exemples())
    assert r["ok"] and not r["erreurs"]
    # le seul avertissement possible des exemples : le modèle de détection absent de ce PC
    assert all("modèle de détection" in m for m in r["avertissements"]), r


def test_fichier_faux_sur_le_disque(lieu):
    E.chemin_equipe(lieu, "dialogues").write_text("version: 1\nregles: [\n", encoding="utf-8")
    r = E.verifier_equipe(lieu)
    assert not r["ok"] and "dialogues.yaml" in r["erreurs"][0]


def test_contenu_donne_faux(lieu):
    r = E.verifier_equipe(lieu, {"camera": {"version": 1}})
    assert not r["ok"] and all(m.startswith("camera.yaml") for m in r["erreurs"])


def test_personnalite_inconnue_d_une_regle(lieu):
    d = exemples()
    d["dialogues"]["regles"][3]["personnalite"] = "joyeux"
    r = E.verifier_equipe(lieu, d)
    assert any("« joyeux » n'existe pas dans personnalites.yaml" in m for m in r["erreurs"]), r
    # sans personnalites.yaml : un avertissement
    d["personnalites"] = None
    r = E.verifier_equipe(lieu, d)
    assert r["ok"] and any("pas de personnalites.yaml" in m for m in r["avertissements"]), r


def test_motifs_douteux(lieu):
    d = exemples()["dialogues"]
    d["regles"].append({"id": "piece", "motifs": ["aller à {piece}"], "action": "dire", "reponse": "Non."})
    d["regles"].append({"id": "double", "motifs": ["Bonjour !"], "action": "dire", "reponse": "Re."})
    d["regles"].append({"id": "vide", "motifs": ["?!"], "action": "dire", "reponse": "…"})
    d["regles"].append({"id": "deux", "motifs": ["de {salle} a {salle}"], "action": "guider",
                        "reponse": "Je vous emmène à {nom_salle} {heure}."})
    d["regles"].append({"id": "tout", "motifs": ["{*}"], "action": "dire", "reponse": "Hein ?"})
    d["regles"].append({"id": "nom", "motifs": ["{salle} ferme"], "action": "dire", "reponse": "{nom_salle} ferme."})
    assert E.valider_equipe("dialogues", d) == []          # le schéma et les règles du contrat l'acceptent
    r = E.verifier_equipe(lieu, {"dialogues": d})
    texte = "\n".join(r["erreurs"] + r["avertissements"])
    assert "{piece}, qui n'existe pas" in texte and not r["ok"]
    assert "« Bonjour ! » ne servira jamais : la règle « bonjour »" in texte
    assert "« ?! » ne contient aucun mot" in texte
    assert "plusieurs {salle}" in texte and "{heure}" in texte
    assert "correspond à toutes les phrases" in texte
    assert "n'est remplacé que pour l'action guider" in texte


def test_phrases_et_personnalites_douteuses(lieu):
    p = exemples()["personnalites"]
    p["personnalites"][0]["phrases"]["depart"] = "On va à {salle} !"
    p["personnalites"][0]["geste_salut"] = 13
    p["personnalites"][1]["voix"]["volume"] = 0
    p["personnalites"][1]["vitesse_max"] = 0.05
    r = E.verifier_equipe(lieu, {"personnalites": p})
    texte = "\n".join(r["avertissements"])
    assert r["ok"] and "{salle} ne sera pas remplacé" in texte and "geste 13" in texte
    assert "volume 0" in texte and "avancera à peine" in texte
    # vague 5 : sous 0,2 m/s, le vrai robot ne marche pas (avertissement, pas une erreur)
    assert "n'a pas d'effet sur le vrai robot" in texte
    p["personnalites"][1]["vitesse_max"] = 0.2
    texte = "\n".join(E.verifier_equipe(lieu, {"personnalites": p})["avertissements"])
    assert "n'a pas d'effet" not in texte


def test_vitesse_minimale_du_contrat():
    from atelier.lieu import robot
    assert E.VITESSE_PAS_MIN == robot.VITESSE_MAX_MIN


def test_salles_qui_partagent_un_nom(lieu):
    salles = (lieu / "salles.yaml").read_text(encoding="utf-8")
    (lieu / "salles.yaml").write_text(salles.replace('alias: ["cdi", "bibliothèque"', 'alias: ["cdi", "hall"'),
                                      encoding="utf-8")
    r = E.verifier_equipe(lieu, {"dialogues": exemples()["dialogues"]})
    assert any("« hall » désigne plusieurs salles (accueil, cdi)" in m for m in r["avertissements"]), r


def test_guider_sans_salles(lieu):
    (lieu / "salles.yaml").write_text("[]\n", encoding="utf-8")
    r = E.verifier_equipe(lieu, {"dialogues": exemples()["dialogues"]})
    assert any("aucune salle" in m for m in r["avertissements"]), r


@pytest.mark.parametrize("changement, attendu", [
    (lambda c: c["camera"]["position"].update(z=2.0), "vérifiez z"),
    (lambda c: c["camera"]["position"].update(tangage=0.9), "le sol"),
    (lambda c: c["camera"]["position"].update(tangage=-0.9), "le plafond"),
    (lambda c: c["camera"]["position"].update(roulis=0.5), "penchée"),
    (lambda c: c["detection"].update(frequence_hz=50), "plus vite que la caméra"),
    (lambda c: c["camera"].pop("champ_horizontal_deg"), "champ_horizontal_deg"),
    (lambda c: c["camera"].update(modele="See3CAM_11CUG", largeur=1920, hauteur=1080), "--list-formats-ext"),
    (lambda c: c["detection"].update(modele="introuvable_xyz.pt"), "introuvable"),
])
def test_camera_douteuse(lieu, changement, attendu):
    c = copy.deepcopy(exemples()["camera"])
    changement(c)
    assert E.valider_equipe("camera", c) == []
    r = E.verifier_equipe(lieu, {"camera": c})
    assert r["ok"] and any(attendu in m for m in r["avertissements"]), r


def test_camera_modele_present(lieu):
    c = exemples()["camera"]
    c["detection"]["modele"] = "yolo11n-pose.pt"
    if not any((atelier.RACINE / "modeles").rglob("yolo11n-pose.pt")):
        pytest.skip("modèle yolo11n-pose.pt absent de ce PC")
    assert E.verifier_equipe(lieu, {"camera": c})["avertissements"] == []


def test_salles_fausses(lieu):
    (lieu / "salles.yaml").write_text("- id: 3\n", encoding="utf-8")
    r = E.verifier_equipe(lieu, {"dialogues": exemples()["dialogues"]})
    assert any("salles.yaml est invalide" in m for m in r["avertissements"]), r
