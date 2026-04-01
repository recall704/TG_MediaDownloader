class ConfigFile:
    TG_SESSION: str
    TG_API_ID: int
    TG_API_HASH: str
    TG_BOT_TOKEN: str
    TG_DOWNLOAD_PATH: str
    TG_MAX_PARALLEL: int
    TG_DL_TIMEOUT: int
    TG_AUTHORIZED_USER_ID: list[int]
    FORWARD_TYPE: dict
    DOWNLOAD_UPLOAD: bool
    UPLOAD_DELETE: bool

    def __init__(self, data=None):
        if data is None:
            return
        self.TG_SESSION = data["TG_SESSION"]
        self.TG_API_ID = data["TG_API_ID"]
        self.TG_API_HASH = data["TG_API_HASH"]
        self.TG_BOT_TOKEN = data["TG_BOT_TOKEN"]
        self.TG_DOWNLOAD_PATH = data["TG_DOWNLOAD_PATH"]
        self.TG_MAX_PARALLEL = data.get("TG_MAX_PARALLEL", 4)
        self.TG_DL_TIMEOUT = data.get("TG_DL_TIMEOUT", 5400)
        self.TG_AUTHORIZED_USER_ID = data["TG_AUTHORIZED_USER_ID"]
        self.FORWARD_TYPE = data.get(
            "FORWARD_TYPE",
            {
                "video": True,
                "photo": True,
                "audio": True,
                "voice": True,
                "animation": True,
                "document": True,
                "text": True,
                "video_note": True,
            },
        )
        self.DOWNLOAD_UPLOAD = data.get("DOWNLOAD_UPLOAD", True)
        self.UPLOAD_DELETE = data.get("UPLOAD_DELETE", False)
