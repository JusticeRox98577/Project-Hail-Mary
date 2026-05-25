@echo off
setlocal

set KSP_DIR=D:\KSP\Kerbal Space Program
set SOURCE_DIR=%~dp0GameData\ProjectHailMary\Plugins\Source
set OUTPUT_DLL=%~dp0GameData\ProjectHailMary\Plugins\ProjectHailMary.dll

echo.
echo === Project Hail Mary - Plugin Builder ===
echo KSP path: %KSP_DIR%
echo.

:: Check KSP assemblies exist
if not exist "%KSP_DIR%\KSP_x64_Data\Managed\Assembly-CSharp.dll" (
    echo ERROR: Could not find Assembly-CSharp.dll at:
    echo   %KSP_DIR%\KSP_x64_Data\Managed\Assembly-CSharp.dll
    echo.
    echo Check that your KSP path is correct at the top of this script.
    pause
    exit /b 1
)

:: Check dotnet is installed
where dotnet >nul 2>&1
if errorlevel 1 (
    echo ERROR: dotnet not found. Install the .NET SDK from:
    echo   https://dotnet.microsoft.com/download
    pause
    exit /b 1
)

:: Create Plugins folder if missing
if not exist "%~dp0GameData\ProjectHailMary\Plugins" (
    mkdir "%~dp0GameData\ProjectHailMary\Plugins"
)

echo Building plugin...
dotnet build "%SOURCE_DIR%\ProjectHailMary.csproj" ^
    -c Release ^
    /p:KSP_DIR="%KSP_DIR%" ^
    /p:OutputPath="%~dp0GameData\ProjectHailMary\Plugins" ^
    /p:AppendTargetFrameworkToOutputPath=false ^
    --nologo

if errorlevel 1 (
    echo.
    echo BUILD FAILED. See errors above.
    pause
    exit /b 1
)

:: Verify DLL landed in the right place
if exist "%OUTPUT_DLL%" (
    echo.
    echo BUILD SUCCEEDED.
    echo DLL location: %OUTPUT_DLL%
    echo.
    echo Next step: copy GameData\ProjectHailMary\ into your KSP GameData\ folder.
) else (
    echo.
    echo Build reported success but DLL not found at expected location:
    echo   %OUTPUT_DLL%
    echo Check the build output above for the actual output path.
)

pause
