"""Deployed hashes and setup through the real IngeTrazo extension API."""
import hashlib
import json
import os
from pathlib import Path
import sys
from PySide6.QtCore import QObject,Signal,Qt
from PySide6.QtWidgets import QApplication,QMainWindow,QToolBar
from core.extensions import discover_plugins
import core.extensions as extension_module
from core.scene import Scene
from views.extension_api import ExtensionApp

qt=QApplication.instance() or QApplication([])
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'ingetrazo_twinmotion_sync'
destination=Path(os.environ['APPDATA'])/'ingetrazo/plugins/ingetrazo_twinmotion_sync'
state=Path(os.environ['LOCALAPPDATA'])/'IngeTrazo/twinmotion_sync'
record=json.loads((state/'installation.json').read_text())
hashes_match=all((destination/relative).is_file() and
    hashlib.sha256((destination/relative).read_bytes()).hexdigest()==digest
    for relative,digest in record['files'].items())
source_matches=all(hashlib.sha256((source/relative).read_bytes()).hexdigest()==digest
                   for relative,digest in record.get('source_files',record['files']).items())
original_candidates=extension_module._candidates
extension_module._candidates=lambda folder:iter([(destination.name,destination/'__init__.py')])
try:
    plugins,errors=discover_plugins([destination.parent])
finally:
    extension_module._candidates=original_candidates
errors=[error for error in errors if error.stem==destination.name]
plugin=next(p for p in plugins if p.stem==destination.name)
class Viewport(QObject):
    sceneVersionChanged=Signal(int)
    scene=Scene()
window=QMainWindow();window.viewport=Viewport(window)
window._current_path=None
window._ext_menu=window.menuBar().addMenu('Extensions')
app=ExtensionApp(window,destination.name)
plugin.setup(app);plugin.setup(app)
controller=window._twinmotion_sync_prototype
bars=window.findChildren(QToolBar,'ingetrazo_twinmotion_sync_toolbar')
assert len(bars)==1
controller.enabled=True;window.viewport.sceneVersionChanged.emit(1)
callback_works=controller.dirty and controller.timer.isActive()
controller.stop()
toolbar=bars[0]
icons_valid=all(not action.icon().isNull() for action in toolbar.actions())
no_vendor_bundled=not any((destination/name).exists() or (destination/'native'/name).exists()
    for name in ('DatasmithFacadeCSharp.dll','DatasmithRhino6.rhp','tbbmalloc.dll'))
runtime=json.loads((state/'runtime.json').read_text())
report={'pass':hashes_match and source_matches and not errors and callback_works
               and icons_valid and no_vendor_bundled,
        'installed_hashes_match':hashes_match,'source_hashes_match':source_matches,
        'plugin_discovery_errors':[error.error for error in errors],
        'real_extension_api_setup':True,'setup_idempotent':True,
        'real_document_change_callback':callback_works,'icons_valid':icons_valid,
        'icon_size':toolbar.iconSize().width(),'icon_only':toolbar.toolButtonStyle()==Qt.ToolButtonIconOnly,
        'toolbar_preferred_width':toolbar.sizeHint().width(),
        'debounce_ms':controller.timer.interval(),'vendor_bundled':not no_vendor_bundled,
        'worker_exe':runtime['worker_exe'],'plugin':str(destination),
        'desktop_toolbar_visual_check':'not measured by this offscreen installation check',
        'receiver_connection':'unverified','camera_sync':False}
report['camera_button_present']=controller.camera_action in toolbar.actions()
report['camera_publication_default_on']=controller.camera_action.isChecked()
report['pass']=report['pass'] and report['camera_button_present'] and report['camera_publication_default_on']
controller.shutdown();window.close()
output=Path(sys.argv[1]);output.parent.mkdir(parents=True,exist_ok=True)
output.write_text(json.dumps(report,indent=2),encoding='utf8')
print(json.dumps(report,indent=2))
assert report['pass']
