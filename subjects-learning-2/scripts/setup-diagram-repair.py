"""Download a pinned ONNX inpainting model locally, verify its published LFS hash."""
import hashlib, json, time, urllib.request, concurrent.futures
from pathlib import Path
from runtime_paths import MANIFEST_ROOT, RUNTIME_ROOT, portable_manifest, read_manifest

target = RUNTIME_ROOT / 'models/diagram-repair'
target.mkdir(parents=True,exist_ok=True)
pinned = read_manifest(MANIFEST_ROOT / 'diagram-repair/manifest.json')
checksums = read_manifest(MANIFEST_ROOT / 'checksums.json')
artifact = next(item for item in checksums['files'] if Path(item['path']) == target / 'lama_fp32.onnx')
metadata = {'sha': pinned['revision'], 'siblings': [{'rfilename': 'lama_fp32.onnx',
            'lfs': {'sha256': pinned['sha256'], 'size': artifact['bytes']}}]}
(target/'download-metadata.json').write_text(json.dumps(metadata),encoding='utf-8')
entry = next(x for x in metadata['siblings'] if x['rfilename']=='lama_fp32.onnx')
digest = entry['lfs']['sha256']
revision = metadata['sha']
url = f'https://huggingface.co/Carve/LaMa-ONNX/resolve/{revision}/lama_fp32.onnx'
model = target/'lama_fp32.onnx'
partial = target/'lama_fp32.onnx.part'
if not model.exists():
    pieces=target/'download-parts'; pieces.mkdir(exist_ok=True)
    size=entry['lfs']['size']; block=4*1024*1024
    def fetch(start):
        end=min(size,start+block)-1; piece=pieces/f'{revision}-{start}.part'
        if piece.exists() and piece.stat().st_size==end-start+1:
            return piece
        data=piece.read_bytes() if piece.exists() else b''
        for attempt in range(200):
            try:
                offset=start+len(data)
                request=urllib.request.Request(url+f'?download=true&part={offset}',headers={'Range':f'bytes={offset}-{end}','Accept-Encoding':'identity'})
                with urllib.request.urlopen(request,timeout=60) as response:
                    assert response.headers.get('Content-Range')==f'bytes {offset}-{end}/{size}'
                    data+=response.read(end-offset+1)
                piece.write_bytes(data)
                if len(data)==end-start+1:
                    piece.write_bytes(data)
                    print(f'Chunk {start//block+1}/{(size+block-1)//block} downloaded',flush=True)
                    return piece
            except Exception:
                if attempt==199: raise
                time.sleep(1)
        raise RuntimeError('Incomplete download')
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        downloaded=list(pool.map(fetch,range(0,size,block)))
    count=0
    with partial.open('wb') as output:
        for piece in downloaded:
            data=piece.read_bytes(); output.write(data); count+=len(data)
    assert count == entry['lfs']['size'], (count,entry['lfs']['size'])
    assert hashlib.sha256(partial.read_bytes()).hexdigest() == digest
    partial.replace(model)
assert hashlib.sha256(model.read_bytes()).hexdigest() == digest
manifest = {'model':str(model),'sha256':digest,'revision':revision,'url':url,'license':'Apache-2.0',
    'source':'https://huggingface.co/Carve/LaMa-ONNX','original':'https://github.com/advimman/lama'}
(target/'manifest.json').write_text(json.dumps(portable_manifest(manifest),indent=2),encoding='utf-8')
print(json.dumps(manifest),flush=True)
