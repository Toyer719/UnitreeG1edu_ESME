// Joystick tactile du pilotage (section 11.5 du plan), utilisable au doigt sur une tablette :
// un manche pour avancer, reculer et faire des pas de côté (vx, vy), un curseur pour tourner (wz).
// Vague 5 (section 12.2, comme Unitree Explore) : disposition « double », deux manettes rondes posées sur
// la vue, celle de gauche pour avancer et faire des pas de côté, celle de droite pour tourner.
// Tant qu'un doigt (ou la souris) tient un manche, l'ordre part toutes les 0,1 s ; dès qu'on lâche,
// « lâcher » part tout de suite. Homme mort au nœud pilotage : sans ordre depuis 0,5 s, il arrête
// le robot. Les valeurs envoyées sont déjà plafonnées ; le nœud plafonne encore.

import * as F from '../formulaire.js';

const PERIODE_MS = 100;

function borne(v) {
  return Math.max(-1, Math.min(1, v));
}

export class Joystick {
  // element : le conteneur ; limites : {vx, vy, wz} ; envoyer(message) : vers le WebSocket ;
  // options : {disposition: 'double'} (deux manettes rondes) ; sans : le manche et le curseur d'avant
  constructor(element, limites, envoyer, options) {
    options = options || {};
    this.limites = Object.assign({}, limites);
    this.envoyer = envoyer;
    this.manche = { x: 0, y: 0, tenu: false };
    this.rotation = { x: 0, tenu: false };
    this.minuteur = null;
    this.actif = true;
    this.double = options.disposition === 'double';
    const cadre = F.el('div', 'joystick' + (this.double ? ' joystick-double' : ''));
    this.pave = F.el('div', 'joystick-pave');
    this.pave.setAttribute('role', 'application');
    this.pave.setAttribute('aria-label', 'Manche : avancer, reculer, pas de côté');
    this.bouton = F.el('div', 'joystick-bouton');
    this.pave.appendChild(this.bouton);
    ['avant', 'arriere', 'gauche', 'droite'].forEach((s) => this.pave.appendChild(F.el('span', 'joystick-repere joystick-' + s)));
    this.curseur = F.el('div', 'joystick-rotation');
    this.curseur.setAttribute('aria-label', 'Tourner à gauche ou à droite');
    this.poignee = F.el('div', 'joystick-poignee');
    this.curseur.appendChild(this.poignee);
    if (this.double) {
      ['gauche', 'droite'].forEach((s) => this.curseur.appendChild(F.el('span', 'joystick-repere joystick-' + s)));
      this.curseur.appendChild(F.el('span', 'joystick-texte-rotation', '↺ ↻'));
    } else {
      this.curseur.appendChild(F.el('span', 'joystick-texte-rotation', '↺  tourner  ↻'));
    }
    cadre.appendChild(this.pave);
    cadre.appendChild(this.curseur);
    this.lecture = F.el('p', 'panneau-note joystick-lecture', 'Robot à l\'arrêt.');
    element.appendChild(cadre);
    element.appendChild(this.lecture);
    this.cadre = cadre;
    this._suivre(this.pave, (e, r) => {
      this.manche.x = borne((e.clientX - (r.left + r.width / 2)) / (r.width / 2));
      this.manche.y = borne((e.clientY - (r.top + r.height / 2)) / (r.height / 2));
      const n = Math.hypot(this.manche.x, this.manche.y);
      if (n > 1) { this.manche.x /= n; this.manche.y /= n; }
    }, (tenu) => { this.manche.tenu = tenu; if (!tenu) { this.manche.x = 0; this.manche.y = 0; } });
    this._suivre(this.curseur, (e, r) => {
      this.rotation.x = borne((e.clientX - (r.left + r.width / 2)) / (r.width / 2));
    }, (tenu) => { this.rotation.tenu = tenu; if (!tenu) this.rotation.x = 0; });
    this._perte = () => this.toutLacher();
    window.addEventListener('blur', this._perte);
    document.addEventListener('visibilitychange', this._perte);
    this.dessiner();
  }

  _suivre(zone, bouger, tenir) {
    zone.addEventListener('pointerdown', (e) => {
      if (e.button !== undefined && e.button !== 0 && e.pointerType === 'mouse') return;
      e.preventDefault();
      try {
        zone.setPointerCapture(e.pointerId);
      } catch (err) {
        // pas grave : pointerup arrivera quand même
      }
      tenir(true);
      bouger(e, zone.getBoundingClientRect());
      this.changement();
    });
    zone.addEventListener('pointermove', (e) => {
      if (!zone.hasPointerCapture || !zone.hasPointerCapture(e.pointerId)) return;
      bouger(e, zone.getBoundingClientRect());
      this.changement();
    });
    const lacher = () => {
      tenir(false);
      this.changement();
    };
    zone.addEventListener('pointerup', lacher);
    zone.addEventListener('pointercancel', lacher);
    zone.addEventListener('lostpointercapture', lacher);
    zone.addEventListener('contextmenu', (e) => e.preventDefault());
  }

  consigne() {
    // manche vers le haut : avancer ; vers la gauche : pas à gauche (vy > 0) ; curseur à gauche : wz > 0
    const arrondi = (v) => Math.round(v * 1000) / 1000;
    return {
      vx: arrondi(-this.manche.y * this.limites.vx),
      vy: arrondi(-this.manche.x * this.limites.vy),
      wz: arrondi(-this.rotation.x * this.limites.wz),
    };
  }

  tenu() {
    return this.actif && (this.manche.tenu || this.rotation.tenu);
  }

  changement() {
    this.dessiner();
    if (this.tenu()) {
      if (!this.minuteur) {
        this.envoyer(this.consigne());
        this.minuteur = setInterval(() => {
          if (this.tenu()) this.envoyer(this.consigne());
        }, PERIODE_MS);
      }
    } else if (this.minuteur) {
      clearInterval(this.minuteur);
      this.minuteur = null;
      this.envoyer({ lacher: true });
    }
  }

  toutLacher() {
    this.manche = { x: 0, y: 0, tenu: false };
    this.rotation = { x: 0, tenu: false };
    this.changement();
  }

  dessiner() {
    this.bouton.style.left = (50 + this.manche.x * 38) + '%';
    this.bouton.style.top = (50 + this.manche.y * 38) + '%';
    this.poignee.style.left = (50 + this.rotation.x * (this.double ? 34 : 42)) + '%';
    this.pave.classList.toggle('tenu', this.manche.tenu);
    this.curseur.classList.toggle('tenu', this.rotation.tenu);
    const c = this.consigne();
    const v = (x) => x.toFixed(2).replace('.', ',');
    if (this.double) {
      this.lecture.textContent = this.tenu() ? v(c.vx) + ' m/s · ' + v(c.vy) + ' m/s · ' + v(c.wz) + ' rad/s' : '';
    } else {
      this.lecture.textContent = this.tenu()
        ? 'Ordre : avance ' + v(c.vx) + ' m/s, côté ' + v(c.vy) + ' m/s, rotation ' + v(c.wz) + ' rad/s'
        : 'Lâché : le robot s\'arrête. (Plafonds : ' + this.limites.vx + ' m/s, ' + this.limites.vy + ' m/s, ' + this.limites.wz + ' rad/s.)';
    }
  }

  activer(oui) {
    this.actif = !!oui;
    if (this.cadre) this.cadre.classList.toggle('inactif', !this.actif);
    if (!this.actif) this.toutLacher();
  }

  fermer() {
    this.toutLacher();
    window.removeEventListener('blur', this._perte);
    document.removeEventListener('visibilitychange', this._perte);
  }
}
