# -*- coding: utf-8 -*-
#!/usr/bin/env python
#
# EazeBot Free python/telegram bot for easy execution and surveillance of crypto trading plans on multiple exchanges.
# Copyright (C) 2019
# Marcel Beining <marcel.beining@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser Public License for more details.
#
# You should have received a copy of the GNU Lesser Public License
# along with this program.  If not, see [http://www.gnu.org/licenses/].

from git import Repo
import sys,os,re

# get path to file
pathname = os.path.dirname(sys.argv[0]).replace('/','\\')

# get the current version
with open(os.path.join(pathname,'eazebot','__init__.py')) as fh:
    versiontext = str(fh.read())
    thisVersionOld = re.search('(?<=__version__ = \')[0-9\.]+',versiontext).group(0)
thisVersion = thisVersionOld

from ccxt import __version__ as ccxtVersion
with open(os.path.join(pathname,'requirements.txt')) as fh:
    requirementsTxt = str(fh.read())
    
ccxtTxtVersion = re.search('(?<=ccxt \>\= )[0-9\.]+',requirementsTxt).group(0)
if ccxtVersion > ccxtTxtVersion:
    with open(os.path.join(pathname,'requirements.txt'),'w') as fh:
        fh.write(requirementsTxt.replace(ccxtTxtVersion,ccxtVersion))
    
# ask if this is a minor, major, or new edition change and update the version variable accordingly
print('What type of new version? (1.2.3)?:')
answer = input()
if re.match('^[1-3]{1}$',answer) is not None:
    answer = int(answer)
    thisVersion = [int(val) for val in thisVersion.split('.')]
    thisVersion[answer-1] = thisVersion[answer-1] + 1
    if answer < 3:
        thisVersion[2] = 0
    if answer < 2:
        thisVersion[1] = 0
thisVersion = '.'.join([str(val) for val in thisVersion])

# update version number accordingly
with open(os.path.join(pathname,'eazebot','__init__.py'),'w') as fh:
    fh.write(versiontext.replace(thisVersionOld,thisVersion))

with open(os.path.join(pathname,'licenseTemplate'),'r') as fh:
    licenseTxt = str(fh.read())
with open(os.path.join(pathname,'eazebot','version.txt'),'w') as fh:
    fh.write(licenseTxt+'version = %s'%thisVersion)

# initialize Repo object, add all relevant files and print the git status
repo = Repo(pathname)
assert repo.bare == False

git = repo.git
with open('.gitignore','r') as fh:
    ignore = fh.read().splitlines()
if '' in ignore:
    ignore.remove('')
ignore += [val[:-1] for val in ignore if val[-1]=='/']
ignore = "(" + ")|(".join([val.replace('.','\.').replace('*','.*') for val in ignore]) + ")"

# function to add all files in the folder and subfolders except for .git, all ignored 
# files and modified config files
def addFiles(path='.'):
    for file in os.listdir(path):
        absFile = os.path.join(path,file)
        if file in ['.git']:
            continue
        elif not re.match(ignore, file):
            if os.path.isdir(absFile):
                if len(os.listdir(absFile)) > 0:
                    addFiles(absFile)
                else:
                    print('Warning, empty folder "%s" ignored.'%absFile)
            if 'APIs.json' in file:
                with open(absFile) as fh:
                    if '"apiKeyBinance": "YOURBINANCEKEY"' not in str(fh.read()):
                        continue
            elif 'botConfig.json' in file:
                with open(absFile) as fh:
                    if '"telegramAPI": "YOURBOTTOKEN"' not in str(fh.read()):
                        continue
            print(file)
            git.add(absFile)

# add modified files
p = re.compile('modified:\s+(\S+)\n')
modifiedFiles = re.findall(p,git.status())
for file in modifiedFiles:
    if 'APIs.json' in file:
        with open(file) as fh:
            if '"apiKeyBinance": "YOURBINANCEKEY"' not in str(fh.read()):
                continue
    elif 'botConfig.json' in file:
        with open(file) as fh:
            if '"telegramAPI": "YOURBOTTOKEN"' not in str(fh.read()):
                continue
    print('Adding: '+file)
    git.add(file)

# also add deleted files
p = re.compile('deleted:\s+(\S+)\n')
deletedFiles = re.findall(p,git.status())
for file in deletedFiles:
    git.rm(file)
print(git.status())


# get commit message and unescape backslashes
print('What message do you want to add to the commit?')
commitMessage = input()
commitMessage = commitMessage.encode('utf-8').decode('unicode_escape')  

# commit, tag and push changes
commitType = ['New edition','Major','Minor'][answer-1]
git.commit('-m "%s changes: %s"'%(commitType,commitMessage))
git.execute('git tag -a "%s" -m ""'%('EazeBot_%s'%thisVersion))
git.push()
git.push('--tags')