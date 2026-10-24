"""Isolated local UI/PDF fixture. Never writes to the user's learning database."""
import os
import sys
from pathlib import Path
from io import BytesIO
import json

root = Path(__file__).resolve().parents[1]
verification = root / "data/tmp/core-verification"
os.environ["DATA_DIR"] = str(verification)
os.environ["DEEPSEEK_API_KEY"] = ""
sys.path.insert(0, str(root / "backend"))
from PIL import Image, ImageDraw, ImageFont
from app.db.session import init_db, SessionLocal
from app.db.models import Asset, Question, KnowledgeNode
from app.modules.learning import service as f
from app.modules.learning.ai import save_configuration
from app.api.v1.questions import service
from app.modules.learning.pdf import export_pdf
from app.storage.local_store import LocalFilesystemContentStore

init_db()
output = root / "output/pdf"
output.mkdir(parents=True, exist_ok=True)
with SessionLocal() as db:
    if not db.query(Question).count():
        n = KnowledgeNode(subject="数学", kind="type", name="验证用 · 方程与图形", summary="仅用于开发验证，不是用户学习记录。")
        db.add(n);db.commit()
        for index, stem in enumerate((r"已知 $x^2-3x+2=0$，求方程的两个根。", r"如图，在直角三角形ABC中，$AB=3$，$AC=4$，求 $BC=\sqrt{AB^2+AC^2}$。")):
            q=Question(subject="数学",status="approved")
            db.add(q);db.commit()
            service().update(db,q,{"content":{"stem":stem,"has_diagram":index==1,"options":[]}})
            s=f.state_for(db,q.id);s.topic_id=n.id;s.answer="x=1或2" if index==0 else "5";s.answer_confirmed=True
            if index:
                im=Image.new("RGB",(900,440),"white");draw=ImageDraw.Draw(im)
                font=ImageFont.truetype("C:/Windows/Fonts/simhei.ttf",28)
                draw.line([(160,80),(160,340),(550,340),(160,80)],fill="black",width=3)
                for pos,text in (((115,350),"A"),((570,340),"B"),((145,35),"C"),((340,350),"3"),((120,195),"4")):
                    draw.text(pos,text,fill="black",font=font)
                buffer=BytesIO();im.save(buffer,"PNG")
                store=LocalFilesystemContentStore();key,digest=store.put_bytes("original-images",buffer.getvalue(),".png")
                a=Asset(kind="image",storage_key=key,sha256=digest,mime_type="image/png",byte_size=len(buffer.getvalue()),width=900,height=440)
                db.add(a);db.flush();q.source_asset_id=a.id;s.data={"crop_asset_id":a.id}
            f.mark_error(db,q.id,f.today(),f"verification-{index}",target=f.today())
        db.commit()
    save_configuration(db,{"key":""})
    f.plan(db)
    e=db.query(f.LearningEvent).filter(f.LearningEvent.kind=="error").first()
    pdf=export_pdf(db,e.id)
    (output/"核心流程打印验证.pdf").write_bytes(pdf.read_bytes())
    (verification/"fixture.json").write_text(json.dumps({"round_id":e.data["round_id"],"event_id":e.id},ensure_ascii=False),encoding="utf-8")
print("Isolated UI fixture and PDF ready")
