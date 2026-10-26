// Écran Salles : placer les destinations du guide sur la carte. Clic pour placer, glisser pour
// orienter (le robot s'arrête tourné vers la salle). Panneau : nom, alias, phrase d'arrivée.
// Enregistrer écrit salles.yaml, et met à jour les nœuds de même id dans itineraires.yaml.
//
// Vague 4 (section 11.2 du plan) : le point principal du lieu est la salle qui porte l'étiquette
// « principal » (à défaut, la salle « accueil »). Il est dessiné d'une étoile, avec le badge
// « principal », et sa flèche (le sens du robot) se tourne en la glissant, par pas de 15°. C'est
// l'accueil : le robot y démarre en simulation, on l'y pose au démarrage (« Repérer le robot »), et
// il y revient après chaque visite. En enregistrant, sa pose est aussi recopiée dans l'accueil de
// lieu.yaml et dans le départ du robot du monde (PUT …/salles?synchroniser=true). « Faire de cette
// salle le point principal » déplace l'étiquette ; le point principal ne se supprime pas sans en
// avoir choisi un autre.

import { api, urlLieu } from '../api.js';
import { contexte, rechargerLieu } from '../contexte.js';
import * as F from '../formulaire.js';
import * as G from '../geometrie.js';
import { afficherErreur, afficherMessage, afficherRapport } from '../messages.js';
import { creerPlan, iconeOrientee, ll, suivrePointeur } from '../plan.js';

const L = window.L;
const PAS = 0.05;      // m : les salles s'accrochent aux 5 cm
const PAS_ANGLE = 15;  // degrés : l'orientation glissée s'accroche par pas de 15° (valeur exacte dans le panneau)
export const ETIQUETTE_PRINCIPAL = 'principal';
const ID_PRINCIPAL_IMPLICITE = 'accueil';

const OUTILS = [
  { id: 'choisir', texte: 'Choisir', aide: "Cliquez sur une salle pour la modifier. Faites glisser son rond pour la déplacer, et la petite poignée pour l'orienter. L'étoile est le point principal (l'accueil) : glissez sa poignée pour tourner sa flèche, le sens du robot quand il y est posé." },
  { id: 'ajouter', texte: 'Ajouter une salle', aide: "Cliquez devant la porte de la salle, là où le robot doit s'arrêter, et glissez vers la salle pour l'orienter." },
];

// ---------------------------------------------------------------- point principal (partagé avec Simulation et Monde)

// La salle du point principal d'une liste : celle qui porte l'étiquette ; à défaut, la salle
// « accueil » ; null s'il n'y en a pas (ou s'il y en a deux : salles.yaml les refuse).
export function sallePrincipale(salles) {
  const marquees = salles.filter((s) => (s.etiquettes || []).includes(ETIQUETTE_PRINCIPAL));
  if (marquees.length === 1) return marquees[0];
  if (marquees.length) return null;
  return salles.find((s) => s.id === ID_PRINCIPAL_IMPLICITE) || null;
}

// Icône du point principal : la flèche de la salle (le sens du robot), une étoile au centre.
export function iconePrincipal(theta, classes) {
  const deg = -theta * 180 / Math.PI;     // à l'écran, y vers le bas : on tourne dans l'autre sens
  return L.divIcon({
    className: 'icone-orientee salle principal' + (classes ? ' ' + classes : ''),
    html: '<div class="icone-fleche" style="transform: rotate(' + deg + 'deg)"></div>'
      + '<span class="etoile-principal" aria-hidden="true">★</span>',
    iconSize: [34, 34],
    iconAnchor: [17, 17],
  });
}

// Étiquette posée à côté d'une salle sur la carte : son nom, et le badge « principal ».
export function etiquetteSalle(nom, principale) {
  const e = document.createElement('span');
  if (principale) {
    const b = document.createElement('span');
    b.className = 'badge-principal';
    b.textContent = 'principal';
    e.appendChild(b);
    e.appendChild(document.createTextNode(' '));
  }
  e.appendChild(document.createTextNode(nom));
  return e;
}

export function ouvrir(racine) {
  const lieu = contexte.lieu;
  const etage = contexte.etage;
  const etat = { salles: [], choisi: null, outil: 'choisir', modifie: false, trace: null, idsAuto: new Set() };

  racine.innerHTML = `
    <div class="barre">
      <div class="barre-gauche" data-role="outils"></div>
      <div class="barre-droite">
        <button type="button" class="bouton bouton-principal" data-role="enregistrer">Enregistrer les salles</button>
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

  function sallesEtage() {
    return etat.salles.filter((s) => s.etage === etage);
  }

  function salle(id) {
    return etat.salles.find((s) => s.id === id) || null;
  }

  function principale() {
    return sallePrincipale(etat.salles);
  }

  function modifier(f) {
    f();
    etat.modifie = true;
    rafraichir();
  }

  // « Faire de cette salle le point principal » : l'étiquette passe à cette salle, et à elle seule
  function fairePrincipal(s) {
    const avant = principale();
    modifier(() => {
      etat.salles.forEach((x) => {
        const autres = (x.etiquettes || []).filter((e) => e !== ETIQUETTE_PRINCIPAL);
        if (x === s) x.etiquettes = [ETIQUETTE_PRINCIPAL].concat(autres);
        else if (autres.length) x.etiquettes = autres;
        else delete x.etiquettes;
      });
    });
    afficherMessage('« ' + s.nom + ' » sera le point principal (l\'accueil du robot) à l\'enregistrement'
      + (avant && avant !== s ? ', à la place de « ' + avant.nom + ' »' : '') + '.', 'info');
  }

  function refuserSuppression(s) {
    afficherMessage('« ' + s.nom + ' » est le point principal du lieu (l\'accueil : le robot y démarre et y revient '
      + 'après chaque visite). Choisissez d\'abord un autre point principal (« Faire de cette salle le point '
      + 'principal » sur une autre salle), puis supprimez celle-ci.', 'erreur');
  }

  function poigneeOrientation(s, m, estPrincipale) {
    // poignée d'orientation, à 1 m devant la salle (1,5 m pour la flèche du point principal)
    const r = estPrincipale ? 1.5 : 1.0;
    const icone = (theta) => (estPrincipale ? iconePrincipal(theta, s.id === etat.choisi ? 'choisi' : '')
      : iconeOrientee('salle choisi', theta));
    const poignee = L.marker(ll(s.pose.x + r * Math.cos(s.pose.theta), s.pose.y + r * Math.sin(s.pose.theta)), {
      icon: L.divIcon({ className: 'poignee' + (estPrincipale ? ' poignee-principal' : ''), iconSize: [18, 18], iconAnchor: [9, 9] }),
      draggable: true, keyboard: false,
      title: estPrincipale ? 'Glisser pour tourner la flèche du point principal (le sens du robot)' : 'Glisser pour orienter',
    });
    const ligne = L.polyline([ll(s.pose.x, s.pose.y), poignee.getLatLng()],
      { className: 'ligne-poignee' + (estPrincipale ? ' fleche-principal' : ''), interactive: false });
    poignee.on('dragstart', () => { etat.choisi = s.id; });
    poignee.on('drag', () => {
      const q = poignee.getLatLng();
      ligne.setLatLngs([ll(s.pose.x, s.pose.y), q]);
      m.setIcon(icone(G.accrocherAngle(Math.atan2(q.lat - s.pose.y, q.lng - s.pose.x), PAS_ANGLE)));
    });
    poignee.on('dragend', () => {
      const q = poignee.getLatLng();
      modifier(() => { s.pose.theta = G.accrocherAngle(Math.atan2(q.lat - s.pose.y, q.lng - s.pose.x), PAS_ANGLE); });
    });
    ligne.addTo(calque);
    poignee.addTo(calque);
  }

  function dessiner() {
    calque.clearLayers();
    const p = principale();
    sallesEtage().forEach((s) => {
      const choisie = s.id === etat.choisi;
      const estPrincipale = s === p;
      const m = L.marker(ll(s.pose.x, s.pose.y), {
        icon: estPrincipale ? iconePrincipal(s.pose.theta, choisie ? 'choisi' : '')
          : iconeOrientee('salle' + (choisie ? ' choisi' : ''), s.pose.theta),
        draggable: etat.outil === 'choisir', keyboard: false,
        title: estPrincipale ? s.nom + ' (point principal)' : s.nom,
        zIndexOffset: estPrincipale ? 500 : 0,
      });
      m.bindTooltip(etiquetteSalle(s.nom, estPrincipale), { permanent: true, direction: 'right', offset: [14, 0], className: 'etiquette' });
      m.on('click', () => { etat.choisi = s.id; rafraichir(); });
      m.on('dragstart', () => { etat.choisi = s.id; });
      m.on('dragend', () => {
        const q = m.getLatLng();
        modifier(() => {
          s.pose.x = G.accrocher(q.lng, PAS);
          s.pose.y = G.accrocher(q.lat, PAS);
        });
      });
      m.addTo(calque);
      // la flèche du point principal se tourne toujours ; celle d'une autre salle, une fois choisie
      if (etat.outil === 'choisir' && (choisie || estPrincipale)) poigneeOrientation(s, m, estPrincipale);
    });
  }

  function dessinerTrace() {
    calqueTrace.clearLayers();
    const t = etat.trace;
    if (!t) return;
    L.marker(ll(t.x, t.y), { icon: iconeOrientee('salle trace', t.theta), interactive: false }).addTo(calqueTrace);
  }

  const arreterPointeur = suivrePointeur(plan, {
    debut: (p) => {
      if (etat.outil !== 'ajouter') return false;
      const q = G.accrocherPoint(p, PAS);
      etat.trace = { x: q[0], y: q[1], theta: 0 };
      dessinerTrace();
      return true;
    },
    deplacer: (p) => {
      const t = etat.trace;
      if (!t) return;
      if (G.distance([t.x, t.y], p) > 0.2) t.theta = G.accrocherAngle(Math.atan2(p[1] - t.y, p[0] - t.x), PAS_ANGLE);
      dessinerTrace();
    },
    fin: () => {
      const t = etat.trace;
      etat.trace = null;
      dessinerTrace();
      if (!t) return;
      const id = G.idLibre('salle', etat.salles.map((s) => s.id));
      etat.idsAuto.add(id);
      modifier(() => {
        etat.salles.push({ id: id, nom: 'Nouvelle salle', alias: [], etage: etage, pose: { x: t.x, y: t.y, theta: t.theta }, phrase_arrivee: '' });
        etat.choisi = id;
      });
      choisirOutil('choisir');
      const champ = $('panneau').querySelector('[data-champ="nom"] input');
      if (champ) {
        champ.focus();
        champ.select();
      }
    },
    annuler: () => { etat.trace = null; dessinerTrace(); },
  });

  function choisirOutil(id) {
    etat.outil = id;
    outils.choisir(id);
    plan.cadre.classList.toggle('dessin', id !== 'choisir');
    if (id === 'choisir') carte.dragging.enable();
    else carte.dragging.disable();
    $('aide').textContent = OUTILS.find((o) => o.id === id).aide;
    dessiner();
  }

  function badge(parent) {
    return parent.appendChild(F.el('span', 'badge-principal', 'principal'));
  }

  function panneau() {
    const z = $('panneau');
    z.innerHTML = '';
    const s = salle(etat.choisi);
    const p = principale();
    if (s) {
      const estPrincipale = s === p;
      const t = F.titre(z, 'Salle « ' + s.nom + ' »');
      if (estPrincipale) {
        t.appendChild(document.createTextNode(' '));
        badge(t);
        F.paragraphe(z, 'Point principal du lieu : le robot y démarre en simulation, on l\'y pose au démarrage, tourné '
          + 'dans le sens de la flèche (« Repérer le robot »), et il y revient seul après chaque visite.', 'panneau-note note-principal');
      }
      const champNom = F.champTexte(z, 'Nom affiché et annoncé', s.nom, (v) => modifier(() => {
        s.nom = v.trim() || s.nom;
        if (etat.idsAuto.has(s.id)) {
          // identifiant fabriqué depuis le nom, tant que l'utilisateur ne l'a pas choisi lui-même
          const nouvel = G.idDepuisNom(s.nom);
          if (nouvel && !G.verifierId(nouvel, etat.salles.filter((x) => x !== s).map((x) => x.id))) {
            etat.idsAuto.delete(s.id);
            etat.idsAuto.add(nouvel);
            s.id = nouvel;
            etat.choisi = nouvel;
          }
        }
      }));
      champNom.parentNode.setAttribute('data-champ', 'nom');
      const figee = estPrincipale || s.id === ID_PRINCIPAL_IMPLICITE;
      const champId = F.champTexte(z, 'Identifiant', s.id, (v) => {
        v = v.trim();
        const refus = G.verifierId(v, etat.salles.filter((x) => x !== s).map((x) => x.id), 'une salle');
        if (refus) {
          afficherMessage(refus, 'erreur');
          panneau();
          return;
        }
        modifier(() => {
          etat.idsAuto.delete(s.id);
          s.id = v;
          etat.choisi = v;
        });
      }, { lectureSeule: figee });
      if (figee) {
        champId.title = estPrincipale ? 'Le point principal garde son identifiant (son nœud dans les itinéraires a le même).'
          : 'L\'accueil garde toujours l\'identifiant « accueil ».';
      }
      F.champTexte(z, 'Autres noms (séparés par des virgules)', s.alias.join(', '), (v) => modifier(() => {
        s.alias = v.split(',').map((a) => a.trim()).filter((a) => a);
      }), { indice: 'ex. labo de physique, b204' });
      F.champTexte(z, 'Phrase à l\'arrivée', s.phrase_arrivee, (v) => modifier(() => { s.phrase_arrivee = v.trim(); }),
        { lignes: 3, indice: 'Vide : le robot annonce le nom de la salle.' });
      F.champNombre(z, 'x', s.pose.x, { pas: PAS, unite: 'm' }, (v) => modifier(() => { s.pose.x = v; }));
      F.champNombre(z, 'y', s.pose.y, { pas: PAS, unite: 'm' }, (v) => modifier(() => { s.pose.y = v; }));
      F.champNombre(z, estPrincipale ? 'Orientation (sens du robot)' : 'Orientation', G.degres(s.pose.theta), { pas: 15, unite: '°', decimales: 1 },
        (v) => modifier(() => { s.pose.theta = G.arrondir(G.normaliserAngle(G.radians(v)), 4); }));
      F.paragraphe(z, '0° : vers l\'est (la droite de la carte), 90° : vers le nord (le haut). En glissant la poignée, '
        + 'l\'orientation va par pas de 15°.', 'panneau-note');
      if (!estPrincipale) {
        F.bouton(z, 'Faire de cette salle le point principal', () => fairePrincipal(s), 'bouton bouton-faire-principal');
      }
      // le point principal ne se supprime pas : on dit pourquoi et quoi faire
      F.bouton(z, 'Supprimer la salle', () => {
        if (s === principale()) {
          refuserSuppression(s);
          return;
        }
        modifier(() => {
          etat.salles = etat.salles.filter((x) => x !== s);
          etat.choisi = null;
        });
      }, 'bouton bouton-danger');
      F.bouton(z, 'Retour à la liste', () => { etat.choisi = null; rafraichir(); });
      return;
    }
    F.titre(z, 'Salles de l\'étage (' + sallesEtage().length + ')');
    if (!sallesEtage().length) F.paragraphe(z, 'Aucune salle : choisissez « Ajouter une salle » en haut.');
    if (!p) {
      F.paragraphe(z, 'Ce lieu n\'a pas encore de point principal (l\'accueil, où le robot démarre et revient) : '
        + 'choisissez une salle, puis « Faire de cette salle le point principal ».', 'panneau-note note-sans-principal');
    } else if (p.etage !== etage) {
      F.paragraphe(z, 'Le point principal « ' + p.nom + ' » est sur un autre étage (' + p.etage + ').', 'panneau-note');
    }
    const ul = F.el('ul', 'liste-choix');
    sallesEtage().forEach((x) => {
      const li = F.el('li');
      F.bouton(li, x.nom + ' (' + x.id + ')', () => {
        etat.choisi = x.id;
        carte.panTo(ll(x.pose.x, x.pose.y));
        rafraichir();
      }, 'bouton-lien');
      if (x === p) {
        li.appendChild(document.createTextNode(' '));
        badge(li);
      }
      ul.appendChild(li);
    });
    z.appendChild(ul);
    F.paragraphe(z, 'En enregistrant, chaque salle reçoit aussi un nœud de même nom dans les itinéraires. Reliez-le ensuite au reste dans l\'onglet Itinéraires.', 'panneau-note');
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

  $('enregistrer').addEventListener('click', async () => {
    const b = $('enregistrer');
    b.disabled = true;
    try {
      const r = await api.ecrire(urlLieu(lieu) + '/salles?synchroniser=true', etat.salles);
      etat.modifie = false;
      majEtat();
      const autres = r.enregistre.filter((f) => f !== 'salles.yaml');
      const p = principale();
      afficherRapport(r.rapport, 'Salles enregistrées' + (autres.length ? ' (mis à jour aussi : ' + autres.join(', ') + ')' : '') + '.'
        + (p ? ' Point principal : « ' + p.nom + ' ».' : ''));
      rechargerLieu().catch(() => {});
    } catch (e) {
      afficherErreur(e);
    } finally {
      b.disabled = false;
    }
  });

  async function charger() {
    try {
      await plan.afficherFond(lieu, etage);
      etat.salles = await api.lire(urlLieu(lieu) + '/salles');
    } catch (e) {
      afficherErreur(e);
    }
    choisirOutil('choisir');
    rafraichir();
  }
  racine.classList.add('chargement');     // rien n'est modifiable avant la fin du chargement
  charger().finally(() => racine.classList.remove('chargement'));

  return {
    modifie: () => etat.modifie,
    fermer: () => {
      arreterPointeur();
      plan.detruire();
    },
  };
}
