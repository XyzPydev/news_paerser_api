# Архітектура та План Розробки: Low-Latency News Scraper (Репозиторій 1: Backend)

Цей документ описує архітектурне рішення, технологічний стек, принципи мінімізації затримки (latency) та етапи впровадження системи збору новин для трейдингу.

Зараз ми фокусуємося виключно на **Репозиторії 1: news-scraper-backend**, який розгортається безпосередньо в корені робочої папки. Створення бота відкладено на наступний етап.

---

## 1. Архітектурна Схема (System Architecture)

Для забезпечення мінімальної затримки архітектура розділена на **два паралельні контури** в межах бекенду:
1. **Гарячий контур (Hot Path - Raw News)**: Миттєва доставка сирих новин до клієнтів (WebSockets) за допомогою Redis Pub/Sub в обхід баз даних та важкого аналізу. Цільова затримка: `< 50ms`.
2. **Теплий контур (Warm Path - Enrichment & Storage)**: Асинхронна обробка новин за допомогою LLM (сентимент, сутності, переклад) та збереження в PostgreSQL. Цільова затримка: `1-3s`.

```mermaid
graph TD
    %% Source Ingestion
    subgraph Ingestion ["Фонові Воркери (Background Tasks)"]
        TG_Worker["Telegram Scraper (Telethon MTProto)"]
        TS_Worker["Truth Social Scraper (Mastodon/RSS)"]
    end

    %% Streaming & Broker
    subgraph Broker ["Шина Сообщень (Redis)"]
        Redis_PubSub["Redis Pub/Sub (Raw Streams)"]
        Redis_Queue["Redis Queue / Streams (Enrichment Queue)"]
    end

    %% Ingestion flow
    TG_Worker -->|Миттєва публікація| Redis_PubSub
    TS_Worker -->|Миттєва публікація| Redis_PubSub
    
    TG_Worker -->|В чергу обробки| Redis_Queue
    TS_Worker -->|В чергу обробки| Redis_Queue

    %% Backend & Gateway
    subgraph API_Gateway ["Бекенд (FastAPI Async - Репліки 1..N)"]
        FastAPI["FastAPI App (Uvicorn)"]
        WS_Server["WebSocket Manager (In-Memory Clients)"]
        FastAPI <--> WS_Server
    end

    Redis_PubSub -->|Real-time feed| FastAPI

    %% Clients (External for Backend)
    subgraph Consumers ["Споживачі (Clients)"]
        Trader_Client["Трейдинговий Термінал / Бот / WebSocket Client"]
    end

    WS_Server -->|Миттєве сповіщення (Raw)| Trader_Client

    %% Processing & Storage Layer
    subgraph Processing ["Слой Обробки та Зберігання"]
        Enrich_Worker["Enrichment Worker (Async Python)"]
        LLM_Service["Lightweight LLM (Ollama / Groq API)"]
        Postgres["PostgreSQL + TimescaleDB (Сховище)"]
    end

    Redis_Queue --> Enrich_Worker
    Enrich_Worker <-->|NLP / Sentiment / Entities| LLM_Service
    Enrich_Worker -->|Збереження структурованих новин| Postgres
    Enrich_Worker -->|Оновлений (Enriched) івент| Redis_PubSub
```

---

## 2. Технологічний Стек (Technology Stack)

| Компонент | Технологія | Обґрунтування для Low-Latency |
| :--- | :--- | :--- |
| **Менеджер пакетів** | `uv` | Найшвидший менеджер пакетів у Python-екосистемі. Використовуватиметься для керування віртуальним середовищем та швидкого кешування збірок. |
| **Контейнеризація**| `Docker & Compose` | Багатоетапний Dockerfile з використанням `uv` для бекенду. Docker Compose для підняття бази даних PostgreSQL, брокера Redis та самого FastAPI. |
| **Бекенд-фреймворк**| `FastAPI` (ASGI) | Асинхронний веб-фреймворк на базі Starlette. Обробка WebSockets з мінімальним overhead. |
| **Шина повідомлень** | `Redis` (Pub/Sub & Streams) | Наднадійна шина повідомлень в оперативній пам'яті для миттєвої маршрутизації даних. |
| **Клієнт Telegram**  | `Telethon` (MTProto) | Працює з бінарним протоколом Telegram напряму, що значно швидше, ніж опитування через Bot API. |
| **БД**               | `PostgreSQL` | Для збереження історії новин, аналітики, тегів та метаданих. |
| **LLM Інтеграція**   | `Groq API` / `Ollama` | Легке підключення локальної або віддаленої мовних моделей для сентимент-аналізу. |

---

## 3. Структура Директорій Бекенду (Layered Structure)

Проект будується за чистими шарами (Layers):

```
news_scraper/
├── app/
│   ├── common/            # Налаштування, логування, підключення до БД/Redis, утилити
│   │   ├── config.py
│   │   ├── database.py
│   │   └── redis.py
│   ├── repositories/      # Слой роботи з базою даних (CRUD, запити, транзакції)
│   │   ├── base.py
│   │   └── news.py
│   ├── services/          # Слой бізнес-логіки (воркери, збір даних, інтеграція з LLM)
│   │   ├── telegram_scraper.py
│   │   ├── truth_scraper.py
│   │   └── enrichment.py
│   └── main.py            # Точка входу в FastAPI та запуск фонових задач (lifespan)
├── Dockerfile             # Dockerfile на базі uv
├── docker-compose.yml     # Оркестрація локального оточення (App + Redis + DB)
├── pyproject.toml         # Залежності проекту
└── .env.example           # Зразок конфігураційного файлу
```

---

## 4. Оптимізація Навантаження на API (Load Optimization & Scaling)

Для уникнення перевантаження бекенду (FastAPI) під час високої частоти новин та великої кількості WebSocket-клієнтів, впроваджуються наступні архітектурні рішення:

### A. Горизонтальне Масштабування за допомогою Redis Pub/Sub (State-free Backend)
* **Проблема**: WebSocket-з'єднання тримають постійний стейт. Один сервер FastAPI може перевантажитись по CPU/RAM при обслуговуванні тисяч підключень.
* **Рішення**:
  - Запускається кілька реплік FastAPI за балансувальником навантаження (Nginx / HAProxy / Traefik).
  - **Кожна репліка** підписується на той самий Redis Pub/Sub канал (`raw_news_stream`).
  - Коли воркер публікує новину в Redis, Redis миттєво доставляє її до всіх реплік FastAPI. Кожна репліка розсилає новину своїм локально підключеним WebSocket-клієнтам.
  - Це дозволяє масштабувати бекенд безкінечно, просто додаючи нові контейнери FastAPI.

### B. Кешування Останніх Новин в Redis (In-Memory Read Cache)
* **Проблема**: Клієнти, що щойно підключились, або мобільні додатки будуть робити GET-запити для отримання останніх 50-100 новин. Робити прямі запити до PostgreSQL на кожен такий запит при великому навантаженні — неефективно (Postgres ляже від IOPS).
* **Рішення**:
  - При отриманні новини воркер (або Enrichment Worker) не лише пише її в Postgres, але й зберігає в Redis-список (Redis List) фіксованої довжини (наприклад, останні 200 новин за допомогою команди `LTRIM`).
  - Коли клієнт запитує список останніх новин через HTTP GET, FastAPI дістає ці дані безпосередньо з оперативної пам'яті Redis (команда `LRANGE`), обминаючи PostgreSQL.
  - Швидкість відповіді на такі GET-запити становить `< 2ms`.

### C. Неблокуючий Асинхронний Fan-out для WebSockets
* **Проблема**: Якщо робити розсилку повідомлень клієнтам у простому циклі `for client in clients: await client.send_text()`, повільний клієнт (з поганим інтернет-з'єднанням) заблокує або сповільнить розсилку іншим швидким клієнтам.
* **Рішення**:
  - Використовується оптимізований `ConnectionManager`, який запускає відправку повідомлень асинхронно через `asyncio.create_task` або `asyncio.gather(..., return_exceptions=True)`.
  - У випадку помилки тайм-ауту або відключення клієнта, його з'єднання миттєво закривається та видаляється з реєстру, щоб не витрачати ресурси CPU на наступні ітерації.

### D. Використання Швидких Серіалізаторів (Fast JSON Parsing)
* **Проблема**: Стандартний `json` модуль Python є повільним при високій частоті повідомлень.
* **Рішення**:
  - Увесь JSON-парсинг та серіалізація на рівні FastAPI та Redis клієнта виконуються за допомогою бібліотеки **`orjson`** або **`ujson`** (написані на Rust/C), що в 5-10 разів швидше за стандартний `json`.

---

## 5. План Покрокової Реалізації (Implementation Roadmap)

### Етап 1: Конфігурація та Docker-Scaffolding (Поточний крок)
- [ ] Ініціалізувати `pyproject.toml` за допомогою `uv init`.
- [ ] Створити `docker-compose.yml` та `Dockerfile`.
- [ ] Створити структуру директорій `app/common`, `app/repositories`, `app/services` та файл `app/main.py`.
- [ ] Написати `.env.example`.
- [ ] Запустити збірку та перевірити локальний запуск контейнерів.

### Етап 2: Реалізація Гарячого Контуру (Hot Path)
- [ ] Налаштування клієнтів Redis та бази даних.
- [ ] Створення скелета Telegram та Truth Social воркерів.
- [ ] Реалізація WebSockets для транслювання новин.

### Етап 3: Обробка та Збереження (Warm Path)
- [ ] Реалізація сентимент-аналізу через LLM.
- [ ] Створення моделей бази даних та репозиторіїв для збереження результатів.
