import os
import logging
import pymysql
from pymysql.cursors import DictCursor
from datetime import datetime, timedelta
import pytz
import feedparser
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from aiogram import Bot
from asyncio import sleep, gather, create_task
from dotenv import load_dotenv
import re

# Загрузка токенов из файла .env
load_dotenv("all.env")

TELEGRAM_API_TOKEN = os.getenv('TELEGRAM_API_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')

if not TELEGRAM_API_TOKEN:
    raise ValueError("Отсутствует TELEGRAM_API_TOKEN в файле .env")

# Инициализация бота
bot = Bot(token=TELEGRAM_API_TOKEN)

# Локальная временная зона
LOCAL_TIMEZONE = pytz.timezone('Europe/Moscow')

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)

# RSS источники с задержками публикаций
RSS_SOURCES = [
    {"url": "https://www.theguardian.com/uk/rss", "source": "www.theguardian.com", "delay": 300}, #5 min
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml", "source": "www.nytimes.com", "delay": 600}, #10 min
    {"url": "https://www.aljazeera.com/xml/rss/all.xml", "source": "www.aljazeera.com", "delay": 900} #15 min
]

# Настройки подключения к базе данных
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",  # Укажите пароль
    "database": "ENnewsMJFWbot",
    "charset": "utf8mb4",
    "cursorclass": DictCursor
}

# Срок хранения записей в днях
RECORD_RETENTION_DAYS = 30

def get_db_connection():
    """Устанавливает соединение с базой данных."""
    try:
        return pymysql.connect(**DB_CONFIG)
    except pymysql.MySQLError as err:
        logging.error(f"Ошибка подключения к базе данных: {err}")
        raise

def initialize_db():
    """Создаёт таблицу для учёта опубликованных статей, если её нет."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS published_articles (
                id INT AUTO_INCREMENT PRIMARY KEY,
                link VARCHAR(1024) NOT NULL UNIQUE,
                title VARCHAR(512),
                source VARCHAR(256),
                content TEXT,
                html TEXT,
                publication_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                posted BOOLEAN DEFAULT FALSE
            )
            '''
        )
        conn.commit()
        logging.info("База данных и таблица опубликованных статей готовы.")
    except pymysql.MySQLError as e:
        logging.error(f"Ошибка создания таблицы: {e}")
    finally:
        conn.close()

def check_and_repair_table():
    """Проверяет и восстанавливает таблицу, если она повреждена."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("CHECK TABLE published_articles")
        repair_result = cursor.fetchall()
        for row in repair_result:
            if row['Msg_text'] != 'OK':
                logging.warning(f"Необходим ремонт таблицы: {row}")
                cursor.execute("REPAIR TABLE published_articles")
                logging.info("Таблица восстановлена.")
    except pymysql.MySQLError as e:
        logging.error(f"Ошибка проверки или восстановления таблицы: {e}")
    finally:
        conn.close()

def reset_auto_increment():
    """Сбрасывает значение AUTO_INCREMENT, если необходимо."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE published_articles AUTO_INCREMENT = 1")
        conn.commit()
        logging.info("Значение AUTO_INCREMENT успешно сброшено.")
    except pymysql.MySQLError as e:
        logging.error(f"Ошибка сброса AUTO_INCREMENT: {e}")
    finally:
        conn.close()

def clean_article_text(raw_text):
    """
    Форматирует и очищает текст статьи от лишнего хлама.

    :param raw_text: Исходный текст статьи.
    :return: Очищенный и отформатированный текст.
    """
    text = re.sub(r'\s+', ' ', raw_text)  # Замена любых пробелов на один
    text = re.sub(r'\n+', '\n', text.strip())  # Удаление лишних переносов строк
    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'<.*?>', '', text)
    text = re.sub(r'(?i)<script.*?>.*?</script>', '', text, flags=re.DOTALL)
    text = re.sub(r'(?i)<style.*?>.*?</style>', '', text, flags=re.DOTALL)

    keywords_to_remove = [
        "Privacy Policy",
        "protected by reCAPTCHA",
        "Terms of Service",
        "Read More",
        "Click here",
        "Advertisement",
        "Subscribe now"
    ]
    for keyword in keywords_to_remove:
        text = text.replace(keyword, '')

    text = re.sub(r'https?://\S+|www\.\S+', '', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'[.]{2,}', '.', text)
    text = re.sub(r'[-=~_*#]{3,}', '', text)

    return text.strip()

def clear_old_records():
    """Удаляет устаревшие записи из базы данных."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        threshold_date = datetime.now() - timedelta(days=RECORD_RETENTION_DAYS)
        cursor.execute("DELETE FROM published_articles WHERE publication_date < %s", (threshold_date,))
        conn.commit()
        logging.info(f"Удалены записи старше {RECORD_RETENTION_DAYS} дней.")
    except pymysql.MySQLError as e:
        logging.error(f"Ошибка при удалении устаревших записей: {e}")
    finally:
        conn.close()

async def fetch_full_article_with_playwright(article_url):
    """Загружает полный текст статьи и HTML через Playwright."""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(article_url, timeout=60000, wait_until="domcontentloaded")

            # Увеличение времени ожидания
            try:
                await page.wait_for_selector('div.content__article-body, article, div.wysiwyg, div.article-content', timeout=20000)
            except Exception as e:
                logging.warning(f"Селектор для статьи не найден на странице {article_url}: {e}")

            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, 'html.parser')

        # Основной и дополнительные селекторы для Al Jazeera
        selectors = ['div.content__article-body', 'article', 'div.article-content', 'div.body-content', 'div.wysiwyg']
        for selector in selectors:
            content = soup.select_one(selector)
            if content:
                text = clean_article_text(content.get_text(separator="\n", strip=True))
                return content.prettify(), text, html

        # Если контент не найден, возвращаем общий текст страницы
        for tag in soup(["script", "style", "aside", "footer"]):
            tag.decompose()
        clean_text = clean_article_text(soup.get_text(separator="\n", strip=True))
        return None, clean_text[:3072], html

    except Exception as e:
        logging.error(f"Ошибка при загрузке статьи {article_url}: {e}")
        return None, "", None

def is_article_published(link):
    """Проверяет, была ли статья уже опубликована."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT posted FROM published_articles WHERE link = %s", (link,))
        result = cursor.fetchone()
        return result and result['posted']
    finally:
        conn.close()

def mark_article_as_published(link):
    """Обновляет статус статьи на опубликованную."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE published_articles SET posted = TRUE WHERE link = %s", (link,))
        conn.commit()
    except pymysql.MySQLError as e:
        logging.error(f"Ошибка при обновлении статуса статьи: {e}")
    finally:
        conn.close()

def add_article_to_db(link, title, source, content, html=None):
    """Добавляет статью в таблицу опубликованных."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT IGNORE INTO published_articles (link, title, source, content, html) VALUES (%s, %s, %s, %s, %s)",
            (link, title, source, content, html)
        )
        conn.commit()
    except pymysql.MySQLError as e:
        logging.error(f"Ошибка при добавлении статьи в базу данных: {e.args}")
    finally:
        conn.close()

async def process_rss_feed(rss_feed):
    """Обрабатывает отдельный RSS-канал."""
    while True:
        try:
            feed = feedparser.parse(rss_feed["url"])
            for entry in feed.entries:
                if not is_article_published(entry.link):
                    html, full_text, raw_html = await fetch_full_article_with_playwright(entry.link)
                    if full_text or raw_html:
                        add_article_to_db(entry.link, entry.title, rss_feed["source"], full_text or "HTML контент сохранён", raw_html)
                        header = f"<b><u>{entry.title}</u></b>\n"
                        source_info = f"<i>Source: {rss_feed['source']}</i>\n"
                        footer = f"\n<a href=\"{entry.link}\">Read in full on the website</a>"
                        truncated_content = (full_text or "HTML контент сохранён")[:3072]
                        message = f"{header}{source_info}\n{truncated_content}{footer}"

                        await bot.send_message(
                            chat_id=TELEGRAM_CHANNEL_ID,
                            text=message,
                            parse_mode="HTML"
                        )
                        logging.info(f"Опубликована статья: {entry.title}")
                        mark_article_as_published(entry.link)
                        break

            await sleep(rss_feed["delay"])
        except Exception as e:
            logging.error(f"Ошибка при обработке RSS {rss_feed['source']}: {e}")

async def periodic_notification():
    """Отправляет сообщение в канал каждые 30 минут."""
    while True:
        try:
            message = (
                "<b>Welcome!</b>\n"
                "<i>This channel was created to introduce the capabilities of the Telegram bot</i> - <b>News MJFW Bot</b>.\n"
                "<i>You can contact the developer at:</i> "
                "<a href=\"https://www.mjfw.ru/\">mjfw.ru</a>."
            )
            await bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=message,
                parse_mode="HTML"
            )
            logging.info("Периодическое сообщение отправлено в канал.")
        except Exception as e:
            logging.error(f"Ошибка при отправке периодического сообщения: {e}")
        await sleep(1800)  # Задержка в 30 минут

async def main():
    """Основная функция запуска обработки."""
    try:
        initialize_db()
        check_and_repair_table()
        reset_auto_increment()
        clear_old_records()

        tasks = [process_rss_feed(feed) for feed in RSS_SOURCES]
        tasks.append(periodic_notification())
        await gather(*tasks)
    except Exception as e:
        logging.error(f"Ошибка в основном процессе: {e}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
