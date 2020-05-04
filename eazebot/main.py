import argparse
import os

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
        from eazebot.auxiliaries import copy_init_files
        copy_init_files(warning=args.warning)
    elif args.config:
        from eazebot.auxiliaries import start_config_dialog
        start_config_dialog()
    else:
        from eazebot.bot import EazeBot
        EazeBot().start_bot()


if __name__ == '__main__':
    main()
