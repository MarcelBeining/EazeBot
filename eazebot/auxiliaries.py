# -*- coding: utf-8 -*-
"""
Created on Fri Feb  1 08:43:48 2019

@author: beiningm
"""
import json
import os
import logging
import re

import ccxt
import dill
from copy import deepcopy
from shutil import copy2
from collections import defaultdict
import time
import importlib
import warnings


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
        logging.warning('No backup file found')
        pass
    # rename last save to backup
    try:
        os.rename(os.path.join(user_dir, 'data.pickle'), os.path.join(user_dir, 'data.bkp'))
        logging.info('Created user data autosave backup')
    except (FileNotFoundError, PermissionError):
        logging.warning('Could not rename last saved data to backup')
        pass
    clean_data(user_data)
    # write user data
    with open(os.path.join(user_dir, 'data.pickle'), 'wb') as f:
        dill.dump(user_data, f)
    logging.info('User data autosaved')


def backup_data(arg, user_dir: str = 'user_data'):
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
    logging.info('User data backuped')   
    
    
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
        
        
def load_data(filename='data.pickle', user_dir: str = 'user_data'):

    filename = os.path.join(user_dir, filename)
    # load latest user data
    if os.path.isfile(filename):
        if os.path.getmtime(filename) < time.time() - 60*60*24*14:
            answer = input('WARNING! The tradeSet data you want to load is older than 2 weeks! '
                           'Are you sure you want to load it? (y/n): ')
            if answer != 'y':
                os.rename('data.pickle', 'data.old')
        try:
            with open(filename, 'rb') as f:
                logging.info('Loading user data')
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
        logging.error('No autosave file found')
        return defaultdict(dict)    
