// Carte 3D de l'Atelier (vague 5, section 12.3 du plan) : le nuage de points du scan (ou le monde de
// Gazebo en Simulation) dans une vue three.js qu'on tourne et déplace, où l'on pose l'accueil, les salles
// et leur orientation. Module de l'agent Carte 3D.
//
// Repère : celui de la carte (map), z vers le haut, sans aucune conversion : x, y et theta sont ceux du
// plan 2D, de salles.yaml, itineraires.yaml et zones.yaml ; le sol est à z = 0 (le nuage d'affichage a
// déjà le plan du sol soustrait) ; la flèche d'une pose est tournée de theta autour de z.
//
// Gestes (I7) : clic gauche glissé = tourner ; clic droit glissé, ou Maj + gauche = déplacer ; molette =
// zoom vers le point du sol sous le pointeur ; clic du milieu glissé = tourner (Ctrl + milieu : déplacer,
// comme SolidWorks) ; tactile : un doigt tourne, deux doigts déplacent et zooment. Clavier (la vue a le
// focus après un clic) : flèches = déplacer (Maj : tourner), + et - = zoomer, 1 Dessus, 2 Iso, 3 Face,
// F = recadrer, Échap = geste en cours annulé et retour à « naviguer ». Double-clic sur le sol : recentrer.
// La caméra ne passe jamais sous le sol et ne bouge jamais d'elle-même, sauf au premier affichage du
// nuage, du monde ou de la carte 2D, et sur demande (vue, recadrer, centrerSur).
//
// Outils (I8) : « naviguer » : clic sur un repère = le choisir (surSelection), glisser un repère = le
// déplacer, glisser la poignée blanche au bout de la flèche du repère choisi = le tourner ; « salle » et
// « accueil » : un appui sur le sol pose le point (accroché à 5 cm), glisser depuis là règle l'orientation
// (accrochée à 15°, Maj : libre), glisser le repère en cours le déplace ; « noeud » : un appui pose ou
// déplace le nœud ; « mesurer » : deux clics au sol, la distance s'affiche. Chaque étape émet surPose
// {outil, genre, id, x, y, theta, fini, geste} (fini vrai au relâchement ; geste : poser, deplacer,
// tourner) ; Échap pendant un geste : {…, fini: true, annule: true} avec la pose d'avant (rien pour un
// nouvel élément). C'est l'écran (Salles, ou edition.js) qui garde la liste, l'enregistre, et rappelle
// afficherSalles (afficherItineraires pour un nœud) avec la liste à jour, pendant l'appel de surPose : sinon
// la pose n'a pas été retenue, et le repère revient à sa place. surPose(fn, {genres: ['salle']}) : l'écran
// ne reçoit que les poses de ces genres. Un repère ne se glisse ou ne se tourne que si un écran écoute les
// poses de son genre ; sinon le glisser tourne la vue, et un clic le choisit toujours. Pendant le glissé
// d'un nœud, ses couloirs le suivent.
//
// Nuage : les points du sol (moins de SEUIL_SOL) n'écrivent pas la profondeur et sont dessinés avant les
// zones, couloirs et trajets, qui restent visibles sur un sol dense ; les murs et les meubles les cachent.
// Les noms des salles se placent sans se chevaucher (à droite de la tête, sinon à gauche, dessus,
// dessous ; sinon cachés, la tête numérotée reste). Les vues cadrent le contenu sous la barre flottante.
//
// Rendu à la demande (pas de boucle au repos). Sans WebGL : un message ([data-role=carte3d-sans-webgl]),
// etat().webgl faux, et toutes les méthodes restent appelables sans effet.

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/OrbitControls.js';
import { dansPolygone } from '../geometrie.js';
import * as G3 from './geometrie3d.js';
import * as R from './reperes.js';
import { construireMonde, lireSTL, meshDuMaillage } from './monde3d.js';

export const VUES = ['dessus', 'iso', 'face'];
export const CALQUES = ['nuage', 'carte2d', 'monde', 'points', 'itineraires', 'zones', 'robot', 'pietons', 'trajet'];
export const OUTILS = ['naviguer', 'salle', 'accueil', 'noeud', 'mesurer'];
export const HAUTEUR_COUPE = 2.2;      // m : points plus hauts cachés par défaut (plafond)
export const FOND = '#1e1e1e';         // fond de la vue, quel que soit le thème (--vue-fond)
export const TAILLE_POINTS = 0.05;     // m : taille des points par défaut (la grille du nuage)
export const TAILLES_POINTS = { min: 0.02, max: 0.15 };
// m : les points plus bas sont le sol. Ils sont dessinés sans écrire la profondeur, après la carte 2D et
// avant les zones, couloirs et trajets : ces repères posés au sol restent visibles sur un sol dense, et
// les murs et les meubles les cachent toujours.
export const SEUIL_SOL = 0.12;

const NOMS_CALQUES = {
  nuage: 'Nuage de points', carte2d: 'Carte 2D au sol', monde: 'Monde', points: 'Accueil et salles',
  itineraires: 'Itinéraires', zones: 'Zones', robot: 'Robot', pietons: 'Piétons', trajet: 'Trajet du scan',
};
const NOMS_VUES = { dessus: 'Dessus', iso: 'Iso', face: 'Face' };
const OUTILS_POSE = ['salle', 'accueil', 'noeud'];
const VUES_SOLIDWORKS = { 5: 'dessus', 7: 'iso', 1: 'face' };
const CHAMP_VISION = 50;               // degrés, vertical
const DISTANCES = { min: 0.6, max: 600 };
const ECHELLE_REPERES = 14;            // m : au-delà, les repères grossissent pour rester visibles
const TAILLE_MIN_POINT_PX = 1.5;       // px : un point lointain ne disparaît jamais tout à fait
const COUPE_BASSE = -0.5;              // m : points sous le sol (reflets) cachés
const MARGE_HAUT = 56;                 // px : la barre flottante en haut de la vue (coque : 48 px ; module : 46 px)
const HAUTEUR_ETIQUETTE = 22;          // px : nom d'une salle (carte3d.css : ligne de 18 px, 2 px en haut et en bas)
const RAYON_TETE = { salle: 12, principal: 14 };   // px : demi-largeur des têtes d'épingle (carte3d.css)

// Couleurs : les jetons de theme.css (lus par getComputedStyle), avec ces valeurs en repli
const JETONS = {
  fond: ['--vue-fond', FOND], grille: ['--vue-grille', '#34343c'], accueil: ['--repere-accueil', '#ffa724'],
  salle: ['--repere-salle', '#6577e0'], choisi: ['--repere-choisi', '#ffffff'], robot: ['--repere-robot', '#e8772e'],
  itineraire: ['--itineraire', '#22d3ee'], zoneInterdite: ['--zone-interdite', '#ef4444'],
  zoneLente: ['--zone-lente', '#f59e0b'], trajet: ['--trajet', '#e0453a'], nuageBas: ['--nuage-bas', '#2e9e6b'],
  nuageMilieu: ['--nuage-milieu', '#ccad78'], nuageHaut: ['--nuage-haut', '#db3866'],
};
const COULEUR_PIETON = '#9fb4d8';

function lireJetons(element) {
  let style = null;
  try {
    style = window.getComputedStyle(element || document.documentElement);
  } catch (e) {
    style = null;
  }
  const c = {};
  Object.keys(JETONS).forEach((k) => {
    const v = style ? style.getPropertyValue(JETONS[k][0]).trim() : '';
    c[k] = G3.couleurDepuisTexte(v) ? v : JETONS[k][1];
  });
  return c;
}

function webglDisponible() {
  try {
    const toile = document.createElement('canvas');
    return !!(window.WebGLRenderingContext && (toile.getContext('webgl2') || toile.getContext('webgl')));
  } catch (e) {
    return false;
  }
}

function element(balise, classe, texte) {
  const e = document.createElement(balise);
  if (classe) e.className = classe;
  if (texte !== undefined && texte !== null) e.textContent = texte;
  return e;
}

// Nuanceur des points : taille en mètres (atténuée par la distance, jamais sous 1,5 px), couleur par la
// hauteur au-dessus du sol (dégradé à trois couleurs, comme couleurHauteur de geometrie3d.js), points
// plus hauts que la coupe (plafond) ou sous le sol cachés. Les points sont ronds (coins écartés).
const NUANCEUR_POINTS = `
uniform float taille;
uniform float echelle;
uniform float tailleMin;
uniform float coupe;
uniform float coupeBasse;
uniform float hauteurMax;
uniform vec3 couleurBas;
uniform vec3 couleurMilieu;
uniform vec3 couleurHaut;
varying vec3 vCouleur;
void main() {
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = max(taille * echelle / max(-mv.z, 0.001), tailleMin);
  float t = clamp(position.z / hauteurMax, 0.0, 1.0);
  vCouleur = t < 0.5 ? mix(couleurBas, couleurMilieu, t * 2.0) : mix(couleurMilieu, couleurHaut, t * 2.0 - 1.0);
  if (position.z > coupe || position.z < coupeBasse) {
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    gl_PointSize = 0.0;
  }
}`;
const NUANCEUR_COULEUR = `
varying vec3 vCouleur;
void main() {
  vec2 d = gl_PointCoord - vec2(0.5);
  if (dot(d, d) > 0.25) discard;
  gl_FragColor = vec4(vCouleur, 1.0);
}`;

function vecteur3(couleurTexte) {
  const c = G3.couleurDepuisTexte(couleurTexte) || [1, 1, 1];
  return new THREE.Vector3(c[0], c[1], c[2]);   // valeurs sRGB telles quelles : le nuanceur ne les convertit pas
}

// Toutes les méthodes sans effet (sans WebGL)
function carteInerte(racine, options, raison) {
  const rien = () => {};
  const abonner = () => rien;
  const carte = {
    chargerNuage: () => Promise.reject(new Error(raison)),
    afficherPoints: rien, afficherMonde: () => Promise.resolve({ ok: false, sansWebgl: true, maillage: 0, erreur: raison }),
    afficherCarte2D: () => Promise.resolve({ ok: false, sansWebgl: true, erreur: raison }),
    afficherSalles: rien, afficherItineraires: rien, afficherZones: rien, afficherRobot: rien,
    afficherPietons: rien, afficherTrajet: rien, vue: rien, recadrer: rien, centrerSur: rien,
    calque: () => false, coupe: rien, outil: rien, choisir: rien, surSelection: abonner, surPose: abonner,
    surPointeur: abonner, versEcran: () => null, versSol: () => null, redimensionner: rien,
    taillePoints: rien, positionRepere: () => null, dessiner: rien,
    etat: () => ({ webgl: false, points: 0, vue: 'iso', outil: 'naviguer', calques: {}, camera: null, raison: raison }),
    detruire: () => {
      racine.remove();
      if (options.nomGlobal && window[options.nomGlobal] === carte) delete window[options.nomGlobal];
    },
  };
  if (options.nomGlobal) window[options.nomGlobal] = carte;
  return carte;
}

// Crée la carte dans conteneur (élément vide, de taille fixée par la coque). options :
//   etage (obligatoire : seuls les éléments de cet étage sont montrés), nomGlobal (ex. 'carte3d' :
//   window.carte3d pour les tests), hauteurCoupe (2.2), plafond (faux : points au-dessus cachés),
//   en plus : barre (vrai : barre flottante Dessus, Iso, Face, Recadrer, Calques, et la case « Afficher le
//   plafond » dans la légende, posées par ce module ; faux par défaut : la coque a les siennes), reglages
//   (vrai : la case du plafond sans la barre), animation (vrai : changements de vue en 0,3 s),
//   conserverImage (vrai : captures d'écran de la toile), margeHaut (56 px : les vues cadrent le contenu
//   sous la barre flottante du haut de la vue ; 0 sans barre).
export function creerCarte3D(conteneur, options) {
  const o = Object.assign({ hauteurCoupe: HAUTEUR_COUPE, plafond: false, barre: false, animation: true,
    margeHaut: MARGE_HAUT }, options || {});
  const etage = o.etage || null;
  if (window.getComputedStyle(conteneur).position === 'static') conteneur.style.position = 'relative';
  const racine = element('div', 'carte3d');
  racine.setAttribute('data-role', 'carte3d');
  racine.tabIndex = 0;
  racine.setAttribute('aria-label', 'Carte 3D : glisser pour tourner, clic droit pour déplacer, molette pour zoomer');
  conteneur.appendChild(racine);

  const raisonSansWebgl = 'La vue 3D n\'est pas disponible dans ce navigateur (WebGL est coupé ou absent). '
    + 'Le Plan 2D permet de tout faire.';
  let rendu = null;
  if (webglDisponible()) {
    try {
      rendu = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: !!o.conserverImage });
    } catch (e) {
      rendu = null;
    }
  }
  if (!rendu) {
    racine.classList.add('carte3d-absente');
    const m = element('div', 'carte3d-sans-webgl', raisonSansWebgl);
    m.setAttribute('data-role', 'carte3d-sans-webgl');
    racine.appendChild(m);
    return carteInerte(racine, o, raisonSansWebgl);
  }

  // ------------------------------------------------------------ scène
  const couleurs = lireJetons(conteneur);
  const toile = rendu.domElement;
  toile.className = 'carte3d-toile';
  toile.setAttribute('data-role', 'carte3d-toile');
  racine.appendChild(toile);
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  rendu.setPixelRatio(ratio);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(couleurs.fond);
  const camera = new THREE.PerspectiveCamera(CHAMP_VISION, 1, 0.05, 2000);
  camera.up.set(0, 0, 1);                              // z vers le haut, AVANT les contrôles
  camera.position.set(-8, -16, 14);
  const controles = new OrbitControls(camera, toile);
  controles.target.set(0, 0, 0);
  controles.enableDamping = false;
  controles.screenSpacePanning = false;                // déplacer parallèlement au sol
  controles.zoomToCursor = true;      // pincement à deux doigts : vers le milieu des doigts (la molette est gérée ici)
  controles.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.ROTATE, RIGHT: THREE.MOUSE.PAN };
  controles.touches = { ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_PAN };
  controles.maxPolarAngle = Math.PI / 2 - 0.05;        // jamais sous le sol
  controles.minDistance = DISTANCES.min;
  controles.maxDistance = DISTANCES.max;
  controles.update();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x3a3a44, 1.6));
  const soleil = new THREE.DirectionalLight(0xffffff, 1.6);
  soleil.position.set(-12, -20, 30);
  scene.add(soleil);

  const groupes = {};
  CALQUES.forEach((nom) => {
    groupes[nom] = new THREE.Group();
    groupes[nom].name = nom;
    scene.add(groupes[nom]);
  });
  const groupeOutils = new THREE.Group();       // fantôme d'un nouveau point, mesure
  scene.add(groupeOutils);
  let grille = null;

  // nuage : un seul objet Points, nuanceur maison
  const uniformes = {
    taille: { value: TAILLE_POINTS }, echelle: { value: 500 }, tailleMin: { value: TAILLE_MIN_POINT_PX * ratio },
    coupe: { value: o.plafond ? 1e6 : o.hauteurCoupe }, coupeBasse: { value: COUPE_BASSE },
    hauteurMax: { value: G3.HAUTEUR_DEGRADE }, couleurBas: { value: vecteur3(couleurs.nuageBas) },
    couleurMilieu: { value: vecteur3(couleurs.nuageMilieu) }, couleurHaut: { value: vecteur3(couleurs.nuageHaut) },
  };
  const materiauNuage = new THREE.ShaderMaterial({ uniforms: uniformes, vertexShader: NUANCEUR_POINTS,
    fragmentShader: NUANCEUR_COULEUR });
  const nuage = new THREE.Points(new THREE.BufferGeometry(), materiauNuage);
  nuage.frustumCulled = false;
  groupes.nuage.add(nuage);
  // le sol (SEUIL_SOL) : mêmes uniformes, sans écrire la profondeur, dessiné avec les repères au sol, après
  // la grille (ordre 1) et la carte 2D (2), avant le trajet (5), les zones (6, 7) et les couloirs (8)
  const materiauSol = new THREE.ShaderMaterial({ uniforms: uniformes, vertexShader: NUANCEUR_POINTS,
    fragmentShader: NUANCEUR_COULEUR, transparent: true, depthWrite: false });
  const nuageSol = new THREE.Points(new THREE.BufferGeometry(), materiauSol);
  nuageSol.frustumCulled = false;
  nuageSol.renderOrder = 3;
  groupes.nuage.add(nuageSol);

  // ------------------------------------------------------------ calques HTML
  const calqueHtml = element('div', 'carte3d-html');
  calqueHtml.setAttribute('data-role', 'carte3d-etiquettes');
  racine.appendChild(calqueHtml);
  const chargement = element('div', 'carte3d-chargement', 'Chargement du nuage de points…');
  chargement.setAttribute('data-role', 'carte3d-chargement');
  chargement.hidden = true;
  racine.appendChild(chargement);

  // ------------------------------------------------------------ état
  const etat = {
    vue: 'iso', outil: 'naviguer', idOutil: null, coupe: o.plafond ? null : o.hauteurCoupe, taille: TAILLE_POINTS,
    calques: {}, points: 0, grille: null, bornes: { nuage: null, monde: null, carte: null, salles: null },
    cadre: false, choix: null, actif: true,
  };
  CALQUES.forEach((nom) => { etat.calques[nom] = true; });
  const salles = { liste: [], principal: null, reperes: new Map(), html: new Map(), fantome: null };
  const noeuds = { donnees: { noeuds: {}, couloirs: [] }, reperes: new Map(), couloirs: [] };
  let zones = [];
  const robot = { objet: null, pose: null, depart: null };
  const pietons = new Map();
  let mesure = { a: null, b: null, objet: null, html: null };
  let geste = null;            // geste en cours (poser, deplacer, tourner) : capture du pointeur
  let appui = null;            // appui du bouton gauche laissé aux contrôles : un clic sans bouger choisit
  let animation = null;
  let rafPrevu = 0;
  let pointeurPrevu = null;
  const abonnes = { selection: new Set(), pose: new Set(), pointeur: new Set() };
  const genresPose = new Map();    // abonné de surPose → genres qu'il modifie (null : tous)
  const versions = { salle: 0, noeud: 0 };   // comptent les afficherSalles et afficherItineraires
  let barre = null;            // barre flottante (option barre)
  let legende = null;          // légende des hauteurs et réglages du nuage
  let casePlafond = null;
  let curseurTaille = null;

  function emettre(genre, valeur) {
    abonnes[genre].forEach((f) => {
      if (genre === 'pose') {
        const g = genresPose.get(f);
        if (g && g.indexOf(valeur.genre) < 0) return;      // un écran ne reçoit que les genres qu'il modifie
      }
      try {
        f(valeur);
      } catch (e) {
        console.error(e);     // un abonné en erreur n'empêche pas les autres
      }
    });
  }

  function abonner(genre) {
    return (f) => {
      abonnes[genre].add(f);
      return () => abonnes[genre].delete(f);
    };
  }

  // surPose(fn, {genres}) : genres (ex. ['salle']) : seulement les poses de ces genres ; sans genres, toutes
  function surPose(f, options2) {
    const g = options2 && Array.isArray(options2.genres) ? options2.genres.map(String) : null;
    abonnes.pose.add(f);
    genresPose.set(f, g);
    majChoix();                // la poignée d'orientation suit
    return () => {
      abonnes.pose.delete(f);
      genresPose.delete(f);
      majChoix();
    };
  }

  // Un repère de ce genre (salle, noeud) se glisse ou se tourne seulement si un écran écoute ses poses
  // (surPose) : sinon le glisser tourne la vue, et un clic le choisit toujours.
  function modifiable(genre) {
    let oui = false;
    abonnes.pose.forEach((f) => {
      const g = genresPose.get(f);
      if (!g || g.indexOf(genre) >= 0) oui = true;
    });
    return oui;
  }

  // ------------------------------------------------------------ rendu à la demande
  function demanderRendu() {
    if (!etat.actif || rafPrevu) return;
    rafPrevu = requestAnimationFrame(rendre);
  }
  controles.addEventListener('change', () => {
    // garde-fou : un pincement fort, vers un point du sol tout proche, ne fait jamais passer sous le sol
    if (camera.position.z < 0.05 || controles.target.z < 0) {
      camera.position.z = Math.max(camera.position.z, 0.05);
      controles.target.z = Math.max(controles.target.z, 0);
      controles.update();
    }
    demanderRendu();
  });
  controles.addEventListener('start', () => { etat.interaction = true; });

  function taille() {
    return { l: Math.max(racine.clientWidth, 1), h: Math.max(racine.clientHeight, 1) };
  }

  function redimensionner() {
    const t = taille();
    rendu.setSize(t.l, t.h, false);
    camera.aspect = t.l / t.h;
    camera.updateProjectionMatrix();
    uniformes.echelle.value = (t.h * ratio) / (2 * Math.tan(CHAMP_VISION * Math.PI / 360));
    // cadrée quand la vue était cachée (taille nulle) : on recadre à son premier vrai affichage
    if (etat.cadreSansTaille && t.l > 2 && t.h > 2) {
      etat.cadreSansTaille = false;
      if (!etat.interaction) vue(etat.vue, false);
    }
    demanderRendu();
  }

  // Hauteur des épingles selon l'élévation de la caméra : debout en perspective (1 sous 60°), rentrées en
  // vue de dessus (0 au-dessus de 80°) : la tête numérotée est alors juste sur le point posé.
  function facteurPoteau() {
    const offset = camera.position.clone().sub(controles.target);
    const elevation = Math.asin(Math.max(-1, Math.min(1, offset.z / Math.max(offset.length(), 1e-9)))) * 180 / Math.PI;
    return Math.max(0, Math.min(1, (80 - elevation) / 20));
  }

  // Échelle des repères : 1 de près, plus grands de loin (au-delà de 14 m) pour rester visibles
  function echelleA(position) {
    return Math.max(1, camera.position.distanceTo(position) / ECHELLE_REPERES);
  }

  function rendre() {
    rafPrevu = 0;
    if (!etat.actif) return;
    if (animation) {
      const s = Math.min(1, (performance.now() - animation.debut) / animation.duree);
      const e = s < 0.5 ? 2 * s * s : 1 - 2 * (1 - s) * (1 - s);
      camera.position.lerpVectors(animation.dePosition, animation.aPosition, e);
      controles.target.lerpVectors(animation.deCible, animation.aCible, e);
      controles.update();
      if (s >= 1) animation = null;
      else demanderRendu();
    }
    camera.updateMatrixWorld();
    const reperes = [];
    salles.reperes.forEach((r) => reperes.push(r));
    noeuds.reperes.forEach((r) => reperes.push(r));
    if (salles.fantome) reperes.push(salles.fantome.objet);
    etat.poteau = facteurPoteau();
    reperes.forEach((r) => {
      r.scale.setScalar(echelleA(r.position));
      const poteau = r.getObjectByName('poteau');
      if (poteau) {
        poteau.scale.y = Math.max(etat.poteau, 0.001);     // y : l'axe du cylindre, couché sur z
        poteau.position.z = R.HAUTEUR_POTEAU * etat.poteau / 2;
        poteau.visible = etat.poteau > 0.02;
      }
    });
    if (robot.objet && robot.objet.visible) {
      const sol = robot.objet.getObjectByName('sol');       // anneau et flèche au sol
      if (sol) sol.scale.setScalar(echelleA(robot.objet.position));
    }
    rendu.render(scene, camera);
    placerHtml();
    dessinerAxes();
  }

  // ------------------------------------------------------------ projections
  const rayon = new THREE.Raycaster();

  function rayonDuPixel(px, py) {
    const t = taille();
    camera.updateMatrixWorld();
    rayon.setFromCamera(new THREE.Vector2((px / t.l) * 2 - 1, -(py / t.h) * 2 + 1), camera);
    return rayon.ray;
  }

  // Point du sol (z = 0) sous un pixel du conteneur, ou null (on vise le ciel, ou trop loin)
  function versSol(px, py) {
    const r = rayonDuPixel(px, py);
    const p = G3.intersectionSol(r.origin.toArray(), r.direction.toArray(), 0);
    if (!p || p.t > 3 * DISTANCES.max) return null;
    return { x: p.x, y: p.y };
  }

  // Pixel du conteneur d'un point (z = 0 par défaut), ou null s'il est derrière la caméra
  function versEcran(x, y, z) {
    camera.updateMatrixWorld();
    const p = new THREE.Vector3(x, y, z || 0);
    const dansCamera = p.clone().applyMatrix4(camera.matrixWorldInverse);
    if (dansCamera.z > -camera.near) return null;
    p.project(camera);
    const t = taille();
    return { x: (p.x + 1) / 2 * t.l, y: (1 - p.y) / 2 * t.h };
  }

  function pixelDe(ev) {
    const r = racine.getBoundingClientRect();
    return [ev.clientX - r.left, ev.clientY - r.top];
  }

  // ------------------------------------------------------------ bornes et caméra
  // Ce qu'on cadre : le nuage (et les salles) quand il y en a un, sinon le monde, la carte 2D et les salles
  function bornesContenu() {
    let b = null;
    const cles = etat.bornes.nuage ? ['nuage', 'salles'] : ['monde', 'carte', 'salles'];
    cles.forEach((k) => { b = G3.reunirBornes(b, etat.bornes[k]); });
    return b || { xmin: -5, ymin: -5, xmax: 5, ymax: 5 };
  }

  function hauteurCadrage(b) {
    const zmax = typeof b.zmax === 'number' && b.zmax > 0.3 ? b.zmax : G3.HAUTEUR_DEGRADE;
    return Math.min(zmax, etat.coupe === null ? zmax : etat.coupe);
  }

  function allerVers(pose, anime) {
    const position = new THREE.Vector3().fromArray(pose.position);
    const cible = new THREE.Vector3().fromArray(pose.cible);
    if (o.animation && anime !== false) {
      animation = { dePosition: camera.position.clone(), deCible: controles.target.clone(), aPosition: position,
        aCible: cible, debut: performance.now(), duree: 300 };
    } else {
      animation = null;
      camera.position.copy(position);
      controles.target.copy(cible);
      controles.update();
    }
    demanderRendu();
  }

  // Les vues cadrent le contenu sous la barre flottante du haut (celle de la coque ou celle du module)
  function sousLaBarre(poseDe) {
    const t = taille();
    return G3.cadrageSousMarge(poseDe, CHAMP_VISION, t.l, t.h, o.margeHaut);
  }

  function vue(nom, anime) {
    if (VUES.indexOf(nom) < 0) return;
    etat.vue = nom;
    const b = bornesContenu();
    allerVers(sousLaBarre((fov, aspect) => G3.poseVue(nom, b, fov, aspect, { hauteur: hauteurCadrage(b) })), anime);
    majBarre();
  }

  function recadrer(bornes) {
    const b = bornes || bornesContenu();
    const u = camera.position.clone().sub(controles.target).normalize().toArray();
    const zCible = etat.vue === 'face' ? hauteurCadrage(b) / 2 : 0;
    allerVers(sousLaBarre((fov, aspect) => G3.cadrage(b, u, fov, aspect, { hauteur: hauteurCadrage(b), zCible: zCible })));
  }

  function centrerSur(x, y) {
    const decalage = new THREE.Vector3(x - controles.target.x, y - controles.target.y, 0);
    allerVers({ position: camera.position.clone().add(decalage).toArray(),
      cible: controles.target.clone().add(decalage).toArray() });
  }

  // Premier affichage d'un contenu (nuage, monde ou carte 2D) : la vue de départ le cadre, une fois. Le
  // premier nuage recadre encore, si personne n'a touché à la vue depuis (la carte 2D arrive souvent avant).
  function cadrerUneFois(nuageArrive) {
    if (etat.cadre && !(nuageArrive && !etat.cadreNuage && !etat.interaction)) return;
    etat.cadre = true;
    if (nuageArrive) etat.cadreNuage = true;
    redimensionner();
    const t = taille();
    etat.cadreSansTaille = t.l <= 2 || t.h <= 2;
    vue(etat.vue, false);
  }

  function majGrille() {
    const b = bornesContenu();
    const cle = [b.xmin, b.ymin, b.xmax, b.ymax].map((v) => Math.round(v)).join(',');
    if (cle === etat.grille) return;
    etat.grille = cle;
    if (grille) {
      scene.remove(grille);
      R.liberer(grille);
    }
    const marge = 2;
    const largeur = Math.min(b.xmax - b.xmin + 2 * marge, 400);
    const hauteur = Math.min(b.ymax - b.ymin + 2 * marge, 400);
    const cx = (b.xmin + b.xmax) / 2;
    const cy = (b.ymin + b.ymax) / 2;
    grille = R.creerGrille({ xmin: cx - largeur / 2, ymin: cy - hauteur / 2, xmax: cx + largeur / 2, ymax: cy + hauteur / 2 },
      couleurs.grille);
    scene.add(grille);
    demanderRendu();
  }

  // Zoom de facteur k (< 1 : on s'approche) autour du point du sol sous le pixel (px, py) : la caméra et
  // sa cible subissent la même homothétie, la visée ne change pas et ce point reste sous le pointeur.
  function zoomer(k, px, py) {
    animation = null;
    const distance = camera.position.distanceTo(controles.target);
    const kBorne = Math.max(DISTANCES.min / distance, Math.min(DISTANCES.max / distance, k));
    let centre = null;
    const sol = versSol(px, py);
    if (sol) centre = [sol.x, sol.y, 0];
    else {
      const r = rayonDuPixel(px, py);
      centre = r.origin.clone().addScaledVector(r.direction, distance).toArray();
    }
    camera.position.fromArray(G3.homothetie(camera.position.toArray(), centre, kBorne));
    controles.target.fromArray(G3.homothetie(controles.target.toArray(), centre, kBorne));
    if (controles.target.z < 0) controles.target.z = 0;
    controles.update();
    demanderRendu();
  }

  // Déplacer la vue au clavier : dx vers la droite de l'écran, dy vers le haut, en part de la distance
  function deplacerVue(dx, dy) {
    animation = null;
    const distance = camera.position.distanceTo(controles.target);
    const avant = controles.target.clone().sub(camera.position);
    avant.z = 0;
    if (avant.lengthSq() < 1e-9) avant.set(0, 1, 0);
    avant.normalize();
    const droite = new THREE.Vector3(avant.y, -avant.x, 0);
    const d = droite.multiplyScalar(dx * distance).add(avant.multiplyScalar(dy * distance));
    camera.position.add(d);
    controles.target.add(d);
    controles.update();
  }

  // Tourner la vue au clavier : azimut et élévation en degrés
  function tournerVue(dAzimut, dElevation) {
    animation = null;
    const offset = camera.position.clone().sub(controles.target);
    const r = offset.length();
    const a = G3.anglesDepuisDirection(offset.toArray());
    const el = Math.max(2.9, Math.min(89.97, a.elevation + dElevation));
    const u = G3.directionDepuisAngles(a.azimut + dAzimut, el);
    camera.position.copy(controles.target).add(new THREE.Vector3().fromArray(u).multiplyScalar(r));
    controles.update();
  }

  // ------------------------------------------------------------ nuage
  function geometriePoints(positions) {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    return g;
  }

  function afficherPoints(positions, bornes) {
    const tous = positions instanceof Float32Array ? positions : new Float32Array(positions || []);
    const n = Math.floor(tous.length / 3);
    const p = n * 3 === tous.length ? tous : tous.subarray(0, 3 * n);
    const parts = G3.separerSol(p, SEUIL_SOL);
    nuage.geometry.dispose();
    nuage.geometry = geometriePoints(parts.reste);
    nuageSol.geometry.dispose();
    nuageSol.geometry = geometriePoints(parts.sol);
    etat.points = n;
    etat.pointsSol = parts.sol.length / 3;
    etat.bornesNuage = n ? (bornes || G3.bornesPositions(p)) : null;     // en-tête : tous les points
    etat.bornes.nuage = n ? G3.bornesRobustes(p) : null;                  // cadrage : sans les points isolés
    legende.hidden = !n;
    majOpaciteCarte();
    majGrille();
    if (n) cadrerUneFois(true);
    demanderRendu();
  }

  let numeroChargement = 0;
  async function chargerNuage(url) {
    numeroChargement += 1;
    const numero = numeroChargement;
    chargement.hidden = false;
    try {
      let reponse;
      try {
        reponse = await fetch(url);
      } catch (e) {
        throw new Error('Le serveur de l\'Atelier ne répond pas : le nuage 3D n\'a pas pu être chargé.');
      }
      if (!reponse.ok) {
        let detail = null;
        try {
          const j = await reponse.json();
          detail = j && typeof j.detail === 'string' ? j.detail : null;
        } catch (e) {
          detail = null;
        }
        let message = detail || ('Le nuage 3D n\'a pas pu être chargé (erreur ' + reponse.status + ' du serveur).');
        if (reponse.status === 404 && !detail) {
          message = 'Pas encore de nuage 3D : faites un scan, puis « Utiliser cette carte ».';
        } else if (reponse.status === 501) {
          message = 'Le nuage 3D n\'est pas encore servi par l\'Atelier : la vue montre la carte et les points sans lui.';
        }
        const erreur = new Error(message);
        erreur.statut = reponse.status;
        throw erreur;
      }
      const entetes = G3.lireEntetesNuage((nom) => reponse.headers.get(nom));
      const tampon = await reponse.arrayBuffer();
      const positions = G3.positionsDepuisTampon(tampon);
      const n = positions.length / 3;
      if (entetes.points !== null && entetes.points !== n) {
        console.warn('Nuage 3D : l\'en-tête annonce ' + entetes.points + ' points, le fichier en contient ' + n + '.');
      }
      if (numero !== numeroChargement) return { points: n, bornes: entetes.bornes, grille: entetes.grille, remplace: true };
      afficherPoints(positions, entetes.bornes);
      return { points: n, bornes: etat.bornesNuage, grille: entetes.grille, source: entetes.source };
    } finally {
      if (numero === numeroChargement) chargement.hidden = true;
    }
  }

  // ------------------------------------------------------------ monde et carte 2D
  // Le monde de la Simulation en volumes ; avec carte_extrudee et urlMaillage, le maillage STL de la carte
  // extrudée. Rend une promesse qui ne rejette jamais : {ok, maillage (triangles), erreur?}.
  async function afficherMonde(monde, options2) {
    const opt = options2 || {};
    R.liberer(groupes.monde);
    groupes.monde.clear();
    robot.depart = monde && monde.depart_robot ? monde.depart_robot : null;
    const m = construireMonde(monde, { sol: !etat.bornes.carte });
    groupes.monde.add(m.groupe);
    etat.bornes.monde = m.bornes;
    etat.monde = { objets: m.groupe.children.length, maillage: 0 };
    majRobot();
    majGrille();
    if (m.bornes) cadrerUneFois();
    demanderRendu();
    if (!(monde && monde.carte_extrudee && opt.urlMaillage)) return { ok: true, maillage: 0 };
    try {
      const reponse = await fetch(opt.urlMaillage);
      if (!reponse.ok) throw new Error('le maillage de la carte extrudée n\'a pas pu être chargé (erreur ' + reponse.status + ')');
      const geometrie = lireSTL(await reponse.arrayBuffer());
      if (groupes.monde.children[0] !== m.groupe) {      // un autre monde a été affiché entre-temps
        geometrie.dispose();
        return { ok: false, maillage: 0, erreur: 'remplacé' };
      }
      m.groupe.add(meshDuMaillage(geometrie));
      const triangles = geometrie.getAttribute('position').count / 3;
      etat.monde.maillage = triangles;
      demanderRendu();
      return { ok: true, maillage: triangles };
    } catch (e) {
      console.warn('Carte 3D : ' + e.message);
      return { ok: false, maillage: 0, erreur: e.message };
    }
  }

  // Sous un nuage, la carte 2D se fait discrète (le nuage montre déjà le sol et les murs)
  let materiauCarte = null;
  function majOpaciteCarte() {
    if (materiauCarte) materiauCarte.opacity = etat.points ? 0.35 : 1;
  }

  // La carte 2D (carte.png) posée au sol sur ses bornes, recolorée pour le fond sombre : libre gris foncé,
  // occupé clair, inconnu transparent. Rend une promesse qui ne rejette jamais : {ok, largeur, hauteur} ou
  // {ok: false, erreur}.
  function afficherCarte2D(url, bornes) {
    return new Promise((resoudre) => {
      const image = new Image();
      image.onload = () => {
        const t = document.createElement('canvas');
        t.width = image.naturalWidth;
        t.height = image.naturalHeight;
        const ctx = t.getContext('2d');
        ctx.drawImage(image, 0, 0);
        const donnees = ctx.getImageData(0, 0, t.width, t.height);
        const d = donnees.data;
        for (let i = 0; i < d.length; i += 4) {
          const v = d[i];
          if (v < 100) {
            d[i] = 205; d[i + 1] = 209; d[i + 2] = 220; d[i + 3] = 255;     // occupé
          } else if (v > 230) {
            d[i] = 48; d[i + 1] = 49; d[i + 2] = 58; d[i + 3] = 235;        // libre
          } else {
            d[i + 3] = 0;                                                    // inconnu
          }
        }
        ctx.putImageData(donnees, 0, 0);
        const texture = new THREE.CanvasTexture(t);
        texture.magFilter = THREE.NearestFilter;
        texture.colorSpace = THREE.SRGBColorSpace;
        R.liberer(groupes.carte2d);
        groupes.carte2d.clear();
        const lx = bornes.xmax - bornes.xmin;
        const ly = bornes.ymax - bornes.ymin;
        materiauCarte = new THREE.MeshBasicMaterial({ map: texture, transparent: true, depthWrite: false });
        majOpaciteCarte();
        const plan = new THREE.Mesh(new THREE.PlaneGeometry(lx, ly), materiauCarte);
        plan.position.set(bornes.xmin + lx / 2, bornes.ymin + ly / 2, R.Z_REPERES.carte);
        plan.renderOrder = 2;
        groupes.carte2d.add(plan);
        etat.bornes.carte = { xmin: bornes.xmin, ymin: bornes.ymin, xmax: bornes.xmax, ymax: bornes.ymax };
        majGrille();
        cadrerUneFois();
        demanderRendu();
        resoudre({ ok: true, largeur: t.width, hauteur: t.height });
      };
      image.onerror = () => {
        const message = 'La carte 2D n\'a pas pu être chargée : fabriquez-la (Placer › Carte, ou « Fabriquer la carte »).';
        console.warn('Carte 3D : ' + message);
        resoudre({ ok: false, erreur: message });
      };
      image.src = url;
    });
  }

  // ------------------------------------------------------------ salles
  function couleursSalle(principal) {
    return { repere: principal ? couleurs.accueil : couleurs.salle, choisi: couleurs.choisi };
  }

  function creerHtmlSalle(s, principal, numero, fantome) {
    const tete = element('div', 'carte3d-tete' + (principal ? ' principal' : '') + (fantome ? ' fantome' : ''));
    tete.appendChild(element('span', 'carte3d-numero', principal ? '★' : String(numero || '+')));
    const nom = element('div', 'carte3d-etiquette' + (principal ? ' principal' : '') + (fantome ? ' fantome' : ''),
      fantome ? 'Nouvelle salle' : s.nom);
    if (!fantome) {
      tete.setAttribute('data-salle', s.id);
      nom.setAttribute('data-salle', s.id);
      tete.title = s.nom + (principal ? ' (point principal)' : '');
      if (!principal && String(numero) === String(s.nom).trim()) nom.classList.add('doublon');   // « 3 » sur l'épingle 3
    }
    calqueHtml.appendChild(tete);
    calqueHtml.appendChild(nom);
    return { tete: tete, nom: nom };
  }

  function retirerFantome() {
    if (!salles.fantome) return;
    groupeOutils.remove(salles.fantome.objet);
    R.liberer(salles.fantome.objet);
    salles.fantome.html.tete.remove();
    salles.fantome.html.nom.remove();
    salles.fantome = null;
    demanderRendu();
  }

  function afficherSalles(liste, principal) {
    versions.salle += 1;
    const toutes = Array.isArray(liste) ? liste : [];
    const p = principal === undefined ? G3.idPrincipal(toutes) : principal;
    salles.principal = p === null || p === undefined ? null : String(p);
    salles.liste = toutes.filter((s) => !etage || s.etage === etage);
    salles.reperes.forEach((r) => {
      groupes.points.remove(r);
      R.liberer(r);
    });
    salles.reperes.clear();
    salles.html.forEach((h) => {
      h.tete.remove();
      h.nom.remove();
    });
    salles.html.clear();
    retirerFantome();
    const numeros = G3.numerosSalles(salles.liste, salles.principal);
    salles.liste.forEach((s) => {
      const id = String(s.id);                     // un id lu comme un nombre reste une clé texte
      const estPrincipal = id === salles.principal;
      const r = R.creerRepereSalle(couleursSalle(estPrincipal), estPrincipal, false);
      r.position.set(s.pose.x, s.pose.y, 0);
      R.orienterRepere(r, s.pose.theta);
      r.userData.id = id;
      r.userData.theta = s.pose.theta;
      salles.reperes.set(id, r);
      groupes.points.add(r);
      salles.html.set(id, creerHtmlSalle(s, estPrincipal, numeros[s.id], false));
    });
    const pts = salles.liste.map((s) => [s.pose.x, s.pose.y]);
    etat.bornes.salles = G3.bornesDePoints(pts, 2);
    if (geste && geste.genre === 'salle' && geste.id && !salles.reperes.has(geste.id)) annulerGeste(false);
    majChoix();
    demanderRendu();
  }

  // Éléments HTML (têtes d'épingle, noms, mesure) posés sur la projection de leur point
  function placerUn(e, point, cache) {
    if (cache || !point) {
      e.hidden = true;
      return;
    }
    const t = taille();
    const dehors = point.x < -40 || point.y < -40 || point.x > t.l + 40 || point.y > t.h + 40;
    e.hidden = dehors;
    if (!dehors) e.style.transform = 'translate(' + point.x.toFixed(1) + 'px, ' + point.y.toFixed(1) + 'px)';
  }

  // Hauteur (m) de la tête d'une épingle : en haut du poteau, à l'échelle du repère
  function hauteurTete(r) {
    return R.HAUTEUR_POTEAU * r.scale.x * (etat.poteau === undefined ? 1 : etat.poteau);
  }

  // Candidat au placement des étiquettes (placerEtiquettes) : seulement un nom affiché, avec sa largeur
  // (mesurée une fois : le texte ne change pas sans recréer l'élément)
  function candidatEtiquette(cle, h, p, rang, distance, principal) {
    if (!p || h.tete.hidden || h.nom.hidden || h.nom.classList.contains('doublon')) return null;
    if (!h.largeur) h.largeur = h.nom.offsetWidth;
    if (!h.largeur) return null;                     // vue cachée : rien à placer
    return { id: cle, x: p.x, y: p.y, largeur: h.largeur, hauteur: HAUTEUR_ETIQUETTE,
      rayon: principal ? RAYON_TETE.principal : RAYON_TETE.salle, rang: rang, distance: distance, nom: h.nom };
  }

  function placerHtml() {
    const cache = !etat.calques.points;
    const c = etat.choix;
    const candidats = [];
    const tetes = [];          // toutes les têtes affichées, même sans nom (« 3 » sur l'épingle 3) : obstacles
    const noterTete = (cle, h, p, principal) => {
      if (p && !h.tete.hidden) {
        tetes.push({ id: cle, x: p.x, y: p.y, rayon: principal ? RAYON_TETE.principal : RAYON_TETE.salle });
      }
    };
    salles.reperes.forEach((r, id) => {
      const h = salles.html.get(id);
      if (!h) return;
      const p = versEcran(r.position.x, r.position.y, hauteurTete(r));
      placerUn(h.tete, p, cache);
      placerUn(h.nom, p, cache);
      noterTete(id, h, p, id === salles.principal);
      // les plus proches devant ; l'accueil, puis la salle choisie, par-dessus
      const distance = camera.position.distanceTo(r.position);
      const choisie = !!c && c.genre === 'salle' && c.id === id;
      let z = Math.max(1, 999 - Math.round(distance * 4));
      if (id === salles.principal) z += 1000;
      if (choisie) z += 2000;
      h.tete.style.zIndex = String(z + 1);
      h.nom.style.zIndex = String(z);
      const k = candidatEtiquette(id, h, p, choisie ? 1 : (id === salles.principal ? 2 : 3), distance,
        id === salles.principal);
      if (k) candidats.push(k);
    });
    if (salles.fantome) {
      const r = salles.fantome.objet;
      const p = versEcran(r.position.x, r.position.y, hauteurTete(r));
      placerUn(salles.fantome.html.tete, p, false);
      placerUn(salles.fantome.html.nom, p, false);
      noterTete(':fantome', salles.fantome.html, p, false);
      const k = candidatEtiquette(':fantome', salles.fantome.html, p, 0, 0, false);
      if (k) candidats.push(k);
    }
    // les noms sans chevauchement : la salle en cours de pose, la choisie, l'accueil, puis les plus proches
    candidats.sort((a, b) => a.rang - b.rang || a.distance - b.distance);
    const places = G3.placerEtiquettes(candidats, tetes);
    candidats.forEach((k) => {
      const place = places[k.id];
      k.nom.classList.toggle('cachee', !place);
      if (place) k.nom.setAttribute('data-place', place);
    });
    if (mesure.html) {
      const a = mesure.a;
      const b = mesure.b || mesure.a;
      placerUn(mesure.html, versEcran((a.x + b.x) / 2, (a.y + b.y) / 2, 0.05), false);
    }
  }

  // ------------------------------------------------------------ itinéraires, zones, trajet
  function afficherItineraires(donnees) {
    versions.noeud += 1;
    const d = donnees || {};
    noeuds.donnees = { noeuds: d.noeuds || {}, couloirs: d.couloirs || [] };
    R.liberer(groupes.itineraires);
    groupes.itineraires.clear();
    const r = R.creerItineraires(noeuds.donnees.noeuds, noeuds.donnees.couloirs, etage, couleurs);
    groupes.itineraires.add(r.groupe);
    noeuds.reperes = r.noeuds;
    noeuds.couloirs = r.couloirs;
    majChoix();
    demanderRendu();
  }

  // Les couloirs d'un nœud suivent le nœud glissé : ceux qui le touchent, refaits avec ce bout en (x, y)
  function majCouloirsDe(id, x, y) {
    const d = noeuds.donnees.noeuds;
    noeuds.couloirs.forEach((c) => {
      if (c.a !== id && c.b !== id) return;
      const pa = c.a === id ? { x: x, y: y } : d[c.a];
      const pb = c.b === id ? { x: x, y: y } : d[c.b];
      if (!pa || !pb) return;
      const nouveau = R.creerCouloir(pa, pb, couleurs);
      const parent = c.objet.parent;
      if (parent) {
        parent.remove(c.objet);
        parent.add(nouveau);
      }
      R.liberer(c.objet);
      c.objet = nouveau;
    });
    demanderRendu();
  }

  function afficherZones(donnees) {
    R.liberer(groupes.zones);
    groupes.zones.clear();
    const r = R.creerZones(donnees, etage, couleurs);
    groupes.zones.add(r.groupe);
    zones = r.zones;
    majChoix();
    demanderRendu();
  }

  function afficherTrajet(points) {
    R.liberer(groupes.trajet);
    groupes.trajet.clear();
    groupes.trajet.add(R.creerTrajet(points, couleurs.trajet));
    demanderRendu();
  }

  // ------------------------------------------------------------ robot et piétons
  function majRobot() {
    const pose = robot.pose || robot.depart;
    if (!pose) {
      if (robot.objet) robot.objet.visible = false;
      demanderRendu();
      return;
    }
    if (!robot.objet) {
      robot.objet = R.creerRobot(couleurs);
      groupes.robot.add(robot.objet);
    }
    robot.objet.visible = true;
    robot.objet.position.set(pose.x, pose.y, 0);
    robot.objet.rotation.z = pose.theta || 0;
    R.estomperRobot(robot.objet, !robot.pose || !!pose.perimee);
    demanderRendu();
  }

  function afficherRobot(pose) {
    robot.pose = pose && typeof pose.x === 'number' && typeof pose.y === 'number' ? pose : null;
    majRobot();
  }

  function afficherPietons(liste) {
    const vus = new Set();
    (liste || []).forEach((p) => {
      if (!p || typeof p.x !== 'number' || typeof p.y !== 'number') return;
      const id = String(p.id);
      let h = pietons.get(id);
      if (!h) {
        h = R.creerPieton(COULEUR_PIETON);
        pietons.set(id, h);
        groupes.pietons.add(h);
      }
      h.position.set(p.x, p.y, 0);
      h.rotation.z = p.theta || 0;
      vus.add(id);
    });
    pietons.forEach((h, id) => {
      if (vus.has(id)) return;
      groupes.pietons.remove(h);
      R.liberer(h);
      pietons.delete(id);
    });
    demanderRendu();
  }

  // ------------------------------------------------------------ calques, coupe, taille des points
  function calque(nom, visible) {
    if (CALQUES.indexOf(nom) < 0) return false;
    if (visible !== undefined) {
      etat.calques[nom] = !!visible;
      groupes[nom].visible = !!visible;
      if (nom === 'points') placerHtml();         // les noms et les têtes d'épingle suivent tout de suite
      majBarre();
      demanderRendu();
    }
    return etat.calques[nom];
  }

  function coupe(hauteur) {
    etat.coupe = typeof hauteur === 'number' && isFinite(hauteur) ? hauteur : null;
    uniformes.coupe.value = etat.coupe === null ? 1e6 : etat.coupe;
    casePlafond.checked = etat.coupe === null;
    demanderRendu();
  }

  function taillePoints(m) {
    const v = Number(m);
    if (!isFinite(v)) return;
    etat.taille = Math.max(TAILLES_POINTS.min, Math.min(TAILLES_POINTS.max, v));
    uniformes.taille.value = etat.taille;
    curseurTaille.value = String(etat.taille);
    demanderRendu();
  }

  // ------------------------------------------------------------ sélection
  function majChoix() {
    const c = etat.choix;
    const tourner = modifiable('salle');
    salles.reperes.forEach((r, id) => R.marquerChoisi(r, !!c && c.genre === 'salle' && c.id === id, tourner));
    salles.html.forEach((h, id) => h.tete.classList.toggle('choisi', !!c && c.genre === 'salle' && c.id === id));
    noeuds.reperes.forEach((r, id) => R.marquerChoisi(r, !!c && c.genre === 'noeud' && c.id === id));
    zones.forEach((z) => R.marquerZoneChoisie(z, !!c && c.genre === 'zone' && c.id === z.id));
    demanderRendu();
  }

  function choisir(genre, id) {
    etat.choix = genre && id !== undefined && id !== null ? { genre: genre, id: String(id) } : null;
    majChoix();
  }

  // Le repère touché sous le pixel p : {genre, id, partie: 'repere'|'poignee', distance}, ou null.
  // filtre(genre, id) : seuls les repères acceptés comptent.
  function toucher(p, filtre) {
    let meilleur = null;
    const proposer = (candidat) => {
      if (filtre && !filtre(candidat.genre, candidat.id)) return;
      if (candidat.distance > G3.RAYON_TOUCHE_PX) return;
      if (!meilleur || (candidat.partie === 'poignee' && meilleur.partie !== 'poignee')
        || (candidat.partie === meilleur.partie && candidat.distance < meilleur.distance)) meilleur = candidat;
    };
    if (etat.calques.points) {
      salles.reperes.forEach((r, id) => {
        const s = r.scale.x;
        const base = versEcran(r.position.x, r.position.y, 0);
        const haut = versEcran(r.position.x, r.position.y, hauteurTete(r));
        if (base && haut) {
          proposer({ genre: 'salle', id: id, partie: 'repere',
            distance: G3.distancePointSegment(p, [base.x, base.y], [haut.x, haut.y]) });
        }
        const c = etat.choix;
        if (c && c.genre === 'salle' && c.id === id && modifiable('salle')) {
          const bout = G3.boutFleche(r.position.x, r.position.y, r.userData.theta || 0, r.userData.longueur * s);
          const q = versEcran(bout.x, bout.y, 0);
          if (q) proposer({ genre: 'salle', id: id, partie: 'poignee', distance: Math.hypot(p[0] - q.x, p[1] - q.y) });
        }
      });
    }
    if (etat.calques.itineraires) {
      noeuds.reperes.forEach((r, id) => {
        const q = versEcran(r.position.x, r.position.y, 0);
        if (q) proposer({ genre: 'noeud', id: id, partie: 'repere', distance: Math.hypot(p[0] - q.x, p[1] - q.y) + 3 });
      });
    }
    return meilleur;
  }

  // Pixel d'un repère (tests, coque) : partie 'base' (le point posé, par défaut), 'tete' (la tête de
  // l'épingle) ou 'poignee' (le bout de la flèche, qu'on glisse pour tourner) ; null s'il n'existe pas
  function positionRepere(genre, id, partie) {
    const r = genre === 'salle' ? salles.reperes.get(String(id)) : (genre === 'noeud' ? noeuds.reperes.get(String(id)) : null);
    if (!r) return null;
    if (partie === 'tete') return versEcran(r.position.x, r.position.y, hauteurTete(r));
    if (partie === 'poignee') {
      const bout = G3.boutFleche(r.position.x, r.position.y, r.userData.theta || 0, (r.userData.longueur || 0) * r.scale.x);
      return versEcran(bout.x, bout.y, 0);
    }
    return versEcran(r.position.x, r.position.y, 0);
  }

  // ------------------------------------------------------------ outils
  function outil(nom, options2) {
    if (OUTILS.indexOf(nom) < 0) nom = 'naviguer';
    if (geste) annulerGeste(true);
    retirerFantome();
    if (nom !== 'mesurer') effacerMesure();
    etat.outil = nom;
    etat.idOutil = options2 && options2.id !== undefined && options2.id !== null ? String(options2.id) : null;
    OUTILS.forEach((n) => racine.classList.toggle('outil-' + n, n === nom));
    demanderRendu();
  }

  // Élément visé par l'outil de pose : {genre, id} (id null : nouvel élément)
  function cibleOutil() {
    if (etat.outil === 'accueil') return { genre: 'salle', id: salles.principal };
    if (etat.outil === 'salle') return { genre: 'salle', id: etat.idOutil };
    if (etat.outil === 'noeud') return { genre: 'noeud', id: etat.idOutil };
    return null;
  }

  function repereDe(genre, id) {
    if (id === null || id === undefined) return null;
    return genre === 'salle' ? salles.reperes.get(id) || null : noeuds.reperes.get(id) || null;
  }

  function poseActuelle(genre, id) {
    const r = repereDe(genre, id);
    if (!r) return null;
    return { x: r.position.x, y: r.position.y, theta: genre === 'salle' ? (r.userData.theta || 0) : null };
  }

  function emettrePose(g, fini, extra) {
    const e = Object.assign({ outil: etat.outil, genre: g.genre, id: g.id, x: g.x, y: g.y,
      theta: g.genre === 'salle' ? g.theta : null, fini: !!fini, geste: g.type }, extra || {});
    emettre('pose', e);
  }

  // Montre la pose du geste en cours : le repère de l'élément, ou un fantôme pour un nouvel élément
  function montrerGeste() {
    const g = geste;
    let r = repereDe(g.genre, g.id);
    if (!r && g.genre === 'salle') {
      if (!salles.fantome) {
        const objet = R.creerRepereSalle(couleursSalle(false), false, true);
        groupeOutils.add(objet);
        salles.fantome = { objet: objet, html: creerHtmlSalle(null, false, null, true) };
      }
      r = salles.fantome.objet;
    } else if (!r && g.genre === 'noeud') {
      if (!salles.fantome) {
        const objet = R.creerRepereNoeud(couleurs);
        groupeOutils.add(objet);
        const html = { tete: element('div', 'carte3d-tete fantome noeud'), nom: element('div', 'carte3d-etiquette fantome', 'Nouveau nœud') };
        html.tete.appendChild(element('span', 'carte3d-numero', '+'));
        calqueHtml.appendChild(html.tete);
        calqueHtml.appendChild(html.nom);
        salles.fantome = { objet: objet, html: html };
      }
      r = salles.fantome.objet;
    }
    if (!r) return;
    r.position.set(g.x, g.y, 0);
    if (g.genre === 'salle') {
      r.userData.theta = g.theta;
      R.orienterRepere(r, g.theta);
    } else if (repereDe('noeud', g.id)) {
      majCouloirsDe(g.id, g.x, g.y);
    }
    demanderRendu();
  }

  function demarrerGeste(type, cible, sol, p, ev) {
    const avant = poseActuelle(cible.genre, cible.id);
    geste = {
      type: type, genre: cible.genre, id: cible.id, avant: avant, depart: p, bouge: false, pointeur: ev.pointerId,
      x: avant ? avant.x : 0, y: avant ? avant.y : 0, theta: avant && avant.theta !== null ? avant.theta : 0,
    };
    if (type === 'poser') {
      const q = G3.accrocherPosition(sol.x, sol.y);
      geste.x = q.x;
      geste.y = q.y;
      geste.ancre = q;
      montrerGeste();
      emettrePose(geste, false);
    } else if (type === 'deplacer') {
      geste.decalage = { x: geste.x - sol.x, y: geste.y - sol.y };
    }
    try {
      toile.setPointerCapture(ev.pointerId);
    } catch (e) {
      // pointeur déjà relâché : le geste finira au prochain pointerup
    }
    racine.classList.add('geste-en-cours');
  }

  function suivreGeste(p, libre) {
    const g = geste;
    const sol = versSol(p[0], p[1]);
    if (!sol) return;
    const ecart = Math.hypot(p[0] - g.depart[0], p[1] - g.depart[1]);
    if (g.type === 'poser') {
      if (g.genre !== 'salle' || ecart < G3.SEUIL_ORIENTATION_PX) return;
      const theta = G3.angleFleche(g.ancre.x, g.ancre.y, sol.x, sol.y, libre);
      if (theta === null) return;
      g.bouge = true;
      g.theta = theta;
    } else if (g.type === 'deplacer') {
      if (!g.bouge && ecart < G3.SEUIL_CLIC_PX) return;
      g.bouge = true;
      const q = G3.accrocherPosition(sol.x + g.decalage.x, sol.y + g.decalage.y);
      g.x = q.x;
      g.y = q.y;
    } else if (g.type === 'tourner') {
      const theta = G3.angleFleche(g.x, g.y, sol.x, sol.y, libre);
      if (theta === null) return;
      g.bouge = true;
      g.theta = theta;
    }
    montrerGeste();
    emettrePose(geste, false);
  }

  function finirGeste() {
    const g = geste;
    geste = null;
    racine.classList.remove('geste-en-cours');
    try {
      toile.releasePointerCapture(g.pointeur);
    } catch (e) {
      // déjà relâché
    }
    if (g.type === 'deplacer' && !g.bouge) {
      // un clic sur un repère, sans le bouger : on le choisit
      etat.choix = { genre: g.genre, id: g.id };
      majChoix();
      emettre('selection', { genre: g.genre, id: g.id });
      return;
    }
    if (g.type !== 'poser') {
      etat.choix = { genre: g.genre, id: g.id };
      majChoix();
    }
    const version = versions[g.genre];
    emettrePose(g, true);
    // l'écran qui accepte la pose rappelle afficherSalles (ou afficherItineraires) pendant surPose ; sinon,
    // rien n'a été retenu : le repère revient à la place que disent les données
    if (versions[g.genre] === version) remettreEnPlace(g.genre, g.id);
    if (g.type === 'poser') retirerFantome();
  }

  // Le repère d'une salle ou d'un nœud, remis à la pose de sa dernière donnée affichée
  function remettreEnPlace(genre, id) {
    const r = repereDe(genre, id);
    if (!r) return;
    if (genre === 'salle') {
      const s = salles.liste.find((x) => String(x.id) === id);
      if (!s) return;
      r.position.set(s.pose.x, s.pose.y, 0);
      r.userData.theta = s.pose.theta;
      R.orienterRepere(r, s.pose.theta);
    } else {
      const n = noeuds.donnees.noeuds[id];
      if (n) {
        r.position.set(n.x, n.y, 0);
        majCouloirsDe(id, n.x, n.y);
      }
    }
    demanderRendu();
  }

  // Échap, ou un autre outil : le repère revient à sa pose d'avant
  function annulerGeste(prevenir) {
    const g = geste;
    if (!g) return;
    geste = null;
    racine.classList.remove('geste-en-cours');
    try {
      toile.releasePointerCapture(g.pointeur);
    } catch (e) {
      // déjà relâché
    }
    if (g.avant) {
      const r = repereDe(g.genre, g.id);
      if (r) {
        r.position.set(g.avant.x, g.avant.y, 0);
        if (g.genre === 'salle') {
          r.userData.theta = g.avant.theta;
          R.orienterRepere(r, g.avant.theta);
        } else {
          majCouloirsDe(g.id, g.avant.x, g.avant.y);
        }
      }
      if (prevenir) {
        emettre('pose', { outil: etat.outil, genre: g.genre, id: g.id, x: g.avant.x, y: g.avant.y,
          theta: g.avant.theta, fini: true, geste: g.type, annule: true });
      }
    }
    retirerFantome();
    demanderRendu();
  }

  function effacerMesure() {
    if (mesure.objet) {
      groupeOutils.remove(mesure.objet);
      R.liberer(mesure.objet);
    }
    if (mesure.html) mesure.html.remove();
    mesure = { a: null, b: null, objet: null, html: null };
    demanderRendu();
  }

  function cliquerMesure(sol) {
    if (!mesure.a || mesure.b) {
      effacerMesure();
      mesure.a = sol;
      mesure.html = element('div', 'carte3d-mesure', 'Cliquez le second point');
      mesure.html.setAttribute('data-role', 'carte3d-mesure');
      calqueHtml.appendChild(mesure.html);
    } else {
      mesure.b = sol;
      mesure.objet = R.creerTraitMesure(mesure.a, mesure.b, couleurs.choisi);
      groupeOutils.add(mesure.objet);
      mesure.html.textContent = G3.texteDistance(Math.hypot(mesure.b.x - mesure.a.x, mesure.b.y - mesure.a.y));
    }
    demanderRendu();
  }

  // ------------------------------------------------------------ pointeur
  function surAppui(ev) {
    if (ev.target !== toile) return;          // boutons et réglages posés sur la vue : ils gèrent seuls
    try {
      racine.focus({ preventScroll: true });
    } catch (e) {
      racine.focus();
    }
    if (geste) {                                // second doigt pendant un geste : on l'annule
      annulerGeste(true);
      return;
    }
    const gauche = ev.pointerType === 'touch' ? ev.isPrimary : ev.button === 0;
    if (!gauche) {
      appui = null;
      return;
    }
    const p = pixelDe(ev);
    const sol = versSol(p[0], p[1]);
    if (OUTILS_POSE.indexOf(etat.outil) >= 0) {
      const cible = cibleOutil();
      ev.stopPropagation();
      ev.preventDefault();
      const touche = cible.id !== null ? toucher(p, (genre, id) => genre === cible.genre && id === cible.id) : null;
      if (touche && touche.partie === 'poignee') demarrerGeste('tourner', cible, sol, p, ev);
      else if (touche && sol) demarrerGeste('deplacer', cible, sol, p, ev);
      else if (sol) demarrerGeste('poser', cible, sol, p, ev);
      return;
    }
    if (etat.outil === 'mesurer') {
      ev.stopPropagation();
      ev.preventDefault();
      if (sol) cliquerMesure(sol);
      return;
    }
    const touche = toucher(p);
    if (touche && sol && modifiable(touche.genre)) {
      ev.stopPropagation();
      ev.preventDefault();
      demarrerGeste(touche.partie === 'poignee' ? 'tourner' : 'deplacer', touche, sol, p, ev);
      return;
    }
    // un repère que personne ne modifie : le glisser tourne la vue, un clic le choisit (au relâchement)
    appui = { p: p, sol: sol, touche: touche };
  }

  function signalerPointeur() {
    const p = pointeurPrevu;
    pointeurPrevu = null;
    if (!p) return;
    if (p === 'dehors') {
      emettre('pointeur', null);
      racine.classList.remove('survol-repere', 'survol-choix');
      return;
    }
    const sol = versSol(p[0], p[1]);
    emettre('pointeur', sol ? G3.accrocherPosition(sol.x, sol.y, 0.01) : null);
    const t = etat.outil === 'naviguer' ? toucher(p) : null;
    racine.classList.toggle('survol-repere', !!t && modifiable(t.genre));      // main : on peut le glisser
    racine.classList.toggle('survol-choix', !!t && !modifiable(t.genre));      // doigt : on peut le choisir
  }

  function surMouvement(ev) {
    const p = pixelDe(ev);
    if (geste && ev.pointerId === geste.pointeur) {
      suivreGeste(p, ev.shiftKey);
      return;
    }
    if (pointeurPrevu === null) requestAnimationFrame(signalerPointeur);
    pointeurPrevu = p;
  }

  function surRelache(ev) {
    if (geste && ev.pointerId === geste.pointeur) {
      suivreGeste(pixelDe(ev), ev.shiftKey);
      finirGeste();
      return;
    }
    const a = appui;
    appui = null;
    if (!a || etat.outil !== 'naviguer') return;
    const p = pixelDe(ev);
    if (Math.hypot(p[0] - a.p[0], p[1] - a.p[1]) >= G3.SEUIL_CLIC_PX) return;
    // clic sur un repère (que personne ne modifie) : on le choisit ; sur le sol : une zone sous le pointeur,
    // sinon plus rien de choisi
    let choix = a.touche ? { genre: a.touche.genre, id: a.touche.id } : null;
    if (!choix && a.sol && etat.calques.zones) {
      const z = zones.slice().reverse().find((zz) => dansPolygone([a.sol.x, a.sol.y], zz.polygone));
      if (z) choix = { genre: 'zone', id: z.id };
    }
    etat.choix = choix;
    majChoix();
    emettre('selection', choix || { genre: null, id: null });
  }

  function surAnnulationPointeur(ev) {
    if (geste && ev.pointerId === geste.pointeur) annulerGeste(true);
    appui = null;
  }

  function surMolette(ev) {
    ev.preventDefault();
    ev.stopPropagation();          // les contrôles n'ont pas la molette : le zoom vers le pointeur est ici
    if (geste) return;
    etat.interaction = true;
    const p = pixelDe(ev);
    zoomer(G3.facteurMolette(ev.deltaY, ev.deltaMode, ev.ctrlKey), p[0], p[1]);
  }

  function surDoubleClic(ev) {
    if (etat.outil !== 'naviguer') return;
    const p = pixelDe(ev);
    const sol = versSol(p[0], p[1]);
    if (sol && !toucher(p)) centrerSur(sol.x, sol.y);
  }

  function surTouche(ev) {
    if (ev.target !== racine && ev.target !== toile) return;    // un champ de la barre ou de la légende
    if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && VUES_SOLIDWORKS[ev.key]) {
      etat.interaction = true;
      vue(VUES_SOLIDWORKS[ev.key]);       // Ctrl+5 dessus, Ctrl+7 iso, Ctrl+1 face, comme SolidWorks
      ev.preventDefault();
      return;
    }
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const t = taille();
    let fait = true;
    switch (ev.key) {
      case 'ArrowLeft': if (ev.shiftKey) tournerVue(-10, 0); else deplacerVue(-0.1, 0); break;
      case 'ArrowRight': if (ev.shiftKey) tournerVue(10, 0); else deplacerVue(0.1, 0); break;
      case 'ArrowUp': if (ev.shiftKey) tournerVue(0, 5); else deplacerVue(0, 0.1); break;
      case 'ArrowDown': if (ev.shiftKey) tournerVue(0, -5); else deplacerVue(0, -0.1); break;
      case '+': case '=': zoomer(0.8, t.l / 2, t.h / 2); break;
      case '-': case '_': zoomer(1.25, t.l / 2, t.h / 2); break;
      case '1': vue('dessus'); break;
      case '2': vue('iso'); break;
      case '3': vue('face'); break;
      case 'f': case 'F': recadrer(); break;
      case 'Escape':
        // Échap reste aussi l'ARRÊT de la coque : on ne retient pas l'événement
        if (geste) annulerGeste(true);
        if (etat.outil !== 'naviguer') outil('naviguer');
        effacerMesure();
        return;
      default: fait = false;
    }
    if (fait) {
      etat.interaction = true;
      ev.preventDefault();
    }
  }

  racine.addEventListener('pointerdown', surAppui, true);
  toile.addEventListener('pointermove', surMouvement);
  toile.addEventListener('pointerup', surRelache);
  toile.addEventListener('pointercancel', surAnnulationPointeur);
  toile.addEventListener('pointerleave', () => {
    if (!geste) {
      if (pointeurPrevu === null) requestAnimationFrame(signalerPointeur);
      pointeurPrevu = 'dehors';
    }
  });
  toile.addEventListener('dblclick', surDoubleClic);
  racine.addEventListener('wheel', surMolette, { capture: true, passive: false });
  racine.addEventListener('keydown', surTouche);
  racine.addEventListener('contextmenu', (ev) => ev.preventDefault());
  toile.addEventListener('webglcontextlost', (ev) => ev.preventDefault());

  // ------------------------------------------------------------ indicateur d'orientation (axes, z en haut)
  const SVG = 'http://www.w3.org/2000/svg';
  const axes = document.createElementNS(SVG, 'svg');
  axes.setAttribute('class', 'carte3d-axes');
  axes.setAttribute('data-role', 'carte3d-axes');
  axes.setAttribute('viewBox', '0 0 80 80');
  axes.setAttribute('width', '92');
  axes.setAttribute('height', '92');
  const fondAxes = document.createElementNS(SVG, 'circle');
  fondAxes.setAttribute('cx', '40');
  fondAxes.setAttribute('cy', '40');
  fondAxes.setAttribute('r', '38');
  fondAxes.setAttribute('class', 'carte3d-axes-fond');
  axes.appendChild(fondAxes);
  const AXES = [
    { nom: 'x', v: new THREE.Vector3(1, 0, 0), classe: 'axe-x', titre: 'x (est) : vue Iso', vue: 'iso' },
    { nom: 'y', v: new THREE.Vector3(0, 1, 0), classe: 'axe-y', titre: 'y (nord) : vue de Face', vue: 'face' },
    { nom: 'z', v: new THREE.Vector3(0, 0, 1), classe: 'axe-z', titre: 'z (haut) : vue de Dessus', vue: 'dessus' },
  ];
  AXES.forEach((a) => {
    const g = document.createElementNS(SVG, 'g');
    g.setAttribute('class', 'carte3d-axe ' + a.classe);
    g.setAttribute('data-axe', a.nom);
    const titre = document.createElementNS(SVG, 'title');
    titre.textContent = a.titre;
    g.appendChild(titre);
    const ligne = document.createElementNS(SVG, 'line');
    ligne.setAttribute('x1', '40');
    ligne.setAttribute('y1', '40');
    const rond = document.createElementNS(SVG, 'circle');
    rond.setAttribute('r', '8');
    const lettre = document.createElementNS(SVG, 'text');
    lettre.setAttribute('text-anchor', 'middle');
    lettre.setAttribute('dominant-baseline', 'central');
    lettre.textContent = a.nom;
    g.appendChild(ligne);
    g.appendChild(rond);
    g.appendChild(lettre);
    g.addEventListener('click', () => vue(a.vue));
    axes.appendChild(g);
    a.g = g;
    a.ligne = ligne;
    a.rond = rond;
    a.lettre = lettre;
  });
  racine.appendChild(axes);

  function dessinerAxes() {
    const inverse = camera.quaternion.clone().invert();
    AXES.map((a) => ({ a: a, v: a.v.clone().applyQuaternion(inverse) }))
      .sort((p, q) => p.v.z - q.v.z)
      .forEach((e) => {
        const x = 40 + 26 * e.v.x;
        const y = 40 - 26 * e.v.y;
        e.a.ligne.setAttribute('x2', x.toFixed(1));
        e.a.ligne.setAttribute('y2', y.toFixed(1));
        e.a.rond.setAttribute('cx', x.toFixed(1));
        e.a.rond.setAttribute('cy', y.toFixed(1));
        e.a.lettre.setAttribute('x', x.toFixed(1));
        e.a.lettre.setAttribute('y', y.toFixed(1));
        e.a.g.classList.toggle('derriere', e.v.z < -0.2);
        axes.appendChild(e.a.g);           // l'axe qui vient vers nous est dessiné en dernier
      });
  }

  // ------------------------------------------------------------ légende et réglages du nuage
  legende = element('div', 'carte3d-legende');
  legende.setAttribute('data-role', 'carte3d-legende');
  legende.hidden = true;
  legende.appendChild(element('div', 'carte3d-legende-titre', 'Hauteur au-dessus du sol'));
  legende.appendChild(element('div', 'carte3d-degrade'));
  const graduations = element('div', 'carte3d-graduations');
  ['0', '1,1', '2,2 m'].forEach((t) => graduations.appendChild(element('span', '', t)));
  legende.appendChild(graduations);
  const lignePlafond = element('label', 'carte3d-reglage');
  casePlafond = element('input');
  casePlafond.type = 'checkbox';
  casePlafond.checked = etat.coupe === null;
  casePlafond.setAttribute('data-role', 'carte3d-plafond');
  casePlafond.addEventListener('change', () => coupe(casePlafond.checked ? null : o.hauteurCoupe));
  lignePlafond.appendChild(casePlafond);
  lignePlafond.appendChild(element('span', '', 'Afficher le plafond'));
  // la coque a sa case « Afficher le plafond » dans sa barre (12.2) : celle-ci seulement avec la barre du module
  if (o.barre || o.reglages) legende.appendChild(lignePlafond);
  const ligneTaille = element('label', 'carte3d-reglage');
  ligneTaille.appendChild(element('span', '', 'Taille des points'));
  curseurTaille = element('input');
  curseurTaille.type = 'range';
  curseurTaille.min = String(TAILLES_POINTS.min);
  curseurTaille.max = String(TAILLES_POINTS.max);
  curseurTaille.step = '0.01';
  curseurTaille.value = String(TAILLE_POINTS);
  curseurTaille.setAttribute('data-role', 'carte3d-taille');
  curseurTaille.setAttribute('aria-label', 'Taille des points');
  curseurTaille.addEventListener('input', () => taillePoints(curseurTaille.value));
  ligneTaille.appendChild(curseurTaille);
  legende.appendChild(ligneTaille);
  racine.appendChild(legende);

  // ------------------------------------------------------------ barre flottante (option barre)
  function majBarre() {
    if (!barre) return;
    barre.querySelectorAll('[data-cadrage]').forEach((b) => {
      b.setAttribute('aria-pressed', b.getAttribute('data-cadrage') === etat.vue ? 'true' : 'false');
    });
    barre.querySelectorAll('input[data-calque]').forEach((c) => {
      c.checked = !!etat.calques[c.getAttribute('data-calque')];
    });
  }
  if (o.barre) {
    barre = element('div', 'carte3d-barre');
    barre.setAttribute('data-role', 'carte3d-barre');
    const aides = { dessus: 'Vue de dessus (touche 1)', iso: 'Vue en perspective (touche 2)', face: 'Vue de face, depuis le sud (touche 3)' };
    VUES.forEach((nom) => {
      const b = element('button', 'carte3d-bouton', NOMS_VUES[nom]);
      b.type = 'button';
      b.title = aides[nom];
      b.setAttribute('data-cadrage', nom);
      b.addEventListener('click', () => {
        etat.interaction = true;
        vue(nom);
      });
      barre.appendChild(b);
    });
    const tout = element('button', 'carte3d-bouton', 'Recadrer');
    tout.type = 'button';
    tout.title = 'Tout voir (touche F)';
    tout.setAttribute('data-cadrage', 'recadrer');
    tout.addEventListener('click', () => {
      etat.interaction = true;
      recadrer();
    });
    barre.appendChild(tout);
    const menu = element('details', 'carte3d-menu');
    const resume = element('summary', 'carte3d-bouton', 'Calques');
    resume.title = 'Ce qui est montré dans la vue';
    menu.appendChild(resume);
    const liste = element('div', 'carte3d-menu-liste');
    CALQUES.forEach((nom) => {
      const l = element('label', 'carte3d-reglage');
      const c = element('input');
      c.type = 'checkbox';
      c.checked = etat.calques[nom];
      c.setAttribute('data-calque', nom);
      c.addEventListener('change', () => calque(nom, c.checked));
      l.appendChild(c);
      l.appendChild(element('span', '', NOMS_CALQUES[nom]));
      liste.appendChild(l);
    });
    menu.appendChild(liste);
    barre.appendChild(menu);
    racine.appendChild(barre);
    majBarre();
  }

  // ------------------------------------------------------------ cycle de vie
  const observateur = new ResizeObserver(() => redimensionner());
  observateur.observe(racine);
  redimensionner();
  outil('naviguer');

  function etatPublic() {
    const offset = camera.position.clone().sub(controles.target);
    const angles = G3.anglesDepuisDirection(offset.toArray());
    const calques = {};
    CALQUES.forEach((n) => { calques[n] = etat.calques[n]; });
    const arrondi = (v) => v.toArray().map((x) => Math.round(x * 1000) / 1000);
    return {
      webgl: true, points: etat.points, vue: etat.vue, outil: etat.outil, idOutil: etat.idOutil, calques: calques,
      camera: { position: arrondi(camera.position), cible: arrondi(controles.target),
        distance: Math.round(offset.length() * 1000) / 1000, azimut: angles.azimut, elevation: angles.elevation,
        champ: CHAMP_VISION },
      coupe: etat.coupe, taillePoints: etat.taille, selection: etat.choix ? Object.assign({}, etat.choix) : null,
      salles: salles.liste.length, principal: salles.principal, noeuds: noeuds.reperes.size, zones: zones.length,
      pietons: pietons.size, robot: robot.pose ? { x: robot.pose.x, y: robot.pose.y, theta: robot.pose.theta || 0 } : null,
      monde: etat.monde ? Object.assign({}, etat.monde) : null,
      anime: !!animation, geste: geste ? geste.type : null, bornes: bornesContenu(),
      taille: { largeur: taille().l, hauteur: taille().h },
      pointsSol: etat.pointsSol || 0, modifiables: { salle: modifiable('salle'), noeud: modifiable('noeud') },
      couloirs: noeuds.couloirs.map((c) => ({ a: c.a, b: c.b, de: c.objet.userData.a, vers: c.objet.userData.b })),
    };
  }

  function detruire() {
    etat.actif = false;
    if (rafPrevu) cancelAnimationFrame(rafPrevu);
    rafPrevu = 0;
    observateur.disconnect();
    controles.dispose();
    R.liberer(scene);
    if (grille) R.liberer(grille);
    rendu.dispose();
    racine.remove();
    Object.keys(abonnes).forEach((k) => abonnes[k].clear());
    genresPose.clear();
    if (o.nomGlobal && window[o.nomGlobal] === carte) delete window[o.nomGlobal];
  }

  const carte = {
    chargerNuage: chargerNuage,
    afficherPoints: afficherPoints,
    afficherMonde: afficherMonde,
    afficherCarte2D: afficherCarte2D,
    afficherSalles: afficherSalles,
    afficherItineraires: afficherItineraires,
    afficherZones: afficherZones,
    afficherRobot: afficherRobot,
    afficherPietons: afficherPietons,
    afficherTrajet: afficherTrajet,
    vue: (nom) => {
      etat.interaction = true;
      vue(nom);
    },
    recadrer: (bornes) => {
      etat.interaction = true;
      recadrer(bornes);
    },
    centrerSur: (x, y) => {
      etat.interaction = true;
      centrerSur(x, y);
    },
    calque: calque,
    coupe: coupe,
    outil: outil,
    choisir: choisir,
    surSelection: abonner('selection'),
    surPose: surPose,
    surPointeur: abonner('pointeur'),
    versEcran: versEcran,
    versSol: versSol,
    redimensionner: redimensionner,
    etat: etatPublic,
    detruire: detruire,
    // en plus du contrat : taille des points (m), pixel de la base d'un repère, rendu immédiat (tests)
    taillePoints: taillePoints,
    positionRepere: positionRepere,
    dessiner: () => {
      if (rafPrevu) cancelAnimationFrame(rafPrevu);
      rafPrevu = 0;
      rendre();
    },
  };
  if (o.nomGlobal) window[o.nomGlobal] = carte;
  return carte;
}
