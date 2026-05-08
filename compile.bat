@echo off
echo Compile SEEN.txt...
cd Seen
del *.TXT

python ../rlc.py -e utf8 -G KOYO -i ../GAMEEXE.INI *.org

echo.

python ../kprl.py -a -G KOYO ../SEEN.TXT Seen*.TXT
pause