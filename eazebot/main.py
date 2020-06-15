import argparse
import logging
from logging.handlers import RotatingFileHandler
import os

log_file_name = 'telegramEazeBot'

log_formatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")
logger = logging.getLogger('eazebot')
logger.handlers = []  # delete old handlers in case bot is restarted but not python kernel
logger.setLevel('INFO')  # DEBUG
file_handler = RotatingFileHandler("{0}/{1}.log".format(os.getcwd(), log_file_name),
                                                    maxBytes=1000000,
                                                    backupCount=5)
file_handler.setFormatter(log_formatter)
logger.addHandler(file_handler)
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)


def check_dir_arg(folder):
    if not os.path.isdir(folder):
        raise NotADirectoryError(f"Argument '{folder}' is no known directory.")
    return os.path.abspath(folder)


# execute main if running as script
def main(sysargv = None):
    # execute main if running as script
    parser = argparse.ArgumentParser(description='Processes input to eazebot main function.')
    parser.add_argument('-i', '--init', dest='init', action='store_true', required=False,
                        help='copies the necessary user config files to the current directory')
    parser.add_argument('-c', '--config', dest='config', action='store_true', required=False,
                        help='calls a dialog to fill out the configs interactively')
    parser.add_argument('-n', '--no-warning', dest='warning', action='store_false', required=False,
                        help='does not warn for preexisting config files when running the --init flag')
    parser.add_argument('-d', '--user-dir', dest='user_dir', default=None, type=check_dir_arg, required=False,
                        help="Absolute or relative path to the user folder")

    parser.parse_args('-ic'.split())

    args = parser.parse_args(sysargv)

    # change current path to user directory if argument exists
    if args.user_dir is not None:
        os.chdir(args.user_dir)

    if args.init:
        from eazebot.auxiliary_methods import copy_init_files
        copy_init_files(warning=args.warning)
    elif args.config:
        from eazebot.auxiliary_methods import start_config_dialog
        start_config_dialog()
    else:
        from eazebot.bot import EazeBot
        EazeBot().start_bot()


if __name__ == '__main__':
    main()
