# Validation and known limits — 2026-10-29

The published adapter/native source matches the locally tested 0.3.0 prototype.
The host tests use IngeTrazo source commit
`a369d1ed1bf3567f98045113b6a64df23b8d5f43`. Discovery, toolbar setup and compact
encoding also loaded in the installed host's Python 3.12/Qt runtime.

All 25 local tests passed with the external Epic runtime. They cover binary and
legacy geometry equivalence; invalid input retaining the previous scene;
default white and recovered images; inherited paint; mirrored/nonuniform
transforms; mesh cache invalidation; material rebinding; deletion; stable IDs;
camera transforms and mesh preservation; latest-pose dispatch; diagnostics
coalescing; Save As separation; upgrade preservation and clean shutdown.
CI runs portable tests only and skips native cases without the external runtime.

A saved-house export audit checked 4,025 objects, 246,742 triangles, 142 materials
and 11 diffuse images. Every referenced native mesh/image existed, white was
linear RGB 1, and the input model hash stayed unchanged. Camera-only updates
preserved all mesh files. Comparing every capture value before/after the
capture refinement yielded identical geometry/material data. These export checks
do not certify full-house rendered shading, UV orientation or curved surfaces.

## Source measurements

| Measurement | Previous prototype | 0.3.0 |
|---|---:|---:|
| Sender cadence, 3-second small fixture | 9.33 updates/s | 29.33 updates/s |
| Send-gap median / p95 | 109.74 / 112.57 ms | 33.70 / 34.96 ms |
| Diagnostic writes, including lifecycle |31 |5 |
| Identical house native snapshot | 14.34 s | 1.29 s, 4,025 meshes reused |
| House transport | 86.2 MB JSON | 1.70 MB metadata + 26.65 MB buffer |

These are source-process measurements. The 60 Hz source-only benchmark delivered
51.66 updates/s, but that is not a Twinmotion frame or camera-apply rate.
Full geometry capture remains on the host GUI thread (about 7 seconds for the
large house), and the camera pauses during an in-flight geometry request.

## Live Twinmotion 2026.1 receiver

The existing import was reconnected after the worker update. DCC Camera Sync
became active and followed an IngeTrazo orbit. Brick texture and white faces
were visible on a small cube fixture.

Two four-second camera sweeps with Twinmotion foreground measured:

| Source target | Actual source sends | Receiver camera-change events | Median / p95 receiver gap |
|---|---:|---:|---:|
| 30 Hz |27.99/s |9.75/s | 101 / 104 ms |
| 60 Hz |33.36/s |9.46/s | 102 / 104 ms |

The original pose/rate were restored; geometry publication count and scene
version stayed unchanged during the sweeps. Receiver events came from its
`OnChangedElement ingetrazo_active_view` log entries, not displayed-frame
timestamps or per-pose latency. 60 Hz source sampling did not improve this result.

The actual facade 5.8.4 public wrapper and
[API](https://dev.epicgames.com/documentation/unreal-engine/API/Developer/DatasmithFacade/FDatasmithFacadeDirectLink)
expose no supported rate setter or separate camera transport. Locally installed
UE 5.8.2 implementation source uses 50 ms endpoint polling, staged exchanges and a
single pending snapshot. That is consistent with the observed cadence, but is
not byte-identical proof for facade 5.8.4 or a universal 10 Hz Twinmotion ceiling.

Remaining gaps: transparency/glass and other PBR maps; orthographic and two-point
views; face-me figures; receiver roll behavior; arbitrary mapping cases; full-house
rendered acceptance; and large-model responsiveness. Camera sync works but is
not yet as smooth as the D5 prototype. Contributions addressing these limits
need repeatable sender **and receiver** evidence.
