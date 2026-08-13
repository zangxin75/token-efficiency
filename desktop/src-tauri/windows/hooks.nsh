; tokeneff NSIS install/uninstall hooks (B5).
; Related: docs/04-技术方案/tokeneff-B5-NSIS安装器-Windows执行指令.md
;
; After install: register autostart (write HKCU Run key).
; Before uninstall: clear autostart entry + kill leftover processes (floating ball + sidecar).
; After uninstall: ask whether to delete local data (~/.tokeneff: usage history, config, SQLite).

!macro NSIS_HOOK_PREINSTALL
  ; Before install: no special action
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; After install: register autostart (HKCU current user, no admin required)
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "tokeneff" "$INSTDIR\tokeneff.exe"
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ; Before uninstall: clear autostart
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "tokeneff"
  ; Kill leftover processes (floating ball + sidecar) to avoid locked files blocking the uninstall
  nsExec::ExecToLog 'taskkill /IM "tokeneff.exe" /F'
  nsExec::ExecToLog 'taskkill /IM "tokeneff-sidecar.exe" /F'
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  ; After uninstall: ask whether to delete local data
  MessageBox MB_YESNO|MB_ICONQUESTION "是否同时删除 tokeneff 本地数据（用量历史、配置）？" IDNO skip_data
    RMDir /r "$PROFILE\.tokeneff"
  skip_data:
!macroend
