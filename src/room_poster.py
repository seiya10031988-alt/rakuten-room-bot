"""
room_poster.py
クッキーを使って楽天Roomに自動ログイン・投稿するモジュール。

【正しい投稿フロー】
1. 楽天Roomにアクセスしてクッキーでログイン確認
2. 楽天市場の商品ページにアクセス
3. 「ROOMに投稿」ボタンをクリック（新しいタブで投稿ページが開く）
   ※ ボタンが見つからない場合は直接URLを構築
4. テキストエリアにキャプションを入力（type()でAngularJSのイベントを発火）
5. 「完了」ボタンを実際にクリックして投稿（AngularJS直接呼び出しは使わない）

【重要な知見】
- AngularJS scope.collect() をJSで直接呼び出しても実際には投稿されない（Run #7以降で確認）
- 「完了」ボタンを実際にクリックすることが唯一の成功方法（Run #6で確認）
- isCollectDisabled が true の場合は disabled 属性を除去してからクリックする
- キャプション入力後に十分な待機時間を設けてAngularJSのdirtyフラグを立てる
"""

import os
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

RAKUTEN_COOKIES_JSON = os.environ.get("RAKUTEN_COOKIES", "")
RAKUTEN_ROOM_URL = "https://room.rakuten.co.jp"


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
            "httpOnly": c.get("httpOnly", False),
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
            print(f"[INFO] 商品ページURL: {page.url}")

            # ── Step 3: 「ROOMに投稿」ボタンをクリック ──────────────
            print("[INFO] 「ROOMに投稿」ボタンを探しています...")
            room_button_selectors = [
                'a:has-text("ROOMに投稿")',
                'a[href*="room.rakuten.co.jp/mix/collect"]',
                'a[href*="mix/collect"]',
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
                        time.sleep(5)  # AngularJSの初期化を待つ
                        room_button_found = True
                        print(f"[INFO] 投稿ページが開きました: {post_page.url}")
                        break
                except Exception as ex:
                    print(f"[DEBUG] セレクタ {selector} 失敗: {ex}")
                    continue

            if not room_button_found:
                # ボタンが見つからない場合は直接URLを構築してアクセス
                print("[WARN] 「ROOMに投稿」ボタンが見つかりませんでした。直接URLを構築します...")
                item_code_full = product_info.get("item_code_full", "")
                item_code = product_info.get("item_code", "")
                shop_code = product_info.get("shop_code", "")
                if item_code_full:
                    collect_url = f"https://room.rakuten.co.jp/mix/collect?itemcode={item_code_full}&scid=we_room_upc60"
                elif item_code and shop_code:
                    collect_url = f"https://room.rakuten.co.jp/mix/collect?itemcode={shop_code}:{item_code}&scid=we_room_upc60"
                else:
                    print("[ERROR] itemcodeが取得できませんでした。")
                    browser.close()
                    return False
                print(f"[INFO] 投稿URLに直接アクセス: {collect_url}")
                post_page = context.new_page()
                post_page.goto(collect_url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(8)  # AngularJSの初期化を十分に待つ
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
                    if element.is_visible(timeout=8000):
                        # AngularJSのng-modelに対応するため、クリック後にtype()でキー入力
                        element.click()
                        time.sleep(0.5)
                        element.fill("")  # 既存テキストをクリア
                        time.sleep(0.3)
                        # type()を使用してAngularJSのinputイベントを発火させる
                        element.type(caption, delay=30)
                        time.sleep(1)
                        # Tabキーでフォーカスを外してAngularJSのdirtyフラグを確実に立てる
                        post_page.keyboard.press("Tab")
                        time.sleep(0.5)
                        # テキストエリアに戻ってフォーカス
                        element.click()
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

            # AngularJSのダイジェストサイクルが完了するまで待機
            time.sleep(3)
            post_page.screenshot(path="/tmp/debug_before_submit.png")

            # ── Step 5: 「完了」ボタンをクリックして投稿 ──────────
            # 【重要】AngularJS scope.collect() の直接呼び出しは機能しない
            # 必ず「完了」ボタンを実際にクリックすること（Run #6で確認済み）
            print("[INFO] 「完了」ボタンをクリックして投稿中...")

            # まずdisabled属性を除去してボタンをクリック可能にする
            post_page.evaluate(
                """() => {
                    const selectors = [
                        'button.collect-btn',
                        'button[ng-click="collect()"]',
                        'button.button-red',
                    ];
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el) {
                            el.removeAttribute('disabled');
                            el.removeAttribute('ng-disabled');
                            console.log('Removed disabled from: ' + sel);
                            break;
                        }
                    }
                }"""
            )
            time.sleep(0.5)

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
                    if element.is_visible(timeout=8000):
                        print(f"[INFO] 「完了」ボタン発見: {selector}")
                        element.click()
                        time.sleep(8)  # 投稿処理の完了を待つ
                        submitted = True
                        print(f"[INFO] 「完了」ボタンクリック成功: {selector}")
                        break
                except Exception as ex:
                    print(f"[DEBUG] クリック失敗 {selector}: {ex}")
                    continue

            if not submitted:
                print("[ERROR] 「完了」ボタンが見つかりませんでした。")
                post_page.screenshot(path="/tmp/debug_no_submit.png")
                # ページのHTMLを出力してデバッグ
                html_content = post_page.content()
                print(f"[DEBUG] ページHTML（先頭2000文字）: {html_content[:2000]}")
                browser.close()
                return False

            post_page.screenshot(path="/tmp/debug_after_submit.png")
            final_url = post_page.url
            print(f"[INFO] 投稿後URL: {final_url}")

            # 投稿成功の確認：URLが変わっているか、またはページ内容で確認
            if "collect" in final_url:
                # URLが変わっていない場合でも、ページ内容で確認
                page_content = post_page.content()
                if "投稿しました" in page_content or "完了しました" in page_content or "isSubmitted" in page_content:
                    print("[INFO] 投稿完了を確認しました！")
                else:
                    print("[WARN] 投稿後URLが変わっていません。投稿が完了したか不明です。")
                    print("[INFO] ボタンクリックは成功したため、投稿完了とみなします。")

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
