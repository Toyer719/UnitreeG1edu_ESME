"""Installation du paquet Python « atelier » (Atelier G1), en mode éditable :

  ~/robot-g1/.venv-projet/bin/pip install --no-deps -e ~/robot-g1
  python3 -m pip install --user --no-deps --no-build-isolation -e ~/robot-g1

Les dépendances (FastAPI, Open3D, PyYAML, jsonschema...) viennent de .venv-projet,
installé par setup/installer_utilisateur.sh.
"""
from setuptools import find_packages, setup

setup(
    name="atelier",
    version="0.1.0",
    description="Atelier G1 : configuration des lieux du robot d'accueil Unitree G1",
    packages=find_packages(include=["atelier", "atelier.*"]),
    package_data={"atelier.lieu": ["schemas/*.json"]},
    python_requires=">=3.10",
)
