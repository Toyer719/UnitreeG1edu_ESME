// Caméra (vague 4, section 11.6 du plan) : écran de l'agent Équipe.
// La caméra See3CAM de l'équipe (camera.yaml) : périphérique, image, position et orientation sur
// le robot (repère base_link), et réglages de la détection des visiteurs. Une vue de dessus et une
// vue de côté montrent ce que la caméra voit ; les visiteurs publiés sur /visiteurs/detectes (et
// les personnes du LiDAR, /personnes/lidar) s'y dessinent en direct.

import { api } from '../api.js';
import { abonner } from '../direct.js';
import * as F from '../formulaire.js';
import * as G from '../geometrie.js';
import { afficherMessage } from '../messages.js';
import { age, aide, champNombreFacultatif, creerEditeur, note } from '../equipe/commun.js';

const AIDE = 'La caméra des visiteurs est fixée sur le robot. Ses réglages servent au nœud caméra de l\'équipe '
  + '(détection des personnes, publiée sur /visiteurs/detectes) ; sa position et son orientation sont à mesurer sur '
  + 'le robot, dans le repère du robot (base_link : x vers l\'avant, y vers sa gauche, z vers le haut, depuis le sol '
  + 'entre les pieds).';
const ABSENT = 'Ce fichier est facultatif : sans caméra, le robot voit les visiteurs avec son LiDAR seulement. '
  + 'Partez de l\'exemple, ou du préréglage See3CAM_11CUG, puis mesurez la position de la caméra sur le robot.';
const SVG = 'http://www.w3.org/2000/svg';
const ECHELLE = 60;          // pixels par mètre, vue de dessus
const COTE_ECHELLE = 120;    // pixels par mètre, vue de côté

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

export function ouvrir(racine) {
  let editeur = null;
  let direct = null;          // dernier message de /ws/etat
  let peripheriques = [];

  function rendre(etat) {
    const d = etat.donnees;
    const zone = etat.zones.contenu;
    zone.innerHTML = '';
    const espace = F.el('div', 'espace-deux equipe-espace');
    const gauche = F.el('div', 'equipe-liste');
    const cote = F.el('div', 'cote');
    const panneau = F.el('div', 'panneau');
    panneau.setAttribute('data-role', 'panneau');
    cote.appendChild(panneau);
    espace.appendChild(gauche);
    espace.appendChild(cote);
    zone.appendChild(espace);

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
    const legende = F.el('p', 'panneau-note', 'Orange : le robot (pieds) ; bleu : le champ de la caméra, jusqu\'à la distance '
      + 'maximale de détection ; points verts : visiteurs de /visiteurs/detectes (caméra) ; points gris : personnes '
      + 'du LiDAR (/personnes/lidar). Une case : 1 m.');
    gauche.appendChild(legende);
    dessinerDessus(svgDessus, d);
    dessinerCote(svgCote, d);
    majDetections();
    panneauCamera(etat, panneau);
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
      t.textContent = 'id ' + p.id + ' : ' + G.nb(p.distance_m) + ' m, confiance ' + G.nb(p.confiance);
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
    const zone = racine.querySelector('[data-role="detections"]');
    if (!zone) return;
    const v = direct && direct.visiteurs;
    if (!direct || !direct.ros || !direct.ros.actif) {
      zone.textContent = 'ROS 2 n\'est pas actif dans le serveur de l\'Atelier : les détections ne s\'affichent pas.';
    } else if (!v) {
      zone.textContent = 'Aucune détection reçue sur /visiteurs/detectes : le nœud caméra de l\'équipe (ou la fausse '
        + 'caméra : ros2 run g1_equipe fausse_camera) ne publie pas encore.';
    } else {
      const n = (v.personnes || []).length;
      zone.textContent = n + ' visiteur' + (n > 1 ? 's' : '') + ' vu' + (n > 1 ? 's' : '') + ' par la caméra ('
        + age(v) + (v.perime ? ', ancien' : '') + ')';
    }
    zone.setAttribute('data-visiteurs', v && !v.perime ? String((v.personnes || []).length) : '');
    dessinerPersonnes(racine.querySelector('[data-role="personnes"]'));
  }

  function panneauCamera(etat, z) {
    const d = etat.donnees;
    const schema = etat.infos.fichiers.camera.schema;
    const aideCam = (c) => aide(schema, ['properties', 'camera', 'properties', c]);
    const modifier = (f) => editeur.modifier(f);
    z.innerHTML = '';
    F.titre(z, 'Caméra');
    F.champTexte(z, 'Modèle', d.camera.modele || '', (v) => modifier((x) => {
      if (v.trim()) x.camera.modele = v.trim();
      else delete x.camera.modele;
    }), { indice: 'ex. See3CAM_11CUG' });
    const prereglages = etat.infos.prereglages_camera || {};
    Object.keys(prereglages).forEach((nom) => {
      F.bouton(z, 'Préréglage ' + nom, () => {
        const p = prereglages[nom];
        modifier((x) => {
          x.camera.modele = p.modele;
          x.camera.largeur = p.largeur;
          x.camera.hauteur = p.hauteur;
          x.camera.ips = p.ips;
        });
        afficherMessage(p.note, 'info');
      });
    });
    const per = F.champTexte(z, 'Périphérique', d.camera.peripherique, (v) => modifier((x) => { x.camera.peripherique = v.trim() || x.camera.peripherique; }));
    per.setAttribute('list', 'cam-peripheriques');
    const liste = F.el('datalist');
    liste.id = 'cam-peripheriques';
    peripheriques.forEach((c) => {
      const o = F.el('option');
      o.value = c.peripherique;
      o.textContent = c.nom;
      liste.appendChild(o);
    });
    z.appendChild(liste);
    note(z, peripheriques.length
      ? 'Caméras branchées sur cet ordinateur : ' + peripheriques.map((c) => c.peripherique + ' (' + c.nom + ')').join(', ')
        + '. Sur le robot, le numéro peut changer : « v4l2-ctl --list-devices » sur le Jetson.'
      : 'Aucune caméra branchée sur cet ordinateur. Sur le robot : « v4l2-ctl --list-devices » sur le Jetson.');
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

    F.titre(z, 'Position sur le robot (base_link)');
    const pos = d.camera.position;
    [['x', 'x (vers l\'avant)', -1, 1], ['y', 'y (vers la gauche)', -1, 1], ['z', 'z (hauteur)', 0, 2]].forEach((c) => {
      F.champNombre(z, c[1], pos[c[0]], { pas: 0.01, min: c[2], max: c[3], unite: 'm' },
        (v) => modifier((x) => { x.camera.position[c[0]] = G.arrondir(v, 3); }));
    });
    [['roulis', 'Roulis'], ['tangage', 'Tangage'], ['lacet', 'Lacet']].forEach((c) => {
      F.champNombre(z, c[1], G.degres(pos[c[0]]), { pas: 1, min: -180, max: 180, unite: '°', decimales: 1 },
        (v) => modifier((x) => { x.camera.position[c[0]] = G.arrondir(G.radians(v), 4); }));
    });
    note(z, 'Tangage positif : la caméra regarde vers le bas (convention de ROS). Une caméra inclinée de 10 à 15° vers le '
      + 'haut a un tangage de −10 à −15°. Lacet : 0 si elle regarde droit devant, positif vers la gauche. À mesurer au '
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
    note(z, 'Personnes plus loin, ou moins sûres, ignorées. La See3CAM ne mesure pas la distance : le nœud de l\'équipe '
      + 'l\'estime par la taille de la personne dans l\'image.');
  }

  editeur = creerEditeur(racine, 'camera', {
    titre: 'Caméra', aide: AIDE, absent: ABSENT, rendre: rendre,
    apresChargement: async () => {
      try {
        peripheriques = await api.lire('/api/equipe/cameras');
      } catch (e) {
        peripheriques = [];
      }
    },
  });
  const desabonner = abonner((e) => {
    direct = e;
    majDetections();
  });

  return {
    modifie: () => editeur.modifie(),
    fermer: () => desabonner(),
  };
}
