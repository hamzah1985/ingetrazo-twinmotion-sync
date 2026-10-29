"""Repeatable Qt sender benchmark; does not claim Twinmotion render latency."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtCore import QTimer,Qt
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication,QMainWindow
from core.camera import OrbitCamera
from core.extensions import _import_by_path
from core.scene import Scene

parser=argparse.ArgumentParser()
parser.add_argument('--package',type=Path,required=True)
parser.add_argument('--worker',type=Path,required=True)
parser.add_argument('--vendor',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--duration',type=float,default=3)
parser.add_argument('--fps',type=int,default=0,choices=(0,30,60))
args=parser.parse_args()
qt=QApplication.instance() or QApplication([])
package=_import_by_path('tm_camera_benchmark',args.package.resolve()/'__init__.py')
with tempfile.TemporaryDirectory(prefix='tm_camera_benchmark_') as temporary:
    folder=Path(temporary);document=folder/'SenderBenchmark.igz';document.touch()
    configuration=folder/'runtime.json'
    configuration.write_text(json.dumps({'worker_exe':str(args.worker.resolve()),
                                         'vendor_dir':str(args.vendor.resolve())}),encoding='utf8')
    os.environ['INGETRAZO_TM_RUNTIME']=str(configuration)
    class Host:
        window=QMainWindow()
        scene=Scene()
        viewport=SimpleNamespace(camera=OrbitCamera())
        def on_document_changed(self,fn): self.changed=fn
        def add_menu_action(self,*args): pass
    host=Host();host.window._current_path=document
    host.scene.loose_mesh.add_face([QVector3D(0,0,0),QVector3D(1,0,0),QVector3D(0,1,0)])
    controller=package.TwinmotionController(host)
    if args.fps:
        controller.set_camera_fps(args.fps)
    writes=[0]
    if not hasattr(controller,'diagnostics_writes'):
        original_diagnostics=controller.write_diagnostics
        def diagnostics():
            writes[0]+=1
            return original_diagnostics()
        controller.write_diagnostics=diagnostics
    sends=[];rtts=[];inflight=[];inputs=[0];start=[None]
    original_send=controller.send;original_reply=controller.handle_reply
    def send(request):
        if request['op']=='camera':
            now=time.perf_counter();sends.append(now);inflight.append(now)
        return original_send(request)
    def reply(result):
        if result.get('op')=='camera' and inflight:
            rtts.append((time.perf_counter()-inflight.pop(0))*1000)
        return original_reply(result)
    controller.send=send;controller.handle_reply=reply
    controller.connect()
    def wait(predicate,timeout=20):
        until=time.perf_counter()+timeout
        while not predicate():
            qt.processEvents();time.sleep(.001)
            if not controller.enabled or time.perf_counter()>until:
                raise RuntimeError(controller.status_text+'\n'+controller.errors)
    try:
        wait(lambda:controller.published>=1 and not controller.busy)
        def move():
            inputs[0]+=1;host.viewport.camera.yaw+=.004
        input_timer=QTimer();input_timer.setTimerType(Qt.PreciseTimer)
        input_timer.setInterval(16);input_timer.timeout.connect(move)
        start[0]=time.perf_counter();input_timer.start()
        while time.perf_counter()-start[0]<args.duration:
            qt.processEvents();time.sleep(.001)
        input_timer.stop();end=time.perf_counter()
        final_pose=controller.camera_signature(controller.current_camera())
        wait(lambda:controller.last_camera_revision==final_pose and not controller.busy)
        gaps=[(b-a)*1000 for a,b in zip(sends,sends[1:])]
        def percentile(values,fraction):
            return round(sorted(values)[int((len(values)-1)*fraction)],3) if values else None
        report={'input_frames':inputs[0],'elapsed_seconds':round(end-start[0],3),
                'camera_updates':len(sends),'sender_updates_per_second':round(len(sends)/(end-start[0]),2),
                'send_gap_p50_ms':percentile(gaps,.5),'send_gap_p95_ms':percentile(gaps,.95),
                'roundtrip_p50_ms':percentile(rtts,.5),'roundtrip_p95_ms':percentile(rtts,.95),
                'latest_pose_delivered':True,'geometry_publications':controller.published,
                'configured_camera_interval_ms':controller.camera_timer.interval(),
                'receiver_visual_latency':'not measured; source-only benchmark',
                'package':str(args.package.resolve()),'worker':str(args.worker.resolve())}
        if hasattr(controller,'diagnostics_writes'):
            report['diagnostics_writes']=controller.diagnostics_writes
        else:
            report['diagnostics_writes']=writes[0]
    finally:
        controller.shutdown()
    report['clean_worker_exit']=not controller.worker.running
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report,indent=2))
