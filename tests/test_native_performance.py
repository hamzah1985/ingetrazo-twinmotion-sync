"""Real SDK cache acceptance and repeatable sender-only benchmark utility."""
import argparse
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import queue
import statistics
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT/'ingetrazo_twinmotion_sync/native/DirectLinkWorker.exe'
PREFIX = 'INGETRAZO_TM '


class Worker:
    def __init__(self, exe, vendor, cache):
        self.queue = queue.Queue()
        self.logs, self.errors = [], []
        self.proc = subprocess.Popen([str(exe), str(vendor)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, encoding='utf8')
        def read():
            for line in self.proc.stdout:
                if line.startswith(PREFIX): self.queue.put(json.loads(line[len(PREFIX):]))
                else: self.logs.append(line.rstrip())
        def errors(): self.errors.extend(self.proc.stderr)
        self.threads = [threading.Thread(target=read, daemon=True), threading.Thread(target=errors, daemon=True)]
        for thread in self.threads: thread.start()
        self.init, _ = self.request('init', scene_name='IngeTrazo isolated performance '+uuid.uuid4().hex,
                                    cache_dir=str(cache))
        if not self.init.get('ok'): raise RuntimeError(self.init)
        self.xml = Path(self.init['scene_path'])

    def request(self, op, **fields):
        payload=json.dumps({'op':op, **fields}, ensure_ascii=False)+'\n'
        start=time.perf_counter()
        self.proc.stdin.write(payload); self.proc.stdin.flush()
        result=self.queue.get(timeout=180)
        return result, (time.perf_counter()-start)*1000

    def close(self):
        try:
            if self.proc.poll() is None:
                self.request('quit'); self.proc.stdin.close(); self.proc.wait(timeout=15)
            if self.proc.returncode: raise AssertionError(''.join(self.errors))
        finally:
            if self.proc.poll() is None: self.proc.kill(); self.proc.wait(timeout=5)
            for thread in self.threads: thread.join(timeout=2)
            for stream in (self.proc.stdin,self.proc.stdout,self.proc.stderr):
                if not stream.closed: stream.close()


def pose(x=2):
    return {'position':[x,3,4], 'forward':[0,-1,-.2], 'up':[0,0,1], 'horizontal_fov':70,
            'aspect':1.6, 'focus_distance':5, 'orthographic':False}


def mesh(identifier, x=0):
    return {'id':identifier, 'name':identifier, 'material_id':'white',
            'vertices':[[x,0,0],[x+1,0,0],[x,1,0]], 'triangles':[[0,1,2]],
            'normals':[[0,0,1]]*3, 'uvs':[[0,0],[1,0],[0,1]]}


def fixture():
    return {'materials':[{'id':'white','name':'White','color':'#FFFFFF'}],
            'objects':[mesh('a'),mesh('b',3)], 'camera':pose()}


@unittest.skipUnless(os.environ.get('TM_VENDOR_DIR'), 'Set TM_VENDOR_DIR for real-SDK performance tests')
class NativeCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.folder=Path(self.temp.name)
        self.worker=Worker(WORKER, os.environ['TM_VENDOR_DIR'], self.folder/'cache')
        self.sequence=0

    def tearDown(self):
        self.worker.close(); self.temp.cleanup()

    def snapshot(self, value):
        self.sequence+=1; path=self.folder/('scene%d.json'%self.sequence)
        path.write_text(json.dumps(value),encoding='utf8')
        reply,_=self.worker.request('snapshot', snapshot_path=str(path)); self.assertTrue(reply['ok'],reply)
        for field in ('snapshot_parse_ms','snapshot_export_ms','snapshot_publish_ms','snapshot_total_ms'):
            self.assertGreaterEqual(reply[field],0)
        root=ET.parse(self.worker.xml).getroot()
        for element in root.findall('StaticMesh'):
            self.assertTrue((self.worker.xml.parent/element.find('file').attrib['path']).is_file())
        return reply

    def assets(self):
        return {p.name:(hashlib.sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns)
                for p in self.worker.xml.parent.rglob('*.udsmesh')}

    def test_unchanged_changed_added_removed_and_camera_paths(self):
        value=fixture(); initial=self.snapshot(value); before=self.assets()
        self.assertEqual((initial['mesh_exported'],initial['mesh_reused']),(2,0))
        unchanged=self.snapshot(value)
        self.assertEqual((unchanged['mesh_exported'],unchanged['mesh_reused']),(0,2))
        self.assertEqual(self.assets(),before)
        for i in range(12):
            reply,_=self.worker.request('camera',camera=pose(i))
            self.assertTrue(reply['ok'],reply); self.assertGreaterEqual(reply['cameraPublish_ms'],0)
            self.assertEqual(reply['mesh_cache_entries'],2)
        self.assertEqual(self.assets(),before)
        value['objects'][0]['vertices'][1][0]=1.25
        changed=self.snapshot(value)
        self.assertEqual((changed['mesh_exported'],changed['mesh_reused']),(1,1))
        after=self.assets(); self.assertEqual(sum(before[k]!=after[k] for k in before),1)
        value['objects'].append(mesh('c',6))
        added=self.snapshot(value); self.assertEqual((added['mesh_exported'],added['mesh_reused']),(1,2))
        value['objects']=value['objects'][1:]
        removed=self.snapshot(value)
        self.assertEqual((removed['mesh_exported'],removed['mesh_reused'],removed['mesh_cache_entries']),(0,2,2))
        self.assertEqual(len(ET.parse(self.worker.xml).getroot().findall('ActorMesh')),2)
        # Removed assets remain on disk; the worker never prunes user files.
        self.assertEqual(len(self.assets()),3)
        value['objects']=[]
        emptied=self.snapshot(value)
        self.assertEqual((emptied['mesh_exported'],emptied['mesh_reused'],emptied['mesh_cache_entries']),(0,0,0))
        self.assertFalse(ET.parse(self.worker.xml).getroot().findall('StaticMesh'))
        self.assertEqual(len(self.assets()),3)

    def test_transform_normal_uv_and_flip_invalidate_only_affected_mesh(self):
        value=fixture(); self.snapshot(value)
        for change in ('transform','normal','uv','indices','flip'):
            with self.subTest(change=change):
                if change=='transform': value['objects'][0]['transform']=[[1,0,0,2],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
                elif change=='normal': value['objects'][0]['normals']=[[0,.25,1]]*3
                elif change=='uv': value['objects'][0]['uvs'][1][0]=.25
                elif change=='indices': value['objects'][0]['triangles']=[[0,2,1]]
                else: value['uv_flip_v']=False
                reply=self.snapshot(value)
                expected=(2,0) if change=='flip' else (1,1)
                self.assertEqual((reply['mesh_exported'],reply['mesh_reused']),expected)

    def test_missing_asset_regenerates_and_material_change_reuses_geometry(self):
        value=fixture(); self.snapshot(value)
        target=next(self.worker.xml.parent.rglob('*.udsmesh')); target.unlink()
        regenerated=self.snapshot(value)
        self.assertEqual((regenerated['mesh_exported'],regenerated['mesh_reused']),(1,1))
        self.assertTrue(target.is_file())
        before=self.assets(); value['materials'][0]['color']='#00FF00'
        reused=self.snapshot(value); self.assertEqual((reused['mesh_exported'],reused['mesh_reused']),(0,2))
        self.assertEqual(self.assets(),before)
        root=ET.parse(self.worker.xml).getroot()
        color=root.find('UEPbrMaterial/Expressions/Color').attrib['constant']
        self.assertIn('R=0.000000,G=1.000000,B=0.000000',color)
        reply,_=self.worker.request('camera',camera=pose(10),write_scene=True)
        self.assertTrue(reply['ok'],reply)
        self.assertEqual(self.assets(),before)
        for element in ET.parse(self.worker.xml).getroot().findall('StaticMesh'):
            self.assertTrue((self.worker.xml.parent/element.find('file').attrib['path']).is_file())

    def test_cached_material_rebinding_and_texture_links_after_repeated_writes(self):
        texture=self.folder/'texture.png'
        texture.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aB4cAAAAASUVORK5CYII='))
        value=fixture(); value['materials'][0]['diffuse_map']=str(texture)
        self.snapshot(value); before=self.assets()
        value['materials'].append({'id':'red','name':'Red','color':'#FF0000'})
        value['objects'][0]['material_id']='red'
        reply=self.snapshot(value)
        self.assertEqual((reply['mesh_exported'],reply['mesh_reused']),(0,2))
        self.assertEqual(self.assets(),before)
        for _ in range(2):
            reply,_=self.worker.request('camera',camera=pose(10),write_scene=True)
            self.assertTrue(reply['ok'],reply)
            root=ET.parse(self.worker.xml).getroot()
            actor=next(a for a in root.findall('ActorMesh') if a.attrib['label']=='a')
            element=next(m for m in root.findall('StaticMesh') if m.attrib['name']==actor.find('mesh').attrib['name'])
            red=next(m for m in root.findall('UEPbrMaterial') if m.attrib['label']=='Red')
            self.assertEqual(element.find('Material').attrib['name'],red.attrib['name'])
            textures=root.findall('Texture'); self.assertEqual(len(textures),1)
            self.assertTrue((self.worker.xml.parent/textures[0].attrib['file']).is_file())
        self.assertEqual(self.assets(),before)


def benchmark(args):
    destination=Path(args.report).resolve().parent; destination.mkdir(parents=True,exist_ok=True)
    snapshot=Path(args.snapshot).resolve(); data=json.loads(snapshot.read_text(encoding='utf8'))
    count=sum(len(obj['triangles']) for obj in data['objects'])
    worker=Worker(Path(args.benchmark),os.environ['TM_VENDOR_DIR'],destination/(Path(args.report).stem+'-cache'))
    results={}
    try:
        for label in ('initial','unchanged'):
            reply,elapsed=worker.request('snapshot',snapshot_path=str(snapshot))
            if not reply.get('ok'): raise RuntimeError(reply)
            results[label]={'roundtrip_ms':elapsed,'response':reply}
        times=[]; native=[]
        for i in range(25):
            reply,elapsed=worker.request('camera',camera=pose(i*.02))
            if not reply.get('ok'): raise RuntimeError(reply)
            if i>=5:
                times.append(elapsed)
                if 'cameraPublish_ms' in reply: native.append(reply['cameraPublish_ms'])
        def stats(values):
            ordered=sorted(values)
            return {'samples':len(values),'min_ms':min(values),'median_ms':statistics.median(values),
                    'p95_ms':ordered[math.ceil(.95*len(values))-1],'max_ms':max(values)}
        import math
        results['camera_roundtrip']=stats(times)
        if native: results['camera_native_publish']=stats(native)
        # Force all object signatures to change without touching the user's file.
        for obj in data['objects']:
            if obj['vertices']: obj['vertices'][0][0]+=.0001
        changed=destination/(Path(args.report).stem+'-changed.json')
        changed.write_text(json.dumps(data,separators=(',',':')),encoding='utf8')
        reply,elapsed=worker.request('snapshot',snapshot_path=str(changed))
        if not reply.get('ok'): raise RuntimeError(reply)
        results['full_changed']={'roundtrip_ms':elapsed,'response':reply}
    finally: worker.close()
    report={'method':'Separate sender worker; serial JSON stdin/response wall clock; 5 warmup +20 camera samples; initial, identical, and all-object changed snapshots; no GUI/receiver assertions.',
            'source_snapshot':str(snapshot),'source_bytes':snapshot.stat().st_size,'objects':len(data['objects']),
            'triangles':count,'worker':str(args.benchmark),'worker_sha256':hashlib.sha256(Path(args.benchmark).read_bytes()).hexdigest(),
            'receiver_performance':'unverified','results':results}
    Path(args.report).write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='results'},indent=2))
    print(json.dumps({k:(v if 'roundtrip_ms' not in v else {'roundtrip_ms':v['roundtrip_ms']}) for k,v in results.items()},indent=2))


if __name__=='__main__':
    if '--benchmark' in __import__('sys').argv:
        parser=argparse.ArgumentParser(); parser.add_argument('--benchmark',required=True)
        parser.add_argument('--snapshot',required=True);parser.add_argument('--report',required=True)
        benchmark(parser.parse_args())
    else: unittest.main()
