; NSIS hooks for Appian Sentinel.
; The desktop supervisor owns child lifetime. The installer only copies files.

!macro _sentinelForceCloseApp
  InitPluginsDir
  FileOpen $9 "$PLUGINSDIR\sentinel-force-close.ps1" w
  FileWrite $9 `param([string]$$Root='',[string]$$App='')$\r$\n`
  FileWrite $9 `$$ErrorActionPreference='SilentlyContinue'$\r$\n`
  FileWrite $9 `$$sys="$$env:SystemRoot\System32"$\r$\n`
  FileWrite $9 `$$app=$$App.ToLower()$\r$\n`
  FileWrite $9 `$$marks=@('documents\appiansentinel','\programs\appiansentinel')$\r$\n`
  FileWrite $9 `if($$Root){$$marks+=$$Root.ToLower().TrimEnd('\')}$\r$\n`
  FileWrite $9 `$$all=@{}$\r$\n`
  FileWrite $9 `foreach($$p in @(Get-CimInstance Win32_Process)){$$all[[int]$$p.ProcessId]=$$p}$\r$\n`
  FileWrite $9 `$$keep=@();$$cur=[int]$$PID$\r$\n`
  FileWrite $9 `for($$i=0;$$i -lt 8 -and $$cur -gt 4;$$i++){$$keep+=$$cur;$$q=$$all[$$cur];if(-not $$q){break};$$cur=[int]$$q.ParentProcessId}$\r$\n`
  FileWrite $9 `function Mine([string]$$text){if(-not $$text){return $$false};$$lower=$$text.ToLower();foreach($$mark in $$marks){if($$lower.Contains($$mark)){return $$true}};return $$false}$\r$\n`
  FileWrite $9 `function Nuke([int]$$id,[string]$$why){if($$id -le 4 -or $$keep -contains $$id){return};$$old=$$all[$$id];$$now=Get-CimInstance Win32_Process -Filter "ProcessId=$$id";if(-not $$old -or -not $$now -or [string]$$old.CreationDate -ne [string]$$now.CreationDate){return};& "$$sys\taskkill.exe" /F /T /PID $$id 2>$$null|Out-Null}$\r$\n`
  FileWrite $9 `foreach($$p in @($$all.Values)){$\r$\n`
  FileWrite $9 ` $$name=([string]$$p.Name).ToLower();$$identity=[string]$$p.ExecutablePath+' '+[string]$$p.CommandLine$\r$\n`
  FileWrite $9 ` if($$app -and $$name -eq $$app -and (Mine $$identity)){Nuke ([int]$$p.ProcessId) 'app';continue}$\r$\n`
  FileWrite $9 ` if($$name -eq 'appian-sentinel-sidecar.exe' -and (Mine $$identity)){Nuke ([int]$$p.ProcessId) 'sidecar'}$\r$\n`
  FileWrite $9 `}$\r$\n`
  FileWrite $9 `# Ports are shared. Kill only listeners whose install path proves ownership.$\r$\n`
  FileWrite $9 `$$listen=@(& "$$sys\netstat.exe" -ano -p TCP|Where-Object{$$_ -match 'LISTENING'})$\r$\n`
  FileWrite $9 `foreach($$port in 7851,8871){foreach($$line in @($$listen|Where-Object{$$_ -match ":$$port\s"})){$\r$\n`
  FileWrite $9 ` $$id=0;[void][int]::TryParse((($$line.Trim() -split '\s+')[-1]),[ref]$$id);$$q=$$all[$$id]$\r$\n`
  FileWrite $9 ` if($$q -and (Mine ([string]$$q.ExecutablePath+' '+[string]$$q.CommandLine)){Nuke $$id "port $$port"}$\r$\n`
  FileWrite $9 `}}$\r$\n`
  FileClose $9
  nsExec::Exec '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\sentinel-force-close.ps1" "$INSTDIR" "${APP_EXECUTABLE_FILENAME}"'
  Pop $0
!macroend

; electron-builder uses this in installer and uninstaller flows.
!macro customCheckAppRunning
  !insertmacro _sentinelForceCloseApp
!macroend

!macro customInit
  ReadEnvStr $R9 "SENTINEL_NSIS_INSTDIR"
  ${If} $R9 != ""
    StrCpy $INSTDIR $R9
  ${Else}
    StrCpy $INSTDIR "$PROFILE\Documents\AppianSentinel\install\desktop-app"
  ${EndIf}
  CreateDirectory "$PROFILE\Documents\AppianSentinel\logs"
  DetailPrint "Appian Sentinel: extracting desktop application."
!macroend

!macro customUnInit
  !insertmacro _sentinelForceCloseApp
!macroend
