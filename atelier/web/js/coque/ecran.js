// Outils communs aux écrans de la coque (vague 5, section 12.2 du plan) : un écran reçoit
// ouvrir(racine, options) ; preparerEcran donne la vue, le panneau et l'interface de la coque, et
// fabrique tout cela dans la racine quand l'écran est ouvert seul (sans coque : essais, anciens appels).
// Module de l'agent Coquille.

import * as F from '../formulaire.js';
import { afficherMessage } from '../messages.js';
import { demanderConfirmation, demanderSaisie } from './confirmation.js';
import { construireEntete, ouvrirPanneau } from './panneau.js';

const RIEN = () => {};

// Interface de coque minimale, quand l'écran est ouvert seul
function coqueSeule() {
  return {
    mode: 'simu',
    confirmer: (texte, o) => demanderConfirmation(texte, o),
    saisir: (texte, o) => demanderSaisie(texte, o),
    message: (texte, genre, details, sortie) => afficherMessage(texte, genre, details, sortie),
    pleinEcran: RIEN, ouvrirCommande: () => false, choisirVue: () => 'plan', vue: () => 'plan',
    surVue: () => RIEN, barreEtat: null, activer: RIEN, griser: RIEN, libelle: RIEN, menu: RIEN, coche: RIEN,
    cases: () => ({ accompagner: false, retour: true, joysticks: true }), aide: RIEN, lieuModifie: RIEN,
    choisirDansArbre: RIEN, carte3d: () => null, telecommande: () => false, noterTelecommande: RIEN, arret: RIEN,
    coordonnees: RIEN,
  };
}

// {vue, panneau, coque, mode, commande, valeur, carte3d} : vue = l'élément où l'écran dessine sa carte ou sa
// page ; panneau = le corps du panneau de tâches. Ouvert seul : deux colonnes fabriquées dans la racine.
export function preparerEcran(racine, options) {
  options = options || {};
  const coque = Object.assign(coqueSeule(), options.coque || {});
  if (options.panneau) {
    return { vue: racine, panneau: options.panneau, coque: coque, mode: options.mode || coque.mode || 'simu',
      commande: options.commande || null, valeur: options.valeur, carte3d: options.carte3d || null };
  }
  racine.textContent = '';
  racine.classList.add('ecran-seul');
  const vue = F.el('div', 'ecran-seul-vue');
  const panneau = F.el('aside', 'panneau');
  panneau.setAttribute('data-role', 'panneau');
  const corps = F.el('div', 'panneau-corps');
  corps.setAttribute('data-role', 'panneau-corps');
  panneau.appendChild(corps);
  construireEntete(panneau, corps);
  racine.appendChild(vue);
  racine.appendChild(panneau);
  return { vue: vue, panneau: corps, coque: coque, mode: options.mode || 'simu', commande: options.commande || null,
    valeur: options.valeur, carte3d: options.carte3d || null };
}

// Panneau d'un écran d'édition : titre, ✓ Enregistrer et ✗ Annuler (actifs s'il y a des modifications)
export function panneauEdition(element, titre, aide, actions) {
  return ouvrirPanneau(element, {
    titre: titre, aide: aide,
    ok: { texte: 'Enregistrer', action: actions.enregistrer, actif: actions.modifie(), titre: 'Enregistrer (Ctrl+S)' },
    annuler: { texte: 'Annuler', action: actions.annuler, actif: actions.modifie(),
      titre: 'Abandonner les modifications non enregistrées' },
  });
}

// Bloc repliable « Avancé » dans un panneau (identifiants, réglages rares)
export function blocAvance(parent, titre) {
  const d = F.el('details', 'bloc-avance');
  d.appendChild(F.el('summary', '', titre || 'Avancé'));
  const corps = F.el('div', 'bloc-avance-corps');
  d.appendChild(corps);
  parent.appendChild(d);
  return corps;
}

// Section titrée d'un panneau (data-section : repère des tests et des commandes Avancé)
export function section(parent, titre, nom) {
  const s = F.el('section', 'section-panneau');
  if (nom) s.setAttribute('data-section', nom);
  if (titre) s.appendChild(F.el('h3', 'panneau-titre', titre));
  parent.appendChild(s);
  return s;
}
