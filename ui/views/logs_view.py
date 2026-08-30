from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton
)
from PySide6.QtCore import Qt
from database.db import db


class LogsView(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        # ─── Page Header ───
        header = QLabel("سجل أحداث النظام")
        header.setProperty("class", "section-title")
        layout.addWidget(header)

        subtitle = QLabel("جميع العمليات والأخطاء والاستجابات التقنية مسجلة هنا للمراجعة والتشخيص.")
        subtitle.setProperty("class", "section-subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # ─── Top Bar ───
        top_bar = QHBoxLayout()

        self.btn_refresh = QPushButton("🔄  تحديث")
        self.btn_refresh.setProperty("class", "secondary-btn")
        self.btn_refresh.clicked.connect(self.load_logs)
        top_bar.addWidget(self.btn_refresh)

        self.btn_clear = QPushButton("🗑️  مسح العرض")
        self.btn_clear.setProperty("class", "secondary-btn")
        self.btn_clear.clicked.connect(lambda: self.log_display.clear())
        top_bar.addWidget(self.btn_clear)

        top_bar.addStretch()

        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color: #64748b; font-size: 12px;")
        top_bar.addWidget(self.count_label)

        layout.addLayout(top_bar)

        # ─── Log Display ───
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setStyleSheet(
            "font-family: 'Cascadia Code', 'Consolas', 'Courier New', monospace;"
            "font-size: 12px;"
            "background-color: #0c1222;"
            "border: 1px solid #1e293b;"
            "border-radius: 8px;"
            "padding: 10px;"
            "color: #94a3b8;"
            "line-height: 1.6;"
        )
        layout.addWidget(self.log_display)

        self.load_logs()

    def load_logs(self):
        logs = db.get_system_logs(300)
        lines = []
        for log in logs:
            time_str = log.get("created_at", "")
            level = log.get("level", "INFO")
            module = log.get("module", "APP")
            msg = log.get("message", "")

            # Color-code by level
            if level == "ERROR":
                color = "#f87171"
            elif level == "WARNING":
                color = "#fbbf24"
            else:
                color = "#94a3b8"

            lines.append(
                f'<span style="color:#475569;">[{time_str}]</span> '
                f'<span style="color:{color};font-weight:bold;">[{level}]</span> '
                f'<span style="color:#64748b;">[{module}]</span> '
                f'<span style="color:#e2e8f0;">{msg}</span>'
            )

        if not lines:
            html_content = '<span style="color:#64748b;">لا توجد سجلات حتى الآن.</span>'
        else:
            html_content = "<br>".join(lines)

        self.log_display.setHtml(html_content)
        self.count_label.setText(f"{len(logs)} سجل")
