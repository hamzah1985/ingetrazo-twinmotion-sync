"""Verify Epic's external runtime, build our source, then install our plugin."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import install_local

ROOT=Path(__file__).resolve().parent

def prerequisites(vendor):
    if os.name!='nt':
        raise RuntimeError('This prototype requires Windows x64.')
    vendor=Path(vendor).resolve()
    for name,digest in install_local.HASHES.items():
        path=vendor/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('Missing or unexpected official runtime file: '+name)
    compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.is_file():
        raise FileNotFoundError('The Windows x64 .NET Framework C# compiler is unavailable.')
    return vendor,compiler

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor-dir',required=True)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--check-only',action='store_true')
    mode.add_argument('--build-only',action='store_true')
    args=parser.parse_args()
    vendor,compiler=prerequisites(args.vendor_dir)
    if args.check_only:
        print(json.dumps({'prerequisites_ok':True,'vendor_dir':str(vendor),
                          'compiler':str(compiler),'installed':False},indent=2))
        return
    native=ROOT/'ingetrazo_twinmotion_sync/native'
    subprocess.run([str(compiler),'/nologo','/target:exe','/platform:x64',
        '/out:'+str(native/'DirectLinkWorker.exe'),
        '/reference:'+str(vendor/'DatasmithRhino6.rhp'),
        '/reference:System.Web.Extensions.dll',str(native/'DirectLinkWorker.cs')],check=True)
    if args.build_only:
        print(json.dumps({'built':str(native/'DirectLinkWorker.exe'),'installed':False},indent=2))
    else:
        print(json.dumps(install_local.install(vendor),indent=2))

if __name__=='__main__':
    try:
        main()
    except (OSError,ValueError,RuntimeError,subprocess.CalledProcessError) as error:
        print('Twinmotion Sync setup failed: '+str(error),file=sys.stderr)
        sys.exit(1)
