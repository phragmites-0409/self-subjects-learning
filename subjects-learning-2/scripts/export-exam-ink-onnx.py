"""Export verified data-only handwriting segmentation weights for local CPU use."""
import hashlib,json,os
from pathlib import Path
from runtime_paths import RUNTIME_ROOT, portable_manifest, read_manifest
os.environ['HF_HUB_OFFLINE']='1'
import numpy as np
import torch
import segmentation_models_pytorch as smp
from safetensors.torch import load_file
import onnxruntime as ort

ROOT=RUNTIME_ROOT/'models/exam-ink-seg'
metadata=read_manifest(ROOT/'manifest.json')
assert hashlib.sha256((ROOT/'model.safetensors').read_bytes()).hexdigest()==metadata['sha256']
torch.set_num_threads(4)
model=smp.UnetPlusPlus(encoder_name='resnet50',encoder_weights=None,in_channels=3,classes=1,decoder_attention_type='scse',activation=None)
state={key.removeprefix('_orig_mod.'):value for key,value in load_file(str(ROOT/'model.safetensors')).items()}
model.load_state_dict({key:value for key,value in state.items() if key in model.state_dict()},strict=True)
model.eval();del state
torch.manual_seed(2026);sample=torch.rand(1,3,256,256)
target=ROOT/'model.onnx'
torch.onnx.export(model,sample,str(target),input_names=['image'],output_names=['logits'],opset_version=17,dynamo=False,dynamic_axes={'image':{2:'height',3:'width'},'logits':{2:'height',3:'width'}})
settings=ort.SessionOptions();settings.intra_op_num_threads=4;settings.inter_op_num_threads=1
session=ort.InferenceSession(str(target),sess_options=settings,providers=['CPUExecutionProvider'])
with torch.inference_mode():expected=model(sample).numpy()
actual=session.run(None,{'image':sample.numpy()})[0]
error=float(np.max(np.abs(actual-expected)))
assert error<.002,error
manifest={**{key:value for key,value in metadata.items() if key!='production_enabled'},'onnx_file':str(target),'onnx_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'onnx_bytes':target.stat().st_size,'onnx_max_logit_difference':error,'normalization':{'mean':[.485,.456,.406],'std':[.229,.224,.225]},'full_page_automatic_enabled':False,'brush_refinement_enabled':True,'usage':'Only refine an explicit user removal brush; always preview, never automatic full-page erasure'}
(ROOT/'manifest.json').write_text(json.dumps(portable_manifest(manifest),ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(manifest),flush=True)
