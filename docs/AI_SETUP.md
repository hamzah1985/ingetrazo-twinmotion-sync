# Setup and troubleshooting for Codex or OpenCode

Run locally on the user's Windows x64 computer with access to their installed
apps and normal development tools. The connector is experimental; report what
you actually verified and preserve the user's current model.

## Prepare and install

1. Read AGENTS.md and README.md. Find IngeTrazo's user-plugin folder and inspect
   `%LOCALAPPDATA%/IngeTrazo/twinmotion_sync/runtime.json` if present. Do not
   expose credentials, unrelated files or private model data in public reports.
2. Confirm Twinmotion is installed. DCC Camera Sync needs Twinmotion 2025.2+.
   Check for Python 3.10+ and the x64 .NET Framework compiler at
   `%WINDIR%/Microsoft.NET/Framework64/v4.0.30319/csc.exe`.
3. Obtain the exact external runtime using docs/RUNTIME.md. Rhino does not need
   to be installed. The three files must be in one directory and match the
   checked hashes. Ask the user to handle vendor terms or security prompts
   when your tool rules require it; do not bypass those prompts.
4. From this extracted repository run:

   ```powershell
   python setup_local.py --vendor-dir 'C:\DatasmithRuntime' --check-only
   python setup_local.py --vendor-dir 'C:\DatasmithRuntime'
   ```

   This verifies the runtime before building and installing our source. A C++
   compiler, standalone Unreal SDK, Blender and D5 are unnecessary. The Python
   path avoids a permanent PowerShell execution-policy change.
5. After preserving unsaved work, restart IngeTrazo. Use the extension's Show
   Toolbar command if necessary. The toolbar has four small, icon-only buttons.

## Establish the receiver connection

Save a separate test `.igz`, click TM, then select that model's Direct Link
source in Twinmotion's Import panel. Enable viewport DCC Camera Sync and choose
IngeTrazo Active View. The button should be enabled in both the source and
receiver. If an update leaves the import disconnected, use the existing import's
Direct Link settings to select the current worker source again.

Create a small box, paint one face a color and another with an image, and orbit
the perspective camera. Compare both apps visually. Keep a white face to check
the default color. Source diagnostics alone cannot prove these rendered results.

## Diagnose an error

Read `<model-name>_twinmotion_sync/ingetrazo-twinmotion-diagnostics.json` next to
the saved model. Check source status, capture warnings, worker stderr and the
last worker response. Runtime configuration stores absolute paths local to
that computer; a copied configuration from someone else's PC will not work.

- **Runtime missing/hash mismatch:** use the exact documented official runtime;
  do not bypass hash verification or copy another user's runtime pointer.
- **Worker fails to load:** verify x64, .NET Framework, the three runtime files
  and the Microsoft VC++ runtime required by Epic's native facade. Use official
  installers for any missing prerequisites.
- **Toolbar absent:** check installation path, restart after preserving work,
  then use Extensions → Ingetrazo twinmotion sync → Show Toolbar.
- **Geometry updates but camera stays still:** enable Camera on the source and
  DCC Camera Sync in Twinmotion; select IngeTrazo Active View and perspective.
- **Camera is choppy:** source sampling defaults to 30 Hz, but the measured
  Twinmotion receiver applied changes at about 10 Hz.60Hz sampling did not fix
  that test. Record receiver behavior; do not claim that a faster source fixes it.
- **Textures missing:** check warnings and the companion material manifest.
  Missing originals can be recovered from the content-hashed companion images.
  Keep that folder with the model. Do not delete cached files while troubleshooting.
- **Save As/New/Open:** reconnect to the correct saved model's new source.

If reporting an issue, include app/plugin/runtime versions, minimal steps,
the exact relevant error and a sanitized diagnostic excerpt. Keep personal
paths, usernames and models private unless the user chooses to share them.

## Uninstall

Close IngeTrazo after preserving unsaved work. Remove only this extension folder
from the user's IngeTrazo plugins directory. Keep companion folders with models;
they can contain the surviving texture copies. Installation backups remain under
the local runtime-state folder. Never purge unrelated plugins or user data.
