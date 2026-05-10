"""
room_poster.py
クッキーを使って楽天Roomに自動ログイン・投稿するモジュール。
【正しい投稿フロー】
1. 楽天市場の商品ページにアクセス
2. 「ROOMに投稿」ボタンをクリック（新しいタブで投稿ページが開く）
3. テキストエリアにキャプションを入力
4. 「完了」ボタンをクリック

【修正履歴】
- v6: 403エラーと「要求されたURL存在しません」の検知処理を追加
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


def check_page_error(page) -> str:
    """
    ページにエラーが表示されているか確認する。
    エラーの種類を返す。エラーなしの場合は空文字を返す。
    """
    try:
        content = page.content()
        if "403 Forbidden" in content or "認証が失敗しました" in content:
            return "403_forbidden"
        if "要求されたURL存在しません" in content:
            return "url_not_found"
        if "ページが見つかりません" in content or "404" in content:
            return "404_not_found"
    except Exception:
        pass
    return ""


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

            # Step 3: 「ROOMに投稿」ボタンをクリック
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
                        with context.expect_page() as new_page_info:
                            element.click()
                        post_page = new_page_info.value
                        post_page.wait_for_load_state("domcontentloaded", timeout=60000)
                        time.sleep(3)

                        # 新しいページのエラーチェック
                        page_error = check_page_error(post_page)
                        if page_error == "403_forbidden":
                            print("[ERROR] 403 Forbidden - クッキーを更新してください。")
                            post_page.screenshot(path="/tmp/debug_403.png")
                            browser.close()
                            return False
                        elif page_error == "url_not_found":
                            print("[WARN] 「要求されたURL存在しません」- 商品が存在しないか投稿不可です。")
                            post_page.screenshot(path="/tmp/debug_url_not_found.png")
                            # 投稿フォームが表示されているか確認（ダイアログが出ても続行できる場合がある）
                            try:
                                # OKボタンがあればクリックして続行
                                ok_btn = post_page.locator('button:has-text("OK"), input[value="OK"]').first
                                if ok_btn.is_visible(timeout=3000):
                                    ok_btn.click()
                                    time.sleep(1)
                                    print("[INFO] OKボタンをクリックして続行")
                            except Exception:
                                pass

                        room_button_found = True
                        print(f"[INFO] 投稿ページが開きました: {post_page.url}")
                        break
                except Exception as ex:
                    print(f"[DEBUG] セレクタ {selector} 失敗: {ex}")
                    continue

            if not room_button_found:
                # 直接URLを構築してアクセス
                print("[WARN] 「ROOMに投稿」ボタンが見つかりませんでした。直接URLを構築します...")
                page.screenshot(path="/tmp/debug_no_room_button.png")
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
                print(f"[INFO] 投稿URLに直接アクセス: {collect_url}")
                post_page = context.new_page()
                post_page.goto(collect_url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(3)
                print(f"[INFO] 投稿ページURL: {post_page.url}")

                # 直接アクセス時のエラーチェック
                page_error = check_page_error(post_page)
                if page_error == "403_forbidden":
                    print("[ERROR] 403 Forbidden - クッキーを更新してください。")
                    post_page.screenshot(path="/tmp/debug_403.png")
                    browser.close()
                    return False
                elif page_error == "url_not_found":
                    print("[WARN] 「要求されたURL存在しません」- 商品が存在しないか投稿不可です。")
                    post_page.screenshot(path="/tmp/debug_url_not_found.png")
                    # OKボタンがあればクリック
                    try:
                        ok_btn = post_page.locator('button:has-text("OK"), input[value="OK"]').first
                        if ok_btn.is_visible(timeout=3000):
                            ok_btn.click()
                            time.sleep(1)
                            print("[INFO] OKボタンをクリックして続行")
                    except Exception:
                        pass

            # Step 4: キャプション入力
            print("[INFO] キャプション入力中...")
            post_page.screenshot(path="/tmp/debug_post_page.png")
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

            # Step 5: 「完了」ボタンをクリック
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
