@echo off
:: Project Hail Mary — texconv conversion script
:: Run from repo root after generate_terrain_textures.py

texconv -f DXT1 -o "GameData\ProjectHailMary\Textures\Parallax" Tools\terrain_src\parallax\*[!m].png
texconv -f DXT5 -ddn -o "GameData\ProjectHailMary\Textures\Parallax" Tools\terrain_src\parallax\*_nrm.png
texconv -f DXT1 -o "GameData\ProjectHailMary\Textures\EVE" Tools\terrain_src\eve\*.png
echo Done.
