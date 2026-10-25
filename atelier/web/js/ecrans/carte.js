// Écran Carte : fabriquer la carte 2D de navigation depuis le monde inventé (g1-monde generer),
// puis l'afficher avec Leaflet (CRS.Simple, coordonnées en mètres).

import { api, urlEtage } from '../api.js';
import { contexte, etageCourant, rechargerLieu } from '../contexte.js';
import * as F from '../formulaire.js';
import { nb } from '../geometrie.js';
import { afficherErreur, afficherMessage, afficherRapport } from '../messages.js';
import { creerPlan } from '../plan.js';

export function ouvrir(racine) {
  const lieu = contexte.lieu;
  const etage = contexte.etage;
  racine.innerHTML = `
    <div class="barre">
      <div class="barre-gauche">
        <button type="button" class="bouton bouton-principal bouton-grand" data-role="fabriquer">Fabriquer la carte</button>
        <span class="etat-action" data-role="etat"></span>
      </div>
    </div>
    <p class="aide">La carte 2D est ce que le robot utilise pour se déplacer : noir = obstacle, blanc = libre, gris = inconnu. Elle se fabrique depuis le monde dessiné dans l'onglet Monde (murs et objets entre 0,1 et 1,5 m de haut ; les piétons n'y sont pas, le robot les voit en direct).</p>
    <div class="espace-deux">
      <div class="plan" data-role="plan"></div>
      <div class="cote cote-etroit"><div class="panneau" data-role="infos"></div></div>
    </div>`;
  const $ = (r) => racine.querySelector('[data-role="' + r + '"]');
  const plan = creerPlan($('plan'));

  function afficherInfos(info) {
    const z = $('infos');
    z.innerHTML = '';
    F.titre(z, 'Carte de l\'étage');
    if (!info) {
      F.paragraphe(z, 'Pas encore de carte pour cet étage. Le fond montre le dessin du monde. Cliquez sur « Fabriquer la carte ».');
      return;
    }
    const b = info.bornes;
    F.valeur(z, 'Résolution', nb(info.resolution * 100, 1) + ' cm par pixel');
    F.valeur(z, 'Image', info.largeur + ' × ' + info.hauteur + ' pixels');
    F.valeur(z, 'Surface', nb(b.xmax - b.xmin, 2) + ' × ' + nb(b.ymax - b.ymin, 2) + ' m');
    F.valeur(z, 'Coin bas gauche', '[' + nb(b.xmin, 2) + ' ; ' + nb(b.ymin, 2) + '] m');
    F.valeur(z, 'Fichier', 'cartes/' + etage + '.yaml et ' + info.image);
    if (info.modifiee) F.valeur(z, 'Fabriquée le', new Date(info.modifiee * 1000).toLocaleString('fr-FR'));
    const e = etageCourant();
    F.valeur(z, 'Faite depuis', e && e.source_carte === 'scan' ? 'le scan du robot' : 'le monde inventé');
  }

  async function afficher() {
    try {
      const r = await plan.afficherFond(lieu, etage);
      afficherInfos(r.info);
      if (!r.monde && !r.info) $('etat').textContent = 'Pas encore de monde ni de carte : commencez par l\'onglet Monde.';
    } catch (e) {
      afficherErreur(e);
    }
  }

  $('fabriquer').addEventListener('click', async () => {
    const e = etageCourant();
    if (e && e.source_carte === 'scan' && !window.confirm('La carte de cet étage vient du scan du robot. '
      + 'La fabriquer depuis le monde inventé va la remplacer. Continuer ?')) return;
    const b = $('fabriquer');
    b.disabled = true;
    $('etat').textContent = 'Fabrication en cours… (quelques secondes)';
    try {
      const r = await api.envoyer(urlEtage(lieu, etage) + '/monde/generer');
      $('etat').textContent = 'Carte fabriquée en ' + nb(r.duree_s, 1) + ' s.';
      const faits = [];
      if (r.fichiers.carte) faits.push('carte 2D');
      if (r.fichiers.interdit) faits.push('masque des zones interdites');
      if (r.fichiers.sdf) faits.push('monde Gazebo');
      afficherMessage('Fabriqué : ' + faits.join(', ') + '.', 'succes', [], r.sortie);
      afficherRapport(r.rapport);
      plan.cadre_initial = false;
      await afficher();
      rechargerLieu().catch(() => {});
    } catch (err) {
      $('etat').textContent = 'La fabrication a échoué.';
      afficherErreur(err);
    } finally {
      b.disabled = false;
    }
  });

  racine.classList.add('chargement');
  afficher().finally(() => racine.classList.remove('chargement'));
  return {
    modifie: () => false,
    fermer: () => plan.detruire(),
  };
}
