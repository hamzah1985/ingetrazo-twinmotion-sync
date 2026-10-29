# IngeTrazo Twinmotion Sync

Experimental, unofficial **Windows x64** connector for IngeTrazo → Twinmotion
Datasmith Direct Link. Pull requests and reproducible bug reports are welcome.

It sends visible geometry, default white/painted colors, diffuse textures,
smooth normals, nested transforms and the perspective camera. A compact SVG
toolbar provides Connect, Sync Now, Camera and Disconnect. Blender, D5, Rhino
and Unreal Editor do not run during sync.

**Current limitation:** camera following works, but our live Twinmotion 2026.1
test applied camera changes about **10 times per second** while the sender ran
at about 28 updates/s. It is not yet as smooth as our D5 connector. The optional
60 Hz source sampling mode did not improve that receiver rate. See
[validation and limitations](docs/VALIDATION.md).

## Have Codex or OpenCode install it

Give a local Codex or OpenCode session this repository link and this request:

> Install and configure https://github.com/hamzah1985/ingetrazo-twinmotion-sync
> for my existing IngeTrazo and Twinmotion installations. Read AGENTS.md and
> the setup documentation first, obtain the required runtime from Epic's
> official source, build the community worker and install the connector.
> Preserve my models and existing plugins. Test with a separate saved test
> model, enable Twinmotion DCC Camera Sync, and investigate any installation,
> connection, material or camera errors. Explain anything that needs my action
> and the remaining limitations; do not claim success from a sender response alone.

This is a source package with a build/install helper. It does not contain every
dependency, and an AI assistant may need your help with vendor terms, permission
prompts or software installation. [AI setup guide](docs/AI_SETUP.md).

## Setup

1. Have **IngeTrazo and Twinmotion installed**. Twinmotion 2025.2 or newer is
   needed for its DCC Camera Sync feature. The live receiver tested here is
   Twinmotion 2026.1 on Windows x64.
2. Obtain the separately licensed **Epic Datasmith 5.8.4 runtime** described in
   [runtime setup](docs/RUNTIME.md). The installer checks the exact hashes of
   `DatasmithFacadeCSharp.dll`, `DatasmithRhino6.rhp` and `tbbmalloc.dll`.
   They remain outside this repository and outside our installed plugin.
3. [Download the source ZIP](https://github.com/hamzah1985/ingetrazo-twinmotion-sync/archive/refs/heads/main.zip)
   and extract it. Close IngeTrazo before a normal installation. Use Python
   3.10+ and Windows' .NET Framework x64 C# compiler:

   ```powershell
   python setup_local.py --vendor-dir 'C:\DatasmithRuntime'
   ```

   Replace that directory with your runtime location. The helper verifies the
   runtime, compiles our C# worker and installs our extension. It needs no C++
   SDK or Unreal Editor. If `python` is unavailable, a configured `py -3`
   launcher can run the same script. No permanent execution-policy change is needed.
4. Start IngeTrazo. Open **Extensions → Ingetrazo twinmotion sync → Show Toolbar**
   if the toolbar is hidden. Save a test `.igz` model and click **TM**.
5. In Twinmotion, choose **Import → Direct Link**, select the IngeTrazo source
   for the saved model and import it. Enable **DCC Camera Sync** in the viewport
   and select **IngeTrazo Active View**. Model import alone does not enable
   camera following.

If a worker update breaks an existing connection, open that imported item's
**Direct Link settings** and select the running IngeTrazo source again. Worker
filenames currently include a content hash; the receiver may show that name.

Installation backs up the previous extension/configuration and writes only to
`%APPDATA%/ingetrazo/plugins/ingetrazo_twinmotion_sync` and
`%LOCALAPPDATA%/IngeTrazo/twinmotion_sync`. Normal users do not need administrator
access for these writes. Runtime prerequisites can have their own installation
requirements. See [AI setup and troubleshooting](docs/AI_SETUP.md).

## Materials, camera and updates

The first connection creates **`<model-name>_twinmotion_sync` beside the saved
`.igz`**. It holds content-named texture images, a material manifest, geometry
buffers, diagnostics and the `.udatasmith` scene with `.udsmesh` assets. Keep
this folder with the model. Originals are not rewritten. Missing images produce
warnings and fall back to face colors; default faces are white.

Edits debounce before publication. Unchanged native meshes are reused. Camera
updates use the retained scene and never recapture geometry or rebuild mesh
files. Only the latest pose is kept while the worker is busy. Camera sampling
defaults to 30 Hz; the menu's 60 Hz option is experimental source sampling,
not a guarantee of smoother Twinmotion playback.

Disconnect leaves Twinmotion open. New/Open/Save As to a different path
disconnects the source; reconnect for the new model location. Turn off the
Camera button to pause publication. Release Twinmotion's DCC Camera Sync mode
for independent navigation there.

Known gaps include glass/transparency and other PBR maps, orthographic and
two-point/off-center camera views, face-me figures, receiver roll behavior,
large-model capture pauses and full-house rendered visual acceptance. Worker
acknowledgements describe sender publication, not proof of a rendered result.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md), [the protocol](docs/PROTOCOL.md),
[validation](docs/VALIDATION.md) and [AGENTS.md](AGENTS.md). The existing
[D5 suggestion topic](https://github.com/ingelibre/ingetrazo/discussions/1000)
contains the community request for this Twinmotion connector.

Our code and SVG icons are **GPL-3.0-or-later**; see [LICENSE](LICENSE) and
[NOTICE.md](NOTICE.md). Epic runtime files retain their separate terms. No
Epic DLLs, exporter installer, Twinmotion installer, personal models or texture
caches are included. This project is not endorsed by Epic, Twinmotion or IngeTrazo.
