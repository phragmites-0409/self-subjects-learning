"""Fetch data-only InkErase weights locally at a pinned revision and SHA256."""
import argparse,concurrent.futures,hashlib,json,time,urllib.request
from pathlib import Path
from runtime_paths import RUNTIME_ROOT, portable_manifest, read_manifest

parser=argparse.ArgumentParser();parser.add_argument('--model',choices=['erase','segment'],default='erase');args=parser.parse_args()
if args.model=='erase':
    name='ink-erase';repo='InkErase';REVISION='362c38441a6aa03c915bf4a28b6c33a692c2ce33';SIZE=204806056;SHA='78acd1c02b274179ae975134eb827ed0bdb34d4e5890b7981f8dde08bb35eb7a'
else:
    name='exam-ink-seg';repo='ExamInk-Seg';REVISION='72bcd67da4c0e19cf5e64a3d316bf1a81b723126';SIZE=204810588;SHA='f23fa08ab21b5acce191c29c3f96dced710ad36cd20a319ca4bdb79f9432c42f'
ROOT=(RUNTIME_ROOT/'models')/name
ROOT.mkdir(parents=True,exist_ok=True)
SOURCE=f'https://huggingface.co/ynyg/{repo}'
URL=f'{SOURCE}/resolve/{REVISION}/model.safetensors'
model=ROOT/'model.safetensors'
for name in ('config.json','README.md'):
    with urllib.request.urlopen(f'{SOURCE}/resolve/{REVISION}/{name}',timeout=30) as response:
        (ROOT/name).write_bytes(response.read())
if not model.is_file():
    parts=ROOT/'download-parts';parts.mkdir(exist_ok=True)
    block=4*1024*1024
    def fetch(start):
        end=min(SIZE,start+block)-1;part=parts/f'{start}.part'
        for attempt in range(80):
            current=part.stat().st_size if part.exists() else 0
            if current==end-start+1:return part
            if current>end-start+1:raise RuntimeError('Oversized chunk')
            offset=start+current
            try:
                req=urllib.request.Request(URL+f'?download=true&offset={offset}',headers={'Range':f'bytes={offset}-{end}','Accept-Encoding':'identity'})
                with urllib.request.urlopen(req,timeout=25) as response:
                    if response.headers.get('Content-Range')!=f'bytes {offset}-{end}/{SIZE}':raise RuntimeError('Unexpected range')
                    with part.open('ab') as target:
                        while target.tell()<end-start+1:
                            data=response.read(min(1024*1024,end-start+1-target.tell()))
                            if not data:break
                            target.write(data)
                if part.stat().st_size==end-start+1:
                    print(f'Completed {start//block+1}/{(SIZE+block-1)//block}',flush=True);return part
            except Exception as error:
                if attempt==79:raise
                if attempt in (0,9,39):print(f'Retry chunk {start//block+1}: {type(error).__name__}',flush=True)
                time.sleep(.5)
        raise RuntimeError('Incomplete chunk')
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:files=list(pool.map(fetch,range(0,SIZE,block)))
    partial=ROOT/'model.safetensors.part'
    with partial.open('wb') as output:
        for part in files:output.write(part.read_bytes())
    if partial.stat().st_size!=SIZE or hashlib.sha256(partial.read_bytes()).hexdigest()!=SHA:raise RuntimeError('Invalid model bytes')
    partial.replace(model)
if model.stat().st_size!=SIZE or hashlib.sha256(model.read_bytes()).hexdigest()!=SHA:raise RuntimeError('Model digest mismatch')
manifest={'source':SOURCE,'revision':REVISION,'file':str(model),'bytes':SIZE,'sha256':SHA,'license_notes':'metadata Apache-2.0; config/README MIT; keep provenance; personal evaluation only','production_enabled':False}
if (ROOT/'manifest.json').is_file():
    previous=read_manifest(ROOT/'manifest.json')
    if previous.get('sha256')==SHA and previous.get('onnx_file'):
        converted=Path(previous['onnx_file']).resolve()
        if converted.is_relative_to(ROOT.resolve()) and converted.is_file() and hashlib.sha256(converted.read_bytes()).hexdigest()==previous.get('onnx_sha256'):
            manifest.update({key:value for key,value in previous.items() if key not in manifest})
            manifest.pop('production_enabled',None)
(ROOT/'manifest.json').write_text(json.dumps(portable_manifest(manifest),ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(manifest),flush=True)
