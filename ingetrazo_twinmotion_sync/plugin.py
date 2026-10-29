# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI-thread scene capture and a separate Datasmith Direct Link worker."""
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
import uuid
from collections import deque

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QToolBar
from .scene_capture import capture_camera, capture_scene, prepare_texture_folder
from .worker_process import WorkerProcess
from .scene_transport import prepare_scene

ROOT = Path(__file__).resolve().parent
PREFIX = 'INGETRAZO_TM '
PROTOTYPE_VERSION = '0.3.0'

def find_runtime():
    configuration = Path(os.environ.get('INGETRAZO_TM_RUNTIME',
        str(Path(os.environ.get('LOCALAPPDATA', Path.home()))/'IngeTrazo'/'twinmotion_sync'/'runtime.json')))
    if not configuration.is_file():
        raise ValueError('Twinmotion Sync runtime is not configured. Run the local prototype installer.')
    data = json.loads(configuration.read_text(encoding='utf-8-sig'))
    worker = Path(data['worker_exe']).resolve()
    vendor = Path(data['vendor_dir']).resolve()
    if not worker.is_file() or worker.suffix.lower() != '.exe':
        raise ValueError('The configured Direct Link worker is missing.')
    for name in ('DatasmithFacadeCSharp.dll', 'DatasmithRhino6.rhp', 'tbbmalloc.dll'):
        if not (vendor/name).is_file():
            raise ValueError('The separately obtained Datasmith runtime is missing ' + name)
    return worker, vendor

def write_snapshot(path, scene):
    data = json.dumps(scene, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf8')
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.tmp', delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return hashlib.sha256(data).hexdigest()

class TwinmotionController:
    def __init__(self, app):
        self.app = app
        self.prototype_version = PROTOTYPE_VERSION
        self.worker = WorkerProcess(app.window)
        self.worker.output.connect(self.read_reply,Qt.QueuedConnection)
        self.worker.errors.connect(self.read_errors,Qt.QueuedConnection)
        self.worker.exited.connect(self.finished,Qt.QueuedConnection)
        self.worker.failed.connect(self.process_error,Qt.QueuedConnection)
        self.timer = QTimer(app.window)
        self.timer.setSingleShot(True)
        self.timer.setInterval(350)
        self.timer.timeout.connect(self.capture)
        self.location_timer = QTimer(app.window)
        self.location_timer.setInterval(500)
        self.location_timer.timeout.connect(self.check_location)
        self.camera_timer = QTimer(app.window)
        self.camera_timer.setTimerType(Qt.PreciseTimer)
        self.camera_fps = 30
        self.camera_timer.setInterval(33)
        self.camera_timer.timeout.connect(self.poll_camera)
        self.dispatch_timer = QTimer(app.window)
        self.dispatch_timer.setSingleShot(True)
        self.dispatch_timer.setTimerType(Qt.PreciseTimer)
        self.dispatch_timer.timeout.connect(self.dispatch_pending)
        self.diagnostics_timer = QTimer(app.window)
        self.diagnostics_timer.setSingleShot(True)
        self.diagnostics_timer.setInterval(1000)
        self.diagnostics_timer.timeout.connect(self.write_diagnostics)
        self.timeout = QTimer(app.window)
        self.timeout.setSingleShot(True)
        self.timeout.setInterval(180000)
        self.timeout.timeout.connect(self.response_timeout)
        self.kill_timer = QTimer(app.window)
        self.kill_timer.setSingleShot(True)
        self.kill_timer.setInterval(1500)
        self.kill_timer.timeout.connect(self.kill_worker)
        self.enabled = self.ready = self.busy = self.stopping = False
        self.dirty = False
        self.errors = ''
        self.last_revision = None
        self.last_result = None
        self.capture_warnings = []
        self.last_camera_revision = None
        self.camera_updates = 0
        self.camera_warning = ''
        self.camera_last_send = 0.0
        self.camera_roundtrips = deque(maxlen=120)
        self.diagnostics_writes = 0
        self.geometry_due = False
        self.geometry_deadline = 0.0
        self.native_buffers = False
        self.last_scene_result = None
        self.geometry_capture_ms = self.geometry_encode_ms = 0.0
        self.published = 0
        self.status_text = 'Disconnected'
        app.on_document_changed(self.schedule)
        self._toolbar()
        instance = QApplication.instance()
        if instance:
            instance.aboutToQuit.connect(self.shutdown)

    def _toolbar(self):
        self.toolbar = QToolBar('IngeTrazo → Twinmotion Sync', self.app.window)
        self.toolbar.setObjectName('ingetrazo_twinmotion_sync_toolbar')
        self.toolbar.setIconSize(QSize(20,20))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.connect_action = QAction(QIcon(str(ROOT/'icons/connect.svg')), 'Connect Twinmotion', self.app.window)
        self.sync_action = QAction(QIcon(str(ROOT/'icons/sync.svg')), 'Sync Now', self.app.window)
        self.camera_action = QAction(QIcon(str(ROOT/'icons/camera.svg')), 'Publish Camera', self.app.window)
        self.camera_action.setCheckable(True)
        self.camera_action.setChecked(True)
        self.camera_action.toggled.connect(self.camera_toggled)
        self.disconnect_action = QAction(QIcon(str(ROOT/'icons/disconnect.svg')), 'Disconnect Twinmotion', self.app.window)
        for action, callback in ((self.connect_action,self.connect), (self.sync_action,self.sync_now),
                                 (self.disconnect_action,self.stop)):
            action.triggered.connect(lambda _checked=False, callback=callback: callback())
            self.toolbar.addAction(action)
        self.toolbar.insertAction(self.disconnect_action,self.camera_action)
        self.app.window.addToolBar(Qt.TopToolBarArea,self.toolbar)
        self.app.add_menu_action('Twinmotion Sync: Show Toolbar',self.toolbar.show)
        self.app.add_menu_action('Twinmotion Sync: Connect',self.connect)
        self.app.add_menu_action('Twinmotion Sync: Disconnect',self.stop)
        self.smooth_camera_action = self.app.add_menu_action('Twinmotion Sync: Faster Camera Sampling (60 Hz, Experimental)',self.toggle_camera_speed)
        if self.smooth_camera_action is not None:
            self.smooth_camera_action.setCheckable(True)
            self.smooth_camera_action.setStatusTip('Increases source sampling. Twinmotion may apply Direct Link camera changes more slowly; 60 Hz does not guarantee smoother playback.')
        self.actions()

    def actions(self):
        self.connect_action.setEnabled(not self.enabled and not self.stopping)
        self.sync_action.setEnabled(self.enabled and self.ready)
        self.disconnect_action.setEnabled(self.enabled)
        self.connect_action.setToolTip('Twinmotion Sync: '+self.status_text)
        self.sync_action.setToolTip('Publish the current model through Datasmith Direct Link')
        self.disconnect_action.setToolTip('Stop the source and leave Twinmotion open')
        self.camera_action.setToolTip(self.camera_warning or 'Publish IngeTrazo camera movements. In Twinmotion, enable DCC Camera Sync and select IngeTrazo Active View.')

    def status(self,text):
        self.status_text = text
        print('[IngeTrazo Twinmotion prototype] '+text)
        self.app.window.statusBar().showMessage(text,15000)
        self.actions()
        self.write_diagnostics()

    def write_diagnostics(self):
        self.diagnostics_timer.stop()
        if not hasattr(self,'cache'):
            return
        timings=sorted(self.camera_roundtrips)
        report = {'prototype_version':'0.3.0', 'status':self.status_text,
                  'source_running':self.enabled and self.ready and self.worker.running,
                  'receiver_connection':'unverified', 'camera_sync':False,
                  'published_snapshots':self.published,
                  'camera_publication_enabled':self.camera_action.isChecked(),
                  'camera_updates_sent':self.camera_updates,
                  'camera_warning':self.camera_warning,
                  'receiver_camera_sync':'unverified',
                  'capture_warnings':self.capture_warnings,
                  'worker':self.last_result, 'worker_scene':self.last_scene_result,
                  'worker_stderr':self.errors,
                  'diagnostics_writes':self.diagnostics_writes+1,
                  'camera_target_fps':self.camera_fps,
                  'camera_interval_ms':self.camera_timer.interval(),
                  'camera_roundtrip_samples':len(timings),
                  'camera_roundtrip_p50_ms':round(timings[(len(timings)-1)//2],3) if timings else None,
                  'camera_roundtrip_p95_ms':round(timings[int((len(timings)-1)*.95)],3) if timings else None,
                  'geometry_capture_ms':round(self.geometry_capture_ms,3),
                  'geometry_encode_ms':round(self.geometry_encode_ms,3),
                  'binary_geometry':self.native_buffers}
        try:
            write_snapshot(self.cache/'ingetrazo-twinmotion-diagnostics.json',report)
            self.diagnostics_writes += 1
        except OSError as error:
            print('[IngeTrazo Twinmotion prototype] Cannot save diagnostics: '+str(error))

    def schedule_diagnostics(self):
        if not self.diagnostics_timer.isActive():
            self.diagnostics_timer.start()

    def set_camera_fps(self,fps):
        if fps not in (30,60):
            raise ValueError('Camera rate must be 30 or 60 Hz.')
        self.camera_fps=fps
        self.camera_timer.setInterval(round(1000/fps))
        if self.smooth_camera_action is not None:
            self.smooth_camera_action.setChecked(fps==60)
        self.schedule_diagnostics()

    def toggle_camera_speed(self):
        fps=60 if self.smooth_camera_action is not None and self.smooth_camera_action.isChecked() else 30
        self.set_camera_fps(fps)

    def dispatch_pending(self):
        if not self.enabled or self.busy:
            return
        if self.geometry_due:
            self.capture()
        else:
            self.poll_camera()

    def connect(self):
        if self.enabled or self.stopping:
            return
        try:
            current = getattr(self.app.window,'_current_path',None)
            if not current or not Path(current).is_file() or Path(current).suffix.lower() != '.igz':
                save = getattr(self.app.window,'_on_save_as',None)
                if callable(save):
                    save()
                current = getattr(self.app.window,'_current_path',None)
            if not current:
                self.status('Save cancelled. Twinmotion Sync remains off.')
                return
            self.document = Path(current).resolve()
            self.document_input = str(current)
            self.cache = prepare_texture_folder(self.document)
            worker, vendor = find_runtime()
        except (OSError, ValueError, KeyError) as error:
            self.status(str(error))
            return
        self.enabled = True
        self.ready = self.busy = False
        self.last_revision = None
        self.last_result = None
        self.capture_warnings = []
        self.published = 0
        self.camera_updates = 0
        self.last_camera_revision = None
        self.camera_warning = ''
        self.camera_last_send = 0.0
        self.camera_roundtrips.clear()
        self.geometry_due = False
        self.geometry_deadline = 0.0
        self.native_buffers = False
        self.last_scene_result = None
        self.diagnostics_writes = 0
        self.connection_token = uuid.uuid4().hex[:12]
        self.buffer_slot = 0
        self.errors = ''
        try:
            self.worker.start(worker,vendor)
            self.initialize_worker()
        except OSError as error:
            self.stop()
            self.status('Cannot start Direct Link worker: '+str(error))
            return
        self.timeout.start()
        self.location_timer.start()
        self.camera_timer.start()
        self.status('Starting Datasmith Direct Link source…')

    def initialize_worker(self):
        self.send({'op':'init','scene_name':'IngeTrazo — '+self.document.stem,
                   'cache_dir':str(self.cache)})

    def send(self,request):
        try:
            if request['op']=='camera':
                self.camera_last_send = time.perf_counter()
            self.worker.send(request)
        except (OSError,ValueError) as error:
            self.stop()
            self.status('The Direct Link worker could not accept an update: '+str(error))
            return False
        self.timeout.start()
        return True

    def check_location(self):
        if not self.enabled:
            return False
        current = getattr(self.app.window,'_current_path',None)
        # Save As / New / Open changes the raw path. Avoid resolving a OneDrive
        # path through the filesystem for every camera frame.
        if not current or str(current) != self.document_input:
            self.stop()
            self.status('Model location changed. Reconnect Twinmotion Sync.')
            return False
        return True

    def schedule(self):
        if self.enabled:
            now=time.perf_counter()
            if not self.dirty:
                self.geometry_deadline=now+.75
            self.dirty = True
            self.timer.start(max(0,min(350,round((self.geometry_deadline-now)*1000))))

    def sync_now(self):
        if not self.enabled:
            self.connect()
            return
        self.last_revision = None
        self.dirty = True
        self.capture()

    @staticmethod
    def camera_signature(camera):
        if camera is None:
            return None
        # Suppress float noise below one micrometre / a tiny fraction of a
        # screen pixel. The actual transmitted pose retains full precision.
        return tuple(round(v,6) for v in camera['position']) + tuple(
            round(v,7) for key in ('forward','up') for v in camera[key]) + (
            round(camera['horizontal_fov'],5),round(camera['aspect'],6),round(camera['focus_distance'],6))

    def current_camera(self):
        if not self.camera_action.isChecked():
            return None
        try:
            viewport = getattr(self.app,'viewport',None)
            camera = getattr(viewport,'camera',None)
            if camera is None:
                raise ValueError('The active viewport camera is unavailable.')
            result = capture_camera(camera)
            warning = ''
        except (ValueError,AttributeError) as error:
            warning = str(error)
            result = None
        if self.camera_warning != warning:
            self.camera_warning = warning
            self.camera_action.setToolTip(warning or 'Publish IngeTrazo camera movements; choose IngeTrazo Active View in Twinmotion DCC Camera Sync.')
            self.write_diagnostics()
        return result

    def camera_toggled(self,_enabled):
        self.last_camera_revision = None
        if self.enabled:
            self.write_diagnostics()

    def poll_camera(self):
        if not (self.enabled and self.ready and self.published and not self.busy):
            return
        if self.geometry_due:
            self.dispatch_timer.start(0)
            return
        if not self.check_location():
            return
        camera = self.current_camera()
        signature = self.camera_signature(camera)
        if camera is None or signature == self.last_camera_revision:
            return
        remaining=self.camera_timer.interval()/1000-(time.perf_counter()-self.camera_last_send)
        if remaining>0:
            # A worker acknowledgement can arrive between sampling ticks. Keep
            # the latest pose, and wake at the remaining cadence deadline so
            # timer jitter cannot turn one skipped tick into a double interval.
            delay=max(1,math.ceil(remaining*1000))
            if not self.dispatch_timer.isActive() or self.dispatch_timer.remainingTime()>delay:
                self.dispatch_timer.start(delay)
            return
        self.inflight_camera = signature
        self.busy = True
        if not self.send({'op':'camera','camera':camera}):
            self.busy = False

    def capture(self):
        if not self.enabled or not self.ready or not self.check_location():
            return
        if self.busy:
            self.dirty = True
            self.geometry_due = True
            return
        self.geometry_due = False
        prepared = None
        try:
            started=time.perf_counter()
            scene = capture_scene(self.app.scene,self.document,self.cache)
            self.geometry_capture_ms=(time.perf_counter()-started)*1000
            self.capture_warnings = scene.get('warnings',[])
            scene['uv_flip_v'] = True
            encoded=time.perf_counter()
            if self.native_buffers:
                prepared=prepare_scene(scene,self.cache)
                revision=prepared.revision
            else:
                revision = hashlib.sha256(json.dumps(scene,sort_keys=True,allow_nan=False).encode('utf8')).hexdigest()
            self.dirty = False
            if revision == self.last_revision:
                self.dispatch_timer.start(0)
                return
            camera = self.current_camera()
            if camera is not None:
                scene['camera'] = camera
            path = self.cache/'ingetrazo-scene.json'
            if prepared is not None:
                # Camera is separate from the geometry fingerprint. Alternate
                # buffers only after a complete previous request was consumed.
                buffer_name='ingetrazo-geometry-%s-%d.bin' % (self.connection_token,self.buffer_slot)
                prepared.commit(path,buffer_name,camera)
                self.buffer_slot=1-self.buffer_slot
            else:
                write_snapshot(path,scene)
            self.geometry_encode_ms=(time.perf_counter()-encoded)*1000
            self.inflight = revision
            self.inflight_camera = self.camera_signature(camera)
            self.busy = True
            if not self.send({'op':'snapshot','snapshot_path':str(path)}):
                self.busy = False
        except Exception as error:
            self.busy = False
            self.dirty = False
            self.status('Scene capture failed: '+str(error))
        finally:
            if prepared is not None:
                prepared.close()

    def read_reply(self,line):
        if not line.startswith(PREFIX):
            return
        try:
            result = json.loads(line[len(PREFIX):])
        except ValueError:
            self.stop()
            self.status('The Direct Link worker returned an invalid reply.')
            return
        self.handle_reply(result)

    def handle_reply(self,result):
        if not self.enabled:
            return
        self.last_result = result
        self.timeout.stop()
        if not result.get('ok'):
            self.stop()
            self.status('Direct Link failed: '+str(result.get('error','unknown error')))
            return
        if result.get('op') == 'init':
            self.native_buffers = bool(result.get('snapshot_buffers_supported'))
            self.ready = True
            self.status('Source advertised. Select IngeTrazo in Twinmotion Direct Link.')
            QTimer.singleShot(0,self.capture)
        elif result.get('op') == 'snapshot':
            self.last_scene_result = result
            self.last_revision = self.inflight
            self.last_camera_revision = self.inflight_camera
            self.busy = False
            self.published += 1
            warnings = self.capture_warnings + (result.get('warnings') or [])
            self.status('Published to Direct Link; receiver import is not verified.' if not warnings else
                        'Published with %d warning(s). See diagnostics.' % len(warnings))
            self.dispatch_timer.start(0)
        elif result.get('op') == 'camera':
            self.last_camera_revision = self.inflight_camera
            self.camera_updates += 1
            self.camera_roundtrips.append((time.perf_counter()-self.camera_last_send)*1000)
            self.busy = False
            self.schedule_diagnostics()
            self.dispatch_timer.start(0)

    def read_errors(self,text):
        self.errors = (self.errors + text)[-12000:]

    def response_timeout(self):
        self.stop()
        self.status('Direct Link worker timed out. Reconnect when ready.')

    def process_error(self,detail):
        if not self.stopping:
            self.stop()
            self.status('Direct Link worker stopped: '+detail)

    def finished(self,*_args):
        was_enabled = self.enabled
        self.enabled = self.ready = self.busy = self.stopping = False
        self.kill_timer.stop()
        self.timer.stop()
        self.timeout.stop()
        self.location_timer.stop()
        self.camera_timer.stop()
        self.dispatch_timer.stop()
        self.diagnostics_timer.stop()
        if was_enabled:
            self.status('Direct Link worker exited. Reconnect to resume.')
        else:
            self.actions()

    def stop(self,update_ui=True):
        self.enabled = self.ready = self.busy = False
        self.timer.stop()
        self.timeout.stop()
        self.location_timer.stop()
        self.camera_timer.stop()
        self.dispatch_timer.stop()
        self.diagnostics_timer.stop()
        if self.worker.running:
            self.stopping = True
            try:
                self.worker.send({'op':'quit'})
            except (OSError,ValueError):
                self.worker.kill()
            self.kill_timer.start()
        if update_ui:
            self.status('Disconnected')

    def kill_worker(self):
        self.worker.kill()

    def shutdown(self):
        self.stop(update_ui=False)
        if not self.worker.wait(1.5):
            self.worker.kill()
            self.worker.wait(1)
        self.status_text = 'Disconnected'
        self.write_diagnostics()

def setup(app):
    existing = getattr(app.window,'_twinmotion_sync_prototype',None)
    if existing and getattr(existing,'prototype_version',None)==PROTOTYPE_VERSION:
        existing.toolbar.show()
        return
    resume=False
    old_menu=None
    if existing:
        # The host extension API has no unsubscribe handle for document
        # callbacks. Retire the old controller disabled; its stopped timers and
        # callbacks remain harmless until app shutdown. Never close the model.
        resume=existing.enabled
        existing.shutdown()
        owners=getattr(app.window,'_ext_action_owner',{})
        actions=[action for action,owner in list(owners.items())
                 if owner=='ingetrazo_twinmotion_sync' and action.menu() is None]
        for menu in app.window.findChildren(QMenu):
            owned=[action for action in actions if action in menu.actions()]
            if owned and old_menu is None:
                old_menu=menu
            for action in owned:
                menu.removeAction(action)
        for action in actions:
            owners.pop(action,None)
        app.window.removeToolBar(existing.toolbar)
        existing.toolbar.hide()
        existing.toolbar.setParent(None)
        app.window.__dict__.setdefault('_twinmotion_sync_retired',[]).append(existing)
    controller=TwinmotionController(app)
    if existing:
        controller.camera_action.setChecked(existing.camera_action.isChecked())
        controller.set_camera_fps(getattr(existing,'camera_fps',30))
    app.window.__dict__['_twinmotion_sync_prototype']=controller
    if old_menu is not None:
        owners=getattr(app.window,'_ext_action_owner',{})
        for action,owner in list(owners.items()):
            if owner=='ingetrazo_twinmotion_sync' and action.menu() is None:
                for menu in app.window.findChildren(QMenu):
                    if action in menu.actions():
                        menu.removeAction(action)
                old_menu.addAction(action)
    if resume:
        QTimer.singleShot(0,controller.connect)
