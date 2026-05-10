"""
room_poster.py
クッキーを使って楽天Roomに自動ログイン・投稿するモジュール。

【修正履歴】
- v8: Playwrightのdialogイベントで「要求されたURL存在しません」を確実に検知
      「完了」ボタンクリック後にダイアログが出た場合はurl_not_foundを返す
      vanilla-vagueなど投稿不可ショップのブラックリストを追加
"""
import os
import json
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

RAKUTEN_COOKIES_JSON = os.environ.get("RAKUTEN_COOKIES", "")
RAKUTEN_ROOM_URL = "https://room.rakuten.co.jp"

# 楽天ROOMに投稿できないショップコードのブラックリスト
BLACKLISTED_SHOPS = [
    "vanilla-vague",  # 「要求されたURL存在しません」エラーが発生するショップ
    "ferry",          # 不正なitemcode（ferry:10000000）を返すショップ
]


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


def is_blacklisted_shop(item_code_full: str) -> bool:
    """ショップコードがブラックリストに含まれているか確認する。"""
    if not item_code_full or ":" not in item_code_full:
        return False
    shop_code = item_code_full.split(":")[0]
    return shop_code in BLACKLISTED_SHOPS


def post_to_rakuten_room(product_info: dict, caption: str):
    """
    楽天ROOMに商品を投稿する。
    戻り値:
      True: 投稿成功
      "url_not_found": 商品がROOMに投稿できない（別商品で再試行すべき）
      False: その他の失敗
    """
    item_code_full = product_info.get("item_code_full", "")

    # ブラックリストチェック
    if is_blacklisted_shop(item_code_full):
        print(f"[WARN] ブラックリストのショップのためスキップ: {item_code_full}")
        return "url_not_found"

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

        # ダイアログ（アラート）を自動的に閉じ、内容を記録する
        dialog_messages = []

        def handle_dialog(dialog):
            msg = dialog.message
            dialog_messages.append(msg)
            print(f"[INFO] ダイアログ検知: {msg}")
            dialog.accept()

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

                        # ダイアログハンドラを設定
                        post_page.on("dialog", handle_dialog)
                        time.sleep(1)  # ダイアログが出るのを待つ

                        # 403チェック
                        content = post_page.content()
                        if "403 Forbidden" in content or "認証が失敗しました" in content:
                            print("[ERROR] 403 Forbidden - クッキーを更新してください。")
                            post_page.screenshot(path="/tmp/debug_403.png")
                            browser.close()
                            return False

                        # ダイアログで「要求されたURL存在しません」が出た場合
                        if any("要求されたURL" in m or "存在しません" in m for m in dialog_messages):
                            print("[WARN] 「要求されたURL存在しません」ダイアログ検知 - この商品はROOMに投稿できません。")
                            post_page.screenshot(path="/tmp/debug_url_not_found.png")
                            browser.close()
                            return "url_not_found"

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
                if item_code_full:
                    collect_url = f"https://room.rakuten.co.jp/mix/collect?itemcode={item_code_full}&scid=we_room_upc60"
                else:
                    shop_code = product_info.get("shop_code", "")
                    item_code = product_info.get("item_code", "")
                    if shop_code and item_code:
                        collect_url = f"https://room.rakuten.co.jp/mix/collect?itemcode={shop_code}:{item_code}&scid=we_room_upc60"
                    else:
                        print("[ERROR] itemcodeが取得できませんでした。")
                        browser.close()
                        return False

                print(f"[INFO] 投稿URLに直接アクセス: {collect_url}")
                post_page = context.new_page()
                # ダイアログハンドラを先に設定
                post_page.on("dialog", handle_dialog)
                post_page.goto(collect_url, wait_until="domcontentloaded", timeout=60000)
                time.sleep(5)  # ダイアログが出るのを十分待つ
                print(f"[INFO] 投稿ページURL: {post_page.url}")

                # ダイアログで「要求されたURL存在しません」が出た場合
                if any("要求されたURL" in m or "存在しません" in m for m in dialog_messages):
                    print("[WARN] 「要求されたURL存在しません」ダイアログ検知 - この商品はROOMに投稿できません。")
                    post_page.screenshot(path="/tmp/debug_url_not_found.png")
                    browser.close()
                    return "url_not_found"

                # 403チェック
                content = post_page.content()
                if "403 Forbidden" in content or "認証が失敗しました" in content:
                    print("[ERROR] 403 Forbidden - クッキーを更新してください。")
                    post_page.screenshot(path="/tmp/debug_403.png")
                    browser.close()
                    return False

            # 投稿前のURLを記録
            url_before_submit = post_page.url
            dialog_messages.clear()  # ダイアログ履歴をリセット

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
                        time.sleep(5)  # ダイアログが出るのを十分待つ
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

            # 「完了」クリック後のダイアログチェック
            if any("要求されたURL" in m or "存在しません" in m for m in dialog_messages):
                print("[WARN] 「完了」クリック後に「要求されたURL存在しません」ダイアログ検知")
                print("[WARN] この商品はROOMに投稿できません。別の商品で再試行します。")
                post_page.screenshot(path="/tmp/debug_url_not_found_after_submit.png")
                browser.close()
                return "url_not_found"

            post_page.screenshot(path="/tmp/debug_after_submit.png")
            url_after_submit = post_page.url
            print(f"[INFO] 投稿後URL: {url_after_submit}")

            # 投稿後のURLが変わったか確認
            if url_after_submit == url_before_submit:
                print("[WARN] 投稿後のURLが変わっていません。")
                # ページ内容を確認
                try:
                    content = post_page.content()
                    if "コレ！して投稿する" in content:
                        print("[WARN] まだ投稿フォームが表示されています。投稿が完了していません。")
                        browser.close()
                        return "url_not_found"
                    title = post_page.title()
                    print(f"[INFO] ページタイトル: {title}")
                except Exception:
                    pass

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
