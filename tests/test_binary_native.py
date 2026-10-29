"""Independent struct encoder / real-SDK binary transport acceptance tests."""
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET

from test_native_performance import Worker, WORKER, fixture


def encode(scene, path):
    """Fixture encoder intentionally independent of the production encoder."""
    root={k:copy.deepcopy(v) for k,v in scene.items() if k!='objects'}
    root.update(geometry_format='float32-uint32-le-v1', geometry_buffer=path.name, objects=[])
    with path.open('wb') as stream:
        stream.write(b'IGTMESH1'+struct.pack('<II',1,0))
        for obj in scene['objects']:
            record={k:copy.deepcopy(v) for k,v in obj.items() if k not in ('vertices','triangles','normals','uvs')}
            record['geometry']={'offset':stream.tell(),'vertices':len(obj['vertices']),
                                'triangles':len(obj['triangles']), 'normals':'normals' in obj,'uvs':'uvs' in obj}
            for field,dimensions,kind in (('vertices',3,'f'),('normals',3,'f'),('uvs',2,'f'),('triangles',3,'I')):
                for row in obj.get(field,[]): stream.write(struct.pack('<'+str(dimensions)+kind,*row))
            root['objects'].append(record)
    root['geometry_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    return root


@unittest.skipUnless(os.environ.get('TM_VENDOR_DIR'), 'Set TM_VENDOR_DIR for binary native tests')
class BinaryNativeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.worker=Worker(WORKER,os.environ['TM_VENDOR_DIR'],self.folder/'cache')
        self.number=0

    def tearDown(self):
        self.worker.close();self.temp.cleanup()

    def send(self,root):
        self.number+=1;path=self.folder/('snapshot%d.json'%self.number)
        path.write_text(json.dumps(root),encoding='utf8')
        reply,_=self.worker.request('snapshot',snapshot_path=str(path))
        return reply

    def asset_state(self,worker=None):
        worker=worker or self.worker
        root=ET.parse(worker.xml).getroot();result={}
        for element in root.findall('StaticMesh'):
            path=worker.xml.parent/element.find('file').attrib['path']
            self.assertTrue(path.is_file())
            result[element.attrib['name']]={'hash':hashlib.sha256(path.read_bytes()).hexdigest(),
                'mtime':path.stat().st_mtime_ns,'size':element.find('Size').attrib,
                'materials':[child.attrib for child in element.findall('Material')]}
        return result

    def test_legacy_binary_geometry_equivalence_and_unchanged_cache(self):
        self.assertTrue(self.worker.init['snapshot_buffers_supported'])
        value=fixture()
        value['objects'][0]['vertices'][1]=[1.25,.5,0]
        value['objects'][0]['normals']=[[0,.25,1]]*3
        value['objects'][0]['uvs'][1]=[.25,.5]
        value['objects'][0]['transform']=[[-2,0,0,1],[0,3,0,2],[0,0,4,3],[0,0,0,1]]
        del value['objects'][1]['normals']; del value['objects'][1]['uvs']
        legacy=self.send(value);self.assertTrue(legacy['ok'],legacy);before=self.asset_state()
        root=encode(value,self.folder/'side.bin')
        binary=self.send(root);self.assertTrue(binary['ok'],binary)
        self.assertEqual((binary['objects'],binary['triangles'],binary['mesh_exported'],binary['mesh_reused']),(2,2,0,2))
        self.assertEqual(self.asset_state(),before)
        repeat=self.send(root);self.assertTrue(repeat['ok'],repeat);self.assertEqual(repeat['mesh_reused'],2)
        self.assertEqual(self.asset_state(),before)
        # Fresh source forces the actual binary-decoded geometry export.
        other=Worker(WORKER,os.environ['TM_VENDOR_DIR'],self.folder/'fresh')
        try:
            source=self.folder/'fresh.json';source.write_text(json.dumps(root),encoding='utf8')
            reply,_=other.request('snapshot',snapshot_path=str(source));self.assertTrue(reply['ok'],reply)
            self.assertEqual(reply['mesh_exported'],2)
            fresh=self.asset_state(other)
            for key in before:
                self.assertEqual({k:v for k,v in before[key].items() if k!='mtime'},
                                 {k:v for k,v in fresh[key].items() if k!='mtime'})
        finally:other.close()

    def test_malformed_binary_inputs_preserve_previous_scene(self):
        valid=self.send(fixture());self.assertTrue(valid['ok'],valid)
        xml_before=self.worker.xml.read_bytes();assets_before=self.asset_state()
        root=encode(fixture(),self.folder/'good.bin');payload=(self.folder/'good.bin').read_bytes()
        cases=[]
        wrong=copy.deepcopy(root);wrong['geometry_sha256']='0'*64;cases.append(('hash',wrong,payload))
        wrong=copy.deepcopy(root);wrong['objects'][0]['geometry']['offset']=len(payload)+1;cases.append(('offset',wrong,payload))
        wrong=copy.deepcopy(root);wrong['objects'][0]['geometry']['offset']=15;cases.append(('header_overlap',wrong,payload))
        wrong=copy.deepcopy(root);wrong['objects'][0]['geometry']['vertices']=-1;cases.append(('negative_count',wrong,payload))
        wrong=copy.deepcopy(root);wrong['objects'][0]['geometry']['vertices']=2147483647;cases.append(('huge_count',wrong,payload))
        wrong=copy.deepcopy(root);wrong['objects'][0]['geometry']['normals']='true';cases.append(('bad_flag',wrong,payload))
        cases.append(('header',copy.deepcopy(root),b'INVALID!'+payload[8:]))
        cases.append(('truncated',copy.deepcopy(root),payload[:-1]))
        wrong_index=bytearray(payload);geometry=root['objects'][0]['geometry']
        offset=geometry['offset']+geometry['vertices']*(12+12+8)
        struct.pack_into('<I',wrong_index,offset,0xffffffff)
        cases.append(('negative_index',copy.deepcopy(root),bytes(wrong_index)))
        nonfinite=bytearray(payload);struct.pack_into('<f',nonfinite,16,float('nan'))
        cases.append(('nonfinite',copy.deepcopy(root),bytes(nonfinite)))
        wrong=copy.deepcopy(root);wrong['geometry_format']='unknown-v2';cases.append(('format',wrong,payload))
        for name,metadata,data in cases:
            with self.subTest(name=name):
                file=self.folder/(name+'.bin');file.write_bytes(data);metadata['geometry_buffer']=file.name
                if name!='hash':metadata['geometry_sha256']=hashlib.sha256(data).hexdigest()
                reply=self.send(metadata);self.assertFalse(reply['ok'],reply)
                self.assertEqual(self.worker.xml.read_bytes(),xml_before)
                self.assertEqual(self.asset_state(),assets_before)
                info,_=self.worker.request('info');self.assertEqual(info['revision'],1)
        for filename in ('../good.bin',str(self.folder/'good.bin'),'sub/good.bin','sub\\good.bin'):
            with self.subTest(filename=filename):
                metadata=copy.deepcopy(root);metadata['geometry_buffer']=filename
                reply=self.send(metadata);self.assertFalse(reply['ok'],reply)
                self.assertEqual(self.worker.xml.read_bytes(),xml_before)


if __name__=='__main__':unittest.main()
