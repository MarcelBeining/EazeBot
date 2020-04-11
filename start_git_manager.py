import os
import re
import sys
import warnings
from git import Repo, GitCommandError
from eazebot import __version__ as current_version
from ccxt import __version__ as ccxt_version
from subprocess import Popen, PIPE
import shutil

def git_push(git_obj, branch_name):
    try:
        git_obj.push(u="origin " + branch_name)
        git_obj.push('--tags')
    except GitCommandError as e:
        if 'correct access rights' in str(e):
            warnings.warn('It seems your ssh keys are not set in an accessible way. Please push the new release branch'
                          ' manually')
        else:
            raise e


# get path to file
pathname = os.path.dirname(sys.argv[0]).replace('/', '\\')

current_version_parsed = [int(x) for x in current_version.split('.')]
print(f'Current version: {current_version}')

# initialize Repo object
repo = Repo(os.path.dirname(__file__).replace('/', '\\'))
assert repo.bare is False, 'Folder is no existing Git repository!'
git = repo.git

if repo.active_branch.name in ['dev', 'master']:
    # ask for new version type
    version_type = input('What type of new version? Major (0), minor (1) or hotfix (2)?\n')
    assert re.match('^[0-2]$', version_type) is not None, 'Please give a number!'
    version_type = int(version_type)

    # update version number accordingly
    new_version_parsed = current_version_parsed
    new_version_parsed[version_type] += 1
    if version_type < 1:
        new_version_parsed[1] = 0
    if version_type < 2:
        new_version_parsed[2] = 0

    new_version_string = '.'.join([str(x) for x in new_version_parsed])

    # create the new release branch and checkout
    if version_type < 2:
        assert repo.active_branch.name == 'dev', f"Creating a new release branch is only allowed from branch 'dev', " \
                                                 f"you are on {repo.active_branch.name}"
        new_branch_name = f"release/v{new_version_string}"
    else:
        assert repo.active_branch.name == 'master', f"Creating a new hotfix branch is only allowed from branch " \
                                                    f"'master', you are on {repo.active_branch.name}"
        new_branch_name = f"hotfix/v{new_version_string}"
    git.checkout('HEAD', b=new_branch_name)  # create a new branch

    # change the version in the pipeline
    with open('eazebot/__init__.py', 'w') as fh:
        fh.write(f"__version__ = '{new_version_string}'\n")

    with open(os.path.join(pathname, 'licenseTemplate'), 'r') as fh:
        licenseTxt = str(fh.read())
    with open(os.path.join(pathname, 'eazebot', 'version.txt'), 'w') as fh:
        fh.write(licenseTxt + 'version = %s' % new_version_string)

    with open(os.path.join(pathname, 'requirements.txt')) as fh:
        requirementsTxt = str(fh.read())
    ccxt_txt_version = re.search(r'(?<=ccxt \>\= )[0-9\.]+', requirementsTxt).group(0)
    if ccxt_version > ccxt_txt_version:
        with open(os.path.join(pathname, 'requirements.txt'), 'w') as fh:
            fh.write(requirementsTxt.replace(ccxt_txt_version, ccxt_version))

    git.add('eazebot/__init__.py')
    git.add('eazebot/version.txt')
    git.add('requirements.txt')

    print(git.status())

    # get commit message and unescape backslashes
    print('What message do you want to add to the commit?')
    commit_message = input()
    commit_message = commit_message.encode('utf-8').decode('unicode_escape')

    # commit, tag and push changes
    commitType = ['New edition', 'Major', 'Minor'][version_type]
    git.commit('-m "%s changes: %s"' % (commitType, commit_message))
    git.execute(f'git tag -a \"{new_branch_name.replace("/", "_")}_first_commit" -m "{commit_message}\"')
    git_push(git, new_branch_name)

elif 'hotfix/' in repo.active_branch.name or 'release/' in repo.active_branch.name:
    while True:
        answer = input(f"You are about to merge branch {repo.active_branch.name} into dev & master. Continue? (y/n)\n")
        if answer == 'y':
            break
        elif answer == 'n':
            exit(0)

    branch_to_merge = repo.active_branch.name
    # merge into master and dev
    for branch in ['master', 'dev']:
        git.checkout(branch)
        git.merge(branch_to_merge)
        if branch == 'master':
            shutil.rmtree('dist')
            p = Popen(['python', 'setup.py', 'sdist', 'bdist_wheel'], cwd=os.path.dirname(__file__))
            p.wait()

            p = Popen(['python -m twine upload dist/*'], cwd=os.path.dirname(__file__))
            p.communicate(input('Username:'))
            p.communicate(input('Password:'))
            p.wait()
            git.execute(f'git tag v{current_version}')  # -a x -m "{commit_message}\"
    for branch in ['master', 'dev']:
        git_push(git, branch)
elif 'feature/' in repo.active_branch.name:
    while True:
        answer = input(f"You are about to merge branch {repo.active_branch.name} into dev. Continue? (y/n)\n")
        if answer == 'y':
            break
        elif answer == 'n':
            exit(0)

    branch_to_merge = repo.active_branch.name
    # merge into dev
    git.checkout('dev')
    git.merge(branch_to_merge)
    git_push(git, 'dev')

else:
    raise Exception(f"Unknown branch {repo.active_branch.name}")

# add modified files
# p = re.compile(r'modified:\s+(\S+)\n')
# modified_files = re.findall(p, git.status())
# for file in modified_files:
#     print('Adding modified file: ' + file)
#     git.add(file)
#
# # also add deleted files
# p = re.compile(r'deleted:\s+(\S+)\n')
# deleted_files = re.findall(p, git.status())
# for file in deleted_files:
#     print('Removing deleted file: ' + file)
#     git.rm(file)
