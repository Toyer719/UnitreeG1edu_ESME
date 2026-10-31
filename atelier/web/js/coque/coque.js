// La coque de l'Atelier (vague 5, section 12.2 du plan) : écran d'accueil (Simulation ou Robot réel),
// puis l'espace de travail à la SolidWorks (barre d'outils, ruban, arbre, vue centrale, panneau de
// tâches, barre d'état). Module de l'agent Coquille.
//
// Les écrans (js/ecrans/*.js) s'ouvrent par ouvrir(racine, options) → {modifie(), fermer(), commande?(nom,
// valeur), selectionner?(genre, id), vue?(nom), enregistrer?(), defaire?(), refaire?(), peutDefaire?(),
// peutRefaire?(), recadrer?()} : racine est la vue Plan 2D de la vue centrale ; options : {panneau, mode,
// commande, valeur, vue, carte3d, coque}. Un écran d'avant, ouvrir(racine) seul, marche encore : il dessine
// tout dans la racine.

import { api, urlEtage, urlLieu } from '../api.js';
import { choisirEtage, choisirLieu, contexte, ecouter } from '../contexte.js';
import { abonner, dernierEtat, suivreConnexion } from '../direct.js';
import { apresValidations } from '../formulaire.js';
import { afficherErreur, brancherMessages } from '../messages.js';
import { flechesTenues } from '../teleop.js';
import { afficherAccueil } from './accueil.js';
import { destinationDuHash } from './anciens_hash.js';
import { construireArbre } from './arbre.js';
import { decisionEchap, etatMouvement, monterArret } from './arret.js';
import { construireBarreEtat } from './barre_etat.js';
import { demanderConfirmation, demanderSaisie, fenetreOuverte } from './confirmation.js';
import { icone } from './icones.js';
import { construireEntete, ouvrirPanneau } from './panneau.js';
import { commande as commandeParId, commandesDe, construireRuban, ONGLETS_RUBAN } from './ruban.js';
import { construireVue } from './vue.js';

export const MODES = ['simu', 'reel', 'repetition'];

// Clés du stockage du navigateur (localStorage), toutes préfixées par « atelier. » (section 12.2)
export const CLES_MEMOIRE = {
  mode: 'atelier.mode',                 // simu | reel
  repetition: 'atelier.repetition',     // 1 : Réel sans robot (faux G1) ; 0 sinon
  theme: 'atelier.theme',               // sombre | clair
  lieu: 'atelier.lieu',
  etage: 'atelier.etage',
  onglet: 'atelier.onglet.',            // + simu | reel : dernier onglet du ruban
  vue: 'atelier.vue.',                  // + simu | reel : 3d | plan | camera
  calques: 'atelier.calques',           // JSON {nuage: true, carte2d: false…}
  arbreReplie: 'atelier.arbre.replie',
  rubanReplie: 'atelier.ruban.replie',
  // anciennes clés, encore écrites pour les écrans d'avant
  modeSimulation: 'atelier.mode-simulation',   // simu | repetition | robot
  modeScan: 'atelier.scan.mode',               // simu | robot
  repetitionScan: 'atelier.scan.repetition',
};
const CLE_CASES = 'atelier.cases';                // JSON {accompagner, retour, joysticks} des commandes à cocher
const CLE_PLAFOND = 'atelier.plafond';

// Les écrans : module (chargé à la demande), vues de la vue centrale (vide : l'écran occupe toute la vue,
// sans barre flottante), vue par défaut, et sansLieu (s'ouvre même sans lieu choisi).
const ECRANS = {
  lieux: { id: 'lieux', titre: 'Le lieu', charger: () => import('../ecrans/lieux.js'), vues: [] },
  monde: { id: 'monde', titre: 'Monde', charger: () => import('../ecrans/monde.js'), vues: ['plan', '3d'], vue: 'plan' },
  carte: { id: 'carte', titre: 'Carte', charger: () => import('../ecrans/carte.js'), vues: ['plan', '3d'], vue: 'plan' },
  salles: { id: 'salles', titre: 'Salles', charger: () => import('../ecrans/salles.js'), vues: ['3d', 'plan'], vue: '3d' },
  itineraires: { id: 'itineraires', titre: 'Itinéraires', charger: () => import('../ecrans/itineraires.js'), vues: ['plan', '3d'], vue: 'plan' },
  zones: { id: 'zones', titre: 'Zones', charger: () => import('../ecrans/zones.js'), vues: ['plan', '3d'], vue: 'plan' },
  simulation: { id: 'simulation', titre: 'Simulation', charger: () => import('../ecrans/simulation.js'), vues: ['3d', 'plan', 'camera'], vue: '3d' },
  scan: { id: 'scan', titre: 'Scan', charger: () => import('../ecrans/scan.js'), vues: [] },
  pilotage: { id: 'pilotage', titre: 'Piloter', charger: () => import('../ecrans/pilotage.js'), vues: [], sansLieu: true },
  personnalites: { id: 'personnalites', titre: 'Personnalités', charger: () => import('../ecrans/personnalites.js'), vues: [] },
  dialogues: { id: 'dialogues', titre: 'Dialogues', charger: () => import('../ecrans/dialogues.js'), vues: [] },
  camera: { id: 'camera', titre: 'Caméra', charger: () => import('../ecrans/camera.js'), vues: [] },
};
// Écran ouvert par chaque onglet du ruban, quand on clique sur l'onglet lui-même
const ECRAN_DE_L_ONGLET = {
  dessiner: { ecran: 'monde', commande: 'choisir' }, placer: { ecran: 'salles' }, simuler: { ecran: 'simulation' },
  scanner: { ecran: 'scan' }, naviguer: { ecran: 'simulation' }, piloter: { ecran: 'pilotage' },
  equipe: { ecran: 'personnalites', commande: 'ouvrir' },
};
// Commandes qui sont des actions ponctuelles (pas un outil qui reste enfoncé)
const ACTIONS = ['lancer', 'arreter', 'y-aller', 'reperer', 'bloquer', 'debloquer', 'main', 'postures', 'gestes',
  'utiliser', 'scan', 'fin', 'refaire'];
const NOMS_MODES = { simu: 'SIMULATION', reel: 'RÉEL', repetition: 'RÉPÉTITION' };
const PERIODE_BARRE_MS = 400;
const PERIODE_BATTERIE_MS = 5000;

const etat = {
  mode: 'simu',
  repetition: false,
  telecommande: false,
  accueil: null,
  espace: null,          // éléments de l'espace de travail
  ruban: null,
  arbre: null,
  barreEtat: null,
  arret: null,
  vue: null,
  carte3d: null,
  carte3dCle: null,
  carte3dDesabonner: [],
  cameraVue: null,
  ecran: null,           // {id, def, instance, racine, commande, ancien}
  ouverture: 0,
  cases: { accompagner: false, retour: true, joysticks: true },
  ecouteursVue: new Set(),
  minuteries: [],
  desabonner: [],
  ignorerLieu: false,
  pointeurPlan: null,
  connecte: false,       // la liaison /ws/etat est ouverte (sinon : on ne sait pas ce qui tourne)
};

function el(balise, classe, texte) {
  const e = document.createElement(balise);
  if (classe) e.className = classe;
  if (texte !== undefined && texte !== null) e.textContent = texte;
  return e;
}

function lire(cle) {
  try {
    return localStorage.getItem(cle);
  } catch (e) {
    return null;
  }
}

function ecrire(cle, valeur) {
  try {
    if (valeur === null || valeur === undefined) localStorage.removeItem(cle);
    else localStorage.setItem(cle, valeur);
  } catch (e) {
    // navigation privée ou stockage bloqué : on s'en passe
  }
}

function lireJson(cle, defaut) {
  try {
    const v = JSON.parse(lire(cle) || 'null');
    return v && typeof v === 'object' ? v : defaut;
  } catch (e) {
    return defaut;
  }
}

// 'simu' | 'reel' | 'repetition' (Réel avec la case « Répétition sans robot »)
export function modeCourant() {
  if (etat.mode !== 'reel') return 'simu';
  return etat.repetition ? 'repetition' : 'reel';
}

function modeRuban() {
  return etat.mode === 'reel' ? 'reel' : 'simu';
}

// ---------------------------------------------------------------- thème

export function lireTheme() {
  return lire(CLES_MEMOIRE.theme) === 'clair' ? 'clair' : 'sombre';
}

export function appliquerTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme === 'clair' ? 'clair' : 'sombre');
}

function basculerTheme() {
  const t = lireTheme() === 'clair' ? 'sombre' : 'clair';
  ecrire(CLES_MEMOIRE.theme, t);
  appliquerTheme(t);
  document.dispatchEvent(new CustomEvent('atelier-theme', { detail: t }));
}

// ---------------------------------------------------------------- mémoire du mode (anciennes clés comprises)

function memoriserMode() {
  ecrire(CLES_MEMOIRE.mode, etat.mode);
  ecrire(CLES_MEMOIRE.repetition, etat.repetition ? '1' : '0');
  ecrire(CLES_MEMOIRE.modeSimulation, etat.mode === 'simu' ? 'simu' : (etat.repetition ? 'repetition' : 'robot'));
  ecrire(CLES_MEMOIRE.modeScan, etat.mode === 'simu' ? 'simu' : 'robot');
  ecrire(CLES_MEMOIRE.repetitionScan, etat.repetition ? '1' : '0');
}

// Mode retenu pour une ancienne adresse : {mode, repetition, commande?}
function modeMemorise(destination, nom) {
  const ancien = lire(CLES_MEMOIRE.modeSimulation);
  if (destination.mode === 'simu') return { mode: 'simu', repetition: false };
  if (destination.mode === 'reel') {
    return { mode: 'reel', repetition: lire(CLES_MEMOIRE.repetition) === '1' || ancien === 'repetition' };
  }
  if (nom === 'simulation' && ancien) {
    return { mode: ancien === 'simu' ? 'simu' : 'reel', repetition: ancien === 'repetition' };
  }
  if (nom === 'scan' && lire(CLES_MEMOIRE.modeScan)) {
    const simu = lire(CLES_MEMOIRE.modeScan) === 'simu';
    return { mode: simu ? 'simu' : 'reel', repetition: !simu && lire(CLES_MEMOIRE.repetitionScan) === '1',
      commande: simu ? 'simule' : null };
  }
  const mode = lire(CLES_MEMOIRE.mode) === 'reel' ? 'reel' : 'simu';
  return { mode: mode, repetition: mode === 'reel' && lire(CLES_MEMOIRE.repetition) === '1' };
}

// ---------------------------------------------------------------- démarrage

// Démarre l'Atelier : l'accueil, ou directement l'espace de travail si l'adresse a un hash (#salles…)
// ou ?recharger.
export async function demarrerCoque(options) {
  options = options || {};
  appliquerTheme(lireTheme());
  etat.cases = Object.assign(etat.cases, lireJson(CLE_CASES, {}));
  try {
    contexte.serveur = await api.lire('/api/etat');
  } catch (e) {
    contexte.serveur = null;
  }
  ecouter('aller-ecran', (id) => {
    if (etat.espace && ECRANS[id]) ouvrirEcran(id, null, undefined, { forcer: true });
  });
  ecouter('lieu', () => {
    // un écran d'avant a changé de lieu ou d'étage (ex. l'adoption d'un scan) : la coque suit
    if (etat.ignorerLieu || !etat.espace) return;
    majChoixLieu();
    rafraichirLieu();
  });
  window.addEventListener('hashchange', () => allerAuHash(false));
  window.addEventListener('beforeunload', (ev) => {
    if (ecranModifie()) {
      ev.preventDefault();
      ev.returnValue = '';
    }
  });
  // en capture, sur la fenêtre : la coque voit Échap avant les menus et les fenêtres qui se ferment avec
  window.addEventListener('keydown', clavier, true);
  suivreConnexion((ok) => { etat.connecte = ok; });
  abonner(() => {});      // /ws/etat dès l'accueil : on sait ce qui tourne (Échap, ARRÊT de l'accueil)
  return allerAuHash(true, options);
}

async function allerAuHash(premiereFois) {
  const nom = location.hash.replace(/^#/, '');
  const destination = destinationDuHash(nom);
  const recharger = /[?&]recharger\b/.test(location.search);
  if (!premiereFois && !destination) return null;
  if (destination && destination.accueil) return retourAccueil(true);
  if (!destination && !recharger) return retourAccueil(true);
  const choix = destination ? modeMemorise(destination, nom) : modeMemorise({ mode: 'memoire' }, '');
  const lieu = lire(CLES_MEMOIRE.lieu);
  const sansLieu = !!(destination && destination.sansLieu);
  if (!lieu && !sansLieu) return retourAccueil(true);
  let commandeNom = null;
  if (destination && destination.commande) {
    const cmd = commandeParId(destination.commande);
    commandeNom = cmd ? cmd.commande : null;
  }
  if (choix.commande) commandeNom = choix.commande;
  return ouvrirEspace({ mode: choix.mode, repetition: choix.repetition, lieu: lieu, etage: lire(CLES_MEMOIRE.etage),
    ecran: destination ? destination.ecran : null, commande: commandeNom, sansLieu: sansLieu });
}

// ---------------------------------------------------------------- accueil

// Mode envoyé par l'ARRÊT de l'accueil : celui du dernier espace ouvert (le serveur ajoute le verrou si la
// navigation qui tourne est celle du robot ou de la répétition)
function modeMemoriseArret() {
  if (lire(CLES_MEMOIRE.mode) !== 'reel') return 'simu';
  return lire(CLES_MEMOIRE.repetition) === '1' ? 'repetition' : 'reel';
}

export async function retourAccueil(sansConfirmer) {
  if (!sansConfirmer && !(await quitterEcranPermis())) return false;
  fermerEspace();
  if (etat.accueil) etat.accueil.fermer();
  const racine = document.getElementById('atelier');
  brancherMessages(null);
  etat.accueil = afficherAccueil(racine, {
    surOuvrir: (choix) => ouvrirEspace(choix),
    modeArret: modeMemoriseArret(),
    surPilotageSansLieu: () => ouvrirEspace({ mode: 'reel', repetition: lire(CLES_MEMOIRE.repetition) === '1',
      lieu: null, ecran: 'pilotage', sansLieu: true }),
    surTheme: basculerTheme,
  });
  if (location.hash) history.replaceState(null, '', location.pathname);
  return true;
}

// ---------------------------------------------------------------- espace de travail

// Ouvre l'espace de travail : {mode: 'simu'|'reel', repetition, lieu, etage, telecommande, ecran?, commande?}
export async function ouvrirEspace(choix) {
  choix = choix || {};
  const numero = ++etat.ouverture;
  etat.mode = choix.mode === 'reel' ? 'reel' : 'simu';
  etat.repetition = etat.mode === 'reel' && !!choix.repetition;
  if (choix.telecommande !== undefined) etat.telecommande = !!choix.telecommande;
  memoriserMode();
  etat.ignorerLieu = true;
  try {
    if (choix.lieu) {
      await choisirLieu(choix.lieu, choix.etage);
    } else {
      await choisirLieu(null);
    }
  } catch (e) {
    etat.ignorerLieu = false;
    if (e && e.statut === 404) ecrire(CLES_MEMOIRE.lieu, null);
    await retourAccueil(true);
    afficherErreur(e);
    return null;
  }
  etat.ignorerLieu = false;
  if (numero !== etat.ouverture) return null;
  if (etat.accueil) {
    etat.accueil.fermer();
    etat.accueil = null;
  }
  construireEspace();
  await preparerCarte3D();
  if (numero !== etat.ouverture) return null;
  if (choix.ecran) {
    await ouvrirEcran(choix.ecran, choix.commande || null, undefined, { forcer: true });
  } else {
    const onglet = lire(CLES_MEMOIRE.onglet + modeRuban());
    const ids = ONGLETS_RUBAN[modeRuban()].map((o) => o.id);
    await ouvrirOnglet(ids.indexOf(onglet) >= 0 ? onglet : ids[ids.indexOf('placer') >= 0 ? ids.indexOf('placer') : 0]);
  }
  return etat.espace;
}

function construireEspace() {
  fermerEspace();
  const racine = document.getElementById('atelier');
  racine.textContent = '';
  const espace = el('div', 'espace');
  espace.setAttribute('data-role', 'espace');
  espace.setAttribute('data-mode', modeCourant());
  if (lire(CLES_MEMOIRE.arbreReplie) === '1') espace.classList.add('arbre-replie');

  // ------------------------------------------------ barre d'outils
  const barre = el('header', 'barre-outils');
  barre.setAttribute('data-role', 'barre-outils');
  // tout sauf ARRÊT, dans une partie qui rétrécit : ARRÊT reste toujours entier et visible, même étroit
  const gauche = el('div', 'barre-outils-gauche');
  const accueil = boutonIcone('maison', 'Accueil : changer de mode ou de lieu', 'accueil-retour');
  accueil.addEventListener('click', () => retourAccueil(false));
  gauche.appendChild(accueil);
  const marque = el('span', 'marque marque-barre', 'Atelier G1');
  gauche.appendChild(marque);
  gauche.appendChild(el('span', 'barre-separateur'));
  // l'arbre : tiroir sous 1100 px ; au-dessus, ce bouton n'apparaît que l'arbre replié, pour le rouvrir
  const tiroirArbre = boutonIcone('arbre', 'Montrer ou cacher l\'arbre du lieu', 'basculer-arbre');
  tiroirArbre.classList.add('seulement-etroit');
  tiroirArbre.addEventListener('click', () => {
    if (ecranEtroit()) basculerTiroir('arbre');
    else replierArbre(false);
  });
  gauche.appendChild(tiroirArbre);
  const choixLieu = el('label', 'choix-barre choix-lieu');
  choixLieu.appendChild(icone('lieu', 18));
  const selectLieu = el('select');
  selectLieu.setAttribute('data-role', 'lieu');
  selectLieu.setAttribute('aria-label', 'Lieu');
  choixLieu.appendChild(selectLieu);
  gauche.appendChild(choixLieu);
  gauche.appendChild(el('span', 'barre-chevron', '›'));
  const choixEtage = el('label', 'choix-barre choix-etage');
  const selectEtage = el('select');
  selectEtage.setAttribute('data-role', 'etage');
  selectEtage.setAttribute('aria-label', 'Étage');
  choixEtage.appendChild(selectEtage);
  gauche.appendChild(choixEtage);
  const pastilleMode = el('button', 'pastille-mode', NOMS_MODES[modeCourant()]);
  pastilleMode.type = 'button';
  pastilleMode.setAttribute('data-role', 'mode');
  pastilleMode.title = 'Changer de mode : retour à l\'accueil';
  pastilleMode.addEventListener('click', () => retourAccueil(false));
  gauche.appendChild(pastilleMode);
  gauche.appendChild(el('span', 'barre-separateur'));
  const defaire = boutonIcone('defaire', 'Annuler (Ctrl+Z)', 'defaire');
  defaire.addEventListener('click', () => appelerEcran('defaire'));
  const refaire = boutonIcone('refaire', 'Rétablir (Ctrl+Y)', 'refaire');
  refaire.addEventListener('click', () => appelerEcran('refaire'));
  const enregistrer = el('button', 'bouton-barre bouton-enregistrer');
  enregistrer.type = 'button';
  enregistrer.setAttribute('data-role', 'enregistrer');
  enregistrer.title = 'Enregistrer (Ctrl+S)';
  enregistrer.appendChild(icone('enregistrer', 18));
  enregistrer.appendChild(el('span', 'bouton-barre-texte', 'Enregistrer'));
  enregistrer.addEventListener('click', () => appelerEcran('enregistrer'));
  [defaire, refaire, enregistrer].forEach((b) => gauche.appendChild(b));
  gauche.appendChild(el('span', 'espace-flexible'));
  const etats = el('div', 'etats-barre');
  etats.setAttribute('data-role', 'etats');
  const pastilles = {};
  [['serveur', 'serveur', 'Serveur'], ['ros', 'ros', 'ROS 2'], ['robot', 'robot', 'Robot'], ['batterie', 'batterie', '']]
    .forEach((d) => {
      const p = el('span', 'etat-pastille');
      p.setAttribute('data-etat', d[0]);
      p.appendChild(icone(d[1], 16));
      p.appendChild(el('span', 'etat-pastille-texte', d[2]));
      p.setAttribute('data-genre', 'inconnu');
      pastilles[d[0]] = p;
      etats.appendChild(p);
    });
  pastilles.robot.hidden = etat.mode !== 'reel';
  pastilles.batterie.hidden = true;
  gauche.appendChild(etats);
  const theme = boutonIcone('theme', 'Thème clair ou sombre', 'theme');
  theme.addEventListener('click', basculerTheme);
  gauche.appendChild(theme);
  const reglages = boutonIcone('reglages', 'Réglages et aide', 'reglages');
  gauche.appendChild(reglages);
  const tiroirPanneau = boutonIcone('panneau', 'Montrer ou cacher le panneau', 'basculer-panneau');
  tiroirPanneau.classList.add('seulement-etroit');
  tiroirPanneau.addEventListener('click', () => basculerTiroir('panneau'));
  gauche.appendChild(tiroirPanneau);
  const zoneArret = el('div', 'zone-arret');
  barre.appendChild(gauche);
  barre.appendChild(zoneArret);
  espace.appendChild(barre);

  // ------------------------------------------------ ruban
  const ruban = el('section', 'ruban');
  espace.appendChild(ruban);

  // ------------------------------------------------ centre : arbre, vue, panneau
  const centre = el('div', 'centre');
  const arbre = el('aside', 'arbre');
  const enteteArbre = el('div', 'arbre-entete');
  enteteArbre.appendChild(el('span', 'arbre-titre', 'Le lieu'));
  const boutonReplier = boutonIcone('replier-gauche', 'Replier l\'arbre (le bouton ▸ Le lieu le rouvre)', 'replier-arbre');
  boutonReplier.classList.add('petit');
  boutonReplier.addEventListener('click', () => {
    if (ecranEtroit()) espace.classList.remove('tiroir-arbre');
    else replierArbre(true);
  });
  enteteArbre.appendChild(boutonReplier);
  const contenuArbre = el('div', 'arbre-contenu');
  arbre.appendChild(enteteArbre);
  arbre.appendChild(contenuArbre);
  const vue = el('main', 'vue');
  const panneau = el('aside', 'panneau');
  panneau.setAttribute('data-role', 'panneau');
  const corps = el('div', 'panneau-corps');
  corps.setAttribute('data-role', 'panneau-corps');
  panneau.appendChild(corps);
  construireEntete(panneau, corps);
  centre.appendChild(arbre);
  centre.appendChild(vue);
  centre.appendChild(panneau);
  espace.appendChild(centre);
  const voile = el('div', 'voile-tiroir');
  voile.addEventListener('click', () => {
    espace.classList.remove('tiroir-arbre', 'tiroir-panneau');
  });
  espace.appendChild(voile);

  // ------------------------------------------------ barre d'état
  const barreEtat = el('footer', 'barre-etat');
  espace.appendChild(barreEtat);
  racine.appendChild(espace);

  etat.espace = { racine: espace, selectLieu: selectLieu, selectEtage: selectEtage, pastilles: pastilles,
    defaire: defaire, refaire: refaire, enregistrer: enregistrer, panneau: panneau, corps: corps, arbre: contenuArbre,
    reglages: reglages, pastilleMode: pastilleMode };
  etat.barreEtat = construireBarreEtat(barreEtat);
  brancherMessages((texte, genre, details, sortie) => etat.barreEtat.message(texte, genre, details, sortie));
  etat.arret = monterArret(zoneArret, { mode: modeCourant(), message: (t, g, d) => etat.barreEtat.message(t, g, d) });
  etat.vue = construireVue(vue, {
    surVue: (nom, parUtilisateur) => changementDeVue(nom, parUtilisateur),
    surCadrage: (nom) => cadrer(nom),
    surCalque: (nom, visible) => changerCalque(nom, visible),
    surPlafond: (oui) => {
      ecrire(CLE_PLAFOND, oui ? '1' : '0');
      if (etat.carte3d) etat.carte3d.coupe(oui ? null : 2.2);
    },
  });
  // arbre replié : une languette au bord gauche de la vue le rouvre (elle n'existe que l'arbre replié)
  const languette = el('button', 'languette-arbre');
  languette.type = 'button';
  languette.setAttribute('data-role', 'deplier-arbre');
  languette.title = 'Montrer l\'arbre du lieu';
  languette.appendChild(icone('deplier-droite', 16));
  languette.appendChild(el('span', 'languette-texte', 'Le lieu'));
  languette.addEventListener('click', () => replierArbre(false));
  vue.appendChild(languette);
  etat.ruban = construireRuban(ruban, {
    mode: modeCourant(),
    onglet: lire(CLES_MEMOIRE.onglet + modeRuban()),
    replie: lire(CLES_MEMOIRE.rubanReplie) === '1',
    surCommande: (cmd, valeur) => executerCommande(cmd, valeur),
    surOnglet: (id) => ouvrirOnglet(id),
    surRepli: (replie) => {
      ecrire(CLES_MEMOIRE.rubanReplie, replie ? '1' : '0');
      redimensionnerVues();
    },
  });
  ['accompagner', 'retour', 'joysticks'].forEach((nom) => {
    COMMANDES_A_COCHER.forEach((id) => {
      const cmd = commandeParId(id);
      if (cmd && cmd.commande === nom) etat.ruban.coche(id, etat.cases[nom]);
    });
  });
  etat.arbre = construireArbre(contenuArbre, {
    lieu: contexte.lieu, etage: contexte.etage, mode: modeRuban(),
    surChoix: (choix) => choixDansArbre(choix, false),
    surDoubleClic: (choix) => choixDansArbre(choix, true),
  });
  menuReglages(reglages);
  majChoixLieu();
  griserSansLieu();
  selectLieu.addEventListener('change', () => changerLieu(selectLieu.value));
  selectEtage.addEventListener('change', () => changerEtage(selectEtage.value));

  // états en direct (serveur, ROS 2, robot) et boutons de la barre
  suivreConnexion((ok) => {
    if (!etat.espace) return;
    majPastille('serveur', ok ? 'ok' : 'ko', ok ? 'Serveur' : 'Serveur injoignable');
    etat.barreEtat.liaison(ok ? '' : 'Serveur injoignable', ok ? 'ok' : 'ko');
  });
  etat.desabonner.push(abonner(recevoirDirect));
  // x, y sous le pointeur dans le Plan 2D (plan.js) ; en 3D, la carte 3D les donne (surPointeur)
  const surPointeurPlan = (ev) => {
    if (!etat.barreEtat || !etat.vue || etat.vue.courante() !== 'plan') return;
    const d = ev.detail;
    etat.barreEtat.coordonnees(d ? d.x : null, d ? d.y : null);
  };
  document.addEventListener('atelier-pointeur', surPointeurPlan);
  etat.desabonner.push(() => document.removeEventListener('atelier-pointeur', surPointeurPlan));
  etat.minuteries.push(setInterval(majBarre, PERIODE_BARRE_MS));
  if (etat.mode === 'reel') {
    lireBatterie();
    etat.minuteries.push(setInterval(lireBatterie, PERIODE_BATTERIE_MS));
  }
}

const COMMANDES_A_COCHER = ['simulation.accompagner', 'simulation.retour', 'pilotage.joysticks'];

function boutonIcone(nomIcone, titre, role) {
  const b = el('button', 'bouton-icone');
  b.type = 'button';
  b.title = titre;
  b.setAttribute('aria-label', titre);
  if (role) b.setAttribute('data-role', role);
  b.appendChild(icone(nomIcone, 20));
  return b;
}

function ecranEtroit() {
  return window.innerWidth < 1100;
}

// Replie (oui) ou rouvre l'arbre du lieu (écrans larges ; sous 1100 px, l'arbre est un tiroir)
function replierArbre(oui) {
  if (!etat.espace) return;
  etat.espace.racine.classList.toggle('arbre-replie', !!oui);
  ecrire(CLES_MEMOIRE.arbreReplie, oui ? '1' : '0');
  redimensionnerVues();
}

function basculerTiroir(quoi) {
  const e = etat.espace.racine;
  const classe = 'tiroir-' + quoi;
  const ouvert = !e.classList.contains(classe);
  e.classList.remove('tiroir-arbre', 'tiroir-panneau');
  if (ouvert) e.classList.add(classe);
}

function menuReglages(bouton) {
  bouton.setAttribute('aria-haspopup', 'menu');
  bouton.addEventListener('click', () => {
    const existant = document.querySelector('.menu-reglages');
    if (existant) {
      existant.remove();
      return;
    }
    const menu = el('div', 'menu-ruban menu-reglages');
    menu.setAttribute('role', 'menu');
    const item = (texte, nomIcone, action) => {
      const b = el('button', 'menu-ruban-choix');
      b.type = 'button';
      b.setAttribute('role', 'menuitem');
      b.appendChild(icone(nomIcone, 18));
      b.appendChild(el('span', '', texte));
      b.addEventListener('click', () => {
        menu.remove();
        action();
      });
      menu.appendChild(b);
    };
    item('Thème clair ou sombre', 'theme', basculerTheme);
    const replie = etat.espace.racine.classList.contains('arbre-replie');
    if (!ecranEtroit()) item(replie ? 'Montrer l\'arbre du lieu' : 'Cacher l\'arbre du lieu', 'arbre', () => replierArbre(!replie));
    item('Ce qui tourne (commandes lancées)', 'console', () => etat.barreEtat.ceQuiTourne(true));
    item('Derniers messages', 'messages', () => etat.barreEtat.journal(true));
    if (contexte.lieu) item('Vérifier le lieu', 'valider', () => ouvrirEcran('lieux', 'verifier'));
    item('Raccourcis clavier', 'aide', () => {
      demanderConfirmation('Échap : ARRÊT dès que le robot bouge ou que quelque chose tourne (simulation, '
        + 'navigation, pilotage). Sinon, Échap ferme le menu ou la fenêtre, annule la saisie ou l\'outil en cours.\n\n'
        + '- Ctrl+Z, Ctrl+Y : annuler, rétablir\n- Ctrl+S : enregistrer (même pendant une saisie)\n- F : tout voir (vue 3D)\n'
        + '- Ctrl+Page haut, Ctrl+Page bas : onglet précédent, suivant\n- Suppr : supprimer l\'élément choisi',
      { titre: 'Raccourcis clavier', ok: 'Compris', annuler: 'Fermer' });
    });
    const r = bouton.getBoundingClientRect();
    etat.espace.racine.appendChild(menu);
    menu.style.left = Math.max(8, r.right - menu.offsetWidth) + 'px';
    menu.style.top = (r.bottom + 4) + 'px';
    const fermer = (ev) => {
      if (!menu.contains(ev.target) && !bouton.contains(ev.target)) {
        menu.remove();
        document.removeEventListener('mousedown', fermer, true);
      }
    };
    document.addEventListener('mousedown', fermer, true);
  });
}

function fermerEspace() {
  fermerEcran();
  detruireCarte3D();
  if (etat.cameraVue) {
    try {
      etat.cameraVue.detruire();
    } catch (e) {
      // la vue de la caméra est déjà détruite
    }
    etat.cameraVue = null;
  }
  etat.minuteries.forEach((m) => clearInterval(m));
  etat.minuteries = [];
  etat.desabonner.forEach((f) => f());
  etat.desabonner = [];
  if (etat.ruban) etat.ruban.detruire();
  if (etat.arbre) etat.arbre.detruire();
  if (etat.arret) etat.arret.detruire();
  if (etat.vue) etat.vue.detruire();
  if (etat.barreEtat) etat.barreEtat.detruire();
  etat.ruban = etat.arbre = etat.arret = etat.vue = etat.barreEtat = null;
  etat.espace = null;
  document.querySelectorAll('.menu-ruban').forEach((m) => m.remove());
}

// ---------------------------------------------------------------- lieu et étage

async function majChoixLieu() {
  if (!etat.espace) return;
  const s = etat.espace.selectLieu;
  const e = etat.espace.selectEtage;
  let liste = [];
  try {
    liste = await api.lire('/api/lieux');
  } catch (err) {
    liste = [];
  }
  if (!etat.espace) return;
  s.textContent = '';
  if (!contexte.lieu) {
    const o = el('option', '', 'Aucun lieu');
    o.value = '';
    s.appendChild(o);
  }
  liste.forEach((l) => {
    const o = el('option', '', l.nom);
    o.value = l.id;
    s.appendChild(o);
  });
  s.value = contexte.lieu || '';
  e.textContent = '';
  const info = contexte.infoLieu;
  (info ? info.etages : []).forEach((x) => {
    const o = el('option', '', x.nom);
    o.value = x.id;
    e.appendChild(o);
  });
  e.value = contexte.etage || '';
  e.disabled = !info;
  e.parentNode.hidden = !info;
}

async function changerLieu(id) {
  if (!(await quitterEcranPermis())) {
    etat.espace.selectLieu.value = contexte.lieu || '';
    return;
  }
  const ecran = etat.ecran ? { id: etat.ecran.id, commande: etat.ecran.commande } : null;
  fermerEcran();
  await ouvrirEspace({ mode: etat.mode, repetition: etat.repetition, lieu: id || null,
    ecran: ecran && (id || ECRANS[ecran.id].sansLieu) ? ecran.id : null, commande: ecran ? ecran.commande : null });
}

async function changerEtage(id) {
  if (!(await quitterEcranPermis())) {
    etat.espace.selectEtage.value = contexte.etage || '';
    return;
  }
  etat.ignorerLieu = true;
  choisirEtage(id);
  etat.ignorerLieu = false;
  await rafraichirLieu();
}

// Après un changement d'étage (ou de lieu par un écran d'avant) : arbre, carte 3D, écran rouvert
async function rafraichirLieu() {
  if (!etat.espace) return;
  const ecran = etat.ecran ? { id: etat.ecran.id, commande: etat.ecran.commande } : null;
  fermerEcran();
  majChoixLieu();
  etat.arbre.reglages({ lieu: contexte.lieu, etage: contexte.etage });
  etat.arbre.rafraichir();
  griserSansLieu();
  await preparerCarte3D();
  if (ecran) await ouvrirEcran(ecran.id, ecran.commande, undefined, { forcer: true });
}

function griserSansLieu() {
  if (!etat.ruban) return;
  commandesDe(modeCourant()).forEach((cmd) => {
    const ecran = ECRANS[cmd.ecran];
    etat.ruban.griser(cmd.id, !contexte.lieu && !(ecran && ecran.sansLieu)
      ? 'Ouvrez d\'abord un lieu (⌂ Accueil)' : null);
  });
}

// ---------------------------------------------------------------- ruban et écrans

async function ouvrirOnglet(id) {
  if (!etat.ruban) return;
  etat.ruban.choisirOnglet(id);
  ecrire(CLES_MEMOIRE.onglet + modeRuban(), id);
  if (etat.ecran && ongletDeLEcran(etat.ecran.id, etat.ecran.commande) === id) return;
  const cible = ECRAN_DE_L_ONGLET[id];
  if (!cible) return;
  if (!contexte.lieu && !(ECRANS[cible.ecran] && ECRANS[cible.ecran].sansLieu)) {
    fermerEcran();
    panneauSansLieu();
    return;
  }
  await ouvrirEcran(cible.ecran, cible.commande || null);
}

// Onglet du ruban d'un écran ouvert (d'après la commande qui l'a ouvert, sinon la première de l'écran)
function ongletDeLEcran(idEcran, nomCommande) {
  const liste = commandesDe(modeCourant()).filter((c) => c.ecran === idEcran);
  const exacte = liste.find((c) => c.commande === nomCommande && !c.avance);
  const premiere = liste.find((c) => !c.avance) || liste[0];
  return exacte ? exacte.onglet : (premiere ? premiere.onglet : null);
}

function idCommande(idEcran, nom) {
  const cmd = commandesDe(modeCourant()).find((c) => c.ecran === idEcran && c.commande === nom);
  return cmd ? cmd.id : null;
}

// Exécute une commande du ruban par son identifiant (registre COMMANDES de ruban.js)
export function ouvrirCommande(id, valeur) {
  const cmd = commandeParId(id);
  if (!cmd || !etat.espace) return false;
  if (cmd.modes.indexOf(modeRuban()) < 0) return false;
  executerCommande(cmd, valeur);
  return true;
}

async function executerCommande(cmd, valeur) {
  if (cmd.case) {
    etat.cases[cmd.commande] = !!valeur;
    ecrire(CLE_CASES, JSON.stringify(etat.cases));
  }
  if (etat.ruban.onglet() !== cmd.onglet && !cmd.avance) etat.ruban.choisirOnglet(cmd.onglet);
  if (cmd.case && etat.ecran && etat.ecran.id !== cmd.ecran) return;   // retenue pour l'écran, sans l'ouvrir
  // d'abord l'aide et la commande enfoncée par défaut ; l'écran peut les préciser en recevant la commande
  const avant = etat.ecran && etat.ecran.id === cmd.ecran;
  if (avant) {
    if (!cmd.case && ACTIONS.indexOf(cmd.commande) < 0) etat.ruban.activer(cmd.id);
    etat.barreEtat.outil(cmd.aide);
  }
  await ouvrirEcran(cmd.ecran, cmd.commande, valeur, { vue: cmd.vue });
}

function ecranModifie() {
  const e = etat.ecran;
  if (!e || !e.instance || !e.instance.modifie) return false;
  try {
    return !!e.instance.modifie();
  } catch (err) {
    return false;
  }
}

async function quitterEcranPermis() {
  if (!ecranModifie()) return true;
  return demanderConfirmation('Les modifications de « ' + etat.ecran.def.titre + ' » ne sont pas enregistrées. '
    + 'Les abandonner ?', { titre: 'Modifications non enregistrées', ok: 'Abandonner', annuler: 'Rester ici', danger: true });
}

function fermerEcran() {
  const e = etat.ecran;
  etat.ecran = null;
  if (e && e.instance && e.instance.fermer) {
    try {
      e.instance.fermer();
    } catch (err) {
      console.error(err);
    }
  }
  if (e && etat.vue) {
    e.racine.textContent = '';
    e.racine.className = 'vue-calque vue-plan';
    e.racine.removeAttribute('data-ecran');
  }
  if (etat.espace) {
    ouvrirPanneau(etat.espace.corps, { titre: '' });
    etat.espace.racine.classList.remove('plein-ecran');
  }
  if (etat.ruban) etat.ruban.activer(null);
  etat.ecouteursVue.clear();
}

function panneauSansLieu() {
  const p = ouvrirPanneau(etat.espace.corps, { titre: 'Aucun lieu ouvert' });
  p.corps.appendChild(el('p', 'panneau-texte', 'Ces commandes travaillent sur un lieu.'));
  const b = el('button', 'bouton bouton-principal', 'Choisir un lieu');
  b.type = 'button';
  b.addEventListener('click', () => retourAccueil(false));
  p.corps.appendChild(b);
}

function vuesPermises(def) {
  let vues = def.vues.slice();
  if (modeRuban() !== 'reel') vues = vues.filter((v) => v !== 'camera');
  if (!carte3dPrete()) vues = vues.filter((v) => v !== '3d');
  return vues;
}

// Ouvre un écran (ou lui passe la commande s'il est déjà ouvert). plus : {vue, forcer}
async function ouvrirEcran(id, nomCommande, valeur, plus) {
  plus = plus || {};
  const def = ECRANS[id];
  if (!def || !etat.espace) return false;
  if (etat.ecran && etat.ecran.id === id && etat.ecran.instance && !plus.forcer) {
    if (plus.vue && etat.vue.permises().indexOf(plus.vue) >= 0) etat.vue.choisir(plus.vue);
    if (nomCommande && etat.ecran.instance.commande) {
      try {
        etat.ecran.instance.commande(nomCommande, valeur);
      } catch (e) {
        afficherErreur(e);
      }
    }
    etat.ecran.commande = nomCommande || etat.ecran.commande;
    return true;
  }
  if (!plus.forcer && !(await quitterEcranPermis())) return false;
  const numero = ++etat.ouverture;
  // un autre écran : le message de l'écran d'avant ne reste pas dans la barre d'état (il est dans le journal)
  if (etat.ecran && etat.ecran.id !== id && etat.barreEtat) etat.barreEtat.effacer();
  fermerEcran();
  if (!def.sansLieu && (!contexte.lieu || !contexte.etage)) {
    panneauSansLieu();
    return false;
  }
  const racine = etat.vue.plan;
  racine.textContent = '';
  racine.className = 'vue-calque vue-plan ecran ecran-' + id + (def.vues.length ? '' : ' ecran-page');
  racine.setAttribute('data-ecran', id);
  const vues = vuesPermises(def);
  etat.vue.permettre(vues);
  let vue = plus.vue && vues.indexOf(plus.vue) >= 0 ? plus.vue : null;
  if (!vue) {
    const memoire = lire(CLES_MEMOIRE.vue + modeRuban() + '.' + id);
    vue = memoire && vues.indexOf(memoire) >= 0 ? memoire : (vues.indexOf(def.vue) >= 0 ? def.vue : (vues[0] || 'plan'));
  }
  if (!vues.length) vue = 'plan';
  etat.vue.choisir(vue);
  ouvrirPanneau(etat.espace.corps, { titre: def.titre });
  etat.espace.corps.appendChild(el('p', 'panneau-note chargement-panneau', 'Chargement…'));
  let module;
  try {
    module = await def.charger();
  } catch (e) {
    if (numero === etat.ouverture) {
      ouvrirPanneau(etat.espace.corps, { titre: def.titre });
      etat.barreEtat.message('L\'écran « ' + def.titre + ' » n\'a pas pu être chargé : ' + (e && e.message ? e.message : e)
        + '. Rechargez la page (F5).', 'erreur');
    }
    return false;
  }
  if (numero !== etat.ouverture || !etat.espace) return false;
  ouvrirPanneau(etat.espace.corps, { titre: def.titre });
  const ancien = !module.ouvrir || module.ouvrir.length < 2;
  if (ancien) racine.classList.add('ecran-ancien');
  const options = {
    panneau: etat.espace.corps, mode: modeCourant(), commande: nomCommande || null, valeur: valeur,
    vue: etat.vue.courante(), carte3d: carte3dPrete() ? etat.carte3d : null, coque: interfaceCoque(id),
  };
  let instance = null;
  try {
    instance = ancien ? module.ouvrir(racine) : module.ouvrir(racine, options);
  } catch (e) {
    afficherErreur(e);
  }
  instance = instance || { modifie: () => false, fermer: () => {} };
  etat.ecran = { id: id, def: def, instance: instance, racine: racine, commande: nomCommande || null, ancien: ancien };
  if (ancien && !etat.espace.corps.childNodes.length) {
    ouvrirPanneau(etat.espace.corps, { titre: def.titre });
    etat.espace.corps.appendChild(el('p', 'panneau-note', 'Les commandes de cet écran sont dans la vue, au centre.'));
  }
  const onglet = ongletDeLEcran(id, nomCommande);
  if (onglet && etat.ruban.onglet() !== onglet) etat.ruban.choisirOnglet(onglet);
  if (onglet) ecrire(CLES_MEMOIRE.onglet + modeRuban(), onglet);
  const cmd = idCommande(id, nomCommande);
  const c = cmd ? commandeParId(cmd) : null;
  if (c && !c.case && ACTIONS.indexOf(c.commande) < 0) etat.ruban.activer(cmd);
  etat.barreEtat.outil(c ? c.aide : '');
  if (location.hash !== '#' + id && id !== 'lieux') history.replaceState(null, '', '#' + id);
  if (etat.arbre) etat.arbre.choisir(null);
  return true;
}

function appelerEcran(methode) {
  const e = etat.ecran;
  if (!e || !e.instance || typeof e.instance[methode] !== 'function') return null;
  try {
    return e.instance[methode]();
  } catch (err) {
    afficherErreur(err);
    return null;
  }
}

function peut(methode) {
  const e = etat.ecran;
  if (!e || !e.instance || typeof e.instance[methode] !== 'function') return false;
  try {
    return !!e.instance[methode]();
  } catch (err) {
    return false;
  }
}

// Boutons de la barre d'outils selon l'écran ouvert (appelée plusieurs fois par seconde)
function majBarre() {
  if (!etat.espace) return;
  const e = etat.ecran;
  const i = e && e.instance;
  const modifie = ecranModifie();
  etat.espace.enregistrer.disabled = !(i && i.enregistrer && modifie);
  etat.espace.enregistrer.classList.toggle('a-enregistrer', !!(i && i.enregistrer && modifie));
  etat.espace.defaire.disabled = !(i && i.defaire && peut('peutDefaire'));
  etat.espace.refaire.disabled = !(i && i.refaire && peut('peutRefaire'));
}

function interfaceCoque(idEcran) {
  const id = (nom) => idCommande(idEcran, nom);
  return {
    mode: modeCourant(),
    confirmer: (texte, o) => demanderConfirmation(texte, o),
    saisir: (texte, o) => demanderSaisie(texte, o),
    message: (texte, genre, details, sortie) => (etat.barreEtat ? etat.barreEtat.message(texte, genre, details, sortie) : null),
    effacerMessage: () => { if (etat.barreEtat) etat.barreEtat.effacer(); },
    pleinEcran: (oui) => {
      if (!etat.espace) return;
      etat.espace.racine.classList.toggle('plein-ecran', !!oui);
      redimensionnerVues();
    },
    ouvrirCommande: (idCmd, valeur) => ouvrirCommande(idCmd, valeur),
    choisirVue: (nom) => choisirVue(nom),
    vue: () => (etat.vue ? etat.vue.courante() : null),
    surVue: (fn) => {
      etat.ecouteursVue.add(fn);
      return () => etat.ecouteursVue.delete(fn);
    },
    barreEtat: etat.barreEtat,
    // le ruban, par le nom de commande de l'écran (« salle », « lancer »…)
    activer: (nom) => {
      if (!etat.ruban) return;
      etat.ruban.activer(nom ? id(nom) : null);
      const c = nom ? commandeParId(id(nom)) : null;
      if (etat.barreEtat) etat.barreEtat.outil(c ? c.aide : '');
    },
    griser: (nom, raison) => { if (etat.ruban && id(nom)) etat.ruban.griser(id(nom), raison || null); },
    libelle: (nom, texte) => { if (etat.ruban && id(nom)) etat.ruban.libelle(id(nom), texte); },
    menu: (nom, choix) => { if (etat.ruban && id(nom)) etat.ruban.menu(id(nom), choix); },
    coche: (nom, valeur) => {
      if (Object.prototype.hasOwnProperty.call(etat.cases, nom) && etat.cases[nom] !== !!valeur) {
        etat.cases[nom] = !!valeur;
        ecrire(CLE_CASES, JSON.stringify(etat.cases));
      }
      if (etat.ruban && id(nom)) etat.ruban.coche(id(nom), valeur);
    },
    cases: () => Object.assign({}, etat.cases),
    aide: (texte) => { if (etat.barreEtat) etat.barreEtat.outil(texte); },
    lieuModifie: (quoi) => {
      if (etat.arbre) etat.arbre.rafraichir();
      chargerDonnees3D(quoi || 'tout');
      if (quoi === 'lieu') majChoixLieu();
    },
    choisirDansArbre: (genre, ident) => { if (etat.arbre) etat.arbre.choisir(genre, ident); },
    carte3d: () => (carte3dPrete() ? etat.carte3d : null),
    telecommande: () => etat.telecommande,
    noterTelecommande: (oui) => { etat.telecommande = !!oui; },
    arret: () => (etat.arret ? etat.arret.arreter('écran') : null),
    coordonnees: (x, y) => { if (etat.barreEtat) etat.barreEtat.coordonnees(x, y); },
    // un élément posé par-dessus la vue centrale, quelle que soit la vue (ex. la caméra en incrustation)
    incruster: (element) => {
      if (!etat.vue) return () => {};
      etat.vue.plan.parentNode.appendChild(element);
      return () => element.remove();
    },
  };
}

// ---------------------------------------------------------------- arbre

async function choixDansArbre(choix, double) {
  const g = choix.genre;
  if (g === 'etage') {
    if (choix.id !== contexte.etage) {
      etat.espace.selectEtage.value = choix.id;
      await changerEtage(choix.id);
    }
    return;
  }
  if (g === 'lieu') {
    await ouvrirEcran('lieux', null);
    return;
  }
  if (g === 'equipe') {
    await ouvrirEcran(choix.id, 'ouvrir');
    return;
  }
  const ecrans = { carte: 'carte', monde: 'monde', salle: 'salles', noeud: 'itineraires', couloir: 'itineraires',
    zone: 'zones', scan: 'scan' };
  const idEcran = ecrans[g];
  if (!idEcran) return;
  // un écran qui sait montrer cet élément le garde (ex. la simulation et ses salles)
  const ouvert = etat.ecran;
  const garde = ouvert && ouvert.instance && ouvert.instance.selectionner && ouvert.id !== idEcran
    && (g === 'salle' && ouvert.id === 'simulation');
  if (!garde && !(await ouvrirEcran(idEcran, null))) return;
  const e = etat.ecran;
  if (e && e.instance && e.instance.selectionner) {
    try {
      e.instance.selectionner(g, choix.id, double);
    } catch (err) {
      afficherErreur(err);
    }
  }
  if (double) recentrerSur(g, choix.id);
}

// Double-clic dans l'arbre : la vue 3D se centre sur l'élément (le plan 2D : l'écran le fait)
async function recentrerSur(genre, id) {
  if (!etat.carte3d || etat.vue.courante() !== '3d' || !contexte.lieu) return;
  let x = null;
  let y = null;
  try {
    if (genre === 'salle') {
      const s = (await api.lire(urlLieu(contexte.lieu) + '/salles')).find((v) => v.id === id);
      if (s) { x = s.pose.x; y = s.pose.y; }
    } else if (genre === 'noeud') {
      const n = (await api.lire(urlLieu(contexte.lieu) + '/itineraires')).noeuds[id];
      if (n) { x = n.x; y = n.y; }
    }
  } catch (e) {
    return;
  }
  if (x !== null && etat.carte3d) {
    etat.carte3d.centrerSur(x, y);
    etat.carte3d.choisir(genre, id);
  }
}

// ---------------------------------------------------------------- vue centrale et carte 3D

function carte3dPrete() {
  if (!etat.carte3d) return false;
  try {
    return !!etat.carte3d.etat().webgl;
  } catch (e) {
    return false;
  }
}

function choisirVue(nom) {
  if (!etat.vue) return null;
  if (etat.vue.permises().indexOf(nom) < 0) return etat.vue.courante();
  return etat.vue.choisir(nom);
}

function changementDeVue(nom, parUtilisateur) {
  if (parUtilisateur && etat.ecran) ecrire(CLES_MEMOIRE.vue + modeRuban() + '.' + etat.ecran.id, nom);
  if (parUtilisateur) ecrire(CLES_MEMOIRE.vue + modeRuban(), nom);
  if (nom === '3d' && etat.carte3d) {
    requestAnimationFrame(() => { if (etat.carte3d) etat.carte3d.redimensionner(); });
  }
  if (nom === 'camera') demarrerCamera();
  else if (etat.cameraVue) etat.cameraVue.arreter();
  if (nom !== '3d' && etat.barreEtat) etat.barreEtat.coordonnees(null, null);
  const e = etat.ecran;
  if (e && e.instance && e.instance.vue) {
    try {
      e.instance.vue(nom);
    } catch (err) {
      afficherErreur(err);
    }
  }
  etat.ecouteursVue.forEach((f) => {
    try {
      f(nom);
    } catch (err) {
      console.error(err);
    }
  });
}

async function demarrerCamera() {
  if (!etat.vue) return;
  if (!etat.cameraVue) {
    try {
      const m = await import('../camera/flux.js');
      if (!etat.vue) return;
      etat.cameraVue = m.creerVueCamera(etat.vue.camera, { source: 'poitrine', cadres: true, petit: false });
    } catch (e) {
      etat.vue.camera.textContent = 'La vue de la caméra n\'a pas pu être chargée.';
      return;
    }
  }
  try {
    etat.cameraVue.demarrer();
  } catch (e) {
    console.error(e);
  }
}

function redimensionnerVues() {
  requestAnimationFrame(() => {
    if (etat.carte3d) etat.carte3d.redimensionner();
    window.dispatchEvent(new Event('resize'));
  });
}

// Vues prédéfinies et « Recadrer » : la carte 3D, ou en Plan 2D l'écran ouvert (tout le plan de l'étage)
function cadrer(nom) {
  if (etat.vue && etat.vue.courante() === 'plan') {
    if (nom === 'recadrer') appelerEcran('recadrer');
    return;
  }
  if (!etat.carte3d) return;
  if (nom === 'recadrer') etat.carte3d.recadrer();
  else etat.carte3d.vue(nom);
}

function calquesMemorises() {
  return lireJson(CLES_MEMOIRE.calques, {});
}

function changerCalque(nom, visible) {
  const c = calquesMemorises();
  c[nom] = !!visible;
  ecrire(CLES_MEMOIRE.calques, JSON.stringify(c));
  if (etat.carte3d) etat.carte3d.calque(nom, !!visible);
}

function detruireCarte3D() {
  etat.carte3dDesabonner.forEach((f) => f());
  etat.carte3dDesabonner = [];
  if (etat.carte3d) {
    try {
      etat.carte3d.detruire();
    } catch (e) {
      console.error(e);
    }
  }
  etat.carte3d = null;
  etat.carte3dCle = null;
  if (window.carte3d) window.carte3d = null;
}

// La carte 3D partagée de l'étage (12.3), créée une fois par lieu, étage et mode
async function preparerCarte3D() {
  if (!etat.vue || !contexte.lieu || !contexte.etage) {
    detruireCarte3D();
    return null;
  }
  const cle = contexte.lieu + '/' + contexte.etage + '/' + modeRuban();
  if (etat.carte3d && etat.carte3dCle === cle) return etat.carte3d;
  detruireCarte3D();
  let module;
  try {
    module = await import('../carte3d/carte3d.js');
  } catch (e) {
    console.error(e);
    return null;
  }
  if (!etat.vue) return null;
  etat.vue.trois.textContent = '';
  try {
    etat.carte3d = module.creerCarte3D(etat.vue.trois, {
      etage: contexte.etage, nomGlobal: 'carte3d', hauteurCoupe: 2.2, plafond: lire(CLE_PLAFOND) === '1',
    });
  } catch (e) {
    console.error(e);
    etat.carte3d = null;
    return null;
  }
  etat.carte3dCle = cle;
  const c = etat.carte3d;
  etat.carte3dDesabonner.push(c.surPointeur((p) => {
    if (etat.barreEtat && etat.vue && etat.vue.courante() === '3d') etat.barreEtat.coordonnees(p ? p.x : null, p ? p.y : null);
  }));
  etat.carte3dDesabonner.push(c.surSelection((choix) => {
    if (!choix || !choix.genre) return;
    if (etat.arbre) etat.arbre.choisir(choix.genre, choix.id);
    const e = etat.ecran;
    if (e && e.instance && e.instance.selectionner) {
      try {
        e.instance.selectionner(choix.genre, choix.id);
      } catch (err) {
        afficherErreur(err);
      }
    }
  }));
  // calques : ceux retenus ; le nuage en Réel, le monde en Simulation
  const memoire = calquesMemorises();
  // en Simulation, le monde en volumes et la carte 2D au sol (I7) ; en Réel, le nuage (la carte 2D si l'étage n'en a pas)
  const defauts = { nuage: true, carte2d: modeRuban() === 'simu', monde: modeRuban() === 'simu', points: true, itineraires: true,
    zones: true, robot: true, pietons: true, trajet: false };
  const calques = Object.assign({}, defauts, memoire);
  Object.keys(calques).forEach((nom) => {
    try {
      c.calque(nom, calques[nom]);
    } catch (e) {
      // calque inconnu de ce module
    }
  });
  etat.vue.calques(calques, modeRuban() === 'simu' ? ['carte2d', 'monde', 'points', 'itineraires', 'zones', 'robot', 'pietons']
    : ['nuage', 'carte2d', 'points', 'itineraires', 'zones', 'robot', 'pietons', 'trajet']);
  etat.vue.plafond(lire(CLE_PLAFOND) === '1');
  if (carte3dPrete()) chargerDonnees3D('tout');
  return c;
}

// Données de la carte 3D : 'tout', ou ce qui vient de changer (salles, itineraires, zones, monde, carte)
async function chargerDonnees3D(quoi) {
  const c = etat.carte3d;
  if (!c || !carte3dPrete() || !contexte.lieu || !contexte.etage) return;
  const lieu = contexte.lieu;
  const etage = contexte.etage;
  const base = urlEtage(lieu, etage);
  const tout = quoi === 'tout';
  const encore = () => etat.carte3d === c && contexte.lieu === lieu && contexte.etage === etage;
  const taches = [];
  if (tout || quoi === 'carte') {
    taches.push(api.lire(base + '/carte.yaml').then((info) => {
      if (encore()) c.afficherCarte2D(base + '/carte.png?v=' + Date.now(), info.bornes);
      return info;
    }).catch(() => null));
  }
  if ((tout || quoi === 'monde') && modeRuban() === 'simu') {
    taches.push(api.lire(base + '/monde').then((monde) => {
      if (encore()) c.afficherMonde(monde, { urlMaillage: monde && monde.carte_extrudee ? base + '/monde/maillage' : null });
    }).catch(() => null));
  }
  if (tout && modeRuban() === 'reel') {
    taches.push(c.chargerNuage(base + '/nuage').then((r) => r).catch((e) => {
      if (encore() && etat.barreEtat) {
        etat.barreEtat.message(e && e.message ? e.message : 'Pas encore de nuage 3D pour cet étage.', 'info');
      }
      // sans nuage : la carte 2D au sol reste visible
      try {
        c.calque('carte2d', true);
      } catch (err) {
        // calque inconnu
      }
      return null;
    }));
  }
  if (tout || quoi === 'salles') {
    taches.push(api.lire(urlLieu(lieu) + '/salles').then((salles) => {
      if (!encore()) return;
      const p = salles.filter((s) => (s.etiquettes || []).indexOf('principal') >= 0);
      const principal = p.length === 1 ? p[0].id : (salles.some((s) => s.id === 'accueil') ? 'accueil' : null);
      c.afficherSalles(salles, principal);
    }).catch(() => null));
  }
  if (tout || quoi === 'itineraires' || quoi === 'salles') {
    taches.push(api.lire(urlLieu(lieu) + '/itineraires').then((i) => { if (encore()) c.afficherItineraires(i); })
      .catch(() => null));
  }
  if (tout || quoi === 'zones') {
    taches.push(api.lire(urlLieu(lieu) + '/zones').then((z) => { if (encore()) c.afficherZones(z); }).catch(() => null));
  }
  await Promise.all(taches);
  if (tout && encore()) {
    try {
      c.recadrer();
    } catch (e) {
      // pas encore de taille : la carte se cadrera à son premier affichage
    }
  }
}

// ---------------------------------------------------------------- en direct (/ws/etat)

function majPastille(nom, genre, texte, titre) {
  if (!etat.espace) return;
  const p = etat.espace.pastilles[nom];
  if (!p) return;
  p.setAttribute('data-genre', genre);
  p.querySelector('.etat-pastille-texte').textContent = texte;
  p.title = titre || texte;
}

// pastille du robot (courte : la barre d'outils reste entière à 1366 px ; le message complet en infobulle)
const TEXTES_PONT = {
  demarrage: ['attente', 'Robot démarre'], attente_reperage: ['attente', 'À repérer'],
  pret: ['ok', 'Robot prêt'], en_mouvement: ['ok', 'En marche'], arret: ['attente', 'Robot arrêté'],
  arret_verrouille: ['ko', 'Robot bloqué'], robot_muet: ['ko', 'Robot muet'], refus: ['ko', 'Refus du robot'],
  pilotage: ['ok', 'Piloté'], pas_en_marche: ['ko', 'Pas en marche'],
};

function recevoirDirect(d) {
  if (!etat.espace) return;
  const ros = d.ros || {};
  majPastille('ros', ros.actif ? (ros.nav2 === false ? 'attente' : 'ok') : 'ko', ros.actif ? 'ROS 2' : 'Sans ROS 2',
    ros.actif ? (ros.nav2 ? 'ROS 2 actif, Nav2 prêt' : 'ROS 2 actif') : (ros.erreur || 'Le pont ROS 2 du serveur ne tourne pas'));
  if (etat.mode === 'reel') {
    const p = d.pont;
    if (p && !p.perime) {
      const t = TEXTES_PONT[p.etat] || ['attente', 'Robot : ' + p.etat];
      majPastille('robot', t[0], t[1], p.message || t[1]);
    } else {
      majPastille('robot', 'inconnu', 'Robot', d.mode ? 'Pas encore de nouvelles du robot' : 'Ni robot ni répétition en cours');
    }
  }
  if (etat.barreEtat) etat.barreEtat.processus(d.processus || {});
  // robot et piétons dans la carte 3D
  const c = etat.carte3d;
  if (c && carte3dPrete()) {
    const sim = d.simulation;
    const ici = !!(sim && sim.en_cours && sim.lieu === contexte.lieu && sim.etage === contexte.etage) || d.mode === 'robot';
    // perimee (répétition et vrai robot : pose du repérage trop vieille, ou robot pas repéré) : robot estompé
    const perimee = !!(d.robot && d.robot.perimee);
    const cle = ici && d.robot ? [d.robot.x, d.robot.y, d.robot.theta].map((v) => Math.round(v * 100)).join(',')
      + (perimee ? ',perimee' : '') : '';
    if (cle !== etat.robotVu) {
      etat.robotVu = cle;
      c.afficherRobot(ici && d.robot ? { x: d.robot.x, y: d.robot.y, theta: d.robot.theta, perimee: perimee } : null);
    }
    const pietons = ici ? (d.pietons || []).map((p) => ({ id: p.id, x: p.x, y: p.y })) : [];
    const cleP = pietons.map((p) => p.id + Math.round(p.x * 20) + ',' + Math.round(p.y * 20)).join(';');
    if (cleP !== etat.pietonsVus) {
      etat.pietonsVus = cleP;
      c.afficherPietons(pietons);
    }
  }
}

async function lireBatterie() {
  if (!etat.espace || etat.mode !== 'reel' || document.hidden) return;
  try {
    const e = await api.lire('/api/pilotage/etat');
    const b = e && e.batterie;
    if (b && typeof b.pourcent === 'number') {
      etat.espace.pastilles.batterie.hidden = false;
      majPastille('batterie', b.pourcent < 20 ? 'ko' : (b.pourcent < 40 ? 'attente' : 'ok'), b.pourcent + ' %',
        'Batterie du robot : ' + b.pourcent + ' %');
    }
  } catch (err) {
    if (etat.espace) etat.espace.pastilles.batterie.hidden = true;
  }
}

// ---------------------------------------------------------------- clavier

function dansUnChamp(cible) {
  return !!(cible && (cible.tagName === 'INPUT' || cible.tagName === 'TEXTAREA' || cible.tagName === 'SELECT'
    || cible.isContentEditable));
}

// Commandes du ruban qui sont un outil en cours qu'Échap annule (retour à « Choisir ») : Placer, Dessiner
// (sauf « Choisir » lui-même) et « Robot ailleurs » de Naviguer
function outilAnnulable(id) {
  const c = commandeParId(id);
  if (!c || c.case || id === 'monde.choisir') return false;
  return c.onglet === 'placer' || c.onglet === 'dessiner' || id === 'navigation.position';
}

// Échap a-t-il un usage dans la page à cet instant : fermer un menu, une fenêtre, un volet, un tiroir, annuler
// une saisie, l'outil ou le geste en cours ? Vu avant que ces éléments réagissent (écoute en capture).
function echapServi(ev) {
  if (fenetreOuverte() || document.querySelector('.menu-ruban')) return true;
  if (dansUnChamp(ev.target)) return true;
  if (!etat.espace) return !!(etat.accueil && etat.accueil.formulaireOuvert && etat.accueil.formulaireOuvert());
  const r = etat.espace.racine;
  if (r.querySelector('.menu-calques:not([hidden]), [data-role=journal]:not([hidden]), [data-role=ce-qui-tourne]:not([hidden])')) {
    return true;
  }
  if (r.classList.contains('tiroir-arbre') || r.classList.contains('tiroir-panneau')) return true;
  if (carte3dPrete()) {
    try {
      const e = etat.carte3d.etat();
      if (e.geste || (e.outil && e.outil !== 'naviguer')) return true;
    } catch (err) {
      // carte 3D détruite entre-temps
    }
  }
  const presse = r.querySelector('.ruban-commandes .commande[aria-pressed=true]:not(.commande-case)');
  return !!(presse && outilAnnulable(presse.getAttribute('data-commande')));
}

// Échap : l'ARRÊT dès que le robot bouge (toujours) ou que quelque chose tourne (si la touche ne sert pas déjà
// à fermer ou annuler) ; sinon, la touche ferme et annule seulement (revue de la vague 5 : un Échap pour fermer
// un menu bloquait le robot en répétition). Sur l'accueil aussi : la navigation peut tourner encore.
function echap(ev) {
  const servi = echapServi(ev);
  const m = etatMouvement(etat.connecte ? dernierEtat() : null, flechesTenues());
  const decision = decisionEchap(m, servi);
  if (decision === 'arret') {
    if (etat.arret) etat.arret.arreter('touche Échap');
    else if (etat.accueil && etat.accueil.arreter) etat.accueil.arreter('touche Échap');
  }
  // ce que la coque a ouvert se ferme (les menus du ruban, les fenêtres et les outils réagissent d'eux-mêmes)
  document.querySelectorAll('.menu-reglages').forEach((x) => x.remove());
  if (etat.espace) {
    etat.espace.racine.classList.remove('tiroir-arbre', 'tiroir-panneau');
    if (etat.barreEtat) {
      etat.barreEtat.journal(false);
      etat.barreEtat.ceQuiTourne(false);
    }
    if (etat.vue) etat.vue.fermerCalques();
    if (decision === 'rien' && etat.barreEtat) {
      etat.barreEtat.message('Échap : rien ne bouge ni ne tourne, rien à arrêter (ARRÊT reste en haut à droite).', 'info');
    }
  }
}

function clavier(ev) {
  if (ev.key === 'Escape') {
    echap(ev);
    return;
  }
  if (!etat.espace) return;
  if (fenetreOuverte()) return;
  const ctrl = ev.ctrlKey || ev.metaKey;
  if (ctrl && (ev.key === 'PageUp' || ev.key === 'PageDown')) {
    ev.preventDefault();
    const ids = etat.ruban.onglets();
    const i = ids.indexOf(etat.ruban.onglet());
    ouvrirOnglet(ids[(i + (ev.key === 'PageUp' ? ids.length - 1 : 1)) % ids.length]);
    return;
  }
  const touche = (ev.key || '').toLowerCase();
  if (ctrl && touche === 's') {
    // même pendant une saisie : le champ quitté est validé, puis l'écran enregistre (la page web ne
    // s'enregistre jamais à la place)
    ev.preventDefault();
    const actif = document.activeElement;
    if (dansUnChamp(actif) && actif.blur) actif.blur();
    apresValidations(() => appelerEcran('enregistrer'));
    return;
  }
  if (dansUnChamp(ev.target)) return;
  if (ctrl && touche === 'z' && !ev.shiftKey) {
    ev.preventDefault();
    appelerEcran('defaire');
  } else if (ctrl && (touche === 'y' || (touche === 'z' && ev.shiftKey))) {
    ev.preventDefault();
    appelerEcran('refaire');
  } else if (!ctrl && !ev.altKey && touche === 'f' && etat.vue && ['3d', 'plan'].indexOf(etat.vue.courante()) >= 0) {
    cadrer('recadrer');
  } else if (ctrl && etat.vue && etat.vue.courante() === '3d' && ['1', '5', '7'].indexOf(touche) >= 0) {
    ev.preventDefault();
    cadrer({ 1: 'face', 5: 'dessus', 7: 'iso' }[touche]);
  }
}
