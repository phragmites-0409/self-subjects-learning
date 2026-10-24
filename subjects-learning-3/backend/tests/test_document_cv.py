import numpy as np
from PIL import Image,ImageDraw
from app.modules.learning.document_cv import normalize_illumination,rotate_preserving_edges,rectify_line
from app.modules.learning.reading_order import paragraphs
from app.modules.learning.local_ocr import Line

def test_shadow_normalization_retains_decimal_and_faint_rule():
    image=Image.new('RGB',(300,130),(180,170,155));draw=ImageDraw.Draw(image)
    draw.line((20,70,270,70),fill=(130,125,120),width=1);draw.ellipse((100,90,102,92),fill='black')
    normalized,ink,background=normalize_illumination(image)
    assert np.asarray(normalized)[70,80].mean()<np.asarray(normalized)[60,80].mean()-20
    assert normalized.getpixel((101,91))==(0,0,0)
    assert ink.size==background.size==image.size and image.getpixel((80,60))==(180,170,155)

def test_geometric_view_keeps_edges_and_does_not_mutate_original():
    image=Image.new('RGB',(200,80),'white');ImageDraw.Draw(image).rectangle((0,0,199,79),outline='black',width=2)
    corrected=rotate_preserving_edges(image,4)
    assert corrected.width>200 and corrected.height>80 and image.size==(200,80)
    line=Line('x=2',[.1,.2,.9,.8],1,None,[[.1,.2],[.9,.3],[.9,.8],[.1,.7]])
    assert rectify_line(image,line).width>=160

def test_physical_wraps_join_but_question_parts_and_formulas_stay_separate():
    lines=[Line('已知一带电粒子只在电场力作用下',[.1,.1,.9,.13]),Line('从A运动到B，求其运动时间。',[.1,.14,.9,.17]),Line('(1) 求速度。',[.1,.20,.8,.23]),Line('(2) 求加速度。',[.1,.25,.8,.28]),Line('$$a=F/m$$',[.2,.32,.8,.36])]
    text=paragraphs(lines)
    assert '作用下从A' in text and '下\n' not in text
    assert '\n\n(1)' in text and '\n\n(2)' in text and '\n\n$$' in text


def test_fold_free_warp_still_detects_cutting_off_visible_diagram():
    from app.modules.learning.document_unwarp import clipped_ink_fraction
    image=Image.new('RGB',(200,100),'white')
    ImageDraw.Draw(image).rectangle((5,10,35,80),fill='black')
    x,y=np.meshgrid(np.linspace(-1,1,20),np.linspace(-1,1,12))
    assert clipped_ink_fraction(image,np.stack((x,y)))==0
    assert clipped_ink_fraction(image,np.stack((x*.7+.3,y)))>.99
