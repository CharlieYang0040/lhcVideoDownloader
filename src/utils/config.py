import json
import os
import appdirs

class ConfigManager:
    def __init__(self):
        self.app_name = "LHCVideoDownloader"
        self.app_author = "LHCinema"
        self.config_dir = appdirs.user_data_dir(self.app_name, self.app_author)
        self.config_file = os.path.join(self.config_dir, "config.json")
        
        self.defaults = {
            "last_download_path": os.path.join(os.getcwd(), "downloads"),
            "last_auth_method": "None", # "APP Login (Rec)", "Firefox", "File", "None"
            "cookie_file_path": "",
            "url_history": [],
            "post_process": "None",
            "format_index": 0
        }
        
        self.config = self.load_config()

    def load_config(self):
        if not os.path.exists(self.config_file):
            return self.defaults.copy()
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                # Merge with defaults to ensure all keys exist
                config = self.defaults.copy()
                config.update(saved)
                return config
        except Exception as e:
            print(f"Failed to load config: {e}")
            return self.defaults.copy()

    def save_config(self):
        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir)
            
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Failed to save config: {e}")

    def get(self, key):
        return self.config.get(key, self.defaults.get(key))

    def set(self, key, value):
        self.config[key] = value

    def add_history(self, url):
        history = self.config.get("url_history", [])
        if url in history:
            history.remove(url)
        history.insert(0, url)
        # Limit to 20
        self.config["url_history"] = history[:20]
