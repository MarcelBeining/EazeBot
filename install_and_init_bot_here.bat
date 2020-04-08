cd %~dp0
if not exist "eazebot/EazeBot.py" python -m pip install -U eazebot
python -m eazebot --init
python -m eazebot --config
pause