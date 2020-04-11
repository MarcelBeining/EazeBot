cd %~dp0
if not exist "eazebot/bot.py" python -m pip install -U eazebot
python -m eazebot --init
pause