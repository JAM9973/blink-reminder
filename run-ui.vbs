Option Explicit
Dim shell, files, folder, python, launcher
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
python = files.BuildPath(folder, ".venv\Scripts\pythonw.exe")
launcher = files.BuildPath(folder, "desktop_launcher.pyw")
If Not files.FileExists(python) Or Not files.FileExists(launcher) Then
    MsgBox "Python environment missing. Run setup from README.md first.", 16, "Blink reminder"
    WScript.Quit 1
End If
If WScript.Arguments.Named.Exists("check") Then WScript.Quit 0
shell.CurrentDirectory = folder
shell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & launcher & Chr(34) & " --mode rebound-conservative", 0, False
