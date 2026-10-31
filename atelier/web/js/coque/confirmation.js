// Fenêtre de confirmation dans la page, à la place de window.confirm (vague 5, section 12.2 du plan) :
// tous les écrans s'en servent (options.coque.confirmer). Module de l'agent Coquille ; squelette livré
// par l'agent Contrats, qui passe encore par window.confirm.
// Repères : [data-role=confirmation], boutons [data-role=confirmer] et [data-role=renoncer].

// options : {titre, ok: 'Libellé du bouton', annuler: 'Libellé', danger: bool} ; résout true ou false
export function demanderConfirmation(texte, options) {   // eslint-disable-line no-unused-vars
  return Promise.resolve(window.confirm(texte));
}
