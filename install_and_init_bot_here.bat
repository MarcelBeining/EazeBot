cd %~dp0
if not exist "eazebot/EazeBot.py" python -m pip install -U eazebot
python -m eazebot --init
pause