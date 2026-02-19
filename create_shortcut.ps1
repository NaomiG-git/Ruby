$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut("C:\Users\grind\Desktop\Ruby.lnk")
$s.TargetPath = "c:\Users\grind\Desktop\memu-agent\RubyLauncher.vbs"
$s.WorkingDirectory = "c:\Users\grind\Desktop\memu-agent"
# Point to the icon in the root folder
$s.IconLocation = "c:\Users\grind\Desktop\memu-agent\ruby_icon_pure.ico"
$s.Save()
