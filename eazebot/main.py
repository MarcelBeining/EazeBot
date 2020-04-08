import argparse

# execute main if running as script
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Processes input to eazebot main function.')
    parser.add_argument('--init', dest='init', action='store_true', required=False,
                        help='copies the necessary user config files to the current directory')
    parser.add_argument('--config', dest='config', action='store_true', required=False,
                        help='calls a dialog to fill out the configs interactively')

    args = parser.parse_args()

    if args.init:
        from eazebot.auxiliaries import copy_user_files
        copy_user_files()
    elif args.config:
        from eazebot.auxiliaries import start_config_dialog
        start_config_dialog()
    else:
        from eazebot.EazeBot import start_bot
        start_bot()
