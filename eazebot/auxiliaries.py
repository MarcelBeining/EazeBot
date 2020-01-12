# -*- coding: utf-8 -*-
"""
Created on Fri Feb  1 08:43:48 2019

@author: beiningm
"""
import os
import logging 
import dill
from copy import deepcopy
from shutil import copy2
from collections import defaultdict
import time
import importlib


def copyJSON(folder=os.getcwd(), force=0, warning=True):
    if force == 0 and os.path.isfile(os.path.join(folder, 'botConfig.json')) and warning:
        print('Warning: botConfig.json already exists in\n%s\n'
              'If wanted, use copyJSON(targetfolder,force=1) or copyJSON(force=1) to overwrite both (!) JSONs' % folder)
    else:
        copy2(os.path.join(os.path.dirname(__file__), 'botConfig.json'), folder)
    if force == 0 and os.path.isfile(os.path.join(folder, 'APIs.json')) and warning:
        print('Warning: APIs.json already exists in\n%s\n'
              'If wanted, use copyJSON(targetfolder,force=1) or copyJSON(force=1) to overwrite both (!) JSONs' % folder)
    else:  
        copy2(os.path.join(os.path.dirname(__file__), 'APIs.json'), folder)
    copy2(os.path.join(os.path.dirname(__file__), 'startBotScript.py'), folder)
    copy2(os.path.join(os.path.dirname(__file__), 'startBot.bat'), folder)
    copy2(os.path.join(os.path.dirname(__file__), 'updateBot.bat'), folder)
    print('botConfig.json and APIs.json successfully copied to\n%s\n'
          'Please open and configure these files before running the bot' % folder)


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


def save_data(arg):
    if isinstance(arg, dict):
        user_data = deepcopy(arg)
    else:
        user_data = deepcopy(arg.job.context.dispatcher.user_data)
    # remove backup
    try:
        os.remove('data.bkp') 
    except FileNotFoundError:
        logging.warning('No backup file found')
        pass
    # rename last save to backup
    try:
        os.rename('data.pickle', 'data.bkp')
        logging.info('Created user data autosave backup')
    except [FileNotFoundError, PermissionError]:
        logging.warning('Could not rename last saved data to backup')
        pass
    clean_data(user_data)
    # write user data
    with open('data.pickle', 'wb') as f:
        dill.dump(user_data, f)
    logging.info('User data autosaved')


def backup_data(arg):
    if isinstance(arg, dict):
        user_data = deepcopy(arg)
    else:
        user_data = deepcopy(arg.job.context.dispatcher.user_data)
        
    clean_data(user_data)
    # write user data
    if not os.path.isdir('backup'):
        os.mkdir('backup')
    with open(os.path.join('backup', time.strftime('%Y_%m_%d_data.pickle')), 'wb') as f:
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
        
        
def load_data(filename='data.pickle'):
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
            convert_data(from_=from_, to_=to_, filename='data.pickle', filenameout='data.pickle')
            with open(filename, 'rb') as f:
                return dill.load(f)
        except Exception as e:
            raise e
    else:
        logging.error('No autosave file found')
        return defaultdict(dict)    
