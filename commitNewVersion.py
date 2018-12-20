# -*- coding: utf-8 -*-
"""
Created on Mon Dec  3 11:13:39 2018
This function semi-automatically creates a new version and commit
@author: beiningm
"""
from git import Repo
import sys,os,re

# get path to file
pathname = os.path.dirname(sys.argv[0]).replace('/','\\')

# get the current version
with open(os.path.join(pathname,'eazebot','version.txt')) as fh:
    versiontext = str(fh.read())
    thisVersionOld = re.search('(?<=version = )[0-9\.]+',versiontext).group(0)
thisVersion = thisVersionOld

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

# update version number in version.txt accordingly
with open(os.path.join(pathname,'eazebot','version.txt'),'w') as fh:
    fh.write(versiontext.replace(thisVersionOld,thisVersion))

# initialize Repo object, add all relevant files (py and version.txt) and print the git status
repo = Repo(pathname)
assert repo.bare == False
#repo.index.add([os.path.join('eazebot','tradeHandler.py')],force=False)  
git = repo.git
git.add('*.py')
git.add('eazebot/*.py')
git.add('eazebot/version.txt')
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