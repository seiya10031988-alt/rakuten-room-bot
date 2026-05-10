"""
room_poster.py v10
クッキーを使って楽天Roomに自動ログイン・投稿するモジュール。

【修正履歴】
- v10: 楽天市場商品ページのHTMLから「ROOMに投稿」リンクのhref（数字itemcode）を取得する方式に変更
       networkidleまで待機してからHTMLを解析
       数字形式のitemcodeを使うことで商品画像が正常に表示され投稿が成功する
"""
import os
import json
import time
import re
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


def get_room_collect_url_from_item_page(page, item_url: str) -> str:
    """
    楽天市場の商品ページにアクセスし、「ROOMに投稿」ボタンのhrefから
    数字形式のitemcodeを含むROOM投稿URLを取得する。
    
    Returns:
        str: ROOMの投稿URL（例: https://room.rakuten.co.jp/mix/collect?itemcode=1100052541980281&scid=we_room_upc60）
        None: 取得失敗
    """
    print(f"[INFO] 商品ページにアクセス中: {item_url[:80]}...")
    
    try:
        # networkidleまで待機してJavaScriptを完全に実行させる
        page.goto(item_url, wait_until="networkidle", timeout=60000)
    except Exception:
        # networkidleがタイムアウトしても続行
        try:
            page.goto(item_url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(5)  # JSの実行を待つ
        except Exception as e:
            print(f"[ERROR] 商品ページのアクセスに失敗: {e}")
            return None
    
    page.screenshot(path="/tmp/debug_item_page.png")
    print(f"[INFO] 商品ページURL: {page.url}")
    
    # HTMLからROOM投稿URLを抽出
    html = page.content()
    
    # パターン1: href属性から直接取得
    patterns = [
        r'href="(https://room\.rakuten\.co\.jp/mix/collect\?itemcode=[^"&]+[^"]*)"',
        r"href='(https://room\.rakuten\.co\.jp/mix/collect\?itemcode=[^'&]+[^']*)'",
        r'(https://room\.rakuten\.co\.jp/mix/collect\?itemcode=\d+[^"\'&\s]*)',
        r'"(//room\.rakuten\.co\.jp/mix/collect\?itemcode=[^"]+)"',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, html)
        if matches:
            url = matches[0]
            if url.startswith("//"):
                url = "https:" + url
            # scidパラメータがない場合は追加
            if "scid=" not in url:
                url += "&scid=we_room_upc60"
            print(f"[INFO] ROOMの投稿URL取得成功: {url}")
            return url
    
    # パターン2: JavaScriptでリンクを探す
    try:
        room_links = page.evaluate("""
            () => {
                const links = Array.from(document.querySelectorAll('a[href*="room.rakuten.co.jp/mix/collect"]'));
                return links.map(l => l.href);
            }
        """)
        if room_links:
            url = room_links[0]
            if "scid=" not in url:
                url += "&scid=we_room_upc60"
            print(f"[INFO] JS経由でROOMの投稿URL取得成功: {url}")
            return url
    except Exception as e:
        print(f"[DEBUG] JS経由の取得失敗: {e}")
    
    # パターン3: 「ROOMに投稿」テキストを含むリンクを探す
    try:
        room_link = page.locator('a:has-text("ROOMに投稿")').first
        if room_link.is_visible(timeout=3000):
            href = room_link.get_attribute("href")
            if href:
                if href.startswith("//"):
                    href = "https:" + href
                if "scid=" not in href:
                    href += "&scid=we_room_upc60"
                print(f"[INFO] テキスト検索でROOMの投稿URL取得成功: {href}")
                return href
    except Exception as e:
        print(f"[DEBUG] テキスト検索失敗: {e}")
    
    print("[WARN] ROOMの投稿URLが見つかりませんでした。")
    return None


def post_to_rakuten_room(product_info: dict, caption: str):
    """
    楽天ROOMに商品を投稿する。
    戻り値:
      True: 投稿成功
      "url_not_found": 商品がROOMに投稿できない（別商品で再試行すべき）
      False: その他の失敗
    """
    item_code_full = product_info.get("item_code_full", "")
    item_url = product_info.get("item_url", "")

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

            # Step 2: 楽天市場の商品ページから数字形式のitemcodeを取得
            collect_url = None
            if item_url:
                collect_url = get_room_collect_url_from_item_page(page, item_url)
            
            # フォールバック: shop_code:item_code形式でURLを構築
            if not collect_url:
                print("[WARN] 商品ページからROOM URLが取得できませんでした。フォールバック...")
                if item_code_full:
                    collect_url = f"https://room.rakuten.co.jp/mix/collect?itemcode={item_code_full}&scid=we_room_upc60"
                    print(f"[WARN] フォールバックURL: {collect_url}")
                else:
                    print("[ERROR] itemcodeが取得できませんでした。")
                    browser.close()
                    return False

            # Step 3: ROOMの投稿ページにアクセス
            print(f"[INFO] ROOMの投稿ページにアクセス: {collect_url}")
            post_page = context.new_page()
            # ダイアログハンドラを先に設定
            post_page.on("dialog", handle_dialog)
            post_page.goto(collect_url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(5)  # AngularJSの初期化とダイアログが出るのを待つ
            
            post_page.screenshot(path="/tmp/debug_post_page.png")
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

            # 商品画像が表示されているか確認（img要素が存在するか）
            try:
                img_count = post_page.evaluate("() => document.querySelectorAll('.collect-item-image img, .item-image img, img[src*=\"thumbnail\"], img[src*=\"item\"]').length")
                print(f"[INFO] 商品画像数: {img_count}")
                if img_count == 0:
                    # より広いセレクタで確認
                    all_imgs = post_page.evaluate("() => document.querySelectorAll('img').length")
                    print(f"[INFO] ページ内の全img数: {all_imgs}")
            except Exception:
                pass

            # 投稿前のURLを記録
            url_before_submit = post_page.url
            dialog_messages.clear()  # ダイアログ履歴をリセット

            # Step 4: キャプション入力
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

            # 投稿後のURLが変わったか確認（変わっていなければ投稿失敗）
            if url_after_submit == url_before_submit:
                print("[WARN] 投稿後のURLが変わっていません。投稿が完了していません。")
                try:
                    title = post_page.title()
                    print(f"[INFO] ページタイトル: {title}")
                    post_page.screenshot(path="/tmp/debug_url_unchanged.png")
                except Exception:
                    pass
                browser.close()
                return "url_not_found"

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
