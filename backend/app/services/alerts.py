from app.db import (
    create_price_alert, get_alerts_for_user, delete_alert, update_alert,
)

VALID_ALERT_TYPES = {"price_above", "price_below", "scan_signal"}
VALID_SCAN_TYPES = {"bird_beak", "near_ema60", "volume_breakout", "institutional_buying"}


class AlertError(Exception):
    pass


def add_alert(user_id: int, ticker: str, alert_type: str,
               target_price: float | None = None, scan_type: str | None = None) -> int:
    if alert_type not in VALID_ALERT_TYPES:
        raise AlertError("alert_type 需為 price_above / price_below / scan_signal")
    if not ticker:
        raise AlertError("ticker 不可為空")

    if alert_type in ("price_above", "price_below"):
        if not target_price or target_price <= 0:
            raise AlertError("target_price 需大於 0")
        scan_type = None
    else:
        if scan_type not in VALID_SCAN_TYPES:
            raise AlertError(f"scan_type 需為 {VALID_SCAN_TYPES} 其中之一")
        target_price = None

    return create_price_alert(user_id, ticker, alert_type, target_price, scan_type)


def list_alerts(user_id: int) -> list[dict]:
    return get_alerts_for_user(user_id)


def remove_alert(user_id: int, alert_id: int):
    if not delete_alert(alert_id, user_id):
        raise AlertError("提醒不存在或無權限刪除")


def edit_alert(user_id: int, alert_id: int, target_price: float | None = None,
                scan_type: str | None = None):
    if target_price is not None and target_price <= 0:
        raise AlertError("target_price 需大於 0")
    if scan_type is not None and scan_type not in VALID_SCAN_TYPES:
        raise AlertError(f"scan_type 需為 {VALID_SCAN_TYPES} 其中之一")
    if not update_alert(alert_id, user_id, target_price, scan_type):
        raise AlertError("提醒不存在或無權限編輯")
