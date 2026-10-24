"""Expose the official ONNX model's low-resolution sampling mesh for auditing."""
import hashlib,json
from pathlib import Path
from runtime_paths import RUNTIME_ROOT, portable_manifest, read_manifest
import onnx
root=RUNTIME_ROOT/'models/uvdoc'
data=read_manifest(root/'manifest.json')
assert hashlib.sha256((root/'inference.onnx').read_bytes()).hexdigest()==data['sha256']
model=onnx.load(root/'inference.onnx')
producers={name:node for node in model.graph.node for name in node.output}
sample=next(node for node in model.graph.node if node.op_type=='GridSample')
node=producers[sample.input[1]]
while node.op_type=='Identity':node=producers[node.input[0]]
assert node.op_type=='Transpose'
node=producers[node.input[0]];assert node.op_type=='Resize'
grid=node.input[0]
model.graph.output.append(onnx.helper.make_tensor_value_info(grid,onnx.TensorProto.FLOAT,[None,2,None,None]))
onnx.checker.check_model(model)
target=root/'inference-grid.onnx';onnx.save(model,target)
data.update(grid_path=str(target),grid_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),conversion='Expose pre-resize mesh; original operators/weights unchanged')
(root/'manifest.json').write_text(json.dumps(portable_manifest(data),indent=2),encoding='utf-8')
print(data['grid_sha256'])
