# Document Word « Atelier G1 : le logiciel, de A à Z » : notes

Dossier : `~/robot-g1-donnees/vague5/documents/logiciel/` (hors de `/tmp` : il survit à un redémarrage).
Le document : `Atelier_G1_documentation_logiciel.docx` (15 chapitres, 14 schémas, 56 pages dans le PDF de
contrôle sans les captures, environ 59 avec les 7 captures prévues).

## Regénérer

```bash
/home/joonho/robot-g1-donnees/venv-docx/bin/python \
    /home/joonho/robot-g1-donnees/vague5/documents/logiciel/generer.py
```

En 15 à 30 s, le script :
1. redessine les schémas modifiés (`schemas/*.dot` → `schemas/png/*.png`, Graphviz, 200 dpi, DejaVu Sans) ;
2. mesure les chiffres du dépôt (`~/robot-g1`) : commits, lignes de code, commandes, routes (par
   `.venv-projet`), tests collectés par pytest (sans les lancer), critères ; ils remplacent les `[[cle]]`
   du contenu (fonction `chiffres()`, avec des valeurs de repli si une mesure échoue) ;
3. écrit le `.docx` (python-docx) ;
4. le convertit en PDF avec LibreOffice (`controle/Atelier_G1_documentation_logiciel.pdf`), relève la
   page de chaque titre et réécrit la table des matières avec ces numéros (2 ou 3 passes).

Options :
- `--captures DOSSIER` : dossier des captures (défaut `~/robot-g1-donnees/vague5/captures`) ;
- `--sortie FICHIER.docx` : écrire ailleurs (par exemple un essai, sans toucher au document) ;
- `--images` : pages du PDF en PNG à 60 dpi dans `controle/pages/` ; puis
  `/usr/bin/python3 controle/planches.py` les réunit 8 par image dans `controle/planches/` pour la relecture ;
- `--sans-pdf` : sans LibreOffice (la table des matières n'a alors pas de numéros de page ; Word les met) ;
- `--schemas` : redessiner tous les schémas.

Vérifier le fichier (schémas OOXML ; le script du skill docx demande `defusedxml`, absent de ce PC : un
remplaçant minimal suffit pour un fichier que l'on a produit soi-même) :
`cd <skill docx>/scripts/office && PYTHONPATH=<dossier du remplaçant> <venv-docx>/bin/python validate.py <docx>`.
Dernier passage : « All validations PASSED! ».

## Où mettre les captures

Mettre les PNG dans `~/robot-g1-donnees/vague5/captures/` (sous-dossiers permis), puis regénérer. Le
chapitre 11 (`contenu/chapitre_11.py`) a 7 emplacements ; chacun essaie des motifs de noms, dans l'ordre,
et prend le premier fichier trouvé (jamais deux fois le même). Sans fichier, l'emplacement est omis : ni
trou, ni mention. Le seul texte qui dépend des captures est une phrase d'introduction (bloc `si_captures`).

| Emplacement | Motifs essayés (le premier trouvé gagne) |
|---|---|
| Accueil | `accueil_reel_sombre*.png`, `accueil_reel*.png`, `accueil_simulation_sombre*.png`, `accueil*.png` |
| Espace en Simulation | `simulation_sombre_dessiner*.png`, `simulation_*dessiner*.png`, `simulation_sombre_placer*.png` |
| Carte 3D | `*carte3d_iso_sombre*1366*.png`, `*carte3d_iso_sombre*.png`, `*carte3d_iso*.png`, `*carte3d*.png`, `reel_sombre_placer*.png`, `*placer*.png` |
| Scan | `*pendant_le_scan*1366*.png`, `*pendant_le_scan*.png`, `*scan*en_cours*.png`, `reel_sombre_scanner*.png`, `*scanner*.png` |
| Naviguer | `reel_sombre_naviguer*.png`, `reel_naviguer*.png`, `*naviguer*.png` |
| Piloter | `reel_sombre_piloter*.png`, `*piloter*.png` |
| Caméra | `*vue_camera_sombre*1366*.png`, `*vue_camera_sombre*.png`, `*vue_camera*.png`, `*equipe_camera_sombre*1366*.png`, `*camera*.png` |

Les noms suivent ceux de `tests_e2e/outils_coque_e2e.py captures` et des captures de l'assemblage
(`~/robot-g1-donnees/vague5/assemblage/captures/`). Si la vérification nomme ses captures autrement,
changer les motifs dans `contenu/chapitre_11.py`. Les PNG sont convertis en JPEG (qualité 88, 1 600 px de
large au plus) par le Pillow du système dans `controle/captures_jpeg/`, pour un `.docx` plus léger.
Essai avec les captures de l'assemblage, sans toucher au document :
`generer.py --captures ~/robot-g1-donnees/vague5/assemblage/captures --sortie controle/essai_captures.docx`
(fait le 31/10 : 7 captures trouvées, 59 pages, mise en page relue).

## Comment le contenu est rangé

- `contenu/couverture.py` (dictionnaire `COUVERTURE`) et `contenu/chapitre_01.py` à `chapitre_15.py`
  (liste `BLOCS`). Blocs : `("h1"|"h2"|"h3", titre)`, `("p", texte)`, `("chapeau", texte)`,
  `("puces", [..])` (un élément peut être `(texte, [sous-éléments])`), `("num", [..])`,
  `("table", {entetes, lignes, largeurs (cm), taille, legende, premiere_col_gras})`, `("code", texte)`,
  `("encadre", titre, texte ou [lignes ; « - » = puce], "retenir"|"attention"|"info")`,
  `("schema", nom, légende, largeur_cm, hauteur_max_cm)`, `("capture", [motifs], légende, largeur, hauteur)`,
  `("si_captures", [blocs])`, `("fiche", {nom, quoi, pourquoi, ici, exemple})`, `("saut",)`.
- Dans le texte : `**gras**`, `` `code` ``, `__italique__` ; `[[cle]]` = chiffre mesuré (voir `chiffres()`).
  Les espaces insécables du français (avant `: ; ! ? »`, après `«`, entre un nombre et son unité, dans
  `1 454`) sont posés par le générateur. Une ligne de code de plus de 84 caractères déclenche un
  avertissement (elle serait coupée à l'affichage).
- Mise en forme Word : A4, Calibri 11, titres numérotés automatiquement (numérotation liée aux styles
  « Titre 1 » à « Titre 3 »), vraies listes Word (numbering.xml), tableaux à en-tête ombré (`clear`) qui
  se répète sur chaque page et sans ligne isolée en haut ou en bas de page, en-tête et pied de page
  (« Page X sur Y »), légendes « Tableau N » et « Figure N » par champs SEQ, table des matières par
  champ TOC (niveaux 1 et 2), déjà remplie.
- **À l'ouverture dans Word**, une question demande s'il faut mettre à jour les champs : répondre
  **Oui** (Word refait la table des matières et les numéros avec sa propre mise en page). LibreOffice
  affiche la table telle qu'elle a été remplie.
- **Polices du PDF de contrôle** : ce PC n'a ni Calibri ni Carlito. Pour la conversion seulement,
  `controle/fonts.conf` (variable `FONTCONFIG_FILE`) remplace Calibri par Lato (la police dont Carlito est
  tirée) et Consolas par Liberation Mono ; LibreOffice tourne avec un profil à part
  (`controle/profil_libreoffice/`). Dans Word, avec Calibri, le document peut faire une ou deux pages de
  moins que le PDF de contrôle.

## Points incertains, à faire vérifier

1. **La vague 5 n'est pas finie** : sa vérification finale tournait pendant la rédaction (31/10, 20 h). Les
   chiffres « vivants » (commits, lignes, tests collectés, routes) se mettent à jour en regénérant ; le
   résultat « N / 36 » et le nombre de tests réussis de la vague 5 finie ne sont **pas** dans le document
   (section 12.4 : « vérification finale en cours ») : à ajouter dans `contenu/chapitre_12.py` (tableau
   « Les chiffres, vague après vague ») et dans `chapitre_10.py` (tableau des vagues, ligne 5).
2. **Le chapitre 11 décrit l'interface de l'assemblage de la vague 5** (17 h, 31/10) ; la vérification peut
   changer des libellés ou des comportements : relire le chapitre 11 avec les captures finales.
3. **Les zones lentes** : d'après le code (`ws/src/g1_nav`), Nav2 n'applique que le masque des zones
   interdites ; les zones lentes sont décrites et dessinées, sans effet sur la vitesse (écrit en 6.1 et
   dans le glossaire, chapitre 14). À confirmer.
4. **Les chiffres de la phase « comprendre »** (horloge en retard de 138 s, 59 % de nuages jetés, 8,2 m
   d'erreur, 39,7 % retirés, 45 % de damier, 92 objets dont 11 « personnes », panneaux de 24 px,
   36 boutons, 120 cases…) viennent des **résumés** de `vague5/comprendre/` : les rapports complets ont été
   perdus au redémarrage du 31/10. Les chiffres du scan retraité viennent, eux, de
   `lieux/seance/scans/2026-10-27_14h22/rapport.json` et `session.json`.
5. **Séance n° 1 (27/10)** : la feuille `docs/releves/seance_2026-10-27.md` n'a pas été remplie ; les
   résultats cités (0,1 m/s sans pas, 0,2 m/s qui marche, modes 0, 3, 501, 802, services arrêtés, 7105
   accepté assis) viennent des notes de Claude et du plan (12.12) ; C3, C4, C5 et C7 n'ont pas été notés.
6. **Formats d'Unitree non essayés** (1804, 7101, 7100, 7106, gestes, voix, LED, videohub) : l'annexe F dit
   « pas encore » ; ils viennent de la documentation d'Unitree ou de projets tiers.
7. **Versions** : relevées sur le PC le 31/10 (dpkg, pip, fichiers) ; celles du Jetson (Ubuntu 20.04.6,
   L4T R35.3.1, Docker 24.0.7, 15 Go) viennent du relevé du 22/10. Le modèle exact du Jetson n'est écrit
   nulle part : le document dit seulement « Jetson (PC2) ».
8. **Ordres de grandeur repris des documents** : image Docker « environ 2 Go » sur le Jetson (tutoriels),
   recette complète « environ 3 h » (README), G1 « d'environ 1,3 m » (taille du robot proxy).
9. **`lieux/seance` n'est pas dans Git** au moment de la rédaction (`git status` : non suivi) ; si
   l'intégrateur l'ajoute, corriger le chapitre 5 (tableau « Ce qui n'est pas dans Git ») et la recette 13.8.
10. **L'avancement (≈ 52 %, « environ 50 % »)** est l'estimation de l'intégrateur, avec ses poids ; il est
    repris tel quel (section 1.4).
11. **Annexe B** (routes) et **annexe C** (sujets) sont écrites à la main d'après le code du 31/10 (100 routes
    des modules + `/api/etat` et `/ws/etat` ; sujets relevés dans le code) : à revoir si la vérification
    ajoute ou retire des routes ou des sujets.
12. **Numéros de page de la table des matières** : ceux du PDF de contrôle (LibreOffice, Lato) ; Word les
    recalcule à l'ouverture (répondre Oui).
