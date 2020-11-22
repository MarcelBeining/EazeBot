import re
import shutil
from subprocess import Popen
from git import Repo
import os
from dev_utils import Github, GitManagerError
from eazebot.auxiliary_methods import Sections, ChangeLog
from eazebot import __version__ as current_version

# The owner repo ID of the EazeBot on Github
user = 'MarcelBeining'
repo_id = 'EazeBot'


def increase_version(version_parsed, version_type: int):
    assert 3 > version_type >= 0
    version_parsed[version_type] += 1
    if version_type < 1:
        version_parsed[1] = 0
    if version_type < 2:
        version_parsed[2] = 0
    return '.'.join([str(x) for x in version_parsed])


current_version_parsed = [int(x) for x in current_version.split('.')]
print(f'Current version: {current_version}')

# initialize Repo object, add all relevant files (py) and print the git status
repo = Repo(os.path.dirname(__file__))
assert repo.bare is False, 'Folder is no existing Git repository!'
git = repo.git
git_remote = Github(git_object=git, owner=user, repo_id=repo_id)
branch_of_interest = repo.active_branch.name
print("******Pulling current branch to make sure we are up-to-date...******")
git_remote.git_pull()
user_name = git.config('user.name')

# initialize git steps to do
steps_to_do = []
steps_done = []

# Initializing the ChangeLog class
chglog = ChangeLog(compare_url='https://github.com/MarcelBeining/EazeBot/compare',
                   version_prefix='v')
try:
    if branch_of_interest == 'master':
        # ask for new version type
        answer = input('You are on branch master. Possible options:\n'
                       '- New Hotfix (v*.*.X)\n'
                       'Continue (y/n)?')
        if answer != 'y':
            print('Aborted...')
            exit(0)

        # update version number accordingly
        new_version_string = increase_version(current_version_parsed, 2)

        # fill steps to do list
        steps_to_do.extend(['Log changes to change_log.json and create new change_log.md',
                            f'Checkout to "hotfix/v{new_version_string}"',
                            'Write new version number to __init__.py',
                            'Add __init__.py and change_log* to git stage',
                            "Commit git changes",
                            "Push new branch to origin"])

        # ask for the changes that will be done and add them to the change log
        print(f'******Please log the changes you will be doing on this Hotfix branch! '
              f'This will be used for the change log!******')
        section_list = chglog.ask_for_changes(user_name, [Sections.fixed])
        chglog.create_new_version(new_version_string, section_list)
        chglog.write_log()
        steps_done.append(steps_to_do.pop(0))

        # create the new release branch and checkout
        new_branch_name = f"hotfix/v{new_version_string}"
        git.checkout('HEAD', b=new_branch_name)  # create a new branch
        steps_done.append(steps_to_do.pop(0))

        # change the version in the (caution if at any time there will be more info in __init__ than just
        # version!
        with open('eazebot/__init__.py', 'w') as fh:
            fh.write(f"__version__ = '{new_version_string}'\n")
        steps_done.append(steps_to_do.pop(0))

        git.add('change_log*')
        git.add('eazebot/__init__.py')
        steps_done.append(steps_to_do.pop(0))
        print(git.status())

        # commit and push changes
        git.commit('-m "New Hotfix. Initial branch commit"')
        steps_done.append(steps_to_do.pop(0))
        print(f'******Finished checking out new branch {new_branch_name}. Pushing now...******')
        git_remote.git_push(new_branch_name)
        steps_done.append(steps_to_do.pop(0))
    elif branch_of_interest == 'dev':
        # ask for new version type
        answer = input('You are on branch dev. Possible options:\n'
                       '- New major (vX.0.0) release (1)\n'
                       '- New minor (v*.X.0) release (2)\n'
                       '- New feature branch (3)\n'
                       '- New bugfix branch (4)\n\n'
                       'Please choose a number!')
        assert re.match('^[1-4]$', answer) is not None, 'Please give a number from 1 to 4!'

        answer = int(answer)
        type_version = answer - 1
        if answer <= 2:
            # new release branch
            new_version_string = increase_version(current_version_parsed, type_version)
            new_branch_name = f"release/v{new_version_string}"

            print("******Please log, if there\'ll be any changes to be done on this release branch not already done in "
                  'dev! This will be used for the change log!******')
            ask_list = [Sections.added, Sections.changed, Sections.fixed]
        else:
            new_version_string = None
            if answer == 3:
                branch_type = 'feature'
                ask_list = [Sections.added, Sections.changed]
            else:
                branch_type = 'bugfix'
                ask_list = [Sections.fixed]
            while True:
                branch_name = input(f'What should be the name of the {branch_type} branch?')
                if re.match('^[a-zA-Z_]+$', branch_name) is not None:
                    break
                else:
                    print('Only letters and underscore is allowed!')
            new_branch_name = f"{branch_type}/{branch_name}"
            print(f'******Please log the changes you will be doing on this {branch_type} branch! '
                  f'This will be used for the change log!******')

        # fill steps to do list
        steps_to_do.extend(['Log changes to change_log.json and create new change_log.md',
                            f'Checkout to "{new_branch_name}"',
                            'Write new version number to __init__.py',
                            'Add (__init__.py and) change_log* to git stage',
                            "Commit git changes",
                            "Push new branch to origin"])
        if new_version_string is None:
            steps_to_do.remove('Write new version number to __init__.py')

        # ask for the changes that will be done and add them to the change log
        section_list = chglog.ask_for_changes(user_name, ask_list)
        chglog.create_new_version(new_version_string, section_list)
        chglog.write_log()
        steps_done.append(steps_to_do.pop(0))
        git.checkout('HEAD', b=new_branch_name)  # create a new branch
        steps_done.append(steps_to_do.pop(0))

        if new_version_string is not None:
            # change the version
            # caution if at any time there will be more info in __init__ than just version
            with open('eazebot/__init__.py', 'w') as fh:
                fh.write(f"__version__ = '{new_version_string}'\n")
            steps_done.append(steps_to_do.pop(0))
            git.add('eazebot/__init__.py')

        # commit and push changes
        git.add('change_log*')
        steps_done.append(steps_to_do.pop(0))
        print(git.status())
        commitType = ['Major changes', 'Intermediate changes', 'New feature', 'New bugfix'][type_version]
        git.commit('-m "%s. Initial branch commit"' % commitType)
        steps_done.append(steps_to_do.pop(0))

        print(f'******Finished checking out new branch {new_branch_name}. Pushing now...******')
        git_remote.git_push(new_branch_name)
        steps_done.append(steps_to_do.pop(0))

    elif 'hotfix/' in branch_of_interest or 'release/' in branch_of_interest:
        answer = input(f"Add more change log information? (0)\n"
                       f"Merge branch {branch_of_interest} into:\n- Dev? (1)\n- Master? (2)\n- Dev & Master? (3)\n"
                       f"Please choose a number.")
        if re.match('^[0-3]$', answer) is None:
            print(f"Answer was {answer}, aborting...")
            exit(0)

        if answer == '0':
            # fill steps to do list
            steps_to_do.extend(['Log changes to change_log.json and create new change_log.md',
                                'Add change_log* to git stage',
                                "Commit git changes",
                                "Push new branch to origin"])

            if 'hotfix/' in branch_of_interest:
                ask_sections = [Sections.fixed]
            else:
                ask_sections = [Sections.added, Sections.changed, Sections.fixed]
            section_list = chglog.ask_for_changes(user_name, ask_sections)
            chglog.add_to_version(current_version, section_list)
            chglog.write_log()
            steps_done.append(steps_to_do.pop(0))
            git.add('change_log*')
            steps_done.append(steps_to_do.pop(0))
            print(git.status())
            print(f'******Committing and pushing change log changes now...******')
            git.commit('-m "Added more change log information"')
            steps_done.append(steps_to_do.pop(0))
            git_remote.git_push(branch_of_interest)
            steps_done.append(steps_to_do.pop(0))

        else:
            # fill steps to do list
            steps_to_do.extend(['Create new wheels using create_dist.bat',
                                'Merge branch into dev / master (directly+pushing or via merge request)'])

            if answer == '1':
                branches_to_merge = ['dev']
            elif answer == '2':
                branches_to_merge = ['master']
            else:
                branches_to_merge = ['dev', 'master']

            commit_history = {}
            if 'master' in branches_to_merge:
                # fill steps to do list
                steps_to_do.insert(0, f"Check if latest commit on master is in your branch {branch_of_interest}")
                # only do the commit check if there will be merge into master
                # find last common ancestor between current and branch master
                common_commit = git.execute(['git', 'merge-base', 'HEAD', 'origin/master'])

                # find most recent commit of master
                last_master_commit = git.execute(['git', 'rev-parse', 'origin/master'])
                steps_done.append(steps_to_do.pop(0))
                if common_commit != last_master_commit:
                    raise GitManagerError(f"Your branch {branch_of_interest} does not include the latest commit from "
                                          f"master! Please merge master into your current branch and manually correct "
                                          f"the version numbers accordingly!")
                commit_history['master'] = git.execute([
                    'git', 'log', '--pretty=format:"%h%x09%an:%x09%s"', f'{last_master_commit}..HEAD'])
            if 'dev' in branches_to_merge:
                last_dev_commit = git.execute(['git', 'rev-parse', 'origin/dev'])
                commit_history['dev'] = git.execute(['git', 'log', '--pretty=format:"%h%x09%an:%x09%s"',
                                                    f'{last_dev_commit}..HEAD'])

            protected_branches = git_remote.get_protected_branches()
            descr = None
            shutil.rmtree('dist')
            # create the new wheel distribution
            p = Popen(['python', 'setup.py', 'sdist', 'bdist_wheel'], cwd=os.path.dirname(__file__))
            p.wait()
            print('******New wheel file created.******')
            steps_done.append(steps_to_do.pop(0))
            # replace this message with the real ones
            steps_to_do.pop(0)
            for main_branch in branches_to_merge:
                if main_branch in protected_branches:
                    steps_to_do.append(f'Create merge request for branch {branch_of_interest} into {main_branch}')
                else:
                    steps_to_do.append(f'Merge branch {branch_of_interest} into {main_branch}')
                    steps_to_do.append(f'Push {main_branch} to origin')

            for main_branch in branches_to_merge:
                if main_branch in protected_branches:
                    print(f'******{main_branch} is a protected branch on Remote! Creating merge request...******')
                    if descr is None:
                        descr = input(f'Enter some description for the merge to {main_branch} '
                                      f'(adding all git commit messages if nothing entered)\n')
                        if len(descr) <= 1:
                            text = '* ' + '* '.join(commit_history[main_branch].splitlines(True))

                            def descr(br):
                                return f"Merge of {branch_of_interest} into {br}.\n\nGit history:\n\n{text}"
                    git_remote.create_merge_request(
                        source_branch=branch_of_interest,
                        target_branch=main_branch,
                        description=descr(main_branch) if callable(descr) else descr)
                    steps_done.append(steps_to_do.pop(0))
                else:
                    print(f'******Merging {branch_of_interest} into {main_branch} , tagging and pushing...******')

                    git.checkout(main_branch)
                    git.merge(['--no-ff', branch_of_interest])
                    steps_done.append(steps_to_do.pop(0))
                    if main_branch == 'master':
                        git.execute(['git', 'tag', f'v{current_version}'])  # -a x -m "{commit_message}\"
                        git_remote.git_push(main_branch, tag=f'v{current_version}')
                    git_remote.git_push(main_branch)
                    steps_done.append(steps_to_do.pop(0))

    elif 'feature/' in branch_of_interest or 'bugfix/' in branch_of_interest:
        answer = input(f"Add more change log information? (0)\n"
                       f"Merge branch {branch_of_interest} into dev? (1)\n"
                       f"Please choose one option by typing the number.\n")
        if re.match('^[0-1]$', answer) is None:
            print(f"Answer was {answer}, aborting...")
            exit(0)

        if answer == '0':
            # fill steps to do list
            steps_to_do.extend(['Log changes to change_log.json and create new change_log.md',
                                'Add change_log* to git stage',
                                "Commit git changes",
                                "Push new branch to origin"])

            if 'bugfix/' in branch_of_interest:
                ask_sections = [Sections.fixed]
            else:
                ask_sections = [Sections.added, Sections.changed, Sections.fixed]
            section_list = chglog.ask_for_changes(user_name, ask_sections)
            chglog.add_to_version(None, section_list)
            chglog.write_log()
            steps_done.append(steps_to_do.pop(0))
            git.add('change_log*')
            steps_done.append(steps_to_do.pop(0))
            print(git.status())
            print(f'******Committing and pushing change log changes now...******')
            git.commit('-m "Added more change log information"')
            steps_done.append(steps_to_do.pop(0))
            git_remote.git_push(branch_of_interest)
            steps_done.append(steps_to_do.pop(0))
        else:
            print('******Checking latest commit of dev...******')
            steps_to_do.insert(0, f"Check if latest commit on dev is in your branch {branch_of_interest}")

            # find last common ancestor between current and branch dev
            common_commit = git.execute(['git', 'merge-base', 'HEAD', 'origin/dev'])

            # find most recent commit of dev
            last_dev_commit = git.execute(['git', 'rev-parse', 'origin/dev'])
            steps_done.append(steps_to_do.pop(0))
            if common_commit != last_dev_commit:
                raise GitManagerError(f"Your branch {branch_of_interest} does not include the latest commit from dev!"
                                      f"Please merge dev into your current branch and rerun the script!")

            protected_branches = git_remote.get_protected_branches()
            if 'dev' in protected_branches:
                # fill steps to do list
                steps_to_do.append(f'Create merge request for branch {branch_of_interest} into dev')

                print('******Dev is a protected branch on Remote! Creating merge request...******')
                descr = input(f'Enter some description for the merge to dev (git commit history if nothing entered)\n')
                if len(descr) <= 1:
                    commit_history = git.execute([
                        'git', 'log', '--pretty=format:"%h%x09%an:%x09%s"', f'{last_dev_commit}..HEAD'])
                    commit_history = '* ' + '* '.join(commit_history.splitlines(True))
                    descr = f"Merge of {branch_of_interest} into dev.\n\nGit history:\n{commit_history}"
                git_remote.create_merge_request(
                    source_branch=branch_of_interest,
                    target_branch='dev',
                    description=descr)
                steps_done.append(steps_to_do.pop(0))

            else:
                steps_to_do.append(f'Merge branch {branch_of_interest} into dev')
                steps_to_do.append(f'Push dev to origin')
                print(f'******Merging {branch_of_interest} into dev and pushing...******')
                # merge into dev
                git.checkout('dev')
                git.merge(['--no-ff', branch_of_interest])
                steps_done.append(steps_to_do.pop(0))
                git_remote.git_push('dev')
                steps_done.append(steps_to_do.pop(0))

    else:
        raise GitManagerError(f"Unknown branch {branch_of_interest}")
except Exception as e:
    if isinstance(e, GitManagerError):
        raise e
    msg = f"Exception was raised:\n{e}\n\nThese steps had been performed successfully:\n"
    msg += '-' + '\n-'.join(steps_done)
    msg += "\n\nThese steps still need to be done (manually now):\n"
    msg += '-' + '\n-'.join(steps_to_do)
    raise Exception(msg)
