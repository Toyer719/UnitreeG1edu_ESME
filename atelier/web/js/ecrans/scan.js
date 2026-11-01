// Écran de scan (vague 5, section 12.5 du plan) : scanner un étage avec le LiDAR, comme « 3D LiDAR Mapping »
// d'Unitree Explore. Plein écran sombre pendant le scan : le nuage en direct coloré par la hauteur, le trajet
// et le robot, un gros bouton Scan puis Fin, les compteurs (durée, distance, points). Après « Fin » : la
// fabrication de la carte (progression), le nuage final, la carte 2D, puis « Utiliser cette carte ».
// Plus de reconnaissance des meubles ni de revue (décision S2) : la carte du scan sert telle quelle.
//   - dans la coque : ouvrir(racine, options) ; options.mode : simu (Simulation › Avancé › Scan simulé),
//     reel (Réel › Scanner, le vrai robot) ou repetition (Réel sans robot) ; réglages, résumé et scans
//     précédents dans options.panneau ; commandes du ruban : scan, fin, utiliser, simule ;
//     options.coque.pleinEcran(vrai) pendant le scan ; options.coque.confirmer pour les confirmations ;
//   - sans la coque (ancien app.js) : ouvrir(racine) seul, avec le choix du mode dans l'écran.
// API : sections 9.7 et 12.4 du plan (/api/scan/…, /api/scan/nuage). Flèches du robot simulé : teleop.js.

import { api } from '../api.js';
import { contexte, etageCourant, memoriser, rechargerLieu, souvenir } from '../contexte.js';
import { demanderConfirmation } from '../coque/confirmation.js';
import * as F from '../formulaire.js';
import { nb } from '../geometrie.js';
import { afficherErreur, afficherMessage, afficherRapport } from '../messages.js';
import { Nuage3D, telechargerNuage } from '../nuage3d.js';
import { Teleop } from '../teleop.js';

const PERIODE_ETAT = 1000;          // ms : GET /api/scan/etat
const PERIODE_DIRECT = 2000;        // ms : apercu.json et le nuage en direct (réécrits toutes les 2 s)

// Étapes après « Fin » (vague 5) : la barre de progression
export const ETAPES = [
  { id: 'arret', texte: 'Fin du scan, enregistrement fermé' },
  { id: 'carte_3d', texte: 'Nuage 3D : tous les nuages assemblés, passants retirés' },
  { id: 'carte_2d', texte: 'Carte 2D : les obstacles au-dessus du sol' },
  { id: 'nuage', texte: 'Nuage de la carte 3D' },
];
const NOMS_ETAPES = {
  preparation: 'Préparation', enregistrement: 'Scan en cours', arret: 'Fin du scan', carte_3d: 'Nuage 3D',
  carte_2d: 'Carte 2D', nuage: 'Nuage de la carte 3D', fini: 'Fini',
  reconnaissance: 'Reconnaissance (ancien scan)', monde: 'Monde (ancien scan)',
};
const NOMS_ETATS = {
  en_cours: 'Scan en cours', arret_en_cours: 'Fin du scan', traitement: 'Fabrication de la carte', termine: 'Terminé',
  echec: 'Échec',
};

function enc(v) {
  return encodeURIComponent(v);
}

function urlScan(quoi, lieu, session) {
  return '/api/scan/' + quoi + '?lieu=' + enc(lieu) + (session ? '&session=' + enc(session) : '');
}

function urlSession(lieu, session, quoi) {
  return '/api/scan/sessions/' + enc(session) + '/' + quoi + '?lieu=' + enc(lieu);
}

// GET qui rend null au lieu d'une erreur 404 (fichier pas encore écrit)
async function lireOuNull(url) {
  try {
    return await api.lire(url);
  } catch (e) {
    if (e.statut === 404) return null;
    throw e;
  }
}

export function texteDuree(secondes) {
  if (secondes === null || secondes === undefined || isNaN(secondes)) return '—';
  const s = Math.max(0, Math.floor(secondes));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  const deux = (x) => (x < 10 ? '0' : '') + x;
  return h ? h + ' h ' + deux(m) + ' min' : m + ':' + deux(r);
}

function entier(n) {
  return n === null || n === undefined ? '—' : Math.round(n).toLocaleString('fr-FR');
}

function dateCourte(iso) {
  const t = Date.parse(iso);
  if (isNaN(t)) return iso || '—';
  return new Date(t).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function texteMode(s) {
  if (s.mode === 'simu') return 'Simulation';
  return s.repetition ? 'Répétition sans robot' : 'Vrai robot';
}

function simule(s) {
  return s.mode === 'simu' || !!s.repetition;
}

function dureeSession(s) {
  const debut = Date.parse(s.debut);
  if (isNaN(debut)) return s.statistiques ? s.statistiques.duree_s : null;
  const fin = s.fin ? Date.parse(s.fin) : Date.now();
  return (fin - debut) / 1000;
}

// Réglages du scan d'après le mode de la coque (fixe), ou les choix gardés dans le navigateur (sans coque)
export function reglagesDuMode(mode) {
  if (mode === 'simu') return { mode: 'simu', repetition: false, fixe: true };
  if (mode === 'reel') return { mode: 'robot', repetition: false, fixe: true };
  if (mode === 'repetition') return { mode: 'robot', repetition: true, fixe: true };
  return { mode: souvenir('scan.mode') === 'robot' ? 'robot' : 'simu', repetition: souvenir('scan.repetition') === '1',
    fixe: false };
}

function el(parent, balise, classe, texte, role) {
  const e = F.el(balise, classe, texte);
  if (role) e.dataset.role = role;
  if (parent) parent.appendChild(e);
  return e;
}

export function ouvrir(racine, options) {
  const o = options || {};
  const coque = o.coque || null;
  const lieu = contexte.lieu;
  const etage = contexte.etage;
  const infoEtage = etageCourant();
  const reglages = reglagesDuMode(o.mode);
  reglages.explorer = souvenir('scan.explorer') === '1';
  reglages.nom = '';
  const etat = { suivie: null, ferme: false, minuteur: null, minuteurDirect: null, vue: null, cleVue: null, session: null,
    cleHistorique: null, erreurEtat: null, dateNuage: null, enCours: false, pleinEcran: false, teleop: null,
    nuageFinal: null, carteFinale: null, nuageEtage: false };

  // ------------------------------------------------------------ la vue sombre (dans racine)
  racine.textContent = '';
  racine.classList.add('scan-racine');
  const ecran = el(racine, 'div', 'scan-ecran', null, 'scan-ecran');
  const zoneVue = el(ecran, 'div', 'scan-vue', null, 'scan-vue3d');
  const nuage = new Nuage3D(zoneVue, { nomGlobal: 'scanNuage3d' });
  const image2d = el(ecran, 'img', 'scan-image2d', null, 'scan-image2d');
  image2d.alt = 'Vue de dessus du scan';
  image2d.hidden = true;
  const haut = el(ecran, 'div', 'scan-haut');
  const titre = el(haut, 'div', 'scan-titre', null, 'scan-titre');
  const compteurs = el(haut, 'div', 'scan-compteurs', null, 'scan-compteurs');
  const valeurs = {};
  [['duree', 'Durée'], ['distance', 'Distance'], ['points', 'Points mesurés'], ['nuages', 'Nuages']].forEach((c) => {
    const b = el(compteurs, 'div', 'scan-compteur');
    b.dataset.compteur = c[0];
    el(b, 'span', 'scan-compteur-valeur', '—');
    el(b, 'span', 'scan-compteur-libelle', c[1]);
    valeurs[c[0]] = b.firstChild;
  });
  const outilsVue = el(ecran, 'div', 'scan-outils-vue');
  const boutonOutil = (texte, aide, action) => {
    const b = el(outilsVue, 'button', 'scan-outil', texte);
    b.type = 'button';
    b.title = aide;
    b.addEventListener('click', action);
    return b;
  };
  // une barre de vues comme celle de la carte 3D (Dessus, Iso, Suivre, plafond, taille des points)
  boutonOutil('Dessus', 'Regarder l\'étage de dessus', () => nuage.vue('dessus'));
  boutonOutil('Iso', 'Regarder l\'étage en biais', () => nuage.vue('iso'));
  const boutonSuivre = boutonOutil('Suivre', 'La vue suit le robot', () => nuage.suivre(true));
  boutonSuivre.dataset.role = 'scan-suivre';
  const casePlafond = el(outilsVue, 'label', 'scan-outil scan-case');
  const entreePlafond = el(casePlafond, 'input');
  entreePlafond.type = 'checkbox';
  entreePlafond.dataset.role = 'scan-plafond';
  casePlafond.appendChild(document.createTextNode(' Plafond'));
  casePlafond.title = 'Montrer aussi les points au-dessus de 2,2 m';
  entreePlafond.addEventListener('change', () => nuage.plafond(entreePlafond.checked));
  const ligneTaille = el(outilsVue, 'label', 'scan-outil scan-taille');
  ligneTaille.title = 'Taille des points';
  ligneTaille.appendChild(document.createTextNode('Points '));
  const curseurTaille = el(ligneTaille, 'input');
  curseurTaille.type = 'range';
  curseurTaille.min = '0.4';
  curseurTaille.max = '2.5';
  curseurTaille.step = '0.1';
  curseurTaille.value = '1';
  curseurTaille.dataset.role = 'scan-taille-points';
  curseurTaille.setAttribute('aria-label', 'Taille des points');
  curseurTaille.addEventListener('input', () => nuage.facteurTaille(curseurTaille.value));
  const message = el(ecran, 'p', 'scan-message', '', 'scan-message');
  const teleopZone = el(ecran, 'div', 'scan-teleop', null, 'scan-teleop');
  teleopZone.hidden = true;
  // la carte de progression (après « Fin »)
  const progression = el(ecran, 'section', 'scan-progression', null, 'scan-progression');
  progression.hidden = true;
  el(progression, 'h2', 'scan-progression-titre', 'Fabrication de la carte');
  const barreFond = el(progression, 'div', 'scan-progression-fond');
  barreFond.setAttribute('role', 'progressbar');
  barreFond.setAttribute('aria-valuemin', '0');
  barreFond.setAttribute('aria-valuemax', '100');
  barreFond.setAttribute('aria-label', 'Avancement de la fabrication de la carte');
  const barre = el(barreFond, 'div', 'scan-progression-barre', null, 'scan-progression-barre');
  const pourcent = el(progression, 'p', 'scan-progression-texte', '', 'scan-progression-texte');
  const listeEtapes = el(progression, 'ol', 'scan-etapes');
  const lignesEtapes = ETAPES.map((e) => {
    const li = el(listeEtapes, 'li', 'scan-etape', e.texte);
    li.dataset.etape = e.id;
    return li;
  });
  // les gros boutons, en bas au milieu
  const bas = el(ecran, 'div', 'scan-bas');
  const boutonScan = el(bas, 'button', 'scan-rond scan-rond-scan', 'Scan', 'scan-lancer');
  boutonScan.type = 'button';
  boutonScan.title = 'Commencer le scan de l\'étage';
  const boutonFin = el(bas, 'button', 'scan-rond scan-rond-fin', 'Fin', 'scan-fin');
  boutonFin.type = 'button';
  boutonFin.title = 'Arrêter le scan ; la carte se fabrique toute seule';
  const boutonUtiliser = el(bas, 'button', 'scan-bouton-utiliser', 'Utiliser cette carte', 'scan-utiliser');
  boutonUtiliser.type = 'button';
  boutonUtiliser.title = 'Cette carte devient celle de l\'étage, avec son nuage 3D et sa simulation';
  const boutonNouveau = el(bas, 'button', 'scan-bouton-nouveau', 'Nouveau scan', 'scan-nouveau');
  boutonNouveau.type = 'button';
  const boutonTerminer = el(bas, 'button', 'scan-bouton-nouveau', 'Terminer ce scan', 'scan-terminer');
  boutonTerminer.type = 'button';
  boutonTerminer.title = 'Le programme du scan s\'est arrêté : le clore, et fabriquer la carte s\'il a été enregistré';

  // ------------------------------------------------------------ le panneau (réglages, résumé, scans précédents)
  let panneau = o.panneau || null;
  if (!panneau) {
    panneau = el(racine, 'aside', 'scan-panneau-integre');
    racine.classList.add('scan-sans-coque');
  }
  panneau.textContent = '';
  const blocReglages = el(panneau, 'section', 'scan-bloc', null, 'scan-reglages');
  const blocResume = el(panneau, 'section', 'scan-bloc', null, 'scan-resume');
  const blocHistorique = el(panneau, 'section', 'scan-bloc', null, 'scan-historique');
  el(blocHistorique, 'h3', 'scan-bloc-titre', 'Scans précédents');
  const listeHistorique = el(blocHistorique, 'div', 'scan-liste-sessions', null, 'historique');

  titre.textContent = 'Scan de l\'étage « ' + (infoEtage ? infoEtage.nom : etage) + ' »';

  function dire(texte, genre) {
    if (coque && coque.message) coque.message(texte, genre || 'info');
    else afficherMessage(texte, genre === 'erreur' ? 'erreur' : (genre || 'info'));
  }

  function confirmer(texte, opts) {
    if (coque && coque.confirmer) return coque.confirmer(texte, opts || {});
    return demanderConfirmation(texte, opts || {});
  }

  function pleinEcran(oui) {
    if (etat.pleinEcran === oui) return;
    etat.pleinEcran = oui;
    ecran.classList.toggle('scan-plein-ecran', oui);
    if (coque && coque.pleinEcran) {
      try {
        coque.pleinEcran(oui);
      } catch (e) {
        console.error(e);
      }
    }
    setTimeout(() => nuage.redimensionner(), 50);
  }

  // ------------------------------------------------------------ réglages avant le scan
  function majReglages() {
    blocReglages.textContent = '';
    el(blocReglages, 'h3', 'scan-bloc-titre', 'Avant le scan');
    const robotReel = reglages.mode === 'robot' && !reglages.repetition;
    const avecSimulation = !robotReel;
    if (!reglages.fixe) {
      const modes = el(blocReglages, 'div', 'scan-modes');
      modes.setAttribute('role', 'radiogroup');
      modes.setAttribute('aria-label', 'Qui scanne ?');
      [['simu', 'Simulation', 'Le robot simulé scanne le monde dessiné.'],
        ['robot', 'Robot', 'Le vrai G1 scanne le bâtiment.']].forEach((m) => {
        const b = el(modes, 'button', 'scan-mode', m[1]);
        b.type = 'button';
        b.dataset.mode = m[0];
        b.title = m[2];
        b.setAttribute('role', 'radio');
        b.setAttribute('aria-checked', reglages.mode === m[0] ? 'true' : 'false');
        b.classList.toggle('actif', reglages.mode === m[0]);
        b.addEventListener('click', () => {
          reglages.mode = m[0];
          memoriser('scan.mode', m[0]);
          majReglages();
        });
      });
      if (reglages.mode === 'robot') {
        F.caseACocher(blocReglages, 'Répétition sans robot', reglages.repetition, (v) => {
          reglages.repetition = v;
          memoriser('scan.repetition', v ? '1' : '0');
          majReglages();
        });
      }
    } else {
      el(blocReglages, 'p', 'scan-mode-fixe', reglages.mode === 'simu' ? 'Le robot simulé scanne le monde dessiné de l\'étage.'
        : (reglages.repetition ? 'Répétition sans robot : tout comme avec le vrai robot, sur cet ordinateur.'
          : 'Le vrai G1 scanne le bâtiment : promenez-le lentement partout, à la télécommande.'));
    }
    if (robotReel) {
      const l = el(blocReglages, 'ol', 'scan-consignes');
      ['Câble Ethernet entre le PC et le robot (le scan ne passe pas par le Wi-Fi).',
        'Dans un terminal : source ~/robot-g1/setup/robot.sh',
        'Robot posé au point de départ (l\'accueil), puis « Scan ».',
        'Marchez lentement, virages doux, personne entre le robot et les murs ; revenez au départ, puis « Fin ».',
      ].forEach((t) => el(l, 'li', '', t));
    }
    if (avecSimulation) {
      F.caseACocher(blocReglages, 'Exploration automatique (le robot suit seul les couloirs)', reglages.explorer, (v) => {
        reglages.explorer = v;
        memoriser('scan.explorer', v ? '1' : '0');
      });
      if (infoEtage && infoEtage.a_sdf === false) {
        el(blocReglages, 'p', 'scan-alerte', 'Cet étage n\'a pas encore de monde Gazebo : fabriquez d\'abord la carte (Dessiner).');
      }
    }
    F.champTexte(blocReglages, 'Nom du scan', reglages.nom, (v) => { reglages.nom = v.trim(); },
      { indice: 'facultatif, ex. Rez-de-chaussée, aile nord' });
  }

  // ------------------------------------------------------------ compteurs, vues, boutons
  function majCompteurs(s, stats) {
    const st = stats || (s && s.statistiques) || {};
    valeurs.duree.textContent = s ? texteDuree(s.etat === 'en_cours' ? dureeSession(s) : st.duree_s) : '—';
    valeurs.distance.textContent = st.distance_m !== undefined ? nb(st.distance_m, 1) + ' m' : '—';
    valeurs.points.textContent = entier(st.points);
    // le résultat : le même nombre de nuages que le résumé (ceux relus pour fabriquer la carte)
    const relus = s && etat.nuagesRelus && etat.nuagesRelus.session === s.id ? etat.nuagesRelus.nombre : null;
    valeurs.nuages.textContent = entier(relus !== null && s.etat === 'termine' ? relus : st.nuages);
  }

  function vueDe(s) {
    if (!s) return 'choix';
    if (s.interrompue) return 'interrompu';
    if (s.etat === 'en_cours') return 'direct';
    if (s.etat === 'arret_en_cours' || s.etat === 'traitement') return 'traitement';
    if (s.etat === 'termine') return 'resultat';
    return 'echec';
  }

  function montrer(id, s) {
    ecran.dataset.vue = id;
    boutonScan.hidden = id !== 'choix';
    boutonFin.hidden = id !== 'direct';
    boutonUtiliser.hidden = id !== 'resultat';
    boutonNouveau.hidden = ['resultat', 'echec', 'interrompu'].indexOf(id) < 0;
    boutonTerminer.hidden = id !== 'interrompu';
    progression.hidden = id !== 'traitement';
    blocReglages.hidden = id !== 'choix';
    compteurs.hidden = id === 'choix';
    outilsVue.hidden = !nuage.ok;
    const teleop = id === 'direct' && s && simule(s) && !s.explorer;
    teleopZone.hidden = !teleop;
    if (teleop && !etat.teleop) {
      etat.teleop = new Teleop(teleopZone);
      etat.teleop.activer();
    } else if (!teleop && etat.teleop) {
      etat.teleop.detruire();
      etat.teleop = null;
      teleopZone.textContent = '';
    }
    pleinEcran(id === 'direct' || id === 'traitement');
  }

  function texteMessage(s) {
    if (!s) {
      const avant = etat.nuageEtage ? 'Le nuage 3D actuel de l\'étage. ' : '';
      return avant + (reglages.mode === 'simu' || reglages.repetition
        ? 'Appuyez sur « Scan » : le robot simulé démarre, et la carte se construit en direct.'
        : 'Appuyez sur « Scan », puis promenez le robot lentement dans tout l\'étage.');
    }
    // un scan déjà utilisé : son message de fin (« …, puis Utiliser cette carte ») ne vaut plus (recette de la
    // vague 5 : il contredisait « Déjà utilisée » du résumé)
    if (s.etat === 'termine' && s.adoption) {
      return 'Ce scan est déjà la carte de l\'étage (utilisé le ' + dateCourte(s.adoption.quand)
        + '). « Nouveau scan » pour en refaire un.';
    }
    return s.message || '';
  }

  // ------------------------------------------------------------ suivi de l'état (chaque seconde)
  function recevoir(e) {
    etat.erreurEtat = null;
    let s = e.session;
    if (!etat.suivie && e.actif && s) etat.suivie = s.id;     // scan lancé ailleurs, ou avant de recharger la page
    if (!etat.suivie || !s || s.id !== etat.suivie) s = null;
    const id = vueDe(s);
    // la vue est refaite quand elle change, ou quand la session change (autre scan, ou tout juste utilisé)
    const cleVue = id + '|' + (s ? s.id + (s.adoption ? '|utilise' : '') : '');
    etat.session = s;
    if (cleVue !== etat.cleVue) {
      etat.cleVue = cleVue;
      etat.vue = id;
      montrer(id, s);
      entrerDans(id, s);
    }
    majVue(s);
    const cle = s ? s.id + s.etat + (s.adoption ? 'a' : '') : '';
    if (cle !== etat.cleHistorique) {
      etat.cleHistorique = cle;
      majHistorique();
    }
  }

  function majVue(s) {
    message.textContent = texteMessage(s);
    majCompteurs(s);
    if (s && etat.vue === 'traitement') {
      const p = Math.max(0, Math.min(100, s.progression || 0));
      barre.style.width = p + '%';
      barreFond.setAttribute('aria-valuenow', String(p));
      pourcent.textContent = p + ' % · ' + (s.etat === 'arret_en_cours' ? 'Fin du scan' : (NOMS_ETAPES[s.etape] || s.etape));
      const rang = ETAPES.findIndex((x) => x.id === (s.etat === 'arret_en_cours' ? 'arret' : s.etape));
      lignesEtapes.forEach((li, i) => {
        li.classList.toggle('fait', i < rang);
        li.classList.toggle('en-cours', i === rang);
      });
    }
    let t = 'Scan de l\'étage « ' + (infoEtage ? infoEtage.nom : etage) + ' »';
    if (s) t += ' · ' + (NOMS_ETATS[s.etat] || s.etat) + ' · ' + texteMode(s);
    titre.textContent = t;
  }

  function entrerDans(id, s) {
    clearTimeout(etat.minuteurDirect);
    etat.dateNuage = null;
    blocResume.textContent = '';
    image2d.hidden = true;
    if (id === 'choix') {
      majReglages();
      chargerNuageEtage();
    } else if (id === 'direct' || id === 'traitement') {
      if (id === 'direct') {
        nuage.afficherPoints(new Float32Array(0), null);     // le nuage de l'étage laisse la place au scan
        nuage.recommencer(16);
      }
      nuage.suivre(true);
      majDirect();
    } else if (id === 'resultat') {
      chargerResultat(s);
    } else if (id === 'echec') {
      el(blocResume, 'h3', 'scan-bloc-titre', 'Le scan a échoué');
      el(blocResume, 'p', 'scan-alerte', s.message);
      el(blocResume, 'p', 'scan-note', 'Étape : ' + (NOMS_ETAPES[s.etape] || s.etape) + '. ' + texteMode(s)
        + ', commencé le ' + dateCourte(s.debut) + '.');
      if (s.journal) el(blocResume, 'p', 'scan-note scan-code', 'Journal : ' + s.journal);
    } else if (id === 'interrompu') {
      el(blocResume, 'h3', 'scan-bloc-titre', 'Le scan s\'est arrêté sans prévenir');
      el(blocResume, 'p', 'scan-note', 'Le programme du scan « ' + s.nom + ' » ne tourne plus. « Terminer ce scan » '
        + 'le clôt : s\'il a été enregistré, la carte est fabriquée ; sinon, il faut recommencer.');
    }
  }

  async function interroger() {
    if (etat.ferme) return;
    try {
      const e = await api.lire(urlScan('etat', lieu, etat.suivie));
      if (!etat.ferme) recevoir(e);
    } catch (err) {
      if (err.statut === 404 && etat.suivie) {
        etat.suivie = null;          // la session a disparu (dossier supprimé)
      } else if (etat.erreurEtat !== err.message) {
        etat.erreurEtat = err.message;
        message.textContent = err.message;
      }
    }
    if (!etat.ferme) etat.minuteur = setTimeout(interroger, PERIODE_ETAT);
  }

  function suivre(session) {
    // une autre session : l'ancien message (« Pas encore de carte… ») ne reste pas affiché
    if (session !== etat.suivie && coque && coque.effacerMessage) coque.effacerMessage();
    etat.suivie = session;
    clearTimeout(etat.minuteur);
    interroger();
  }

  // ------------------------------------------------------------ nuages
  async function chargerNuageEtage() {
    try {
      await nuage.chargerBinaire('/api/lieux/' + enc(lieu) + '/etages/' + enc(etage) + '/nuage');
      etat.nuageEtage = true;
      if (!etat.ferme && etat.vue === 'choix') message.textContent = texteMessage(null);
    } catch (e) {
      if (e.statut !== 404) console.error(e);
      etat.nuageEtage = false;
      nuage.afficherPoints(new Float32Array(0), { xmin: -5, ymin: -5, xmax: 5, ymax: 5 });
      nuage.cadrer({ xmin: -5, ymin: -5, xmax: 5, ymax: 5 });
    }
    nuage.afficherTrajet([]);
    nuage.afficherRobot(null);
  }

  // Pendant le scan et la fabrication de la carte : apercu.json (trajet, robot, chiffres) et le nuage en direct
  async function majDirect() {
    const s = etat.session;
    if (etat.ferme || !s || (etat.vue !== 'direct' && etat.vue !== 'traitement')) return;
    try {
      const a = await lireOuNull(urlScan('apercu.json', lieu, s.id));
      if (a && !etat.ferme) {
        nuage.afficherTrajet(a.trajectoire);
        nuage.afficherRobot(a.robot ? { x: a.robot.x, y: a.robot.y, theta: a.robot.theta } : null);
        if (a.statistiques && etat.vue === 'direct') majCompteurs(s, a.statistiques);
        if (!nuage.ok) {
          image2d.hidden = false;
          image2d.src = urlScan('apercu.png', lieu, s.id) + '&v=' + enc(a.maj || Date.now());
        }
      }
      if (nuage.ok) {
        const r = await telechargerNuage(urlScan('nuage', lieu, s.id) + '&apercu=1');
        if (!etat.ferme && r.entete.date !== etat.dateNuage) {
          etat.dateNuage = r.entete.date;
          nuage.grilleNuage(r.entete.grille);
          nuage.afficherPoints(r.positions, r.entete.bornes);
          ecran.dataset.points = String(r.positions.length / 3);
        }
      }
    } catch (err) {
      if (err.statut !== 404) message.textContent = 'Aperçu indisponible : ' + err.message;
    }
    if (!etat.ferme) etat.minuteurDirect = setTimeout(majDirect, PERIODE_DIRECT);
  }

  // Scan terminé : le nuage final, la carte 2D et le résumé du traitement
  async function chargerResultat(s) {
    pleinEcran(false);
    nuage.recommencer(6);
    nuage.suivre(false);
    el(blocResume, 'h3', 'scan-bloc-titre', 'Résultat du scan');
    const resume = el(blocResume, 'div', 'scan-resume-texte', null, 'scan-resume-texte');
    if (s.adoption) el(blocResume, 'p', 'scan-note', 'Déjà utilisée pour l\'étage le ' + dateCourte(s.adoption.quand) + '.');
    const vignette = el(blocResume, 'figure', 'scan-vignette');
    const img = el(vignette, 'img', 'scan-vignette-image', null, 'scan-carte2d');
    img.alt = 'Carte 2D du scan (noir : obstacles)';
    el(vignette, 'figcaption', 'scan-note', 'La carte 2D du scan : le robot évite le noir.');
    img.src = urlSession(lieu, s.id, 'carte.png') + '&v=' + enc(s.maj || Date.now());
    try {
      const r = await nuage.chargerBinaire(urlScan('nuage', lieu, s.id));
      ecran.dataset.points = String(r.points);
      if (!etat.ferme) nuage.vue('iso');
    } catch (e) {
      if (!nuage.ok || e.statut === 404) {
        image2d.hidden = false;
        image2d.src = img.src;
      }
      if (e.statut !== 404 && e.statut !== undefined) message.textContent = e.message;
    }
    try {
      const a = await lireOuNull(urlScan('apercu.json', lieu, s.id));
      if (a && !etat.ferme) nuage.afficherTrajet(a.trajectoire);
    } catch (e) {
      // pas de trajet : tant pis
    }
    try {
      const rapport = await lireOuNull(urlSession(lieu, s.id, 'rapport'));
      if (etat.ferme || !rapport) return;
      const lignes = [];
      if (rapport.nuages) {
        lignes.push(entier(rapport.nuages.utilises) + ' nuages assemblés sur ' + entier(rapport.nuages.recus)
          + (rapport.nuages.ignores ? ' (' + entier(rapport.nuages.ignores) + ' ignorés)' : '') + '.');
        etat.nuagesRelus = { session: s.id, nombre: rapport.nuages.recus };
        valeurs.nuages.textContent = entier(rapport.nuages.recus);
      }
      if (rapport.affichage) {
        lignes.push(entier(rapport.affichage.points) + ' points gardés dans la carte 3D (un par case de '
          + nb((rapport.affichage.grille || 0.05) * 100, 0) + ' cm).');
      }
      if (rapport.mobiles_retires !== undefined) lignes.push(entier(rapport.mobiles_retires) + ' points de passants retirés.');
      if (rapport.sol) {
        const plat = rapport.sol.methode === 'centile';
        lignes.push(plat ? 'Sol peu vu : pris à plat (un scan plus long le verra mieux).'
          : 'Sol trouvé, penché de ' + nb(rapport.sol.inclinaison_deg, 2) + '°.');
      }
      if (rapport.carte) lignes.push('Carte 2D : ' + rapport.carte.largeur + ' × ' + rapport.carte.hauteur + ' pixels de 5 cm.');
      lignes.forEach((t) => el(resume, 'p', 'scan-note', t));
      (rapport.avertissements || []).forEach((t) => {
        // anciennes sessions : la note de développeur sur le repère devient une phrase simple (détail en infobulle)
        const technique = /^Repère des points/.test(t);
        const p = el(resume, 'p', 'scan-alerte', technique ? 'Scan du vrai robot : regardez la carte avant de '
          + 'l\'utiliser, elle ne doit être ni dédoublée ni tournée.' : t);
        if (technique) p.title = t;
      });
    } catch (e) {
      // rapport illisible : le résumé reste vide
    }
  }

  // ------------------------------------------------------------ les actions : Scan, Fin, Utiliser cette carte
  async function lancer() {
    if (etat.enCours) return;
    if (etat.session && (etat.vue === 'direct' || etat.vue === 'traitement')) {
      dire('Un scan est déjà en cours : « Fin » l\'arrête.', 'avertissement');
      return;
    }
    const robotReel = reglages.mode === 'robot' && !reglages.repetition;
    if (robotReel) {
      const ok = await confirmer('Scan avec le vrai robot : le câble Ethernet relie le PC au robot, « source '
        + '~/robot-g1/setup/robot.sh » est fait, et vous avez la télécommande en main. Pendant le scan, promenez le '
        + 'robot lentement, en marchant derrière lui avec le PC.', { titre: 'Commencer le scan', ok: 'Commencer' });
      if (!ok) return;
    }
    const avecSimulation = reglages.mode === 'simu' || reglages.repetition;
    const corps = { lieu: lieu, etage: etage, mode: reglages.mode, repetition: reglages.mode === 'robot' && reglages.repetition,
      explorer: avecSimulation && !!reglages.explorer };
    if (reglages.nom) corps.nom = reglages.nom;
    etat.enCours = true;
    boutonScan.disabled = true;
    boutonScan.textContent = '…';
    try {
      const e = await api.envoyer('/api/scan/demarrer', corps);
      dire('Scan démarré : ' + e.session.nom + '.', 'succes');
      etat.suivie = e.session.id;
      recevoir(e);
    } catch (err) {
      afficherErreur(err);
    } finally {
      etat.enCours = false;
      boutonScan.disabled = false;
      boutonScan.textContent = 'Scan';
    }
  }

  async function finir() {
    const s = etat.session;
    if (!s || etat.vue !== 'direct') {
      dire('Aucun scan en cours : « Fin » sert à arrêter un scan.', 'avertissement');
      return;
    }
    if (etat.enCours) return;
    etat.enCours = true;
    boutonFin.disabled = true;
    boutonFin.textContent = '…';
    if (etat.teleop) etat.teleop.desactiver();
    message.textContent = 'Fin du scan : fermeture de l\'enregistrement (jusqu\'à 30 s)…';
    try {
      const e = await api.envoyer('/api/scan/arreter', { lieu: lieu, session: s.id });
      if (!etat.ferme) recevoir(e);
    } catch (err) {
      afficherErreur(err);
      if (etat.teleop) etat.teleop.activer();
    } finally {
      etat.enCours = false;
      boutonFin.disabled = false;
      boutonFin.textContent = 'Fin';
    }
  }

  async function utiliser() {
    const s = etat.session;
    if (!s || s.etat !== 'termine') {
      dire('Pas encore de carte à utiliser : faites un scan, puis attendez la fin de sa fabrication.', 'avertissement');
      return;
    }
    if (etat.enCours) return;
    let question = 'La carte 2D et le nuage 3D de l\'étage « ' + s.etage + ' » vont être remplacés par ceux de ce scan. '
      + 'La simulation de l\'étage tournera sur cette carte (les murs dessinés sont gardés dans le dossier du scan).';
    if (s.adoption) question = 'Ce scan a déjà été utilisé une fois. ' + question;
    const ok = await confirmer(question, { titre: 'Utiliser cette carte', ok: 'Utiliser cette carte' });
    if (!ok) return;
    etat.enCours = true;
    boutonUtiliser.disabled = true;
    try {
      const r = await api.envoyer(urlSession(lieu, s.id, 'adopter'), {});
      afficherMessage('Carte du scan utilisée pour l\'étage « ' + s.etage + ' ».', 'succes', [], r.sortie);
      (r.avertissements || []).forEach((a) => dire(a, 'avertissement'));
      afficherRapport(r.rapport);
      await rechargerLieu();
      suivre(s.id);
    } catch (err) {
      afficherErreur(err);
    } finally {
      etat.enCours = false;
      boutonUtiliser.disabled = false;
    }
  }

  async function terminerInterrompu() {
    const s = etat.session;
    if (!s) return;
    boutonTerminer.disabled = true;
    try {
      recevoir(await api.envoyer('/api/scan/arreter', { lieu: lieu, session: s.id }));
    } catch (err) {
      afficherErreur(err);
    } finally {
      boutonTerminer.disabled = false;
    }
  }

  function nouveau() {
    etat.suivie = null;
    recevoir({ session: null, actif: false });
  }

  boutonScan.addEventListener('click', lancer);
  boutonFin.addEventListener('click', finir);
  boutonUtiliser.addEventListener('click', utiliser);
  boutonNouveau.addEventListener('click', nouveau);
  boutonTerminer.addEventListener('click', terminerInterrompu);

  // ------------------------------------------------------------ scans précédents
  async function majHistorique() {
    let sessions;
    try {
      sessions = await api.lire('/api/scan/sessions?lieu=' + enc(lieu));
    } catch (e) {
      return;
    }
    if (etat.ferme) return;
    listeHistorique.textContent = '';
    if (!sessions.length) {
      el(listeHistorique, 'p', 'scan-note', 'Aucun scan pour ce lieu pour l\'instant.');
      return;
    }
    sessions.forEach((s) => {
      const ligne = el(listeHistorique, 'div', 'scan-session' + (s.id === etat.suivie ? ' scan-session-suivie' : ''));
      ligne.dataset.session = s.id;
      if (s.illisible) {
        el(ligne, 'span', 'scan-session-nom', s.id);
        el(ligne, 'span', 'scan-alerte', 'Fichier session.json illisible : ce scan ne peut plus servir.');
        return;
      }
      const texte = el(ligne, 'div', 'scan-session-texte');
      el(texte, 'span', 'scan-session-nom', s.nom);
      let detail = dateCourte(s.debut) + ' · ' + texteMode(s) + ' · '
        + (s.interrompue ? 'interrompu' : (NOMS_ETATS[s.etat] || s.etat));
      if (s.etat === 'traitement') detail += ' (' + s.progression + ' %)';
      if (s.adoption) detail += ' · utilisé pour l\'étage';
      el(texte, 'span', 'scan-session-detail', detail);
      if (s.id !== etat.suivie) {
        const b = el(ligne, 'button', 'scan-bouton-lien', 'Voir');
        b.type = 'button';
        b.addEventListener('click', () => suivre(s.id));
      } else {
        el(ligne, 'span', 'scan-session-detail', 'affiché');
      }
    });
  }

  // ------------------------------------------------------------ commandes du ruban
  function commande(nom) {
    if (nom === 'scan') lancer();
    else if (nom === 'fin') finir();
    else if (nom === 'utiliser') utiliser();
  }

  interroger();
  if (o.commande && o.commande !== 'simule') {
    // la commande du ruban qui a ouvert l'écran : après le premier état lu
    setTimeout(() => { if (!etat.ferme) commande(o.commande); }, PERIODE_ETAT + 200);
  }
  return {
    modifie: () => false,
    commande: commande,
    fermer: () => {
      etat.ferme = true;
      clearTimeout(etat.minuteur);
      clearTimeout(etat.minuteurDirect);
      if (etat.teleop) etat.teleop.detruire();
      pleinEcran(false);
      nuage.detruire();
      if (window.scanNuage3d === nuage) window.scanNuage3d = null;
      racine.classList.remove('scan-racine', 'scan-sans-coque');
    },
  };
}
