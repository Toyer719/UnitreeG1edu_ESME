from setuptools import find_packages, setup

package_name = 'g1_equipe'

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
    description="Emplacements de l'équipe : chatbot, personnalités, caméra (Atelier G1)",
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'dialogue = g1_equipe.dialogue:main',
        ],
    },
)
