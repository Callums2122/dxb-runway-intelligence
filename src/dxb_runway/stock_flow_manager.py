from __future__ import annotations
from PySide6.QtCore import QObject,QRunnable,QThreadPool,QTimer,Signal
from .database import Database
from .stock_flow import configured_stock_flow_service

class _Signals(QObject):finished=Signal(object);failed=Signal(str)
class _Job(QRunnable):
    def __init__(self,db):super().__init__();self.db=db;self.signals=_Signals()
    def run(self):
        try:
            service=configured_stock_flow_service(self.db)
            if service is None:raise RuntimeError("Stock Flow sync is not connected")
            self.signals.finished.emit(service.sync())
        except Exception as error:self.signals.failed.emit(str(error))

class StockFlowManager(QObject):
    status_changed=Signal(str,bool);data_changed=Signal()
    def __init__(self,db:Database,parent=None):
        super().__init__(parent);self.db=db;self._busy=False;self._job=None;self.timer=QTimer(self);self.timer.setInterval(300_000);self.timer.timeout.connect(self.sync);self.timer.start();QTimer.singleShot(3500,self.sync)
    def sync(self):
        if self._busy or configured_stock_flow_service(self.db) is None:return
        self._busy=True;self.status_changed.emit("Checking Stock Flow…",True);job=_Job(self.db);self._job=job;job.signals.finished.connect(self._finished);job.signals.failed.connect(self._failed);QThreadPool.globalInstance().start(job)
    def _finished(self,result):
        self._busy=False;changed=int(getattr(result,"linked",0))+int(getattr(result,"updated",0));review=int(getattr(result,"review",0));self.status_changed.emit(f"Stock Flow · {changed} updates"+(f" · {review} review" if review else ""),True)
        if changed or review:self.data_changed.emit()
    def _failed(self,message):self._busy=False;self.db.set_setting("stock_flow_sync_last_error",message);self.status_changed.emit("Stock Flow unavailable",False)
