# import json, os, threading
# from typing import Dict, Any
#
# class JSONStorage:
#     def __init__(self, filename="storage.json"):
#         self.filename = filename
#         self._lock = threading.Lock()
#         self.data = {"last_sent": {}}  # structure: { "chat_id": { "PAIR": ts } }
#         if os.path.exists(self.filename):
#             try:
#                 with open(self.filename, "r", encoding="utf-8") as f:
#                     self.data = json.load(f)
#             except Exception:
#                 pass
#
#     def save(self):
#         with self._lock:
#             with open(self.filename, "w", encoding="utf-8") as f:
#                 json.dump(self.data, f, indent=2, ensure_ascii=False)
#
#     def get_last_sent(self, chat_id: str, pair: str):
#         return self.data.get("last_sent", {}).get(str(chat_id), {}).get(pair)
#
#     def set_last_sent(self, chat_id: str, pair: str, ts: int):
#         with self._lock:
#             self.data.setdefault("last_sent", {}).setdefault(str(chat_id), {})[pair] = ts
#             self.save()
# storage.py
import json, os, tempfile
from threading import Lock

class JSONStorage:
    def __init__(self, path="storage.json"):
        self.path = path
        self.lock = Lock()
        # ensure file exists and contains a JSON object
        if not os.path.exists(self.path) or os.path.getsize(self.path) == 0:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({}, f)

    def _read_all(self):
        with open(self.path, "r", encoding="utf-8") as f:
            try:
                return json.load(f) or {}
            except Exception:
                # if file corrupted or empty, return empty dict
                return {}

    def _write_all(self, data):
        # atomic write: write to temp file then replace
        dirn = os.path.dirname(self.path) or "."
        fd, tmp = tempfile.mkstemp(dir=dirn)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass

    def get_last_sent(self, chat_id, pair):
        with self.lock:
            data = self._read_all()
            return data.get(str(chat_id), {}).get(str(pair))

    def set_last_sent(self, chat_id, pair, ts):
        with self.lock:
            print(f'SET_SENT')
            data = self._read_all()
            chat_key = str(chat_id)
            p_key = str(pair)
            if chat_key not in data:
                data[chat_key] = {}
            data[chat_key][p_key] = int(ts)
            self._write_all(data)

    def get_last_sent_pivot(self, chat_id, pair, level, timeframe):
        with self.lock:
            data = self._read_all()
            chat_key = str(chat_id)
            if chat_key not in data:
                return None

            pivot_data = data[chat_key].get("pivot", {})
            # ключ формата "BTC/USDT:R1:5m"
            pivot_key = f"{pair}:{level}:{timeframe}"
            return pivot_data.get(pivot_key)

    def set_last_sent_pivot(self, chat_id, pair, level, timeframe, ts):
        with self.lock:
            data = self._read_all()
            chat_key = str(chat_id)
            if chat_key not in data:
                data[chat_key] = {"simple": {}, "pivot": {}}
            if "pivot" not in data[chat_key]:
                data[chat_key]["pivot"] = {}

            pivot_key = f"{pair}:{level}:{timeframe}"
            data[chat_key]["pivot"][pivot_key] = int(ts)
            self._write_all(data)
