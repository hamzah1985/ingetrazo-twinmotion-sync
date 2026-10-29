# Contributing

Fork this repository, make a focused change and open a pull request against
`main`. Read AGENTS.md and include reproduction steps, relevant app/runtime
versions and verification. Do not commit vendor binaries, generated executables,
user documents, texture caches, diagnostic logs or installation backups.

## Portable tests

Use a separate Python 3.13 development environment. IngeTrazo's requirements and
the tested versions are pinned independently from the plugin's runtime:

```powershell
git clone https://github.com/ingelibre/ingetrazo .test-deps/ingetrazo
git -C .test-deps/ingetrazo checkout a369d1ed1bf3567f98045113b6a64df23b8d5f43
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt -r .test-deps/ingetrazo/requirements.txt
$env:PYTHONPATH = (Resolve-Path '.test-deps/ingetrazo').Path
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONUTF8 = '1'
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

Without `TM_VENDOR_DIR`, native cases skip. Report that distinction. CI uses
this pinned host API and portable checks; it cannot certify Twinmotion rendering.

## Native and live checks

Obtain the exact external runtime from docs/RUNTIME.md and build without installing:

```powershell
$env:TM_VENDOR_DIR = 'C:\DatasmithRuntime'
python setup_local.py --vendor-dir $env:TM_VENDOR_DIR --build-only
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

Native tests start isolated worker sources/caches and check real Datasmith assets.
`tests/audit_house.py <saved-model.igz> <report.json>` reads the supplied saved
model, publishes through the Qt controller and audits native asset references;
it writes a companion folder beside that model. Use your own disposable copy.
Do not point live acceptance at an unsaved user document or a production project.

For camera/material fixes, compare actual views in both apps on a separate model.
Include receiver evidence rather than only worker acknowledgements. Keep the
current public protocol backward compatible where possible and update docs/tests
for durable behavior changes. The original benchmarks were small bounded runs;
do not present them as broad performance guarantees.
