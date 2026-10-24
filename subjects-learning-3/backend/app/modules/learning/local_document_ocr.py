"""Pinned, loopback-only document model. Never calls an external provider."""
import base64,hashlib,json,math,os,secrets,socket,subprocess,tempfile,threading,time,urllib.request
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from app.core.errors import AppError
from app.core.runtime import RUNTIME_ROOT, read_manifest

BASE=RUNTIME_ROOT
MODEL=BASE/'models/glm-ocr';STATE=BASE/'document-ocr/service';PORT=8053
LOCK=threading.RLock();PROCESS=None

def configuration():
    try:
        config=read_manifest(MODEL/'manifest.json')
        entries=config['files'][:2]
        executable=Path(config['engine_dir'])/'llama-server.exe'
        if len(entries)==2 and executable.is_file() and executable.resolve().is_relative_to((BASE/'document-ocr').resolve()) and all(Path(item['path']).resolve().is_relative_to(MODEL.resolve()) and Path(item['path']).is_file() and Path(item['path']).stat().st_size==item['bytes'] for item in entries):return config
    except (OSError,ValueError,KeyError,TypeError):pass
    return None

def status():
    return {'ready':configuration() is not None,'engine':'GLM-OCR Q8 local','external':False,'acceptance':'strict multi-view'}

@lru_cache(maxsize=4)
def verify_file(path,digest,size,modified):
    checksum=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):checksum.update(block)
    if checksum.hexdigest()!=digest:raise AppError('DOCUMENT_MODEL_INVALID','本地文档模型校验失败',409)

def service():
    global PROCESS
    with LOCK:
        config=configuration()
        if not config:raise AppError('DOCUMENT_MODEL_NOT_READY','本地文档识别模型尚未准备好',409)
        STATE.mkdir(parents=True,exist_ok=True)
        keyfile=STATE/'api-key.txt'
        if not keyfile.exists():keyfile.write_text(secrets.token_urlsafe(32),encoding='utf-8')
        key=keyfile.read_text(encoding='utf-8').strip()
        headers={'Authorization':'Bearer '+key}
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(urllib.request.Request(f'http://127.0.0.1:{PORT}/v1/models',headers=headers),timeout=2) as response:
                models=json.load(response)
                if any(item.get('id')=='subjects-learning-glm-ocr' for item in models.get('data',[])):return opener,key
        except OSError:pass
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1',PORT))==0:
                raise AppError('DOCUMENT_SERVICE_BUSY','本地文档识别端口被占用，未替换现有服务',409)
        for item in config['files'][:2]:
            path=Path(item['path']);verify_file(str(path),item['sha256'],path.stat().st_size,path.stat().st_mtime_ns)
        executable=Path(config['engine_dir'])/'llama-server.exe'
        if not executable.resolve().is_relative_to((BASE/'document-ocr').resolve()) or not executable.is_file():
            raise AppError('DOCUMENT_MODEL_NOT_READY','本地识别运行程序缺失',409)
        args=[str(executable),'-m',config['files'][0]['path'],'--mmproj',config['files'][1]['path'],'--alias','subjects-learning-glm-ocr','--host','127.0.0.1','--port',str(PORT),'--api-key-file',str(keyfile),'--no-webui','--cors-origins','localhost','--device','Vulkan0','-ngl','99','--ctx-size','4096','--parallel','1','--cache-ram','64','--threads','4','--batch-size','256','--ubatch-size','128','--reasoning-format','none','--sleep-idle-seconds','180']
        # This device produced nonfinite logits in Vulkan. Use CPU throughout
        # until a GPU runtime has passed cold-start transcription checks.
        args.extend(['--flash-attn','off','--no-cache-prompt','--no-mmproj-offload'])
        args[args.index('--device')+1]='none'
        args[args.index('-ngl')+1]='0'
        env={**os.environ,'LLAMA_CACHE':str(BASE/'cache/llama'),'TEMP':str(BASE/'tmp'),'TMP':str(BASE/'tmp')}
        output=(STATE/'server-output.log').open('ab');errors=(STATE/'server-error.log').open('ab')
        try:PROCESS=subprocess.Popen(args,env=env,cwd=executable.parent,stdout=output,stderr=errors,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        finally:output.close();errors.close()
        (STATE/'process.json').write_text(json.dumps({'pid':PROCESS.pid,'executable':str(executable),'port':PORT}),encoding='utf-8')
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            if PROCESS.poll() is not None:raise AppError('DOCUMENT_MODEL_START_FAILED','本地文档模型启动失败，请查看 runtimes/document-ocr/service 中的识别日志',503)
            try:
                with opener.open(urllib.request.Request(f'http://127.0.0.1:{PORT}/health',headers=headers),timeout=2) as response:
                    if response.status==200:return opener,key
            except OSError:time.sleep(.25)
        raise AppError('DOCUMENT_MODEL_START_TIMEOUT','本地文档模型仍在加载，请稍后重试',503)


def recognize(image,task='formula',max_tokens=512):
    if task not in ('formula','text','table'):raise ValueError('Unsupported document task')
    config=configuration()
    if not config:raise AppError('DOCUMENT_MODEL_NOT_READY','本地文档模型尚未准备好',409)
    if image.width*image.height>4_000_000:raise AppError('DOCUMENT_CROP_TOO_LARGE','请分块识别复杂内容',422)
    buffer=BytesIO();image.convert('RGB').save(buffer,'PNG');raw=buffer.getvalue()
    cache=BASE/'cache/document-ocr';cache.mkdir(parents=True,exist_ok=True)
    cache_key=hashlib.sha256((config['files'][0]['sha256']+config['files'][1]['sha256']+task+str(max_tokens)+'v5-cpu').encode()+raw).hexdigest()
    path=cache/f'{cache_key}.json'
    if path.exists():
        data=json.loads(path.read_text(encoding='utf-8'));return {**data,'cached':True}
    opener,key=service()
    prompt={'formula':'Formula Recognition:','text':'Text Recognition:','table':'Table Recognition:'}[task]
    payload={'messages':[{'role':'user','content':[{'type':'text','text':prompt},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(raw).decode()}}]}],'temperature':0,'top_p':1,'max_tokens':max_tokens,'logprobs':True,'top_logprobs':1,'seed':42}
    started=time.perf_counter()
    request=urllib.request.Request(f'http://127.0.0.1:{PORT}/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
    with LOCK,opener.open(request,timeout=120) as response:result=json.load(response)
    choice=result['choices'][0];text=choice['message'].get('content') or ''
    logs=(choice.get('logprobs') or {}).get('content',[])
    if any(item.get('logprob') is not None and not math.isfinite(item['logprob']) for item in logs):
        raise AppError('DOCUMENT_ENGINE_OUTPUT','本地文档模型置信数据异常，本页剩余公式保留原图',503)
    token_data=[{'token':item.get('token',''),'probability':math.exp(min(0,item['logprob']))} for item in logs if item.get('logprob') is not None]
    probabilities=[item['probability'] for item in token_data]
    if not probabilities or any(ord(char)<32 and char not in '\t\n\r' for char in text):
        raise AppError('DOCUMENT_ENGINE_OUTPUT','本地文档模型输出异常，本页剩余公式保留原图',503)
    data={'text':text,'mean_probability':sum(probabilities)/len(probabilities) if probabilities else None,'min_probability':min(probabilities) if probabilities else None,'weak_tokens':[item for item in token_data if item['probability']<.95],'finish_reason':choice.get('finish_reason'),'tokens':len(probabilities),'seconds':round(time.perf_counter()-started,2),'engine':'GLM-OCR Q8 local','cached':False,'task':task}
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=cache,suffix='.json',delete=False) as temporary:
        json.dump(data,temporary,ensure_ascii=False);name=temporary.name
    Path(name).replace(path)
    return data
