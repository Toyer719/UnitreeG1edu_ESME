// Caméra (vague 4, section 11.6 du plan ; vague 5, section 12.7) : écran de l'agent Caméra.
// La caméra de poitrine See3CAM (camera.yaml) : l'image en direct avec un cadre autour de chaque
// visiteur (js/camera/flux.js), une vue de dessus et une vue de côté de ce que voit la caméra (les
// visiteurs vus par la caméra et les personnes vues par le LiDAR s'y dessinent en direct), et les
// réglages : périphérique, image, place sur le robot (repère base_link), détection des visiteurs,
// et en « Réglages avancés » l'exposition, la publication des images et l'étalonnage des distances.
// Contrat des écrans de la coque (12.2) : ouvrir(racine, options) ; l'image et les vues dans la page
// (au centre), les réglages dans le panneau de tâches (✓ Enregistrer, ✗ Annuler), comme les autres écrans
// de l'équipe (js/coque/ecran.js) ; ouvert seul (sans la coque), preparerEcran fabrique les deux colonnes.

import { api } from '../api.js';
import { creerVueCamera } from '../camera/flux.js';
import { blocAvance, panneauEdition, preparerEcran } from '../coque/ecran.js';
import { abonner } from '../direct.js';
import * as F from '../formulaire.js';
import * as G from '../geometrie.js';
import { age, aide, champNombreFacultatif, creerEditeur, note } from '../equipe/commun.js';

const AIDE = 'La caméra de poitrine voit les visiteurs. Réglez ici sa place sur le robot et la détection : '
  + 'l\'image en direct montre ce qu\'elle voit, avec un cadre autour de chaque personne. Mesurez sa position '
  + 'sur le robot debout (x vers l\'avant, y vers sa gauche, z vers le haut, depuis le sol entre les pieds).';
const ABSENT = 'Ce fichier est facultatif : sans caméra, le robot voit les visiteurs avec son LiDAR seulement. '
  + 'Partez de l\'exemple, ou du préréglage See3CAM_11CUG, puis mesurez la position de la caméra sur le robot.';
const SVG = 'http://www.w3.org/2000/svg';
const ECHELLE = 60;          // pixels par mètre, vue de dessus
const COTE_ECHELLE = 120;    // pixels par mètre, vue de côté
const SOURCES = [
  { id: 'poitrine', texte: 'Caméra', titre: 'L\'image de la caméra, avec les cadres des visiteurs' },
  { id: 'visiteurs', texte: 'Image analysée', titre: 'L\'image dessinée par g1-visiteurs --image (cadres et distances)' },
];
// Défauts du nœud de la caméra (camera_usb) et de la détection, montrés quand le fichier ne dit rien
const DEFAUTS = { exposition: 'auto', temps_100us: 156, gain: 4, frequence_hz: 10, largeur: 640, qualite_jpeg: 70,
  taille_personne_m: 1.7, correction_distance: 1.0 };

function svg(balise, attributs, parent) {
  const e = document.createElementNS(SVG, balise);
  Object.keys(attributs || {}).forEach((k) => e.setAttribute(k, attributs[k]));
  if (parent) parent.appendChild(e);
  return e;
}

function texteSvg(parent, x, y, texte, classe) {
  const t = svg('text', { x: x, y: y, class: classe || 'cam-texte' }, parent);
  t.textContent = texte;
  return t;
}

export function ouvrir(racine, options) {
  const ecran = preparerEcran(racine, options);
  const afficherMessage = (texte, genre) => ecran.coque.message(texte, genre);
  let editeur = null;
  let direct = null;          // dernier message de /ws/etat
  let peripheriques = [];
  let vueCamera = null;
  let source = 'poitrine';
  // Équipe › ⚙ Avancé › Réglages de la caméra (commande « reglages ») : le bloc des réglages avancés s'ouvre
  let avanceOuvert = ecran.commande === 'reglages';

  function actions() {
    return { modifie: () => editeur.modifie(), enregistrer: () => editeur.enregistrer(),
      annuler: () => editeur.abandonner() };
  }

  function rendre(etat) {
    const d = etat.donnees;
    const zone = etat.zones.contenu;
    zone.innerHTML = '';
    const gauche = F.el('div', 'equipe-liste cam-liste');
    zone.appendChild(gauche);

    const vues = F.el('div', 'cam-vues');
    const dessus = F.el('div', 'cam-vue');
    dessus.appendChild(F.el('h3', 'panneau-titre', 'Vue de dessus'));
    const svgDessus = svg('svg', { class: 'cam-svg', viewBox: '-300 -330 600 400', 'data-role': 'vue-dessus' }, dessus);
    const profil = F.el('div', 'cam-vue cam-vue-cote');
    profil.appendChild(F.el('h3', 'panneau-titre', 'Vue de côté'));
    const svgCote = svg('svg', { class: 'cam-svg', viewBox: '-60 -230 420 260', 'data-role': 'vue-cote' }, profil);
    vues.appendChild(dessus);
    vues.appendChild(profil);
    gauche.appendChild(vues);
    const etatDirect = F.el('p', 'equipe-annonce');
    etatDirect.setAttribute('data-role', 'detections');
    gauche.appendChild(etatDirect);
    gauche.appendChild(F.el('p', 'panneau-note', 'Orange : le robot (pieds) ; bleu : ce que voit la caméra, '
      + 'jusqu\'à la distance maximale de détection ; points verts : visiteurs vus par la caméra ; points gris : '
      + 'personnes vues par le LiDAR. Une case : 1 m.'));
    dessinerDessus(svgDessus, d);
    dessinerCote(svgCote, d);
    majDetections();
    panneauCamera(etat, panneauEdition(ecran.panneau, 'Caméra', null, actions()).corps);
  }

  function dessinerDessus(s, d) {
    s.innerHTML = '';
    const g = svg('g', {}, s);
    for (let i = -5; i <= 5; i++) {
      svg('line', { x1: i * ECHELLE, y1: -330, x2: i * ECHELLE, y2: 70, class: 'cam-grille' }, g);
    }
    for (let j = -5; j <= 1; j++) {
      svg('line', { x1: -300, y1: j * ECHELLE, x2: 300, y2: j * ECHELLE, class: 'cam-grille' }, g);
    }
    // repère : x du robot vers le haut de l'image, y vers la gauche
    const pos = d.camera.position;
    const det = d.detection;
    const champ = d.camera.champ_horizontal_deg || 0;
    const portee = det.distance_max_m;
    const cx = -pos.y * ECHELLE;
    const cy = -pos.x * ECHELLE;
    if (champ > 0) {
      const demi = G.radians(Math.min(champ, 359) / 2);
      const pas = 24;
      const points = [[cx, cy]];
      for (let k = 0; k <= pas; k++) {
        const a = pos.lacet - demi + (2 * demi * k) / pas;
        points.push([cx - Math.sin(a) * portee * ECHELLE, cy - Math.cos(a) * portee * ECHELLE]);
      }
      svg('polygon', { points: points.map((p) => p.join(',')).join(' '), class: 'cam-champ', 'data-role': 'champ' }, g);
    } else {
      svg('line', { x1: cx, y1: cy, x2: cx - Math.sin(pos.lacet) * portee * ECHELLE, y2: cy - Math.cos(pos.lacet) * portee * ECHELLE,
        class: 'cam-axe' }, g);
    }
    // robot : pieds et buste du G1 vus de dessus (environ 0,3 × 0,45 m)
    svg('rect', { x: -0.225 * ECHELLE, y: -0.15 * ECHELLE, width: 0.45 * ECHELLE, height: 0.3 * ECHELLE, rx: 6, class: 'cam-robot' }, g);
    svg('line', { x1: 0, y1: 0, x2: 0, y2: -0.45 * ECHELLE, class: 'cam-robot-cap' }, g);
    svg('circle', { cx: cx, cy: cy, r: 6, class: 'cam-camera' }, g);
    texteSvg(g, 8, -0.5 * ECHELLE, 'avant (x)');
    texteSvg(g, -290, 60, '1 case = 1 m');
    const calque = svg('g', { 'data-role': 'personnes' }, g);
    dessinerPersonnes(calque);
  }

  function dessinerPersonnes(calque) {
    if (!calque) return;
    calque.innerHTML = '';
    const ajouter = (liste, classe) => (liste || []).forEach((p) => {
      if (typeof p.x !== 'number' || typeof p.y !== 'number') return;
      const c = svg('circle', { cx: -p.y * ECHELLE, cy: -p.x * ECHELLE, r: 8, class: classe }, calque);
      const t = svg('title', {}, c);
      t.textContent = 'n° ' + p.id + ' : ' + G.nb(p.distance_m) + ' m, confiance ' + G.nb(p.confiance);
      texteSvg(calque, -p.y * ECHELLE + 10, -p.x * ECHELLE - 8, String(p.id), 'cam-texte-petit');
    });
    const lidar = direct && direct.personnes && !direct.personnes.perime ? direct.personnes.personnes : [];
    const camera = direct && direct.visiteurs && !direct.visiteurs.perime ? direct.visiteurs.personnes : [];
    ajouter(lidar, 'cam-lidar');
    ajouter(camera, 'cam-visiteur');
  }

  function dessinerCote(s, d) {
    s.innerHTML = '';
    const g = svg('g', {}, s);
    svg('line', { x1: -60, y1: 0, x2: 360, y2: 0, class: 'cam-sol' }, g);
    // silhouette simplifiée du G1 (1,32 m), vue de profil, regard vers la droite
    svg('rect', { x: -0.08 * COTE_ECHELLE, y: -1.32 * COTE_ECHELLE, width: 0.16 * COTE_ECHELLE, height: 0.55 * COTE_ECHELLE, rx: 8,
      class: 'cam-robot' }, g);
    svg('rect', { x: -0.05 * COTE_ECHELLE, y: -0.77 * COTE_ECHELLE, width: 0.1 * COTE_ECHELLE, height: 0.77 * COTE_ECHELLE, rx: 5,
      class: 'cam-robot' }, g);
    const pos = d.camera.position;
    const cx = pos.x * COTE_ECHELLE;
    const cy = -pos.z * COTE_ECHELLE;
    const champVertical = d.camera.champ_horizontal_deg
      ? 2 * Math.atan(Math.tan(G.radians(Math.min(d.camera.champ_horizontal_deg, 170)) / 2) * d.camera.hauteur / d.camera.largeur)
      : 0;
    const portee = Math.min(d.detection.distance_max_m, 2.8) * COTE_ECHELLE;
    // tangage positif : la caméra regarde vers le bas (rotation autour de y, convention ROS)
    const bords = champVertical > 0 ? [pos.tangage - champVertical / 2, pos.tangage + champVertical / 2] : [pos.tangage];
    bords.forEach((a) => {
      svg('line', { x1: cx, y1: cy, x2: cx + Math.cos(a) * portee, y2: cy + Math.sin(a) * portee, class: 'cam-axe' }, g);
    });
    svg('circle', { cx: cx, cy: cy, r: 5, class: 'cam-camera' }, g);
    texteSvg(g, cx + 8, cy - 8, G.nb(pos.z) + ' m');
    texteSvg(g, 200, 20, 'sol');
  }

  function majDetections() {
    const zone = ecran.vue.querySelector('[data-role="detections"]');
    if (!zone) return;
    const v = direct && direct.visiteurs;
    if (!direct || !direct.ros || !direct.ros.actif) {
      zone.textContent = 'ROS 2 n\'est pas actif dans le serveur de l\'Atelier : les visiteurs ne s\'affichent pas.';
    } else if (!v) {
      zone.textContent = 'Aucun visiteur reçu : lancez g1-visiteurs sur ce PC (ou la fausse caméra : ros2 run '
        + 'g1_equipe fausse_camera).';
    } else {
      const n = (v.personnes || []).length;
      zone.textContent = n + ' visiteur' + (n > 1 ? 's' : '') + ' vu' + (n > 1 ? 's' : '') + ' par la caméra ('
        + age(v) + (v.perime ? ', ancien' : '') + ')';
    }
    zone.setAttribute('data-visiteurs', v && !v.perime ? String((v.personnes || []).length) : '');
    dessinerPersonnes(ecran.vue.querySelector('[data-role="personnes"]'));
  }

  // ---------------------------------------------------------------- image en direct

  function monterDirect() {
    const bloc = F.el('section', 'cam-direct carte-section');
    bloc.setAttribute('data-role', 'camera-direct');
    const tete = F.el('div', 'cam-direct-tete');
    tete.appendChild(F.el('h3', 'panneau-titre', 'Image en direct'));
    const choix = F.el('div', 'cam-sources');
    choix.setAttribute('role', 'radiogroup');
    SOURCES.forEach((s) => {
      const b = F.el('button', 'bouton bouton-petit cam-source', s.texte);
      b.type = 'button';
      b.title = s.titre;
      b.setAttribute('data-source', s.id);
      b.setAttribute('role', 'radio');
      b.addEventListener('click', () => changerSource(s.id));
      choix.appendChild(b);
    });
    tete.appendChild(choix);
    bloc.appendChild(tete);
    const vue = F.el('div', 'cam-direct-vue');
    bloc.appendChild(vue);
    const aideEl = page.querySelector('[data-role="aide"]');
    if (aideEl && aideEl.parentNode) aideEl.parentNode.insertBefore(bloc, aideEl.nextSibling);
    else page.appendChild(bloc);
    return { bloc: bloc, vue: vue, choix: choix };
  }

  function changerSource(id) {
    source = id;
    if (vueCamera) vueCamera.detruire();
    vueCamera = creerVueCamera(blocDirect.vue, { source: id, cadres: id === 'poitrine' });
    vueCamera.demarrer();
    blocDirect.choix.querySelectorAll('[data-source]').forEach((b) => {
      const actif = b.getAttribute('data-source') === id;
      b.classList.toggle('actif', actif);
      b.setAttribute('aria-checked', actif ? 'true' : 'false');
    });
  }

  // ---------------------------------------------------------------- réglages

  function panneauCamera(etat, z) {
    const d = etat.donnees;
    const schema = etat.infos.fichiers.camera.schema;
    const aideCam = (c) => aide(schema, ['properties', 'camera', 'properties', c]);
    const modifier = (f) => editeur.modifier(f);
    F.champTexte(z, 'Modèle', d.camera.modele || '', (v) => modifier((x) => {
      if (v.trim()) x.camera.modele = v.trim();
      else delete x.camera.modele;
    }), { indice: 'ex. See3CAM_11CUG' });
    const prereglages = etat.infos.prereglages_camera || {};
    Object.keys(prereglages).forEach((nom) => {
      F.bouton(z, 'Préréglage ' + nom, () => {
        const p = prereglages[nom];
        // la même caméra branchée sur ce PC : son nom stable (numéro de série), qui sert aussi sur le robot
        const branchee = peripheriques.find((c) => c.by_id && (c.nom || '').indexOf(p.modele) >= 0);
        modifier((x) => {
          x.camera.modele = p.modele;
          x.camera.largeur = p.largeur;
          x.camera.hauteur = p.hauteur;
          x.camera.ips = p.ips;
          if (branchee) x.camera.peripherique = branchee.by_id;
        });
        afficherMessage(p.note, 'info');
      });
    });
    const per = F.champTexte(z, 'Périphérique', d.camera.peripherique, (v) => modifier((x) => { x.camera.peripherique = v.trim() || x.camera.peripherique; }));
    per.setAttribute('list', 'cam-peripheriques');
    const liste = F.el('datalist');
    liste.id = 'cam-peripheriques';
    peripheriques.forEach((c) => {
      [c.by_id, c.peripherique].forEach((chemin) => {
        if (!chemin) return;
        const option = F.el('option');
        option.value = chemin;
        option.textContent = c.nom;
        liste.appendChild(option);
      });
    });
    z.appendChild(liste);
    note(z, peripheriques.length
      ? 'Caméras branchées sur cet ordinateur : ' + peripheriques.map((c) => c.peripherique + ' (' + c.nom
        + (c.usb_mbps ? ', USB ' + (c.usb_mbps >= 5000 ? '3' : '2') : '') + ')').join(', ')
        + '. Sur le robot, le conteneur reçoit la See3CAM sous le nom /dev/g1_camera : rien à changer ici.'
      : 'Aucune caméra branchée sur cet ordinateur. Sur le robot, le conteneur reçoit la See3CAM sous le nom '
        + '/dev/g1_camera (g1-jetson verifier la montre).');
    F.champNombre(z, 'Largeur', d.camera.largeur, { pas: 1, min: 160, max: 4096, unite: 'px', decimales: 0 },
      (v) => modifier((x) => { x.camera.largeur = Math.round(v); }));
    F.champNombre(z, 'Hauteur', d.camera.hauteur, { pas: 1, min: 120, max: 3072, unite: 'px', decimales: 0 },
      (v) => modifier((x) => { x.camera.hauteur = Math.round(v); }));
    F.champNombre(z, 'Images par seconde', d.camera.ips, { pas: 1, min: 1, max: 120, decimales: 0 },
      (v) => modifier((x) => { x.camera.ips = Math.round(v); }));
    champNombreFacultatif(z, 'Champ horizontal', d.camera.champ_horizontal_deg, { pas: 1, min: 1, max: 200, unite: '°', indice: 'à mesurer' },
      (v) => modifier((x) => {
        if (v === null) delete x.camera.champ_horizontal_deg;
        else x.camera.champ_horizontal_deg = v;
      }));
    note(z, aideCam('champ_horizontal_deg') + ' Il dépend de l\'objectif monté sur la See3CAM.');

    F.titre(z, 'Position sur le robot');
    const pos = d.camera.position;
    [['x', 'x (vers l\'avant)', -1, 1], ['y', 'y (vers la gauche)', -1, 1], ['z', 'z (hauteur)', 0, 2]].forEach((c) => {
      F.champNombre(z, c[1], pos[c[0]], { pas: 0.01, min: c[2], max: c[3], unite: 'm' },
        (v) => modifier((x) => { x.camera.position[c[0]] = G.arrondir(v, 3); }));
    });
    [['roulis', 'Roulis'], ['tangage', 'Tangage'], ['lacet', 'Lacet']].forEach((c) => {
      F.champNombre(z, c[1], G.degres(pos[c[0]]), { pas: 1, min: -180, max: 180, unite: '°', decimales: 1 },
        (v) => modifier((x) => { x.camera.position[c[0]] = G.arrondir(G.radians(v), 4); }));
    });
    note(z, 'Tangage positif : la caméra regarde vers le bas. Une caméra inclinée de 10 à 15° vers le haut a un '
      + 'tangage de −10 à −15°. Lacet : 0 si elle regarde droit devant, positif vers la gauche. À mesurer au '
      + 'mètre ruban et au rapporteur, robot debout.');

    F.titre(z, 'Détection des visiteurs');
    F.caseACocher(z, 'Utiliser la caméra', d.detection.actif, (v) => modifier((x) => { x.detection.actif = v; }));
    F.champTexte(z, 'Modèle de détection', d.detection.modele || '', (v) => modifier((x) => {
      if (v.trim()) x.detection.modele = v.trim();
      else delete x.detection.modele;
    }), { indice: 'ex. yolo11n-pose.pt, dans ~/robot-g1/modeles/' });
    F.champNombre(z, 'Confiance minimale', d.detection.confiance_min, { pas: 0.05, min: 0, max: 1, decimales: 2 },
      (v) => modifier((x) => { x.detection.confiance_min = Math.min(1, Math.max(0, v)); }));
    F.champNombre(z, 'Distance maximale', d.detection.distance_max_m, { pas: 0.5, min: 0.5, max: 20, unite: 'm' },
      (v) => modifier((x) => { x.detection.distance_max_m = v; }));
    F.champNombre(z, 'Fréquence de publication', d.detection.frequence_hz, { pas: 1, min: 1, max: 60, unite: 'Hz' },
      (v) => modifier((x) => { x.detection.frequence_hz = v; }));
    note(z, 'Personnes plus loin, ou moins sûres, ignorées. La caméra ne mesure pas la distance : g1-visiteurs '
      + 'l\'estime par la taille de la personne dans l\'image.');
    reglagesAvances(z, d, modifier);
  }

  // Réglages rares (I3) : exposition et publication des images (nœud de la caméra sur le robot),
  // étalonnage des distances. Vide : le défaut du nœud ; une valeur l'écrit dans camera.yaml.
  function reglagesAvances(z, d, modifier) {
    const bloc = blocAvance(z, 'Réglages avancés');
    const details = bloc.parentNode;
    details.setAttribute('data-role', 'reglages-avances');
    details.open = avanceOuvert;
    details.addEventListener('toggle', () => { avanceOuvert = details.open; });
    const expo = d.camera.exposition || {};
    const publi = d.camera.publication || {};
    const sousBloc = (x, cle) => {
      if (!x.camera[cle]) x.camera[cle] = cle === 'exposition' ? { mode: DEFAUTS.exposition } : {};
      return x.camera[cle];
    };
    const nettoyer = (x, cle) => {
      const b = x.camera[cle];
      if (b && !Object.keys(b).length) delete x.camera[cle];
    };
    F.listeDeroulante(bloc, 'Exposition', expo.mode || DEFAUTS.exposition,
      [{ id: 'auto', texte: 'automatique (conseillé)' }, { id: 'manuelle', texte: 'manuelle' }],
      (v) => modifier((x) => { sousBloc(x, 'exposition').mode = v; }));
    if ((expo.mode || DEFAUTS.exposition) === 'manuelle') {
      champNombreFacultatif(bloc, 'Temps d\'exposition', expo.temps_100us === undefined ? null : expo.temps_100us / 10,
        { pas: 0.1, min: 0.1, max: 10000, unite: 'ms', indice: String(DEFAUTS.temps_100us / 10) },
        (v) => modifier((x) => {
          const e = sousBloc(x, 'exposition');
          if (v === null) delete e.temps_100us;
          else e.temps_100us = Math.max(1, Math.round(v * 10));
        }));
      champNombreFacultatif(bloc, 'Gain', expo.gain === undefined ? null : expo.gain,
        { pas: 1, min: 0, max: 1000, indice: String(DEFAUTS.gain) },
        (v) => modifier((x) => {
          const e = sousBloc(x, 'exposition');
          if (v === null) delete e.gain;
          else e.gain = Math.round(v);
        }));
    }
    note(bloc, 'La See3CAM démarre en exposition manuelle (image noire dans une pièce sombre) : le nœud de la '
      + 'caméra la met en automatique au démarrage, sauf réglage manuel ici.');
    [['frequence_hz', 'Images publiées par seconde', 'Hz', 1, 30, 1],
      ['largeur', 'Largeur des images publiées', 'px', 160, 4096, 2],
      ['qualite_jpeg', 'Qualité JPEG', '', 10, 100, 1]].forEach((c) => {
      champNombreFacultatif(bloc, c[1], publi[c[0]] === undefined ? null : publi[c[0]],
        { pas: c[5], min: c[3], max: c[4], unite: c[2], indice: String(DEFAUTS[c[0]]) },
        (v) => modifier((x) => {
          const p = sousBloc(x, 'publication');
          if (v === null) delete p[c[0]];
          else p[c[0]] = c[0] === 'frequence_hz' ? v : Math.round(v);
          nettoyer(x, 'publication');
        }));
    });
    note(bloc, 'Images envoyées par le robot à l\'Atelier et à g1-visiteurs (vide : 10 par seconde, 640 pixels de '
      + 'large, qualité 70).');
    champNombreFacultatif(bloc, 'Taille d\'une personne', d.detection.taille_personne_m === undefined ? null
      : d.detection.taille_personne_m, { pas: 0.05, min: 1, max: 2.2, unite: 'm', indice: String(DEFAUTS.taille_personne_m) },
    (v) => modifier((x) => {
      if (v === null) delete x.detection.taille_personne_m;
      else x.detection.taille_personne_m = v;
    }));
    champNombreFacultatif(bloc, 'Correction des distances', d.detection.correction_distance === undefined ? null
      : d.detection.correction_distance, { pas: 0.01, min: 0.5, max: 2, indice: String(DEFAUTS.correction_distance) },
    (v) => modifier((x) => {
      if (v === null) delete x.detection.correction_distance;
      else x.detection.correction_distance = v;
    }));
    note(bloc, 'Étalonnage : posez des repères au sol à 1, 2, 3 et 4 m, lisez la distance affichée pour une personne '
      + 'debout sur chacun, puis mettez ici le rapport (distance vraie ÷ distance affichée, en moyenne).');
  }

  function panneauSansFichier() {
    if (editeur && editeur.etat.donnees) return;
    const z = panneauEdition(ecran.panneau, 'Caméra', null, actions()).corps;
    F.paragraphe(z, 'Ce lieu n\'a pas encore de réglages de caméra : partez de l\'exemple (au centre), '
      + 'puis réglez ici la caméra, sa place sur le robot et la détection.', 'panneau-note');
  }

  const page = F.el('div', 'page-contenu cam-page');
  ecran.vue.appendChild(page);
  editeur = creerEditeur(page, 'camera', {
    titre: 'Caméra', aide: AIDE, absent: ABSENT, rendre: rendre, sansBarre: true,
    apresChargement: async () => {
      try {
        // les nœuds « index1 » d'une caméra ne donnent que des métadonnées, pas d'image
        peripheriques = (await api.lire('/api/equipe/cameras')).filter((c) => !c.by_id || /index0$/.test(c.by_id));
      } catch (e) {
        peripheriques = [];
      }
    },
  });
  editeur.pret.then(panneauSansFichier);
  const blocDirect = monterDirect();
  changerSource(source);
  const desabonner = abonner((e) => {
    direct = e;
    majDetections();
  });

  return {
    modifie: () => editeur.modifie(),
    enregistrer: () => editeur.enregistrer(),
    commande: (nom) => {
      if (nom === 'reglages') {
        avanceOuvert = true;
        const bloc = document.querySelector('[data-role="reglages-avances"]');
        if (bloc) bloc.open = true;
      }
    },
    fermer: () => {
      desabonner();
      if (vueCamera) vueCamera.detruire();
      vueCamera = null;
    },
  };
}
