@ECHO OFF
setlocal enabledelayedexpansion
cd %~dp0
python -c "import virtualenv"
IF errorlevel 1 (
echo Installing virtualenv
call python -m pip install virtualenv -U --no-cache --ignore-installed
)
IF EXIST %~dp0venv (
echo venv already exists
) ELSE (
echo Creating venv
call python -m virtualenv %~dp0venv
)

call venv\Scripts\activate.bat && python -m pip install -r requirements.txt 

set /P question=Do you want to install the dev libraries, too?
if /I "%question%" EQU "Y" (
call venv\Scripts\activate.bat && python -m pip install -r dev_requirements.txt
)

pause