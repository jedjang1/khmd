"""Load only pinned v0_1 modules; unchanged files are not duplicated."""
import importlib.util, os, sys
from pathlib import Path
from binding import PROJECT, ANNUAL
DLL=None
if Path(sys.executable).parent.name=='Python312':
    DLL=os.add_dll_directory(str(Path(sys.executable).parents[2]/'bin'))
sys.path.insert(0,str(PROJECT/'src'))
sys.path.insert(0,str(ANNUAL/'csv_spatial_5179_busan_v0_2'))
sys.path.insert(0,str(ANNUAL/'csv_regional_demand_v0_1'))

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def audit_loaded_modules(out):
    import json
    from binding import HERE, need, write
    roots=(HERE.resolve(),HERE.parent.joinpath('khmd_construction_code_candidate_v0_1').resolve())
    runtime_root=Path(sys.base_prefix).resolve()
    if runtime_root.name=='Python312':runtime_root=runtime_root.parents[1]
    records=[]
    for name,module in sorted(sys.modules.items()):
        filename=getattr(module,'__file__',None)
        if not filename or filename.startswith('<'):continue
        p=Path(filename).resolve()
        internal=any(p.is_relative_to(r) for r in roots)
        need(internal or p.is_relative_to(runtime_root),'UNDECLARED_CODE_OR_OLD_PROJECT_IMPORT:'+str(p))
        records.append(dict(module=name,path=str(p),candidate_code=internal))
    write(Path(out)/'loaded_modules.json',dict(status='PASS',candidate_roots=[str(r) for r in roots],runtime_root=str(runtime_root),modules=records))
