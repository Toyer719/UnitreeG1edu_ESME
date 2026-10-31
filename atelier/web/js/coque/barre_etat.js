// Barre d'état (en bas) : consigne de l'outil actif, messages courts (à la place des notifications
// volantes), coordonnées sous le pointeur, liaison, et en Avancé « Ce qui tourne » (vague 5, section 12.2
// du plan). Module de l'agent Coquille.
//
// construireBarreEtat(element) → {message(texte, genre, details, sortie), effacer(), coordonnees(x, y),
//   outil(texte), liaison(texte, genre), processus(etat), journal(ouvrir), detruire()}
// effacer() : plus de message dans la barre (il reste dans le journal) ; la coque l'appelle quand on change
// d'écran (un avertissement d'un autre écran ne reste pas affiché).
// Repères : [data-role=barre-etat], [data-role=etat-message] (data-genre), [data-role=etat-coordonnees],
// [data-role=etat-liaison], [data-role=journal] (les messages, avec leurs détails : .message.message-<genre>),
// [data-role=ce-qui-tourne].

import { icone } from './icones.js';

const DUREE_MESSAGE_MS = { info: 9000, succes: 9000, avertissement: 30000, erreur: 0 };
const JOURNAL_MAX = 60;
const NOMS_PROCESSUS = {
  simulation: 'Simulation (Gazebo)', navigation: 'Navigation (guide)', faux_slam: 'Faux service de cartographie',
  scan: 'Scan', pilotage: 'Pilotage du robot',
};
const SYMBOLES = { info: 'info', succes: 'coche', avertissement: 'alerte', erreur: 'alerte' };

function el(balise, classe, texte) {
  const e = document.createElement(balise);
  if (classe) e.className = classe;
  if (texte !== undefined && texte !== null) e.textContent = texte;
  return e;
}

function nb(v, d) {
  return Number(v).toFixed(d === undefined ? 2 : d).replace('.', ',').replace('-', '−');
}

function heure() {
  const t = new Date();
  const z = (n) => ('0' + n).slice(-2);
  return z(t.getHours()) + ':' + z(t.getMinutes()) + ':' + z(t.getSeconds());
}

export function construireBarreEtat(element) {
  element.textContent = '';
  element.classList.add('barre-etat');
  element.setAttribute('data-role', 'barre-etat');
  const outil = el('span', 'etat-outil');
  outil.setAttribute('data-role', 'etat-outil');
  const zoneMessage = el('button', 'etat-message');
  zoneMessage.type = 'button';
  zoneMessage.setAttribute('data-role', 'etat-message');
  zoneMessage.title = 'Voir les derniers messages';
  const symbole = el('span', 'etat-message-symbole');
  const texteMessage = el('span', 'etat-message-texte');
  const compteur = el('span', 'etat-message-compteur');
  zoneMessage.appendChild(symbole);
  zoneMessage.appendChild(texteMessage);
  zoneMessage.appendChild(compteur);
  const coordonnees = el('span', 'etat-coordonnees', '');
  coordonnees.setAttribute('data-role', 'etat-coordonnees');
  const boutonProcessus = el('button', 'etat-bouton');
  boutonProcessus.type = 'button';
  boutonProcessus.setAttribute('data-role', 'bouton-ce-qui-tourne');
  boutonProcessus.title = 'Ce qui tourne : les commandes lancées par l\'Atelier et leurs derniers messages';
  boutonProcessus.appendChild(icone('console', 16));
  boutonProcessus.appendChild(el('span', '', 'Ce qui tourne'));
  boutonProcessus.hidden = true;     // montré seulement quand l'Atelier a lancé quelque chose (sinon : menu ⚙)
  const liaison = el('span', 'etat-liaison');
  liaison.setAttribute('data-role', 'etat-liaison');
  [outil, zoneMessage, coordonnees, boutonProcessus, liaison].forEach((e) => element.appendChild(e));

  // journal des messages (au-dessus de la barre)
  const journal = el('div', 'etat-volet etat-journal');
  journal.setAttribute('data-role', 'journal');
  journal.hidden = true;
  const enteteJournal = el('div', 'etat-volet-entete');
  enteteJournal.appendChild(el('strong', '', 'Messages'));
  const vider = el('button', 'bouton-lien', 'Tout effacer');
  vider.type = 'button';
  const fermerJournal = el('button', 'bouton-icone petit');
  fermerJournal.type = 'button';
  fermerJournal.title = 'Fermer';
  fermerJournal.appendChild(icone('croix', 16));
  enteteJournal.appendChild(vider);
  enteteJournal.appendChild(fermerJournal);
  const listeJournal = el('div', 'etat-volet-liste');
  journal.appendChild(enteteJournal);
  journal.appendChild(listeJournal);
  element.appendChild(journal);

  // « Ce qui tourne »
  const volet = el('div', 'etat-volet etat-processus');
  volet.setAttribute('data-role', 'ce-qui-tourne');
  volet.hidden = true;
  const enteteVolet = el('div', 'etat-volet-entete');
  enteteVolet.appendChild(el('strong', '', 'Ce qui tourne'));
  const fermerVolet = el('button', 'bouton-icone petit');
  fermerVolet.type = 'button';
  fermerVolet.title = 'Fermer';
  fermerVolet.appendChild(icone('croix', 16));
  enteteVolet.appendChild(fermerVolet);
  const listeProcessus = el('div', 'etat-volet-liste');
  volet.appendChild(enteteVolet);
  volet.appendChild(listeProcessus);
  element.appendChild(volet);

  let minuterie = null;
  let nonLus = 0;
  let dernierProcessus = '';

  function ouvrirJournal(oui) {
    journal.hidden = !oui;
    if (oui) {
      volet.hidden = true;
      nonLus = 0;
      compteur.textContent = '';
    }
  }

  function ouvrirVolet(oui) {
    volet.hidden = !oui;
    if (oui) journal.hidden = true;
  }

  zoneMessage.addEventListener('click', () => ouvrirJournal(journal.hidden));
  fermerJournal.addEventListener('click', () => ouvrirJournal(false));
  vider.addEventListener('click', () => {
    listeJournal.textContent = '';
    texteMessage.textContent = '';
    symbole.textContent = '';
    zoneMessage.dataset.genre = '';
    ouvrirJournal(false);
  });
  boutonProcessus.addEventListener('click', () => ouvrirVolet(volet.hidden));
  fermerVolet.addEventListener('click', () => ouvrirVolet(false));

  function message(texte, genre, details, sortie) {
    genre = genre || 'info';
    // dans la barre : le texte seul, sur une ligne
    zoneMessage.dataset.genre = genre;
    symbole.textContent = '';
    symbole.appendChild(icone(SYMBOLES[genre] || 'info', 16));
    texteMessage.textContent = texte + ((details && details.length) || sortie ? ' (détails)' : '');
    zoneMessage.title = texte;
    zoneMessage.classList.remove('nouveau');
    void zoneMessage.offsetWidth;          // relance l'animation d'apparition
    zoneMessage.classList.add('nouveau');
    if (minuterie) clearTimeout(minuterie);
    minuterie = null;
    const duree = DUREE_MESSAGE_MS[genre];
    if (duree) {
      minuterie = setTimeout(() => {
        if (zoneMessage.dataset.genre === genre && texteMessage.textContent.indexOf(texte) === 0) {
          zoneMessage.dataset.genre = 'ancien';
        }
      }, duree);
    }
    // dans le journal : le message complet
    const boite = el('div', 'message message-' + genre);
    boite.setAttribute('role', genre === 'erreur' ? 'alert' : 'status');
    const tete = el('div', 'message-tete');
    tete.appendChild(el('span', 'message-heure', heure()));
    tete.appendChild(el('p', 'message-texte', texte));
    boite.appendChild(tete);
    if (details && details.length) {
      const liste = el('ul', 'message-details');
      details.forEach((d) => liste.appendChild(el('li', '', d)));
      boite.appendChild(liste);
    }
    if (sortie) {
      const plus = el('details', 'message-sortie');
      plus.appendChild(el('summary', '', 'Message complet de la commande'));
      plus.appendChild(el('pre', '', sortie));
      boite.appendChild(plus);
    }
    listeJournal.insertBefore(boite, listeJournal.firstChild);
    while (listeJournal.children.length > JOURNAL_MAX) listeJournal.lastChild.remove();
    if (journal.hidden && (genre === 'erreur' || genre === 'avertissement')) {
      nonLus += 1;
      compteur.textContent = String(nonLus);
    }
    // une erreur avec des détails à lire : le journal s'ouvre de lui-même
    if (genre === 'erreur' && ((details && details.length) || sortie)) ouvrirJournal(true);
    return boite;
  }

  function majProcessus(processus) {
    const cle = JSON.stringify(processus || {});
    if (cle === dernierProcessus) return;
    dernierProcessus = cle;
    listeProcessus.textContent = '';
    const roles = Object.keys(processus || {});
    boutonProcessus.hidden = !roles.length;
    const enCours = roles.filter((r) => processus[r].en_cours).length;
    boutonProcessus.classList.toggle('actif', enCours > 0);
    boutonProcessus.querySelector('span').textContent = enCours ? 'Ce qui tourne (' + enCours + ')' : 'Ce qui tourne';
    const enErreur = roles.some((r) => (!processus[r].en_cours && !processus[r].arret_demande && processus[r].code)
      || (processus[r].en_cours && processus[r].plantages && processus[r].plantages.length));
    boutonProcessus.classList.toggle('erreur', enErreur);
    if (!roles.length) {
      listeProcessus.appendChild(el('p', 'panneau-note', 'Rien ne tourne.'));
      return;
    }
    roles.forEach((role) => {
      const p = processus[role];
      const bloc = el('div', 'processus-bloc');
      const etat = p.en_cours ? 'en cours' : (p.arret_demande ? 'arrêté' : 'terminé (code ' + p.code + ')');
      bloc.appendChild(el('div', 'processus-titre' + (!p.en_cours && !p.arret_demande && p.code ? ' processus-erreur' : ''),
        (NOMS_PROCESSUS[role] || role) + ' : ' + etat));
      if (p.en_cours && p.plantages && p.plantages.length) {
        bloc.appendChild(el('div', 'processus-erreur', 'Arrêtés seuls : ' + p.plantages.join(', ')
          + ' (arrêtez, puis relancez)'));
      }
      bloc.appendChild(el('div', 'code', p.commande));
      if (p.dernieres_lignes && p.dernieres_lignes.length) bloc.appendChild(el('pre', 'processus-sortie', p.dernieres_lignes.join('\n')));
      if (p.journal) bloc.appendChild(el('div', 'panneau-note', 'Journal complet : ' + p.journal));
      listeProcessus.appendChild(bloc);
    });
  }

  function effacer() {
    if (minuterie) clearTimeout(minuterie);
    minuterie = null;
    texteMessage.textContent = '';
    symbole.textContent = '';
    zoneMessage.dataset.genre = '';
    zoneMessage.title = 'Voir les derniers messages';
  }

  return {
    message: message,
    effacer: effacer,
    coordonnees: (x, y) => {
      coordonnees.textContent = (x === null || x === undefined || y === null || y === undefined) ? ''
        : 'x ' + nb(x) + ' m   y ' + nb(y) + ' m';
    },
    outil: (texte) => {
      outil.textContent = texte || '';
      outil.title = texte || '';
    },
    liaison: (texte, genre) => {
      liaison.textContent = texte || '';
      liaison.dataset.genre = genre || '';
    },
    processus: majProcessus,
    journal: ouvrirJournal,
    ceQuiTourne: ouvrirVolet,
    detruire: () => {
      if (minuterie) clearTimeout(minuterie);
      element.textContent = '';
    },
  };
}
