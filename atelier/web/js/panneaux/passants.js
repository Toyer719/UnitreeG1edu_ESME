// Panneau des passants dans l'onglet Simulation (vague 4, section 11.3 du plan) : agent Passants.
// simulation.js appelle monter(element, outils) et, en fermant l'onglet, fermer() de l'objet
// renvoyé. outils : {lieu, etage, plan, carte}.
//
// Il montre, en direct (champ pietons de /ws/etat, tiré de /pietons/etat quand la simulation a des
// piétons crédibles) : chaque piéton, ce qu'il fait (il marche, s'arrête pour le robot, s'écarte...)
// et la distance bord à bord entre le robot et le piéton le plus proche (rouge : contact). Il liste
// aussi les scènes d'essai (GET /api/passants/scenes, à lancer avec g1-banc --scene ID) et les
// derniers bancs (GET /api/passants/bancs : réussite, contacts et qui les a causés).

import { api } from '../api.js';
import { abonner } from '../direct.js';

const RAYON_ROBOT = 0.26;      // m, cercle de contact du robot proxy (atelier.lieu.passants)
const SEUIL_CONTACT = 0.05;    // m bord à bord : contact

export const LIBELLES_PIETONS = {
  marche: 'marche',
  pause: 'attend',
  arret: 's\'est arrêté pour le robot',
  ecart: 's\'écarte du robot',
  pilote: 'piloté (faux visiteur)',
  fini: 'arrivé, ne bouge plus',
};

const REACTIONS = { aucune: 'ne voit pas le robot', arret: 's\'arrête', ecart: 's\'écarte' };

function el(balise, classe, texte) {
  const e = document.createElement(balise);
  if (classe) e.className = classe;
  if (texte !== undefined) e.textContent = texte;
  return e;
}

function nombre(v, chiffres) {
  return v === null || v === undefined || Number.isNaN(v) ? '—' : Number(v).toFixed(chiffres).replace('.', ',');
}

// Distance bord à bord entre le robot {x, y} et un piéton {x, y, rayon_m}
export function distanceBord(robot, p) {
  return Math.hypot(p.x - robot.x, p.y - robot.y) - RAYON_ROBOT - (p.rayon_m || 0.25);
}

export function classeDistance(d) {
  if (d === null || d === undefined) return '';
  if (d < SEUIL_CONTACT) return 'passants-contact';
  if (d < 0.2) return 'passants-pres';
  if (d < 0.6) return 'passants-moyen';
  return 'passants-loin';
}

export function monter(element, outils) {   // eslint-disable-line no-unused-vars
  element.hidden = false;
  element.innerHTML = `
    <h3 class="panneau-titre">Passants</h3>
    <div class="passants-distance" data-role="distance">Aucun piéton</div>
    <ul class="passants-liste" data-role="pietons"></ul>
    <details class="passants-details">
      <summary>Scènes d'essai</summary>
      <p class="panneau-note">Chaque scène se joue sur une copie du lieu, avec la commande indiquée
        (Gazebo et la navigation sont lancés par le banc) : résultats en CSV, avec les contacts.</p>
      <ul class="passants-scenes" data-role="scenes"><li class="panneau-note">Chargement…</li></ul>
    </details>
    <details class="passants-details">
      <summary>Derniers bancs</summary>
      <ul class="passants-bancs" data-role="bancs"><li class="panneau-note">Chargement…</li></ul>
    </details>`;
  const $ = (r) => element.querySelector('[data-role="' + r + '"]');
  let ferme = false;

  function afficherDirect(d) {
    const pietons = (d && d.pietons) || [];
    const liste = $('pietons');
    liste.textContent = '';
    if (!pietons.length) {
      $('distance').textContent = 'Aucun piéton dans la simulation';
      $('distance').className = 'passants-distance';
      return;
    }
    const robot = d.robot;
    let plusProche = null;
    pietons.forEach((p) => {
      const li = el('li', 'passants-pieton');
      const etat = p.etat ? (LIBELLES_PIETONS[p.etat] || p.etat) : '';
      li.append(el('span', 'passants-id', p.id));
      if (etat) li.append(el('span', 'passants-etat passants-etat-' + p.etat, etat));
      if (p.corps === false) li.append(el('span', 'passants-note', 'sans corps'));
      if (robot) {
        const db = distanceBord(robot, p);
        li.append(el('span', 'passants-d ' + classeDistance(db), nombre(db, 2) + ' m'));
        if (plusProche === null || db < plusProche.d) plusProche = { d: db, p };
      }
      li.title = p.reaction ? 'Réaction au robot : ' + (REACTIONS[p.reaction] || p.reaction) : '';
      liste.append(li);
    });
    const zone = $('distance');
    if (plusProche) {
      const contact = plusProche.d < SEUIL_CONTACT;
      zone.textContent = (contact ? 'Contact avec ' : 'Piéton le plus proche : ') + plusProche.p.id + ', '
        + nombre(plusProche.d, 2) + ' m bord à bord';
      zone.className = 'passants-distance ' + classeDistance(plusProche.d);
    } else {
      zone.textContent = pietons.length + ' piéton(s) ; position du robot inconnue';
      zone.className = 'passants-distance';
    }
  }

  async function chargerScenes() {
    const liste = $('scenes');
    try {
      const r = await api.lire('/api/passants/scenes');
      if (ferme) return;
      liste.textContent = '';
      r.scenes.forEach((s) => {
        const li = el('li', 'passants-scene');
        li.append(el('strong', '', s.nom));
        if (s.description) li.append(el('p', 'panneau-note', s.description));
        const seuils = [];
        const m = s.mesures || {};
        if (m.reussite_min !== undefined) seuils.push('réussite ≥ ' + Math.round(100 * m.reussite_min) + ' %');
        if (m.distance_bord_min_m !== undefined) seuils.push('≥ ' + nombre(m.distance_bord_min_m, 2) + ' m bord à bord');
        if (m.contacts_robot_max !== undefined) seuils.push('contacts causés par le robot ≤ ' + m.contacts_robot_max);
        if (m.detours_max !== undefined) seuils.push('détours ≤ ' + m.detours_max);
        if (m.duree_max_s !== undefined) seuils.push('≤ ' + m.duree_max_s + ' s');
        if (m.longueur_max_m !== undefined) seuils.push('≤ ' + m.longueur_max_m + ' m parcourus');
        const essais = s.hasard ? s.hasard + ' trajets tirés au sort'
          : s.trajets.map((t) => t.join(' → ')).join(', ') + ' × ' + s.essais;
        li.append(el('p', 'panneau-note', essais + (seuils.length ? ' ; seuils : ' + seuils.join(', ') : '')));
        li.append(el('code', 'passants-commande', s.commande));
        liste.append(li);
      });
      (r.erreurs || []).forEach((e) => liste.append(el('li', 'passants-erreur', e.fichier + ' : ' + e.detail)));
      if (!r.scenes.length && !(r.erreurs || []).length) liste.append(el('li', 'panneau-note', 'Aucune scène.'));
    } catch (e) {
      if (!ferme) liste.textContent = e.message;
    }
  }

  async function chargerBancs() {
    const liste = $('bancs');
    try {
      const r = await api.lire('/api/passants/bancs');
      if (ferme) return;
      liste.textContent = '';
      r.bancs.slice(0, 8).forEach((b) => {
        const li = el('li', 'passants-banc');
        const titre = (b.scene ? 'Scène ' + b.scene : b.nom) + ' — ' + b.date.replace('T', ' ');
        li.append(el('strong', '', titre));
        let texte = b.reussis + ' / ' + b.trajets + ' trajets réussis, ' + b.detours + ' détour(s)';
        if (b.vague4) {
          texte += ' ; ' + b.contacts + ' contact(s) (robot : ' + b.contacts_robot + ', piéton : ' + b.contacts_pieton
            + ') ; au plus près : ' + nombre(b.distance_min_bord_m, 2) + ' m bord à bord';
        }
        li.append(el('p', 'panneau-note' + (b.contacts_robot ? ' passants-contact' : ''), texte));
        liste.append(li);
      });
      if (!r.bancs.length) liste.append(el('li', 'panneau-note', 'Aucun banc dans ' + r.dossier + '.'));
    } catch (e) {
      if (!ferme) liste.textContent = e.message;
    }
  }

  const desabonner = abonner(afficherDirect);
  chargerScenes();
  chargerBancs();
  return {
    fermer: () => {
      ferme = true;
      desabonner();
    },
  };
}
