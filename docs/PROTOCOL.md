# Worker protocol and architecture

`native/DirectLinkWorker.cs` is our standalone C# process. It resolves the
external official facade at runtime and does not invoke Rhino APIs. Source
capture stays on IngeTrazo's GUI thread; anonymous pipes use background readers
and queued Qt signals. Geometry travels through atomic files rather than stdin.

Build with `python setup_local.py --vendor-dir <directory> --build-only`.
Run the resulting `DirectLinkWorker.exe <external-runtime-directory>` and send
one UTF-8 JSON object per stdin line. Recognize only stdout lines beginning
`INGETRAZO_TM `; the suffix is a JSON reply including `ok` and `op`. SDK logging
also appears on stdout.

```json
{"op":"init","scene_name":"IngeTrazo — Test","cache_dir":"C:/Test/Test_twinmotion_sync"}
{"op":"snapshot","snapshot_path":"C:/Test/Test_twinmotion_sync/ingetrazo-scene.json"}
{"op":"camera","camera":{"position":[1,2,3],"forward":[0,1,0],"up":[0,0,1],"horizontal_fov":60,"aspect":1.7777778,"focus_distance":10,"orthographic":false}}
{"op":"info"}
{"op":"quit"}
```

The native scene/source persist between snapshots. Actor/mesh/material IDs are
deterministic. Omitted camera data preserves the previous pose. A camera request
with `write_scene:true` also refreshes diagnostic XML without rebuilding meshes;
ordinary camera-only updates stay in live Direct Link memory.

Materials use `id`, `name`, sRGB `color` (`#RRGGBB` or normalized RGB), roughness,
metallic, optional specular and optional `diffuse_map`. Images are staged by
content hash. Missing images warn and preserve face color. White is linear RGB1;
diffuse images use sRGB. Normal/PBR maps and opacity are not yet captured.

Objects contain `id`, `name`, `material_id`, optional row-major 4×4 transform,
and either legacy arrays (`vertices`, `triangles`, optional `normals`/`uvs`) or
the compact descriptor below. Source coordinates are right-handed Z-up metres.
Positions bake the transform; normals use inverse transpose; mirrored transforms
reverse winding and degenerate triangles are filtered. The facade converts to
left-handed centimetres. `uv_flip_v` defaults to true.

## Compact geometry

The init capability `snapshot_buffers_supported:true` enables the binary path.
Root snapshot fields are `geometry_format:"float32-uint32-le-v1"`,
`geometry_buffer:"filename.bin"` and `geometry_sha256:"<64 hex characters>"`.
The sidecar must be a basename beside the snapshot. Its 16-byte header is
`IGTMESH1`, uint32LE version1 and uint32LE reserved0. Each object replaces its
four arrays with:

```json
{"geometry":{"offset":16,"vertices":3,"triangles":1,"normals":true,"uvs":true}}
```

At that absolute offset: N×3 float32LE positions, optional N×3 normals, optional
N×2 UVs and T×3 uint32LE indices, without padding. Format, digest, header,
location and checked ranges validate before allocation; floats must be finite
and indices in range. The entire snapshot validates before resetting the scene.
Two session-owned alternating buffers keep the prior committed pair readable.

## Cache and reporting

Native mesh signatures include transformed positions, normals, UVs, emitted
triangles and UV flip. Unchanged mesh elements/assets are reused. Material
rebinding updates without a mesh export. Missing assets regenerate and removed
objects release cache entries; user disk assets are not pruned. Absolute asset
paths are restored before repeated XML exports because the SDK mutates them to
relative paths.

Replies include mesh reuse/export counts and parse/export/publish timings.
Camera replies include `cameraPublish_ms` and `camera_total_ms`. These are
sender measurements. `receiver_connection`/`receiver_camera_sync` stay
`unverified` and legacy `camera_sync:false` remains for compatibility because
the worker does not confirm Twinmotion's rendered view. Live camera following
was separately observed; see VALIDATION.md for the measured cadence and limits.
