# System tools security contract

System actions use a platform capability matrix before Misha claims support for app
launching, window control, volume, brightness, media, screenshots, or power. Missing
backends are reported as unavailable; shell-based compatibility fallbacks are not
used.

PyAutoGUI's top-left emergency failsafe is reapplied immediately before every UI
automation action, with a minimum pause. Screenshot output is limited to Desktop or
Pictures and symlink targets are rejected. Window titles accept only a bounded safe
character set before being passed as an AppleScript, PowerShell, or wmctrl argument.

Application launchers use argv arrays. Windows URI launch is limited to
`ms-settings:` and no action module uses `shell=True`. macOS wallpaper paths are
passed as AppleScript argv rather than interpolated into code. Remote wallpaper
download is disabled; the guarded browser download plus local wallpaper action is
the supported flow.

Shutdown and restart require both the runtime's user approval and an exact second
confirmation (`CONFIRM SHUTDOWN` or `CONFIRM RESTART`). Legacy arbitrary terminal
execution and generated desktop Python execution are fail-closed stubs.
