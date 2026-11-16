@echo off
rem Construit dist\ParamDigitizer.exe (un seul fichier). A lancer dans l'environnement Python
rem du projet, depuis ce dossier.
python -m qtsocle.build main.py --name ParamDigitizer --icon ressources\icons\icon.ico --data ressources
