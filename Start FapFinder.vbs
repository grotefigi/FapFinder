Option Explicit
Dim fs, shell, folder, packaged, python, entry
Set fs = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
folder = fs.GetParentFolderName(WScript.ScriptFullName)
packaged = fs.BuildPath(folder, "dist\FapFinder\FapFinder.exe")
python = fs.BuildPath(folder, ".venv\Scripts\pythonw.exe")
entry = fs.BuildPath(folder, "run.py")
shell.CurrentDirectory = folder
If fs.FileExists(packaged) Then
    shell.Run Chr(34) & packaged & Chr(34), 1, False
ElseIf fs.FileExists(python) Then
    shell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & entry & Chr(34), 0, False
Else
    MsgBox "Run setup.ps1 with Python 3.12 first, then open FapFinder again.", 48, "FapFinder setup"
End If
