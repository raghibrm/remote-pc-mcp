' Launches start.bat with no visible window. Used by the
' "remote-pc-mcp" scheduled task to run the server hidden at logon.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = scriptDir
sh.Run """" & scriptDir & "\start.bat""", 0, False
