from login_gui_v3 import login_handler
from logger_pyside6 import my_logger
from price_changer_ui import main_ui

import os
import sys
import configparser
import pandas as pd
from datetime import datetime, timedelta
import certifi
from enum import Enum
import threading
import time

import fubon_neo
from fubon_neo.sdk import FubonSDK, Mode, Order
from fubon_neo.constant import TimeInForce, OrderType, PriceType, MarketType, BSAction

from PySide6.QtWidgets import QTableWidgetItem, QFileDialog, QApplication, QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QGridLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QPlainTextEdit
from PySide6.QtGui import QIcon, QTextCursor, QFont
from PySide6.QtCore import Qt, Signal, QObject, QTimer

class EXESTATUS(Enum):
    MONITORING = "監控中"
    SUCCESS = "成功改單"
    FAILED = "改單失敗"
    PAUSED = "-"

class Communicate(QObject):
    # 定義一個帶參數的信號
    log_signal = Signal(str)
    modify_res_signal = Signal(str, object)

class MainApp(QWidget):
    def __init__(self, login_handler):
        super().__init__()

        os.environ['SSL_CERT_FILE'] = certifi.where()
        self.ws_mode = Mode.Normal
        self.login_handler = login_handler
        self.sdk = self.login_handler.sdk
        self.sdk.init_realtime(self.ws_mode) # 建立行情連線

        self.reststock = sdk.marketdata.rest_client.stock
        self.wsstock = sdk.marketdata.websocket_client.stock
        self.active_account = self.login_handler.active_account

        self.pc_ui = main_ui()
        
        # 將 main_ui 的佈局設定到 MainWindow
        self.setLayout(self.pc_ui.layout())

        self.setWindowIcon(self.login_handler.windowIcon())
        self.setWindowTitle(self.pc_ui.windowTitle())
        self.resize(1300, 700)

        # communicator init and slot function connect
        self.communicator = Communicate()
        self.communicator.log_signal.connect(self.print_log)
        self.communicator.modify_res_signal.connect(self.modify_res_update)

        self.pc_logger = my_logger(log_signal=self.communicator.log_signal, file_name="pc_app")
        self.logger = self.pc_logger.logger
        self.logger.info(f"Current SDK Version: {fubon_neo.__version__}")
        self.logger.info(f"Current Account:\n{self.active_account}")

        self.pc_table = self.pc_ui.tablewidget
        self.table_header = self.pc_ui.table_header
        self.button_order_fetch = self.pc_ui.button_order_fetch
        self.button_start = self.pc_ui.button_start
        self.button_stop = self.pc_ui.button_stop
        self.lineEdit_default_modify_time = self.pc_ui.lineEdit_default_modify_time

        # table control variable
        self.col_idx_map = dict(zip(self.pc_ui.table_header, range(len(self.pc_ui.table_header))))
        self.row_idx_map = {}

        # table slot
        # self.pc_table.itemChanged.connect(self.on_item_changed)
        self.button_order_fetch.clicked.connect(self.fetch_order_n_show)
        self.button_start.clicked.connect(self.on_start_clicked)
        self.button_stop.clicked.connect(self.on_stop_clicked)

        self.stock_name_map = self.stock_name_fetch()
        self.limit_ud_dict = {}
        self.all_ud_orders = {}
        self.exe_up_buy_orders = {}
        self.exe_down_sell_orders = {}

        # 設定今天 13:29:58.000（如果已過，改成明天）
        now = datetime.now()
        self.target_time = now.replace(hour=18, minute=2, second=20, microsecond=0)
        self.check_timer = QTimer()
        self.check_timer.setInterval(100)  # 檢查間隔（你可改為 50 或 200 毫秒）
        self.check_timer.setSingleShot(False)
        self.check_timer.timeout.connect(self.check_time)

        self.remain_seconds = 1000000
        self.sdk.set_on_event(self.on_event)

    # A callback to receive Event data
    def on_event(self, code, msg):
        self.logger.info(f"{code}, {msg}")
        if code == '301':
            self.logger.info("pong missed")
        elif code == '300':
            max_retry = 10
            self.logger.debug("Trade connection down")
            for i in range(max_retry):
                self.logger.info(f"Relogin {i}/{max_retry}")
                relogin_res = self.login_handler.re_login()
                    
                if relogin_res.is_success == False:
                    self.logger.info(f"Relogin Fail: {relogin_res.message}, retry after 3 seconds")
                    time.sleep(3)
                else:
                    self.sdk, self.active_account = self.login_handler.sdk, self.login_handler.active_account
                    self.logger.info(f"Relogin Success, current account:\n{self.active_account}")
                    return True

            self.logger.error(f"Relogin max retry {max_retry} exceed")

    def modify_res_update(self, order_no, modify_res):
        if modify_res.is_success:
            self.logger.info(f"[{order_no}] 改單成功, 代號: {modify_res.data.stock_no}, 現價: {modify_res.data.after_price}")
            for row in range(self.pc_table.rowCount()):
                if self.pc_table.item(row, self.col_idx_map['委託單號']).text() == order_no:
                    self.pc_table.item(row, self.col_idx_map['執行狀態']).setText(EXESTATUS.SUCCESS.value)
                    return
        else:
            self.logger.error(f"[{order_no}] 改單失敗: {modify_res.message}")
            for row in range(self.pc_table.rowCount()):
                if self.pc_table.item(row, self.col_idx_map['委託單號']).text() == order_no:
                    self.pc_table.item(row, self.col_idx_map['執行狀態']).setText(EXESTATUS.FAILED.value)
                    return

    def modify_price_order(self, order_content):
        symbol = order_content.stock_no
        if order_content.buy_sell == BSAction.Buy:
            modify_price = str(self.limit_ud_dict[symbol]['down'])
        elif order_content.buy_sell == BSAction.Sell:
            modify_price = str(self.limit_ud_dict[symbol]['up'])

        modify_price_obj = self.sdk.stock.make_modify_price_obj(order_content, modify_price)
        modify_res = sdk.stock.modify_price(self.active_account, modify_price_obj)
        self.communicator.modify_res_signal.emit(order_content.order_no, modify_res)

    def check_time(self):
        now = datetime.now()
        cur_remain = round((self.target_time-now).total_seconds())
        if now >= self.target_time:
            try:
                self.logger.info(f"!!!觸發時間：{now.strftime('%H:%M:%S.%f')}!!!")
                if self.exe_up_buy_orders:
                    for order_no, order_content in self.exe_up_buy_orders.items():
                        buy_order_thread = threading.Thread(target=self.modify_price_order, args=(order_content,))
                        buy_order_thread.start()
                if self.exe_down_sell_orders:
                    for order_no, order_content in self.exe_down_sell_orders.items():
                        sell_order_thread = threading.Thread(target=self.modify_price_order, args=(order_content,))
                        sell_order_thread.start()
            except Exception as e:
                self.logger.error(f"!!!時間觸發，丟單錯誤!!!")

            self.check_timer.stop()
        elif self.remain_seconds != cur_remain:
            self.logger.info(f"***觸發倒數{cur_remain}秒***")
            self.remain_seconds = cur_remain

    def start_monitor(self):
        now = datetime.now()
        
        if self.target_time < now:
            self.target_time += timedelta(days=1)

        self.logger.info(f"開始監控目標：{self.target_time.strftime('%H:%M:%S')}")
        self.check_timer.start()

    def stop_monitor(self):
        now = datetime.now()
        self.logger.info(f"停止監控目標：{self.target_time.strftime('%H:%M:%S')} 現在時間:{now}")
        self.check_timer.stop()

    def lock_col_items(self, table: QTableWidget, col_name):
        for row in range(table.rowCount()):
            item = table.item(row, self.col_idx_map[col_name])
            if item is not None:
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)  # 鎖定：無法編輯、無法勾選
    
    def open_col_items(self, table: QTableWidget, col_name):
        for row in range(table.rowCount()):
            item = table.item(row, self.col_idx_map[col_name])
            if item is not None:
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable | ~Qt.ItemIsSelectable & ~Qt.ItemIsUserTristate)

    def on_start_clicked(self):
        if self.pc_table.rowCount() == 0:
            self.logger.info("Table is empty!!")
            return
        
        try:
            change_time_str = self.lineEdit_default_modify_time.text()
            now = datetime.now()
            self.target_time = datetime.strptime(change_time_str, "%H:%M:%S")
            self.target_time = self.target_time.replace(year=now.year, month=now.month, day=now.day)
            self.logger.info(f"Target Time: {self.target_time}")
        except Exception as e:
            self.logger.error(f"請填入正確時間格式 HH:MM:SS, {e}")
            return
        
        self.button_order_fetch.setEnabled(False)
        self.lock_col_items(self.pc_table, '股票名稱')

        self.button_start.setVisible(False)
        self.button_start.setEnabled(False)
        self.button_stop.setVisible(True)
        self.button_stop.setEnabled(True)
        self.lineEdit_default_modify_time.setEnabled(False)

        for row in range(self.pc_table.rowCount()):
            check_item = self.pc_table.item(row, self.col_idx_map['股票名稱'])
            if check_item.checkState() == Qt.Checked:
                order_no = self.pc_table.item(row, self.col_idx_map['委託單號']).text()
                bs_direction = self.pc_table.item(row, self.col_idx_map['買賣方向']).text()
                if bs_direction == "Buy":
                    self.exe_up_buy_orders[order_no] = self.all_ud_orders[order_no]
                elif bs_direction == "Sell":
                    self.exe_down_sell_orders[order_no] = self.all_ud_orders[order_no]
                self.pc_table.item(row, self.col_idx_map['執行狀態']).setText(EXESTATUS.MONITORING.value)

        self.start_monitor()

    def on_stop_clicked(self):
        self.button_order_fetch.setEnabled(True)
        self.open_col_items(self.pc_table, '股票名稱')

        self.button_start.setVisible(True)
        self.button_start.setEnabled(True)
        self.button_stop.setVisible(False)
        self.button_stop.setEnabled(False)
        self.lineEdit_default_modify_time.setEnabled(True)

        for row in range(self.pc_table.rowCount()):
            self.pc_table.item(row, self.col_idx_map['執行狀態']).setText(EXESTATUS.PAUSED.value)

        self.stop_monitor()

    def fetch_order_n_show(self):
        cur_orders_res = sdk.stock.get_order_results(self.active_account)

        if cur_orders_res.is_success:
            self.all_ud_orders = {}
            self.exe_up_buy_orders = {}
            self.exe_down_sell_orders = {}

            for order in cur_orders_res.data:
                if order.status == 10:
                    if order.stock_no not in self.limit_ud_dict:
                        ticker_res = self.reststock.intraday.ticker(symbol=order.stock_no)
                        self.limit_ud_dict[order.stock_no] = {}
                        self.limit_ud_dict[order.stock_no]['up'] = ticker_res['limitUpPrice']
                        self.limit_ud_dict[order.stock_no]['down'] = ticker_res['limitDownPrice']
                    
                    cur_up = self.limit_ud_dict[order.stock_no]['up']
                    cur_down = self.limit_ud_dict[order.stock_no]['down']

                    if order.after_price == cur_up and order.buy_sell == BSAction.Buy:
                        self.all_ud_orders[order.order_no] = order
                        self.logger.info(f"[漲停買]{order.order_no} fetched, Buy_Sell: {order.buy_sell}, Price: {order.after_price}")

                    elif order.after_price == cur_down and order.buy_sell == BSAction.Sell:
                        self.all_ud_orders[order.order_no] = order
                        self.logger.info(f"[跌停賣]{order.order_no} fetched, Buy_Sell: {order.buy_sell}, Price: {order.after_price}")
        else:
            self.logger.error(f"Order Results Fetch Failed, {cur_orders_res.message}")
            return
        
        self.logger.info("漲停買 跌停賣 委託抓取完成")

        self.pc_table.clearContents()
        self.pc_table.setRowCount(0)

        if self.all_ud_orders:
            self.table_init(self.all_ud_orders)

    def table_init(self, cur_orders):
        for order_no, order_content in cur_orders.items():
            self.logger.debug(f"update [{order_no}]")

            stock_symbol = order_content.stock_no
            stock_name = self.stock_name_map[stock_symbol]
            row = self.pc_table.rowCount()
            self.pc_table.insertRow(row)
            self.row_idx_map[stock_symbol] = row

            # ['股票名稱', '股票代號', '委託單號', '委託張數', '買賣方向', '委託價格', '執行狀態']
            for j in range(len(self.table_header)):
                item = QTableWidgetItem()
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if self.table_header[j] == '股票名稱':
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                    item.setCheckState(Qt.Checked)
                    item.setText(stock_name)
                    self.pc_table.setItem(row, j, item)
                elif self.table_header[j] == '股票代號':
                    item.setText(stock_symbol)
                    self.pc_table.setItem(row, j, item)
                elif self.table_header[j] == '委託單號':
                    item.setText(str(order_no))
                    self.pc_table.setItem(row, j, item)
                elif self.table_header[j] == '委託張數':
                    item.setText(str(order_content.after_qty//1000))
                    self.pc_table.setItem(row, j, item)
                elif self.table_header[j] == '買賣方向':
                    if order_content.buy_sell == BSAction.Buy:
                        item.setText(str("Buy"))
                    elif order_content.buy_sell == BSAction.Sell:
                        item.setText(str("Sell"))
                    else:
                        item.setText('-')
                    self.pc_table.setItem(row, j, item)
                elif self.table_header[j] == '委託價格':
                    item.setText(f'{order_content.after_price}')
                    self.pc_table.setItem(row, j, item)
                elif self.table_header[j] == '執行狀態':
                    item.setText(EXESTATUS.PAUSED.value)
                    self.pc_table.setItem(row, j, item)

    # 用Snapshot抓取股票中文名稱
    def stock_name_fetch(self):
        TSE_res = self.reststock.snapshot.quotes(market='TSE')
        OTC_res = self.reststock.snapshot.quotes(market='OTC')
        TIB_res = self.reststock.snapshot.quotes(market='TIB')

        TSE_df = pd.DataFrame(TSE_res["data"])
        OTC_df = pd.DataFrame(OTC_res["data"])
        TIB_df = pd.DataFrame(TIB_res["data"])

        stock_df = pd.concat([TSE_df, OTC_df, TIB_df])
        name_dict = pd.Series(stock_df['name'].values, index=stock_df['symbol']).to_dict()
        self.logger.info("股票名稱抓取完成")
        return name_dict

    def print_log(self, log_info):
        self.pc_ui.log_text.appendPlainText(log_info)
        self.pc_ui.log_text.moveCursor(QTextCursor.End)

if __name__ == "__main__":
    trade_env_file = "./trade_env.ini"
    trade_env_config = configparser.ConfigParser()
    if os.path.exists(trade_env_file):
        trade_env_config.read(trade_env_file)

    sim_url = None
    try:
        sim_url = trade_env_config.get('DEFAULT', 'SIM')
    except configparser.NoOptionError:
        print("使用正式環境")

    try:
        if not sim_url:
            sdk = FubonSDK(30, 2)
        else:
            sdk = FubonSDK(30, 2, sim_url)
        
    except ValueError:
        raise ValueError("請確認網路連線")
    
    if not QApplication.instance():
        app = QApplication(sys.argv)
    else:
        app = QApplication.instance()

    font = QFont("Microsoft JhengHei", 12)  # 字體名稱和大小
    app.setFont(font)
    form = login_handler(sdk, MainApp, 'out.ico')
    form.show()
    
    sys.exit(app.exec())