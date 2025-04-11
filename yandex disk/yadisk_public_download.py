import os
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

# Публичная ссылка на папку Яндекс.Диска
PUBLIC_KEY = "https://disk.yandex.ru/d/SIwZ3EFq62fSZQ"

# Локальная папка, куда будем сохранять файлы, сохраняя структуру
LOCAL_SAVE_DIR = "yadisk_public_download"

# Базовый URL для работы с публичными ресурсами Яндекс.Диска
PUBLIC_API_URL = "https://cloud-api.yandex.net/v1/disk/public/resources"

# Количество потоков (воркеров) для одновременного скачивания
MAX_WORKERS = 5


def ensure_local_folder_exists(local_path: str):
    """Гарантирует, что нужная локальная папка существует (создаёт при необходимости)."""
    if not os.path.exists(local_path):
        os.makedirs(local_path)


def strip_public_prefix(path_str: str) -> str:
    """
    Безопасно убирает 'public:' в начале пути, если оно есть.
    Пример:
      "public:MyKey/Folder/File.txt" -> "MyKey/Folder/File.txt"
      "public:MyKey" -> "MyKey"
      "public:" -> "" (если есть только 'public:')
      "Folder/File.txt" -> "Folder/File.txt" (если двоеточия вообще нет)
    """
    prefix = "public:"
    if path_str.startswith(prefix):
        return path_str[len(prefix):]
    return path_str


def get_resource_info(public_key: str, path: str = None, limit: int = 100, offset: int = 0) -> dict:
    """
    Запрашивает у Яндекс.Диска метаданные ресурсов в публичной папке.
    - public_key: публичная ссылка (или ключ) на папку
    - path: относительный путь внутри публичной папки (если None — значит корень)
    """
    params = {
        "public_key": public_key,
        "limit": limit,
        "offset": offset
    }
    # Если хотим посмотреть конкретную вложенную папку, укажем path
    if path:
        params["path"] = path

    response = requests.get(PUBLIC_API_URL, params=params)
    response.raise_for_status()
    return response.json()


def list_public_files_recursive(public_key: str, path: str = None) -> list:
    """
    Рекурсивно получает все файлы внутри публичной папки (или подпапки).
    Возвращает список словарей вида:
    [
      {
        "public_path": <полный путь "public:KEY/...">,
        "full_path":   <то же самое>,
        "is_dir":      <True/False>,
        "name":        <имя файла или папки>
      },
      ...
    ]
    """
    all_items = []
    offset = 0
    limit = 100

    while True:
        data = get_resource_info(public_key, path=path, limit=limit, offset=offset)
        embedded = data.get("_embedded", {})
        items = embedded.get("items", [])

        for item in items:
            item_type = item["type"]       # "file" или "dir"
            item_name = item["name"]
            item_path = item["path"]       # Например: "public:KEY/Папка/Файл.txt", но может быть короче

            all_items.append({
                "public_path": item_path,
                "full_path": item_path,
                "is_dir": (item_type == "dir"),
                "name": item_name
            })

        if len(items) < limit:
            # Нет больше страниц
            break
        else:
            offset += limit

    # Рекурсивно обходим подпапки
    final_list = []
    for entry in all_items:
        final_list.append(entry)
        if entry["is_dir"]:
            # Для подпапки надо получить её содержимое
            sub_path = strip_public_prefix(entry["public_path"])
            if sub_path:
                # Рекурсивно уходим вниз
                subdir_items = list_public_files_recursive(public_key, path=sub_path)
                final_list.extend(subdir_items)
    return final_list


def get_download_url(public_key: str, public_path: str) -> str:
    """
    Возвращает прямую ссылку (href) на скачивание файла (public_path) из публичной папки public_key.
    """
    download_url = f"{PUBLIC_API_URL}/download"
    path_for_api = strip_public_prefix(public_path)

    params = {
        "public_key": public_key,
        "path": path_for_api
    }
    resp = requests.get(download_url, params=params)
    resp.raise_for_status()
    return resp.json().get("href")


def build_local_path(item: dict) -> str:
    """
    Формирует локальный путь (папка/файл) для сохранения, исходя из структуры публичного ресурса.
    - item["full_path"] например: "public:KEY/Папка1/Папка2/Файл.txt"
    - Убираем "public:KEY/" => "Папка1/Папка2/Файл.txt"
    """
    full_path = item["full_path"]            # "public:KEY/Папка/Файл.txt"
    without_prefix = strip_public_prefix(full_path)  # "KEY/Папка/Файл.txt" 
    parts = without_prefix.split("/", 1)     # ["KEY", "Папка/Файл.txt"] (если хотя бы один слеш есть)
    if len(parts) > 1:
        relative_path = parts[1]            # "Папка/Файл.txt"
    else:
        # Нет слеша => просто ключ, берем имя файла
        relative_path = item["name"]

    local_path = os.path.join(LOCAL_SAVE_DIR, relative_path)
    return local_path


def download_one_file(file_item: dict, public_key: str) -> None:
    """
    Функция для скачивания ОДНОГО файла с прогресс-баром.
    Используется в потоках через ThreadPoolExecutor.
    """
    # 1. Определяем локальный путь
    local_path = build_local_path(file_item)
    ensure_local_folder_exists(os.path.dirname(local_path))

    # 2. Получаем прямую ссылку
    direct_url = get_download_url(public_key, file_item["public_path"])
    if not direct_url:
        print(f"Не удалось получить ссылку для {file_item['name']}")
        return

    # 3. Скачиваем с отображением прогресса
    #    Определим имя для отображения в прогрессе:
    progress_label = os.path.basename(local_path)  # только имя файла
    with requests.get(direct_url, stream=True) as r:
        r.raise_for_status()
        total_size = int(r.headers.get("Content-Length", 0))
        block_size = 8192  # 8 KB
        # Инициируем прогресс-бар tqdm
        with tqdm(
            total=total_size,
            unit="B",
            unit_scale=True,
            desc=progress_label,
            leave=True
        ) as progress:
            with open(local_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=block_size):
                    f.write(chunk)
                    progress.update(len(chunk))

    # Дополнительно можно сделать time.sleep, если боитесь упереться в лимиты
    time.sleep(0.05)


def main():
    ensure_local_folder_exists(LOCAL_SAVE_DIR)
    print(f"Сканируем публичную папку: {PUBLIC_KEY}")
    
    # 1. Рекурсивно собираем все объекты
    items = list_public_files_recursive(PUBLIC_KEY, path=None)
    print(f"Найдено {len(items)} объектов (файлов и папок).")

    # 2. Фильтруем только файлы
    files = [it for it in items if not it["is_dir"]]
    print(f"Из них файлов: {len(files)}.\n")

    # 3. Скачиваем в несколько потоков
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Создаём задачи на скачивание
        future_to_file = {
            executor.submit(download_one_file, file_item, PUBLIC_KEY): file_item
            for file_item in files
        }
        # Ожидаем окончания всех потоков
        for future in as_completed(future_to_file):
            file_item = future_to_file[future]
            try:
                future.result()  # если были исключения, здесь они пробросятся
            except Exception as e:
                print(f"Ошибка при скачивании {file_item['name']}: {e}")

    print("\nЗагрузка завершена!")


if __name__ == "__main__":
    main()
