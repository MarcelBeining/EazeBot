"""
This module contains utility classes for code maintenance
Developers only!

"""
import os
from abc import abstractmethod, ABC
from copy import deepcopy
from enum import Enum
import json
import warnings
from typing import Dict, List, Union
from datetime import datetime
import pystache
import requests
from git import GitCommandError


class GitManagerError(Exception):
    pass


class Sections(Enum):
    """
    Enumerator to define possible change log sections
    """
    added = 'Added'
    changed = 'Changed'
    fixed = 'Fixed'


class ChangeLog:
    """
    A class to create a formatted markdown change log from a mustache template and the changes as json

    """
    def __init__(self, file: str = 'change_log', template_file: str = 'change_log.tpl',
                 compare_url=None, version_prefix: str = ''):
        """

        :param file: File name without ending of the markdown change log file to be generated
        :param template_file:  File name of the change log template. Has to be in mustache format
        :param compare_url: Git url that is used to compare commits/branches with each other. Mostly ends with /compare/
        :param version_prefix: Optional prefix that will be added to the version string before creating the log data
        """
        self.file_name = file

        self.data = {}
        if not os.path.isfile(file + '.json'):
            self._init_json()
        self.read_json()
        self.compare_url = compare_url
        self.version_prefix = version_prefix
        self.template_file = template_file
        self.renderer = pystache.Renderer()

    def _init_json(self):
        template = {
            "general": [
                {
                    "title": "Changelog",
                    "description": "All notable changes to this project will be documented in this file.\n\n"
                                   "The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), "
                                   "and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)."
                }
            ],
            "versions": []
        }
        with open(self.file_name + '.json', 'w') as fh:
            json.dump(template, fh, indent=4)

    def read_json(self):
        with open(self.file_name + '.json', 'r') as fh:
            data = json.load(fh)
        # assert version info sorted in descending date order
        data['versions'] = sorted(data['versions'], key=lambda x: x['date'] if x['date'] != '' else 'Z',
                                  reverse=True)
        self.data = data

    def write_json(self):
        with open(self.file_name + '.json', 'w') as fh:
            json.dump(self.data, fh, indent=4)

    def get_version(self, version: str) -> Union[None, Dict]:
        """
        Returns a copy of the change log for the requested version

        :param version: The requested version as string
        :return: The version's change log as dict

        """
        for version_dict in self.data['versions']:
            if version_dict['version'] == self.version_prefix + version:
                return deepcopy(version_dict)
        return None

    def get_changes(self, prev_version: str, this_version: str, text_only: bool = False) -> List:
        chg_list = []
        for version_dict in self.data['versions']:
            if self.version_prefix + prev_version < version_dict['version'] <= self.version_prefix + this_version:
                if text_only:
                    for sec in version_dict['section']:
                        for entry in sec['entries']:
                            chg_list.append(entry['message'])
                else:
                    chg_list.append(version_dict)
        return chg_list


    @staticmethod
    def ask_for_changes(user: str, sections: List[Sections]) -> List:
        """
        This method asks interactively for changes and returns a section list ready to be handed over to ChangeLog
        :param user: Name of the user, who did the changes. Should be the git user name if possible
        :param sections: A list of sections that should be added
        :return:
        """
        section_list = []
        for section in sections:
            assert isinstance(section, Sections), 'List entries have to be values from the Enum "Sections"!'
            sec_string = section.value
            entries = []
            while True:
                answer = input(
                    f"Any (more) changes to document for section \n'{sec_string}'\n? "
                    f"(Type the change or enter nothing for continuing)\n")
                if answer == '':
                    break
                else:
                    entries.append({'author': user,
                                    'message': answer})
            if entries:
                section_list.append({'label': sec_string,
                                     'entries': entries})
        return section_list

    @staticmethod
    def _add_sections(version_dict: Dict, sections: Dict) -> Dict:
        """

        :param version_dict:
        :param sections:
        :return:
        """
        label_dict = {}
        for n, section in enumerate(version_dict['section']):
            label_dict[section['label']] = n
        for section in sections:
            label = section['label']
            if label not in label_dict:
                # create section
                version_dict['section'].append({'label': label, 'entries': []})
                label_dict[label] = len(version_dict['section']) - 1
            # add all messages of unrel_dicts section to this section
            version_dict['section'][label_dict[label]]['entries'].extend(section['entries'])
        return version_dict

    def create_new_version(self, new_version: str, new_sections=None):
        """
        Adds a new version to the change log
        :param new_version: String of the new version, such as v0.5.2 . If the changes are still for an unreleased \
        state, use None!
        :param new_sections: A formatted list of new_sections, obtained from method ask_for_changes
        :return:
        """
        if new_version is None or new_version == 'Unreleased':
            new_version = 'Unreleased'
        else:
            new_version = self.version_prefix + new_version
        date_ = datetime.now().strftime('%Y-%m-%d %H:%M') if new_version != 'Unreleased' else ''

        found = False
        # search for existing version with same string (forbidden) or Unreleased tag (will be moved into new version)
        for version_dict in self.data['versions']:
            # remember, self.data is a dict (i.e. mutable) so all changes directly apply to it
            if version_dict['version'] == new_version and new_version != 'Unreleased':
                raise Exception(f"Version {new_version} already exists! Use method add_to_version if you want to add "
                                f"sections to an existing version!")
            elif version_dict['version'] == 'Unreleased':
                found = True
                version_dict['version'] = new_version
                version_dict['date'] = date_
                if new_sections is not None:
                    # add new sections. No need to get result as dicts are mutable
                    self._add_sections(version_dict, new_sections)

        if not found:
            if new_sections is None:
                raise Exception('No entry found for Unreleased version and no new version information added. '
                                'Adding empty new version is not allowed!')
            else:
                self.data['versions'].insert(0,
                                             {'version': new_version,
                                              'date': date_,
                                              'section': new_sections})

        # update the json file
        self.write_json()

    def add_to_version(self, version: Union[str, None], new_sections):
        """
        Adds change logs to an existing version
        :param version: String of the version to add changes to, such as v0.5.2 . If the changes are still for an \
        unreleased state, use None!
        :param new_sections: A formatted list of new_sections, obtained from method ask_for_changes
        :return:
        """
        if version is None or version == 'Unreleased':
            version = 'Unreleased'
        else:
            version = self.version_prefix + version
        found = False
        for version_dict in self.data['versions']:
            # remember, self.data is a dict (i.e. mutable) so all changes directly apply to it
            if version_dict['version'] == version:
                found = True
                # add new sections. No need to get result as dicts are mutable
                self._add_sections(version_dict, new_sections)

        if not found:
            self.create_new_version(new_version=version, new_sections=new_sections)

        # update the json file
        self.write_json()

    def _add_branch_comparison(self, data: Dict):
        if self.compare_url is not None:
            if 'version_comparison' in data:
                data.pop('version_comparison')
            # assumes the dict is ordered by date!!
            newer_version = None
            comparison_list = []
            for version_dict in data['versions']:
                if newer_version is None:
                    newer_version = version_dict['version']
                else:
                    comparison_list.append({
                        'version': newer_version,
                        'url': f"{self.compare_url}/{version_dict['version']}..."
                               f"{newer_version if newer_version != 'Unreleased' else 'dev'}"
                    })
            data['version_comparison'] = comparison_list
        return data

    def write_log(self):
        extended_data = self._add_branch_comparison(self.data)
        with open(self.template_file, 'r') as fh:
            template = fh.read()
        with open(self.file_name + '.md', 'w') as fh:
            fh.write(self.renderer.render(template, extended_data))


class BaseGitPlattform(ABC):
    """
    A base class to communicate with platforms such as Gitlab and Github for pushing and merge requests

    """

    @property
    @abstractmethod
    def base_url(self):
        raise NotImplementedError

    def __init__(self, git_object, repo_id, ssh_works=True):
        """

        :param git_object: git object from git python
        :param repo_id: Platforms repo id or repo name
        :param ssh_works: Boolean if ssh connection to platform is set
        """
        self.git_obj = git_object
        self.token = None
        self.pw = None
        self.repo_id = repo_id
        self.http_success = [200, 201, 202, 203, 204, 205, 206, 207, 208, 226]
        self.ssh_works = ssh_works

    def git_push(self, branch='HEAD', tag=None):
        self.git_remote(method='push', branch=branch, tag=tag)

    def git_pull(self):
        self.git_remote(method='pull')

    @abstractmethod
    def _set_git_to(self, method='SSH'):
        """

        :param method: SSH or HTTPS
        :return:
        """
        raise NotImplementedError

    def git_remote_https(self, method, branch='HEAD', tag=None):
        assert method in ['push', 'pull']
        if branch == 'HEAD':
            branch = self.git_obj.execute(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])

        self._set_git_to('HTTPS')

        try:
            if method == 'push':
                self.git_obj.execute(['git', 'push', 'origin', branch])
                if tag is not None:
                    self.git_obj.execute([f'git', 'push', 'origin', f'refs/tags/{tag}'])
            else:
                self.git_obj.execute(['git', 'pull', 'origin', branch])
        except GitCommandError as e:
            raise Exception(f"Trying to communicate via https failed due to:\n{str(e)}\n\n"
                            f"Please pull/push manually!!!")
        finally:
            # make sure remote tracking is set back to the default
            self.git_obj.fetch('origin')
            self.git_obj.execute([f'git', 'branch', '--set-upstream-to', f'origin/{branch}'])
            self._set_git_to('SSH')

    def git_remote(self, method, branch='HEAD', tag=None):
        assert method in ['push', 'pull']
        if branch == 'HEAD':
            branch = self.git_obj.execute(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])
        self.git_obj.checkout(branch)
        if self.ssh_works:
            try:
                if method == 'push':
                    self.git_obj.execute([f'git', 'push', '--set-upstream', 'origin', branch])
                    if tag is not None:
                        self.git_obj.execute([f'git', 'push', 'origin', f'refs/tags/{tag}'])
                else:
                    self.git_obj.execute(['git', 'pull', 'origin'])
            except GitCommandError as e:
                if 'correct access rights' in str(e):
                    warnings.warn('It seems your ssh keys are not existent/accessible. Trying to communicate via https')
                    self.ssh_works = False
                    self.git_remote_https(method=method, branch=branch, tag=tag)
                else:
                    raise e
        else:
            self.git_remote_https(method=method, branch=branch, tag=tag)

    @abstractmethod
    def get_access(self):
        """
        Gets an access token and stores it under self.token

        :return:
        """
        raise NotImplementedError

    @abstractmethod
    def _make_request(self, url, method='GET', **kwargs):
        """
        Implements the request itself including the authentication

        :param url: The url to request
        :param method: GET, POST, PUT
        :param kwargs: additional request keyword args such as params
        :return: Returns the request
        """
        raise NotImplementedError

    @abstractmethod
    def get_protected_branches(self):
        raise NotImplementedError

    @abstractmethod
    def create_merge_request(self, source_branch, target_branch, description):
        raise NotImplementedError


class Github(BaseGitPlattform):
    base_url = 'https://api.github.com'

    def __init__(self, git_object, owner: str, repo_id: str):
        self.owner = owner
        super().__init__(git_object=git_object, repo_id=repo_id)

    def get_protected_branches(self):
        response = self._make_request(f'{self.base_url}/repos/{self.owner}/{self.repo_id}/branches')
        protected = []
        for br in response:
            if br['protected']:
                if 'required_pull_request_reviews' in self._make_request(
                        f"{self.base_url}/repos/{self.owner}/{self.repo_id}/branches/{br['name']}/protection"):
                    protected.append(br['name'])
        return protected

    def create_merge_request(self, source_branch, target_branch, description):
        raise NotImplementedError

    def get_access(self):
        with open('github_token', 'r') as fh:
            self.token = fh.read().strip()

    def _make_request(self, url, method='GET', **kwargs) -> Dict:
        if self.token is None:
            self.get_access()
        response = requests.request(method.upper(), url, auth=(self.owner, self.token), **kwargs)
        if response.status_code not in self.http_success:
            raise ConnectionError(response.text)
        return response.json()

    def _set_git_to(self, method='SSH'):
        info = self._make_request(f'{self.base_url}/repos/{self.owner}/{self.repo_id}')
        if method == 'SSH':
            self.git_obj.execute(['git', 'remote', 'set-url', 'origin', info['ssh_url']])
        else:
            url = info['git_url'].replace('git://', f'https://{self.owner}:{self.token}@')
            # set origin to https url
            self.git_obj.execute(['git', 'remote', 'set-url', 'origin', url])