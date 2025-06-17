import sys 
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QGridLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QPlainTextEdit
from PySide6.QtGui import QIcon, QFont, QRegularExpressionValidator
from PySide6.QtCore import Qt, Signal, QObject, QRegularExpression

class main_ui(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Python尾盤改單小幫手(教學範例，僅供參考)")
        self.resize(1200, 700)

        # 製作上下排列layout上為庫存表，下為log資訊
        layout = QVBoxLayout()

        title_font_size = "20px"
        
        # 製作上下排列layout上為庫存表，下為log資訊
        layout = QVBoxLayout()
        # 現有委託表表頭
        self.table_header = ['股票名稱', '股票代號', '委託單號', '委託張數', '買賣方向', '委託價格', '執行狀態']
        
        self.tablewidget = QTableWidget(0, len(self.table_header))
        self.tablewidget.setHorizontalHeaderLabels([f'{item}' for item in self.table_header])

        # 趴數設定區layout
        layout_condition = QGridLayout()
        label_modify_time = QLabel('改單時間:')
        layout_condition.addWidget(label_modify_time, 0, 0)
        self.lineEdit_default_modify_time = QLineEdit()
        self.lineEdit_default_modify_time.setText(str("13:29:58"))
        layout_condition.addWidget(self.lineEdit_default_modify_time, 0, 1)

        # MA參數設定區layout
        layout_control = QHBoxLayout()

        # 啟動按鈕
        self.button_order_fetch = QPushButton('抓取委託')
        self.button_order_fetch.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.MinimumExpanding)
        self.button_order_fetch.setStyleSheet("QPushButton { font-size: 24px; font-weight: bold; }")
        layout_control.addWidget(self.button_order_fetch)

        # 啟動按鈕
        self.button_start = QPushButton('開始監控')
        self.button_start.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.MinimumExpanding)
        self.button_start.setStyleSheet("QPushButton { font-size: 24px; font-weight: bold; }")
        layout_control.addWidget(self.button_start)

        # 停止按鈕
        self.button_stop = QPushButton('停止監控')
        self.button_stop.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.MinimumExpanding)
        self.button_stop.setStyleSheet("QPushButton { font-size: 24px; font-weight: bold; }")
        layout_control.addWidget(self.button_stop)
        self.button_stop.setVisible(False)
        
        # layout_sim = QHBoxLayout()
        # self.button_WS = QPushButton('開始報價')
        # self.button_filled = QPushButton('成交回報')
        # layout_sim.addWidget(self.button_WS)
        # layout_sim.addWidget(self.button_filled)

        layout_log = QVBoxLayout()
        # 監控區layout設定
        label_log_text = QLabel('執行日誌')
        label_log_text.setStyleSheet(f"QLabel {{ font-size: {title_font_size}; font-weight: bold; }}")
        label_log_text.setAlignment(Qt.AlignLeft)
        layout_log.addWidget(label_log_text, 0)

        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        layout_log.addWidget(self.log_text, 1)

        layout.addWidget(self.tablewidget, stretch=10)
        layout.addLayout(layout_condition, stretch=1)
        layout.addLayout(layout_control, stretch=1)
        # layout.addLayout(layout_sim)
        layout.addLayout(layout_log, stretch=5)
        self.setLayout(layout)

if __name__ == "__main__":

    if not QApplication.instance():
        app = QApplication(sys.argv)
    else:
        app = QApplication.instance()

    multi_out_ui = main_ui()
    font = QFont("Microsoft JhengHei", 12)  # 字體名稱和大小
    app.setFont(font)
    multi_out_ui.show()

    sys.exit(app.exec())