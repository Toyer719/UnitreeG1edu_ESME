// Ruban de commandes (CommandManager de SolidWorks) : onglets et commandes par mode (vague 5,
// section 12.2 du plan). Module de l'agent Coquille. Le registre COMMANDES ci-dessous est le
// contrat livré par l'agent Contrats : identifiants stables (repères [data-commande=<id>] des
// tests), écran qui exécute la commande et nom de la commande passé à cet écran. L'agent Coquille
// peut compléter les libellés, icônes et aides, ajouter des commandes Avancé, mais ne renomme pas un
// identifiant sans mettre à jour la section 12.2.

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

// Chaque commande : id (stable), modes ('simu' et/ou 'reel'), onglet, groupe (trait entre groupes),
// libelle (court, sous l'icône), icone (nom d'une icône SVG de la coque), aide (une phrase, en
// infobulle), ecran (module de js/ecrans/ qui l'exécute) et commande (passée à l'écran :
// options.commande à l'ouverture, ou instance.commande(nom) s'il est déjà ouvert). avance : rangée
// dans le menu « Avancé » (⚙) de l'onglet. case : commande à cocher (vrai/faux), pas un bouton.
function c(id, modes, onglet, groupe, libelle, icone, aide, ecran, commande, plus) {
  const d = { id: id, modes: modes, onglet: onglet, groupe: groupe, libelle: libelle, icone: icone,
    aide: aide, ecran: ecran, commande: commande, avance: false, case: false };
  return Object.assign(d, plus || {});
}
const S = ['simu'];
const R = ['reel'];
const SR = ['simu', 'reel'];

export const COMMANDES = [
  // Simulation › Dessiner : le monde de Gazebo (la carte se refait seule après « Enregistrer »)
  c('monde.choisir', S, 'dessiner', 'outils', 'Choisir', 'fleche', 'Cliquez sur un mur, un objet ou un piéton pour le modifier.', 'monde', 'choisir'),
  c('monde.mur', S, 'dessiner', 'outils', 'Mur', 'mur', 'Cliquez au début du mur, puis à sa fin.', 'monde', 'mur'),
  c('monde.passage', S, 'dessiner', 'outils', 'Passage', 'porte', 'Cliquez sur un mur là où il faut une porte.', 'monde', 'passage'),
  c('monde.objet', S, 'dessiner', 'outils', 'Objet', 'objet', 'Choisissez un meuble, puis cliquez pour le poser.', 'monde', 'objet'),
  c('monde.pieton', S, 'dessiner', 'outils', 'Piéton', 'pieton', 'Cliquez les points de son trajet, puis « Terminer le trajet ».', 'monde', 'pieton'),
  c('monde.depart', S, 'dessiner', 'outils', 'Départ', 'depart', 'Le robot apparaît ici dans la simulation : c\'est l\'accueil.', 'monde', 'depart'),
  c('carte.refaire', S, 'dessiner', 'carte', 'Refaire la carte', 'carte', 'Refait la carte de navigation depuis le monde (elle se refait déjà seule après « Enregistrer »).', 'carte', 'refaire', { avance: true }),

  // Placer (Simulation et Réel ; en Réel, dans la vue Nuage par défaut)
  c('salles.salle', SR, 'placer', 'points', 'Salle', 'salle', 'Cliquez sur le sol devant la porte, puis tirez vers la salle.', 'salles', 'salle'),
  c('salles.accueil', SR, 'placer', 'points', 'Accueil', 'etoile', 'Placez l\'accueil : le robot y démarre et y revient après chaque visite.', 'salles', 'accueil'),
  c('itineraires.noeud', SR, 'placer', 'itineraires', 'Nœud', 'noeud', 'Cliquez pour poser un point de passage du robot.', 'itineraires', 'noeud'),
  c('itineraires.relier', SR, 'placer', 'itineraires', 'Relier', 'relier', 'Cliquez sur deux nœuds pour les relier par un couloir de 8 m au plus.', 'itineraires', 'relier'),
  c('zones.interdite', SR, 'placer', 'zones', 'Zone interdite', 'interdit', 'Cliquez les coins d\'une zone où le robot ne va jamais.', 'zones', 'interdite'),
  c('zones.lente', SR, 'placer', 'zones', 'Zone lente', 'lent', 'Cliquez les coins d\'une zone où le robot ralentit.', 'zones', 'lente'),

  // Simulation › Simuler
  c('simulation.lancer', S, 'simuler', 'simulation', 'Lancer', 'lancer', 'Démarre Gazebo et la navigation sur ce lieu.', 'simulation', 'lancer'),
  c('simulation.arreter', S, 'simuler', 'simulation', 'Arrêter', 'stop', 'Arrête la simulation.', 'simulation', 'arreter'),
  c('simulation.y-aller', S, 'simuler', 'guide', 'Y aller', 'cible', 'Choisissez une salle : le robot y va.', 'simulation', 'y-aller'),
  c('simulation.accompagner', S, 'simuler', 'guide', 'Accompagner', 'visiteur', 'Le robot vérifie que le visiteur le suit.', 'simulation', 'accompagner', { case: true }),
  c('simulation.retour', S, 'simuler', 'guide', 'Retour', 'retour', 'Après la visite, le robot revient seul à l\'accueil.', 'simulation', 'retour', { case: true }),
  c('simulation.faux-visiteur', S, 'simuler', 'avance', 'Faux visiteur', 'visiteur', 'Un piéton de Gazebo joue le visiteur : il suit, traîne ou part.', 'simulation', 'faux-visiteur', { avance: true }),
  c('simulation.passants', S, 'simuler', 'avance', 'Passants', 'pieton', 'Scènes de passants et résultats des derniers bancs d\'essai.', 'simulation', 'passants', { avance: true }),
  c('simulation.reglages-guide', S, 'simuler', 'avance', 'Réglages du guide', 'reglages', 'Délais et distances du guide (retour, visiteur, passants).', 'simulation', 'reglages-guide', { avance: true }),
  c('scan.simule', S, 'simuler', 'avance', 'Scan simulé', 'scan', 'Scanner le monde de Gazebo avec le robot simulé (essais).', 'scan', 'simule', { avance: true }),

  // Réel › Scanner
  c('scan.scan', R, 'scanner', 'scan', 'Scan', 'scan', 'Commence le scan : promenez le robot lentement partout, à la télécommande.', 'scan', 'scan'),
  c('scan.fin', R, 'scanner', 'scan', 'Fin', 'stop', 'Termine le scan ; la carte se fabrique toute seule.', 'scan', 'fin'),
  c('scan.utiliser', R, 'scanner', 'scan', 'Utiliser cette carte', 'valider', 'Cette carte devient celle de l\'étage.', 'scan', 'utiliser'),

  // Réel › Naviguer (vrai robot, ou répétition sans robot)
  c('navigation.lancer', R, 'naviguer', 'navigation', 'Lancer', 'lancer', 'Démarre la navigation sur le robot (ou la répétition sans robot).', 'simulation', 'lancer'),
  c('navigation.reperer', R, 'naviguer', 'navigation', 'Repérer', 'reperer', 'Posez le robot sur l\'accueil, tourné comme la flèche, puis cliquez.', 'simulation', 'reperer'),
  c('navigation.y-aller', R, 'naviguer', 'guide', 'Y aller', 'cible', 'Choisissez une salle : le robot y va.', 'simulation', 'y-aller'),
  c('navigation.bloquer', R, 'naviguer', 'securite', 'Bloquer', 'cadenas', 'Le robot reste immobile jusqu\'à « Débloquer ».', 'simulation', 'bloquer'),
  c('navigation.debloquer', R, 'naviguer', 'securite', 'Débloquer', 'cadenas-ouvert', 'Le robot peut de nouveau marcher.', 'simulation', 'debloquer'),
  c('navigation.arreter', R, 'naviguer', 'navigation', 'Arrêter la navigation', 'stop', 'Arrête la navigation (et la répétition).', 'simulation', 'arreter'),

  // Réel › Piloter (vrai robot, ou répétition avec le faux G1)
  c('pilotage.main', R, 'piloter', 'main', 'Prendre la main', 'main', 'Pilotez le robot vous-même : le guide attend.', 'pilotage', 'main'),
  c('pilotage.postures', R, 'piloter', 'robot', 'Postures', 'posture', 'Démarrer, s\'accroupir, se lever, s\'asseoir.', 'pilotage', 'postures'),
  c('pilotage.gestes', R, 'piloter', 'robot', 'Gestes', 'geste', 'Saluer, applaudir, faire un cœur…', 'pilotage', 'gestes'),
  c('pilotage.voix', R, 'piloter', 'robot', 'Voix', 'voix', 'Le robot dit une phrase.', 'pilotage', 'voix'),
  c('pilotage.led', R, 'piloter', 'robot', 'Lumière', 'led', 'Couleur des lumières du robot.', 'pilotage', 'led'),
  c('pilotage.joysticks', R, 'piloter', 'robot', 'Joysticks', 'joystick', 'Deux manettes à l\'écran : avancer à gauche, tourner à droite.', 'pilotage', 'joysticks'),
  c('pilotage.danses', R, 'piloter', 'spectacle', 'Danses', 'danse', 'Les danses du robot (zone libre de 2 à 3 m).', 'pilotage', 'danses'),
  c('pilotage.choregraphies', R, 'piloter', 'spectacle', 'Chorégraphies', 'choregraphie', 'Vos chorégraphies, avec leur aperçu 3D.', 'pilotage', 'choregraphies'),
  c('pilotage.portique', R, 'piloter', 'avance', 'Portique', 'portique', 'Amortir, couple nul : seulement robot tenu au portique.', 'pilotage', 'portique', { avance: true }),
  c('pilotage.volume', R, 'piloter', 'avance', 'Volume', 'volume', 'Volume du haut-parleur du robot.', 'pilotage', 'volume', { avance: true }),

  // Équipe (les deux modes)
  c('personnalites.ouvrir', SR, 'equipe', 'equipe', 'Personnalités', 'personnalite', 'Le caractère du robot : salutation, voix, couleurs.', 'personnalites', 'ouvrir'),
  c('dialogues.ouvrir', SR, 'equipe', 'equipe', 'Dialogues', 'dialogue', 'Ce que le robot répond aux visiteurs.', 'dialogues', 'ouvrir'),
  c('camera.ouvrir', SR, 'equipe', 'equipe', 'Caméra', 'camera', 'La caméra de poitrine et les visiteurs vus.', 'camera', 'ouvrir'),
];

// Commandes d'un mode ('simu', 'reel' ; la répétition prend 'reel'), et d'un onglet s'il est donné
export function commandesDe(mode, onglet) {
  const m = mode === 'repetition' ? 'reel' : mode;
  return COMMANDES.filter((x) => x.modes.indexOf(m) >= 0 && (!onglet || x.onglet === onglet));
}

// Construit le ruban dans element. options : {mode, surCommande(commande)}. Squelette : à écrire par
// l'agent Coquille. Renvoie {choisirOnglet(id), activer(id), griser(id, raison), detruire()}.
export function construireRuban(element, options) {   // eslint-disable-line no-unused-vars
  return { choisirOnglet: () => {}, activer: () => {}, griser: () => {}, detruire: () => {} };
}
