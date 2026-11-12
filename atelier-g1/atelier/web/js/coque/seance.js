// La boîte noire dans l'Atelier (vague 6, section 13.3 du plan) : module de l'agent Boîte noire.
//
// Contrat (outils de la coque : {mode, repetition, lieu, etage, api, message(texte, genre, details),
// confirmer(texte, options) → promesse, ouvrirCommande(id, valeur)}) :
//   surEspace(outils)
//       appelée par la coque à chaque ouverture de l'espace de travail : en Réel (vrai robot ou répétition),
//       la séance s'ouvre seule (POST /api/seance/demarrer {mode, lieu, etage, ouverture: 'auto'}) ; une séance
//       déjà ouverte est rendue telle quelle ; en Simulation, une séance ouverte est terminée (corrections de la
//       vague 6 : une séance correspond au mode Réel ; POST /api/seance/arreter {fermeture: 'simulation'}, refusé
//       tant que la navigation du robot ou de la répétition tourne) ;
//   monterSeanceBarre(element, outils) → {detruire()}
//       dans la barre d'outils : le badge « ● Enregistrement » ([data-role=seance], data-etat=enregistrement|
//       coupe|arrete) tant qu'une séance est ouverte (champ seance de /ws/etat) ; un clic : le petit menu de la
//       séance ([data-role=menu-seance] : Terminer la séance, les rapports) ; après « Terminer », le lien du
//       rapport ([data-role=rapport-seance], data-etat=en_cours|pret|echec) ; en Réel sans séance ouverte, le
//       bouton « Nouvelle séance » ([data-role=nouvelle-seance], corrections de la vague 6) ;
//   executer(nom, valeur, outils)
//       commandes du ruban seance.terminer (« terminer » : confirmation dans la page, POST /api/seance/arreter,
//       puis le lien du rapport) et seance.rapport (« rapport » : le menu, avec les rapports des dernières séances).
// Le rapport s'ouvre dans un onglet (GET /api/seances/<id>/rapport). Le menu ne couvre jamais l'ARRÊT (il est sous
// la barre d'outils), se ferme par Échap, par ✗ et par un clic ailleurs. Textes simples ; aucune donnée insérée en
// HTML (textContent) ; jamais de fenêtre du navigateur.

import { abonner } from '../direct.js';
import { icone } from './icones.js';

export const TEXTES_BADGE = {
  enregistrement: 'Enregistrement',
  coupe: 'Enregistrement coupé',
  arrete: 'Séance sans enregistrement',
};
export const TEXTE_BADGE_COURT = 'Séance';     // le badge quand la barre manque de place (corrections de la vague 6)
export const TEXTES_RAPPORT = { absent: 'Pas de rapport', en_cours: 'Le rapport s\'écrit…', pret: 'Rapport prêt',
  echec: 'Rapport en échec' };
const PERIODE_RAPPORT_MS = 2000;      // suivi du rapport après « Terminer »
const DUREE_SUIVI_MS = 180000;        // 3 min au plus
const SEANCES_DANS_LE_MENU = 5;

// État du module, partagé par la barre d'outils, le menu et les commandes du ruban
const memoire = { seance: null, terminee: null, abonnes: [], menu: null, ancre: null, suivi: null };

function el(balise, classe, texte) {
  const e = document.createElement(balise);
  if (classe) e.className = classe;
  if (texte !== undefined && texte !== null) e.textContent = texte;
  return e;
}

function notifier() {
  memoire.abonnes.slice().forEach((f) => {
    try {
      f();
    } catch (e) {
      console.error(e);
    }
  });
}

// ---------------------------------------------------------------- fonctions pures (testées)

// Le mode de la séance d'après les outils de la coque : 'reel', 'repetition', ou null (Simulation : pas de séance)
export function modeSeance(outils) {
  const o = outils || {};
  if (o.mode === 'repetition') return 'repetition';
  if (o.mode === 'reel') return o.repetition ? 'repetition' : 'reel';
  return null;
}

// « 14:03 » d'une heure ISO du serveur (sans dépendre du fuseau du navigateur)
export function heureDe(iso) {
  const m = /T(\d\d):(\d\d)/.exec(String(iso || ''));
  return m ? m[1] + ':' + m[2] : '';
}

// « 12/11 » d'une date ISO
export function jourDe(iso) {
  const m = /^\d{4}-(\d\d)-(\d\d)T/.exec(String(iso || ''));
  return m ? m[2] + '/' + m[1] : '';
}

// 1843200 → « 1,8 Mo » ; 5300 → « 5 ko »
export function tailleLisible(octets) {
  const n = Number(octets) || 0;
  if (n < 1000 * 1000) return Math.round(n / 1000) + '\u00a0ko';
  return String(Math.round(n / 100000) / 10).replace('.', ',') + '\u00a0Mo';
}

// 2532 → « 42 min » ; 3725 → « 1 h 02 » ; 45 → « 45 s »
export function dureeLisible(s) {
  const n = Math.max(0, Math.round(Number(s) || 0));
  if (n < 60) return n + ' s';
  if (n < 3600) return Math.floor(n / 60) + ' min';
  return Math.floor(n / 3600) + ' h ' + String(Math.floor((n % 3600) / 60)).padStart(2, '0');
}

// Le badge d'une séance (champ seance de /ws/etat) : {etat, texte, titre}, ou null sans séance
export function badgeDe(seance) {
  if (!seance) return null;
  const etat = TEXTES_BADGE[seance.badge] ? seance.badge : 'arrete';
  const e = seance.enregistrement || {};
  let titre = 'Séance ouverte à ' + heureDe(seance.debut) + ' : ' + (seance.actions || 0) + ' action'
    + ((seance.actions || 0) > 1 ? 's' : '') + ' notée' + ((seance.actions || 0) > 1 ? 's' : '');
  if (etat === 'enregistrement') titre += ', ' + tailleLisible(e.octets) + ' enregistrés';
  if (e.message) titre += '. ' + e.message;
  titre += ' Cliquez pour la terminer ou voir les rapports.';
  return { etat: etat, texte: seance.fermeture ? 'Fin de la séance…' : TEXTES_BADGE[etat], titre: titre };
}

// Le bref d'une séance (champ seance de /ws/etat) d'après son manifeste (réponse de POST /api/seance/demarrer)
export function brefDuManifeste(m) {
  if (!m || m.etat !== 'ouverte') return null;
  const e = m.enregistrement || {};
  const badge = (e.etat === 'demarrage' || e.etat === 'en_cours') ? 'enregistrement' : (e.etat === 'coupe' ? 'coupe' : 'arrete');
  return { id: m.id, etat: 'ouverte', mode: m.mode, lieu: m.lieu, etage: m.etage, debut: m.debut, actions: m.actions || 0,
    badge: badge, enregistrement: { etat: e.etat, octets: e.octets || 0, message: e.message || null } };
}

// Adresse du rapport d'une séance (html par défaut, ou md, json)
export function urlRapport(id, format) {
  return '/api/seances/' + encodeURIComponent(id) + '/rapport' + (format && format !== 'html' ? '?format=' + format : '');
}

// Une ligne de la liste des séances : « 12/11 14:03 · 42 min · Répétition »
export function ligneSeance(s) {
  const mode = s.mode === 'repetition' ? 'Répétition' : 'Robot réel';
  const morceaux = [jourDe(s.debut) + ' ' + heureDe(s.debut)];
  if (s.duree_s !== null && s.duree_s !== undefined) morceaux.push(dureeLisible(s.duree_s));
  morceaux.push(mode + (s.etat === 'interrompue' ? ' (interrompue)' : ''));
  if (s.lieu) morceaux.push(s.lieu);
  return morceaux.join(' · ');
}

// ---------------------------------------------------------------- ouverture automatique

export function surEspace(outils) {
  const mode = modeSeance(outils);
  if (!outils || !outils.api) return null;
  if (!mode) return finirEnSimulation(outils);
  return outils.api.envoyer('/api/seance/demarrer', { mode: mode, lieu: outils.lieu || null,
    etage: outils.etage || null, ouverture: 'auto' })
    .then((r) => {
      const bref = brefDuManifeste(r && r.seance);
      if (bref && !(memoire.seance && memoire.seance.id === bref.id)) {
        memoire.seance = bref;             // /ws/etat le remplace aussitôt par le sien
        notifier();
      }
      return r ? r.seance : null;
    })
    .catch((e) => {
      if (outils.message) {
        outils.message('La boîte noire n\'a pas pu ouvrir la séance : ' + (e && e.message ? e.message : e),
          'avertissement');
      }
      return null;
    });
}

// En Simulation : une séance restée ouverte (espace ouvert avant en Réel) est terminée, son rapport s'écrit.
// Tant que la navigation du robot ou de la répétition tourne, le serveur refuse (409) : elle continue d'enregistrer.
export function finirEnSimulation(outils) {
  if (!outils || !outils.api || !outils.api.lire) return null;
  return outils.api.lire('/api/seance')
    .then((r) => {
      if (!r || !r.seance || r.seance.etat !== 'ouverte') return null;
      return outils.api.envoyer('/api/seance/arreter', { fermeture: 'simulation' })
        .then((rep) => {
          const m = rep && rep.seance;
          if (!m) return null;
          memoire.terminee = { id: m.id, rapport: (m.rapport && m.rapport.etat) || 'en_cours' };
          memoire.seance = null;
          notifier();
          if (outils.message) {
            outils.message('Séance terminée : vous êtes passé en Simulation, le rapport s\'écrit (une minute au plus).',
              'info');
          }
          if (memoire.terminee.rapport !== 'pret') suivreRapport(m.id, outils);
          return m;
        });
    })
    .catch((e) => {
      if (outils.message) outils.message('La séance continue : ' + (e && e.message ? e.message : e), 'avertissement');
      return null;
    });
}

// Une nouvelle séance à la main (ouverture « manuel »), depuis le bouton « Nouvelle séance » ou le menu
export function commencerSeance(outils) {
  const mode = modeSeance(outils);
  if (!mode) return Promise.resolve(null);
  return outils.api.envoyer('/api/seance/demarrer', { mode: mode, lieu: outils.lieu || null, etage: outils.etage || null,
    ouverture: 'manuel' })
    .then((r) => {
      const bref = brefDuManifeste(r && r.seance);
      if (bref) {
        memoire.seance = bref;
        memoire.terminee = null;
        notifier();
      }
      if (outils.message) outils.message('Séance commencée : l\'enregistrement démarre.', 'succes');
      return r ? r.seance : null;
    });
}

// ---------------------------------------------------------------- barre d'outils

export function monterSeanceBarre(element, outils) {
  if (!element) return { detruire: () => {} };
  const badge = el('button', 'seance-badge');
  badge.type = 'button';
  badge.setAttribute('data-role', 'seance');
  badge.setAttribute('aria-haspopup', 'menu');
  badge.hidden = true;
  badge.appendChild(el('span', 'seance-point'));
  const texte = el('span', 'seance-badge-texte', TEXTES_BADGE.enregistrement);
  badge.appendChild(texte);
  badge.appendChild(el('span', 'seance-badge-court', TEXTE_BADGE_COURT));    // de 1 440 à 1 799 px (seance.css)
  badge.addEventListener('click', () => basculerMenu(badge, outils));
  const lien = el('a', 'seance-lien-rapport');
  lien.setAttribute('data-role', 'rapport-seance');
  lien.target = '_blank';
  lien.rel = 'noopener';
  lien.hidden = true;
  lien.appendChild(icone('rapport', 16));
  const texteLien = el('span', 'seance-lien-texte', 'Rapport de séance');
  lien.appendChild(texteLien);
  // corrections de la vague 6 : en Réel sans séance ouverte (après « Terminer »), en commencer une sans revenir à
  // l'accueil
  const nouvelle = el('button', 'seance-nouvelle');
  nouvelle.type = 'button';
  nouvelle.setAttribute('data-role', 'nouvelle-seance');
  nouvelle.hidden = true;
  nouvelle.appendChild(icone('seance', 16));
  nouvelle.appendChild(el('span', 'seance-nouvelle-texte', 'Nouvelle séance'));
  nouvelle.title = 'Aucune séance ouverte : cliquez pour en commencer une (la boîte noire enregistre de nouveau)';
  nouvelle.setAttribute('aria-label', 'Commencer une nouvelle séance');
  nouvelle.addEventListener('click', () => {
    nouvelle.disabled = true;
    commencerSeance(outils)
      .catch((e) => {
        if (outils.message) outils.message(e.message, 'erreur');
      })
      .then(() => {
        nouvelle.disabled = false;
      });
  });
  element.appendChild(badge);
  element.appendChild(lien);
  element.appendChild(nouvelle);

  function dessiner() {
    const b = badgeDe(memoire.seance);
    badge.hidden = !b;
    if (b) {
      badge.setAttribute('data-etat', b.etat);
      texte.textContent = b.texte;
      badge.title = b.titre;
      badge.setAttribute('aria-label', b.texte + ' : menu de la séance');
    }
    nouvelle.hidden = !!b || !modeSeance(outils);
    const t = memoire.terminee;
    lien.hidden = !t || !!b;
    if (t && !b) {
      lien.setAttribute('data-etat', t.rapport);
      if (t.rapport === 'pret') {
        lien.href = urlRapport(t.id);
        lien.removeAttribute('aria-disabled');
        lien.title = 'Ouvre le rapport de la séance ' + t.id + ' dans un onglet';
        texteLien.textContent = 'Rapport de séance';
      } else {
        lien.removeAttribute('href');
        lien.setAttribute('aria-disabled', 'true');
        lien.title = t.rapport === 'echec' ? 'Le rapport n\'a pas pu être écrit : voyez le menu de la séance (Refaire)'
          : 'Le rapport s\'écrit (une minute au plus)';
        texteLien.textContent = t.rapport === 'echec' ? 'Rapport en échec' : 'Rapport…';
      }
    }
  }
  const surDirect = (d) => {
    const avant = JSON.stringify(memoire.seance);
    memoire.seance = d ? d.seance || null : null;
    if (memoire.seance && memoire.terminee && memoire.seance.id !== memoire.terminee.id) memoire.terminee = null;
    if (JSON.stringify(memoire.seance) !== avant) notifier();
  };
  const desabonner = abonner(surDirect);
  memoire.abonnes.push(dessiner);
  memoire.ancre = badge;
  dessiner();
  return {
    detruire: () => {
      desabonner();
      const i = memoire.abonnes.indexOf(dessiner);
      if (i >= 0) memoire.abonnes.splice(i, 1);
      if (memoire.ancre === badge) memoire.ancre = null;
      fermerMenu();
      badge.remove();
      lien.remove();
      nouvelle.remove();
    },
  };
}

// ---------------------------------------------------------------- terminer la séance et suivre le rapport

function suivreRapport(id, outils) {
  if (memoire.suivi) clearTimeout(memoire.suivi);
  const fin = Date.now() + DUREE_SUIVI_MS;
  const tour = () => {
    memoire.suivi = null;
    outils.api.lire('/api/seances/' + encodeURIComponent(id))
      .then((m) => {
        const etat = (m && m.rapport && m.rapport.etat) || 'en_cours';
        if (memoire.terminee && memoire.terminee.id === id && memoire.terminee.rapport !== etat) {
          memoire.terminee.rapport = etat;
          notifier();
          if (etat === 'pret' && outils.message) outils.message('Rapport de séance prêt : cliquez sur « Rapport de séance ».', 'succes');
          if (etat === 'echec' && outils.message) outils.message('Le rapport de séance n\'a pas pu être écrit : '
            + ((m.rapport && m.rapport.message) || 'voyez le menu de la séance'), 'erreur');
        }
        if ((etat === 'en_cours' || etat === 'absent') && Date.now() < fin) memoire.suivi = setTimeout(tour, PERIODE_RAPPORT_MS);
      })
      .catch(() => {
        if (Date.now() < fin) memoire.suivi = setTimeout(tour, PERIODE_RAPPORT_MS);
      });
  };
  memoire.suivi = setTimeout(tour, PERIODE_RAPPORT_MS);
}

export async function terminer(outils) {
  fermerMenu();
  if (!memoire.seance) {
    if (outils && outils.message) {
      outils.message(modeSeance(outils) ? 'Aucune séance ouverte : « Nouvelle séance », dans la barre d\'outils, en '
        + 'commence une.' : 'Aucune séance ouverte : elle s\'ouvre seule quand on ouvre l\'espace en Réel.', 'info');
    }
    return null;
  }
  const ok = await outils.confirmer('Terminer la séance ?\n\nL\'enregistrement s\'arrête et le rapport s\'écrit tout seul '
    + '(une minute au plus). Une nouvelle séance s\'ouvrira à la prochaine ouverture de l\'espace en Réel.',
  { titre: 'Terminer la séance', ok: 'Terminer', annuler: 'Continuer' });
  if (!ok) return null;
  const r = await outils.api.envoyer('/api/seance/arreter', { fermeture: 'terminer' });
  const m = r && r.seance;
  if (!m) return null;
  memoire.terminee = { id: m.id, rapport: (m.rapport && m.rapport.etat) || 'en_cours' };
  memoire.seance = null;
  notifier();
  if (outils.message) {
    outils.message('Séance terminée : le rapport s\'écrit (une minute au plus). « Nouvelle séance », dans la barre '
      + 'd\'outils, en commence une autre.', 'succes');
  }
  if (memoire.terminee.rapport !== 'pret') suivreRapport(m.id, outils);
  return m;
}

// ---------------------------------------------------------------- le menu de la séance

function fermerMenu() {
  if (!memoire.menu) return;
  const m = memoire.menu;
  memoire.menu = null;
  document.removeEventListener('keydown', m.clavier, true);
  document.removeEventListener('mousedown', m.dehors, true);
  m.element.remove();
  if (m.ancre) m.ancre.setAttribute('aria-expanded', 'false');
}

function basculerMenu(ancre, outils) {
  if (memoire.menu) {
    fermerMenu();
    return;
  }
  ouvrirMenu(ancre, outils);
}

function ligneRapport(s, outils, liste) {
  const ligne = el('div', 'seance-menu-ligne');
  ligne.setAttribute('data-seance', s.id);
  const etat = s.rapport || 'absent';
  if (etat === 'pret') {
    const a = el('a', 'seance-menu-lien');
    a.href = urlRapport(s.id);
    a.target = '_blank';
    a.rel = 'noopener';
    a.setAttribute('data-role', 'rapport-seance');
    a.setAttribute('data-etat', 'pret');
    a.appendChild(icone('rapport', 16));
    a.appendChild(el('span', '', ligneSeance(s)));
    ligne.appendChild(a);
  } else {
    const t = el('span', 'seance-menu-texte');
    t.appendChild(el('span', '', ligneSeance(s)));
    t.appendChild(el('span', 'seance-menu-etat', TEXTES_RAPPORT[etat] || etat));
    ligne.appendChild(t);
    if (etat === 'echec' || etat === 'absent') {
      const b = el('button', 'bouton petit seance-refaire', 'Refaire');
      b.type = 'button';
      b.title = 'Écrire de nouveau le rapport de cette séance';
      b.addEventListener('click', () => {
        b.disabled = true;
        outils.api.envoyer('/api/seances/' + encodeURIComponent(s.id) + '/rapport', {})
          .then(() => {
            if (outils.message) outils.message('Le rapport de la séance ' + s.id + ' s\'écrit…', 'info');
            memoire.terminee = { id: s.id, rapport: 'en_cours' };
            notifier();
            suivreRapport(s.id, outils);
            fermerMenu();
          })
          .catch((e) => {
            b.disabled = false;
            if (outils.message) outils.message(e.message, 'erreur');
          });
      });
      ligne.appendChild(b);
    }
  }
  liste.appendChild(ligne);
}

export function ouvrirMenu(ancre, outils) {
  fermerMenu();
  const hote = (ancre && ancre.closest && ancre.closest('[data-role=espace]')) || document.body;
  const menu = el('div', 'menu-ruban menu-seance');
  menu.setAttribute('role', 'menu');
  menu.setAttribute('data-role', 'menu-seance');
  const entete = el('div', 'seance-menu-entete');
  entete.appendChild(el('strong', '', 'Séance'));
  const fermer = el('button', 'bouton-icone petit');
  fermer.type = 'button';
  fermer.title = 'Fermer';
  fermer.setAttribute('aria-label', 'Fermer le menu de la séance');
  fermer.setAttribute('data-role', 'fermer-menu-seance');
  fermer.appendChild(icone('croix', 16));
  fermer.addEventListener('click', fermerMenu);
  entete.appendChild(fermer);
  menu.appendChild(entete);
  const b = badgeDe(memoire.seance);
  const etat = el('p', 'seance-menu-etat-ouverte');
  if (b) {
    const e = (memoire.seance && memoire.seance.enregistrement) || {};
    etat.textContent = b.texte + ' depuis ' + heureDe(memoire.seance.debut) + ' · ' + (memoire.seance.actions || 0)
      + ' action' + ((memoire.seance.actions || 0) > 1 ? 's' : '') + (b.etat === 'enregistrement' ? ' · ' + tailleLisible(e.octets) : '');
    menu.appendChild(etat);
    if (e.message) menu.appendChild(el('p', 'seance-menu-message', e.message));
    const terminerBouton = el('button', 'menu-ruban-choix');
    terminerBouton.type = 'button';
    terminerBouton.setAttribute('role', 'menuitem');
    terminerBouton.setAttribute('data-role', 'terminer-seance');
    terminerBouton.appendChild(icone('stop', 18));
    terminerBouton.appendChild(el('span', '', 'Terminer la séance'));
    terminerBouton.addEventListener('click', () => {
      terminer(outils).catch((err) => {
        if (outils.message) outils.message(err.message, 'erreur');
      });
    });
    menu.appendChild(terminerBouton);
  } else {
    const mode = modeSeance(outils);
    etat.textContent = mode ? 'Aucune séance ouverte : « Commencer une séance » en ouvre une (la boîte noire '
      + 'enregistre de nouveau).' : 'Aucune séance ouverte : elle s\'ouvre seule quand on ouvre l\'espace en Réel.';
    menu.appendChild(etat);
    if (mode) {
      // à la main (13.3) : une nouvelle séance tout de suite, sans rouvrir l'espace de travail
      const commencer = el('button', 'menu-ruban-choix');
      commencer.type = 'button';
      commencer.setAttribute('role', 'menuitem');
      commencer.setAttribute('data-role', 'commencer-seance');
      commencer.appendChild(icone('seance', 18));
      commencer.appendChild(el('span', '', 'Commencer une séance'));
      commencer.addEventListener('click', () => {
        commencer.disabled = true;
        commencerSeance(outils)
          .then(() => {
            fermerMenu();
          })
          .catch((e) => {
            commencer.disabled = false;
            if (outils.message) outils.message(e.message, 'erreur');
          });
      });
      menu.appendChild(commencer);
    }
  }
  menu.appendChild(el('div', 'seance-menu-titre', 'Rapports des dernières séances'));
  const liste = el('div', 'seance-menu-liste');
  liste.appendChild(el('div', 'menu-ruban-vide', 'Chargement…'));
  menu.appendChild(liste);
  hote.appendChild(menu);
  // sous la barre d'outils (jamais sur l'ARRÊT, qui est dedans), aligné sur l'ancre, dans la fenêtre
  const r = ancre && ancre.getBoundingClientRect ? ancre.getBoundingClientRect() : { left: 8, right: 8, bottom: 48 };
  const barre = ancre && ancre.closest ? ancre.closest('[data-role=barre-outils]') : null;
  const bas = Math.max(r.bottom, barre ? barre.getBoundingClientRect().bottom : 48);
  const largeur = Math.max(menu.offsetWidth, 260);
  menu.style.left = Math.max(8, Math.min(window.innerWidth - largeur - 8, r.left)) + 'px';
  menu.style.top = (bas + 4) + 'px';
  menu.style.maxHeight = Math.max(160, window.innerHeight - bas - 24) + 'px';
  if (ancre && ancre.setAttribute) ancre.setAttribute('aria-expanded', 'true');
  const clavier = (ev) => {
    if (ev.key === 'Escape') fermerMenu();      // la coque, elle, envoie l'ARRÊT si le robot bouge
  };
  const dehors = (ev) => {
    if (!menu.contains(ev.target) && !(ancre && ancre.contains && ancre.contains(ev.target))) fermerMenu();
  };
  document.addEventListener('keydown', clavier, true);
  document.addEventListener('mousedown', dehors, true);
  memoire.menu = { element: menu, ancre: ancre, clavier: clavier, dehors: dehors };
  outils.api.lire('/api/seances')
    .then((seances) => {
      if (!memoire.menu || memoire.menu.element !== menu) return;
      liste.textContent = '';
      const fermees = (seances || []).filter((s) => s.etat !== 'ouverte').slice(0, SEANCES_DANS_LE_MENU);
      if (!fermees.length) liste.appendChild(el('div', 'menu-ruban-vide', 'Pas encore de séance terminée.'));
      fermees.forEach((s) => ligneRapport(s, outils, liste));
    })
    .catch((e) => {
      liste.textContent = '';
      liste.appendChild(el('div', 'menu-ruban-vide', 'Liste des séances indisponible : ' + e.message));
    });
  const premier = menu.querySelector('button[data-role=terminer-seance]');
  if (premier) premier.focus();
  return menu;
}

// ---------------------------------------------------------------- commandes du ruban

export function executer(nom, valeur, outils) {
  if (nom === 'terminer') return terminer(outils);
  if (nom === 'rapport') {
    const ancre = memoire.ancre && document.contains(memoire.ancre) && !memoire.ancre.hidden ? memoire.ancre
      : document.querySelector('[data-role=zone-seance]');
    ouvrirMenu(ancre, outils);
    return Promise.resolve(null);
  }
  return null;
}
