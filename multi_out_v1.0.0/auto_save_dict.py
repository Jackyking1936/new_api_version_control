#%%
import json
import threading
import os

class ObservableDict(dict):
    """可觀察的字典，用於通知 AutoSaveDict 儲存變更。"""

    def __init__(self, parent_dict, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent_dict = parent_dict

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.parent_dict.save_with_thread()

    def __delitem__(self, key):
        super().__delitem__(key)
        self.parent_dict.save_with_thread()

    def clear(self):
        super().clear()
        self.parent_dict.save_with_thread()

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self.parent_dict.save_with_thread()

class AutoSaveDict(dict):
    """使用線程自動儲存成 JSON 的字典，並使用鎖確保線程安全。"""

    def __init__(self, filename, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.filename = filename
        self.lock = threading.Lock()  # 建立鎖
        self.load()

    def save_thread(self):
        """在單獨的線程中儲存 JSON，並使用鎖。"""
        with self.lock:  # 取得鎖
            try:
                with open(self.filename, 'w', encoding='utf-8') as f:
                    json.dump(self, f, ensure_ascii=False, indent=4)
            except Exception as e:
                print(f"儲存字典時發生錯誤：{e}")

    def save_with_thread(self):
        """立即儲存，使用線程和鎖。"""
        thread = threading.Thread(target=self.save_thread)
        thread.start()

    def __setitem__(self, key, value):
        if isinstance(value, dict):
            value = ObservableDict(self, value)
        super().__setitem__(key, value)
        self.save_with_thread()

    def __delitem__(self, key):
        super().__delitem__(key)
        self.save_with_thread()

    def clear(self):
        super().clear()
        self.save_with_thread()

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self.save_with_thread()

    def load(self):
        """從 JSON 檔案載入字典，並使用鎖。如果檔案不存在，則創建一個空的 JSON 檔案。"""
        with self.lock:  # 取得鎖
            try:
                if os.path.exists(self.filename): #檢查檔案是否存在
                    with open(self.filename, 'r', encoding='utf-8') as f:
                        loaded_data = json.load(f)
                        self.update(self.convert_to_observable_dict(loaded_data)) # 將載入的資料轉換為 ObservableDict
                else:
                    #檔案不存在，創建一個空的json檔案
                    with open(self.filename, 'w', encoding='utf-8') as f:
                        json.dump({}, f, ensure_ascii=False, indent=4)
            except Exception as e:
                print(f"載入字典時發生錯誤：{e}")

    def convert_to_observable_dict(self, data):
      """將原始 dict 物件轉換為 ObservableDict 物件。"""
      if isinstance(data, dict):
        return ObservableDict(self, {k: self.convert_to_observable_dict(v) for k, v in data.items()})
      return data

# 範例用法
if __name__ == "__main__":
    my_dict = AutoSaveDict("my_data.json")
    my_dict['key1'] = {'nested_key': 1}
    my_dict['key1']['nested_key'] = 2 #測試巢狀字典的改動
    print(my_dict)

# %%
