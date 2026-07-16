import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

from PySide6.QtWidgets import QApplication

from dxb_runway.database import Database
from dxb_runway.dialogs import OnboardingDialog
from dxb_runway.main_window import MainWindow


def app():
    return QApplication.instance() or QApplication([])


def test_first_run_onboarding_constructs(tmp_path: Path):
    application=app(); db=Database(tmp_path/"data.db")
    assert db.get_setting("onboarding_complete")=="0"
    dialog=OnboardingDialog(db)
    assert dialog.pages.count()==4
    assert dialog.fields["uk_cash_gbp"].value()==2000
    dialog.close()


def test_every_major_screen_constructs_and_navigates(tmp_path: Path):
    application=app(); db=Database(tmp_path/"data.db"); db.seed_demo()
    window=MainWindow(db)
    assert set(window.pages)=={"dashboard","vehicles","transactions","debt","earnings","scenarios","budgets","calendar","goals","reports","settings"}
    for key,page in window.pages.items():
        window.navigate(key)
        assert window.stack.currentWidget() is page
    window.close()
