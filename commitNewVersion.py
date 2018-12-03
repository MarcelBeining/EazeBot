# -*- coding: utf-8 -*-
"""
Created on Mon Dec  3 11:13:39 2018

@author: beiningm
"""
from git import Repo
import sys,os,re

pathname = os.path.dirname(sys.argv[0]).replace('/','\\')
print(pathname)
with open(os.path.join(pathname,'eazebot','version.txt')) as fh:
    versiontext = str(fh.read())
    thisVersionOld = re.search('(?<=version = )[0-9\.]+',versiontext).group(0)

thisVersion = thisVersionOld

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

with open(os.path.join(pathname,'eazebot','version.txt'),'w') as fh:
    fh.write(versiontext.replace(thisVersionOld,thisVersion))

repo = Repo(pathname)
assert repo.bare == False
#repo.index.add([os.path.join('eazebot','tradeHandler.py')],force=False)  
git = repo.git
git.add('*.py')
git.add('eazebot/*.py')
git.add('eazebot/version.txt')
print(git.status())



commitType = ['New edition','Major','Minor'][answer-1]

print('What message do you want to add to the commit?')
commitMessage = input()
fsdf
git.commit('-m "%s changes: %s"'%(commitType,commitMessage))
git.tag('-a "%s" -m ""'%('EazeBot_%s'%thisVersion))
git.push()

# Commit the changes to deviate masters history
#repo.index.commit("Added a new file in the past - for later merege")
repo.index.add()