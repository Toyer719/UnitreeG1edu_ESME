// Écran Zones : polygones interdits (rouge : le robot n'y va jamais) et lents (orange : le
// robot y roule doucement). Clic pour chaque sommet, puis « Terminer la zone ».

import { api, urlLieu } from '../api.js';
import { contexte } from '../contexte.js';
import * as F from '../formulaire.js';
import * as G from '../geometrie.js';
import { afficherErreur, afficherMessage, afficherRapport } from '../messages.js';
import { creerPlan, ll, lls, suivrePointeur } from '../plan.js';

const L = window.L;
const PAS = 0.25;

const OUTILS = [
  { id: 'choisir', texte: 'Choisir', aide: "Cliquez dans une zone pour la modifier ; faites glisser ses sommets pour changer sa forme." },
  { id: 'interdite', texte: 'Zone interdite', aide: "Cliquez chaque coin de la zone où le robot ne doit jamais aller (escalier, local technique...), puis « Terminer la zone »." },
  { id: 'lente', texte: 'Zone lente', aide: "Cliquez chaque coin de la zone où le robot doit ralentir (hall, sortie de classe...), puis « Terminer la zone »." },
];

export function ouvrir(racine) {
  const lieu = contexte.lieu;
  const etage = contexte.etage;
  const etat = { zones: { interdites: [], lentes: [] }, outil: 'choisir', choisi: null, trace: null, vitesse: 0.25, modifie: false };

  racine.innerHTML = `
    <div class="barre">
      <div class="barre-gauche" data-role="outils"></div>
      <div class="barre-options" data-role="options"></div>
      <div class="barre-droite">
        <button type="button" class="bouton bouton-principal" data-role="enregistrer">Enregistrer les zones</button>
        <span class="etat-enregistrement" data-role="etat"></span>
      </div>
    </div>
    <p class="aide" data-role="aide"></p>
    <div class="espace-deux">
      <div class="plan" data-role="plan"></div>
      <div class="cote cote-etroit"><div class="panneau" data-role="panneau"></div></div>
    </div>`;
  const $ = (r) => racine.querySelector('[data-role="' + r + '"]');
  const plan = creerPlan($('plan'));
  const carte = plan.carte;
  const calque = L.layerGroup().addTo(carte);
  const calqueTrace = L.layerGroup().addTo(carte);
  const outils = F.barreOutils($('outils'), OUTILS, etat.outil, choisirOutil);

  const liste = (genre) => (genre === 'interdite' ? etat.zones.interdites : etat.zones.lentes);
  const zoneChoisie = () => (etat.choisi ? liste(etat.choisi.genre)[etat.choisi.indice] || null : null);

  function modifier(f) {
    f();
    etat.modifie = true;
    rafraichir();
  }

  function dessiner() {
    calque.clearLayers();
    ['interdite', 'lente'].forEach((genre) => {
      liste(genre).forEach((z, i) => {
        if (z.etage !== etage) return;
        const choisie = etat.choisi && etat.choisi.genre === genre && etat.choisi.indice === i;
        const poly = L.polygon(lls(z.polygone), { className: 'zone zone-' + genre + (choisie ? ' choisi' : '') });
        const titre = (genre === 'interdite' ? 'Interdite' : 'Lente, ' + G.nb(z.vitesse_max, 2) + ' m/s') + (z.nom ? ' : ' + z.nom : '');
        poly.bindTooltip(titre, { sticky: true });
        poly.on('click', (e) => {
          if (etat.outil !== 'choisir') return;
          L.DomEvent.stopPropagation(e);
          etat.choisi = { genre: genre, indice: i };
          rafraichir();
        });
        poly.addTo(calque);
        if (choisie) {
          z.polygone.forEach((p, k) => {
            const sommet = L.marker(ll(p[0], p[1]), {
              icon: L.divIcon({ className: 'sommet', iconSize: [14, 14], iconAnchor: [7, 7] }), draggable: true, keyboard: false,
            });
            sommet.on('drag', () => {
              const q = sommet.getLatLng();
              const pts = z.polygone.slice();
              pts[k] = [q.lng, q.lat];
              poly.setLatLngs(lls(pts));
            });
            sommet.on('dragend', () => {
              const q = sommet.getLatLng();
              modifier(() => { z.polygone[k] = G.accrocherPoint([q.lng, q.lat], PAS); });
            });
            sommet.addTo(calque);
          });
        }
      });
    });
  }

  function dessinerTrace(p) {
    calqueTrace.clearLayers();
    const t = etat.trace;
    if (p && etat.outil !== 'choisir') L.circleMarker(ll(p[0], p[1]), { radius: 4, className: 'curseur-grille', interactive: false }).addTo(calqueTrace);
    if (!t) return;
    const pts = t.points.concat(p ? [p] : []);
    if (pts.length > 1) L.polygon(lls(pts), { className: 'zone zone-' + t.genre + ' trace', interactive: false }).addTo(calqueTrace);
    t.points.forEach((q) => L.circleMarker(ll(q[0], q[1]), { radius: 5, className: 'point-trace', interactive: false }).addTo(calqueTrace));
  }

  function terminerZone() {
    const t = etat.trace;
    if (!t) return;
    if (t.points.length < 3) {
      afficherMessage('Une zone a besoin d\'au moins trois coins : cliquez encore.', 'avertissement');
      return;
    }
    const z = { etage: etage, polygone: t.points, nom: '' };
    if (t.genre === 'lente') z.vitesse_max = etat.vitesse;
    modifier(() => {
      liste(t.genre).push(z);
      etat.choisi = { genre: t.genre, indice: liste(t.genre).length - 1 };
    });
    etat.trace = null;
    dessinerTrace(null);
    choisirOutil('choisir');
  }

  const arreterPointeur = suivrePointeur(plan, {
    debut: () => etat.outil !== 'choisir',
    survol: (p) => { if (etat.outil !== 'choisir') dessinerTrace(G.accrocherPoint(p, PAS)); },
    deplacer: (p) => dessinerTrace(G.accrocherPoint(p, PAS)),
    fin: (p) => {
      const q = G.accrocherPoint(p, PAS);
      if (!etat.trace) etat.trace = { genre: etat.outil, points: [] };
      const pts = etat.trace.points;
      if (pts.length >= 3 && G.distance(pts[0], q) < 1e-6) {
        terminerZone();         // clic sur le premier coin : la zone se ferme
        return;
      }
      if (pts.length && G.distance(pts[pts.length - 1], q) < 1e-6) return;
      pts.push(q);
      dessinerTrace(q);
      majOptions();
    },
    annuler: () => dessinerTrace(null),
  });

  carte.on('click', () => {
    if (etat.outil === 'choisir' && etat.choisi) {
      etat.choisi = null;
      rafraichir();
    }
  });

  function choisirOutil(id) {
    etat.outil = id;
    etat.trace = null;
    outils.choisir(id);
    plan.cadre.classList.toggle('dessin', id !== 'choisir');
    if (id === 'choisir') carte.dragging.enable();
    else carte.dragging.disable();
    $('aide').textContent = OUTILS.find((o) => o.id === id).aide;
    dessinerTrace(null);
    majOptions();
    rafraichir();
  }

  function majOptions() {
    const z = $('options');
    z.innerHTML = '';
    if (etat.outil === 'choisir') return;
    if (etat.outil === 'lente') {
      F.champNombre(z, 'Vitesse maximale', etat.vitesse, { pas: 0.05, min: 0.05, max: 1, unite: 'm/s' }, (v) => { etat.vitesse = v; });
    }
    const n = etat.trace ? etat.trace.points.length : 0;
    F.bouton(z, 'Terminer la zone (' + n + ' coin' + (n > 1 ? 's' : '') + ')', terminerZone, 'bouton bouton-principal').disabled = n < 3;
    F.bouton(z, 'Abandonner', () => { etat.trace = null; dessinerTrace(null); majOptions(); }).disabled = n === 0;
  }

  function panneau() {
    const p = $('panneau');
    p.innerHTML = '';
    const z = zoneChoisie();
    if (z) {
      const genre = etat.choisi.genre;
      F.titre(p, genre === 'interdite' ? 'Zone interdite' : 'Zone lente');
      F.champTexte(p, 'Nom (facultatif)', z.nom || '', (v) => modifier(() => { z.nom = v.trim(); }), { indice: 'ex. Escalier' });
      if (genre === 'lente') {
        F.champNombre(p, 'Vitesse maximale', z.vitesse_max, { pas: 0.05, min: 0.05, max: 1, unite: 'm/s' }, (v) => modifier(() => { z.vitesse_max = v; }));
      }
      F.valeur(p, 'Coins', String(z.polygone.length));
      F.bouton(p, 'Supprimer la zone', () => modifier(() => {
        liste(genre).splice(etat.choisi.indice, 1);
        etat.choisi = null;
      }), 'bouton bouton-danger');
      return;
    }
    const nI = etat.zones.interdites.filter((x) => x.etage === etage).length;
    const nL = etat.zones.lentes.filter((x) => x.etage === etage).length;
    F.titre(p, 'Zones de l\'étage');
    F.paragraphe(p, nI + ' interdite(s) en rouge, ' + nL + ' lente(s) en orange.');
    F.paragraphe(p, 'Après avoir changé les zones interdites, fabriquez à nouveau la carte (onglet Carte) : c\'est elle qui contient le masque que le robot respecte.', 'panneau-note');
  }

  function majEtat() {
    $('etat').textContent = etat.modifie ? 'Modifications non enregistrées' : 'Tout est enregistré';
    $('etat').classList.toggle('non-enregistre', etat.modifie);
  }

  function rafraichir() {
    dessiner();
    panneau();
    majEtat();
  }

  function clavier(ev) {
    const c = ev.target;
    if (c && (c.tagName === 'INPUT' || c.tagName === 'TEXTAREA')) return;
    if (ev.key === 'Enter') terminerZone();
    if (ev.key === 'Escape') { etat.trace = null; dessinerTrace(null); majOptions(); }
  }
  document.addEventListener('keydown', clavier);

  $('enregistrer').addEventListener('click', async () => {
    const b = $('enregistrer');
    b.disabled = true;
    try {
      const r = await api.ecrire(urlLieu(lieu) + '/zones', etat.zones);
      etat.modifie = false;
      majEtat();
      afficherRapport(r.rapport, 'Zones enregistrées. Fabriquez à nouveau la carte pour mettre à jour le masque des zones interdites.');
    } catch (e) {
      afficherErreur(e);
    } finally {
      b.disabled = false;
    }
  });

  async function charger() {
    try {
      await plan.afficherFond(lieu, etage);
      etat.zones = await api.lire(urlLieu(lieu) + '/zones');
    } catch (e) {
      afficherErreur(e);
    }
    choisirOutil('choisir');
  }
  racine.classList.add('chargement');     // rien n'est modifiable avant la fin du chargement
  charger().finally(() => racine.classList.remove('chargement'));

  return {
    modifie: () => etat.modifie,
    fermer: () => {
      document.removeEventListener('keydown', clavier);
      arreterPointeur();
      plan.detruire();
    },
  };
}
