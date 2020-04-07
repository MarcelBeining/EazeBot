import os.path

try:
    # check if script is started from package folder or not
    if os.path.isfile('EazeBot.py'):
        from EazeBot import start_bot
    else:
        from eazebot.EazeBot import start_bot

    start_bot()
except Exception as e:
    print('An error occured:\n%s\n\nPress Enter to abort'%str(e))
    input()
