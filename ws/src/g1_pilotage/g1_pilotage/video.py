"""
Importer les bras d'une chorégraphie depuis une vidéo de danse (section 11.5 du plan, facultatif).

  g1-pilotage importer-video DANSE.mp4 --id ma_danse [--debut 5 --duree 20] [--bpm 120]

La pose humaine vient d'ultralytics (YOLO pose, hors ligne : modeles/yolo/yolo11n-pose.pt) :
17 points du corps par image, dont les épaules, les coudes, les poignets et les hanches. Seuls les
bras sont gardés ; les jambes, la taille et les pas ne viennent jamais d'une vidéo.

Le danseur est supposé face à la caméra. Pour chaque bras, la direction du bras (épaule → coude)
est lue dans le plan de l'image par rapport au torse (vers le bas, vers l'extérieur) ; sa
composante vers l'avant vient du raccourcissement apparent (longueur du bras vue, comparée à sa
plus grande longueur dans la vidéo). Elle donne le tangage et le roulis de l'épaule du G1 (la
rotation de l'épaule et les poignets restent à 0) ; l'angle du coude vient de l'angle entre bras
et avant-bras. Ce n'est qu'une approximation : une vidéo ne dit rien de la profondeur.

Puis : points peu sûrs oubliés et comblés, filtre médian puis moyenne glissante, une pose clé par
demi-temps (0,5 s à 120 temps par minute), angles ramenés aux limites (LIMITES_BRAS) et écarts
entre poses bornés pour que la vitesse reste sous VITESSE_BRAS_MAX, rampes du poids au début et à
la fin. La chorégraphie obtenue passe verifier_choregraphie avant d'être écrite.

Python du projet (.venv-projet : ultralytics, OpenCV, numpy). La partie géométrique ne dépend que
de numpy et se teste sans modèle.
"""
import argparse
import math
from pathlib import Path
import sys

import numpy as np

from .contrat import charger

D = charger()

POINTS = {'epaule_g': 5, 'epaule_d': 6, 'coude_g': 7, 'coude_d': 8, 'poignet_g': 9,
          'poignet_d': 10, 'hanche_g': 11, 'hanche_d': 12}
CONFIANCE_MIN = 0.4
RAPPORT_BRAS_EPAULES = 0.85     # longueur du bras / largeur des épaules (proportions humaines)
PERIODE_S = 0.1                 # images lues : 10 par seconde
FENETRE = 5                     # filtre médian puis moyenne, sur 5 images (0,5 s)
RAMPE_S = 1.5
AVANCE_S = 0.5                  # première pose après la rampe
MARGE_VITESSE = 0.92            # 8 % de marge sous VITESSE_BRAS_MAX
DUREE_MAX_S = 120.0
COUDE_MAX = 2.0
MODELE_DEFAUT = Path(__file__).resolve().parents[4] / 'modeles' / 'yolo' / 'yolo11n-pose.pt'
MESUREES = ('left_shoulder_pitch', 'left_shoulder_roll', 'left_elbow', 'right_shoulder_pitch',
            'right_shoulder_roll', 'right_elbow')


class ErreurImport(Exception):
    """Vidéo illisible, personne introuvable, modèle absent : le message dit quoi faire."""


# ---------------------------------------------------------------- géométrie (sans modèle)

def _unitaire(v):
    n = float(np.hypot(v[0], v[1]))
    return None if n < 1e-6 else np.asarray(v, dtype=float) / n


def angles_bras(points, confiance, longueurs_ref=None):
    """
    Angles des deux bras du G1 depuis les points d'une image (COCO, x à droite, y en bas).

    points : tableau (17, 2) ; confiance : (17,). longueurs_ref : {'g': R, 'd': R} longueur
    apparente d'un bras dans le plan de l'image (sinon : 0,85 × largeur des épaules). Renvoie
    {articulation: angle}, sans les bras peu sûrs (None si les épaules sont invisibles ; sans
    les hanches, le bas est pris perpendiculaire aux épaules : plans serrés sur le haut du corps).
    """
    p = np.asarray(points, dtype=float)
    c = np.asarray(confiance, dtype=float)
    if min(c[POINTS['epaule_g']], c[POINTS['epaule_d']]) < CONFIANCE_MIN:
        return None
    # vers la gauche du danseur
    lateral = _unitaire(p[POINTS['epaule_g']] - p[POINTS['epaule_d']])
    largeur = float(np.hypot(*(p[POINTS['epaule_g']] - p[POINTS['epaule_d']])))
    if lateral is None or largeur < 1e-3:
        return None
    # sans les hanches : le bas est perpendiculaire aux épaules
    bas = np.array([-lateral[1], lateral[0]])
    if min(c[POINTS['hanche_g']], c[POINTS['hanche_d']]) >= CONFIANCE_MIN:
        epaules = (p[POINTS['epaule_g']] + p[POINTS['epaule_d']]) / 2
        hanches = (p[POINTS['hanche_g']] + p[POINTS['hanche_d']]) / 2
        bas = _unitaire(hanches - epaules)
        if bas is None:
            return None
    angles = {}
    for cote, nom in (('g', 'left'), ('d', 'right')):
        e, k, w = (POINTS[f'{m}_{cote}'] for m in ('epaule', 'coude', 'poignet'))
        if min(c[e], c[k]) < CONFIANCE_MIN:
            continue
        bras = p[k] - p[e]
        r = float(np.hypot(*bras))
        ref = (longueurs_ref or {}).get(cote) or RAPPORT_BRAS_EPAULES * largeur
        ref = max(ref, r, 1e-6)
        z = -float(bras @ bas) / ref                      # vers le haut (repère du robot)
        y = float(bras @ lateral) / ref                   # vers la gauche du robot
        x = math.sqrt(max(0.0, 1.0 - min(1.0, (r / ref) ** 2)))   # vers l'avant (raccourci)
        roulis = math.asin(max(-1.0, min(1.0, y)))
        tangage = math.atan2(-x, -z) if abs(x) + abs(z) > 1e-9 else 0.0
        angles[f'{nom}_shoulder_pitch'] = tangage
        angles[f'{nom}_shoulder_roll'] = roulis
        coude = 0.0
        if c[w] >= CONFIANCE_MIN:
            avant_bras = p[w] - p[k]
            if np.hypot(*avant_bras) > 1e-6 and r > 1e-6:
                cosinus = float(bras @ avant_bras) / (r * float(np.hypot(*avant_bras)))
                coude = math.acos(max(-1.0, min(1.0, cosinus)))       # 0 : bras tendu
        angles[f'{nom}_elbow'] = min(COUDE_MAX, coude)
    return angles


def filtrer(serie, fenetre=FENETRE):
    """Valeurs manquantes (NaN) comblées, puis filtre médian et moyenne glissante."""
    s = np.asarray(serie, dtype=float)
    ok = np.isfinite(s)
    if not ok.any():
        return np.zeros_like(s)
    indices = np.arange(len(s))
    s = np.interp(indices, indices[ok], s[ok])
    demi = fenetre // 2
    bord = np.pad(s, demi, mode='edge')
    mediane = np.array([np.median(bord[i:i + fenetre]) for i in range(len(s))])
    bord = np.pad(mediane, demi, mode='edge')
    return np.convolve(bord, np.ones(fenetre) / fenetre, mode='valid')


def _borner(q):
    bornes = {}
    for nom, v in q.items():
        bas, haut = D.LIMITES_BRAS[nom]
        bornes[nom] = round(max(bas, min(haut, float(v))), 3)
    return bornes


def choregraphie_depuis_angles(instants, series, ident, nom=None, bpm=120.0, pas_cle_s=None):
    """
    Chorégraphie sûre (bras seulement) depuis des séries d'angles {articulation: [angles]}.

    instants : temps des images (s, depuis le début de l'extrait). Une pose clé par demi-temps,
    angles bornés, écarts entre poses bornés (vitesse), rampes du poids. Renvoie le dict, vérifié.
    """
    if len(instants) < 2:
        raise ErreurImport('extrait trop court : il faut au moins deux images')
    pas_cle_s = pas_cle_s or 30.0 / bpm
    filtrees = {n: filtrer(series.get(n, [0.0] * len(instants))) for n in D.ARTICULATIONS_BRAS}
    duree_video = float(instants[-1] - instants[0])
    ecart_max = D.VITESSE_BRAS_MAX * MARGE_VITESSE * 2.0 / math.pi      # rad par seconde d'écart
    poses = []
    precedent = dict(D.REPOS_BRAS)
    t_precedent = RAMPE_S
    k = 0
    while k * pas_cle_s <= duree_video + 1e-9:
        tv = instants[0] + k * pas_cle_s
        q = {n: float(np.interp(tv, instants, filtrees[n])) for n in D.ARTICULATIONS_BRAS}
        q = _borner(q)
        t = round(RAMPE_S + AVANCE_S + k * pas_cle_s, 3)
        dt = t - t_precedent
        for n in q:
            pas = ecart_max * dt
            q[n] = round(max(precedent[n] - pas, min(precedent[n] + pas, q[n])), 3)
        q = _borner(q)
        poses.append({'t': t, 'nom': f'image {tv:.1f} s', 'q': q})
        precedent, t_precedent = q, t
        k += 1
    # retour au repos : assez de temps pour la vitesse, puis la rampe de fin
    retour = max(AVANCE_S, max(abs(v) for v in precedent.values()) / ecart_max + 0.05)
    duree = round(t_precedent + retour + RAMPE_S, 1) + 0.1
    if duree > DUREE_MAX_S:
        raise ErreurImport(f'extrait de {duree_video:.0f} s : {DUREE_MAX_S:.0f} s au plus '
                           '(--duree)')
    d = {'version': 1, 'id': ident, 'nom': nom or ident, 'auteur': 'Import vidéo (Atelier G1)',
         'duree_s': duree, 'zone_libre_m': 2.0,
         'musique': {'fichier': None, 'battement': {'bpm': float(bpm), 'accent': 4},
                     'decalage_s': RAMPE_S + AVANCE_S, 'sortie': 'navigateur'},
         'bras': {'rampe_s': RAMPE_S, 'interpolation': 'douce', 'poses': poses}}
    erreurs = D.verifier_choregraphie(d)
    if erreurs:
        raise ErreurImport('la chorégraphie obtenue n\'est pas sûre : ' + ' ; '.join(erreurs[:3]))
    return d


# ---------------------------------------------------------------- lecture de la vidéo

def lire_points(video, modele=MODELE_DEFAUT, debut_s=0.0, duree_s=None, periode_s=PERIODE_S):
    """[(t, points (17, 2), confiance (17,))] de la personne principale, une image par période."""
    try:
        import cv2
        from ultralytics import YOLO
    except ImportError as e:
        raise ErreurImport(f'{e} : lancez avec le Python du projet '
                           '(~/robot-g1/.venv-projet)') from None
    if not Path(modele).is_file():
        raise ErreurImport(f'modèle de pose introuvable ({modele}) : il faut un modèle YOLO '
                           '« pose » hors ligne, par exemple modeles/yolo/yolo11n-pose.pt')
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ErreurImport(f'vidéo illisible : {video}')
    ips = capture.get(cv2.CAP_PROP_FPS) or 25.0
    yolo = YOLO(str(modele))
    resultats = []
    precedent = None
    i = 0
    prochain = debut_s
    try:
        while True:
            ok, image = capture.read()
            if not ok:
                break
            t = i / ips
            i += 1
            if t + 1e-9 < prochain:
                continue
            if duree_s is not None and t > debut_s + duree_s:
                break
            prochain += periode_s
            r = yolo.predict(image, verbose=False)[0]
            if r.keypoints is None or len(r.keypoints) == 0:
                continue
            points = r.keypoints.xy.cpu().numpy()
            confiance = r.keypoints.conf.cpu().numpy() if r.keypoints.conf is not None \
                else np.ones(points.shape[:2])
            boites = r.boxes.xyxy.cpu().numpy()
            # la personne principale : la plus grande, puis la plus proche de la précédente
            surfaces = (boites[:, 2] - boites[:, 0]) * (boites[:, 3] - boites[:, 1])
            choix = int(np.argmax(surfaces))
            if precedent is not None and len(points) > 1:
                ecarts = [float(np.nanmean(np.hypot(*(pt[5:13] - precedent[5:13]).T)))
                          for pt in points]
                proches = [j for j in range(len(points)) if surfaces[j] >= 0.5 * surfaces.max()]
                choix = min(proches, key=lambda j: ecarts[j])
            precedent = points[choix]
            resultats.append((t - debut_s, points[choix], confiance[choix]))
    finally:
        capture.release()
    if len(resultats) < 2:
        raise ErreurImport('aucune personne vue dans la vidéo (ou moins de deux images) : '
                           'filmez le danseur de face, en entier, bien éclairé')
    return resultats


def choregraphie_depuis_video(video, ident, nom=None, bpm=120.0, debut_s=0.0, duree_s=None,
                              modele=MODELE_DEFAUT):
    """La chorégraphie (bras seulement) d'une vidéo de danse."""
    points = lire_points(video, modele, debut_s, duree_s)
    longueurs = {}
    for cote in ('g', 'd'):
        e, k = POINTS[f'epaule_{cote}'], POINTS[f'coude_{cote}']
        vues = [float(np.hypot(*(p[k] - p[e]))) for _, p, c in points
                if min(c[e], c[k]) >= CONFIANCE_MIN]
        if vues:
            longueurs[cote] = float(np.percentile(vues, 95))
    instants = [t for t, _, _ in points]
    series = {n: [] for n in D.ARTICULATIONS_BRAS}
    for _, p, c in points:
        angles = angles_bras(p, c, longueurs) or {}
        for n in series:
            series[n].append(angles.get(n, math.nan if n in MESUREES else 0.0))
    return choregraphie_depuis_angles(instants, series, ident, nom, bpm)


def main(argv=None):
    a = argparse.ArgumentParser(prog='g1-pilotage importer-video',
                                description='Bras d\'une chorégraphie depuis une vidéo de danse '
                                            '(pose humaine d\'ultralytics, hors ligne).')
    a.add_argument('video')
    a.add_argument('--id', required=True, help='nom de la chorégraphie (ex. ma_danse)')
    a.add_argument('--nom', default=None)
    a.add_argument('--bpm', type=float, default=120.0, help='tempo : une pose clé par demi-temps')
    a.add_argument('--debut', type=float, default=0.0, help='début de l\'extrait (s)')
    a.add_argument('--duree', type=float, default=None, help='durée de l\'extrait (s)')
    a.add_argument('--modele', default=str(MODELE_DEFAUT))
    a.add_argument('--dossier', default=str(D.DOSSIER_CHOREGRAPHIES))
    args = a.parse_args(argv)
    if not D.atelier.MOTIF_ID.match(args.id) or args.id == 'exemple_kpop':
        print(f'importer-video : nom « {args.id} » refusé (lettres minuscules, chiffres, _ et -)',
              file=sys.stderr)
        return 2
    try:
        d = choregraphie_depuis_video(args.video, args.id, args.nom, args.bpm, args.debut,
                                      args.duree, args.modele)
    except ErreurImport as e:
        print(f'importer-video : {e}', file=sys.stderr)
        return 1
    import yaml
    chemin = D.chemin_choregraphie(args.id, args.dossier)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    entete = ('# Bras importés d\'une vidéo (g1-pilotage importer-video) : vérifiez dans '
              'l\'onglet Pilotage, aperçu 3D.\n')
    corps = yaml.safe_dump(d, allow_unicode=True, sort_keys=False, default_flow_style=None,
                           width=110)
    chemin.write_text(entete + corps, encoding='utf-8')
    print(f'{chemin} : {len(d["bras"]["poses"])} poses, {d["duree_s"]} s ; à essayer '
          'd\'abord dans l\'aperçu 3D, puis au portique à la vitesse 1/2')
    return 0


if __name__ == '__main__':
    sys.exit(main())
