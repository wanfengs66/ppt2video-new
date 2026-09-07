@echo off
chcp 65001 >nul
title PPT2Video Server
cd /d "%~dp0"
python start.py
pause
