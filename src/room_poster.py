"""
room_poster.py
クッキーを使って楽天Roomに自動ログイン・投稿するモジュール。
reCAPTCHAを回避するため、ブラウザログインは行わずクッキーを直接セットする。
GitHub Actions環境（ヘッドレス）でも動作するように設計。
"""

import os
import json
import time
import requests
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# 環境変数から認証情報を取得
RAKUTEN_COOKIES_JSON = os.environ.get("RAKUTEN_COOKIES", "")

# 楽天RoomのURL
RAKUTEN_ROOM_URL = "https://room.rakuten.co.jp"
RAKUTEN_ROOM_POST_URL = "https://room.rakuten.co.jp/post/new"


def download_image(url: str ) -> str | None:
    try:
        high_res_url = url.replace("128x128", "500x500").replace("_ex=128x128", "_ex=500x500")
        response = requests.get(high_res_url, timeout=10)
        response.raise_for_status()
        suffix = ".jpg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(response.content)
            return f.name
    except Exception as e:
        print(f"[WARN] 画像ダウンロード失敗: {e}")
        return None


def load_cookies() -> list:
    if not RAKUTEN_COOKIES_JSON:
        raise ValueError("環境変数 RAKUTEN_COOKIES が設定されていません。")
    cookies_raw = json.loads(RAKUTEN_COOKIES_JSON)
    playwright_cookies = []
    for c in cookies_raw:
        cookie = {
            "name": c["name"],
            "value": c["value"],
            "domain": c["domain"],
            "path": c.get("path", "/"),
            "secure": c.get("secure", False),
            "httpOnly": c.get("httpOnly", False ),
        }
        same_site = c.get("sameSite")
        if same_site == "no_restriction":
            cookie["sameSite"] = "None"
        elif same_site == "lax":
            cookie["sameSite"] = "Lax"
        elif same_site == "strict":
            cookie["sameSite"] = "Strict"
        else:
            cookie["sameSite"] = "None"
        if not c.get("session", True) and c.get("expirationDate"):
            cookie["expires"] = int(c["expirationDate"])
        playwright_cookies.append(cookie)
    return playwright_cookies


def post_to_rakuten_room(product_info: dict, caption: str) -> bool:
    image_path = None
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        print("[INFO] クッキーをセット中...")
        try:
            cookies = load_cookies()
            context.add_cookies(cookies)
            print(f"[INFO] {len(cookies)}件のクッキーをセットしました。")
        except Exception as e:
            print(f"[ERROR] クッキーのロードに失敗しました: {e}")
            browser.close()
            return False

        page = context.new_page()
        try:
            print("[INFO] 楽天Roomにアクセス中...")
            page.goto(RAKUTEN_ROOM_URL, wait_until="networkidle", timeout=30000)
            time.sleep(2)
            if "login" in page.url.lower():
                print("[ERROR] クッキーが無効です。再度クッキーをエクスポートしてください。")
                page.screenshot(path="/tmp/debug_login_failed.png")
                browser.close()
                return False
            print("[INFO] ログイン確認済み")

            image_url = product_info.get("image_url", "")
            if image_url:
                image_path = download_image(image_url)
                print(f"[INFO] 画像ダウンロード: {image_path}")

            print("[INFO] 投稿ページへ移動中...")
            page.goto(RAKUTEN_ROOM_POST_URL, wait_until="networkidle", timeout=30000)
            time.sleep(3)
            page.screenshot(path="/tmp/debug_post_page.png")
            print(f"[INFO] 投稿ページURL: {page.url}")

            if "login" in page.url.lower() or "nid" in page.url.lower():
                print("[ERROR] 投稿ページへのアクセスに失敗。クッキーが期限切れの可能性があります。")
                browser.close()
                return False

            item_url = product_info.get("item_url", "")
            print(f"[INFO] 商品URL入力: {item_url[:60]}...")
            url_input_selectors = [
                'input[placeholder*="URL"]',
                'input[placeholder*="url"]',
                'input[placeholder*="商品"]',
                'input[placeholder*="楽天"]',
                'input[name*="url"]',
                'input[name*="item"]',
                'input[type="url"]',
                'input[type="text"]',
            ]
            url_entered = False
            for selector in url_input_selectors:
                try:
                    element = page.locator(selector).first
                    if element.is_visible(timeout=3000):
                        element.fill(item_url)
                        time.sleep(1)
                        element.press("Enter")
                        time.sleep(3)
                        print(f"[INFO] 商品URL入力成功: {selector}")
                        url_entered = True
                        break
                except Exception:
                    continue
            if not url_entered:
                print("[WARN] 商品URL入力欄が見つかりませんでした。")
                page.screenshot(path="/tmp/debug_no_url_input.png")

            print("[INFO] キャプション入力中...")
            caption_selectors = [
                'textarea[placeholder*="コメント"]',
                'textarea[placeholder*="テキスト"]',
                'textarea[placeholder*="説明"]',
                'textarea[name*="comment"]',
                'textarea[name*="caption"]',
                'textarea[name*="text"]',
                'textarea',
                '[contenteditable="true"]',
            ]
            for selector in caption_selectors:
                try:
                    element = page.locator(selector).first
                    if element.is_visible(timeout=3000):
                        element.fill(caption)
                        time.sleep(1)
                        print(f"[INFO] キャプション入力成功: {selector}")
                        break
                except Exception:
                    continue

            page.screenshot(path="/tmp/debug_before_submit.png")
            print("[INFO] 投稿を実行中...")
            submit_selectors = [
                'button[type="submit"]',
                'button:has-text("投稿")',
                'button:has-text("シェア")',
                'button:has-text("公開")',
                'button:has-text("保存")',
                'input[type="submit"]',
            ]
            submitted = False
            for selector in submit_selectors:
                try:
                    element = page.locator(selector).first
                    if element.is_visible(timeout=3000):
                        element.click()
                        page.wait_for_load_state("networkidle", timeout=30000)
                        time.sleep(3)
                        submitted = True
                        print(f"[INFO] 投稿ボタンクリック: {selector}")
                        break
                except Exception:
                    continue

            if not submitted:
                print("[ERROR] 投稿ボタンが見つかりませんでした。")
                page.screenshot(path="/tmp/debug_no_submit.png")
                browser.close()
                return False

            page.screenshot(path="/tmp/debug_after_submit.png")
            print(f"[INFO] 投稿後URL: {page.url}")
            print("[INFO] 投稿が完了しました！")
            browser.close()
            return True

        except PlaywrightTimeoutError as e:
            print(f"[ERROR] タイムアウトエラー: {e}")
            try:
                page.screenshot(path="/tmp/debug_timeout.png")
            except Exception:
                pass
            browser.close()
            return False
        except Exception as e:
            print(f"[ERROR] 予期しないエラー: {e}")
            try:
                page.screenshot(path="/tmp/debug_error.png")
            except Exception:
                pass
            browser.close()
            return False
        finally:
            if image_path and Path(image_path).exists():
                Path(image_path).unlink()


if __name__ == "__main__":
    print("[INFO] room_poster.py の動作確認")
    print(f"[INFO] RAKUTEN_COOKIES: {'設定済み' if RAKUTEN_COOKIES_JSON else '未設定'}")
