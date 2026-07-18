import os
import re
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

def fetch_suborders(order_number: str) -> list[str]:
    """
    Авторизуется на сайте, загружает страницу заказа и возвращает 
    отсортированный список всех подзаказов для данного order_number.
    """
    load_dotenv()
    LOGIN_USER = os.environ.get("LOGIN_USER")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

    if not LOGIN_USER or not ADMIN_PASSWORD:
        raise ValueError("В .env не заданы LOGIN_USER или ADMIN_PASSWORD")

    # Формируем URL с Basic Auth и фильтром по orderid
    url = f"https://admin:{ADMIN_PASSWORD}@sborka.ua/adm/orders.php?type=all&datefrom=2026-06-17&datetill=2026-08-16&datefrom2=2026-06-17&datetill2=2026-08-16&client_id=&orderid={order_number}&manager=0&statuss=0&politics=0&pay=0&delivery=0&sborka_id=&button=ok"

    print(f"[{order_number}] Подключение к сайту и поиск подзаказов...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()
        page.set_default_timeout(30000)

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)

            # Если на сайте есть дополнительная форма логина
            if page.query_selector('input[name="pass_worker"]'):
                page.fill('input[name="pass_worker"]', LOGIN_USER)
                page.click('input[name="button"]')
                page.wait_for_load_state("domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)

            html_content = page.content()
            suborders = parse_suborders_from_html(html_content, order_number)
            return sorted(suborders)

        except Exception as e:
            print(f"❌ Ошибка во время загрузки страницы: {e}")
            return []
        finally:
            browser.close()


def parse_suborders_from_html(html_content: str, main_order_number: str) -> list[str]:
    soup = BeautifulSoup(html_content, "html.parser")
    suborders = []

    # Ищем основную таблицу заказов
    target_table = None
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all(["th", "td"])]
        if "заказчик" in headers and "тираж" in headers:
            target_table = table
            break

    if not target_table:
        print("❌ Таблица с заказами не найдена на странице.")
        return []

    rows = target_table.find_all("tr")

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 11:
            continue

        # Первая ячейка (индекс 0) содержит номер заказа и подзаказа: "25509673 (25509667)"
        order_num_raw = cells[0].get_text(strip=True)
        match = re.search(r"(\d+)\s*(?:\((\d+)\))?", order_num_raw)
        
        if match:
            sub_id = match.group(1) # Например, 25509673
            main_id = match.group(2) # Например, 25509667

            # Обязательно проверяем, что строка относится к искомому заказу
            # Либо main_id совпадает, либо это он и есть
            if main_id == main_order_number or sub_id == main_order_number:
                suborders.append(sub_id)

    # Убираем дубликаты на всякий случай
    return list(set(suborders))

if __name__ == "__main__":
    # Быстрый тест
    res = fetch_suborders("25509667")
    print("Найдены подзаказы:", res)
