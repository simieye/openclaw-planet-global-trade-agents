"""
API Client SDK
统一封装所有外部系统 API 调用：Shopify、Amazon、TikTok、WhatsApp、HeyGen、Stripe 等
"""

import asyncio
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger("openclaw.apis")


# ============================================================
# Base Client
# ============================================================

@dataclass
class APIClientConfig:
    base_url: str
    api_key: str = ""
    api_secret: str = ""
    timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 1.0
    headers: dict = field(default_factory=dict)


class BaseAPIClient:
    """API 客户端基类"""

    def __init__(self, config: APIClientConfig):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.timeout,
                headers=self._build_headers(),
            )
        return self._client

    def _build_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        headers.update(self.config.headers)
        return headers

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        """带重试的请求"""
        client = await self._get_client()
        last_error = None

        for attempt in range(self.config.max_retries):
            try:
                response = await client.request(method, path, **kwargs)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                last_error = e
                logger.warning(f"API error [{attempt + 1}/{self.config.max_retries}]: {e}")
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(self.config.retry_delay * (2 ** attempt))
            except Exception as e:
                last_error = e
                logger.error(f"API request failed: {e}")
                break

        raise last_error or Exception("API request failed")

    async def get(self, path: str, **kwargs) -> dict:
        return await self._request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs) -> dict:
        return await self._request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs) -> dict:
        return await self._request("PUT", path, **kwargs)

    async def delete(self, path: str, **kwargs) -> dict:
        return await self._request("DELETE", path, **kwargs)

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


# ============================================================
# Shopify Client
# ============================================================

class ShopifyClient(BaseAPIClient):
    """Shopify Admin API 客户端"""

    def __init__(self, store_url: str, api_key: str, api_secret: str = ""):
        super().__init__(APIClientConfig(
            base_url=f"https://{store_url}/admin/api/2024-01",
            api_key=api_key,
            api_secret=api_secret,
            headers={"X-Shopify-Access-Token": api_key},
        ))

    async def get_orders(self, status: str = "any", limit: int = 50) -> dict:
        return await self.get(f"/orders.json?status={status}&limit={limit}")

    async def get_order(self, order_id: int) -> dict:
        return await self.get(f"/orders/{order_id}.json")

    async def get_products(self, limit: int = 50) -> dict:
        return await self.get(f"/products.json?limit={limit}")

    async def get_product(self, product_id: int) -> dict:
        return await self.get(f"/products/{product_id}.json")

    async def update_product(self, product_id: int, data: dict) -> dict:
        return await self.put(f"/products/{product_id}.json", json={"product": data})

    async def get_customers(self, limit: int = 50) -> dict:
        return await self.get(f"/customers.json?limit={limit}")

    async def get_inventory_levels(self, inventory_item_ids: list[int]) -> dict:
        ids = ",".join(map(str, inventory_item_ids))
        return await self.get(f"/inventory_levels.json?inventory_item_ids={ids}")

    async def create_webhook(self, topic: str, address: str) -> dict:
        return await self.post("/webhooks.json", json={
            "webhook": {"topic": topic, "address": address, "format": "json"}
        })


# ============================================================
# Amazon SP-API Client
# ============================================================

class AmazonClient(BaseAPIClient):
    """Amazon Selling Partner API 客户端"""

    def __init__(self, seller_id: str, api_key: str, api_secret: str = ""):
        super().__init__(APIClientConfig(
            base_url="https://sellingpartnerapi-na.amazon.com",
            api_key=api_key,
            api_secret=api_secret,
        ))
        self.seller_id = seller_id

    async def get_orders(self, created_after: str = None) -> dict:
        params = {"MarketplaceIds": "ATVPDKIKX0DER"}
        if created_after:
            params["CreatedAfter"] = created_after
        return await self.get("/orders/v0/orders", params=params)

    async def get_order_items(self, order_id: str) -> dict:
        return await self.get(f"/orders/v0/orders/{order_id}/orderItems")

    async def get_inventory_summary(self) -> dict:
        return await self.get("/fba/inventory/v1/summaries", params={
            "granularityType": "Marketplace",
            "granularityId": "ATVPDKIKX0DER",
            "marketplaceIds": "ATVPDKIKX0DER",
        })

    async def get_listings(self) -> dict:
        return await self.get(f"/listings/2021-08-01/items/{self.seller_id}")

    async def get_catalog_item(self, asin: str) -> dict:
        return await self.get(f"/catalog/2022-04-01/items/{asin}")


# ============================================================
# TikTok Shop Client
# ============================================================

class TikTokShopClient(BaseAPIClient):
    """TikTok Shop API 客户端"""

    def __init__(self, api_key: str, api_secret: str = ""):
        super().__init__(APIClientConfig(
            base_url="https://open-api.tiktokglobalshop.com",
            api_key=api_key,
            api_secret=api_secret,
        ))

    def _sign(self, path: str, params: dict) -> str:
        """生成签名"""
        if not self.config.api_secret:
            return ""
        param_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        sign_str = f"{path}?{param_str}{self.config.api_secret}"
        return hashlib.sha256(sign_str.encode()).hexdigest()

    async def get_orders(self, page_size: int = 20) -> dict:
        params = {"page_size": page_size, "timestamp": int(time.time())}
        params["sign"] = self._sign("/order/list", params)
        return await self.get("/order/list", params=params)

    async def get_order_detail(self, order_id: str) -> dict:
        params = {"order_id": order_id, "timestamp": int(time.time())}
        params["sign"] = self._sign("/order/detail", params)
        return await self.get("/order/detail", params=params)

    async def get_products(self) -> dict:
        params = {"timestamp": int(time.time())}
        params["sign"] = self._sign("/product/list", params)
        return await self.get("/product/list", params=params)

    async def get_shop_performance(self) -> dict:
        params = {"timestamp": int(time.time())}
        params["sign"] = self._sign("/shop/performance", params)
        return await self.get("/shop/performance", params=params)

    async def send_message(self, conversation_id: str, message: str) -> dict:
        return await self.post("/message/send", json={
            "conversation_id": conversation_id,
            "message": {"content": message, "type": "text"},
        })


# ============================================================
# WhatsApp Business API Client
# ============================================================

class WhatsAppClient(BaseAPIClient):
    """WhatsApp Business API 客户端 (Meta Cloud API)"""

    def __init__(self, phone_number_id: str, api_key: str):
        super().__init__(APIClientConfig(
            base_url=f"https://graph.facebook.com/v18.0/{phone_number_id}",
            api_key=api_key,
        ))

    async def send_message(self, to: str, body: str, preview_url: bool = False) -> dict:
        return await self.post("/messages", json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body, "preview_url": preview_url},
        })

    async def send_template(self, to: str, template_name: str, language: str = "en", components: list = None) -> dict:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {"name": template_name, "language": {"code": language}},
        }
        if components:
            payload["template"]["components"] = components
        return await self.post("/messages", json=payload)

    async def send_image(self, to: str, image_url: str, caption: str = "") -> dict:
        return await self.post("/messages", json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": {"link": image_url, "caption": caption},
        })

    async def send_document(self, to: str, document_url: str, filename: str, caption: str = "") -> dict:
        return await self.post("/messages", json={
            "messaging_product": "whatsapp",
            "to": to,
            "type": "document",
            "document": {"link": document_url, "filename": filename, "caption": caption},
        })

    async def mark_as_read(self, message_id: str) -> dict:
        return await self.post("/messages", json={
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        })


# ============================================================
# HeyGen Client
# ============================================================

class HeyGenClient(BaseAPIClient):
    """HeyGen 数字人视频 API 客户端"""

    def __init__(self, api_key: str):
        super().__init__(APIClientConfig(
            base_url="https://api.heygen.com",
            api_key=api_key,
            timeout=300,
        ))

    async def create_avatar_video(
        self,
        avatar_id: str,
        voice_id: str,
        script: str,
        background: str = "#ffffff",
        dimension: str = "1920x1080",
    ) -> dict:
        """创建数字人视频"""
        return await self.post("/v2/video/generate", json={
            "video_inputs": [{
                "character": {
                    "type": "avatar",
                    "avatar_id": avatar_id,
                    "avatar_style": "normal",
                },
                "voice": {
                    "type": "text",
                    "voice_id": voice_id,
                    "input_text": script,
                },
                "background": {
                    "type": "color",
                    "value": background,
                },
            }],
            "dimension": {"width": 1920, "height": 1080},
        })

    async def get_video_status(self, video_id: str) -> dict:
        return await self.get(f"/v2/video/generate/status?video_id={video_id}")

    async def list_avatars(self) -> dict:
        return await self.get("/v2/avatars")

    async def list_voices(self) -> dict:
        return await self.get("/v2/voices")

    async def create_talking_photo(
        self,
        photo_url: str,
        script: str,
        voice_id: str = "",
    ) -> dict:
        """创建照片说话视频"""
        return await self.post("/v2/talking_photo/generate", json={
            "talking_photo_input": {
                "type": "photo",
                "photo_url": photo_url,
            },
            "voice": {
                "type": "text",
                "voice_id": voice_id,
                "input_text": script,
            },
        })


# ============================================================
# Stripe Client
# ============================================================

class StripeClient(BaseAPIClient):
    """Stripe 支付 API 客户端"""

    def __init__(self, api_key: str):
        super().__init__(APIClientConfig(
            base_url="https://api.stripe.com/v1",
            api_key=api_key,
        ))

    async def create_payment_link(
        self,
        amount: int,
        currency: str = "usd",
        description: str = "",
        metadata: dict = None,
    ) -> dict:
        data = {
            "line_items[0][price_data][currency]": currency,
            "line_items[0][price_data][product_data][name]": description,
            "line_items[0][price_data][unit_amount]": amount,
            "line_items[0][quantity]": 1,
        }
        if metadata:
            for k, v in metadata.items():
                data[f"metadata[{k}]"] = v
        return await self.post("/payment_links", data=data)

    async def create_invoice(self, customer_id: str, items: list[dict]) -> dict:
        return await self.post("/invoices", json={
            "customer": customer_id,
            "collection_method": "send_invoice",
            "days_until_due": 30,
        })

    async def get_payment_intent(self, payment_intent_id: str) -> dict:
        return await self.get(f"/payment_intents/{payment_intent_id}")

    async def create_refund(self, payment_intent_id: str, amount: int = None) -> dict:
        data = {"payment_intent": payment_intent_id}
        if amount:
            data["amount"] = amount
        return await self.post("/refunds", data=data)


# ============================================================
# Email Client
# ============================================================

class EmailClient:
    """邮件客户端（支持 SendGrid / SMTP）"""

    def __init__(self, provider: str = "sendgrid", api_key: str = "", smtp_config: dict = None):
        self.provider = provider
        self.api_key = api_key
        self.smtp_config = smtp_config or {}

    async def send(self, to: str, subject: str, body: str, html_body: str = "", from_addr: str = "") -> dict:
        """发送邮件"""
        if self.provider == "sendgrid":
            return await self._send_via_sendgrid(to, subject, body, html_body, from_addr)
        elif self.provider == "smtp":
            return await self._send_via_smtp(to, subject, body, html_body, from_addr)
        else:
            logger.warning(f"Email provider not configured: {self.provider}")
            return {"sent": False, "error": f"Provider not configured: {self.provider}"}

    async def _send_via_sendgrid(self, to: str, subject: str, body: str, html_body: str, from_addr: str) -> dict:
        try:
            import sendgrid
            from sendgrid.helpers.mail import Mail, Email, Content

            sg = sendgrid.SendGridAPIClient(api_key=self.api_key)
            message = Mail(
                from_email=Email(from_addr or "noreply@example.com"),
                to_emails=to,
                subject=subject,
                plain_text_content=Content("text/plain", body),
            )
            if html_body:
                message.add_content(Content("text/html", html_body))

            response = sg.send(message)
            return {"sent": True, "status_code": response.status_code}
        except ImportError:
            logger.warning("sendgrid not installed, falling back to mock")
            return {"sent": True, "mock": True}
        except Exception as e:
            logger.error(f"SendGrid error: {e}")
            return {"sent": False, "error": str(e)}

    async def _send_via_smtp(self, to: str, subject: str, body: str, html_body: str, from_addr: str) -> dict:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = from_addr or self.smtp_config.get("username", "")
            msg["To"] = to
            msg.attach(MIMEText(body, "plain"))
            if html_body:
                msg.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP(self.smtp_config.get("host", "localhost"), self.smtp_config.get("port", 587)) as server:
                server.starttls()
                server.login(self.smtp_config["username"], self.smtp_config["password"])
                server.send_message(msg)

            return {"sent": True}
        except Exception as e:
            logger.error(f"SMTP error: {e}")
            return {"sent": False, "error": str(e)}


# ============================================================
# APIClientFactory
# ============================================================

class APIClientFactory:
    """API 客户端工厂 - 统一创建和管理所有外部 API 客户端"""

    def __init__(self, config: dict = None):
        self._config = config or {}
        self._clients: dict[str, BaseAPIClient] = {}

    def get_shopify(self) -> ShopifyClient:
        if "shopify" not in self._clients:
            self._clients["shopify"] = ShopifyClient(
                store_url=self._config.get("SHOPIFY_STORE_URL", ""),
                api_key=self._config.get("SHOPIFY_API_KEY", ""),
            )
        return self._clients["shopify"]

    def get_amazon(self) -> AmazonClient:
        if "amazon" not in self._clients:
            self._clients["amazon"] = AmazonClient(
                seller_id=self._config.get("AMAZON_SELLER_ID", ""),
                api_key=self._config.get("AMAZON_API_KEY", ""),
            )
        return self._clients["amazon"]

    def get_tiktok_shop(self) -> TikTokShopClient:
        if "tiktok" not in self._clients:
            self._clients["tiktok"] = TikTokShopClient(
                api_key=self._config.get("TIKTOK_SHOP_API_KEY", ""),
            )
        return self._clients["tiktok"]

    def get_whatsapp(self) -> WhatsAppClient:
        if "whatsapp" not in self._clients:
            self._clients["whatsapp"] = WhatsAppClient(
                phone_number_id=self._config.get("WHATSAPP_PHONE_NUMBER_ID", ""),
                api_key=self._config.get("WHATSAPP_API_KEY", ""),
            )
        return self._clients["whatsapp"]

    def get_heygen(self) -> HeyGenClient:
        if "heygen" not in self._clients:
            self._clients["heygen"] = HeyGenClient(
                api_key=self._config.get("HEYGEN_API_KEY", ""),
            )
        return self._clients["heygen"]

    def get_stripe(self) -> StripeClient:
        if "stripe" not in self._clients:
            self._clients["stripe"] = StripeClient(
                api_key=self._config.get("STRIPE_API_KEY", ""),
            )
        return self._clients["stripe"]

    def get_email(self) -> EmailClient:
        return EmailClient(
            provider=self._config.get("EMAIL_PROVIDER", "sendgrid"),
            api_key=self._config.get("SENDGRID_API_KEY", ""),
            smtp_config={
                "host": self._config.get("SMTP_HOST", ""),
                "port": int(self._config.get("SMTP_PORT", "587")),
                "username": self._config.get("SMTP_USERNAME", ""),
                "password": self._config.get("SMTP_PASSWORD", ""),
            },
        )

    async def close_all(self):
        """关闭所有客户端"""
        for client in self._clients.values():
            await client.close()
        self._clients.clear()
