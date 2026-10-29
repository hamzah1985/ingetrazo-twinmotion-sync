# Working on IngeTrazo Twinmotion Sync

Read README.md, docs/AI_SETUP.md and docs/RUNTIME.md first. This repository is
the Windows Python/C# Twinmotion connector, not the D5 or SketchUp plugin.

## Installation work

- Inspect installed IngeTrazo/Twinmotion versions and existing plugin/runtime
  configuration before changing them. Preserve user models, companion folders
  and unrelated plugins. Use a separate saved test model for acceptance.
- Obtain the separately licensed runtime from Epic's official source. Follow
  vendor terms and the user's approval requirements. Do not redistribute or
  commit the MSI, DLLs, .rhp wrapper or extracted vendor files.
- Use `python setup_local.py --vendor-dir <runtime-folder>` to verify hashes,
  build our worker and install. `--check-only` validates prerequisites without
  installing. The helper uses Windows' .NET Framework C# compiler, not C++.
- Do not weaken execution policies, firewall settings or security protections.
  Use the Python setup path when PowerShell scripts are blocked. Explain any
  vendor/OS prompt the user must handle under your own tool rules.
- Restart IngeTrazo after a normal update. Do not restart an app holding
  unsaved work without preserving it and obtaining any required authorization.
- Configure the existing Twinmotion Direct Link import and DCC Camera Sync.
  A new worker filename may require relinking that existing import.
- Inspect the companion diagnostics on errors. Test geometry, white faces,
  a diffuse image and camera orbit separately. A successful native reply does
  not establish receiver import, matching pose or correct shading.

## Implementation and verification

- `ingetrazo_twinmotion_sync/plugin.py`: toolbar, GUI-thread capture, scheduling,
  latest-pose backpressure, lifecycle and diagnostics.
- `scene_capture.py`: read-only host geometry/material/camera capture and
  persistent texture recovery. Keep default white and nearest-parent paint.
- `scene_transport.py`: validated binary sidecar encoding and atomic commits.
- `worker_process.py`: native I/O on background readers with queued Qt signals.
- `native/DirectLinkWorker.cs`: native validation, mesh cache and publication.
- Keep live host scene reads on its GUI thread. Keep camera-only updates free
  of geometry capture/export. Do not delete user assets from companion folders.
- Preserve stable identities, inverse-transpose normals, mirrored winding and
  material rebinding. Validate a complete input before replacing the native scene.
- Run the tests in CONTRIBUTING.md. Native tests require the external official
  runtime and a built worker; report skipped tests honestly. Run relevant native
  tests for geometry/material/protocol changes and live acceptance for UI claims.
- The measured receiver rate was about 10 Hz on one small Twinmotion 2026.1
  fixture. Do not describe the source's 30/60Hz target as receiver frame rate
  or promise D5-like camera smoothness. Do not patch vendor binaries to claim a fix.
- Commit readable source only. Keep vendor binaries, generated executables,
  user documents, logs, installation backups and texture caches out of Git.

Publish only changes explicitly authorized by the user. Do not upload a user's
diagnostics or models as part of troubleshooting without their authorization.
