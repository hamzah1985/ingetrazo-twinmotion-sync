"""Real Datasmith camera publication and asset-preservation acceptance checks.

These verify sender XML and native update acknowledgments. They do not assert
that Twinmotion has selected the imported camera or matched its viewport.
"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / 'ingetrazo_twinmotion_sync/native/DirectLinkWorker.exe'
PREFIX = 'INGETRAZO_TM '


def camera(**changes):
    value = {'position': [1.25, 2.5, 3.75], 'forward': [-2, 1, -.5],
             'up': [0, 0, 1], 'horizontal_fov': 73, 'aspect': 1.6,
             'focus_distance': 6.25, 'orthographic': False}
    value.update(changes)
    return value


def scene(view=None):
    value = {'materials': [{'id': 'white', 'name': 'White', 'color': '#FFFFFF'}],
             'objects': [{'id': 'triangle', 'name': 'Triangle', 'material_id': 'white',
                          'vertices': [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                          'triangles': [[0, 1, 2]]}]}
    if view is not None:
        value['camera'] = view
    return value


def unit(v):
    length = math.sqrt(sum(x*x for x in v))
    return [x/length for x in v]


def rotate(q, v):
    # Independent Hamilton quaternion rotation of a vector.
    x, y, z, w = q
    t = [2*(y*v[2]-z*v[1]), 2*(z*v[0]-x*v[2]), 2*(x*v[1]-y*v[0])]
    cross = [y*t[2]-z*t[1], z*t[0]-x*t[2], x*t[1]-y*t[0]]
    return [v[i]+w*t[i]+cross[i] for i in range(3)]


@unittest.skipUnless(os.environ.get('TM_VENDOR_DIR'), 'Set TM_VENDOR_DIR for native camera tests')
class NativeCameraTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.replies = queue.Queue()
        self.logs, self.errors = [], []
        self.process = subprocess.Popen([str(WORKER), os.environ['TM_VENDOR_DIR']],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, encoding='utf-8')
        def stdout():
            for line in self.process.stdout:
                if line.startswith(PREFIX):
                    self.replies.put(json.loads(line[len(PREFIX):]))
                else:
                    self.logs.append(line.rstrip())
        def stderr():
            self.errors.extend(self.process.stderr)
        self.readers = [threading.Thread(target=stdout, daemon=True),
                        threading.Thread(target=stderr, daemon=True)]
        for thread in self.readers:
            thread.start()
        reply = self.request('init', scene_name='IngeTrazo Camera Test', cache_dir=str(self.folder/'cache'))
        self.assertTrue(reply['ok'], reply)
        self.xml = Path(reply['scene_path'])
        self.snapshot_number = 0

    def tearDown(self):
        try:
            if self.process.poll() is None:
                reply = self.request('quit')
                self.assertTrue(reply['ok'], reply)
                self.process.stdin.close()
                self.process.wait(timeout=10)
            self.assertEqual(self.process.returncode, 0, ''.join(self.errors))
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=5)
            for thread in self.readers:
                thread.join(timeout=2)
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                if stream and not stream.closed:
                    stream.close()
            self.temp.cleanup()

    def request(self, op, **fields):
        self.process.stdin.write(json.dumps({'op': op, **fields}, ensure_ascii=False)+'\n')
        self.process.stdin.flush()
        try:
            return self.replies.get(timeout=15)
        except queue.Empty:
            self.fail('Native worker timeout: '+''.join(self.errors)+'\n'+'\n'.join(self.logs))

    def snapshot(self, value):
        self.snapshot_number += 1
        path = self.folder/('snapshot_%d.json' % self.snapshot_number)
        path.write_text(json.dumps(value), encoding='utf-8')
        return self.request('snapshot', snapshot_path=str(path))

    def camera_xml(self):
        views = ET.parse(self.xml).getroot().findall('Camera')
        self.assertEqual(len(views), 1)
        return views[0]

    def assert_camera(self, view, expected):
        self.assertEqual(view.attrib['name'], 'ingetrazo_active_view')
        self.assertEqual(view.attrib['label'].replace('_', ' '), 'IngeTrazo Active View')
        transform = view.find('Transform').attrib
        for key, value in zip(('tx', 'ty', 'tz'),
                              (expected['position'][0]*100, -expected['position'][1]*100, expected['position'][2]*100)):
            self.assertAlmostEqual(float(transform[key]), value, places=4)
        q = [float(transform[key]) for key in ('qx', 'qy', 'qz', 'qw')]
        forward = unit(expected['forward'])
        up = unit(expected['up'])
        dot = sum(a*b for a, b in zip(forward, up))
        up = unit([up[i]-forward[i]*dot for i in range(3)])
        for actual, source in ((rotate(q, [1, 0, 0]), forward), (rotate(q, [0, 0, 1]), up)):
            target = [source[0], -source[1], source[2]]
            for a, b in zip(actual, target):
                self.assertAlmostEqual(a, b, places=5)
        self.assertAlmostEqual(float(view.find('SensorWidth').attrib['value']), 36)
        self.assertAlmostEqual(float(view.find('SensorAspectRatio').attrib['value']), expected['aspect'], places=5)
        self.assertAlmostEqual(float(view.find('FocusDistance').attrib['value']), expected['focus_distance']*100, places=3)
        focal = float(view.find('FocalLength').attrib['value'])
        self.assertAlmostEqual(focal, 36/(2*math.tan(math.radians(expected['horizontal_fov'])/2)), places=4)
        self.assertEqual(view.find('DepthOfField').attrib['enabled'], '0')

    def mesh_state(self):
        assets = sorted(self.xml.parent.rglob('*.udsmesh'))
        self.assertTrue(assets)
        return {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in assets}

    def assert_mesh_links(self):
        for mesh in ET.parse(self.xml).getroot().findall('StaticMesh'):
            path = self.xml.parent/mesh.find('file').attrib['path']
            self.assertTrue(path.is_file(), str(path))

    def test_snapshot_exports_genuine_camera_pose_and_projection(self):
        initial = self.request('info')
        self.assertTrue(initial['camera_updates_supported'])
        self.assertFalse(initial['camera_published'])
        first = self.snapshot(scene(camera()))
        self.assertTrue(first['ok'], first)
        self.assertTrue(first['camera_published'])
        self.assertEqual(first['camera_revision'], 1)
        self.assertFalse(first['camera_sync'])
        self.assertEqual(first['receiver_camera_sync'], 'unverified')
        self.assert_camera(self.camera_xml(), camera())

    def test_camera_only_publish_keeps_mesh_assets_and_default_scene_file_unchanged(self):
        first = self.snapshot(scene(camera()))
        self.assertTrue(first['ok'], first)
        mesh_before = self.mesh_state()
        xml_before = self.xml.read_bytes(), self.xml.stat().st_mtime_ns
        next_view = camera(position=[-5, 2, 10], forward=[0, -1, -.2], up=[.1, 0, 1],
                           horizontal_fov=95, aspect=2.25, focus_distance=12)
        time.sleep(.03)
        reply = self.request('camera', camera=next_view)
        self.assertTrue(reply['ok'], reply)
        self.assertFalse(reply['scene_written'])
        self.assertEqual(reply['revision'], first['revision'])
        self.assertEqual(reply['camera_revision'], 2)
        self.assertEqual(self.mesh_state(), mesh_before)
        self.assertEqual((self.xml.read_bytes(), self.xml.stat().st_mtime_ns), xml_before)
        # Export only for independent pose/projection inspection; this still
        # must not invoke the mesh exporter or change mesh asset timestamps.
        inspect = self.request('camera', camera=next_view, write_scene=True)
        self.assertTrue(inspect['ok'], inspect)
        self.assertTrue(inspect['scene_written'])
        self.assertEqual(self.mesh_state(), mesh_before)
        self.assert_camera(self.camera_xml(), next_view)
        self.assert_mesh_links()
        preserve = self.snapshot(scene())
        self.assertTrue(preserve['ok'], preserve)
        self.assert_camera(self.camera_xml(), next_view)
        self.assertEqual(preserve['camera_revision'], 4)

    def test_invalid_camera_preserves_latest_pose_and_rejects_orthographic(self):
        good = camera()
        first = self.snapshot(scene(good))
        self.assertTrue(first['ok'], first)
        xml_before = self.xml.read_bytes()
        invalid = [camera(orthographic=True), camera(forward=[0, 0, 0]),
                   camera(forward=[0, 0, 1], up=[0, 0, 2]), camera(up=[0, 0, 0]),
                   camera(position=[float('inf'), 0, 0]), camera(horizontal_fov=180),
                   camera(horizontal_fov=0), camera(aspect=0), camera(aspect=1e-300),
                   camera(aspect=1e100), camera(focus_distance=0), camera(focus_distance=1e-300)]
        for value in invalid:
            with self.subTest(value=value):
                failed = self.request('camera', camera=value, write_scene=True)
                self.assertFalse(failed['ok'], failed)
                if value.get('orthographic'):
                    self.assertIn('Orthographic', failed['error'])
                self.assertEqual(self.xml.read_bytes(), xml_before)
                self.assertEqual(self.request('info')['camera_revision'], 1)
        self.assert_camera(self.camera_xml(), good)
        # Validation also precedes the geometry reset in a full snapshot.
        bad_snapshot = {'materials': [], 'objects': [], 'camera': camera(aspect=-1)}
        self.assertFalse(self.snapshot(bad_snapshot)['ok'])
        self.assertEqual(self.xml.read_bytes(), xml_before)
        self.assertEqual(len(ET.parse(self.xml).getroot().findall('ActorMesh')), 1)
        self.assert_camera(self.camera_xml(), good)


if __name__ == '__main__':
    unittest.main()
