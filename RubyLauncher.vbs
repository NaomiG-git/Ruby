Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strPath = fso.GetParentFolderName(WScript.ScriptFullName)
' Run launch_ruby.bat hidden (0 = hidden, False = don't wait for completion)
WshShell.Run "cmd /c """ & strPath & "\launch_ruby.bat""", 0, False
