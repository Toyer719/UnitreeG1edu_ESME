// Ligne de temps de l'éditeur de chorégraphies (section 11.5 du plan) : une piste par sorte
// d'événement (poses des bras, pas, gestes, LED, paroles), les rampes du poids des bras, la grille
// du battement et la tête de lecture. Cliquer choisit un élément ou place la tête de lecture ;
// glisser un élément change son temps (calé au battement si l'aimant est mis).

const PISTES = [
  { id: 'bras', texte: 'Bras' }, { id: 'pas', texte: 'Pas' }, { id: 'gestes', texte: 'Gestes' },
  { id: 'led', texte: 'LED' }, { id: 'paroles', texte: 'Paroles' },
];
const MARGE_GAUCHE = 70;
const HAUTEUR_PISTE = 30;
const HAUT = 22;

export class LigneTemps {
  // element : conteneur ; rappels : {choisir(choix), temps(t), modifie()}
  constructor(element, rappels) {
    this.rappels = rappels || {};
    this.d = null;
    this.t = 0;
    this.choix = null;              // {piste, index}
    this.aimant = true;
    this.toile = document.createElement('canvas');
    this.toile.className = 'ligne-temps';
    this.toile.setAttribute('aria-label', 'Ligne de temps de la chorégraphie');
    this.toile.style.height = (HAUT + HAUTEUR_PISTE * PISTES.length + 6) + 'px';
    element.appendChild(this.toile);
    this.contexte = this.toile.getContext('2d');
    this.glisse = null;
    this.toile.addEventListener('pointerdown', (e) => this._appui(e));
    this.toile.addEventListener('pointermove', (e) => this._bouger(e));
    const fin = () => {
      if (this.glisse && this.glisse.bouge && this.rappels.modifie) this.rappels.modifie();
      this.glisse = null;
    };
    this.toile.addEventListener('pointerup', fin);
    this.toile.addEventListener('pointercancel', fin);
    this.observateur = new ResizeObserver(() => this.dessiner());
    this.observateur.observe(element);
  }

  definir(d) {
    this.d = d;
    if (this.choix && !this._element(this.choix)) this.choix = null;
    this.dessiner();
  }

  temps(t) {
    this.t = t;
    this.dessiner();
  }

  choisir(choix) {
    this.choix = choix;
    this.dessiner();
  }

  _largeur() {
    return this.toile.clientWidth || 600;
  }

  _x(t) {
    const l = this._largeur() - MARGE_GAUCHE - 10;
    return MARGE_GAUCHE + (t / Math.max(1, this.d.duree_s)) * l;
  }

  _t(x) {
    const l = this._largeur() - MARGE_GAUCHE - 10;
    return Math.max(0, Math.min(this.d.duree_s, ((x - MARGE_GAUCHE) / l) * this.d.duree_s));
  }

  _liste(piste) {
    if (!this.d) return [];
    if (piste === 'bras') return (this.d.bras && this.d.bras.poses) || [];
    return this.d[piste] || [];
  }

  _element(choix) {
    return this._liste(choix.piste)[choix.index];
  }

  _caler(t) {
    const m = this.d.musique || {};
    if (this.aimant && m.battement && m.battement.bpm) {
      const demi = 30 / m.battement.bpm;
      const decalage = m.decalage_s || 0;
      return Math.round(((t - decalage) / demi)) * demi + decalage;
    }
    return Math.round(t * 20) / 20;
  }

  _trouver(x, y) {
    const rang = Math.floor((y - HAUT) / HAUTEUR_PISTE);
    if (rang < 0 || rang >= PISTES.length) return null;
    const piste = PISTES[rang].id;
    const liste = this._liste(piste);
    let meilleur = null;
    liste.forEach((e, i) => {
      const x0 = this._x(e.t);
      const x1 = piste === 'pas' ? this._x(e.t + e.duree_s) : x0;
      const ecart = x < x0 ? x0 - x : (x > x1 ? x - x1 : 0);
      if (ecart <= 7 && (!meilleur || ecart < meilleur.ecart)) meilleur = { piste, index: i, ecart };
    });
    return meilleur ? { piste: meilleur.piste, index: meilleur.index } : { piste, index: null };
  }

  _appui(e) {
    if (!this.d) return;
    const r = this.toile.getBoundingClientRect();
    const x = e.clientX - r.left;
    const y = e.clientY - r.top;
    const trouve = this._trouver(x, y);
    if (trouve && trouve.index !== null) {
      this.choix = { piste: trouve.piste, index: trouve.index };
      const el = this._element(this.choix);
      this.glisse = { decalage: this._t(x) - el.t, bouge: false };
      try {
        this.toile.setPointerCapture(e.pointerId);
      } catch (err) {
        // pas grave
      }
      if (this.rappels.choisir) this.rappels.choisir(this.choix);
    } else {
      const t = this._t(x);
      if (this.rappels.temps) this.rappels.temps(t);
      if (trouve && this.rappels.choisir) this.rappels.choisir({ piste: trouve.piste, index: null, t });
    }
    this.dessiner();
  }

  _bouger(e) {
    if (!this.glisse || !this.choix) return;
    const r = this.toile.getBoundingClientRect();
    const el = this._element(this.choix);
    if (!el) return;
    const t = this._caler(this._t(e.clientX - r.left) - this.glisse.decalage);
    if (Math.abs(t - el.t) < 1e-6) return;
    el.t = Math.max(0, Math.round(t * 1000) / 1000);
    this.glisse.bouge = true;
    if (this.choix.piste === 'bras') {
      const liste = this._liste('bras');
      liste.sort((a, b) => a.t - b.t);
      this.choix.index = liste.indexOf(el);
    }
    this.dessiner();
  }

  dessiner() {
    if (!this.d) return;
    const c = this.contexte;
    const r = Math.min(window.devicePixelRatio || 1, 2);
    const l = this._largeur();
    const h = HAUT + HAUTEUR_PISTE * PISTES.length + 6;
    if (this.toile.width !== Math.round(l * r)) this.toile.width = Math.round(l * r);
    if (this.toile.height !== Math.round(h * r)) this.toile.height = Math.round(h * r);
    c.setTransform(r, 0, 0, r, 0, 0);
    c.clearRect(0, 0, l, h);
    c.font = '12px system-ui, sans-serif';
    const d = this.d;
    // grille du battement et secondes
    const m = d.musique || {};
    if (m.battement && m.battement.bpm) {
      const periode = 60 / m.battement.bpm;
      const accent = m.battement.accent || 4;
      for (let k = 0; ; k += 1) {
        const t = (m.decalage_s || 0) + k * periode;
        if (t > d.duree_s) break;
        if (t < 0) continue;
        c.strokeStyle = k % accent === 0 ? '#c3c9d1' : '#eceff3';
        c.beginPath();
        c.moveTo(this._x(t), HAUT);
        c.lineTo(this._x(t), h);
        c.stroke();
      }
    }
    c.fillStyle = '#5b6573';
    for (let s = 0; s <= d.duree_s; s += (d.duree_s > 40 ? 5 : 2)) c.fillText(s + ' s', this._x(s) - 6, 14);
    PISTES.forEach((p, i) => {
      const y = HAUT + i * HAUTEUR_PISTE;
      c.fillStyle = i % 2 ? '#fafbfc' : '#f3f5f8';
      c.fillRect(MARGE_GAUCHE, y, l - MARGE_GAUCHE - 10, HAUTEUR_PISTE);
      c.fillStyle = '#1d2430';
      c.fillText(p.texte, 8, y + 19);
    });
    // rampes du poids des bras
    if (d.bras && d.bras.poses && d.bras.poses.length) {
      const rampe = d.bras.rampe_s === undefined ? 1 : d.bras.rampe_s;
      c.fillStyle = 'rgba(31, 111, 235, 0.12)';
      c.fillRect(this._x(0), HAUT, this._x(rampe) - this._x(0), HAUTEUR_PISTE);
      c.fillRect(this._x(d.duree_s - rampe), HAUT, this._x(d.duree_s) - this._x(d.duree_s - rampe), HAUTEUR_PISTE);
    }
    const estChoisi = (piste, i) => this.choix && this.choix.piste === piste && this.choix.index === i;
    this._liste('bras').forEach((e, i) => {
      const x = this._x(e.t);
      const y = HAUT + HAUTEUR_PISTE / 2;
      c.fillStyle = estChoisi('bras', i) ? '#1f6feb' : '#2e7d32';
      c.beginPath();
      c.moveTo(x, y - 8); c.lineTo(x + 7, y); c.lineTo(x, y + 8); c.lineTo(x - 7, y); c.closePath();
      c.fill();
    });
    this._liste('pas').forEach((e, i) => {
      const y = HAUT + HAUTEUR_PISTE + 5;
      c.fillStyle = estChoisi('pas', i) ? '#1f6feb' : '#b26a00';
      c.fillRect(this._x(e.t), y, Math.max(3, this._x(e.t + e.duree_s) - this._x(e.t)), HAUTEUR_PISTE - 10);
    });
    this._liste('gestes').forEach((e, i) => {
      const x = this._x(e.t);
      c.fillStyle = estChoisi('gestes', i) ? '#1f6feb' : '#6b7280';
      c.fillRect(x - 5, HAUT + 2 * HAUTEUR_PISTE + 8, 10, 14);
    });
    this._liste('led').forEach((e, i) => {
      const x = this._x(e.t);
      c.fillStyle = 'rgb(' + e.r + ',' + e.g + ',' + e.b + ')';
      c.strokeStyle = estChoisi('led', i) ? '#1f6feb' : '#1d2430';
      c.lineWidth = estChoisi('led', i) ? 3 : 1;
      c.fillRect(x - 6, HAUT + 3 * HAUTEUR_PISTE + 8, 12, 14);
      c.strokeRect(x - 6, HAUT + 3 * HAUTEUR_PISTE + 8, 12, 14);
      c.lineWidth = 1;
    });
    this._liste('paroles').forEach((e, i) => {
      const x = this._x(e.t);
      const y = HAUT + 4 * HAUTEUR_PISTE + 8;
      c.fillStyle = estChoisi('paroles', i) ? '#1f6feb' : '#7a4fb5';
      c.beginPath();
      c.moveTo(x, y); c.lineTo(x + 10, y + 7); c.lineTo(x, y + 14); c.closePath();
      c.fill();
      c.fillStyle = '#1d2430';
      c.fillText(String(e.texte).slice(0, 18), x + 12, y + 12);
    });
    // tête de lecture
    c.strokeStyle = '#c62828';
    c.lineWidth = 2;
    c.beginPath();
    c.moveTo(this._x(this.t), HAUT - 4);
    c.lineTo(this._x(this.t), h);
    c.stroke();
    c.lineWidth = 1;
  }

  fermer() {
    this.observateur.disconnect();
  }
}
