import base64
import requests
from pathlib import Path
from core.config import Config
from core.logger import logger

class ImageService:
    """
    Robust Service to upload local image files.
    Supports primary ImgBB, secondary FreeImage.host fallback,
    and inline Data URL fallback so publishing NEVER fails.
    """

    FREEIMAGE_HOST_KEY = "6d207e02198a847aa98d0a2a901485a5"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or Config.IMGBB_API_KEY
        self.imgbb_url = "https://api.imgbb.com/1/upload"
        self.freeimage_url = "https://freeimage.host/api/1/upload"

    def upload_image(self, file_path: str) -> str:
        """
        Uploads a local image file with multi-provider fallback:
        1. ImgBB (Multipart)
        2. ImgBB (Base64)
        3. FreeImage.host
        4. Base64 Data URL (guarantees publishing never crashes)
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"لم يتم العثور على ملف الصورة: {file_path}")

        logger.info(f"جاري رفع الصورة: {path.name}")

        # ------------------------------------------------------------------
        # Provider 1: ImgBB (Binary Multipart)
        # ------------------------------------------------------------------
        if self.api_key:
            try:
                with open(path, "rb") as file_obj:
                    files = {"image": file_obj}
                    data = {"key": self.api_key, "name": path.stem}
                    response = requests.post(self.imgbb_url, data=data, files=files, timeout=15)

                if response.status_code == 200:
                    res_json = response.json()
                    if res_json.get("success"):
                        direct_url = res_json["data"]["url"]
                        logger.info(f"تم رفع الصورة بنجاح على ImgBB: {direct_url}")
                        return direct_url
                    else:
                        err_msg = res_json.get("error", {}).get("message", response.text)
                        logger.warning(f"ملاحظة ImgBB: {err_msg}")
                else:
                    err_msg = response.text
                    try:
                        err_json = response.json()
                        if "error" in err_json:
                            err_msg = err_json["error"].get("message", response.text)
                    except Exception:
                        pass
                    logger.warning(f"تعذر الرفع على ImgBB (الكود {response.status_code}: {err_msg})")

            except Exception as e:
                logger.warning(f"فشل الاتصال بـ ImgBB: {e}")

            # --------------------------------------------------------------
            # Provider 1 Fallback: ImgBB (Base64)
            # --------------------------------------------------------------
            try:
                with open(path, "rb") as file_obj:
                    b64_str = base64.b64encode(file_obj.read()).decode("utf-8")

                payload = {"key": self.api_key, "image": b64_str, "name": path.stem}
                response2 = requests.post(self.imgbb_url, data=payload, timeout=15)

                if response2.status_code == 200:
                    res_json2 = response2.json()
                    if res_json2.get("success"):
                        direct_url = res_json2["data"]["url"]
                        logger.info(f"تم رفع الصورة بنجاح كـ Base64 على ImgBB: {direct_url}")
                        return direct_url
            except Exception as e:
                logger.warning(f"فشل المحاولة الثانية لـ ImgBB: {e}")

        # ------------------------------------------------------------------
        # Provider 2: FreeImage.host
        # ------------------------------------------------------------------
        logger.info("محاولة الرفع على السيرفر البديل (FreeImage.host)...")
        try:
            with open(path, "rb") as file_obj:
                files = {"source": file_obj}
                data = {
                    "key": self.FREEIMAGE_HOST_KEY,
                    "action": "upload",
                    "format": "json"
                }
                res_free = requests.post(self.freeimage_url, data=data, files=files, timeout=20)

            if res_free.status_code == 200:
                res_json = res_free.json()
                if res_json.get("status_code") == 200 and "image" in res_json:
                    direct_url = res_json["image"]["url"]
                    logger.info(f"تم رفع الصورة بنجاح عبر السيرفر البديل FreeImage.host: {direct_url}")
                    return direct_url
        except Exception as e:
            logger.warning(f"فشل الرفع على FreeImage.host: {e}")

        # ------------------------------------------------------------------
        # Provider 3: Inline Data URL Fallback
        # (Guarantees article direct publish will never fail)
        # ------------------------------------------------------------------
        logger.warning("تنشيط الخيار الاحتياطي النهائي: تحويل الصورة لـ Data URL سريعة لضمان إتمام النشر بدون أي تعطل...")
        try:
            ext = path.suffix.lstrip(".").lower()
            if ext == "jpg":
                ext = "jpeg"
            elif not ext:
                ext = "png"

            with open(path, "rb") as file_obj:
                b64_encoded = base64.b64encode(file_obj.read()).decode("utf-8")

            data_url = f"data:image/{ext};base64,{b64_encoded}"
            logger.info("تم إنشاء Data URL للصورة بنجاح وسيتم إدراجها مباشرة في المقال.")
            return data_url
        except Exception as e:
            logger.error(f"فشل إنشاء Data URL: {e}")
            raise e


image_service = ImageService()
