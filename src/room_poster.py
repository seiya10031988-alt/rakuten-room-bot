"""
room_poster.py
Playwrightを使って楽天Roomに自動ログイン・投稿するモジュール。
GitHub Actions環境（ヘッドレス）でも動作するように設計。
"""

import os
import time
import requests
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# 環境変数から認証情報を取得
RAKUTEN_EMAIL = os.environ.get("RAKUTEN_EMAIL", "")
RAKUTEN_PASSWORD = os.environ.get("RAKUTEN_PASSWORD", "")

# 楽天RoomのURL
RAKUTEN_LOGIN_URL = "https://grp01.id.rakuten.co.jp/rms/nid/login"
RAKUTEN_ROOM_URL = "https://room.rakuten.co.jp"


def download_image(url: str) -> str | None:
    """
    商品画像をダウンロードして一時ファイルパスを返す。
    """
    try:
        # 楽天の画像URLを高解像度版に変換
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


def post_to_rakuten_room(product_info: dict, caption: str) -> bool:
    """
    楽天Roomに商品を投稿する。
    product_info: format_product_info()で整形された商品情報
    caption: generate_caption()で生成されたキャプション
    戻り値: 投稿成功時True、失敗時False
    """
    image_path = None

    with sync_playwright() as p:
        # ヘッドレスブラウザ起動（GitHub Actions対応）
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        try:
            # ── Step 1: 楽天ログイン ──────────────────────────
            print("[INFO] 楽天にログイン中...")
            page.goto(RAKUTEN_LOGIN_URL, wait_until="networkidle", timeout=30000)
            time.sleep(1)

            # メールアドレス入力
            page.fill('input[name="u"]', RAKUTEN_EMAIL)
            time.sleep(0.5)
            # パスワード入力
            page.fill('input[name="p"]', RAKUTEN_PASSWORD)
            time.sleep(0.5)
            # ログインボタンクリック
            page.click('input[name="submit"]')
            page.wait_for_load_state("networkidle", timeout=30000)
            time.sleep(2)

            # ログイン確認
            if "login" in page.url.lower() or "error" in page.url.lower():
                print("[ERROR] ログインに失敗しました。メールアドレスとパスワードを確認してください。")
                return False
            print("[INFO] ログイン成功")

            # ── Step 2: 楽天Roomへ移動 ────────────────────────
            print("[INFO] 楽天Roomへ移動中...")
            page.goto(RAKUTEN_ROOM_URL, wait_until="networkidle", timeout=30000)
            time.sleep(2)

            # ── Step 3: 商品画像のダウンロード ────────────────
            image_url = product_info.get("image_url", "")
            if image_url:
                image_path = download_image(image_url)
                print(f"[INFO] 画像ダウンロード: {image_path}")

            # ── Step 4: 投稿ボタンをクリック ──────────────────
            print("[INFO] 投稿ボタンを探しています...")

            # 投稿ボタン（カメラアイコンまたは「投稿」ボタン）を探す
            post_button_selectors = [
                'a[href*="post"]',
                'button[class*="post"]',
                '[data-testid="post-button"]',
                'a[class*="post"]',
                '.post-button',
                'a[href*="/post/new"]',
            ]

            clicked = False
            for selector in post_button_selectors:
                try:
                    element = page.locator(selector).first
                    if element.is_visible(timeout=3000):
                        element.click()
                        clicked = True
                        print(f"[INFO] 投稿ボタンクリック成功: {selector}")
                        break
                except Exception:
                    continue

            if not clicked:
                # 直接投稿URLへ移動を試みる
                print("[INFO] 直接投稿URLへ移動を試みます...")
                page.goto(f"{RAKUTEN_ROOM_URL}/post/new", wait_until="networkidle", timeout=30000)
                time.sleep(2)

            # ── Step 5: 商品URLを入力 ─────────────────────────
            item_url = product_info.get("item_url", "")
            print(f"[INFO] 商品URL入力: {item_url}")

            url_input_selectors = [
                'input[placeholder*="URL"]',
                'input[placeholder*="url"]',
                'input[name*="url"]',
                'input[type="url"]',
                'input[placeholder*="商品"]',
            ]

            for selector in url_input_selectors:
                try:
                    element = page.locator(selector).first
                    if element.is_visible(timeout=3000):
                        element.fill(item_url)
                        time.sleep(1)
                        # Enterキーまたは「追加」ボタンを押す
                        element.press("Enter")
                        time.sleep(2)
                        print(f"[INFO] 商品URL入力成功: {selector}")
                        break
                except Exception:
                    continue

            # ── Step 6: キャプション（コメント）入力 ──────────
            print("[INFO] キャプション入力中...")
            caption_selectors = [
                'textarea[placeholder*="コメント"]',
                'textarea[placeholder*="テキスト"]',
                'textarea[name*="comment"]',
                'textarea[name*="caption"]',
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

            # ── Step 7: 投稿実行 ──────────────────────────────
            print("[INFO] 投稿を実行中...")
            submit_selectors = [
                'button[type="submit"]',
                'button:has-text("投稿")',
                'button:has-text("シェア")',
                'button:has-text("公開")',
                'input[type="submit"]',
                '[data-testid="submit"]',
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
                # スクリーンショットを保存（デバッグ用）
                page.screenshot(path="/tmp/debug_screenshot.png")
                print("[INFO] デバッグ用スクリーンショットを /tmp/debug_screenshot.png に保存しました。")
                return False

            # 投稿成功確認
            current_url = page.url
            print(f"[INFO] 投稿後URL: {current_url}")
            print("[INFO] 投稿が完了しました！")
            return True

        except PlaywrightTimeoutError as e:
            print(f"[ERROR] タイムアウトエラー: {e}")
            try:
                page.screenshot(path="/tmp/debug_timeout.png")
            except Exception:
                pass
            return False
        except Exception as e:
            print(f"[ERROR] 予期しないエラー: {e}")
            try:
                page.screenshot(path="/tmp/debug_error.png")
            except Exception:
                pass
            return False
        finally:
            # 一時ファイルの削除
            if image_path and Path(image_path).exists():
                Path(image_path).unlink()
            browser.close()


if __name__ == "__main__":
    # 動作確認用（実際の投稿は行わない）
    print("[INFO] room_poster.py の動作確認")
    print(f"[INFO] RAKUTEN_EMAIL: {'設定済み' if RAKUTEN_EMAIL else '未設定'}")
    print(f"[INFO] RAKUTEN_PASSWORD: {'設定済み' if RAKUTEN_PASSWORD else '未設定'}")
