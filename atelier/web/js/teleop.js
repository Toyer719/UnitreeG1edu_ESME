// Pilotage du robot simulé avec des flèches à l'écran et au clavier : POST /api/simulation/teleop.
// Le serveur n'applique une consigne que 0,5 s (homme mort) : on la renvoie toutes les 0,2 s tant
// qu'une commande reste appuyée, puis on envoie {0, 0, 0} dès que tout est relâché.
// Clavier : ↑ ↓ avancer et reculer, ← → tourner, Q et D pas de côté (à gauche, à droite).

import { api } from './api.js';
import * as F from './formulaire.js';
import { afficherErreur, afficherMessage } from './messages.js';

export const VITESSES = { vx: 0.4, vy: 0.2, wz: 0.6 };     // m/s, m/s, rad/s (le serveur plafonne à 0,5 / 0,25 / 0,8)
export const PERIODE_TELEOP = 200;                          // ms entre deux envois de la même consigne

// Chaque commande : un sens pour vx, vy ou wz
const COMMANDES = {
  pasGauche: { texte: '⇠', titre: 'Pas à gauche (touche Q)', axe: 'vy', sens: 1 },
  avancer: { texte: '↑', titre: 'Avancer (flèche du haut)', axe: 'vx', sens: 1 },
  pasDroite: { texte: '⇢', titre: 'Pas à droite (touche D)', axe: 'vy', sens: -1 },
  gauche: { texte: '↺', titre: 'Tourner à gauche (flèche de gauche)', axe: 'wz', sens: 1 },
  reculer: { texte: '↓', titre: 'Reculer (flèche du bas)', axe: 'vx', sens: -1 },
  droite: { texte: '↻', titre: 'Tourner à droite (flèche de droite)', axe: 'wz', sens: -1 },
};
const TOUCHES = { arrowup: 'avancer', arrowdown: 'reculer', arrowleft: 'gauche', arrowright: 'droite', q: 'pasGauche', d: 'pasDroite' };

function dansUnChamp(cible) {
  return !!(cible && cible.closest && cible.closest('input, textarea, select, [contenteditable="true"]'));
}

export class Teleop {
  // element : où dessiner les six boutons. Le clavier n'est écouté qu'après activer().
  constructor(element) {
    this.element = element;
    this.appuyees = new Set();
    this.boutons = {};
    this.actif = false;
    this.enVol = false;           // une requête est en cours : on n'en empile pas d'autre
    this.minuteur = null;
    this.erreurMontree = false;
    this.avertissementMontre = false;
    this.derniereEnvoyee = null;
    const grille = F.el('div', 'teleop-grille');
    Object.keys(COMMANDES).forEach((id) => {
      const c = COMMANDES[id];
      const b = F.el('button', 'teleop-bouton', c.texte);
      b.type = 'button';
      b.title = c.titre;
      b.setAttribute('aria-label', c.titre);
      b.dataset.commande = id;
      b.addEventListener('pointerdown', (e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        try {
          b.setPointerCapture(e.pointerId);
        } catch (err) {
          // pas grave : pointerup arrivera quand même sur le bouton
        }
        this.appuyer(id);
      });
      const lacher = () => this.relacher(id);
      b.addEventListener('pointerup', lacher);
      b.addEventListener('pointercancel', lacher);
      b.addEventListener('lostpointercapture', lacher);
      b.addEventListener('contextmenu', (e) => e.preventDefault());     // appui long sur tablette
      this.boutons[id] = b;
      grille.appendChild(b);
    });
    element.appendChild(grille);
    this.etat = F.el('p', 'panneau-note teleop-etat', 'Robot à l\'arrêt.');
    element.appendChild(this.etat);
    this._clavierBas = (e) => {
      const id = TOUCHES[(e.key || '').toLowerCase()];
      if (!id || !this.actif || e.ctrlKey || e.metaKey || e.altKey || dansUnChamp(e.target)) return;
      e.preventDefault();                 // les flèches ne font pas défiler la page
      if (!e.repeat) this.appuyer(id);
    };
    this._clavierHaut = (e) => {
      const id = TOUCHES[(e.key || '').toLowerCase()];
      if (id) this.relacher(id);
    };
    this._toutLacher = () => this.toutRelacher();
    this._visibilite = () => {
      if (document.hidden) this.toutRelacher();
    };
  }

  activer() {
    if (this.actif) return;
    this.actif = true;
    window.addEventListener('keydown', this._clavierBas);
    window.addEventListener('keyup', this._clavierHaut);
    window.addEventListener('blur', this._toutLacher);
    document.addEventListener('visibilitychange', this._visibilite);
    this.element.classList.remove('teleop-inactif');
  }

  desactiver() {
    this.toutRelacher();
    this.actif = false;
    window.removeEventListener('keydown', this._clavierBas);
    window.removeEventListener('keyup', this._clavierHaut);
    window.removeEventListener('blur', this._toutLacher);
    document.removeEventListener('visibilitychange', this._visibilite);
    this.element.classList.add('teleop-inactif');
  }

  detruire() {
    this.desactiver();
    this.element.innerHTML = '';
  }

  consigne() {
    const v = { vx: 0, vy: 0, wz: 0 };
    this.appuyees.forEach((id) => {
      const c = COMMANDES[id];
      v[c.axe] += c.sens * VITESSES[c.axe];
    });
    return v;
  }

  appuyer(id) {
    if (!this.actif || this.appuyees.has(id)) return;
    this.appuyees.add(id);
    this.boutons[id].classList.add('appuye');
    this.envoyer(this.consigne());
    if (!this.minuteur) this.minuteur = setInterval(() => this.envoyer(this.consigne()), PERIODE_TELEOP);
  }

  relacher(id) {
    if (!this.appuyees.has(id)) return;
    this.appuyees.delete(id);
    this.boutons[id].classList.remove('appuye');
    if (this.appuyees.size) {
      this.envoyer(this.consigne());
      return;
    }
    clearInterval(this.minuteur);
    this.minuteur = null;
    this.erreurMontree = false;
    this.envoyer({ vx: 0, vy: 0, wz: 0 }, true);
  }

  toutRelacher() {
    Array.from(this.appuyees).forEach((id) => this.relacher(id));
  }

  // forcer : l'arrêt part même si une requête est en vol (il ne doit jamais être perdu)
  async envoyer(v, forcer) {
    const arret = !v.vx && !v.vy && !v.wz;
    if (this.enVol && !forcer) return;
    if (!arret && this.erreurMontree) return;       // erreur déjà dite : on attend que l'on relâche
    this.enVol = true;
    try {
      const r = await api.envoyer('/api/simulation/teleop', v);
      this.derniereEnvoyee = r.envoye;
      this.etat.textContent = arret ? 'Robot à l\'arrêt.' : 'Consigne : ' + texteConsigne(r.envoye) + '.';
      if (r.avertissement && !this.avertissementMontre) {
        this.avertissementMontre = true;
        afficherMessage(r.avertissement, 'avertissement');
      }
    } catch (e) {
      if (!arret && !this.erreurMontree) {
        this.erreurMontree = true;
        afficherErreur(e);
      }
      this.etat.textContent = 'Le robot ne reçoit pas les consignes (voir le message).';
    } finally {
      this.enVol = false;
      // tout a été relâché pendant que cette consigne voyageait : l'arrêt repart après elle
      if (!arret && !this.appuyees.size) this.envoyer({ vx: 0, vy: 0, wz: 0 }, true);
    }
  }
}

export function texteConsigne(v) {
  const morceaux = [];
  const f = (x) => Math.abs(x).toLocaleString('fr-FR', { maximumFractionDigits: 2 });
  if (v.vx) morceaux.push((v.vx > 0 ? 'avance' : 'recule') + ' à ' + f(v.vx) + ' m/s');
  if (v.vy) morceaux.push('pas ' + (v.vy > 0 ? 'à gauche' : 'à droite') + ' à ' + f(v.vy) + ' m/s');
  if (v.wz) morceaux.push('tourne ' + (v.wz > 0 ? 'à gauche' : 'à droite') + ' à ' + f(v.wz) + ' rad/s');
  return morceaux.join(', ') || 'arrêt';
}
