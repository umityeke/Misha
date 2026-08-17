# Misha desktop behavior

Misha stays available from the macOS menu bar while its main window is hidden.
Closing the window hides it; only **Quit Misha** stops the application and its
background services.

The menu-bar menu provides:

- show/hide;
- microphone mute and hands-free wake controls;
- always-on-top preference;
- start-at-login preference;
- explicit quit.

Start at login uses the user-scoped
`~/Library/LaunchAgents/com.umityeke.misha.plist`. It stores an absolute
argument list and never invokes a shell. Disabling it removes only Misha's own
LaunchAgent file. Window position is stored locally and restored only when it
intersects an available display; disconnected-display coordinates fall back to
the primary screen.

`MISHA_DATA_DIR` may point to an absolute isolated data directory for packaged
smoke tests or portable development runs. Relative overrides are ignored. The
normal application default remains `~/.misha`.
