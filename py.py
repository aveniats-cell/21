import os
import sys
import requests
from llama_cpp import Llama

# --- 1. Настройки ---
MODEL_URL = "https://huggingface.co/unsloth/gemma-3-270m-it-GGUF/resolve/main/gemma-3-270m-it-Q8_0.gguf?download=true"
MODEL_PATH = "gemma-3-270m-it-Q8_0.gguf"

# --- 2. Скачивание модели (с докачкой) ---
def download_model(url, path):
    if os.path.exists(path):
        print(f"Файл уже существует: {path}")
        return

    print("Начинаю скачивание модели...")
    # Используем stream=True для больших файлов [citation:1][citation:5]
    response = requests.get(url, stream=True, timeout=30)
    response.raise_for_status()

    total_size = int(response.headers.get('content-length', 0))
    downloaded = 0

    with open(path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    percent = (downloaded / total_size) * 100
                    # Простой прогресс-бар в одной строке
                    sys.stdout.write(f"\rСкачано: {percent:.1f}% ({downloaded / 1024 / 1024:.1f} MB)")
                    sys.stdout.flush()
    print("\nСкачивание завершено.")

# --- 3. Запуск интерактивного чата ---
def main():
    # Скачиваем, если файла нет
    download_model(MODEL_URL, MODEL_PATH)

    print("Загрузка модели в память...")
    # Инициализация Llama. n_ctx=4096 достаточно для чата [citation:14]
    llm = Llama(
        model_path=MODEL_PATH,
        n_ctx=4096,
        n_threads=os.cpu_count() or 4,
        verbose=False
    )

    print("Чат готов. Введите 'exit' или 'quit' для выхода.\n")
    print("-" * 40)

    # История сообщений для сохранения контекста
    messages = [
        {"role": "system", "content": "Ты — полезный ассистент. Отвечай кратко и по делу."}
    ]

    while True:
        try:
            user_input = input("Вы: ")
        except (EOFError, KeyboardInterrupt):
            print("\nВыход.")
            break

        if user_input.lower() in ["exit", "quit", "выход"]:
            print("Пока!")
            break

        if not user_input.strip():
            continue

        # Добавляем сообщение пользователя в историю
        messages.append({"role": "user", "content": user_input})

        # Генерируем ответ
        response = llm.create_chat_completion(
            messages=messages,
            max_tokens=512,
            temperature=0.7,
            stop=["<end_of_turn>", "<eos>"]  # Стандартные стоп-токены для Gemma
        )

        reply = response["choices"][0]["message"]["content"].strip()
        print(f"Бот: {reply}\n")

        # Добавляем ответ бота в историю, чтобы он помнил контекст
        messages.append({"role": "assistant", "content": reply})

if __name__ == "__main__":
    main()
