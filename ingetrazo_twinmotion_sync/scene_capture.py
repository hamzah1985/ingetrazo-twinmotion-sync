# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only IngeTrazo geometry and material capture for Twinmotion."""
import hashlib
import json
import math
import os
import re
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parent
IDENTITY = [[1,0,0,0], [0,1,0,0], [0,0,1,0], [0,0,0,1]]
MATERIAL_CACHE = 'ingetrazo-twinmotion-materials.json'


def read_material_cache(folder):
    path = Path(folder)/MATERIAL_CACHE
    if not path.exists():
        return {'assets': {}}
    if path.resolve().parent != Path(folder).resolve():
        raise ValueError('The Twinmotion material cache points outside the companion folder.')
    record = json.loads(path.read_text(encoding='utf8'))
    if record.get('generator') != 'IngeTrazo Twinmotion Sync' or record.get('format') != 1:
        raise ValueError('The Twinmotion material cache has an unsupported format; it was not overwritten.')
    if not isinstance(record.get('assets'), dict) or not all(
            isinstance(k,str) and isinstance(v,str) for k,v in record['assets'].items()):
        raise ValueError('The Twinmotion material cache has an invalid asset index.')
    return record


def write_material_cache(folder, document_path, materials, assets, warnings):
    folder = Path(folder).resolve()
    portable = []
    for material in sorted(materials, key=lambda item:item['id']):
        item = dict(material)
        if item.get('diffuse_map'):
            image = Path(item['diffuse_map']).resolve()
            if image.parent != folder:
                raise ValueError('Cached material image is outside the companion folder.')
            item['diffuse_map'] = image.name
        portable.append(item)
    record = {'generator':'IngeTrazo Twinmotion Sync', 'format':1,
              'document':Path(document_path).name, 'materials':portable,
              'assets':assets, 'warnings':warnings}
    with tempfile.NamedTemporaryFile(dir=str(folder), suffix='.json.tmp', delete=False) as out:
        temporary = Path(out.name)
        out.write(json.dumps(record, indent=2, ensure_ascii=False).encode('utf8'))
    try:
        os.replace(temporary, folder/MATERIAL_CACHE)
    finally:
        if temporary.exists():
            temporary.unlink()


def prepare_texture_folder(document_path):
    """Created on first Connect, always beside an already saved IGZ file."""
    if not document_path:
        raise ValueError('Save the IngeTrazo model before starting Twinmotion Sync.')
    document = Path(document_path).resolve()
    if document.suffix.lower() != '.igz' or not document.is_file():
        raise ValueError('Save the model as an IngeTrazo .igz file before starting Twinmotion Sync.')
    folder = document.parent / (document.stem + '_twinmotion_sync')
    folder.mkdir(exist_ok=True)
    if folder.resolve().parent != document.parent:
        raise ValueError('The texture companion folder points outside the model directory.')
    return folder


def cache_texture(source_path, folder, document_path, assets=None):
    """Copy valid images only; content names avoid collisions and overwrites."""
    from core.texture import is_image_file
    source = Path(source_path)
    if not source.is_absolute():
        source = Path(document_path).resolve().parent / source
    source = source.resolve()
    folder = Path(folder).resolve()
    assets = read_material_cache(folder)['assets'] if assets is None else assets
    source_key = os.path.normcase(str(source))
    if not is_image_file(source):
        cached = assets.get(source_key)
        if cached is None:
            matches = {value for key,value in assets.items()
                       if Path(key).name.casefold() == source.name.casefold()}
            cached = next(iter(matches)) if len(matches) == 1 else None
        if cached is not None:
            if not isinstance(cached, str) or not re.fullmatch(r'[0-9a-f]{64}\.[a-z0-9]+', cached):
                raise ValueError('The cached texture index contains an invalid image name.')
            target = (folder/cached).resolve()
            if target.parent != folder:
                raise ValueError('The cached texture points outside the companion folder.')
            if is_image_file(target):
                if hashlib.sha256(target.read_bytes()).hexdigest() != target.stem:
                    raise ValueError('A cached texture does not match its content hash.')
                return target
        raise FileNotFoundError('Texture unavailable: ' + source.name)
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    suffix = source.suffix.lower()
    for signature, extension in [(b'\x89PNG\r\n\x1a\n', '.png'), (b'\xff\xd8\xff', '.jpg'),
                                 (b'GIF', '.gif'), (b'BM', '.bmp'), (b'II*\0', '.tif'),
                                 (b'MM\0*', '.tif'), (b'RIFF', '.webp')]:
        if data.startswith(signature):
            suffix = extension
            break
    target = folder / (digest + suffix)
    assets[source_key] = target.name
    if target.exists():
        if target.read_bytes() != data:
            raise ValueError('An existing texture cache file has unexpected contents: ' + str(target))
        return target
    # A completed image becomes visible to Twinmotion in one rename. Originals and
    # unrelated files in the companion folder are never moved or deleted.
    with tempfile.NamedTemporaryFile(dir=str(folder), suffix='.tmp', delete=False) as out:
        temporary = Path(out.name)
        out.write(data)
    try:
        temporary.rename(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def matrix_rows(matrix):
    if matrix is None:
        return [row[:] for row in IDENTITY]
    data = matrix.data()
    return [[float(data[c*4+r]) for c in range(4)] for r in range(4)]


def capture_camera(camera):
    """Use the actual inverse view, including pan, orbit, roll and first person."""
    if not camera.perspective:
        raise ValueError('Orthographic camera sync is unsupported; use perspective in IngeTrazo.')
    if getattr(camera,'two_point',False):
        raise ValueError('Two-point camera sync is unsupported; use normal perspective in IngeTrazo.')
    world,invertible = camera.view_matrix().inverted()
    if not invertible:
        raise ValueError('Camera view matrix is not invertible.')
    values = world.data()
    vertical_fov,aspect = float(camera.fov_deg),float(camera.aspect)
    distance = float(camera.distance)
    if not all(math.isfinite(v) for v in (vertical_fov,aspect,distance)) or not (
            0<vertical_fov<179 and aspect>0 and distance>0):
        raise ValueError('Camera projection contains invalid values.')
    result = {'position':[float(values[i]) for i in (12,13,14)],
              'forward':[-float(values[i]) for i in (8,9,10)],
              'up':[float(values[i]) for i in (4,5,6)],
              'horizontal_fov':math.degrees(2*math.atan(math.tan(math.radians(vertical_fov)/2)*aspect)),
              'aspect':aspect,'focus_distance':distance,'orthographic':False}
    if not all(math.isfinite(v) for key in ('position','forward','up') for v in result[key]):
        raise ValueError('Camera transform contains invalid values.')
    if not (1<result['horizontal_fov']<179 and 0.0001<=aspect<=10000 and distance<=1e9):
        raise ValueError('Camera projection is outside the supported field of view, aspect or distance range.')
    return result


def capture_scene(scene, document_path=None, texture_folder=None):
    """Read scene on its GUI thread; images copy only into its companion folder."""
    from formats.meshexport import export_triangles, SmoothNormals
    from core.materials import effective_attrs
    from core.texture import affine_uv, planar_uv
    materials = {}
    material_ids = {}
    colors = {}
    objects = []
    cached = {}
    warnings = []
    assets = read_material_cache(texture_folder)['assets'] if texture_folder is not None else {}
    smoother = SmoothNormals()

    def mesh_parts(mesh, path, name, matrix, paint, loose=False):
        parts = {}
        transform = matrix_rows(matrix)
        for face in mesh.faces:
            if not scene.entity_visible(face):
                continue
            attrs = effective_attrs(face.attrs, paint) or {}
            rgb = tuple(attrs.get('color') or (1.0, 1.0, 1.0))[:3]
            color = colors.get(rgb)
            if color is None:
                color = '#' + ''.join('%02X' % max(0, min(255, round(float(c)*255))) for c in rgb)
                colors[rgb] = color
            texture = attrs.get('texture') or {}
            texture_path = texture.get('path')
            diffuse_map = None
            if texture_path:
                if not document_path or texture_folder is None:
                    raise ValueError('Save the model and connect Twinmotion Sync before sending textures.')
                if texture_path not in cached:
                    try:
                        cached[texture_path] = cache_texture(texture_path, texture_folder, document_path, assets)
                    except FileNotFoundError as error:
                        cached[texture_path] = None
                        warnings.append(str(error) + '; using the face color.')
                if cached[texture_path] is not None:
                    diffuse_map = str(cached[texture_path])
                    # The host's own mesh exporter uses white for textured faces.
                    color = '#FFFFFF'
            mat_name = attrs.get('mat') or ('Default White' if not attrs.get('color') and not diffuse_map
                                            else 'Color ' + color)
            key = (mat_name,color,diffuse_map)
            mid = material_ids.get(key)
            if mid is None:
                identity = json.dumps([mat_name, color, Path(diffuse_map).name if diffuse_map else ''], sort_keys=True)
                mid = material_ids[key] = hashlib.sha256(identity.encode('utf8')).hexdigest()[:24]
                materials[mid] = {'id': mid, 'name': mat_name, 'color': color,
                                  'metallic': 0.0, 'specular': 0.5, 'roughness': 0.5}
                if diffuse_map:
                    materials[mid]['diffuse_map'] = diffuse_map
            part = parts.get(mid)
            if part is None:
                part = parts[mid] = {'id': path + '/' + mid, 'name': name,
                                     'vertices': [], 'triangles': [],
                                     'uvs': [], 'normals': [],
                                     'material_id': mid, 'transform': transform}
            smooth = smoother.corners(face)
            flat = smoother.flat(face)
            for tri in export_triangles(face):
                start = len(part['vertices'])
                part['vertices'].extend([[float(p.x()), float(p.y()), float(p.z())] for p in tri])
                part['normals'].extend([list(smooth.get(p.toTuple(), flat).toTuple()) for p in tri])
                if diffuse_map:
                    uvw = texture.get('uvw')
                    uv = affine_uv(uvw, tri) if uvw else planar_uv(
                        face.normal(), tri, texture.get('sw', 1.0) or 1.0,
                        texture.get('sh', 1.0) or 1.0, float(texture.get('rot', 0.0)))
                    part['uvs'].extend([[float(u), float(v)] for u, v in uv])
                else:
                    part['uvs'].extend([[0.0, 0.0] for _ in tri])
                part['triangles'].append([start, start+1, start+2])
        objects.extend(part for part in parts.values() if part['triangles'])

    def group_parts(group, parent, path, top_paint):
        if not scene.entity_visible(group):
            return
        local = getattr(group, 'xform', None)
        world = local if parent is None else parent if local is None else parent * local
        path = path + '/' + str(group.uid)
        paint = getattr(group, 'material', None) or top_paint
        mesh_parts(group.mesh, path, getattr(group, 'name', '') or 'Group', world, paint)
        for child in getattr(group, 'children', ()) or ():
            group_parts(child, world, path, paint)

    mesh_parts(scene.loose_mesh, 'loose', 'Loose geometry', None, None, loose=True)
    for group in scene.groups:
        group_parts(group, None, 'group', getattr(group, 'material', None))
    snapshot = {'materials': list(materials.values()), 'objects': objects}
    if texture_folder is not None:
        snapshot['texture_folder'] = str(Path(texture_folder).resolve())
        snapshot['document_path'] = str(Path(document_path).resolve())
        write_material_cache(texture_folder, document_path, snapshot['materials'], assets, warnings)
    if warnings:
        snapshot['warnings'] = warnings
    return snapshot
