// Bouton ARRÊT unique de la barre d'outils, dans les deux modes, et la touche Échap (la coque l'appelle) :
// POST /api/arret, puis « Débloquer » (POST /api/arret/debloquer) quand un verrou est posé (vague 5,
// section 12.4 du plan). Module de l'agent Coquille.
//
// monterArret(element, {mode, message}) → {arreter(raison), debloquer(), mode(m), detruire()}
//   mode : 'simu' | 'reel' | 'repetition' ; message(texte, genre, details) : la barre d'état.
// Événement : « atelier-arret » sur document, dès l'appui (les écrans lâchent leurs manettes).
// Repère : [data-role=arret] (data-etat=pret|bloque). Le verrou n'existe qu'en Réel et en répétition :
// son état vient de la réponse de l'ARRÊT et du champ arret de /ws/etat. « Débloquer » demande une
// confirmation dans la page : un double clic affolé sur ARRÊT ne relâche jamais le robot.

import { abonner } from '../direct.js';
import { demanderConfirmation } from './confirmation.js';
import { icone } from './icones.js';

function el(balise, classe, texte) {
  const e = document.createElement(balise);
  if (classe) e.className = classe;
  if (texte !== undefined && texte !== null) e.textContent = texte;
  return e;
}

async function poster(url, corps) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(corps || {}) });
  let d = null;
  try {
    d = await r.json();
  } catch (e) {
    d = null;
  }
  return { statut: r.status, corps: d || {} };
}

export function monterArret(element, options) {
  options = options || {};
  let mode = options.mode || 'simu';
  const dire = options.message || (() => {});
  let etat = 'pret';
  let enCours = false;
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
    // les écrans lâchent tout de suite ce qu'ils tiennent (manettes du pilotage, aperçu) : événement de la page
    document.dispatchEvent(new CustomEvent('atelier-arret', { detail: { raison: raison || 'bouton ARRÊT' } }));
    if (enCours) return null;
    enCours = true;
    b.classList.add('appuye');
    try {
      const r = await poster('/api/arret', { mode: mode, raison: raison || 'bouton ARRÊT' });
      const d = r.corps;
      const fautes = Object.keys(d.parties || {}).filter((k) => d.parties[k].ok === false)
        .map((k) => d.parties[k].detail);
      dire(d.message || 'ARRÊT envoyé.', fautes.length ? 'erreur' : 'avertissement', fautes);
      poserEtat(!!d.verrou);
      return d;
    } catch (e) {
      dire('ARRÊT : le serveur de l\'Atelier ne répond pas. Arrêtez le robot avec la télécommande.', 'erreur');
      return null;
    } finally {
      enCours = false;
      setTimeout(() => b.classList.remove('appuye'), 250);
    }
  }

  async function debloquer() {
    try {
      const r = await poster('/api/arret/debloquer', {});
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
  const desabonner = abonner((d) => {
    if (d && d.arret && mode !== 'simu') poserEtat(!!d.arret.verrou);
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
