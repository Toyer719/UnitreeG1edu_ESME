// Placer l'accueil et les salles dans la carte 3D (vague 5, section 12.3 du plan, décision I8) : la liste
// des salles, le panneau (nom, x, y, orientation en degrés), Annuler / Rétablir (historique.js) et
// l'enregistrement par la même route que le plan 2D, PUT /api/lieux/{id}/salles?synchroniser=true
// (chaque salle reçoit son nœud de même id dans itineraires.yaml ; le point principal recopie sa pose
// dans l'accueil de lieu.yaml et dans depart_robot du monde). Mêmes règles que js/ecrans/salles.js :
// point principal = salle étiquetée « principal », à défaut la salle « accueil » ; il ne se supprime pas
// sans en avoir choisi un autre ; identifiants vérifiés par verifierId et fabriqués depuis le nom
// (idDepuisNom) tant que l'utilisateur ne les a pas choisis ; positions au pas de 5 cm et orientation
// glissée au pas de 15° (valeur exacte dans le panneau). Le serveur revalide tout (422 en français).
//
// Utilisé par la page d'essai (essais/carte3d.html) ; l'écran Salles de la coque peut s'en servir tel
// quel : creerEditionSalles(carte, {lieu, etage, panneau, message, apresEnregistrement}).

import { api, urlLieu } from '../api.js';
import * as F from '../formulaire.js';
import * as G from '../geometrie.js';
import { Historique } from '../historique.js';
import { PAS_POSITION, depuisDegres, idPrincipal, versDegres } from './geometrie3d.js';

export const ETIQUETTE_PRINCIPAL = 'principal';
const ID_ACCUEIL = 'accueil';

function copie(v) {
  return JSON.parse(JSON.stringify(v));
}

// carte : la carte 3D (creerCarte3D). options : {lieu, etage, panneau (élément où mettre le formulaire,
// ou null), message(texte, genre) (genre : info, succes, erreur), garderOutil (faux : après une pose,
// retour à « naviguer », comme le plan 2D), apresEnregistrement(reponse)}.
export function creerEditionSalles(carte, options) {
  const o = options || {};
  const lieu = o.lieu;
  const etage = o.etage;
  const etat = { salles: [], choisi: null, modifie: false, idsAuto: new Set(), charge: false };
  const historique = new Historique(200);
  const ecouteurs = new Set();

  function message(texte, genre) {
    if (o.message) o.message(texte, genre || 'info');
  }

  function principal() {
    return idPrincipal(etat.salles);
  }

  function salle(id) {
    return etat.salles.find((s) => s.id === id) || null;
  }

  function sallesEtage() {
    return etat.salles.filter((s) => s.etage === etage);
  }

  function resume() {
    return { salles: copie(etat.salles), choisi: etat.choisi, modifie: etat.modifie, principal: principal(),
      peutAnnuler: historique.peutAnnuler, peutRetablir: historique.peutRefaire };
  }

  function signaler() {
    panneau();
    ecouteurs.forEach((f) => f(resume()));
  }

  function afficher() {
    carte.afficherSalles(etat.salles, principal());
    carte.choisir(etat.choisi ? 'salle' : null, etat.choisi);
  }

  // Toute modification passe par ici : copie pour Annuler, puis dessin et panneau
  function modifier(f) {
    historique.noter({ salles: etat.salles, choisi: etat.choisi });
    f();
    etat.modifie = true;
    afficher();
    signaler();
  }

  function restaurer(e) {
    if (!e) return false;
    etat.salles = e.salles;
    etat.choisi = e.choisi && salle(e.choisi) ? e.choisi : null;
    etat.modifie = true;
    afficher();
    signaler();
    return true;
  }

  function annuler() {
    return restaurer(historique.annuler({ salles: etat.salles, choisi: etat.choisi }));
  }

  function retablir() {
    return restaurer(historique.refaire({ salles: etat.salles, choisi: etat.choisi }));
  }

  // ------------------------------------------------------------ poses venues de la carte 3D
  function nouvelleSalle(e) {
    const id = G.idLibre('salle', etat.salles.map((s) => s.id));
    etat.idsAuto.add(id);
    etat.salles.push({ id: id, nom: 'Nouvelle salle', alias: [], etage: etage,
      pose: { x: e.x, y: e.y, theta: e.theta || 0 }, phrase_arrivee: '' });
    etat.choisi = id;
  }

  // L'accueil sans point principal : la salle « accueil » le devient (comme un lieu neuf)
  function nouvelAccueil(e) {
    const s = salle(ID_ACCUEIL);
    if (s) {
      s.etage = etage;
      s.pose = { x: e.x, y: e.y, theta: e.theta || 0 };
      s.etiquettes = [ETIQUETTE_PRINCIPAL].concat((s.etiquettes || []).filter((t) => t !== ETIQUETTE_PRINCIPAL));
    } else {
      etat.salles.unshift({ id: ID_ACCUEIL, nom: 'Accueil', alias: ['accueil'], etage: etage,
        pose: { x: e.x, y: e.y, theta: e.theta || 0 }, phrase_arrivee: '', etiquettes: [ETIQUETTE_PRINCIPAL] });
    }
    etat.choisi = ID_ACCUEIL;
  }

  function surPose(e) {
    if (e.genre !== 'salle' || e.annule) return;
    if (!e.fini) {
      apercu(e);
      return;
    }
    // après une pose, retour à « naviguer » (comme le plan 2D), avant de prévenir les abonnés
    if (!o.garderOutil && (e.outil === 'salle' || e.outil === 'accueil')) carte.outil('naviguer');
    modifier(() => {
      const s = e.id !== null && e.id !== undefined ? salle(e.id) : null;
      if (s) {
        s.pose = { x: e.x, y: e.y, theta: typeof e.theta === 'number' ? e.theta : s.pose.theta };
        if (s.etage !== etage) s.etage = etage;          // le point principal venu d'un autre étage
        etat.choisi = s.id;
      } else if (e.outil === 'accueil') {
        nouvelAccueil(e);
      } else {
        nouvelleSalle(e);
      }
    });
    const champ = o.panneau ? o.panneau.querySelector('[data-champ="nom"] input') : null;
    if (champ && e.id === null && e.outil === 'salle') {
      champ.focus();
      champ.select();
    }
  }

  function surSelection(e) {
    etat.choisi = e && e.genre === 'salle' && salle(e.id) ? e.id : null;
    signaler();
  }

  // seulement les salles : les nœuds des itinéraires ne se glissent pas ici (ils restent à leur place)
  const desabonner = [carte.surPose(surPose, { genres: ['salle'] }), carte.surSelection(surSelection)];

  // ------------------------------------------------------------ modifications depuis le panneau
  // pose : {x, y, orientation (degrés)}, chacun facultatif ; les valeurs exactes sont gardées
  function modifierPose(id, pose) {
    const s = salle(id);
    if (!s) return false;
    modifier(() => {
      if (typeof pose.x === 'number' && isFinite(pose.x)) s.pose.x = G.arrondir(pose.x, 3);
      if (typeof pose.y === 'number' && isFinite(pose.y)) s.pose.y = G.arrondir(pose.y, 3);
      if (typeof pose.orientation === 'number' && isFinite(pose.orientation)) s.pose.theta = depuisDegres(pose.orientation);
      etat.choisi = s.id;
    });
    return true;
  }

  function renommer(id, nom) {
    const s = salle(id);
    const texte = String(nom || '').trim();
    if (!s || !texte) return false;
    modifier(() => {
      s.nom = texte;
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
    });
    return true;
  }

  function changerId(id, valeur) {
    const s = salle(id);
    const v = String(valeur || '').trim();
    if (!s) return false;
    if (s.id === principal() || s.id === ID_ACCUEIL) {
      message('Le point principal et l\'accueil gardent leur identifiant (leur nœud dans les itinéraires a le même).', 'erreur');
      return false;
    }
    const refus = G.verifierId(v, etat.salles.filter((x) => x !== s).map((x) => x.id), 'une salle');
    if (refus) {
      message(refus, 'erreur');
      return false;
    }
    modifier(() => {
      etat.idsAuto.delete(s.id);
      s.id = v;
      etat.choisi = v;
    });
    return true;
  }

  function fairePrincipal(id) {
    const s = salle(id);
    if (!s) return false;
    modifier(() => {
      etat.salles.forEach((x) => {
        const autres = (x.etiquettes || []).filter((t) => t !== ETIQUETTE_PRINCIPAL);
        if (x === s) x.etiquettes = [ETIQUETTE_PRINCIPAL].concat(autres);
        else if (autres.length) x.etiquettes = autres;
        else delete x.etiquettes;
      });
    });
    message('« ' + s.nom + ' » sera le point principal (l\'accueil du robot) à l\'enregistrement.', 'info');
    return true;
  }

  function supprimer(id) {
    const s = salle(id);
    if (!s) return false;
    if (s.id === principal()) {
      message('« ' + s.nom + ' » est le point principal du lieu (l\'accueil : le robot y démarre et y revient après '
        + 'chaque visite). Choisissez d\'abord un autre point principal, puis supprimez celle-ci.', 'erreur');
      return false;
    }
    modifier(() => {
      etat.salles = etat.salles.filter((x) => x !== s);
      etat.choisi = null;
    });
    return true;
  }

  function choisir(id) {
    etat.choisi = id && salle(id) ? id : null;
    carte.choisir(etat.choisi ? 'salle' : null, etat.choisi);
    signaler();
  }

  // ------------------------------------------------------------ panneau
  let champsApercu = null;

  function apercu(e) {
    if (!champsApercu || e.id !== etat.choisi) return;
    champsApercu.x.value = String(e.x);
    champsApercu.y.value = String(e.y);
    if (typeof e.theta === 'number') champsApercu.orientation.value = String(versDegres(e.theta));
  }

  function marquer(champ, nom) {
    champ.parentNode.setAttribute('data-champ', nom);
    return champ;
  }

  function panneau() {
    const z = o.panneau;
    champsApercu = null;
    if (!z) return;
    z.textContent = '';
    const s = salle(etat.choisi);
    const p = principal();
    if (s) {
      const estPrincipal = s.id === p;
      F.titre(z, (estPrincipal ? '★ ' : '') + 'Salle « ' + s.nom + ' »');
      if (estPrincipal) {
        F.paragraphe(z, 'Point principal du lieu : le robot y démarre, on l\'y pose au démarrage, tourné dans le sens '
          + 'de la flèche, et il y revient après chaque visite.', 'panneau-note');
      }
      marquer(F.champTexte(z, 'Nom affiché et annoncé', s.nom, (v) => renommer(s.id, v)), 'nom');
      const champId = marquer(F.champTexte(z, 'Identifiant', s.id, (v) => {
        if (!changerId(s.id, v)) panneau();
      }, { lectureSeule: estPrincipal || s.id === ID_ACCUEIL }), 'id');
      if (estPrincipal) champId.title = 'Le point principal garde son identifiant.';
      const x = marquer(F.champNombre(z, 'x', s.pose.x, { pas: PAS_POSITION, unite: 'm' }, (v) => modifierPose(s.id, { x: v })), 'x');
      const y = marquer(F.champNombre(z, 'y', s.pose.y, { pas: PAS_POSITION, unite: 'm' }, (v) => modifierPose(s.id, { y: v })), 'y');
      const orientation = marquer(F.champNombre(z, estPrincipal ? 'Orientation (sens du robot)' : 'Orientation',
        versDegres(s.pose.theta), { pas: 15, unite: '°', decimales: 1 }, (v) => modifierPose(s.id, { orientation: v })), 'orientation');
      champsApercu = { x: x, y: y, orientation: orientation };
      F.paragraphe(z, '0° : vers x (la droite de la vue de dessus), 90° : vers y (le haut). Glisser la poignée blanche '
        + 'au bout de la flèche la tourne par pas de 15° (Maj : librement).', 'panneau-note');
      if (!estPrincipal) F.bouton(z, 'Faire de cette salle le point principal', () => fairePrincipal(s.id), 'bouton');
      F.bouton(z, 'Supprimer la salle', () => supprimer(s.id), 'bouton bouton-danger');
      F.bouton(z, 'Retour à la liste', () => choisir(null), 'bouton');
      return;
    }
    F.titre(z, 'Salles de l\'étage (' + sallesEtage().length + ')');
    if (!sallesEtage().length) F.paragraphe(z, 'Aucune salle : choisissez « Salle », puis cliquez sur le sol.');
    if (!p) {
      F.paragraphe(z, 'Ce lieu n\'a pas encore de point principal : choisissez « Accueil », puis cliquez sur le sol.',
        'panneau-note');
    }
    const liste = F.el('ul', 'liste-choix');
    sallesEtage().forEach((x) => {
      const li = F.el('li');
      F.bouton(li, (x.id === p ? '★ ' : '') + x.nom + ' (' + x.id + ')', () => {
        choisir(x.id);
        carte.centrerSur(x.pose.x, x.pose.y);
      }, 'bouton-lien');
      liste.appendChild(li);
    });
    z.appendChild(liste);
  }

  // ------------------------------------------------------------ fichiers
  async function charger() {
    const liste = await api.lire(urlLieu(lieu) + '/salles');
    etat.salles = Array.isArray(liste) ? liste : [];
    etat.choisi = null;
    etat.modifie = false;
    etat.idsAuto.clear();
    historique.vider();
    etat.charge = true;
    afficher();
    signaler();
    return etat.salles.length;
  }

  async function enregistrer() {
    const r = await api.ecrire(urlLieu(lieu) + '/salles?synchroniser=true', etat.salles);
    etat.modifie = false;
    signaler();
    const autres = (r.enregistre || []).filter((f) => f !== 'salles.yaml');
    message('Salles enregistrées' + (autres.length ? ' (mis à jour aussi : ' + autres.join(', ') + ')' : '') + '.', 'succes');
    if (o.apresEnregistrement) o.apresEnregistrement(r);
    return r;
  }

  return {
    charger: charger,
    enregistrer: enregistrer,
    annuler: annuler,
    retablir: retablir,
    choisir: choisir,
    modifierPose: modifierPose,
    renommer: renommer,
    changerId: changerId,
    fairePrincipal: fairePrincipal,
    supprimer: supprimer,
    salles: () => copie(etat.salles),
    etat: resume,
    modifie: () => etat.modifie,
    surChangement: (f) => {
      ecouteurs.add(f);
      return () => ecouteurs.delete(f);
    },
    detruire: () => {
      desabonner.forEach((d) => d());
      ecouteurs.clear();
    },
  };
}
