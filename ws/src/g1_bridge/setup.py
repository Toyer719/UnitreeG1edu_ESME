from glob import glob

from setuptools import find_packages, setup

package_name = 'g1_bridge'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        # Réglages du pont, installés dans share/g1_bridge/config (lus par navigation.launch.py)
        ('share/' + package_name + '/config', glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='joonho',
    maintainer_email='joonhk913@gmail.com',
    description='Pont /cmd_vel → ordres de marche 7105 du G1 (Atelier G1)',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'pont = g1_bridge.pont:main',
        ],
    },
)
