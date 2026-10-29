"""Candidate byte verification, not upstream completeness or source revalidation."""
import json,hashlib,sys
from pathlib import Path
def sha(p,checkpoint=None):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):
   h.update(b)
   if checkpoint:checkpoint('verify_'+p.name)
 return h.hexdigest()
def verify(root,checkpoint=None):
 root=Path(root).resolve();expected=(root/'FILE_INVENTORY.sha256').read_text().split()[0];assert sha(root/'FILE_INVENTORY.json')==expected,'INVENTORY_SHA'
 m=json.loads((root/'FILE_INVENTORY.json').read_text(encoding='utf8'))
 for r in m['files']:
  p=(root/r['path']).resolve();assert p.is_relative_to(root) and not p.is_symlink(),'PATH_ESCAPE';assert p.stat().st_size==r['bytes'] and sha(p,checkpoint)==r['sha256'],r['path']
 return {'status':'PASS','files':len(m['files']),'payload_bytes':m['payload_bytes'],'upstream_revalidation':False}
if __name__=='__main__':print(json.dumps(verify(sys.argv[1])))
