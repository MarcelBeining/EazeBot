#!/usr/bin/env python
"""The setup and build script for the EazeBot library."""

import codecs
import re
from os import path
from setuptools import setup

def requirements():
    """Build the requirements list for this project"""
    requirements_list = []
    with open('requirements.txt') as requirements:
        for install in requirements:
            requirements_list.append(install.strip())
    return requirements_list

packages = ['eazebot']

with codecs.open('readme.md', 'r', 'utf-8') as fd:
    fn = path.join('eazebot/version.txt')
    with open(fn) as fh:
	    __version__ = re.search('(?<=version = ).+',str(fh.read())).group(0)
    with open(path.join('eazebot/APIs.json')) as fh:
        if '"apiKeyBinance": "YOURBINANCEKEY"' not in str(fh.read()):
            raise Exception('Modified key file! Possibly wrong folder?')
			
    setup(name = 'eazebot',
          version=__version__,
		  author = 'Marcel Beining',
          author_email = 'marcel.beining@gmail.com',
		  url = 'https://github.com/marcelbeining/eazebot',
		  download_url = 'https://github.com/marcelbeining/cryptotrader/archive/EazeBot_%s.tar.gz'%__version__,
          license='LGPLv3',
          keywords='python telegram bot api crypto trading',
          description="Free python/telegram bot for easy execution and surveillance of crypto trading plans on multiple exchanges",
          long_description=fd.read(),
		  long_description_content_type='text/markdown',
          packages=packages,
		  include_package_data=True,
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
              'Programming Language :: Python :: 3',
              'Programming Language :: Python :: 3.4',
              'Programming Language :: Python :: 3.5',
              'Programming Language :: Python :: 3.6'
          ],)