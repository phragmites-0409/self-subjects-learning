"""Check saved API authentication/model listing without a billed image request."""
import json
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
os.environ['DATA_DIR']=str(ROOT/'data')
sys.path.insert(0,str(ROOT/'backend'))
from app.db.session import SessionLocal
from app.modules.learning.ai import configuration
import httpx
with SessionLocal() as db:
    config=configuration(db)
    result={'configured':bool(config.deepseek_api_key),'billed_image_requests':0}
    if config.deepseek_api_key:
        try:
            response=httpx.get(config.deepseek_base_url.rstrip('/')+'/models',headers={'Authorization':'Bearer '+config.deepseek_api_key},timeout=15)
            result['model_listing_http_status']=response.status_code
            if response.is_success:
                models=[item.get('id') for item in response.json().get('data',[])]
                result['selected_vision_model_listed']=config.deepseek_vision_model in models
        except httpx.HTTPError as error:
            result['authentication_check_error']=type(error).__name__
(ROOT/'data/logs/api-readiness.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
