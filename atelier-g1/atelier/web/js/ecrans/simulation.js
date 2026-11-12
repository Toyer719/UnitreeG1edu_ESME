// Écran Simulation (Simulation › Simuler) et Navigation (Réel › Naviguer) : lancer Gazebo et le guide (ou
// la navigation du vrai robot, ou la répétition sans robot), voir le robot et les piétons en direct (plan
// 2D, et vue 3D de la coque), envoyer le robot vers une salle (« Y aller »), le repérer, le bloquer.
//
// Le mode vient de la coque (options.mode) : « simu » (Gazebo seul), « repetition » (Gazebo avec le faux
// G1 : la vraie chaîne du robot, repérage et pont compris) ou « reel » (la navigation dans le conteneur du
// Jetson). En répétition et avec le robot, la section Repérage rappelle de poser le robot sur l'accueil
// (l'étoile sur la carte, tourné dans le sens de sa flèche), puis « Repérer » ; sans accueil sur l'étage,
// c'est la marque au sol de la vague 3. « Y aller » reste grisé tant que rien ne tourne, que le robot n'est
// pas repéré ou que Nav2 n'est pas prêt, avec la raison dans l'infobulle et dans le panneau.
//
// Revue de la vague 5 : le panneau montre l'état et la tâche en cours (lancement, repérage, guide, salles),
// pas une deuxième barre de commandes : Lancer, Arrêter, Repérer, Bloquer et Débloquer sont dans le ruban.
// Une seule section repliable ouverte à la fois (Visite guidée, Passants) ; une commande Avancé ouvre la
// sienne en haut du panneau. Une partie qui s'arrête seule (code de sortie, nœud planté) est signalée,
// avec « Relancer ».
//
// Correction du 01/11/2026 (section 12.15 du plan) : « Bloquer » annule le trajet en cours (le guide l'oublie,
// rien ne repart au « Débloquer ») ; tant que le robot est bloqué ou pas en mode marche, le panneau le dit
// (champ immobilise du guide) et « Y aller » est grisé.

import { api, urlLieu } from '../api.js';
import { contexte } from '../contexte.js';
import { abonner } from '../direct.js';
import { verrouVu } from '../coque/arret.js';
import { preparerEcran, section } from '../coque/ecran.js';
import { ouvrirPanneau } from '../coque/panneau.js';
import * as F from '../formulaire.js';
import * as G from '../geometrie.js';
import { afficherErreur } from '../messages.js';
import { creerPlan, iconeOrientee, ll, lls, suivrePointeur } from '../plan.js';
import { sallesDansLOrdre } from '../carte3d/geometrie3d.js';
import { nomLisible } from '../coque/arbre.js';
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

// Section 12.15 : ce qui immobilise le robot (champ immobilise de /guide/etat) ; le message du guide dit quoi faire
export const TITRES_IMMOBILE = {
  verrou: 'Robot bloqué : il ne bouge pas',
  pas_en_marche: 'Pas en mode marche : il ne bouge pas',
  robot_muet: 'Le robot ne répond plus : trajet annulé',
  refus: 'Le robot refuse de marcher : trajet annulé',
  // relecture du 01/11/2026 : le pont vers la marche ne donne plus de nouvelles (tué ou figé)
  pont_absent: 'Pas de nouvelles du pont : il ne bouge pas',
};
export const MESSAGE_BLOQUE = 'Robot bloqué : le trajet en cours est annulé. Il reste immobile jusqu\'à « Débloquer », '
  + 'puis attend un nouveau « Y aller ».';
export const MESSAGE_DEBLOQUE = 'Robot débloqué : il ne repartira qu\'avec un nouveau « Y aller ».';

// Pourquoi « Y aller » est grisé quand le robot est immobilisé (d : /ws/etat, g : /guide/etat), ou null
export function raisonImmobile(d, g) {
  if (verrouVu(d) || (g && g.immobilise === 'verrou')) return 'Robot bloqué : « Débloquer » d\'abord';
  if (g && g.immobilise === 'pas_en_marche') return 'Le robot n\'est pas en mode marche : remettez-le en marche d\'abord';
  if (g && g.immobilise === 'pont_absent') return 'Pas de nouvelles du pont vers la marche : vérifiez la navigation d\'abord';
  return null;
}

const CONFIRMATION_ROBOT = 'La navigation va commander le vrai robot :\n'
  + '- câble Ethernet branché entre le PC et le robot ;\n'
  + '- Atelier lancé après « source ~/robot-g1/setup/robot.sh » ;\n'
  + '- télécommande en main : elle reste l\'arrêt d\'urgence ;\n'
  + '- robot debout, en mode marche, avec quelqu\'un à côté.';

// Le chemin du guide pour l'utilisateur : le nom de la salle pour un nœud de salle, sinon l'identifiant rendu
// lisible (« couloir_nord_1 » → « Couloir nord 1 »), comme l'arbre du lieu (recette de la vague 5)
export function texteChemin(itineraire, salles) {
  return (itineraire || []).map((id) => {
    const s = (salles || []).find((x) => x.id === id);
    return s ? s.nom : nomLisible(id);
  }).join(' → ');
}

export function ouvrir(racine, options) {
  const ecran = preparerEcran(racine, options);
  const coque = ecran.coque;
  const lieu = contexte.lieu;
  const etage = contexte.etage;
  const mode = ecran.mode === 'reel' || ecran.mode === 'repetition' ? ecran.mode : 'simu';
  const defMode = MODES[mode];
  const etat = {
    salles: [], noeuds: {}, monde: null, dernierItineraire: '', enCours: false, modeActif: null, navEnCours: false,
    panne: '',              // parties plantées déjà signalées (la barre d'état ne le dit qu'une fois)
    marque: null,           // pose où poser le robot {x, y, theta}, repère map : l'accueil, sinon la marque au sol
    principal: null,        // point principal de l'étage {salle, nom, etage, x, y, theta}, ou null
    repere: false, reperageEnCours: false, placement: null, choixPosition: false, lancement: false,
    attente: null, ferme: false,
    immobile: null,         // section 12.15 : pourquoi « Y aller » est impossible (robot bloqué…), ou null
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
  // état du lancement (Lancer et Arrêter sont dans le ruban)
  const NOM_LANCEMENT = mode === 'simu' ? 'la simulation' : (mode === 'repetition' ? 'la répétition' : 'la navigation');
  const blocEtat = section(z, null, 'etat');
  const texteEtat = F.el('p', 'etat-action', 'Simulation arrêtée');
  texteEtat.setAttribute('data-role', 'etat-simu');
  blocEtat.appendChild(texteEtat);
  const aideLancer = F.paragraphe(blocEtat, '« Lancer », en haut dans le ruban, démarre ' + NOM_LANCEMENT
    + (mode === 'reel' ? ' sur le robot.' : ' : Gazebo et le guide.'), 'panneau-note');
  aideLancer.setAttribute('data-role', 'aide-lancer');
  const boutonRelancer = F.bouton(blocEtat, 'Relancer ' + NOM_LANCEMENT, () => relancer(), 'bouton bouton-principal');
  boutonRelancer.setAttribute('data-role', 'relancer');
  boutonRelancer.hidden = true;
  // repérage (répétition et robot)
  const blocReperage = section(z, 'Repérage', 'reperage');
  blocReperage.classList.add('panneau-reperage');
  blocReperage.setAttribute('data-role', 'reperage');
  blocReperage.hidden = mode === 'simu';
  const consigne = F.paragraphe(blocReperage, 'Posez le robot sur l\'accueil (étoile sur la carte), tourné dans le sens de la flèche.');
  consigne.setAttribute('data-role', 'consigne-reperage');
  F.paragraphe(blocReperage, 'Puis « Repérer », en haut dans le ruban.', 'panneau-note');
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

  const outilsPanneaux = { lieu: lieu, etage: etage, plan: plan, carte: carte, mode: mode };
  const panneaux = [panneauGuide.monter(zoneComportement, outilsPanneaux)];
  if (mode === 'simu') panneaux.push(panneauPassants.monter(zonePassants, outilsPanneaux));

  // une seule section repliable ouverte à la fois : le panneau reste court
  const sectionsRepliables = [detailsComportement, detailsPassants];
  sectionsRepliables.forEach((d) => d.addEventListener('toggle', () => {
    if (d.open) sectionsRepliables.forEach((x) => { if (x !== d) x.open = false; });
  }));

  // commande Avancé : sa section s'ouvre (seule) et vient en haut du panneau
  function ouvrirSection(details, sousPartie) {
    sectionsRepliables.forEach((x) => { if (x !== details) x.open = false; });
    details.open = true;
    let cible = details;
    if (sousPartie) {
      const d = details.querySelector(sousPartie);
      if (d) {
        d.open = true;
        cible = d;
      }
    }
    const haut = () => {
      const r = cible.getBoundingClientRect();
      const c = z.getBoundingClientRect();
      z.scrollTop += r.top - c.top - 6;
    };
    haut();
    requestAnimationFrame(haut);       // après la mise en page de la section ouverte
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
      // espaces insécables dans les guillemets : « » ne commence jamais une ligne
      const nom = '«\u00a0' + p.nom + '\u00a0»';
      return {
        consigne: 'Posez le robot sur l\'accueil ' + nom + ' (étoile sur la carte), tourné dans le sens de la flèche.',
        lien: 'Le robot n\'est pas sur l\'accueil',
        annuler: 'Annuler : le robot est sur l\'accueil',
        court: 'sur l\'accueil ' + nom,
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
      // section 12.15 : « Bloquer » annule le trajet en cours ; « Débloquer » ne relance rien
      coque.message(r.message || (verrou ? MESSAGE_BLOQUE : MESSAGE_DEBLOQUE), verrou ? 'avertissement' : 'info');
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
    let message = 'Lancez ' + NOM_LANCEMENT + ', puis posez le robot ' + textesPose().court + '.';
    etat.repere = false;
    const relaisPret = !!(r && !r.perime);
    if (avecRobot) {
      if (!relaisPret) {
        titre = 'Le robot se prépare…';
        message = 'Le robot n\'est pas encore prêt à être repéré : « Repérer » sera possible dans quelques secondes.';
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
    lienPosition.disabled = !(avecRobot && ros && relaisPret);
    const raisonReperer = !avecRobot ? 'Lancez d\'abord ' + NOM_LANCEMENT : (!ros ? 'Pas de liaison avec le robot (ROS 2)'
      : (!relaisPret ? 'Le robot se prépare : encore quelques secondes' : (etat.reperageEnCours ? 'Repérage en cours…' : null)));
    coque.griser('reperer', raisonReperer);
    coque.griser('position', !avecRobot ? 'Lancez d\'abord ' + NOM_LANCEMENT : (raisonReperer && !etat.reperageEnCours ? raisonReperer : null));
    coque.griser('bloquer', ros ? null : 'Pas de liaison avec le robot (ROS 2)');
    coque.griser('debloquer', ros ? null : 'Pas de liaison avec le robot (ROS 2)');
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

  // dans l'ordre des épingles de la vue 3D : [{salle, numero}]
  function sallesIci() {
    const p = sallePrincipale(etat.salles);
    return sallesDansLOrdre(etat.salles.filter((s) => s.etage === etage), p ? p.id : null);
  }

  function remplirListeSalles() {
    listeSalles.textContent = '';
    const numerotees = sallesIci();
    const salles = numerotees.map((n) => n.salle);
    const p = sallePrincipale(etat.salles);
    if (!salles.length) listeSalles.appendChild(F.el('li', 'vide', 'Aucune salle : placez-en (Placer › Salle).'));
    numerotees.forEach((n) => {
      const s = n.salle;
      const li = F.el('li');
      li.setAttribute('data-salle', s.id);
      if (s === p) li.appendChild(F.el('span', 'etoile', '★'));
      else if (n.numero !== null && n.numero !== undefined) li.appendChild(F.el('span', 'numero-salle', String(n.numero)));
      li.appendChild(F.el('span', 'nom-salle', s.nom));
      const b = F.bouton(li, 'Y aller', () => allerVers(s.id), 'bouton bouton-principal bouton-petit');
      b.dataset.titre = 'Le robot va à « ' + s.nom + ' »';
      b.title = b.dataset.titre;
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
    if (!etat.navEnCours) {
      coque.message('Lancez d\'abord ' + NOM_LANCEMENT + ' (« Lancer », dans le ruban) : le guide démarre avec elle.', 'avertissement');
      return;
    }
    if (etat.attente) {
      coque.message('« Y aller » attend : ' + etat.attente, 'avertissement');
      return;
    }
    if (etat.immobile) {
      // section 12.15 : le guide refuserait (robot bloqué ou pas en mode marche), la demande n'est pas gardée
      coque.message('« Y aller » impossible : ' + etat.immobile + '.', 'avertissement');
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
      // « Destination envoyée » seulement si un guide l'a reçue ; sinon, le seul avertissement
      if (r.avertissement) coque.message(r.avertissement, 'avertissement');
      else coque.message('Destination envoyée : ' + nomDe(id) + (corps.accompagner ? ', en accompagnant le visiteur' : '') + '.', 'info');
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
    etat.panne = '';
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
      coque.griser('lancer', null);
    } finally {
      etat.lancement = false;
    }
  }

  async function arreter() {
    texteEtat.textContent = 'Arrêt en cours… (quelques secondes)';
    coque.griser('arreter', 'Arrêt en cours…');
    try {
      await api.envoyer('/api/simulation/arreter');
      coque.message(etat.modeActif === 'robot' ? 'Navigation du robot arrêtée.' : (mode === 'repetition'
        ? 'Répétition arrêtée.' : 'Simulation arrêtée.'), 'info');
    } catch (e) {
      afficherErreur(e);
    }
  }

  // une partie s'est arrêtée seule : tout arrêter, puis relancer
  async function relancer() {
    boutonRelancer.disabled = true;
    try {
      await arreter();
      etat.enCours = false;
      await lancer();
    } finally {
      boutonRelancer.disabled = false;
    }
  }

  // Parties lancées par l'Atelier qui se sont arrêtées seules (code de sortie) ou nœuds plantés dans la
  // navigation (« process has died » de ros2 launch) : [phrases]
  const NOMS_PARTIES = { simulation: 'Gazebo', navigation: 'la navigation', faux_slam: 'le faux service de cartographie' };
  function partiesPlantees(procs) {
    const fautes = [];
    Object.keys(NOMS_PARTIES).forEach((role) => {
      const p = procs[role];
      if (!p) return;
      if (!p.en_cours && !p.arret_demande && p.code !== null && p.code !== undefined && p.code !== 0) {
        fautes.push(NOMS_PARTIES[role] + ' s\'est arrêté (code ' + p.code + ')');
      } else if (p.en_cours && p.plantages && p.plantages.length) {
        fautes.push('dans ' + NOMS_PARTIES[role] + ', ' + p.plantages.slice(0, 3).join(', ')
          + (p.plantages.length > 3 ? '…' : '') + ' ' + (p.plantages.length > 1 ? 'ont planté' : 'a planté'));
      }
    });
    return fautes;
  }

  // ---------------------------------------------------------------- en direct

  function texteGuide(g) {
    if (!g) return { titre: 'Guide non lancé', detail: 'Lancez la ' + (mode === 'simu' ? 'simulation' : 'navigation') + ' : le guide démarre avec elle.' };
    let titre = ETATS_GUIDE[g.etat] || ('État : ' + g.etat);
    if (['en_route', 'arrive', 'echec', 'detour', 'bloque', 'retour', 'attente_passage', 'attente_visiteur', 'perdu'].includes(g.etat) && g.cible) {
      titre += (g.etat === 'arrive' ? ' à « ' : ' — vers « ') + nomDe(g.cible) + ' »';
    }
    if (g.immobilise && TITRES_IMMOBILE[g.immobilise]) titre = TITRES_IMMOBILE[g.immobilise];
    let detail = '';
    if (g.reste_m !== null && g.reste_m !== undefined && g.etat !== 'arrive') detail = 'Encore ' + G.nb(g.reste_m, 1) + ' m.';
    if (g.itineraire && g.itineraire.length) detail += ' Chemin : ' + texteChemin(g.itineraire, etat.salles);
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
    // une partie plantée pendant que le reste tourne : la répétition (ou la simulation) n'a pas bien démarré
    const fautes = enCours || (procs.navigation && procs.navigation.en_cours) ? partiesPlantees(procs) : [];
    if (fautes.length) {
      texte = (mode === 'simu' ? 'La simulation' : (mode === 'repetition' ? 'La répétition' : 'La navigation'))
        + ' n\'a pas démarré correctement : ' + fautes.join(' ; ') + '.';
      const cle = fautes.join('|');
      if (cle !== etat.panne) {
        etat.panne = cle;
        coque.message(texte + ' « Relancer » (panneau) ou « Ce qui tourne » pour le détail.', 'erreur');
      }
    }
    texteEtat.textContent = texte;
    texteEtat.classList.toggle('panneau-alerte', fautes.length > 0);
    boutonRelancer.hidden = !fautes.length;
    aideLancer.hidden = enCours || etat.lancement;
    const rienNeTourne = !enCours && !(procs.navigation && procs.navigation.en_cours);
    coque.griser('lancer', enCours ? 'Déjà lancée : « Arrêter » d\'abord' : (etat.lancement ? 'Lancement…' : null));
    coque.griser('arreter', rienNeTourne ? 'Rien ne tourne' : null);
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
    etat.navEnCours = navEnCours;
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
    // section 12.15 : robot bloqué (verrou de l'Atelier ou du pont) ou pas en mode marche : le guide refuserait
    const immobile = navEnCours && avecReperage() ? raisonImmobile(d, g) : null;
    etat.immobile = immobile;
    if (immobile && !(g && g.immobilise)) {
      t.titre = TITRES_IMMOBILE.verrou;
      t.detail = 'Le trajet en cours est annulé. « Débloquer », puis « Y aller » pour repartir.';
    }
    // rien ne tourne : pas de guide pour recevoir « Y aller »
    const raisonYAller = !navEnCours ? 'Lancez d\'abord ' + NOM_LANCEMENT + ' (« Lancer »)'
      : (attendreReperage ? 'Repérez d\'abord le robot' : (immobile || (attendreNav2 ? 'Nav2 se prépare…' : null)));
    listeSalles.querySelectorAll('button').forEach((b) => {
      b.disabled = !!raisonYAller;
      b.title = raisonYAller || b.dataset.titre || '';
    });
    coque.griser('y-aller', raisonYAller);
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
      if (nom === 'plan' && plan.cadrageEnAttente) plan.recadrer();
    },
    recadrer: () => plan.recadrer(),
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
