from __future__ import annotations

from datetime import date, datetime, timedelta
from math import ceil

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .database import Database
from .screens import Page

BLUE, GREEN, RED = "#2c6ecb", "#008060", "#d72c0d"


def money(value: float) -> str:
    return f"AED {value:,.0f}"


class Sparkline(QWidget):
    def __init__(self):
        super().__init__(); self.values=[]; self.setFixedSize(72,32)

    def set_values(self, values): self.values=list(values); self.update()

    def paintEvent(self,event):
        if len(self.values)<2:return
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing); low=min(self.values); span=max(1,max(self.values)-low)
        points=[QPointF(2+i*(self.width()-4)/(len(self.values)-1),self.height()-3-(v-low)*(self.height()-8)/span) for i,v in enumerate(self.values)]
        path=QPainterPath(points[0])
        for point in points[1:]:path.lineTo(point)
        p.setPen(QPen(QColor(BLUE),2.1,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap)); p.drawPath(path)


class TrendChart(QWidget):
    def __init__(self): super().__init__(); self.current=[]; self.previous=[]; self.setMinimumHeight(280)
    def set_values(self,current,previous):self.current=list(current);self.previous=list(previous);self.update()
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing); box=QRectF(56,18,self.width()-72,self.height()-55); values=self.current+self.previous or [0]; high=max(max(values),1); low=min(min(values),0); span=max(1,high-low)
        p.setFont(QFont("Arial",8)); p.setPen(QColor("#dfe3e8"))
        for i in range(5):
            y=box.top()+i*box.height()/4;p.drawLine(QPointF(box.left(),y),QPointF(box.right(),y));p.setPen(QColor("#8c9196"));p.drawText(QRectF(0,y-8,48,16),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,f"{(high-i*span/4)/1000:.0f}K");p.setPen(QColor("#dfe3e8"))
        def line(data,color,dash=False):
            if len(data)<2:return
            pts=[QPointF(box.left()+i*box.width()/(len(data)-1),box.bottom()-(v-low)*box.height()/span) for i,v in enumerate(data)];path=QPainterPath(pts[0])
            for pt in pts[1:]:path.lineTo(pt)
            pen=QPen(QColor(color),2.5);pen.setStyle(Qt.PenStyle.DashLine if dash else Qt.PenStyle.SolidLine);p.setPen(pen);p.drawPath(path)
        line(self.previous,"#b5bdc6",True);line(self.current,BLUE)


class KpiCard(QFrame):
    def __init__(self,title):
        super().__init__();self.setObjectName("commerceCard");l=QHBoxLayout(self);l.setContentsMargins(16,13,14,13);text=QVBoxLayout();self.label=QLabel(title);self.label.setObjectName("commerceLabel");self.value=QLabel("—");self.value.setObjectName("commerceValue");self.compare=QLabel("—");self.compare.setObjectName("commerceCompare");text.addWidget(self.label);text.addWidget(self.value);text.addWidget(self.compare);l.addLayout(text);l.addStretch();self.spark=Sparkline();l.addWidget(self.spark)
    def set_data(self,value,comparison,series,positive=None):
        self.value.setText(value);self.compare.setText(comparison);self.compare.setStyleSheet(f"color:{GREEN if positive else RED if positive is False else '#6d7175'}");self.spark.set_values(series)


class CommerceDashboardPage(Page):
    def __init__(self,db:Database):
        super().__init__(db);outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);host=QWidget();host.setObjectName("commerceCanvas");self.body=QVBoxLayout(host);self.body.setContentsMargins(24,22,24,32);self.body.setSpacing(14);scroll.setWidget(host);outer.addWidget(scroll)
        top=QHBoxLayout();titles=QVBoxLayout();heading=QLabel("Overview");heading.setObjectName("commerceTitle");self.caption=QLabel();self.caption.setObjectName("commerceMuted");titles.addWidget(heading);titles.addWidget(self.caption);top.addLayout(titles);top.addStretch();self.range=QComboBox();self.range.addItems(["This month","Last 30 days","Last 90 days","This year","All time"]);self.range.currentIndexChanged.connect(self.refresh);top.addWidget(self.range);button=QPushButton("↻  Refresh");button.setObjectName("commerceButton");button.clicked.connect(self.refresh);top.addWidget(button);self.body.addLayout(top)
        self.comparison=QLabel();self.comparison.setObjectName("commercePill");self.body.addWidget(self.comparison,0,Qt.AlignmentFlag.AlignLeft)
        grid=QGridLayout();grid.setSpacing(12);self.cards={}
        for i,(key,label) in enumerate((("profit","Gross profit"),("margin","Average deal margin"),("sold","Vehicles fulfilled"),("days","Average days to sell"))):self.cards[key]=KpiCard(label);grid.addWidget(self.cards[key],0,i)
        self.body.addLayout(grid)
        main=QHBoxLayout();main.setSpacing(12);chart_card=QFrame();chart_card.setObjectName("commerceCard");cl=QVBoxLayout(chart_card);cl.setContentsMargins(17,15,17,13);cl.addWidget(self.section("Gross profit over time"));self.chart_value=QLabel("—");self.chart_value.setObjectName("commerceHero");cl.addWidget(self.chart_value);self.chart=TrendChart();cl.addWidget(self.chart);legend=QLabel("━ Selected period     ┄ Previous period");legend.setObjectName("commerceMuted");cl.addWidget(legend,0,Qt.AlignmentFlag.AlignCenter);main.addWidget(chart_card,2)
        breakdown=QFrame();breakdown.setObjectName("commerceCard");bl=QVBoxLayout(breakdown);bl.setContentsMargins(17,15,17,15);bl.addWidget(self.section("Vehicle sales breakdown"));self.breakdown=QVBoxLayout();bl.addLayout(self.breakdown);bl.addStretch();main.addWidget(breakdown,1);self.body.addLayout(main)
        lower=QGridLayout();lower.setSpacing(12);self.stock_panel,self.stock_rows=self.panel("Live inventory","Stock currently working for you");self.product_panel,self.product_rows=self.panel("Top vehicles by profit","Your best-performing products");self.activity_panel,self.activity_rows=self.panel("Operations today","Appointments, calls and workflow");lower.addWidget(self.stock_panel,0,0);lower.addWidget(self.product_panel,0,1);lower.addWidget(self.activity_panel,0,2);self.body.addLayout(lower)
        self.setStyleSheet("""QWidget#commerceCanvas{background:#f6f6f7;color:#202223} QFrame#commerceCard{background:white;border:1px solid #e1e3e5;border-radius:12px} QLabel#commerceTitle{font-size:25px;font-weight:700;color:#202223} QLabel#commerceSection{font-size:13px;font-weight:700;color:#303336} QLabel#commerceLabel{font-size:11px;font-weight:600;color:#4f565d} QLabel#commerceValue{font-size:19px;font-weight:700;color:#202223} QLabel#commerceHero{font-size:27px;font-weight:700;color:#202223} QLabel#commerceMuted{font-size:11px;color:#6d7175} QLabel#commerceCompare{font-size:10px;color:#6d7175} QLabel#commercePill{background:white;border:1px solid #dfe3e8;border-radius:7px;padding:7px 11px;color:#4f565d;font-size:11px} QLabel#commerceRow{padding:10px 2px;border-bottom:1px solid #edf0f2;color:#3b4147;font-size:11px} QLabel#commerceRowValue{padding:10px 2px;border-bottom:1px solid #edf0f2;color:#202223;font-size:11px;font-weight:700} QComboBox,QPushButton#commerceButton{background:white;color:#202223;border:1px solid #c9cccf;border-radius:7px;padding:8px 12px;font-weight:600} QComboBox QAbstractItemView{background:white;color:#202223;selection-background-color:#e7f1ff}""")
        self.refresh()

    def section(self,text):label=QLabel(text);label.setObjectName("commerceSection");return label
    def panel(self,title,subtitle):
        panel=QFrame();panel.setObjectName("commerceCard");layout=QVBoxLayout(panel);layout.setContentsMargins(17,15,17,15);layout.addWidget(self.section(title));sub=QLabel(subtitle);sub.setObjectName("commerceMuted");layout.addWidget(sub);rows=QVBoxLayout();layout.addLayout(rows);layout.addStretch();return panel,rows
    def clear(self,layout):
        while layout.count():
            item=layout.takeAt(0)
            if item.widget():item.widget().deleteLater()
            elif item.layout():self.clear(item.layout())
    def row(self,layout,label,value,color=None):
        line=QHBoxLayout();left=QLabel(label);left.setObjectName("commerceRow");right=QLabel(value);right.setObjectName("commerceRowValue");right.setAlignment(Qt.AlignmentFlag.AlignRight)
        if color:right.setStyleSheet(f"color:{color}")
        line.addWidget(left,2);line.addWidget(right,1);layout.addLayout(line)
    def period(self):
        today=date.today();mode=self.range.currentText()
        if mode=="This month":start=today.replace(day=1)
        elif mode=="Last 30 days":start=today-timedelta(days=29)
        elif mode=="Last 90 days":start=today-timedelta(days=89)
        elif mode=="This year":start=today.replace(month=1,day=1)
        else:start=date(2020,1,1)
        days=(today-start).days+1;pend=start-timedelta(days=1);pstart=pend-timedelta(days=days-1);return start,today,pstart,pend
    @staticmethod
    def profit(row):
        cost=float(row["initial_owner_payout_aed"] or row["purchase_price_aed"] or 0) if row["purchase_type"]=="consignment" else float(row["purchase_price_aed"] or 0)
        return float(row["sold_price_aed"] or 0)-cost
    @staticmethod
    def delta(current,previous,invert=False):
        if not previous:return ("New in selected period",True if current else None)
        pct=(current-previous)/abs(previous)*100;good=pct>=0;good=not good if invert else good;return (f"{'↑' if pct>=0 else '↓'} {abs(pct):.0f}% vs previous period",good)

    def refresh(self):
        start,end,pstart,pend=self.period();vehicles=self.db.query("SELECT * FROM vehicles ORDER BY COALESCE(sold_date,purchased_date)")
        selected=lambda r,a,b:r["status"]=="sold" and r["sold_date"] and a.isoformat()<=str(r["sold_date"])[:10]<=b.isoformat();sold=[r for r in vehicles if selected(r,start,end)];previous=[r for r in vehicles if selected(r,pstart,pend)];stock=[r for r in vehicles if r["status"]=="stock"]
        profit=sum(self.profit(r) for r in sold);old_profit=sum(self.profit(r) for r in previous);revenue=sum(float(r["sold_price_aed"] or 0) for r in sold);cost=revenue-profit
        margins=[100*self.profit(r)/float(r["sold_price_aed"] or 1) for r in sold if r["sold_price_aed"]];old_margins=[100*self.profit(r)/float(r["sold_price_aed"] or 1) for r in previous if r["sold_price_aed"]]
        holding=lambda r:max(0,(date.fromisoformat(str(r["sold_date"])[:10])-date.fromisoformat(str(r["purchased_date"])[:10])).days);days=[holding(r) for r in sold];old_days=[holding(r) for r in previous]
        span=max(1,(end-start).days+1);count=min(14,span);width=max(1,ceil(span/count))
        def series(rows,period_start):
            values=[0.0]*count
            for r in rows:values[min(count-1,(date.fromisoformat(str(r["sold_date"])[:10])-period_start).days//width)]+=self.profit(r)
            return values
        current_series,old_series=series(sold,start),series(previous,pstart);avg=sum(margins)/max(1,len(margins));old_avg=sum(old_margins)/max(1,len(old_margins));avg_days=sum(days)/max(1,len(days));old_avg_days=sum(old_days)/max(1,len(old_days))
        for key,value,comparison,positive,values in (("profit",money(profit),*self.delta(profit,old_profit),current_series),("margin",f"{avg:.1f}%",*self.delta(avg,old_avg),margins or [0]),("sold",str(len(sold)),*self.delta(len(sold),len(previous)),[1]*len(sold) or [0]),("days",f"{avg_days:.0f} days" if days else "—",*self.delta(avg_days,old_avg_days,True),days or [0])):self.cards[key].set_data(value,comparison,values,positive)
        self.chart_value.setText(money(profit));self.chart.set_values(current_series,old_series);self.comparison.setText(f"◷  {start:%d %b %Y} – {end:%d %b %Y}     Compare: {pstart:%d %b} – {pend:%d %b %Y}")
        self.clear(self.breakdown)
        for label,value,color in (("Gross vehicle sales",money(revenue),None),("Vehicle cost / owner payout",f"− {money(cost)}",None),("Gross profit",money(profit),GREEN if profit>=0 else RED),("Cash purchase profit",money(sum(self.profit(r) for r in sold if r["purchase_type"]=="cash")),None),("Consignment profit",money(sum(self.profit(r) for r in sold if r["purchase_type"]=="consignment")),None),("Average sold value",money(revenue/max(1,len(sold))),None)):self.row(self.breakdown,label,value,color)
        self.clear(self.stock_rows);invested=sum(float(r["purchase_price_aed"] or 0) for r in stock if r["purchase_type"]=="cash");expected=sum(max(0,float(r["expected_sale_price_aed"] or 0)-float(r["purchase_price_aed"] or 0)) for r in stock);month=self.db.query("SELECT purchasing_budget_aed FROM performance_months WHERE month=?",(date.today().strftime("%Y-%m"),));budget=float(month[0]["purchasing_budget_aed"]) if month else 0
        for label,value,color in (("Cars currently in stock",str(len(stock)),None),("Capital tied up",money(invested),None),("Expected stock profit",money(expected),GREEN),("Budget deployed",f"{100*invested/budget:.0f}%" if budget else "—",None),("In prep / repair",str(sum(1 for r in stock if any(x in str(r["external_stock_status"] or "").lower() for x in ("prep","repair")))),None)):self.row(self.stock_rows,label,value,color)
        self.clear(self.product_rows)
        for r in sorted(sold,key=self.profit,reverse=True)[:5]:self.row(self.product_rows,str(r["vehicle_name"]),money(self.profit(r)),GREEN)
        if not sold:self.row(self.product_rows,"No realised sales in this period","—")
        self.clear(self.activity_rows);today=date.today().isoformat();calls=self.db.query("SELECT COALESCE(SUM(call_count),0) n FROM kpi_calls WHERE substr(called_at,1,10)=?",(today,))[0]["n"];appointments=self.db.query("SELECT COUNT(*) n FROM pipeline_appointments WHERE appointment_date=?",(today,))[0]["n"];matches=self.db.query("SELECT COUNT(*) n FROM pipeline_appointments WHERE appointment_date=? AND match_grade='green'",(today,))[0]["n"]
        for label,value,color in (("Appointments today",str(appointments),None),("Exact stock matches",str(matches),GREEN if matches else None),("Calls logged today",str(calls),None),("Awaiting market research",str(sum(1 for r in stock if str(r["deal_drive_research_status"] or "") not in ("complete","completed","researched"))),None),("Workflow-linked stock",f"{sum(1 for r in stock if r['external_stock_number'])} / {len(stock)}",None)):self.row(self.activity_rows,label,value,color)
        self.caption.setText(f"Live Runway analytics · {len(stock)} active vehicles · refreshed {datetime.now():%H:%M}")
