// Lieu et étage choisis, partagés par tous les écrans, avec une mémoire dans le navigateur
// (le dernier lieu ouvert revient au rechargement de la page).

import { api, urlLieu } from './api.js';

export const contexte = {
  lieu: null,        // id du lieu choisi
  etage: null,       // id de l'étage choisi
  infoLieu: null,    // réponse de GET /api/lieux/{id}
  serveur: null,     // réponse de GET /api/etat
};

const ecouteurs = {};

export function ecouter(evenement, fonction) {
  (ecouteurs[evenement] = ecouteurs[evenement] || []).push(fonction);
}

export function emettre(evenement, donnees) {
  (ecouteurs[evenement] || []).forEach((f) => f(donnees));
}

export function memoriser(cle, valeur) {
  try {
    if (valeur === null || valeur === undefined) localStorage.removeItem('atelier.' + cle);
    else localStorage.setItem('atelier.' + cle, valeur);
  } catch (e) {
    // navigation privée ou stockage bloqué : on s'en passe
  }
}

export function souvenir(cle) {
  try {
    return localStorage.getItem('atelier.' + cle);
  } catch (e) {
    return null;
  }
}

// Choisit un lieu (et un étage : celui demandé, sinon le premier). Prévient les écrans.
export async function choisirLieu(id, etage) {
  if (!id) {
    contexte.lieu = contexte.etage = contexte.infoLieu = null;
    memoriser('lieu', null);
    emettre('lieu');
    return;
  }
  const info = await api.lire(urlLieu(id));
  contexte.lieu = id;
  contexte.infoLieu = info;
  const ids = info.etages.map((e) => e.id);
  contexte.etage = ids.indexOf(etage) >= 0 ? etage : (ids[0] || null);
  memoriser('lieu', id);
  memoriser('etage', contexte.etage);
  emettre('lieu');
}

export function choisirEtage(etage) {
  contexte.etage = etage;
  memoriser('etage', etage);
  emettre('lieu');
}

// Relit la fiche du lieu courant (après une création de carte, un ajout d'étage...)
export async function rechargerLieu() {
  if (!contexte.lieu) return null;
  contexte.infoLieu = await api.lire(urlLieu(contexte.lieu));
  emettre('info-lieu');
  return contexte.infoLieu;
}

export function etageCourant() {
  if (!contexte.infoLieu) return null;
  return contexte.infoLieu.etages.find((e) => e.id === contexte.etage) || null;
}
