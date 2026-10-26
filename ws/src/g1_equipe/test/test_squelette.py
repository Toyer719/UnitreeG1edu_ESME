"""Le squelette de g1_equipe s'importe, et son nœud ne fait rien tant qu'il n'est pas écrit."""
from g1_equipe import dialogue


def test_squelette_sans_effet(capsys):
    assert dialogue.main([]) == 1
    assert 'pas encore écrit' in capsys.readouterr().err
