// Outils communs aux onglets de l'équipe (Personnalités, Dialogues, Caméra), vague 4, section 11.6
// du plan : lecture, vérification et enregistrement d'un fichier facultatif du lieu
// (personnalites.yaml, dialogues.yaml, camera.yaml), aide tirée des schémas, état ROS 2 de l'équipe.
// Agent Équipe.

import { api, urlLieu } from '../api.js';
import { contexte } from '../contexte.js';
import { demanderConfirmation } from '../coque/confirmation.js';
import * as F from '../formulaire.js';
import { afficherErreur, afficherMessage } from '../messages.js';

let infos = null;      // réponse de GET /api/equipe (schémas, exemples, sujets, codes…), gardée

export function copie(v) {
  return v === undefined ? undefined : JSON.parse(JSON.stringify(v));
}

export async function chargerInfos() {
  if (!infos) infos = await api.lire('/api/equipe');
  return infos;
}

// Description d'un champ dans le schéma (chemin : ['properties', 'camera', 'properties', 'ips'])
export function aide(schema, chemin) {
  let s = schema;
  for (let i = 0; i < chemin.length && s; i++) {
    s = s[chemin[i]];
    if (s && s.$ref) s = resoudre(schema, s.$ref);
  }
  return (s && s.description) || '';
}

function resoudre(schema, ref) {
  return ref.replace(/^#\//, '').split('/').reduce((s, k) => (s ? s[k] : null), schema);
}

// Âge lisible d'un message reçu par le pont ROS 2 du serveur
export function age(recu) {
  if (!recu || recu.age_recu_s === undefined) return '';
  const s = recu.age_recu_s;
  return s < 1 ? 'à l\'instant' : 'il y a ' + (s < 60 ? Math.round(s) + ' s' : Math.round(s / 60) + ' min');
}

// Liste d'erreurs et d'avertissements d'une vérification ({ok, erreurs, avertissements})
export function afficherVerification(zone, rapport, titreOk) {
  zone.innerHTML = '';
  if (!rapport) return;
  if (rapport.ok && !(rapport.avertissements || []).length) {
    zone.appendChild(F.el('p', 'rapport-ok', titreOk || 'Aucun problème trouvé.'));
    return;
  }
  [['erreurs', 'rapport-titre-erreur', 'À corriger'], ['avertissements', 'rapport-titre-avertissement', 'À vérifier']]
    .forEach((d) => {
      const liste = rapport[d[0]] || [];
      if (!liste.length) return;
      zone.appendChild(F.el('div', d[1], d[2] + ' (' + liste.length + ')'));
      const ul = F.el('ul');
      liste.forEach((m) => ul.appendChild(F.el('li', '', m)));
      zone.appendChild(ul);
    });
}

// Éditeur d'un fichier de l'équipe. quoi : personnalites, dialogues ou camera.
// racine : l'écran ; il reçoit la barre, l'aide, la zone « fichier absent », le contenu et la
// vérification. rendre(etat) remplit etat.zones.contenu à chaque changement.
// Vague 5 (section 12.2) : options.sansBarre (l'écran met ✓ Enregistrer et ✗ Annuler dans l'en-tête du
// panneau de la coque) : la barre ne garde que le titre, l'état et « Vérifier ».
// Renvoie {etat, modifier(f), rafraichir(), recharger(), enregistrer(), abandonner(), verifier(), pret, modifie()}.
export function creerEditeur(racine, quoi, options) {
  const lieu = contexte.lieu;
  const url = urlLieu(lieu) + '/' + quoi;
  const fichier = quoi + '.yaml';
  const etat = { donnees: null, existe: false, modifie: false, infos: null, zones: {}, rapport: null };
  racine.innerHTML = `
    <div class="barre">
      <div class="barre-gauche">
        <h2 class="equipe-titre" data-role="titre"></h2>
        <span class="equipe-fichier code" data-role="fichier"></span>
      </div>
      <div class="barre-droite">
        <span class="etat-enregistrement" data-role="etat"></span>
        <button type="button" class="bouton" data-role="verifier">Vérifier</button>
        <button type="button" class="bouton" data-role="defaire">Annuler les modifications</button>
        <button type="button" class="bouton bouton-principal" data-role="enregistrer">Enregistrer</button>
      </div>
    </div>
    <p class="aide" data-role="aide"></p>
    <div class="carte-section equipe-absent" data-role="absent" hidden>
      <h2 data-role="absent-titre"></h2>
      <p data-role="absent-texte"></p>
      <button type="button" class="bouton bouton-principal bouton-grand" data-role="exemple">Partir de l'exemple</button>
    </div>
    <div class="equipe-contenu" data-role="contenu"></div>
    <div class="carte-section equipe-verification" data-role="verification-cadre" hidden>
      <h2>Vérification</h2>
      <div class="rapport" data-role="verification"></div>
    </div>`;
  const $ = (r) => racine.querySelector('[data-role="' + r + '"]');
  etat.zones = { contenu: $('contenu'), verification: $('verification') };
  $('titre').textContent = options.titre;
  // le nom du fichier : en infobulle seulement (pas de note de développeur dans les titres, section 12.2)
  $('fichier').textContent = fichier;
  $('fichier').hidden = true;
  $('titre').title = 'Fichier du lieu : ' + fichier;
  $('absent-titre').textContent = options.titreAbsent || (quoi === 'camera'
    ? 'Pas encore de réglages de la caméra pour ce lieu' : 'Pas encore de ' + options.titre.toLowerCase() + ' pour ce lieu');
  $('aide').textContent = options.aide;
  $('absent-texte').textContent = options.absent;
  if (options.sansBarre) {
    $('defaire').remove();
    $('enregistrer').remove();
  }

  function majEtat() {
    const e = $('etat');
    if (!etat.existe && !etat.donnees) e.textContent = '';
    else if (etat.modifie) e.textContent = 'Modifications non enregistrées';
    else e.textContent = 'Tout est enregistré';
    e.classList.toggle('non-enregistre', etat.modifie);
    if ($('enregistrer')) $('enregistrer').disabled = !etat.donnees;
    $('verifier').disabled = !etat.donnees;
    if ($('defaire')) $('defaire').hidden = !etat.modifie || !etat.existe;
    $('absent').hidden = !!etat.donnees;
    $('contenu').hidden = !etat.donnees;
  }

  function rafraichir() {
    majEtat();
    if (etat.donnees) options.rendre(etat);
  }

  function modifier(f) {
    f(etat.donnees);
    etat.modifie = true;
    rafraichir();
  }

  function montrerRapport(rapport) {
    etat.rapport = rapport;
    $('verification-cadre').hidden = !rapport;
    afficherVerification($('verification'), rapport, 'Aucun problème trouvé dans ' + fichier + '.');
  }

  async function verifier() {
    if (!etat.donnees) return null;
    try {
      const r = await api.envoyer(url + '/verifier', etat.donnees);
      montrerRapport(r);
      return r;
    } catch (e) {
      afficherErreur(e);
      return null;
    }
  }

  async function enregistrer() {
    if (!etat.donnees) return false;
    const b = $('enregistrer') || F.el('button');
    b.disabled = true;
    try {
      const r = await api.ecrire(url, etat.donnees);
      etat.donnees = r.donnees;
      etat.existe = true;
      etat.modifie = false;
      afficherMessage(fichier + ' enregistré.', 'succes');
      montrerRapport(r.rapport ? r.rapport.equipe || r.rapport : null);
      rafraichir();
      if (options.apresEnregistrement) options.apresEnregistrement(etat);
      return true;
    } catch (e) {
      afficherErreur(e);
      if (e.erreurs && e.erreurs.length) montrerRapport({ ok: false, erreurs: e.erreurs, avertissements: [] });
      return false;
    } finally {
      majEtat();
    }
  }

  async function recharger() {
    try {
      etat.infos = await chargerInfos();
      try {
        etat.donnees = await api.lire(url);
        etat.existe = true;
      } catch (e) {
        if (e.statut !== 404) throw e;
        etat.donnees = null;
        etat.existe = false;
      }
      etat.modifie = false;
      if (options.apresChargement) await options.apresChargement(etat);
    } catch (e) {
      afficherErreur(e);
    }
    rafraichir();
  }

  async function abandonner() {
    if (!etat.modifie) return false;
    const ok = await demanderConfirmation('Abandonner les modifications et relire ' + fichier + ' ?',
      { titre: 'Annuler les modifications', ok: 'Abandonner', annuler: 'Garder', danger: true });
    if (ok) await recharger();
    return ok;
  }

  $('verifier').addEventListener('click', verifier);
  if ($('enregistrer')) $('enregistrer').addEventListener('click', enregistrer);
  if ($('defaire')) $('defaire').addEventListener('click', abandonner);
  $('exemple').addEventListener('click', () => {
    etat.donnees = copie(etat.infos.fichiers[quoi].exemple);
    if (options.depuisExemple) options.depuisExemple(etat.donnees);
    etat.modifie = true;
    rafraichir();
    afficherMessage('Exemple chargé : adaptez-le, puis « Enregistrer » écrit ' + fichier + ' dans le lieu.', 'info');
  });

  racine.classList.add('chargement');
  const pret = recharger().finally(() => racine.classList.remove('chargement'));
  return {
    etat: etat, modifier: modifier, rafraichir: rafraichir, recharger: recharger, enregistrer: enregistrer,
    abandonner: abandonner, verifier: verifier, pret: pret, modifie: () => etat.modifie,
  };
}

// Interroge GET /api/equipe/etat toutes les « periode » ms tant que l'écran est ouvert.
// Renvoie la fonction qui arrête.
export function suivreEtat(surEtat, periode) {
  let actif = true;
  let minuterie = null;
  async function tour() {
    if (!actif) return;
    try {
      surEtat(await api.lire('/api/equipe/etat'));
    } catch (e) {
      surEtat(null);
    }
    if (actif) minuterie = setTimeout(tour, periode || 1500);
  }
  tour();
  return () => {
    actif = false;
    if (minuterie) clearTimeout(minuterie);
  };
}

// Champ nombre facultatif : vide = absent du fichier. surChangement(valeur ou null).
export function champNombreFacultatif(parent, libelle, valeur, options, surChangement) {
  const c = F.el('input');
  c.type = 'number';
  c.step = options.pas === undefined ? 'any' : String(options.pas);
  if (options.min !== undefined) c.min = String(options.min);
  if (options.max !== undefined) c.max = String(options.max);
  c.value = valeur === null || valeur === undefined ? '' : String(valeur);
  if (options.indice) c.placeholder = options.indice;
  c.addEventListener('change', () => {
    const t = c.value.trim().replace(',', '.');
    if (t === '') {
      surChangement(null);
      return;
    }
    const v = parseFloat(t);
    if (!isNaN(v)) surChangement(v);
  });
  const l = F.el('label', 'champ');
  l.appendChild(F.el('span', 'champ-libelle', libelle));
  l.appendChild(c);
  if (options.unite) l.appendChild(F.el('span', 'champ-unite', options.unite));
  parent.appendChild(l);
  return c;
}

// Note d'aide sous un champ
export function note(parent, texte) {
  if (texte) F.paragraphe(parent, texte, 'panneau-note');
}
