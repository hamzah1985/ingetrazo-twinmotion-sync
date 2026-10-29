# Community Direct Link worker

Build from readable `DirectLinkWorker.cs` using the root `setup_local.py` helper
and the separately obtained runtime. No executable or Epic vendor binaries are
tracked in this repository.

- [Runtime provenance and hashes](../../docs/RUNTIME.md)
- [Protocol and cache](../../docs/PROTOCOL.md)
- [Validation and camera limitations](../../docs/VALIDATION.md)

The current worker protocol version is 0.3.0. The Python adapter, rather than
Rhino, captures the model. Our source is GPL-3.0-or-later under the root LICENSE;
Epic runtime components retain their separate terms.
