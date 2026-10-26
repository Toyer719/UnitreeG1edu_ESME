// Écran Monde : dessiner l'environnement inventé d'un étage, vu de dessus, avec sa vue 3D.
// Murs (cliquer-glisser, accrochés à une grille de 0,25 m), passages, objets, piétons et
// départ du robot. Annuler, refaire, enregistrer (PUT …/monde).
//
// Vague 4 (section 11.2 du plan) : sur l'étage du point principal, le départ du robot EST le point
// principal (l'accueil). Il est affiché « = point principal », sans poignée : on ne le fait pas
// glisser en mode Choisir, et ses valeurs se lisent sans se modifier dans le panneau. L'outil
// « Départ du robot » le place encore, mais alors le point principal le suit : à l'enregistrement
// du monde, PUT …/principal {x, y, theta} déplace aussi la salle, son nœud et l'accueil de
// lieu.yaml. Si le fichier avait un autre départ, il est remis sur le point principal à l'ouverture.

import { api, urlEtage, urlLieu } from '../api.js';
import { contexte, rechargerLieu } from '../contexte.js';
import * as F from '../formulaire.js';
import * as G from '../geometrie.js';
import { Historique } from '../historique.js';
import { afficherErreur, afficherMessage, afficherRapport } from '../messages.js';
import { creerPlan, ll, lls, metresParPixel, suivrePointeur } from '../plan.js';
import { Vue3D } from '../vue3d.js';
import { etiquetteSalle } from './salles.js';

const L = window.L;
const IDS_RESERVES = ['sol', 'g1_proxy'];

const OUTILS = [
  { id: 'choisir', texte: 'Choisir', aide: "Cliquez sur un élément pour voir et changer ses mesures, faites-le glisser pour le déplacer. Glissez le fond pour bouger la vue, molette ou deux doigts pour zoomer." },
  { id: 'mur', texte: 'Mur', aide: "Cliquez-glissez pour tracer un mur, ou cliquez au début puis à la fin. Les bouts s'accrochent à la grille de 0,25 m." },
  { id: 'passage', texte: 'Passage', aide: "Cliquez sur un mur pour y laisser un passage (une porte) de la largeur choisie : le mur est coupé en deux." },
  { id: 'objet', texte: 'Objet', aide: "Choisissez le modèle, puis cliquez là où le poser. Réglez ensuite sa rotation dans le panneau." },
  { id: 'pieton', texte: 'Piéton', aide: "Cliquez les points du trajet du piéton, l'un après l'autre, puis « Terminer le trajet » (ou touche Entrée)." },
  { id: 'depart', texte: 'Départ du robot', aide: "Cliquez là où le robot démarre la simulation ; glissez pour l'orienter." },
];
const AIDE_DEPART_PRINCIPAL = "Le robot démarre au point principal « {nom} » (l'accueil) : cliquez pour le déplacer, glissez "
  + "pour l'orienter. À l'enregistrement du monde, le point principal suit (sa salle, son nœud et l'accueil).";
const EGAL = 1e-6;

const MODELES = [
  { id: 'table', texte: 'Table' }, { id: 'chaise', texte: 'Chaise' }, { id: 'banc', texte: 'Banc' },
  { id: 'poubelle', texte: 'Poubelle' }, { id: 'boite', texte: 'Boîte (meuble, comptoir…)' },
  { id: 'cylindre', texte: 'Poteau' },
];

// Monde neuf pour un étage qui n'en a pas : 20 × 15 m entourés de 4 murs (comme g1-lieu creer)
function mondeNeuf() {
  const x = 20, y = 15;
  const mur = (id, de, a) => ({ id: id, de: de, a: a, epaisseur: 0.2, hauteur: 2.5 });
  return {
    version: 1, emprise: { min: [0, 0], max: [x, y] },
    murs: [mur('ext_sud', [0, 0], [x, 0]), mur('ext_est', [x, 0], [x, y]), mur('ext_nord', [x, y], [0, y]),
      mur('ext_ouest', [0, y], [0, 0])],
    objets: [], pietons: [], depart_robot: { x: 1, y: 1, theta: 0 },
  };
}

function idsDuMonde(m) {
  return m.murs.map((e) => e.id).concat(m.objets.map((e) => e.id), m.pietons.map((e) => e.id));
}

function copie(v) {
  return JSON.parse(JSON.stringify(v));
}

export function ouvrir(racine) {
  const lieu = contexte.lieu;
  const etage = contexte.etage;
  const etat = {
    monde: null, outil: 'choisir', choisi: null, modifie: false, trace: null,
    pas: 0.25, accrocher: true, epaisseur: 0.15, hauteur: 2.5, largeurPassage: 1.0, modele: 'table',
    vitesse: 1.0, allerRetour: true, emprisePrecedente: '',
    principal: null,        // point principal du lieu s'il est sur cet étage {salle, nom, x, y, theta}, sinon null
  };
  const hist = new Historique();

  racine.innerHTML = `
    <div class="barre">
      <div class="barre-gauche" data-role="outils"></div>
      <div class="barre-options" data-role="options"></div>
      <div class="barre-droite">
        <button type="button" class="bouton" data-role="annuler" title="Ctrl+Z">Annuler</button>
        <button type="button" class="bouton" data-role="refaire" title="Ctrl+Y">Refaire</button>
        <button type="button" class="bouton bouton-principal" data-role="enregistrer">Enregistrer le monde</button>
        <span class="etat-enregistrement" data-role="etat"></span>
      </div>
    </div>
    <p class="aide" data-role="aide"></p>
    <div class="espace-deux">
      <div class="plan" data-role="plan"></div>
      <div class="cote">
        <div class="vue3d" data-role="vue3d"></div>
        <div class="panneau" data-role="panneau"></div>
      </div>
    </div>`;
  const $ = (r) => racine.querySelector('[data-role="' + r + '"]');
  const plan = creerPlan($('plan'));
  const carte = plan.carte;
  const vue = new Vue3D($('vue3d'));
  const calqueElements = L.layerGroup().addTo(carte);
  const calqueTrace = L.layerGroup().addTo(carte);

  const outils = F.barreOutils($('outils'), OUTILS, etat.outil, choisirOutil);

  // ------------------------------------------------------------------ modifications

  function pas() {
    return etat.accrocher ? etat.pas : 0.01;
  }

  function accrocher(p) {
    return G.accrocherPoint(p, pas());
  }

  // Agrandit l'emprise (au mètre) pour qu'elle contienne tous les points du monde
  function etendreEmprise(m) {
    const pts = [];
    m.murs.forEach((e) => { pts.push(e.de, e.a); });
    m.objets.forEach((o) => pts.push(o.centre));
    m.pietons.forEach((p) => p.trajet.forEach((q) => pts.push(q)));
    pts.push([m.depart_robot.x, m.depart_robot.y]);
    const e = m.emprise;
    pts.forEach((p) => {
      if (p[0] < e.min[0]) e.min[0] = Math.floor(p[0]);
      if (p[1] < e.min[1]) e.min[1] = Math.floor(p[1]);
      if (p[0] > e.max[0]) e.max[0] = Math.ceil(p[0]);
      if (p[1] > e.max[1]) e.max[1] = Math.ceil(p[1]);
    });
  }

  // Toute modification passe par ici : copie pour « annuler », puis redessin
  function modifier(f) {
    hist.noter(etat.monde);
    f(etat.monde);
    etendreEmprise(etat.monde);
    etat.modifie = true;
    rafraichir();
  }

  // Le départ du robot de cet étage est-il le point principal ?
  function departPrincipal() {
    return !!etat.principal;
  }

  function departDiffere() {
    const d = etat.monde.depart_robot;
    const p = etat.principal;
    return !!p && (Math.abs(d.x - p.x) > EGAL || Math.abs(d.y - p.y) > EGAL || Math.abs(d.theta - p.theta) > EGAL);
  }

  function aideOutil(id) {
    if (id === 'depart' && departPrincipal()) return AIDE_DEPART_PRINCIPAL.replace('{nom}', etat.principal.nom);
    return OUTILS.find((o) => o.id === id).aide;
  }

  function element(choix) {
    if (!choix || !etat.monde) return null;
    const m = etat.monde;
    if (choix.genre === 'depart') return m.depart_robot;
    const liste = { mur: m.murs, objet: m.objets, pieton: m.pietons }[choix.genre];
    return liste.find((e) => e.id === choix.id) || null;
  }

  function supprimerChoisi() {
    const c = etat.choisi;
    if (!c || c.genre === 'depart') return;
    modifier((m) => {
      const cle = { mur: 'murs', objet: 'objets', pieton: 'pietons' }[c.genre];
      m[cle] = m[cle].filter((e) => e.id !== c.id);
    });
    etat.choisi = null;
    rafraichir();
  }

  // ------------------------------------------------------------------ dessin 2D

  function dessiner() {
    const m = etat.monde;
    const e = m.emprise;
    const cle = JSON.stringify(e);
    if (cle !== etat.emprisePrecedente) {
      plan.afficherGrille(e.min[0], e.min[1], e.max[0], e.max[1], 0.25);
      etat.emprisePrecedente = cle;
    }
    calqueElements.clearLayers();
    const choisi = etat.choisi || {};
    L.rectangle([[e.min[1], e.min[0]], [e.max[1], e.max[0]]], { className: 'emprise', interactive: false })
      .addTo(calqueElements);
    m.murs.forEach((mur) => {
      L.polygon(lls(G.coinsMur(mur)), {
        className: 'mur' + (choisi.genre === 'mur' && choisi.id === mur.id ? ' choisi' : ''), interactive: false,
      }).addTo(calqueElements);
    });
    m.objets.forEach((o) => {
      const f = G.empreinteObjet(o);
      const classe = 'objet objet-' + (o.type === 'modele' ? o.modele : o.type)
        + (choisi.genre === 'objet' && choisi.id === o.id ? ' choisi' : '');
      if (f.genre === 'cercle') L.circle(ll(f.centre[0], f.centre[1]), { radius: f.rayon, className: classe, interactive: false }).addTo(calqueElements);
      else L.polygon(lls(f.points), { className: classe, interactive: false }).addTo(calqueElements);
    });
    m.pietons.forEach((p) => {
      const sel = choisi.genre === 'pieton' && choisi.id === p.id ? ' choisi' : '';
      const pts = p.trajet.slice();
      L.polyline(lls(pts), { className: 'trajet-pieton' + sel, interactive: false }).addTo(calqueElements);
      if (!p.aller_retour && pts.length > 2) {
        L.polyline(lls([pts[pts.length - 1], pts[0]]), { className: 'trajet-pieton retour' + sel, interactive: false }).addTo(calqueElements);
      }
      L.circle(ll(pts[0][0], pts[0][1]), { radius: 0.25, className: 'pieton' + sel, interactive: false }).addTo(calqueElements);
    });
    const d = m.depart_robot;
    const selD = (choisi.genre === 'depart' ? ' choisi' : '') + (departPrincipal() ? ' principal' : '');
    const robot = L.polygon(lls(G.rectangle([d.x, d.y], 0.45, 0.30, d.theta)), { className: 'robot' + selD, interactive: false })
      .addTo(calqueElements);
    L.polyline(lls([[d.x, d.y], [d.x + 0.5 * Math.cos(d.theta), d.y + 0.5 * Math.sin(d.theta)]]),
      { className: 'robot-cap' + selD, interactive: false }).addTo(calqueElements);
    if (departPrincipal()) {
      robot.bindTooltip(etiquetteSalle('= point principal « ' + etat.principal.nom + ' »', true),
        { permanent: true, direction: 'right', offset: [10, 0], className: 'etiquette depart-principal' });
    }
  }

  function dessinerTrace(p) {
    calqueTrace.clearLayers();
    const t = etat.trace;
    if (p && etat.outil !== 'choisir') {
      L.circleMarker(ll(p[0], p[1]), { radius: 4, className: 'curseur-grille', interactive: false }).addTo(calqueTrace);
    }
    if (!t) return;
    if (t.genre === 'mur') {
      const mur = { de: t.de, a: t.a, epaisseur: etat.epaisseur };
      if (G.longueurMur(mur) > 0) {
        L.polygon(lls(G.coinsMur(mur)), { className: 'mur trace', interactive: false }).addTo(calqueTrace);
        const milieu = [(t.de[0] + t.a[0]) / 2, (t.de[1] + t.a[1]) / 2];
        L.tooltip({ permanent: true, direction: 'top', className: 'bulle-mesure' })
          .setLatLng(ll(milieu[0], milieu[1])).setContent(G.nb(G.longueurMur(mur), 2) + ' m').addTo(calqueTrace);
      }
    } else if (t.genre === 'pieton') {
      const pts = t.points.concat(p ? [p] : []);
      if (pts.length > 1) L.polyline(lls(pts), { className: 'trajet-pieton trace', interactive: false }).addTo(calqueTrace);
      t.points.forEach((q) => L.circleMarker(ll(q[0], q[1]), { radius: 5, className: 'point-trace', interactive: false }).addTo(calqueTrace));
    } else if (t.genre === 'depart') {
      L.polygon(lls(G.rectangle([t.x, t.y], 0.45, 0.30, t.theta)), { className: 'robot trace', interactive: false }).addTo(calqueTrace);
    } else if (t.genre === 'passage' && t.mur) {
      // aperçu du passage : le morceau de mur qui sera retiré
      const L0 = G.longueurMur(t.mur);
      const proj = G.projeterSurSegment(t.point, t.mur.de, t.mur.a);
      const u = [(t.mur.a[0] - t.mur.de[0]) / L0, (t.mur.a[1] - t.mur.de[1]) / L0];
      const s0 = Math.max(0, proj.t * L0 - etat.largeurPassage / 2), s1 = Math.min(L0, proj.t * L0 + etat.largeurPassage / 2);
      const p0 = [t.mur.de[0] + u[0] * s0, t.mur.de[1] + u[1] * s0], p1 = [t.mur.de[0] + u[0] * s1, t.mur.de[1] + u[1] * s1];
      L.polyline(lls([p0, p1]), { className: 'passage-trace', interactive: false }).addTo(calqueTrace);
    }
  }

  // ------------------------------------------------------------------ recherche sous le pointeur

  function tolerance() {
    return Math.max(0.15, 10 * metresParPixel(carte));
  }

  function trouver(p, seulementMurs) {
    const m = etat.monde;
    const tol = tolerance();
    let meilleur = null;
    let dMin = Infinity;
    const essayer = (choix, d) => {
      if (d <= tol && d < dMin) {
        dMin = d;
        meilleur = choix;
      }
    };
    if (!seulementMurs) {
      const d = m.depart_robot;
      essayer({ genre: 'depart' }, Math.max(0, G.distance(p, [d.x, d.y]) - 0.25));
      m.objets.forEach((o) => essayer({ genre: 'objet', id: o.id }, G.distanceEmpreinte(p, G.empreinteObjet(o))));
      m.pietons.forEach((pi) => essayer({ genre: 'pieton', id: pi.id }, G.distancePolyligne(p, pi.trajet, !pi.aller_retour)));
    }
    m.murs.forEach((mur) => {
      const d = Math.max(0, G.projeterSurSegment(p, mur.de, mur.a).distance - mur.epaisseur / 2);
      // un objet posé contre un mur reste prioritaire : on pénalise un peu les murs
      essayer({ genre: 'mur', id: mur.id }, d + (seulementMurs ? 0 : 0.01));
    });
    return meilleur;
  }

  // ------------------------------------------------------------------ gestes

  function ajouterMur(de, a) {
    if (G.distance(de, a) < 0.2) return;
    modifier((m) => m.murs.push({
      id: G.idLibre('mur', idsDuMonde(m)), de: de, a: a,
      epaisseur: etat.epaisseur, hauteur: etat.hauteur,
    }));
  }

  function poserObjet(p) {
    let nouveau;
    modifier((m) => {
      const ids = idsDuMonde(m);
      if (etat.modele === 'boite') nouveau = { id: G.idLibre('boite', ids), type: 'boite', centre: p, taille: [1.0, 0.6, 0.75], cap: 0 };
      else if (etat.modele === 'cylindre') nouveau = { id: G.idLibre('poteau', ids), type: 'cylindre', centre: p, rayon: 0.2, hauteur: 2.5 };
      else nouveau = { id: G.idLibre(etat.modele, ids), type: 'modele', modele: etat.modele, centre: p, cap: 0 };
      m.objets.push(nouveau);
    });
    etat.choisi = { genre: 'objet', id: nouveau.id };
    rafraichir();
  }

  function terminerPieton() {
    const t = etat.trace;
    if (!t || t.genre !== 'pieton') return;
    if (t.points.length < 2) {
      afficherMessage('Un piéton a besoin d\'au moins deux points sur son trajet : cliquez encore.', 'avertissement');
      return;
    }
    let id;
    modifier((m) => {
      id = G.idLibre('pieton', idsDuMonde(m));
      m.pietons.push({ id: id, trajet: t.points, vitesse: etat.vitesse, aller_retour: etat.allerRetour });
    });
    etat.trace = null;
    etat.choisi = { genre: 'pieton', id: id };
    dessinerTrace(null);
    rafraichir();
  }

  function couperPassage(p) {
    const choix = trouver(p, true);
    if (!choix) {
      afficherMessage('Cliquez sur un mur (ou tout près) pour y laisser un passage.', 'avertissement');
      return;
    }
    modifier((m) => {
      const i = m.murs.findIndex((e) => e.id === choix.id);
      const mur = m.murs[i];
      const autres = idsDuMonde(m).filter((x) => x !== mur.id);
      const morceaux = G.couperMur(mur, p, etat.largeurPassage, autres);
      m.murs.splice.apply(m.murs, [i, 1].concat(morceaux));
    });
    etat.choisi = null;
    rafraichir();
  }

  // Déplacement d'un élément en mode Choisir
  function deplacerElement(choix, original, dx, dy) {
    const m = etat.monde;
    const deplacer = (q) => [G.arrondir(q[0] + dx), G.arrondir(q[1] + dy)];
    if (choix.genre === 'depart') {
      m.depart_robot.x = G.arrondir(original.x + dx);
      m.depart_robot.y = G.arrondir(original.y + dy);
    } else if (choix.genre === 'mur') {
      const e = m.murs.find((x) => x.id === choix.id);
      e.de = deplacer(original.de);
      e.a = deplacer(original.a);
    } else if (choix.genre === 'objet') {
      m.objets.find((x) => x.id === choix.id).centre = deplacer(original.centre);
    } else if (choix.genre === 'pieton') {
      m.pietons.find((x) => x.id === choix.id).trajet = original.trajet.map(deplacer);
    }
  }

  const gestes = {
    debut: (p) => {
      const o = etat.outil;
      if (o === 'choisir') {
        const choix = trouver(p);
        etat.choisi = choix;
        rafraichir();
        if (!choix) return false;            // fond : Leaflet fait glisser la vue
        if (choix.genre === 'depart' && departPrincipal()) return true;    // pas de poignée : il ne glisse pas
        etat.trace = { genre: 'deplacement', choix: choix, depart: p, original: copie(element(choix)), avant: copie(etat.monde), bouge: false };
        return true;
      }
      const q = accrocher(p);
      if (o === 'mur') {
        if (!etat.trace) etat.trace = { genre: 'mur', de: q, a: q, deuxClics: false };
      } else if (o === 'depart') {
        etat.trace = { genre: 'depart', x: q[0], y: q[1], theta: etat.monde.depart_robot.theta };
      }
      dessinerTrace(q);
      return true;
    },
    deplacer: (p) => {
      const t = etat.trace;
      if (!t) return;
      if (t.genre === 'deplacement') {
        const dx = G.accrocher(p[0] - t.depart[0], pas()), dy = G.accrocher(p[1] - t.depart[1], pas());
        if (!t.bouge && dx === 0 && dy === 0) return;
        t.bouge = true;
        deplacerElement(t.choix, t.original, dx, dy);
        dessiner();
        vue.afficherMonde(etat.monde, t.choix.id);
      } else if (t.genre === 'mur') {
        t.a = accrocher(p);
        dessinerTrace(t.a);
      } else if (t.genre === 'depart') {
        if (G.distance([t.x, t.y], p) > 0.2) t.theta = G.accrocherAngle(Math.atan2(p[1] - t.y, p[0] - t.x), etat.accrocher ? 15 : 1);
        dessinerTrace(accrocher(p));
      }
    },
    survol: (p) => {
      const t = etat.trace;
      const q = accrocher(p);
      if (etat.outil === 'passage') {
        const choix = trouver(p, true);
        etat.trace = choix ? { genre: 'passage', mur: element(choix), point: p } : null;
        dessinerTrace(null);
        return;
      }
      if (etat.outil === 'choisir') return;
      if (t && t.genre === 'mur' && t.deuxClics) t.a = q;
      dessinerTrace(q);
    },
    fin: (p) => {
      const t = etat.trace;
      const o = etat.outil;
      const q = accrocher(p);
      if (o === 'choisir') {
        if (t && t.genre === 'deplacement') {
          if (t.bouge) {
            hist.noter(t.avant);
            etendreEmprise(etat.monde);
            etat.modifie = true;
          }
          etat.trace = null;
          rafraichir();
        }
        return;
      }
      if (o === 'mur' && t && t.genre === 'mur') {
        if (t.deuxClics || G.distance(t.de, q) >= 0.2) {
          etat.trace = null;
          ajouterMur(t.de, q);
        } else {
          t.deuxClics = true;      // simple clic : on attend le second bout
        }
      } else if (o === 'passage') {
        etat.trace = null;
        couperPassage(p);
      } else if (o === 'objet') {
        poserObjet(q);
      } else if (o === 'pieton') {
        if (!t || t.genre !== 'pieton') etat.trace = { genre: 'pieton', points: [] };
        const pts = etat.trace.points;
        if (pts.length && G.distance(pts[pts.length - 1], q) < 1e-6) {
          terminerPieton();       // clic sur le dernier point : fin du trajet
          return;
        }
        pts.push(q);
        majOptions();
      } else if (o === 'depart' && t && t.genre === 'depart') {
        etat.trace = null;
        modifier((m) => { m.depart_robot = { x: t.x, y: t.y, theta: t.theta }; });
        etat.choisi = { genre: 'depart' };
        rafraichir();
      }
      dessinerTrace(o === 'mur' || o === 'pieton' ? q : null);
    },
    annuler: () => {
      const t = etat.trace;
      if (t && t.genre === 'deplacement' && t.bouge) etat.monde = t.avant;
      etat.trace = null;
      dessinerTrace(null);
      rafraichir();
    },
  };
  const arreterPointeur = suivrePointeur(plan, gestes);

  // ------------------------------------------------------------------ outils et options

  function choisirOutil(id) {
    if (etat.trace && etat.trace.genre === 'pieton' && etat.trace.points.length >= 2) terminerPieton();
    etat.outil = id;
    etat.trace = null;
    outils.choisir(id);
    if (id === 'choisir') carte.dragging.enable();
    else carte.dragging.disable();
    plan.cadre.classList.toggle('dessin', id !== 'choisir');
    $('aide').textContent = aideOutil(id);
    dessinerTrace(null);
    majOptions();
  }

  function majOptions() {
    const zone = $('options');
    zone.innerHTML = '';
    const o = etat.outil;
    if (o !== 'choisir') {
      F.caseACocher(zone, 'Grille 0,25 m', etat.accrocher, (v) => { etat.accrocher = v; });
    }
    if (o === 'mur') {
      F.champNombre(zone, 'Épaisseur', etat.epaisseur, { pas: 0.05, min: 0.05, max: 1, unite: 'm' }, (v) => { etat.epaisseur = v; });
      F.champNombre(zone, 'Hauteur', etat.hauteur, { pas: 0.1, min: 0.1, max: 10, unite: 'm' }, (v) => { etat.hauteur = v; });
    } else if (o === 'passage') {
      F.champNombre(zone, 'Largeur du passage', etat.largeurPassage, { pas: 0.1, min: 0.5, max: 10, unite: 'm' }, (v) => { etat.largeurPassage = v; });
    } else if (o === 'objet') {
      F.listeDeroulante(zone, 'Modèle', etat.modele, MODELES, (v) => { etat.modele = v; });
    } else if (o === 'pieton') {
      F.champNombre(zone, 'Vitesse', etat.vitesse, { pas: 0.1, min: 0.1, max: 3, unite: 'm/s' }, (v) => { etat.vitesse = v; });
      F.caseACocher(zone, 'Va-et-vient (sinon : boucle)', etat.allerRetour, (v) => { etat.allerRetour = v; });
      const n = etat.trace && etat.trace.genre === 'pieton' ? etat.trace.points.length : 0;
      const b = F.bouton(zone, 'Terminer le trajet (' + n + ' point' + (n > 1 ? 's' : '') + ')', terminerPieton, 'bouton bouton-principal');
      b.disabled = n < 2;
      F.bouton(zone, 'Abandonner le trajet', () => { etat.trace = null; dessinerTrace(null); majOptions(); }).disabled = n === 0;
    }
  }

  // ------------------------------------------------------------------ panneau de détails

  function changer(f) {
    // modification depuis le panneau : on redessine aussi le panneau (valeurs arrondies)
    modifier(f);
  }

  function champId(zone, choix) {
    const e = element(choix);
    F.champTexte(zone, 'Identifiant', e.id, (v) => {
      v = v.trim();
      const autres = idsDuMonde(etat.monde).filter((x) => x !== e.id);
      const refus = G.verifierId(v, autres.concat(IDS_RESERVES), 'déjà un mur, un objet ou un piéton');
      if (refus) {
        afficherMessage(refus, 'erreur');
        panneau();
        return;
      }
      changer(() => { element(choix).id = v; });
      etat.choisi = { genre: choix.genre, id: v };
      rafraichir();
    });
  }

  function champPoint(zone, libelle, lire, ecrire) {
    const p = lire();
    F.champNombre(zone, libelle + ' x', p[0], { pas: pas(), unite: 'm' }, (v) => changer(() => ecrire([v, lire()[1]])));
    F.champNombre(zone, libelle + ' y', p[1], { pas: pas(), unite: 'm' }, (v) => changer(() => ecrire([lire()[0], v])));
  }

  function champCap(zone, lire, ecrire) {
    F.champNombre(zone, 'Rotation', G.degres(lire()), { pas: 15, unite: '°', decimales: 1 },
      (v) => changer(() => ecrire(G.arrondir(G.normaliserAngle(G.radians(v)), 4))));
  }

  function panneau() {
    const zone = $('panneau');
    zone.innerHTML = '';
    const m = etat.monde;
    const c = etat.choisi;
    const e = element(c);
    if (!c || !e) {
      F.titre(zone, 'Le monde de l\'étage');
      F.paragraphe(zone, m.murs.length + ' murs, ' + m.objets.length + ' objets, ' + m.pietons.length + ' piétons. '
        + 'Choisissez un outil en haut pour dessiner, ou cliquez sur un élément pour le modifier.');
      F.paragraphe(zone, 'Emprise : le rectangle qui contient tout le monde. Elle s\'agrandit seule quand vous dessinez au-delà.', 'panneau-note');
      const em = m.emprise;
      F.champNombre(zone, 'x min', em.min[0], { pas: 1, unite: 'm' }, (v) => changer((mm) => { mm.emprise.min[0] = v; }));
      F.champNombre(zone, 'y min', em.min[1], { pas: 1, unite: 'm' }, (v) => changer((mm) => { mm.emprise.min[1] = v; }));
      F.champNombre(zone, 'x max', em.max[0], { pas: 1, unite: 'm' }, (v) => changer((mm) => { mm.emprise.max[0] = v; }));
      F.champNombre(zone, 'y max', em.max[1], { pas: 1, unite: 'm' }, (v) => changer((mm) => { mm.emprise.max[1] = v; }));
      F.bouton(zone, 'Réduire l\'emprise à ce qui est dessiné', () => changer((mm) => {
        // on part d'une emprise « vide », que etendreEmprise agrandit jusqu'aux éléments
        mm.emprise = { min: [1e9, 1e9], max: [-1e9, -1e9] };
        etendreEmprise(mm);
      }));
      return;
    }
    if (c.genre === 'mur') {
      F.titre(zone, 'Mur « ' + e.id + ' »');
      champId(zone, c);
      champPoint(zone, 'Début', () => e.de, (p) => { element(c).de = p; });
      champPoint(zone, 'Fin', () => e.a, (p) => { element(c).a = p; });
      F.valeur(zone, 'Longueur', G.nb(G.longueurMur(e), 2) + ' m');
      F.champNombre(zone, 'Épaisseur', e.epaisseur, { pas: 0.05, min: 0.01, max: 1, unite: 'm' }, (v) => changer(() => { element(c).epaisseur = v; }));
      F.champNombre(zone, 'Hauteur', e.hauteur, { pas: 0.1, min: 0.01, max: 10, unite: 'm' }, (v) => changer(() => { element(c).hauteur = v; }));
    } else if (c.genre === 'objet') {
      const nom = e.type === 'modele' ? (MODELES.find((x) => x.id === e.modele) || { texte: e.modele }).texte
        : (e.type === 'boite' ? 'Boîte' : 'Poteau');
      F.titre(zone, nom + ' « ' + e.id + ' »');
      champId(zone, c);
      champPoint(zone, 'Centre', () => e.centre, (p) => { element(c).centre = p; });
      if (e.type === 'boite') {
        ['Longueur', 'Largeur', 'Hauteur'].forEach((libelle, i) => {
          F.champNombre(zone, libelle, e.taille[i], { pas: 0.05, min: 0.01, max: 20, unite: 'm' }, (v) => changer(() => { element(c).taille[i] = v; }));
        });
      }
      if (e.type === 'cylindre') {
        F.champNombre(zone, 'Rayon', e.rayon, { pas: 0.05, min: 0.01, unite: 'm' }, (v) => changer(() => { element(c).rayon = v; }));
        F.champNombre(zone, 'Hauteur', e.hauteur, { pas: 0.1, min: 0.01, unite: 'm' }, (v) => changer(() => { element(c).hauteur = v; }));
      } else {
        champCap(zone, () => e.cap || 0, (v) => { element(c).cap = v; });
      }
    } else if (c.genre === 'pieton') {
      F.titre(zone, 'Piéton « ' + e.id + ' »');
      champId(zone, c);
      F.champNombre(zone, 'Vitesse', e.vitesse, { pas: 0.1, min: 0.1, max: 3, unite: 'm/s' }, (v) => changer(() => { element(c).vitesse = v; }));
      F.caseACocher(zone, 'Va-et-vient (sinon : boucle, retour direct au départ)', e.aller_retour, (v) => changer(() => { element(c).aller_retour = v; }));
      F.valeur(zone, 'Trajet', e.trajet.length + ' points, départ en [' + G.nb(e.trajet[0][0]) + ' ; ' + G.nb(e.trajet[0][1]) + ']');
    } else if (c.genre === 'depart' && departPrincipal()) {
      F.titre(zone, 'Départ du robot = point principal « ' + etat.principal.nom + ' »');
      F.valeur(zone, 'x', G.nb(e.x, 2) + ' m');
      F.valeur(zone, 'y', G.nb(e.y, 2) + ' m');
      F.valeur(zone, 'Orientation', G.nb(G.degres(e.theta), 1) + ' °');
      F.paragraphe(zone, 'Le robot démarre la simulation au point principal du lieu (l\'accueil), tourné dans le sens de sa '
        + 'flèche : il se place et s\'oriente dans l\'onglet Salles. L\'outil « Départ du robot » le déplace aussi : '
        + 'à l\'enregistrement du monde, le point principal suit.', 'panneau-note note-principal');
    } else if (c.genre === 'depart') {
      F.titre(zone, 'Départ du robot');
      F.champNombre(zone, 'x', e.x, { pas: pas(), unite: 'm' }, (v) => changer((mm) => { mm.depart_robot.x = v; }));
      F.champNombre(zone, 'y', e.y, { pas: pas(), unite: 'm' }, (v) => changer((mm) => { mm.depart_robot.y = v; }));
      champCap(zone, () => e.theta, (v) => { etat.monde.depart_robot.theta = v; });
      F.paragraphe(zone, 'Glisser après le clic oriente le robot, par pas de 15° (réglez ici la valeur exacte).', 'panneau-note');
      F.paragraphe(zone, 'En général, le robot démarre à l\'accueil.', 'panneau-note');
    }
    if (c.genre !== 'depart') {
      F.bouton(zone, 'Supprimer', supprimerChoisi, 'bouton bouton-danger');
    }
  }

  // ------------------------------------------------------------------ état général

  function majBoutons() {
    $('annuler').disabled = !hist.peutAnnuler;
    $('refaire').disabled = !hist.peutRefaire;
    $('etat').textContent = etat.modifie ? 'Modifications non enregistrées' : 'Tout est enregistré';
    $('etat').classList.toggle('non-enregistre', etat.modifie);
  }

  function rafraichir() {
    dessiner();
    vue.afficherMonde(etat.monde, etat.choisi ? etat.choisi.id : null);
    panneau();
    majBoutons();
  }

  function annuler() {
    const precedent = hist.annuler(etat.monde);
    if (!precedent) return;
    etat.monde = precedent;
    etat.modifie = true;
    if (!element(etat.choisi)) etat.choisi = null;
    rafraichir();
  }

  function refaire() {
    const suivant = hist.refaire(etat.monde);
    if (!suivant) return;
    etat.monde = suivant;
    etat.modifie = true;
    if (!element(etat.choisi)) etat.choisi = null;
    rafraichir();
  }

  async function enregistrer() {
    const b = $('enregistrer');
    b.disabled = true;
    try {
      const r = await api.ecrire(urlEtage(lieu, etage) + '/monde', etat.monde);
      etat.modifie = false;
      majBoutons();
      let rapport = r.rapport;
      let suite = '';
      if (departDiffere()) {
        // le départ a été déplacé avec l'outil : le point principal le suit (salle, nœud, accueil)
        const d = etat.monde.depart_robot;
        try {
          const rp = await api.ecrire(urlLieu(lieu) + '/principal', { x: d.x, y: d.y, theta: d.theta });
          etat.principal = Object.assign({}, etat.principal, { x: rp.principal.x, y: rp.principal.y, theta: rp.principal.theta });
          rapport = rp.rapport;
          suite = ' Le point principal « ' + etat.principal.nom + ' » a suivi le départ du robot (salle, nœud et accueil).';
          if (rp.avertissement) afficherMessage(rp.avertissement, 'avertissement');
        } catch (e) {
          afficherErreur(e);
          afficherMessage('Le monde est enregistré, mais le point principal n\'a pas suivi le départ du robot : '
            + 'déplacez-le dans l\'onglet Salles.', 'avertissement');
        }
      }
      afficherRapport(rapport, 'Monde enregistré (' + r.enregistre.join(', ') + ').' + suite
        + ' Pour le voir dans la carte et la simulation : onglet Carte, « Fabriquer la carte ».');
      rechargerLieu().catch(() => {});
      rafraichir();
    } catch (e) {
      afficherErreur(e);
    } finally {
      b.disabled = false;
    }
  }

  function clavier(ev) {
    const cible = ev.target;
    if (cible && (cible.tagName === 'INPUT' || cible.tagName === 'TEXTAREA' || cible.tagName === 'SELECT')) return;
    const ctrl = ev.ctrlKey || ev.metaKey;
    if (ctrl && (ev.key === 'z' || ev.key === 'Z') && !ev.shiftKey) { ev.preventDefault(); annuler(); }
    else if (ctrl && (ev.key === 'y' || ev.key === 'Y' || ((ev.key === 'z' || ev.key === 'Z') && ev.shiftKey))) { ev.preventDefault(); refaire(); }
    else if (ev.key === 'Delete' || ev.key === 'Backspace') { if (etat.choisi) { ev.preventDefault(); supprimerChoisi(); } }
    else if (ev.key === 'Escape') { etat.trace = null; etat.choisi = null; dessinerTrace(null); majOptions(); rafraichir(); }
    else if (ev.key === 'Enter') { terminerPieton(); }
  }

  $('annuler').addEventListener('click', annuler);
  $('refaire').addEventListener('click', refaire);
  $('enregistrer').addEventListener('click', enregistrer);
  document.addEventListener('keydown', clavier);
  carte.on('click', (e) => {
    // clic sur le fond en mode Choisir : rien n'est choisi
    if (etat.outil === 'choisir' && !trouver([e.latlng.lng, e.latlng.lat])) {
      etat.choisi = null;
      rafraichir();
    }
  });

  // Le point principal du lieu, s'il est sur cet étage (son départ du robot est alors lui)
  async function chargerPrincipal() {
    try {
      const p = await api.lire(urlLieu(lieu) + '/principal');
      etat.principal = p && p.etage === etage ? { salle: p.salle, nom: p.nom, x: p.x, y: p.y, theta: p.theta } : null;
    } catch (e) {
      etat.principal = null;          // pas de point principal (ou lieu illisible) : le départ reste libre
    }
  }

  async function charger() {
    await chargerPrincipal();
    try {
      etat.monde = await api.lire(urlEtage(lieu, etage) + '/monde');
    } catch (e) {
      if (e.statut !== 404) {
        afficherErreur(e);
        $('aide').textContent = 'Le monde n\'a pas pu être lu : corrigez le fichier, puis rouvrez cet onglet.';
        return;
      }
      etat.monde = mondeNeuf();
      etat.modifie = true;
      afficherMessage('Cet étage n\'avait pas encore de monde : en voici un de 20 × 15 m, entouré de murs. '
        + 'Modifiez-le, puis « Enregistrer le monde ».', 'info');
    }
    ['murs', 'objets', 'pietons'].forEach((k) => { etat.monde[k] = etat.monde[k] || []; });
    if (departDiffere()) {
      // le départ du robot de l'étage du point principal est le point principal (section 11.2)
      const d = etat.monde.depart_robot;
      const p = etat.principal;
      etat.monde.depart_robot = { x: p.x, y: p.y, theta: p.theta };
      etat.modifie = true;
      afficherMessage('Le départ du robot (' + G.nb(d.x, 2) + ' ; ' + G.nb(d.y, 2) + ') n\'était pas sur le point principal « '
        + p.nom + ' » : il y est remis, car le robot démarre toujours à l\'accueil. Enregistrez le monde pour le garder, '
        + 'ou déplacez le point principal dans l\'onglet Salles.', 'avertissement');
    }
    const em = etat.monde.emprise;
    plan.cadrer(em.min[0], em.min[1], em.max[0], em.max[1]);
    vue.cadrer(em);
    choisirOutil('choisir');
    rafraichir();
  }
  racine.classList.add('chargement');     // rien n'est modifiable avant la fin du chargement
  charger().finally(() => racine.classList.remove('chargement'));

  return {
    modifie: () => etat.modifie,
    fermer: () => {
      document.removeEventListener('keydown', clavier);
      arreterPointeur();
      vue.detruire();
      plan.detruire();
    },
  };
}
