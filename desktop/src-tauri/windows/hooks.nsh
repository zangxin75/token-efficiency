; tokeneff NSIS 安装/卸载钩子（B5）。
; 关联 docs/04-技术方案/tokeneff-B5-NSIS安装器-Windows执行指令.md
;
; 安装后：注册开机自启（写 HKCU Run 键）。
; 卸载前：清自启项 + kill 残留进程（悬浮球 + sidecar）。
; 卸载后：询问是否删本地数据（~/.tokeneff：用量历史、配置、SQLite）。

!macro NSIS_HOOK_PREINSTALL
  ; 安装前：无特殊操作
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; 安装后：注册开机自启（HKCU 当前用户，无需管理员）
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "tokeneff" "$INSTDIR\tokeneff.exe"
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ; 卸载前：清理开机自启
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "tokeneff"
  ; kill 残留进程（悬浮球 + sidecar），避免占用文件导致卸载不全
  nsExec::ExecToLog 'taskkill /IM "tokeneff.exe" /F'
  nsExec::ExecToLog 'taskkill /IM "tokeneff-sidecar.exe" /F'
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  ; 卸载后：询问是否删本地数据
  MessageBox MB_YESNO|MB_ICONQUESTION "是否同时删除 tokeneff 本地数据（用量历史、配置）？" IDNO skip_data
    RMDir /r "$PROFILE\.tokeneff"
  skip_data:
!macroend
