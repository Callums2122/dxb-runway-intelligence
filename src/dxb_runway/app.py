from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import traceback

from PySide6.QtCore import QStandardPaths, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .database import Database
from .dialogs import OnboardingDialog
from .main_window import MainWindow
from .style import APP_QSS


def resource_path(relative: str) -> Path:
    base=Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parents[2]))
    return base/relative


def data_dir(override: str | None = None) -> Path:
    if override:return Path(override)
    root=Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    return root


def place_on_secondary_display(window, app: QApplication, preferred_name: str = "") -> str:
    """Centre the main window on a non-primary display and return its name."""
    primary=app.primaryScreen()
    secondary=[screen for screen in app.screens() if screen is not primary]
    if not secondary:return ""
    target=next((screen for screen in secondary if screen.name()==preferred_name),secondary[0])
    area=target.availableGeometry()
    width=min(window.width(),area.width());height=min(window.height(),area.height())
    window.resize(width,height)
    window.move(area.x()+max(0,(area.width()-width)//2),area.y()+max(0,(area.height()-height)//2))
    return target.name()


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description="DXB RUNWAY Intelligence")
    parser.add_argument("--data-dir",help="Override AppData location for testing")
    parser.add_argument("--demo",action="store_true",help="Seed representative local demo data")
    parser.add_argument("--skip-onboarding",action="store_true")
    parser.add_argument("--screenshot",help="Save a screenshot after launch")
    parser.add_argument("--page",default="intelligence",help="Page to open for screenshot or testing")
    parser.add_argument("--exit-after-ms",type=int,default=0)
    parser.add_argument("--nightly-deal-drive-sync",action="store_true",help=argparse.SUPPRESS)
    args=parser.parse_args(argv)
    QApplication.setOrganizationName("DXB Runway"); QApplication.setApplicationName("DXB RUNWAY Intelligence"); QApplication.setApplicationVersion("3.0.0")
    app=QApplication(sys.argv[:1]); app.setStyle("Fusion"); app.setStyleSheet(APP_QSS)
    icon=resource_path("assets/dxb_runway.icns" if sys.platform=="darwin" else "assets/dxb_runway.ico")
    if not icon.exists():icon=resource_path("assets/dxb_runway_icon.png")
    if icon.exists():app.setWindowIcon(QIcon(str(icon)))
    try:
        db=Database(data_dir(args.data_dir)/"dxb_runway_intelligence.db")
        if args.nightly_deal_drive_sync:
            from .deal_drive import nightly_sync
            nightly_sync(db)
            return 0
        if args.demo:db.seed_demo()
        if db.get_setting("onboarding_complete","0")!="1" and not args.skip_onboarding:
            onboarding=OnboardingDialog(db)
            if onboarding.exec()!=OnboardingDialog.DialogCode.Accepted:return 0
        window=MainWindow(db,icon);window.navigate(args.page);window.show()
        def place_window():
            display_name=place_on_secondary_display(window,app,db.get_setting("preferred_secondary_display",""))
            if display_name:db.set_setting("preferred_secondary_display",display_name)
        QTimer.singleShot(100,place_window)
        if args.screenshot:
            destination=Path(args.screenshot);destination.parent.mkdir(parents=True,exist_ok=True)
            def capture():
                pixmap=window.grab();pixmap.save(str(destination),"PNG")
            QTimer.singleShot(5000,capture)
        if args.exit_after_ms:QTimer.singleShot(args.exit_after_ms,app.quit)
        return app.exec()
    except Exception as error:
        log_dir=data_dir(args.data_dir);log_dir.mkdir(parents=True,exist_ok=True);(log_dir/"crash.log").write_text(traceback.format_exc(),encoding="utf-8")
        if args.nightly_deal_drive_sync:
            return 1
        QMessageBox.critical(None,"DXB RUNWAY Intelligence could not start",f"{error}\n\nA diagnostic log was saved locally.")
        return 1


if __name__=="__main__":raise SystemExit(main())
