"""
room_poster.py
クッキーを使って楽天Roomに自動ログイン・投稿するモジュール。

【正しい投稿フロー】
1. 楽天Roomにアクセスしてクッキーでログイン確認
2. 楽天市場の商品ページにアクセス
3. 「ROOMに投稿」ボタンをクリック（新しいタブで投稿ページが開く）
   ※ ボタンが見つからない場合は直接URLを構築
4. テキストエリアにキャプションを入力
5. AngularJSの collect() 関数をJavaScriptで直接呼び出して投稿

【楽天Room投稿ページのHTML構造】
<button ng-click="collect()" class="button button-red collect-btn ng-click-active"
        ng-disabled="isCollectDisabled || isSubmitted">
  <span ng-show="!isSubmitted" class="ng-binding">完了</span>
</button>
→ AngularJSアプリのため、通常クリックではなくJS経由でcollect()を呼び出す必要がある

【正しい投稿URL形式】
https://room.rakuten.co.jp/mix?itemcode={shop_code}:{item_code}&scid=we_room_upc60
"""

import os
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

RAKUTEN_COOKIES_JSON = os.environ.get("RAKUTEN_COOKIES", "" )
RAKUTEN_ROOM_URL = "https://room.rakuten.co.jp"


def load_cookies( ) -> list:
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
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
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
            # ── Step 1: 楽天Roomにアクセスしてログイン確認 ──────────
            print("[INFO] 楽天Roomにアクセス中...")
            page.goto(RAKUTEN_ROOM_URL, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)
            print(f"[INFO] 現在のURL: {page.url}")
            if "login" in page.url.lower() or "nid" in page.url.lower():
                print("[ERROR] クッキーが無効です。再度クッキーをエクスポートしてください。")
                page.screenshot(path="/tmp/debug_login_failed.png")
                browser.close()
                return False
            print("[INFO] ログイン確認済み")

            # ── Step 2: 楽天市場の商品ページにアクセス ──────────────
            item_url = product_info.get("item_url", "")
            print(f"[INFO] 商品ページにアクセス中: {item_url[:80]}...")
            page.goto(item_url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)
            page.screenshot(path="/tmp/debug_item_page.png")
            print(f"[INFO] 商品ページURL: {page.url}")

            # ── Step 3: 「ROOMに投稿」ボタンをクリック ──────────────
            print("[INFO] 「ROOMに投稿」ボタンを探しています...")
            room_button_selectors = [
                'a:has-text("ROOMに投稿")',
                'a[href*="room.rakuten.co.jp/mix"]',
                'a[href*="/mix?itemcode"]',
                'a:has-text("ROOM")',
            ]
            room_button_found = False
            post_page = None
            for selector in room_button_selectors:
                try:
                    element = page.locator(selector).first
                    if element.is_visible(timeout=5000):
                        print(f"[INFO] 「ROOMに投稿」ボタン発見: {selector}")
                        with context.expect_page(timeout=15000) as new_page_info:
                            element.click()
                        post_page = new_page_info.value
                        post_page.wait_for_load_state("domcontentloaded", timeout=60000)
                        time.sleep(3)
                        room_button_found = True
                        print(f"[INFO] 投稿ページが開きました: {post_page.url}")
                        break
                except Exception as ex:
                    print(f"[DEBUG] セレクタ {selector} 失敗: {ex}")
                    continue

            if not room_button_found:
                # ボタンが見つからない場合は直接URLを構築してアクセス
                print("[WARN] 「ROOMに投稿」ボタンが見つかりませんでした。直接URLを構築します...")
                page.screenshot(path="/tmp/debug_no_room_button.png")
                item_code_full = product_info.get("item_code_full", "")
                item_code = product_info.get("item_code", "")
                shop_code = product_info.get("shop_code", "")
                if item_code_full:
                    collect_url = f"https://room.rakuten.co.jp/mix?itemcode={item_code_full}&scid=we_room_upc60"
                elif item_code and shop_code:
                    collect_url = f"https://room.rakuten.co.jp/mix?itemcode={shop_code}:{item_code}&scid=we_room_upc60"
                else:
                    print("[ERROR] itemcodeが取得できませんでした 。")
                    browser.close()
                    return False
                print(f"[INFO] 投稿URLに直接アクセス: {collect_url}")
                post_page = context.new_page()
                post_page.goto(collect_url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(5)  # AngularJSの初期化を待つ
                print(f"[INFO] 投稿ページURL: {post_page.url}")

            # AngularJSの初期化を十分に待つ
            time.sleep(3)
            post_page.screenshot(path="/tmp/debug_post_page.png")

            # ── Step 4: キャプション入力 ──────────────────────────
            print("[INFO] キャプション入力中...")
            caption_selectors = [
                'textarea[placeholder*="オススメ"]',
                'textarea[placeholder*="コメント"]',
                'textarea',
            ]
            caption_entered = False
            for selector in caption_selectors:
                try:
                    element = post_page.locator(selector).first
                    if element.is_visible(timeout=5000):
                        element.click()
                        time.sleep(0.5)
                        element.fill("")
                        element.type(caption, delay=20)
                        time.sleep(1)
                        # AngularJSのng-modelを更新するためにinputイベントを発火
                        post_page.evaluate(
                            """(selector) => {
                                const el = document.querySelector(selector);
                                if (el) {
                                    const event = new Event('input', { bubbles: true });
                                    el.dispatchEvent(event);
                                    const changeEvent = new Event('change', { bubbles: true });
                                    el.dispatchEvent(changeEvent);
                                }
                            }""",
                            selector,
                        )
                        time.sleep(0.5)
                        print(f"[INFO] キャプション入力成功: {selector}")
                        caption_entered = True
                        break
                except Exception as ex:
                    print(f"[DEBUG] キャプション入力失敗 {selector}: {ex}")
                    continue

            if not caption_entered:
                print("[WARN] キャプション入力欄が見つかりませんでした。")
                post_page.screenshot(path="/tmp/debug_no_caption.png")

            post_page.screenshot(path="/tmp/debug_before_submit.png")

            # ── Step 5: AngularJSのcollect()関数を呼び出して投稿 ──
            print("[INFO] AngularJSのcollect()関数を呼び出して投稿中...")
            try:
                result = post_page.evaluate(
                    """() => {
                        try {
                            const btn = document.querySelector('button.collect-btn');
                            if (!btn) return 'collect-btn not found';
                            const scope = angular.element(btn).scope();
                            if (!scope) return 'scope not found';
                            if (scope.isCollectDisabled) return 'isCollectDisabled is true';
                            if (scope.isSubmitted) return 'isSubmitted is true';
                            scope.collect();
                            scope.$apply();
                            return 'collect() called successfully';
                        } catch(e) {
                            return 'error: ' + e.message;
                        }
                    }"""
                )
                print(f"[INFO] AngularJS collect() 結果: {result}")

                if "successfully" in str(result):
                    time.sleep(5)
                    post_page.screenshot(path="/tmp/debug_after_submit.png")
                    print(f"[INFO] 投稿後URL: {post_page.url}")
                    print("[INFO] 投稿が完了しました！")
                    browser.close()
                    return True
                else:
                    print(f"[WARN] AngularJS呼び出し結果: {result}。通常クリックを試みます...")
            except Exception as e:
                print(f"[WARN] AngularJS直接呼び出し失敗: {e}。通常クリックを試みます...")

            # 方法2: 通常クリック（フォールバック）
            print("[INFO] 「完了」ボタンを通常クリックで試みます...")
            submit_selectors = [
                'button.collect-btn',
                'button[ng-click="collect()"]',
                'button:has-text("完了")',
                '.submit-btn-centered button',
                'button.button-red',
            ]
            submitted = False
            for selector in submit_selectors:
                try:
                    element = post_page.locator(selector).first
                    if element.is_visible(timeout=5000):
                        post_page.evaluate(
                            f"""() => {{
                                const el = document.querySelector('{selector}');
                                if (el) {{
                                    el.removeAttribute('disabled');
                                    el.removeAttribute('ng-disabled');
                                }}
                            }}"""
                        )
                        element.click()
                        time.sleep(5)
                        submitted = True
                        print(f"[INFO] 「完了」ボタンクリック成功: {selector}")
                        break
                except Exception as ex:
                    print(f"[DEBUG] クリック失敗 {selector}: {ex}")
                    continue

            if not submitted:
                print("[ERROR] 「完了」ボタンが見つかりませんでした。")
                post_page.screenshot(path="/tmp/debug_no_submit.png")
                browser.close()
                return False

            post_page.screenshot(path="/tmp/debug_after_submit.png")
            print(f"[INFO] 投稿後URL: {post_page.url}")
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


if __name__ == "__main__":
    print("[INFO] room_poster.py の動作確認")
    print(f"[INFO] RAKUTEN_COOKIES: {'設定済み' if RAKUTEN_COOKIES_JSON else '未設定'}")
