# External Epic runtime

This repository contains our source only. It does not grant permission to
redistribute Epic's exporter or native runtime. Obtain them separately from
Epic, following the applicable vendor terms.

The tested runtime is extracted from the official **Datasmith Rhino exporter
5.8.4**, without running the Rhino plugin installer. No Rhino API or executable
is called by our worker, and Rhino does not need to be installed.

- [Official Epic exporter page](https://www.unrealengine.com/plugins/rhino)
- [Exact tested MSI](https://unrealstudio.epicgames.com/UnrealDatasmithRhinoExporter_5_8_400.msi)
- MSI size:29,286,400 bytes; SHA256:
  `7f0e3039e9c8a772b20654342854d497c16799a92077ba2a9df0e9076f1b1927`

Extract the MSI's embedded cabinet into a separate local runtime directory with
an MSI/CAB extraction tool. Extraction is separate from installing the Rhino
plugin. Codex or OpenCode can help find an appropriate local extractor and
identify the files. Do not run an arbitrary downloaded helper or alter security
settings to extract it. Vendor or OS prompts may need the user's action.

Put these files together in the directory passed as `--vendor-dir`:

| File | SHA256 |
|---|---|
| `DatasmithFacadeCSharp.dll` | `eb3e4881629244bbc3a5cb1062aa579d79f68ebb682b5140a274c7c0d1d6fc08` |
| `DatasmithRhino6.rhp` | `77e2073dc7bd792896f976562f97f125dd1289231338b20ef5bd8d2b6795cd1d` |
| `tbbmalloc.dll` | `87abcd8f7e31003ab049962a97eb645310be1ccab7ba148c46b2cde5262027bf` |

The managed wrapper assembly is `DatasmithRhino6, Version=5.8.4.0`, CLR4. The
native facade and allocator are x64. Their native Microsoft VC++ runtime and
Windows .NET Framework prerequisites remain separate. The setup helper checks
these exact file hashes and stores a local path; it never downloads or bundles
them. A future exporter version needs compatibility testing and reviewed hashes.

The .rhp extension is the managed wrapper's filename. Our process resolves its
public Datasmith facade types directly; it does not load RhinoCommon or call
Rhino modeling APIs. This is an unofficial integration with separately licensed
components, not an Epic-certified distribution bundle.
