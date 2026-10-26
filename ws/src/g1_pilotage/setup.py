from setuptools import find_packages, setup

package_name = 'g1_pilotage'

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
    description="Pilotage du G1 depuis l'Atelier (Atelier G1, section 11.5 du plan)",
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'pilote = g1_pilotage.pilote:main',
        ],
    },
)
