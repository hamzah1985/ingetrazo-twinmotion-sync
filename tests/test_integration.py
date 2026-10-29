"""Actual host capture and Qt/native worker integration; no receiver claim."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import xml.etree.ElementTree as ET

from PySide6.QtGui import QColor, QImage, QVector3D
from PySide6.QtWidgets import QApplication, QMainWindow
from core.extensions import _import_by_path
from core.group import Group
from core.scene import Scene
from core.camera import OrbitCamera

ROOT = Path(__file__).resolve().parents[1]
package = _import_by_path('twinmotion_test',ROOT/'ingetrazo_twinmotion_sync/__init__.py')
adapter = sys.modules[package.TwinmotionController.__module__]
from importlib import import_module
capture = import_module(package.__name__+'.scene_capture')
QT = QApplication.instance() or QApplication([])

def triangle(mesh,offset=0):
    return mesh.add_face([QVector3D(offset,0,0),QVector3D(offset+1,0,0),QVector3D(offset,1,0)])

class Host:
    def __init__(self,path):
        self.window = QMainWindow()
        self.window._current_path = path
        self.scene = Scene()
        self.viewport = SimpleNamespace(scene=self.scene,camera=OrbitCamera())
        self.callbacks = []
        self.menus = []
    def on_document_changed(self,callback): self.callbacks.append(callback)
    def add_menu_action(self,*args): self.menus.append(args)
    def changed(self):
        for callback in self.callbacks: callback()

class CaptureTests(unittest.TestCase):
    def test_camera_view_transform_and_projection(self):
        import math
        camera=OrbitCamera();camera.aspect=16/9;camera.fov_deg=50
        camera.target=QVector3D(3,4,5);camera.distance=12
        camera.yaw=0.6;camera.pitch=0.4;camera.up=QVector3D(0.2,0.1,1)
        result=capture.capture_camera(camera)
        expected=camera.eye().toTuple()
        for got,want in zip(result['position'],expected):
            self.assertAlmostEqual(got,want,places=5)
        for got,want in zip(result['forward'],camera.forward().toTuple()):
            self.assertAlmostEqual(got,want,places=5)
        expected_h=math.degrees(2*math.atan(math.tan(math.radians(50)/2)*(16/9)))
        self.assertAlmostEqual(result['horizontal_fov'],expected_h)
        self.assertEqual(result['aspect'],16/9)
        camera.perspective=False
        with self.assertRaisesRegex(ValueError,'Orthographic'): capture.capture_camera(camera)
        camera.perspective=True;camera.two_point=True
        with self.assertRaisesRegex(ValueError,'Two-point'): capture.capture_camera(camera)

    def test_white_nested_paint_and_texture_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp)/'House.igz'; model.touch()
            folder = capture.prepare_texture_folder(model)
            # Windows runners can expose TEMP through an 8.3 alias while
            # prepare_texture_folder returns the canonical long path.
            self.assertEqual(folder,(model.parent/'House_twinmotion_sync').resolve())
            scene = Scene(); triangle(scene.loose_mesh)
            parent,child,leaf = Group(name='parent'),Group(name='child'),Group(name='leaf')
            parent.material = {'color':(1,0,0)}; child.material = {'color':(0,0,1)}
            triangle(leaf.mesh); child.children.append(leaf);parent.children.append(child);scene.groups.append(parent)
            snapshot = capture.capture_scene(scene,model,folder)
            self.assertEqual({m['color'] for m in snapshot['materials']},{'#FFFFFF','#0000FF'})
            image = QImage(2,2,QImage.Format_RGB32);image.fill(QColor('green'))
            original = model.parent/'original.png';self.assertTrue(image.save(str(original)))
            leaf.mesh.faces[0].attrs['texture'] = {'path':str(original),'sw':1,'sh':1}
            first = capture.capture_scene(scene,model,folder)
            original.unlink()
            recovered = capture.capture_scene(scene,model,folder)
            self.assertEqual(first,recovered)
            maps = [Path(m['diffuse_map']) for m in recovered['materials'] if m.get('diffuse_map')]
            self.assertEqual(len(maps),1);self.assertTrue(maps[0].is_file())
            self.assertEqual(maps[0].parent,folder)

    def test_unsaved_cancel_and_missing_runtime_leave_sync_off(self):
        host = Host(None); controller = adapter.TwinmotionController(host)
        try:
            controller.connect()
            self.assertFalse(controller.enabled)
            with patch.dict(os.environ,{'INGETRAZO_TM_RUNTIME':'Z:/missing/runtime.json'}):
                with self.assertRaisesRegex(ValueError,'not configured'): adapter.find_runtime()
            self.assertEqual(controller.toolbar.iconSize().width(),20)
            self.assertFalse(controller.connect_action.icon().isNull())
        finally:
            controller.shutdown();host.window.close()

@unittest.skipUnless(os.environ.get('TM_VENDOR_DIR'),'Set TM_VENDOR_DIR to run the native integration tests')
class NativeControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.root = Path(self.temp.name)
        model = self.root/'Hóuse 中文.igz';model.touch()
        config = self.root/'runtime.json'
        config.write_text(json.dumps({'worker_exe':str(ROOT/'ingetrazo_twinmotion_sync/native/DirectLinkWorker.exe'),
                                     'vendor_dir':os.environ['TM_VENDOR_DIR']}),encoding='utf8')
        self.env = patch.dict(os.environ,{'INGETRAZO_TM_RUNTIME':str(config)});self.env.start()
        self.host = Host(model);triangle(self.host.scene.loose_mesh)
        self.controller = adapter.TwinmotionController(self.host)

    def tearDown(self):
        self.controller.shutdown()
        self.assertFalse(self.controller.worker.running)
        self.host.window.close();self.env.stop();self.temp.cleanup()

    def wait_for(self,predicate,seconds=45):
        until = time.monotonic()+seconds
        while not predicate():
            QT.processEvents()
            if time.monotonic()>until:
                self.fail(self.controller.status_text+'\n'+self.controller.errors)
            time.sleep(0.01)

    def test_latest_queued_change_deletion_and_source_identity(self):
        c = self.controller;c.connect()
        self.wait_for(lambda:c.busy)
        triangle(self.host.scene.loose_mesh,3);self.host.changed();c.capture()
        self.assertTrue(c.dirty)
        self.wait_for(lambda:c.published>=2 and not c.busy)
        self.assertEqual(c.last_result['triangles'],2)
        self.assertEqual(c.last_result['receiver_connection'],'unverified')
        self.assertFalse(c.last_result['camera_sync'])
        xmlpath = Path(c.last_result['scene_path']);xml = ET.parse(xmlpath).getroot()
        self.assertEqual(xml.findtext('Host'),'IngeTrazo')
        self.assertIn('Hóuse 中文',c.last_result['scene_name'])
        material = xml.find('UEPbrMaterial/Expressions/Color').attrib['constant']
        self.assertIn('R=1.000000,G=1.000000,B=1.000000',material)
        name = xml.find('ActorMesh').attrib['name'];c.sync_now()
        self.wait_for(lambda:c.published>=3 and not c.busy)
        self.assertEqual(ET.parse(xmlpath).getroot().find('ActorMesh').attrib['name'],name)
        self.host.scene.loose_mesh.clear();self.host.changed()
        self.wait_for(lambda:c.published>=4 and not c.busy)
        self.assertEqual(c.last_result['objects'],0)
        self.assertFalse(ET.parse(xmlpath).getroot().findall('ActorMesh'))
        report = json.loads((c.cache/'ingetrazo-twinmotion-diagnostics.json').read_text())
        self.assertEqual(report['published_snapshots'],4)
        self.assertEqual(report['receiver_connection'],'unverified')

    def test_missing_texture_warning_is_persisted(self):
        face = self.host.scene.loose_mesh.faces[0]
        face.attrs['texture'] = {'path':str(self.root/'missing.png')}
        self.controller.connect();self.wait_for(lambda:self.controller.published>=1)
        report = json.loads((self.controller.cache/'ingetrazo-twinmotion-diagnostics.json').read_text())
        self.assertEqual(len(report['capture_warnings']),1)
        self.assertIn('warning',report['status'])
        self.assertTrue(report['worker']['published'])

    def test_camera_moves_publish_without_recapturing_geometry(self):
        c=self.controller;c.connect();self.wait_for(lambda:c.published>=1 and not c.busy)
        xmlpath=Path(c.last_result['scene_path'])
        xml=ET.parse(xmlpath).getroot()
        self.assertIsNotNone(xml.find('Camera'))
        files=[xmlpath.parent/m.find('file').attrib['path'] for m in xml.findall('StaticMesh')]
        before=[(p.stat().st_mtime_ns,p.read_bytes()) for p in files]
        self.host.viewport.camera.yaw+=0.1
        with patch.object(adapter,'capture_scene',side_effect=AssertionError('camera must not recapture geometry')):
            c.poll_camera();self.assertTrue(c.busy)
            self.host.viewport.camera.yaw+=0.2
            self.host.viewport.camera.target+=QVector3D(2,3,1)
            self.host.viewport.camera.distance*=0.75
            self.host.viewport.camera.fov_deg=60
            self.host.viewport.camera.aspect=2
            c.poll_camera()
            self.wait_for(lambda:c.camera_updates>=2 and not c.busy)
        self.assertEqual(c.published,1)
        self.assertEqual(before,[(p.stat().st_mtime_ns,p.read_bytes()) for p in files])
        self.assertEqual(c.last_camera_revision,c.camera_signature(c.current_camera()))
        self.assertEqual(c.last_result['receiver_camera_sync'],'unverified')
        updates=c.camera_updates
        c.camera_action.setChecked(False);self.host.viewport.camera.yaw+=1;c.poll_camera()
        self.assertEqual(c.camera_updates,updates)
        c.camera_action.setChecked(True);c.poll_camera()
        self.wait_for(lambda:c.camera_updates>updates and not c.busy)
        self.host.viewport.camera.perspective=False;c.poll_camera()
        self.assertIn('Orthographic',c.camera_warning)
        self.assertFalse(c.busy)

    def test_save_as_disconnects_before_publishing_other_model(self):
        c=self.controller;c.connect();self.wait_for(lambda:c.published>=1)
        old=c.document;self.host.window._current_path=self.root/'Other.igz'
        self.assertFalse(c.check_location());self.assertFalse(c.enabled)
        self.wait_for(lambda:not c.worker.running)
        self.assertIn('location changed',c.status_text)
        self.assertEqual(c.document,old)

if __name__=='__main__': unittest.main()
