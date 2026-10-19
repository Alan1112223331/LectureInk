# Native tools write progress to stderr; Windows PowerShell 5.1 would treat that as an error under
# 'Stop', so failures are detected from exit codes instead.
$ErrorActionPreference = 'Continue'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw '请先创建 .venv 并安装 requirements.txt' }

& $python -m pytest -q -p no:cacheprovider (Join-Path $PSScriptRoot 'tests')
if ($LASTEXITCODE -ne 0) { throw '测试未通过' }

& $python -m PyInstaller --noconfirm --clean --log-level WARN --distpath (Join-Path $PSScriptRoot 'dist\single') --workpath (Join-Path $PSScriptRoot 'build') (Join-Path $PSScriptRoot 'LectureInk.spec')
if ($LASTEXITCODE -ne 0) { throw '打包失败' }
Write-Host '已生成 dist\single\LectureInk.exe'
