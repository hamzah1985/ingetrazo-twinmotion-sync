"""Cadence/backpressure, diagnostics and the actual compact geometry writer."""
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import time

from PySide6.QtCore import Qt,QObject,Signal
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QMainWindow,QToolBar
from views.extension_api import ExtensionApp
from core.scene import Scene
from test_integration import QT,Host,adapter,triangle
from importlib import import_module
transport=import_module(adapter.__package__+'.scene_transport')
capture=import_module(adapter.__package__+'.scene_capture')

class TransportTests(unittest.TestCase):
    def test_binary_pair_roundtrip_and_stable_revision(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);host=Host(folder/'Model.igz');triangle(host.scene.loose_mesh)
            scene=capture.capture_scene(host.scene)
            first=transport.prepare_scene(scene,folder)
            second=transport.prepare_scene(scene,folder)
            try:
                self.assertEqual(first.revision,second.revision)
                first.commit(folder/'scene.json','geometry-a.bin')
                data=json.loads((folder/'scene.json').read_text())
                self.assertNotIn('vertices',data['objects'][0])
                raw=(folder/'geometry-a.bin').read_bytes()
                self.assertEqual(raw[:16],transport.HEADER)
                info=data['objects'][0]['geometry'];offset=info['offset']
                self.assertEqual(struct.unpack_from('<9f',raw,offset),tuple(v for p in scene['objects'][0]['vertices'] for v in p))
                # Writing another slot cannot change the JSON currently on disk
                # until commit. A rejected commit leaves the prior pair valid.
                before=(folder/'scene.json').read_bytes()
                with self.assertRaises(ValueError): second.commit(folder/'scene.json','../escape.bin')
                self.assertEqual((folder/'scene.json').read_bytes(),before)
                second.commit(folder/'scene.json','geometry-b.bin')
                self.assertEqual((folder/'geometry-a.bin').read_bytes(),raw)
            finally:
                first.close();second.close();host.window.close()
            self.assertFalse(list(folder.glob('*.tmp')))

    def test_invalid_arrays_leave_no_temporary_files(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);host=Host(None);triangle(host.scene.loose_mesh)
            scene=capture.capture_scene(host.scene)
            scene['objects'][0]['triangles']=[[0,1,99]]
            with self.assertRaises(ValueError): transport.prepare_scene(scene,folder)
            self.assertFalse(list(folder.iterdir()))
            scene['objects'][0]['triangles']=[[0,1,2]]
            scene['objects'][0]['vertices'][0][0]=float('nan')
            with self.assertRaises(ValueError): transport.prepare_scene(scene,folder)
            self.assertFalse(list(folder.iterdir()));host.window.close()

class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.model=self.folder/'Model.igz';self.model.touch()
        self.host=Host(self.model);self.c=adapter.TwinmotionController(self.host)
        self.c.enabled=self.c.ready=True;self.c.published=1
        self.c.document=self.model.resolve();self.c.document_input=str(self.model)
        self.c.cache=self.folder
        self.requests=[]
        def send(request):
            if request['op']=='camera': self.c.camera_last_send=time.perf_counter()
            self.requests.append(request);return True
        self.c.send=send
    def tearDown(self):
        self.c.shutdown();self.host.window.close();self.temp.cleanup()

    def test_precise_cadence_and_no_filesystem_resolution_per_frame(self):
        self.assertEqual(self.c.camera_timer.timerType(),Qt.PreciseTimer)
        self.assertEqual(self.c.camera_timer.interval(),33)
        self.c.set_camera_fps(60);self.assertEqual(self.c.camera_timer.interval(),17)
        with patch.object(Path,'resolve',side_effect=AssertionError('camera frame must not resolve files')):
            self.c.poll_camera()
        self.assertEqual(len(self.requests),1)

    def test_one_inflight_latest_pose_and_no_starvation_during_debounce(self):
        self.c.schedule()
        self.assertTrue(self.c.dirty)
        self.c.poll_camera()
        self.assertEqual(len(self.requests),1)
        self.host.viewport.camera.yaw+=.5
        self.c.poll_camera();self.assertEqual(len(self.requests),1)
        self.c.handle_reply({'op':'camera','ok':True})
        self.c.camera_last_send=0
        self.c.poll_camera();self.assertEqual(len(self.requests),2)
        self.assertEqual(self.requests[-1]['camera'],capture.capture_camera(self.host.viewport.camera))

    def test_camera_diagnostics_are_coalesced_and_late_replies_ignored(self):
        for i in range(25):
            self.c.busy=True;self.c.inflight_camera=('pose',i)
            self.c.camera_last_send=time.perf_counter()
            self.c.handle_reply({'op':'camera','ok':True})
        self.assertEqual(self.c.diagnostics_writes,0)
        self.assertTrue(self.c.diagnostics_timer.isActive())
        self.c.write_diagnostics()
        record=json.loads((self.folder/'ingetrazo-twinmotion-diagnostics.json').read_text())
        self.assertEqual(record['camera_updates_sent'],25)
        self.assertEqual(record['diagnostics_writes'],1)
        self.c.stop();self.c.handle_reply({'op':'init','ok':True})
        self.assertFalse(self.c.ready)

    def test_final_geometry_edit_is_dispatched_immediately_after_camera_ack(self):
        self.c.poll_camera();self.c.capture()
        self.assertTrue(self.c.geometry_due)
        self.c.handle_reply({'op':'camera','ok':True})
        calls=[]
        with patch.object(self.c,'capture',side_effect=lambda:calls.append(True)):
            self.c.dispatch_pending()
        self.assertEqual(calls,[True])

    def test_early_camera_tick_schedules_remaining_cadence(self):
        self.c.last_camera_revision=None
        self.c.camera_last_send=time.perf_counter()
        self.c.poll_camera()
        self.assertEqual(self.requests,[])
        self.assertTrue(self.c.dispatch_timer.isActive())
        self.assertLessEqual(self.c.dispatch_timer.remainingTime(),33)
        self.assertEqual(self.c.dispatch_timer.timerType(),Qt.PreciseTimer)

    def test_tiny_numeric_noise_does_not_stream_idle_camera(self):
        view=capture.capture_camera(self.host.viewport.camera)
        key=self.c.camera_signature(view)
        view['forward'][0]+=1e-10;view['position'][0]+=1e-10
        self.assertEqual(self.c.camera_signature(view),key)

class UpgradeTests(unittest.TestCase):
    def test_live_upgrade_preserves_model_submenu_and_single_toolbar(self):
        class Viewport(QObject):
            sceneVersionChanged=Signal(int)
        window=QMainWindow();window.viewport=Viewport(window)
        window.viewport.scene=Scene()
        triangle(window.viewport.scene.loose_mesh)
        window._current_path=Path('untitled2.igz')
        window._ext_menu=window.menuBar().addMenu('Extensions')
        app=ExtensionApp(window,'ingetrazo_twinmotion_sync')
        before=(id(window.viewport.scene),window.viewport.scene.version,
                len(window.viewport.scene.loose_mesh.faces),window._current_path)
        old=adapter.TwinmotionController(app);old.prototype_version='0.2.0'
        window._twinmotion_sync_prototype=old
        menu=window._ext_menu.addMenu('IngeTrazo Twinmotion Sync')
        owners=window._ext_action_owner
        for action in list(window._ext_menu.actions()):
            if owners.get(action)=='ingetrazo_twinmotion_sync':
                window._ext_menu.removeAction(action);menu.addAction(action)
        owners[menu.menuAction()]='ingetrazo_twinmotion_sync'
        other=window._ext_menu.addAction('Unrelated extension')
        old.enabled=True;old.timer.start();old.camera_timer.start()
        old.camera_action.setChecked(False)
        old.set_camera_fps(60)
        try:
            with patch.object(adapter.TwinmotionController,'connect') as resume:
                adapter.setup(app);QT.processEvents()
                resume.assert_called_once()
            current=window._twinmotion_sync_prototype
            self.assertIsNot(current,old)
            self.assertFalse(old.enabled)
            self.assertFalse(old.camera_timer.isActive())
            self.assertFalse(old.timer.isActive())
            self.assertFalse(current.camera_action.isChecked())
            self.assertEqual(current.camera_fps,60)
            self.assertEqual(window.findChildren(QToolBar,'ingetrazo_twinmotion_sync_toolbar'),[current.toolbar])
            self.assertIn(menu.menuAction(),window._ext_menu.actions())
            self.assertIn(other,window._ext_menu.actions())
            self.assertEqual(len(menu.actions()),4)
            self.assertEqual(len({a.text() for a in menu.actions()}),4)
            adapter.setup(app)
            self.assertIs(window._twinmotion_sync_prototype,current)
            self.assertEqual(len(menu.actions()),4)
            self.assertEqual(before,(id(window.viewport.scene),window.viewport.scene.version,
                                    len(window.viewport.scene.loose_mesh.faces),window._current_path))
            # A stale document subscription remains harmless; only the new
            # controller responds to the host signal after the upgrade.
            current.enabled=True;window.viewport.sceneVersionChanged.emit(1)
            self.assertTrue(current.timer.isActive())
            self.assertFalse(old.timer.isActive())
        finally:
            window._twinmotion_sync_prototype.shutdown();window.close()

if __name__=='__main__': unittest.main()
