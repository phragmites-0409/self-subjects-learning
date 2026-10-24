"""Download pinned official llama.cpp + GLM-OCR artifacts inside the configured runtime."""
import concurrent.futures,hashlib,json,time,urllib.request,zipfile
from pathlib import Path
from runtime_paths import RUNTIME_ROOT, portable_manifest
BASE=RUNTIME_ROOT
MODEL=BASE/'models/glm-ocr';MODEL.mkdir(parents=True,exist_ok=True)
TOOLS=BASE/'document-ocr/llama-b11429-vulkan';TOOLS.mkdir(parents=True,exist_ok=True)
REV='65a42de1148dbed2297e922b5dbc7d9b70c36578'
FILES=[
 (MODEL/'GLM-OCR-Q8_0.gguf',f'https://huggingface.co/ggml-org/GLM-OCR-GGUF/resolve/{REV}/GLM-OCR-Q8_0.gguf',950433408,'45bc244a6446aff850521dc41f18bc8d7105ad5f0c2c8c28af04e7cc4f4d50b1'),
 (MODEL/'mmproj-GLM-OCR-Q8_0.gguf',f'https://huggingface.co/ggml-org/GLM-OCR-GGUF/resolve/{REV}/mmproj-GLM-OCR-Q8_0.gguf',484403648,'9c4b58e33e316ed142eb5dcb41abec3844d3e6e5dc361ffb782c3fa9d175141f'),
 (TOOLS.parent/'llama-b11429-bin-win-vulkan-x64.zip','https://github.com/ggml-org/llama.cpp/releases/download/b11429/llama-b11429-bin-win-vulkan-x64.zip',33337769,'1bfe78ad9168b79fa02bf67f6af9f5e17a966d824d77238517f7bef12ac73b36')]
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()
def download(entry):
    path,url,size,sha=entry
    assert path.resolve().is_relative_to(BASE.resolve())
    if path.is_file() and path.stat().st_size==size and digest(path)==sha:
        print('Verified cached',path.name,flush=True);return
    pieces=path.parent/(path.name+'-download-parts');pieces.mkdir(exist_ok=True)
    block=2*1024*1024
    def fetch(start):
        end=min(size,start+block)-1;piece=pieces/f'{start}.part'
        for attempt in range(120):
            current=piece.stat().st_size if piece.exists() else 0
            if current==end-start+1:return piece
            assert current<end-start+1,'Oversized partial range'
            offset=start+current
            try:
                req=urllib.request.Request(url+f'?download=true&offset={offset}',headers={'Range':f'bytes={offset}-{end}','Accept-Encoding':'identity','User-Agent':'subjects-learning-local-setup/2'})
                with urllib.request.urlopen(req,timeout=35) as response:
                    assert response.headers.get('Content-Range')==f'bytes {offset}-{end}/{size}','Unexpected response range'
                    with piece.open('ab') as target:
                        while target.tell()<end-start+1:
                            data=response.read(min(1024*1024,end-start+1-target.tell()))
                            if not data:break
                            target.write(data)
            except Exception:
                if attempt==119:raise
                time.sleep(.4)
        raise RuntimeError('Incomplete range')
    last=time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        completed=[]
        for piece in pool.map(fetch,range(0,size,block)):
            completed.append(piece)
            if time.monotonic()-last>20:
                total=sum(item.stat().st_size for item in pieces.glob('*.part'))
                print(path.name,round(total/size*100,1),'%',flush=True);last=time.monotonic()
    partial=path.with_suffix('.verified.tmp')
    with partial.open('wb') as target:
        for piece in completed:
            with piece.open('rb') as source:
                for data in iter(lambda:source.read(1024*1024),b''):target.write(data)
    assert partial.stat().st_size==size and digest(partial)==sha,'Model size/SHA256 mismatch'
    partial.replace(path);print('Downloaded and verified',path.name,flush=True)
def install():
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(download,FILES))
    with zipfile.ZipFile(FILES[2][0]) as archive:
        assert archive.testzip() is None
        for entry in archive.infolist():
            assert (TOOLS/entry.filename).resolve().is_relative_to(TOOLS.resolve()),'Unsafe archive path'
        archive.extractall(TOOLS)
    manifest={'source':'https://huggingface.co/zai-org/GLM-OCR','conversion_source':'https://huggingface.co/ggml-org/GLM-OCR-GGUF','revision':REV,'license':'MIT (upstream model)','quantization':'Q8_0','files':[{'path':str(p),'url':u,'bytes':s,'sha256':h} for p,u,s,h in FILES],'engine_dir':str(TOOLS),'loopback_only':True,'external_api_calls':False}
    (MODEL/'manifest.json').write_text(json.dumps(portable_manifest(manifest),ensure_ascii=False,indent=2),encoding='utf-8')
    print('Setup complete:',TOOLS,flush=True)

if __name__=='__main__':install()
