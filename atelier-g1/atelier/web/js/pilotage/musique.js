// Musique des chorégraphies (section 11.5 du plan) : un battement généré (un clic par temps, plus fort
// sur les temps forts), ou le fichier de l'utilisateur (choregraphies/musique/, jamais dans Git),
// joués par la page et calés sur le départ de la chorégraphie. Sans son possible (navigateur sans
// sortie audio, page pas encore touchée), tout le reste marche.

export class Musique {
  constructor() {
    this.contexte = null;
    this.sources = [];
    this.audio = null;
    this.minuteur = null;
  }

  _contexte() {
    if (!this.contexte) {
      const C = window.AudioContext || window.webkitAudioContext;
      if (!C) return null;
      try {
        this.contexte = new C();
      } catch (e) {
        return null;
      }
    }
    if (this.contexte.state === 'suspended') this.contexte.resume().catch(() => {});
    return this.contexte;
  }

  // Joue la musique de d à partir de l'instant t de la chorégraphie, dans « dans » secondes ;
  // vitesse : vitesse de lecture (0,5 : deux fois plus lent, le battement aussi)
  jouer(d, t, dans, vitesse) {
    this.arreter();
    vitesse = vitesse || 1;
    const m = d.musique || {};
    const decalage = m.decalage_s || 0;
    dans = Math.max(0, dans || 0);
    if (m.fichier) {
      this.audio = new Audio('/api/pilotage/musique/' + encodeURIComponent(m.fichier));
      this.audio.playbackRate = vitesse;
      const partir = () => {
        const position = t - decalage;
        if (position >= 0) this.audio.currentTime = position;
        this.audio.play().catch(() => {});
      };
      this.minuteur = setTimeout(partir, dans * 1000 + (Math.max(0, decalage - t) * 1000) / vitesse);
      return;
    }
    if (!m.battement) return;
    const c = this._contexte();
    if (!c) return;
    const periode = 60 / m.battement.bpm;
    const accent = m.battement.accent || 4;
    const debut = c.currentTime + dans;
    const premier = Math.max(0, Math.ceil((t - decalage) / periode - 1e-6));
    for (let k = premier; decalage + k * periode <= d.duree_s; k += 1) {
      const quand = debut + (decalage + k * periode - t) / vitesse;
      if (quand < c.currentTime) continue;
      this._clic(c, quand, k % accent === 0);
    }
  }

  _clic(c, quand, fort) {
    const osc = c.createOscillator();
    const gain = c.createGain();
    osc.frequency.value = fort ? 1320 : 880;
    gain.gain.setValueAtTime(fort ? 0.5 : 0.25, quand);
    gain.gain.exponentialRampToValueAtTime(0.001, quand + 0.08);
    osc.connect(gain);
    gain.connect(c.destination);
    osc.start(quand);
    osc.stop(quand + 0.1);
    this.sources.push(osc);
  }

  arreter() {
    this.sources.forEach((s) => {
      try {
        s.stop();
      } catch (e) {
        // déjà fini
      }
    });
    this.sources = [];
    if (this.minuteur) clearTimeout(this.minuteur);
    this.minuteur = null;
    if (this.audio) {
      this.audio.pause();
      this.audio = null;
    }
  }
}
