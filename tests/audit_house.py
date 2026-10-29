"""Read-only house capture -> actual Qt worker -> native asset-reference checks."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET
from types import SimpleNamespace

os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication,QMainWindow
from PySide6.QtGui import QVector3D
from core.camera import OrbitCamera
from core.extensions import _import_by_path
from core.scene import Scene
from formats.igz import load_into

ROOT=Path(__file__).resolve().parents[1]
package=_import_by_path('twinmotion_house_audit',ROOT/'ingetrazo_twinmotion_sync/__init__.py')
qt=QApplication.instance() or QApplication([])
source=Path(sys.argv[1]).resolve();report_path=Path(sys.argv[2]).resolve()
original=hashlib.sha256(source.read_bytes()).hexdigest();started=time.monotonic()
print('Loading saved house read-only.',flush=True)
class Host:
    window=QMainWindow()
    scene=Scene()
    def on_document_changed(self,callback): self.changed=callback
    def add_menu_action(self,*args): pass
host=Host();host.window._current_path=source
load_into(host.scene,source)
camera=OrbitCamera();camera.aspect=16/9
home=getattr(host.scene,'camera_home',None) or {}
if 'target' in home:
    camera.target=QVector3D(*home['target'])
for key in ('distance','yaw','pitch','fov_deg','perspective','two_point'):
    if key in home:
        setattr(camera,key,type(getattr(camera,key))(home[key]))
host.viewport=SimpleNamespace(camera=camera,scene=host.scene)
print('Publishing through the actual Qt controller and native worker.',flush=True)
controller=package.TwinmotionController(host)
controller.connect()
try:
    until=time.monotonic()+240
    while controller.published<1:
        qt.processEvents()
        if not controller.enabled or time.monotonic()>until:
            raise RuntimeError(controller.status_text+'\n'+controller.errors)
        time.sleep(0.02)
    result=controller.last_result
    scene_path=Path(result['scene_path']);xml=ET.parse(scene_path).getroot()
    meshes=[scene_path.parent/m.find('file').attrib['path'] for m in xml.findall('StaticMesh')]
    textures=[scene_path.parent/t.attrib['file'] for t in xml.findall('Texture')]
    capture=json.loads((controller.cache/'ingetrazo-scene.json').read_text(encoding='utf8'))
    images={Path(m['diffuse_map']) for m in capture['materials'] if m.get('diffuse_map')}
    view=xml.find('Camera')
    camera_pose_ok=False
    if capture.get('camera'):
        expected=capture['camera']['position']
        actual=view.find('Transform').attrib
        camera_pose_ok=all(abs(float(actual[key])-value)<0.02 for key,value in
                           zip(('tx','ty','tz'),(expected[0]*100,-expected[1]*100,expected[2]*100)))
    stamps=[p.stat().st_mtime_ns for p in meshes]
    xml_before=scene_path.read_bytes()
    camera_start=time.monotonic()
    if capture.get('camera'):
        camera.target+=QVector3D(1,2,0)
        controller.poll_camera()
        until=time.monotonic()+30
        while controller.camera_updates<1 or controller.busy:
            qt.processEvents()
            if not controller.enabled or time.monotonic()>until:
                raise RuntimeError(controller.status_text+' camera update timeout')
            time.sleep(0.01)
    camera_seconds=round(time.monotonic()-camera_start,3)
    camera_preserved_meshes=stamps==[p.stat().st_mtime_ns for p in meshes] and xml_before==scene_path.read_bytes()
    xml_materials={m.attrib['name']:m for m in xml.findall('UEPbrMaterial')}
    default_white=0
    for m in capture['materials']:
        if m['color']=='#FFFFFF' and not m.get('diffuse_map'):
            name='mat_'+hashlib.sha256(m['id'].encode()).hexdigest()[:24]
            value=xml_materials[name].find('Expressions/Color').attrib['constant']
            assert 'R=1.000000,G=1.000000,B=1.000000' in value
            default_white+=1
    record={'source':str(source),'source_sha256':original,
            'source_unchanged':hashlib.sha256(source.read_bytes()).hexdigest()==original,
            'worker':result,'native_meshes':len(meshes),'native_texture_entries':len(textures),
            'unique_texture_images':len(images),'default_white_materials_checked':default_white,
            'all_mesh_assets_exist':all(p.is_file() and p.stat().st_size>100 for p in meshes),
            'all_texture_assets_exist':all(p.is_file() for p in textures+list(images)),
            'capture_warnings':capture.get('warnings',[]),
            'camera_from_saved_home':bool(home),'audit_viewport_aspect':16/9,
            'native_camera_pose_verified':camera_pose_ok,
            'camera_only_updates':controller.camera_updates,'camera_update_seconds':camera_seconds,
            'camera_update_preserved_mesh_files':camera_preserved_meshes,
            'geometry_publications':controller.published,
            'binary_geometry':controller.native_buffers,
            'geometry_capture_ms':controller.geometry_capture_ms,
            'geometry_encode_ms':controller.geometry_encode_ms,
            'receiver_connection':'unverified','visual_acceptance':'not measured by this offscreen export audit',
            'camera_sync':False,'companion_folder':str(controller.cache)}
    record['pass']=(record['source_unchanged'] and record['all_mesh_assets_exist']
                    and record['all_texture_assets_exist'] and len(meshes)==result['objects']
                    and len(images)>0 and default_white>0 and not record['capture_warnings']
                    and camera_pose_ok and camera_preserved_meshes and controller.camera_updates>=1
                    and controller.published==1)
finally:
    controller.shutdown()
record['clean_worker_exit']=not controller.worker.running
record['elapsed_seconds']=round(time.monotonic()-started,2)
record['pass']=record['pass'] and record['clean_worker_exit']
report_path.parent.mkdir(parents=True,exist_ok=True)
report_path.write_text(json.dumps(record,indent=2,ensure_ascii=False),encoding='utf8')
print(json.dumps(record,indent=2,ensure_ascii=False),flush=True)
assert record['pass']
