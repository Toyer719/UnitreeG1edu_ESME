from setuptools import find_packages, setup

package_name = 'g1_accueil'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='joonho',
    maintainer_email='joonhk913@gmail.com',
    description="Démo d'accueil : le nœud accueil (Atelier G1, vague 6, section 13.4 du plan)",
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            # vague 6 (section 13.4 du plan) : le nœud « accueil », lancé par g1-accueil
            'accueil = g1_accueil.noeud:main',
        ],
    },
)
