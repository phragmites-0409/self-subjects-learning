from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.devices.service import DeviceService


def require_device(scope: str):
    def dependency(x_device_key: str | None = Header(default=None), db: Session = Depends(get_db)):
        return DeviceService().authenticate(db, x_device_key or "", scope)

    return dependency
