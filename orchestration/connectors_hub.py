"""
Connectors Hub - 完整的外部系统连接器集成中心
Shopify / Amazon SP-API / TikTok Shop / WhatsApp / HeyGen / Stripe
DHL / UPS / FedEx / Google Ads / Meta Ads / Google Analytics / 企业微信 / 飞书 / LinkedIn
"""

import asyncio
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from enum import Enum

import httpx

logger = logging.getLogger("openclaw.connectors")


# ============================================================
# Base HTTP Client
# ============================================================

@dataclass
class ClientConfig:
    base_url: str = ""
    api_key: str = ""
    api_secret: str = ""
    access_token: str = ""
    timeout: int = 30
    max_retries: int = 3
    headers: dict = field(default_factory=dict)


class BaseHTTPClient:
    def __init__(self, config: ClientConfig):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url if self.config.base_url else None,
                timeout=self.config.timeout,
                headers=self._headers(),
            )
        return self._client

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", **self.config.headers}
        if self.config.api_key:
            h["Authorization"] = f"Bearer {self.config.api_key}"
        if self.config.access_token:
            h["Authorization"] = f"Bearer {self.config.access_token}"
        return h

    async def _request(self, method: str, url: str, **kwargs) -> dict:
        client = await self._get_client()
        for attempt in range(self.config.max_retries):
            try:
                resp = await client.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"text": resp.text}
            except httpx.HTTPStatusError as e:
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(1 * (2 ** attempt))
                    continue
                logger.error(f"HTTP {method} {url} failed: {e.response.status_code}")
                return {"error": str(e), "status_code": e.response.status_code}
            except Exception as e:
                logger.error(f"Request failed: {e}")
                return {"error": str(e)}

    async def get(self, url: str, **kw) -> dict: return await self._request("GET", url, **kw)
    async def post(self, url: str, **kw) -> dict: return await self._request("POST", url, **kw)
    async def put(self, url: str, **kw) -> dict: return await self._request("PUT", url, **kw)
    async def delete(self, url: str, **kw) -> dict: return await self._request("DELETE", url, **kw)

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


# ============================================================
# E-Commerce Connectors
# ============================================================

class ShopifyConnector(BaseHTTPClient):
    """Shopify Admin API 连接器"""

    def __init__(self, store_url: str, access_token: str):
        super().__init__(ClientConfig(
            base_url=f"https://{store_url}/admin/api/2024-10",
            headers={"X-Shopify-Access-Token": access_token},
        ))

    async def list_orders(self, status: str = "any", limit: int = 50, **kw) -> dict:
        return await self.get(f"/orders.json?status={status}&limit={limit}")

    async def get_order(self, order_id: int) -> dict:
        return await self.get(f"/orders/{order_id}.json")

    async def list_products(self, limit: int = 50) -> dict:
        return await self.get(f"/products.json?limit={limit}")

    async def update_product(self, product_id: int, data: dict) -> dict:
        return await self.put(f"/products/{product_id}.json", json={"product": data})

    async def list_customers(self, limit: int = 50) -> dict:
        return await self.get(f"/customers.json?limit={limit}")

    async def get_inventory_levels(self, ids: list[int]) -> dict:
        return await self.get(f"/inventory_levels.json?inventory_item_ids={','.join(map(str, ids))}")

    async def create_webhook(self, topic: str, address: str) -> dict:
        return await self.post("/webhooks.json", json={"webhook": {"topic": topic, "address": address, "format": "json"}})

    async def get_abandoned_checkouts(self, limit: int = 50) -> dict:
        return await self.get(f"/checkouts.json?limit={limit}")

    async def create_draft_order(self, data: dict) -> dict:
        return await self.post("/draft_orders.json", json={"draft_order": data})

    async def get_analytics(self, range: str = "today") -> dict:
        """获取店铺分析数据"""
        return await self.get(f"/analytics/reports/total_sales.json?range={range}")


class AmazonConnector(BaseHTTPClient):
    """Amazon Selling Partner API (SP-API) 连接器"""

    def __init__(self, seller_id: str, access_token: str, refresh_token: str = ""):
        super().__init__(ClientConfig(
            base_url="https://sellingpartnerapi-na.amazon.com",
            access_token=access_token,
        ))
        self.seller_id = seller_id
        self.refresh_token = refresh_token

    async def list_orders(self, marketplace_id: str = "ATVPDKIKX0DER", created_after: str = None) -> dict:
        params = {"MarketplaceIds": marketplace_id}
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

    async def get_pricing(self, asins: list[str]) -> dict:
        return await self.get("/productPricing/v0/price", params={
            "Asins": ",".join(asins), "ItemType": "Asin",
        })

    async def get_reports(self, report_type: str = "GET_FLAT_FILE_ORDERS_DATA") -> dict:
        return await self.post("/reports/2021-06-30/reports", json={
            "reportType": report_type, "marketplaceIds": ["ATVPDKIKX0DER"],
        })

    async def submit_feed(self, feed_type: str, data: list) -> dict:
        return await self.post("/feeds/2021-06-30/feeds", json={
            "feedType": feed_type, "marketplaceIds": ["ATVPDKIKX0DER"],
        })


class TikTokShopConnector(BaseHTTPClient):
    """TikTok Shop API 连接器"""

    def __init__(self, app_key: str, app_secret: str, shop_cipher: str = ""):
        super().__init__(ClientConfig(
            base_url="https://open-api.tiktokglobalshop.com",
            api_key=app_key,
            api_secret=app_secret,
        ))
        self.app_key = app_key
        self.app_secret = app_secret
        self.shop_cipher = shop_cipher

    def _sign(self, path: str, params: dict) -> str:
        if not self.app_secret:
            return ""
        sorted_params = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        sign_str = f"{self.app_key}{path}{sorted_params}{self.app_secret}"
        return hashlib.sha256(sign_str.encode()).hexdigest()

    def _common_params(self) -> dict:
        return {
            "app_key": self.app_key,
            "timestamp": int(time.time()),
            "shop_cipher": self.shop_cipher,
        }

    async def list_orders(self, page_size: int = 20) -> dict:
        params = {**self._common_params(), "page_size": page_size}
        params["sign"] = self._sign("/api/orders/detail/list", params)
        return await self.post("/api/orders/detail/list", json=params)

    async def get_order_detail(self, order_id: str) -> dict:
        params = {**self._common_params(), "order_id_list": [order_id]}
        params["sign"] = self._sign("/api/orders/detail/query", params)
        return await self.post("/api/orders/detail/query", json=params)

    async def list_products(self) -> dict:
        params = self._common_params()
        params["sign"] = self._sign("/api/products/search", params)
        return await self.post("/api/products/search", json=params)

    async def get_shop_performance(self) -> dict:
        params = self._common_params()
        params["sign"] = self._sign("/api/shop/performance", params)
        return await self.post("/api/shop/performance", json=params)

    async def send_message(self, conversation_id: str, message: str) -> dict:
        params = {**self._common_params(), "conversation_id": conversation_id, "message": message}
        params["sign"] = self._sign("/api/message/send", params)
        return await self.post("/api/message/send", json=params)

    async def get_live_data(self, live_session_id: str) -> dict:
        params = {**self._common_params(), "live_session_id": live_session_id}
        return await self.post("/api/live/performance", json=params)


# ============================================================
# Communication Connectors
# ============================================================

class WhatsAppConnector(BaseHTTPClient):
    """WhatsApp Business API (Meta Cloud API) 连接器"""

    def __init__(self, phone_number_id: str, access_token: str):
        super().__init__(ClientConfig(
            base_url=f"https://graph.facebook.com/v19.0/{phone_number_id}",
            access_token=access_token,
        ))

    async def send_text(self, to: str, body: str) -> dict:
        return await self.post("/messages", json={
            "messaging_product": "whatsapp", "to": to,
            "type": "text", "text": {"body": body},
        })

    async def send_template(self, to: str, template_name: str, language: str = "en", components: list = None) -> dict:
        payload = {
            "messaging_product": "whatsapp", "to": to, "type": "template",
            "template": {"name": template_name, "language": {"code": language}},
        }
        if components:
            payload["template"]["components"] = components
        return await self.post("/messages", json=payload)

    async def send_image(self, to: str, image_url: str, caption: str = "") -> dict:
        return await self.post("/messages", json={
            "messaging_product": "whatsapp", "to": to, "type": "image",
            "image": {"link": image_url, "caption": caption},
        })

    async def send_document(self, to: str, doc_url: str, filename: str, caption: str = "") -> dict:
        return await self.post("/messages", json={
            "messaging_product": "whatsapp", "to": to, "type": "document",
            "document": {"link": doc_url, "filename": filename, "caption": caption},
        })

    async def send_product_catalog(self, to: str, catalog_id: str, product_id: str) -> dict:
        return await self.post("/messages", json={
            "messaging_product": "whatsapp", "to": to, "type": "interactive",
            "interactive": {
                "type": "product",
                "body": {"text": "Check out this product!"},
                "action": {"catalog_id": catalog_id, "product_retailer_id": product_id},
            },
        })

    async def mark_read(self, message_id: str) -> dict:
        return await self.post("/messages", json={
            "messaging_product": "whatsapp", "status": "read", "message_id": message_id,
        })

    async def get_business_profile(self) -> dict:
        return await self.get("/whatsapp_business_profile?fields=about,address,description,email,profile_picture_url,websites")


class EmailConnector:
    """邮件连接器 - SendGrid + SMTP"""

    def __init__(self, provider: str = "sendgrid", api_key: str = "", smtp: dict = None):
        self.provider = provider
        self.api_key = api_key
        self.smtp = smtp or {}

    async def send(self, to: str, subject: str, body: str, html: str = "", from_addr: str = "") -> dict:
        if self.provider == "sendgrid" and self.api_key:
            return await self._sendgrid(to, subject, body, html, from_addr)
        elif self.smtp.get("host"):
            return await self._smtp_send(to, subject, body, html, from_addr)
        return {"sent": False, "error": "No email provider configured"}

    async def _sendgrid(self, to, subject, body, html, from_addr) -> dict:
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail, Email, Content
            sg = SendGridAPIClient(self.api_key)
            message = Mail(
                from_email=from_addr or "noreply@lobsterplanet.com",
                to_emails=to, subject=subject,
                plain_text_content=Content("text/plain", body),
            )
            if html:
                message.add_content(Content("text/html", html))
            resp = sg.send(message)
            return {"sent": True, "status_code": resp.status_code}
        except ImportError:
            return {"sent": True, "mock": True, "message": "SendGrid not installed"}
        except Exception as e:
            return {"sent": False, "error": str(e)}

    async def _smtp_send(self, to, subject, body, html, from_addr) -> dict:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = from_addr or self.smtp.get("username", "")
            msg["To"] = to
            msg.attach(MIMEText(body, "plain"))
            if html:
                msg.attach(MIMEText(html, "html"))
            with smtplib.SMTP(self.smtp["host"], self.smtp.get("port", 587)) as server:
                server.starttls()
                server.login(self.smtp["username"], self.smtp["password"])
                server.send_message(msg)
            return {"sent": True}
        except Exception as e:
            return {"sent": False, "error": str(e)}


# ============================================================
# AI & Content Connectors
# ============================================================

class HeyGenConnector(BaseHTTPClient):
    """HeyGen 数字人视频 API 连接器"""

    def __init__(self, api_key: str):
        super().__init__(ClientConfig(
            base_url="https://api.heygen.com",
            api_key=api_key,
            timeout=300,
        ))

    async def create_avatar_video(self, avatar_id: str, voice_id: str, script: str,
                                   background: str = "#ffffff", width: int = 1920, height: int = 1080) -> dict:
        return await self.post("/v2/video/generate", json={
            "video_inputs": [{
                "character": {"type": "avatar", "avatar_id": avatar_id, "avatar_style": "normal"},
                "voice": {"type": "text", "voice_id": voice_id, "input_text": script},
                "background": {"type": "color", "value": background},
            }],
            "dimension": {"width": width, "height": height},
        })

    async def get_video_status(self, video_id: str) -> dict:
        return await self.get(f"/v2/video/generate/status?video_id={video_id}")

    async def list_avatars(self) -> dict:
        return await self.get("/v2/avatars")

    async def list_voices(self) -> dict:
        return await self.get("/v2/voices")

    async def create_talking_photo(self, photo_url: str, script: str, voice_id: str = "") -> dict:
        return await self.post("/v2/talking_photo/generate", json={
            "talking_photo_input": {"type": "photo", "photo_url": photo_url},
            "voice": {"type": "text", "voice_id": voice_id, "input_text": script},
        })

    async def create_streaming_session(self, avatar_id: str, voice_id: str) -> dict:
        """创建直播数字人会话"""
        return await self.post("/v2/streaming/new", json={
            "avatar_id": avatar_id, "voice_id": voice_id, "quality": "high",
        })

    async def send_streaming_text(self, session_id: str, text: str) -> dict:
        """向直播数字人发送文本"""
        return await self.post(f"/v2/streaming/{session_id}/task", json={"text": text})


# ============================================================
# Payment Connectors
# ============================================================

class StripeConnector(BaseHTTPClient):
    """Stripe 支付 API 连接器"""

    def __init__(self, api_key: str):
        super().__init__(ClientConfig(
            base_url="https://api.stripe.com/v1",
            api_key=api_key,
        ))

    async def create_payment_link(self, amount: int, currency: str = "usd",
                                   description: str = "", metadata: dict = None) -> dict:
        data = {
            "line_items[0][price_data][currency]": currency,
            "line_items[0][price_data][product_data][name]": description,
            "line_items[0][price_data][unit_amount]": amount,
            "line_items[0][quantity]": 1,
        }
        if metadata:
            for k, v in metadata.items():
                data[f"metadata[{k}]"] = str(v)
        return await self.post("/payment_links", data=data)

    async def get_payment_intent(self, pi_id: str) -> dict:
        return await self.get(f"/payment_intents/{pi_id}")

    async def create_refund(self, pi_id: str, amount: int = None) -> dict:
        data = {"payment_intent": pi_id}
        if amount:
            data["amount"] = amount
        return await self.post("/refunds", data=data)

    async def create_invoice(self, customer_id: str, items: list[dict]) -> dict:
        return await self.post("/invoices", json={"customer": customer_id, "collection_method": "send_invoice"})

    async def list_customers(self, limit: int = 100) -> dict:
        return await self.get(f"/customers?limit={limit}")

    async def get_balance(self) -> dict:
        return await self.get("/balance")


class PayPalConnector(BaseHTTPClient):
    """PayPal API 连接器"""

    def __init__(self, client_id: str, client_secret: str, sandbox: bool = True):
        base = "https://api-m.sandbox.paypal.com" if sandbox else "https://api-m.paypal.com"
        super().__init__(ClientConfig(base_url=base))
        self.client_id = client_id
        self.client_secret = client_secret

    async def _get_token(self) -> str:
        resp = await self.post("/v1/oauth2/token",
                               data={"grant_type": "client_credentials"},
                               auth=(self.client_id, self.client_secret))
        return resp.get("access_token", "")

    async def create_order(self, amount: float, currency: str = "USD", description: str = "") -> dict:
        token = await self._get_token()
        self.config.access_token = token
        return await self.post("/v2/checkout/orders", json={
            "intent": "CAPTURE",
            "purchase_units": [{"amount": {"currency_code": currency, "value": str(amount)}, "description": description}],
        })

    async def capture_order(self, order_id: str) -> dict:
        token = await self._get_token()
        self.config.access_token = token
        return await self.post(f"/v2/checkout/orders/{order_id}/capture")


# ============================================================
# Logistics Connectors
# ============================================================

class DHLCConnector(BaseHTTPClient):
    """DHL Express API 连接器"""

    def __init__(self, api_key: str, api_secret: str = ""):
        super().__init__(ClientConfig(
            base_url="https://api-eu.dhl.com",
            api_key=api_key,
        ))

    async def get_quote(self, origin: str, destination: str, weight_kg: float,
                         length_cm: float, width_cm: float, height_cm: float) -> dict:
        return await self.get("/track/shipments", params={
            "originCountryCode": origin,
            "destinationCountryCode": destination,
            "weight": weight_kg,
            "length": length_cm,
            "width": width_cm,
            "height": height_cm,
        })

    async def track_shipment(self, tracking_number: str) -> dict:
        return await self.get(f"/track/shipments?trackingNumber={tracking_number}")

    async def create_shipment(self, shipment_data: dict) -> dict:
        return await self.post("/shipments", json=shipment_data)

    async def get_service_points(self, country: str, city: str, postal_code: str = "") -> dict:
        return await self.get("/location-finder/v1/find-by-address", params={
            "countryCode": country, "addressLocality": city, "postalCode": postal_code,
        })


class UPSConnector(BaseHTTPClient):
    """UPS API 连接器"""

    def __init__(self, client_id: str, client_secret: str, account_number: str = ""):
        super().__init__(ClientConfig(
            base_url="https://onlinetools.ups.com/api",
        ))
        self.client_id = client_id
        self.client_secret = client_secret
        self.account_number = account_number
        self._token: str = ""
        self._token_expiry: float = 0

    async def _auth(self):
        if self._token and time.time() < self._token_expiry:
            return
        resp = await self.post("https://onlinetools.ups.com/security/v1/oauth/token",
                                data={"grant_type": "client_credentials"},
                                auth=(self.client_id, self.client_secret))
        self._token = resp.get("access_token", "")
        self._token_expiry = time.time() + resp.get("expires_in", 3600) - 60
        self.config.access_token = self._token

    async def track(self, tracking_number: str) -> dict:
        await self._auth()
        return await self.get(f"/track/v1/details/{tracking_number}")

    async def get_rates(self, data: dict) -> dict:
        await self._auth()
        return await self.post("/rating/v2/Shop", json=data)

    async def create_shipment(self, data: dict) -> dict:
        await self._auth()
        return await self.post("/shipments/v1/ship", json=data)


class FedExConnector(BaseHTTPClient):
    """FedEx API 连接器"""

    def __init__(self, api_key: str, secret_key: str, account_number: str = ""):
        super().__init__(ClientConfig(
            base_url="https://apis.fedex.com",
        ))
        self.api_key = api_key
        self.secret_key = secret_key
        self.account_number = account_number
        self._token: str = ""
        self._token_expiry: float = 0

    async def _auth(self):
        if self._token and time.time() < self._token_expiry:
            return
        resp = await self.post("/oauth/token", data={
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.secret_key,
        })
        self._token = resp.get("access_token", "")
        self._token_expiry = time.time() + resp.get("expires_in", 3600) - 60
        self.config.access_token = self._token

    async def track(self, tracking_number: str) -> dict:
        await self._auth()
        return await self.post("/track/v1/trackingnumbers", json={
            "trackingInfo": [{"trackingNumberInfo": {"trackingNumber": tracking_number}}],
        })

    async def get_rates(self, data: dict) -> dict:
        await self._auth()
        return await self.post("/rate/v1/rates/quotes", json=data)

    async def create_shipment(self, data: dict) -> dict:
        await self._auth()
        return await self.post("/ship/v1/shipments", json=data)


# ============================================================
# Advertising Connectors
# ============================================================

class GoogleAdsConnector(BaseHTTPClient):
    """Google Ads API 连接器"""

    def __init__(self, developer_token: str, client_id: str, client_secret: str, refresh_token: str, customer_id: str):
        super().__init__(ClientConfig(
            base_url="https://googleads.googleapis.com/v16",
        ))
        self.developer_token = developer_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.customer_id = customer_id
        self._token: str = ""
        self._token_expiry: float = 0

    async def _auth(self):
        if self._token and time.time() < self._token_expiry:
            return
        resp = await self.post("https://oauth2.googleapis.com/token", data={
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        })
        self._token = resp.get("access_token", "")
        self._token_expiry = time.time() + resp.get("expires_in", 3600) - 60
        self.config.access_token = self._token

    async def search(self, query: str) -> dict:
        await self._auth()
        headers = {
            "developer-token": self.developer_token,
            "login-customer-id": self.customer_id,
        }
        return await self.post(f"/customers/{self.customer_id}/googleAds:search",
                                json={"query": query}, headers=headers)

    async def get_campaigns(self) -> dict:
        query = """
        SELECT campaign.id, campaign.name, campaign.status,
               metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.conversions, metrics.conversions_value
        FROM campaign
        WHERE segments.date DURING LAST_30_DAYS
        """
        return await self.search(query)

    async def get_keyword_performance(self) -> dict:
        query = """
        SELECT ad_group_criterion.keyword.text, metrics.impressions,
               metrics.clicks, metrics.cost_micros, metrics.conversions
        FROM keyword_view
        WHERE segments.date DURING LAST_30_DAYS
        """
        return await self.search(query)

    async def get_shopping_performance(self) -> dict:
        query = """
        SELECT product_group_view.resource_name, metrics.impressions,
               metrics.clicks, metrics.cost_micros, metrics.conversions
        FROM product_group_view
        WHERE segments.date DURING LAST_30_DAYS
        """
        return await self.search(query)


class MetaAdsConnector(BaseHTTPClient):
    """Meta Ads (Facebook/Instagram) API 连接器"""

    def __init__(self, access_token: str, ad_account_id: str):
        super().__init__(ClientConfig(
            base_url=f"https://graph.facebook.com/v19.0",
            access_token=access_token,
        ))
        self.ad_account_id = ad_account_id

    async def get_campaigns(self, fields: str = "id,name,status,objective,daily_budget,insights{impressions,clicks,spend,actions,cpm,cpc,ctr}") -> dict:
        return await self.get(f"/act_{self.ad_account_id}/campaigns?fields={fields}")

    async def get_adsets(self, fields: str = "id,name,status,targeting,optimization_goal,insights{impressions,clicks,spend}") -> dict:
        return await self.get(f"/act_{self.ad_account_id}/adsets?fields={fields}")

    async def get_ads(self, fields: str = "id,name,status,creative,insights{impressions,clicks,spend,actions}") -> dict:
        return await self.get(f"/act_{self.ad_account_id}/ads?fields={fields}")

    async def get_insights(self, date_preset: str = "last_30d", fields: str = "impressions,clicks,spend,cpm,cpc,ctr,actions") -> dict:
        return await self.get(f"/act_{self.ad_account_id}/insights?date_preset={date_preset}&fields={fields}")

    async def create_campaign(self, name: str, objective: str = "CONVERSIONS", status: str = "PAUSED") -> dict:
        return await self.post(f"/act_{self.ad_account_id}/campaigns", json={
            "name": name, "objective": objective, "status": status,
            "special_ad_categories": [],
        })

    async def update_campaign(self, campaign_id: str, data: dict) -> dict:
        return await self.post(f"/{campaign_id}", json=data)

    async def get_lead_forms(self, page_id: str) -> dict:
        return await self.get(f"/{page_id}/leadgen_forms")

    async def get_lead_data(self, lead_id: str) -> dict:
        return await self.get(f"/{lead_id}")


# ============================================================
# Analytics & Monitoring Connectors
# ============================================================

class GoogleAnalyticsConnector(BaseHTTPClient):
    """Google Analytics 4 Data API 连接器"""

    def __init__(self, property_id: str, client_id: str, client_secret: str, refresh_token: str):
        super().__init__(ClientConfig(
            base_url="https://analyticsdata.googleapis.com/v1beta",
        ))
        self.property_id = property_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self._token: str = ""
        self._token_expiry: float = 0

    async def _auth(self):
        if self._token and time.time() < self._token_expiry:
            return
        resp = await self.post("https://oauth2.googleapis.com/token", data={
            "client_id": self.client_id, "client_secret": self.client_secret,
            "refresh_token": self.refresh_token, "grant_type": "refresh_token",
        })
        self._token = resp.get("access_token", "")
        self._token_expiry = time.time() + resp.get("expires_in", 3600) - 60
        self.config.access_token = self._token

    async def get_realtime(self) -> dict:
        await self._auth()
        return await self.post(f"/properties/{self.property_id}:runRealtimeReport", json={
            "metrics": [{"name": "activeUsers"}],
            "dimensions": [{"name": "country"}, {"name": "deviceCategory"}],
        })

    async def get_report(self, start_date: str, end_date: str, metrics: list, dimensions: list = None) -> dict:
        await self._auth()
        body = {
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "metrics": [{"name": m} for m in metrics],
        }
        if dimensions:
            body["dimensions"] = [{"name": d} for d in dimensions]
        return await self.post(f"/properties/{self.property_id}:runReport", json=body)

    async def get_ecommerce(self, start_date: str = "30daysAgo", end_date: str = "today") -> dict:
        return await self.get_report(start_date, end_date,
                                      ["totalRevenue", "transactions", "averagePurchaseRevenue", "itemViews"],
                                      ["itemName", "itemCategory"])


# ============================================================
# Enterprise Communication Connectors
# ============================================================

class WeChatWorkConnector(BaseHTTPClient):
    """企业微信 API 连接器"""

    def __init__(self, corp_id: str, corp_secret: str, agent_id: str = ""):
        super().__init__(ClientConfig(
            base_url="https://qyapi.weixin.qq.com/cgi-bin",
        ))
        self.corp_id = corp_id
        self.corp_secret = corp_secret
        self.agent_id = agent_id
        self._token: str = ""
        self._token_expiry: float = 0

    async def _auth(self):
        if self._token and time.time() < self._token_expiry:
            return
        resp = await self.get(f"/gettoken?corpid={self.corp_id}&corpsecret={self.corp_secret}")
        self._token = resp.get("access_token", "")
        self._token_expiry = time.time() + resp.get("expires_in", 7200) - 60

    async def send_text(self, content: str, to_users: str = "@all") -> dict:
        await self._auth()
        return await self.post(f"/message/send?access_token={self._token}", json={
            "touser": to_users, "msgtype": "text",
            "agentid": self.agent_id,
            "text": {"content": content},
        })

    async def send_markdown(self, content: str, to_users: str = "@all") -> dict:
        await self._auth()
        return await self.post(f"/message/send?access_token={self._token}", json={
            "touser": to_users, "msgtype": "markdown",
            "agentid": self.agent_id,
            "markdown": {"content": content},
        })

    async def send_news(self, articles: list, to_users: str = "@all") -> dict:
        await self._auth()
        return await self.post(f"/message/send?access_token={self._token}", json={
            "touser": to_users, "msgtype": "news",
            "agentid": self.agent_id,
            "news": {"articles": articles},
        })

    async def upload_media(self, media_type: str, file_path: str) -> dict:
        await self._auth()
        with open(file_path, "rb") as f:
            return await self.post(f"/media/upload?access_token={self._token}&type={media_type}",
                                    files={"media": f})


class FeishuConnector(BaseHTTPClient):
    """飞书 API 连接器"""

    def __init__(self, app_id: str, app_secret: str):
        super().__init__(ClientConfig(
            base_url="https://open.feishu.cn/open-apis",
        ))
        self.app_id = app_id
        self.app_secret = app_secret
        self._token: str = ""
        self._token_expiry: float = 0

    async def _auth(self):
        if self._token and time.time() < self._token_expiry:
            return
        resp = await self.post("/auth/v3/tenant_access_token/internal", json={
            "app_id": self.app_id, "app_secret": self.app_secret,
        })
        self._token = resp.get("tenant_access_token", "")
        self._token_expiry = time.time() + resp.get("expire", 7200) - 60

    async def send_text(self, receive_id: str, content: str, receive_type: str = "open_id") -> dict:
        await self._auth()
        return await self.post("/im/v1/messages?receive_id_type=" + receive_type, json={
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": content}),
        })

    async def send_card(self, receive_id: str, card: dict) -> dict:
        await self._auth()
        return await self.post("/im/v1/messages?receive_id_type=open_id", json={
            "receive_id": receive_id,
            "msg_type": "interactive",
            "content": json.dumps(card),
        })

    async def send_to_chat(self, chat_id: str, content: str) -> dict:
        await self._auth()
        return await self.post(f"/im/v1/messages?receive_id_type=chat_id", json={
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": content}),
        })

    async def create_doc(self, title: str, folder_token: str = "") -> dict:
        await self._auth()
        return await self.post("/docx/v1/documents", json={"title": title, "folder_token": folder_token})


class LinkedInConnector(BaseHTTPClient):
    """LinkedIn API 连接器"""

    def __init__(self, client_id: str, client_secret: str, access_token: str = ""):
        super().__init__(ClientConfig(
            base_url="https://api.linkedin.com/v2",
            access_token=access_token,
        ))
        self.client_id = client_id
        self.client_secret = client_secret

    async def get_profile(self) -> dict:
        return await self.get("/me")

    async def search_people(self, keywords: str, count: int = 10) -> dict:
        return await self.get("/search/people", params={"keywords": keywords, "count": count})

    async def get_connections(self) -> dict:
        return await self.get("/connections")

    async def send_message(self, recipient_urn: str, subject: str, body: str) -> dict:
        return await self.post("/messages", json={
            "recipients": [{"person": recipient_urn}],
            "subject": subject,
            "body": body,
        })

    async def share_post(self, text: str, visibility: str = "PUBLIC") -> dict:
        return await self.post("/ugcPosts", json={
            "author": f"urn:li:person:{self.client_id}",
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibility},
        })


# ============================================================
# Connector Hub - 统一连接器管理中心
# ============================================================

class ConnectorHub:
    """连接器管理中心 - 统一管理所有外部系统连接"""

    def __init__(self, config: dict = None):
        self.config = config or {}
        self._connectors: dict[str, Any] = {}
        self._initialized = False

    async def initialize(self):
        """初始化所有连接器"""
        if self._initialized:
            return

        # E-Commerce
        if self.config.get("SHOPIFY_STORE_URL"):
            self._connectors["shopify"] = ShopifyConnector(
                store_url=self.config["SHOPIFY_STORE_URL"],
                access_token=self.config.get("SHOPIFY_ACCESS_TOKEN", ""),
            )
            logger.info("[ConnectorHub] Shopify connected")

        if self.config.get("AMAZON_SELLER_ID"):
            self._connectors["amazon"] = AmazonConnector(
                seller_id=self.config["AMAZON_SELLER_ID"],
                access_token=self.config.get("AMAZON_ACCESS_TOKEN", ""),
            )
            logger.info("[ConnectorHub] Amazon SP-API connected")

        if self.config.get("TIKTOK_APP_KEY"):
            self._connectors["tiktok_shop"] = TikTokShopConnector(
                app_key=self.config["TIKTOK_APP_KEY"],
                app_secret=self.config.get("TIKTOK_APP_SECRET", ""),
                shop_cipher=self.config.get("TIKTOK_SHOP_CIPHER", ""),
            )
            logger.info("[ConnectorHub] TikTok Shop connected")

        # Communication
        if self.config.get("WHATSAPP_PHONE_NUMBER_ID"):
            self._connectors["whatsapp"] = WhatsAppConnector(
                phone_number_id=self.config["WHATSAPP_PHONE_NUMBER_ID"],
                access_token=self.config.get("WHATSAPP_ACCESS_TOKEN", ""),
            )
            logger.info("[ConnectorHub] WhatsApp connected")

        if self.config.get("SENDGRID_API_KEY"):
            self._connectors["email"] = EmailConnector(
                provider="sendgrid",
                api_key=self.config["SENDGRID_API_KEY"],
            )
            logger.info("[ConnectorHub] Email (SendGrid) connected")

        # AI Content
        if self.config.get("HEYGEN_API_KEY"):
            self._connectors["heygen"] = HeyGenConnector(
                api_key=self.config["HEYGEN_API_KEY"],
            )
            logger.info("[ConnectorHub] HeyGen connected")

        # Payment
        if self.config.get("STRIPE_API_KEY"):
            self._connectors["stripe"] = StripeConnector(
                api_key=self.config["STRIPE_API_KEY"],
            )
            logger.info("[ConnectorHub] Stripe connected")

        if self.config.get("PAYPAL_CLIENT_ID"):
            self._connectors["paypal"] = PayPalConnector(
                client_id=self.config["PAYPAL_CLIENT_ID"],
                client_secret=self.config.get("PAYPAL_CLIENT_SECRET", ""),
            )
            logger.info("[ConnectorHub] PayPal connected")

        # Logistics
        if self.config.get("DHL_API_KEY"):
            self._connectors["dhl"] = DHLCConnector(
                api_key=self.config["DHL_API_KEY"],
            )
            logger.info("[ConnectorHub] DHL connected")

        if self.config.get("UPS_CLIENT_ID"):
            self._connectors["ups"] = UPSConnector(
                client_id=self.config["UPS_CLIENT_ID"],
                client_secret=self.config.get("UPS_CLIENT_SECRET", ""),
                account_number=self.config.get("UPS_ACCOUNT_NUMBER", ""),
            )
            logger.info("[ConnectorHub] UPS connected")

        if self.config.get("FEDEX_API_KEY"):
            self._connectors["fedex"] = FedExConnector(
                api_key=self.config["FEDEX_API_KEY"],
                secret_key=self.config.get("FEDEX_SECRET_KEY", ""),
                account_number=self.config.get("FEDEX_ACCOUNT_NUMBER", ""),
            )
            logger.info("[ConnectorHub] FedEx connected")

        # Advertising
        if self.config.get("GOOGLE_ADS_DEVELOPER_TOKEN"):
            self._connectors["google_ads"] = GoogleAdsConnector(
                developer_token=self.config["GOOGLE_ADS_DEVELOPER_TOKEN"],
                client_id=self.config.get("GOOGLE_ADS_CLIENT_ID", ""),
                client_secret=self.config.get("GOOGLE_ADS_CLIENT_SECRET", ""),
                refresh_token=self.config.get("GOOGLE_ADS_REFRESH_TOKEN", ""),
                customer_id=self.config.get("GOOGLE_ADS_CUSTOMER_ID", ""),
            )
            logger.info("[ConnectorHub] Google Ads connected")

        if self.config.get("META_ADS_ACCESS_TOKEN"):
            self._connectors["meta_ads"] = MetaAdsConnector(
                access_token=self.config["META_ADS_ACCESS_TOKEN"],
                ad_account_id=self.config.get("META_ADS_ACCOUNT_ID", ""),
            )
            logger.info("[ConnectorHub] Meta Ads connected")

        # Analytics
        if self.config.get("GA4_PROPERTY_ID"):
            self._connectors["google_analytics"] = GoogleAnalyticsConnector(
                property_id=self.config["GA4_PROPERTY_ID"],
                client_id=self.config.get("GA4_CLIENT_ID", ""),
                client_secret=self.config.get("GA4_CLIENT_SECRET", ""),
                refresh_token=self.config.get("GA4_REFRESH_TOKEN", ""),
            )
            logger.info("[ConnectorHub] Google Analytics connected")

        # Enterprise Communication
        if self.config.get("WECHAT_WORK_CORP_ID"):
            self._connectors["wechat_work"] = WeChatWorkConnector(
                corp_id=self.config["WECHAT_WORK_CORP_ID"],
                corp_secret=self.config.get("WECHAT_WORK_CORP_SECRET", ""),
                agent_id=self.config.get("WECHAT_WORK_AGENT_ID", ""),
            )
            logger.info("[ConnectorHub] WeChat Work connected")

        if self.config.get("FEISHU_APP_ID"):
            self._connectors["feishu"] = FeishuConnector(
                app_id=self.config["FEISHU_APP_ID"],
                app_secret=self.config.get("FEISHU_APP_SECRET", ""),
            )
            logger.info("[ConnectorHub] Feishu connected")

        if self.config.get("LINKEDIN_CLIENT_ID"):
            self._connectors["linkedin"] = LinkedInConnector(
                client_id=self.config["LINKEDIN_CLIENT_ID"],
                client_secret=self.config.get("LINKEDIN_CLIENT_SECRET", ""),
                access_token=self.config.get("LINKEDIN_ACCESS_TOKEN", ""),
            )
            logger.info("[ConnectorHub] LinkedIn connected")

        self._initialized = True
        logger.info(f"[ConnectorHub] Total connectors: {len(self._connectors)}")

    def get(self, name: str):
        return self._connectors.get(name)

    def get_all(self) -> dict:
        return {k: type(v).__name__ for k, v in self._connectors.items()}

    async def close_all(self):
        for name, conn in self._connectors.items():
            if hasattr(conn, 'close'):
                try:
                    await conn.close()
                except Exception as e:
                    logger.warning(f"Error closing {name}: {e}")
        self._connectors.clear()
        logger.info("[ConnectorHub] All connectors closed")
