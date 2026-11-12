from glob import glob

from setuptools import find_packages, setup

package_name = 'g1_nav'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        # Réglages de Nav2 et lancements, installés dans share/g1_nav
        ('share/' + package_name + '/config', glob('config/*.yaml') + glob('config/*.xml')),
        ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='joonho',
    maintainer_email='joonhk913@gmail.com',
    description='Navigation du guide : Nav2, routeur, guide et banc de test (Atelier G1)',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'guide = g1_nav.guide:main',
            'banc = g1_nav.banc:main',
            'odom_vers_tf = g1_nav.odom_vers_tf:main',
            # vague 4 (section 11.4 du plan), agent Comportement du guide
            'detecteur_personnes = g1_nav.personnes:main',
            'faux_visiteur = g1_nav.faux_visiteur:main',
        ],
    },
)
