// Bouton ARRÊT unique de la barre d'outils, dans les deux modes, et la touche Échap (la coque l'appelle) :
// POST /api/arret, puis « Débloquer » (POST /api/arret/debloquer) quand un verrou est posé (vague 5,
// section 12.4 du plan). Module de l'agent Coquille.
//
// monterArret(element, {mode, message}) → {arreter(raison), debloquer(), mode(m), detruire()}
//   mode : 'simu' | 'reel' | 'repetition' ; message(texte, genre, details) : la barre d'état.
// Événement : « atelier-arret » sur document, dès l'appui (les écrans lâchent leurs manettes).
// Repère : [data-role=arret] (data-etat=pret|bloque). Le verrou n'existe qu'en Réel et en répétition :
// son état vient de la réponse de l'ARRÊT, du champ arret de /ws/etat (le verrou posé par l'Atelier) et du
// verrou du pont lui-même (champ pont : un pont resté bloqué après un redémarrage de l'Atelier montre
// « Débloquer »). « Débloquer » demande une confirmation dans la page : un double clic affolé sur ARRÊT ne
// relâche jamais le robot.
// Chaque appui envoie sa demande (la route est idempotente), avec un délai de 1,5 s : sans réponse, la barre
// d'état dit de prendre la télécommande (un premier ARRÊT resté sans réponse ne fait plus taire les autres).
//
// etatMouvement(d, local) et decisionEchap(m, servi) : ce que fait la touche Échap (la coque les appelle).

import { abonner } from '../direct.js';
import { demanderConfirmation } from './confirmation.js';
import { icone } from './icones.js';

function el(balise, classe, texte) {
  const e = document.createElement(balise);
  if (classe) e.className = classe;
  if (texte !== undefined && texte !== null) e.textContent = texte;
  return e;
}

export const DELAI_ARRET_MS = 1500;       // sans réponse dans ce délai : « prenez la télécommande »
const MESSAGE_SANS_REPONSE = 'ARRÊT : le serveur de l\'Atelier ne répond pas : arrêtez le robot avec la télécommande.';

// États du guide où le robot peut bouger d'un instant à l'autre (atelier.lieu.comportement.ETATS_EN_MISSION)
export const ETATS_EN_MISSION = ['en_route', 'retour', 'bloque', 'detour', 'attente_passage', 'attente_visiteur', 'perdu'];
// Commandes lancées par l'Atelier qui font (ou peuvent faire) bouger le robot
const ROLES_QUI_BOUGENT = ['simulation', 'navigation', 'faux_slam', 'pilotage', 'scan'];

// Ce qui peut bouger, d'après un message de /ws/etat (d, ou null s'il n'y en a pas encore) et les flèches
// tenues dans la page (local) : {connu, enMouvement, tourne: [noms]}. enMouvement : le robot bouge ou peut
// repartir à l'instant (guide en mission, pont qui envoie des consignes, pilotage qui a la main, flèches).
export function etatMouvement(d, local) {
  const tourne = [];
  const noter = (nom) => { if (tourne.indexOf(nom) < 0) tourne.push(nom); };
  let enMouvement = !!local;
  if (local) noter('fleches');
  if (!d) return { connu: false, enMouvement: enMouvement, tourne: tourne };
  if (d.simulation && d.simulation.en_cours) noter('simulation');
  const p = d.processus || {};
  ROLES_QUI_BOUGENT.forEach((r) => { if (p[r] && p[r].en_cours) noter(r); });
  if (d.mode) noter('navigation');
  if (d.pont && !d.pont.perime) {
    noter('pont');
    if (d.pont.etat === 'en_mouvement') enMouvement = true;
  }
  const g = d.guide;
  if (g && ETATS_EN_MISSION.indexOf(g.etat) >= 0 && !(g.age_s > 3)) {
    noter('guide');
    enMouvement = true;
  }
  if (d.maitre && d.maitre.maitre === 'pilotage') {
    noter('pilotage');
    enMouvement = true;
  }
  return { connu: true, enMouvement: enMouvement, tourne: tourne };
}

// Échap : 'arret' (envoyer l'ARRÊT), 'local' (la touche a seulement fermé un menu, une fenêtre, annulé une
// saisie ou un outil) ou 'rien' (rien ne bouge ni ne tourne : rien à arrêter). servi : la touche avait un
// usage dans la page. Le robot qui bouge l'emporte toujours (sécurité) ; sans nouvelles du serveur, on arrête.
export function decisionEchap(m, servi) {
  if (m.enMouvement) return 'arret';
  if (servi) return 'local';
  if (!m.connu || m.tourne.length) return 'arret';
  return 'rien';
}

// Le robot est-il bloqué, d'après un message de /ws/etat ? Le verrou posé par l'Atelier (champ arret), ou celui
// que le pont garde encore (champ pont, s'il est frais) : après un redémarrage de l'Atelier, le serveur a
// oublié son verrou, le pont non (revue de la vague 5)
export function verrouVu(d) {
  if (!d) return false;
  const pont = d.pont && !d.pont.perime ? !!d.pont.verrou : false;
  return !!(d.arret && d.arret.verrou) || pont;
}

async function poster(url, corps, delaiMs) {
  // délai : un serveur saturé ou une liaison coupée ne laisse pas l'ARRÊT attendre sans rien dire
  const controle = typeof AbortController !== 'undefined' ? new AbortController() : null;
  const minuterie = controle && delaiMs ? setTimeout(() => controle.abort(), delaiMs) : null;
  try {
    const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(corps || {}), signal: controle ? controle.signal : undefined });
    let d = null;
    try {
      d = await r.json();
    } catch (e) {
      d = null;
    }
    return { statut: r.status, corps: d || {} };
  } finally {
    if (minuterie) clearTimeout(minuterie);
  }
}

export function monterArret(element, options) {
  options = options || {};
  let mode = options.mode || 'simu';
  const dire = options.message || (() => {});
  let etat = 'pret';
  let enCours = 0;                 // demandes d'ARRÊT parties et pas encore revenues (pour l'aspect du bouton)
  const b = el('button', 'bouton-arret-global');
  b.type = 'button';
  b.setAttribute('data-role', 'arret');
  b.setAttribute('data-etat', 'pret');
  const texte = el('span', 'bouton-arret-texte', 'ARRÊT');
  b.appendChild(icone('arret', 22));
  b.appendChild(texte);
  element.appendChild(b);

  function majBouton() {
    b.setAttribute('data-etat', etat);
    texte.textContent = etat === 'bloque' ? 'Débloquer' : 'ARRÊT';
    b.title = etat === 'bloque'
      ? 'Le robot est bloqué : il reste immobile. Cliquez pour le laisser repartir (touche Échap : ARRÊT).'
      : 'Arrête tout de suite le robot, le guide et le pilotage (touche Échap).';
    b.setAttribute('aria-label', etat === 'bloque' ? 'Débloquer le robot' : 'ARRÊT');
  }

  function poserEtat(verrou) {
    const nouveau = verrou && mode !== 'simu' ? 'bloque' : 'pret';
    if (nouveau !== etat) {
      etat = nouveau;
      majBouton();
    }
  }

  async function arreter(raison) {
    // les écrans lâchent tout de suite ce qu'ils tiennent (manettes du pilotage, flèches) : événement de la page
    document.dispatchEvent(new CustomEvent('atelier-arret', { detail: { raison: raison || 'bouton ARRÊT' } }));
    // chaque appui part, même si le précédent attend encore sa réponse (la route est idempotente)
    enCours += 1;
    b.classList.add('appuye');
    try {
      const r = await poster('/api/arret', { mode: mode, raison: raison || 'bouton ARRÊT' }, DELAI_ARRET_MS);
      if (r.statut >= 500) throw new Error('statut ' + r.statut);
      const d = r.corps;
      const fautes = Object.keys(d.parties || {}).filter((k) => d.parties[k] && d.parties[k].ok === false)
        .map((k) => d.parties[k].detail);
      dire(d.message || 'ARRÊT envoyé.', fautes.length ? 'erreur' : 'avertissement', fautes);
      poserEtat(!!d.verrou);
      return d;
    } catch (e) {
      dire(MESSAGE_SANS_REPONSE, 'erreur');
      return null;
    } finally {
      enCours = Math.max(0, enCours - 1);
      setTimeout(() => { if (!enCours) b.classList.remove('appuye'); }, 250);
    }
  }

  async function debloquer() {
    try {
      const r = await poster('/api/arret/debloquer', {}, 5000);
      if (r.statut >= 200 && r.statut < 300) {
        dire(r.corps.message || 'Robot débloqué.', 'info');
        poserEtat(false);
      } else {
        dire(r.corps.detail || ('Déblocage refusé (' + r.statut + ').'), 'erreur');
      }
      return r.corps;
    } catch (e) {
      dire('Le serveur de l\'Atelier ne répond pas : le robot reste bloqué.', 'erreur');
      return null;
    }
  }

  let question = false;            // la confirmation de « Débloquer » est ouverte

  async function cliquer() {
    if (etat !== 'bloque') {
      arreter('bouton ARRÊT');
      return;
    }
    if (question) return;
    question = true;
    let oui = false;
    try {
      oui = await demanderConfirmation('Le robot pourra de nouveau marcher. Gardez la télécommande en main.',
        { titre: 'Débloquer le robot ?', ok: 'Débloquer', annuler: 'Rester bloqué' });
    } finally {
      question = false;
    }
    if (oui && etat === 'bloque') debloquer();
  }

  b.addEventListener('click', cliquer);
  // le verrou posé par l'Atelier, ou celui que le pont garde encore (Atelier redémarré pendant un verrou)
  const desabonner = abonner((d) => {
    if (!d || mode === 'simu') return;
    if (d.arret || d.pont) poserEtat(verrouVu(d));
  });
  majBouton();

  return {
    arreter: arreter,
    debloquer: debloquer,
    bloque: () => etat === 'bloque',
    mode: (m) => {
      mode = m;
      if (mode === 'simu') poserEtat(false);
    },
    detruire: () => {
      desabonner();
      b.remove();
    },
  };
}
