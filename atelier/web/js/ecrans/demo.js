// Écran Démo (Équipe › Démo, vague 6, sections 13.4, 13.5 et 13.7 du plan) : lancer et arrêter la démo d'accueil,
// suivre ce qu'elle fait (état, visite, voix), la mettre en pause, la reprendre, ramener le robot à l'accueil, ses
// statistiques, l'adresse de la borne en grand avec son code QR, et les réglages de demo.yaml (personnalité, voix,
// visiteurs, délais, borne, salles cachées). Module de l'agent Borne et orchestrateur.
//
// Contrat des écrans (section 12.2) : ouvrir(racine, options) → {modifie(), fermer(), commande(nom, valeur), vue(nom),
// recadrer()} ; commandes du ruban : lancer (POST /api/demo/lancer), arreter (POST /api/demo/arreter), borne
// (l'adresse en grand : [data-role=adresse-borne], incrustée sur la vue), reglages (demo.yaml : PUT
// /api/lieux/{id}/demo). L'état vient du champ demo de /ws/etat (dernier /accueil/etat) ; repères :
// [data-role=demo-etat] (data-etat : l'état de la démo, ou arretee), [data-role=demo-statistiques]. La vue Plan 2D
// montre la carte, les salles et le robot. Aucune donnée insérée en HTML ; jamais de fenêtre du navigateur.

import { api, urlLieu } from '../api.js';
import { contexte } from '../contexte.js';
import { abonner } from '../direct.js';
import { mascotte } from '../borne/dessins.js';
import { svgQR } from '../borne/qr.js';
import { preparerEcran, section } from '../coque/ecran.js';
import { ouvrirPanneau } from '../coque/panneau.js';
import * as F from '../formulaire.js';
import { creerPlan, iconeOrientee, ll } from '../plan.js';
import { iconePrincipal, sallePrincipale } from './salles.js';
import { monterReglagesVoix } from '../voix/reglages_voix.js';

export const DELAI_PERIME_S = 3.0;      // /accueil/etat plus vieux : la démo est tenue pour arrêtée
const PERIODE_ETAT_MS = 2000;
const ETIQUETTE_HORS_BORNE = 'hors_borne';
export const TEXTES_ETATS = {
  arretee: 'Démo arrêtée', demarrage: 'Démarrage…', attente: 'Attend un visiteur', salutation: 'Salue un visiteur',
  choix: 'Le visiteur choisit', depart: 'Départ vers la salle', accompagnement: 'Accompagne un visiteur',
  arrivee: 'Arrivé à la salle', retour: 'Retour à l\'accueil', occupe: 'Occupé : autre visite', pause: 'En pause',
};
export const STATISTIQUES = [
  ['visiteurs', 'Visiteurs salués'], ['visites_reussies', 'Visites réussies'], ['visites_abandonnees', 'Abandons'],
  ['echecs', 'Échecs'], ['pauses', 'Pauses'], ['duree_moyenne_s', 'Durée moyenne'],
];
const ACTIONS_ATELIER = [['pause', 'Mettre en pause'], ['reprendre', 'Reprendre'], ['ramener', 'Ramener à l\'accueil']];
const SORTIES = [{ id: 'robot', texte: 'Le robot' }, { id: 'borne', texte: 'La borne' },
  { id: 'robot_tts', texte: 'Unitree (essai)' }];
const SOURCES = [{ id: 'auto', texte: 'Automatique' }, { id: 'camera', texte: 'La caméra' },
  { id: 'lidar', texte: 'Le LiDAR' }, { id: 'borne', texte: 'La borne seule' }];

// La démo d'après /ws/etat : le dernier /accueil/etat s'il a moins de 3 s, sinon null (arrêtée)
export function demoFraiche(d) {
  const e = d && d.demo;
  if (!e || typeof e.age_recu_s !== 'number' || e.age_recu_s > DELAI_PERIME_S || !e.etat) return null;
  return e;
}

export function texteEtat(demo) {
  return TEXTES_ETATS[demo ? demo.etat : 'arretee'] || TEXTES_ETATS.arretee;
}

// Une statistique lisible : la durée en minutes et secondes, les autres telles quelles
export function valeurStatistique(cle, v) {
  if (v === null || v === undefined) return '—';
  if (cle === 'duree_moyenne_s') {
    const s = Math.round(v);
    return s >= 60 ? Math.floor(s / 60) + ' min ' + String(s % 60).padStart(2, '0') + ' s' : s + ' s';
  }
  return String(v);
}

// La meilleure adresse pour une tablette (la première : le Wi-Fi d'abord), ou null
export function adressePrincipale(adresse) {
  return adresse && Array.isArray(adresse.adresses) && adresse.adresses.length ? adresse.adresses[0] : null;
}

function el(balise, classe, texte) {
  return F.el(balise, classe, texte);
}

export function ouvrir(racine, options) {
  const ecran = preparerEcran(racine, options);
  const coque = ecran.coque;
  const lieu = contexte.lieu;
  const etage = contexte.etage;
  const etat = { lancee: false, demo: null, voix: null, adresse: null, salles: [], ferme: false, reglages: null,
    modifie: false, robot: null, avertissements: [], processus: {} };
  let retirerIncrustation = null;
  let minuterie = null;
  let reglagesVoix = null;       // les réglages de la voix (js/voix/reglages_voix.js), dans les réglages de la démo

  // ---------------------------------------------------------------- vue Plan 2D : carte, salles, robot

  ecran.vue.textContent = '';
  const zonePlan = el('div', 'plan');
  zonePlan.setAttribute('data-role', 'plan');
  ecran.vue.appendChild(zonePlan);
  const plan = creerPlan(zonePlan);
  const calqueSalles = L.layerGroup().addTo(plan.carte);
  const calqueRobot = L.layerGroup().addTo(plan.carte);
  let marqueurRobot = null;

  function dessinerSalles() {
    calqueSalles.clearLayers();
    const p = sallePrincipale(etat.salles);
    const visite = etat.demo && etat.demo.visite ? etat.demo.visite.salle : null;
    etat.salles.filter((s) => s.etage === etage).forEach((s) => {
      const cachee = (s.etiquettes || []).indexOf(ETIQUETTE_HORS_BORNE) >= 0;
      const icone = s === p ? iconePrincipal(s.pose.theta)
        : iconeOrientee('salle' + (s.id === visite ? ' demo-visee' : '') + (cachee ? ' demo-cachee' : ''), s.pose.theta);
      const nom = el('span', '', s.nom + (cachee ? ' (cachée de la borne)' : ''));
      L.marker(ll(s.pose.x, s.pose.y), { icon: icone, keyboard: false, interactive: false })
        .bindTooltip(nom, { permanent: true, direction: 'right', offset: [14, 0], className: 'etiquette' })
        .addTo(calqueSalles);
    });
  }

  function dessinerRobot(r) {
    if (!r || typeof r.x !== 'number') {
      if (marqueurRobot) calqueRobot.removeLayer(marqueurRobot);
      marqueurRobot = null;
      return;
    }
    const icone = iconeOrientee('robot-direct' + (r.perimee ? ' perimee' : ''), r.theta || 0);
    if (!marqueurRobot) marqueurRobot = L.marker(ll(r.x, r.y), { icon: icone, interactive: false, zIndexOffset: 1000 }).addTo(calqueRobot);
    else {
      marqueurRobot.setLatLng(ll(r.x, r.y));
      marqueurRobot.setIcon(icone);
    }
  }

  // ---------------------------------------------------------------- panneau

  const panneau = ouvrirPanneau(ecran.panneau, { titre: 'Démo d\'accueil' });
  const z = panneau.corps;
  z.classList.add('panneau-demo');

  // l'état de la démo
  const blocEtat = section(z, null, 'demo');
  const pastille = el('div', 'demo-etat');
  pastille.setAttribute('data-role', 'demo-etat');
  pastille.setAttribute('data-etat', 'arretee');
  const visage = el('div', 'demo-visage');
  const textesEtat = el('div', 'demo-etat-textes');
  const titreEtat = el('strong', 'demo-etat-titre', TEXTES_ETATS.arretee);
  const messageEtat = el('span', 'demo-etat-message', 'Lancez la démo : le robot accueillera les visiteurs, la borne proposera les salles.');
  messageEtat.setAttribute('data-role', 'demo-message');
  textesEtat.appendChild(titreEtat);
  textesEtat.appendChild(messageEtat);
  pastille.appendChild(visage);
  pastille.appendChild(textesEtat);
  blocEtat.appendChild(pastille);
  const lignesVisite = el('p', 'panneau-note demo-visite');
  lignesVisite.setAttribute('data-role', 'demo-visite');
  lignesVisite.hidden = true;
  blocEtat.appendChild(lignesVisite);
  const boutonsDemo = el('div', 'demo-boutons');
  const lancer = F.bouton(boutonsDemo, 'Lancer la démo', () => commande('lancer'), 'bouton bouton-principal bouton-grand');
  lancer.setAttribute('data-role', 'demo-lancer');
  const arreter = F.bouton(boutonsDemo, 'Arrêter la démo', () => commande('arreter'), 'bouton bouton-grand');
  arreter.setAttribute('data-role', 'demo-arreter');
  blocEtat.appendChild(boutonsDemo);
  const noteDehors = F.paragraphe(blocEtat, 'La démo tourne, lancée hors de l\'Atelier (g1-accueil dans un terminal) : '
    + 'arrêtez-la là où elle a été lancée (Ctrl+C).', 'panneau-note');
  noteDehors.hidden = true;
  const boutonsActions = el('div', 'demo-actions');
  const actions = {};
  ACTIONS_ATELIER.forEach((a) => {
    const b = F.bouton(boutonsActions, a[1], () => agir(a[0]), 'bouton');
    b.setAttribute('data-action', a[0]);
    b.hidden = true;
    actions[a[0]] = b;
  });
  blocEtat.appendChild(boutonsActions);
  const avertissements = el('div', 'demo-avertissements');
  avertissements.setAttribute('data-role', 'demo-avertissements');
  blocEtat.appendChild(avertissements);

  // la borne : son adresse, et le code QR en grand
  const blocBorne = section(z, 'La borne visiteur', 'borne');
  const adressePanneau = el('p', 'demo-adresse code', '…');
  adressePanneau.setAttribute('data-role', 'adresse-borne-panneau');
  blocBorne.appendChild(adressePanneau);
  const aideBorne = F.paragraphe(blocBorne, '', 'panneau-note');
  F.bouton(blocBorne, 'Montrer l\'adresse en grand', () => commande('borne'), 'bouton');

  // les statistiques
  const blocStats = section(z, 'Statistiques', 'statistiques');
  const grille = el('dl', 'demo-statistiques');
  grille.setAttribute('data-role', 'demo-statistiques');
  const valeurs = {};
  STATISTIQUES.forEach((s) => {
    const case_ = el('div', 'demo-statistique');
    case_.setAttribute('data-statistique', s[0]);
    const v = el('dd', 'demo-statistique-valeur', '—');
    case_.appendChild(v);
    case_.appendChild(el('dt', 'demo-statistique-libelle', s[1]));
    grille.appendChild(case_);
    valeurs[s[0]] = v;
  });
  blocStats.appendChild(grille);
  const remise = F.bouton(blocStats, 'Remettre à zéro', () => agir('remise_a_zero'), 'bouton bouton-lien');
  remise.setAttribute('data-action', 'remise_a_zero');

  // la voix
  const blocVoix = section(z, 'Voix', 'voix');
  const texteVoix = F.paragraphe(blocVoix, 'La voix démarre avec la démo.', 'panneau-note');
  texteVoix.setAttribute('data-role', 'demo-voix');

  // les réglages (demo.yaml), repliés : la commande Avancé « Réglages de la démo » les ouvre
  const details = el('details', 'bloc-avance demo-reglages');
  details.setAttribute('data-role', 'demo-reglages');
  details.appendChild(el('summary', '', 'Réglages de la démo'));
  const corpsReglages = el('div', 'bloc-avance-corps');
  details.appendChild(corpsReglages);
  z.appendChild(details);

  // ---------------------------------------------------------------- état

  function majEtat() {
    const demo = etat.demo;
    const e = demo ? demo.etat : 'arretee';
    pastille.setAttribute('data-etat', e);
    titreEtat.textContent = texteEtat(demo);
    messageEtat.textContent = demo ? demo.message
      : (etat.lancee ? 'La démo démarre…' : 'Lancez la démo : le robot accueillera les visiteurs, la borne proposera les salles.');
    const humeur = { attente: 'accueil', salutation: 'content', choix: 'accueil', depart: 'marche', accompagnement: 'marche',
      arrivee: 'content', retour: 'marche', occupe: 'occupe', pause: 'pause' }[e] || 'dort';
    if (visage.getAttribute('data-humeur') !== humeur) {
      visage.setAttribute('data-humeur', humeur);
      visage.textContent = '';
      visage.appendChild(mascotte(humeur));
    }
    const v = demo && demo.visite;
    lignesVisite.hidden = !v;
    if (v) {
      lignesVisite.textContent = 'Salle : ' + (v.nom || v.salle)
        + (typeof v.reste_m === 'number' && demo.etat !== 'arrivee' ? ' · encore ' + Math.round(v.reste_m) + ' m' : '');
    }
    // une démo qui tourne sans avoir été lancée par l'Atelier (g1-accueil dans un terminal) : pas de seconde démo
    const dehors = !!demo && !etat.lancee;
    lancer.hidden = etat.lancee || dehors;
    arreter.hidden = !etat.lancee;
    noteDehors.hidden = !dehors;
    coque.griser('lancer', etat.lancee || dehors ? 'La démo tourne déjà' : null);
    coque.griser('arreter', etat.lancee ? null : 'La démo ne tourne pas');
    const possibles = demo && Array.isArray(demo.actions_possibles) ? demo.actions_possibles : [];
    ACTIONS_ATELIER.forEach((a) => { actions[a[0]].hidden = possibles.indexOf(a[0]) < 0; });
    remise.disabled = !demo;
    const s = demo && demo.statistiques ? demo.statistiques : {};
    STATISTIQUES.forEach((x) => { valeurs[x[0]].textContent = demo ? valeurStatistique(x[0], s[x[0]]) : '—'; });
    avertissements.textContent = '';
    etat.avertissements.forEach((a) => avertissements.appendChild(el('p', 'panneau-alerte', a)));
    const voix = etat.voix;
    if (voix && typeof voix.age_recu_s === 'number' && voix.age_recu_s < DELAI_PERIME_S) {
      const parle = voix.en_cours ? 'dit « ' + voix.en_cours.texte + ' »' : 'se tait';
      const sortie = (SORTIES.find((x) => x.id === voix.sortie) || { texte: voix.sortie }).texte;
      texteVoix.textContent = 'Sortie : ' + sortie + '. Le robot ' + parle + ' (' + voix.dites + ' phrases dites'
        + (voix.erreurs ? ', ' + voix.erreurs + ' erreurs' : '') + ').';
    } else {
      texteVoix.textContent = etat.lancee ? 'La voix ne répond pas : la démo continue en silence.'
        : 'La voix démarre avec la démo (sortie choisie dans les réglages).';
    }
    dessinerSalles();
  }

  function recevoir(d) {
    if (etat.ferme) return;
    const demo = demoFraiche(d);
    const avant = JSON.stringify([etat.demo && etat.demo.etat, etat.demo && etat.demo.message, etat.demo && etat.demo.statistiques,
      etat.demo && etat.demo.visite, etat.voix && etat.voix.dites, etat.voix && etat.voix.en_cours]);
    etat.demo = demo;
    etat.voix = d ? d.voix : null;
    dessinerRobot(d ? d.robot : null);
    const apres = JSON.stringify([demo && demo.etat, demo && demo.message, demo && demo.statistiques, demo && demo.visite,
      etat.voix && etat.voix.dites, etat.voix && etat.voix.en_cours]);
    if (avant !== apres) majEtat();
  }

  async function lireEtat() {
    try {
      const r = await api.lire('/api/demo/etat');
      etat.lancee = !!r.lancee;
      etat.avertissements = r.avertissements || [];
      etat.processus = r.processus || {};
      majEtat();
    } catch (e) {
      // le serveur ne répond pas : la barre d'état le dit déjà
    }
  }

  async function lireAdresse() {
    try {
      etat.adresse = await api.lire('/api/borne/adresse');
    } catch (e) {
      etat.adresse = null;
    }
    const a = adressePrincipale(etat.adresse);
    adressePanneau.textContent = a || (etat.adresse ? etat.adresse.locale : '—');
    aideBorne.textContent = etat.adresse ? etat.adresse.message : 'L\'adresse de la borne n\'a pas pu être lue.';
  }

  // ---------------------------------------------------------------- commandes

  async function commande(nom) {
    if (nom === 'lancer') {
      try {
        const r = await api.envoyer('/api/demo/lancer', { lieu: lieu, etage: etage });
        etat.lancee = true;
        coque.message(r.message, 'succes', r.avertissements && r.avertissements.length ? r.avertissements : null);
        (r.avertissements || []).forEach((a) => coque.message(a, 'avertissement'));
      } catch (e) {
        coque.message(e.message, 'erreur');
      }
      lireEtat();
    } else if (nom === 'arreter') {
      try {
        const r = await api.envoyer('/api/demo/arreter', {});
        etat.lancee = false;
        coque.message(r.message, 'info');
      } catch (e) {
        coque.message(e.message, 'erreur');
      }
      lireEtat();
    } else if (nom === 'borne') {
      if (retirerIncrustation) fermerBorne();      // la commande « Borne » une seconde fois : on referme
      else montrerBorne();
    } else if (nom === 'reglages') {
      details.open = true;
      details.scrollIntoView({ block: 'start' });
    }
  }

  async function agir(action) {
    try {
      const r = await api.envoyer('/api/demo/commande', { action: action });
      coque.message(action === 'remise_a_zero' ? 'Statistiques remises à zéro.' : r.texte, 'succes');
    } catch (e) {
      coque.message(e.message, 'avertissement');
    }
  }

  // ---------------------------------------------------------------- l'adresse de la borne, en grand

  function montrerBorne() {
    if (retirerIncrustation) retirerIncrustation();
    const carte = el('div', 'demo-borne');
    carte.setAttribute('data-role', 'demo-borne');
    // Échap la ferme : la coque n'envoie l'ARRÊT que si le robot bouge (data-ferme-echap, assemblage de la vague 6)
    carte.setAttribute('data-ferme-echap', '');
    const tete = el('div', 'demo-borne-tete');
    tete.appendChild(el('h2', 'demo-borne-titre', 'La borne visiteur'));
    const fermer = F.bouton(tete, '✗', () => fermerBorne(), 'bouton bouton-icone demo-borne-fermer');
    fermer.setAttribute('data-role', 'fermer-borne');
    fermer.title = 'Fermer (✗ ou Échap ; si le robot roule, Échap l\'arrête aussi)';
    fermer.setAttribute('aria-label', 'Fermer');
    carte.appendChild(tete);
    const corps = el('div', 'demo-borne-corps');
    carte.appendChild(corps);
    const remplir = () => {
      corps.textContent = '';
      const a = adressePrincipale(etat.adresse);
      if (a) {
        const qr = el('div', 'demo-qr');
        qr.setAttribute('data-role', 'qr-borne');
        try {
          qr.appendChild(svgQR(a, { titre: 'Code QR de l\'adresse de la borne' }));
        } catch (e) {
          qr.hidden = true;
        }
        corps.appendChild(qr);
      }
      const textes = el('div', 'demo-borne-textes');
      textes.appendChild(el('p', 'demo-borne-consigne', a ? 'Sur la tablette ou le téléphone du hall, connecté au même Wi-Fi, ouvrez :'
        : 'La borne n\'est pas encore joignable depuis une tablette.'));
      const adresse = el('p', 'demo-borne-adresse', a || (etat.adresse ? etat.adresse.locale : '…'));
      adresse.setAttribute('data-role', 'adresse-borne');
      textes.appendChild(adresse);
      if (etat.adresse && etat.adresse.adresses && etat.adresse.adresses.length > 1) {
        textes.appendChild(el('p', 'panneau-note', 'Autres adresses du PC : ' + etat.adresse.adresses.slice(1).join(', ')));
      }
      if (!a && etat.adresse) textes.appendChild(el('p', 'demo-borne-message', etat.adresse.message));
      if (etat.adresse && etat.adresse.locale) {
        const lien = el('a', 'bouton-lien', 'Ouvrir la borne sur ce PC');
        lien.href = etat.adresse.locale;
        lien.target = '_blank';
        lien.rel = 'noopener';
        textes.appendChild(lien);
      }
      corps.appendChild(textes);
    };
    remplir();
    lireAdresse().then(() => { if (carte.isConnected) remplir(); });
    const retirer = coque.incruster(carte);
    ecran.vue.classList.add('demo-borne-ouverte');       // les boutons du plan ne passent pas par-dessus
    retirerIncrustation = () => {
      retirer();
      ecran.vue.classList.remove('demo-borne-ouverte');
      coque.activer(null);                                // « Borne » n'est plus enfoncée dans le ruban
    };
    coque.activer('borne');
    document.addEventListener('keydown', echap, true);
  }

  function echap(ev) {
    if (ev.key !== 'Escape' || !retirerIncrustation) return;
    ev.stopPropagation();
    ev.preventDefault();
    fermerBorne();
  }

  function fermerBorne() {
    document.removeEventListener('keydown', echap, true);
    if (retirerIncrustation) retirerIncrustation();
    retirerIncrustation = null;
  }

  // ---------------------------------------------------------------- réglages (demo.yaml) et salles cachées

  async function chargerReglages() {
    corpsReglages.textContent = '';
    let reglages;
    let personnalites = [];
    try {
      reglages = await api.lire(urlLieu(lieu) + '/demo');
    } catch (e) {
      F.paragraphe(corpsReglages, e.message, 'panneau-alerte');
      return;
    }
    try {
      const p = await api.lire(urlLieu(lieu) + '/personnalites');
      personnalites = p.personnalites || [];
    } catch (e) {
      personnalites = [];
    }
    const r = JSON.parse(JSON.stringify(reglages));
    const changer = () => { etat.modifie = true; enregistrer.disabled = false; };
    F.listeDeroulante(corpsReglages, 'Personnalité', r.personnalite || '', [{ id: '', texte: 'Celle qui est active' }]
      .concat(personnalites.map((p) => ({ id: p.id, texte: p.nom }))), (v) => {
      if (v) r.personnalite = v;
      else delete r.personnalite;
      changer();
    });
    // la voix (assemblage de la vague 6) : le composant de l'agent Voix (sortie, voix, volume, vitesse ; démarrer
    // la voix seule, essayer une phrase) ; ses valeurs sont celles de demo.yaml, enregistrées avec le reste
    corpsReglages.appendChild(el('h4', 'demo-sous-titre', 'La voix du robot'));
    if (reglagesVoix) reglagesVoix.fermer();
    reglagesVoix = monterReglagesVoix(corpsReglages, { lieu: lieu, valeurs: r.voix,
      surChange: (v) => { r.voix = v; changer(); }, message: (texte, genre) => coque.message(texte, genre) });
    corpsReglages.appendChild(el('h4', 'demo-sous-titre', 'Visiteurs et borne'));
    F.listeDeroulante(corpsReglages, 'Visiteurs vus par', r.visiteurs.source, SOURCES, (v) => { r.visiteurs.source = v; changer(); });
    F.champNombre(corpsReglages, 'Salué à moins de', r.visiteurs.distance_m, { min: 0.3, max: 5, pas: 0.1, decimales: 1, unite: 'm' },
      (v) => { r.visiteurs.distance_m = v; changer(); });
    F.champNombre(corpsReglages, 'Temps pour choisir', r.delais.choix_s, { min: 5, max: 600, pas: 5, decimales: 0, unite: 's' },
      (v) => { r.delais.choix_s = v; changer(); });
    F.champNombre(corpsReglages, 'Pause entre deux visiteurs', r.delais.entre_visiteurs_s, { min: 0, max: 600, pas: 1, decimales: 0, unite: 's' },
      (v) => { r.delais.entre_visiteurs_s = v; changer(); });
    F.caseACocher(corpsReglages, 'Accompagner le visiteur (le robot l\'attend s\'il traîne)', r.accompagner, (v) => { r.accompagner = v; changer(); });
    F.caseACocher(corpsReglages, 'Retour seul à l\'accueil après chaque visite', r.retour, (v) => { r.retour = v; changer(); });
    F.champTexte(corpsReglages, 'Titre de la borne', r.borne.titre, (v) => { r.borne.titre = v.trim() || 'Bonjour ! Où voulez-vous aller ?'; changer(); });
    F.listeDeroulante(corpsReglages, 'Langue de la borne', r.borne.langue || 'fr', [{ id: 'fr', texte: 'Français' },
      { id: 'en', texte: 'Anglais' }], (v) => { r.borne.langue = v; changer(); });
    const code = F.champTexte(corpsReglages, 'Code opérateur', r.borne.code_operateur || '', (v) => {
      if (v.trim()) r.borne.code_operateur = v.trim();
      else delete r.borne.code_operateur;
      changer();
    }, { indice: '4 à 8 chiffres, ou vide' });
    code.setAttribute('inputmode', 'numeric');
    code.setAttribute('data-role', 'code-operateur');
    F.paragraphe(corpsReglages, 'Le code opérateur ouvre, sur la borne, la pause, la reprise et le retour à l\'accueil. '
      + 'Ce n\'est pas un mot de passe : il évite qu\'un visiteur mette la démo en pause.', 'panneau-note');
    // les salles proposées par la borne (étiquette hors_borne de salles.yaml)
    const cases = {};
    corpsReglages.appendChild(el('h4', 'demo-sous-titre', 'Salles proposées par la borne'));
    const principal = sallePrincipale(etat.salles);
    etat.salles.filter((s) => s !== principal).forEach((s) => {
      const c = F.caseACocher(corpsReglages, s.nom, (s.etiquettes || []).indexOf(ETIQUETTE_HORS_BORNE) < 0, () => changer());
      c.setAttribute('data-salle-borne', s.id);
      cases[s.id] = c;
    });
    const enregistrer = F.bouton(corpsReglages, 'Enregistrer les réglages', async () => {
      try {
        const reponse = await api.ecrire(urlLieu(lieu) + '/demo', r);
        let sallesChangees = false;
        const salles = etat.salles.map((s) => {
          const copie = JSON.parse(JSON.stringify(s));
          const montree = cases[s.id] ? cases[s.id].checked : true;
          const etiquettes = (copie.etiquettes || []).filter((x) => x !== ETIQUETTE_HORS_BORNE);
          if (!montree) etiquettes.push(ETIQUETTE_HORS_BORNE);
          if (JSON.stringify(etiquettes) !== JSON.stringify(copie.etiquettes || [])) sallesChangees = true;
          if (etiquettes.length) copie.etiquettes = etiquettes;
          else delete copie.etiquettes;
          return copie;
        });
        if (sallesChangees) {
          await api.ecrire(urlLieu(lieu) + '/salles', salles);
          etat.salles = await api.lire(urlLieu(lieu) + '/salles');
          coque.lieuModifie('salles');
        }
        etat.modifie = false;
        enregistrer.disabled = true;
        const notes = reponse.rapport && reponse.rapport.avertissements && reponse.rapport.avertissements.length
          ? reponse.rapport.avertissements : null;
        coque.message('Réglages de la démo enregistrés' + (etat.lancee ? ' : relancez la démo pour qu\'elle les prenne.' : '.'),
          'succes', notes);
        dessinerSalles();
      } catch (e) {
        coque.message(e.message, 'erreur', e.erreurs && e.erreurs.length ? e.erreurs : null);
      }
    }, 'bouton bouton-principal');
    enregistrer.setAttribute('data-role', 'demo-enregistrer');
    enregistrer.disabled = true;
  }

  // ---------------------------------------------------------------- chargement

  async function charger() {
    try {
      await plan.afficherFond(lieu, etage);
      etat.salles = await api.lire(urlLieu(lieu) + '/salles');
    } catch (e) {
      coque.message(e.message, 'erreur');
    }
    if (etat.ferme) return;
    dessinerSalles();
    chargerReglages();
    lireAdresse();
    await lireEtat();
    minuterie = setInterval(lireEtat, PERIODE_ETAT_MS);
    etat.desabonner = abonner(recevoir);
  }
  majEtat();
  ecran.vue.classList.add('chargement');
  const pret = charger().finally(() => ecran.vue.classList.remove('chargement'));
  if (ecran.commande) pret.then(() => commande(ecran.commande));

  return {
    modifie: () => etat.modifie,
    commande: (nom) => pret.then(() => commande(nom)),
    vue: (nom) => {
      plan.carte.invalidateSize();
      if (nom === 'plan' && plan.cadrageEnAttente) plan.recadrer();
    },
    recadrer: () => plan.recadrer(),
    fermer: () => {
      etat.ferme = true;
      if (minuterie) clearInterval(minuterie);
      if (etat.desabonner) etat.desabonner();
      if (reglagesVoix) reglagesVoix.fermer();
      reglagesVoix = null;
      fermerBorne();
      plan.detruire();
    },
  };
}
