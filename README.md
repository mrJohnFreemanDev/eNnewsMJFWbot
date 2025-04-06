# 🌍 eNnewsMJFWbot

A Telegram bot that automatically gathers and posts news from major English-language RSS feeds such as The Guardian, NY Times, and Al Jazeera.

## 🧩 Features

- Fetches and processes full articles using Playwright
- Automatically posts to a specified Telegram channel
- Avoids duplicate posting with database tracking
- Periodic messages to engage channel audience
- Cleans up old database entries automatically
- Smart text cleanup and formatting

## 📡 News Sources

- https://www.theguardian.com/uk/rss
- https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml
- https://www.aljazeera.com/xml/rss/all.xml

## ⚙️ Tech Stack

- Python 3.10+
- Aiogram
- feedparser
- Playwright
- BeautifulSoup
- pymysql (MariaDB)
- dotenv
- Logging & error handling
- Regex-based article cleanup

## 🚀 Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/ENnewsMJFWbot.git
cd ENnewsMJFWbot
```

### 2. Create `.env` file

```env
TELEGRAM_API_TOKEN=your_telegram_token
TELEGRAM_CHANNEL_ID=@your_channel
```

### 3. Configure MySQL

Use a local or remote MariaDB/MySQL server with credentials like:

```env
host=localhost
user=root
password=
database=ENnewsMJFWbot
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
playwright install
```

### 5. Run the bot

```bash
python ENnewsMJFWbot.py
```

## 📬 Contact

- Telegram: [@Mr_John_Freeman_works](https://t.me/Mr_John_Freeman_works)
- Email: [mr.john.freeman.works.rus@gmail.com](mailto:mr.john.freeman.works.rus@gmail.com)

---

🌐 Created with care by Ivan Mudriakov — bringing headlines to your hands.
