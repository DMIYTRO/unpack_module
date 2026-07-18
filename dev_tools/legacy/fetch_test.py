import os
import sys
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

# Загружаем переменные из старого проекта
load_dotenv('/Users/admin/Documents/test_orders/.env')
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
LOGIN_USER = os.environ.get("LOGIN_USER")

if not ADMIN_PASSWORD or not LOGIN_USER:
    print("Error: Credentials not found in .env")
    sys.exit(1)

url = f"https://admin:{ADMIN_PASSWORD}@sborka.ua/adm/orders.php?type=all&datefrom=2026-06-17&datetill=2026-08-16&datefrom2=2026-06-17&datetill2=2026-08-16&client_id=&orderid=25509667&manager=0&statuss=0&politics=0&pay=0&delivery=0&sborka_id=&button=ok"

print("Starting playwright to fetch the page...")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    page.goto(url)
    
    # Авторизация, если есть форма
    if page.query_selector('input[name="pass_worker"]'):
        print("Filling login form...")
        page.fill('input[name="pass_worker"]', LOGIN_USER)
        page.click('input[name="button"]')
        page.wait_for_load_state("domcontentloaded")
        page.goto(url)
        
    print("Page fetched, saving to page_25509667.html")
    with open('page_25509667.html', 'w', encoding='utf-8') as f:
        f.write(page.content())
    browser.close()
