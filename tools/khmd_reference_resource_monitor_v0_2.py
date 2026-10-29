"""Windows reference worker current-working-set guard and external watchdog.

No old monitor is replaced. Current samples enforce; lifetime peak is a
diagnostic that can separately require review before successful publication.
"""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

VERSION = 'KHMD_REFERENCE_RESOURCE_MONITOR_V0_2'
THRESHOLD = 114 * 1024 * 1024
CONTRACT = 'metadata/khmd_nationwide_reference_resource_monitor_contract_v0_2.json'
SAMPLE_SECONDS = 0.1


class ResourceHold(RuntimeError):
    pass


def current_hold(current, threshold=THRESHOLD):
    return int(current) > int(threshold)


def peak_review(peak, threshold=THRESHOLD):
    return int(peak) > int(threshold)


def validate_contract(contract):
    if contract['enforcement_threshold_bytes'] != THRESHOLD:
        raise ResourceHold('RESOURCE_THRESHOLD_DRIFT')
    if contract['enforcement_metric'] != 'CURRENT_PROCESS_WORKING_SET_BYTES':
        raise ResourceHold('RESOURCE_METRIC_DRIFT')
    if contract['watchdog_interval_seconds'] != SAMPLE_SECONDS:
        raise ResourceHold('RESOURCE_SAMPLING_DRIFT')
    return contract


if os.name == 'nt':
    KERNEL = ctypes.WinDLL('kernel32', use_last_error=True)
    PSAPI = ctypes.WinDLL('psapi', use_last_error=True)

    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [(n, ctypes.c_size_t) for n in
            ('peak_working_set', 'working_set', 'peak_paged_pool', 'paged_pool',
             'peak_nonpaged_pool', 'nonpaged_pool', 'pagefile', 'peak_pagefile')]

    class SystemMemory(ctypes.Structure):
        _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD)] + [(n, ctypes.c_ulonglong) for n in
            ('total_ram', 'available_ram', 'total_commit', 'available_commit', 'total_virtual', 'available_virtual', 'extended')]

    class BasicLimit(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                    ('flags', wintypes.DWORD), ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t),
                    ('active_processes', wintypes.DWORD), ('affinity', ctypes.c_size_t),
                    ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]

    class IOCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ('reads', 'writes', 'others', 'read_bytes', 'write_bytes', 'other_bytes')]

    class ExtendedLimit(ctypes.Structure):
        _fields_ = [('basic', BasicLimit), ('io', IOCounters), ('process_memory', ctypes.c_size_t),
                    ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]

    def _bind(lib, name, args, result):
        f = getattr(lib, name); f.argtypes = args; f.restype = result
        return f

    OPEN = _bind(KERNEL, 'OpenProcess', [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE)
    CLOSE = _bind(KERNEL, 'CloseHandle', [wintypes.HANDLE], wintypes.BOOL)
    MEMORY = _bind(PSAPI, 'GetProcessMemoryInfo', [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD], wintypes.BOOL)
    TIMES = _bind(KERNEL, 'GetProcessTimes', [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4, wintypes.BOOL)
    SYSTEM_MEMORY = _bind(KERNEL, 'GlobalMemoryStatusEx', [ctypes.POINTER(SystemMemory)], wintypes.BOOL)
    CREATE_JOB = _bind(KERNEL, 'CreateJobObjectW', [ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE)
    SET_JOB = _bind(KERNEL, 'SetInformationJobObject', [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL)
    ASSIGN_JOB = _bind(KERNEL, 'AssignProcessToJobObject', [wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL)


class WindowsReader:
    """Pinned handle + PID + process creation FILETIME; excludes descendants."""
    def __init__(self, pid=None):
        if os.name != 'nt':
            raise ResourceHold('WINDOWS_RUNTIME_REQUIRED')
        self.pid = os.getpid() if pid is None else int(pid)
        self.handle = OPEN(0x0400 | 0x0010, False, self.pid)
        if not self.handle:
            raise ResourceHold('RESOURCE_PROCESS_OPEN_FAILED')
        self.info = Counters(); self.info.cb = ctypes.sizeof(self.info)
        self.system = SystemMemory(); self.system.length = ctypes.sizeof(self.system)
        self.creation_time_100ns = self._creation()

    def _creation(self):
        values = [wintypes.FILETIME() for _ in range(4)]
        if not TIMES(self.handle, *[ctypes.byref(x) for x in values]):
            raise ResourceHold('RESOURCE_PROCESS_IDENTITY_FAILED')
        return (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime

    def read(self):
        if self._creation() != self.creation_time_100ns:
            raise ResourceHold('RESOURCE_PROCESS_IDENTITY_CHANGED')
        if not MEMORY(self.handle, ctypes.byref(self.info), self.info.cb):
            raise ResourceHold('RESOURCE_MEASUREMENT_FAILED')
        if not SYSTEM_MEMORY(ctypes.byref(self.system)):
            raise ResourceHold('RESOURCE_SYSTEM_MEMORY_FAILED')
        return dict(pid=self.pid, process_creation_time_100ns=self.creation_time_100ns,
                    current_working_set_bytes=int(self.info.working_set),
                    diagnostic_peak_working_set_bytes=int(self.info.peak_working_set),
                    available_ram_bytes=int(self.system.available_ram),
                    available_commit_bytes=int(self.system.available_commit),
                    monotonic_ns=time.monotonic_ns())

    def close(self):
        if self.handle:
            CLOSE(self.handle); self.handle = None


class WorkerJob:
    """One supervised worker, zero worker descendants, kill on supervisor exit."""
    def __init__(self, process):
        self.handle = CREATE_JOB(None, None)
        if not self.handle:
            raise ResourceHold('RESOURCE_JOB_CREATE_FAILED')
        info = ExtendedLimit()
        info.basic.flags = 0x00000008 | 0x00002000  # ACTIVE_PROCESS, KILL_ON_JOB_CLOSE
        info.basic.active_processes = 1
        if not SET_JOB(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            self.close(); raise ResourceHold('RESOURCE_JOB_POLICY_FAILED')
        if not ASSIGN_JOB(self.handle, wintypes.HANDLE(int(process._handle))):
            self.close(); raise ResourceHold('RESOURCE_JOB_ASSIGN_FAILED')

    def close(self):
        if self.handle:
            CLOSE(self.handle); self.handle = None


def load_contract(root, path=None):
    path = Path(path or Path(root) / CONTRACT)
    return validate_contract(json.loads(path.read_text(encoding='utf-8')))


class ReferenceGuard:
    def __init__(self, root, contract_path=None, *, reader=None, disk=None, require_supervisor=True):
        self.root = Path(root); self.contract = load_contract(root, contract_path)
        self.reader = reader or WindowsReader(); self.disk = disk or shutil.disk_usage
        self.require_supervisor = require_supervisor
        self.sample_count = 0; self.max_current = 0; self.max_peak = 0
        self.hold_triggered = False; self.review_hold_triggered = False
        self.phase = None; self.last = {}; self.reserved_bytes = 0

    def _hold(self, message):
        self.hold_triggered = True
        raise ResourceHold(message)

    def admit(self):
        if self.require_supervisor:
            gate = os.environ.get('KHMD_RESOURCE_START_GATE')
            if not gate:
                self._hold('RESOURCE_SUPERVISOR_REQUIRED')
            end = time.monotonic() + 30
            while not Path(gate).exists():
                if time.monotonic() > end:
                    self._hold('RESOURCE_SUPERVISOR_START_TIMEOUT')
                time.sleep(0.01)
            token = json.loads(Path(gate).read_text(encoding='utf8'))
            sample = self.reader.read()
            if token['worker_pid'] != os.getpid() or token['process_creation_time_100ns'] != sample['process_creation_time_100ns']:
                self._hold('RESOURCE_SUPERVISOR_IDENTITY_MISMATCH')
            def child_block(event, args):
                if event in ('subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.spawn'):
                    raise ResourceHold('RESOURCE_WORKER_CHILD_PROCESS_FORBIDDEN')
            sys.addaudithook(child_block)
        self.checkpoint('admission')
        if min(self.last['available_ram_bytes'], self.last['available_commit_bytes']) < THRESHOLD + self.contract['reserve_memory_bytes']:
            self._hold('RESOURCE_ADMISSION_MEMORY_HOLD')
        return self.last

    def checkpoint(self, phase):
        self.phase = phase
        try:
            s = self.reader.read()
            self.sample_count += 1; self.last = s
            self.max_current = max(self.max_current, s['current_working_set_bytes'])
            self.max_peak = max(self.max_peak, s['diagnostic_peak_working_set_bytes'])
            if current_hold(s['current_working_set_bytes']):
                self._hold('RESOURCE_CURRENT_WORKING_SET_HOLD')
            if min(s['available_ram_bytes'], s['available_commit_bytes']) < self.contract['reserve_memory_bytes']:
                self._hold('RESOURCE_MEMORY_RESERVE_HOLD')
            if self.disk(self.root).free < self.contract['reserve_disk_bytes']:
                self._hold('RESOURCE_DISK_RESERVE_HOLD')
            if self.require_supervisor:
                p = os.environ.get('KHMD_RESOURCE_STOP_FILE')
                if not p or Path(p).exists():
                    self._hold('RESOURCE_EXTERNAL_WATCHDOG_HOLD')
            return s
        except ResourceHold:
            raise
        except Exception:
            self._hold('RESOURCE_MONITOR_UNAVAILABLE_HOLD')

    def reserve_output(self, size):
        if size < 0 or self.disk(self.root).free < size + self.contract['reserve_disk_bytes']:
            self._hold('RESOURCE_OUTPUT_DISK_HOLD')
        self.reserved_bytes += size

    def publication_gate(self):
        self.checkpoint('before_success_publication')
        if peak_review(self.max_peak):
            self.review_hold_triggered = True
            raise ResourceHold('RESOURCE_PEAK_CHECKPOINT_DISCREPANCY_REVIEW_HOLD')
        return self.receipt()

    def receipt(self):
        return dict(monitor_version=VERSION, enforcement_metric='CURRENT_PROCESS_WORKING_SET_BYTES',
                    enforcement_threshold_bytes=THRESHOLD, observed_max_enforcement_metric=self.max_current,
                    diagnostic_peak_metric='WINDOWS_PROCESS_LIFETIME_PEAK_WORKING_SET_BYTES',
                    diagnostic_peak_value=self.max_peak, hold_triggered=self.hold_triggered,
                    diagnostic_review_hold_triggered=self.review_hold_triggered,
                    checkpoint_sample_count=self.sample_count, last_phase=self.phase,
                    process_identity={k:self.last.get(k) for k in ('pid','process_creation_time_100ns')},
                    child_process_policy='FORBIDDEN_JOB_ACTIVE_PROCESS_LIMIT_1',
                    strict_instantaneous_ceiling_guaranteed=False)


def _publish(path, data):
    with Path(path).open('x', encoding='utf8') as f:
        json.dump(data, f, ensure_ascii=False, sort_keys=True, indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())


def supervise(command, cwd, env, work_directory, contract_path=None):
    """Launch fresh worker once. Return receipt; never retry/delete partial files.

    Worker must call ReferenceGuard.admit() before workload, publication_gate()
    before successful output and write worker_resource_receipt.json. Caller
    must require status COMPLETE before publishing authoritative success.
    """
    contract = load_contract(cwd, contract_path)
    work = Path(work_directory); work.mkdir(parents=True, exist_ok=False)
    gate = work / 'start_gate.json'; stop = work / 'stop.json'
    environment = dict(env); environment['KHMD_RESOURCE_START_GATE'] = str(gate.resolve())
    environment['KHMD_RESOURCE_STOP_FILE'] = str(stop.resolve())
    environment['KHMD_RESOURCE_WORK_DIRECTORY'] = str(work.resolve())
    process = reader = job = None
    samples = 0; max_current = max_peak = 0; failure = None; creation = None
    start = time.monotonic(); sample_times = []; max_gap = 0.0; last_time = None
    try:
        with (work/'stdout.log').open('x',encoding='utf8') as out, (work/'stderr.log').open('x',encoding='utf8') as err:
            process = subprocess.Popen(command, cwd=cwd, env=environment, stdout=out, stderr=err)
            reader = WindowsReader(process.pid); creation = reader.creation_time_100ns
            job = WorkerJob(process)
            initial = reader.read()
            if current_hold(initial['current_working_set_bytes']):
                raise ResourceHold('RESOURCE_CURRENT_WORKING_SET_HOLD')
            _publish(gate, dict(worker_pid=process.pid, process_creation_time_100ns=creation,
                               job_active_process_limit=1, worker_descendants_allowed=False))
            with (work/'external_samples.jsonl').open('x',encoding='utf8') as log:
                while process.poll() is None:
                    t = time.monotonic()
                    if last_time is not None: max_gap = max(max_gap,t-last_time)
                    last_time=t
                    try: sample=reader.read()
                    except ResourceHold:
                        if process.poll() is not None: break
                        raise
                    samples += 1; max_current=max(max_current,sample['current_working_set_bytes'])
                    max_peak=max(max_peak,sample['diagnostic_peak_working_set_bytes'])
                    log.write(json.dumps(sample,sort_keys=True)+'\n'); log.flush()
                    if current_hold(sample['current_working_set_bytes']):
                        raise ResourceHold('RESOURCE_CURRENT_WORKING_SET_HOLD')
                    if min(sample['available_ram_bytes'],sample['available_commit_bytes']) < contract['reserve_memory_bytes']:
                        raise ResourceHold('RESOURCE_MEMORY_RESERVE_HOLD')
                    if shutil.disk_usage(cwd).free < contract['reserve_disk_bytes']:
                        raise ResourceHold('RESOURCE_DISK_RESERVE_HOLD')
                    time.sleep(SAMPLE_SECONDS)
            process.wait()
            receipt_path=work/'worker_resource_receipt.json'
            if not receipt_path.exists():
                raise ResourceHold('RESOURCE_WORKER_FINAL_RECEIPT_MISSING')
            receipt=json.loads(receipt_path.read_text(encoding='utf8'))
            if receipt['process_identity'] != dict(pid=process.pid,process_creation_time_100ns=creation):
                raise ResourceHold('RESOURCE_WORKER_FINAL_IDENTITY_MISMATCH')
            max_current=max(max_current,receipt['observed_max_enforcement_metric'])
            max_peak=max(max_peak,receipt['diagnostic_peak_value'])
            if process.returncode != 0 or receipt['hold_triggered'] or receipt['diagnostic_review_hold_triggered']:
                raise ResourceHold('RESOURCE_WORKER_NON_SUCCESS_HOLD')
            if peak_review(max_peak):
                raise ResourceHold('RESOURCE_PEAK_CHECKPOINT_DISCREPANCY_REVIEW_HOLD')
    except ResourceHold as e:
        failure=str(e)
    except Exception as e:
        failure='RESOURCE_SUPERVISOR_'+type(e).__name__.upper()+'_HOLD'
    finally:
        if failure and not stop.exists():_publish(stop,dict(status='HOLD',reason=failure))
        if process and process.poll() is None:
            # Factual forced hold preserves any partial files; no auto-retry.
            process.terminate(); process.wait(timeout=10)
        if reader:reader.close()
        if job:job.close()
    result=dict(status='HOLD' if failure else 'COMPLETE',failure=failure,worker_pid=process.pid if process else None,
                process_creation_time_100ns=creation,returncode=process.returncode if process else None,
                enforcement_metric='CURRENT_PROCESS_WORKING_SET_BYTES',enforcement_threshold_bytes=THRESHOLD,
                observed_max_enforcement_metric=max_current,
                diagnostic_peak_metric='WINDOWS_PROCESS_LIFETIME_PEAK_WORKING_SET_BYTES',diagnostic_peak_value=max_peak,
                hold_triggered=bool(failure),external_samples=samples,requested_interval_seconds=SAMPLE_SECONDS,
                observed_max_sample_gap_seconds=max_gap,elapsed_seconds=time.monotonic()-start,
                child_process_policy='FORBIDDEN_JOB_ACTIVE_PROCESS_LIMIT_1',automatic_retry=False,
                strict_instantaneous_ceiling_guaranteed=False,partial_files_preserved=True)
    _publish(work/'supervisor_receipt.json',result)
    return result
