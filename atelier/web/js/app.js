// Atelier G1 : onglets, choix du lieu et de l'étage, liaison en direct avec le serveur.

import { api } from './api.js';
import { choisirEtage, choisirLieu, contexte, ecouter, souvenir, memoriser } from './contexte.js';
import { suivreConnexion, abonner } from './direct.js';
import { afficherErreur } from './messages.js';
import * as carte from './ecrans/carte.js';
import * as itineraires from './ecrans/itineraires.js';
import * as lieux from './ecrans/lieux.js';
import * as monde from './ecrans/monde.js';
import * as salles from './ecrans/salles.js';
import * as scan from './ecrans/scan.js';
import * as simulation from './ecrans/simulation.js';
import * as zones from './ecrans/zones.js';

// Dans l'ordre du travail : créer le lieu, dessiner, fabriquer la carte, placer, simuler
const ECRANS = [
  { id: 'lieux', texte: 'Lieux', module: lieux, sansLieu: true },
  { id: 'monde', texte: 'Monde', module: monde },
  { id: 'carte', texte: 'Carte', module: carte },
  { id: 'salles', texte: 'Salles', module: salles },
  { id: 'itineraires', texte: 'Itinéraires', module: itineraires },
  { id: 'zones', texte: 'Zones', module: zones },
  { id: 'simulation', texte: 'Simulation', module: simulation },
  { id: 'scan', texte: 'Scan', module: scan, sansLieu: true },
];

let ecranOuvert = null;     // {id, instance}

function $(id) {
  return document.getElementById(id);
}

function construireOnglets() {
  const nav = $('onglets');
  ECRANS.forEach((e) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'onglet';
    b.textContent = e.texte;
    b.dataset.ecran = e.id;
    b.addEventListener('click', () => ouvrirEcran(e.id));
    nav.appendChild(b);
  });
}

// Ouvre un écran ; demande confirmation s'il reste des modifications non enregistrées
function ouvrirEcran(id, forcer) {
  const def = ECRANS.find((e) => e.id === id) || ECRANS[0];
  if (ecranOuvert && !forcer && ecranOuvert.instance.modifie()) {
    if (!window.confirm('Des modifications de l\'onglet « ' + ECRANS.find((e) => e.id === ecranOuvert.id).texte
      + ' » ne sont pas enregistrées. Les abandonner ?')) return false;
  }
  if (ecranOuvert) {
    try {
      ecranOuvert.instance.fermer();
    } catch (e) {
      console.error(e);
    }
  }
  const racine = $('ecran');
  racine.innerHTML = '';
  racine.className = 'ecran ecran-' + def.id;
  document.querySelectorAll('.onglet').forEach((b) => b.classList.toggle('actif', b.dataset.ecran === def.id));
  memoriser('ecran', def.id);
  if (location.hash !== '#' + def.id) history.replaceState(null, '', '#' + def.id);
  if (!def.sansLieu && !contexte.lieu) {
    racine.innerHTML = '<div class="carte-section vide-grand"><h2>Choisissez d\'abord un lieu</h2>'
      + '<p>Ouvrez ou créez un lieu dans l\'onglet Lieux.</p></div>';
    ecranOuvert = { id: def.id, instance: { modifie: () => false, fermer: () => {} } };
    return true;
  }
  if (!def.sansLieu && !contexte.etage) {
    racine.innerHTML = '<div class="carte-section vide-grand"><h2>Ce lieu n\'a pas d\'étage</h2>'
      + '<p>Ajoutez un étage dans l\'onglet Lieux.</p></div>';
    ecranOuvert = { id: def.id, instance: { modifie: () => false, fermer: () => {} } };
    return true;
  }
  try {
    ecranOuvert = { id: def.id, instance: def.module.ouvrir(racine) };
  } catch (e) {
    afficherErreur(e);
    ecranOuvert = { id: def.id, instance: { modifie: () => false, fermer: () => {} } };
  }
  return true;
}

function remplirChoix() {
  const choixLieu = $('choix-lieu');
  const choixEtage = $('choix-etage');
  api.lire('/api/lieux').then((liste) => {
    choixLieu.innerHTML = '';
    const vide = document.createElement('option');
    vide.value = '';
    vide.textContent = liste.length ? '— choisir —' : '— aucun lieu —';
    choixLieu.appendChild(vide);
    liste.forEach((l) => {
      const o = document.createElement('option');
      o.value = l.id;
      o.textContent = l.nom + ' (' + l.id + ')';
      choixLieu.appendChild(o);
    });
    choixLieu.value = contexte.lieu || '';
  }).catch(afficherErreur);
  choixEtage.innerHTML = '';
  const info = contexte.infoLieu;
  (info ? info.etages : []).forEach((e) => {
    const o = document.createElement('option');
    o.value = e.id;
    o.textContent = e.nom;
    choixEtage.appendChild(o);
  });
  choixEtage.value = contexte.etage || '';
  choixEtage.disabled = !info;
}

function suivreLiaison() {
  const pastille = $('liaison');
  let serveurOk = false;
  let ros = null;
  const majPastille = () => {
    if (!serveurOk) {
      pastille.textContent = 'Serveur injoignable';
      pastille.className = 'liaison liaison-ko';
    } else if (ros && ros.actif) {
      pastille.textContent = 'Connecté · ROS 2 actif';
      pastille.className = 'liaison liaison-ok';
    } else {
      pastille.textContent = 'Connecté · sans ROS 2';
      pastille.className = 'liaison liaison-partielle';
      pastille.title = (ros && ros.erreur) || 'Le pont ROS 2 du serveur ne tourne pas';
    }
  };
  suivreConnexion((ok) => { serveurOk = ok; majPastille(); });
  abonner((d) => {
    const avant = JSON.stringify(ros);
    ros = d.ros;
    if (JSON.stringify(ros) !== avant) majPastille();
  });
}

async function demarrer() {
  construireOnglets();
  suivreLiaison();
  try {
    contexte.serveur = await api.lire('/api/etat');
  } catch (e) {
    afficherErreur(e);
  }
  const lieuMemorise = souvenir('lieu');
  if (lieuMemorise) {
    try {
      await choisirLieu(lieuMemorise, souvenir('etage'));
    } catch (e) {
      memoriser('lieu', null);     // lieu supprimé depuis : on repart de la liste
    }
  }
  remplirChoix();
  ecouter('lieu', () => {
    remplirChoix();
    ouvrirEcran(ecranOuvert ? ecranOuvert.id : 'lieux', true);
  });
  ecouter('aller-ecran', (id) => ouvrirEcran(id, true));
  $('choix-lieu').addEventListener('change', async (ev) => {
    const id = ev.target.value;
    if (ecranOuvert && ecranOuvert.instance.modifie() && !window.confirm('Des modifications ne sont pas enregistrées. Les abandonner ?')) {
      ev.target.value = contexte.lieu || '';
      return;
    }
    if (ecranOuvert) ecranOuvert.instance.modifie = () => false;
    try {
      await choisirLieu(id || null);
    } catch (e) {
      afficherErreur(e);
    }
  });
  $('choix-etage').addEventListener('change', (ev) => {
    if (ecranOuvert && ecranOuvert.instance.modifie() && !window.confirm('Des modifications ne sont pas enregistrées. Les abandonner ?')) {
      ev.target.value = contexte.etage || '';
      return;
    }
    if (ecranOuvert) ecranOuvert.instance.modifie = () => false;
    choisirEtage(ev.target.value);
  });
  window.addEventListener('beforeunload', (ev) => {
    if (ecranOuvert && ecranOuvert.instance.modifie()) {
      ev.preventDefault();
      ev.returnValue = '';
    }
  });
  const demande = location.hash.replace('#', '') || souvenir('ecran') || (contexte.lieu ? 'monde' : 'lieux');
  ouvrirEcran(demande, true);
}

demarrer();
