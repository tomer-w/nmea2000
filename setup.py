from setuptools import find_packages, setup

setup(
    name='nmea2000',
    packages=find_packages(),
    version='2025.3.2',
    description='NMEA 2000 encoder and decoder',
    long_description=open('README.md').read(),  # Readme file for long description
    long_description_content_type="text/markdown",
    author='Tomer-W',
    url="https://github.com/tomer-w/nmea2000",
    install_requires=['orjson >= 3.10,<4.0', 'pyserial-asyncio >= 0.6'],
    setup_requires=['pytest-runner'],
    tests_require=['pytest==8.3.5'],
    test_suite='tests',
    entry_points={
        "console_scripts": [
            "nmea2000-cli=nmea2000.cli:main"
        ]
    },
)