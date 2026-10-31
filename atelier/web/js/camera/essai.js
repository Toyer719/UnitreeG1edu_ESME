// Page d'essai de la vue Caméra (essais/camera.html, vague 5, section 12.7 du plan), jamais liée par
// l'interface : la vue seule, sans la coque. window.vueCamera est la vue, pour les tests. Paramètres de
// l'adresse : source (poitrine | visiteurs), petit (1 : incrustation), cadres (0 : sans les cadres),
// auto (0 : ne démarre pas tout seul).

import { creerVueCamera } from './flux.js';

const parametres = new URLSearchParams(location.search);
const reglages = {
  source: parametres.get('source') === 'visiteurs' ? 'visiteurs' : 'poitrine',
  petit: parametres.get('petit') === '1',
  cadres: parametres.get('cadres') !== '0',
};
const $ = (role) => document.querySelector('[data-role="' + role + '"]');
const centre = $('essai-centre');
const zone = $('essai-vue');

function monter(demarrer) {
  if (window.vueCamera) window.vueCamera.detruire();
  centre.classList.toggle('petite', reglages.petit);
  window.vueCamera = creerVueCamera(zone, {
    source: reglages.source, petit: reglages.petit, cadres: reglages.cadres && reglages.source === 'poitrine',
  });
  if (demarrer) window.vueCamera.demarrer();
  $('essai-source').setAttribute('aria-pressed', reglages.source === 'visiteurs' ? 'true' : 'false');
  $('essai-petit').setAttribute('aria-pressed', reglages.petit ? 'true' : 'false');
}

$('essai-demarrer').addEventListener('click', () => window.vueCamera.demarrer());
$('essai-arreter').addEventListener('click', () => window.vueCamera.arreter());
$('essai-source').addEventListener('click', () => {
  reglages.source = reglages.source === 'visiteurs' ? 'poitrine' : 'visiteurs';
  monter(true);
});
$('essai-petit').addEventListener('click', () => {
  reglages.petit = !reglages.petit;
  monter(true);
});
$('essai-cacher').addEventListener('click', () => {
  zone.hidden = !zone.hidden;
  $('essai-cacher').setAttribute('aria-pressed', zone.hidden ? 'true' : 'false');
});

monter(parametres.get('auto') !== '0');
setInterval(() => {
  $('essai-etat').textContent = JSON.stringify(window.vueCamera.etat());
}, 500);
