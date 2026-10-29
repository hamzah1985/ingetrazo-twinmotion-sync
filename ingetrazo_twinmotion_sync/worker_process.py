# SPDX-License-Identifier: GPL-3.0-or-later
"""Standard anonymous pipes; native I/O stays outside the GUI event loop."""
import json
import os
import subprocess
import threading
from PySide6.QtCore import QObject, Signal

class WorkerProcess(QObject):
    output = Signal(str)
    errors = Signal(str)
    exited = Signal(int)
    failed = Signal(str)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.process = None
        self.reader = None

    @property
    def running(self):
        return self.process is not None and self.process.poll() is None

    def start(self,worker,vendor):
        if self.running:
            raise RuntimeError('A Direct Link worker is already running.')
        # QProcess named pipes stall this .NET/native facade after its first
        # response on Windows. The actual native contract tests use Popen's
        # synchronous anonymous pipes; use that same proven transport here.
        process = subprocess.Popen([str(worker),str(vendor)],cwd=worker.parent,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=True,encoding='utf8',errors='replace',bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.process = process
        self.reader = threading.Thread(target=self._read,args=(process,),daemon=True)
        self.reader.start()

    def _read(self,process):
        def stderr():
            try:
                for line in process.stderr:
                    self.errors.emit(line)
            except (OSError,ValueError) as error:
                self.errors.emit(str(error))
        errors = threading.Thread(target=stderr,daemon=True)
        errors.start()
        try:
            for line in process.stdout:
                self.output.emit(line)
        except (OSError,ValueError) as error:
            self.failed.emit(str(error))
        finally:
            code = process.wait()
            errors.join(timeout=1)
            for stream in (process.stdin,process.stdout,process.stderr):
                try:
                    stream.close()
                except OSError:
                    pass
            self.exited.emit(code)

    def send(self,request):
        if not self.running:
            raise OSError('Direct Link worker is not running.')
        # One small path-only request is outstanding at a time. Geometry goes
        # through an atomic file, so stdin never carries a large scene payload.
        self.process.stdin.write(json.dumps(request,ensure_ascii=True)+'\n')
        self.process.stdin.flush()

    def kill(self):
        if self.running:
            self.process.kill()

    def wait(self,seconds):
        if self.process is None:
            return True
        try:
            self.process.wait(timeout=seconds)
            if self.reader is not None:
                self.reader.join(timeout=1.5)
            return True
        except subprocess.TimeoutExpired:
            return False
