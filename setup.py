#!/usr/bin/env python
"""The setup and build script for the EazeBot library."""

import codecs
from os import path
from setuptools import setup, find_packages

def requirements():
    """Build the requirements list for this project"""
    requirements_list = []
    with open('requirements.txt') as requirements:
        for install in requirements:
            requirements_list.append(install.strip())
    return requirements_list

packages = ['EazeBot']

with codecs.open('README.md', 'r', 'utf-8') as fd:
    fn = path.join('EazeBot', 'version.py')
    with open(fn) as fh:
        code = compile(fh.read(), fn, 'exec')
        exec(code)

    setup(name = 'eazebot',
          version=__version__,
		  author = 'Marcel Beining',
          author_email = 'marcel.beining@gmail.com',
		  url = 'https://github.com/mbeining/eazebot',
		  download_url = 'https://github.com/mbeining/cryptotrader/archive/EazeBot_v1.0.tar.gz',
          license='LGPLv3',
          keywords='python telegram bot api crypto trading',
          description="Free python/telegram bot for easy execution and surveillance of crypto trading plans on multiple exchanges",
          long_description=fd.read(),
          packages=packages,
          install_requires=requirements(),
          classifiers=[
              'Development Status :: 3 - Alpha',
              'Intended Audience :: End Users/Desktop',
              'License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)',
              'Operating System :: OS Independent',
			  'Topic :: Office/Business :: Financial',
              'Topic :: Communications :: Chat',
              'Topic :: Internet',
              'Programming Language :: Python',
              'Programming Language :: Python :: 2',
              'Programming Language :: Python :: 2.7',
              'Programming Language :: Python :: 3',
              'Programming Language :: Python :: 3.4',
              'Programming Language :: Python :: 3.5',
              'Programming Language :: Python :: 3.6'
          ],)