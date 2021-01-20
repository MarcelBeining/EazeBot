# -*- coding: utf-8 -*-
"""
Created on Fri Feb  1 08:43:48 2019

@author: beiningm
"""
import json
import os
import logging
import re
from datetime import datetime
from enum import Enum
from typing import Union, Dict, List

import ccxt
import dill
from copy import deepcopy
from shutil import copy2
from collections import defaultdict
import time
import importlib
import warnings

from telegram import Bot
from telegram.error import BadRequest

logger = logging.getLogger(__name__)


class TelegramHandler(logging.Handler):
    def __init__(self, bot, level):
        self.bot = bot
        super().__init__(level=level)
        self.addFilter(TelegramFilter())

    def emit(self, record):
        # return msg to user
        count = 0
        while count < 5:
            try:
                self.bot.send_message(chat_id=record.chatId, text=self.format(record), parse_mode='markdown')
                break
            except TypeError:
                pass
            except Exception:
                count += 1
                logger.warning(
                    'Some connection (?) error occured when trying to send a telegram message. Retrying..')
                time.sleep(1)
                continue
        if count >= 5:
            logger.error('Could not send message to bot')


class TelegramFilter(logging.Filter):
    def filter(self, record):
        return hasattr(record, 'chatId')


def copy_init_files(folder=os.getcwd(), force=0, warning=True):
    template_folder = os.path.join(os.path.dirname(__file__), 'templates')
    user_folder = os.path.join(folder, 'user_data')
    if not os.path.isdir(user_folder):
        os.mkdir(user_folder)
    # copy jsons in user_data subfolder
    if force == 0 and os.path.isfile(os.path.join(user_folder, 'botConfig.json')):
        if warning:
            warnings.warn('Warning: botConfig.json already exists in\n%s\nIf wanted, use copy_user_files(targetfolder,'
                          ' force=1) or copy_user_files(force=1) to overwrite both (!) JSONs' % user_folder)
    else:
        copy2(os.path.join(template_folder, 'botConfig.json.tmp'), os.path.join(user_folder, 'botConfig.json'))

    if force == 0 and os.path.isfile(os.path.join(user_folder, 'APIs.json')):
        if warning:
            warnings.warn('Warning: APIs.json already exists in\n%s\nIf wanted, use copy_user_files(targetfolder,'
                          ' force=1) or copy_user_files(force=1) to overwrite both (!) JSONs' % user_folder)
    else:  
        copy2(os.path.join(template_folder, 'APIs.json.tmp'), os.path.join(user_folder, 'APIs.json'))

    # copy rest of files in main folder
    other_files = set(os.listdir(template_folder)) - {'APIs.json.tmp', 'botConfig.json.tmp'}

    if os.environ.get('IN_DOCKER_CONTAINER', False):
        folder_str = f' to target folder.'
        is_docker = True
    else:
        folder_str = f' to\n{folder}'
        is_docker = False

    for file in other_files:
        if '.bat' in file:
            # do not copy bat files if not on windows (can only check if not running with docker)
            if not is_docker and os.name != 'nt':
                continue

            # do only copy the correct bat files
            if is_docker and '.python.' in file:
                continue
            elif not is_docker and '.docker.' in file:
                continue
            else:
                copy2(os.path.join(template_folder, file), os.path.join(folder, file[0:-11]))
        else:
            copy2(os.path.join(template_folder, file), os.path.join(folder, file[0:-4]))

    print(f'User files successfully copied{folder_str}\n'
          'Please configure the json files before running the bot '
          '(e.g. by running "python -m eazebot --config"')


def start_config_dialog(user_dir='user_data'):
    with open(os.path.join(user_dir, 'botConfig.json'), 'r') as fh:
        bot_config = json.load(fh)
    for key in bot_config:
        while True:
            res = input(f"Please enter your {key} [Default:{bot_config[key]}]")
            res = res or bot_config[key]
            if res != 'PLACEHOLDER':
                break
            else:
                print(f"You have to replace the placeholder by a valid input!")

        if isinstance(res, str):
            if res.isnumeric():
                res = int(res)
            elif re.match(r'^-?\d+(?:\.\d+)?$', res):
                res = float(res)

        bot_config[key] = res
    with open(os.path.join(user_dir, 'botConfig.json'), 'w') as fh:
        json.dump(bot_config, fh)

    with open(os.path.join(user_dir, 'APIs.json'), 'r') as fh:
        api_config = json.load(fh)
    entries_to_del = []
    for n_exch, exch in enumerate(api_config):
        if not('exchange' in exch and 'key' in exch and 'secret' in exch):
            print(f"API entry {exch} does not have the reuired keys 'exchange', 'key' and 'secret' and is deleted!")
            entries_to_del.append(n_exch)
        else:
            while True:
                res = input(f"Keep API key {exch['key']} from exchange {exch['exchange']} ? [y/n]")
                if res in ['y', 'n']:
                    break
            if res == 'n':
                entries_to_del.append(n_exch)

    for index in sorted(entries_to_del, reverse=True):
        del api_config[index]

    while True:
        res = input(f"Add another API key? [y/n]")
        if res == 'y':
            api_dict = {}
            flag = False
            while True:
                api_exch = input(f"Please type the exchange name as lower case:")
                if api_exch in ccxt.exchanges:
                    if api_exch in (val['exchange'] for val in api_config):
                        print(f"You already have set an API key pair for that exchange!")
                        flag = True
                    break
                else:
                    print(f"The exchange name has to be one of:\n {ccxt.exchanges}")
            if flag:
                continue
            api_key = input(f"Please type in or paste the API key provided by {api_exch}:")
            api_secret = input(f"Please type in or paste the API secret provided by {api_exch}:")
            api_dict.update({'exchange': api_exch, 'key': api_key, 'secret': api_secret})
            res = input(f"Does a password belong to that API key (not your exchange password!)? [y/n]")
            if res == 'y':
                res = input(f"Please type in or paste the API password provided by {api_exch}:")
                if res:
                    api_dict['password'] = res
            res = input(f"Does a unique id (uid) belong to that API key? [y/n]")
            if res == 'y':
                res = input(f"Please type in or paste the API uid provided by {api_exch}:")
                if res:
                    api_dict['uid'] = res
            api_config.append(api_dict)
        else:
            break
    with open(os.path.join(user_dir, 'APIs.json'), 'w') as fh:
        json.dump(api_config, fh)

    print('EazeBot successfully configurated. You can now start the bot!')


def clean_data(user_data, allowed_users=None):
    del_these = []
    for user in user_data:
        # discard unknown users
        if not ((allowed_users is None or user in allowed_users) and 'trade' in user_data[user]):
            del_these.append(user)
        else:  # discard cached messages
            if 'taxWarn' not in user_data[user]['settings']:
                user_data[user]['settings']['taxWarn'] = True
            if 'messages' in user_data[user]:
                typ = list(user_data[user]['messages'].keys())
                for t in typ:
                    user_data[user]['messages'][t] = []
            user_data[user]['lastFct'] = []
            user_data[user].pop('exchanges', None)
    for k in del_these:
        user_data.pop(k, None)

    return user_data


def save_data(arg, user_dir: str = 'user_data'):
    if isinstance(arg, dict):
        user_data = deepcopy(arg)
    else:
        user_data = deepcopy(arg.job.context.dispatcher.user_data)

    # remove backup
    try:
        os.remove(os.path.join(user_dir, 'data.bkp'))
    except FileNotFoundError:
        logger.warning('No backup file found')
        pass
    # rename last save to backup
    try:
        os.rename(os.path.join(user_dir, 'data.pickle'), os.path.join(user_dir, 'data.bkp'))
        logger.info('Created user data autosave backup')
    except (FileNotFoundError, PermissionError):
        logger.warning('Could not rename last saved data to backup')
        pass
    clean_data(user_data)
    # write user data
    with open(os.path.join(user_dir, 'data.pickle'), 'wb') as f:
        dill.dump(user_data, f)
    logger.info('User data autosaved')


def backup_data(arg, user_dir: str = 'user_data', max_count=12):
    if isinstance(arg, dict):
        user_data = deepcopy(arg)
    else:
        user_data = deepcopy(arg.job.context.dispatcher.user_data)
        
    clean_data(user_data)
    # write user data
    if not os.path.isdir(os.path.join(user_dir, 'backup')):
        os.mkdir(os.path.join(user_dir, 'backup'))
    with open(os.path.join(user_dir, 'backup', time.strftime('%Y_%m_%d_data.pickle')), 'wb') as f:
        dill.dump(user_data, f)
    files = [f for f in os.path.join(user_dir, 'backup') if f.endswith('_data.pickle')]
    files.sort()
    n_files = len(files)
    # removes oldes files (as date is in file name until max count is reached)
    for n, _ in enumerate(files):
        if n_files > max_count:
            os.remove(files[n])
            n_files -= 1
        else:
            break

    logger.info('User data backuped')
    
    
def convert_data(from_='linux', to_='win', filename='data.pickle', filenameout='data.pickle.new'):
    with open(filename, 'rb') as fi:
        byte_content = fi.read()
        with open(filenameout, 'wb') as fo:
            if 'linux' in from_ and 'win' in to_:
                byte_content = byte_content.replace(b'cdill._dill', b'cdill.dill')
            elif 'win' in from_ and 'linux' in to_:
                byte_content = byte_content.replace(b'cdill.dill', b'cdill._dill')
            if 'git' not in from_ and 'git' in to_:
                byte_content = byte_content.replace(b'ceazebot.tradeHandler', b'ctradeHandler')
                byte_content = byte_content.replace(b'ceazebot.EazeBot', b'cEazeBot')
            elif 'git' in from_ and 'git' not in to_:
                byte_content = byte_content.replace(b'ctradeHandler', b'ceazebot.tradeHandler')
                byte_content = byte_content.replace(b'cEazeBot', b'ceazebot.EazeBot')
            fo.write(byte_content)
        
        
def load_data(filename='data.pickle', user_dir: str = 'user_data', no_dialog: bool = False):

    filename = os.path.join(user_dir, filename)
    # load latest user data
    if os.path.isfile(filename):
        if not no_dialog and os.path.getmtime(filename) < time.time() - 60*60*24*14:
            answer = input('WARNING! The tradeSet data you want to load is older than 2 weeks! '
                           'Are you sure you want to load it? (y/n): ')
            if answer != 'y':
                os.rename(filename, filename.replace('.pickle', '.old'))
        try:
            with open(filename, 'rb') as f:
                logger.info('Loading user data')
                try:
                    return dill.load(f)
                except ModuleNotFoundError:
                    # file probably comes from another OS or eazebot is no installed package
                    # as the txt replacement does only occcur if it finds the
                    # corresponding linux/win/git strings, a wrong "from" part does
                    # not matter
                    if os.name == 'nt':
                        from_ = 'linux'
                        to_ = 'win'
                    else:
                        from_ = 'win'
                        to_ = 'linux'
                    if importlib.util.find_spec("eazebot") is None:
                        to_ += 'git'
                    else:
                        from_ += 'git'
            convert_data(from_=from_, to_=to_, filename=filename, filenameout=filename)
            with open(filename, 'rb') as f:
                return dill.load(f)
        except Exception as e:
            raise e
    else:
        logger.error('No autosave file found')
        return defaultdict(dict)    


def is_higher_version(next_version: str, this_version: str):
    for a, b in zip(next_version.split('.'), this_version.split('.')):
        if int(a) > int(b):
            return True
        elif int(a) < int(b):
            return False
    return False


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

    def _init_json(self):
        template = {
            "general": [
                {
                    "title": "Changelog",
                    "description": "All notable changes to this project will be documented in this file.\n\n"
                                   "The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), "
                                   "and this project adheres to "
                                   "[Semantic Versioning](https://semver.org/spec/v2.0.0.html)."
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
        from pystache import Renderer
        extended_data = self._add_branch_comparison(self.data)
        with open(self.template_file, 'r') as fh:
            template = fh.read()
        with open(self.file_name + '.md', 'w') as fh:
            fh.write(Renderer().render(template, extended_data))


class MessageContainer:
    def __init__(self, bot: Bot, chat_id):

        self.msgs = dict(history=[], dialog=[], botInfo=[], settings=[], status=[], start=[], balance=[])
        self.bot = bot
        self.chat_id = chat_id
        self.last_message_from = None

    def __deepcopy__(self, memo):
        # create a copy with self.linked_to *not copied*, just referenced.
        return None  # MessageContainer(bot=copy(self.bot), chat_id=self.chat_id)

    def check_which(self, which):
        if which not in self.msgs:
            self.msgs[which] = []

    def delete_msgs(self, which: Union[str, List], note=None, only_forget=False):
        if which == 'all':
            which = list(self.msgs.keys())
        elif not isinstance(which, list):
            which = [which]
        for wh in which:
            self.check_which(wh)
            messages_to_keep = []
            for msg in self.msgs[wh]:
                if note is None or msg[0] == note:
                    if not only_forget:
                        try:
                            msg[1].delete()
                        except Exception:
                            pass
                else:
                    messages_to_keep.append(msg)
            self.msgs[wh] = messages_to_keep

    def _send(self, which: str, *args, what='message', note=None, **kwargs):
        if what == 'message':
            self.msgs[which].append([note, self.bot.send_message(*args, chat_id=self.chat_id, **kwargs)])
        elif what == 'photo':
            self.msgs[which].append([note, self.bot.send_photo(*args, chat_id=self.chat_id, **kwargs)])
        else:
            raise ValueError(f"Unknown value {what} for what.")

    def send(self, which: str, *args, what='message', overwrite_last=True, note=None, **kwargs):
        self.check_which(which)
        if not overwrite_last or self.last_message_from != which or len(self.msgs[which]) == 0 or what != 'message':
            if overwrite_last:
                self.delete_msgs(which=which, note=note)
            self._send(which=which, *args, what=what, note=note, **kwargs)
        else:
            idx = None
            try:
                if note is None:
                    idx = -1
                    message = self.msgs[which][idx][1]
                    message.edit_text(*args, **kwargs)
                else:
                    found = False
                    for idx, message in enumerate(self.msgs[which]):
                        if message[0] == note:
                            found = True
                            message[1].edit_text(*args, **kwargs)
                    if not found:
                        idx = None
                        self._send(which=which, *args, what=what, note=note, **kwargs)
            except BadRequest as e:
                if 'not modified' in str(e):
                    pass
                elif 'Message to edit not found' in str(e):
                    if idx is not None:
                        self.msgs[which].pop(idx)
                    self._send(which=which, *args, what=what, note=note, **kwargs)
                else:
                    raise e

        self.last_message_from = which
