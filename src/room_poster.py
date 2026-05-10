"""
room_poster.py
クッキーを使って楽天Roomに自動ログイン・投稿するモジュール。

【正しい投稿フロー】
1. 楽天市場の商品ページにアクセス
2. 「ROOMに投稿」ボタンのhrefからitemcodeを取得
3. ROOMの投稿ページ（/mix/collect?itemcode=数字ID）に直接アクセス
4. textareaにキャプションを入力
5. 「完了」ボタンをクリック

【修正履歴】
- v4: 「ROOMに投稿」ボタンのhref属性からitemcodeを取得（数字ID形式）
- v3: wait_for_selectorでAngularJS初期化完了を確実に待機
- v2: Run #6コードに完全復元（element.fill + is_visible方式）
"""

import os
import json
import time
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
            # Step 1: 楽天Roomにアクセスしてログイン確認
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

            # Step 2: 楽天市場の商品ページにアクセス
            item_url = product_info.get("item_url", "")
            print(f"[INFO] 商品ページにアクセス中: {item_url[:80]}...")
            page.goto(item_url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)
            page.screenshot(path="/tmp/debug_item_page.png")
            print(f"[INFO] 商品ページURL: {page.url}")

            # Step 3: 「ROOMに投稿」ボタンのhrefからitemcodeを取得
            print("[INFO] 「ROOMに投稿」ボタンのURLを取得中...")
            collect_url = None
            room_button_selectors = [
                'a:has-text("ROOMに投稿")',
                'a[href*="room.rakuten.co.jp/mix/collect"]',
                'a[href*="mix/collect"]',
                'a:has-text("ROOM")',
            ]
            for selector in room_button_selectors:
                try:
                    element = page.locator(selector).first
                    if element.is_visible(timeout=5000):
                        href = element.get_attribute("href")
                        if href and "collect" in href:
                            # hrefが相対URLの場合はフルURLに変換
                            if href.startswith("//"):
                                href = "https:" + href
                            elif href.startswith("/"):
                                href = "https://room.rakuten.co.jp" + href
                            collect_url = href
                            print(f"[INFO] 「ROOMに投稿」ボタン発見: {selector}")
                            print(f"[INFO] 投稿URL取得: {collect_url}")
                            break
                except Exception as ex:
                    print(f"[DEBUG] セレクタ {selector} 失敗: {ex}")
                    continue

            if not collect_url:
                # hrefが取得できない場合はJavaScriptでページ内のROOMリンクを探す
                print("[WARN] 通常セレクタでURL取得失敗。JavaScriptで検索中...")
                page.screenshot(path="/tmp/debug_no_room_button.png")
                try:
                    collect_url = page.evaluate("""
                        () => {
                            const links = document.querySelectorAll('a[href]');
                            for (const link of links) {
                                const href = link.href || link.getAttribute('href');
                                if (href && href.includes('collect')) {
                                    return href;
                                }
                            }
                            return null;
                        }
                    """)
                    if collect_url:
                        print(f"[INFO] JavaScriptでURL取得: {collect_url}")
                except Exception as e:
                    print(f"[DEBUG] JavaScript検索失敗: {e}")

            if not collect_url:
                # 最終手段: item_code_fullから直接URLを構築
                print("[WARN] URLが取得できませんでした。itemcodeから直接URLを構築します...")
                item_code_full = product_info.get("item_code_full", "")
                shop_code = product_info.get("shop_code", "")
                item_code = product_info.get("item_code", "")
                if item_code_full:
                    collect_url = f"https://room.rakuten.co.jp/mix/collect?itemcode={item_code_full}&scid=we_room_upc60"
                elif shop_code and item_code:
                    collect_url = f"https://room.rakuten.co.jp/mix/collect?itemcode={shop_code}:{item_code}&scid=we_room_upc60"
                else:
                    print("[ERROR] itemcodeが取得できませんでした。")
                    browser.close()
                    return False
                print(f"[INFO] フォールバックURL: {collect_url}")

            # Step 4: 投稿ページに直接アクセス
            print(f"[INFO] 投稿ページにアクセス中: {collect_url}")
            post_page = context.new_page()
            post_page.goto(collect_url, wait_until="domcontentloaded", timeout=60000)
            print(f"[INFO] 投稿ページURL: {post_page.url}")

            # 403エラーチェック
            page_content = post_page.content()
            if "403" in page_content and "Forbidden" in page_content:
                print("[ERROR] 403 Forbidden - 認証エラー。クッキーを更新してください。")
                post_page.screenshot(path="/tmp/debug_403.png")
                browser.close()
                return False

            # 「要求されたURL存在しません」チェック
            if "要求されたURL存在しません" in page_content:
                print("[ERROR] 投稿できない商品です（要求されたURL存在しません）。")
                post_page.screenshot(path="/tmp/debug_url_not_found.png")
                browser.close()
                return False

            # Step 5: AngularJS初期化完了を待ってからキャプション入力
            print("[INFO] 投稿フォームの読み込みを待機中...")
            try:
                post_page.wait_for_selector(
                    'textarea[placeholder*="オススメ"], textarea[placeholder*="コメント"], textarea',
                    state="visible",
                    timeout=30000
                )
                print("[INFO] 投稿フォーム読み込み完了")
            except PlaywrightTimeoutError:
                print("[WARN] 投稿フォームの待機タイムアウト。スクリーンショットを保存します。")
                post_page.screenshot(path="/tmp/debug_form_timeout.png")

            post_page.screenshot(path="/tmp/debug_post_page.png")

            print("[INFO] キャプション入力中...")
            caption_selectors = [
                'textarea[placeholder*="オススメ"]',
                'textarea[placeholder*="コメント"]',
                'textarea[placeholder*="テキスト"]',
                'textarea[placeholder*="説明"]',
                'textarea',
                '[contenteditable="true"]',
            ]
            caption_entered = False
            for selector in caption_selectors:
                try:
                    element = post_page.locator(selector).first
                    if element.is_visible(timeout=5000):
                        element.click()
                        time.sleep(0.5)
                        element.fill(caption)
                        time.sleep(1)
                        print(f"[INFO] キャプション入力成功: {selector}")
                        caption_entered = True
                        break
                except Exception:
                    continue
            if not caption_entered:
                print("[WARN] キャプション入力欄が見つかりませんでした。")
                post_page.screenshot(path="/tmp/debug_no_caption.png")

            post_page.screenshot(path="/tmp/debug_before_submit.png")

            # Step 6: 「完了」ボタンをクリック
            print("[INFO] 「完了」ボタンをクリック中...")
            submit_selectors = [
                'button:has-text("完了")',
                'a:has-text("完了")',
                'input[value="完了"]',
                'button[type="submit"]',
                'button:has-text("投稿")',
                'button:has-text("シェア")',
                'input[type="submit"]',
            ]
            submitted = False
            for selector in submit_selectors:
                try:
                    element = post_page.locator(selector).first
                    if element.is_visible(timeout=5000):
                        element.click()
                        post_page.wait_for_load_state("domcontentloaded", timeout=60000)
                        time.sleep(3)
                        submitted = True
                        print(f"[INFO] 「完了」ボタンクリック成功: {selector}")
                        break
                except Exception:
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
