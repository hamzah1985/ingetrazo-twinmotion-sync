# SPDX-License-Identifier: GPL-3.0-or-later
"""Small JSON metadata plus typed geometry buffers for the native worker."""
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import numpy as np

FORMAT = 'float32-uint32-le-v1'
HEADER = struct.pack('<8sII',b'IGTMESH1',1,0)

def _vectors(values,width,count=None):
    with np.errstate(over='ignore',invalid='ignore'):
        data=np.asarray(values,dtype='<f4')
    if data.size==0:
        data=data.reshape((0,width))
    if data.ndim!=2 or data.shape[1]!=width or (count is not None and len(data)!=count):
        raise ValueError('Invalid geometry array shape.')
    if not np.isfinite(data).all():
        raise ValueError('Geometry contains non-finite coordinates.')
    return np.ascontiguousarray(data)

class PreparedScene:
    def __init__(self,metadata,temporary,revision):
        self.metadata,self.temporary,self.revision=metadata,temporary,revision

    def commit(self,path,buffer_name,camera=None):
        path=Path(path)
        if Path(buffer_name).name!=buffer_name or not buffer_name.endswith('.bin'):
            raise ValueError('Geometry buffer must be a filename beside the snapshot.')
        if self.temporary.parent!=path.parent:
            raise ValueError('Snapshot and geometry buffer must share a directory.')
        metadata=dict(self.metadata,geometry_buffer=buffer_name)
        if camera is not None:
            metadata['camera']=camera
        data=json.dumps(metadata,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf8')
        # Two alternating, session-owned buffers keep the currently referenced
        # buffer intact until the new JSON is atomically committed. No reader
        # sees a JSON file pointing at a partially replaced buffer.
        os.replace(self.temporary,path.parent/buffer_name)
        with tempfile.NamedTemporaryFile(dir=path.parent,suffix='.json.tmp',delete=False) as stream:
            pending=Path(stream.name)
            stream.write(data)
        try:
            os.replace(pending,path)
        finally:
            pending.unlink(missing_ok=True)

    def close(self):
        self.temporary.unlink(missing_ok=True)

def prepare_scene(scene,folder):
    """Read captured arrays only; never touch the live host scene off its GUI thread."""
    metadata={k:v for k,v in scene.items() if k not in ('objects','camera')}
    metadata['geometry_format']=FORMAT
    metadata['objects']=[]
    digest=hashlib.sha256()
    with tempfile.NamedTemporaryFile(dir=folder,suffix='.geometry.tmp',delete=False) as stream:
        temporary=Path(stream.name)
        try:
            stream.write(HEADER);digest.update(HEADER)
            for obj in scene['objects']:
                vertices=_vectors(obj['vertices'],3)
                triangles=np.asarray(obj['triangles'])
                if triangles.size==0:
                    triangles=triangles.reshape((0,3))
                if triangles.ndim!=2 or triangles.shape[1]!=3 or triangles.dtype.kind not in 'iuf':
                    raise ValueError('Invalid triangle array.')
                if not (np.isfinite(triangles).all() and np.equal(triangles,np.trunc(triangles)).all()
                        and (triangles>=0).all() and (triangles<len(vertices)).all()):
                    raise ValueError('Triangle indices are outside the mesh.')
                triangles=np.ascontiguousarray(triangles,dtype='<u4')
                normals=_vectors(obj['normals'],3,len(vertices)) if obj.get('normals') is not None else None
                uvs=_vectors(obj['uvs'],2,len(vertices)) if obj.get('uvs') is not None else None
                item={k:v for k,v in obj.items() if k not in ('vertices','triangles','normals','uvs')}
                item['geometry']={'offset':stream.tell(),'vertices':len(vertices),
                                  'triangles':len(triangles),'normals':normals is not None,'uvs':uvs is not None}
                metadata['objects'].append(item)
                for data in (vertices,normals,uvs,triangles):
                    if data is not None and data.size:
                        view=memoryview(data).cast('B')
                        stream.write(view);digest.update(view)
            metadata['geometry_sha256']=digest.hexdigest()
            compact=json.dumps(metadata,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf8')
            revision=hashlib.sha256(compact).hexdigest()
        except BaseException:
            stream.close();temporary.unlink(missing_ok=True)
            raise
    return PreparedScene(metadata,temporary,revision)
