#!/usr/bin/env python3
from setuptools import setup
import subprocess
import pathlib
import pkg_resources


with pathlib.Path('requirements.txt').open() as requirements_txt:
    requirements = [
        str(requirement)
        for requirement
        in pkg_resources.parse_requirements(requirements_txt)
    ]

try:
    VERSION = subprocess.check_output(['git', 'describe', '--tags']).strip()
except subprocess.CalledProcessError:
    VERSION = '0'


setup(name='kernel_ci',
      description='tool for linux kernel tweaking',
      author='Lenar Khannanov',
      url='https://github.com/comeillfoo/kernel_ci',
      py_modules=[ 'kernel_ci' ],
      license='MIT',
      install_requires=requirements,
      entry_points={
        'console_scripts': [ 'kernel_ci = kernel_ci:cli' ]})