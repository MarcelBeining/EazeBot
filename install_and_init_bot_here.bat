cd %~dp0
if not exist "eazebot/EazeBot.py" python -m pip install eazebot
python -c "from eazebot.auxiliaries import copy_user_files; copy_user_files()"
pause