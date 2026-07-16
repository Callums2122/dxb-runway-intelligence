from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, QDateTime, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDateTimeEdit, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QStackedWidget, QTextEdit, QVBoxLayout, QWidget
)

from .database import Database
from .style import COLORS


class MoneyBox(QDoubleSpinBox):
    def __init__(self, maximum: float = 100_000_000, decimals: int = 2):
        super().__init__()
        self.setRange(0, maximum); self.setDecimals(decimals); self.setGroupSeparatorShown(True); self.setSingleStep(50)


class OnboardingDialog(QDialog):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Welcome to DXB RUNWAY")
        self.setMinimumSize(760, 600)
        self.setModal(True)
        root = QVBoxLayout(self); root.setContentsMargins(32, 28, 32, 28); root.setSpacing(18)
        header = QLabel("BUILD YOUR FINANCIAL RUNWAY")
        header.setObjectName("pageTitle"); root.addWidget(header)
        self.subtitle = QLabel("Private by design. Your data never leaves this PC."); self.subtitle.setObjectName("muted"); root.addWidget(self.subtitle)
        self.pages = QStackedWidget(); root.addWidget(self.pages, 1)
        self.fields: dict[str, QWidget] = {}
        self._intro(); self._starting_position(); self._dubai_plan(); self._protection()
        footer = QHBoxLayout(); self.step = QLabel("1 / 4"); self.step.setObjectName("muted"); footer.addWidget(self.step); footer.addStretch()
        self.back = QPushButton("Back"); self.back.clicked.connect(self.previous); self.back.setEnabled(False)
        self.next = QPushButton("Continue"); self.next.setProperty("primary", True); self.next.clicked.connect(self.advance)
        footer.addWidget(self.back); footer.addWidget(self.next); root.addLayout(footer)

    def _page(self, title: str, copy: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(0, 20, 0, 0); layout.setSpacing(16)
        label = QLabel(title); label.setStyleSheet("font-size:20px;font-weight:700"); layout.addWidget(label)
        text = QLabel(copy); text.setObjectName("muted"); text.setWordWrap(True); layout.addWidget(text)
        self.pages.addWidget(page); return page, layout

    def _intro(self) -> None:
        _, layout = self._page("A calm command centre for the move", "DXB RUNWAY separates cash, debt, protected reserves, deposits and future income. Credit and pending commission are never presented as spendable cash.")
        panel = QFrame(); panel.setProperty("card", True); box = QVBoxLayout(panel); box.setContentsMargins(22, 20, 22, 20)
        for icon, title, body in [("01", "LOCAL ONLY", "SQLite, receipts and backups stay on this computer."),
                                  ("02", "SAFETY FIRST", "See survival runway before upside scenarios."),
                                  ("03", "EDITABLE", "Every starting assumption can be changed later.")]:
            line = QLabel(f"{icon}  <b>{title}</b><br><span style='color:#8894a7'>{body}</span>"); line.setTextFormat(Qt.TextFormat.RichText); line.setStyleSheet("padding:8px"); box.addWidget(line)
        layout.addWidget(panel); layout.addStretch()

    def _starting_position(self) -> None:
        _, layout = self._page("Starting position", "Enter real cash separately from available credit. The latter remains debt capacity, never wealth.")
        form = QFormLayout(); form.setSpacing(12)
        for key, label, value in [("uk_cash_gbp", "UK cash savings (GBP)", 2000), ("available_credit_gbp", "Available credit (GBP)", 4000), ("gbp_aed_rate", "GBP → AED exchange rate", 4.928313)]:
            box = MoneyBox(decimals=6 if key == "gbp_aed_rate" else 2); box.setValue(value); self.fields[key] = box; form.addRow(label, box)
        layout.addLayout(form); layout.addStretch()

    def _dubai_plan(self) -> None:
        _, layout = self._page("Dubai baseline", "These planning ranges begin with conservative mid-points and remain editable.")
        form = QFormLayout(); form.setSpacing(10)
        for key, label, value in [("salary_aed", "Guaranteed salary (AED)", 6000), ("rent_aed", "Accommodation (AED)", 4500),
                                  ("security_deposit_aed", "Refundable deposit (AED)", 1000), ("transport_aed", "Transport estimate (AED)", 2000),
                                  ("food_aed", "Food estimate (AED)", 1250)]:
            box = MoneyBox(); box.setValue(value); self.fields[key] = box; form.addRow(label, box)
        for key, label, raw in [("arrival_date", "Arrival date", "2026-07-23"), ("start_date", "Job start date", "2026-07-27")]:
            box = QDateEdit(QDate.fromString(raw, "yyyy-MM-dd")); box.setCalendarPopup(True); box.setDisplayFormat("dd MMM yyyy"); self.fields[key] = box; form.addRow(label, box)
        layout.addLayout(form)

    def _protection(self) -> None:
        _, layout = self._page("Protect the way home", "The emergency-return fund is excluded from daily allowance and normal spendable cash.")
        form = QFormLayout(); box = MoneyBox(); box.setValue(3000); self.fields["emergency_fund_aed"] = box; form.addRow("Protected emergency fund (AED)", box)
        why = QTextEdit(); why.setMaximumHeight(90); why.setText("Build a stronger future with patience, focus and options."); self.fields["why_i_moved"] = why; form.addRow("Why I moved", why)
        demo = QCheckBox("Load representative demo transactions"); demo.setChecked(True); self.fields["demo"] = demo; form.addRow("", demo)
        layout.addLayout(form); layout.addStretch()
        note = QLabel("You can back up, restore, export or reset all local data from Settings."); note.setObjectName("muted"); layout.addWidget(note)

    def previous(self) -> None:
        self.pages.setCurrentIndex(max(0, self.pages.currentIndex()-1)); self._sync()

    def advance(self) -> None:
        if self.pages.currentIndex() < self.pages.count()-1:
            self.pages.setCurrentIndex(self.pages.currentIndex()+1); self._sync(); return
        for key, widget in self.fields.items():
            if key == "demo": continue
            if isinstance(widget, QDoubleSpinBox): value = str(widget.value())
            elif isinstance(widget, QDateEdit): value = widget.date().toString("yyyy-MM-dd")
            elif isinstance(widget, QTextEdit): value = widget.toPlainText().strip()
            else: continue
            self.db.set_setting(key, value)
        self.db.set_setting("onboarding_complete", "1")
        if isinstance(self.fields["demo"], QCheckBox) and self.fields["demo"].isChecked(): self.db.seed_demo()
        self.accept()

    def _sync(self) -> None:
        index = self.pages.currentIndex(); self.step.setText(f"{index+1} / {self.pages.count()}"); self.back.setEnabled(index > 0)
        self.next.setText("Open my command centre" if index == self.pages.count()-1 else "Continue")


class TransactionDialog(QDialog):
    def __init__(self, db: Database, row=None, parent=None):
        super().__init__(parent); self.db, self.row = db, row; self.receipt_path: str | None = None
        self.setWindowTitle("Edit transaction" if row else "Add transaction"); self.setMinimumWidth(560)
        layout = QVBoxLayout(self); layout.setContentsMargins(24, 22, 24, 22); layout.setSpacing(14)
        title = QLabel("EDIT TRANSACTION" if row else "QUICK ADD"); title.setObjectName("pageTitle"); layout.addWidget(title)
        form = QFormLayout(); form.setSpacing(11)
        self.kind = QComboBox(); self.kind.addItems(["expense", "income"])
        self.amount = MoneyBox(); self.currency = QComboBox(); self.currency.addItems(["AED", "GBP"])
        amount_row = QHBoxLayout(); amount_row.addWidget(self.amount, 1); amount_row.addWidget(self.currency)
        self.when = QDateTimeEdit(QDateTime.currentDateTime()); self.when.setCalendarPopup(True); self.when.setDisplayFormat("dd MMM yyyy  HH:mm")
        self.category = QComboBox(); self.category_rows = db.query("SELECT id,name,essential_default FROM categories ORDER BY name")
        for item in self.category_rows: self.category.addItem(item["name"], item["id"])
        self.category.currentIndexChanged.connect(self._category_default)
        self.merchant = QLineEdit(); self.merchant.setPlaceholderText("Merchant or source")
        self.payment = QComboBox(); self.payment.addItems(["Debit card", "Cash", "Credit card", "Bank transfer"])
        if row and row["card_effect"] == -1: self.payment.addItem("Credit card payment")
        self.card = QComboBox(); self.card.addItem("Choose a card", None)
        for card in db.query("SELECT id,name,currency FROM credit_cards ORDER BY name,id"): self.card.addItem(f"{card['name']} · {card['currency']}",card["id"])
        self.card_label = QLabel("Credit card")
        self.payment.currentTextChanged.connect(self._sync_card_selector)
        self.recurring = QCheckBox("Recurring"); self.essential = QCheckBox("Essential"); self.deposit = QCheckBox("Refundable deposit")
        flags = QHBoxLayout(); flags.addWidget(self.recurring); flags.addWidget(self.essential); flags.addWidget(self.deposit); flags.addStretch()
        self.tags = QLineEdit(); self.tags.setPlaceholderText("comma, separated, tags")
        self.notes = QTextEdit(); self.notes.setMaximumHeight(72)
        receipt_row = QHBoxLayout(); self.receipt_label = QLabel("No receipt attached"); self.receipt_label.setObjectName("muted")
        receipt = QPushButton("Choose file"); receipt.clicked.connect(self.choose_receipt); receipt_row.addWidget(self.receipt_label, 1); receipt_row.addWidget(receipt)
        form.addRow("Type", self.kind); form.addRow("Amount", amount_row); form.addRow("Date and time", self.when); form.addRow("Category", self.category)
        form.addRow("Merchant", self.merchant); form.addRow("Payment method", self.payment); form.addRow(self.card_label, self.card); form.addRow("", flags); form.addRow("Tags", self.tags); form.addRow("Notes", self.notes); form.addRow("Receipt", receipt_row)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save); buttons.accepted.connect(self.validate_and_accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        if row: self._load(row)
        self._sync_card_selector()

    def _sync_card_selector(self) -> None:
        visible = self.payment.currentText() in {"Credit card", "Credit card payment"}
        self.card_label.setVisible(visible); self.card.setVisible(visible)

    def _category_default(self, index: int) -> None:
        if 0 <= index < len(self.category_rows): self.essential.setChecked(bool(self.category_rows[index]["essential_default"]))

    def choose_receipt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Attach local receipt", "", "Receipts (*.pdf *.png *.jpg *.jpeg *.webp);;All files (*.*)")
        if path: self.receipt_path = path; self.receipt_label.setText(Path(path).name)

    def _load(self, row) -> None:
        self.kind.setCurrentText(row["kind"]); self.amount.setValue(row["amount"]); self.currency.setCurrentText(row["currency"])
        self.when.setDateTime(QDateTime.fromString(row["occurred_at"], Qt.DateFormat.ISODate)); self.category.setCurrentIndex(max(0, self.category.findData(row["category_id"])))
        self.merchant.setText(row["merchant"]); self.payment.setCurrentText(row["payment_method"]); self.card.setCurrentIndex(max(0,self.card.findData(row["credit_card_id"]))); self.recurring.setChecked(bool(row["recurring"])); self.essential.setChecked(bool(row["essential"])); self.deposit.setChecked(bool(row["refundable_deposit"])); self.tags.setText(row["tags"]); self.notes.setText(row["notes"])
        self.receipt_path = row["receipt_path"]; self.receipt_label.setText(Path(self.receipt_path).name if self.receipt_path else "No receipt attached")

    def values(self) -> dict:
        return {"amount": self.amount.value(), "currency": self.currency.currentText(), "occurred_at": self.when.dateTime().toString(Qt.DateFormat.ISODate),
                "kind": self.kind.currentText(), "category_id": self.category.currentData(), "merchant": self.merchant.text().strip(),
                "payment_method": self.payment.currentText(), "recurring": int(self.recurring.isChecked()), "notes": self.notes.toPlainText().strip(),
                "receipt_path": self.receipt_path, "refundable_deposit": int(self.deposit.isChecked()), "essential": int(self.essential.isChecked()), "tags": self.tags.text().strip(),
                "credit_card_id": self.card.currentData() if self.payment.currentText() in {"Credit card", "Credit card payment"} else None,
                "card_effect": -1 if self.payment.currentText()=="Credit card payment" else 1 if self.payment.currentText()=="Credit card" and self.kind.currentText()=="expense" else 0}

    def validate_and_accept(self) -> None:
        if self.amount.value() <= 0: QMessageBox.warning(self, "Check amount", "Amount must be greater than zero."); return
        values = self.values()
        if values["card_effect"] and not values["credit_card_id"]: QMessageBox.warning(self,"Choose a card","Select which credit card this transaction belongs to."); return
        if not self.row and self.db.find_duplicates(values["amount"], values["occurred_at"], values["merchant"]):
            answer = QMessageBox.question(self, "Possible duplicate", "A matching transaction already exists for this day. Add it anyway?")
            if answer != QMessageBox.StandardButton.Yes: return
        self.accept()


class PayCardDialog(QDialog):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent); self.db=db; self.cards=db.query("SELECT * FROM credit_cards WHERE current_balance>0 ORDER BY name,id")
        self.setWindowTitle("Pay credit card"); self.setMinimumWidth(520)
        root=QVBoxLayout(self); root.setContentsMargins(24,22,24,22); root.setSpacing(14)
        title=QLabel("PAY CREDIT CARD"); title.setObjectName("pageTitle"); root.addWidget(title)
        copy=QLabel("The payment is saved as a transaction and immediately restores available credit."); copy.setObjectName("muted"); copy.setWordWrap(True); root.addWidget(copy)
        form=QFormLayout(); self.card=QComboBox()
        for row in self.cards: self.card.addItem(f"{row['name']} · {row['currency']}",row["id"])
        self.amount=MoneyBox(); self.when=QDateTimeEdit(QDateTime.currentDateTime()); self.when.setCalendarPopup(True); self.when.setDisplayFormat("dd MMM yyyy  HH:mm")
        self.balance=QLabel(); self.balance.setObjectName("muted"); self.notes=QLineEdit(); self.notes.setPlaceholderText("Optional reference or note")
        self.card.currentIndexChanged.connect(self._sync); self._sync()
        form.addRow("Card",self.card); form.addRow("Current balance",self.balance); form.addRow("Payment amount",self.amount); form.addRow("Date and time",self.when); form.addRow("Note",self.notes); root.addLayout(form)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Save); buttons.button(QDialogButtonBox.StandardButton.Save).setText("Record payment"); buttons.accepted.connect(self.validate_and_accept); buttons.rejected.connect(self.reject); root.addWidget(buttons)

    def selected_card(self):
        card_id=self.card.currentData(); return next((row for row in self.cards if row["id"]==card_id),None)

    def _sync(self)->None:
        row=self.selected_card()
        if not row: return
        self.amount.setMaximum(float(row["current_balance"])); self.amount.setValue(float(row["current_balance"])); self.amount.setSuffix(f" {row['currency']}"); self.balance.setText(f"{row['currency']} {row['current_balance']:,.2f}")

    def validate_and_accept(self)->None:
        if self.amount.value()<=0: QMessageBox.warning(self,"Check payment","Enter a payment greater than zero."); return
        self.accept()

    def values(self)->dict:
        row=self.selected_card(); category=self.db.query("SELECT id FROM categories WHERE name='Debt repayment'")[0]["id"]
        return {"amount":self.amount.value(),"currency":row["currency"],"occurred_at":self.when.dateTime().toString(Qt.DateFormat.ISODate),"kind":"expense","category_id":category,"merchant":f"Payment - {row['name']}","payment_method":"Credit card payment","recurring":0,"notes":self.notes.text().strip(),"receipt_path":None,"refundable_deposit":0,"essential":1,"tags":"credit card payment","credit_card_id":row["id"],"card_effect":-1}


class VehicleDialog(QDialog):
    def __init__(self, db: Database, parent=None):
        super().__init__(parent); self.db=db; self.setWindowTitle("Add vehicle to stock"); self.setMinimumWidth(520)
        root=QVBoxLayout(self); root.setContentsMargins(24,22,24,22); root.setSpacing(14)
        title=QLabel("ADD TO CURRENT STOCK"); title.setObjectName("pageTitle"); root.addWidget(title)
        copy=QLabel("Only the details needed to track stock value and expected profit."); copy.setObjectName("muted"); root.addWidget(copy)
        form=QFormLayout(); form.setSpacing(11); self.name=QLineEdit(); self.name.setPlaceholderText("e.g. BMW M3")
        self.purchase=MoneyBox(); self.expected=MoneyBox(); self.purchased=QDateEdit(QDate.currentDate()); self.purchased.setCalendarPopup(True); self.purchased.setDisplayFormat("dd MMM yyyy")
        self.notes=QLineEdit(); self.notes.setPlaceholderText("Optional note")
        self.profit=QLabel("Expected profit · AED 0"); self.profit.setStyleSheet(f"color:{COLORS['green']};font-weight:700")
        self.purchase.valueChanged.connect(self.update_profit); self.expected.valueChanged.connect(self.update_profit)
        form.addRow("Vehicle",self.name); form.addRow("Purchase price · AED",self.purchase); form.addRow("Expected sale price · AED",self.expected); form.addRow("Purchased",self.purchased); form.addRow("Notes",self.notes); form.addRow("",self.profit); root.addLayout(form)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Save); buttons.accepted.connect(self.validate_and_accept); buttons.rejected.connect(self.reject); root.addWidget(buttons)

    def update_profit(self)->None:
        profit=self.expected.value()-self.purchase.value(); self.profit.setText(f"Expected profit · AED {profit:+,.2f}"); self.profit.setStyleSheet(f"color:{COLORS['green'] if profit>=0 else COLORS['red']};font-weight:700")

    def validate_and_accept(self)->None:
        if not self.name.text().strip(): QMessageBox.warning(self,"Vehicle required","Enter a short vehicle name."); return
        if self.purchase.value()<=0: QMessageBox.warning(self,"Purchase price required","Enter the purchase price."); return
        self.accept()

    def values(self)->dict:
        return {"vehicle_name":self.name.text().strip(),"purchase_price_aed":self.purchase.value(),"expected_sale_price_aed":self.expected.value(),"purchased_date":self.purchased.date().toString("yyyy-MM-dd"),"notes":self.notes.text().strip()}


class SellVehicleDialog(QDialog):
    def __init__(self, vehicle, parent=None):
        super().__init__(parent); self.vehicle=vehicle; self.setWindowTitle("Move vehicle to sold"); self.setMinimumWidth(500)
        root=QVBoxLayout(self); root.setContentsMargins(24,22,24,22); root.setSpacing(14)
        title=QLabel("MARK AS SOLD"); title.setObjectName("pageTitle"); root.addWidget(title)
        name=QLabel(vehicle["vehicle_name"]); name.setStyleSheet("font-size:18px;font-weight:700"); root.addWidget(name)
        form=QFormLayout(); self.price=MoneyBox(); self.price.setValue(vehicle["expected_sale_price_aed"]); self.sold_date=QDateEdit(QDate.currentDate()); self.sold_date.setCalendarPopup(True); self.sold_date.setDisplayFormat("dd MMM yyyy")
        self.profit=QLabel(); self.price.valueChanged.connect(self.update_profit); form.addRow("Purchase price",QLabel(f"AED {vehicle['purchase_price_aed']:,.2f}")); form.addRow("Actual sale price · AED",self.price); form.addRow("Sold date",self.sold_date); form.addRow("",self.profit); root.addLayout(form); self.update_profit()
        note=QLabel("Saving removes this vehicle from current stock and includes its realised profit in the selected sold month immediately."); note.setObjectName("muted"); note.setWordWrap(True); root.addWidget(note)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.Save); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); root.addWidget(buttons)

    def update_profit(self)->None:
        profit=self.price.value()-self.vehicle["purchase_price_aed"]; self.profit.setText(f"Realised profit · AED {profit:+,.2f}"); self.profit.setStyleSheet(f"color:{COLORS['green'] if profit>=0 else COLORS['red']};font-weight:700")

    def values(self)->dict:
        return {"sold_price_aed":self.price.value(),"sold_date":self.sold_date.date().toString("yyyy-MM-dd")}


class CommandPalette(QDialog):
    command_selected = Signal(str)
    def __init__(self, commands: list[tuple[str, str]], parent=None):
        super().__init__(parent); self.commands = commands; self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint); self.setMinimumSize(580, 420)
        layout = QVBoxLayout(self); layout.setContentsMargins(16, 16, 16, 16)
        self.search = QLineEdit(); self.search.setPlaceholderText("Type a command…"); self.search.setStyleSheet("font-size:17px;padding:12px"); self.search.textChanged.connect(self.filter); layout.addWidget(self.search)
        self.list = QListWidget(); self.list.itemActivated.connect(self.activate); layout.addWidget(self.list); self.filter("")

    def showEvent(self, event) -> None: super().showEvent(event); self.search.setFocus()
    def filter(self, text: str) -> None:
        self.list.clear()
        for name, command in self.commands:
            if text.lower() in name.lower(): item = QListWidgetItem(name); item.setData(Qt.ItemDataRole.UserRole, command); self.list.addItem(item)
        if self.list.count(): self.list.setCurrentRow(0)
    def activate(self, item: QListWidgetItem) -> None: self.command_selected.emit(item.data(Qt.ItemDataRole.UserRole)); self.accept()
