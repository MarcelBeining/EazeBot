"""
This module contains utility classes for code maintenance
Developers only!

"""
from abc import abstractmethod, ABC
import warnings
from typing import Dict
import requests
from git import GitCommandError


class GitManagerError(Exception):
    pass


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