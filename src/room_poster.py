"""
room_poster.py
クッキーを使って楽天Roomに自動ログイン・投稿するモジュール。

【正しい投稿フロー】
1. 楽天Roomにアクセスしてクッキーでログイン確認
2. 楽天市場の商品ページにアクセス
3. 「ROOMに投稿」ボタンのhrefからitemcodeを取得して投稿URLを構築
4. 投稿ページにアクセスしてAngularJSの初期化を待つ
5. JavaScriptでtextareaにキャプションを設定してAngularJSのng-modelを更新
6. JavaScriptで「完了」ボタンをクリック（disabled属性を除去してから）

【重要な知見】
- Playwrightの通常click()はdisabledな要素（ng-disabled含む）をクリックできない（Timeout 30000ms）
- textareaもボタンも「見つかっているがclickable/interactableでない」状態になる
- 解決策: すべての操作をJavaScript（page.evaluate）で直接行う
- AngularJSのng-modelを更新するには: valueを設定 → inputイベント発火 → changeイベント発火
- 「完了」ボタンクリック: disabled除去 → isCollectDisabled=false → JS click()
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

            # ── Step 3: 投稿URLを構築 ────────────────────────────
            # まず「ROOMに投稿」ボタンのhrefからitemcodeを取得する
            collect_url = None
            try:
                room_link = page.evaluate(
                    """() => {
                        const links = document.querySelectorAll('a');
                        for (const link of links) {
                            const href = link.href || '';
                            if (href.includes('mix/collect') || href.includes('mix?itemcode')) {
                                return href;
                            }
                            const text = link.textContent || '';
                            if (text.includes('ROOMに投稿') || text.includes('ROOM')) {
                                return href;
                            }
                        }
                        return null;
                    }"""
                )
                if room_link:
                    print(f"[INFO] 「ROOMに投稿」リンク発見: {room_link[:80]}")
                    collect_url = room_link
            except Exception as ex:
                print(f"[DEBUG] リンク取得失敗: {ex}")

            if not collect_url:
                # 直接URLを構築
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
                print(f"[WARN] 「ROOMに投稿」ボタンが見つかりませんでした。直接URLを構築します...")

            # /mix?itemcode= 形式の場合は /mix/collect?itemcode= に変換
            if "/mix?" in collect_url and "itemcode=" in collect_url:
                collect_url = collect_url.replace("/mix?", "/mix/collect?")
                print(f"[INFO] URLを変換: {collect_url[:80]}")

            print(f"[INFO] 投稿URLにアクセス: {collect_url[:80]}")

            # ── Step 4: 投稿ページにアクセス ────────────────────────
            post_page = context.new_page()
            post_page.goto(collect_url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(15)  # AngularJSの完全な初期化を待つ（十分な時間）
            print(f"[INFO] 投稿ページURL: {post_page.url}")
            post_page.screenshot(path="/tmp/debug_post_page.png")

            # AngularJSの初期化状態を確認
            angular_ready = post_page.evaluate(
                """() => {
                    try {
                        return typeof angular !== 'undefined' && angular.element(document.body).injector() !== null;
                    } catch(e) {
                        return false;
                    }
                }"""
            )
            print(f"[INFO] AngularJS初期化状態: {angular_ready}")

            # ── Step 5: JavaScriptでキャプションを入力 ──────────────
            # Playwrightのclick()は使わず、JSで直接操作する
            print("[INFO] JavaScriptでキャプションを入力中...")
            caption_escaped = caption.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
            caption_result = post_page.evaluate(
                f"""() => {{
                    try {{
                        // textareaを探す
                        const textarea = document.querySelector('#collect-content') ||
                                        document.querySelector('textarea[ng-model]') ||
                                        document.querySelector('textarea');
                        if (!textarea) return 'textarea not found';

                        // AngularJSのスコープを取得してng-modelを更新
                        const caption = `{caption_escaped}`;
                        try {{
                            const scope = angular.element(textarea).scope();
                            if (scope) {{
                                // ng-modelのパスを取得
                                const ngModel = textarea.getAttribute('ng-model') || '';
                                console.log('ng-model:', ngModel);

                                // $parentのcontentを設定
                                if (ngModel.includes('$parent.content')) {{
                                    scope.$parent.content = caption;
                                }} else {{
                                    scope.content = caption;
                                }}
                                scope.$apply();
                                console.log('AngularJS scope updated');
                            }}
                        }} catch(e) {{
                            console.log('AngularJS scope update failed: ' + e.message);
                        }}

                        // DOMのvalueも直接設定
                        textarea.value = caption;

                        // inputイベントを発火してAngularJSのng-modelを更新
                        const inputEvent = new Event('input', {{ bubbles: true }});
                        textarea.dispatchEvent(inputEvent);
                        const changeEvent = new Event('change', {{ bubbles: true }});
                        textarea.dispatchEvent(changeEvent);

                        return 'caption set: ' + caption.length + ' chars';
                    }} catch(e) {{
                        return 'error: ' + e.message;
                    }}
                }}"""
            )
            print(f"[INFO] キャプション入力結果: {caption_result}")

            time.sleep(2)
            post_page.screenshot(path="/tmp/debug_before_submit.png")

            # ── Step 6: JavaScriptで「完了」ボタンをクリック ──────────
            print("[INFO] JavaScriptで「完了」ボタンをクリック中...")
            click_result = post_page.evaluate(
                """() => {
                    try {
                        // 「完了」ボタンを探す
                        const btn = document.querySelector('button.collect-btn') ||
                                   document.querySelector('button[ng-click="collect()"]') ||
                                   document.querySelector('button.button-red');
                        if (!btn) return 'button not found';

                        console.log('Button found:', btn.outerHTML.substring(0, 200));

                        // disabled属性を除去
                        btn.removeAttribute('disabled');
                        btn.classList.remove('ng-disabled');

                        // AngularJSのスコープでisCollectDisabledをfalseに設定
                        try {
                            const scope = angular.element(btn).scope();
                            if (scope) {
                                console.log('isCollectDisabled before:', scope.isCollectDisabled);
                                console.log('isSubmitted before:', scope.isSubmitted);
                                scope.isCollectDisabled = false;
                                scope.isSubmitted = false;
                                scope.$apply();
                                console.log('AngularJS scope updated for button');
                            }
                        } catch(e) {
                            console.log('AngularJS scope update failed: ' + e.message);
                        }

                        // JavaScriptでクリックイベントを発火
                        const clickEvent = new MouseEvent('click', {
                            bubbles: true,
                            cancelable: true,
                            view: window
                        });
                        btn.dispatchEvent(clickEvent);

                        return 'button clicked: ' + btn.className;
                    } catch(e) {
                        return 'error: ' + e.message;
                    }
                }"""
            )
            print(f"[INFO] 「完了」ボタンクリック結果: {click_result}")

            if "clicked" in str(click_result):
                time.sleep(10)  # 投稿処理の完了を待つ
                post_page.screenshot(path="/tmp/debug_after_submit.png")
                final_url = post_page.url
                print(f"[INFO] 投稿後URL: {final_url}")
                print("[INFO] 投稿が完了しました！")
                browser.close()
                return True
            else:
                print(f"[ERROR] 「完了」ボタンのクリックに失敗しました: {click_result}")
                post_page.screenshot(path="/tmp/debug_click_failed.png")
                html_content = post_page.content()
                print(f"[DEBUG] ページHTML（先頭3000文字）: {html_content[:3000]}")
                browser.close()
                return False

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
