from auto_save_dict import AutoSaveDict
from login_gui_v3 import login_handler
from multi_out_ui import main_ui
from logger_pyside6 import my_logger

import os
import sys
import math
import time
import json
import threading
import traceback
import configparser
import pandas as pd
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

import fubon_neo
from fubon_neo.sdk import FubonSDK, Mode, Order
from fubon_neo.constant import TimeInForce, OrderType, PriceType, MarketType, BSAction

from PySide6.QtWidgets import QTableWidgetItem, QFileDialog, QApplication, QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QGridLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QPlainTextEdit
from PySide6.QtGui import QIcon, QTextCursor, QFont
from PySide6.QtCore import Qt, Signal, QObject
import certifi

class fake_filled_data:
    date = "2023/09/15"
    branch_no = "6460"
    account = "26"
    order_no = "bA422"
    stock_no = "1101"
    buy_sell = BSAction.Sell
    filled_no = "00000000001"
    filled_avg_price = 35.2
    filled_qty = 1000
    filled_price = 35.2
    order_type = OrderType.Stock
    filled_time = "10:31:00.931"
    user_def = None

    def __str__(self):
        indent = "    "  # 縮排的空格
        return (f"fake_filled_data(\n"
                f"{indent}date='{self.date}',\n"
                f"{indent}branch_no='{self.branch_no}',\n"
                f"{indent}account='{self.account}',\n"
                f"{indent}order_no='{self.order_no}',\n"
                f"{indent}stock_no='{self.stock_no}',\n"
                f"{indent}buy_sell='{self.buy_sell}',\n"
                f"{indent}filled_no='{self.filled_no}',\n"
                f"{indent}filled_avg_price={self.filled_avg_price},\n"
                f"{indent}filled_qty={self.filled_qty},\n"
                f"{indent}filled_price={self.filled_price},\n"
                f"{indent}order_type='{self.order_type}',\n"
                f"{indent}filled_time='{self.filled_time}',\n"
                f"{indent}user_def='{self.user_def}'\n"
                f")")

class Communicate(QObject):
    # 定義一個帶參數的信號
    log_signal = Signal(str)
    table_init_signal = Signal(dict, dict)
    message_update_signal = Signal(dict)
    filled_data_signal = Signal(dict)

class MainApp(QWidget):
    def __init__(self, login_handler):
        super().__init__()

        self.ws_mode = Mode.Normal
        self.login_handler = login_handler
        self.sdk = self.login_handler.sdk
        self.sdk.init_realtime(self.ws_mode) # 建立行情連線

        self.reststock = sdk.marketdata.rest_client.stock
        self.wsstock = sdk.marketdata.websocket_client.stock
        self.active_account = self.login_handler.active_account

        self.multi_out_ui = main_ui()
    
        self.setWindowIcon(self.login_handler.windowIcon())
        self.setWindowTitle(self.multi_out_ui.windowTitle())
        self.resize(1300, 700)

        # 將 main_ui 的佈局設定到 MainWindow
        self.setLayout(self.multi_out_ui.layout())

        # communicator init and slot function connect
        self.communicator = Communicate()
        self.communicator.log_signal.connect(self.print_log)
        self.communicator.table_init_signal.connect(self.table_init)
        self.communicator.message_update_signal.connect(self.message_update)
        self.communicator.filled_data_signal.connect(self.filled_data_update)

        self.inv_logger = my_logger(log_signal=self.communicator.log_signal, file_name="inv_app")
        self.logger = self.inv_logger.logger
        self.logger.info(f"Current SDK Version: {fubon_neo.__version__}")
        self.logger.info(f"Current Account:\n{self.active_account}")
        
        self.inv_rec = AutoSaveDict("inv_rec.json")
        self.trade_config = AutoSaveDict("trade_config.json")
        self.sma_dict = AutoSaveDict("today_sma.json")

        if len(self.trade_config) != 0:
            self.multi_out_ui.lineEdit_default_MA_day.setText(f"{self.trade_config['ma_period']}")
            self.multi_out_ui.lineEdit_MA_batch.setText(f"{self.trade_config['ma_batch']}")
            self.multi_out_ui.lineEdit_MA_gap.setText(f"{self.trade_config['ma_gap']}")
            self.multi_out_ui.lineEdit_default_tp1.setText(f"{self.trade_config['tp1_rate']}")
            self.multi_out_ui.lineEdit_default_tp2.setText(f"{self.trade_config['tp2_rate']}")
            self.multi_out_ui.lineEdit_default_tp3.setText(f"{self.trade_config['tp3_rate']}")

            self.multi_out_ui.lineEdit_tp1_out_pct.setText(f"{self.trade_config['tp1_pct']}")
            self.multi_out_ui.lineEdit_tp2_out_pct.setText(f"{self.trade_config['tp2_pct']}")
            self.multi_out_ui.lineEdit_tp3_out_pct.setText(f"{self.trade_config['tp3_pct']}")

        # table related variable and func
        self.inv_table = self.multi_out_ui.tablewidget
        self.table_header = self.multi_out_ui.table_header
        self.button_start = self.multi_out_ui.button_start
        self.button_stop = self.multi_out_ui.button_stop
        
        # simulated button & slot
        self.button_WS = self.multi_out_ui.button_WS
        self.button_filled = self.multi_out_ui.button_filled
        self.button_WS.clicked.connect(self.fake_ws_data)
        self.button_filled.clicked.connect(self.fake_filled_data)

        # table control variable
        self.col_idx_map = dict(zip(self.multi_out_ui.table_header, range(len(self.multi_out_ui.table_header))))
        self.row_idx_map = {}
        self.hist_dfs = {}

        # table slot
        self.inv_table.itemChanged.connect(self.on_item_changed)
        self.button_start.clicked.connect(self.on_start_clicked)
        self.button_stop.clicked.connect(self.on_stop_clicked)

        # variable init
        self.stock_name_map = self.stock_name_fetch()
        self.subscribed_ids = {}
        self.manully_disconnect = False
        self.relogin_lock = threading.Lock()
        self.user_def = 'Mout'
        self.is_tp1_ordered = {}
        self.is_tp2_ordered = {}
        self.is_tp3_ordered = {}

        self.today = datetime.today()
        self.today_str = datetime.strftime(self.today, "%Y/%m/%d")

        self.init_data_fetch()

        order_results = sdk.stock.get_order_results(self.active_account)

        self.sdk.set_on_event(self.on_event)
        self.sdk.set_on_filled(self.on_filled)
        os.environ['SSL_CERT_FILE'] = certifi.where()

        if order_results.is_success:
            self.logger.debug(f"[Recover] Data Fetched {order_results.data}")
            for order_res in order_results.data:
                if order_res.user_def != None:
                    if self.user_def in order_res.user_def and (order_res.status==10 or order_res.status==40 or order_res.status==50):
                        if order_res.user_def == self.user_def+'1':
                            self.is_tp1_ordered[order_res.stock_no] = order_res.after_qty
                        if order_res.user_def == self.user_def+'2':
                            self.is_tp2_ordered[order_res.stock_no] = order_res.after_qty
                        if order_res.user_def == self.user_def+'3':
                            self.is_tp3_ordered[order_res.stock_no] = order_res.after_qty

                        row = self.row_idx_map[order_res.stock_no]

                        triggered_share_item = self.inv_table.item(row, self.col_idx_map['觸發股數'])
                        triggered_share = int(triggered_share_item.text())
                        triggered_share_item.setText(f"{triggered_share+order_res.after_qty}")

                        filled_share_item = self.inv_table.item(row, self.col_idx_map['程式成交'])
                        filled_share = int(filled_share_item.text())
                        filled_share_item.setText(f"{filled_share+order_res.filled_qty}")
                        self.logger.debug(f"[Recover][{order_res.stock_no}][{order_res.order_no}][{order_res.after_qty}][{order_res.filled_qty}]")
        else:
            self.logger.error(f"[Recover] 今日委託撈取失敗，{order_results.message}")

    def fake_filled_data(self):
        for symbol in self.row_idx_map.keys():
            triggered_item = self.inv_table.item(self.row_idx_map[symbol], self.col_idx_map['觸發股數'])
            triggered_share = triggered_item.text()
            filled_item = self.inv_table.item(self.row_idx_map[symbol], self.col_idx_map['程式成交'])
            filled_share = filled_item.text()
            phase_item = self.inv_table.item(self.row_idx_map[symbol], self.col_idx_map['出場階段'])
            out_phase = phase_item.text()

            if triggered_share == '0':
                continue
            else:
                triggered_share = int(triggered_share)

            if filled_share == '0':
                filled_share = round((triggered_share//1000)/2)
                filled_share = int(filled_share*1000)
            else:
                filled_share = int(filled_share)
                filled_share = triggered_share - filled_share

            my_fake_filled = fake_filled_data()
            my_fake_filled.account = self.active_account.account
            my_fake_filled.stock_no = symbol
            my_fake_filled.filled_qty = filled_share
            # my_fake_filled.user_def = self.user_def+out_phase
            my_fake_filled_user_def = None
            self.on_filled(None, my_fake_filled)
    
    def fake_ws_data(self):
        json_template = """
        {{
            "event": "data",
            "data": {{
                "symbol": "{symbol}",
                "type": "EQUITY",
                "exchange": "TWSE",
                "market": "TSE",
                "bid": 567,
                "ask": 568,
                "price": {price},
                "size": 4778,
                "volume": 54538,
                "isClose": true,
                "time": 1685338200000000,
                "serial": 6652422
            }},
            "id": "<CHANNEL_ID>",
            "channel": "trades"
        }}
        """

        # 替換 symbol 和 price
        for symbol in self.row_idx_map.keys():
            price_item = self.inv_table.item(self.row_idx_map[symbol], self.col_idx_map['現價'])
            if price_item.text() == '-':
                continue
            else:
                price = float(price_item.text())
            new_price = price + 1

            # 使用 format() 方法替換 (使用關鍵字參數)
            data_with_format = json_template.format(symbol=symbol, price=new_price)
            self.handle_message(data_with_format)

    def filled_data_update(self, filled_data):
        if filled_data['user_def'] == None:
            filled_data['user_def'] = ''

        if self.user_def in filled_data['user_def']:
            symbol = filled_data['stock_no']
            filled_qty = filled_data['filled_qty']
            filled_price = filled_data['filled_price']
            self.logger.info(f"[{symbol}][{filled_data['order_no']}] 程式成交{filled_qty}股，成交價: {filled_price}")

            row = self.row_idx_map[symbol]
            filled_share_item = self.inv_table.item(row, self.col_idx_map['程式成交'])
            old_filled_share = int(filled_share_item.text())
            cur_filled_share = old_filled_share+filled_qty
            filled_share_item.setText(f"{cur_filled_share}")
            triggered_item = self.inv_table.item(row, self.col_idx_map['觸發股數'])
            triggered_share = int(triggered_item.text())

            if cur_filled_share == triggered_share:
                out_phase_item = self.inv_table.item(row, self.col_idx_map['出場階段'])
                out_phase = int(out_phase_item.text())
                out_phase = out_phase+1
                if out_phase == 4:
                    out_phase = 1
                out_phase_item.setText(f"{out_phase}")
        else:
            symbol = filled_data['stock_no']
            filled_qty = filled_data['filled_qty']
            filled_price = filled_data['filled_price']

            if symbol in self.row_idx_map:
                self.logger.info(f"[{symbol}][{filled_data['order_no']}] 手動成交{filled_qty}股，成交價: {filled_price}")

                row = self.row_idx_map[symbol]
                filled_share_item = self.inv_table.item(row, self.col_idx_map['手動成交'])
                old_filled_share = int(filled_share_item.text())
                cur_filled_share = old_filled_share+filled_qty
                filled_share_item.setText(f"{cur_filled_share}")
        

    def filled_data_to_dict(self, content):
        filled_dict = {
            "date": content.date,
            "branch_no": content.branch_no,
            "account": content.account,
            "order_no": content.order_no,
            "stock_no": content.stock_no,
            "buy_sell": content.buy_sell,
            "filled_no": content.filled_no,
            "filled_avg_price": content.filled_avg_price,
            "filled_qty": content.filled_qty,
            "filled_price": content.filled_price,
            "order_type": content.order_type,
            "filled_time": content.filled_time,
            "user_def": content.user_def
        }
        
        return filled_dict

    # 主動回報做基本判斷後轉資料給mainthread
    def on_filled(self, err, content):
        self.logger.info(f'[{content.stock_no}][成交] content:{content}')
        if content.account == self.active_account.account:
            cur_filled_data = self.filled_data_to_dict(content)
            self.communicator.filled_data_signal.emit(cur_filled_data)

    def on_event(self, code, msg):
        self.logger.info(f"event: {code}, msg: {msg}")
        if code == '300':
            if self.relogin_lock.acquire(blocking=False):
                self.try_relogin()
            else:
                self.logger.debug("some thread is relogining")
                
    def ma_delay_order(self, symbol, out_share, price, base_price, base_pct, order_num=2, sleep_seconds=30):
        self.logger.info(f"[place_order][{symbol}] 均線之下，全出觸發，{price}/{base_price} 基準漲幅: {base_pct}%，觸發張數: {out_share}")
        batch_qty = out_share//1000//order_num*1000
        last_batch_qty = batch_qty+(((out_share//1000) % order_num)*1000)

        for i in range(order_num):
            if i != order_num-1:
                tp_res = self.sell_market_order(symbol, batch_qty, f'{self.user_def}ma{i+1}')
                if tp_res.is_success:
                    self.logger.info(f"[place_order][{symbol}][{tp_res.data.order_no}] MA{i+1}: {batch_qty}股，委託成功")
                    self.is_tp1_ordered[symbol] = batch_qty
                else:
                    self.logger.error(f"[{symbol}][MA{i+1}] {tp_res.message}, {batch_qty}股")
            else:
                tp_res = self.sell_market_order(symbol, last_batch_qty, f'{self.user_def}ma{i+1}')
                if tp_res.is_success:
                    self.logger.info(f"[place_order][{symbol}][{tp_res.data.order_no}] MA{i+1} (last): {last_batch_qty}股，委託成功")
                    self.is_tp1_ordered[symbol] = self.is_tp1_ordered[symbol]+last_batch_qty
                else:
                    self.logger.error(f"[{symbol}][MA{i+1}](last): {tp_res.message}, {last_batch_qty}股")
            
            time.sleep(sleep_seconds)

    # 停損停利用的市價單函式
    def sell_market_order(self, stock_symbol, sell_qty, sl_or_tp='Mout'):
        order = Order(
            buy_sell = BSAction.Sell,
            symbol = stock_symbol,
            price =  None,
            quantity =  int(sell_qty),
            market_type = MarketType.Common,
            price_type = PriceType.Market,
            time_in_force = TimeInForce.ROD,
            order_type = OrderType.Stock,
            user_def = sl_or_tp # optional field
        )

        order_res = self.sdk.stock.place_order(self.active_account, order)
        return order_res

    def ceil_to_thousand(self, number):
        return int(math.ceil(number / 1000) * 1000)

    def message_update(self, tick_data):
        self.logger.debug(tick_data)
        symbol = tick_data['symbol']
        row = self.row_idx_map[symbol]

        if self.inv_table.item(row, self.col_idx_map['基準價']).text() == '-':
            return
        
        if 'event' in tick_data:
            if tick_data['event'] == 'snapshot':
                if 'price' in tick_data:
                    price = tick_data['price']
                    base_price = float(self.inv_table.item(row, self.col_idx_map['基準價']).text())
                    base_pct = round((price-base_price)/base_price*100, 2)
                    self.inv_table.item(row, self.col_idx_map['現價']).setText(str(price))
                    self.inv_table.item(row, self.col_idx_map['基準漲幅(%)']).setText(f"{base_pct}%")
        else:
            if 'price' in tick_data:
                price = tick_data['price']
                base_price = float(self.inv_table.item(row, self.col_idx_map['基準價']).text())
                base_pct = round((price-base_price)/base_price*100, 2)
                self.inv_table.item(row, self.col_idx_map['現價']).setText(str(price))
                self.inv_table.item(row, self.col_idx_map['基準漲幅(%)']).setText(f"{base_pct}%")

                out_phase_item = self.inv_table.item(row, self.col_idx_map['出場階段'])
                out_phase = out_phase_item.text()

                ma_item = self.inv_table.item(row, self.col_idx_map['均線之下'])
                ma_status = ma_item.text()

                if out_phase == '1':
                    if base_pct >= self.trade_config['tp1_rate'] and symbol not in self.is_tp1_ordered:
                        lastday_share = int(self.inv_table.item(row, self.col_idx_map['昨日股數']).text())
                        triggered_item = self.inv_table.item(row, self.col_idx_map['觸發股數'])
                        triggered_share = int(triggered_item.text())
                        manul_filled = int(self.inv_table.item(row, self.col_idx_map['手動成交']).text())
                        available_share = lastday_share - triggered_share - manul_filled

                        if ma_status == 'No':
                            out_share = self.ceil_to_thousand(available_share*self.trade_config['tp1_pct']/100)
                            if out_share > available_share:
                                self.logger.error(f"[place_order][{symbol}] 階段 1 觸發，剩餘庫存不足下單 {out_share}/{available_share}")
                                return

                            self.logger.info(f"[place_order][{symbol}] 階段 1 觸發，{price}/{base_price} 基準漲幅: {base_pct}%，觸發張數: {out_share}")
                            tp_res = self.sell_market_order(symbol, out_share, self.user_def+'1')
                            if tp_res.is_success:
                                self.logger.info(f"[place_order][{symbol}][{tp_res.data.order_no}] {out_share}股，委託成功")
                                self.is_tp1_ordered[symbol] = out_share
                                triggered_item.setText(f"{triggered_share+out_share}")
                            else:
                                self.logger.error(f"[{symbol}] {tp_res.message}")
                        elif ma_status == 'Yes':
                            if available_share < 1000:
                                self.logger.error(f"[place_order][{symbol}] 均線之下全出觸發，剩餘庫存不足下單，剩餘庫存:{available_share}")
                                return
                            
                            ## ma delay order
                            ## symbol, out_share, price, base_price, base_pct, sleep_seconds=30
                            ma_order_thread = threading.Thread(target=self.ma_delay_order, args=(symbol, available_share, price, base_price, base_pct, self.trade_config['ma_batch'], self.trade_config['ma_gap']))
                            ma_order_thread.start()

                            triggered_item.setText(f"{triggered_share + available_share}")

                elif out_phase == '2':
                    if base_pct >= self.trade_config['tp2_rate'] and symbol not in self.is_tp2_ordered:
                        lastday_share = int(self.inv_table.item(row, self.col_idx_map['昨日股數']).text())
                        triggered_item = self.inv_table.item(row, self.col_idx_map['觸發股數'])
                        triggered_share = int(triggered_item.text())
                        manul_filled = int(self.inv_table.item(row, self.col_idx_map['手動成交']).text())
                        available_share = lastday_share - triggered_share - manul_filled

                        out_share = self.ceil_to_thousand(available_share*self.trade_config['tp2_pct']/100)
                        if out_share > available_share:
                            self.logger.error(f"[place_order][{symbol}] 階段 2 觸發，剩餘庫存不足下單 {out_share}/{available_share}")
                            return

                        self.logger.info(f"[place_order][{symbol}] 階段 2 觸發，{price}/{base_price} 基準漲幅: {base_pct}%，觸發張數: {out_share}")
                        tp_res = self.sell_market_order(symbol, out_share, self.user_def+'2')
                        if tp_res.is_success:
                            self.logger.info(f"[place_order][{symbol}][{tp_res.data.order_no}] {out_share}股，委託成功")
                            self.is_tp2_ordered[symbol] = out_share
                            triggered_item.setText(f"{triggered_share+out_share}")
                        else:
                            self.logger.error(f"[{symbol}] {tp_res.message}")

                elif out_phase == '3':
                    if base_pct >= self.trade_config['tp3_rate'] and symbol not in self.is_tp3_ordered:
                        lastday_share = int(self.inv_table.item(row, self.col_idx_map['昨日股數']).text())
                        triggered_item = self.inv_table.item(row, self.col_idx_map['觸發股數'])
                        triggered_share = int(triggered_item.text())
                        manul_filled = int(self.inv_table.item(row, self.col_idx_map['手動成交']).text())
                        available_share = lastday_share - triggered_share - manul_filled

                        out_share = self.ceil_to_thousand(available_share*self.trade_config['tp3_pct']/100)
                        if out_share > available_share:
                            self.logger.error(f"[place_order][{symbol}] 階段 3 觸發，剩餘庫存不足下單 {out_share}/{available_share}")
                            return

                        self.logger.info(f"[place_order][{symbol}] 階段 3 觸發，{price}/{base_price} 基準漲幅: {base_pct}%，觸發張數: {out_share}")
                        tp_res = self.sell_market_order(symbol, out_share, self.user_def+'3')
                        if tp_res.is_success:
                            self.logger.info(f"[place_order][{symbol}][{tp_res.data.order_no}] {out_share}股，委託成功")
                            self.is_tp3_ordered[symbol] = out_share
                            triggered_item.setText(f"{triggered_share+out_share}")
                        else:
                            self.logger.error(f"[{symbol}] {tp_res.message}")

    def handle_message(self, message):
        data_recive_time = datetime.now()
        msg = json.loads(message)
        event = msg["event"]
        data = msg["data"]

        if event == 'subscribed':
            if type(data) == list:
                for subscribed_item in data:
                    sub_id = subscribed_item["id"]
                    symbol = subscribed_item["symbol"]
                    self.subscribed_ids[symbol] = sub_id
                    self.logger.info(f"[{symbol}] 已訂閱")
            else:
                id = data["id"]
                symbol = data["symbol"]
                self.subscribed_ids[symbol] = id
                self.logger.info(f"[{symbol}] 已訂閱")

        elif event == "unsubscribed":
            if type(data) == list:
                print(data)
                for unsub_item in data:
                    print(unsub_item)
                    unsub_symbol = unsub_item['symbol']
                    self.subscribed_ids.pop(unsub_symbol)
            else:
                self.subscribed_ids.pop(data['symbol'])
                self.logger.info(f"[{data['symbol']}] 取消訂閱")

        elif event == 'snapshot':
            data['event'] = 'snapshot'
            self.communicator.message_update_signal.emit(data)

        if event == "data":
            if 'isTrial' in data:
                if data['isTrial']:
                    return
                
            self.communicator.message_update_signal.emit(data)
            # quote_latency = data_recive_time - datetime.fromtimestamp(data['lastUpdated']/1000000.0)
            # self.logger.info(f"[Quote Latency(b4 queue)] {quote_latency.total_seconds()}")

    def handle_connect(self):
        self.logger.info('WS data connected')
    
    def handle_disconnect(self, code, message):
        if not self.manully_disconnect:
            self.logger.info(f'WS data disconnect: {code}, {message}')
            try:
                self.sdk.init_realtime(self.ws_mode)
                self.logger.info('重新建立行情連線')
            except Exception as e:
                # 如果有login error表示整個交易都斷掉了，嘗試先登入後重連
                if "login error" in str(e).lower():
                    # 拿重連lock，如果拿不到表示on_event正在重連
                    if self.relogin_lock.acquire(blocking=False):
                        relogin_res = self.try_relogin()
                        if relogin_res:
                            self.sdk.init_realtime(self.ws_mode)
                        else:
                            self.logger.error("WS can't connect, because relogin fail")
                            return
                    else:  
                        # 拿不到lock表示on_event正在嘗試重連，等待拿到lock再嘗試重連，最多等30秒
                        max_retry = 10
                        for i in range(max_retry):
                            if self.relogin_lock.acquire(blocking=False):
                                self.sdk.init_realtime(self.ws_mode)
                                self.reststock = sdk.marketdata.rest_client.stock
                                self.wsstock = sdk.marketdata.websocket_client.stock
                                break
                            else:
                                if i == (max_retry-1):
                                    self.logger.error("WS can't connect, because some thread relogin fail")
                                else:
                                    self.logger.error("WS wait 3 seconds to  connect, because some thread is relogining")
                                    time.sleep(3)
                else:
                    self.logger.error(f"Reconnect Wrong: {e}")

            self.wsstock.on("connect", self.handle_connect)
            self.wsstock.on("disconnect", self.handle_disconnect)
            self.wsstock.on("error", self.handle_error)
            self.wsstock.on("message", self.handle_message)
            self.wsstock.connect()
            self.wsstock.subscribe({
                'symbols': list(self.row_idx_map.keys()),
                'channel': 'trades'
            })
        else:
            self.logger.info(f'行情連接已停止')
            self.manully_disconnect = False
            
    
    def handle_error(self, error):
        self.logger.error(f'WS data error: {error}')

    def on_stop_clicked(self):
        self.manully_disconnect = True
        self.wsstock.disconnect()

        # 停止執行，開放所有輸入框
        self.multi_out_ui.lineEdit_default_MA_day.setReadOnly(False)
        self.multi_out_ui.lineEdit_default_tp1.setReadOnly(False)
        self.multi_out_ui.lineEdit_default_tp2.setReadOnly(False)
        self.multi_out_ui.lineEdit_default_tp3.setReadOnly(False)

        self.multi_out_ui.lineEdit_tp1_out_pct.setReadOnly(False)
        self.multi_out_ui.lineEdit_tp2_out_pct.setReadOnly(False)
        self.multi_out_ui.lineEdit_tp3_out_pct.setReadOnly(False)

        # 開放表格可修改部分
        for row in range(self.inv_table.rowCount()):
            base_price_item = self.inv_table.item(row, self.col_idx_map['基準價'])
            if base_price_item:
                base_price_item.setFlags(base_price_item.flags() | Qt.ItemFlag.ItemIsEditable)
            out_phase_item = self.inv_table.item(row, self.col_idx_map['出場階段'])
            if out_phase_item:
                out_phase_item.setFlags(out_phase_item.flags() | Qt.ItemFlag.ItemIsEditable)

        # 切換執行按鈕
        self.button_start.setVisible(True)
        self.button_stop.setVisible(False)

    def on_start_clicked(self):
        if self.inv_hist_fetch_thread.is_alive():
            self.logger.info("請等待均線計算歷史資料抓取完畢")
            return
        
        try:
            self.trade_config['ma_period'] = self.multi_out_ui.lineEdit_default_MA_day.text()
            self.trade_config['ma_period'] = int(self.trade_config['ma_period'])
            self.trade_config['ma_batch'] = self.multi_out_ui.lineEdit_MA_batch.text()
            self.trade_config['ma_batch'] = int(self.trade_config['ma_batch'])
            self.trade_config['ma_gap'] = self.multi_out_ui.lineEdit_MA_gap.text()
            self.trade_config['ma_gap'] = int(self.trade_config['ma_gap'])
        except ValueError:
            self.logger.info("請輸入正確均線參數，僅可為正整數")
            return
        
        try:
            self.trade_config['tp1_rate'] = self.multi_out_ui.lineEdit_default_tp1.text()
            self.trade_config['tp2_rate'] = self.multi_out_ui.lineEdit_default_tp2.text()
            self.trade_config['tp3_rate'] = self.multi_out_ui.lineEdit_default_tp3.text()

            self.trade_config['tp1_pct'] = self.multi_out_ui.lineEdit_tp1_out_pct.text()
            self.trade_config['tp2_pct'] = self.multi_out_ui.lineEdit_tp2_out_pct.text()
            self.trade_config['tp3_pct'] = self.multi_out_ui.lineEdit_tp3_out_pct.text()
            
            self.trade_config['tp1_rate'] = float(self.trade_config['tp1_rate'])
            self.trade_config['tp2_rate'] = float(self.trade_config['tp2_rate'])
            self.trade_config['tp3_rate'] = float(self.trade_config['tp3_rate'])

            self.trade_config['tp1_pct'] = float(self.trade_config['tp1_pct'])
            self.trade_config['tp2_pct'] = float(self.trade_config['tp2_pct'])
            self.trade_config['tp3_pct'] = float(self.trade_config['tp3_pct'])

            self.logger.info(f"已設定，階段 1 停利 {self.trade_config['tp1_rate']}%, 出場 {self.trade_config['tp1_pct']}%")
            self.logger.info(f"已設定，階段 2 停利 {self.trade_config['tp2_rate']}%, 出場 {self.trade_config['tp2_pct']}%")
            self.logger.info(f"已設定，階段 3 停利 {self.trade_config['tp3_rate']}%, 出場 {self.trade_config['tp3_pct']}%")
        except ValueError:
            self.logger.info("請輸入正確停利百分比和出場百分比，不可空白，僅可為正數")
            return
        
        # 成功開始，鎖定所有輸入框
        self.multi_out_ui.lineEdit_default_MA_day.setReadOnly(True)

        self.multi_out_ui.lineEdit_default_tp1.setReadOnly(True)
        self.multi_out_ui.lineEdit_default_tp2.setReadOnly(True)
        self.multi_out_ui.lineEdit_default_tp3.setReadOnly(True)

        self.multi_out_ui.lineEdit_tp1_out_pct.setReadOnly(True)
        self.multi_out_ui.lineEdit_tp2_out_pct.setReadOnly(True)
        self.multi_out_ui.lineEdit_tp3_out_pct.setReadOnly(True)

        # 鎖定表格可修改部分
        for row in range(self.inv_table.rowCount()):
            base_price_item = self.inv_table.item(row, self.col_idx_map['基準價'])
            if base_price_item:
                base_price_item.setFlags(base_price_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            out_phase_item = self.inv_table.item(row, self.col_idx_map['出場階段'])
            if out_phase_item:
                out_phase_item.setFlags(out_phase_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        
        # 計算均線並更新表格
        for symbol in self.row_idx_map.keys():
            ma_item = self.inv_table.item(self.row_idx_map[symbol], self.col_idx_map['均線之下'])
            cur_symbol_sma = self.SMA_cal(symbol, self.trade_config['ma_period'])
            cur_symbol_yesterday_close = self.hist_dfs[symbol]['close'].iloc[0]
            if cur_symbol_sma > cur_symbol_yesterday_close:
                ma_item.setText("Yes")
            else:
                ma_item.setText("No")

        # 切換執行按鈕
        self.button_start.setVisible(False)
        self.button_stop.setVisible(True)

        self.wsstock.on("connect", self.handle_connect)
        self.wsstock.on("disconnect", self.handle_disconnect)
        self.wsstock.on("error", self.handle_error)
        self.wsstock.on("message", self.handle_message)
        self.wsstock.connect()
        self.wsstock.subscribe({
            'symbols': list(self.row_idx_map.keys()),
            'channel': 'trades'
        })

    def on_item_changed(self, item):
        row = item.row()
        col = item.column()
        if self.table_header[col] == "出場階段":  # 檢查是否在目標列中
            symbol = self.inv_table.item(row, self.col_idx_map["股票代號"]).text()
            original_value = self.inv_rec[symbol]["out_phase"]
            try:
                value = int(item.text())  # 嘗試將文字轉換為整數
                if value == original_value:
                    pass
                elif 1 <= value <= 3:  # 檢查數字是否在 1 到 3 的範圍內
                    self.inv_rec[symbol]["out_phase"] = value
                    self.logger.info(f"[{symbol}] 出場階段更新， Phase: {item.text()}")
                else:
                    self.logger.info("出場階段範圍1~3，請重新輸入")
                    # 恢復原先值
                    if original_value is not None:
                      item.setText(str(original_value))
                    else:
                      item.setText("1")
            except ValueError:
                self.logger.error(f"輸入不是數字，請輸入數字，範圍1~3。")
                # 恢復原先值
                if original_value is not None:
                  item.setText(str(original_value))
                else:
                  item.setText("1")
        elif self.table_header[col] == "基準價":
            symbol = self.inv_table.item(row, self.col_idx_map["股票代號"]).text()
            original_value = self.inv_table.item(row, self.col_idx_map["庫存均價"]).text()
            try:
                item_str = item.text()
                if item_str == '-':
                    return
                else:
                    value = float(item_str)  # 嘗試將文字轉換為浮點數

                if value <= 0:
                    self.logger.info("基準價範圍需大於0")
                    item.setText(original_value)
                else:
                    self.logger.info(f"[{symbol}] 已修改基準價為 {value}")
            except ValueError as v:
                self.logger.error(f"{v} 輸入不是數字，請輸入數字，範圍需大於0")
                self.logger.debug(f"base price traceback: {traceback.format_exc()}")
                item.setText(original_value)

    def table_init(self, inv_data, pnl_data):
        # 清除表格資料
        self.inv_table.clearContents()
        self.inv_table.setRowCount(0)

        for key, value in inv_data.items():
            if key in pnl_data:
                self.logger.debug(f"[Init] 代號: {key}, 名稱: {self.stock_name_map[key]}, 昨日: {value.lastday_qty}, 均價: {pnl_data[key].cost_price}")
            else:
                self.logger.debug(f"[Init] 代號: {key}, 名稱: {self.stock_name_map[key]}, 昨日: {value.lastday_qty}")
            
            if key not in self.inv_rec:
                self.logger.debug(f"[Init] Add {key} in inv_rec")
                self.inv_rec[key] = {
                    "out_phase": 1
                }
            
            stock_symbol = key
            stock_name = self.stock_name_map[key]
            row = self.inv_table.rowCount()
            self.inv_table.insertRow(row)
            self.row_idx_map[stock_symbol] = row

            # ['股票名稱', '股票代號', '昨日股數', '庫存均價', '基準價', '現價', '基準漲幅(%)', '出場階段', '觸發股數', '程式成交']
            for j in range(len(self.table_header)):
                item = QTableWidgetItem()
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if self.table_header[j] == '均線之下':
                    item.setText('-')
                    item.setTextAlignment(Qt.AlignCenter)
                    self.inv_table.setItem(row, j, item)
                elif self.table_header[j] == '股票名稱':
                    item.setText(stock_name)
                    self.inv_table.setItem(row, j, item)
                elif self.table_header[j] == '股票代號':
                    item.setText(stock_symbol)
                    self.inv_table.setItem(row, j, item)
                elif self.table_header[j] == '昨日股數':
                    item.setText(str(value.lastday_qty))
                    self.inv_table.setItem(row, j, item)
                elif self.table_header[j] == '庫存均價':
                    if key in pnl_data:
                        item.setText(str(round(pnl_data[key].cost_price, 2)))
                    else:
                        item.setText('-')
                    self.inv_table.setItem(row, j, item)
                elif self.table_header[j] == '基準價':
                    item.setFlags(Qt.ItemIsEditable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    if key in pnl_data:
                        item.setText(str(round(pnl_data[key].cost_price, 2)))
                    else:
                        item.setText('-')
                    self.inv_table.setItem(row, j, item)
                elif self.table_header[j] == '現價':
                    item.setText('-')
                    self.inv_table.setItem(row, j, item)
                elif self.table_header[j] == '基準漲幅(%)':
                    item.setText('-')
                    self.inv_table.setItem(row, j, item)
                elif self.table_header[j] == '出場階段':
                    item.setFlags(Qt.ItemIsEditable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    if key in self.inv_rec:
                        item.setText(str(self.inv_rec[key]['out_phase']))
                    else:
                        item.setText('0')
                    self.inv_table.setItem(row, j, item)
                elif self.table_header[j] == '觸發股數':
                    item.setText('0')
                    self.inv_table.setItem(row, j, item)
                elif self.table_header[j] == '程式成交':
                    item.setText('0')
                    self.inv_table.setItem(row, j, item)
                elif self.table_header[j] == '手動成交':
                    item.setText('0')
                    self.inv_table.setItem(row, j, item)

    def init_data_fetch(self):
        # 抓庫存股票
        inv_res = self.sdk.accounting.inventories(self.active_account)
        inventories = {}
        pnls = {}

        if inv_res.is_success:
            for inv in inv_res.data:
                if inv.order_type == OrderType.Stock:
                    inventories[inv.stock_no] = inv
            self.logger.info(f"庫存股票已抓取，共{len(inventories)}檔")
        else:
            self.logger.error(f"Inventory fetch error, message: {inv_res.message}")
        
        # 抓庫存均價
        pnl_res = sdk.accounting.unrealized_gains_and_loses(self.active_account)
        if pnl_res.is_success:
            for pnl in pnl_res.data:
                pnls[pnl.stock_no] = pnl
            self.logger.info(f"庫存成本已抓取，共{len(pnls)}檔")
        else:
            self.logger.error(f"Inv_Cost fetch error, message: {pnl_res.message}")
        
        # 抓取基準表(階段)
        for key in list(self.inv_rec.keys()):
            if key not in inventories:
                value = self.inv_rec.pop(key)
                self.logger.debug(f"[Init] {key} {value} not in current inventory")

        self.logger.info(f"start inv hist fetch thread")
        self.inv_hist_fetch_thread = threading.Thread(target=self.inv_hist_fetch, args=(inventories, ))
        self.inv_hist_fetch_thread.start()

        self.communicator.table_init_signal.emit(inventories, pnls)
    
    def SMA_cal(self, symbol, ma_period):
        sma = self.hist_dfs[symbol].iloc[:ma_period]['close'].mean()
        sma = round(sma, 2)
        self.logger.info(f"symbol: {symbol}, SMA{ma_period}: {sma}")
        return sma
    
    def inv_hist_fetch(self, inventories):
        yesterday = self.today-timedelta(days=1)
        last_year = self.today-relativedelta(years=1)

        yesterday_date_str = datetime.strftime(yesterday, "%Y-%m-%d")
        last_year_date_str = datetime.strftime(last_year, "%Y-%m-%d")

        for cur_inv in inventories.keys():
            cur_symbol_hist = self.hist_fetch(cur_inv, last_year_date_str, yesterday_date_str)
            self.hist_dfs[cur_inv] = cur_symbol_hist
        self.logger.info("均線計算歷史資料以抓取完成")

    def hist_fetch(self, symbol, start_date, end_date):
        self.logger.info(f"fetching {symbol} historical data...")
        hist_res = self.reststock.historical.candles(**{"symbol": symbol, "from": start_date, "to": end_date})
        hist_df = pd.DataFrame(hist_res["data"])
        self.logger.info(f"{symbol} fetch done, {hist_df.shape[0]} records...")
        return hist_df

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

    # 更新最新log到QPlainTextEdit的slot function
    def print_log(self, log_info):
        self.multi_out_ui.log_text.appendPlainText(log_info)
        self.multi_out_ui.log_text.moveCursor(QTextCursor.End)

    def try_relogin(self):
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
                self.relogin_lock.release()
                return True
        self.logger.error(f"Relogin max retry {max_retry} exceed")
        self.relogin_lock.release()
        return False

    # 視窗關閉時要做的事，主要是關websocket連結
    def closeEvent(self, event):
        # do stuff
        self.print_log("disconnect websocket...")
        self.manully_disconnect = True
        self.wsstock.disconnect()
        self.sdk.logout()

        # try:
        #     if self.fake_ws_timer.is_alive():
        #         self.fake_ws_timer.cancel()
        # except AttributeError:
        #     print("no fake ws timer exist")

        can_exit = True
        if can_exit:
            event.accept() # let the window close
        else:
            event.ignore()
        os._exit(0)

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