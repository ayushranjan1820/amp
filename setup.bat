@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

:: ============================================================================
::  AI Agents Platform - one-shot setup for Windows
::
::  Installs everything needed to run the app locally:
::    - Python virtual environment at .venv  + all backend dependencies
::    - Playwright Chromium  (Browser agent)
::    - server\.env bootstrapped from server\.env.example
::    - Frontend npm packages  (frontend\node_modules)
::    - Root npm packages
::
::  Usage:
::    setup.bat                    default install
::    setup.bat --full             also install heavy optional extras
::                                 (sentence-transformers / torch, ~2 GB)
::    setup.bat --skip-browsers    skip the Playwright Chromium download
::    setup.bat --skip-node        skip all npm installs
::    setup.bat --help             show this help
:: ============================================================================

set "FULL=0"
set "SKIP_BROWSERS=0"
set "SKIP_NODE=0"

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--full"          set "FULL=1"           & shift & goto parse_args
if /I "%~1"=="--skip-browsers" set "SKIP_BROWSERS=1"  & shift & goto parse_args
if /I "%~1"=="--skip-node"     set "SKIP_NODE=1"      & shift & goto parse_args
if /I "%~1"=="--help"          goto usage
if /I "%~1"=="-h"              goto usage
echo [WARN] Unknown option: %~1
shift
goto parse_args

:usage
echo.
echo   setup.bat [--full] [--skip-browsers] [--skip-node]
echo.
echo     --full            also install heavy optional extras from
echo                       server\requirements.txt ^(sentence-transformers/torch^)
echo     --skip-browsers   do not download Playwright Chromium
echo     --skip-node       do not run any npm install
echo.
exit /b 0

:args_done

echo ============================================================
echo   AI Agents Platform - Setup
echo   %CD%
echo ============================================================
echo.

:: ---------------------------------------------------------------------------
:: [1/8] Check prerequisites
:: ---------------------------------------------------------------------------
echo [1/8] Checking prerequisites...

where python >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] Python was not found on PATH.
    echo           Install Python 3.11, 3.12 or 3.13 from https://www.python.org/downloads/
    echo           and tick "Add python.exe to PATH" during installation.
    goto fail
)

for /f "delims=" %%V in ('python -c "import sys;print('%%d.%%d.%%d'%%sys.version_info[:3])" 2^>nul') do set "PYVER=%%V"
python -c "import sys;sys.exit(0 if (3,11)<=sys.version_info[:2]<(3,14) else 1)" >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] Python !PYVER! is not supported. This project requires ^>=3.11 and ^<3.14.
    goto fail
)
echo   OK  Python !PYVER!

if "%SKIP_NODE%"=="0" (
    where npm >nul 2>&1
    if errorlevel 1 (
        echo   [ERROR] npm/Node.js was not found on PATH.
        echo           Install Node.js 20 or newer from https://nodejs.org/
        goto fail
    )
    for /f "delims=" %%V in ('node -v 2^>nul') do set "NODEVER=%%V"
    echo   OK  Node !NODEVER!
) else (
    echo   --  Node checks skipped
)
echo.

:: ---------------------------------------------------------------------------
:: [2/8] Python virtual environment
:: ---------------------------------------------------------------------------
echo [2/8] Preparing Python virtual environment ^(.venv^)...
set "VPY=%CD%\.venv\Scripts\python.exe"

if exist "%VPY%" (
    echo   Reusing existing .venv
) else (
    python -m venv .venv
    if errorlevel 1 (
        echo   [ERROR] Failed to create the virtual environment.
        goto fail
    )
    echo   Created .venv
)

if not exist "%VPY%" (
    echo   [ERROR] .venv\Scripts\python.exe is missing - the venv looks broken.
    echo           Delete the .venv folder and run setup.bat again.
    goto fail
)
echo.

:: ---------------------------------------------------------------------------
:: [3/8] Base packaging tools
:: ---------------------------------------------------------------------------
echo [3/8] Upgrading pip / setuptools / wheel...
"%VPY%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo   [ERROR] Could not upgrade the base packaging tools.
    goto fail
)
echo.

:: ---------------------------------------------------------------------------
:: [4/8] Backend dependencies (pyproject.toml - same set the Dockerfile uses)
:: ---------------------------------------------------------------------------
echo [4/8] Installing backend dependencies from pyproject.toml...
echo       ^(this is the long one - several minutes on a cold cache^)

:: The dependency list is read out of pyproject.toml into a temp requirements
:: file. "pip install -e ." is deliberately NOT used here: in a working copy the
:: repo root also contains server\, frontend\, node_modules\ ... and setuptools
:: flat-layout auto-discovery refuses to build with multiple top-level packages.
:: The Dockerfile gets away with it because only pyproject.toml is present there.
set "DEPFILE=%TEMP%\agents_deps_%RANDOM%.txt"
"%VPY%" -c "import tomllib,pathlib,sys;d=tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8'));pathlib.Path(sys.argv[1]).write_text('\n'.join(d['project']['dependencies']),encoding='utf-8')" "%DEPFILE%"
if errorlevel 1 (
    echo   [ERROR] Could not read the dependency list from pyproject.toml.
    goto fail
)

"%VPY%" -m pip install -r "%DEPFILE%"
if errorlevel 1 (
    del /q "%DEPFILE%" >nul 2>&1
    echo   [ERROR] Backend dependency installation failed. See the pip output above.
    goto fail
)
del /q "%DEPFILE%" >nul 2>&1

:: pymysql is listed in server\requirements.txt but not in pyproject.toml;
:: the SQL DB agent needs it to reach MySQL databases.
"%VPY%" -m pip install "pymysql>=1.1.0"
if errorlevel 1 (
    echo   [ERROR] Failed to install pymysql.
    goto fail
)

if "%FULL%"=="1" (
    echo.
    echo   --full requested: installing optional extras from server\requirements.txt
    echo   ^(includes sentence-transformers + torch, this downloads ~2 GB^)
    "%VPY%" -m pip install -r server\requirements.txt
    if errorlevel 1 (
        echo   [ERROR] Optional extras installation failed.
        goto fail
    )
)
echo   OK  Backend dependencies installed
echo.

:: ---------------------------------------------------------------------------
:: [5/8] Playwright browser
:: ---------------------------------------------------------------------------
echo [5/8] Playwright Chromium ^(Browser agent^)...
if "%SKIP_BROWSERS%"=="1" (
    echo   --  Skipped ^(--skip-browsers^). Run this later from the project root:
    echo       .venv\Scripts\python.exe -m playwright install chromium
) else (
    "%VPY%" -m playwright install chromium
    if errorlevel 1 (
        echo   [WARN] Chromium download failed. The app still runs; only the Browser agent is affected.
        echo          Retry later with: .venv\Scripts\python.exe -m playwright install chromium
    ) else (
        echo   OK  Chromium installed
    )
)
echo.

:: ---------------------------------------------------------------------------
:: [6/8] Environment files
:: ---------------------------------------------------------------------------
echo [6/8] Environment files...
set "ENV_CREATED=0"
if exist "server\.env" (
    echo   OK  server\.env already exists - left untouched
) else (
    if exist "server\.env.example" (
        copy /y "server\.env.example" "server\.env" >nul
        set "ENV_CREATED=1"
        echo   Created server\.env from server\.env.example
    ) else (
        echo   [WARN] server\.env.example not found - create server\.env manually.
    )
)
:: frontend\.env is intentionally NOT created: with VITE_API_URL unset, the Vite
:: dev server proxies /api to the backend on localhost:8000 (see frontend\vite.config.ts).
echo.

:: ---------------------------------------------------------------------------
:: [7/8] Frontend packages
:: ---------------------------------------------------------------------------
echo [7/8] Frontend npm packages...
if "%SKIP_NODE%"=="1" (
    echo   --  Skipped ^(--skip-node^)
) else (
    pushd frontend
    if exist "package-lock.json" (
        call npm ci
        if errorlevel 1 (
            echo   [WARN] "npm ci" failed - falling back to "npm install"
            call npm install
        )
    ) else (
        call npm install
    )
    if errorlevel 1 (
        popd
        echo   [ERROR] Frontend package installation failed.
        goto fail
    )
    popd
    echo   OK  frontend\node_modules ready
)
echo.

:: ---------------------------------------------------------------------------
:: [8/8] Root packages + verification
:: ---------------------------------------------------------------------------
echo [8/8] Root npm packages and verification...
if "%SKIP_NODE%"=="1" (
    echo   --  Root npm install skipped ^(--skip-node^)
) else (
    call npm install
    if errorlevel 1 (
        echo   [WARN] Root "npm install" failed. The frontend and backend still work;
        echo          only root-level tooling is affected.
    ) else (
        echo   OK  Root node_modules ready
    )
)

"%VPY%" -c "import fastapi, uvicorn, pydantic, langchain_core, pymongo, sqlalchemy" >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] Import check failed - core backend packages are not importable.
    goto fail
)
echo   OK  Core backend imports verified
echo.

:: ---------------------------------------------------------------------------
:: Done
:: ---------------------------------------------------------------------------
echo ============================================================
echo   Setup complete
echo ============================================================
echo.
if "%ENV_CREATED%"=="1" (
    echo   NEXT STEP - server\.env was created from the template and still
    echo   holds placeholder values. Fill in at least:
    echo.
    echo     MONGODB_URI            MongoDB connection string
    echo     EXTERNAL_DATABASE_URL  PostgreSQL connection string
    echo     SESSION_SECRET         run: .venv\Scripts\python.exe -c "import secrets;print(secrets.token_hex(32))"
    echo     ANTHROPIC_API_KEY      and/or OPENAI_API_KEY
    echo.
)
echo   Start the app with:   start.bat
echo.
echo     Backend   http://localhost:8000
echo     Frontend  http://localhost:5000
echo.
pause
exit /b 0

:fail
echo.
echo ============================================================
echo   Setup FAILED - see the error above.
echo ============================================================
echo.
pause
exit /b 1