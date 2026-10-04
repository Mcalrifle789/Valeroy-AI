@echo off
setlocal enabledelayedexpansion
rem Build the Valeroy C and C++ native layers with MSVC.
set "ROOT=%~dp0.."
set "OUT=%ROOT%\build\native"
if not exist "%OUT%" mkdir "%OUT%"

call "%~dp0_vcvars.bat"
if errorlevel 1 (
  echo [valeroy] MSVC not found - skipping native build. Python fallbacks will be used.
  exit /b 0
)

echo [valeroy] building C hashing layer
cl /nologo /O2 /W4 /LD /DVALEROY_HASH_SHARED /DVALEROY_HASH_BUILD ^
   "%ROOT%\backend\chash\valeroy_hash.c" ^
   /Fo:"%OUT%\\" /Fe:"%OUT%\valeroy_hash.dll" /link /IMPLIB:"%OUT%\valeroy_hash.lib"
if errorlevel 1 exit /b 1

echo [valeroy] building C hashing selftest
cl /nologo /O2 /W4 "%ROOT%\backend\chash\hash_selftest.c" "%ROOT%\backend\chash\valeroy_hash.c" ^
   /Fo:"%OUT%\\" /Fe:"%OUT%\hash_selftest.exe"
if errorlevel 1 exit /b 1

echo [valeroy] building C++ provider catalog
cl /nologo /O2 /W4 /EHsc /std:c++17 /LD /DVALEROY_CATALOG_SHARED /DVALEROY_CATALOG_BUILD ^
   "%ROOT%\backend\catalog\provider_catalog.cpp" ^
   /Fo:"%OUT%\\" /Fe:"%OUT%\valeroy_catalog.dll" /link /IMPLIB:"%OUT%\valeroy_catalog.lib"
if errorlevel 1 exit /b 1

echo [valeroy] building C++ catalog selftest
cl /nologo /O2 /W4 /EHsc /std:c++17 "%ROOT%\backend\catalog\catalog_selftest.cpp" ^
   "%ROOT%\backend\catalog\provider_catalog.cpp" ^
   /Fo:"%OUT%\\" /Fe:"%OUT%\catalog_selftest.exe"
if errorlevel 1 exit /b 1

echo [valeroy] building C++ TUI render accelerator
cl /nologo /O2 /W4 /EHsc /std:c++17 /LD /DVALEROY_RENDER_SHARED /DVALEROY_RENDER_BUILD ^
   "%ROOT%\frontend\cpp\vtui_render.cpp" ^
   /Fo:"%OUT%\\" /Fe:"%OUT%\vtui_render.dll" /link /IMPLIB:"%OUT%\vtui_render.lib"
if errorlevel 1 exit /b 1

echo [valeroy] native build complete -^> %OUT%
endlocal
exit /b 0
