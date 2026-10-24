param([Parameter(Mandatory=$true)][string]$Payload, [switch]$ValidateOnly)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
try {
$notificationData = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Payload)) | ConvertFrom-Json
if ($notificationData.url -notmatch '^http://127\.0\.0\.1:\d+/(?:[^\s]*)$') { throw 'Invalid local task URL' }
$projectDirectory = Split-Path $PSScriptRoot -Parent
$shortcutDirectory = [Environment]::GetFolderPath('Programs')
$shortcutFile = Join-Path $shortcutDirectory 'SubjectsLearning.lnk'
# Desktop toasts require an installed shortcut with an AppUserModelID.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;
public static class LearningShortcut {
  [DllImport("shell32.dll", CharSet=CharSet.Unicode)]
  public static extern int SetCurrentProcessExplicitAppUserModelID(string appId);
  [ComImport, Guid("00021401-0000-0000-C000-000000000046")] class ShellLink {}
  [ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IShellLinkW {
    void GetPath(StringBuilder a,int b,IntPtr c,int d); void GetIDList(out IntPtr p); void SetIDList(IntPtr p);
    void GetDescription(StringBuilder a,int b); void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string s);
    void GetWorkingDirectory(StringBuilder a,int b); void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string s);
    void GetArguments(StringBuilder a,int b); void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string s);
    void GetHotkey(out short s); void SetHotkey(short s); void GetShowCmd(out int s); void SetShowCmd(int s);
    void GetIconLocation(StringBuilder a,int b,out int s); void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string s,int i);
    void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string s,int i); void Resolve(IntPtr p,int i);
    void SetPath([MarshalAs(UnmanagedType.LPWStr)] string s);
  }
  [StructLayout(LayoutKind.Sequential)] struct PropertyKey { public Guid fmtid; public uint pid; }
  [StructLayout(LayoutKind.Explicit, Size=16)] struct PropVariant {
    [FieldOffset(0)] public ushort vt;
    [FieldOffset(8)] public IntPtr value;
  }
  [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IPropertyStore {
    void GetCount(out uint n); void GetAt(uint n,out PropertyKey k); void GetValue(ref PropertyKey k,out PropVariant v);
    void SetValue(ref PropertyKey k,ref PropVariant v); void Commit();
  }
  public static void Create(string file,string target,string arguments,string workingDirectory) {
    object link=new ShellLink();
    try {
      IShellLinkW shell=(IShellLinkW)link;
      shell.SetPath(target); shell.SetArguments(arguments); shell.SetWorkingDirectory(workingDirectory);
      shell.SetDescription("Subjects Learning"); shell.SetShowCmd(7);
      PropertyKey key=new PropertyKey { fmtid=new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"),pid=5 };
      PropVariant value=new PropVariant { vt=31, value=Marshal.StringToCoTaskMemUni("SubjectsLearning.Local") };
      try {
        IPropertyStore store=(IPropertyStore)link; store.SetValue(ref key,ref value);
        // Protocol activation needs a stub CLSID so Action Center retains the toast.
        key.pid=26;
        IntPtr clsid=Marshal.AllocCoTaskMem(16);
        try {
          Marshal.StructureToPtr(new Guid("7F6C9B7E-63BA-4FC8-A6D8-0555580FD9AA"),clsid,false);
          PropVariant activator=new PropVariant { vt=72,value=clsid };
          store.SetValue(ref key,ref activator); store.Commit();
        } finally { Marshal.FreeCoTaskMem(clsid); }
      }
      finally { Marshal.FreeCoTaskMem(value.value); }
      ((IPersistFile)link).Save(file,true);
    } finally { Marshal.FinalReleaseComObject(link); }
  }
}
'@
if (-not $ValidateOnly) {
    # Register only our own identity. Do not alter the user's notification settings.
    $appKey = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Software\Classes\AppUserModelId\SubjectsLearning.Local')
    try {
        $appKey.SetValue('DisplayName', ([string][char]0x9898 + [char]0x7814))
        $appKey.SetValue('CustomActivator', '{7F6C9B7E-63BA-4FC8-A6D8-0555580FD9AA}')
    } finally { $appKey.Dispose() }
    # Repair existing shortcuts too; early versions omitted the activation property.
    [LearningShortcut]::Create($shortcutFile, $env:ComSpec, ('/c ""' + (Join-Path $projectDirectory 'start-local.cmd') + '""'), $projectDirectory)
    [Runtime.InteropServices.Marshal]::ThrowExceptionForHR([LearningShortcut]::SetCurrentProcessExplicitAppUserModelID('SubjectsLearning.Local'))
}
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
[Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$escapeXml = { param($value) [Security.SecurityElement]::Escape([string]$value) }
$toastXml = '<toast activationType="protocol" launch="' + (& $escapeXml $notificationData.url) + '"><visual><binding template="ToastGeneric"><text>' + (& $escapeXml $notificationData.title) + '</text><text>' + (& $escapeXml $notificationData.message) + '</text></binding></visual></toast>'
$document = New-Object Windows.Data.Xml.Dom.XmlDocument
$document.LoadXml($toastXml)
if ($ValidateOnly) { Write-Output 'Notification payload, XML, Windows Runtime types and shortcut helper validated.'; return }
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('SubjectsLearning.Local')
$toast = [Windows.UI.Notifications.ToastNotification]::new($document)
$toast.Tag = [Guid]::NewGuid().ToString('N').Substring(0,16)
$toast.Group = 'subjects-learning'
$toast.SuppressPopup = $false
$notifier.Show($toast)
# Show() alone is not a delivery receipt. Check our unique toast in Windows history.
$accepted = $false
for ($attempt=0; $attempt -lt 40; $attempt++) {
    Start-Sleep -Milliseconds 100
    foreach ($item in [Windows.UI.Notifications.ToastNotificationManager]::History.GetHistory('SubjectsLearning.Local')) {
        if ($item.Tag -eq $toast.Tag -and $item.Group -eq $toast.Group) { $accepted = $true; break }
    }
    if ($accepted) { break }
}
# Windows creates a first-time sender's settings only after Show(). Use the explicit
# getter: PowerShell's property adapter swallows WinRT getter exceptions as null.
$notificationSetting = [string]$notifier.get_Setting()
if ($notificationSetting -ne 'Enabled') { throw ('Windows notification setting: ' + $notificationSetting) }
if (-not $accepted) { throw 'Windows did not return a notification-center delivery receipt.' }
@{ accepted=$true; app_id='SubjectsLearning.Local'; tag=$toast.Tag; setting=$notificationSetting; receipt='notification_center' } | ConvertTo-Json -Compress
} catch {
    @{ accepted=$false; error=$_.Exception.Message } | ConvertTo-Json -Compress
    exit 1
}
