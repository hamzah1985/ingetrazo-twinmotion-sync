"""Install the local prototype; vendor files remain in their external location."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from datetime import datetime

ROOT = Path(__file__).resolve().parent
HASHES = {
    'DatasmithFacadeCSharp.dll':'eb3e4881629244bbc3a5cb1062aa579d79f68ebb682b5140a274c7c0d1d6fc08',
    'DatasmithRhino6.rhp':'77e2073dc7bd792896f976562f97f125dd1289231338b20ef5bd8d2b6795cd1d',
    'tbbmalloc.dll':'87abcd8f7e31003ab049962a97eb645310be1ccab7ba148c46b2cde5262027bf',
}

def install(vendor):
    vendor = Path(vendor).resolve()
    for name,digest in HASHES.items():
        if hashlib.sha256((vendor/name).read_bytes()).hexdigest() != digest:
            raise ValueError('Unexpected official runtime version: '+name)
    source = ROOT/'ingetrazo_twinmotion_sync'
    if not (source/'native/DirectLinkWorker.exe').is_file():
        raise FileNotFoundError('Build the community Direct Link worker first.')
    destination = Path(os.environ['APPDATA'])/'ingetrazo/plugins/ingetrazo_twinmotion_sync'
    state = Path(os.environ['LOCALAPPDATA'])/'IngeTrazo/twinmotion_sync'
    state.mkdir(parents=True,exist_ok=True)
    configuration = state/'runtime.json'
    backup = None
    if destination.exists() or configuration.exists():
        backup = state/'install-backups'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup.mkdir(parents=True)
        if destination.exists():
            shutil.copytree(destination,backup/'ingetrazo_twinmotion_sync')
        if configuration.exists():
            shutil.copy2(configuration,backup/'runtime.json')
    source_files={str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    files={}
    active_worker=None
    for relative,digest in source_files.items():
        target_relative=relative
        if Path(relative)==Path('native/DirectLinkWorker.exe'):
            # A running Windows image is locked. Install a content-addressed
            # worker and atomically switch the runtime pointer; the old process
            # keeps working until the extension reconnects it gracefully.
            target_relative=str(Path('native')/('DirectLinkWorker-'+digest[:12]+'.exe'))
            active_worker=destination/target_relative
        target=destination/target_relative
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=digest:
            with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as stream:
                temporary=Path(stream.name)
                stream.write((source/relative).read_bytes())
            try:
                os.replace(temporary,target)
            finally:
                temporary.unlink(missing_ok=True)
        files[target_relative]=digest
    with tempfile.NamedTemporaryFile(dir=state,delete=False) as stream:
        temporary=Path(stream.name)
        stream.write(json.dumps({'worker_exe':str(active_worker),'vendor_dir':str(vendor)},indent=2).encode('utf8'))
    try:
        os.replace(temporary,configuration)
    finally:
        temporary.unlink(missing_ok=True)
    record = {'plugin':str(destination),'configuration':str(configuration),
              'backup':str(backup) if backup else None, 'vendor_bundled':False,
              'files':files,'source_files':source_files,'worker_exe':str(active_worker)}
    (state/'installation.json').write_text(json.dumps(record,indent=2),encoding='utf8')
    return record

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--vendor-dir',required=True)
    print(json.dumps(install(parser.parse_args().vendor_dir),indent=2))
