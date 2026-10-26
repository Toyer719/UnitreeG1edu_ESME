"""Le squelette de g1_pilotage s'importe, et son nœud ne fait rien tant qu'il n'est pas écrit."""
from g1_pilotage import pilote


def test_squelette_sans_effet(capsys):
    assert pilote.main([]) == 1
    assert 'pas encore écrit' in capsys.readouterr().err
