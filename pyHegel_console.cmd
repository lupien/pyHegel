@echo off
REM Script to start Console with pyHegel
REM To reset to default behavior, erase the console_c.xml file

set pyHegelpath=C:\Codes\pyHegel
set conf_file=%pyHegelpath%\console_c.xml

if not exist %conf_file% (
 REM copy the template version
 echo Installing the configuration file: %conf_file%
 copy %conf_file%.tmpl %conf_file%
)

start C:"\Program Files (x86)\pythonxy\console\Console.exe" -c %conf_file% -t "pyHegel"
rem start /wait C:"\Program Files (x86)\pythonxy\console\Console.exe" -c %conf_file% -t "pyHegel"
