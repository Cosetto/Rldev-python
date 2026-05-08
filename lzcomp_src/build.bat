@echo off
setlocal
cd /d "%~dp0"

where g++ >nul 2>nul
if errorlevel 1 (
    echo g++ was not found on PATH. Run this from a TDM-GCC command prompt or add TDM-GCC-64\bin to PATH.
    exit /b 1
)

g++ -O3 -std=c++11 -shared -static-libgcc -static-libstdc++ -o lzcomp.dll lzcomp.cpp
if errorlevel 1 exit /b 1

echo Built %CD%\lzcomp.dll
