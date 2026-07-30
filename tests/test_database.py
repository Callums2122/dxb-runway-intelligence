from pathlib import Path

from dxb_runway.database import Database, SCHEMA_VERSION


def test_schema_migrations_and_defaults(tmp_path: Path):
    db=Database(tmp_path/"data"/"runway.db")
    okay,message=db.health_check()
    assert okay, message
    assert db.query("PRAGMA user_version")[0][0]==SCHEMA_VERSION
    assert len(db.query("SELECT * FROM categories"))>=17
    assert db.get_setting("gbp_aed_rate")=="4.928313"
    assert db.get_setting("gbp_aed_rate_updated_at")=="2026-07-14"
    assert "due_date" in {row[1] for row in db.query("PRAGMA table_info(budgets)")}
    assert "purchase_type" in {row[1] for row in db.query("PRAGMA table_info(vehicles)")}
    assert db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='customer_contacts'")
    assert db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='customer_contact_notes'")


def test_rate_snapshot_migration_updates_only_untouched_old_default(tmp_path: Path):
    for filename, old_rate, expected in [("default.db","4.75","4.928313"),("custom.db","4.81","4.81")]:
        path=tmp_path/filename
        historical=Database(path)
        historical.set_setting("gbp_aed_rate",old_rate)
        with historical.connect() as connection:
            connection.execute("PRAGMA user_version=3")
        migrated=Database(path)
        assert migrated.get_setting("gbp_aed_rate")==expected
        assert migrated.get_setting("gbp_aed_rate_updated_at")=="2026-07-14"


def test_credit_card_purchase_increases_debt_not_cash(tmp_path: Path):
    db=Database(tmp_path/"runway.db")
    db.execute("INSERT INTO credit_cards(name,currency,credit_limit,current_balance) VALUES ('Card','AED',10000,1000)")
    category=db.query("SELECT id FROM categories WHERE name='Groceries'")[0]["id"]
    db.add_transaction({"amount":250,"currency":"AED","occurred_at":"2026-07-20T10:00:00","kind":"expense","category_id":category,"merchant":"Shop","payment_method":"Credit card","recurring":0,"notes":"","receipt_path":None,"refundable_deposit":0,"essential":1,"tags":""})
    assert db.query("SELECT current_balance FROM credit_cards")[0][0]==1250
    assert db.transactions()[0]["amount"]==250


def test_credit_card_limit_can_be_edited_without_changing_transaction_balance_and_card_deleted(tmp_path: Path):
    db=Database(tmp_path/"runway.db")
    card_id=db.save_credit_card({"name":"UK card","currency":"GBP","credit_limit":5000,"minimum_payment":50,"apr":24.9})
    card=db.query("SELECT * FROM credit_cards WHERE id=?",(card_id,))[0]
    assert card["credit_limit"]==5000
    assert card["current_balance"]==0
    category=db.query("SELECT id FROM categories WHERE name='Groceries'")[0]["id"]
    db.add_transaction({"amount":1000,"currency":"GBP","occurred_at":"2026-07-20T10:00:00","kind":"expense","category_id":category,"merchant":"Purchase","payment_method":"Credit card","recurring":0,"notes":"","receipt_path":None,"refundable_deposit":0,"essential":1,"tags":"","credit_card_id":card_id})
    db.save_credit_card({"credit_limit":6000},card_id)
    card=db.query("SELECT * FROM credit_cards WHERE id=?",(card_id,))[0]
    assert card["name"]=="UK card" and card["credit_limit"]==6000 and card["current_balance"]==1000
    db.delete_credit_card(card_id)
    assert db.query("SELECT * FROM credit_cards WHERE id=?",(card_id,))==[]


def test_credit_card_payment_transaction_reduces_balance_and_is_reversible(tmp_path: Path):
    db=Database(tmp_path/"runway.db")
    card_id=db.save_credit_card({"name":"UK card","currency":"GBP","credit_limit":5000})
    category=db.query("SELECT id FROM categories WHERE name='Groceries'")[0]["id"]
    purchase={"amount":1000,"currency":"GBP","occurred_at":"2026-07-20T10:00:00","kind":"expense","category_id":category,"merchant":"Purchase","payment_method":"Credit card","recurring":0,"notes":"","receipt_path":None,"refundable_deposit":0,"essential":1,"tags":"","credit_card_id":card_id}
    db.add_transaction(purchase)
    repayment=db.query("SELECT id FROM categories WHERE name='Debt repayment'")[0]["id"]
    payment={"amount":400,"currency":"GBP","occurred_at":"2026-07-21T10:00:00","kind":"expense","category_id":repayment,"merchant":"Payment · UK card","payment_method":"Credit card payment","recurring":0,"notes":"","receipt_path":None,"refundable_deposit":0,"essential":1,"tags":"credit card payment","credit_card_id":card_id,"card_effect":-1}
    payment_id=db.add_transaction(payment)
    assert db.query("SELECT current_balance FROM credit_cards WHERE id=?",(card_id,))[0][0]==600
    row=db.transactions()[0]
    assert row["credit_card_name"]=="UK card" and row["card_effect"]==-1
    db.soft_delete_transaction(payment_id)
    assert db.query("SELECT current_balance FROM credit_cards WHERE id=?",(card_id,))[0][0]==1000
    db.undo_delete(payment_id)
    assert db.query("SELECT current_balance FROM credit_cards WHERE id=?",(card_id,))[0][0]==600


def test_credit_card_purchase_updates_selected_card_only(tmp_path: Path):
    db=Database(tmp_path/"runway.db")
    first=db.save_credit_card({"name":"First","currency":"GBP","credit_limit":5000})
    second=db.save_credit_card({"name":"Second","currency":"GBP","credit_limit":5000})
    category=db.query("SELECT id FROM categories WHERE name='Transport'")[0]["id"]
    db.add_transaction({"amount":250,"currency":"GBP","occurred_at":"2026-07-20T10:00:00","kind":"expense","category_id":category,"merchant":"Taxi","payment_method":"Credit card","recurring":0,"notes":"","receipt_path":None,"refundable_deposit":0,"essential":1,"tags":"","credit_card_id":second})
    assert db.query("SELECT current_balance FROM credit_cards WHERE id=?",(first,))[0][0]==0
    assert db.query("SELECT current_balance FROM credit_cards WHERE id=?",(second,))[0][0]==250


def test_credit_card_purchase_converts_to_card_currency_and_reverses(tmp_path: Path):
    db=Database(tmp_path/"runway.db")
    db.execute("INSERT INTO credit_cards(name,currency,credit_limit,current_balance) VALUES ('UK Card','GBP',4000,100)")
    category=db.query("SELECT id FROM categories WHERE name='Transport'")[0]["id"]
    tx=db.add_transaction({"amount":492.8313,"currency":"AED","occurred_at":"2026-07-20T10:00:00","kind":"expense","category_id":category,"merchant":"Taxi","payment_method":"Credit card","recurring":0,"notes":"","receipt_path":None,"refundable_deposit":0,"essential":1,"tags":""})
    assert db.query("SELECT current_balance FROM credit_cards")[0][0]==200
    db.soft_delete_transaction(tx)
    assert db.query("SELECT current_balance FROM credit_cards")[0][0]==100
    db.undo_delete(tx)
    assert db.query("SELECT current_balance FROM credit_cards")[0][0]==200


def test_receipt_is_copied_into_local_receipt_store(tmp_path: Path):
    db=Database(tmp_path/"runway.db"); source=tmp_path/"receipt.pdf"; source.write_bytes(b"local receipt")
    category=db.query("SELECT id FROM categories WHERE name='Miscellaneous'")[0]["id"]
    db.add_transaction({"amount":10,"currency":"AED","occurred_at":"2026-07-20T10:00:00","kind":"expense","category_id":category,"merchant":"Test","payment_method":"Cash","recurring":0,"notes":"","receipt_path":str(source),"refundable_deposit":0,"essential":0,"tags":""})
    stored=Path(db.transactions()[0]["receipt_path"])
    assert stored.parent==db.receipts_dir
    assert stored.read_bytes()==b"local receipt"


def test_vehicle_moves_atomically_from_stock_to_monthly_sold_history(tmp_path: Path):
    db=Database(tmp_path/"runway.db")
    vehicle_id=db.add_vehicle(vehicle_name="BMW M4",purchase_price_aed=200000,expected_sale_price_aed=225000,purchased_date="2026-07-04")
    assert [row["id"] for row in db.stock_vehicles("2026-07")]==[vehicle_id]
    assert db.sold_vehicles("2026-07")==[]
    db.sell_vehicle(vehicle_id,sold_price_aed=230000,sold_date="2026-07-18")
    assert db.stock_vehicles()==[]
    assert db.monthly_vehicle_purchase_total("2026-07")==200000
    sold=db.sold_vehicles("2026-07")
    assert len(sold)==1 and sold[0]["realised_profit_aed"]==30000
    assert db.sold_vehicles("2026-08")==[]
    db.return_vehicle_to_stock(vehicle_id)
    assert len(db.stock_vehicles())==1 and db.sold_vehicles("2026-07")==[]
    assert db.monthly_vehicle_purchase_total("2026-07")==200000


def test_consignment_stock_tracks_profit_without_using_cash_budget_and_can_be_removed(tmp_path: Path):
    db=Database(tmp_path/"runway.db")
    consignment=db.add_vehicle(vehicle_name="Porsche 911",purchase_type="consignment",purchase_price_aed=300000,expected_sale_price_aed=335000,purchased_date="2026-07-10")
    cash=db.add_vehicle(vehicle_name="BMW M4",purchase_type="cash",purchase_price_aed=200000,expected_sale_price_aed=225000,purchased_date="2026-07-11")
    rows={row["id"]:row for row in db.stock_vehicles()}
    assert rows[consignment]["purchase_type"]=="consignment"
    assert rows[consignment]["expected_profit_aed"]==35000
    assert db.monthly_vehicle_purchase_total("2026-07")==200000
    db.remove_stock_vehicle(consignment)
    assert [row["id"] for row in db.stock_vehicles()]==[cash]
    db.sell_vehicle(cash,sold_price_aed=230000,sold_date="2026-07-18")
    try:
        db.remove_stock_vehicle(cash)
    except ValueError as error:
        assert "no longer available" in str(error)
    else:
        raise AssertionError("Sold vehicles must not be removable from stock")
    sold=db.sold_vehicles("2026-07")
    assert len(sold)==1 and sold[0]["purchase_type"]=="cash"


def test_performance_budget_is_stored_per_month(tmp_path: Path):
    db=Database(tmp_path/"runway.db")
    assert db.performance_budget("2026-07")==3000000
    db.set_performance_budget("2026-07",4500000)
    assert db.performance_budget("2026-07")==4500000
    assert db.performance_budget("2026-08")==3000000


def test_customer_contact_three_day_followup_rapport_and_sold_archive(tmp_path: Path):
    db=Database(tmp_path/"runway.db")
    customer_id=db.add_customer_contact({"customer_name":"Sam","vehicle_name":"BMW M4","phone_last5":"12345","mileage":42000,"vehicle_age_years":2021,"vehicle_price_aed":210000,"cash_offer_aed":190000,"consignment_offer_aed":205000,"next_contact_date":"2026-07-30"})
    row=db.query("SELECT * FROM customer_contacts WHERE id=?",(customer_id,))[0]
    assert row["rapport"]=="green" and row["next_contact_date"]=="2026-07-30" and row["vehicle_age_years"]==2021
    assert db.toggle_customer_rapport(customer_id)=="red"
    db.mark_customer_contacted(customer_id,"2026-07-30")
    row=db.query("SELECT * FROM customer_contacts WHERE id=?",(customer_id,))[0]
    assert row["last_contacted_date"]=="2026-07-30" and row["next_contact_date"]=="2026-08-02"
    db.mark_customer_sold(customer_id,"2026-08-01")
    assert db.customer_contacts()==[]
    archived=db.customer_contacts(search="12345",include_sold=True)
    assert len(archived)==1 and archived[0]["status"]=="sold" and archived[0]["sold_date"]=="2026-08-01"
    first=db.add_customer_contact_note(customer_id,"Seller wants to finish the paid advert first")
    second=db.add_customer_contact_note(customer_id,"Friendly follow-up completed")
    assert [row["id"] for row in db.customer_contact_notes(customer_id)]==[second,first]
    db.delete_customer_contact_note(customer_id,second)
    assert [row["note_text"] for row in db.customer_contact_notes(customer_id)]==["Seller wants to finish the paid advert first"]


def test_soft_delete_and_undo(tmp_path: Path):
    db=Database(tmp_path/"runway.db"); category=db.query("SELECT id FROM categories WHERE name='Miscellaneous'")[0]["id"]
    tx=db.add_transaction({"amount":10,"currency":"AED","occurred_at":"2026-07-20T10:00:00","kind":"expense","category_id":category,"merchant":"Test","payment_method":"Cash","recurring":0,"notes":"","receipt_path":None,"refundable_deposit":0,"essential":0,"tags":""})
    db.soft_delete_transaction(tx); assert db.transactions()==[]
    db.undo_delete(tx); assert len(db.transactions())==1


def test_transaction_highlight_is_persistent_and_reversible(tmp_path: Path):
    db=Database(tmp_path/"runway.db"); category=db.query("SELECT id FROM categories WHERE name='Accommodation'")[0]["id"]
    tx=db.add_transaction({"amount":1000,"currency":"AED","occurred_at":"2026-07-20T10:00:00","kind":"expense","category_id":category,"merchant":"Deposit","payment_method":"Debit card","recurring":0,"notes":"Remember refund","receipt_path":None,"refundable_deposit":1,"essential":1,"tags":"deposit"})
    assert not db.transactions()[0]["highlighted"]
    assert db.toggle_transaction_highlight(tx)
    assert db.transactions()[0]["highlighted"]==1
    assert not db.toggle_transaction_highlight(tx)
    assert db.transactions()[0]["highlighted"]==0


def test_duplicate_detection_csv_and_backup_restore(tmp_path: Path):
    db=Database(tmp_path/"runway.db"); db.seed_demo(); before=len(db.transactions())
    backup=db.backup(tmp_path/"portable.dxbr")
    db.execute("DELETE FROM transactions")
    assert db.transactions()==[]
    db.restore(backup)
    assert len(db.transactions())==before
    assert db.find_duplicates(74,date_prefix(db.transactions()[0]["occurred_at"]),"Lunch")


def test_encrypted_backup_restore(tmp_path: Path):
    db=Database(tmp_path/"runway.db"); db.seed_demo(); backup=db.backup(tmp_path/"private.dxbr.enc","correct horse")
    assert backup.read_bytes().startswith(b"DXBR2\n")
    db.restore(backup,"correct horse")
    assert db.health_check()[0]


def date_prefix(value: str)->str:
    return value[:10]+"T00:00:00"
