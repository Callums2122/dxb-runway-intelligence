from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt, Signal, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSpinBox,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from .database import Database
from .style import COLORS
from .widgets import Card, MetricCard, SectionHeader


WORKOUTS = {
    "Full body A": [
        ("Leg press", 3, "8–12", 10), ("Bench press or chest press", 3, "6–10", 8),
        ("Chest-supported row", 3, "8–12", 10), ("Romanian deadlift", 3, "8–10", 8),
        ("Dumbbell lateral raise", 3, "12–15", 12), ("Cable curl", 2, "10–15", 12),
        ("Rope triceps pressdown", 2, "10–15", 12),
    ],
    "Full body B": [
        ("Hack squat or goblet squat", 3, "8–12", 10), ("Incline dumbbell press", 3, "8–12", 10),
        ("Lat pulldown", 3, "8–12", 10), ("Hip thrust", 3, "8–12", 10),
        ("Seated leg curl", 3, "10–15", 12), ("Standing calf raise", 3, "10–15", 12),
        ("Cable crunch", 3, "10–15", 12),
    ],
    "Full body C": [
        ("Leg press or hack squat", 3, "8–12", 10), ("Machine chest press", 3, "8–12", 10),
        ("Seated cable row", 3, "8–12", 10), ("Bulgarian split squat", 3, "8–12 / leg", 8),
        ("Seated shoulder press", 3, "8–12", 10), ("Dumbbell lateral raise", 3, "12–15", 12),
        ("Cable curl or pressdown", 3, "10–15", 12),
    ],
}


BOWL_COMPONENTS = {
    "Protein": {
        "Double grilled chicken (200g)": (330, 62, 0, 7, 0), "Grilled salmon (160g)": (335, 35, 0, 21, 0),
        "Lean beef (180g)": (380, 48, 0, 19, 0), "Tofu + edamame": (310, 27, 20, 15, 9),
    },
    "Base": {
        "Half brown rice + half greens": (190, 5, 38, 2, 4), "Brown rice": (260, 6, 54, 2, 4),
        "Quinoa": (220, 8, 39, 4, 5), "Greens only": (70, 4, 12, 1, 6),
    },
    "Vegetables": {
        "Broccoli + peppers": (85, 5, 15, 1, 7), "Mixed roast vegetables": (110, 4, 20, 3, 6),
        "Beans + corn + salsa": (160, 7, 31, 2, 9), "Cucumber + tomato + cabbage": (70, 3, 14, 1, 5),
    },
    "Extra": {
        "No extra": (0, 0, 0, 0, 0), "Half avocado": (120, 2, 6, 11, 5),
        "Hummus (2 tbsp)": (80, 2, 7, 5, 2), "Boiled egg": (78, 6, 1, 5, 0),
    },
    "Sauce": {
        "Hot sauce / lemon": (15, 0, 3, 0, 0), "Yogurt herb sauce": (55, 4, 5, 2, 0),
        "Light tahini": (90, 3, 5, 7, 2), "Dressing on side (half used)": (100, 0, 3, 10, 0),
    },
}


def scroll_page(content: QWidget) -> QScrollArea:
    area=QScrollArea(); area.setWidgetResizable(True); area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); area.setWidget(content)
    return area


def item(text: str, color: str | None = None) -> QTableWidgetItem:
    value=QTableWidgetItem(text)
    if color: value.setForeground(QColor(color))
    return value


def progress(value: float, target: float, color: str) -> QProgressBar:
    bar=QProgressBar(); bar.setRange(0,100); bar.setValue(min(100,round(value/target*100)) if target else 0); bar.setTextVisible(True)
    bar.setFormat(f"{value:,.0f} / {target:,.0f}"); bar.setStyleSheet(f"QProgressBar::chunk{{background:{color};border-radius:5px}}"); return bar


class GymPage(QWidget):
    changed=Signal()
    def __init__(self, db: Database): super().__init__(); self.db=db
    def refresh(self) -> None: pass


class GymDashboardPage(GymPage):
    def __init__(self, db: Database):
        super().__init__(db); outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0)
        content=QWidget(); layout=QVBoxLayout(content); layout.setContentsMargins(22,18,22,26); layout.setSpacing(14)
        layout.addWidget(SectionHeader("Gym · Today", "Build muscle, trim the waist and fix the takeaway routine—one repeatable day at a time."))
        metrics=QHBoxLayout(); self.metrics={}
        for key,label,accent in [("calories","Calories",COLORS["amber"]),("protein","Protein",COLORS["cyan"]),("fibre","Fibre",COLORS["green"]),("water","Water",COLORS["purple"])]:
            card=MetricCard(label,accent=accent); metrics.addWidget(card); self.metrics[key]=card
        layout.addLayout(metrics)
        focus=QHBoxLayout(); daily=Card(); dl=QVBoxLayout(daily); dl.addWidget(SectionHeader("Today’s minimum", "A good day beats a perfect plan you cannot repeat."))
        self.training=QLabel(); self.training.setWordWrap(True); dl.addWidget(self.training)
        button_row=QHBoxLayout(); water=QPushButton("+ 250 ml water"); water.clicked.connect(self.add_water); button_row.addWidget(water)
        self.bowel=QCheckBox("Bowel movement logged"); self.bowel.toggled.connect(self.set_bowel); button_row.addWidget(self.bowel); button_row.addStretch(); dl.addLayout(button_row)
        self.next_action=QLabel(); self.next_action.setObjectName("muted"); self.next_action.setWordWrap(True); dl.addWidget(self.next_action); focus.addWidget(daily,2)
        plan=Card(); pl=QVBoxLayout(plan); pl.addWidget(SectionHeader("Your starting plan", "Editable in Nutrition and Progress."))
        plan_copy=QLabel("3 full-body sessions / week\n140g protein / day\n30g fibre / day\n2.5L water / day\nWeekly weight + waist check")
        plan_copy.setStyleSheet(f"color:{COLORS['text']};font-weight:700;line-height:1.5"); pl.addWidget(plan_copy); pl.addStretch(); focus.addWidget(plan,1); layout.addLayout(focus)
        safety=Card(); sl=QVBoxLayout(safety); title=QLabel("Gut reset—not a laxative plan"); title.setStyleSheet(f"color:{COLORS['green']};font-weight:800"); sl.addWidget(title)
        copy=QLabel("Increase fibre gradually and drink alongside it. Use oats, fruit, beans, vegetables and whole grains. If constipation persists, or you have blood, unexplained weight loss, vomiting, severe pain, or cannot pass stool/gas, seek medical help.")
        copy.setWordWrap(True); copy.setObjectName("muted"); sl.addWidget(copy); layout.addWidget(safety); layout.addStretch(); outer.addWidget(scroll_page(content)); self.refresh()

    def add_water(self) -> None:
        self.db.add_gym_water(250,"Glass"); self.changed.emit()

    def set_bowel(self, checked: bool) -> None:
        if self.bowel.signalsBlocked(): return
        self.db.save_gym_habit(bowel_movement=checked); self.changed.emit()

    def refresh(self) -> None:
        profile=self.db.gym_profile(); totals=self.db.gym_daily_totals(); habit=self.db.gym_habit(); workouts=self.db.query("SELECT COUNT(*) n FROM gym_workouts WHERE workout_date=?",(date.today().isoformat(),))[0]["n"]
        values={"calories":(totals["calories"],profile["calorie_target"],"kcal"),"protein":(totals["protein_g"],profile["protein_target_g"],"g"),"fibre":(totals["fibre_g"],profile["fibre_target_g"],"g"),"water":(habit["water_ml"],profile["water_target_ml"],"ml")}
        for key,(current,target,unit) in values.items(): self.metrics[key].set_value(f"{current:,.0f} / {target:,.0f}{unit}",f"{min(100,current/target*100) if target else 0:.0f}% of today’s target")
        self.bowel.blockSignals(True); self.bowel.setChecked(bool(habit["bowel_movement"])); self.bowel.blockSignals(False)
        self.training.setText("✓ Resistance session logged today" if workouts else "○ Resistance session not logged yet")
        gaps=[(profile["protein_target_g"]-totals["protein_g"],"g protein"),(profile["fibre_target_g"]-totals["fibre_g"],"g fibre"),(profile["water_target_ml"]-habit["water_ml"],"ml water")]
        remaining=[f"{max(0,value):,.0f}{label}" for value,label in gaps if value>0]
        self.next_action.setText("Still to cover: "+", ".join(remaining) if remaining else "Daily nutrition targets covered. Do not force extra food just to make the numbers perfect.")


class GymTrainingPage(GymPage):
    def __init__(self, db: Database):
        super().__init__(db); outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); content=QWidget(); layout=QVBoxLayout(content); layout.setContentsMargins(22,18,22,26); layout.setSpacing(14)
        content.setObjectName("gymTrainingContent"); content.setStyleSheet(f"QWidget#gymTrainingContent{{background:{COLORS['bg']};}}")
        layout.addWidget(SectionHeader("Resistance training", "A simple three-day programme built to add muscle to your legs, chest, back, shoulders and arms."))
        guide=QHBoxLayout()
        for title,copy,accent in [
            ("1 · Warm up", "5 minutes easy movement, then 2–3 lighter practice sets for the first big exercise.", COLORS["amber"]),
            ("2 · Working sets", "Use controlled reps and stop with roughly 2 good reps left. Rest 2–3 minutes on big lifts.", COLORS["cyan"]),
            ("3 · Progress", "When every set reaches the top of its target range cleanly, add the smallest weight jump next time.", COLORS["green"]),
        ]:
            card=Card(); card_layout=QVBoxLayout(card); heading=QLabel(title); heading.setStyleSheet(f"color:{accent};font-weight:800"); body=QLabel(copy); body.setObjectName("muted"); body.setWordWrap(True); card_layout.addWidget(heading); card_layout.addWidget(body); guide.addWidget(card)
        layout.addLayout(guide)
        controls=Card(); cl=QGridLayout(controls); self.session=QComboBox(); self.session.addItems(WORKOUTS); self.session.currentTextChanged.connect(self.load_template)
        self.workout_date=QDateEdit(QDate.currentDate()); self.workout_date.setCalendarPopup(True); self.duration=QSpinBox(); self.duration.setRange(10,180); self.duration.setValue(60); self.duration.setSuffix(" min")
        cl.addWidget(QLabel("Session"),0,0); cl.addWidget(self.session,1,0); cl.addWidget(QLabel("Date"),0,1); cl.addWidget(self.workout_date,1,1); cl.addWidget(QLabel("Duration"),0,2); cl.addWidget(self.duration,1,2)
        cl.setColumnStretch(0,2); cl.setColumnStretch(1,1); cl.setColumnStretch(2,1); layout.addWidget(controls)
        table_card=Card(); table_layout=QVBoxLayout(table_card); table_layout.setContentsMargins(12,12,12,12); table_layout.setSpacing(9)
        table_title=QHBoxLayout(); heading=QLabel("TODAY’S WORKING SETS"); heading.setObjectName("eyebrow"); table_title.addWidget(heading); table_title.addStretch(); legend=QLabel("RIR 2 = finish with 2 clean reps still possible"); legend.setObjectName("muted"); table_title.addWidget(legend); table_layout.addLayout(table_title)
        self.exercise_table=QTableWidget(0,7); self.exercise_table.setHorizontalHeaderLabels(["Exercise","Target","Last time","Sets","Reps done","Weight · kg","Effort · RIR"])
        header=self.exercise_table.horizontalHeader(); header.setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch); header.setSectionResizeMode(1,QHeaderView.ResizeMode.Fixed); header.setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch)
        for column,width in [(1,120),(3,88),(4,110),(5,125),(6,155)]: header.setSectionResizeMode(column,QHeaderView.ResizeMode.Fixed); self.exercise_table.setColumnWidth(column,width)
        self.exercise_table.verticalHeader().setVisible(False); self.exercise_table.setAlternatingRowColors(True); self.exercise_table.setMinimumHeight(395); self.exercise_table.setMaximumHeight(440); table_layout.addWidget(self.exercise_table)
        logging_note=QLabel("Weight logging: use the machine or barbell’s total load. For dumbbells, choose per-hand or combined weight and stay consistent every session. Leave 0 kg only for bodyweight movements."); logging_note.setObjectName("muted"); logging_note.setWordWrap(True); table_layout.addWidget(logging_note); layout.addWidget(table_card)
        actions=QHBoxLayout(); self.notes=QLineEdit(); self.notes.setPlaceholderText("Session note (optional)"); actions.addWidget(self.notes,1); save=QPushButton("Log workout"); save.setProperty("primary",True); save.clicked.connect(self.log_workout); actions.addWidget(save); layout.addLayout(actions)
        layout.addWidget(SectionHeader("Recent sessions", "Your estimated logged volume helps compare similar sessions; it is not a score to chase at the expense of form.")); self.recent=QTableWidget(0,5); self.recent.setHorizontalHeaderLabels(["Date","Session","Duration","Exercises","Estimated volume"]); recent_header=self.recent.horizontalHeader(); recent_header.setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch); recent_header.setSectionResizeMode(4,QHeaderView.ResizeMode.Stretch); self.recent.verticalHeader().setVisible(False); self.recent.setMinimumHeight(210); self.recent.setMaximumHeight(280); layout.addWidget(self.recent); layout.addStretch(); outer.addWidget(scroll_page(content)); self.load_template(); self.refresh()

    def load_template(self) -> None:
        rows=WORKOUTS.get(self.session.currentText(),[]); self.exercise_table.setRowCount(len(rows))
        for row,(name,sets,target_reps,start_reps) in enumerate(rows):
            self.exercise_table.setRowHeight(row,50); self.exercise_table.setItem(row,0,item(name)); self.exercise_table.setItem(row,1,item(f"{sets} × {target_reps}"))
            last=self.db.gym_last_exercise(name); last_text="First session"
            if last: last_text=f"{last['weight_kg']:g} kg × {last['reps']} · RIR {last['rir']}\n{last['workout_date']}"
            last_item=item(last_text,COLORS["muted"]); self.exercise_table.setItem(row,2,last_item)
            set_box=QSpinBox(); set_box.setRange(1,8); set_box.setValue(sets); rep_box=QSpinBox(); rep_box.setRange(1,30); rep_box.setValue(int(last["reps"]) if last else start_reps); weight=QDoubleSpinBox(); weight.setRange(0,500); weight.setDecimals(1); weight.setSingleStep(2.5); weight.setSuffix(" kg"); weight.setValue(float(last["weight_kg"]) if last else 0)
            rir=QComboBox(); rir.addItem("3 · easy",3); rir.addItem("2 · ideal",2); rir.addItem("1 · hard",1); rir.addItem("0 · failure",0); rir.setCurrentIndex(1)
            for widget in (set_box,rep_box,weight,rir): widget.setMinimumHeight(36)
            for column,widget in [(3,set_box),(4,rep_box),(5,weight),(6,rir)]: self.exercise_table.setCellWidget(row,column,widget)

    def log_workout(self) -> None:
        exercises=[]
        for row in range(self.exercise_table.rowCount()):
            exercises.append({"exercise_name":self.exercise_table.item(row,0).text(),"set_count":self.exercise_table.cellWidget(row,3).value(),"reps":self.exercise_table.cellWidget(row,4).value(),"weight_kg":self.exercise_table.cellWidget(row,5).value(),"rir":self.exercise_table.cellWidget(row,6).currentData()})
        self.db.add_gym_workout(self.workout_date.date().toString("yyyy-MM-dd"),self.session.currentText(),self.duration.value(),exercises,self.notes.text()); self.notes.clear(); self.changed.emit(); QMessageBox.information(self,"Workout logged","Session saved. Next time, beat one number with clean form.")

    def refresh(self) -> None:
        rows=self.db.gym_workouts(); self.recent.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,text in enumerate([row["workout_date"],row["session_name"],f"{row['duration_min']} min",str(row["exercises"]),f"{row['volume_kg']:,.0f} kg"]): self.recent.setItem(r,c,item(text))


class GymNutritionPage(GymPage):
    def __init__(self, db: Database):
        super().__init__(db); outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); content=QWidget(); content.setObjectName("gymNutritionContent"); content.setStyleSheet(f"QWidget#gymNutritionContent{{background:{COLORS['bg']};}}")
        layout=QVBoxLayout(content); layout.setContentsMargins(22,18,22,26); layout.setSpacing(14)
        layout.addWidget(SectionHeader("Nutrition · Daily log", "Review any recent day and fill in a forgotten meal without changing today’s record."))
        date_row=QHBoxLayout(); date_row.addWidget(QLabel("Viewing day")); self.log_date=QDateEdit(QDate.currentDate()); self.log_date.setCalendarPopup(True); self.log_date.setMaximumDate(QDate.currentDate()); self.log_date.setDisplayFormat("dd MMM yyyy"); self.log_date.dateChanged.connect(self.refresh); date_row.addWidget(self.log_date); today_button=QPushButton("Today"); today_button.clicked.connect(lambda:self.log_date.setDate(QDate.currentDate())); date_row.addWidget(today_button); yesterday_button=QPushButton("Yesterday"); yesterday_button.clicked.connect(lambda:self.log_date.setDate(QDate.currentDate().addDays(-1))); date_row.addWidget(yesterday_button); date_row.addStretch(); layout.addLayout(date_row)

        summary=QHBoxLayout(); self.score_card=MetricCard("Daily score",accent=COLORS["green"]); self.streak_card=MetricCard("Logging streak",accent=COLORS["amber"]); self.water_card=MetricCard("Water",accent=COLORS["cyan"]); self.meals_card=MetricCard("Meals logged",accent=COLORS["purple"])
        for card in (self.score_card,self.streak_card,self.water_card,self.meals_card): summary.addWidget(card)
        layout.addLayout(summary)

        coach=Card(); coach_layout=QHBoxLayout(coach); coach_layout.setContentsMargins(18,15,18,15); coach_icon=QLabel("→"); coach_icon.setStyleSheet(f"color:{COLORS['cyan']};font-size:28px;font-weight:900"); coach_layout.addWidget(coach_icon)
        coach_copy=QVBoxLayout(); self.coach_title=QLabel("Start the day"); self.coach_title.setStyleSheet("font-size:17px;font-weight:800"); self.coach_text=QLabel(); self.coach_text.setObjectName("muted"); self.coach_text.setWordWrap(True); coach_copy.addWidget(self.coach_title); coach_copy.addWidget(self.coach_text); coach_layout.addLayout(coach_copy,1); layout.addWidget(coach)

        quick=QHBoxLayout()
        water_card=Card(); wl=QVBoxLayout(water_card); wl.addWidget(SectionHeader("Log a bottle", "Tap once when you finish it. Each drink appears below.")); self.water_progress=QProgressBar(); self.water_progress.setTextVisible(True); self.water_progress.setMinimumHeight(26); self.water_progress.setStyleSheet(f"QProgressBar{{color:{COLORS['text']};font-weight:750}} QProgressBar::chunk{{background:{COLORS['cyan']};border-radius:5px}}"); wl.addWidget(self.water_progress)
        water_buttons=QGridLayout()
        for index,(label,amount) in enumerate([("Small · 330 ml",330),("Bottle · 500 ml",500),("Large · 750 ml",750),("Big · 1.5 L",1500)]):
            button=QPushButton(f"＋ {label}"); button.clicked.connect(lambda _checked=False,value=amount,name=label:self.add_water(value,name.split(" ·")[0])); water_buttons.addWidget(button,index//2,index%2)
        wl.addLayout(water_buttons); custom_row=QHBoxLayout(); self.custom_water=QSpinBox(); self.custom_water.setRange(50,3000); self.custom_water.setSingleStep(50); self.custom_water.setValue(500); self.custom_water.setSuffix(" ml"); custom_row.addWidget(self.custom_water,1); custom=QPushButton("Log custom bottle"); custom.clicked.connect(lambda:self.add_water(self.custom_water.value(),"Custom bottle")); custom_row.addWidget(custom); wl.addLayout(custom_row)
        self.water_log=QTableWidget(0,3); self.water_log.setHorizontalHeaderLabels(["Time","Bottle","Amount"]); self.water_log.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch); self.water_log.verticalHeader().setVisible(False); self.water_log.setMaximumHeight(170); self.water_log.setMinimumHeight(120); wl.addWidget(self.water_log)
        remove_water=QPushButton("Remove selected water"); remove_water.clicked.connect(self.delete_water); wl.addWidget(remove_water,0,Qt.AlignmentFlag.AlignRight); quick.addWidget(water_card,1)

        meal_card=Card(); ml=QVBoxLayout(meal_card); ml.addWidget(SectionHeader("Log a meal", "Use a researched favourite in seconds, or enter the label from your meal."))
        favourite_row=QHBoxLayout(); self.quick_meal=QComboBox(); self.quick_meal.setMinimumWidth(330); favourite_row.addWidget(self.quick_meal,1); favourite=QPushButton("＋ Add researched meal"); favourite.setProperty("primary",True); favourite.clicked.connect(self.quick_add_meal); favourite_row.addWidget(favourite); ml.addLayout(favourite_row)
        divider=QLabel("OR LOG THE NUMBERS FROM THE LABEL / APP"); divider.setObjectName("eyebrow"); ml.addWidget(divider)
        form=QGridLayout(); self.meal_name=QLineEdit(); self.meal_name.setPlaceholderText("What did you eat?"); self.meal_values={}; form.addWidget(self.meal_name,0,0,1,5)
        for index,(key,label,maximum) in enumerate([("calories","Calories",3000),("protein_g","Protein",300),("carbs_g","Carbs",500),("fat_g","Fat",250),("fibre_g","Fibre",80)]):
            box=QDoubleSpinBox(); box.setRange(0,maximum); box.setDecimals(1); box.setSuffix(" g" if key!="calories" else " kcal"); self.meal_values[key]=box; form.addWidget(QLabel(label),1,index); form.addWidget(box,2,index)
        ml.addLayout(form); add=QPushButton("＋ Log this meal"); add.setProperty("primary",True); add.clicked.connect(self.add_meal); ml.addWidget(add,0,Qt.AlignmentFlag.AlignRight); quick.addWidget(meal_card,2); layout.addLayout(quick)

        day=Card(); dl=QVBoxLayout(day); self.day_progress_title=SectionHeader("Selected day’s progress", "Protein supports muscle; fibre and water support the gut. Calories are a guide, not a moral score."); dl.addWidget(self.day_progress_title); self.totals_grid=QGridLayout(); dl.addLayout(self.totals_grid); layout.addWidget(day)

        logs=QHBoxLayout(); meals_wrap=Card(); meal_log_layout=QVBoxLayout(meals_wrap); self.meal_log_title=SectionHeader("Selected day’s meals"); meal_log_layout.addWidget(self.meal_log_title); self.entries=QTableWidget(0,7); self.entries.setHorizontalHeaderLabels(["Meal","Calories","Protein","Carbs","Fat","Fibre","Source"]); self.entries.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch); self.entries.horizontalHeader().setSectionResizeMode(6,QHeaderView.ResizeMode.Stretch); self.entries.verticalHeader().setVisible(False); self.entries.setMinimumHeight(230); meal_log_layout.addWidget(self.entries); delete=QPushButton("Remove selected meal"); delete.clicked.connect(self.delete_meal); meal_log_layout.addWidget(delete,0,Qt.AlignmentFlag.AlignRight); logs.addWidget(meals_wrap); layout.addLayout(logs)

        gut=Card(); gl=QHBoxLayout(gut); gut_copy=QVBoxLayout(); gut_title=QLabel("Gut check"); gut_title.setStyleSheet("font-weight:800"); gut_help=QLabel("Logging this helps you notice whether consistent water and gradual fibre are working."); gut_help.setObjectName("muted"); gut_help.setWordWrap(True); gut_copy.addWidget(gut_title); gut_copy.addWidget(gut_help); gl.addLayout(gut_copy,1); self.bowel=QCheckBox("Bowel movement on this day"); self.bowel.toggled.connect(self.save_habits); gl.addWidget(self.bowel); gl.addWidget(QLabel("Bristol score")); self.stool=QComboBox(); self.stool.addItems(["Not logged"]+[str(i) for i in range(1,8)]); self.stool.currentIndexChanged.connect(self.save_habits); gl.addWidget(self.stool); layout.addWidget(gut)

        target_card=Card(); targets=QGridLayout(target_card); target_heading=QLabel("Adjust daily targets"); target_heading.setStyleSheet("font-weight:800"); targets.addWidget(target_heading,0,0,1,6); self.target_fields={}
        specs=[("calorie_target","Calories",1200,5000," kcal"),("protein_target_g","Protein",50,300," g"),("carb_target_g","Carbs",50,500," g"),("fat_target_g","Fat",30,200," g"),("fibre_target_g","Fibre",15,60," g"),("water_target_ml","Water",1000,6000," ml")]
        for index,(key,label,low,high,suffix) in enumerate(specs): box=QSpinBox(); box.setRange(low,high); box.setSuffix(suffix); self.target_fields[key]=box; targets.addWidget(QLabel(label),1,index); targets.addWidget(box,2,index)
        save_targets=QPushButton("Save targets"); save_targets.clicked.connect(self.save_targets); targets.addWidget(save_targets,3,5); layout.addWidget(target_card); layout.addStretch(); outer.addWidget(scroll_page(content)); self.refresh()

    def save_targets(self) -> None:
        self.db.save_gym_profile({key:field.value() for key,field in self.target_fields.items()}); self.changed.emit(); QMessageBox.information(self,"Targets saved","Gym targets updated across Runway.")

    def add_meal(self) -> None:
        values={key:box.value() for key,box in self.meal_values.items()}; values.update({"meal_name":self.meal_name.text(),"source":"Manual","entry_date":self.selected_date()})
        try: self.db.add_gym_food(values)
        except ValueError as error: QMessageBox.warning(self,"Meal not saved",str(error)); return
        self.meal_name.clear(); [box.setValue(0) for box in self.meal_values.values()]; self.changed.emit(); QMessageBox.information(self,"Meal logged","Nice. Your targets and next recommendation have updated.")

    def quick_add_meal(self) -> None:
        meal_id=self.quick_meal.currentData()
        if not meal_id: return
        rows=self.db.query("SELECT * FROM gym_meals WHERE id=?",(meal_id,))
        if not rows: return
        row=rows[0]; self.db.add_gym_food({"meal_name":row["name"],"calories":row["calories"],"protein_g":row["protein_g"],"carbs_g":row["carbs_g"],"fat_g":row["fat_g"],"fibre_g":row["fibre_g"],"source":row["provider"],"notes":row["restaurant"],"entry_date":self.selected_date()}); self.changed.emit(); QMessageBox.information(self,"Meal logged",f"{row['name']} added to {self.log_date.date().toString('dd MMM yyyy')}.")

    def add_water(self, amount: int, label: str) -> None:
        self.db.add_gym_water(amount,label,self.selected_date()); self.changed.emit()

    def delete_water(self) -> None:
        row=self.water_log.currentRow()
        if row<0: return
        self.db.delete_gym_water(int(self.water_log.item(row,0).data(Qt.ItemDataRole.UserRole))); self.changed.emit()

    def delete_meal(self) -> None:
        row=self.entries.currentRow()
        if row<0: return
        self.db.delete_gym_food(int(self.entries.item(row,0).data(Qt.ItemDataRole.UserRole))); self.changed.emit()

    def save_habits(self, *_args) -> None:
        if self.bowel.signalsBlocked(): return
        self.db.save_gym_habit(self.selected_date(),bowel_movement=self.bowel.isChecked(),stool_score=self.stool.currentIndex()); self.changed.emit()

    def selected_date(self) -> str:
        return self.log_date.date().toString("yyyy-MM-dd")

    def refresh(self) -> None:
        chosen=self.selected_date(); profile=self.db.gym_profile(); totals=self.db.gym_daily_totals(chosen); habit=self.db.gym_habit(chosen); food_rows=self.db.gym_food_entries(chosen); water_rows=self.db.gym_water_entries(chosen); streak=self.db.gym_logging_streak()
        for key,field in self.target_fields.items(): field.setValue(int(profile[key]))
        current_quick=self.quick_meal.currentData(); self.quick_meal.blockSignals(True); self.quick_meal.clear(); self.quick_meal.addItem("Choose a researched meal…",None)
        for meal in self.db.gym_meals(): self.quick_meal.addItem(f"{meal['name']} · {meal['calories']:.0f} kcal · {meal['protein_g']:.0f}g protein",meal["id"])
        if current_quick:
            index=self.quick_meal.findData(current_quick); self.quick_meal.setCurrentIndex(max(0,index))
        self.quick_meal.blockSignals(False)
        while self.totals_grid.count():
            widget=self.totals_grid.takeAt(0).widget()
            if widget: widget.deleteLater()
        data=[("Calories",totals["calories"],profile["calorie_target"],COLORS["amber"]),("Protein",totals["protein_g"],profile["protein_target_g"],COLORS["cyan"]),("Carbs",totals["carbs_g"],profile["carb_target_g"],COLORS["purple"]),("Fat",totals["fat_g"],profile["fat_target_g"],COLORS["pink"]),("Fibre",totals["fibre_g"],profile["fibre_target_g"],COLORS["green"]),("Water",habit["water_ml"],profile["water_target_ml"],COLORS["blue"])]
        for index,(label,current,target,color) in enumerate(data): self.totals_grid.addWidget(QLabel(label),index,0); self.totals_grid.addWidget(progress(current,target,color),index,1)
        self.entries.setRowCount(len(food_rows))
        for r,row in enumerate(food_rows):
            cells=[row["meal_name"],f"{row['calories']:,.0f}",f"{row['protein_g']:,.1f}g",f"{row['carbs_g']:,.1f}g",f"{row['fat_g']:,.1f}g",f"{row['fibre_g']:,.1f}g",row["source"]]
            for c,text in enumerate(cells): self.entries.setItem(r,c,item(text))
            self.entries.item(r,0).setData(Qt.ItemDataRole.UserRole,row["id"])
        self.water_log.setRowCount(len(water_rows))
        for r,row in enumerate(water_rows):
            timestamp=str(row["created_at"]); time_text=timestamp[11:16] if len(timestamp)>=16 else "—"
            for c,text in enumerate([time_text,row["label"],f"{row['amount_ml']:,} ml"]): self.water_log.setItem(r,c,item(text))
            self.water_log.item(r,0).setData(Qt.ItemDataRole.UserRole,row["id"])
        for widget in (self.bowel,self.stool): widget.blockSignals(True)
        self.bowel.setChecked(bool(habit["bowel_movement"])); self.stool.setCurrentIndex(int(habit["stool_score"]))
        for widget in (self.bowel,self.stool): widget.blockSignals(False)
        water_pct=min(100,float(habit["water_ml"])/float(profile["water_target_ml"])*100) if profile["water_target_ml"] else 0; self.water_progress.setRange(0,100); self.water_progress.setValue(round(water_pct)); self.water_progress.setFormat(f"{habit['water_ml']:,} / {profile['water_target_ml']:,} ml · {water_pct:.0f}%")
        protein_pct=min(1,totals["protein_g"]/float(profile["protein_target_g"])) if profile["protein_target_g"] else 0; fibre_pct=min(1,totals["fibre_g"]/float(profile["fibre_target_g"])) if profile["fibre_target_g"] else 0; meal_pct=min(1,len(food_rows)/3); score=round((protein_pct*.30+fibre_pct*.25+min(1,water_pct/100)*.25+meal_pct*.20)*100)
        self.score_card.set_value(f"{score}%","Build the score with useful actions—not perfection.",COLORS["green"] if score>=75 else COLORS["cyan"])
        self.streak_card.set_value(f"{streak} day{'s' if streak!=1 else ''}","One bottle or meal keeps the logging chain alive.")
        self.water_card.set_value(f"{habit['water_ml']:,} ml",f"{max(0,int(profile['water_target_ml'])-int(habit['water_ml'])):,} ml remaining")
        self.meals_card.set_value(str(len(food_rows)),f"{totals['protein_g']:.0f}g protein logged")
        protein_left=max(0,float(profile["protein_target_g"])-totals["protein_g"]); fibre_left=max(0,float(profile["fibre_target_g"])-totals["fibre_g"]); water_left=max(0,int(profile["water_target_ml"])-int(habit["water_ml"]))
        if not food_rows: title,copy="Log your first meal","Start with what you actually ate. Accuracy today gives you a better recommendation tonight."
        elif water_left>=750: title,copy="Finish your next bottle",f"You have {water_left:,} ml left. Log the bottle as soon as it is empty and watch the score move."
        elif protein_left>=35: title,copy="Make the next meal protein-led",f"You still need roughly {protein_left:.0f}g protein. A chicken bowl, lean beef, fish or Greek yogurt is the cleanest next move."
        elif fibre_left>=8: title,copy="Add a fibre win",f"About {fibre_left:.0f}g fibre remains. Choose beans, vegetables, oats, berries, a pear or a half-rice/half-greens bowl. Increase gradually."
        elif score<90: title,copy="Close the small gaps","You are on track. Keep the next meal normal, include vegetables, and avoid turning a good day into an all-or-nothing one."
        else: title,copy="Day secured — strong work","Targets are covered. Stay consistent, stop chasing perfection, and repeat the process tomorrow."
        self.coach_title.setText(title); self.coach_text.setText(copy)


class GymProgressPage(GymPage):
    def __init__(self, db: Database):
        super().__init__(db); outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); content=QWidget(); layout=QVBoxLayout(content); layout.setContentsMargins(22,18,22,26); layout.setSpacing(14)
        layout.addWidget(SectionHeader("Progress", "Use the weekly trend: body weight, waist and gym performance—not a single mirror check."))
        metrics=QHBoxLayout(); self.weight_card=MetricCard("Current weight",accent=COLORS["cyan"]); self.waist_card=MetricCard("Waist change",accent=COLORS["green"]); self.training_card=MetricCard("Sessions this month",accent=COLORS["purple"]); metrics.addWidget(self.weight_card); metrics.addWidget(self.waist_card); metrics.addWidget(self.training_card); layout.addLayout(metrics)
        card=Card(); form=QGridLayout(card); self.measured_date=QDateEdit(QDate.currentDate()); self.measured_date.setCalendarPopup(True); self.measure_fields={}
        form.addWidget(QLabel("Date"),0,0); form.addWidget(self.measured_date,1,0)
        for index,(key,label,initial) in enumerate([("weight_kg","Weight kg",70),("waist_cm","Waist cm",0),("chest_cm","Chest cm",0),("arm_cm","Arm cm",0),("thigh_cm","Thigh cm",0)],1):
            box=QDoubleSpinBox(); box.setRange(0 if key!="weight_kg" else 30,250); box.setDecimals(1); box.setValue(initial); self.measure_fields[key]=box; form.addWidget(QLabel(label),0,index); form.addWidget(box,1,index)
        self.notes=QLineEdit(); self.notes.setPlaceholderText("Same lighting/time/conditions; optional note"); form.addWidget(self.notes,2,0,1,5); save=QPushButton("Log check-in"); save.setProperty("primary",True); save.clicked.connect(self.log_measurement); form.addWidget(save,2,5); layout.addWidget(card)
        actions=QHBoxLayout(); delete=QPushButton("Delete selected"); delete.clicked.connect(self.delete_measurement); actions.addWidget(delete); actions.addStretch(); layout.addLayout(actions)
        self.table=QTableWidget(0,7); self.table.setHorizontalHeaderLabels(["Date","Weight","Waist","Chest","Arm","Thigh","Notes"]); self.table.horizontalHeader().setStretchLastSection(True); self.table.setMinimumHeight(310); layout.addWidget(self.table)
        note=QLabel("Aim for slow, boring consistency. If strength rises while waist falls or stays controlled, the plan is working—even when scale weight moves slowly."); note.setObjectName("muted"); note.setWordWrap(True); layout.addWidget(note); layout.addStretch(); outer.addWidget(scroll_page(content)); self.refresh()

    def log_measurement(self) -> None:
        values={key:box.value() for key,box in self.measure_fields.items()}; values.update({"measured_date":self.measured_date.date().toString("yyyy-MM-dd"),"notes":self.notes.text()})
        self.db.add_gym_measurement(values); self.notes.clear(); self.changed.emit()

    def delete_measurement(self) -> None:
        row=self.table.currentRow()
        if row<0: return
        self.db.delete_gym_measurement(int(self.table.item(row,0).data(Qt.ItemDataRole.UserRole))); self.changed.emit()

    def refresh(self) -> None:
        rows=self.db.gym_measurements(); profile=self.db.gym_profile(); self.measure_fields["weight_kg"].setValue(float(profile["weight_kg"])); self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            cells=[row["measured_date"],f"{row['weight_kg']:.1f} kg",f"{row['waist_cm']:.1f} cm" if row["waist_cm"] else "—",f"{row['chest_cm']:.1f} cm" if row["chest_cm"] else "—",f"{row['arm_cm']:.1f} cm" if row["arm_cm"] else "—",f"{row['thigh_cm']:.1f} cm" if row["thigh_cm"] else "—",row["notes"]]
            for c,text in enumerate(cells): self.table.setItem(r,c,item(text))
            self.table.item(r,0).setData(Qt.ItemDataRole.UserRole,row["id"])
        current=float(rows[0]["weight_kg"]) if rows else float(profile["weight_kg"]); self.weight_card.set_value(f"{current:.1f} kg","Starting profile: 70.0 kg")
        valid=[row for row in reversed(rows) if row["waist_cm"]]
        change=float(valid[-1]["waist_cm"]-valid[0]["waist_cm"]) if len(valid)>1 else 0; self.waist_card.set_value(f"{change:+.1f} cm","From first to latest logged waist")
        month=date.today().strftime("%Y-%m"); count=self.db.query("SELECT COUNT(*) n FROM gym_workouts WHERE substr(workout_date,1,7)=?",(month,))[0]["n"]; self.training_card.set_value(str(count),"Target: 3 sessions each week")


class GymMealsPage(GymPage):
    def __init__(self, db: Database):
        super().__init__(db); outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); content=QWidget(); layout=QVBoxLayout(content); layout.setContentsMargins(22,18,22,26); layout.setSpacing(14)
        layout.addWidget(SectionHeader("Meals & healthy bowls", "Delivery shortcuts researched for Dubai, plus a bowl builder that keeps protein and fibre visible."))
        builder=Card(); grid=QGridLayout(builder); self.bowl_boxes={}
        for index,(group,choices) in enumerate(BOWL_COMPONENTS.items()):
            box=QComboBox(); box.addItems(choices); box.currentTextChanged.connect(self.update_bowl); self.bowl_boxes[group]=box; grid.addWidget(QLabel(group),0,index); grid.addWidget(box,1,index)
        self.bowl_result=QLabel(); self.bowl_result.setStyleSheet(f"color:{COLORS['green']};font-weight:800;font-size:16px"); grid.addWidget(self.bowl_result,2,0,1,4); add=QPushButton("Add bowl to today"); add.setProperty("primary",True); add.clicked.connect(self.add_bowl); grid.addWidget(add,2,4); layout.addWidget(builder)
        filters=QHBoxLayout(); self.search=QLineEdit(); self.search.setPlaceholderText("Search meal, restaurant or goal…"); self.search.textChanged.connect(self.refresh); filters.addWidget(self.search,1); self.provider=QComboBox(); self.provider.addItems(["All","Talabat","Deliveroo","Careem","Keeta"]); self.provider.currentTextChanged.connect(self.refresh); filters.addWidget(self.provider); export=QPushButton("Export meal spreadsheet CSV"); export.clicked.connect(self.export_csv); filters.addWidget(export); layout.addLayout(filters)
        self.table=QTableWidget(0,9); self.table.setHorizontalHeaderLabels(["Meal","Restaurant","App","Kcal","Protein","Carbs","Fat","Fibre","AED"]); self.table.horizontalHeader().setStretchLastSection(True); self.table.setMinimumHeight(360); self.table.itemSelectionChanged.connect(self.selection_changed); layout.addWidget(self.table)
        for column,width in enumerate([240,130,185,78,88,78,78,78,70]): self.table.setColumnWidth(column,width)
        actions=QHBoxLayout(); self.route=QLabel("Select a meal to see why it fits."); self.route.setObjectName("muted"); self.route.setWordWrap(True); actions.addWidget(self.route,1); add_meal=QPushButton("Add selected to today"); add_meal.clicked.connect(self.add_selected); actions.addWidget(add_meal); source=QPushButton("Open source/menu"); source.clicked.connect(self.open_source); actions.addWidget(source); layout.addLayout(actions)
        caveat=QLabel("Prices, availability and restaurant portions change. Talabat/Careem/Keeta may carry the same restaurant under a different branch; search the exact meal name and verify the live listing. Fibre values marked in notes are estimates."); caveat.setObjectName("muted"); caveat.setWordWrap(True); layout.addWidget(caveat); layout.addStretch(); outer.addWidget(scroll_page(content)); self.update_bowl(); self.refresh()

    def bowl_values(self) -> tuple[str,tuple[float,float,float,float,float]]:
        totals=[0.0]*5; names=[]
        for group,box in self.bowl_boxes.items():
            choice=box.currentText(); names.append(choice); values=BOWL_COMPONENTS[group][choice]
            totals=[a+b for a,b in zip(totals,values)]
        return " + ".join(names),tuple(totals)

    def update_bowl(self, *_args) -> None:
        _name,(calories,protein,carbs,fat,fibre)=self.bowl_values(); self.bowl_result.setText(f"{calories:,.0f} kcal · {protein:,.0f}g protein · {carbs:,.0f}g carbs · {fat:,.0f}g fat · {fibre:,.0f}g fibre")

    def add_bowl(self) -> None:
        name,values=self.bowl_values(); calories,protein,carbs,fat,fibre=values; self.db.add_gym_food({"meal_name":"Custom healthy bowl","calories":calories,"protein_g":protein,"carbs_g":carbs,"fat_g":fat,"fibre_g":fibre,"source":"Bowl builder","notes":name}); self.changed.emit(); QMessageBox.information(self,"Bowl added","Your custom bowl has been added to today’s macros.")

    def selected(self):
        row=self.table.currentRow()
        if row<0: return None
        meal_id=self.table.item(row,0).data(Qt.ItemDataRole.UserRole); rows=self.db.query("SELECT * FROM gym_meals WHERE id=?",(meal_id,)); return rows[0] if rows else None

    def selection_changed(self) -> None:
        row=self.selected(); self.route.setText(f"{row['route']} · {row['notes']}" if row else "Select a meal to see why it fits.")

    def add_selected(self) -> None:
        row=self.selected()
        if not row: return
        self.db.add_gym_food({"meal_name":row["name"],"calories":row["calories"],"protein_g":row["protein_g"],"carbs_g":row["carbs_g"],"fat_g":row["fat_g"],"fibre_g":row["fibre_g"],"source":row["provider"],"notes":row["restaurant"]}); self.changed.emit(); QMessageBox.information(self,"Meal added",f"{row['name']} added to today’s macros.")

    def open_source(self) -> None:
        row=self.selected()
        if row and row["source_url"]: QDesktopServices.openUrl(QUrl(row["source_url"]))

    def export_csv(self) -> None:
        destination,_=QFileDialog.getSaveFileName(self,"Export gym meals",str(Path.home()/"Downloads"/"DXB_Runway_Gym_Meals.csv"),"CSV files (*.csv)")
        if not destination: return
        rows=self.db.gym_meals()
        with Path(destination).open("w",newline="",encoding="utf-8-sig") as handle:
            writer=csv.writer(handle); writer.writerow(["Meal","Restaurant","Provider","Calories","Protein g","Carbs g","Fat g","Fibre g","Price AED","Best route","Notes","Source","Checked"])
            for row in rows: writer.writerow([row["name"],row["restaurant"],row["provider"],row["calories"],row["protein_g"],row["carbs_g"],row["fat_g"],row["fibre_g"],row["price_aed"],row["route"],row["notes"],row["source_url"],row["checked_on"]])
        QMessageBox.information(self,"Export complete",f"Meal spreadsheet saved to:\n{destination}")

    def refresh(self, *_args) -> None:
        provider=self.provider.currentText() if hasattr(self,"provider") else "All"; rows=self.db.gym_meals(self.search.text() if hasattr(self,"search") else "",provider); self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            values=[row["name"],row["restaurant"],row["provider"],f"{row['calories']:,.0f}",f"{row['protein_g']:,.1f}g",f"{row['carbs_g']:,.1f}g",f"{row['fat_g']:,.1f}g",f"{row['fibre_g']:,.1f}g",f"{row['price_aed']:,.0f}"]
            for c,text in enumerate(values): self.table.setItem(r,c,item(text,COLORS["green"] if c==4 and float(row["protein_g"])>=35 else None))
            self.table.item(r,0).setData(Qt.ItemDataRole.UserRole,row["id"])
        if rows: self.table.selectRow(0)
