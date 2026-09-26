# Використовуємо легкий базовий образ Python
FROM python:3.13-slim

# Встановлюємо робочу директорію
WORKDIR /app

# Оновлюємо системні пакунки та встановлюємо tzdata для київського часу
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Встановлюємо часовий пояс України
ENV TZ=Europe/Kyiv

# Копіюємо файл залежностей
COPY requirements.txt .

# Встановлюємо Python-бібліотеки
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо решту файлів проекту
COPY . .

# Створюємо директорію під базу даних
RUN mkdir -p data

# Запускаємо бота
CMD ["python", "bot.py"]
