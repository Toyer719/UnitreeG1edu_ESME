"""Scènes des passants (atelier.monde.scene, atelier/monde/scenes/) et monde simulé avec corps.

Chaque scène du plan (11.3) existe, est valide et s'applique à une copie du demo ; la référence
n'est jamais modifiée. Le monde simulé remplace les <actor> des piétons-corps par des corps solides.
"""
import hashlib
import math
import xml.etree.ElementTree as ET

import pytest

from atelier import RACINE
from atelier.lieu import (ErreurLieu, Monde, Pieton, charger_fiche, charger_monde, charger_salles, copier_lieu,
                          valider_donnees, valider_lieu)
from atelier.lieu.passants import RAYON_PIETON, reglages_pieton
from atelier.monde import sdf as S
from atelier.monde.foule import CarteLibre
from atelier.monde.scene import (DOSSIER_SCENES, appliquer_scene, charger_scene, copier_pour_scene, est_reference,
                                 lister_scenes, resume_scene, trajets_de_scene)

DEMO = RACINE / "lieux" / "demo"
SCENES_DU_PLAN = ("immobile_couloir", "en_face", "coupe_route", "groupe_couloir", "groupe_reste", "foule")


def empreinte(dossier):
    h = hashlib.sha256()
    for f in sorted(p for p in dossier.rglob("*") if p.is_file()):
        h.update(str(f.relative_to(dossier)).encode())
        h.update(f.read_bytes())
    return h.hexdigest()


@pytest.fixture
def demo(tmp_path):
    return copier_lieu(DEMO, tmp_path / "demo")


def test_les_scenes_du_plan_existent_et_sont_valides():
    ids = [p.name[:-len(".scene.yaml")] for p in lister_scenes()]
    assert set(SCENES_DU_PLAN) <= set(ids)
    for ident in SCENES_DU_PLAN:
        scene = charger_scene(ident)
        assert scene["id"] == ident and scene["lieu"] == "demo" and scene["etage"] == "rdc"
        assert valider_donnees("scene", scene) == []
        assert scene.get("mesures"), f"{ident} : pas de seuils"
        assert resume_scene(scene)["commande"] == f"g1-banc --scene {ident}"


def test_scenes_conformes_au_plan():
    immobile = charger_scene("immobile_couloir")
    p = Pieton.depuis_dict(immobile["pietons"][0])
    assert tuple(p.trajet[0]) == (12.0, 13.0) and reglages_pieton(p)["reaction"] == "aucune"
    assert immobile["essais"] == 5 and immobile["mesures"]["distance_bord_min_m"] == 0.2
    en_face = Pieton.depuis_dict(charger_scene("en_face")["pietons"][0])
    assert en_face.vitesse == 1.0 and all(y == 13.0 for _, y in en_face.trajet[:2])
    assert en_face.trajet[0][0] > en_face.trajet[1][0]                       # vers l'ouest
    coupe = Pieton.depuis_dict(charger_scene("coupe_route")["pietons"][0])
    (x1, y1), (x2, y2) = coupe.trajet
    assert x1 < 2.5 < x2 and 11.0 <= min(y1, y2) and max(y1, y2) <= 12.5     # coupe la ligne x = 2,5
    for ident, duree in (("groupe_couloir", 60), ("groupe_reste", 600)):
        scene = charger_scene(ident)
        groupe = [Pieton.depuis_dict(d) for d in scene["pietons"]]
        assert sorted(g.trajet[0][1] for g in groupe) == [12.0, 13.0, 14.0]
        assert all(g.trajet[0][0] == 15.5 for g in groupe)
        assert all(0 < g.pauses[0]["duree_s"] <= duree and g.pauses[0]["point"] == 0 for g in groupe)
    assert charger_scene("groupe_reste")["mesures"]["longueur_max_m"] == 75
    foule = charger_scene("foule")
    assert foule["ajouter"] and foule["hasard"] == 20 and len(foule["pietons"]) == 3


def test_groupe_bouche_le_couloir():
    """Les trois passants en x = 15,5 ne laissent aucun passage de 0,7 m (2 × robot_radius de Nav2)."""
    for ident in ("groupe_couloir", "groupe_reste"):
        ys = sorted(d["trajet"][0][1] for d in charger_scene(ident)["pietons"])
        bords = [11.575] + [v for y in ys for v in (y - RAYON_PIETON, y + RAYON_PIETON)] + [14.425]
        trous = [b - a for a, b in zip(bords[0::2], bords[1::2])]
        assert max(trous) < 0.7, trous


def test_trajets_des_pietons_dans_l_espace_libre():
    carte = CarteLibre(charger_monde(DEMO, "rdc"))
    for ident in SCENES_DU_PLAN:
        for d in charger_scene(ident)["pietons"]:
            p = Pieton.depuis_dict(d)
            for (x1, y1), (x2, y2) in zip(p.trajet, p.trajet[1:]):
                n = max(2, int(math.dist((x1, y1), (x2, y2)) / 0.1))
                for k in range(n + 1):
                    x, y = x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n
                    assert carte.libre(x, y, reglages_pieton(p)["rayon_m"]), (ident, p.id, (x, y))


def test_trajets_et_essais(demo):
    salles = [s.id for s in charger_salles(demo)]
    assert trajets_de_scene(charger_scene("immobile_couloir"), salles) == [("accueil", "b204")] * 5
    foule = trajets_de_scene(charger_scene("foule"), salles)
    assert len(foule) == 20 and foule[0][0] == "accueil"
    assert all(a != b for a, b in foule) and all(foule[i][1] == foule[i + 1][0] for i in range(19))
    assert foule == trajets_de_scene(charger_scene("foule"), salles)        # graine fixe


def test_appliquer_une_scene_a_une_copie(demo):
    avant = empreinte(DEMO)
    monde = appliquer_scene(demo, charger_scene("groupe_couloir"))
    assert [p.id for p in monde.pietons] == ["groupe_nord", "groupe_milieu", "groupe_sud"]
    assert [p.id for p in charger_monde(demo, "rdc").pietons] == [p.id for p in monde.pietons]
    assert charger_fiche(demo).guide == {"retour_auto": False, "delai_passant_s": 20}
    racine = ET.parse(demo / "mondes" / "rdc.sdf").getroot()
    assert sorted(a.get("name") for a in racine.iter("actor")) == sorted(p.id for p in monde.pietons)
    rapport = valider_lieu(demo)
    assert rapport.erreurs == [], rapport.texte()
    # « ajouter » : la foule garde les piétons qui sont déjà là (ici, le groupe)
    appliquer_scene(demo, charger_scene("foule"), reaction="arret")
    pietons = charger_monde(demo, "rdc").pietons
    assert [p.id for p in pietons][:3] == ["groupe_nord", "groupe_milieu", "groupe_sud"] and len(pietons) == 6
    assert {reglages_pieton(p)["reaction"] for p in pietons[3:]} == {"arret"}
    assert empreinte(DEMO) == avant


def test_foule_complete_le_demo(tmp_path):
    copie = copier_pour_scene("foule", tmp_path / "essai", reference=DEMO)
    pietons = charger_monde(copie, "rdc").pietons
    assert [p.id for p in pietons] == ["pieton_sud", "pieton_nord", "pieton_3", "pieton_4", "pieton_5"]
    assert all(reglages_pieton(p)["reaction"] == "ecart" and reglages_pieton(p)["corps"] for p in pietons)
    assert not list((copie / "cartes").glob("*.pcd"))


def test_la_reference_est_refusee(tmp_path, monkeypatch):
    avant = empreinte(DEMO)
    with pytest.raises(ErreurLieu, match="lieu de référence"):
        appliquer_scene(DEMO, charger_scene("en_face"))
    # une scène qui vise un autre lieu de référence : celui-ci aussi est protégé
    monkeypatch.setenv("ATELIER_LIEUX", str(tmp_path))
    copie = copier_lieu(DEMO, tmp_path / "demo")
    assert est_reference(copie, charger_scene("en_face"))
    with pytest.raises(ErreurLieu, match="lieu de référence"):
        appliquer_scene(copie, charger_scene("en_face"))
    assert empreinte(DEMO) == avant


def test_scenes_fausses(tmp_path):
    with pytest.raises(ErreurLieu, match="introuvable"):
        charger_scene("inconnue")
    faux = tmp_path / "autre.scene.yaml"
    faux.write_text((DOSSIER_SCENES / "en_face.scene.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ErreurLieu, match="nom du"):
        charger_scene(faux)
    casse = tmp_path / "casse.scene.yaml"
    casse.write_text("version: 1\nid: casse\nnom: x\nlieu: demo\netage: rdc\npietons: []\ntrajets: []\n",
                     encoding="utf-8")
    with pytest.raises(ErreurLieu, match="il faut des trajets"):
        charger_scene(casse)
    with pytest.raises(ErreurLieu, match="réaction"):
        appliquer_scene(tmp_path, charger_scene("en_face"), reaction="fuite")


# ---------------------------------------------------------------- monde simulé (piétons-corps)

def test_monde_simule_remplace_les_actor_par_des_corps(demo):
    monde = charger_monde(demo, "rdc")
    monde.pietons[1].corps = False
    texte, ids = S.sdf_simulation((demo / "mondes" / "rdc.sdf").read_text(encoding="utf-8"), monde,
                                  demo / "mondes")
    assert ids == ["pieton_sud"]
    racine = ET.fromstring(texte)
    acteurs = racine.findall("world/actor")
    assert [a.get("name") for a in acteurs] == ["pieton_nord"]
    assert acteurs[0].findtext("skin/filename") == str(demo / "mondes" / "pieton.dae")
    modele = racine.find("world/model[@name='pieton_sud']")
    assert modele.findtext("static") is None                       # un corps qui bouge
    collision = modele.find("link/collision")
    assert collision.findtext("geometry/cylinder/radius") == "0.25"
    assert collision.findtext("geometry/cylinder/length") == "1.7"
    assert collision.findtext("surface/contact/collide_bitmask") == "0x0002"
    assert modele.find("link/visual/visibility_flags") is None     # le LiDAR le voit
    plugins = {p.get("name").rsplit("::", 1)[-1]: p for p in modele.findall("plugin")}
    assert plugins["VelocityControl"].findtext("topic") == "/model/pieton_sud/cmd_vel"
    assert plugins["OdometryPublisher"].findtext("odom_topic") == "/model/pieton_sud/odometry"
    assert plugins["OdometryPublisher"].findtext("dimensions") == "2"
    pose = [float(v) for v in modele.findtext("pose").split()]
    assert pose[:2] == list(monde.pietons[0].trajet[0]) and pose[2] == S.SOL_CORPS
    # les autres modèles du monde ne changent pas
    assert len(racine.findall("world/model")) == len(ET.parse(demo / "mondes" / "rdc.sdf").getroot()
                                                     .findall("world/model")) + 1


def test_monde_simule_acteurs_et_masques():
    monde = Monde.depuis_dict({
        "version": 1, "emprise": {"min": [0, 0], "max": [10, 10]},
        "pietons": [{"id": f"p{i}", "trajet": [[1, i * 0.5 + 1], [9, i * 0.5 + 1]], "vitesse": 1.0,
                     "aller_retour": True, "rayon_m": 0.3} for i in range(17)],
        "depart_robot": {"x": 0.5, "y": 0.5, "theta": 0}})
    texte = S.texte_sdf(monde, "rdc")
    assert S.sdf_simulation(texte, monde, "/x", mode="acteurs")[1] == []
    texte2, ids = S.sdf_simulation(texte, monde, "/x")
    assert len(ids) == 17 and "<actor" not in texte2
    masques = [S.masque_collision(r) for r in range(17)]
    assert len(set(masques[:15])) == 15 and masques[15] == masques[0]       # 15 bits, puis ils reviennent
    assert all(m & 0xffff and not m & 1 for m in masques)
    assert ET.fromstring(texte2).find("world/model[@name='p0']/link/collision/geometry/cylinder/radius").text == "0.3"
    with pytest.raises(ValueError):
        S.pietons_avec_corps(monde, "fantomes")


def test_pont_des_pietons():
    texte = S.texte_pont_pietons(["a", "b"])
    import yaml
    entrees = yaml.safe_load(texte)
    assert len(entrees) == 4
    assert {e["ros_topic_name"] for e in entrees} == {"/pietons/corps/a/cmd_vel", "/pietons/corps/a/odom",
                                                      "/pietons/corps/b/cmd_vel", "/pietons/corps/b/odom"}
    assert {e["direction"] for e in entrees} == {"ROS_TO_GZ", "GZ_TO_ROS"}
