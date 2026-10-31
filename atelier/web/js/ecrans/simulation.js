// Écran Simulation (Simulation › Simuler) et Navigation (Réel › Naviguer) : lancer Gazebo et le guide (ou
// la navigation du vrai robot, ou la répétition sans robot), voir le robot et les piétons en direct (plan
// 2D, et vue 3D de la coque), envoyer le robot vers une salle (« Y aller »), le repérer, le bloquer.
//
// Le mode vient de la coque (options.mode) : « simu » (Gazebo seul), « repetition » (Gazebo avec le faux
// G1 : la vraie chaîne du robot, repérage et pont compris) ou « reel » (la navigation dans le conteneur du
// Jetson). En répétition et avec le robot, la section Repérage rappelle de poser le robot sur l'accueil
// (l'étoile sur la carte, tourné dans le sens de sa flèche), puis « Repérer » ; sans accueil sur l'étage,
// c'est la marque au sol de la vague 3. « Y aller » reste grisé tant que le robot n'est pas repéré ou que
// Nav2 n'est pas prêt, avec la raison dans l'infobulle et dans le panneau.

import { api, urlLieu } from '../api.js';
import { contexte } from '../contexte.js';
import { abonner } from '../direct.js';
import { preparerEcran, section } from '../coque/ecran.js';
import { ouvrirPanneau } from '../coque/panneau.js';
import * as F from '../formulaire.js';
import * as G from '../geometrie.js';
import { afficherErreur } from '../messages.js';
import { creerPlan, iconeOrientee, ll, lls, suivrePointeur } from '../plan.js';
import { etiquetteSalle, iconePrincipal, sallePrincipale } from './salles.js';
// Vague 4 (section 11 du plan) : panneaux des agents Comportement du guide et Passants
import * as panneauGuide from '../panneaux/guide.js';
import * as panneauPassants from '../panneaux/passants.js';

const L = window.L;

const MODES = {
  simu: { titre: 'Simulation', texte: 'Le robot simulé de Gazebo, conduit par le guide.', mode: 'simu' },
  repetition: { titre: 'Répétition sans robot', texte: 'La chaîne du vrai robot, avec un faux G1 dans Gazebo.', mode: 'repetition' },
  reel: { titre: 'Robot réel', texte: 'La navigation tourne dans le Jetson et commande le vrai G1.', mode: 'robot' },
};

const ETATS_REPERAGE = {
  non_repere: 'Non repéré',
  en_cours: 'Repérage en cours…',
  repere: 'Repéré',
  perdu: 'Repérage perdu',
  echec: 'Échec du repérage',
};

const ETATS_PONT = {
  demarrage: 'démarrage', attente_reperage: 'attend le repérage', pret: 'prêt', en_mouvement: 'en marche',
  arret: 'arrêt demandé', arret_verrouille: 'bloqué', robot_muet: 'le robot ne répond pas', refus: 'refus du robot',
  pilotage: 'piloté à la main', pas_en_marche: 'pas en mode marche',
};

const ETATS_GUIDE = {
  attente: 'Prêt : choisissez une salle',
  en_route: 'En route',
  bloque: 'Bloqué : quelque chose gêne le passage',
  detour: 'Détour par un autre chemin',
  arrive: 'Arrivé',
  echec: 'Échec : le guide n\'a pas pu y aller',
  // vague 4 (section 11.4)
  retour: 'Retour à l\'accueil',
  attente_passage: 'Attend qu\'un passant libère le passage',
  attente_visiteur: 'Attend le visiteur',
  perdu: 'Perdu : le robot ne sait plus où il est',
};

const CONFIRMATION_ROBOT = 'La navigation va commander le vrai robot :\n'
  + '- câble Ethernet branché entre le PC et le robot ;\n'
  + '- Atelier lancé après « source ~/robot-g1/setup/robot.sh » ;\n'
  + '- télécommande en main : elle reste l\'arrêt d\'urgence ;\n'
  + '- robot debout, en mode marche, avec quelqu\'un à côté.';

export function ouvrir(racine, options) {
  const ecran = preparerEcran(racine, options);
  const coque = ecran.coque;
  const lieu = contexte.lieu;
  const etage = contexte.etage;
  const mode = ecran.mode === 'reel' || ecran.mode === 'repetition' ? ecran.mode : 'simu';
  const defMode = MODES[mode];
  const etat = {
    salles: [], noeuds: {}, monde: null, dernierItineraire: '', enCours: false, modeActif: null,
    marque: null,           // pose où poser le robot {x, y, theta}, repère map : l'accueil, sinon la marque au sol
    principal: null,        // point principal de l'étage {salle, nom, etage, x, y, theta}, ou null
    repere: false, reperageEnCours: false, placement: null, choixPosition: false, lancement: false,
    attente: null, ferme: false,
  };

  ecran.vue.innerHTML = '<div class="plan" data-role="plan"></div>';
  const plan = creerPlan(ecran.vue.querySelector('[data-role=plan]'));
  const carte = plan.carte;
  const calqueSalles = L.layerGroup().addTo(carte);
  const calqueMarque = L.layerGroup().addTo(carte);
  const calqueItineraire = L.layerGroup().addTo(carte);
  const calqueDirect = L.layerGroup().addTo(carte);
  let marqueurRobot = null;
  let marqueurPlacement = null;
  const marqueursPietons = new Map();

  // ---------------------------------------------------------------- panneau (sections fixes)

  const panneau = ouvrirPanneau(ecran.panneau, { titre: mode === 'simu' ? 'Simuler' : 'Naviguer' });
  const z = panneau.corps;
  z.classList.add('panneau-simulation');
  const bandeau = F.el('div', 'mode-bandeau');
  bandeau.setAttribute('data-mode', mode);
  bandeau.setAttribute('data-role', 'mode-simulation');
  const textesBandeau = F.el('div', '');
  textesBandeau.appendChild(F.el('div', 'mode-bandeau-titre', defMode.titre));
  textesBandeau.appendChild(F.el('div', 'mode-bandeau-texte', defMode.texte));
  bandeau.appendChild(textesBandeau);
  z.appendChild(bandeau);
  // état et lancement
  const blocEtat = section(z, null, 'etat');
  const texteEtat = F.el('p', 'etat-action', 'Simulation arrêtée');
  texteEtat.setAttribute('data-role', 'etat-simu');
  blocEtat.appendChild(texteEtat);
  const boutons = F.el('div', 'boutons-simulation');
  const boutonLancer = F.bouton(boutons, mode === 'simu' ? 'Lancer la simulation' : (mode === 'repetition'
    ? 'Lancer la répétition' : 'Lancer sur le robot'), () => lancer(), 'bouton bouton-principal bouton-grand');
  boutonLancer.setAttribute('data-role', 'lancer');
  const boutonArreter = F.bouton(boutons, mode === 'simu' ? 'Arrêter la simulation' : (mode === 'repetition'
    ? 'Arrêter la répétition' : 'Arrêter la navigation'), () => arreter(), 'bouton');
  boutonArreter.setAttribute('data-role', 'arreter');
  blocEtat.appendChild(boutons);
  // repérage (répétition et robot)
  const blocReperage = section(z, 'Repérage', 'reperage');
  blocReperage.classList.add('panneau-reperage');
  blocReperage.setAttribute('data-role', 'reperage');
  blocReperage.hidden = mode === 'simu';
  const consigne = F.paragraphe(blocReperage, 'Posez le robot sur l\'accueil (étoile sur la carte), tourné dans le sens de la flèche.');
  consigne.setAttribute('data-role', 'consigne-reperage');
  const boutonReperer = F.bouton(blocReperage, 'Repérer le robot', () => reperer(null), 'bouton bouton-principal bouton-grand bouton-reperer');
  boutonReperer.setAttribute('data-role', 'reperer');
  const lienPosition = F.bouton(blocReperage, 'Le robot n\'est pas sur l\'accueil', () => choisirPosition(!etat.choixPosition), 'bouton-lien');
  lienPosition.setAttribute('data-role', 'pas-sur-marque');
  const aidePosition = F.paragraphe(blocReperage, 'Cliquez sur le plan là où se trouve le robot, puis glissez vers son avant : '
    + 'le repérage part quand vous lâchez.', 'panneau-note');
  aidePosition.setAttribute('data-role', 'aide-position');
  aidePosition.hidden = true;
  const etatReperage = F.el('div', 'etat-reperage', 'Non repéré');
  etatReperage.setAttribute('data-role', 'etat-reperage');
  blocReperage.appendChild(etatReperage);
  const messageReperage = F.el('div', 'panneau-note');
  messageReperage.setAttribute('data-role', 'message-reperage');
  blocReperage.appendChild(messageReperage);
  const pastillePont = F.el('div', 'pastille-pont', 'Pont vers la marche : —');
  pastillePont.setAttribute('data-role', 'pont');
  blocReperage.appendChild(pastillePont);
  const verrous = F.el('div', 'boutons-verrou');
  const boutonBloquer = F.bouton(verrous, 'Bloquer le robot', () => verrouiller(true), 'bouton bouton-danger');
  boutonBloquer.setAttribute('data-role', 'bloquer');
  const boutonDebloquer = F.bouton(verrous, 'Débloquer', () => verrouiller(false), 'bouton');
  boutonDebloquer.setAttribute('data-role', 'debloquer');
  blocReperage.appendChild(verrous);
  // guide
  const blocGuide = section(z, 'Envoyer le robot', 'guide');
  const etatGuide = F.el('div', 'guide-etat', 'Guide non lancé');
  etatGuide.setAttribute('data-role', 'guide');
  blocGuide.appendChild(etatGuide);
  const detailGuide = F.el('div', 'guide-detail');
  detailGuide.setAttribute('data-role', 'guide-detail');
  blocGuide.appendChild(detailGuide);
  const listeSalles = F.el('ul', 'liste-salles');
  listeSalles.setAttribute('data-role', 'salles');
  blocGuide.appendChild(listeSalles);
  // comportement du guide et passants (vague 4), repliés
  const detailsComportement = F.el('details', 'section-panneau section-comportement');
  detailsComportement.setAttribute('data-section', 'comportement');
  detailsComportement.appendChild(F.el('summary', '', 'Visite guidée'));
  const zoneComportement = F.el('div', 'panneau-comportement');
  zoneComportement.setAttribute('data-role', 'panneau-comportement');
  detailsComportement.appendChild(zoneComportement);
  z.appendChild(detailsComportement);
  const detailsPassants = F.el('details', 'section-panneau section-passants');
  detailsPassants.setAttribute('data-section', 'passants');
  detailsPassants.appendChild(F.el('summary', '', 'Passants'));
  const zonePassants = F.el('div', 'panneau-passants');
  zonePassants.setAttribute('data-role', 'panneau-passants');
  detailsPassants.appendChild(zonePassants);
  detailsPassants.hidden = mode !== 'simu';
  z.appendChild(detailsPassants);

  const outilsPanneaux = { lieu: lieu, etage: etage, plan: plan, carte: carte };
  const panneaux = [panneauGuide.monter(zoneComportement, outilsPanneaux)];
  if (mode === 'simu') panneaux.push(panneauPassants.monter(zonePassants, outilsPanneaux));

  function ouvrirSection(details, sousPartie) {
    details.open = true;
    if (sousPartie) {
      const d = details.querySelector(sousPartie);
      if (d) d.open = true;
    }
    details.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }

  // ---------------------------------------------------------------- incrustation de la caméra (Réel)

  let camera = null;
  let retirerIncrustation = null;
  let cadreCamera = null;
  // dans la vue centrale Caméra, l'incrustation ferait double emploi (et couvrirait l'image) : cachée, son
  // flux arrêté ; elle revient en 3D et en Plan 2D
  function incrustationSelonVue(nom) {
    if (!cadreCamera) return;
    cadreCamera.hidden = nom === 'camera';
    if (!camera) return;
    if (cadreCamera.hidden) camera.arreter();
    else camera.demarrer();
  }
  if (mode !== 'simu' && coque.incruster) {
    const cadre = F.el('div', 'incrustation-camera');
    cadre.setAttribute('data-role', 'incrustation-camera');
    // titre posé sur l'image ; sans image, l'incrustation se replie en « Caméra : pas d'image » (atelier.css)
    const titre = F.el('span', 'incrustation-titre', 'Caméra');
    titre.appendChild(F.el('span', 'incrustation-sans-image', ' : pas d\'image'));
    cadre.title = 'Caméra de poitrine (détails : Équipe › Caméra)';
    cadre.appendChild(titre);
    retirerIncrustation = coque.incruster(cadre);
    cadreCamera = cadre;
    import('../camera/flux.js').then((m) => {
      if (etat.ferme) return;
      camera = m.creerVueCamera(cadre, { source: 'poitrine', cadres: true, petit: true });
      incrustationSelonVue(coque.vue ? coque.vue() : null);
    }).catch(() => { cadre.remove(); });
  }

  // ---------------------------------------------------------------- point principal et marque au sol

  function avecReperage() {
    return mode !== 'simu';
  }

  function textesPose() {
    const p = etat.principal;
    if (p) {
      return {
        consigne: 'Posez le robot sur l\'accueil « ' + p.nom + ' » (étoile sur la carte), tourné dans le sens de la flèche.',
        lien: 'Le robot n\'est pas sur l\'accueil',
        annuler: 'Annuler : le robot est sur l\'accueil',
        court: 'sur l\'accueil « ' + p.nom + ' »',
      };
    }
    return {
      consigne: 'Posez le robot sur la marque au sol (croix sur la carte), tourné dans le sens de la flèche.',
      lien: 'Le robot n\'est pas sur la marque',
      annuler: 'Annuler : le robot est sur la marque',
      court: 'sur la marque au sol',
    };
  }

  function majTextesPose() {
    const t = textesPose();
    consigne.textContent = t.consigne;
    lienPosition.textContent = etat.choixPosition ? t.annuler : t.lien;
  }

  async function chargerMarque() {
    try {
      const r = await api.lire('/api/robot/etat?lieu=' + encodeURIComponent(lieu) + '&etage=' + encodeURIComponent(etage));
      if (!r.mode || (r.lieu === lieu && r.etage === etage)) {
        etat.marque = r.marque;
        etat.principal = r.principal || null;
      }
    } catch (e) {
      etat.marque = null;          // pas grave : la marque n'est qu'une aide
      etat.principal = null;
    }
    if (etat.ferme) return;
    majTextesPose();
    dessinerMarque();
  }

  function dessinerMarque() {
    calqueMarque.clearLayers();
    if (!etat.marque || !avecReperage()) return;
    const m = etat.marque;
    if (etat.principal) {
      // l'accueil est déjà dessiné (étoile et flèche, calque des salles) : on l'entoure
      L.circle(ll(m.x, m.y), { radius: 0.6, className: 'marque-principal', interactive: false })
        .bindTooltip('Accueil « ' + etat.principal.nom + ' » : posez le robot ici, tourné dans le sens de la flèche',
          { direction: 'top', className: 'etiquette' })
        .addTo(calqueMarque);
      return;
    }
    const deg = -m.theta * 180 / Math.PI;
    L.marker(ll(m.x, m.y), {
      icon: L.divIcon({ className: 'marque-sol', iconSize: [34, 34], iconAnchor: [17, 17],
        html: '<div class="marque-sol-croix" style="transform: rotate(' + deg + 'deg)"><span></span></div>' }),
      interactive: false, keyboard: false,
    }).bindTooltip('Marque au sol : posez le robot ici', { direction: 'top', offset: [0, -14], className: 'etiquette' })
      .addTo(calqueMarque);
  }

  // ---------------------------------------------------------------- repérage

  async function reperer(pose) {
    if (etat.reperageEnCours) return;
    etat.reperageEnCours = true;
    boutonReperer.disabled = true;
    boutonReperer.textContent = 'Repérage…';
    coque.griser('reperer', 'Repérage en cours…');
    const corps = { lieu: lieu, etage: etage };
    if (pose) {
      corps.x = G.arrondir(pose.x, 3);
      corps.y = G.arrondir(pose.y, 3);
      corps.cap = G.arrondir(pose.theta, 4);
    }
    try {
      const r = await api.envoyer('/api/robot/reperer', corps);
      coque.message(r.message || 'Robot repéré.', 'succes');
    } catch (e) {
      afficherErreur(e);
    } finally {
      etat.reperageEnCours = false;
      boutonReperer.textContent = 'Repérer le robot';
      boutonReperer.disabled = false;
    }
  }

  function choisirPosition(oui) {
    etat.choixPosition = oui;
    aidePosition.hidden = !oui;
    majTextesPose();
    plan.cadre.classList.toggle('dessin', oui);
    if (oui) {
      coque.choisirVue('plan');
      coque.activer('position');
    } else {
      coque.activer(null);
    }
  }

  function dessinerPlacement() {
    const t = etat.placement;
    if (!t) {
      if (marqueurPlacement) calqueDirect.removeLayer(marqueurPlacement);
      marqueurPlacement = null;
      return;
    }
    const icone = iconeOrientee('robot-direct trace', t.theta);
    if (!marqueurPlacement) marqueurPlacement = L.marker(ll(t.x, t.y), { icon: icone, interactive: false, zIndexOffset: 900 }).addTo(calqueDirect);
    else {
      marqueurPlacement.setLatLng(ll(t.x, t.y));
      marqueurPlacement.setIcon(icone);
    }
  }

  const arreterPointeur = suivrePointeur(plan, {
    debut: (p) => {
      if (!etat.choixPosition) return false;
      etat.placement = { x: p[0], y: p[1], theta: etat.marque ? etat.marque.theta : 0 };
      dessinerPlacement();
      return true;
    },
    deplacer: (p) => {
      const t = etat.placement;
      if (!t) return;
      if (G.distance([t.x, t.y], p) > 0.2) t.theta = G.accrocherAngle(Math.atan2(p[1] - t.y, p[0] - t.x), 5);
      dessinerPlacement();
    },
    fin: () => {
      const t = etat.placement;
      choisirPosition(false);
      if (t) {
        reperer(t).finally(() => {
          etat.placement = null;
          dessinerPlacement();
        });
      }
    },
    annuler: () => {
      etat.placement = null;
      dessinerPlacement();
    },
  });

  async function verrouiller(verrou) {
    try {
      const r = await api.envoyer('/api/robot/arret', { verrou: verrou });
      coque.message(verrou ? 'Robot bloqué : il reste immobile jusqu\'à « Débloquer ».'
        : 'Robot débloqué : il repartira à la prochaine consigne.', verrou ? 'avertissement' : 'info');
      if (r.avertissement) coque.message(r.avertissement, 'avertissement');
    } catch (e) {
      afficherErreur(e);
    }
  }

  function majReperage(d) {
    const r = d.reperage;
    const avecRobot = !!etat.modeActif && etat.modeActif !== 'simu';
    let titre = 'Non repéré';
    let classe = 'reperage-non_repere';
    let message = 'Lancez la navigation, puis posez le robot ' + textesPose().court + '.';
    etat.repere = false;
    if (avecRobot) {
      if (!r || r.perime) {
        titre = 'Relais de position…';
        message = 'Le relais de position démarre : « Repérer » sera possible dans quelques secondes.';
      } else {
        titre = ETATS_REPERAGE[r.etat] || r.etat;
        classe = 'reperage-' + r.etat;
        message = r.message || '';
        etat.repere = !!r.repere;
        if (r.repere) {
          const morceaux = [];
          if (r.precision_m !== null && r.precision_m !== undefined) morceaux.push('précision ' + Math.max(1, Math.round(r.precision_m * 100)) + ' cm');
          if (r.age_s !== null && r.age_s !== undefined) morceaux.push('il y a ' + G.nb(r.age_s, 1) + ' s');
          if (morceaux.length) titre += ' (' + morceaux.join(', ') + ')';
        }
      }
    }
    etatReperage.textContent = titre;
    etatReperage.className = 'etat-reperage ' + classe;
    messageReperage.textContent = message;
    const ros = !!(d.ros && d.ros.actif);
    boutonReperer.disabled = !(avecRobot && ros) || etat.reperageEnCours;
    lienPosition.disabled = !(avecRobot && ros);
    boutonBloquer.disabled = !ros;
    boutonDebloquer.disabled = !ros;
    coque.griser('reperer', !avecRobot ? 'Lancez d\'abord la navigation' : (!ros ? 'Pas de liaison ROS 2' : (etat.reperageEnCours ? 'Repérage en cours…' : null)));
    coque.griser('position', !(avecRobot && ros) ? 'Lancez d\'abord la navigation' : null);
    coque.griser('bloquer', ros ? null : 'Pas de liaison ROS 2');
    coque.griser('debloquer', ros ? null : 'Pas de liaison ROS 2');
    const p = d.pont;
    if (!p || p.perime) {
      pastillePont.textContent = 'Pont vers la marche : ' + (avecRobot ? 'pas encore de nouvelles' : '—');
      pastillePont.className = 'pastille-pont';
    } else {
      pastillePont.textContent = 'Pont vers la marche : ' + (ETATS_PONT[p.etat] || p.etat) + (p.message ? ' — ' + p.message : '');
      const ok = p.etat === 'pret' || p.etat === 'en_mouvement';
      const ko = p.etat === 'robot_muet' || p.etat === 'refus' || p.etat === 'arret_verrouille' || p.etat === 'pas_en_marche';
      pastillePont.className = 'pastille-pont ' + (ok ? 'pont-ok' : (ko ? 'pont-ko' : 'pont-attente'));
    }
  }

  // ---------------------------------------------------------------- salles et « Y aller »

  function nomDe(id) {
    const s = etat.salles.find((x) => x.id === id);
    return s ? s.nom : id;
  }

  function sallesIci() {
    const p = sallePrincipale(etat.salles);
    return etat.salles.filter((s) => s.etage === etage)
      .sort((a, b) => (a === p ? -1 : (b === p ? 1 : a.nom.localeCompare(b.nom, 'fr'))));
  }

  function remplirListeSalles() {
    listeSalles.textContent = '';
    const salles = sallesIci();
    const p = sallePrincipale(etat.salles);
    if (!salles.length) listeSalles.appendChild(F.el('li', 'vide', 'Aucune salle : placez-en (Placer › Salle).'));
    salles.forEach((s) => {
      const li = F.el('li');
      li.setAttribute('data-salle', s.id);
      if (s === p) li.appendChild(F.el('span', 'etoile', '★'));
      li.appendChild(F.el('span', 'nom-salle', s.nom));
      F.bouton(li, 'Y aller', () => allerVers(s.id), 'bouton bouton-principal');
      listeSalles.appendChild(li);
    });
    coque.menu('y-aller', salles.map((s) => ({ valeur: s.id, libelle: (s === p ? '★ ' : '') + s.nom })));
  }

  function dessinerSalles() {
    calqueSalles.clearLayers();
    const p = sallePrincipale(etat.salles);
    etat.salles.filter((s) => s.etage === etage).forEach((s) => {
      const icone = s === p ? iconePrincipal(s.pose.theta) : iconeOrientee('salle', s.pose.theta);
      L.marker(ll(s.pose.x, s.pose.y), { icon: icone, keyboard: false, zIndexOffset: s === p ? 500 : 0,
        title: 'Y aller : ' + s.nom })
        .bindTooltip(etiquetteSalle(s.nom, s === p), { permanent: true, direction: 'right', offset: [14, 0], className: 'etiquette' })
        .on('click', () => allerVers(s.id))
        .addTo(calqueSalles);
    });
  }

  async function allerVers(id) {
    if (etat.attente) {
      coque.message('« Y aller » attend : ' + etat.attente, 'avertissement');
      return;
    }
    const corps = { cible: id };
    if (mode === 'simu') {
      const cases = coque.cases();
      if (cases.accompagner) corps.accompagner = true;
      if (cases.retour === false) corps.retour = false;
      else if (cases.accompagner) corps.retour = true;
    }
    try {
      const r = await api.envoyer('/api/guide/aller', corps);
      coque.message('Destination envoyée : ' + nomDe(id) + (corps.accompagner ? ', en accompagnant le visiteur' : '') + '.', 'info');
      if (r.avertissement) coque.message(r.avertissement, 'avertissement');
    } catch (e) {
      afficherErreur(e);
    }
  }

  // ---------------------------------------------------------------- lancer et arrêter

  async function confirmerRobot() {
    let liaison = null;
    try {
      liaison = await api.lire('/api/robot/liaison');
    } catch (e) {
      liaison = null;
    }
    const pret = liaison && liaison.pret;
    const texte = CONFIRMATION_ROBOT + '\n\n' + (liaison ? liaison.message : 'La liaison avec le robot n\'a pas pu être vérifiée.')
      + (coque.telecommande() ? '' : '\n\nAvez-vous la télécommande en main ?');
    return coque.confirmer(texte, { titre: pret ? 'Lancer sur le robot' : 'Le robot n\'est peut-être pas prêt',
      ok: 'Lancer sur le robot', annuler: 'Pas maintenant', danger: !pret });
  }

  async function lancer() {
    if (etat.lancement || etat.enCours) return;
    if (mode === 'reel' && !(await confirmerRobot())) return;
    if (mode === 'reel') coque.noterTelecommande(true);
    etat.lancement = true;
    boutonLancer.disabled = true;
    coque.griser('lancer', 'Lancement…');
    texteEtat.textContent = 'Lancement…';
    try {
      const corps = { lieu: lieu, etage: etage };
      if (defMode.mode !== 'simu') corps.mode = defMode.mode;
      const r = await api.envoyer('/api/simulation/demarrer', corps);
      const av = (r.simulation && r.simulation.avertissements) || [];
      if (mode === 'simu') coque.message('Simulation lancée : le robot apparaît dans quelques secondes.', 'succes');
      else if (mode === 'repetition') coque.message('Répétition lancée : quand le relais de position est prêt, « Repérer ».', 'succes');
      else coque.message('Navigation lancée sur le robot. Posez-le ' + textesPose().court + ', tourné comme la flèche, puis « Repérer ».', 'succes');
      av.forEach((m) => coque.message(m, 'avertissement'));
    } catch (e) {
      afficherErreur(e);
      boutonLancer.disabled = false;
      coque.griser('lancer', null);
    } finally {
      etat.lancement = false;
    }
  }

  async function arreter() {
    boutonArreter.disabled = true;
    texteEtat.textContent = 'Arrêt en cours… (quelques secondes)';
    try {
      await api.envoyer('/api/simulation/arreter');
      coque.message(etat.modeActif === 'robot' ? 'Navigation du robot arrêtée.' : (mode === 'repetition'
        ? 'Répétition arrêtée.' : 'Simulation arrêtée.'), 'info');
    } catch (e) {
      afficherErreur(e);
    } finally {
      boutonArreter.disabled = false;
    }
  }

  // ---------------------------------------------------------------- en direct

  function texteGuide(g) {
    if (!g) return { titre: 'Guide non lancé', detail: 'Lancez la ' + (mode === 'simu' ? 'simulation' : 'navigation') + ' : le guide démarre avec elle.' };
    let titre = ETATS_GUIDE[g.etat] || ('État : ' + g.etat);
    if (['en_route', 'arrive', 'echec', 'detour', 'bloque', 'retour', 'attente_passage', 'attente_visiteur', 'perdu'].includes(g.etat) && g.cible) {
      titre += (g.etat === 'arrive' ? ' à « ' : ' — vers « ') + nomDe(g.cible) + ' »';
    }
    let detail = '';
    if (g.reste_m !== null && g.reste_m !== undefined && g.etat !== 'arrive') detail = 'Encore ' + G.nb(g.reste_m, 1) + ' m.';
    if (g.itineraire && g.itineraire.length) detail += ' Chemin : ' + g.itineraire.join(' → ');
    return { titre: titre, detail: detail };
  }

  function dessinerItineraire(g) {
    const cle = g && g.itineraire ? g.itineraire.join(',') + g.etat : '';
    if (cle === etat.dernierItineraire) return;
    etat.dernierItineraire = cle;
    calqueItineraire.clearLayers();
    if (!g || !g.itineraire || g.etat === 'arrive' || g.etat === 'attente') return;
    const pts = g.itineraire.map((id) => etat.noeuds[id]).filter((n) => n && n.etage === etage).map((n) => [n.x, n.y]);
    if (pts.length > 1) L.polyline(lls(pts), { className: 'itineraire-direct', interactive: false }).addTo(calqueItineraire);
  }

  function recevoir(d) {
    if (etat.ferme) return;
    const sim = d.simulation;
    const procs = d.processus || {};
    const robot = d.mode === 'robot';
    const enCours = !!(sim && sim.en_cours) || robot;
    etat.enCours = enCours;
    etat.modeActif = d.mode || null;
    let texte = mode === 'simu' ? 'Simulation arrêtée' : (mode === 'repetition' ? 'Répétition arrêtée' : 'Navigation arrêtée');
    if (robot) {
      texte = 'Navigation du robot en cours : « ' + sim.lieu + ' », ' + sim.etage;
    } else if (enCours) {
      texte = (d.mode === 'repetition' ? 'Répétition en cours' : 'Simulation en cours') + ' : « ' + sim.lieu + ' », ' + sim.etage;
      if (procs.navigation) texte += procs.navigation.en_cours ? ', guide lancé' : ', guide arrêté';
    } else if (procs.simulation && !procs.simulation.en_cours && !procs.simulation.arret_demande) {
      texte = 'La simulation s\'est arrêtée seule (code ' + procs.simulation.code + ') : voir « Ce qui tourne », en bas.';
    }
    if (enCours && sim && (sim.lieu !== lieu || sim.etage !== etage)) texte += ' (un autre lieu que celui-ci)';
    if (enCours && etat.modeActif && MODES[mode].mode !== etat.modeActif) {
      texte += ' — mode ' + (etat.modeActif === 'simu' ? 'simulation' : etat.modeActif);
    }
    if (!d.ros || !d.ros.actif) texte += ' — pas de liaison ROS 2' + (d.ros && d.ros.erreur ? ' (' + d.ros.erreur + ')' : '');
    texteEtat.textContent = texte;
    boutonLancer.disabled = enCours || etat.lancement;
    boutonArreter.disabled = !enCours && !(procs.navigation && procs.navigation.en_cours);
    coque.griser('lancer', enCours ? 'Déjà lancée : « Arrêter » d\'abord' : (etat.lancement ? 'Lancement…' : null));
    coque.griser('arreter', boutonArreter.disabled ? 'Rien ne tourne' : null);
    if (avecReperage()) majReperage(d);

    const memeLieu = !!sim && sim.lieu === lieu && sim.etage === etage;
    // robot
    const r = d.robot;
    if (r && memeLieu) {
      const icone = iconeOrientee('robot-direct' + (r.perimee ? ' perimee' : ''), r.theta);
      if (!marqueurRobot) marqueurRobot = L.marker(ll(r.x, r.y), { icon: icone, interactive: false, zIndexOffset: 1000 }).addTo(calqueDirect);
      else {
        marqueurRobot.setLatLng(ll(r.x, r.y));
        marqueurRobot.setIcon(icone);
      }
    } else if (marqueurRobot) {
      calqueDirect.removeLayer(marqueurRobot);
      marqueurRobot = null;
    }
    // piétons
    const vus = new Set();
    (memeLieu ? d.pietons || [] : []).forEach((p) => {
      vus.add(p.id);
      let m = marqueursPietons.get(p.id);
      if (!m) {
        m = L.circle(ll(p.x, p.y), { radius: 0.25, className: 'pieton-direct', interactive: false }).addTo(calqueDirect);
        marqueursPietons.set(p.id, m);
      } else m.setLatLng(ll(p.x, p.y));
    });
    marqueursPietons.forEach((m, id) => {
      if (!vus.has(id)) {
        calqueDirect.removeLayer(m);
        marqueursPietons.delete(id);
      }
    });
    // guide. Juste après le lancement, Nav2 se prépare (20 à 30 s) et refuserait un but : on attend
    // tant qu'il est vu inactif, ou 60 s au plus s'il n'est pas encore visible (le moteur unitree
    // n'a pas de Nav2 : au-delà, on laisse faire).
    const g = enCours || d.guide ? d.guide : null;
    const t = texteGuide(g);
    const nav = procs.navigation;
    const nav2 = d.ros ? d.ros.nav2 : null;
    const navEnCours = robot || !!(nav && nav.en_cours);
    const attendreNav2 = navEnCours && !!(d.ros && d.ros.actif)
      && (nav2 === false || (nav2 === null && (robot || nav.duree_s < 60)));
    // répétition et robot : il faut d'abord repérer le robot (la carte globale de Nav2 attend sa position)
    const attendreReperage = navEnCours && avecReperage() && !etat.repere;
    etat.attente = null;
    if (attendreReperage) {
      t.titre = 'Le guide attend le repérage du robot';
      t.detail = 'Posez le robot ' + textesPose().court + ', tourné dans le sens de la flèche, puis « Repérer ».';
      etat.attente = 'repérez d\'abord le robot';
    } else if (attendreNav2) {
      t.titre = 'Le guide démarre…';
      t.detail = 'Nav2 se prépare (20 à 30 secondes après le lancement). « Y aller » sera possible ensuite.';
      etat.attente = 'Nav2 se prépare';
    }
    if (g && g.message && !attendreReperage) t.detail = g.message + (t.detail ? ' ' + t.detail : '');
    listeSalles.querySelectorAll('button').forEach((b) => { b.disabled = attendreNav2 || attendreReperage; });
    coque.griser('y-aller', attendreReperage ? 'Repérez d\'abord le robot' : (attendreNav2 ? 'Nav2 se prépare…' : null));
    etatGuide.textContent = t.titre;
    etatGuide.className = 'guide-etat' + (g ? ' guide-' + g.etat : '');
    detailGuide.textContent = t.detail;
    dessinerItineraire(g);
  }

  // ---------------------------------------------------------------- commandes du ruban

  function commande(nom, valeur) {
    if (nom === 'lancer') lancer();
    else if (nom === 'arreter') arreter();
    else if (nom === 'y-aller') {
      if (valeur) allerVers(valeur);
      else blocGuide.scrollIntoView({ block: 'start', behavior: 'smooth' });
    } else if (nom === 'reperer') reperer(null);
    else if (nom === 'position') choisirPosition(true);
    else if (nom === 'bloquer') verrouiller(true);
    else if (nom === 'debloquer') verrouiller(false);
    else if (nom === 'faux-visiteur') ouvrirSection(detailsComportement, '.comportement-faux-visiteur');
    else if (nom === 'reglages-guide') ouvrirSection(detailsComportement, '.comportement-reglages');
    else if (nom === 'passants') ouvrirSection(detailsPassants);
  }

  let desabonner = null;
  async function charger() {
    try {
      const fond = await plan.afficherFond(lieu, etage);
      etat.monde = fond.monde;
      etat.salles = await api.lire(urlLieu(lieu) + '/salles');
      etat.noeuds = (await api.lire(urlLieu(lieu) + '/itineraires')).noeuds;
    } catch (e) {
      afficherErreur(e);
    }
    if (etat.ferme) return;
    dessinerSalles();
    remplirListeSalles();
    chargerMarque();
    desabonner = abonner(recevoir);
  }
  ecran.vue.classList.add('chargement');     // rien n'est modifiable avant la fin du chargement
  const pret = charger().finally(() => ecran.vue.classList.remove('chargement'));
  if (ecran.commande) pret.then(() => commande(ecran.commande, ecran.valeur));

  return {
    modifie: () => false,
    commande: (nom, valeur) => pret.then(() => commande(nom, valeur)),
    selectionner: (genre, id) => {
      if (genre !== 'salle') return;
      const li = listeSalles.querySelector('[data-salle="' + String(id).replace(/"/g, '') + '"]');
      if (li) {
        li.scrollIntoView({ block: 'nearest' });
        li.classList.add('choisie');
        setTimeout(() => li.classList.remove('choisie'), 1200);
      }
    },
    vue: (nom) => {
      incrustationSelonVue(nom);
      plan.carte.invalidateSize();
    },
    fermer: () => {
      etat.ferme = true;
      if (desabonner) desabonner();
      panneaux.forEach((p) => p.fermer());
      if (camera) camera.detruire();
      if (retirerIncrustation) retirerIncrustation();
      arreterPointeur();
      plan.detruire();
    },
  };
}
