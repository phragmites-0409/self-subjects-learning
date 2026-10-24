from PIL import Image,ImageDraw
from app.modules.learning import structured_ocr as document,formula_rendering
from app.modules.learning.local_ocr import Line
from app.modules.learning.question_pages import merge_pages


def view(text,mean=.998,weak=None):
    return {'text':text,'mean_probability':mean,'finish_reason':'stop','weak_tokens':weak or []}


def test_nonfinite_engine_confidence_can_never_pass_acceptance():
    for confidence in (float('nan'),float('inf'),1.01,None):
        assert not document.accepted([view('x=2',confidence)]*2)[0]


def test_confident_shared_model_error_is_vetoed_by_phase_evidence(monkeypatch):
    monkeypatch.setattr(formula_rendering,'render',lambda text:(b'',1,1))
    wrong=view(r'\mathrm{H}_{2}\mathrm{O}(1)')
    assert not document.accepted([wrong,wrong],source='H2O(l)')[0]
    right=view(r'\mathrm{H}_{2}\mathrm{O}(\mathrm{l})')
    assert document.accepted([right,right],source='H2O(l)')[0]


def test_radical_dot_cannot_disappear_at_high_model_probability(monkeypatch):
    monkeypatch.setattr(formula_rendering,'render',lambda text:(b'',1,1))
    result=view(r'H_2O_2\rightarrow2HO')
    assert not document.accepted([result,result],source='H2O2→2HO.')[0]
    dotted=view(r'H_2O_2\rightarrow2HO\cdot')
    assert document.accepted([dotted,dotted],source='H2O2→2HO.')[0]


def test_threshold_critical_digits_disagreement_and_renderer_are_independent_gates(monkeypatch):
    monkeypatch.setattr(formula_rendering,'render',lambda text:(b'',1,1))
    result=view(r'a_{n+1}=\frac{2a_n+1}{a_n+2}')
    assert document.accepted([result,result])[0]
    assert not document.accepted([result,view(result['text'],.984)])[0]
    assert not document.accepted([result,view(result['text'].replace('2a','3a'))])[0]
    assert not document.accepted([result,view(result['text'],weak=[{'token':'2','probability':.94}])])[0]
    monkeypatch.setattr(formula_rendering,'render',lambda text:(_ for _ in ()).throw(ValueError('unsupported')))
    assert not document.accepted([result,result])[0]
    assert document.canonical(r'\Delta H_2')==r'\Delta{}H_2'


def test_chemical_atom_uses_literal_confident_source_only():
    words=[{'score':.999} for _ in range(4)]
    views=[view(r'\mathrm{和}\mathrm{C}_3\mathrm{H}_8\mathrm{的}')]*2
    assert document.chemical_atom('C3H8',words,views,.985)==r'\mathrm{C}_{3}\mathrm{H}_{8}'
    assert document.chemical_atom('C2H8',words,views,.985) is None
    assert document.chemical_atom('C3H8',[{'score':.98}],views,.985) is None


def test_fraction_requires_observed_rule_and_preserves_full_source_width():
    image=Image.new('RGB',(600,400),'white');draw=ImageDraw.Draw(image)
    draw.line((230,198,290,198),fill='black',width=2)
    num=Line('E0',[.39,.43,.47,.48],.99,.05,words=[{'text':'E0','box':[.39,.43,.47,.48],'score':.99}])
    den=Line('T',[.4,.51,.46,.56],.99,.05,words=[{'text':'T','box':[.4,.51,.46,.56],'score':.99}])
    combined=document.fraction_lines(image,[num,den],[])
    assert len(combined)==1 and combined[0].words[0]['fraction']
    box=document.span_box(image,combined[0],combined[0].words)
    assert box[0]<=num.box[0] and box[2]>=num.box[2]
    assert len(document.fraction_lines(Image.new('RGB',image.size,'white'),[num,den],[]))==2


def test_page_merge_keeps_inline_placement_and_formula_provenance():
    output={'stem':'条件[[图块:1]]','inline_regions':[{'key':'1','kind':'formula','box':[.2,.2,.4,.3],'line_height':.02,'placement':'inline'}],
            'formula_audit':[{'box':[.2,.2,.4,.3],'accepted':False,'source':'x','reason':'不同'}]}
    result=merge_pages([output,output],[{'box':[0,0,1,.4]},{'box':[0,.5,1,1]}])
    assert result['inline_regions'][1]['key']=='2'
    assert result['inline_regions'][1]['placement']=='inline'
    assert result['formula_audit'][1]['page']==2
    assert result['formula_audit'][1]['box']==[.2,.6,.4,.65]


def test_formula_fallback_in_text_choices_keeps_option_labels(monkeypatch):
    def words(text,y):
        return [{'text':char,'box':[.1+i*.025,y,.12+i*.025,y+.03],'score':.99} for i,char in enumerate(text)]
    lines=[Line('选择正确的选项',[.1,.1,.9,.14],.99,.03,words=words('选择正确的选项',.1)),
           Line('[A]H2',[.1,.2,.4,.24],.99,.03,words=words('[A]H2',.2)),
           Line('[B]H3',[.1,.3,.4,.34],.99,.03,words=words('[B]H3',.3))]
    monkeypatch.setattr(document.local_document_ocr,'recognize',lambda *args:view('bad',.5))
    result=document.transcribe(Image.new('RGB',(600,400),'white'),lines,[],{'options':['[A] H2','[B] H3']})
    assert result['options']==['[A] [[图块:1]]','[B] [[图块:2]]']
    assert '图块' not in result['stem']
    graphic=document.transcribe(Image.new('RGB',(600,400),'white'),lines,[],{'options':['[A]','[B]']})
    assert graphic is None


def test_unavailable_engine_is_not_retried_for_every_formula(monkeypatch):
    calls=[]
    def broken(*args):
        calls.append(args)
        raise RuntimeError('invalid local model output')
    monkeypatch.setattr(document.local_document_ocr,'recognize',broken)
    def row(text,y):
        words=[{'text':c,'box':[.1+i*.05,y,.14+i*.05,y+.03],'score':.999} for i,c in enumerate(text)]
        return Line(text,[.1,y,.5,y+.03],.999,.03,words=words)
    result=document.transcribe(Image.new('RGB',(600,400),'white'),[row('H2',.1),row('H3',.3)],[],{})
    assert len(calls)==1 and len(result['inline_regions'])==2
    assert all(not item['accepted'] and 'invalid local model output' in item['reason'] for item in result['formula_audit'])


def test_reaction_tail_not_discarded_by_semantic_handwriting_false_positive():
    import numpy as np
    from app.modules.learning.printed_document import filter_printed
    image=Image.new('RGB',(100,100),'black')
    anchor=Line('④2HO•→',[.03,.15,.12,.18],.95)
    tail=Line('1O2+H2O',[.124,.15,.24,.18],.8)
    note=Line('2x+3=7',[.7,.7,.9,.8],.99)
    kept,_,_=filter_printed(image,[anchor,tail,note],[],np.ones((100,100)))
    assert tail in kept and note not in kept


def test_source_indices_veto_shared_high_probability_formula_error(monkeypatch):
    monkeypatch.setattr(formula_rendering,'render',lambda text:(b'',1,1))
    wrong=view(r'C_2H_8')
    words=[{'text':c,'score':.999} for c in 'C3H8']
    assert not document.accepted([wrong,wrong],source='C3H8',words=words)[0]
    less=view('x<y')
    assert document.accepted([less,less],source='x<y')[0]


def test_enhancement_previews_and_stale_edits_preserve_originals(client,db,png_bytes,monkeypatch):
    from test_printed_document import make_inline_question
    qid,q=make_inline_question(client,db,png_bytes,monkeypatch)
    url=f'/api/v1/learning/questions/{qid}';source=q['data']['inline_images'][0]['asset_id']
    before=client.get(f'/api/v1/assets/{source}/download').content
    response=client.post(url+'/image/enhance-preview',json={'asset_id':source,'mode':'paper'})
    assert response.status_code==200
    staged=response.json();draft=staged['data']['image_repair_draft']
    assert draft['adoptable'] and staged['data']['inline_images'][0]['asset_id']==source
    assert client.get(f'/api/v1/assets/{source}/download').content==before
    assert client.patch(url,json={'version_id':'stale','content':{'stem':'bad'}}).status_code==409
    adopted=client.post(url+'/image/repair-adopt',json={'asset_id':draft['asset_id']}).json()
    assert adopted['data']['inline_images'][0]['asset_id']!=source and adopted['data']['image_review_required']
    replaced=client.patch(url,json={'version_id':adopted['version_id'],'content':{'stem':'公式已改为 $x=2$'}}).json()
    assert replaced['data']['inline_images']==[] and replaced['content']['inline_images']==[]
