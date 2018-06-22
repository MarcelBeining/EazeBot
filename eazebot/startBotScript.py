import os.path
# check if script is started from packacge folder or not
if os.path.isfile('EazeBot.py') :
	from EazeBot import startBot
else:
	from eazebot.EazeBot import startBot
startBot()