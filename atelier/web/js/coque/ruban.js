// Ruban de commandes (CommandManager de SolidWorks) : onglets et commandes par mode (vague 5,
// section 12.2 du plan). Module de l'agent Coquille. Le registre COMMANDES ci-dessous est le
// contrat livré par l'agent Contrats : identifiants stables (repères [data-commande=<id>] des
// tests), écran qui exécute la commande et nom de la commande passé à cet écran. L'agent Coquille
// complète les libellés, icônes et aides, et ajoute des commandes Avancé ; il ne renomme pas un
// identifiant sans mettre à jour la section 12.2.

import { icone } from './icones.js';

// Onglets du ruban : 4 en Simulation, 5 en Réel (la répétition sans robot utilise ceux du Réel)
export const ONGLETS_RUBAN = {
  simu: [
    { id: 'dessiner', libelle: 'Dessiner' },
    { id: 'placer', libelle: 'Placer' },
    { id: 'simuler', libelle: 'Simuler' },
    { id: 'equipe', libelle: 'Équipe' },
  ],
  reel: [
    { id: 'scanner', libelle: 'Scanner' },
    { id: 'placer', libelle: 'Placer' },
    { id: 'naviguer', libelle: 'Naviguer' },
    { id: 'piloter', libelle: 'Piloter' },
    { id: 'equipe', libelle: 'Équipe' },
  ],
};

// Titres des groupes qui en ont un (les autres sont séparés par un simple trait)
export const TITRES_GROUPES = { spectacle: 'Spectacle' };

// Chaque commande : id (stable), modes ('simu' et/ou 'reel'), onglet, groupe (trait entre groupes),
// libelle (court, sous l'icône), icone (nom d'une icône SVG de js/coque/icones.js), aide (une phrase, en
// infobulle et dans la barre d'état), ecran (module de js/ecrans/ qui l'exécute) et commande (passée à
// l'écran : options.commande à l'ouverture, ou instance.commande(nom, valeur) s'il est déjà ouvert).
// avance : rangée dans le menu « Avancé » (⚙) de l'onglet. case : commande à cocher (vrai/faux), pas
// un bouton. Ajouts de la coque : vue (vue centrale préférée : '3d' ou 'plan' ; sans : celle de l'écran),
// menu (choix proposés sous le bouton ; la valeur choisie part avec la commande ; « dynamique » : les choix
// viennent de l'écran, par ruban.menu(id, choix)).
function c(id, modes, onglet, groupe, libelle, icone, aide, ecran, commande, plus) {
  const d = { id: id, modes: modes, onglet: onglet, groupe: groupe, libelle: libelle, icone: icone,
    aide: aide, ecran: ecran, commande: commande, avance: false, case: false };
  return Object.assign(d, plus || {});
}
const S = ['simu'];
const R = ['reel'];
const SR = ['simu', 'reel'];

const MEUBLES = [
  { valeur: 'table', libelle: 'Table' }, { valeur: 'chaise', libelle: 'Chaise' }, { valeur: 'banc', libelle: 'Banc' },
  { valeur: 'poubelle', libelle: 'Poubelle' }, { valeur: 'boite', libelle: 'Meuble (boîte)' },
  { valeur: 'cylindre', libelle: 'Poteau' },
];
// Postures et gestes : les valeurs du contrat (atelier.lieu.pilotage : POSTURES, GESTES_BRAS)
const POSTURES = [
  { valeur: 500, libelle: 'Démarrer' }, { valeur: 706, libelle: 'Accroupi ↔ debout' },
  { valeur: 702, libelle: 'Se lever' }, { valeur: 3, libelle: 'S\'asseoir' },
];
const GESTES = [
  { valeur: 26, libelle: 'Grand salut' }, { valeur: 25, libelle: 'Saluer' }, { valeur: 17, libelle: 'Applaudir' },
  { valeur: 20, libelle: 'Cœur' }, { valeur: 18, libelle: 'Tape-m\'en cinq' }, { valeur: 19, libelle: 'Câlin' },
  { valeur: 27, libelle: 'Serrer la main' }, { valeur: 99, libelle: 'Relâcher les bras' },
];

export const COMMANDES = [
  // Simulation › Dessiner : le monde de Gazebo (la carte se refait seule après « Enregistrer »)
  c('monde.choisir', S, 'dessiner', 'outils', 'Choisir', 'fleche', 'Cliquez sur un mur, un meuble ou un piéton pour le modifier ; glissez-le pour le déplacer.', 'monde', 'choisir', { vue: 'plan' }),
  c('monde.mur', S, 'dessiner', 'construire', 'Mur', 'mur', 'Cliquez au début du mur, puis à sa fin (ou glissez).', 'monde', 'mur', { vue: 'plan' }),
  c('monde.passage', S, 'dessiner', 'construire', 'Passage', 'porte', 'Cliquez sur un mur là où il faut une porte.', 'monde', 'passage', { vue: 'plan' }),
  c('monde.objet', S, 'dessiner', 'meubler', 'Objet', 'objet', 'Choisissez un meuble, puis cliquez pour le poser.', 'monde', 'objet', { vue: 'plan', menu: MEUBLES }),
  c('monde.pieton', S, 'dessiner', 'meubler', 'Piéton', 'pieton', 'Cliquez les points de son trajet, puis ✓ pour le terminer.', 'monde', 'pieton', { vue: 'plan' }),
  c('monde.depart', S, 'dessiner', 'robot', 'Départ', 'depart', 'Le robot démarre ici, à l\'accueil : cliquez, puis glissez pour l\'orienter.', 'monde', 'depart', { vue: 'plan' }),
  c('carte.refaire', S, 'dessiner', 'carte', 'Refaire la carte', 'carte', 'Refait la carte du robot depuis le monde (elle se refait déjà seule après « Enregistrer »).', 'carte', 'refaire', { avance: true }),

  // Placer (Simulation et Réel ; en Réel, dans la vue Nuage par défaut)
  c('salles.salle', SR, 'placer', 'points', 'Salle', 'salle', 'Cliquez sur le sol devant la porte, puis tirez vers la salle.', 'salles', 'salle', { vue: '3d' }),
  c('salles.accueil', SR, 'placer', 'points', 'Accueil', 'etoile', 'Placez l\'accueil : le robot y démarre et y revient après chaque visite.', 'salles', 'accueil', { vue: '3d' }),
  c('itineraires.noeud', SR, 'placer', 'itineraires', 'Nœud', 'noeud', 'Cliquez pour poser un point de passage du robot.', 'itineraires', 'noeud', { vue: 'plan' }),
  c('itineraires.relier', SR, 'placer', 'itineraires', 'Relier', 'relier', 'Cliquez sur deux nœuds pour les relier par un couloir de 8 m au plus.', 'itineraires', 'relier', { vue: 'plan' }),
  c('zones.interdite', SR, 'placer', 'zones', 'Zone interdite', 'interdit', 'Cliquez les coins d\'une zone où le robot ne va jamais.', 'zones', 'interdite', { vue: 'plan' }),
  c('zones.lente', SR, 'placer', 'zones', 'Zone lente', 'lent', 'Cliquez les coins d\'une zone où le robot ralentit.', 'zones', 'lente', { vue: 'plan' }),

  // Simulation › Simuler
  c('simulation.lancer', S, 'simuler', 'simulation', 'Lancer', 'lancer', 'Démarre Gazebo et le guide sur ce lieu.', 'simulation', 'lancer'),
  c('simulation.arreter', S, 'simuler', 'simulation', 'Arrêter', 'stop', 'Arrête la simulation.', 'simulation', 'arreter'),
  c('simulation.y-aller', S, 'simuler', 'guide', 'Y aller', 'cible', 'Choisissez une salle : le robot y va.', 'simulation', 'y-aller', { menu: 'dynamique' }),
  c('simulation.accompagner', S, 'simuler', 'guide', 'Accompagner', 'visiteur', 'Le robot vérifie que le visiteur le suit.', 'simulation', 'accompagner', { case: true }),
  c('simulation.retour', S, 'simuler', 'guide', 'Retour', 'retour', 'Après la visite, le robot revient seul à l\'accueil.', 'simulation', 'retour', { case: true }),
  c('simulation.faux-visiteur', S, 'simuler', 'avance', 'Faux visiteur', 'visiteur', 'Un piéton de Gazebo joue le visiteur : il suit, traîne ou part.', 'simulation', 'faux-visiteur', { avance: true }),
  c('simulation.passants', S, 'simuler', 'avance', 'Passants', 'pieton', 'Les piétons en direct, les scènes d\'essai et les derniers bancs.', 'simulation', 'passants', { avance: true }),
  c('simulation.reglages-guide', S, 'simuler', 'avance', 'Réglages du guide', 'reglages', 'Délais et distances du guide (retour, visiteur, passants).', 'simulation', 'reglages-guide', { avance: true }),
  c('scan.simule', S, 'simuler', 'avance', 'Scan simulé', 'scan', 'Scanner le monde de Gazebo avec le robot simulé (essais).', 'scan', 'simule', { avance: true }),

  // Réel › Scanner
  c('scan.scan', R, 'scanner', 'scan', 'Scan', 'scan', 'Commence le scan : promenez le robot lentement partout, à la télécommande.', 'scan', 'scan'),
  c('scan.fin', R, 'scanner', 'scan', 'Fin', 'stop', 'Termine le scan ; la carte se fabrique toute seule.', 'scan', 'fin'),
  c('scan.utiliser', R, 'scanner', 'scan', 'Utiliser cette carte', 'valider', 'Cette carte devient celle de l\'étage.', 'scan', 'utiliser'),

  // Réel › Naviguer (vrai robot, ou répétition sans robot)
  c('navigation.lancer', R, 'naviguer', 'navigation', 'Lancer', 'lancer', 'Démarre la navigation sur le robot (ou la répétition sans robot).', 'simulation', 'lancer'),
  c('navigation.reperer', R, 'naviguer', 'navigation', 'Repérer', 'reperer', 'Posez le robot sur l\'accueil, tourné comme la flèche, puis cliquez.', 'simulation', 'reperer'),
  c('navigation.y-aller', R, 'naviguer', 'guide', 'Y aller', 'cible', 'Choisissez une salle : le robot y va.', 'simulation', 'y-aller', { menu: 'dynamique' }),
  c('navigation.bloquer', R, 'naviguer', 'securite', 'Bloquer', 'cadenas', 'Le robot reste immobile jusqu\'à « Débloquer ».', 'simulation', 'bloquer'),
  c('navigation.debloquer', R, 'naviguer', 'securite', 'Débloquer', 'cadenas-ouvert', 'Le robot peut de nouveau marcher.', 'simulation', 'debloquer'),
  c('navigation.arreter', R, 'naviguer', 'navigation', 'Arrêter', 'stop', 'Arrête la navigation (et la répétition).', 'simulation', 'arreter'),
  c('navigation.position', R, 'naviguer', 'avance', 'Robot ailleurs', 'position', 'Le robot n\'est pas sur l\'accueil : cliquez sur la carte où il est, puis glissez vers son avant.', 'simulation', 'position', { avance: true, vue: 'plan' }),

  // Réel › Piloter (vrai robot, ou répétition avec le faux G1)
  c('pilotage.main', R, 'piloter', 'main', 'Prendre la main', 'main', 'Pilotez le robot vous-même : le guide attend.', 'pilotage', 'main'),
  c('pilotage.postures', R, 'piloter', 'robot', 'Postures', 'posture', 'Démarrer, s\'accroupir, se lever, s\'asseoir.', 'pilotage', 'postures', { menu: POSTURES }),
  c('pilotage.gestes', R, 'piloter', 'robot', 'Gestes', 'geste', 'Saluer, applaudir, faire un cœur…', 'pilotage', 'gestes', { menu: GESTES }),
  c('pilotage.voix', R, 'piloter', 'robot', 'Voix', 'voix', 'Le robot dit une phrase.', 'pilotage', 'voix'),
  c('pilotage.led', R, 'piloter', 'robot', 'Lumière', 'led', 'Couleur des lumières du robot.', 'pilotage', 'led'),
  c('pilotage.joysticks', R, 'piloter', 'robot', 'Joysticks', 'joystick', 'Deux manettes sur la vue : avancer à gauche, tourner à droite.', 'pilotage', 'joysticks', { case: true }),
  c('pilotage.danses', R, 'piloter', 'spectacle', 'Danses', 'danse', 'Les danses du robot (zone libre de 2 à 3 m).', 'pilotage', 'danses'),
  c('pilotage.choregraphies', R, 'piloter', 'spectacle', 'Chorégraphies', 'choregraphie', 'Vos chorégraphies, avec leur aperçu 3D.', 'pilotage', 'choregraphies'),
  c('pilotage.portique', R, 'piloter', 'avance', 'Portique', 'portique', 'Amortir, couple nul : seulement robot tenu au portique.', 'pilotage', 'portique', { avance: true }),
  c('pilotage.volume', R, 'piloter', 'avance', 'Volume', 'volume', 'Volume du haut-parleur du robot.', 'pilotage', 'volume', { avance: true }),

  // Équipe (les deux modes)
  c('personnalites.ouvrir', SR, 'equipe', 'equipe', 'Personnalités', 'personnalite', 'Le caractère du robot : salutation, voix, couleurs.', 'personnalites', 'ouvrir'),
  c('dialogues.ouvrir', SR, 'equipe', 'equipe', 'Dialogues', 'dialogue', 'Ce que le robot répond aux visiteurs.', 'dialogues', 'ouvrir'),
  c('camera.ouvrir', SR, 'equipe', 'equipe', 'Caméra', 'camera', 'La caméra de poitrine et les visiteurs vus.', 'camera', 'ouvrir'),
  c('camera.reglages', SR, 'equipe', 'avance', 'Réglages de la caméra', 'reglages', 'Image, exposition et place de la caméra sur le robot.', 'camera', 'reglages', { avance: true }),
];

// Commandes d'un mode ('simu', 'reel' ; la répétition prend 'reel'), et d'un onglet s'il est donné
export function commandesDe(mode, onglet) {
  const m = mode === 'repetition' ? 'reel' : mode;
  return COMMANDES.filter((x) => x.modes.indexOf(m) >= 0 && (!onglet || x.onglet === onglet));
}

// La commande d'un identifiant, ou null
export function commande(id) {
  return COMMANDES.find((x) => x.id === id) || null;
}

function el(balise, classe, texte) {
  const e = document.createElement(balise);
  if (classe) e.className = classe;
  if (texte !== undefined && texte !== null) e.textContent = texte;
  return e;
}

// Construit le ruban dans element. options : {mode, surCommande(commande, valeur), surOnglet(id),
// replie, surRepli(replie)}. Renvoie {choisirOnglet(id), onglet(), activer(id), griser(id, raison),
// coche(id, valeur), libelle(id, texte), menu(id, choix), replier(oui), detruire()}.
export function construireRuban(element, options) {
  options = options || {};
  const mode = options.mode === 'repetition' ? 'reel' : (options.mode || 'simu');
  const onglets = ONGLETS_RUBAN[mode];
  element.textContent = '';
  element.classList.add('ruban');
  element.setAttribute('data-role', 'ruban');
  const barreOnglets = el('div', 'ruban-onglets');
  barreOnglets.setAttribute('role', 'tablist');
  barreOnglets.setAttribute('aria-label', 'Onglets du ruban');
  const zone = el('div', 'ruban-commandes');
  zone.setAttribute('role', 'tabpanel');
  element.appendChild(barreOnglets);
  element.appendChild(zone);
  const boutonsOnglets = {};
  const boutons = {};             // id → bouton (y compris ceux du menu Avancé)
  const raisons = {};             // id → raison du grisé
  const menusDynamiques = {};     // id → [{valeur, libelle}]
  let ongletCourant = null;
  let menuOuvert = null;          // {menu, bouton}

  onglets.forEach((o) => {
    const b = el('button', 'ruban-onglet', o.libelle);
    b.type = 'button';
    b.setAttribute('role', 'tab');
    b.setAttribute('data-onglet', o.id);
    b.setAttribute('aria-selected', 'false');
    b.addEventListener('click', () => {
      if (element.classList.contains('ruban-replie')) replier(false);
      choisirOnglet(o.id);
      if (options.surOnglet) options.surOnglet(o.id);
    });
    boutonsOnglets[o.id] = b;
    barreOnglets.appendChild(b);
  });
  barreOnglets.appendChild(el('span', 'ruban-espace'));
  const boutonRepli = el('button', 'bouton-icone petit ruban-replier');
  boutonRepli.type = 'button';
  boutonRepli.setAttribute('data-role', 'ruban-replier');
  barreOnglets.appendChild(boutonRepli);
  boutonRepli.addEventListener('click', () => replier(!element.classList.contains('ruban-replie')));

  function fermerMenu() {
    if (!menuOuvert) return;
    menuOuvert.menu.remove();
    menuOuvert.bouton.setAttribute('aria-expanded', 'false');
    menuOuvert = null;
  }

  // Menu déroulant sous un bouton : choix [{valeur, libelle, desactive}] ou commandes (Avancé)
  function ouvrirMenu(bouton, choix, surChoix, vide) {
    const etaitOuvert = menuOuvert && menuOuvert.bouton === bouton;
    fermerMenu();
    if (etaitOuvert) return;
    const menu = el('div', 'menu-ruban');
    menu.setAttribute('role', 'menu');
    if (!choix.length) menu.appendChild(el('div', 'menu-ruban-vide', vide || 'Rien à choisir.'));
    choix.forEach((x) => {
      const item = x.element || el('button', 'menu-ruban-choix', x.libelle);
      if (!x.element) {
        item.type = 'button';
        item.setAttribute('role', 'menuitem');
        item.setAttribute('data-valeur', String(x.valeur));
        item.disabled = !!x.desactive;
        item.addEventListener('click', () => {
          fermerMenu();
          surChoix(x.valeur);
        });
      }
      menu.appendChild(item);
    });
    // le menu est posé dans la coque (au-dessus de tout), sous le bouton
    const r = bouton.getBoundingClientRect();
    const hote = element.closest('[data-role=espace]') || document.body;
    hote.appendChild(menu);
    const largeur = Math.max(menu.offsetWidth, 180);
    menu.style.left = Math.max(8, Math.min(window.innerWidth - largeur - 8, r.left)) + 'px';
    menu.style.top = (r.bottom + 4) + 'px';
    menu.style.maxHeight = Math.max(160, window.innerHeight - r.bottom - 24) + 'px';
    bouton.setAttribute('aria-expanded', 'true');
    menuOuvert = { menu: menu, bouton: bouton };
    const premier = menu.querySelector('button:not(:disabled)');
    if (premier) premier.focus();
  }

  function fermerSiDehors(ev) {
    if (!menuOuvert) return;
    if (menuOuvert.menu.contains(ev.target) || menuOuvert.bouton.contains(ev.target)) return;
    fermerMenu();
  }
  function echapMenu(ev) {
    if (ev.key === 'Escape' && menuOuvert) fermerMenu();
  }
  document.addEventListener('mousedown', fermerSiDehors, true);
  document.addEventListener('keydown', echapMenu, true);
  window.addEventListener('resize', fermerMenu);

  function boutonCommande(cmd, dansMenu) {
    const b = el('button', dansMenu ? 'menu-ruban-choix commande-avancee' : 'commande');
    b.type = 'button';
    b.setAttribute('data-commande', cmd.id);
    b.setAttribute('aria-pressed', 'false');
    b.title = cmd.aide;
    if (dansMenu) b.setAttribute('role', 'menuitem');
    b.appendChild(icone(cmd.icone, dansMenu ? 18 : 24));
    b.appendChild(el('span', 'commande-libelle', cmd.libelle));
    if (cmd.menu && !dansMenu) {
      b.classList.add('commande-menu');
      b.setAttribute('aria-haspopup', 'menu');
      b.setAttribute('aria-expanded', 'false');
      b.appendChild(el('span', 'commande-fleche', '▾'));
    }
    if (cmd.case) b.classList.add('commande-case');
    b.addEventListener('click', () => {
      if (b.disabled) return;
      if (dansMenu) fermerMenu();
      if (cmd.menu && !dansMenu) {
        // le menu s'ouvre, et l'écran reçoit aussi la commande sans valeur (ex. la section des postures)
        const ouvert = menuOuvert && menuOuvert.bouton === b;
        const choix = cmd.menu === 'dynamique' ? (menusDynamiques[cmd.id] || []) : cmd.menu;
        ouvrirMenu(b, choix, (valeur) => options.surCommande(cmd, valeur),
          cmd.menu === 'dynamique' ? 'Aucune salle sur cet étage.' : '');
        if (!ouvert) options.surCommande(cmd);
        return;
      }
      if (cmd.case) {
        const valeur = b.getAttribute('aria-pressed') !== 'true';
        b.setAttribute('aria-pressed', valeur ? 'true' : 'false');
        options.surCommande(cmd, valeur);
        return;
      }
      options.surCommande(cmd);
    });
    boutons[cmd.id] = b;
    return b;
  }

  function choisirOnglet(id) {
    if (!boutonsOnglets[id]) id = onglets[0].id;
    fermerMenu();
    ongletCourant = id;
    Object.keys(boutonsOnglets).forEach((k) => {
      boutonsOnglets[k].setAttribute('aria-selected', k === id ? 'true' : 'false');
      boutonsOnglets[k].classList.toggle('actif', k === id);
    });
    zone.textContent = '';
    zone.setAttribute('data-onglet-courant', id);
    const liste = commandesDe(mode, id);
    let groupe = null;
    let zoneGroupe = null;
    liste.filter((x) => !x.avance).forEach((cmd) => {
      if (cmd.groupe !== groupe) {
        if (zoneGroupe) zone.appendChild(el('span', 'ruban-separateur'));
        groupe = cmd.groupe;
        zoneGroupe = el('div', 'ruban-groupe');
        zoneGroupe.setAttribute('data-groupe', groupe);
        if (TITRES_GROUPES[groupe]) {
          zoneGroupe.setAttribute('data-titre', TITRES_GROUPES[groupe]);
          zoneGroupe.appendChild(el('span', 'ruban-groupe-titre', TITRES_GROUPES[groupe]));
        }
        zone.appendChild(zoneGroupe);
      }
      zoneGroupe.appendChild(boutonCommande(cmd, false));
    });
    const avancees = liste.filter((x) => x.avance);
    if (avancees.length) {
      zone.appendChild(el('span', 'ruban-espace'));
      const b = el('button', 'commande commande-avance');
      b.type = 'button';
      b.setAttribute('data-role', 'avance');
      b.setAttribute('aria-haspopup', 'menu');
      b.setAttribute('aria-expanded', 'false');
      b.title = 'Commandes avancées de cet onglet';
      b.appendChild(icone('reglages', 24));
      b.appendChild(el('span', 'commande-libelle', 'Avancé'));
      b.appendChild(el('span', 'commande-fleche', '▾'));
      const elements = avancees.map((cmd) => ({ element: boutonCommande(cmd, true) }));
      b.addEventListener('click', () => {
        elements.forEach((x) => {
          const id2 = x.element.getAttribute('data-commande');
          x.element.disabled = !!raisons[id2];
          x.element.title = raisons[id2] || commande(id2).aide;
        });
        ouvrirMenu(b, elements, () => {});
      });
      zone.appendChild(b);
    }
    // les états (grisé, enfoncé, libellé) survivent au changement d'onglet
    Object.keys(raisons).forEach((k) => appliquerGrise(k));
    Object.keys(etatsAppuyes).forEach((k) => {
      if (boutons[k] && boutons[k].isConnected) boutons[k].setAttribute('aria-pressed', etatsAppuyes[k] ? 'true' : 'false');
    });
    Object.keys(libelles).forEach((k) => {
      if (boutons[k] && boutons[k].isConnected) boutons[k].querySelector('.commande-libelle').textContent = libelles[k];
    });
  }

  const etatsAppuyes = {};
  const libelles = {};

  function appliquerGrise(id) {
    const b = boutons[id];
    if (!b) return;
    const cmd = commande(id);
    b.disabled = !!raisons[id];
    b.title = raisons[id] || (cmd ? cmd.aide : '');
  }

  function replier(oui) {
    fermerMenu();
    element.classList.toggle('ruban-replie', !!oui);
    boutonRepli.title = oui ? 'Déplier le ruban' : 'Replier le ruban';
    boutonRepli.setAttribute('aria-label', boutonRepli.title);
    boutonRepli.textContent = '';
    boutonRepli.appendChild(icone(oui ? 'deplier' : 'replier', 18));
    if (options.surRepli) options.surRepli(!!oui);
  }

  replier(!!options.replie);
  choisirOnglet(options.onglet || onglets[0].id);

  return {
    choisirOnglet: choisirOnglet,
    onglet: () => ongletCourant,
    onglets: () => onglets.map((o) => o.id),
    // met en avant la commande active (outil en cours) ; null : aucune. Les cases ne changent pas.
    activer: (id) => {
      COMMANDES.forEach((cmd) => {
        if (cmd.case) return;
        etatsAppuyes[cmd.id] = cmd.id === id;
        const b = boutons[cmd.id];
        if (b && b.isConnected) b.setAttribute('aria-pressed', cmd.id === id ? 'true' : 'false');
      });
    },
    griser: (id, raison) => {
      if (raison) raisons[id] = raison;
      else delete raisons[id];
      appliquerGrise(id);
    },
    coche: (id, valeur) => {
      etatsAppuyes[id] = !!valeur;
      const b = boutons[id];
      if (b) b.setAttribute('aria-pressed', valeur ? 'true' : 'false');
    },
    libelle: (id, texte) => {
      const cmd = commande(id);
      if (texte && cmd && texte !== cmd.libelle) libelles[id] = texte;
      else delete libelles[id];
      const b = boutons[id];
      if (b) b.querySelector('.commande-libelle').textContent = texte || (cmd ? cmd.libelle : '');
    },
    menu: (id, choix) => { menusDynamiques[id] = choix || []; },
    fermerMenu: fermerMenu,
    replier: replier,
    detruire: () => {
      fermerMenu();
      document.removeEventListener('mousedown', fermerSiDehors, true);
      document.removeEventListener('keydown', echapMenu, true);
      window.removeEventListener('resize', fermerMenu);
      element.textContent = '';
    },
  };
}
