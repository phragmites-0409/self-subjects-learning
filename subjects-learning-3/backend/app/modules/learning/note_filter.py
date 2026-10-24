"""Explicit same-question handwriting masks, applied only to derived question images."""
from PIL import ImageDraw


def boxes_for(q, state):
    settings=state.data.get("note_filters",{})
    return settings.get("boxes",[]) if settings.get("source_asset_id")==q.source_asset_id else []


def within_page(boxes, frame):
    output=[]
    for box in boxes:
        left,top,right,bottom=max(box[0],frame[0]),max(box[1],frame[1]),min(box[2],frame[2]),min(box[3],frame[3])
        if right<=left or bottom<=top:continue
        output.append([(left-frame[0])/(frame[2]-frame[0]),(top-frame[1])/(frame[3]-frame[1]),(right-frame[0])/(frame[2]-frame[0]),(bottom-frame[1])/(frame[3]-frame[1])])
    return output


def apply(image, boxes):
    result=image.copy();draw=ImageDraw.Draw(result)
    for box in boxes:
        draw.rectangle((round(box[0]*image.width),round(box[1]*image.height),max(round(box[0]*image.width),round(box[2]*image.width)-1),max(round(box[1]*image.height),round(box[3]*image.height)-1)),fill="white")
    return result
